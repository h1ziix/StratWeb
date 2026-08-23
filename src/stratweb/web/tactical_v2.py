"""API and inspection UI for Tactical Intelligence V2."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from stratweb.adapters.persistence import (
    DuckDBOpponentRepository,
    DuckDBTacticalV2Repository,
    DuckDBTacticalV2SourceRepository,
)
from stratweb.application.tactical_v2 import (
    ComputeTacticalV2Service,
    TacticalV2QueryService,
)
from stratweb.domain.enums import Side
from stratweb.exceptions import (
    OpponentNotFoundError,
    TacticalV2ConfigurationError,
    TacticalV2NotFoundError,
)
from stratweb.tactical_v2.models import TacticalInsightType, TacticalV2Config
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template


def tactical_v2_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    opponents = DuckDBOpponentRepository(database_path)
    sources = DuckDBTacticalV2SourceRepository(database_path)
    repository = DuckDBTacticalV2Repository(database_path)
    compute = ComputeTacticalV2Service(opponents, sources, repository)
    query = TacticalV2QueryService(repository)

    @router.post(
        "/api/opponents/{profile_id}/tactical-v2/compute",
        tags=["tactical-v2"],
        response_model=None,
    )
    def compute_tactical_v2(
        request: Request,
        profile_id: UUID,
        heatmap_cell_size_units: Annotated[float, Query(gt=0)] = 512.0,
        force: bool = False,
    ) -> Response:
        require_localhost(request, "Tactical V2 computation")
        try:
            result = compute.compute(
                profile_id,
                config=TacticalV2Config(heatmap_cell_size_units=heatmap_cell_size_units),
                replace=force,
            )
        except TacticalV2ConfigurationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/opponents/{profile_id}/tactical-v2", status_code=303)
        return JSONResponse(content=result.model_dump(mode="json"))

    @router.get("/api/opponents/{profile_id}/tactical-v2/summary", tags=["tactical-v2"])
    def summary(profile_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return query.get_summary(profile_id, tactical_run_id=run_id).model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/tactical-v2/runs", tags=["tactical-v2"])
    def runs(profile_id: UUID) -> dict[str, Any]:
        values = query.list_runs(profile_id)
        return {
            "profile_id": str(profile_id),
            "count": len(values),
            "runs": [item.model_dump(mode="json") for item in values],
        }

    @router.get("/api/opponents/{profile_id}/tactical-v2/insights", tags=["tactical-v2"])
    def insights(
        profile_id: UUID,
        run_id: UUID | None = None,
        insight_type: TacticalInsightType | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 500,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        values = query.list_insights(
            profile_id,
            tactical_run_id=run_id,
            insight_type=insight_type,
            map_name=map_name,
            side=side,
            limit=limit,
            offset=offset,
        )
        return {
            "profile_id": str(profile_id),
            "count": len(values),
            "insights": [item.model_dump(mode="json") for item in values],
        }

    @router.get(
        "/api/opponents/{profile_id}/tactical-v2/insights/{insight_id}/evidence",
        tags=["tactical-v2"],
    )
    def evidence(profile_id: UUID, insight_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        values = query.list_evidence(profile_id, insight_id, tactical_run_id=run_id)
        return {
            "profile_id": str(profile_id),
            "insight_id": str(insight_id),
            "count": len(values),
            "evidence": [item.model_dump(mode="json") for item in values],
        }

    @router.get(
        "/ui/opponents/{profile_id}/tactical-v2",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def tactical_page(profile_id: UUID, run_id: UUID | None = None) -> HTMLResponse:
        profile = opponents.get_profile(profile_id)
        if profile is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
        try:
            selected = query.get_summary(profile_id, tactical_run_id=run_id)
            values = query.list_insights(
                profile_id, tactical_run_id=selected.tactical_run_id, limit=5000
            )
            regular = tuple(
                item for item in values if item.insight_type is not TacticalInsightType.HEATMAP_CELL
            )
            heatmap = tuple(
                item for item in values if item.insight_type is TacticalInsightType.HEATMAP_CELL
            )
            unavailable_reason = None
        except TacticalV2NotFoundError as exc:
            selected = None
            regular = ()
            heatmap = ()
            unavailable_reason = str(exc)
        return HTMLResponse(
            render_template(
                "opponents/tactical_v2.html",
                profile=profile,
                summary=selected,
                insights=regular,
                heatmap_cells=heatmap[:30],
                unavailable_reason=unavailable_reason,
                match_context=None,
            )
        )

    return router


__all__ = ["tactical_v2_router"]
