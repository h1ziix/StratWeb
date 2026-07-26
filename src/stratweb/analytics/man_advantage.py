"""Alive-count timelines and first-advantage facts without clutch inference."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from stratweb.application.canonical_models import CanonicalRound
from stratweb.domain.enums import Side

from .definitions import ClassifiedKill, Participant
from .models import (
    AdvantageState,
    DeathClassification,
    ManAdvantageTransition,
)


@dataclass(frozen=True, slots=True)
class AdvantageRoundResult:
    transitions: tuple[ManAdvantageTransition, ...]
    lineup_valid: bool
    first_advantage_team_id: UUID | None
    first_advantage_size: int
    first_advantage_lost: bool
    reached_plus_two: frozenset[UUID]
    max_advantage: dict[UUID, int]
    final_alive: dict[UUID, int]


def advantage_for_round(
    round_item: CanonicalRound,
    kills: tuple[ClassifiedKill, ...],
    participants: dict[UUID, Participant],
) -> AdvantageRoundResult:
    t_team = round_item.t_team_id
    ct_team = round_item.ct_team_id
    t_players = {item.player_id for item in participants.values() if item.side is Side.T}
    ct_players = {item.player_id for item in participants.values() if item.side is Side.CT}
    lineup_valid = (
        t_team is not None
        and ct_team is not None
        and t_team != ct_team
        and bool(t_players)
        and bool(ct_players)
        and len(t_players) == len(ct_players)
        and t_players.isdisjoint(ct_players)
    )
    if t_team is None or ct_team is None:
        return AdvantageRoundResult((), False, None, 0, False, frozenset(), {}, {})

    alive = {Side.T: len(t_players), Side.CT: len(ct_players)}
    dead: set[UUID] = set()
    first_team = None
    first_size = 0
    first_lost = False
    reached_plus_two: set[UUID] = set()
    max_advantage = {t_team: 0, ct_team: 0}
    transitions: list[ManAdvantageTransition] = []

    for item in kills:
        event = item.event
        if event.victim_player_id is None:
            continue
        victim = participants.get(event.victim_player_id)
        if victim is None:
            continue
        before_t, before_ct = alive[Side.T], alive[Side.CT]
        classification = _death_classification(item.classification)
        if event.victim_player_id in dead:
            classification = DeathClassification.REPEATED
        else:
            dead.add(event.victim_player_id)
            alive[victim.side] = max(0, alive[victim.side] - 1)
        after_t, after_ct = alive[Side.T], alive[Side.CT]
        signed_before = before_t - before_ct
        signed_after = after_t - after_ct
        transitions.append(
            ManAdvantageTransition(
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                tick=event.tick,
                event_id=event.event_id,
                t_alive_before=before_t,
                t_alive_after=after_t,
                ct_alive_before=before_ct,
                ct_alive_after=after_ct,
                signed_advantage_before=signed_before,
                signed_advantage_after=signed_after,
                advantage_before=_state(signed_before),
                advantage_after=_state(signed_after),
                causing_killer_player_id=event.attacker_player_id,
                causing_victim_player_id=event.victim_player_id,
                event_classification=classification,
            )
        )
        current_team = _advantaged_team(alive, t_team, ct_team) if lineup_valid else None
        if first_team is None and current_team is not None:
            first_team = current_team
            first_size = abs(signed_after)
        elif first_team is not None and current_team != first_team:
            first_lost = True
        if lineup_valid:
            t_advantage = max(signed_after, 0)
            ct_advantage = max(-signed_after, 0)
            max_advantage[t_team] = max(max_advantage[t_team], t_advantage)
            max_advantage[ct_team] = max(max_advantage[ct_team], ct_advantage)
            if t_advantage >= 2:
                reached_plus_two.add(t_team)
            if ct_advantage >= 2:
                reached_plus_two.add(ct_team)

    return AdvantageRoundResult(
        transitions=tuple(transitions),
        lineup_valid=lineup_valid,
        first_advantage_team_id=first_team,
        first_advantage_size=first_size,
        first_advantage_lost=first_lost,
        reached_plus_two=frozenset(reached_plus_two),
        max_advantage=max_advantage,
        final_alive={t_team: alive[Side.T], ct_team: alive[Side.CT]},
    )


def _state(signed: int) -> AdvantageState:
    if signed > 0:
        return AdvantageState.T_ADVANTAGE
    if signed < 0:
        return AdvantageState.CT_ADVANTAGE
    return AdvantageState.EVEN


def _advantaged_team(alive: dict[Side, int], t_team: UUID, ct_team: UUID) -> UUID | None:
    signed = alive[Side.T] - alive[Side.CT]
    return t_team if signed > 0 else ct_team if signed < 0 else None


def _death_classification(value: str) -> DeathClassification:
    try:
        return DeathClassification(value)
    except ValueError:
        return DeathClassification.INVALID
