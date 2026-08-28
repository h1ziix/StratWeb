"""Immutable contracts for Spatial Engine 1.0."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from stratweb.application.canonical_models import CanonicalPlayer, Sha256, ValidationSeverity
from stratweb.domain.enums import Side
from stratweb.maps.models import MapSelectionEvidence, MapSemanticsPin
from stratweb.temporal.models import RoundTimeline, TemporalRunSummary

from .projectiles import (
    ProjectileCapabilities,
    ProjectileExtraction,
    ProjectileRunMetadata,
    ProjectileSnapshot,
    SpatialProjectile,
    UtilityEffect,
    unavailable_projectile_capabilities,
)

SPATIAL_SCHEMA_VERSION = "1.3.0"
SPATIAL_RULE_VERSION = "1.4.0"
Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpatialAvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNRELIABLE = "unreliable"


class SpatialAuthority(StrEnum):
    DEMO_ENTITY_DERIVED = "demo_entity_derived"
    TEMPORAL_AUTHORITATIVE = "temporal_authoritative"
    DERIVED = "derived"
    UNRELIABLE = "unreliable"
    UNAVAILABLE = "unavailable"


class SpatialComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class CoordinateSystem(SpatialModel):
    name: str = "source2_world_units"
    x_axis: str = "+X Source 2 world axis"
    y_axis: str = "+Y Source 2 world axis"
    z_axis: str = "+Z Source 2 vertical axis"
    unit: str = "Source 2 world unit"
    transformed: bool = False


class MapBounds(SpatialModel):
    min_x: Coordinate
    max_x: Coordinate
    min_y: Coordinate
    max_y: Coordinate
    min_z: Coordinate
    max_z: Coordinate


class MapPoint(SpatialModel):
    name: str
    x: Coordinate
    y: Coordinate
    z: Coordinate
    source: str


class SpatialMapModel(SpatialModel):
    map_name: str
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    bounds: MapBounds | None = None
    spawn_locations: tuple[MapPoint, ...] = ()
    bomb_sites: tuple[MapPoint, ...] = ()
    bounds_status: SpatialAvailabilityStatus = SpatialAvailabilityStatus.UNAVAILABLE
    spawn_locations_status: SpatialAvailabilityStatus = SpatialAvailabilityStatus.UNAVAILABLE
    bomb_sites_status: SpatialAvailabilityStatus = SpatialAvailabilityStatus.UNAVAILABLE
    warnings: tuple[str, ...] = ()


class SpatialCapability(SpatialModel):
    status: SpatialAvailabilityStatus
    authority: SpatialAuthority
    population: int = Field(ge=0)
    covered: int = Field(ge=0)
    source_fields: tuple[str, ...] = ()
    sampling_interval_ticks: int | None = Field(default=None, ge=1)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_coverage(self) -> SpatialCapability:
        if self.covered > self.population:
            raise ValueError("covered cannot exceed population")
        return self


class SpatialCapabilities(SpatialModel):
    positions: SpatialCapability
    view_angles: SpatialCapability
    bomb_positions: SpatialCapability
    map_metadata: SpatialCapability
    sampling_frequency: SpatialCapability


class SpatialConfig(SpatialModel):
    sampling_interval_ticks: int = Field(default=16, ge=1, le=4096)
    max_abs_coordinate: float = Field(default=1_000_000, gt=0, allow_inf_nan=False)
    include_round_boundaries: bool = True
    include_temporal_event_ticks: bool = True


class SpatialSourceSample(SpatialModel):
    tick: int = Field(ge=0)
    steam_id: str | None = None
    player_name: str | None = None
    x: Coordinate | None = None
    y: Coordinate | None = None
    z: Coordinate | None = None
    pitch: Coordinate | None = None
    yaw: Coordinate | None = None
    source_alive: bool | None = None
    source_team_number: int | None = None
    inventory_item_ids: tuple[int, ...] | None = None
    inventory_names: tuple[str, ...] | None = None


class SpatialExtraction(SpatialModel):
    parser_name: str
    parser_version: str
    source_demo_sha256: Sha256
    requested_ticks: tuple[int, ...]
    samples: tuple[SpatialSourceSample, ...]
    source_columns: tuple[str, ...]
    invalid_numeric_value_count: int = Field(default=0, ge=0)
    map_selection_evidence: MapSelectionEvidence | None = None
    projectiles: ProjectileExtraction = Field(default_factory=ProjectileExtraction)
    warnings: tuple[str, ...] = ()


class SpatialTickTarget(SpatialModel):
    tick: int = Field(ge=0)
    round_id: UUID
    round_number: int = Field(ge=1)


class SnapshotAvailability(SpatialModel):
    position: SpatialAvailabilityStatus
    view_angles: SpatialAvailabilityStatus
    alive_link: SpatialAvailabilityStatus
    has_bomb: SpatialAvailabilityStatus
    utility_inventory: SpatialAvailabilityStatus = SpatialAvailabilityStatus.UNAVAILABLE
    warnings: tuple[str, ...] = ()


class SpatialSnapshot(SpatialModel):
    snapshot_id: UUID
    match_id: UUID
    temporal_run_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    participant_id: UUID
    x: Coordinate | None = None
    y: Coordinate | None = None
    z: Coordinate | None = None
    yaw: Coordinate | None = None
    pitch: Coordinate | None = None
    alive: bool | None = None
    has_bomb: bool | None = None
    utility_inventory: tuple[str, ...] | None = None
    physical_team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    map_name: str
    source: str
    position_authority: SpatialAuthority
    view_angle_authority: SpatialAuthority
    alive_source: str = "temporal_snapshot"
    has_bomb_source: str | None = None
    utility_inventory_source: str | None = None
    availability: SnapshotAvailability

    @model_validator(mode="after")
    def validate_coordinate_tuple(self) -> SpatialSnapshot:
        values = (self.x, self.y, self.z)
        if any(item is None for item in values) and any(item is not None for item in values):
            raise ValueError("position coordinates must be all present or all absent")
        return self


class BombPositionSnapshot(SpatialModel):
    snapshot_id: UUID
    match_id: UUID
    temporal_run_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    x: Coordinate
    y: Coordinate
    z: Coordinate
    carrier_participant_id: UUID
    position_authority: SpatialAuthority = SpatialAuthority.DERIVED
    source: str = "derived:confirmed_c4_carrier_player_origin"


class SpatialValidationIssue(SpatialModel):
    code: str
    severity: ValidationSeverity
    is_fatal: bool = False
    entity_type: str
    entity_id: str | None = None
    message: str
    evidence: dict[str, JsonValue] = Field(default_factory=dict)


class SpatialSummary(SpatialModel):
    rounds: int = Field(ge=0)
    requested_ticks: int = Field(ge=0)
    source_rows: int = Field(ge=0)
    snapshots: int = Field(ge=0)
    participants: int = Field(ge=0)
    bomb_position_snapshots: int = Field(ge=0)
    projectiles: int = Field(default=0, ge=0)
    projectile_snapshots: int = Field(default=0, ge=0)
    utility_effects: int = Field(default=0, ge=0)
    validation_issue_count: int = Field(ge=0)


class SpatialMatchInput(SpatialModel):
    match_id: UUID
    dataset_fingerprint: Sha256
    map_name: str
    temporal: TemporalRunSummary
    timelines: tuple[RoundTimeline, ...]
    players: tuple[CanonicalPlayer, ...]
    tick_targets: tuple[SpatialTickTarget, ...]
    extraction: SpatialExtraction


class SpatialMatchState(SpatialModel):
    spatial_schema_version: str = SPATIAL_SCHEMA_VERSION
    spatial_rule_version: str = SPATIAL_RULE_VERSION
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    source_demo_sha256: Sha256
    parser_name: str
    parser_version: str
    config: SpatialConfig
    map_model: SpatialMapModel
    map_semantics: MapSemanticsPin | None = None
    capabilities: SpatialCapabilities
    projectile_metadata: ProjectileRunMetadata
    projectile_capabilities: ProjectileCapabilities
    summary: SpatialSummary
    snapshots: tuple[SpatialSnapshot, ...]
    bomb_positions: tuple[BombPositionSnapshot, ...]
    projectiles: tuple[SpatialProjectile, ...]
    projectile_snapshots: tuple[ProjectileSnapshot, ...]
    utility_effects: tuple[UtilityEffect, ...]
    validation_issues: tuple[SpatialValidationIssue, ...]
    warnings: tuple[str, ...]


class SpatialSaveResult(SpatialModel):
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    status: SpatialComputeStatus
    row_counts: dict[str, int]


class SpatialComputeResult(SpatialModel):
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_schema_version: str
    spatial_rule_version: str
    match_id: UUID
    temporal_run_id: UUID
    status: SpatialComputeStatus
    map_semantics: MapSemanticsPin | None = None
    capabilities: SpatialCapabilities
    projectile_metadata: ProjectileRunMetadata | None = None
    projectile_capabilities: ProjectileCapabilities = Field(
        default_factory=unavailable_projectile_capabilities
    )
    summary: SpatialSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


class SpatialRunSummary(SpatialModel):
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_schema_version: str
    spatial_rule_version: str
    spatial_config_hash: Sha256
    match_id: UUID
    dataset_fingerprint: Sha256
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    source_demo_sha256: Sha256
    parser_name: str
    parser_version: str
    config: SpatialConfig
    map_model: SpatialMapModel
    map_semantics: MapSemanticsPin | None = None
    legacy_map_semantics: bool = False
    capabilities: SpatialCapabilities
    projectile_metadata: ProjectileRunMetadata | None = None
    projectile_capabilities: ProjectileCapabilities = Field(
        default_factory=lambda: unavailable_projectile_capabilities(legacy=True)
    )
    summary: SpatialSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]


class SpatialRunRecord(SpatialModel):
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    match_id: UUID
    temporal_run_id: UUID
    spatial_schema_version: str
    spatial_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool
    canonical_map_name: str | None = None
    selected_map_revision: str | None = None
    map_definition_version: str | None = None
    legacy_map_semantics: bool = False


class DeleteSpatialResult(SpatialModel):
    match_id: UUID
    deleted: bool
    deleted_runs: int = Field(ge=0)
