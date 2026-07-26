from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from stratweb.analytics.engine import AnalyticsEngine
from stratweb.analytics.models import (
    AnalyticsAvailability,
    AnalyticsConfig,
    MatchAnalytics,
    MatchAnalyticsInput,
    MultikillCategory,
    PlayerRoundAnalytics,
    TimeConversionStatus,
    TradeWindowConfig,
    TradeWindowMode,
    seconds_to_ticks,
)
from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalKill,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalTeam,
    DataAvailability,
    EventPhase,
    PlayerTeamMembership,
    RoundOutcomeStatus,
)
from stratweb.domain.enums import Side


@dataclass(frozen=True)
class Scenario:
    data: MatchAnalyticsInput
    players: dict[str, UUID]
    teams: dict[str, UUID]


def _scenario(
    kills: Iterable[tuple[str | None, str, int, str | None]] = (),
    *,
    winner: Side | None = Side.T,
    t_count: int = 5,
    ct_count: int = 5,
    bombs: Iterable[tuple[str, str | None, int, str | int | None]] = (),
    damages: Iterable[tuple[str | None, str, int, int, int | None]] = (),
    membership_starts: dict[str, int] | None = None,
    seed: str = "scenario",
) -> Scenario:
    match_id = uuid5(NAMESPACE_URL, f"analytics:{seed}")
    teams = {name: uuid5(match_id, f"team:{name}") for name in ("a", "b")}
    names = [*(f"t{index}" for index in range(1, t_count + 1))]
    names.extend(f"c{index}" for index in range(1, ct_count + 1))
    players = {name: uuid5(match_id, f"player:{name}") for name in names}
    canonical_players = tuple(
        CanonicalPlayer(
            player_id=player_id,
            steam_id=str(76561198000000000 + index),
            current_name=name,
            known_names=(name,),
        )
        for index, (name, player_id) in enumerate(players.items(), start=1)
    )
    canonical_teams = (
        CanonicalTeam(
            team_id=teams["a"],
            match_id=match_id,
            internal_name="Team A",
            starting_player_ids=tuple(players[name] for name in names if name.startswith("t")),
            identity_confidence=1,
        ),
        CanonicalTeam(
            team_id=teams["b"],
            match_id=match_id,
            internal_name="Team B",
            starting_player_ids=tuple(players[name] for name in names if name.startswith("c")),
            identity_confidence=1,
        ),
    )
    starts = membership_starts or {}
    memberships = tuple(
        PlayerTeamMembership(
            player_id=player_id,
            team_id=teams["a"] if name.startswith("t") else teams["b"],
            side=Side.T if name.startswith("t") else Side.CT,
            valid_from_tick=starts.get(name, 100),
            source="test",
            confidence=1,
        )
        for name, player_id in players.items()
    )
    round_id = uuid5(match_id, "round:1")
    score_available = winner is not None
    round_item = CanonicalRound(
        round_id=round_id,
        match_id=match_id,
        round_number=1,
        start_tick=100,
        freeze_end_tick=110,
        end_tick=900,
        official_end_tick=1000,
        start_source="test",
        end_source="test",
        t_team_id=teams["a"],
        ct_team_id=teams["b"],
        winner_side=winner,
        outcome_status=(
            RoundOutcomeStatus.SOURCE_EVENT
            if winner is not None
            else RoundOutcomeStatus.MISSING_FROM_SOURCE
        ),
        outcome_source="test" if winner is not None else None,
        score_t_before=0 if score_available else None,
        score_ct_before=0 if score_available else None,
        score_t_after=1 if winner is Side.T else 0 if score_available else None,
        score_ct_after=1 if winner is Side.CT else 0 if score_available else None,
        score_status=(
            DataAvailability.AVAILABLE if score_available else DataAvailability.MISSING_FROM_SOURCE
        ),
        score_source="test" if score_available else None,
        is_complete=True,
    )

    canonical_kills = []
    for index, (attacker, victim, tick, assister) in enumerate(kills):
        attacker_team = _team_for(attacker, teams)
        victim_team = _team_for(victim, teams)
        canonical_kills.append(
            CanonicalKill(
                event_id=uuid5(match_id, f"kill:{index}"),
                match_id=match_id,
                round_id=round_id,
                round_number=1,
                tick=tick,
                relative_tick=tick - 100,
                phase=EventPhase.LIVE,
                source_event="player_death",
                attacker_player_id=players.get(attacker) if attacker else None,
                victim_player_id=players[victim],
                assister_player_id=players.get(assister) if assister else None,
                attacker_team_id=attacker_team,
                victim_team_id=victim_team,
                attacker_side=_side_for(attacker),
                victim_side=_side_for(victim),
                headshot=index % 2 == 0,
                is_teamkill=(attacker_team == victim_team) if attacker else False,
                is_suicide=attacker == victim if attacker else False,
            )
        )
    canonical_bombs = tuple(
        CanonicalBombEvent(
            event_id=uuid5(match_id, f"bomb:{index}"),
            match_id=match_id,
            round_id=round_id,
            round_number=1,
            tick=tick,
            relative_tick=tick - 100,
            phase=EventPhase.LIVE,
            source_event=f"bomb_{event_type}",
            player_id=players.get(player) if player else None,
            team_id=_team_for(player, teams),
            side=_side_for(player),
            event_type=event_type,
            site_raw=site,
        )
        for index, (event_type, player, tick, site) in enumerate(bombs)
    )
    canonical_damages = tuple(
        CanonicalDamage(
            event_id=uuid5(match_id, f"damage:{index}"),
            match_id=match_id,
            round_id=round_id,
            round_number=1,
            tick=tick,
            relative_tick=tick - 100,
            phase=EventPhase.LIVE,
            source_event="player_hurt",
            attacker_player_id=players.get(attacker) if attacker else None,
            victim_player_id=players[victim],
            attacker_team_id=_team_for(attacker, teams),
            victim_team_id=_team_for(victim, teams),
            attacker_side=_side_for(attacker),
            victim_side=_side_for(victim),
            damage_health=damage,
            victim_health_after=health_after,
        )
        for index, (attacker, victim, tick, damage, health_after) in enumerate(damages)
    )
    return Scenario(
        data=MatchAnalyticsInput(
            match_id=match_id,
            dataset_fingerprint=hashlib.sha256(seed.encode()).hexdigest(),
            teams=canonical_teams,
            players=canonical_players,
            memberships=memberships,
            rounds=(round_item,),
            kills=tuple(canonical_kills),
            damages=canonical_damages,
            shots=(),
            bomb_events=canonical_bombs,
        ),
        players=players,
        teams=teams,
    )


def _compute(scenario: Scenario, *, ticks: int = 100) -> MatchAnalytics:
    return AnalyticsEngine().compute(
        scenario.data,
        AnalyticsConfig(trade_window=TradeWindowConfig.ticks(ticks)),
    )


def _team_for(player: str | None, teams: dict[str, UUID]) -> UUID | None:
    if player is None:
        return None
    return teams["a"] if player.startswith("t") else teams["b"]


def _side_for(player: str | None) -> Side:
    if player is None:
        return Side.UNKNOWN
    return Side.T if player.startswith("t") else Side.CT


def _player_round(result: MatchAnalytics, scenario: Scenario, name: str) -> PlayerRoundAnalytics:
    return next(row for row in result.player_rounds if row.player_id == scenario.players[name])


@pytest.mark.parametrize("prefix", [(), (("t1", "t2", 120, None),), ((None, "t1", 120, None),)])
def test_opening_skips_teamkill_suicide_and_world(
    prefix: tuple[tuple[str | None, str, int, str | None], ...],
) -> None:
    suicide = (("t1", "t1", 120, None),) if not prefix else prefix
    scenario = _scenario((*suicide, ("t2", "c1", 140, None)), seed=f"opening-{prefix}")

    result = _compute(scenario)

    assert len(result.opening_duels) == 1
    assert result.opening_duels[0].opening_killer_player_id == scenario.players["t2"]
    assert result.opening_duels[0].opening_victim_player_id == scenario.players["c1"]


def test_opening_same_tick_uses_event_id_and_empty_round_has_none() -> None:
    scenario = _scenario((("t1", "c1", 200, None), ("c2", "t2", 200, None)), seed="opening-tie")
    expected = min(scenario.data.kills, key=lambda item: str(item.event_id))
    result = _compute(scenario)

    assert result.opening_duels[0].event_id == expected.event_id
    assert _compute(_scenario(seed="opening-empty")).opening_duels == ()


@pytest.mark.parametrize(("winner", "converted"), [(Side.T, True), (Side.CT, False), (None, None)])
def test_opening_conversion_respects_winner_availability(
    winner: Side | None, converted: bool | None
) -> None:
    result = _compute(_scenario((("t1", "c1", 200, None),), winner=winner, seed=str(winner)))

    assert result.opening_duels[0].opening_team_won_round is converted
    if winner is None:
        assert (
            result.availability.win_conversion_metrics.status is AnalyticsAvailability.UNAVAILABLE
        )
        assert result.player_matches[0].opening_kill_conversion_percentage is None


def test_direct_trade_and_trade_denominators() -> None:
    scenario = _scenario((("c1", "t1", 200, None), ("t2", "c1", 250, None)), seed="direct-trade")
    result = _compute(scenario)

    assert len(result.trade_events) == 1
    trade = result.trade_events[0]
    assert trade.trader_player_id == scenario.players["t2"]
    assert trade.traded_player_id == scenario.players["t1"]
    assert trade.tick_delta == 50
    assert _player_round(result, scenario, "t1").kast_t
    team_a = next(row for row in result.team_matches if row.team_id == scenario.teams["a"])
    assert (team_a.trade_opportunities, team_a.successful_trades) == (1, 1)
    assert (team_a.traded_deaths, team_a.untraded_deaths) == (1, 0)


@pytest.mark.parametrize(
    "kills",
    [
        (("c1", "t1", 200, None), ("t2", "c1", 350, None)),
        (("c1", "t1", 200, None), ("t2", "c2", 250, None)),
        (("c1", "t1", 200, None), ("t2", "t3", 250, None)),
        (("c1", "t1", 200, None), ("c1", "c1", 250, None)),
    ],
)
def test_non_direct_or_invalid_kills_are_not_trades(
    kills: tuple[tuple[str | None, str, int, str | None], ...],
) -> None:
    assert _compute(_scenario(kills, seed=f"not-trade-{kills}")).trade_events == ()


def test_chain_trade_is_direct_per_death_and_original_is_used_once() -> None:
    scenario = _scenario(
        (
            ("c1", "t1", 200, None),
            ("t2", "c1", 230, None),
            ("c2", "t2", 260, None),
            ("t3", "c2", 280, None),
            ("t4", "c2", 290, None),
        ),
        seed="chain-trade",
    )
    result = _compute(scenario)

    assert len(result.trade_events) == 3
    assert len({item.original_kill_event_id for item in result.trade_events}) == 3


def test_killer_already_dead_cannot_be_traded_again() -> None:
    scenario = _scenario(
        (
            ("c1", "t1", 200, None),
            ("c2", "c1", 220, None),
            ("t2", "c1", 240, None),
        ),
        seed="dead-killer-not-trade",
    )
    assert _compute(scenario).trade_events == ()


def test_trade_ties_are_deterministic_and_window_is_configurable() -> None:
    scenario = _scenario((("c1", "t1", 200, None), ("t2", "c1", 200, None)), seed="trade-tie")
    first = _compute(scenario, ticks=1)
    second = _compute(scenario, ticks=1)
    assert first.trade_events == second.trade_events
    assert first.analytics_fingerprint == second.analytics_fingerprint

    outside = _scenario((("c1", "t1", 200, None), ("t2", "c1", 301, None)), seed="custom-window")
    assert _compute(outside, ticks=100).trade_events == ()
    assert len(_compute(outside, ticks=101).trade_events) == 1


def test_tick_mode_is_authoritative_without_tickrate_and_does_not_claim_seconds() -> None:
    scenario = _scenario((("c1", "t1", 200, None), ("t2", "c1", 220, None)), seed="tick-policy")
    result = AnalyticsEngine().compute(scenario.data)

    assert result.config.trade_window == TradeWindowConfig.ticks(320)
    assert result.availability.trade_metrics.status is AnalyticsAvailability.AVAILABLE
    assert result.availability.kast_metrics.trade_window_mode is TradeWindowMode.TICKS
    assert result.trade_events[0].seconds_delta is None
    assert result.trade_events[0].seconds_delta_status is TimeConversionStatus.UNAVAILABLE
    assert result.trade_events[0].seconds_delta_source is None


def test_kast_k_a_s_t_and_no_kast() -> None:
    scenario = _scenario(
        (
            ("t1", "c1", 180, "t2"),
            ("c2", "t3", 200, None),
            ("t4", "c2", 230, None),
            ("c3", "t5", 250, None),
        ),
        seed="kast",
    )
    result = _compute(scenario)

    assert _player_round(result, scenario, "t1").kast_k
    assert _player_round(result, scenario, "t2").kast_a
    assert _player_round(result, scenario, "t2").kast_s
    assert _player_round(result, scenario, "t3").kast_t
    assert not _player_round(result, scenario, "t5").kast


@pytest.mark.parametrize("invalid_assister", ["c2", None])
def test_invalid_or_missing_assister_does_not_create_kast_a(invalid_assister: str | None) -> None:
    scenario = _scenario(
        (("t1", "c1", 180, invalid_assister),), seed=f"invalid-assist-{invalid_assister}"
    )
    result = _compute(scenario)
    if invalid_assister:
        assert not _player_round(result, scenario, invalid_assister).kast_a
    assert sum(row.assists for row in result.player_rounds) == 0


def test_teamkill_assist_is_excluded() -> None:
    scenario = _scenario((("t1", "t2", 180, "t3"),), seed="teamkill-assist")
    result = _compute(scenario)
    assert sum(row.assists for row in result.player_rounds) == 0
    assert _player_round(result, scenario, "t1").teamkill_count == 1


@pytest.mark.parametrize(
    ("count", "category"),
    [
        (0, MultikillCategory.ZERO),
        (1, MultikillCategory.ONE),
        (2, MultikillCategory.TWO),
        (3, MultikillCategory.THREE),
        (4, MultikillCategory.FOUR),
        (5, MultikillCategory.FIVE),
        (6, MultikillCategory.FIVE_PLUS),
    ],
)
def test_multikill_categories_preserve_overflow(count: int, category: MultikillCategory) -> None:
    kills = tuple(("t1", f"c{index}", 150 + index, None) for index in range(1, count + 1))
    scenario = _scenario(kills, t_count=6, ct_count=6, seed=f"multikill-{count}")
    row = _player_round(_compute(scenario), scenario, "t1")
    assert (row.multikill_count, row.multikill_category) == (count, category)


@pytest.mark.parametrize(
    "death",
    [
        ("c1", "t1", 200, None),
        ("t2", "t1", 200, None),
        ("t1", "t1", 200, None),
        (None, "t1", 200, None),
    ],
)
def test_any_observed_death_means_not_survived(
    death: tuple[str | None, str, int, str | None],
) -> None:
    scenario = _scenario((death,), seed=f"survival-{death}")
    assert not _player_round(_compute(scenario), scenario, "t1").survived


def test_nonparticipant_has_no_false_survival_row() -> None:
    scenario = _scenario(membership_starts={"t5": 1100}, seed="nonparticipant")
    result = _compute(scenario)
    assert all(row.player_id != scenario.players["t5"] for row in result.player_rounds)
    assert len(result.player_rounds) == 9


def test_advantage_timeline_and_plus_two_conversion() -> None:
    scenario = _scenario(
        (("t1", "c1", 200, None), ("t2", "c2", 220, None)), seed="advantage-plus-two"
    )
    result = _compute(scenario)
    transitions = result.man_advantage_transitions
    assert [(row.t_alive_after, row.ct_alive_after) for row in transitions] == [(5, 4), (5, 3)]
    team_a = next(row for row in result.team_rounds if row.team_id == scenario.teams["a"])
    assert team_a.gained_first_advantage
    assert team_a.reached_plus_two
    assert team_a.converted_plus_two is True


def test_first_advantage_can_be_lost_in_tied_trade_sequence() -> None:
    scenario = _scenario((("t1", "c1", 200, None), ("c2", "t1", 220, None)), seed="advantage-lost")
    team_a = next(
        row for row in _compute(scenario).team_rounds if row.team_id == scenario.teams["a"]
    )
    assert team_a.gained_first_advantage
    assert team_a.lost_first_advantage


def test_unequal_initial_lineup_disables_advantage_conversion() -> None:
    scenario = _scenario((("t1", "c1", 200, None),), t_count=4, ct_count=5, seed="four-v-five")
    result = _compute(scenario)
    assert result.availability.advantage_metrics.status is AnalyticsAvailability.UNAVAILABLE
    assert all(not row.lineup_valid for row in result.team_rounds)
    assert all(
        not row.gained_first_advantage and not row.reached_plus_two for row in result.team_rounds
    )
    assert all(row.converted_first_advantage is None for row in result.team_rounds)


def test_no_kills_has_stable_alive_state_without_transitions() -> None:
    result = _compute(_scenario(seed="no-kills"))
    assert result.man_advantage_transitions == ()
    assert {row.final_alive for row in result.team_rounds} == {5}


@pytest.mark.parametrize(
    ("winner", "bombs", "expected"),
    [
        (Side.T, (("planted", "t1", 500, 999),), (1, 0, 0, True)),
        (
            Side.CT,
            (("planted", "t1", 500, 999), ("defused", "c1", 700, 999)),
            (1, 1, 0, False),
        ),
        (
            Side.T,
            (("planted", "t1", 500, 999), ("exploded", None, 800, 999)),
            (1, 0, 1, True),
        ),
    ],
)
def test_bomb_metrics_use_round_sides_not_optional_event_team(
    winner: Side,
    bombs: tuple[tuple[str, str | None, int, str | int | None], ...],
    expected: tuple[int, int, int, bool],
) -> None:
    scenario = _scenario(winner=winner, bombs=bombs, seed=f"bomb-{winner}-{bombs}")
    result = _compute(scenario)
    team_a = next(row for row in result.team_matches if row.team_id == scenario.teams["a"])
    team_b = next(row for row in result.team_matches if row.team_id == scenario.teams["b"])
    assert (
        team_a.plants,
        team_b.defuses,
        team_a.explosions,
        bool(team_a.post_plant_wins),
    ) == expected
    assert scenario.data.bomb_events[0].site_raw == 999


def test_bomb_conversions_are_null_without_winner() -> None:
    result = _compute(
        _scenario(winner=None, bombs=(("planted", "t1", 500, "unknown"),), seed="bomb-null")
    )
    assert all(row.post_plant_won is None for row in result.team_rounds if row.planted_round)
    assert all(row.post_plant_conversion_percentage is None for row in result.team_matches)


def test_effective_enemy_damage_clamps_overkill_without_mutating_canonical() -> None:
    scenario = _scenario(
        damages=(("t1", "c1", 200, 80, 20), ("t1", "c1", 220, 100, 0)),
        seed="effective-damage",
    )
    result = _compute(scenario)
    row = _player_round(result, scenario, "t1")
    assert row.enemy_damage == 100
    assert scenario.data.damages[-1].damage_health == 100


def test_zero_denominators_are_null_and_output_order_is_deterministic() -> None:
    scenario = _scenario(seed="zero-denominator")
    result = _compute(scenario)
    assert all(row.kd_ratio is None for row in result.player_matches)
    assert all(row.headshot_percentage is None for row in result.player_matches)
    assert [str(row.player_id) for row in result.player_matches] == sorted(
        str(row.player_id) for row in result.player_matches
    )


def test_physical_team_identity_survives_side_swap_and_overtime() -> None:
    first = _scenario((("t1", "c1", 150, None),), seed="side-swap")
    data = first.data
    round_one = data.rounds[0].model_copy(update={"end_tick": 200, "official_end_tick": 210})
    round_two_id = uuid5(data.match_id, "round:2")
    round_two = round_one.model_copy(
        update={
            "round_id": round_two_id,
            "round_number": 2,
            "start_tick": 300,
            "freeze_end_tick": 310,
            "end_tick": 400,
            "official_end_tick": 410,
            "t_team_id": first.teams["b"],
            "ct_team_id": first.teams["a"],
            "winner_side": Side.CT,
            "is_overtime": True,
        }
    )
    memberships = []
    for item in data.memberships:
        memberships.append(item.model_copy(update={"valid_to_tick": 210}))
        memberships.append(
            item.model_copy(
                update={
                    "side": Side.CT if item.side is Side.T else Side.T,
                    "valid_from_tick": 300,
                    "valid_to_tick": None,
                }
            )
        )
    original = data.kills[0]
    second_kill = original.model_copy(
        update={
            "event_id": uuid5(data.match_id, "kill:round2"),
            "round_id": round_two_id,
            "round_number": 2,
            "tick": 350,
            "relative_tick": 50,
            "attacker_side": Side.CT,
            "victim_side": Side.T,
        }
    )
    result = AnalyticsEngine().compute(
        data.model_copy(
            update={
                "rounds": (round_one, round_two),
                "memberships": tuple(memberships),
                "kills": (original, second_kill),
            }
        ),
        AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100)),
    )
    team_a = next(row for row in result.team_matches if row.team_id == first.teams["a"])
    assert (team_a.rounds_played, team_a.t_rounds, team_a.ct_rounds) == (2, 1, 1)
    assert (team_a.t_round_wins, team_a.ct_round_wins, team_a.round_wins) == (1, 1, 2)


def test_fingerprint_changes_only_with_canonical_or_analytics_inputs() -> None:
    scenario = _scenario((("t1", "c1", 200, None),), seed="fingerprint")
    engine = AnalyticsEngine()
    base = engine.compute(scenario.data, AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100)))
    repeat = engine.compute(
        scenario.data, AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100))
    )
    changed_config = engine.compute(
        scenario.data, AnalyticsConfig(trade_window=TradeWindowConfig.ticks(101))
    )
    changed_dataset = engine.compute(
        scenario.data.model_copy(update={"dataset_fingerprint": "f" * 64}),
        AnalyticsConfig(trade_window=TradeWindowConfig.ticks(100)),
    )
    assert base.analytics_fingerprint == repeat.analytics_fingerprint
    assert base.analytics_fingerprint != changed_config.analytics_fingerprint
    assert base.analytics_fingerprint != changed_dataset.analytics_fingerprint
    assert base.validation_issues == ()


def test_seconds_mode_resolves_ticks_and_emits_sourced_seconds() -> None:
    scenario = _scenario((("c1", "t1", 200, None), ("t2", "c1", 250, None)), seed="seconds-policy")
    config = AnalyticsConfig(
        trade_window=TradeWindowConfig.seconds(
            1.25, tickrate=40, tickrate_source="canonical:test_tickrate"
        )
    )

    result = AnalyticsEngine().compute(scenario.data, config)
    repeat = AnalyticsEngine().compute(scenario.data, config)
    tick_mode = AnalyticsEngine().compute(
        scenario.data,
        AnalyticsConfig(trade_window=TradeWindowConfig.ticks(50)),
    )

    assert result.config.trade_window.resolved_ticks == 50
    assert result.summary.trade_window_requested_seconds == 1.25
    assert result.trade_events[0].seconds_delta == 1.25
    assert result.trade_events[0].seconds_delta_status is TimeConversionStatus.AVAILABLE
    assert result.trade_events[0].seconds_delta_source == "canonical:test_tickrate"
    assert result.availability.kast_metrics.trade_window_mode is TradeWindowMode.SECONDS
    assert result.analytics_fingerprint == repeat.analytics_fingerprint
    assert result.analytics_fingerprint != tick_mode.analytics_fingerprint


def test_seconds_to_ticks_uses_deterministic_half_up_rounding() -> None:
    assert seconds_to_ticks(1.25, 2) == 3
