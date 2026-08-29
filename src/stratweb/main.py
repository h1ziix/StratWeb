"""FastAPI application factory."""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.types import Scope

from stratweb import __version__
from stratweb.config import get_settings
from stratweb.exceptions import (
    AnalysisFindingNotFoundError,
    CounterStrategyNotFoundError,
    EconomyNotFoundError,
    HeadToHeadNotFoundError,
    PatternNotFoundError,
    RoundFeatureNotFoundError,
    SpatialNotFoundError,
    StatisticalTrustNotFoundError,
    TacticalV2NotFoundError,
    ZoneAssignmentNotFoundError,
)
from stratweb.maps.registry import MapRegistry
from stratweb.web.counter_strategy import counter_strategy_router
from stratweb.web.critical_mistakes import critical_mistakes_router
from stratweb.web.design_system import design_system_router
from stratweb.web.economy import economy_router
from stratweb.web.findings import finding_router
from stratweb.web.head_to_head import head_to_head_router
from stratweb.web.maps import map_router
from stratweb.web.opponents import opponent_router
from stratweb.web.patterns import pattern_router
from stratweb.web.rendering import render_template
from stratweb.web.round_features import round_feature_router
from stratweb.web.routers import product_router
from stratweb.web.scouting_report import scouting_report_router
from stratweb.web.spatial import spatial_ui_router
from stratweb.web.spatial_explorer import spatial_explorer_router
from stratweb.web.statistical_trust import statistical_trust_router
from stratweb.web.tactical_v2 import tactical_v2_router
from stratweb.web.temporal import temporal_ui_router
from stratweb.web.zones import zone_assignment_router

logger = logging.getLogger(__name__)


class RevalidatingStaticFiles(StaticFiles):
    """Prevent stale frontend bundles while the local application is evolving."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def create_app(
    database_path: Path | None = None,
    map_overview_path: Path | None = None,
    *,
    map_registry: MapRegistry | None = None,
    map_developer_mode: bool | None = None,
    cs2_demo_directory: Path | None = None,
) -> FastAPI:
    """Create the HTTP application without touching storage or parser resources."""

    application = FastAPI(
        title="StratWeb",
        version=__version__,
        description="Offline analysis of completed Counter-Strike 2 demo files.",
    )
    application.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.exception_handler(SpatialNotFoundError)
    async def spatial_not_found(
        request: Request, exc: SpatialNotFoundError
    ) -> JSONResponse | HTMLResponse:
        if request.url.path.startswith("/ui/"):
            return HTMLResponse(
                render_template(
                    "errors/page.html",
                    title="Spatial data unavailable",
                    detail=str(exc),
                    error_id=exc.error_code,
                    match_context=None,
                ),
                status_code=404,
            )
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @application.exception_handler(ZoneAssignmentNotFoundError)
    async def zone_assignment_not_found(
        request: Request, exc: ZoneAssignmentNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(EconomyNotFoundError)
    async def economy_not_found(request: Request, exc: EconomyNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(RoundFeatureNotFoundError)
    async def round_feature_not_found(
        request: Request, exc: RoundFeatureNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(PatternNotFoundError)
    async def pattern_not_found(request: Request, exc: PatternNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(AnalysisFindingNotFoundError)
    async def analysis_finding_not_found(
        request: Request, exc: AnalysisFindingNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(StatisticalTrustNotFoundError)
    async def statistical_trust_not_found(
        request: Request, exc: StatisticalTrustNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(TacticalV2NotFoundError)
    async def tactical_v2_not_found(request: Request, exc: TacticalV2NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(HeadToHeadNotFoundError)
    async def head_to_head_not_found(
        request: Request, exc: HeadToHeadNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(CounterStrategyNotFoundError)
    async def counter_strategy_not_found(
        request: Request, exc: CounterStrategyNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": exc.error_code},
        )

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse | HTMLResponse:
        if request.url.path.startswith("/ui/"):
            return HTMLResponse(
                render_template(
                    "errors/page.html",
                    title="Page unavailable",
                    detail=str(exc.detail),
                    error_id=f"http_{exc.status_code}",
                    match_context=None,
                ),
                status_code=exc.status_code,
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse | HTMLResponse:
        logger.exception("Unhandled request failure for %s", request.url.path, exc_info=exc)
        detail = (
            "Произошла непредвиденная ошибка. Сервер продолжает работать; "
            "запрос можно безопасно повторить."
        )
        if request.url.path.startswith("/ui/"):
            return HTMLResponse(
                render_template(
                    "errors/page.html",
                    title="Непредвиденная ошибка сервера",
                    detail=detail,
                    error_id="internal_server_error",
                    match_context=None,
                ),
                status_code=500,
            )
        return JSONResponse(
            status_code=500,
            content={"detail": detail, "error_code": "internal_server_error"},
        )

    selected_database = (database_path or get_settings().duckdb_path).expanduser().resolve()
    selected_overviews = (
        (map_overview_path or get_settings().map_overview_dir).expanduser().resolve()
    )
    static_directory = Path(__file__).parent / "web" / "static"
    application.mount(
        "/static",
        RevalidatingStaticFiles(directory=static_directory),
        name="static",
    )
    settings = get_settings()
    application.include_router(
        product_router(
            selected_database,
            max_upload_bytes=settings.max_upload_bytes,
            max_batch_upload_bytes=settings.max_batch_upload_bytes,
            sampling_interval_ticks=settings.position_sample_interval_ticks,
            max_queue_size=settings.import_queue_size,
            parser_timeout_seconds=settings.parser_timeout_seconds,
            parser_memory_limit_bytes=settings.parser_memory_limit_bytes,
            minimum_free_disk_bytes=settings.import_minimum_free_disk_bytes,
            cancel_grace_seconds=settings.import_cancel_grace_seconds,
            asset_directory=selected_overviews,
            map_registry=map_registry,
            map_developer_mode=(
                settings.map_developer_mode if map_developer_mode is None else map_developer_mode
            ),
        )
    )
    application.include_router(opponent_router(selected_database))
    application.include_router(design_system_router())
    application.include_router(temporal_ui_router(selected_database))
    application.include_router(spatial_ui_router(selected_database))
    application.include_router(zone_assignment_router(selected_database))
    application.include_router(economy_router(selected_database))
    application.include_router(scouting_report_router(selected_database))
    application.include_router(round_feature_router(selected_database))
    application.include_router(counter_strategy_router(selected_database))
    application.include_router(critical_mistakes_router(selected_database))
    application.include_router(pattern_router(selected_database))
    application.include_router(statistical_trust_router(selected_database))
    application.include_router(tactical_v2_router(selected_database))
    application.include_router(head_to_head_router(selected_database))
    application.include_router(finding_router(selected_database))
    application.include_router(
        spatial_explorer_router(
            selected_database,
            selected_overviews,
            map_registry=map_registry,
            cs2_demo_directory=cs2_demo_directory or settings.cs2_demo_dir,
        )
    )
    application.include_router(
        map_router(
            selected_database,
            selected_overviews,
            map_registry=map_registry,
            developer_mode=(
                settings.map_developer_mode if map_developer_mode is None else map_developer_mode
            ),
        )
    )

    return application


app = create_app()
