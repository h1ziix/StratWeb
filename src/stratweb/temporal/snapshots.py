"""Replay immutable temporal transitions into point-in-time snapshots."""

from __future__ import annotations

from uuid import UUID

from stratweb.domain.enums import Side

from .definitions import temporal_time
from .models import (
    BombState,
    FinalStateStatus,
    GroupStateProjection,
    IntermediateStateStatus,
    ParticipationStatus,
    PlayerLifeStatus,
    RoundSnapshot,
    RoundTimeline,
    SimultaneousEventGroup,
    SimultaneousOrderingStatus,
    SnapshotStateStatus,
    TemporalConfig,
    TemporalEvent,
    TemporalOrderingStatus,
    TemporalUnavailableReason,
)
from .ordering import temporal_event_key
from .phases import phase_at_tick


class SnapshotBuilder:
    def at_tick(
        self,
        timeline: RoundTimeline,
        tick: int,
        config: TemporalConfig,
    ) -> RoundSnapshot:
        self._validate_tick(timeline, tick)
        events = tuple(event for event in timeline.ordered_events if event.time.tick <= tick)
        affected = tuple(group for group in timeline.simultaneous_groups if group.tick <= tick)
        unresolved = next(
            (
                group
                for group in affected
                if group.final_state_status
                in {FinalStateStatus.AMBIGUOUS, FinalStateStatus.CONFLICTING}
            ),
            None,
        )
        current = next((group for group in affected if group.tick == tick), None)
        return self._build(
            timeline,
            tick,
            events,
            config,
            ambiguity_flags=(
                ("simultaneous_event_order",)
                if current is not None
                and current.ordering_status
                in {
                    SimultaneousOrderingStatus.AMBIGUOUS_ORDER,
                    SimultaneousOrderingStatus.CONFLICTING,
                }
                else ()
            ),
            state_status=(
                SnapshotStateStatus.UNAVAILABLE if unresolved else SnapshotStateStatus.AVAILABLE
            ),
            tick_group=current,
            unavailable_reasons=(
                (TemporalUnavailableReason.CONFLICTING_EVENTS,) if unresolved else ()
            ),
        )

    def before_tick_group(
        self, timeline: RoundTimeline, group_id: UUID, config: TemporalConfig
    ) -> RoundSnapshot:
        group = self._group(timeline, group_id)
        events = tuple(event for event in timeline.ordered_events if event.time.tick < group.tick)
        return self._build(
            timeline, group.tick, events, config, ambiguity_flags=(), tick_group=group
        )

    def after_tick_group(
        self, timeline: RoundTimeline, group_id: UUID, config: TemporalConfig
    ) -> RoundSnapshot:
        group = self._group(timeline, group_id)
        return self.at_tick(timeline, group.tick, config)

    def before_event(
        self,
        timeline: RoundTimeline,
        event_id: UUID,
        config: TemporalConfig,
    ) -> RoundSnapshot:
        target = self._event(timeline, event_id)
        group = self._event_group(timeline, target)
        if (
            group is not None
            and group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
        ):
            events = tuple(
                event for event in timeline.ordered_events if event.time.tick < target.time.tick
            )
            return self._build(
                timeline,
                target.time.tick,
                events,
                config,
                ambiguity_flags=("ambiguous_same_tick_order",),
                state_status=(
                    SnapshotStateStatus.AMBIGUOUS
                    if group.intermediate_state_status is IntermediateStateStatus.AMBIGUOUS
                    else SnapshotStateStatus.UNAVAILABLE
                ),
                tick_group=group,
                possible_states=group.possible_intermediate_states,
                unavailable_reasons=(TemporalUnavailableReason.AMBIGUOUS_SAME_TICK_ORDER,),
            )
        key = temporal_event_key(target)
        events = tuple(
            event for event in timeline.ordered_events if temporal_event_key(event) < key
        )
        flags = (
            ("simultaneous_event_order",)
            if target.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS
            else ()
        )
        return self._build(timeline, target.time.tick, events, config, flags)

    def after_event(
        self,
        timeline: RoundTimeline,
        event_id: UUID,
        config: TemporalConfig,
    ) -> RoundSnapshot:
        target = self._event(timeline, event_id)
        group = self._event_group(timeline, target)
        if (
            group is not None
            and group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
        ):
            events = tuple(
                event for event in timeline.ordered_events if event.time.tick < target.time.tick
            )
            return self._build(
                timeline,
                target.time.tick,
                events,
                config,
                ambiguity_flags=("ambiguous_same_tick_order",),
                state_status=(
                    SnapshotStateStatus.AMBIGUOUS
                    if group.intermediate_state_status is IntermediateStateStatus.AMBIGUOUS
                    else SnapshotStateStatus.UNAVAILABLE
                ),
                tick_group=group,
                possible_states=group.possible_intermediate_states,
                unavailable_reasons=(TemporalUnavailableReason.AMBIGUOUS_SAME_TICK_ORDER,),
            )
        key = temporal_event_key(target)
        events = tuple(
            event for event in timeline.ordered_events if temporal_event_key(event) <= key
        )
        flags = (
            ("simultaneous_event_order",)
            if target.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS
            else ()
        )
        return self._build(timeline, target.time.tick, events, config, flags)

    def final(self, timeline: RoundTimeline, config: TemporalConfig) -> RoundSnapshot:
        if timeline.effective_end_tick is None:
            raise ValueError("round has no effective end tick")
        return self.at_tick(timeline, timeline.effective_end_tick, config)

    @staticmethod
    def _validate_tick(timeline: RoundTimeline, tick: int) -> None:
        if tick < 0:
            raise ValueError("snapshot tick cannot be negative")
        if timeline.start_tick is not None and tick < timeline.start_tick:
            raise ValueError("snapshot tick is before round start")
        if timeline.effective_end_tick is not None and tick > timeline.effective_end_tick:
            raise ValueError("snapshot tick is after effective round end")

    @staticmethod
    def _event(timeline: RoundTimeline, event_id: UUID) -> TemporalEvent:
        event = next((item for item in timeline.ordered_events if item.event_id == event_id), None)
        if event is None:
            raise KeyError(f"temporal event not found: {event_id}")
        return event

    @staticmethod
    def _group(timeline: RoundTimeline, group_id: UUID) -> SimultaneousEventGroup:
        group = next(
            (item for item in timeline.simultaneous_groups if item.group_id == group_id), None
        )
        if group is None:
            raise KeyError(f"simultaneous event group not found: {group_id}")
        return group

    @staticmethod
    def _event_group(
        timeline: RoundTimeline, event: TemporalEvent
    ) -> SimultaneousEventGroup | None:
        if event.simultaneous_group_id is None:
            return None
        return next(
            (
                item
                for item in timeline.simultaneous_groups
                if item.group_id == event.simultaneous_group_id
            ),
            None,
        )

    @staticmethod
    def _build(
        timeline: RoundTimeline,
        tick: int,
        events: tuple[TemporalEvent, ...],
        config: TemporalConfig,
        ambiguity_flags: tuple[str, ...],
        state_status: SnapshotStateStatus = SnapshotStateStatus.AVAILABLE,
        tick_group: SimultaneousEventGroup | None = None,
        possible_states: tuple[GroupStateProjection, ...] = (),
        unavailable_reasons: tuple[TemporalUnavailableReason, ...] = (),
    ) -> RoundSnapshot:
        life = {item.player_id: item.initial_alive_status for item in timeline.participants}
        participant_by_id = {item.player_id: item for item in timeline.participants}
        life_by_event = {item.event_id: item for item in timeline.life_transitions}
        bomb_by_event = {
            item.event_id: item for item in timeline.bomb_transitions if item.event_id is not None
        }
        bomb_state = BombState.UNAVAILABLE
        processed = []
        flags = set(ambiguity_flags)
        for event in events:
            processed.append(event)
            if event.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS:
                flags.add("simultaneous_event_order")
            if life_transition := life_by_event.get(event.event_id):
                life[life_transition.player_id] = life_transition.after
            if bomb_transition := bomb_by_event.get(event.event_id):
                bomb_state = bomb_transition.after
        for terminal_bomb_transition in timeline.bomb_transitions:
            if (
                terminal_bomb_transition.event_id is None
                and terminal_bomb_transition.time.tick <= tick
            ):
                bomb_state = terminal_bomb_transition.after

        participating = tuple(
            sorted(
                (
                    item.player_id
                    for item in timeline.participants
                    if item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
                ),
                key=str,
            )
        )
        alive = tuple(
            sorted((pid for pid in participating if life[pid] is PlayerLifeStatus.ALIVE), key=str)
        )
        dead = tuple(
            sorted((pid for pid in participating if life[pid] is PlayerLifeStatus.DEAD), key=str)
        )
        unknown = tuple(
            sorted(
                (
                    pid
                    for pid in participating
                    if life[pid] in {PlayerLifeStatus.UNKNOWN, PlayerLifeStatus.NOT_PARTICIPATING}
                ),
                key=str,
            )
        )
        team_counts: dict[UUID, int] = {}
        for player_id in alive:
            team_id = participant_by_id[player_id].physical_team_id
            if team_id is not None:
                team_counts[team_id] = team_counts.get(team_id, 0) + 1
        last_tick = max((item.time.tick for item in processed), default=None)
        last_ids = tuple(item.event_id for item in processed if item.time.tick == last_tick)
        return RoundSnapshot(
            match_id=timeline.match_id,
            round_id=timeline.round_id,
            round_number=timeline.round_number,
            time=temporal_time(tick, config),
            phase=phase_at_tick(timeline.phase_intervals, tick),
            participants=participating,
            alive_players=alive,
            dead_players=dead,
            unknown_players=unknown,
            t_alive=sum(participant_by_id[player_id].side is Side.T for player_id in alive),
            ct_alive=sum(participant_by_id[player_id].side is Side.CT for player_id in alive),
            team_alive_counts=dict(sorted(team_counts.items(), key=lambda item: str(item[0]))),
            bomb_state=bomb_state,
            last_event_ids=last_ids,
            availability=timeline.availability,
            state_status=state_status,
            tick_group_id=tick_group.group_id if tick_group else None,
            post_group_state_deterministic=(
                tick_group.post_group_snapshot_deterministic if tick_group else None
            ),
            possible_states=possible_states,
            unavailable_reasons=unavailable_reasons,
            # A point-in-time snapshot must not inherit ambiguity from a future tick.
            # Flags are accumulated only from events actually replayed (plus the
            # target event for before/after queries).
            ambiguity_flags=tuple(sorted(flags)),
        )
