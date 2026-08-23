"""Match library, overview and diagnostics routes."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from shutil import disk_usage
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTeamNameRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.application.import_jobs import LocalImportJobManager
from stratweb.application.product import ProductQueryService
from stratweb.application.team_names import TeamNameSource, normalize_team_display_name
from stratweb.exceptions import (
    ImportDuplicateError,
    ImportJobNotCancellableError,
    ImportJobNotFoundError,
    ImportJobNotRetryableError,
    ImportQueueFullError,
    MatchNotFoundError,
)
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template
from stratweb.web.view_models import MatchLibraryItemView, MatchOverviewView


def product_router(
    database_path: Path,
    *,
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024,
    sampling_interval_ticks: int = 16,
    max_queue_size: int = 4,
    parser_timeout_seconds: int = 1800,
    parser_memory_limit_bytes: int = 4 * 1024 * 1024 * 1024,
    minimum_free_disk_bytes: int = 2 * 1024 * 1024 * 1024,
    cancel_grace_seconds: float = 5.0,
    asset_directory: Path | None = None,
    map_registry: MapRegistry | None = None,
    map_developer_mode: bool = False,
) -> APIRouter:
    router = APIRouter()
    match_repository = DuckDBMatchRepository(database_path)
    spatial_repository = DuckDBSpatialRepository(database_path)
    zone_repository = DuckDBZoneAssignmentRepository(database_path)
    team_name_repository = DuckDBTeamNameRepository(database_path)
    service = ProductQueryService(
        match_repository,
        DuckDBAnalyticsRepository(database_path),
        DuckDBTemporalRepository(database_path),
        spatial_repository,
        team_name_repository,
    )
    jobs = LocalImportJobManager(
        database_path,
        sampling_interval_ticks=sampling_interval_ticks,
        max_queue_size=max_queue_size,
        parser_timeout_seconds=parser_timeout_seconds,
        parser_memory_limit_bytes=parser_memory_limit_bytes,
        minimum_free_disk_bytes=minimum_free_disk_bytes,
        cancel_grace_seconds=cancel_grace_seconds,
    )
    router.add_event_handler("shutdown", jobs.shutdown)
    upload_directory = (database_path.parent / "uploads").resolve()
    definitions = map_registry or DEFAULT_MAP_REGISTRY
    map_assets = (
        MapOverviewRegistry(asset_directory, definitions) if asset_directory is not None else None
    )

    @router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
    def match_library(
        search: Annotated[str, Query(max_length=200)] = "",
        sort: Annotated[str, Query(pattern="^(newest|map|rounds)$")] = "newest",
    ) -> HTMLResponse:
        matches = service.list_matches(search=search, sort=sort)
        thumbnails = {
            item.match_id: _map_overview(
                item.match_id,
                item.map_name,
                spatial_repository,
                definitions,
                map_assets,
            )
            for item in matches
        }
        return HTMLResponse(
            render_template(
                "matches/library.html",
                matches=matches,
                search=search,
                sort=sort,
                map_thumbnails=thumbnails,
                recent_jobs=jobs.list_recent(8),
                match_context=None,
            )
        )

    @router.get("/ui/matches/{match_id}", response_class=HTMLResponse, include_in_schema=False)
    def match_overview(match_id: UUID) -> HTMLResponse:
        overview = _overview(service, match_id)
        return HTMLResponse(
            render_template(
                "matches/overview.html",
                overview=overview,
                match_context=_match_context(overview.match),
            )
        )

    @router.get(
        "/ui/matches/{match_id}/players",
        response_class=RedirectResponse,
        include_in_schema=False,
    )
    def players(match_id: UUID) -> RedirectResponse:
        _overview(service, match_id)
        return RedirectResponse(f"/ui/matches/{match_id}#players", status_code=303)

    @router.post(
        "/api/matches/{match_id}/teams/{team_id}/display-name",
        tags=["match-presentation"],
        response_model=None,
    )
    def set_team_display_name(
        request: Request,
        match_id: UUID,
        team_id: UUID,
        display_name: Annotated[str, Form(min_length=1, max_length=100)],
        source_reference: Annotated[str | None, Form(max_length=500)] = None,
    ) -> Response:
        require_localhost(request, "Изменение названия команды")
        try:
            normalized = normalize_team_display_name(display_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        normalized_reference = source_reference.strip() if source_reference else None
        label = team_name_repository.save(
            match_id,
            team_id,
            normalized,
            source=TeamNameSource.MANUAL,
            source_reference=normalized_reference or None,
        )
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/matches/{match_id}", status_code=303)
        return JSONResponse(content=label.model_dump(mode="json"))

    @router.post(
        "/api/matches/{match_id}/teams/{team_id}/display-name/reset",
        tags=["match-presentation"],
        response_model=None,
    )
    def reset_team_display_name(request: Request, match_id: UUID, team_id: UUID) -> Response:
        require_localhost(request, "Сброс названия команды")
        deleted = team_name_repository.delete(match_id, team_id)
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/matches/{match_id}", status_code=303)
        return JSONResponse(content={"deleted": deleted})

    @router.get(
        "/ui/matches/{match_id}/diagnostics",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def diagnostics(match_id: UUID) -> HTMLResponse:
        overview = _overview(service, match_id)
        map_overview = _map_overview(
            match_id,
            overview.match.map_name,
            spatial_repository,
            definitions,
            map_assets,
        )
        spatial_summary = spatial_repository.get_summary(match_id)
        zone_summary = (
            zone_repository.get_summary_for_spatial_run(match_id, spatial_summary.spatial_run_id)
            if spatial_summary is not None
            else None
        )
        return HTMLResponse(
            render_template(
                "matches/diagnostics.html",
                overview=overview,
                map_overview=map_overview,
                zone_summary=zone_summary,
                map_revisions=(
                    definitions.revisions(overview.match.map_name)
                    if definitions.canonicalize(overview.match.map_name) is not None
                    else ()
                ),
                map_developer_mode=map_developer_mode,
                match_context=_match_context(overview.match),
            )
        )

    @router.post(
        "/api/import-jobs",
        status_code=202,
        tags=["local-import"],
        response_model=None,
    )
    async def create_import_job(
        request: Request,
        demo: Annotated[UploadFile, File()],
    ) -> Response:
        _require_localhost(request)
        original_name = _safe_original_name(demo.filename)
        if not original_name.casefold().endswith(".dem"):
            raise HTTPException(status_code=415, detail="Only completed .dem files are accepted.")
        upload_directory.mkdir(parents=True, exist_ok=True)
        internal_path = (upload_directory / f"{uuid4()}.dem").resolve()
        if internal_path.parent != upload_directory:
            raise HTTPException(status_code=400, detail="Unsafe upload target.")
        written = 0
        digest = sha256()
        try:
            with internal_path.open("xb") as stream:
                while chunk := await demo.read(1024 * 1024):
                    written += len(chunk)
                    if written > max_upload_bytes:
                        raise HTTPException(
                            status_code=413, detail="Demo exceeds max_upload_bytes."
                        )
                    if disk_usage(upload_directory).free < minimum_free_disk_bytes + len(chunk):
                        raise HTTPException(
                            status_code=507,
                            detail="Not enough free disk space to retain this demo safely.",
                        )
                    stream.write(chunk)
                    digest.update(chunk)
            with internal_path.open("rb") as stream:
                signature = stream.read(7)
            if signature != b"PBDEMS2":
                raise HTTPException(status_code=415, detail="File is not a completed CS2 demo.")
        except Exception:
            if internal_path.is_file():
                internal_path.unlink()
            raise
        finally:
            await demo.close()
        try:
            job = jobs.submit(
                internal_path,
                original_name,
                demo_sha256=digest.hexdigest(),
                file_size_bytes=written,
            )
        except ImportDuplicateError as exc:
            internal_path.unlink(missing_ok=True)
            detail = {
                "error_code": exc.error_code,
                "message": str(exc),
                "job_id": str(exc.job_id) if exc.job_id is not None else None,
                "match_id": str(exc.match_id) if exc.match_id is not None else None,
            }
            return JSONResponse(status_code=409, content={"detail": detail})
        except ImportQueueFullError as exc:
            internal_path.unlink(missing_ok=True)
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "10"},
                content={"detail": {"error_code": exc.error_code, "message": str(exc)}},
            )
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/import-jobs/{job.job_id}", status_code=303)
        return JSONResponse(status_code=202, content=job.model_dump(mode="json"))

    @router.get("/api/import-jobs/{job_id}", tags=["local-import"])
    def import_job(job_id: UUID) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Import job not found.")
        return job.model_dump(mode="json")

    @router.post(
        "/api/import-jobs/{job_id}/retry",
        status_code=202,
        tags=["local-import"],
        response_model=None,
    )
    def retry_import_job(request: Request, job_id: UUID) -> Response:
        _require_localhost(request)
        try:
            job = jobs.retry(job_id)
        except ImportJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ImportJobNotRetryableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ImportQueueFullError as exc:
            raise HTTPException(
                status_code=429, detail=str(exc), headers={"Retry-After": "10"}
            ) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/import-jobs/{job.job_id}", status_code=303)
        return JSONResponse(status_code=202, content=job.model_dump(mode="json"))

    @router.post(
        "/api/import-jobs/{job_id}/cancel",
        status_code=202,
        tags=["local-import"],
        response_model=None,
    )
    def cancel_import_job(request: Request, job_id: UUID) -> Response:
        _require_localhost(request)
        try:
            job = jobs.cancel(job_id)
        except ImportJobNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ImportJobNotCancellableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/import-jobs/{job.job_id}", status_code=303)
        return JSONResponse(status_code=202, content=job.model_dump(mode="json"))

    @router.get(
        "/ui/import-jobs/{job_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def import_job_page(job_id: UUID) -> HTMLResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Import job not found.")
        return HTMLResponse(
            render_template(
                "matches/job.html",
                job=job,
                match_context=None,
            )
        )

    return router


def _overview(service: ProductQueryService, match_id: UUID) -> MatchOverviewView:
    try:
        return service.overview(match_id)
    except MatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _match_context(match: MatchLibraryItemView) -> dict[str, Any]:
    score = "Счёт недоступен"
    if match.score_available:
        score = ":".join(str(team.score) for team in match.teams)
    return {
        "match_id": match.match_id,
        "short_id": match.short_id,
        "map_name": match.map_name,
        "team_names": tuple(team.name for team in match.teams),
        "score": score,
    }


def _safe_original_name(value: str | None) -> str:
    candidate = (value or "uploaded.dem").replace("\\", "/").split("/")[-1].strip()
    if not candidate or len(candidate) > 255 or "\x00" in candidate:
        raise HTTPException(status_code=400, detail="Invalid original filename.")
    return candidate


def _require_localhost(request: Request) -> None:
    require_localhost(request, "Demo import")


def _map_overview(
    match_id: UUID,
    raw_map_name: str,
    spatial_repository: DuckDBSpatialRepository,
    definitions: MapRegistry,
    assets: MapOverviewRegistry | None,
) -> Any:
    if assets is None:
        return None
    summary = spatial_repository.get_summary(match_id)
    if summary is not None:
        return assets.get_for_run(summary.map_model.map_name, summary.map_semantics).model
    definition = definitions.preferred_definition(raw_map_name)
    return assets.get_definition(definition).model if definition is not None else None
