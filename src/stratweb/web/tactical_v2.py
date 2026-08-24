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
from stratweb.web.i18n import (
    LOCALE_COOKIE_MAX_AGE_SECONDS,
    LOCALE_COOKIE_NAME,
    SUPPORTED_LOCALES,
    normalize_locale,
    resolve_locale,
)
from stratweb.web.rendering import render_template
from stratweb.web.tactical_v2_presenter import TacticalV2Filters, build_tactical_v2_page


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
    def tactical_page(
        request: Request,
        profile_id: UUID,
        run_id: UUID | None = None,
        insight_type: Annotated[TacticalInsightType | None, Query(alias="type")] = None,
        map_name: Annotated[str | None, Query(alias="map", max_length=100)] = None,
        side: Side | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        lang: Annotated[str | None, Query(max_length=20)] = None,
    ) -> HTMLResponse:
        locale = resolve_locale(lang, request.cookies.get(LOCALE_COOKIE_NAME))
        profile = opponents.get_profile(profile_id)
        if profile is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
        try:
            selected = query.get_summary(profile_id, tactical_run_id=run_id)
            values = query.list_insights(
                profile_id, tactical_run_id=selected.tactical_run_id, limit=5000
            )
            page_view = build_tactical_v2_page(
                profile_id,
                selected.tactical_run_id,
                values,
                filters=TacticalV2Filters(
                    insight_type=insight_type,
                    map_name=map_name,
                    side=side,
                ),
                page=page,
            )
            unavailable_reason = None
        except TacticalV2NotFoundError as exc:
            selected = None
            page_view = None
            unavailable_reason = str(exc)
        response = HTMLResponse(
            render_template(
                "opponents/tactical_v2.html",
                locale=locale,
                profile=profile,
                summary=selected,
                page_view=page_view,
                unavailable_reason=unavailable_reason,
                match_context=None,
                locale_switcher=True,
                supported_locales=SUPPORTED_LOCALES,
            )
        )
        if lang is not None and normalize_locale(lang) is not None:
            response.set_cookie(
                LOCALE_COOKIE_NAME,
                locale,
                max_age=LOCALE_COOKIE_MAX_AGE_SECONDS,
                httponly=True,
                samesite="lax",
            )
        return response

    return router


__all__ = ["tactical_v2_router"]
