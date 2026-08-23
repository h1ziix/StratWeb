"""Versioned contracts for deterministic Tactical Intelligence V2."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.domain.enums import Side

TACTICAL_V2_SCHEMA_VERSION = "1.0.0"
TACTICAL_V2_RULE_VERSION = "tactical_intelligence_v2.0.0"
TACTICAL_V2_ROUTE_RULE = "checkpoint_zone_formation_exact_v1"
TACTICAL_V2_UTILITY_RULE = "owner_weapon_time_association_v1"
TACTICAL_V2_ROTATION_RULE = "post_contact_zone_transition_v1"
TACTICAL_V2_CLUTCH_RULE = "post_tick_group_one_vs_many_v1"
TACTICAL_V2_HEATMAP_RULE = "world_grid_sample_share_v1"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class TacticalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TacticalAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class TacticalInsightType(StrEnum):
    PATH_CLUSTER = "path_cluster"
    EXECUTE_PACKAGE = "execute_package"
    UTILITY_OUTCOME = "utility_outcome"
    SPACING_PROFILE = "spacing_profile"
    ENTRY_STRUCTURE = "entry_structure"
    TRADE_STRUCTURE = "trade_structure"
    ROTATION_TRANSITION = "rotation_transition"
    CLUTCH_BEHAVIOR = "clutch_behavior"
    SAVE_BEHAVIOR = "save_behavior"
    HEATMAP_CELL = "heatmap_cell"


class TacticalComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class TacticalV2Config(TacticalModel):
    checkpoint_offsets_ticks: tuple[int, ...] = (640, 1280, 1920)
    maximum_snapshot_age_ticks: int = Field(default=32, ge=0, le=1024)
    minimum_players_for_formation: int = Field(default=2, ge=2, le=5)
    execute_window_ticks: int = Field(default=640, ge=1, le=8192)
    utility_outcome_grace_ticks: int = Field(default=64, ge=0, le=1024)
    rotation_window_ticks: int = Field(default=1280, ge=1, le=8192)
    isolated_player_distance_units: FiniteFloat = Field(default=1500.0, gt=0)
    heatmap_cell_size_units: FiniteFloat = Field(default=512.0, gt=0)
    target_corpus_matches: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def validate_checkpoints(self) -> TacticalV2Config:
        if tuple(sorted(set(self.checkpoint_offsets_ticks))) != self.checkpoint_offsets_ticks:
            raise ValueError("tactical checkpoints must be unique and strictly increasing")
        return self


class TacticalSourcePin(TacticalModel):
    match_id: UUID
    team_id: UUID
    map_name: str
    dataset_fingerprint: Sha256
    analytics_fingerprint: Sha256
    analytics_rule_version: str
    temporal_run_id: UUID
    temporal_fingerprint: Sha256
    temporal_rule_version: str
    spatial_run_id: UUID
    spatial_fingerprint: Sha256
    spatial_rule_version: str
    zone_assignment_run_id: UUID
    zone_assignment_fingerprint: Sha256
    zone_assignment_rule_version: str
    feature_run_id: UUID | None = None
    feature_fingerprint: Sha256 | None = None
    feature_rule_version: str | None = None

    @model_validator(mode="after")
    def validate_optional_feature_lineage(self) -> TacticalSourcePin:
        feature_values = (
            self.feature_run_id,
            self.feature_fingerprint,
            self.feature_rule_version,
        )
        if any(value is not None for value in feature_values) and any(
            value is None for value in feature_values
        ):
            raise ValueError("tactical feature lineage must be complete or absent")
        return self


class TacticalPlayerSample(TacticalModel):
    snapshot_id: UUID
    player_id: UUID
    tick: int = Field(ge=0)
    x: FiniteFloat
    y: FiniteFloat
    z: FiniteFloat
    alive: bool | None = None
    side: Side
    zone_id: str | None = None
    zone_name: str | None = None


class TacticalKillSample(TacticalModel):
    event_id: UUID
    tick: int = Field(ge=0)
    attacker_player_id: UUID | None = None
    victim_player_id: UUID | None = None
    attacker_team_id: UUID | None = None
    victim_team_id: UUID | None = None
    is_teamkill: bool | None = None
    is_suicide: bool | None = None


class TacticalDamageSample(TacticalModel):
    event_id: UUID
    tick: int = Field(ge=0)
    attacker_player_id: UUID | None = None
    victim_player_id: UUID | None = None
    attacker_team_id: UUID | None = None
    victim_team_id: UUID | None = None
    weapon: str | None = None
    damage_health: int | None = Field(default=None, ge=0)


class TacticalTradeSample(TacticalModel):
    traded_kill_event_id: UUID
    original_kill_event_id: UUID
    tick_delta: int = Field(ge=0)
    team_id: UUID


class TacticalUtilitySample(TacticalModel):
    effect_id: UUID
    projectile_id: UUID | None = None
    owner_player_id: UUID | None = None
    owner_team_id: UUID | None = None
    effect_type: str
    start_tick: int = Field(ge=0)
    end_tick: int | None = Field(default=None, ge=0)
    center_x: FiniteFloat | None = None
    center_y: FiniteFloat | None = None
    center_z: FiniteFloat | None = None

    @model_validator(mode="after")
    def validate_ticks(self) -> TacticalUtilitySample:
        if self.end_tick is not None and self.end_tick < self.start_tick:
            raise ValueError("tactical utility end tick precedes start tick")
        return self


class TacticalPlantSample(TacticalModel):
    event_id: UUID
    tick: int = Field(ge=0)
    site: str | None = None
    player_id: UUID | None = None


class TacticalSaveSignal(TacticalModel):
    feature_id: UUID
    saved: bool
    tick_start: int | None = Field(default=None, ge=0)
    tick_end: int | None = Field(default=None, ge=0)
    snapshot_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_ticks(self) -> TacticalSaveSignal:
        if (
            self.tick_start is not None
            and self.tick_end is not None
            and self.tick_end < self.tick_start
        ):
            raise ValueError("tactical save end tick precedes start tick")
        return self


class TacticalRoundInput(TacticalModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    side: Side
    selected_team_won: bool | None = None
    is_warmup: bool
    is_complete: bool
    live_start_tick: int | None = Field(default=None, ge=0)
    effective_end_tick: int | None = Field(default=None, ge=0)
    selected_player_ids: tuple[UUID, ...]
    opponent_player_ids: tuple[UUID, ...]
    samples: tuple[TacticalPlayerSample, ...]
    kills: tuple[TacticalKillSample, ...]
    damages: tuple[TacticalDamageSample, ...]
    trades: tuple[TacticalTradeSample, ...]
    utility: tuple[TacticalUtilitySample, ...]
    plant: TacticalPlantSample | None = None
    save_availability: TacticalAvailability = TacticalAvailability.UNAVAILABLE
    save_signal: TacticalSaveSignal | None = None


class TacticalMatchInput(TacticalModel):
    source: TacticalSourcePin
    rounds: tuple[TacticalRoundInput, ...]
    limitations: tuple[str, ...] = ()


class TacticalV2Input(TacticalModel):
    profile_id: UUID
    matches: tuple[TacticalMatchInput, ...]
    excluded_match_ids: tuple[UUID, ...] = ()
    warnings: tuple[str, ...] = ()


class TacticalEvidenceReference(TacticalModel):
    match_id: UUID
    round_number: int = Field(ge=1)
    tick_start: int | None = Field(default=None, ge=0)
    tick_end: int | None = Field(default=None, ge=0)
    event_ids: tuple[UUID, ...] = ()
    snapshot_ids: tuple[UUID, ...] = ()
    feature_ids: tuple[UUID, ...] = ()
    projectile_ids: tuple[UUID, ...] = ()
    effect_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_ticks(self) -> TacticalEvidenceReference:
        if (
            self.tick_start is not None
            and self.tick_end is not None
            and self.tick_end < self.tick_start
        ):
            raise ValueError("tactical evidence end tick precedes start tick")
        return self


class TacticalInsight(TacticalModel):
    insight_id: UUID
    tactical_run_id: UUID
    profile_id: UUID
    insight_type: TacticalInsightType
    map_name: str
    side: Side
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    availability: TacticalAvailability
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    match_count: int = Field(ge=1)
    small_sample_warning: bool
    metrics: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_references: tuple[TacticalEvidenceReference, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ratio(self) -> TacticalInsight:
        if self.numerator > self.denominator:
            raise ValueError("tactical numerator exceeds denominator")
        if self.sample_size != self.denominator:
            raise ValueError("tactical sample size must equal denominator")
        if abs(self.frequency - self.numerator / self.denominator) > 1e-12:
            raise ValueError("tactical frequency is inconsistent")
        evidence_matches = {item.match_id for item in self.evidence_references}
        if len(evidence_matches) != self.match_count:
            raise ValueError("tactical evidence match count is inconsistent")
        return self


class TacticalCapability(TacticalModel):
    status: TacticalAvailability
    eligible_units: int = Field(ge=0)
    covered_units: int = Field(ge=0)
    insight_count: int = Field(ge=0)
    unavailable_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_coverage(self) -> TacticalCapability:
        if self.covered_units > self.eligible_units:
            raise ValueError("tactical capability coverage exceeds population")
        return self


class TacticalV2Summary(TacticalModel):
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    excluded_matches: int = Field(ge=0)
    eligible_rounds: int = Field(ge=0)
    insights: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    insight_type_counts: dict[TacticalInsightType, int]
    small_sample_insights: int = Field(ge=0)


class TacticalV2Run(TacticalModel):
    tactical_schema_version: str = TACTICAL_V2_SCHEMA_VERSION
    tactical_rule_version: str = TACTICAL_V2_RULE_VERSION
    tactical_run_id: UUID
    tactical_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    config: TacticalV2Config
    source_pins: tuple[TacticalSourcePin, ...]
    capabilities: dict[TacticalInsightType, TacticalCapability]
    summary: TacticalV2Summary
    insights: tuple[TacticalInsight, ...]
    warnings: tuple[str, ...] = ()


class TacticalV2RunSummary(TacticalModel):
    tactical_schema_version: str
    tactical_rule_version: str
    tactical_run_id: UUID
    tactical_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    config: TacticalV2Config
    source_pins: tuple[TacticalSourcePin, ...]
    capabilities: dict[TacticalInsightType, TacticalCapability]
    summary: TacticalV2Summary
    row_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


class TacticalV2RunRecord(TacticalModel):
    tactical_run_id: UUID
    tactical_fingerprint: Sha256
    profile_id: UUID
    tactical_schema_version: str
    tactical_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class TacticalV2SaveResult(TacticalModel):
    tactical_run_id: UUID
    tactical_fingerprint: Sha256
    status: TacticalComputeStatus
    row_counts: dict[str, int]


class TacticalV2ComputeResult(TacticalModel):
    tactical_run_id: UUID
    tactical_fingerprint: Sha256
    tactical_schema_version: str
    tactical_rule_version: str
    profile_id: UUID
    status: TacticalComputeStatus
    summary: TacticalV2Summary
    capabilities: dict[TacticalInsightType, TacticalCapability]
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


__all__ = [
    name for name in globals() if name.startswith("TACTICAL_V2_") or name.startswith("Tactical")
]
