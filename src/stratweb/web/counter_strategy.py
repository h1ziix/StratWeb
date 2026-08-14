"""JSON endpoints for deterministic Stage 8.7 counter-strategy runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request

from stratweb.adapters.persistence import (
    DuckDBAnalysisRepository,
    DuckDBCounterStrategyRepository,
    DuckDBPatternRepository,
)
from stratweb.application.counter_strategy import (
    ComputeCounterStrategiesService,
    CounterStrategyQueryService,
    ValidateCounterStrategiesService,
)
from stratweb.application.findings import AnalysisFindingQueryService
from stratweb.counter_strategy.models import CounterStrategyCategory, CounterStrategyConfig
from stratweb.counter_strategy.validation_models import StrategyValidationConfig
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.readiness.models import FindingReadinessConfig
from stratweb.web.context import require_localhost


def counter_strategy_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    finding_query = AnalysisFindingQueryService(
        DuckDBPatternRepository(database_path), DuckDBAnalysisRepository(database_path)
    )
    repository = DuckDBCounterStrategyRepository(database_path)
    compute = ComputeCounterStrategiesService(finding_query, repository)
    query = CounterStrategyQueryService(finding_query, repository)
    validation = ValidateCounterStrategiesService(finding_query, query)

    @router.post(
        "/api/opponents/{profile_id}/analysis/strategies/compute",
        tags=["counter-strategy"],
    )
    def compute_strategies(
        request: Request,
        profile_id: UUID,
        minimum_corpus_matches: Annotated[int, Query(ge=1)] = 20,
        minimum_finding_matches: Annotated[int, Query(ge=1)] = 2,
        force: bool = False,
    ) -> dict[str, Any]:
        require_localhost(request, "Counter-strategy computation")
        result = compute.compute(
            profile_id,
            readiness_config=FindingReadinessConfig(
                minimum_corpus_matches=minimum_corpus_matches,
                minimum_finding_matches=minimum_finding_matches,
            ),
            strategy_config=CounterStrategyConfig(),
            replace=force,
        )
        return result.model_dump(mode="json")

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies/summary",
        tags=["counter-strategy"],
    )
    def summary(profile_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return query.get_summary(profile_id, strategy_run_id=run_id).model_dump(mode="json")

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies/runs",
        tags=["counter-strategy"],
    )
    def runs(profile_id: UUID) -> dict[str, Any]:
        records = query.list_runs(profile_id)
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "runs": [item.model_dump(mode="json") for item in records],
        }

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies",
        tags=["counter-strategy"],
    )
    def recommendations(
        profile_id: UUID,
        run_id: UUID | None = None,
        map_name: Annotated[str | None, Query(alias="map")] = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        category: CounterStrategyCategory | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        records = query.list_recommendations(
            profile_id,
            strategy_run_id=run_id,
            map_name=map_name,
            side=side,
            buy_type=buy_type,
            category=category,
            limit=limit,
            offset=offset,
        )
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "recommendations": [item.model_dump(mode="json") for item in records],
        }

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies/skipped",
        tags=["counter-strategy"],
    )
    def skipped(profile_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        records = query.list_skipped(profile_id, strategy_run_id=run_id)
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "skipped": [item.model_dump(mode="json") for item in records],
        }

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies/validation",
        tags=["counter-strategy-validation"],
    )
    def validation_audit(
        profile_id: UUID,
        run_id: UUID | None = None,
        minimum_corpus_matches: Annotated[int, Query(ge=1)] = 20,
        require_both_sides: bool = True,
        require_recommendations: bool = True,
    ) -> dict[str, Any]:
        result = validation.validate(
            profile_id,
            strategy_run_id=run_id,
            config=StrategyValidationConfig(
                minimum_corpus_matches=minimum_corpus_matches,
                require_both_sides=require_both_sides,
                require_at_least_one_recommendation=require_recommendations,
            ),
        )
        return result.model_dump(mode="json")

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies/{recommendation_id}",
        tags=["counter-strategy"],
    )
    def recommendation(
        profile_id: UUID, recommendation_id: UUID, run_id: UUID | None = None
    ) -> dict[str, Any]:
        return query.get_recommendation(
            profile_id, recommendation_id, strategy_run_id=run_id
        ).model_dump(mode="json")

    @router.get(
        "/api/opponents/{profile_id}/analysis/strategies/{recommendation_id}/evidence",
        tags=["counter-strategy"],
    )
    def evidence(
        profile_id: UUID, recommendation_id: UUID, run_id: UUID | None = None
    ) -> dict[str, Any]:
        record = query.get_recommendation(profile_id, recommendation_id, strategy_run_id=run_id)
        return {
            "strategy_run_id": str(record.strategy_run_id),
            "recommendation_id": str(record.recommendation_id),
            "source_finding_id": str(record.source_finding_id),
            "count": len(record.evidence_references),
            "evidence": [item.model_dump(mode="json") for item in record.evidence_references],
        }

    return router


__all__ = ["counter_strategy_router"]
