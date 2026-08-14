"""Immutable contracts for persisted, versioned spatial-to-zone assignments."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.maps.models import MapLevel, MapSelectionStatus
from stratweb.spatial.models import SpatialAvailabilityStatus
from stratweb.zones.models import ZoneKind

ZONE_ASSIGNMENT_SCHEMA_VERSION = "1.0.0"
ZONE_ASSIGNMENT_RULE_VERSION = "snapshot_point_to_zone_v1"


class ZoneAssignmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ZoneAssignmentStatus(StrEnum):
    RESOLVED = "resolved"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class ZoneAssignmentComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class ZoneAssignmentConfig(ZoneAssignmentModel):
    """Explicit policy switches that are part of the deterministic fingerprint."""

    allow_unproven_map_revision: bool = True


class ZoneAssignmentCapability(ZoneAssignmentModel):
    status: SpatialAvailabilityStatus
    population: int = Field(ge=0)
    resolved: int = Field(ge=0)
    unknown: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> ZoneAssignmentCapability:
        if self.resolved + self.unknown + self.unavailable != self.population:
            raise ValueError("zone assignment capability counts must equal population")
        return self


class ZoneAssignmentSummary(ZoneAssignmentModel):
    snapshots: int = Field(ge=0)
    rounds: int = Field(ge=0)
    participants: int = Field(ge=0)
    position_available: int = Field(ge=0)
    resolved: int = Field(ge=0)
    unknown: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    coverage: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_counts(self) -> ZoneAssignmentSummary:
        if self.resolved + self.unknown + self.unavailable != self.snapshots:
            raise ValueError("zone assignment summary counts must equal snapshots")
        if self.position_available > self.snapshots:
            raise ValueError("position_available cannot exceed snapshots")
        expected = self.resolved / self.position_available if self.position_available > 0 else None
        if expected is None and self.coverage is not None:
            raise ValueError("coverage must be unknown when no positions are available")
        if expected is not None and (
            self.coverage is None or abs(self.coverage - expected) > 1e-12
        ):
            raise ValueError("coverage must equal resolved / position_available")
        return self


class ZoneAssignment(ZoneAssignmentModel):
    assignment_id: UUID
    zone_assignment_run_id: UUID
    spatial_run_id: UUID
    spatial_snapshot_id: UUID
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    participant_id: UUID
    status: ZoneAssignmentStatus
    zone_id: str | None = None
    zone_name: str | None = None
    kind: ZoneKind | None = None
    level: MapLevel | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_resolution(self) -> ZoneAssignment:
        resolved_fields = (self.zone_id, self.zone_name, self.kind, self.level)
        if self.status is ZoneAssignmentStatus.RESOLVED and any(
            item is None for item in resolved_fields
        ):
            raise ValueError("resolved zone assignment requires complete zone identity")
        if self.status is not ZoneAssignmentStatus.RESOLVED and any(
            item is not None for item in resolved_fields
        ):
            raise ValueError("unknown or unavailable assignment cannot claim a zone")
        return self


class ZoneAssignmentState(ZoneAssignmentModel):
    zone_assignment_schema_version: str = ZONE_ASSIGNMENT_SCHEMA_VERSION
    zone_assignment_rule_version: str = ZONE_ASSIGNMENT_RULE_VERSION
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    zone_assignment_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_schema_version: str
    spatial_rule_version: str
    canonical_map_name: str | None = None
    selected_map_revision: str | None = None
    map_definition_fingerprint: Sha256 | None = None
    map_revision_selection_status: MapSelectionStatus | None = None
    zone_set_fingerprint: Sha256 | None = None
    zone_set_key: str
    zone_schema_version: str | None = None
    zone_resolution_rule_version: str | None = None
    zone_validation_rule_version: str | None = None
    config: ZoneAssignmentConfig
    capability: ZoneAssignmentCapability
    summary: ZoneAssignmentSummary
    assignments: tuple[ZoneAssignment, ...]
    warnings: tuple[str, ...] = ()


class ZoneAssignmentRunSummary(ZoneAssignmentModel):
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    zone_assignment_schema_version: str
    zone_assignment_rule_version: str
    zone_assignment_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_schema_version: str
    spatial_rule_version: str
    canonical_map_name: str | None = None
    selected_map_revision: str | None = None
    map_definition_fingerprint: Sha256 | None = None
    map_revision_selection_status: MapSelectionStatus | None = None
    zone_set_fingerprint: Sha256 | None = None
    zone_set_key: str
    zone_schema_version: str | None = None
    zone_resolution_rule_version: str | None = None
    zone_validation_rule_version: str | None = None
    config: ZoneAssignmentConfig
    capability: ZoneAssignmentCapability
    summary: ZoneAssignmentSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


class ZoneAssignmentRunRecord(ZoneAssignmentModel):
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    match_id: UUID
    spatial_run_id: UUID
    zone_assignment_schema_version: str
    zone_assignment_rule_version: str
    zone_set_fingerprint: Sha256 | None = None
    canonical_map_name: str | None = None
    selected_map_revision: str | None = None
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class ZoneAssignmentSaveResult(ZoneAssignmentModel):
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    status: ZoneAssignmentComputeStatus
    row_counts: dict[str, int]


class ZoneAssignmentComputeResult(ZoneAssignmentModel):
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    zone_assignment_schema_version: str
    zone_assignment_rule_version: str
    match_id: UUID
    spatial_run_id: UUID
    status: ZoneAssignmentComputeStatus
    capability: ZoneAssignmentCapability
    summary: ZoneAssignmentSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


class DeleteZoneAssignmentsResult(ZoneAssignmentModel):
    match_id: UUID
    deleted: bool
    deleted_runs: int = Field(ge=0)


__all__ = [
    "ZONE_ASSIGNMENT_RULE_VERSION",
    "ZONE_ASSIGNMENT_SCHEMA_VERSION",
    "DeleteZoneAssignmentsResult",
    "ZoneAssignment",
    "ZoneAssignmentCapability",
    "ZoneAssignmentComputeResult",
    "ZoneAssignmentComputeStatus",
    "ZoneAssignmentConfig",
    "ZoneAssignmentRunRecord",
    "ZoneAssignmentRunSummary",
    "ZoneAssignmentSaveResult",
    "ZoneAssignmentState",
    "ZoneAssignmentStatus",
    "ZoneAssignmentSummary",
]
