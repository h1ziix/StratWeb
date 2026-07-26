"""Application services joining canonical persistence to temporal state."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from uuid import UUID

from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalShot,
)
from stratweb.exceptions import (
    MatchNotFoundError,
    TemporalIntegrityError,
    TemporalNotFoundError,
    TemporalSnapshotError,
)
from stratweb.ports import AnalyticsRepository, MatchRepository, TemporalRepository
from stratweb.temporal.engine import TemporalEngine
from stratweb.temporal.models import (
    BombTransition,
    DeleteTemporalResult,
    ParticipantRoundState,
    RoundSnapshot,
    RoundTimeline,
    SimultaneousEventGroup,
    TemporalComputeResult,
    TemporalConfig,
    TemporalEvent,
    TemporalMatchInput,
    TemporalRunRecord,
    TemporalRunSummary,
    TemporalTransition,
    TemporalValidationIssue,
)
from stratweb.temporal.snapshots import SnapshotBuilder
from stratweb.temporal.validation import TemporalValidator


class ComputeTemporalStateService:
    def __init__(
        self,
        match_repository: MatchRepository,
        temporal_repository: TemporalRepository,
        *,
        analytics_repository: AnalyticsRepository | None = None,
        engine: TemporalEngine | None = None,
    ) -> None:
        self._matches = match_repository
        self._temporal = temporal_repository
        self._analytics = analytics_repository
        self._engine = engine or TemporalEngine()

    def compute(
        self,
        match_id: UUID,
        *,
        config: TemporalConfig | None = None,
        replace: bool = False,
    ) -> TemporalComputeResult:
        started = perf_counter()
        source = self._load_input(match_id)
        result = self._engine.compute(source, config)
        fatal = tuple(issue for issue in result.validation_issues if issue.is_fatal)
        if fatal:
            codes = ", ".join(sorted({item.code for item in fatal}))
            raise TemporalIntegrityError(
                f"Temporal validation found structural contradictions: {codes}."
            )
        self._cross_check_analytics(result.timelines)
        saved = self._temporal.save_temporal(result, replace=replace)
        return TemporalComputeResult(
            match_id=match_id,
            dataset_fingerprint=source.dataset_fingerprint,
            temporal_fingerprint=saved.temporal_fingerprint,
            temporal_run_id=saved.temporal_run_id,
            temporal_schema_version=result.temporal_schema_version,
            temporal_rule_version=result.temporal_rule_version,
            temporal_config_hash=result.temporal_config_hash,
            status=saved.status,
            row_counts=saved.row_counts,
            config=result.config,
            capability_summary=result.summary.availability,
            warnings=result.warnings,
            duration_seconds=perf_counter() - started,
        )

    def _load_input(self, match_id: UUID) -> TemporalMatchInput:
        match = self._matches.get_match(match_id)
        if match is None:
            raise MatchNotFoundError(f"Canonical match not found: {match_id}")
        rounds = self._matches.get_rounds(match_id)
        kills: list[CanonicalKill] = []
        damages: list[CanonicalDamage] = []
        shots: list[CanonicalShot] = []
        grenades: list[CanonicalGrenade] = []
        bomb_events: list[CanonicalBombEvent] = []
        for round_item in rounds:
            events = self._matches.get_round_events(match_id, round_item.round_number)
            if events is None:
                continue
            kills.extend(events.kills)
            damages.extend(events.damages)
            shots.extend(events.shots)
            grenades.extend(events.grenades)
            bomb_events.extend(events.bomb_events)
        return TemporalMatchInput(
            match_id=match_id,
            dataset_fingerprint=match.dataset_fingerprint,
            teams=tuple(
                sorted(self._matches.get_teams(match_id), key=lambda item: str(item.team_id))
            ),
            players=tuple(
                sorted(self._matches.get_players(match_id), key=lambda item: str(item.player_id))
            ),
            memberships=tuple(
                sorted(
                    self._matches.get_memberships(match_id),
                    key=lambda item: (
                        item.valid_from_tick,
                        item.valid_to_tick if item.valid_to_tick is not None else 2**63 - 1,
                        str(item.player_id),
                        str(item.team_id),
                    ),
                )
            ),
            rounds=tuple(sorted(rounds, key=lambda item: (item.round_number, str(item.round_id)))),
            kills=tuple(sorted(kills, key=_event_key)),
            damages=tuple(sorted(damages, key=_event_key)),
            shots=tuple(sorted(shots, key=_event_key)),
            grenades=tuple(sorted(grenades, key=_event_key)),
            bomb_events=tuple(sorted(bomb_events, key=_event_key)),
        )

    def _cross_check_analytics(self, timelines: tuple[RoundTimeline, ...]) -> None:
        if self._analytics is None or not timelines:
            return
        if self._analytics.get_summary(timelines[0].match_id) is None:
            return
        validator = TemporalValidator()
        mismatches: list[TemporalValidationIssue] = []
        openings = {
            item.round_number: item
            for item in self._analytics.list_opening_duels(timelines[0].match_id)
        }
        for timeline in timelines:
            if (
                self._analytics.get_round_analytics(timeline.match_id, timeline.round_number)
                is None
            ):
                continue
            advantages = self._analytics.get_man_advantage_timeline(
                timeline.match_id, timeline.round_number
            )
            mismatches.extend(
                validator.cross_check_analytics(
                    timeline,
                    opening=openings.get(timeline.round_number),
                    advantages=advantages,
                )
            )
        if mismatches:
            codes = ", ".join(sorted({item.code for item in mismatches}))
            raise TemporalIntegrityError(f"Stage 5 temporal cross-check failed: {codes}.")


class TemporalQueryService:
    def __init__(self, repository: TemporalRepository) -> None:
        self._repository = repository

    def get_match_temporal_summary(self, match_id: UUID) -> TemporalRunSummary:
        result = self._repository.get_summary(match_id)
        if result is None:
            raise TemporalNotFoundError(f"Temporal run not found for match: {match_id}")
        return result

    def list_temporal_runs(self, match_id: UUID) -> tuple[TemporalRunRecord, ...]:
        result = self._repository.list_runs(match_id)
        if not result:
            raise TemporalNotFoundError(f"Temporal run not found for match: {match_id}")
        return result

    def get_temporal_run_summary(
        self, match_id: UUID, temporal_run_id: UUID | None = None
    ) -> TemporalRunSummary:
        if temporal_run_id is None:
            return self.get_match_temporal_summary(match_id)
        result = self._repository.get_summary_for_run(match_id, temporal_run_id)
        if result is None:
            raise TemporalNotFoundError(
                f"Compatible temporal run not found for match {match_id}: {temporal_run_id}"
            )
        return result

    def get_round_timeline(
        self,
        match_id: UUID,
        round_number: int,
        temporal_run_id: UUID | None = None,
    ) -> RoundTimeline:
        self.get_temporal_run_summary(match_id, temporal_run_id)
        result = (
            self._repository.get_round_timeline(match_id, round_number)
            if temporal_run_id is None
            else self._repository.get_round_timeline_for_run(
                match_id, temporal_run_id, round_number
            )
        )
        if result is None:
            raise TemporalNotFoundError(
                f"Temporal round not found for match {match_id}: {round_number}"
            )
        return result

    def get_group_snapshot_before(
        self,
        match_id: UUID,
        round_number: int,
        group_id: UUID,
        temporal_run_id: UUID | None = None,
    ) -> RoundSnapshot:
        timeline = self.get_round_timeline(match_id, round_number, temporal_run_id)
        return self._snapshot_for_run(
            lambda builder, config: builder.before_tick_group(timeline, group_id, config),
            match_id,
            temporal_run_id,
        )

    def get_group_snapshot_after(
        self,
        match_id: UUID,
        round_number: int,
        group_id: UUID,
        temporal_run_id: UUID | None = None,
    ) -> RoundSnapshot:
        timeline = self.get_round_timeline(match_id, round_number, temporal_run_id)
        return self._snapshot_for_run(
            lambda builder, config: builder.after_tick_group(timeline, group_id, config),
            match_id,
            temporal_run_id,
        )

    def get_event_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        event_id: UUID,
        temporal_run_id: UUID | None = None,
    ) -> tuple[RoundSnapshot, RoundSnapshot]:
        timeline = self.get_round_timeline(match_id, round_number, temporal_run_id)
        before = self._snapshot_for_run(
            lambda builder, config: builder.before_event(timeline, event_id, config),
            match_id,
            temporal_run_id,
        )
        after = self._snapshot_for_run(
            lambda builder, config: builder.after_event(timeline, event_id, config),
            match_id,
            temporal_run_id,
        )
        return before, after

    def get_tick_snapshot(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        temporal_run_id: UUID | None = None,
    ) -> RoundSnapshot:
        timeline = self.get_round_timeline(match_id, round_number, temporal_run_id)
        return self._snapshot_for_run(
            lambda builder, config: builder.at_tick(timeline, tick, config),
            match_id,
            temporal_run_id,
        )

    def get_round_events(self, match_id: UUID, round_number: int) -> tuple[TemporalEvent, ...]:
        self.get_round_timeline(match_id, round_number)
        return self._repository.list_round_events(match_id, round_number)

    def get_round_transitions(
        self, match_id: UUID, round_number: int
    ) -> tuple[TemporalTransition, ...]:
        self.get_round_timeline(match_id, round_number)
        return self._repository.list_round_transitions(match_id, round_number)

    def get_simultaneous_groups(
        self, match_id: UUID, round_number: int | None = None
    ) -> tuple[SimultaneousEventGroup, ...]:
        self.get_match_temporal_summary(match_id)
        return self._repository.list_simultaneous_groups(match_id, round_number)

    def get_simultaneous_group(self, match_id: UUID, group_id: UUID) -> SimultaneousEventGroup:
        self.get_match_temporal_summary(match_id)
        result = self._repository.get_simultaneous_group(match_id, group_id)
        if result is None:
            raise TemporalNotFoundError(
                f"Simultaneous event group not found for match {match_id}: {group_id}"
            )
        return result

    def get_round_participants(
        self, match_id: UUID, round_number: int
    ) -> tuple[ParticipantRoundState, ...]:
        self.get_round_timeline(match_id, round_number)
        return self._repository.list_round_participants(match_id, round_number)

    def get_snapshot(self, match_id: UUID, round_number: int, tick: int) -> RoundSnapshot:
        timeline = self.get_round_timeline(match_id, round_number)
        return self._snapshot(
            lambda builder, config: builder.at_tick(timeline, tick, config), match_id
        )

    def get_snapshot_before_event(self, match_id: UUID, event_id: UUID) -> RoundSnapshot:
        found = self._repository.find_event(match_id, event_id)
        if found is None:
            raise TemporalNotFoundError(
                f"Temporal event not found for match {match_id}: {event_id}"
            )
        round_number, _ = found
        timeline = self.get_round_timeline(match_id, round_number)
        return self._snapshot(
            lambda builder, config: builder.before_event(timeline, event_id, config),
            match_id,
        )

    def get_snapshot_after_event(self, match_id: UUID, event_id: UUID) -> RoundSnapshot:
        found = self._repository.find_event(match_id, event_id)
        if found is None:
            raise TemporalNotFoundError(
                f"Temporal event not found for match {match_id}: {event_id}"
            )
        round_number, _ = found
        timeline = self.get_round_timeline(match_id, round_number)
        return self._snapshot(
            lambda builder, config: builder.after_event(timeline, event_id, config),
            match_id,
        )

    def get_final_snapshot(
        self,
        match_id: UUID,
        round_number: int,
        temporal_run_id: UUID | None = None,
    ) -> RoundSnapshot:
        timeline = self.get_round_timeline(match_id, round_number, temporal_run_id)
        return self._snapshot_for_run(
            lambda builder, config: builder.final(timeline, config),
            match_id,
            temporal_run_id,
        )

    def get_bomb_timeline(self, match_id: UUID, round_number: int) -> tuple[BombTransition, ...]:
        self.get_round_timeline(match_id, round_number)
        return self._repository.list_bomb_transitions(match_id, round_number)

    def delete_temporal(self, match_id: UUID) -> DeleteTemporalResult:
        summary = self._repository.get_summary(match_id)
        return DeleteTemporalResult(
            temporal_fingerprint=(summary.temporal_fingerprint if summary is not None else None),
            deleted=self._repository.delete_temporal(match_id),
        )

    def _snapshot(
        self,
        operation: Callable[[SnapshotBuilder, TemporalConfig], RoundSnapshot],
        match_id: UUID,
    ) -> RoundSnapshot:
        config = self.get_match_temporal_summary(match_id).config
        try:
            return operation(SnapshotBuilder(), config)
        except (KeyError, ValueError) as exc:
            raise TemporalSnapshotError(str(exc)) from exc

    def _snapshot_for_run(
        self,
        operation: Callable[[SnapshotBuilder, TemporalConfig], RoundSnapshot],
        match_id: UUID,
        temporal_run_id: UUID | None,
    ) -> RoundSnapshot:
        config = self.get_temporal_run_summary(match_id, temporal_run_id).config
        try:
            return operation(SnapshotBuilder(), config)
        except (KeyError, ValueError) as exc:
            raise TemporalSnapshotError(str(exc)) from exc


def _event_key(
    item: CanonicalKill | CanonicalDamage | CanonicalShot | CanonicalGrenade | CanonicalBombEvent,
) -> tuple[int, int, str]:
    return item.round_number if item.round_number is not None else -1, item.tick, str(item.event_id)
