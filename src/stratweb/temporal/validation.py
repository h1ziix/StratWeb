"""Independent structural validation and optional Stage 5 consistency checks."""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from stratweb.analytics.models import ManAdvantageTransition, OpeningDuel
from stratweb.application.canonical_models import EventPhase, ValidationSeverity
from stratweb.domain.enums import Side

from .models import (
    BombState,
    ParticipationStatus,
    PlayerLifeStatus,
    RoundSnapshot,
    RoundTimeline,
    TemporalDeathClassification,
    TemporalOrderingStatus,
    TemporalValidationIssue,
)
from .ordering import temporal_event_key


class TemporalValidator:
    def validate(
        self, timeline: RoundTimeline, final_snapshot: RoundSnapshot | None = None
    ) -> tuple[TemporalValidationIssue, ...]:
        issues: list[TemporalValidationIssue] = []
        keys = [temporal_event_key(item) for item in timeline.ordered_events]
        if keys != sorted(keys):
            issues.append(_fatal("nondeterministic_event_order", timeline.round_id))
        event_counts = Counter(item.event_id for item in timeline.ordered_events)
        if any(count > 1 for count in event_counts.values()):
            issues.append(_fatal("duplicate_temporal_event_id", timeline.round_id))

        intervals = timeline.phase_intervals
        if any(item.end_tick is not None and item.end_tick < item.start_tick for item in intervals):
            issues.append(_fatal("invalid_phase_interval", timeline.round_id))
        for previous, current in zip(intervals, intervals[1:], strict=False):
            if previous.end_tick is None or current.start_tick < previous.end_tick:
                issues.append(_fatal("overlapping_phase_intervals", timeline.round_id))
                break
        if (
            timeline.live_start_tick is not None
            and timeline.effective_end_tick is not None
            and timeline.live_start_tick > timeline.effective_end_tick
        ):
            issues.append(_fatal("live_start_after_effective_end", timeline.round_id))

        if any(
            item.ordering_status is TemporalOrderingStatus.OUT_OF_RANGE
            for item in timeline.ordered_events
        ):
            issues.append(
                _warning(
                    "out_of_range_temporal_events",
                    timeline.round_id,
                    "Canonical events exist outside proven round boundaries.",
                )
            )
        if any(
            item.victim_player_id is None
            for item in timeline.ordered_events
            if item.event_type == "death"
        ):
            issues.append(
                _warning(
                    "death_without_victim",
                    timeline.round_id,
                    "A death event has no canonical victim identity.",
                )
            )
        participant_ids = {item.player_id for item in timeline.participants}
        if any(
            item.victim_player_id is not None and item.victim_player_id not in participant_ids
            for item in timeline.ordered_events
            if item.event_type == "death"
        ):
            issues.append(_fatal("death_victim_missing_from_participants", timeline.round_id))
        if timeline.live_start_tick is not None and any(
            item.time.tick < timeline.live_start_tick for item in timeline.life_transitions
        ):
            issues.append(
                _warning(
                    "death_before_live_start",
                    timeline.round_id,
                    "A canonical death precedes the proven live boundary; "
                    "life coverage is partial.",
                )
            )
        if any(
            item.death_classification is TemporalDeathClassification.REPEATED
            for item in timeline.life_transitions
        ):
            issues.append(
                _warning(
                    "duplicate_death_without_respawn",
                    timeline.round_id,
                    "A player died repeatedly without an authoritative respawn.",
                )
            )
        life_state = {item.player_id: item.initial_alive_status for item in timeline.participants}
        life_ticks: list[int] = []
        for transition in timeline.life_transitions:
            life_ticks.append(transition.time.tick)
            if (
                life_state.get(transition.player_id, PlayerLifeStatus.UNKNOWN)
                is not transition.before
                or transition.after is not PlayerLifeStatus.DEAD
            ):
                issues.append(_fatal("impossible_life_transition", timeline.round_id))
                break
            life_state[transition.player_id] = transition.after
        if life_ticks != sorted(life_ticks):
            issues.append(_fatal("unordered_life_transitions", timeline.round_id))
        if any(
            item.participation_status is ParticipationStatus.UNRESOLVED
            for item in timeline.participants
        ):
            issues.append(
                _warning(
                    "participant_identity_conflict",
                    timeline.round_id,
                    "Participant physical-team or side evidence conflicts.",
                )
            )
        if any(item.after is BombState.UNRESOLVED for item in timeline.bomb_transitions):
            issues.append(
                _warning(
                    "bomb_state_conflict",
                    timeline.round_id,
                    "Bomb event sequence is unresolved.",
                )
            )

        if final_snapshot is not None:
            expected_dead = {
                item.player_id
                for item in timeline.life_transitions
                if item.after is PlayerLifeStatus.DEAD
            }
            if not expected_dead.issubset(set(final_snapshot.dead_players)):
                issues.append(_fatal("final_life_state_mismatch", timeline.round_id))
            if final_snapshot.bomb_state is not timeline.final_bomb_state:
                issues.append(_fatal("final_bomb_state_mismatch", timeline.round_id))
        return tuple(sorted(issues, key=lambda item: (item.code, item.entity_id or "")))

    def cross_check_analytics(
        self,
        timeline: RoundTimeline,
        *,
        opening: OpeningDuel | None,
        advantages: tuple[ManAdvantageTransition, ...],
    ) -> tuple[TemporalValidationIssue, ...]:
        issues: list[TemporalValidationIssue] = []
        # Stage 5 opening/advantage eligibility is live-phase only. Pre-live
        # temporal deaths remain as partial evidence, but comparing them to an
        # analytics stream that intentionally excludes them is a false mismatch.
        live_death_ids = {
            item.event_id
            for item in timeline.ordered_events
            if item.event_type == "death"
            and item.canonical_phase is EventPhase.LIVE
            and item.ordering_status is not TemporalOrderingStatus.OUT_OF_RANGE
        }
        first_enemy = next(
            (
                item
                for item in timeline.ordered_events
                if item.combat_death_classification is TemporalDeathClassification.ENEMY
                and item.event_id in live_death_ids
            ),
            None,
        )
        if (opening is None) != (first_enemy is None) or (
            opening is not None
            and first_enemy is not None
            and first_enemy.event_id != opening.event_id
        ):
            issues.append(_fatal("stage5_opening_mismatch", timeline.round_id))
        temporal_deaths = tuple(
            item.event_id for item in timeline.life_transitions if item.event_id in live_death_ids
        )
        analytic_deaths = tuple(item.event_id for item in advantages)
        if temporal_deaths != analytic_deaths:
            issues.append(_fatal("stage5_advantage_death_stream_mismatch", timeline.round_id))
            return tuple(issues)

        # Compare only authoritative post-tick states. Stage 5 serializes events
        # inside a tick for reproducibility; Temporal 1.1 does not treat those
        # intermediate counts as physical truth.
        participant_by_id = {item.player_id: item for item in timeline.participants}
        alive = {
            Side.T: sum(
                item.side is Side.T and item.initial_alive_status is PlayerLifeStatus.ALIVE
                for item in timeline.participants
            ),
            Side.CT: sum(
                item.side is Side.CT and item.initial_alive_status is PlayerLifeStatus.ALIVE
                for item in timeline.participants
            ),
        }
        event_by_id = {item.event_id: item for item in timeline.ordered_events}
        live_dead: set[UUID] = set()
        temporal_post_tick: dict[int, tuple[int, int]] = {}
        for event_id in temporal_deaths:
            death_event = event_by_id[event_id]
            victim_id = death_event.victim_player_id
            participant = participant_by_id.get(victim_id) if victim_id is not None else None
            if participant is not None and victim_id is not None and victim_id not in live_dead:
                live_dead.add(victim_id)
                if participant.side in {Side.T, Side.CT}:
                    alive[participant.side] = max(0, alive[participant.side] - 1)
            temporal_post_tick[death_event.time.tick] = (alive[Side.T], alive[Side.CT])
        analytic_post_tick: dict[int, tuple[int, int]] = {}
        for analytic_transition in advantages:
            analytic_post_tick[analytic_transition.tick] = (
                analytic_transition.t_alive_after,
                analytic_transition.ct_alive_after,
            )
        if temporal_post_tick != analytic_post_tick:
            issues.append(_fatal("stage5_advantage_post_tick_mismatch", timeline.round_id))
        return tuple(issues)


def _fatal(code: str, entity_id: UUID) -> TemporalValidationIssue:
    return TemporalValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        is_fatal=True,
        entity_type="round_timeline",
        entity_id=str(entity_id),
        message=code.replace("_", " ").capitalize() + ".",
    )


def _warning(code: str, entity_id: UUID, message: str) -> TemporalValidationIssue:
    return TemporalValidationIssue(
        code=code,
        severity=ValidationSeverity.WARNING,
        entity_type="round_timeline",
        entity_id=str(entity_id),
        message=message,
    )
