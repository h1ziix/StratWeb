"""Read-only composition service for the Stage 8.8 scouting report."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from stratweb.application.counter_strategy import CounterStrategyQueryService
from stratweb.application.findings import AnalysisFindingQueryService
from stratweb.application.readiness import FindingReadinessService
from stratweb.counter_strategy.models import (
    CounterStrategyRecommendation,
    CounterStrategyRunSummary,
    SkippedStrategyFinding,
)
from stratweb.counter_strategy.validation import CounterStrategyValidationEngine
from stratweb.counter_strategy.validation_models import (
    CounterStrategyValidationAudit,
    CounterStrategyValidationInput,
    StrategyValidationConfig,
)
from stratweb.findings.models import AnalysisFinding, AnalysisRunSummary
from stratweb.readiness.models import FindingReadinessAudit


class ScoutingReportSource(BaseModel):
    """One pinned, internally consistent source bundle for report rendering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: CounterStrategyRunSummary
    analysis: AnalysisRunSummary
    readiness: FindingReadinessAudit
    validation: CounterStrategyValidationAudit
    findings: tuple[AnalysisFinding, ...]
    recommendations: tuple[CounterStrategyRecommendation, ...]
    skipped_findings: tuple[SkippedStrategyFinding, ...]
    analysis_created_at: datetime | None = None
    strategy_created_at: datetime | None = None


class ScoutingReportService:
    def __init__(
        self,
        findings: AnalysisFindingQueryService,
        strategies: CounterStrategyQueryService,
        *,
        validation_engine: CounterStrategyValidationEngine | None = None,
    ) -> None:
        self._findings = findings
        self._strategies = strategies
        self._validation_engine = validation_engine or CounterStrategyValidationEngine()

    def get_source(
        self,
        profile_id: UUID,
        *,
        strategy_run_id: UUID | None = None,
        validation_config: StrategyValidationConfig | None = None,
    ) -> ScoutingReportSource:
        strategy = self._strategies.get_summary(profile_id, strategy_run_id=strategy_run_id)
        analysis = self._findings.get_summary(
            profile_id, analysis_run_id=strategy.source_analysis_run_id
        )
        findings = self._findings.list_findings(
            profile_id,
            analysis_run_id=analysis.analysis_run_id,
            limit=5000,
        )
        readiness = FindingReadinessService(self._findings).audit(
            profile_id,
            analysis_run_id=analysis.analysis_run_id,
            config=strategy.readiness_config,
        )
        recommendations = self._strategies.list_recommendations(
            profile_id,
            strategy_run_id=strategy.strategy_run_id,
            limit=5000,
        )
        skipped = self._strategies.list_skipped(
            profile_id, strategy_run_id=strategy.strategy_run_id
        )
        validation = self._validation_engine.validate(
            CounterStrategyValidationInput(
                strategy=strategy,
                analysis=analysis,
                readiness=readiness,
                findings=findings,
                recommendations=recommendations,
                skipped_findings=skipped,
            ),
            validation_config,
        )
        analysis_created_at = next(
            (
                item.created_at
                for item in self._findings.list_runs(profile_id)
                if item.analysis_run_id == analysis.analysis_run_id
            ),
            None,
        )
        strategy_created_at = next(
            (
                item.created_at
                for item in self._strategies.list_runs(profile_id)
                if item.strategy_run_id == strategy.strategy_run_id
            ),
            None,
        )
        return ScoutingReportSource(
            strategy=strategy,
            analysis=analysis,
            readiness=readiness,
            validation=validation,
            findings=findings,
            recommendations=recommendations,
            skipped_findings=skipped,
            analysis_created_at=analysis_created_at,
            strategy_created_at=strategy_created_at,
        )


__all__ = ["ScoutingReportService", "ScoutingReportSource"]
