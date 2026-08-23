"""Versioned evidence-trust contracts; never tactical recommendations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.patterns.models import (
    CrossMatchPattern,
    PatternAvailability,
    PatternScope,
    PatternType,
)

STATISTICAL_TRUST_SCHEMA_VERSION = "1.0.0"
STATISTICAL_TRUST_RULE_VERSION = "match_clustered_trust_v1"
CLUSTER_INTERVAL_METHOD = "deterministic_match_cluster_bootstrap_percentile_v1"
MULTIPLE_COMPARISON_METHOD = "benjamini_hochberg_global_family_v1"
RAW_HYPOTHESIS_TEST_METHOD = "exact_one_sided_match_cluster_sign_v1"
RANKING_METHOD = "evidence_reliability_rank_v1"


class TrustModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TrustAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class TrustDecision(StrEnum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_TESTABLE = "not_testable"


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"


class StabilityDimension(StrEnum):
    MATCH = "match"
    PATCH = "patch"
    ROSTER_PERIOD = "roster_period"


class StatisticalTrustConfig(TrustModel):
    confidence_level: float = Field(default=0.95, gt=0.5, lt=1)
    bootstrap_iterations: int = Field(default=2000, ge=200, le=100_000)
    null_frequency: float = Field(default=0.5, gt=0, lt=1)
    minimum_effect_size: float = Field(default=0.1, ge=0, lt=1)
    false_discovery_rate: float = Field(default=0.05, gt=0, lt=1)
    minimum_cluster_matches: int = Field(default=5, ge=2)
    minimum_stability_matches: int = Field(default=3, ge=2)
    maximum_leave_one_out_range: float = Field(default=0.2, ge=0, le=1)
    minimum_direction_consistency: float = Field(default=0.6, ge=0, le=1)


class StatisticalTrustInput(TrustModel):
    profile_id: UUID
    source_pattern_run_id: UUID
    source_pattern_fingerprint: Sha256
    source_pattern_schema_version: str
    source_pattern_rule_version: str
    patterns: tuple[CrossMatchPattern, ...]


class MatchClusterEstimate(TrustModel):
    availability: TrustAvailability
    method: str = CLUSTER_INTERVAL_METHOD
    confidence_level: float = Field(gt=0.5, lt=1)
    point_estimate: float | None = Field(default=None, ge=0, le=1)
    lower_bound: float | None = Field(default=None, ge=0, le=1)
    upper_bound: float | None = Field(default=None, ge=0, le=1)
    cluster_count: int = Field(ge=0)
    bootstrap_iterations: int = Field(ge=0)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> MatchClusterEstimate:
        values = (self.point_estimate, self.lower_bound, self.upper_bound)
        if self.availability is TrustAvailability.AVAILABLE:
            if any(value is None for value in values) or self.unavailable_reason is not None:
                raise ValueError("available clustered estimate requires complete bounds")
            assert self.point_estimate is not None
            assert self.lower_bound is not None
            assert self.upper_bound is not None
            if not self.lower_bound <= self.point_estimate <= self.upper_bound:
                raise ValueError("clustered point estimate must be inside bounds")
        elif any(value is not None for value in values) or not self.unavailable_reason:
            raise ValueError("unavailable clustered estimate requires only a reason")
        return self


class MatchContribution(TrustModel):
    match_id: UUID
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_frequency(self) -> MatchContribution:
        if self.numerator > self.denominator:
            raise ValueError("match contribution numerator exceeds denominator")
        if abs(self.frequency - self.numerator / self.denominator) > 1e-12:
            raise ValueError("match contribution frequency is inconsistent")
        return self


class StabilityAssessment(TrustModel):
    dimension: StabilityDimension
    availability: TrustAvailability
    stable: bool | None = None
    group_count: int = Field(ge=0)
    leave_one_out_min: float | None = Field(default=None, ge=0, le=1)
    leave_one_out_max: float | None = Field(default=None, ge=0, le=1)
    leave_one_out_range: float | None = Field(default=None, ge=0, le=1)
    direction_consistency: float | None = Field(default=None, ge=0, le=1)
    unavailable_reason: str | None = None
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_availability(self) -> StabilityAssessment:
        measures = (
            self.leave_one_out_min,
            self.leave_one_out_max,
            self.leave_one_out_range,
            self.direction_consistency,
        )
        if self.availability is TrustAvailability.AVAILABLE:
            if self.stable is None or any(value is None for value in measures):
                raise ValueError("available stability requires all deterministic measures")
            if self.unavailable_reason is not None:
                raise ValueError("available stability cannot have unavailable reason")
        elif self.stable is not None or any(value is not None for value in measures):
            raise ValueError("unavailable stability cannot expose fabricated measures")
        elif not self.unavailable_reason:
            raise ValueError("unavailable stability requires a reason")
        return self


class MultipleComparisonResult(TrustModel):
    availability: TrustAvailability
    method: str = MULTIPLE_COMPARISON_METHOD
    family_id: str = "all_testable_patterns"
    family_size: int = Field(ge=0)
    raw_test_method: str = RAW_HYPOTHESIS_TEST_METHOD
    tested_cluster_count: int = Field(ge=0)
    raw_p_value: float | None = Field(default=None, ge=0, le=1)
    adjusted_q_value: float | None = Field(default=None, ge=0, le=1)
    alpha: float = Field(gt=0, lt=1)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> MultipleComparisonResult:
        values = (self.raw_p_value, self.adjusted_q_value)
        if self.availability is TrustAvailability.AVAILABLE:
            if any(value is None for value in values) or self.unavailable_reason is not None:
                raise ValueError("available multiplicity result requires p and q values")
        elif any(value is not None for value in values) or not self.unavailable_reason:
            raise ValueError("unavailable multiplicity result requires only a reason")
        return self


class TrustGates(TrustModel):
    source_quality: GateStatus
    cluster_count: GateStatus
    practical_effect: GateStatus
    clustered_lower_bound: GateStatus
    multiple_comparison: GateStatus
    match_stability: GateStatus


class StatisticalTrustAssessment(TrustModel):
    assessment_id: UUID
    trust_run_id: UUID
    profile_id: UUID
    source_pattern_run_id: UUID
    source_pattern_id: UUID
    source_pattern_type: PatternType
    source_availability: PatternAvailability
    scope: PatternScope
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1)
    denominator_match_count: int = Field(ge=1)
    match_contributions: tuple[MatchContribution, ...]
    clustered_interval: MatchClusterEstimate
    null_frequency: float | None = Field(default=None, ge=0, le=1)
    effect_size: float | None = Field(default=None, ge=-1, le=1)
    multiple_comparison: MultipleComparisonResult
    match_stability: StabilityAssessment
    patch_stability: StabilityAssessment
    roster_period_stability: StabilityAssessment
    gates: TrustGates
    decision: TrustDecision
    ranking_method: str = RANKING_METHOD
    reliability_score: float | None = Field(default=None, ge=0, le=1)
    reliability_rank: int | None = Field(default=None, ge=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_statistics(self) -> StatisticalTrustAssessment:
        if self.numerator > self.denominator:
            raise ValueError("trust numerator exceeds denominator")
        if abs(self.frequency - self.numerator / self.denominator) > 1e-12:
            raise ValueError("trust frequency is inconsistent")
        if sum(item.numerator for item in self.match_contributions) != self.numerator:
            raise ValueError("cluster numerators do not preserve source numerator")
        if sum(item.denominator for item in self.match_contributions) != self.denominator:
            raise ValueError("cluster denominators do not preserve source denominator")
        if len(self.match_contributions) != self.denominator_match_count:
            raise ValueError("cluster count does not preserve source match count")
        gate_values = (
            self.gates.source_quality,
            self.gates.cluster_count,
            self.gates.practical_effect,
            self.gates.clustered_lower_bound,
            self.gates.multiple_comparison,
            self.gates.match_stability,
        )
        if self.decision is TrustDecision.SUPPORTED:
            if any(value is not GateStatus.PASS for value in gate_values):
                raise ValueError("supported trust assessment requires every gate to pass")
            if self.reliability_score is None or self.reliability_rank is None:
                raise ValueError("supported trust assessment requires a reliability rank")
        if self.decision is TrustDecision.NOT_TESTABLE:
            if self.null_frequency is not None or self.effect_size is not None:
                raise ValueError("not-testable assessment cannot invent a null or effect")
            if self.multiple_comparison.availability is not TrustAvailability.UNAVAILABLE:
                raise ValueError("not-testable assessment cannot expose a hypothesis test")
        if self.decision is TrustDecision.INSUFFICIENT_DATA and (
            self.reliability_score is not None or self.reliability_rank is not None
        ):
            raise ValueError("insufficient assessment cannot receive a reliability rank")
        if self.decision is not TrustDecision.SUPPORTED and (
            self.reliability_score is not None or self.reliability_rank is not None
        ):
            raise ValueError("only supported assessments can receive a reliability rank")
        return self


class StatisticalTrustSummary(TrustModel):
    source_patterns: int = Field(ge=0)
    testable_patterns: int = Field(ge=0)
    supported_patterns: int = Field(ge=0)
    not_supported_patterns: int = Field(ge=0)
    insufficient_data_patterns: int = Field(ge=0)
    not_testable_patterns: int = Field(ge=0)
    patch_stability_available: int = Field(ge=0)
    roster_period_stability_available: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> StatisticalTrustSummary:
        if (
            self.supported_patterns
            + self.not_supported_patterns
            + self.insufficient_data_patterns
            + self.not_testable_patterns
            != self.source_patterns
        ):
            raise ValueError("statistical trust decisions do not cover all source patterns")
        if self.testable_patterns + self.not_testable_patterns != self.source_patterns:
            raise ValueError("testability counts do not cover all source patterns")
        return self


class StatisticalTrustRun(TrustModel):
    trust_schema_version: str = STATISTICAL_TRUST_SCHEMA_VERSION
    trust_rule_version: str = STATISTICAL_TRUST_RULE_VERSION
    trust_run_id: UUID
    trust_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    source_pattern_run_id: UUID
    source_pattern_fingerprint: Sha256
    source_pattern_schema_version: str
    source_pattern_rule_version: str
    config: StatisticalTrustConfig
    assessments: tuple[StatisticalTrustAssessment, ...]
    summary: StatisticalTrustSummary
    warnings: tuple[str, ...] = ()


class StatisticalTrustRunSummary(TrustModel):
    trust_schema_version: str
    trust_rule_version: str
    trust_run_id: UUID
    trust_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    source_pattern_run_id: UUID
    source_pattern_fingerprint: Sha256
    source_pattern_schema_version: str
    source_pattern_rule_version: str
    config: StatisticalTrustConfig
    summary: StatisticalTrustSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


class StatisticalTrustRunRecord(TrustModel):
    trust_run_id: UUID
    trust_fingerprint: Sha256
    profile_id: UUID
    source_pattern_run_id: UUID
    trust_schema_version: str
    trust_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class StatisticalTrustComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class StatisticalTrustSaveResult(TrustModel):
    trust_run_id: UUID
    trust_fingerprint: Sha256
    status: StatisticalTrustComputeStatus
    row_counts: dict[str, int]


class StatisticalTrustComputeResult(TrustModel):
    trust_run_id: UUID
    trust_fingerprint: Sha256
    trust_schema_version: str
    trust_rule_version: str
    profile_id: UUID
    status: StatisticalTrustComputeStatus
    summary: StatisticalTrustSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0)


__all__ = [
    "CLUSTER_INTERVAL_METHOD",
    "MULTIPLE_COMPARISON_METHOD",
    "RANKING_METHOD",
    "RAW_HYPOTHESIS_TEST_METHOD",
    "STATISTICAL_TRUST_RULE_VERSION",
    "STATISTICAL_TRUST_SCHEMA_VERSION",
    "GateStatus",
    "MatchClusterEstimate",
    "MatchContribution",
    "MultipleComparisonResult",
    "StabilityAssessment",
    "StabilityDimension",
    "StatisticalTrustAssessment",
    "StatisticalTrustComputeResult",
    "StatisticalTrustComputeStatus",
    "StatisticalTrustConfig",
    "StatisticalTrustInput",
    "StatisticalTrustRun",
    "StatisticalTrustRunRecord",
    "StatisticalTrustRunSummary",
    "StatisticalTrustSaveResult",
    "StatisticalTrustSummary",
    "TrustAvailability",
    "TrustDecision",
    "TrustGates",
]
