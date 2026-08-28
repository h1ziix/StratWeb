"""Steam-ID-first player resolution and physical-team/side reconstruction."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from uuid import UUID, uuid5

from stratweb.application.canonical_models import (
    CanonicalPlayer,
    CanonicalRound,
    CanonicalTeam,
    PlayerTeamMembership,
)
from stratweb.application.normalization_utils import (
    StableRawRow,
    optional_steam_id,
    role_values,
    stable_rows,
    value,
)
from stratweb.application.round_assignment import RoundAssignmentService
from stratweb.contracts import ParsedDemo
from stratweb.domain.enums import Side

PlayerReferenceKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class SideObservation:
    player_id: UUID
    tick: int
    side: Side
    source: str


@dataclass(frozen=True, slots=True)
class PlayerResolutionResult:
    players: tuple[CanonicalPlayer, ...]
    by_steam_id: dict[str, UUID]
    reference_player_ids: dict[PlayerReferenceKey, UUID]
    side_observations: tuple[SideObservation, ...]

    def player_for(self, row: StableRawRow, role: str) -> UUID | None:
        return self.reference_player_ids.get((row.source_event, row.row_key, role))


@dataclass(frozen=True, slots=True)
class TeamResolutionResult:
    teams: tuple[CanonicalTeam, ...]
    memberships: tuple[PlayerTeamMembership, ...]
    rounds: tuple[CanonicalRound, ...]
    player_team_ids: dict[UUID, UUID]
    warnings: tuple[str, ...]

    def team_for(self, player_id: UUID | None) -> UUID | None:
        return self.player_team_ids.get(player_id) if player_id else None

    def side_for(self, player_id: UUID | None, tick: int) -> Side:
        if player_id is None:
            return Side.UNKNOWN
        for membership in self.memberships:
            if membership.player_id != player_id:
                continue
            if tick < membership.valid_from_tick:
                continue
            if membership.valid_to_tick is None or tick <= membership.valid_to_tick:
                return membership.side
        return Side.UNKNOWN


@dataclass(slots=True)
class _PlayerAccumulator:
    player_id: UUID
    steam_id: str | None
    names: list[tuple[int, str]] = field(default_factory=list)
    is_bot: bool = False
    warnings: set[str] = field(default_factory=set)
    connect_ticks: list[int] = field(default_factory=list)
    disconnect_ticks: list[int] = field(default_factory=list)


class PlayerResolver:
    """Resolve real players only by Steam ID; unknown actors stay occurrence-scoped."""

    def resolve(self, parsed: ParsedDemo, match_id: UUID) -> PlayerResolutionResult:
        accumulators: dict[UUID, _PlayerAccumulator] = {}
        by_steam: dict[str, UUID] = {}
        references: dict[PlayerReferenceKey, UUID] = {}
        side_observations: list[SideObservation] = []

        for row in stable_rows("player_info", parsed.player_info, exclude_warmup=False):
            steam, name, _side, is_bot = role_values(row.data, "user")
            player_id = self._resolve_id(
                match_id,
                source="player_info",
                row=row,
                role="user",
                steam_id=steam,
                name=name,
                by_steam=by_steam,
            )
            self._record(
                accumulators,
                player_id,
                steam_id=steam,
                name=name,
                tick=-1,
                is_bot=is_bot,
                raw_steam=value(row.data, "steamid", "steam_id"),
            )

        for source_event, frame in sorted(parsed.tables.items()):
            for row in stable_rows(source_event, frame):
                for role in _roles_for_event(source_event):
                    steam, name, side, is_bot = role_values(row.data, role)
                    if steam is None and name is None:
                        continue
                    if (
                        source_event in {"player_connect_full", "player_disconnect"}
                        and steam is None
                    ):
                        continue
                    player_id = self._resolve_id(
                        match_id,
                        source=source_event,
                        row=row,
                        role=role,
                        steam_id=steam,
                        name=name,
                        by_steam=by_steam,
                    )
                    references[(source_event, row.row_key, role)] = player_id
                    raw_steam = _raw_role_steam(row, role)
                    self._record(
                        accumulators,
                        player_id,
                        steam_id=steam,
                        name=name,
                        tick=row.tick if row.tick is not None else -1,
                        is_bot=is_bot,
                        raw_steam=raw_steam,
                    )
                    if row.tick is not None and source_event == "player_connect_full":
                        accumulators[player_id].connect_ticks.append(row.tick)
                    if row.tick is not None and source_event == "player_disconnect":
                        accumulators[player_id].disconnect_ticks.append(row.tick)
                    if row.tick is not None and side is not Side.UNKNOWN:
                        side_observations.append(
                            SideObservation(
                                player_id=player_id,
                                tick=row.tick,
                                side=side,
                                source=f"{source_event}.{role}_team",
                            )
                        )

        players: list[CanonicalPlayer] = []
        for accumulator in accumulators.values():
            known_names = tuple(sorted({name for _tick, name in accumulator.names}))
            if not known_names:
                known_names = (f"UnknownPlayer-{str(accumulator.player_id)[:8]}",)
            current_name = max(accumulator.names, default=(-1, known_names[0]))[1]
            if len(known_names) > 1:
                accumulator.warnings.add("nickname_change_observed")
            if any(
                connect_tick > disconnect_tick
                for connect_tick in accumulator.connect_ticks
                for disconnect_tick in accumulator.disconnect_ticks
            ):
                accumulator.warnings.add("reconnect_observed")
            if accumulator.steam_id is None:
                accumulator.warnings.add("steam_id_missing; identity was not merged by nickname")
            if accumulator.is_bot:
                accumulator.warnings.add("bot_identity")
            players.append(
                CanonicalPlayer(
                    player_id=accumulator.player_id,
                    steam_id=accumulator.steam_id,
                    current_name=current_name,
                    known_names=known_names,
                    is_bot=accumulator.is_bot,
                    warnings=tuple(sorted(accumulator.warnings)),
                )
            )

        return PlayerResolutionResult(
            players=tuple(sorted(players, key=lambda item: str(item.player_id))),
            by_steam_id=by_steam,
            reference_player_ids=references,
            side_observations=tuple(
                sorted(
                    side_observations,
                    key=lambda item: (item.tick, str(item.player_id), item.source),
                )
            ),
        )

    @staticmethod
    def _resolve_id(
        match_id: UUID,
        *,
        source: str,
        row: StableRawRow,
        role: str,
        steam_id: str | None,
        name: str | None,
        by_steam: dict[str, UUID],
    ) -> UUID:
        if steam_id:
            player_id = by_steam.setdefault(
                steam_id,
                uuid5(match_id, f"player:steam:{steam_id}"),
            )
            return player_id
        # Occurrence-scoped IDs deliberately avoid merging unrelated people who
        # happen to share a nickname.
        return uuid5(match_id, f"player:unknown:{source}:{row.row_key}:{role}:{name or ''}")

    @staticmethod
    def _record(
        accumulators: dict[UUID, _PlayerAccumulator],
        player_id: UUID,
        *,
        steam_id: str | None,
        name: str | None,
        tick: int,
        is_bot: bool,
        raw_steam: object,
    ) -> None:
        accumulator = accumulators.setdefault(
            player_id,
            _PlayerAccumulator(player_id=player_id, steam_id=steam_id),
        )
        if name:
            accumulator.names.append((tick, name))
        accumulator.is_bot = accumulator.is_bot or is_bot
        if raw_steam is not None and optional_steam_id(raw_steam) is None:
            accumulator.warnings.add("invalid_steam_id")


class TeamResolver:
    """Separate physical roster identity from observed T/CT assignments."""

    def resolve(
        self,
        match_id: UUID,
        players: PlayerResolutionResult,
        rounds: tuple[CanonicalRound, ...],
    ) -> TeamResolutionResult:
        assignment = RoundAssignmentService(rounds)
        round_observations: dict[int, list[SideObservation]] = defaultdict(list)
        first_side: dict[UUID, tuple[int, Side]] = {}
        for observation in players.side_observations:
            assigned = assignment.assign(observation.tick)
            if assigned.round_number is None:
                continue
            round_observations[assigned.round_number].append(observation)
            candidate = (assigned.round_number, observation.side)
            if (
                observation.player_id not in first_side
                or candidate[0] < first_side[observation.player_id][0]
            ):
                first_side[observation.player_id] = candidate

        first_observed_round = min(
            (round_number for round_number, _side in first_side.values()),
            default=None,
        )
        side_groups: dict[Side, set[UUID]] = {Side.T: set(), Side.CT: set()}
        for player_id, (round_number, side) in first_side.items():
            if round_number == first_observed_round and side in side_groups:
                side_groups[side].add(player_id)

        populated = [group for group in side_groups.values() if group]
        populated.sort(key=lambda group: tuple(sorted(str(player_id) for player_id in group)))
        group_team_ids: dict[frozenset[UUID], UUID] = {}
        teams: list[CanonicalTeam] = []
        for index, group in enumerate(populated):
            signature = ",".join(sorted(str(player_id) for player_id in group))
            team_id = uuid5(match_id, f"physical-team:{signature}")
            group_team_ids[frozenset(group)] = team_id
            warnings = () if len(group) >= 2 else ("Physical team identity has a one-player seed.",)
            teams.append(
                CanonicalTeam(
                    team_id=team_id,
                    match_id=match_id,
                    internal_name=f"Team{'Alpha' if index == 0 else 'Bravo'}",
                    starting_player_ids=tuple(sorted(group, key=str)),
                    identity_confidence=1.0 if len(group) >= 2 else 0.5,
                    warnings=warnings,
                )
            )

        player_team_ids: dict[UUID, UUID] = {}
        for frozen_group, team_id in group_team_ids.items():
            for player_id in frozen_group:
                player_team_ids[player_id] = team_id

        identity_warnings: list[str] = []
        for player_id, (round_number, side) in sorted(
            first_side.items(), key=lambda item: (item[1][0], str(item[0]))
        ):
            if player_id in player_team_ids or round_number == first_observed_round:
                continue
            votes: Counter[UUID] = Counter()
            for observation in round_observations.get(round_number, []):
                known_team = player_team_ids.get(observation.player_id)
                if known_team is not None and observation.side is side:
                    votes[known_team] += 1
            if votes:
                player_team_ids[player_id] = votes.most_common(1)[0][0]
                identity_warnings.append(
                    f"Substitution or late join inferred for player {player_id} "
                    f"in round {round_number}."
                )
            else:
                identity_warnings.append(
                    f"Physical team is unresolved for late player {player_id} "
                    f"in round {round_number}."
                )

        resolved_rounds, round_warnings = self._resolve_round_sides(
            rounds,
            round_observations,
            player_team_ids,
            tuple(team.team_id for team in teams),
        )
        memberships = self._memberships(players, resolved_rounds, player_team_ids)

        return TeamResolutionResult(
            teams=tuple(sorted(teams, key=lambda item: item.internal_name)),
            memberships=memberships,
            rounds=resolved_rounds,
            player_team_ids=player_team_ids,
            warnings=tuple(dict.fromkeys((*identity_warnings, *round_warnings))),
        )

    @staticmethod
    def _resolve_round_sides(
        rounds: tuple[CanonicalRound, ...],
        observations: dict[int, list[SideObservation]],
        player_team_ids: dict[UUID, UUID],
        team_ids: tuple[UUID, ...],
    ) -> tuple[tuple[CanonicalRound, ...], list[str]]:
        result: list[CanonicalRound] = []
        warnings: list[str] = []
        previous_pair: tuple[UUID, UUID] | None = None
        switch_count = 0

        for round_item in rounds:
            votes: dict[Side, Counter[UUID]] = {Side.T: Counter(), Side.CT: Counter()}
            for observation in observations.get(round_item.round_number, []):
                team_id = player_team_ids.get(observation.player_id)
                if team_id and observation.side in votes:
                    votes[observation.side][team_id] += 1

            t_team = votes[Side.T].most_common(1)[0][0] if votes[Side.T] else None
            ct_team = votes[Side.CT].most_common(1)[0][0] if votes[Side.CT] else None
            if len(team_ids) == 2:
                if t_team is not None and ct_team is None:
                    ct_team = next(team for team in team_ids if team != t_team)
                elif ct_team is not None and t_team is None:
                    t_team = next(team for team in team_ids if team != ct_team)
                elif t_team is None and ct_team is None and previous_pair is not None:
                    t_team, ct_team = previous_pair

            round_warning = list(round_item.warnings)
            if t_team is None or ct_team is None or t_team == ct_team:
                round_warning.append("Physical team side assignment is uncertain.")
                warnings.append(
                    f"Side resolution is uncertain for round {round_item.round_number}."
                )

            current_pair = (t_team, ct_team) if t_team and ct_team and t_team != ct_team else None
            if current_pair and previous_pair and current_pair == previous_pair[::-1]:
                switch_count += 1
            if current_pair:
                previous_pair = current_pair

            result.append(
                round_item.model_copy(
                    update={
                        "t_team_id": t_team,
                        "ct_team_id": ct_team,
                        # Overtime begins only after a second observed physical-team
                        # side transition; no fixed regulation round number is used.
                        "is_overtime": round_item.is_overtime or switch_count >= 2,
                        "warnings": tuple(dict.fromkeys(round_warning)),
                    }
                )
            )
        return tuple(result), warnings

    @staticmethod
    def _memberships(
        players: PlayerResolutionResult,
        rounds: tuple[CanonicalRound, ...],
        player_team_ids: dict[UUID, UUID],
    ) -> tuple[PlayerTeamMembership, ...]:
        memberships: list[PlayerTeamMembership] = []
        for player in players.players:
            team_id = player_team_ids.get(player.player_id)
            spans: list[tuple[int, int | None, Side]] = []
            for round_item in rounds:
                if round_item.start_tick is None or team_id is None:
                    continue
                if round_item.t_team_id == team_id:
                    side = Side.T
                elif round_item.ct_team_id == team_id:
                    side = Side.CT
                else:
                    continue
                end_tick = round_item.end_tick
                if spans and spans[-1][2] is side:
                    start, _old_end, existing_side = spans[-1]
                    spans[-1] = (start, end_tick, existing_side)
                else:
                    if spans:
                        old_start, _old_end, old_side = spans[-1]
                        spans[-1] = (old_start, round_item.start_tick - 1, old_side)
                    spans.append((round_item.start_tick, end_tick, side))

            for start_tick, end_tick, side in spans:
                memberships.append(
                    PlayerTeamMembership(
                        player_id=player.player_id,
                        team_id=team_id,
                        side=side,
                        valid_from_tick=start_tick,
                        valid_to_tick=end_tick,
                        source="observed event-side majority by canonical round",
                        confidence=0.9,
                    )
                )
        return tuple(
            sorted(
                memberships,
                key=lambda item: (str(item.player_id), item.valid_from_tick, item.side.value),
            )
        )


def _roles_for_event(source_event: str) -> tuple[str, ...]:
    if source_event == "player_death":
        return ("attacker", "victim", "assister")
    if source_event == "player_hurt":
        return ("attacker", "victim")
    if source_event == "player_blind":
        return ("attacker", "user")
    return ("user",)


def _raw_role_steam(row: StableRawRow, role: str) -> object:
    prefix = {
        "attacker": "attacker_",
        "victim": "user_",
        "assister": "assister_",
        "user": "user_",
    }[role]
    raw = value(row.data, f"{prefix}steamid", f"{prefix}steam_id")
    if role == "user" and raw is None:
        raw = value(row.data, "steamid", "steam_id", "player_steamid")
    return raw
