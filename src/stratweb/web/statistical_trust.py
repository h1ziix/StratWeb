"""API and compact UI for deterministic Stage 9.4 statistical trust."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from stratweb.adapters.persistence import (
    DuckDBOpponentRepository,
    DuckDBPatternRepository,
    DuckDBStatisticalTrustRepository,
)
from stratweb.application.statistical_trust import (
    ComputeStatisticalTrustService,
    StatisticalTrustQueryService,
)
from stratweb.exceptions import (
    OpponentNotFoundError,
    PatternNotFoundError,
    StatisticalTrustNotFoundError,
)
from stratweb.statistical_trust.models import StatisticalTrustConfig, TrustDecision
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template


def statistical_trust_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    patterns = DuckDBPatternRepository(database_path)
    repository = DuckDBStatisticalTrustRepository(database_path)
    opponents = DuckDBOpponentRepository(database_path)
    compute = ComputeStatisticalTrustService(patterns, repository)
    query = StatisticalTrustQueryService(patterns, repository)

    @router.post(
        "/api/opponents/{profile_id}/statistical-trust/compute",
        tags=["statistical-trust"],
        response_model=None,
    )
    def compute_trust(
        request: Request,
        profile_id: UUID,
        minimum_cluster_matches: Annotated[int, Query(ge=2)] = 5,
        minimum_effect_size: Annotated[float, Query(ge=0, lt=1)] = 0.1,
        false_discovery_rate: Annotated[float, Query(gt=0, lt=1)] = 0.05,
        force: bool = False,
    ) -> Response:
        require_localhost(request, "Statistical trust computation")
        try:
            result = compute.compute(
                profile_id,
                config=StatisticalTrustConfig(
                    minimum_cluster_matches=minimum_cluster_matches,
                    minimum_effect_size=minimum_effect_size,
                    false_discovery_rate=false_discovery_rate,
                ),
                replace=force,
            )
        except PatternNotFoundError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(
                f"/ui/opponents/{profile_id}/statistical-trust", status_code=303
            )
        return JSONResponse(content=result.model_dump(mode="json"))

    @router.get(
        "/api/opponents/{profile_id}/statistical-trust/summary",
        tags=["statistical-trust"],
    )
    def summary(profile_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return query.get_summary(profile_id, trust_run_id=run_id).model_dump(mode="json")

    @router.get(
        "/api/opponents/{profile_id}/statistical-trust/runs",
        tags=["statistical-trust"],
    )
    def runs(profile_id: UUID) -> dict[str, Any]:
        records = query.list_runs(profile_id)
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "runs": [item.model_dump(mode="json") for item in records],
        }

    @router.get(
        "/api/opponents/{profile_id}/statistical-trust/assessments",
        tags=["statistical-trust"],
    )
    def assessments(
        profile_id: UUID,
        run_id: UUID | None = None,
        decision: TrustDecision | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        records = query.list_assessments(
            profile_id,
            trust_run_id=run_id,
            decision=decision,
            limit=limit,
            offset=offset,
        )
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "assessments": [item.model_dump(mode="json") for item in records],
        }

    @router.get(
        "/ui/opponents/{profile_id}/statistical-trust",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def trust_page(profile_id: UUID, run_id: UUID | None = None) -> HTMLResponse:
        profile = opponents.get_profile(profile_id)
        if profile is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
        try:
            selected = query.get_summary(profile_id, trust_run_id=run_id)
            rows = query.list_assessments(
                profile_id, trust_run_id=selected.trust_run_id, limit=5000
            )
            unavailable_reason = None
        except StatisticalTrustNotFoundError as exc:
            selected = None
            rows = ()
            unavailable_reason = str(exc)
        return HTMLResponse(
            render_template(
                "opponents/statistical_trust.html",
                profile=profile,
                summary=selected,
                assessments=rows,
                unavailable_reason=unavailable_reason,
                match_context=None,
            )
        )

    return router


__all__ = ["statistical_trust_router"]
