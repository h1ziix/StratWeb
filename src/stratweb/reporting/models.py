"""Stable typed contract for complete evidence report exports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from stratweb.application.canonical_models import Sha256
from stratweb.counter_strategy.models import (
    CounterStrategyRecommendation,
    SkippedStrategyFinding,
)
from stratweb.counter_strategy.validation_models import CounterStrategyValidationAudit
from stratweb.findings.models import AnalysisFinding
from stratweb.readiness.models import FindingReadinessAudit

REPORT_EXPORT_SCHEMA_VERSION = "1.0.0"
REPORT_EXPORT_RULE_VERSION = "evidence_report_export_v1"


class ExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReportExportVersions(ExportModel):
    opponent_schema_version: str
    opponent_identity_rule_version: str
    opponent_overlap_rule_version: str
    analysis_schema_version: str
    analysis_rule_version: str
    source_pattern_schema_version: str
    source_pattern_rule_version: str
    readiness_schema_version: str
    readiness_rule_version: str
    strategy_schema_version: str
    strategy_rule_version: str
    validation_schema_version: str
    validation_rule_version: str


class ReportExportScope(ExportModel):
    selected_matches: int = Field(ge=0)
    included_matches: int = Field(ge=0)
    excluded_matches: int = Field(ge=0)
    required_matches: int = Field(ge=1)
    maps: tuple[str, ...]
    sides: tuple[str, ...]
    buy_types: tuple[str, ...]
    source_findings: int = Field(ge=0)
    ready_findings: int = Field(ge=0)
    recommendations: int = Field(ge=0)
    evidence_references: int = Field(ge=0)


class ReportExportCorpusMatch(ExportModel):
    match_id: UUID
    demo_file_id: UUID | None = None
    original_file_name: str | None = None
    demo_sha256: Sha256 | None = None
    map_name: str
    opponent_team_name: str | None = None
    round_count: int | None = Field(default=None, ge=0)
    input_status: str
    exclusion_reason: str | None = None


class ScoutingReportExport(ExportModel):
    export_schema_version: str = REPORT_EXPORT_SCHEMA_VERSION
    export_rule_version: str = REPORT_EXPORT_RULE_VERSION
    export_fingerprint: Sha256
    profile_id: UUID
    display_name: str
    analysis_created_at: datetime | None = None
    strategy_created_at: datetime | None = None
    analysis_run_id: UUID
    analysis_fingerprint: Sha256
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    acceptance_status: str
    versions: ReportExportVersions
    scope: ReportExportScope
    corpus: tuple[ReportExportCorpusMatch, ...]
    validation: CounterStrategyValidationAudit
    readiness: FindingReadinessAudit
    findings: tuple[AnalysisFinding, ...]
    recommendations: tuple[CounterStrategyRecommendation, ...]
    skipped_findings: tuple[SkippedStrategyFinding, ...]
    sample_limitations: tuple[str, ...]
    warnings: tuple[str, ...]


__all__ = [name for name in globals() if not name.startswith("_")]
