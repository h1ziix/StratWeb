"""Application services for deterministic, version-pinned zone assignments."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.exceptions import (
    SpatialNotFoundError,
    ZoneAssignmentConfigurationError,
    ZoneAssignmentNotFoundError,
)
from stratweb.ports import SpatialRepository, ZoneAssignmentRepository
from stratweb.spatial.models import (
    SPATIAL_RULE_VERSION,
    SPATIAL_SCHEMA_VERSION,
    SpatialSnapshot,
)
from stratweb.zones.assignment_models import (
    ZONE_ASSIGNMENT_RULE_VERSION,
    ZONE_ASSIGNMENT_SCHEMA_VERSION,
    DeleteZoneAssignmentsResult,
    ZoneAssignment,
    ZoneAssignmentComputeResult,
    ZoneAssignmentConfig,
    ZoneAssignmentRunRecord,
    ZoneAssignmentRunSummary,
    ZoneAssignmentStatus,
)
from stratweb.zones.assignments import ZoneAssignmentEngine
from stratweb.zones.definitions import zone_set_for


class ComputeZoneAssignmentsService:
    def __init__(
        self,
        spatial_repository: SpatialRepository,
        zone_repository: ZoneAssignmentRepository,
        *,
        engine: ZoneAssignmentEngine | None = None,
        page_size: int = 20_000,
    ) -> None:
        self._spatial = spatial_repository
        self._zones = zone_repository
        self._engine = engine or ZoneAssignmentEngine()
        self._page_size = page_size

    def compute(
        self,
        match_id: UUID,
        *,
        spatial_run_id: UUID | None = None,
        config: ZoneAssignmentConfig | None = None,
        replace: bool = False,
    ) -> ZoneAssignmentComputeResult:
        started = perf_counter()
        spatial = (
            self._spatial.get_summary_for_run(match_id, spatial_run_id)
            if spatial_run_id is not None
            else self._spatial.get_summary(match_id)
        )
        if spatial is None:
            raise SpatialNotFoundError(f"Spatial run not found for match: {match_id}")
        if (spatial.spatial_schema_version, spatial.spatial_rule_version) != (
            SPATIAL_SCHEMA_VERSION,
            SPATIAL_RULE_VERSION,
        ):
            raise ZoneAssignmentConfigurationError(
                "Zone assignment requires an exact compatible current Spatial run."
            )
        snapshots: list[SpatialSnapshot] = []
        offset = 0
        while True:
            page = self._spatial.list_snapshots(
                match_id,
                limit=self._page_size,
                offset=offset,
                spatial_run_id=spatial.spatial_run_id,
            )
            snapshots.extend(page)
            if len(page) < self._page_size:
                break
            offset += len(page)
        semantics = spatial.map_semantics
        zone_set = (
            zone_set_for(semantics.canonical_name, semantics.selected_map_revision)
            if semantics is not None
            and semantics.canonical_name is not None
            and semantics.selected_map_revision is not None
            else None
        )
        state = self._engine.compute(spatial, snapshots, zone_set, config or ZoneAssignmentConfig())
        saved = self._zones.save_zone_assignments(state, replace=replace)
        return ZoneAssignmentComputeResult(
            zone_assignment_run_id=saved.zone_assignment_run_id,
            zone_assignment_fingerprint=saved.zone_assignment_fingerprint,
            zone_assignment_schema_version=ZONE_ASSIGNMENT_SCHEMA_VERSION,
            zone_assignment_rule_version=ZONE_ASSIGNMENT_RULE_VERSION,
            match_id=match_id,
            spatial_run_id=spatial.spatial_run_id,
            status=saved.status,
            capability=state.capability,
            summary=state.summary,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )


class ZoneAssignmentQueryService:
    def __init__(self, repository: ZoneAssignmentRepository) -> None:
        self._repository = repository

    def get_summary(
        self, match_id: UUID, *, spatial_run_id: UUID | None = None
    ) -> ZoneAssignmentRunSummary:
        value = (
            self._repository.get_summary_for_spatial_run(match_id, spatial_run_id)
            if spatial_run_id is not None
            else self._repository.get_summary(match_id)
        )
        if value is None:
            raise ZoneAssignmentNotFoundError(
                f"Zone assignment run not found for match: {match_id}"
            )
        return value

    def list_runs(self, match_id: UUID) -> tuple[ZoneAssignmentRunRecord, ...]:
        return self._repository.list_runs(match_id)

    def list_assignments(
        self,
        match_id: UUID,
        *,
        zone_assignment_run_id: UUID | None = None,
        round_number: int | None = None,
        status: ZoneAssignmentStatus | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[ZoneAssignment, ...]:
        if zone_assignment_run_id is None:
            self.get_summary(match_id)
        elif self._repository.get_summary_for_run(match_id, zone_assignment_run_id) is None:
            raise ZoneAssignmentNotFoundError(
                f"Zone assignment run not found for match: {match_id}"
            )
        return self._repository.list_assignments(
            match_id,
            zone_assignment_run_id=zone_assignment_run_id,
            round_number=round_number,
            status=status,
            limit=limit,
            offset=offset,
        )

    def delete(self, match_id: UUID) -> DeleteZoneAssignmentsResult:
        runs = self._repository.delete_zone_assignments(match_id)
        return DeleteZoneAssignmentsResult(match_id=match_id, deleted=runs > 0, deleted_runs=runs)


__all__ = ["ComputeZoneAssignmentsService", "ZoneAssignmentQueryService"]
