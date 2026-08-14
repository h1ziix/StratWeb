"""JSON endpoints for deterministic Stage 8.5 cross-match patterns."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBPatternRepository,
    DuckDBRoundFeatureRepository,
)
from stratweb.application.patterns import (
    ComputeCrossMatchPatternsService,
    PatternQueryService,
)
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import OpponentNotFoundError, PatternConfigurationError
from stratweb.patterns.models import PatternAvailability, PatternConfig, PatternType
from stratweb.web.context import require_localhost


def pattern_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    repository = DuckDBPatternRepository(database_path)
    query_service = PatternQueryService(repository)
    compute_service = ComputeCrossMatchPatternsService(
        DuckDBOpponentRepository(database_path),
        DuckDBMatchRepository(database_path),
        DuckDBRoundFeatureRepository(database_path),
        repository,
    )

    @router.post("/api/opponents/{profile_id}/patterns/compute", tags=["patterns"])
    def compute_patterns(
        request: Request,
        profile_id: UUID,
        minimum_corpus_matches: Annotated[int, Query(ge=1)] = 20,
        minimum_sample_size: Annotated[int, Query(ge=1)] = 5,
        include_partial_features: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        require_localhost(request, "Cross-match pattern computation")
        try:
            result = compute_service.compute(
                profile_id,
                config=PatternConfig(
                    minimum_corpus_matches=minimum_corpus_matches,
                    minimum_sample_size=minimum_sample_size,
                    include_partial_features=include_partial_features,
                ),
                replace=force,
            )
        except OpponentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PatternConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return result.model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/patterns/summary", tags=["patterns"])
    def pattern_summary(
        profile_id: UUID,
        run_id: UUID | None = None,
    ) -> dict[str, Any]:
        return query_service.get_summary(profile_id, pattern_run_id=run_id).model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/patterns/runs", tags=["patterns"])
    def pattern_runs(profile_id: UUID) -> dict[str, Any]:
        runs = query_service.list_runs(profile_id)
        return {
            "profile_id": str(profile_id),
            "count": len(runs),
            "runs": [item.model_dump(mode="json") for item in runs],
        }

    @router.get("/api/opponents/{profile_id}/patterns", tags=["patterns"])
    def list_patterns(
        profile_id: UUID,
        run_id: UUID | None = None,
        map_name: Annotated[str | None, Query(alias="map")] = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        pattern_type: Annotated[PatternType | None, Query(alias="type")] = None,
        availability: PatternAvailability | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        records = query_service.list_patterns(
            profile_id,
            pattern_run_id=run_id,
            map_name=map_name,
            side=side,
            buy_type=buy_type,
            pattern_type=pattern_type,
            availability=availability,
            limit=limit,
            offset=offset,
        )
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "patterns": [item.model_dump(mode="json") for item in records],
        }

    return router


__all__ = ["pattern_router"]
