"""Pure deterministic Temporal Round State Engine 1.1."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid5

from pydantic import JsonValue

from stratweb.application.canonical_models import CanonicalRound, ValidationSeverity
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.exceptions import TemporalConfigurationError

from .alive_state import life_transitions_for_round
from .bomb_state import bomb_transitions_for_round
from .definitions import (
    aggregate_capabilities,
    capability,
    first_available_tick,
    temporal_config_hash,
    temporal_time,
)
from .groups import classify_simultaneous_groups
from .models import (
    TEMPORAL_RULE_VERSION,
    TEMPORAL_SCHEMA_VERSION,
    BombState,
    BombTransition,
    DeathEffectStatus,
    FinalStateStatus,
    IntermediateStateStatus,
    LifeTransition,
    ParticipantRoundState,
    ParticipationStatus,
    PhaseInterval,
    PlayerLifeStatus,
    RoundPhase,
    RoundTimeline,
    SimultaneousEventGroup,
    SimultaneousOrderingStatus,
    TemporalAvailability,
    TemporalAvailabilityStatus,
    TemporalConfig,
    TemporalEvent,
    TemporalEventKind,
    TemporalMatchInput,
    TemporalMatchState,
    TemporalOrderingStatus,
    TemporalSummary,
    TemporalTransition,
    TemporalTransitionStatus,
    TemporalTransitionType,
    TemporalUnavailableReason,
    TemporalValidationIssue,
)
from .ordering import ordered_temporal_events
from .participants import participants_for_round, participating_states
from .phases import build_phase_intervals
from .snapshots import SnapshotBuilder
from .validation import TemporalValidator


class TemporalEngine:
    """Build immutable timelines without parser, persistence, clocks or randomness."""

    def compute(
        self,
        data: TemporalMatchInput,
        config: TemporalConfig | None = None,
    ) -> TemporalMatchState:
        selected_config = config or TemporalConfig()
        if selected_config.conflicting_tickrate_sources:
            sources = ", ".join(
                sorted(
                    {
                        *(selected_config.conflicting_tickrate_sources),
                        *(
                            (selected_config.tickrate_source,)
                            if selected_config.tickrate_source
                            else ()
                        ),
                    }
                )
            )
            raise TemporalConfigurationError(
                f"Temporal seconds conversion has conflicting tickrate sources: {sources}."
            )

        rounds = tuple(
            sorted(
                (item for item in data.rounds if not item.is_warmup),
                key=lambda item: (item.round_number, str(item.round_id)),
            )
        )
        timelines = tuple(
            self._timeline(round_item, data, selected_config) for round_item in rounds
        )
        availability = _aggregate_availability(timelines)
        summary = TemporalSummary(
            rounds=len(timelines),
            complete_rounds=sum(item.complete for item in timelines),
            total_temporal_events=sum(len(item.ordered_events) for item in timelines),
            total_transitions=sum(len(item.state_transitions) for item in timelines),
            life_transitions=sum(len(item.life_transitions) for item in timelines),
            bomb_transitions=sum(len(item.bomb_transitions) for item in timelines),
            participant_states=sum(len(item.participants) for item in timelines),
            ambiguity_groups=sum(len(item.simultaneous_groups) for item in timelines),
            ambiguous_order_groups=sum(
                group.ordering_status is SimultaneousOrderingStatus.AMBIGUOUS_ORDER
                for item in timelines
                for group in item.simultaneous_groups
            ),
            ambiguous_intermediate_groups=sum(
                group.intermediate_state_status is IntermediateStateStatus.AMBIGUOUS
                for item in timelines
                for group in item.simultaneous_groups
            ),
            ambiguous_final_groups=sum(
                group.final_state_status is FinalStateStatus.AMBIGUOUS
                for item in timelines
                for group in item.simultaneous_groups
            ),
            conflicting_groups=sum(
                group.final_state_status is FinalStateStatus.CONFLICTING
                for item in timelines
                for group in item.simultaneous_groups
            ),
            death_events_without_victim=sum(
                event.death_effect_status is DeathEffectStatus.UNAVAILABLE
                for item in timelines
                for event in item.ordered_events
            ),
            availability=availability,
        )
        issues = tuple(issue for timeline in timelines for issue in timeline.validation_issues)
        warnings = _warnings(availability, issues)
        config_digest = temporal_config_hash(selected_config)
        provisional = TemporalMatchState(
            temporal_schema_version=TEMPORAL_SCHEMA_VERSION,
            temporal_rule_version=TEMPORAL_RULE_VERSION,
            temporal_config_hash=config_digest,
            temporal_fingerprint="0" * 64,
            temporal_run_id=UUID(int=0),
            match_id=data.match_id,
            dataset_fingerprint=data.dataset_fingerprint,
            config=selected_config,
            timelines=timelines,
            summary=summary,
            validation_issues=issues,
            warnings=warnings,
        )
        fingerprint = compute_temporal_fingerprint(provisional)
        return provisional.model_copy(
            update={
                "temporal_fingerprint": fingerprint,
                "temporal_run_id": uuid5(data.match_id, f"temporal:{fingerprint}"),
            }
        )

    def _timeline(
        self,
        round_item: CanonicalRound,
        data: TemporalMatchInput,
        config: TemporalConfig,
    ) -> RoundTimeline:
        events = ordered_temporal_events(
            round_item,
            kills=data.kills,
            damages=data.damages,
            shots=data.shots,
            grenades=data.grenades,
            bomb_events=data.bomb_events,
            config=config,
        )
        participants = participants_for_round(
            round_item,
            players=data.players,
            memberships=data.memberships,
            kills=data.kills,
            damages=data.damages,
            shots=data.shots,
            grenades=data.grenades,
            bomb_events=data.bomb_events,
        )
        phases = build_phase_intervals(round_item)
        life, _ = life_transitions_for_round(round_item, participants, events, data.kills)
        bomb, final_bomb = bomb_transitions_for_round(round_item, events, config)
        events, groups = classify_simultaneous_groups(events, participants, life, bomb)
        bomb, final_bomb = _localize_bomb_group_conflict(
            round_item, groups, bomb, final_bomb, config
        )
        availability = _round_availability(
            round_item, participants, events, groups, phases, life, bomb, config
        )
        ambiguity_flags = tuple(
            sorted(
                {
                    "simultaneous_event_order"
                    for event in events
                    if event.ordering_status is TemporalOrderingStatus.SIMULTANEOUS_AMBIGUOUS
                }
            )
        )
        transitions = _normalized_transitions(
            round_item,
            participants,
            phases,
            events,
            life,
            bomb,
            config,
        )
        provisional = RoundTimeline(
            match_id=round_item.match_id,
            round_id=round_item.round_id,
            round_number=round_item.round_number,
            start_tick=round_item.start_tick,
            freeze_end_tick=round_item.freeze_end_tick,
            live_start_tick=round_item.freeze_end_tick,
            end_tick=round_item.end_tick,
            official_end_tick=round_item.official_end_tick,
            effective_end_tick=first_available_tick(
                round_item.official_end_tick, round_item.end_tick
            ),
            end_source=round_item.end_source,
            complete=round_item.is_complete,
            overtime=round_item.is_overtime,
            participants=participants,
            ordered_events=events,
            simultaneous_groups=groups,
            phase_intervals=phases,
            state_transitions=transitions,
            life_transitions=life,
            bomb_transitions=bomb,
            final_bomb_state=final_bomb,
            availability=availability,
            validation_issues=tuple(issue for group in groups for issue in group.validation_issues),
            ambiguity_flags=ambiguity_flags,
        )
        final_snapshot = None
        if provisional.effective_end_tick is not None and (
            provisional.start_tick is None
            or provisional.effective_end_tick >= provisional.start_tick
        ):
            final_snapshot = SnapshotBuilder().final(provisional, config)
        issues = (
            *provisional.validation_issues,
            *TemporalValidator().validate(provisional, final_snapshot),
        )
        return provisional.model_copy(update={"validation_issues": issues})


def compute_temporal_fingerprint(state: TemporalMatchState) -> str:
    payload = state.model_dump(mode="json", exclude={"temporal_fingerprint", "temporal_run_id"})
    payload["derived_milestone_snapshots"] = _milestone_snapshots(state)
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def _localize_bomb_group_conflict(
    round_item: CanonicalRound,
    groups: tuple[SimultaneousEventGroup, ...],
    transitions: tuple[BombTransition, ...],
    final_state: BombState,
    config: TemporalConfig,
) -> tuple[tuple[BombTransition, ...], BombState]:
    unresolved = next(
        (
            group
            for group in groups
            if TemporalEventKind.BOMB in group.involved_event_families
            and group.final_state_status
            in {FinalStateStatus.AMBIGUOUS, FinalStateStatus.CONFLICTING}
        ),
        None,
    )
    if unresolved is None or final_state is BombState.UNRESOLVED:
        return transitions, final_state
    transition = BombTransition(
        transition_id=uuid5(
            round_item.round_id,
            f"temporal:bomb:simultaneous-unresolved:{unresolved.group_id}",
        ),
        match_id=round_item.match_id,
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        time=temporal_time(unresolved.tick, config),
        before=final_state,
        after=BombState.UNRESOLVED,
        source=f"simultaneous_group:{unresolved.group_id}",
        status=TemporalTransitionStatus.UNRESOLVED,
    )
    return (*transitions, transition), BombState.UNRESOLVED


def _milestone_snapshots(state: TemporalMatchState) -> list[dict[str, JsonValue]]:
    builder = SnapshotBuilder()
    result: list[dict[str, JsonValue]] = []
    for timeline in state.timelines:
        ticks = (
            ("round_start", timeline.start_tick),
            ("freeze_end", timeline.freeze_end_tick),
            ("final", timeline.effective_end_tick),
        )
        for label, tick in ticks:
            if tick is None:
                continue
            if timeline.start_tick is not None and tick < timeline.start_tick:
                continue
            if timeline.effective_end_tick is not None and tick > timeline.effective_end_tick:
                continue
            snapshot = builder.at_tick(timeline, tick, state.config)
            result.append(
                {
                    "label": label,
                    "round_id": str(timeline.round_id),
                    "snapshot": snapshot.model_dump(mode="json"),
                }
            )
    return result


def _round_availability(
    round_item: CanonicalRound,
    participants: tuple[ParticipantRoundState, ...],
    events: tuple[TemporalEvent, ...],
    groups: tuple[SimultaneousEventGroup, ...],
    phases: tuple[PhaseInterval, ...],
    life: tuple[LifeTransition, ...],
    bomb: tuple[BombTransition, ...],
    config: TemporalConfig,
) -> TemporalAvailability:
    boundary_reasons: list[TemporalUnavailableReason] = []
    effective_end = first_available_tick(round_item.official_end_tick, round_item.end_tick)
    boundary_invalid = any(
        (left is not None and right is not None and left > right)
        for left, right in (
            (round_item.start_tick, round_item.freeze_end_tick),
            (round_item.freeze_end_tick, effective_end),
            (round_item.end_tick, round_item.official_end_tick),
        )
    )
    boundary_covered = int(round_item.start_tick is not None and effective_end is not None)
    if not boundary_covered:
        boundary_reasons.append(TemporalUnavailableReason.MISSING_ROUND_BOUNDARY)
    if not round_item.is_complete:
        boundary_reasons.append(TemporalUnavailableReason.INCOMPLETE_ROUND)
    if boundary_invalid:
        boundary_reasons.append(TemporalUnavailableReason.SOURCE_CONFLICT)
    out_of_range = any(
        event.ordering_status is TemporalOrderingStatus.OUT_OF_RANGE for event in events
    )
    if out_of_range:
        boundary_reasons.append(TemporalUnavailableReason.OUT_OF_RANGE_EVENTS)
    tick_timeline = capability(1, boundary_covered, boundary_reasons, unresolved=boundary_invalid)
    seconds_timeline = (
        capability(1, 1)
        if config.tickrate is not None
        else capability(1, 0, (TemporalUnavailableReason.MISSING_TICKRATE,))
    )
    phase_covered = int(
        round_item.start_tick is not None
        and round_item.freeze_end_tick is not None
        and bool(phases)
        and boundary_covered
    )
    phase_timeline = capability(
        1,
        phase_covered,
        (
            (TemporalUnavailableReason.SOURCE_CONFLICT,)
            if boundary_invalid
            else (() if phase_covered else (TemporalUnavailableReason.MISSING_ROUND_BOUNDARY,))
        ),
        unresolved=boundary_invalid,
    )
    participating = participating_states(participants)
    participant_covered = sum(
        item.participation_status is not ParticipationStatus.UNRESOLVED
        and item.physical_team_id is not None
        and item.side in {Side.T, Side.CT}
        for item in participating
    )
    unresolved_participant = any(
        item.participation_status is ParticipationStatus.UNRESOLVED for item in participating
    )
    participant_reasons: tuple[TemporalUnavailableReason, ...]
    if participant_covered == len(participating) and participating:
        participant_reasons = ()
    elif unresolved_participant:
        participant_reasons = (TemporalUnavailableReason.SOURCE_CONFLICT,)
    else:
        participant_reasons = (TemporalUnavailableReason.MISSING_PARTICIPANTS,)
    participant_state = capability(
        max(1, len(participating)),
        participant_covered,
        participant_reasons,
        unresolved=unresolved_participant,
    )
    known_initial = sum(
        item.initial_alive_status is PlayerLifeStatus.ALIVE for item in participating
    )
    alive_reasons: list[TemporalUnavailableReason] = []
    if known_initial != len(participating) or not participating:
        alive_reasons.append(TemporalUnavailableReason.MISSING_PARTICIPANTS)
    if any(item.status is not TemporalTransitionStatus.AVAILABLE for item in life):
        alive_reasons.append(TemporalUnavailableReason.SOURCE_CONFLICT)
    if out_of_range:
        alive_reasons.append(TemporalUnavailableReason.OUT_OF_RANGE_EVENTS)
    unresolved_life = any(
        group.final_state_status in {FinalStateStatus.AMBIGUOUS, FinalStateStatus.CONFLICTING}
        and any(family is TemporalEventKind.DEATH for family in group.involved_event_families)
        for group in groups
    )
    victimless_deaths = sum(
        event.death_effect_status is DeathEffectStatus.UNAVAILABLE for event in events
    )
    if unresolved_life:
        alive_reasons.append(TemporalUnavailableReason.CONFLICTING_EVENTS)
    elif victimless_deaths:
        alive_reasons.append(TemporalUnavailableReason.DEATH_EFFECT_UNAVAILABLE)
    alive_state = capability(
        max(1, len(participating)),
        known_initial,
        alive_reasons,
        unresolved=unresolved_life,
    )
    deterministic_groups = sum(
        group.final_state_status is FinalStateStatus.DETERMINISTIC for group in groups
    )
    unresolved_groups = any(
        group.final_state_status in {FinalStateStatus.AMBIGUOUS, FinalStateStatus.CONFLICTING}
        for group in groups
    )
    tick_group_state = (
        capability(
            max(1, len(groups)),
            deterministic_groups,
            (TemporalUnavailableReason.CONFLICTING_EVENTS,) if unresolved_groups else (),
            unresolved=unresolved_groups,
        )
        if groups
        else capability(1, 1)
    )
    ambiguous_intermediate = sum(
        group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
        for group in groups
    )
    per_event_state = capability(
        max(1, len(events)),
        max(
            0,
            len(events)
            - sum(
                group.event_count
                for group in groups
                if group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
            ),
        ),
        (TemporalUnavailableReason.AMBIGUOUS_SAME_TICK_ORDER,) if ambiguous_intermediate else (),
    )
    intermediate_ordering = (
        capability(
            max(1, len(groups)),
            sum(
                group.intermediate_state_status is IntermediateStateStatus.DETERMINISTIC
                for group in groups
            ),
            (TemporalUnavailableReason.AMBIGUOUS_SAME_TICK_ORDER,)
            if ambiguous_intermediate
            else (),
        )
        if groups
        else capability(1, 1)
    )
    bomb_reasons = [TemporalUnavailableReason.UNSUPPORTED_BOMB_SEMANTICS]
    if any(item.after is BombState.UNRESOLVED for item in bomb):
        bomb_reasons.append(TemporalUnavailableReason.CONFLICTING_EVENTS)
    bomb_state = capability(1, int(bool(bomb)), bomb_reasons, unresolved=len(bomb_reasons) > 1)
    final_reasons = list(boundary_reasons)
    if not participating:
        final_reasons.append(TemporalUnavailableReason.MISSING_PARTICIPANTS)
    final_unresolved = (
        unresolved_participant
        or unresolved_groups
        or any(item.after is BombState.UNRESOLVED for item in bomb)
    )
    if final_unresolved:
        final_reasons.append(TemporalUnavailableReason.CONFLICTING_EVENTS)
    final_state = capability(
        1,
        int(boundary_covered and bool(participating)),
        final_reasons,
        unresolved=final_unresolved or boundary_invalid,
    )
    return TemporalAvailability(
        tick_timeline=tick_timeline,
        seconds_timeline=seconds_timeline,
        phase_timeline=phase_timeline,
        participant_state=participant_state,
        alive_state=alive_state,
        bomb_state=bomb_state,
        final_state=final_state,
        tick_group_state=tick_group_state,
        per_event_state=per_event_state,
        intermediate_ordering=intermediate_ordering,
        final_alive_state=alive_state,
    )


def _normalized_transitions(
    round_item: CanonicalRound,
    participants: tuple[ParticipantRoundState, ...],
    phases: tuple[PhaseInterval, ...],
    events: tuple[TemporalEvent, ...],
    life: tuple[LifeTransition, ...],
    bomb: tuple[BombTransition, ...],
    config: TemporalConfig,
) -> tuple[TemporalTransition, ...]:
    values: list[TemporalTransition] = []

    def add(
        tick: int,
        transition_type: TemporalTransitionType,
        source: str,
        before: dict[str, JsonValue],
        after: dict[str, JsonValue],
        *,
        event_id: UUID | None = None,
        status: TemporalTransitionStatus = TemporalTransitionStatus.AVAILABLE,
        ordinal: int = 0,
    ) -> None:
        transition_id = uuid5(
            round_item.round_id,
            f"temporal:transition:{tick}:{transition_type.value}:{event_id}:{ordinal}",
        )
        values.append(
            TemporalTransition(
                transition_id=transition_id,
                match_id=round_item.match_id,
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                time=temporal_time(tick, config),
                event_id=event_id,
                transition_type=transition_type,
                before_state=before,
                after_state=after,
                source=source,
                status=status,
            )
        )

    previous_phase = RoundPhase.PRESTART
    for index, interval in enumerate(phases):
        add(
            interval.start_tick,
            TemporalTransitionType.PHASE_CHANGED,
            interval.start_source,
            {"phase": previous_phase.value},
            {"phase": interval.phase.value},
            ordinal=index,
        )
        previous_phase = interval.phase
    for index, participant in enumerate(participants):
        if participant.participation_status is not ParticipationStatus.EVENT_OBSERVED:
            continue
        tick = first_available_tick(participant.first_seen_tick, round_item.start_tick)
        if tick is None:
            continue
        add(
            tick,
            TemporalTransitionType.PARTICIPANT_OBSERVED,
            ",".join(participant.participation_sources) or "canonical:event",
            {"participation": ParticipationStatus.NOT_PARTICIPATING.value},
            {
                "participation": participant.participation_status.value,
                "player_id": str(participant.player_id),
            },
            ordinal=index,
            status=TemporalTransitionStatus.PARTIAL,
        )
    for index, life_item in enumerate(life):
        add(
            life_item.time.tick,
            TemporalTransitionType.PLAYER_DIED,
            life_item.source,
            {"life": life_item.before.value},
            {
                "life": life_item.after.value,
                "player_id": str(life_item.player_id),
            },
            event_id=life_item.event_id,
            status=life_item.status,
            ordinal=index,
        )
    bomb_types = {
        BombState.PLANTED: TemporalTransitionType.BOMB_PLANTED,
        BombState.DEFUSED: TemporalTransitionType.BOMB_DEFUSED,
        BombState.EXPLODED: TemporalTransitionType.BOMB_EXPLODED,
    }
    for index, bomb_item in enumerate(bomb):
        transition_type = bomb_types.get(bomb_item.after)
        if transition_type is None:
            if bomb_item.after is BombState.ROUND_ENDED_BEFORE_RESOLUTION:
                transition_type = TemporalTransitionType.ROUND_ENDED
            else:
                transition_type = TemporalTransitionType.AMBIGUITY_DETECTED
        add(
            bomb_item.time.tick,
            transition_type,
            bomb_item.source,
            {"bomb": bomb_item.before.value},
            {"bomb": bomb_item.after.value},
            event_id=bomb_item.event_id,
            status=bomb_item.status,
            ordinal=index,
        )
    groups: dict[UUID, TemporalEvent] = {}
    for event in events:
        if event.simultaneous_group_id is not None:
            groups.setdefault(event.simultaneous_group_id, event)
    for index, (group_id, event) in enumerate(
        sorted(groups.items(), key=lambda item: str(item[0]))
    ):
        add(
            event.time.tick,
            TemporalTransitionType.AMBIGUITY_DETECTED,
            "temporal:simultaneous_group",
            {},
            {"simultaneous_group_id": str(group_id)},
            event_id=event.event_id,
            status=TemporalTransitionStatus.UNRESOLVED,
            ordinal=index,
        )
    effective_end = first_available_tick(round_item.official_end_tick, round_item.end_tick)
    if effective_end is not None:
        add(
            effective_end,
            TemporalTransitionType.ROUND_ENDED,
            round_item.end_source or "canonical:effective_end",
            {"round": "active"},
            {"round": "ended"},
            ordinal=len(values),
        )
    return tuple(
        sorted(
            values,
            key=lambda item: (
                item.time.tick,
                item.transition_type.value,
                str(item.transition_id),
            ),
        )
    )


def _aggregate_availability(
    timelines: tuple[RoundTimeline, ...],
) -> TemporalAvailability:
    names = (
        "tick_timeline",
        "seconds_timeline",
        "phase_timeline",
        "participant_state",
        "alive_state",
        "bomb_state",
        "final_state",
        "tick_group_state",
        "per_event_state",
        "intermediate_ordering",
        "final_alive_state",
    )
    values = {
        name: aggregate_capabilities(getattr(timeline.availability, name) for timeline in timelines)
        for name in names
    }
    return TemporalAvailability(**values)


def _warnings(
    availability: TemporalAvailability,
    issues: tuple[TemporalValidationIssue, ...],
) -> tuple[str, ...]:
    warnings = []
    for name, value in availability:
        if value.status is not TemporalAvailabilityStatus.AVAILABLE:
            reasons = ",".join(reason.value for reason in value.reasons)
            warnings.append(f"{name}:{value.status.value}:{reasons}")
    warnings.extend(
        f"validation:{issue.code}"
        for issue in issues
        if issue.severity is ValidationSeverity.WARNING
    )
    return tuple(dict.fromkeys(warnings))
