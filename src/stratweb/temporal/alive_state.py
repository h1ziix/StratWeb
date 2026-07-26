"""Deterministic player life-state transitions from canonical deaths."""

from __future__ import annotations

from uuid import UUID, uuid5

from stratweb.application.canonical_models import CanonicalKill, CanonicalRound

from .models import (
    LifeTransition,
    ParticipantRoundState,
    PlayerLifeStatus,
    TemporalDeathClassification,
    TemporalEvent,
    TemporalEventKind,
    TemporalOrderingStatus,
    TemporalTransitionStatus,
)


def life_transitions_for_round(
    round_item: CanonicalRound,
    participants: tuple[ParticipantRoundState, ...],
    events: tuple[TemporalEvent, ...],
    kills: tuple[CanonicalKill, ...],
) -> tuple[tuple[LifeTransition, ...], dict[UUID, PlayerLifeStatus]]:
    states = {item.player_id: item.initial_alive_status for item in participants}
    kill_by_id = {item.event_id: item for item in kills}
    transitions: list[LifeTransition] = []
    for event in events:
        if event.kind is not TemporalEventKind.DEATH or event.victim_player_id is None:
            continue
        if event.ordering_status is TemporalOrderingStatus.OUT_OF_RANGE:
            continue
        victim_id = event.victim_player_id
        before = states.get(victim_id, PlayerLifeStatus.UNKNOWN)
        kill = kill_by_id.get(event.event_id)
        classification = event.combat_death_classification or classify_death(kill)
        status = TemporalTransitionStatus.AVAILABLE
        if before is PlayerLifeStatus.DEAD:
            after = PlayerLifeStatus.DEAD
            classification = TemporalDeathClassification.REPEATED
            status = TemporalTransitionStatus.PARTIAL
        elif before in {PlayerLifeStatus.UNKNOWN, PlayerLifeStatus.NOT_PARTICIPATING}:
            after = PlayerLifeStatus.DEAD
            status = TemporalTransitionStatus.PARTIAL
        else:
            after = PlayerLifeStatus.DEAD
        if round_item.freeze_end_tick is None or event.time.tick < round_item.freeze_end_tick:
            status = TemporalTransitionStatus.PARTIAL
        states[victim_id] = after
        transitions.append(
            LifeTransition(
                transition_id=uuid5(
                    round_item.round_id,
                    f"temporal:life:{event.event_id}:{victim_id}",
                ),
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                time=event.time,
                event_id=event.event_id,
                player_id=victim_id,
                before=before,
                after=after,
                death_classification=classification,
                killer_player_id=event.actor_player_id,
                source=event.source_event,
                status=status,
            )
        )
    return tuple(transitions), states


def classify_death(kill: CanonicalKill | None) -> TemporalDeathClassification:
    """Classify canonical combat semantics independently of temporal life state."""
    if kill is None:
        return TemporalDeathClassification.UNKNOWN
    if kill.is_suicide is True or kill.attacker_player_id == kill.victim_player_id:
        return TemporalDeathClassification.SUICIDE
    if kill.attacker_player_id is None:
        return TemporalDeathClassification.WORLD
    if kill.is_teamkill is True or (
        kill.attacker_team_id is not None and kill.attacker_team_id == kill.victim_team_id
    ):
        return TemporalDeathClassification.TEAMKILL
    if (
        kill.attacker_team_id is not None
        and kill.victim_team_id is not None
        and kill.attacker_team_id != kill.victim_team_id
    ):
        return TemporalDeathClassification.ENEMY
    return TemporalDeathClassification.UNKNOWN
