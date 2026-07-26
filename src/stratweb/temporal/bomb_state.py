"""Conservative bomb state machine for canonical plant/defuse/explode events."""

from __future__ import annotations

from uuid import uuid5

from stratweb.application.canonical_models import CanonicalRound

from .definitions import first_available_tick, temporal_time
from .models import (
    BombState,
    BombTransition,
    TemporalConfig,
    TemporalEvent,
    TemporalEventKind,
    TemporalOrderingStatus,
    TemporalTransitionStatus,
)


def bomb_transitions_for_round(
    round_item: CanonicalRound,
    events: tuple[TemporalEvent, ...],
    config: TemporalConfig,
) -> tuple[tuple[BombTransition, ...], BombState]:
    state = BombState.UNAVAILABLE
    transitions: list[BombTransition] = []
    terminal_seen: set[str] = set()
    for event in events:
        if event.kind is not TemporalEventKind.BOMB or not event.state_affecting:
            continue
        if event.ordering_status is TemporalOrderingStatus.OUT_OF_RANGE:
            continue
        event_type = event.event_type.removeprefix("bomb:")
        before = state
        status = TemporalTransitionStatus.AVAILABLE
        if event_type == "planted":
            if state in {BombState.UNAVAILABLE}:
                after = BombState.PLANTED
            else:
                after = BombState.UNRESOLVED
                status = TemporalTransitionStatus.UNRESOLVED
        elif event_type == "defused":
            terminal_seen.add(event_type)
            if state is BombState.PLANTED and "exploded" not in terminal_seen:
                after = BombState.DEFUSED
            else:
                after = BombState.UNRESOLVED
                status = TemporalTransitionStatus.UNRESOLVED
        elif event_type == "exploded":
            terminal_seen.add(event_type)
            if state is BombState.PLANTED and "defused" not in terminal_seen:
                after = BombState.EXPLODED
            else:
                after = BombState.UNRESOLVED
                status = TemporalTransitionStatus.UNRESOLVED
        else:
            continue
        if len(terminal_seen) > 1:
            after = BombState.UNRESOLVED
            status = TemporalTransitionStatus.UNRESOLVED
        state = after
        transitions.append(
            BombTransition(
                transition_id=uuid5(
                    round_item.round_id,
                    f"temporal:bomb:{event.event_id}:{event_type}",
                ),
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                time=event.time,
                event_id=event.event_id,
                before=before,
                after=after,
                actor_player_id=event.actor_player_id,
                physical_team_id=event.physical_team_id,
                side=event.side,
                site_raw=event.site_raw,
                source=event.source_event,
                status=status,
            )
        )

    effective_end = first_available_tick(round_item.official_end_tick, round_item.end_tick)
    if state is BombState.PLANTED and effective_end is not None:
        after = BombState.ROUND_ENDED_BEFORE_RESOLUTION
        transitions.append(
            BombTransition(
                transition_id=uuid5(
                    round_item.round_id,
                    f"temporal:bomb:round_end:{effective_end}",
                ),
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                time=temporal_time(effective_end, config),
                before=state,
                after=after,
                source=round_item.end_source or "canonical:effective_end",
                status=TemporalTransitionStatus.PARTIAL,
            )
        )
        state = after
    return tuple(transitions), state
