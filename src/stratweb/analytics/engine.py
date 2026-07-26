"""Pure deterministic Gameplay Analytics Engine V1."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from uuid import UUID

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalRound,
    EventPhase,
    RoundOutcomeStatus,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.exceptions import AnalyticsConfigurationError

from .definitions import (
    ClassifiedKill,
    Participant,
    config_hash,
    eligible_rounds,
    multikill_category,
    ordered_round_kills,
    participants_by_round,
    percentage,
    ratio,
    winner_team_id,
)
from .kast import is_kast
from .man_advantage import AdvantageRoundResult, advantage_for_round
from .models import (
    ANALYTICS_RULE_VERSION,
    ANALYTICS_SCHEMA_VERSION,
    AnalyticsAvailability,
    AnalyticsAvailabilitySummary,
    AnalyticsCapability,
    AnalyticsConfig,
    AnalyticsSummary,
    AnalyticsUnavailableReason,
    ManAdvantageTransition,
    MatchAnalytics,
    MatchAnalyticsInput,
    OpeningDuel,
    PlayerMatchAnalytics,
    PlayerRoundAnalytics,
    TeamMatchAnalytics,
    TeamRoundAnalytics,
    TradeEvent,
    TradePolicyCapability,
    TradeWindowMode,
)
from .opening_duels import opening_duel_for_round
from .trades import TradeRoundResult, trades_for_round
from .validation import AnalyticsValidator


@dataclass(slots=True)
class _PlayerRound:
    participant: Participant
    kills: int = 0
    deaths: int = 0
    enemy_deaths: int = 0
    assists: int = 0
    headshots: int = 0
    damage: int = 0
    enemy_damage: int = 0
    team_damage: int = 0
    shots: int = 0
    survived: bool = True
    traded_kills: int = 0
    traded_deaths: int = 0
    trade_opportunities: int = 0
    successful_trades: int = 0
    opening_kill: bool = False
    opening_death: bool = False
    kast_t: bool = False
    teamkill_count: int = 0
    suicide_count: int = 0
    plants: int = 0
    defuses: int = 0


class AnalyticsEngine:
    """Compute typed analytics without parser, DuckDB, clocks, or randomness."""

    def compute(
        self,
        data: MatchAnalyticsInput,
        config: AnalyticsConfig | None = None,
    ) -> MatchAnalytics:
        selected_config = config or AnalyticsConfig()
        if (
            selected_config.trade_window.mode is TradeWindowMode.LEGACY_AMBIGUOUS
            or selected_config.resolved_trade_window_ticks is None
        ):
            raise AnalyticsConfigurationError(
                "A legacy ambiguous trade-window policy cannot be used for computation."
            )
        rounds = eligible_rounds(data.rounds)
        participants = participants_by_round(rounds, data.memberships)
        player_rows: list[PlayerRoundAnalytics] = []
        team_rows: list[TeamRoundAnalytics] = []
        openings: list[OpeningDuel] = []
        trades: list[TradeEvent] = []
        transitions: list[ManAdvantageTransition] = []
        valid_kill_count = 0
        teamkill_count = 0
        suicide_count = 0
        world_count = 0
        enemy_deaths: Counter[UUID] = Counter()

        for round_item, round_participants in zip(rounds, participants, strict=True):
            accumulators = {
                player_id: _PlayerRound(participant)
                for player_id, participant in round_participants.items()
            }
            classified = ordered_round_kills(data.kills, round_item, round_participants)
            round_valid = tuple(item for item in classified if item.is_valid_enemy)
            valid_kill_count += len(round_valid)
            round_teamkills = sum(item.classification == "teamkill" for item in classified)
            round_suicides = sum(item.classification == "suicide" for item in classified)
            round_world = sum(item.classification == "world" for item in classified)
            teamkill_count += round_teamkills
            suicide_count += round_suicides
            world_count += round_world
            dead: set[UUID] = set()

            for item in classified:
                event = item.event
                victim_id = event.victim_player_id
                attacker_id = event.attacker_player_id
                if victim_id in accumulators and victim_id not in dead:
                    accumulators[victim_id].deaths += 1
                    accumulators[victim_id].survived = False
                    dead.add(victim_id)
                if item.classification == "suicide" and victim_id in accumulators:
                    accumulators[victim_id].suicide_count += 1
                if item.classification == "teamkill" and attacker_id in accumulators:
                    accumulators[attacker_id].teamkill_count += 1
                if not item.is_valid_enemy or attacker_id not in accumulators:
                    continue
                accumulators[attacker_id].kills += 1
                if event.headshot is True:
                    accumulators[attacker_id].headshots += 1
                if victim_id is not None:
                    enemy_deaths[victim_id] += 1
                    accumulators[victim_id].enemy_deaths += 1
                assister_id = event.assister_player_id
                if (
                    assister_id in accumulators
                    and assister_id != attacker_id
                    and assister_id != victim_id
                    and accumulators[assister_id].participant.team_id
                    == accumulators[attacker_id].participant.team_id
                ):
                    accumulators[assister_id].assists += 1

            opening = opening_duel_for_round(
                round_item, classified, round_participants, selected_config
            )
            if opening is not None:
                openings.append(opening)
                accumulators[opening.opening_killer_player_id].opening_kill = True
                accumulators[opening.opening_victim_player_id].opening_death = True

            trade_result = trades_for_round(
                round_item, classified, round_participants, selected_config
            )
            trades.extend(trade_result.events)
            self._apply_trades(accumulators, classified, trade_result)
            self._apply_damage(accumulators, data.damages, round_item.round_id)
            self._apply_shots(accumulators, data, round_item.round_id)
            round_bombs = self._round_bombs(data.bomb_events, round_item.round_id)
            self._apply_player_bombs(accumulators, round_bombs)
            advantage = advantage_for_round(round_item, classified, round_participants)
            transitions.extend(advantage.transitions)

            for player_id in sorted(accumulators, key=str):
                player_rows.append(
                    self._player_round_model(
                        round_item,
                        accumulators[player_id],
                        trade_available=True,
                    )
                )
            team_rows.extend(
                self._team_round_models(
                    round_item,
                    accumulators,
                    opening,
                    trade_result,
                    advantage,
                    round_bombs,
                    selected_config,
                )
            )

        availability = self._availability(rounds, participants, data, selected_config)
        player_matches = self._player_matches(
            data,
            tuple(player_rows),
            tuple(openings),
            enemy_deaths,
            availability,
        )
        team_matches = self._team_matches(
            data,
            tuple(team_rows),
            availability,
        )
        summary = AnalyticsSummary(
            rounds=len(rounds),
            players=len(player_matches),
            teams=len(team_matches),
            valid_enemy_kills=valid_kill_count,
            excluded_teamkills=teamkill_count,
            excluded_suicides=suicide_count,
            excluded_world_kills=world_count,
            opening_duels=len(openings),
            trade_events=len(trades),
            trade_window_mode=selected_config.trade_window.mode,
            trade_window_requested_ticks=selected_config.trade_window.requested_ticks,
            trade_window_requested_seconds=selected_config.trade_window.requested_seconds,
            trade_window_resolved_ticks=selected_config.trade_window.resolved_ticks,
            trade_window_tickrate=selected_config.trade_window.tickrate,
            trade_window_tickrate_source=selected_config.trade_window.tickrate_source,
            trade_window_resolution_source=selected_config.trade_window.resolution_source,
            rounds_with_plant=len(
                {
                    event.round_id
                    for event in data.bomb_events
                    if event.event_type == "planted"
                    and event.phase is EventPhase.LIVE
                    and event.round_id in {item.round_id for item in rounds}
                }
            ),
            winner_covered_rounds=sum(item.outcome_status.is_available for item in rounds),
        )
        warnings = self._warnings(availability)
        config_digest = config_hash(selected_config)
        provisional = MatchAnalytics(
            analytics_schema_version=ANALYTICS_SCHEMA_VERSION,
            analytics_rule_version=ANALYTICS_RULE_VERSION,
            analytics_config_hash=config_digest,
            analytics_fingerprint="0" * 64,
            match_id=data.match_id,
            dataset_fingerprint=data.dataset_fingerprint,
            config=selected_config,
            availability=availability,
            summary=summary,
            player_rounds=tuple(player_rows),
            player_matches=player_matches,
            team_rounds=tuple(team_rows),
            team_matches=team_matches,
            opening_duels=tuple(openings),
            trade_events=tuple(trades),
            man_advantage_transitions=tuple(transitions),
            validation_issues=(),
            warnings=warnings,
        )
        issues = AnalyticsValidator().validate(provisional)
        with_issues = provisional.model_copy(update={"validation_issues": issues})
        return with_issues.model_copy(
            update={"analytics_fingerprint": compute_analytics_fingerprint(with_issues)}
        )

    @staticmethod
    def _apply_trades(
        accumulators: dict[UUID, _PlayerRound],
        classified: tuple[ClassifiedKill, ...],
        result: TradeRoundResult,
    ) -> None:
        events_by_id = {item.event.event_id: item.event for item in classified}
        opportunity_ids = set(result.opportunities)
        valid_events = tuple(
            item.event
            for item in classified
            if item.is_valid_enemy and item.event.event_id in opportunity_ids
        )
        for original in valid_events:
            victim_id = original.victim_player_id
            if victim_id is None or victim_id not in accumulators:
                continue
            victim_team = accumulators[victim_id].participant.team_id
            for player_id, accumulator in accumulators.items():
                if player_id == victim_id or accumulator.participant.team_id != victim_team:
                    continue
                died_before = any(
                    event.victim_player_id == player_id
                    and (event.tick, str(event.event_id)) <= (original.tick, str(original.event_id))
                    for event in events_by_id.values()
                )
                if not died_before:
                    accumulator.trade_opportunities += 1
        for trade in result.events:
            accumulators[trade.trader_player_id].traded_kills += 1
            accumulators[trade.trader_player_id].successful_trades += 1
            accumulators[trade.traded_player_id].traded_deaths += 1
            accumulators[trade.traded_player_id].kast_t = True

    @staticmethod
    def _apply_damage(
        accumulators: dict[UUID, _PlayerRound],
        damages: tuple[CanonicalDamage, ...],
        round_id: UUID,
    ) -> None:
        health: defaultdict[UUID, int] = defaultdict(lambda: 100)
        for event in sorted(
            (
                item
                for item in damages
                if item.round_id == round_id and item.phase is EventPhase.LIVE
            ),
            key=lambda item: (item.tick, str(item.event_id)),
        ):
            victim_id = event.victim_player_id
            if victim_id not in accumulators or victim_id is None:
                continue
            raw = event.damage_health or 0
            effective = min(raw, health[victim_id])
            health[victim_id] = (
                event.victim_health_after
                if event.victim_health_after is not None
                else max(0, health[victim_id] - effective)
            )
            attacker_id = event.attacker_player_id
            if attacker_id not in accumulators or attacker_id is None:
                continue
            attacker = accumulators[attacker_id]
            victim = accumulators[victim_id]
            attacker.damage += effective
            if attacker.participant.team_id != victim.participant.team_id:
                attacker.enemy_damage += effective
            elif attacker_id != victim_id:
                attacker.team_damage += effective

    @staticmethod
    def _apply_shots(
        accumulators: dict[UUID, _PlayerRound],
        data: MatchAnalyticsInput,
        round_id: UUID,
    ) -> None:
        for event in data.shots:
            if (
                event.round_id == round_id
                and event.phase is EventPhase.LIVE
                and event.player_id in accumulators
            ):
                accumulators[event.player_id].shots += 1

    @staticmethod
    def _round_bombs(
        events: tuple[CanonicalBombEvent, ...], round_id: UUID
    ) -> tuple[CanonicalBombEvent, ...]:
        return tuple(
            sorted(
                (
                    event
                    for event in events
                    if event.round_id == round_id and event.phase is EventPhase.LIVE
                ),
                key=lambda event: (event.tick, str(event.event_id)),
            )
        )

    @staticmethod
    def _apply_player_bombs(
        accumulators: dict[UUID, _PlayerRound],
        events: tuple[CanonicalBombEvent, ...],
    ) -> None:
        for event in events:
            if event.player_id not in accumulators or event.player_id is None:
                continue
            if event.event_type == "planted":
                accumulators[event.player_id].plants += 1
            elif event.event_type == "defused":
                accumulators[event.player_id].defuses += 1

    @staticmethod
    def _player_round_model(
        round_item: CanonicalRound,
        accumulator: _PlayerRound,
        *,
        trade_available: bool,
    ) -> PlayerRoundAnalytics:
        kills = accumulator.kills
        assists = accumulator.assists
        kast_k = kills > 0
        kast_a = assists > 0
        kast_s = accumulator.survived
        return PlayerRoundAnalytics(
            match_id=round_item.match_id,
            round_id=round_item.round_id,
            round_number=round_item.round_number,
            player_id=accumulator.participant.player_id,
            team_id=accumulator.participant.team_id,
            side=accumulator.participant.side,
            kills=kills,
            deaths=accumulator.deaths,
            assists=assists,
            headshots=accumulator.headshots,
            damage=accumulator.damage,
            enemy_damage=accumulator.enemy_damage,
            team_damage=accumulator.team_damage,
            shots=accumulator.shots,
            survived=accumulator.survived,
            traded_kills=accumulator.traded_kills if trade_available else None,
            traded_deaths=accumulator.traded_deaths if trade_available else None,
            trade_opportunities=accumulator.trade_opportunities if trade_available else None,
            successful_trades=accumulator.successful_trades if trade_available else None,
            opening_kill=accumulator.opening_kill,
            opening_death=accumulator.opening_death,
            multikill_count=kills,
            multikill_category=multikill_category(kills),
            kast_k=kast_k,
            kast_a=kast_a,
            kast_s=kast_s,
            kast_t=accumulator.kast_t if trade_available else None,
            kast=(
                is_kast(
                    kill=kast_k,
                    assist=kast_a,
                    survived=kast_s,
                    traded=accumulator.kast_t,
                )
                if trade_available
                else None
            ),
            teamkill_count=accumulator.teamkill_count,
            suicide_count=accumulator.suicide_count,
            plants=accumulator.plants,
            defuses=accumulator.defuses,
        )

    def _team_round_models(
        self,
        round_item: CanonicalRound,
        accumulators: dict[UUID, _PlayerRound],
        opening: OpeningDuel | None,
        trade_result: TradeRoundResult,
        advantage: AdvantageRoundResult,
        bombs: tuple[CanonicalBombEvent, ...],
        config: AnalyticsConfig,
    ) -> tuple[TeamRoundAnalytics, ...]:
        if round_item.t_team_id is None or round_item.ct_team_id is None:
            return ()
        winner = winner_team_id(round_item)
        rows: list[TeamRoundAnalytics] = []
        for team_id, opponent_id, side in (
            (round_item.t_team_id, round_item.ct_team_id, Side.T),
            (round_item.ct_team_id, round_item.t_team_id, Side.CT),
        ):
            players = [
                value for value in accumulators.values() if value.participant.team_id == team_id
            ]
            opening_kill = opening is not None and opening.killer_team_id == team_id
            opening_death = opening is not None and opening.victim_team_id == team_id
            trade_available = True
            opportunities = sum(
                1
                for event_id in trade_result.opportunities
                if trade_result.opportunity_teams.get(event_id) == team_id
            )
            successful = sum(event.team_id == team_id for event in trade_result.events)
            traded_deaths = sum(event.team_id == team_id for event in trade_result.events)
            gained = advantage.first_advantage_team_id == team_id
            disadvantaged = advantage.first_advantage_team_id is not None and not gained
            plants = (
                sum(event.event_type == "planted" for event in bombs)
                if team_id == round_item.t_team_id
                else 0
            )
            defuses = (
                sum(event.event_type == "defused" for event in bombs)
                if team_id == round_item.ct_team_id
                else 0
            )
            explosions = (
                sum(event.event_type == "exploded" for event in bombs)
                if team_id == round_item.t_team_id
                else 0
            )
            planted = plants > 0
            winner_known = winner is not None
            rows.append(
                TeamRoundAnalytics(
                    match_id=round_item.match_id,
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=team_id,
                    opponent_team_id=opponent_id,
                    side=side,
                    participant_count=len(players),
                    lineup_valid=advantage.lineup_valid,
                    round_won=(team_id == winner) if winner_known else None,
                    kills=sum(item.kills for item in players),
                    deaths=sum(item.enemy_deaths for item in players),
                    assists=sum(item.assists for item in players),
                    enemy_damage=sum(item.enemy_damage for item in players),
                    opening_kill=opening_kill,
                    opening_death=opening_death,
                    opening_kill_converted=(team_id == winner)
                    if opening_kill and winner_known
                    else None,
                    recovered_after_opening_death=(team_id == winner)
                    if opening_death and winner_known
                    else None,
                    trade_opportunities=opportunities if trade_available else None,
                    successful_trades=successful if trade_available else None,
                    traded_deaths=traded_deaths if trade_available else None,
                    untraded_deaths=(sum(item.enemy_deaths for item in players) - traded_deaths)
                    if trade_available
                    else None,
                    gained_first_advantage=gained,
                    first_advantage_size=advantage.first_advantage_size if gained else 0,
                    lost_first_advantage=advantage.first_advantage_lost if gained else False,
                    converted_first_advantage=(team_id == winner)
                    if gained and winner_known and advantage.lineup_valid
                    else None,
                    recovered_after_first_disadvantage=(team_id == winner)
                    if disadvantaged and winner_known and advantage.lineup_valid
                    else None,
                    reached_plus_two=team_id in advantage.reached_plus_two,
                    converted_plus_two=(team_id == winner)
                    if team_id in advantage.reached_plus_two
                    and winner_known
                    and advantage.lineup_valid
                    else None,
                    max_advantage=advantage.max_advantage.get(team_id, 0),
                    final_alive=advantage.final_alive.get(team_id, 0),
                    plants=plants,
                    defuses=defuses,
                    explosions=explosions,
                    planted_round=planted,
                    post_plant_won=(team_id == winner) if planted and winner_known else None,
                    bomb_outcome_observed=planted
                    and any(event.event_type in {"defused", "exploded"} for event in bombs),
                )
            )
        return tuple(rows)

    def _player_matches(
        self,
        data: MatchAnalyticsInput,
        rows: tuple[PlayerRoundAnalytics, ...],
        openings: tuple[OpeningDuel, ...],
        enemy_deaths: Counter[UUID],
        availability: AnalyticsAvailabilitySummary,
    ) -> tuple[PlayerMatchAnalytics, ...]:
        player_by_id = {item.player_id: item for item in data.players}
        grouped: dict[UUID, list[PlayerRoundAnalytics]] = defaultdict(list)
        for row in rows:
            grouped[row.player_id].append(row)
        win_available = (
            availability.win_conversion_metrics.status is AnalyticsAvailability.AVAILABLE
        )
        trade_available = availability.trade_metrics.status is AnalyticsAvailability.AVAILABLE
        result: list[PlayerMatchAnalytics] = []
        for player_id in sorted(grouped, key=str):
            items = grouped[player_id]
            player = player_by_id[player_id]
            rounds_played = len(items)
            kills = sum(item.kills for item in items)
            deaths = sum(item.deaths for item in items)
            assists = sum(item.assists for item in items)
            opening_kills = sum(item.opening_kill for item in items)
            opening_deaths = sum(item.opening_death for item in items)
            opening_wins = sum(
                duel.opening_team_won_round is True
                for duel in openings
                if duel.opening_killer_player_id == player_id
            )
            trade_opportunities = sum(item.trade_opportunities or 0 for item in items)
            successful_trades = sum(item.successful_trades or 0 for item in items)
            traded_deaths = sum(item.traded_deaths or 0 for item in items)
            result.append(
                PlayerMatchAnalytics(
                    match_id=data.match_id,
                    player_id=player_id,
                    current_name=player.current_name,
                    steam_id=player.steam_id,
                    rounds_played=rounds_played,
                    kills=kills,
                    deaths=deaths,
                    assists=assists,
                    kd_ratio=ratio(kills, deaths),
                    kill_differential=kills - deaths,
                    adr=ratio(sum(item.enemy_damage for item in items), rounds_played),
                    kpr=ratio(kills, rounds_played),
                    dpr=ratio(deaths, rounds_played),
                    apr=ratio(assists, rounds_played),
                    headshots=sum(item.headshots for item in items),
                    headshot_percentage=percentage(sum(item.headshots for item in items), kills),
                    total_damage=sum(item.damage for item in items),
                    enemy_damage=sum(item.enemy_damage for item in items),
                    team_damage=sum(item.team_damage for item in items),
                    shots=sum(item.shots for item in items),
                    survival_rounds=sum(item.survived for item in items),
                    survival_percentage=percentage(
                        sum(item.survived for item in items), rounds_played
                    ),
                    opening_kills=opening_kills,
                    opening_deaths=opening_deaths,
                    opening_duel_attempts=opening_kills + opening_deaths,
                    opening_duel_success_percentage=percentage(
                        opening_kills, opening_kills + opening_deaths
                    ),
                    opening_kill_round_wins=opening_wins if win_available else None,
                    opening_kill_conversion_percentage=percentage(opening_wins, opening_kills)
                    if win_available
                    else None,
                    traded_kills=sum(item.traded_kills or 0 for item in items)
                    if trade_available
                    else None,
                    traded_deaths=traded_deaths if trade_available else None,
                    trade_opportunities=trade_opportunities if trade_available else None,
                    successful_trades=successful_trades if trade_available else None,
                    trade_success_percentage=percentage(successful_trades, trade_opportunities)
                    if trade_available
                    else None,
                    traded_death_percentage=percentage(traded_deaths, enemy_deaths[player_id])
                    if trade_available
                    else None,
                    multikill_rounds=sum(item.multikill_count >= 2 for item in items),
                    two_k_rounds=sum(item.multikill_count == 2 for item in items),
                    three_k_rounds=sum(item.multikill_count == 3 for item in items),
                    four_k_rounds=sum(item.multikill_count == 4 for item in items),
                    five_k_rounds=sum(item.multikill_count == 5 for item in items),
                    five_plus_rounds=sum(item.multikill_count >= 5 for item in items),
                    kast_rounds=sum(item.kast is True for item in items)
                    if trade_available
                    else None,
                    kast_percentage=percentage(
                        sum(item.kast is True for item in items), rounds_played
                    )
                    if trade_available
                    else None,
                    kast_k_rounds=sum(item.kast_k for item in items),
                    kast_a_rounds=sum(item.kast_a for item in items),
                    kast_s_rounds=sum(item.kast_s for item in items),
                    kast_t_rounds=sum(item.kast_t is True for item in items)
                    if trade_available
                    else None,
                    teamkills=sum(item.teamkill_count for item in items),
                    suicides=sum(item.suicide_count for item in items),
                    plants=sum(item.plants for item in items),
                    defuses=sum(item.defuses for item in items),
                )
            )
        return tuple(result)

    def _team_matches(
        self,
        data: MatchAnalyticsInput,
        rows: tuple[TeamRoundAnalytics, ...],
        availability: AnalyticsAvailabilitySummary,
    ) -> tuple[TeamMatchAnalytics, ...]:
        team_by_id = {item.team_id: item for item in data.teams}
        grouped: dict[UUID, list[TeamRoundAnalytics]] = defaultdict(list)
        for row in rows:
            grouped[row.team_id].append(row)
        win_available = (
            availability.win_conversion_metrics.status is AnalyticsAvailability.AVAILABLE
        )
        trade_available = availability.trade_metrics.status is AnalyticsAvailability.AVAILABLE
        result: list[TeamMatchAnalytics] = []
        for team_id in sorted(grouped, key=str):
            items = grouped[team_id]
            team = team_by_id[team_id]
            rounds_played = len(items)
            opening_kills = sum(item.opening_kill for item in items)
            opening_deaths = sum(item.opening_death for item in items)
            first_adv = sum(item.gained_first_advantage for item in items)
            first_disadv = sum(
                any(
                    other.gained_first_advantage and other.round_id == item.round_id
                    for other in rows
                    if other.team_id != team_id
                )
                for item in items
            )
            plus_two = sum(item.reached_plus_two for item in items)
            planted = sum(item.planted_round for item in items)
            observed_bomb = sum(item.bomb_outcome_observed for item in items if item.planted_round)
            opportunities = sum(item.trade_opportunities or 0 for item in items)
            successful = sum(item.successful_trades or 0 for item in items)
            traded_deaths = sum(item.traded_deaths or 0 for item in items)
            enemy_deaths = sum(item.deaths for item in items)
            ct_plant_opportunities = sum(
                item.side is Side.CT
                and any(
                    other.round_id == item.round_id
                    and other.team_id != team_id
                    and other.planted_round
                    for other in rows
                )
                for item in items
            )
            result.append(
                TeamMatchAnalytics(
                    match_id=data.match_id,
                    team_id=team_id,
                    internal_name=team.internal_name,
                    display_name=team.display_name,
                    rounds_played=rounds_played,
                    round_wins=sum(item.round_won is True for item in items)
                    if win_available
                    else None,
                    t_rounds=sum(item.side is Side.T for item in items),
                    ct_rounds=sum(item.side is Side.CT for item in items),
                    t_round_wins=sum(
                        item.side is Side.T and item.round_won is True for item in items
                    )
                    if win_available
                    else None,
                    ct_round_wins=sum(
                        item.side is Side.CT and item.round_won is True for item in items
                    )
                    if win_available
                    else None,
                    kills=sum(item.kills for item in items),
                    deaths=sum(item.deaths for item in items),
                    assists=sum(item.assists for item in items),
                    enemy_damage=sum(item.enemy_damage for item in items),
                    adr=ratio(sum(item.enemy_damage for item in items), rounds_played),
                    opening_kills=opening_kills,
                    opening_deaths=opening_deaths,
                    opening_kill_conversions=sum(
                        item.opening_kill_converted is True for item in items
                    )
                    if win_available
                    else None,
                    opening_conversion_percentage=percentage(
                        sum(item.opening_kill_converted is True for item in items), opening_kills
                    )
                    if win_available
                    else None,
                    opening_death_recoveries=sum(
                        item.recovered_after_opening_death is True for item in items
                    )
                    if win_available
                    else None,
                    opening_death_recovery_percentage=percentage(
                        sum(item.recovered_after_opening_death is True for item in items),
                        opening_deaths,
                    )
                    if win_available
                    else None,
                    trade_opportunities=opportunities if trade_available else None,
                    successful_trades=successful if trade_available else None,
                    trade_percentage=percentage(successful, opportunities)
                    if trade_available
                    else None,
                    traded_deaths=traded_deaths if trade_available else None,
                    untraded_deaths=(enemy_deaths - traded_deaths) if trade_available else None,
                    first_advantage_rounds=first_adv,
                    first_advantage_conversions=sum(
                        item.converted_first_advantage is True for item in items
                    )
                    if win_available
                    else None,
                    first_advantage_conversion_percentage=percentage(
                        sum(item.converted_first_advantage is True for item in items), first_adv
                    )
                    if win_available
                    else None,
                    first_disadvantage_rounds=first_disadv,
                    first_disadvantage_recoveries=sum(
                        item.recovered_after_first_disadvantage is True for item in items
                    )
                    if win_available
                    else None,
                    first_disadvantage_recovery_percentage=percentage(
                        sum(item.recovered_after_first_disadvantage is True for item in items),
                        first_disadv,
                    )
                    if win_available
                    else None,
                    plus_two_rounds=plus_two,
                    plus_two_conversions=sum(item.converted_plus_two is True for item in items)
                    if win_available
                    else None,
                    plus_two_conversion_percentage=percentage(
                        sum(item.converted_plus_two is True for item in items), plus_two
                    )
                    if win_available
                    else None,
                    plants=sum(item.plants for item in items),
                    defuses=sum(item.defuses for item in items),
                    explosions=sum(item.explosions for item in items),
                    rounds_with_plant=planted,
                    rounds_with_defuse=sum(item.defuses > 0 for item in items),
                    rounds_with_explosion=sum(item.explosions > 0 for item in items),
                    post_plant_wins=sum(item.post_plant_won is True for item in items)
                    if win_available
                    else None,
                    post_plant_conversion_percentage=percentage(
                        sum(item.post_plant_won is True for item in items), planted
                    )
                    if win_available
                    else None,
                    bomb_outcome_coverage_percentage=percentage(observed_bomb, planted),
                    ct_defuse_success_percentage=percentage(
                        sum(item.side is Side.CT and item.defuses > 0 for item in items),
                        ct_plant_opportunities,
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _availability(
        rounds: tuple[CanonicalRound, ...],
        participants: tuple[dict[UUID, Participant], ...],
        data: MatchAnalyticsInput,
        config: AnalyticsConfig,
    ) -> AnalyticsAvailabilitySummary:
        total = len(rounds)
        populated = sum(
            any(item.side is Side.T for item in items.values())
            and any(item.side is Side.CT for item in items.values())
            for items in participants
        )
        combat = _coverage_capability(
            total, populated, AnalyticsUnavailableReason.MISSING_PARTICIPANTS
        )
        winner_covered = sum(item.outcome_status.is_available for item in rounds)
        winner_reasons: tuple[AnalyticsUnavailableReason, ...] = ()
        if winner_covered < total:
            winner_reasons = (
                AnalyticsUnavailableReason.SOURCE_CONFLICT
                if any(
                    item.outcome_status is RoundOutcomeStatus.UNRESOLVED_CONFLICT for item in rounds
                )
                else AnalyticsUnavailableReason.MISSING_ROUND_WINNER,
            )
        win = _explicit_capability(total, winner_covered, winner_reasons)
        score_covered = sum(item.score_status.value == "available" for item in rounds)
        score = _explicit_capability(
            total,
            score_covered,
            (() if score_covered == total else (AnalyticsUnavailableReason.SOURCE_CONFLICT,)),
        )
        trade = _trade_policy_capability(combat, config)
        bomb_covered = len(
            {
                event.round_id
                for event in data.bomb_events
                if event.phase is EventPhase.LIVE
                and event.round_id in {item.round_id for item in rounds}
            }
        )
        bomb = (
            AnalyticsCapability(
                status=AnalyticsAvailability.UNAVAILABLE,
                reasons=(AnalyticsUnavailableReason.NO_POPULATION,),
                population=0,
                covered=0,
            )
            if total == 0
            else AnalyticsCapability(
                status=(
                    AnalyticsAvailability.PARTIAL
                    if bomb_covered
                    else AnalyticsAvailability.UNAVAILABLE
                ),
                reasons=(AnalyticsUnavailableReason.UNSUPPORTED_EVENT_SEMANTICS,),
                population=total,
                covered=bomb_covered,
            )
        )
        advantage_covered = sum(
            bool(items)
            and sum(item.side is Side.T for item in items.values())
            == sum(item.side is Side.CT for item in items.values())
            for items in participants
        )
        advantage = _coverage_capability(
            total, advantage_covered, AnalyticsUnavailableReason.MISSING_PARTICIPANTS
        )
        return AnalyticsAvailabilitySummary(
            combat_metrics=combat,
            opening_metrics=combat,
            trade_metrics=trade,
            kast_metrics=trade,
            win_conversion_metrics=win,
            bomb_metrics=bomb,
            score_metrics=score,
            advantage_metrics=advantage,
        )

    @staticmethod
    def _warnings(availability: AnalyticsAvailabilitySummary) -> tuple[str, ...]:
        warnings = []
        for name, capability in availability:
            if capability.status is not AnalyticsAvailability.AVAILABLE:
                reasons = ",".join(reason.value for reason in capability.reasons)
                warnings.append(f"{name}:{capability.status.value}:{reasons}")
        return tuple(warnings)


def compute_analytics_fingerprint(analytics: MatchAnalytics) -> str:
    payload = analytics.model_dump(mode="json", exclude={"analytics_fingerprint"})
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _coverage_capability(
    population: int,
    covered: int,
    reason: AnalyticsUnavailableReason,
) -> AnalyticsCapability:
    if population == 0:
        return AnalyticsCapability(
            status=AnalyticsAvailability.UNAVAILABLE,
            reasons=(AnalyticsUnavailableReason.NO_POPULATION,),
            population=0,
            covered=0,
        )
    if covered == population:
        return AnalyticsCapability(
            status=AnalyticsAvailability.AVAILABLE,
            population=population,
            covered=covered,
        )
    return AnalyticsCapability(
        status=AnalyticsAvailability.PARTIAL if covered else AnalyticsAvailability.UNAVAILABLE,
        reasons=(reason,),
        population=population,
        covered=covered,
    )


def _trade_policy_capability(
    capability: AnalyticsCapability,
    config: AnalyticsConfig,
) -> TradePolicyCapability:
    window = config.trade_window
    return TradePolicyCapability(
        status=capability.status,
        reasons=capability.reasons,
        population=capability.population,
        covered=capability.covered,
        trade_window_mode=window.mode,
        requested_ticks=window.requested_ticks,
        requested_seconds=window.requested_seconds,
        resolved_ticks=window.resolved_ticks,
        tickrate=window.tickrate,
        tickrate_source=window.tickrate_source,
        resolution_source=window.resolution_source,
    )


def _explicit_capability(
    population: int,
    covered: int,
    reasons: tuple[AnalyticsUnavailableReason, ...],
) -> AnalyticsCapability:
    if population == 0:
        return AnalyticsCapability(
            status=AnalyticsAvailability.UNAVAILABLE,
            reasons=(AnalyticsUnavailableReason.NO_POPULATION,),
            population=0,
            covered=0,
        )
    status = (
        AnalyticsAvailability.AVAILABLE
        if covered == population
        else AnalyticsAvailability.PARTIAL
        if covered
        else AnalyticsAvailability.UNAVAILABLE
    )
    return AnalyticsCapability(
        status=status,
        reasons=() if status is AnalyticsAvailability.AVAILABLE else reasons,
        population=population,
        covered=covered,
    )
