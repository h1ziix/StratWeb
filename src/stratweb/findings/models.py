"""Versioned contracts for reproducible Stage 8.6 analysis findings."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.patterns.models import (
    CrossMatchPattern,
    PatternAvailability,
    PatternInputStatus,
    PatternScope,
    PatternType,
    PatternValue,
    WilsonConfidence,
)

FINDING_SCHEMA_VERSION = "1.0.0"
FINDING_RULE_VERSION = "analysis_findings_v1"


class FindingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FindingCategory(StrEnum):
    TEAM_TENDENCY = "team_tendency"
    PLAYER_TENDENCY = "player_tendency"
    OUTCOME_ASSOCIATION = "outcome_association"
    ROUND_EVENT_FREQUENCY = "round_event_frequency"


class FindingTextAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class FindingText(FindingModel):
    availability: FindingTextAvailability
    text: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> FindingText:
        if self.availability is FindingTextAvailability.AVAILABLE:
            if not self.text or self.reason is not None:
                raise ValueError("available finding text requires text and no reason")
        elif self.text is not None or not self.reason:
            raise ValueError("unavailable finding text requires a reason and no text")
        return self


class FindingConfig(FindingModel):
    include_partial_patterns: bool = True
    include_zero_frequency: bool = False


class FindingMatchInput(FindingModel):
    match_id: UUID
    team_id: UUID
    map_name: str
    input_status: PatternInputStatus
    exclusion_reason: str | None = None
    demo_file_id: UUID | None = None
    source_demo_sha256: Sha256 | None = None
    dataset_fingerprint: Sha256 | None = None
    feature_run_id: UUID | None = None
    feature_fingerprint: Sha256 | None = None

    @model_validator(mode="after")
    def validate_included_provenance(self) -> FindingMatchInput:
        required = (
            self.demo_file_id,
            self.source_demo_sha256,
            self.dataset_fingerprint,
            self.feature_run_id,
            self.feature_fingerprint,
        )
        if self.input_status is PatternInputStatus.INCLUDED and any(
            item is None for item in required
        ):
            raise ValueError("included finding input requires complete provenance")
        return self


class FindingEngineInput(FindingModel):
    profile_id: UUID
    pattern_run_id: UUID
    pattern_fingerprint: Sha256
    pattern_schema_version: str
    pattern_rule_version: str
    workspace_fingerprint: Sha256
    corpus_below_minimum: bool
    pattern_warnings: tuple[str, ...] = ()
    matches: tuple[FindingMatchInput, ...]
    patterns: tuple[CrossMatchPattern, ...]


class EvidenceReference(FindingModel):
    evidence_id: UUID
    analysis_run_id: UUID
    finding_id: UUID
    source_pattern_id: UUID
    demo_file_id: UUID
    demo_sha256: Sha256
    match_id: UUID
    round_id: UUID
    round_number: int = Field(ge=1)
    tick: int | None = Field(default=None, ge=0)
    contributed_to_numerator: bool
    feature_ids: tuple[UUID, ...] = ()
    event_ids: tuple[UUID, ...] = ()
    snapshot_ids: tuple[UUID, ...] = ()
    economy_snapshot_ids: tuple[UUID, ...] = ()
    description: str = Field(min_length=1)
    map_href: str
    timeline_href: str
    limitations: tuple[str, ...] = ()


class AnalysisFinding(FindingModel):
    finding_id: UUID
    analysis_run_id: UUID
    profile_id: UUID
    source_pattern_run_id: UUID
    source_pattern_id: UUID
    rule_id: str
    rule_version: str = FINDING_RULE_VERSION
    category: FindingCategory
    title: str
    scope: PatternScope
    pattern_type: PatternType
    pattern_value: PatternValue
    source_availability: PatternAvailability
    observation: FindingText
    tactical_implication: FindingText
    recommended_response: FindingText
    avoid: FindingText
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    numerator_match_count: int = Field(ge=0)
    denominator_match_count: int = Field(ge=1)
    minimum_sample_size: int = Field(ge=1)
    small_sample_warning: bool
    confidence: WilsonConfidence
    evidence_references: tuple[EvidenceReference, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_statistics(self) -> AnalysisFinding:
        if self.numerator > self.denominator:
            raise ValueError("finding numerator cannot exceed denominator")
        if self.sample_size != self.denominator:
            raise ValueError("finding sample size must equal denominator")
        if abs(self.frequency - self.numerator / self.denominator) > 1e-12:
            raise ValueError("finding frequency does not match numerator/denominator")
        if len(self.evidence_references) != self.denominator:
            raise ValueError("finding evidence must preserve the complete denominator")
        positive = sum(item.contributed_to_numerator for item in self.evidence_references)
        if positive != self.numerator:
            raise ValueError("finding numerator does not match contributing evidence")
        return self


class FindingSummary(FindingModel):
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    excluded_matches: int = Field(ge=0)
    source_patterns: int = Field(ge=0)
    findings: int = Field(ge=0)
    partial_findings: int = Field(ge=0)
    small_sample_findings: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    maps: tuple[str, ...] = ()


class AnalysisRun(FindingModel):
    analysis_schema_version: str = FINDING_SCHEMA_VERSION
    analysis_rule_version: str = FINDING_RULE_VERSION
    analysis_run_id: UUID
    analysis_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    workspace_fingerprint: Sha256
    source_pattern_run_id: UUID
    source_pattern_fingerprint: Sha256
    source_pattern_schema_version: str
    source_pattern_rule_version: str
    config: FindingConfig
    matches: tuple[FindingMatchInput, ...]
    findings: tuple[AnalysisFinding, ...]
    summary: FindingSummary
    warnings: tuple[str, ...] = ()


class AnalysisRunSummary(FindingModel):
    analysis_schema_version: str
    analysis_rule_version: str
    analysis_run_id: UUID
    analysis_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    workspace_fingerprint: Sha256
    source_pattern_run_id: UUID
    source_pattern_fingerprint: Sha256
    source_pattern_schema_version: str
    source_pattern_rule_version: str
    config: FindingConfig
    input_matches: tuple[FindingMatchInput, ...]
    summary: FindingSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]


class AnalysisRunRecord(FindingModel):
    analysis_run_id: UUID
    analysis_fingerprint: Sha256
    profile_id: UUID
    source_pattern_run_id: UUID
    analysis_schema_version: str
    analysis_rule_version: str
    created_at: datetime
    compatible: bool
    selected_by_default: bool


class AnalysisComputeStatus(StrEnum):
    COMPUTED = "computed"
    ALREADY_EXISTS = "already_exists"
    REPLACED = "replaced"


class AnalysisSaveResult(FindingModel):
    analysis_run_id: UUID
    analysis_fingerprint: Sha256
    status: AnalysisComputeStatus
    row_counts: dict[str, int]


class AnalysisComputeResult(FindingModel):
    analysis_run_id: UUID
    analysis_fingerprint: Sha256
    analysis_schema_version: str
    analysis_rule_version: str
    profile_id: UUID
    source_pattern_run_id: UUID
    status: AnalysisComputeStatus
    summary: FindingSummary
    row_counts: dict[str, int]
    warnings: tuple[str, ...]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


__all__ = [name for name in globals() if not name.startswith("_")]
