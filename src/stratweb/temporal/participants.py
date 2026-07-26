"""Evidence-ranked per-round participation and team/side identity."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGameplayEvent,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalShot,
    PlayerTeamMembership,
)
from stratweb.domain.enums import Side

from .definitions import first_available_tick
from .models import (
    ParticipantRoundState,
    ParticipationStatus,
    PlayerLifeStatus,
)


@dataclass(frozen=True, slots=True)
class _Observation:
    team_id: UUID | None
    side: Side
    source: str
    tick: int


def participants_for_round(
    round_item: CanonicalRound,
    *,
    players: tuple[CanonicalPlayer, ...],
    memberships: tuple[PlayerTeamMembership, ...],
    kills: tuple[CanonicalKill, ...],
    damages: tuple[CanonicalDamage, ...],
    shots: tuple[CanonicalShot, ...],
    grenades: tuple[CanonicalGrenade, ...],
    bomb_events: tuple[CanonicalBombEvent, ...],
) -> tuple[ParticipantRoundState, ...]:
    observations = _observations(
        round_item,
        kills=kills,
        damages=damages,
        shots=shots,
        grenades=grenades,
        bomb_events=bomb_events,
    )
    player_ids = (
        {item.player_id for item in players}
        | {item.player_id for item in memberships}
        | set(observations)
    )
    end_tick = first_available_tick(
        round_item.official_end_tick, round_item.end_tick, round_item.start_tick
    )
    result: list[ParticipantRoundState] = []
    for player_id in sorted(player_ids, key=str):
        membership_values: set[tuple[UUID, Side]] = set()
        membership_sources: set[str] = set()
        for membership in memberships:
            if membership.player_id != player_id or membership.team_id is None:
                continue
            if not _intersects(membership, round_item.start_tick, end_tick):
                continue
            side = _side_for_team(round_item, membership.team_id)
            if side is None:
                continue
            membership_values.add((membership.team_id, side))
            membership_sources.add(f"membership:{membership.source}")

        observed = observations.get(player_id, ())
        observed_values = {
            value
            for item in observed
            if (value := _resolved_observation(round_item, item)) is not None
        }
        sources = membership_sources | {f"event:{item.source}" for item in observed}
        first_seen = min((item.tick for item in observed), default=None)
        last_seen = max((item.tick for item in observed), default=None)

        if len(membership_values) == 1:
            team_id, side = next(iter(membership_values))
            if observed_values and observed_values != membership_values:
                status = ParticipationStatus.UNRESOLVED
                initial = PlayerLifeStatus.UNKNOWN
            else:
                status = ParticipationStatus.INFERRED_FROM_MEMBERSHIP
                initial = PlayerLifeStatus.ALIVE
        elif len(membership_values) > 1:
            team_id, side = None, Side.UNKNOWN
            status = ParticipationStatus.UNRESOLVED
            initial = PlayerLifeStatus.UNKNOWN
        elif len(observed_values) == 1:
            team_id, side = next(iter(observed_values))
            status = ParticipationStatus.EVENT_OBSERVED
            initial = PlayerLifeStatus.UNKNOWN
        elif observed:
            team_id, side = None, Side.UNKNOWN
            status = ParticipationStatus.UNRESOLVED
            initial = PlayerLifeStatus.UNKNOWN
        else:
            team_id, side = None, Side.UNKNOWN
            status = ParticipationStatus.NOT_PARTICIPATING
            initial = PlayerLifeStatus.NOT_PARTICIPATING

        result.append(
            ParticipantRoundState(
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                player_id=player_id,
                physical_team_id=team_id,
                side=side,
                participation_status=status,
                participation_sources=tuple(sorted(sources)),
                initial_alive_status=initial,
                first_seen_tick=first_seen,
                last_seen_tick=last_seen,
            )
        )
    return tuple(result)


def participating_states(
    states: tuple[ParticipantRoundState, ...],
) -> tuple[ParticipantRoundState, ...]:
    return tuple(
        item
        for item in states
        if item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
    )


def _intersects(
    membership: PlayerTeamMembership,
    start_tick: int | None,
    end_tick: int | None,
) -> bool:
    if start_tick is None:
        return False
    if end_tick is None:
        end_tick = start_tick
    if membership.valid_from_tick > end_tick:
        return False
    return membership.valid_to_tick is None or membership.valid_to_tick >= start_tick


def _side_for_team(round_item: CanonicalRound, team_id: UUID) -> Side | None:
    if team_id == round_item.t_team_id:
        return Side.T
    if team_id == round_item.ct_team_id:
        return Side.CT
    return None


def _resolved_observation(
    round_item: CanonicalRound, observation: _Observation
) -> tuple[UUID, Side] | None:
    if observation.team_id is not None:
        side = _side_for_team(round_item, observation.team_id)
        if side is None:
            return None
        if observation.side not in {Side.UNKNOWN, side}:
            return None
        return observation.team_id, side
    if observation.side is Side.T and round_item.t_team_id is not None:
        return round_item.t_team_id, Side.T
    if observation.side is Side.CT and round_item.ct_team_id is not None:
        return round_item.ct_team_id, Side.CT
    return None


def _observations(
    round_item: CanonicalRound,
    *,
    kills: tuple[CanonicalKill, ...],
    damages: tuple[CanonicalDamage, ...],
    shots: tuple[CanonicalShot, ...],
    grenades: tuple[CanonicalGrenade, ...],
    bomb_events: tuple[CanonicalBombEvent, ...],
) -> dict[UUID, tuple[_Observation, ...]]:
    values: dict[UUID, list[_Observation]] = defaultdict(list)

    def add(
        event: CanonicalGameplayEvent,
        player_id: UUID | None,
        team_id: UUID | None,
        side: Side,
    ) -> None:
        if player_id is not None and _belongs(event, round_item):
            values[player_id].append(_Observation(team_id, side, event.source_event, event.tick))

    for kill_event in kills:
        add(
            kill_event,
            kill_event.attacker_player_id,
            kill_event.attacker_team_id,
            kill_event.attacker_side,
        )
        add(
            kill_event,
            kill_event.victim_player_id,
            kill_event.victim_team_id,
            kill_event.victim_side,
        )
    for damage_event in damages:
        add(
            damage_event,
            damage_event.attacker_player_id,
            damage_event.attacker_team_id,
            damage_event.attacker_side,
        )
        add(
            damage_event,
            damage_event.victim_player_id,
            damage_event.victim_team_id,
            damage_event.victim_side,
        )
    for shot_event in shots:
        add(shot_event, shot_event.player_id, shot_event.team_id, shot_event.side)
    for grenade_event in grenades:
        add(
            grenade_event,
            grenade_event.player_id,
            grenade_event.team_id,
            grenade_event.side,
        )
    for bomb_event in bomb_events:
        add(bomb_event, bomb_event.player_id, bomb_event.team_id, bomb_event.side)
    return {player_id: tuple(items) for player_id, items in values.items()}


def _belongs(event: CanonicalGameplayEvent, round_item: CanonicalRound) -> bool:
    return event.round_id == round_item.round_id and event.round_number == round_item.round_number
