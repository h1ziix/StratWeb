"""Versioned contracts for deterministic cross-match pattern aggregation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.features.models import FeatureAvailability, RoundFeature

PATTERN_SCHEMA_VERSION = "1.0.0"
PATTERN_RULE_VERSION = "cross_match_patterns_v1"
PATTERN_CONFIDENCE_METHOD = "wilson_score_95_v1"


class PatternModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PatternType(StrEnum):
    SITE_PREFERENCE = "site_preference"
    EARLY_ZONE_OCCUPATION = "early_zone_occupation"
    RECURRING_OPENING_PLAYER = "recurring_opening_player"
    RECURRING_OPENING_DEATH = "recurring_opening_death"
    FIRST_CONTACT_ZONE = "first_contact_zone"
    FIRST_UTILITY = "first_utility"
    BOMB_ROUTING = "bomb_routing"
    CT_STARTING_POSITION = "ct_starting_position"
    EARLY_ROTATION = "early_rotation"
    OPENING_KILL_CONVERSION = "opening_kill_conversion"
    RECOVERY_AFTER_OPENING_DEATH = "recovery_after_opening_death"
    LOST_MAN_ADVANTAGE = "lost_man_advantage"
    UNTRADED_DEATH = "untraded_death"
    PLANT_TIMING = "plant_timing"
    RETAKE_FREQUENCY = "retake_frequency"
    SAVE_FREQUENCY = "save_frequency"


class PatternAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class PatternInputStatus(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"


class PatternComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class PatternConfig(PatternModel):
    minimum_corpus_matches: int = Field(default=15, ge=1)
    minimum_sample_size: int = Field(default=5, ge=1)
    plant_timing_bucket_seconds: tuple[float, ...] = (20.0, 40.0, 60.0)
    include_partial_features: bool = True

    @model_validator(mode="after")
    def validate_buckets(self) -> PatternConfig:
        values = self.plant_timing_bucket_seconds
        if any(value <= 0 for value in values):
            raise ValueError("plant timing bucket boundaries must be positive")
        if tuple(sorted(set(values))) != values:
            raise ValueError("plant timing bucket boundaries must be unique and increasing")
        return self


class PatternPlayerIdentity(PatternModel):
    player_id: UUID
    identity_key: str = Field(min_length=1)
    current_name: str = Field(min_length=1)
    steam_id: str | None = None
    cross_match_resolved: bool


class PatternRoundInput(PatternModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    team_id: UUID
    side: Side
    buy_type: BuyType | None = None
    is_warmup: bool = False
    is_complete: bool
    opponent_won: bool | None = None
    features: tuple[RoundFeature, ...] = ()


class PatternMatchInput(PatternModel):
    profile_id: UUID
    match_id: UUID
    team_id: UUID
    map_name: str = Field(min_length=1)
    status: PatternInputStatus
    exclusion_reason: str | None = None
    dataset_fingerprint: Sha256 | None = None
    feature_run_id: UUID | None = None
    feature_fingerprint: Sha256 | None = None
    feature_schema_version: str | None = None
    feature_rule_version: str | None = None
    players: tuple[PatternPlayerIdentity, ...] = ()
    rounds: tuple[PatternRoundInput, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> PatternMatchInput:
        pinned = (
            self.dataset_fingerprint,
            self.feature_run_id,
            self.feature_fingerprint,
            self.feature_schema_version,
            self.feature_rule_version,
        )
        if self.status is PatternInputStatus.INCLUDED and any(item is None for item in pinned):
            raise ValueError("included pattern input requires one pinned feature run")
        if self.status is PatternInputStatus.EXCLUDED and self.exclusion_reason is None:
            raise ValueError("excluded pattern input requires a reason")
        return self


class CrossMatchPatternInput(PatternModel):
    profile_id: UUID
    inputs: tuple[PatternMatchInput, ...]


class PatternScope(PatternModel):
    map_name: str = Field(min_length=1)
    side: Side
    buy_type: BuyType | None = None
    feature_rule_version: str = Field(min_length=1)


class CategoricalPatternValue(PatternModel):
    kind: Literal["categorical"] = "categorical"
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    zone_id: str | None = None
    zone_name: str | None = None
    role: str | None = None
    grenade_type: str | None = None


class PlayerPatternValue(PatternModel):
    kind: Literal["player"] = "player"
    identity_key: str = Field(min_length=1)
    current_name: str = Field(min_length=1)
    steam_id: str | None = None
    role: Literal["opening_killer", "opening_victim"]
    cross_match_resolved: bool


class RoutePatternValue(PatternModel):
    kind: Literal["route"] = "route"
    zone_ids: tuple[str, ...] = Field(min_length=1)
    zone_names: tuple[str, ...] = Field(min_length=1)
    label: str = Field(min_length=1)


class ZoneCount(PatternModel):
    zone_id: str
    zone_name: str
    player_count: int = Field(ge=1)


class SetupPatternValue(PatternModel):
    kind: Literal["setup"] = "setup"
    positions: tuple[ZoneCount, ...] = Field(min_length=1)
    label: str = Field(min_length=1)


class TimingBucketPatternValue(PatternModel):
    kind: Literal["timing_bucket"] = "timing_bucket"
    lower_seconds: float = Field(ge=0, allow_inf_nan=False)
    upper_seconds: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    label: str = Field(min_length=1)


class BinaryPatternValue(PatternModel):
    kind: Literal["binary"] = "binary"
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)


PatternValue = Annotated[
    CategoricalPatternValue
    | PlayerPatternValue
    | RoutePatternValue
    | SetupPatternValue
    | TimingBucketPatternValue
    | BinaryPatternValue,
    Field(discriminator="kind"),
]


class WilsonConfidence(PatternModel):
    method: str = PATTERN_CONFIDENCE_METHOD
    level: float = Field(default=0.95, gt=0, lt=1)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    lower_bound: float = Field(ge=0, le=1, allow_inf_nan=False)
    upper_bound: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> WilsonConfidence:
        if not self.lower_bound <= self.score <= self.upper_bound:
            raise ValueError("confidence score must be inside the Wilson interval")
        return self


class PatternRoundEvidence(PatternModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int | None = Field(default=None, ge=0)
    contributed_to_numerator: bool
    feature_ids: tuple[UUID, ...] = ()
    event_ids: tuple[UUID, ...] = ()
    snapshot_ids: tuple[UUID, ...] = ()
    economy_snapshot_ids: tuple[UUID, ...] = ()
    feature_availability: FeatureAvailability | None = None
    limitations: tuple[str, ...] = ()


class PatternRoundExclusion(PatternModel):
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    reason: str = Field(min_length=1)
    feature_ids: tuple[UUID, ...] = ()


class CrossMatchPattern(PatternModel):
    pattern_id: UUID
    pattern_run_id: UUID
    profile_id: UUID
    pattern_type: PatternType
    scope: PatternScope
    value: PatternValue
    availability: PatternAvailability
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    minimum_sample_size: int = Field(ge=1)
    small_sample_warning: bool
    confidence: WilsonConfidence
    numerator_match_count: int = Field(ge=0)
    denominator_match_count: int = Field(ge=1)
    evidence_references: tuple[PatternRoundEvidence, ...]
    included_rounds: tuple[PatternRoundEvidence, ...]
    excluded_rounds: tuple[PatternRoundExclusion, ...] = ()
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_statistics(self) -> CrossMatchPattern:
        if self.numerator > self.denominator:
            raise ValueError("pattern numerator cannot exceed denominator")
        if self.sample_size != self.denominator:
            raise ValueError("pattern sample size must equal denominator")
        if abs(self.frequency - (self.numerator / self.denominator)) > 1e-12:
            raise ValueError("pattern frequency does not match numerator/denominator")
        if self.small_sample_warning != (self.sample_size < self.minimum_sample_size):
            raise ValueError("small sample flag does not match configured threshold")
        if len(self.included_rounds) != self.denominator:
            raise ValueError("included round count must equal denominator")
        if len(self.evidence_references) != self.numerator:
            raise ValueError("one numerator evidence reference is required per positive round")
        if any(not item.contributed_to_numerator for item in self.evidence_references):
            raise ValueError("numerator evidence must be marked as contributing")
        return self


class PatternCapability(PatternModel):
    pattern_type: PatternType
    availability: PatternAvailability
    eligible_rounds: int = Field(ge=0)
    excluded_rounds: int = Field(ge=0)
    scope_count: int = Field(ge=0)
    pattern_count: int = Field(ge=0)
    limitations: tuple[str, ...] = ()


class PatternSummary(PatternModel):
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    excluded_matches: int = Field(ge=0)
    eligible_rounds: int = Field(ge=0)
    patterns: int = Field(ge=0)
    available_patterns: int = Field(ge=0)
    partial_patterns: int = Field(ge=0)
    maps: tuple[str, ...] = ()
    corpus_below_minimum: bool

    @model_validator(mode="after")
    def validate_counts(self) -> PatternSummary:
        if self.included_matches + self.excluded_matches != self.selected_matches:
            raise ValueError("pattern match counts do not equal selected corpus")
        if self.available_patterns + self.partial_patterns != self.patterns:
            raise ValueError("pattern availability counts do not equal patterns")
        return self


class PatternState(PatternModel):
    pattern_schema_version: str = PATTERN_SCHEMA_VERSION
    pattern_rule_version: str = PATTERN_RULE_VERSION
    confidence_method: str = PATTERN_CONFIDENCE_METHOD
    pattern_run_id: UUID
    pattern_fingerprint: Sha256
    pattern_config_hash: Sha256
    workspace_fingerprint: Sha256
    profile_id: UUID
    config: PatternConfig
    inputs: tuple[PatternMatchInput, ...]
    capabilities: dict[PatternType, PatternCapability]
    summary: PatternSummary
    patterns: tuple[CrossMatchPattern, ...]
    warnings: tuple[str, ...] = ()


class PatternRunSummary(PatternModel):
    pattern_schema_version: str
    pattern_rule_version: str
    confidence_method: str
    pattern_run_id: UUID
    pattern_fingerprint: Sha256
    pattern_config_hash: Sha256
    workspace_fingerprint: Sha256
    profile_id: UUID
    config: PatternConfig
    capabilities: dict[PatternType, PatternCapability]
    summary: PatternSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


class PatternRunRecord(PatternModel):
    pattern_run_id: UUID
    pattern_fingerprint: Sha256
    profile_id: UUID
    pattern_schema_version: str
    pattern_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class PatternRunInputRecord(PatternModel):
    pattern_run_id: UUID
    match_id: UUID
    team_id: UUID
    map_name: str
    input_status: PatternInputStatus
    exclusion_reason: str | None = None
    feature_run_id: UUID | None = None
    feature_fingerprint: Sha256 | None = None
    feature_rule_version: str | None = None


class PatternSaveResult(PatternModel):
    pattern_run_id: UUID
    pattern_fingerprint: Sha256
    status: PatternComputeStatus
    row_counts: dict[str, int]


class PatternComputeResult(PatternModel):
    pattern_run_id: UUID
    pattern_fingerprint: Sha256
    pattern_schema_version: str
    pattern_rule_version: str
    profile_id: UUID
    status: PatternComputeStatus
    summary: PatternSummary
    capabilities: dict[PatternType, PatternCapability]
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


__all__ = [
    "PATTERN_CONFIDENCE_METHOD",
    "PATTERN_RULE_VERSION",
    "PATTERN_SCHEMA_VERSION",
    "BinaryPatternValue",
    "CategoricalPatternValue",
    "CrossMatchPattern",
    "CrossMatchPatternInput",
    "PatternAvailability",
    "PatternCapability",
    "PatternComputeResult",
    "PatternComputeStatus",
    "PatternConfig",
    "PatternInputStatus",
    "PatternMatchInput",
    "PatternPlayerIdentity",
    "PatternRoundEvidence",
    "PatternRoundExclusion",
    "PatternRoundInput",
    "PatternRunRecord",
    "PatternRunInputRecord",
    "PatternRunSummary",
    "PatternSaveResult",
    "PatternScope",
    "PatternState",
    "PatternSummary",
    "PatternType",
    "PatternValue",
    "PlayerPatternValue",
    "RoutePatternValue",
    "SetupPatternValue",
    "TimingBucketPatternValue",
    "WilsonConfidence",
    "ZoneCount",
]
