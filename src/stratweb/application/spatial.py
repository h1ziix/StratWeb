"""Application services connecting spatial extraction, Temporal state, and persistence."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from uuid import UUID

from stratweb.exceptions import (
    MatchNotFoundError,
    SpatialConfigurationError,
    SpatialIntegrityError,
    SpatialNotFoundError,
    TemporalNotFoundError,
)
from stratweb.ports import (
    MatchRepository,
    SpatialExtractor,
    SpatialRepository,
    TemporalRepository,
)
from stratweb.spatial.engine import SpatialEngine
from stratweb.spatial.models import (
    SPATIAL_RULE_VERSION,
    SPATIAL_SCHEMA_VERSION,
    BombPositionSnapshot,
    DeleteSpatialResult,
    SpatialComputeResult,
    SpatialConfig,
    SpatialMatchInput,
    SpatialRunRecord,
    SpatialRunSummary,
    SpatialSnapshot,
    SpatialTickTarget,
    SpatialValidationIssue,
)
from stratweb.temporal.models import (
    TEMPORAL_RULE_VERSION,
    TEMPORAL_SCHEMA_VERSION,
    RoundTimeline,
)


class ComputeSpatialStateService:
    def __init__(
        self,
        match_repository: MatchRepository,
        temporal_repository: TemporalRepository,
        spatial_repository: SpatialRepository,
        extractor: SpatialExtractor,
        *,
        engine: SpatialEngine | None = None,
    ) -> None:
        self._matches = match_repository
        self._temporal = temporal_repository
        self._spatial = spatial_repository
        self._extractor = extractor
        self._engine = engine or SpatialEngine()

    def compute(
        self,
        match_id: UUID,
        demo_path: Path,
        *,
        config: SpatialConfig | None = None,
        replace: bool = False,
    ) -> SpatialComputeResult:
        started = perf_counter()
        resolved = config or SpatialConfig()
        match = self._matches.get_match(match_id)
        if match is None:
            raise MatchNotFoundError(f"Canonical match not found: {match_id}")
        temporal = self._temporal.get_summary(match_id)
        if temporal is None:
            raise TemporalNotFoundError(f"Temporal run not found for match: {match_id}")
        if (temporal.temporal_schema_version, temporal.temporal_rule_version) != (
            TEMPORAL_SCHEMA_VERSION,
            TEMPORAL_RULE_VERSION,
        ):
            raise SpatialConfigurationError(
                "Spatial Engine requires an exact compatible Temporal 1.1 run."
            )
        timelines = tuple(
            self._require_timeline(match_id, temporal.temporal_run_id, round_number)
            for round_number in range(1, temporal.summary.rounds + 1)
        )
        targets = _sampling_targets(timelines, resolved)
        extraction = self._extractor.extract(
            demo_path,
            tuple(item.tick for item in targets),
            expected_sha256=match.source_demo_sha256,
        )
        state = self._engine.compute(
            SpatialMatchInput(
                match_id=match_id,
                dataset_fingerprint=match.dataset_fingerprint,
                map_name=match.map_name or "unknown",
                temporal=temporal,
                timelines=timelines,
                players=self._matches.get_players(match_id),
                tick_targets=targets,
                extraction=extraction,
            ),
            resolved,
        )
        fatal = tuple(item for item in state.validation_issues if item.is_fatal)
        if fatal:
            codes = ", ".join(sorted({item.code for item in fatal}))
            raise SpatialIntegrityError(
                f"Spatial validation found structural contradictions: {codes}."
            )
        saved = self._spatial.save_spatial(state, replace=replace)
        return SpatialComputeResult(
            spatial_run_id=saved.spatial_run_id,
            spatial_fingerprint=saved.spatial_fingerprint,
            spatial_schema_version=SPATIAL_SCHEMA_VERSION,
            spatial_rule_version=SPATIAL_RULE_VERSION,
            match_id=match_id,
            temporal_run_id=temporal.temporal_run_id,
            status=saved.status,
            map_semantics=state.map_semantics,
            capabilities=state.capabilities,
            projectile_metadata=state.projectile_metadata,
            projectile_capabilities=state.projectile_capabilities,
            summary=state.summary,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )

    def _require_timeline(
        self, match_id: UUID, temporal_run_id: UUID, round_number: int
    ) -> RoundTimeline:
        result = self._temporal.get_round_timeline_for_run(match_id, temporal_run_id, round_number)
        if result is None:
            raise TemporalNotFoundError(
                f"Temporal round not found for match {match_id}: {round_number}"
            )
        return result


class SpatialQueryService:
    def __init__(self, repository: SpatialRepository) -> None:
        self._repository = repository

    def get_status(self, match_id: UUID) -> SpatialRunSummary:
        return self.get_summary(match_id)

    def get_summary(self, match_id: UUID) -> SpatialRunSummary:
        result = self._repository.get_summary(match_id)
        if result is None:
            raise SpatialNotFoundError(f"Spatial run not found for match: {match_id}")
        return result

    def list_runs(self, match_id: UUID) -> tuple[SpatialRunRecord, ...]:
        return self._repository.list_runs(match_id)

    def list_snapshots(
        self,
        match_id: UUID,
        *,
        round_number: int | None = None,
        participant_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[SpatialSnapshot, ...]:
        self.get_summary(match_id)
        return self._repository.list_snapshots(
            match_id,
            round_number=round_number,
            participant_id=participant_id,
            limit=limit,
            offset=offset,
        )

    def list_bomb_positions(
        self, match_id: UUID, *, round_number: int | None = None
    ) -> tuple[BombPositionSnapshot, ...]:
        self.get_summary(match_id)
        return self._repository.list_bomb_positions(match_id, round_number=round_number)

    def validate(self, match_id: UUID) -> tuple[SpatialValidationIssue, ...]:
        self.get_summary(match_id)
        return self._repository.list_validation_issues(match_id)

    def delete(self, match_id: UUID) -> DeleteSpatialResult:
        runs = self._repository.delete_spatial(match_id)
        return DeleteSpatialResult(match_id=match_id, deleted=runs > 0, deleted_runs=runs)


def _sampling_targets(
    timelines: tuple[RoundTimeline, ...], config: SpatialConfig
) -> tuple[SpatialTickTarget, ...]:
    by_tick: dict[int, SpatialTickTarget] = {}
    ordered = sorted(timelines, key=lambda item: (item.start_tick or -1, item.round_number))
    for index, timeline in enumerate(ordered):
        start = timeline.live_start_tick or timeline.start_tick
        if start is None or timeline.effective_end_tick is None:
            continue
        next_start = ordered[index + 1].start_tick if index + 1 < len(ordered) else None
        end = timeline.effective_end_tick
        if next_start is not None and end >= next_start:
            end = next_start - 1
        if end < start:
            continue
        ticks = set(range(start, end + 1, config.sampling_interval_ticks))
        if config.include_round_boundaries:
            ticks.add(start)
            ticks.add(end)
        if config.include_temporal_event_ticks:
            ticks.update(
                event.time.tick
                for event in timeline.ordered_events
                if start <= event.time.tick <= end
            )
        for tick in ticks:
            by_tick[tick] = SpatialTickTarget(
                tick=tick,
                round_id=timeline.round_id,
                round_number=timeline.round_number,
            )
    return tuple(by_tick[tick] for tick in sorted(by_tick))
