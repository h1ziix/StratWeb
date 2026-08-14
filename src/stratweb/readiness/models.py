"""Typed contracts for the Stage 8.6.1 finding readiness gate."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256
from stratweb.findings.models import AnalysisFinding, AnalysisRunSummary

READINESS_SCHEMA_VERSION = "1.0.0"
READINESS_RULE_VERSION = "finding_readiness_v1"


class ReadinessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FindingReadinessStatus(StrEnum):
    READY = "ready"
    LIMITED = "limited"
    BLOCKED = "blocked"


class ReadinessReason(StrEnum):
    CORPUS_BELOW_MINIMUM = "corpus_below_minimum"
    FINDING_MATCHES_BELOW_MINIMUM = "finding_matches_below_minimum"
    FINDING_SAMPLE_BELOW_MINIMUM = "finding_sample_below_minimum"
    SOURCE_PATTERN_PARTIAL = "source_pattern_partial"
    BUY_TYPE_UNAVAILABLE = "buy_type_unavailable"
    EVIDENCE_TICK_PARTIAL = "evidence_tick_partial"


class FindingReadinessConfig(ReadinessModel):
    """Explicit policy used before Stage 8.7 may consume a finding."""

    minimum_corpus_matches: int = Field(default=20, ge=1)
    minimum_finding_matches: int = Field(default=2, ge=1)
    block_partial_source: bool = True
    require_known_buy_type: bool = True
    require_all_evidence_ticks: bool = False


class FindingReadinessRecord(ReadinessModel):
    finding_id: UUID
    status: FindingReadinessStatus
    eligible_for_stage_8_7: bool
    blocking_reasons: tuple[ReadinessReason, ...] = ()
    limitations: tuple[ReadinessReason, ...] = ()
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    denominator_match_count: int = Field(ge=1)
    evidence_with_tick: int = Field(ge=0)
    evidence_total: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_status(self) -> FindingReadinessRecord:
        expected = (
            FindingReadinessStatus.BLOCKED
            if self.blocking_reasons
            else FindingReadinessStatus.LIMITED
            if self.limitations
            else FindingReadinessStatus.READY
        )
        if self.status is not expected:
            raise ValueError("finding readiness status does not match its reasons")
        if self.eligible_for_stage_8_7 != (expected is FindingReadinessStatus.READY):
            raise ValueError("only ready findings may be eligible for Stage 8.7")
        if self.evidence_with_tick > self.evidence_total:
            raise ValueError("evidence_with_tick cannot exceed evidence_total")
        return self


class FindingReadinessSummary(ReadinessModel):
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    required_corpus_matches: int = Field(ge=1)
    findings: int = Field(ge=0)
    ready_findings: int = Field(ge=0)
    limited_findings: int = Field(ge=0)
    blocked_findings: int = Field(ge=0)
    eligible_for_stage_8_7: int = Field(ge=0)
    stage_8_7_ready: bool
    reason_counts: dict[ReadinessReason, int]

    @model_validator(mode="after")
    def validate_counts(self) -> FindingReadinessSummary:
        if self.ready_findings + self.limited_findings + self.blocked_findings != self.findings:
            raise ValueError("readiness status counts must equal findings")
        if self.eligible_for_stage_8_7 != self.ready_findings:
            raise ValueError("eligible count must equal ready findings")
        if self.stage_8_7_ready != (self.findings > 0 and self.ready_findings > 0):
            raise ValueError("stage readiness flag does not match ready findings")
        return self


class FindingReadinessInput(ReadinessModel):
    analysis: AnalysisRunSummary
    findings: tuple[AnalysisFinding, ...]


class FindingReadinessAudit(ReadinessModel):
    readiness_schema_version: str = READINESS_SCHEMA_VERSION
    readiness_rule_version: str = READINESS_RULE_VERSION
    audit_id: UUID
    audit_fingerprint: Sha256
    configuration_hash: Sha256
    profile_id: UUID
    source_analysis_run_id: UUID
    source_analysis_fingerprint: Sha256
    source_analysis_schema_version: str
    source_analysis_rule_version: str
    config: FindingReadinessConfig
    summary: FindingReadinessSummary
    records: tuple[FindingReadinessRecord, ...]
    warnings: tuple[str, ...] = ()


__all__ = [name for name in globals() if not name.startswith("_")]
