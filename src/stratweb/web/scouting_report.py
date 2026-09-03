"""Server-rendered scouting report and Stage 8.9 evidence exports."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from stratweb.adapters.persistence import (
    DuckDBAnalysisRepository,
    DuckDBCounterStrategyRepository,
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBPatternRepository,
    DuckDBRoundFeatureRepository,
    DuckDBTeamNameRepository,
)
from stratweb.application.counter_strategy import (
    ComputeCounterStrategiesService,
    CounterStrategyQueryService,
)
from stratweb.application.findings import (
    AnalysisFindingQueryService,
    ComputeAnalysisFindingsService,
)
from stratweb.application.opponent_models import OpponentWorkspace
from stratweb.application.opponents import OpponentWorkspaceService
from stratweb.application.patterns import ComputeCrossMatchPatternsService
from stratweb.application.report_preparation import (
    PrepareScoutingReportService,
    ReportPreparationUnavailableError,
)
from stratweb.application.scouting_reports import ScoutingReportService
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import (
    CounterStrategyNotFoundError,
    OpponentNotFoundError,
    PersistenceError,
)
from stratweb.patterns.models import PatternType
from stratweb.reporting import ScoutingReportExporter, ScoutingReportPdfRenderer
from stratweb.reporting.models import ScoutingReportExport
from stratweb.reporting.pdf import PdfFontUnavailableError
from stratweb.reporting.presentation import (
    check_label,
    check_message,
    finding_observation,
    finding_title,
    limitation_label,
    status_label,
    warning_label,
)
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template
from stratweb.web.view_models import (
    ScoutingReportFilters,
    build_coach_report_page,
    build_match_cheat_sheet_page,
    build_scouting_report_detail,
    build_scouting_report_page,
)

logger = logging.getLogger(__name__)


def scouting_report_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    opponents = OpponentWorkspaceService(
        DuckDBOpponentRepository(database_path),
        DuckDBMatchRepository(database_path),
        DuckDBTeamNameRepository(database_path),
    )
    finding_query = AnalysisFindingQueryService(
        DuckDBPatternRepository(database_path), DuckDBAnalysisRepository(database_path)
    )
    strategy_query = CounterStrategyQueryService(
        finding_query, DuckDBCounterStrategyRepository(database_path)
    )
    reports = ScoutingReportService(finding_query, strategy_query)
    preparation = PrepareScoutingReportService(
        ComputeCrossMatchPatternsService(
            DuckDBOpponentRepository(database_path),
            DuckDBMatchRepository(database_path),
            DuckDBRoundFeatureRepository(database_path),
            DuckDBPatternRepository(database_path),
        ),
        ComputeAnalysisFindingsService(
            DuckDBPatternRepository(database_path),
            DuckDBMatchRepository(database_path),
            DuckDBAnalysisRepository(database_path),
        ),
        ComputeCounterStrategiesService(
            finding_query, DuckDBCounterStrategyRepository(database_path)
        ),
    )
    exporter = ScoutingReportExporter()
    pdf_renderer = ScoutingReportPdfRenderer()

    def pending_report(
        workspace: OpponentWorkspace,
        *,
        error: str | None = None,
        pinned_missing: bool = False,
        status_code: int = 200,
    ) -> HTMLResponse:
        return HTMLResponse(
            render_template(
                "opponents/report.html",
                workspace=workspace,
                report=None,
                coach_report=None,
                report_mode="coach",
                preparation_error=error,
                pinned_missing=pinned_missing,
                preparation_allowed=bool(workspace.selected_matches) and not pinned_missing,
                match_context=None,
            ),
            status_code=status_code,
        )

    @router.post(
        "/ui/opponents/{profile_id}/report/prepare",
        include_in_schema=False,
    )
    def prepare_report(request: Request, profile_id: UUID) -> Response:
        require_localhost(request, "Match plan preparation")
        workspace = _workspace(opponents, profile_id)
        if not workspace.selected_matches:
            return pending_report(
                workspace,
                error="Сначала добавьте матч и подтвердите команду соперника.",
                status_code=422,
            )
        try:
            preparation.prepare(profile_id)
            # Resolve the current chain again: do not redirect to a stale result if
            # the profile or upstream runs changed during preparation.
            source = reports.get_source(profile_id)
        except ReportPreparationUnavailableError:
            return pending_report(
                workspace,
                error="Пока нет обработанных матчей для плана. Откройте выбранный матч "
                "и завершите его обработку, затем повторите подготовку.",
                status_code=422,
            )
        except PersistenceError:
            logger.exception("Could not prepare match plan for profile %s", profile_id)
            return pending_report(
                workspace,
                error="Не удалось завершить подготовку плана. Сохранённые матчи не потеряны. "
                "Попробуйте ещё раз; если ошибка повторится, проверьте обработку матчей.",
                status_code=503,
            )
        return RedirectResponse(
            f"/ui/opponents/{profile_id}/report?run_id={source.strategy.strategy_run_id}",
            status_code=303,
        )

    @router.get(
        "/ui/opponents/{profile_id}/report",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def report_page(
        profile_id: UUID,
        run_id: UUID | None = None,
        map_name: Annotated[str | None, Query(alias="map")] = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        pattern_type: PatternType | None = None,
        minimum_sample_size: Annotated[int, Query(ge=1)] = 1,
        minimum_confidence: Annotated[float, Query(ge=0, le=1)] = 0,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=10, le=100)] = 30,
        mode: Literal["coach", "analyst"] = "coach",
    ) -> HTMLResponse:
        workspace = _workspace(opponents, profile_id)
        filters = ScoutingReportFilters(
            map_name=map_name,
            side=side,
            buy_type=buy_type,
            pattern_type=pattern_type,
            minimum_sample_size=minimum_sample_size,
            minimum_confidence=minimum_confidence,
            page=page,
            page_size=page_size,
        )
        try:
            source = reports.get_source(profile_id, strategy_run_id=run_id)
        except CounterStrategyNotFoundError:
            return pending_report(
                workspace,
                pinned_missing=run_id is not None,
                status_code=404 if run_id is not None else 200,
            )
        report = build_scouting_report_page(source, workspace, filters)
        coach_report = build_coach_report_page(source, workspace)
        return HTMLResponse(
            render_template(
                "opponents/report.html",
                workspace=workspace,
                report=report,
                coach_report=coach_report,
                report_mode=mode,
                unavailable_reason=None,
                match_context=None,
            )
        )

    @router.get(
        "/ui/opponents/{profile_id}/cheat-sheet",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def cheat_sheet_page(
        profile_id: UUID,
        run_id: UUID | None = None,
        map_name: Annotated[str | None, Query(alias="map", max_length=100)] = None,
    ) -> HTMLResponse:
        workspace = _workspace(opponents, profile_id)
        try:
            source = reports.get_source(profile_id, strategy_run_id=run_id)
            cheat_sheet = build_match_cheat_sheet_page(
                source,
                workspace,
                map_name=map_name,
            )
        except CounterStrategyNotFoundError as exc:
            return HTMLResponse(
                render_template(
                    "opponents/cheat_sheet.html",
                    workspace=workspace,
                    cheat_sheet=None,
                    unavailable_reason=str(exc),
                    match_context=None,
                ),
                status_code=404,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(
            render_template(
                "opponents/cheat_sheet.html",
                workspace=workspace,
                cheat_sheet=cheat_sheet,
                unavailable_reason=None,
                match_context=None,
            )
        )

    @router.get(
        "/ui/opponents/{profile_id}/report/findings/{finding_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def report_finding(
        profile_id: UUID,
        finding_id: UUID,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        workspace = _workspace(opponents, profile_id)
        source = reports.get_source(profile_id, strategy_run_id=run_id)
        finding = next((item for item in source.findings if item.finding_id == finding_id), None)
        if finding is None:
            raise HTTPException(
                status_code=404,
                detail="Finding does not belong to the pinned report run.",
            )
        detail = build_scouting_report_detail(source, workspace, finding)
        return HTMLResponse(
            render_template(
                "opponents/report_finding.html",
                detail=detail,
                match_context=None,
            )
        )

    @router.get(
        "/ui/opponents/{profile_id}/report/print",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def report_print(
        profile_id: UUID,
        run_id: UUID | None = None,
    ) -> HTMLResponse:
        workspace = _workspace(opponents, profile_id)
        source = reports.get_source(profile_id, strategy_run_id=run_id)
        exported = exporter.build(source, workspace)
        return HTMLResponse(
            render_template(
                "opponents/report_print.html",
                exported=exported,
                recommendations_by_finding={
                    item.source_finding_id: item for item in exported.recommendations
                },
                finding_title=finding_title,
                finding_observation=finding_observation,
                limitation_label=limitation_label,
                warning_label=warning_label,
                check_label=check_label,
                check_message=check_message,
                export_status_label=status_label,
                match_context=None,
            )
        )

    @router.get("/api/opponents/{profile_id}/report", tags=["scouting-report"])
    def report_json(
        profile_id: UUID,
        run_id: UUID | None = None,
        map_name: Annotated[str | None, Query(alias="map")] = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        pattern_type: PatternType | None = None,
        minimum_sample_size: Annotated[int, Query(ge=1)] = 1,
        minimum_confidence: Annotated[float, Query(ge=0, le=1)] = 0,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=10, le=100)] = 30,
    ) -> dict[str, Any]:
        workspace = _workspace(opponents, profile_id)
        source = reports.get_source(profile_id, strategy_run_id=run_id)
        report = build_scouting_report_page(
            source,
            workspace,
            ScoutingReportFilters(
                map_name=map_name,
                side=side,
                buy_type=buy_type,
                pattern_type=pattern_type,
                minimum_sample_size=minimum_sample_size,
                minimum_confidence=minimum_confidence,
                page=page,
                page_size=page_size,
            ),
        )
        return report.model_dump(mode="json")

    @router.get(
        "/api/opponents/{profile_id}/report/export.json",
        tags=["scouting-report"],
    )
    def report_export_json(
        profile_id: UUID,
        run_id: UUID | None = None,
    ) -> Response:
        workspace = _workspace(opponents, profile_id)
        source = reports.get_source(profile_id, strategy_run_id=run_id)
        exported = exporter.build(source, workspace)
        return _export_response(
            exporter.render_json(exported),
            media_type="application/json",
            extension="json",
            report=exported,
        )

    @router.get(
        "/api/opponents/{profile_id}/report/export.pdf",
        tags=["scouting-report"],
    )
    def report_export_pdf(
        profile_id: UUID,
        run_id: UUID | None = None,
    ) -> Response:
        workspace = _workspace(opponents, profile_id)
        source = reports.get_source(profile_id, strategy_run_id=run_id)
        exported = exporter.build(source, workspace)
        try:
            content = pdf_renderer.render(exported)
        except PdfFontUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _export_response(
            content,
            media_type="application/pdf",
            extension="pdf",
            report=exported,
        )

    return router


def _workspace(service: OpponentWorkspaceService, profile_id: UUID) -> OpponentWorkspace:
    try:
        return service.get_workspace(profile_id)
    except OpponentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _export_response(
    content: bytes,
    *,
    media_type: str,
    extension: str,
    report: ScoutingReportExport,
) -> Response:
    filename = f"stratweb-report-{report.profile_id}-{report.strategy_run_id}.{extension}"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": f'"{report.export_fingerprint}"',
            "X-StratWeb-Export-Schema": report.export_schema_version,
            "X-StratWeb-Export-Rule": report.export_rule_version,
        },
    )


__all__ = ["scouting_report_router"]
