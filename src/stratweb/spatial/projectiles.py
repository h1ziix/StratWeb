"""Parser-independent projectile and utility evidence contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.domain.enums import Side

PROJECTILE_SCHEMA_VERSION = "1.0.0"
PROJECTILE_EXTRACTION_RULE_VERSION = "demoparser2-projectiles-v1"
PROJECTILE_SAMPLING_INTERVAL_TICKS = 4
PROJECTILE_REQUESTED_PROPERTIES = (
    "Grenade.m_nBounces",
    "Grenade.m_vInitialVelocity",
)
PROJECTILE_REQUESTED_EVENTS = (
    "weapon_fire",
    "flashbang_detonate",
    "hegrenade_detonate",
    "smokegrenade_detonate",
    "smokegrenade_expired",
    "inferno_startburn",
    "inferno_expire",
    "decoy_started",
    "decoy_detonate",
)
ProjectileCoordinate = Annotated[float, Field(allow_inf_nan=False)]
ProjectileFingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ProjectileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectileType(StrEnum):
    SMOKE = "smoke"
    FLASHBANG = "flashbang"
    HE_GRENADE = "he_grenade"
    MOLOTOV = "molotov"
    INCENDIARY = "incendiary"
    DECOY = "decoy"
    UNKNOWN = "unknown"


class ProjectileLifecycle(StrEnum):
    THROWN = "thrown"
    IN_FLIGHT = "in_flight"
    BOUNCED = "bounced"
    LANDED = "landed"
    DETONATED = "detonated"
    EFFECT_ACTIVE = "effect_active"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"


class ProjectileAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ProjectileAuthority(StrEnum):
    PARSER_ENTITY = "parser_entity"
    GAME_EVENT = "game_event"
    DERIVED_ASSOCIATION = "derived_association"
    UNAVAILABLE = "unavailable"


class UtilityEffectType(StrEnum):
    SMOKE = "smoke"
    FIRE = "fire"
    FLASH = "flash"
    HE = "he"
    DECOY = "decoy"
    UNKNOWN = "unknown"


class ProjectileSourcePoint(ProjectileModel):
    tick: int = Field(ge=0)
    x: ProjectileCoordinate
    y: ProjectileCoordinate
    z: ProjectileCoordinate
    bounce_count: int | None = Field(default=None, ge=0)
    lifecycle: ProjectileLifecycle
    availability: ProjectileAvailability = ProjectileAvailability.AVAILABLE
    source: str
    warnings: tuple[str, ...] = ()


class ProjectileSourceTrack(ProjectileModel):
    source_track_id: str
    source_entity_id: int = Field(ge=0)
    raw_projectile_type: str
    projectile_type: ProjectileType
    owner_steam_id: str | None = None
    owner_name: str | None = None
    thrown_tick: int | None = Field(default=None, ge=0)
    first_position_tick: int = Field(ge=0)
    terminal_tick: int = Field(ge=0)
    terminal_event: str | None = None
    initial_velocity_x: ProjectileCoordinate | None = None
    initial_velocity_y: ProjectileCoordinate | None = None
    initial_velocity_z: ProjectileCoordinate | None = None
    points: tuple[ProjectileSourcePoint, ...]
    availability: ProjectileAvailability
    source: str = "demoparser2:parse_grenades"
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_span(self) -> ProjectileSourceTrack:
        if self.terminal_tick < self.first_position_tick:
            raise ValueError("projectile terminal tick precedes first position")
        if not self.points:
            raise ValueError("projectile track requires at least one position")
        return self


class UtilityEffectSource(ProjectileModel):
    source_effect_id: str
    source_track_id: str | None = None
    source_entity_id: int | None = Field(default=None, ge=0)
    effect_type: UtilityEffectType
    start_tick: int = Field(ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    center_x: ProjectileCoordinate | None = None
    center_y: ProjectileCoordinate | None = None
    center_z: ProjectileCoordinate | None = None
    start_event: str
    end_event: str | None = None
    availability: ProjectileAvailability
    source: str = "demoparser2:game_event"
    warnings: tuple[str, ...] = ()


class ProjectileCapability(ProjectileModel):
    status: ProjectileAvailability
    authority: ProjectileAuthority
    population: int = Field(ge=0)
    covered: int = Field(ge=0)
    source_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_coverage(self) -> ProjectileCapability:
        if self.covered > self.population:
            raise ValueError("projectile capability covered cannot exceed population")
        return self


class ProjectileCapabilities(ProjectileModel):
    positions: ProjectileCapability
    owner: ProjectileCapability
    initial_velocity: ProjectileCapability
    throw_actions: ProjectileCapability
    lifecycle: ProjectileCapability
    bounce_events: ProjectileCapability
    detonation_events: ProjectileCapability
    smoke_lifecycle: ProjectileCapability
    fire_lifecycle: ProjectileCapability
    decoy_lifecycle: ProjectileCapability


def unavailable_projectile_capabilities(*, legacy: bool = False) -> ProjectileCapabilities:
    warning = "legacy_spatial_run_without_projectile_layer" if legacy else "parser_unavailable"

    def item() -> ProjectileCapability:
        return ProjectileCapability(
            status=ProjectileAvailability.UNAVAILABLE,
            authority=ProjectileAuthority.UNAVAILABLE,
            population=0,
            covered=0,
            warnings=(warning,),
        )

    return ProjectileCapabilities(
        positions=item(),
        owner=item(),
        initial_velocity=item(),
        throw_actions=item(),
        lifecycle=item(),
        bounce_events=item(),
        detonation_events=item(),
        smoke_lifecycle=item(),
        fire_lifecycle=item(),
        decoy_lifecycle=item(),
    )


class ProjectileExtraction(ProjectileModel):
    schema_version: str = PROJECTILE_SCHEMA_VERSION
    rule_version: str = PROJECTILE_EXTRACTION_RULE_VERSION
    requested_properties: tuple[str, ...] = PROJECTILE_REQUESTED_PROPERTIES
    requested_events: tuple[str, ...] = PROJECTILE_REQUESTED_EVENTS
    sampling_interval_ticks: int = Field(default=PROJECTILE_SAMPLING_INTERVAL_TICKS, ge=1)
    tracks: tuple[ProjectileSourceTrack, ...] = ()
    effects: tuple[UtilityEffectSource, ...] = ()
    capabilities: ProjectileCapabilities = Field(
        default_factory=unavailable_projectile_capabilities
    )
    warnings: tuple[str, ...] = ()


class ProjectileRunMetadata(ProjectileModel):
    schema_version: str = PROJECTILE_SCHEMA_VERSION
    extraction_rule_version: str = PROJECTILE_EXTRACTION_RULE_VERSION
    requested_properties: tuple[str, ...] = PROJECTILE_REQUESTED_PROPERTIES
    requested_events: tuple[str, ...] = PROJECTILE_REQUESTED_EVENTS
    sampling_interval_ticks: int = Field(default=PROJECTILE_SAMPLING_INTERVAL_TICKS, ge=1)
    sampling_policy: str = "every_n_ticks_plus_first_terminal_and_bounce_changes"
    capability_fingerprint: ProjectileFingerprint


class SpatialProjectile(ProjectileModel):
    projectile_id: UUID
    match_id: UUID
    temporal_run_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    source_track_id: str
    source_entity_id: int = Field(ge=0)
    projectile_type: ProjectileType
    raw_projectile_type: str
    owner_participant_id: UUID | None = None
    owner_physical_team_id: UUID | None = None
    owner_side: Side = Side.UNKNOWN
    thrown_tick: int | None = Field(default=None, ge=0)
    first_position_tick: int = Field(ge=0)
    terminal_tick: int = Field(ge=0)
    terminal_event: str | None = None
    initial_velocity_x: ProjectileCoordinate | None = None
    initial_velocity_y: ProjectileCoordinate | None = None
    initial_velocity_z: ProjectileCoordinate | None = None
    availability: ProjectileAvailability
    source: str
    warnings: tuple[str, ...] = ()


class ProjectileSnapshot(ProjectileModel):
    snapshot_id: UUID
    projectile_id: UUID
    match_id: UUID
    temporal_run_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    x: ProjectileCoordinate
    y: ProjectileCoordinate
    z: ProjectileCoordinate
    bounce_count: int | None = Field(default=None, ge=0)
    lifecycle: ProjectileLifecycle
    availability: ProjectileAvailability
    source: str
    warnings: tuple[str, ...] = ()


class UtilityEffect(ProjectileModel):
    effect_id: UUID
    projectile_id: UUID | None = None
    match_id: UUID
    temporal_run_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    effect_type: UtilityEffectType
    start_tick: int = Field(ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    center_x: ProjectileCoordinate | None = None
    center_y: ProjectileCoordinate | None = None
    center_z: ProjectileCoordinate | None = None
    radius: ProjectileCoordinate | None = Field(default=None, gt=0)
    availability: ProjectileAvailability
    source: str
    warnings: tuple[str, ...] = ()
