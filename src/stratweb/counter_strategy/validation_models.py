"""Typed Stage 8.7.1 corpus and recommendation acceptance contracts."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.counter_strategy.models import (
    CounterStrategyRecommendation,
    CounterStrategyRunSummary,
    SkippedStrategyFinding,
)
from stratweb.findings.models import AnalysisFinding, AnalysisRunSummary
from stratweb.readiness.models import FindingReadinessAudit

VALIDATION_SCHEMA_VERSION = "1.0.0"
VALIDATION_RULE_VERSION = "counter_strategy_validation_v1"


class ValidationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StrategyAcceptanceStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"


class ValidationCheckStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    BLOCKED = "blocked"
    FAILED = "failed"


class ValidationCheckCode(StrEnum):
    SOURCE_RUN_INTEGRITY = "source_run_integrity"
    ANALYSIS_INPUT_COUNTS = "analysis_input_counts"
    READINESS_REPRODUCIBILITY = "readiness_reproducibility"
    COMPLETE_FINDING_CLASSIFICATION = "complete_finding_classification"
    CORPUS_SIZE = "corpus_size"
    BOTH_SIDES_COVERED = "both_sides_covered"
    BUY_CONTEXT_COVERAGE = "buy_context_coverage"
    PUBLISHED_RECOMMENDATIONS = "published_recommendations"
    READY_GATE_ENFORCED = "ready_gate_enforced"
    STATISTICS_PRESERVED = "statistics_preserved"
    EVIDENCE_PRESERVED = "evidence_preserved"
    EVIDENCE_WITHIN_CORPUS = "evidence_within_corpus"
    DUPLICATE_RECOMMENDATIONS = "duplicate_recommendations"
    CAUSALITY_GUARD = "causality_guard"


class StrategyValidationConfig(ValidationModel):
    minimum_corpus_matches: int = Field(default=20, ge=1)
    require_both_sides: bool = True
    require_at_least_one_recommendation: bool = True
    warn_unknown_buy_context: bool = True


class ValidationCheck(ValidationModel):
    code: ValidationCheckCode
    status: ValidationCheckStatus
    message: str = Field(min_length=1)
    observed: int | float | str | bool | None = None
    required: int | float | str | bool | None = None
    affected_ids: tuple[UUID, ...] = ()


class CorpusCoverage(ValidationModel):
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    excluded_matches: int = Field(ge=0)
    maps: tuple[str, ...] = ()
    sides: tuple[str, ...] = ()
    buy_types: tuple[str, ...] = ()
    source_findings: int = Field(ge=0)
    ready_findings: int = Field(ge=0)
    recommendations: int = Field(ge=0)
    skipped_findings: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    evidence_matches: int = Field(ge=0)
    evidence_rounds: int = Field(ge=0)


class RuleCoverage(ValidationModel):
    rule_id: str
    recommendations: int = Field(ge=0)
    evidence_references: int = Field(ge=0)
    evidence_matches: int = Field(ge=0)


class CounterStrategyValidationInput(ValidationModel):
    strategy: CounterStrategyRunSummary
    analysis: AnalysisRunSummary
    readiness: FindingReadinessAudit
    findings: tuple[AnalysisFinding, ...]
    recommendations: tuple[CounterStrategyRecommendation, ...]
    skipped_findings: tuple[SkippedStrategyFinding, ...]


class CounterStrategyValidationAudit(ValidationModel):
    validation_schema_version: str = VALIDATION_SCHEMA_VERSION
    validation_rule_version: str = VALIDATION_RULE_VERSION
    validation_id: UUID
    validation_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    source_analysis_run_id: UUID
    source_analysis_fingerprint: Sha256
    readiness_audit_id: UUID
    readiness_fingerprint: Sha256
    config: StrategyValidationConfig
    status: StrategyAcceptanceStatus
    coverage: CorpusCoverage
    rule_coverage: tuple[RuleCoverage, ...]
    checks: tuple[ValidationCheck, ...]
    blockers: tuple[ValidationCheckCode, ...] = ()
    failures: tuple[ValidationCheckCode, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status(self) -> CounterStrategyValidationAudit:
        expected = (
            StrategyAcceptanceStatus.FAILED
            if self.failures
            else StrategyAcceptanceStatus.BLOCKED
            if self.blockers
            else StrategyAcceptanceStatus.PASSED
        )
        if self.status is not expected:
            raise ValueError("acceptance status does not match blockers and failures")
        return self


__all__ = [name for name in globals() if not name.startswith("_")]
