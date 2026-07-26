"""Bounded, deterministic classification of simultaneous state events."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID, uuid5

from stratweb.application.canonical_models import ValidationSeverity
from stratweb.domain.enums import Side

from .models import (
    BombState,
    BombTransition,
    DeathEffectStatus,
    FinalStateStatus,
    GroupStateProjection,
    IntermediateStateStatus,
    LifeTransition,
    ParticipantRoundState,
    ParticipationStatus,
    PlayerLifeStatus,
    SimultaneousEventGroup,
    SimultaneousOrderingStatus,
    TemporalEvent,
    TemporalEventKind,
    TemporalOrderingStatus,
    TemporalValidationIssue,
)
from .ordering import temporal_event_key

MAX_ENUMERATED_EFFECTS = 8
_ROUND_BOUNDARIES = {
    TemporalEventKind.ROUND_END,
    TemporalEventKind.OFFICIAL_END,
    TemporalEventKind.FALLBACK_END,
}


def classify_simultaneous_groups(
    events: tuple[TemporalEvent, ...],
    participants: tuple[ParticipantRoundState, ...],
    life: tuple[LifeTransition, ...],
    bomb: tuple[BombTransition, ...],
) -> tuple[tuple[TemporalEvent, ...], tuple[SimultaneousEventGroup, ...]]:
    """Annotate deaths and model every multi-event state-affecting tick."""
    transition_by_event = {item.event_id: item for item in life}
    annotated: list[TemporalEvent] = []
    for event in events:
        status = event.death_effect_status
        if event.kind is TemporalEventKind.DEATH:
            if event.ordering_status is TemporalOrderingStatus.OUT_OF_RANGE:
                status = DeathEffectStatus.OUT_OF_RANGE
            elif event.victim_player_id is None:
                status = DeathEffectStatus.UNAVAILABLE
            elif (
                transition := transition_by_event.get(event.event_id)
            ) is not None and transition.before is PlayerLifeStatus.ALIVE:
                status = DeathEffectStatus.APPLIED
            else:
                status = DeathEffectStatus.CONFLICTING
        annotated.append(event.model_copy(update={"death_effect_status": status}))

    by_tick: dict[int, list[TemporalEvent]] = defaultdict(list)
    for event in annotated:
        if (
            event.state_affecting
            and event.ordering_status is not TemporalOrderingStatus.OUT_OF_RANGE
        ):
            by_tick[event.time.tick].append(event)

    groups: list[SimultaneousEventGroup] = []
    event_groups: dict[UUID, SimultaneousEventGroup] = {}
    for _tick, values in sorted(by_tick.items()):
        if len(values) < 2:
            continue
        ordered = tuple(sorted(values, key=temporal_event_key))
        group = _classify_group(ordered, participants, life, bomb)
        groups.append(group)
        for event in ordered:
            event_groups[event.event_id] = group

    result: list[TemporalEvent] = []
    for event in annotated:
        event_group = event_groups.get(event.event_id)
        if event_group is None:
            result.append(event)
            continue
        ambiguous = event_group.ordering_status in {
            SimultaneousOrderingStatus.AMBIGUOUS_ORDER,
            SimultaneousOrderingStatus.CONFLICTING,
        }
        effect = event.death_effect_status
        if (
            event.kind is TemporalEventKind.DEATH
            and event_group.final_state_status is FinalStateStatus.CONFLICTING
        ):
            effect = DeathEffectStatus.CONFLICTING
        result.append(
            event.model_copy(
                update={
                    "simultaneous_group_id": event_group.group_id,
                    "ordering_status": (
                        TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS
                        if ambiguous
                        else event.ordering_status
                    ),
                    "death_effect_status": effect,
                }
            )
        )
    return tuple(result), tuple(groups)


def _classify_group(
    events: tuple[TemporalEvent, ...],
    participants: tuple[ParticipantRoundState, ...],
    life: tuple[LifeTransition, ...],
    bomb: tuple[BombTransition, ...],
) -> SimultaneousEventGroup:
    tick = events[0].time.tick
    group_id = uuid5(events[0].round_id, f"temporal:simultaneous:{tick}")
    pre_life = {item.player_id: item.initial_alive_status for item in participants}
    for life_transition in life:
        if life_transition.time.tick < tick:
            pre_life[life_transition.player_id] = life_transition.after
    pre_bomb = BombState.UNAVAILABLE
    for bomb_transition in bomb:
        if bomb_transition.time.tick < tick:
            pre_bomb = bomb_transition.after
    pre = _projection(pre_life, pre_bomb, participants)

    deaths = tuple(item for item in events if item.kind is TemporalEventKind.DEATH)
    bombs = tuple(item for item in events if item.kind is TemporalEventKind.BOMB)
    boundaries = tuple(item for item in events if item.kind in _ROUND_BOUNDARIES)
    known_victims = tuple(
        item.victim_player_id for item in deaths if item.victim_player_id is not None
    )
    victimless = any(item.victim_player_id is None for item in deaths)
    duplicate_victim = len(set(known_victims)) != len(known_victims)
    invalid_prestate = any(
        pre_life.get(victim, PlayerLifeStatus.UNKNOWN) is not PlayerLifeStatus.ALIVE
        for victim in known_victims
    )
    bomb_types = {item.event_type.removeprefix("bomb:") for item in bombs}

    reasons: list[str] = []
    issues: list[TemporalValidationIssue] = []
    ordering = SimultaneousOrderingStatus.AMBIGUOUS_ORDER
    intermediate = IntermediateStateStatus.AMBIGUOUS
    final = FinalStateStatus.DETERMINISTIC

    if duplicate_victim or invalid_prestate:
        ordering = SimultaneousOrderingStatus.CONFLICTING
        intermediate = IntermediateStateStatus.AMBIGUOUS
        final = FinalStateStatus.CONFLICTING
        reasons.append("duplicate_or_previously_dead_victim")
    elif {"defused", "exploded"}.issubset(bomb_types):
        ordering = SimultaneousOrderingStatus.CONFLICTING
        intermediate = IntermediateStateStatus.AMBIGUOUS
        final = FinalStateStatus.CONFLICTING
        reasons.append("incompatible_terminal_bomb_events")
    elif {"planted", "defused"}.issubset(bomb_types):
        final = FinalStateStatus.AMBIGUOUS
        reasons.append("plant_defuse_order_not_proven")
    elif len(bombs) > 1:
        ordering = SimultaneousOrderingStatus.CONFLICTING
        final = FinalStateStatus.CONFLICTING
        reasons.append("multiple_non_commutative_bomb_events")
    elif victimless:
        intermediate = IntermediateStateStatus.UNAVAILABLE
        reasons.append("death_effect_unavailable")
    elif len(deaths) > 1:
        reasons.append("commutative_deaths_unknown_order")
    elif deaths and bombs:
        reasons.append("independent_life_and_bomb_effects_unknown_order")
    elif bombs and boundaries:
        reasons.append("bomb_resolution_and_round_boundary_same_tick")
    elif (deaths or bombs) and any(
        item.kind in _ROUND_BOUNDARIES | {TemporalEventKind.PHASE_BOUNDARY} for item in events
    ):
        reasons.append("state_effect_and_boundary_order_not_proven")
    elif all(
        item.kind in _ROUND_BOUNDARIES | {TemporalEventKind.PHASE_BOUNDARY} for item in events
    ):
        ordering = SimultaneousOrderingStatus.DEFINITIVELY_ORDERED
        intermediate = IntermediateStateStatus.DETERMINISTIC
    else:
        ordering = SimultaneousOrderingStatus.CANONICALLY_GROUPED
        intermediate = IntermediateStateStatus.DETERMINISTIC

    if final in {FinalStateStatus.AMBIGUOUS, FinalStateStatus.CONFLICTING}:
        issues.append(
            TemporalValidationIssue(
                code="simultaneous_group_final_state_not_deterministic",
                severity=ValidationSeverity.WARNING,
                entity_type="simultaneous_event_group",
                entity_id=str(group_id),
                message="Same-tick state effects do not prove one post-group state.",
                evidence={"tick": tick, "event_ids": [str(item.event_id) for item in events]},
            )
        )

    post_life = dict(pre_life)
    for victim in sorted(set(known_victims), key=str):
        post_life[victim] = PlayerLifeStatus.DEAD
    post_bomb = pre_bomb
    group_bomb_transitions = [
        item for item in bomb if item.time.tick == tick and item.event_id is not None
    ]
    if group_bomb_transitions:
        post_bomb = group_bomb_transitions[-1].after
    post = (
        _projection(post_life, post_bomb, participants)
        if final is FinalStateStatus.DETERMINISTIC
        else None
    )

    possible: list[GroupStateProjection] = []
    if intermediate is IntermediateStateStatus.AMBIGUOUS and len(events) <= MAX_ENUMERATED_EFFECTS:
        for event in events:
            life_state = dict(pre_life)
            bomb_state = pre_bomb
            if event.kind is TemporalEventKind.DEATH and event.victim_player_id is not None:
                life_state[event.victim_player_id] = PlayerLifeStatus.DEAD
            candidate_bomb_transition = next(
                (item for item in group_bomb_transitions if item.event_id == event.event_id), None
            )
            if candidate_bomb_transition is not None:
                bomb_state = candidate_bomb_transition.after
            candidate = _projection(life_state, bomb_state, participants)
            if candidate not in possible:
                possible.append(candidate)
    elif intermediate is IntermediateStateStatus.AMBIGUOUS:
        intermediate = IntermediateStateStatus.UNAVAILABLE
        reasons.append("bounded_variant_limit_exceeded")

    player_ids = {
        player_id
        for event in events
        for player_id in (event.actor_player_id, event.victim_player_id)
        if player_id is not None
    }
    return SimultaneousEventGroup(
        group_id=group_id,
        match_id=events[0].match_id,
        round_id=events[0].round_id,
        round_number=events[0].round_number,
        tick=tick,
        ordered_event_ids=tuple(item.event_id for item in events),
        event_count=len(events),
        involved_player_ids=tuple(sorted(player_ids, key=str)),
        involved_event_families=tuple(sorted({item.kind for item in events}, key=str)),
        ordering_status=ordering,
        intermediate_state_status=intermediate,
        final_state_status=final,
        ambiguity_reasons=tuple(reasons),
        validation_issues=tuple(issues),
        pre_group_state=pre,
        possible_intermediate_states=tuple(possible),
        post_group_state=post,
        post_group_snapshot_deterministic=final is FinalStateStatus.DETERMINISTIC,
    )


def _projection(
    life: dict[UUID, PlayerLifeStatus],
    bomb_state: BombState,
    participants: tuple[ParticipantRoundState, ...],
) -> GroupStateProjection:
    participating = tuple(
        item
        for item in participants
        if item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
    )
    alive = tuple(
        sorted(
            (
                item.player_id
                for item in participating
                if life.get(item.player_id) is PlayerLifeStatus.ALIVE
            ),
            key=str,
        )
    )
    dead = tuple(
        sorted(
            (
                item.player_id
                for item in participating
                if life.get(item.player_id) is PlayerLifeStatus.DEAD
            ),
            key=str,
        )
    )
    unknown = tuple(
        sorted(
            (
                item.player_id
                for item in participating
                if life.get(item.player_id) not in {PlayerLifeStatus.ALIVE, PlayerLifeStatus.DEAD}
            ),
            key=str,
        )
    )
    counts: dict[UUID, int] = {}
    by_id = {item.player_id: item for item in participating}
    for player_id in alive:
        team_id = by_id[player_id].physical_team_id
        if team_id is not None:
            counts[team_id] = counts.get(team_id, 0) + 1
    return GroupStateProjection(
        alive_players=alive,
        dead_players=dead,
        unknown_players=unknown,
        t_alive=sum(by_id[player_id].side is Side.T for player_id in alive),
        ct_alive=sum(by_id[player_id].side is Side.CT for player_id in alive),
        team_alive_counts=dict(sorted(counts.items(), key=lambda item: str(item[0]))),
        bomb_state=bomb_state,
    )
