"""Application services for deterministic Stage 8.7 counter-strategy runs."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.application.findings import AnalysisFindingQueryService
from stratweb.application.readiness import FindingReadinessService
from stratweb.counter_strategy.engine import CounterStrategyEngine
from stratweb.counter_strategy.models import (
    STRATEGY_RULE_VERSION,
    STRATEGY_SCHEMA_VERSION,
    CounterStrategyCategory,
    CounterStrategyComputeResult,
    CounterStrategyConfig,
    CounterStrategyInput,
    CounterStrategyRecommendation,
    CounterStrategyRunRecord,
    CounterStrategyRunSummary,
    SkippedStrategyFinding,
)
from stratweb.counter_strategy.validation import CounterStrategyValidationEngine
from stratweb.counter_strategy.validation_models import (
    CounterStrategyValidationAudit,
    CounterStrategyValidationInput,
    StrategyValidationConfig,
)
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import AnalysisFindingNotFoundError, CounterStrategyNotFoundError
from stratweb.ports import CounterStrategyRepository
from stratweb.readiness.models import FindingReadinessConfig


class ComputeCounterStrategiesService:
    def __init__(
        self,
        findings: AnalysisFindingQueryService,
        strategies: CounterStrategyRepository,
        *,
        engine: CounterStrategyEngine | None = None,
    ) -> None:
        self._findings = findings
        self._strategies = strategies
        self._engine = engine or CounterStrategyEngine()

    def compute(
        self,
        profile_id: UUID,
        *,
        readiness_config: FindingReadinessConfig | None = None,
        strategy_config: CounterStrategyConfig | None = None,
        replace: bool = False,
    ) -> CounterStrategyComputeResult:
        started = perf_counter()
        analysis = self._findings.get_summary(profile_id)
        findings = self._findings.list_findings(
            profile_id, analysis_run_id=analysis.analysis_run_id, limit=5000
        )
        readiness = FindingReadinessService(self._findings).audit(
            profile_id,
            analysis_run_id=analysis.analysis_run_id,
            config=readiness_config,
        )
        state = self._engine.compute(
            CounterStrategyInput(
                analysis_fingerprint=analysis.analysis_fingerprint,
                analysis_schema_version=analysis.analysis_schema_version,
                analysis_rule_version=analysis.analysis_rule_version,
                profile_id=profile_id,
                readiness=readiness,
                findings=findings,
            ),
            strategy_config,
        )
        saved = self._strategies.save_strategy(state, replace=replace)
        return CounterStrategyComputeResult(
            strategy_run_id=saved.strategy_run_id,
            strategy_fingerprint=saved.strategy_fingerprint,
            strategy_schema_version=STRATEGY_SCHEMA_VERSION,
            strategy_rule_version=STRATEGY_RULE_VERSION,
            profile_id=profile_id,
            source_analysis_run_id=analysis.analysis_run_id,
            status=saved.status,
            summary=state.summary,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )


class CounterStrategyQueryService:
    def __init__(
        self,
        findings: AnalysisFindingQueryService,
        strategies: CounterStrategyRepository,
    ) -> None:
        self._findings = findings
        self._strategies = strategies

    def get_summary(
        self, profile_id: UUID, *, strategy_run_id: UUID | None = None
    ) -> CounterStrategyRunSummary:
        if strategy_run_id is not None:
            result = self._strategies.get_summary_for_run(profile_id, strategy_run_id)
        else:
            try:
                analysis = self._findings.get_summary(profile_id)
            except AnalysisFindingNotFoundError as exc:
                raise CounterStrategyNotFoundError(
                    f"Compatible Stage 8.7 run not found for profile {profile_id}."
                ) from exc
            result = self._strategies.get_summary(
                profile_id, source_analysis_run_id=analysis.analysis_run_id
            )
        if result is None:
            raise CounterStrategyNotFoundError(
                f"Compatible Stage 8.7 run not found for profile {profile_id}."
            )
        return result

    def list_runs(self, profile_id: UUID) -> tuple[CounterStrategyRunRecord, ...]:
        try:
            analysis_run_id = self._findings.get_summary(profile_id).analysis_run_id
        except AnalysisFindingNotFoundError:
            analysis_run_id = None
        return self._strategies.list_runs(profile_id, current_analysis_run_id=analysis_run_id)

    def list_recommendations(
        self,
        profile_id: UUID,
        *,
        strategy_run_id: UUID | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        category: CounterStrategyCategory | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[CounterStrategyRecommendation, ...]:
        summary = self.get_summary(profile_id, strategy_run_id=strategy_run_id)
        return self._strategies.list_recommendations(
            profile_id,
            strategy_run_id=summary.strategy_run_id,
            map_name=map_name,
            side=side,
            buy_type=buy_type,
            category=category,
            limit=limit,
            offset=offset,
        )

    def get_recommendation(
        self,
        profile_id: UUID,
        recommendation_id: UUID,
        *,
        strategy_run_id: UUID | None = None,
    ) -> CounterStrategyRecommendation:
        summary = self.get_summary(profile_id, strategy_run_id=strategy_run_id)
        result = self._strategies.get_recommendation(
            profile_id, summary.strategy_run_id, recommendation_id
        )
        if result is None:
            raise CounterStrategyNotFoundError(
                f"Counter-strategy recommendation not found: {recommendation_id}"
            )
        return result

    def list_skipped(
        self, profile_id: UUID, *, strategy_run_id: UUID | None = None
    ) -> tuple[SkippedStrategyFinding, ...]:
        summary = self.get_summary(profile_id, strategy_run_id=strategy_run_id)
        return self._strategies.list_skipped(summary.strategy_run_id)

    def delete(self, profile_id: UUID) -> int:
        return self._strategies.delete_strategies(profile_id)


class ValidateCounterStrategiesService:
    def __init__(
        self,
        findings: AnalysisFindingQueryService,
        strategies: CounterStrategyQueryService,
        *,
        engine: CounterStrategyValidationEngine | None = None,
    ) -> None:
        self._findings = findings
        self._strategies = strategies
        self._engine = engine or CounterStrategyValidationEngine()

    def validate(
        self,
        profile_id: UUID,
        *,
        strategy_run_id: UUID | None = None,
        config: StrategyValidationConfig | None = None,
    ) -> CounterStrategyValidationAudit:
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
        return self._engine.validate(
            CounterStrategyValidationInput(
                strategy=strategy,
                analysis=analysis,
                readiness=readiness,
                findings=findings,
                recommendations=recommendations,
                skipped_findings=skipped,
            ),
            config,
        )


__all__ = [
    "ComputeCounterStrategiesService",
    "CounterStrategyQueryService",
    "ValidateCounterStrategiesService",
]
