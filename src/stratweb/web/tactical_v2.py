"""API and inspection UI for Tactical Intelligence V2."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from stratweb.adapters.persistence import (
    DuckDBAnalysisRepository,
    DuckDBAnalystNoteRepository,
    DuckDBCounterStrategyRepository,
    DuckDBOpponentRepository,
    DuckDBPatternRepository,
    DuckDBTacticalV2Repository,
    DuckDBTacticalV2SourceRepository,
)
from stratweb.application.analyst_notes import ANALYST_NOTE_MAX_LENGTH
from stratweb.application.counter_strategy import CounterStrategyQueryService
from stratweb.application.findings import AnalysisFindingQueryService
from stratweb.application.opponent_models import OpponentProfile, OpponentSubjectType
from stratweb.application.tactical_v2 import (
    ComputeTacticalV2Service,
    TacticalV2QueryService,
)
from stratweb.domain.enums import Side
from stratweb.exceptions import (
    CounterStrategyNotFoundError,
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
from stratweb.web.tactical_evidence_presenter import build_tactical_evidence_page
from stratweb.web.tactical_v2_presenter import TacticalV2Filters, build_tactical_v2_page


def tactical_v2_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    opponents = DuckDBOpponentRepository(database_path)
    sources = DuckDBTacticalV2SourceRepository(database_path)
    repository = DuckDBTacticalV2Repository(database_path)
    compute = ComputeTacticalV2Service(opponents, sources, repository)
    query = TacticalV2QueryService(repository)
    strategy_query = CounterStrategyQueryService(
        AnalysisFindingQueryService(
            DuckDBPatternRepository(database_path), DuckDBAnalysisRepository(database_path)
        ),
        DuckDBCounterStrategyRepository(database_path),
    )
    notes = DuckDBAnalystNoteRepository(database_path)

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
        _require_team_profile(opponents, profile_id)
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
        _require_team_profile(opponents, profile_id)
        return query.get_summary(profile_id, tactical_run_id=run_id).model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/tactical-v2/runs", tags=["tactical-v2"])
    def runs(profile_id: UUID) -> dict[str, Any]:
        _require_team_profile(opponents, profile_id)
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
        _require_team_profile(opponents, profile_id)
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
        _require_team_profile(opponents, profile_id)
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
        profile = _require_team_profile(opponents, profile_id)
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
        try:
            strategy_query.get_summary(profile_id)
            report_ready = True
        except CounterStrategyNotFoundError:
            report_ready = False
        response = HTMLResponse(
            render_template(
                "opponents/tactical_v2.html",
                locale=locale,
                profile=profile,
                summary=selected,
                page_view=page_view,
                unavailable_reason=unavailable_reason,
                report_ready=report_ready,
                match_context=None,
                locale_switcher=True,
                supported_locales=SUPPORTED_LOCALES,
            )
        )
        _remember_locale(response, lang, locale)
        return response

    @router.get(
        "/ui/opponents/{profile_id}/tactical-v2/insights/{insight_id}/evidence",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def tactical_evidence_page(
        request: Request,
        profile_id: UUID,
        insight_id: UUID,
        run_id: UUID | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        lang: Annotated[str | None, Query(max_length=20)] = None,
        note_status: Literal["saved", "deleted"] | None = None,
    ) -> HTMLResponse:
        locale = resolve_locale(lang, request.cookies.get(LOCALE_COOKIE_NAME))
        profile = _require_team_profile(opponents, profile_id)
        try:
            selected = query.get_summary(profile_id, tactical_run_id=run_id)
            insight = query.get_insight(
                profile_id,
                insight_id,
                tactical_run_id=selected.tactical_run_id,
            )
            evidence_values = query.list_evidence(
                profile_id,
                insight_id,
                tactical_run_id=selected.tactical_run_id,
            )
        except TacticalV2NotFoundError:
            response = HTMLResponse(
                render_template(
                    "opponents/tactical_evidence_error.html",
                    locale=locale,
                    profile=profile,
                    error_title_key="evidence.error.not_found_title",
                    error_detail_key="evidence.error.not_found",
                    match_context=None,
                    locale_switcher=True,
                    supported_locales=SUPPORTED_LOCALES,
                ),
                status_code=404,
            )
            _remember_locale(response, lang, locale)
            return response
        page_view = build_tactical_evidence_page(
            selected,
            insight,
            evidence_values,
            page=page,
        )
        response = HTMLResponse(
            render_template(
                "opponents/tactical_evidence.html",
                locale=locale,
                profile=profile,
                summary=selected,
                page_view=page_view,
                analyst_note=notes.get(
                    profile_id,
                    selected.tactical_run_id,
                    insight.insight_id,
                ),
                analyst_note_max_length=ANALYST_NOTE_MAX_LENGTH,
                note_status=note_status,
                match_context=None,
                locale_switcher=True,
                supported_locales=SUPPORTED_LOCALES,
            )
        )
        _remember_locale(response, lang, locale)
        return response

    @router.post(
        "/ui/opponents/{profile_id}/tactical-v2/insights/{insight_id}/note",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def save_analyst_note(
        request: Request,
        profile_id: UUID,
        insight_id: UUID,
        run_id: UUID,
        body: Annotated[str, Form()] = "",
    ) -> Response:
        require_localhost(request, "Analyst note editing")
        locale = resolve_locale(None, request.cookies.get(LOCALE_COOKIE_NAME))
        profile = _require_team_profile(opponents, profile_id)
        try:
            query.get_insight(profile_id, insight_id, tactical_run_id=run_id)
            note = notes.save(profile_id, run_id, insight_id, body)
        except TacticalV2NotFoundError:
            return _note_error_response(locale, profile, status_code=404)
        except ValueError:
            return _note_error_response(locale, profile, status_code=422, invalid=True)
        if "text/html" not in request.headers.get("accept", ""):
            return JSONResponse(content=note.model_dump(mode="json"))
        return RedirectResponse(
            _evidence_note_href(profile_id, insight_id, run_id, "saved"),
            status_code=303,
        )

    @router.post(
        "/ui/opponents/{profile_id}/tactical-v2/insights/{insight_id}/note/delete",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def delete_analyst_note(
        request: Request,
        profile_id: UUID,
        insight_id: UUID,
        run_id: UUID,
    ) -> Response:
        require_localhost(request, "Analyst note editing")
        locale = resolve_locale(None, request.cookies.get(LOCALE_COOKIE_NAME))
        profile = _require_team_profile(opponents, profile_id)
        try:
            query.get_insight(profile_id, insight_id, tactical_run_id=run_id)
        except TacticalV2NotFoundError:
            return _note_error_response(locale, profile, status_code=404)
        deleted = notes.delete(profile_id, run_id, insight_id)
        if "text/html" not in request.headers.get("accept", ""):
            return JSONResponse(content={"deleted": deleted})
        return RedirectResponse(
            _evidence_note_href(profile_id, insight_id, run_id, "deleted"),
            status_code=303,
        )

    return router


def _require_team_profile(opponents: DuckDBOpponentRepository, profile_id: UUID) -> OpponentProfile:
    profile = opponents.get_profile(profile_id)
    if profile is None:
        raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
    if profile.subject_type is OpponentSubjectType.PLAYER:
        raise HTTPException(
            status_code=409,
            detail="Командный тактический обзор недоступен для профиля одного игрока.",
        )
    return profile


def _remember_locale(response: Response, requested: str | None, resolved: str) -> None:
    if requested is None or normalize_locale(requested) is None:
        return
    response.set_cookie(
        LOCALE_COOKIE_NAME,
        resolved,
        max_age=LOCALE_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )


def _evidence_note_href(
    profile_id: UUID,
    insight_id: UUID,
    run_id: UUID,
    status: Literal["saved", "deleted"],
) -> str:
    return (
        f"/ui/opponents/{profile_id}/tactical-v2/insights/{insight_id}/evidence"
        f"?run_id={run_id}&note_status={status}#analyst-note"
    )


def _note_error_response(
    locale: str,
    profile: OpponentProfile,
    *,
    status_code: int,
    invalid: bool = False,
) -> HTMLResponse:
    return HTMLResponse(
        render_template(
            "opponents/tactical_evidence_error.html",
            locale=locale,
            profile=profile,
            error_title_key=(
                "evidence.note.invalid_title" if invalid else "evidence.error.not_found_title"
            ),
            error_detail_key=("evidence.note.invalid" if invalid else "evidence.error.not_found"),
            match_context=None,
            locale_switcher=True,
            supported_locales=SUPPORTED_LOCALES,
        ),
        status_code=status_code,
    )


__all__ = ["tactical_v2_router"]
