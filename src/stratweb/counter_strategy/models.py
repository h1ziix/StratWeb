"""Versioned contracts for deterministic Stage 8.7 counter-strategy rules."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.findings.models import AnalysisFinding, EvidenceReference, FindingText
from stratweb.patterns.models import PatternScope, PatternType, PatternValue, WilsonConfidence
from stratweb.readiness.models import (
    FindingReadinessAudit,
    FindingReadinessConfig,
    FindingReadinessStatus,
    ReadinessReason,
)

STRATEGY_SCHEMA_VERSION = "1.0.0"
STRATEGY_RULE_VERSION = "counter_strategy_rules_v1"


class StrategyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CounterStrategyCategory(StrEnum):
    MAP_CONTROL = "map_control"
    PLAYER_SPECIFIC = "player_specific"
    ROUND_MANAGEMENT = "round_management"
    TRADE_STRUCTURE = "trade_structure"


class CounterStrategyRuleId(StrEnum):
    FREQUENT_SITE = "frequent_site_v1"
    FREQUENT_EARLY_CONTROL = "frequent_early_control_v1"
    RECURRING_OPENING_PLAYER = "recurring_opening_player_v1"
    RECURRING_OPENING_DEATH = "recurring_opening_death_v1"
    LOW_OPENING_CONVERSION = "low_opening_conversion_v1"
    OPENING_DEATH_RECOVERY = "opening_death_recovery_v1"
    LOST_MAN_ADVANTAGE = "lost_man_advantage_v1"
    UNTRADED_DEATH = "untraded_death_v1"


class StrategySkipReason(StrEnum):
    NOT_READY = "finding_not_ready"
    NO_SUPPORTED_RULE = "no_supported_rule"
    THRESHOLD_NOT_MET = "rule_threshold_not_met"


class CounterStrategyConfig(StrategyModel):
    frequent_site_threshold: float = Field(default=0.60, ge=0, le=1)
    frequent_control_threshold: float = Field(default=0.60, ge=0, le=1)
    recurring_opening_player_threshold: float = Field(default=0.35, ge=0, le=1)
    recurring_opening_death_threshold: float = Field(default=0.30, ge=0, le=1)
    low_opening_conversion_threshold: float = Field(default=0.55, ge=0, le=1)
    opening_death_recovery_threshold: float = Field(default=0.35, ge=0, le=1)
    lost_advantage_threshold: float = Field(default=0.25, ge=0, le=1)
    untraded_death_threshold: float = Field(default=0.25, ge=0, le=1)


class CounterStrategyRecommendation(StrategyModel):
    recommendation_id: UUID
    strategy_run_id: UUID
    profile_id: UUID
    source_analysis_run_id: UUID
    source_finding_id: UUID
    rule_id: CounterStrategyRuleId
    rule_version: str = STRATEGY_RULE_VERSION
    category: CounterStrategyCategory
    title: str = Field(min_length=1)
    scope: PatternScope
    pattern_type: PatternType
    pattern_value: PatternValue
    observation: FindingText
    tactical_interpretation: FindingText
    recommendation: FindingText
    avoid: FindingText
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    numerator_match_count: int = Field(ge=0)
    denominator_match_count: int = Field(ge=1)
    confidence: WilsonConfidence
    evidence_references: tuple[EvidenceReference, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evidence(self) -> CounterStrategyRecommendation:
        if self.numerator > self.denominator:
            raise ValueError("recommendation numerator cannot exceed denominator")
        if self.sample_size != self.denominator:
            raise ValueError("recommendation sample size must equal denominator")
        if abs(self.frequency - self.numerator / self.denominator) > 1e-12:
            raise ValueError("recommendation frequency does not match its ratio")
        if len(self.evidence_references) != self.denominator:
            raise ValueError("recommendation must preserve complete finding evidence")
        if any(item.finding_id != self.source_finding_id for item in self.evidence_references):
            raise ValueError("recommendation evidence belongs to another finding")
        if any(
            item.availability.value != "available"
            for item in (
                self.observation,
                self.tactical_interpretation,
                self.recommendation,
                self.avoid,
            )
        ):
            raise ValueError("published recommendation text must be explicitly available")
        return self


class SkippedStrategyFinding(StrategyModel):
    finding_id: UUID
    reason: StrategySkipReason
    readiness_status: FindingReadinessStatus
    readiness_blockers: tuple[ReadinessReason, ...] = ()
    readiness_limitations: tuple[ReadinessReason, ...] = ()
    pattern_type: PatternType
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)


class CounterStrategySummary(StrategyModel):
    source_findings: int = Field(ge=0)
    ready_findings: int = Field(ge=0)
    recommendations: int = Field(ge=0)
    skipped_not_ready: int = Field(ge=0)
    skipped_no_rule: int = Field(ge=0)
    skipped_threshold: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    maps: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> CounterStrategySummary:
        if (
            self.recommendations
            + self.skipped_not_ready
            + self.skipped_no_rule
            + self.skipped_threshold
            != self.source_findings
        ):
            raise ValueError("recommendation and skipped counts must equal source findings")
        if self.ready_findings != (
            self.recommendations + self.skipped_no_rule + self.skipped_threshold
        ):
            raise ValueError("every ready finding must be published or rule-skipped")
        if self.skipped_not_ready != self.source_findings - self.ready_findings:
            raise ValueError("not-ready count does not match source and ready findings")
        return self


class CounterStrategyInput(StrategyModel):
    analysis_fingerprint: Sha256
    analysis_schema_version: str
    analysis_rule_version: str
    profile_id: UUID
    readiness: FindingReadinessAudit
    findings: tuple[AnalysisFinding, ...]


class CounterStrategyRun(StrategyModel):
    strategy_schema_version: str = STRATEGY_SCHEMA_VERSION
    strategy_rule_version: str = STRATEGY_RULE_VERSION
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    source_analysis_run_id: UUID
    source_analysis_fingerprint: Sha256
    source_analysis_schema_version: str
    source_analysis_rule_version: str
    readiness_audit_id: UUID
    readiness_fingerprint: Sha256
    readiness_schema_version: str
    readiness_rule_version: str
    readiness_config: FindingReadinessConfig
    config: CounterStrategyConfig
    recommendations: tuple[CounterStrategyRecommendation, ...]
    skipped_findings: tuple[SkippedStrategyFinding, ...]
    summary: CounterStrategySummary
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_children(self) -> CounterStrategyRun:
        if len(self.recommendations) != self.summary.recommendations:
            raise ValueError("strategy recommendation count differs from summary")
        if len(self.skipped_findings) != (
            self.summary.skipped_not_ready
            + self.summary.skipped_no_rule
            + self.summary.skipped_threshold
        ):
            raise ValueError("strategy skipped count differs from summary")
        if any(item.strategy_run_id != self.strategy_run_id for item in self.recommendations):
            raise ValueError("recommendation belongs to another strategy run")
        return self


class CounterStrategyRunSummary(StrategyModel):
    strategy_schema_version: str
    strategy_rule_version: str
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    source_analysis_run_id: UUID
    source_analysis_fingerprint: Sha256
    source_analysis_schema_version: str
    source_analysis_rule_version: str
    readiness_audit_id: UUID
    readiness_fingerprint: Sha256
    readiness_schema_version: str
    readiness_rule_version: str
    readiness_config: FindingReadinessConfig
    config: CounterStrategyConfig
    summary: CounterStrategySummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


class CounterStrategyRunRecord(StrategyModel):
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    profile_id: UUID
    source_analysis_run_id: UUID
    strategy_schema_version: str
    strategy_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class StrategyComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class CounterStrategySaveResult(StrategyModel):
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    status: StrategyComputeStatus
    row_counts: dict[str, int]


class CounterStrategyComputeResult(StrategyModel):
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    strategy_schema_version: str
    strategy_rule_version: str
    profile_id: UUID
    source_analysis_run_id: UUID
    status: StrategyComputeStatus
    summary: CounterStrategySummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


__all__ = [name for name in globals() if not name.startswith("_")]
