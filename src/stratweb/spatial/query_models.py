"""Typed read models for Stage 7.1 spatial exploration without interpretation."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field

from stratweb.domain.enums import Side
from stratweb.maps.models import (
    CalibrationStatus,
    MapLevel,
    MapLevelPolicy,
    MapSelectionStatus,
    MapValidationStatus,
)
from stratweb.spatial.models import (
    BombPositionSnapshot,
    SpatialAvailabilityStatus,
    SpatialModel,
    SpatialSnapshot,
)
from stratweb.spatial.projectiles import (
    ProjectileCapabilities,
    ProjectileRunMetadata,
    ProjectileSnapshot,
    SpatialProjectile,
    UtilityEffect,
    unavailable_projectile_capabilities,
)

SPATIAL_QUERY_SCHEMA_VERSION = "1.0.0"
SPATIAL_PLAYBACK_SCHEMA_VERSION = "1.2.0"


class TickResolutionStatus(StrEnum):
    EXACT = "exact"
    UNAVAILABLE = "unavailable"


class SpatialEventMarkerKind(StrEnum):
    SHOT = "shot"
    DAMAGE = "damage"
    GRENADE = "grenade"
    DEATH = "death"
    PLANT = "plant"
    DEFUSE = "defuse"
    EXPLOSION = "explosion"
    TRADE = "trade"
    OPENING_DUEL = "opening_duel"


class EntityRenderStatus(StrEnum):
    AVAILABLE = "available"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class MapOverview(SpatialModel):
    map_name: str
    status: SpatialAvailabilityStatus
    canonical_name: str | None = None
    display_name: str | None = None
    selected_revision: str | None = None
    revision_selection_status: MapSelectionStatus | None = None
    selection_evidence: tuple[str, ...] = ()
    image_url: str | None = None
    lower_image_url: str | None = None
    image_sha256: str | None = None
    metadata_sha256: str | None = None
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    pos_x: float | None = Field(default=None, allow_inf_nan=False)
    pos_y: float | None = Field(default=None, allow_inf_nan=False)
    scale: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    rotate: int | None = None
    asset_version: str | None = None
    map_definition_version: str | None = None
    map_definition_fingerprint: str | None = None
    calibration_status: CalibrationStatus | None = None
    validation_status: MapValidationStatus | None = None
    level_policy: MapLevelPolicy | None = None
    legacy_map_semantics: bool = False
    source: str
    warnings: tuple[str, ...] = ()


class MapProjection(SpatialModel):
    pixel_x: float = Field(allow_inf_nan=False)
    pixel_y: float = Field(allow_inf_nan=False)
    percent_x: float = Field(allow_inf_nan=False)
    percent_y: float = Field(allow_inf_nan=False)
    inside_image: bool
    normalized_x: float | None = Field(default=None, allow_inf_nan=False)
    normalized_y: float | None = Field(default=None, allow_inf_nan=False)
    level: MapLevel = MapLevel.DEFAULT
    warnings: tuple[str, ...] = ()


class MapViewDirection(SpatialModel):
    yaw_degrees: float = Field(allow_inf_nan=False)
    start_pixel_x: float = Field(allow_inf_nan=False)
    start_pixel_y: float = Field(allow_inf_nan=False)
    end_pixel_x: float = Field(allow_inf_nan=False)
    end_pixel_y: float = Field(allow_inf_nan=False)


class SpatialPlayerView(SpatialModel):
    snapshot: SpatialSnapshot
    player_name: str
    team_name: str | None = None
    projection: MapProjection | None = None
    view_direction: MapViewDirection | None = None
    render_status: EntityRenderStatus = EntityRenderStatus.UNAVAILABLE
    rejection_reasons: tuple[str, ...] = ()


class TickNavigation(SpatialModel):
    requested_tick: int = Field(ge=0)
    status: TickResolutionStatus
    previous_tick: int | None = Field(default=None, ge=0)
    next_tick: int | None = Field(default=None, ge=0)
    minimum_tick: int | None = Field(default=None, ge=0)
    maximum_tick: int | None = Field(default=None, ge=0)
    available_tick_count: int = Field(ge=0)


class SpatialEventMarker(SpatialModel):
    marker_id: str
    event_id: UUID
    kind: SpatialEventMarkerKind
    tick: int = Field(ge=0)
    player_id: UUID | None = None
    player_name: str | None = None
    projection: MapProjection | None = None
    source: str
    temporal_url: str
    render_status: EntityRenderStatus = EntityRenderStatus.UNAVAILABLE
    rejection_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class SpatialTickSnapshot(SpatialModel):
    schema_version: str = SPATIAL_QUERY_SCHEMA_VERSION
    match_id: UUID
    spatial_run_id: UUID
    temporal_run_id: UUID
    round_number: int = Field(ge=1)
    navigation: TickNavigation
    players: tuple[SpatialPlayerView, ...]
    bomb_position: BombPositionSnapshot | None = None
    bomb_projection: MapProjection | None = None
    bomb_carrier_id: UUID | None = None
    events: tuple[SpatialEventMarker, ...] = ()
    overview: MapOverview
    warnings: tuple[str, ...] = ()


class PlayerPath(SpatialModel):
    schema_version: str = SPATIAL_QUERY_SCHEMA_VERSION
    match_id: UUID
    spatial_run_id: UUID
    temporal_run_id: UUID
    round_number: int = Field(ge=1)
    participant_id: UUID
    player_name: str
    team_id: UUID | None = None
    side: Side = Side.UNKNOWN
    points: tuple[SpatialPlayerView, ...]
    overview: MapOverview
    warnings: tuple[str, ...] = ()


class TeamTickSnapshot(SpatialModel):
    schema_version: str = SPATIAL_QUERY_SCHEMA_VERSION
    match_id: UUID
    spatial_run_id: UUID
    temporal_run_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    team_id: UUID
    team_name: str
    players: tuple[SpatialPlayerView, ...]
    overview: MapOverview


class NearestPlayer(SpatialModel):
    participant_id: UUID
    player_name: str
    distance_world_units: float = Field(ge=0, allow_inf_nan=False)
    same_physical_team: bool | None = None
    alive: bool | None = None


class NearestPlayersResult(SpatialModel):
    schema_version: str = SPATIAL_QUERY_SCHEMA_VERSION
    match_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    source_participant_id: UUID
    players: tuple[NearestPlayer, ...]
    warnings: tuple[str, ...] = ()


class PlaybackFilters(SpatialModel):
    physical_team_id: UUID | None = None
    participant_id: UUID | None = None
    alive_only: bool = False
    bomb_carrier_only: bool = False


class PlaybackSample(SpatialModel):
    """One authoritative evidence sample; never an interpolated visual frame."""

    sample_index: int = Field(ge=0)
    tick: int = Field(ge=0)
    players: tuple[SpatialPlayerView, ...]
    bomb_position: BombPositionSnapshot | None = None
    bomb_projection: MapProjection | None = None
    bomb_render_status: EntityRenderStatus = EntityRenderStatus.UNAVAILABLE
    bomb_rejection_reasons: tuple[str, ...] = ()
    bomb_carrier_id: UUID | None = None
    events: tuple[SpatialEventMarker, ...] = ()
    warnings: tuple[str, ...] = ()


class ProjectileSnapshotView(SpatialModel):
    projectile: SpatialProjectile
    snapshot: ProjectileSnapshot
    owner_name: str | None = None
    projection: MapProjection | None = None
    render_status: EntityRenderStatus = EntityRenderStatus.UNAVAILABLE
    rejection_reasons: tuple[str, ...] = ()


class UtilityEffectView(SpatialModel):
    effect: UtilityEffect
    projection: MapProjection | None = None
    render_status: EntityRenderStatus = EntityRenderStatus.UNAVAILABLE
    rejection_reasons: tuple[str, ...] = ()


class PlaybackDiagnostics(SpatialModel):
    authoritative_player_samples: int = Field(ge=0)
    unavailable_player_samples: int = Field(ge=0)
    rejected_player_markers: int = Field(ge=0)
    authoritative_projectile_samples: int = Field(ge=0)
    rejected_projectile_markers: int = Field(ge=0)
    utility_effects: int = Field(ge=0)
    rejected_utility_effects: int = Field(ge=0)
    event_markers: int = Field(ge=0)
    rejected_event_markers: int = Field(ge=0)
    repeated_player_samples: int = Field(default=0, ge=0)
    suspicious_player_jumps: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()


class PlaybackNavigation(SpatialModel):
    from_index: int = Field(ge=0)
    returned_samples: int = Field(ge=0)
    total_samples: int = Field(ge=0)
    previous_from_index: int | None = Field(default=None, ge=0)
    next_from_index: int | None = Field(default=None, ge=0)
    has_more: bool


class PlaybackClockMetadata(SpatialModel):
    basis: str = "relative_demo_ticks"
    tick_duration_ms: float = Field(default=15.625, gt=0, allow_inf_nan=False)
    presentation_ticks_per_second: float = Field(default=64.0, gt=0, allow_inf_nan=False)
    rate_source: str = "presentation_policy:not_canonical_tickrate"
    canonical_tickrate_used: bool = False
    event_density_independent: bool = True


class SpatialPlaybackChunk(SpatialModel):
    schema_version: str = SPATIAL_PLAYBACK_SCHEMA_VERSION
    evidence_semantics: str = "authoritative_spatial_samples"
    visual_interpolation_included: bool = False
    match_id: UUID
    spatial_run_id: UUID
    temporal_run_id: UUID
    round_number: int = Field(ge=1)
    ticks: tuple[int, ...]
    samples: tuple[PlaybackSample, ...]
    projectiles: tuple[SpatialProjectile, ...] = ()
    projectile_samples: tuple[ProjectileSnapshotView, ...] = ()
    utility_effects: tuple[UtilityEffectView, ...] = ()
    clock: PlaybackClockMetadata = Field(default_factory=PlaybackClockMetadata)
    navigation: PlaybackNavigation
    filters: PlaybackFilters
    overview: MapOverview
    position_availability: SpatialAvailabilityStatus
    view_angle_availability: SpatialAvailabilityStatus
    projectile_metadata: ProjectileRunMetadata | None = None
    projectile_capabilities: ProjectileCapabilities = Field(
        default_factory=unavailable_projectile_capabilities
    )
    diagnostics: PlaybackDiagnostics
    warnings: tuple[str, ...] = ()
