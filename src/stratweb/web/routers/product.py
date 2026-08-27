"""Match library, overview and diagnostics routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from shutil import disk_usage
from typing import Annotated, Any
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBEconomyRepository,
    DuckDBImportBatchRepository,
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBRoundFeatureRepository,
    DuckDBSpatialRepository,
    DuckDBTeamNameRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.application.import_batch_models import (
    ImportBatchItem,
    ImportBatchItemDisposition,
    ImportBatchItemView,
    ImportBatchRecord,
    ImportBatchView,
)
from stratweb.application.import_jobs import LocalImportJobManager
from stratweb.application.opponents import OpponentWorkspaceService
from stratweb.application.product import ProductQueryService
from stratweb.application.team_names import TeamNameSource, normalize_team_display_name
from stratweb.exceptions import (
    ImportDuplicateError,
    ImportJobNotCancellableError,
    ImportJobNotFoundError,
    ImportJobNotRetryableError,
    ImportQueueFullError,
    MatchNotFoundError,
    OpponentConflictError,
    OpponentNotFoundError,
    OpponentSelectionError,
)
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.ports import ImportBatchRepository
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.web.context import require_localhost
from stratweb.web.rendering import render_template
from stratweb.web.view_models import (
    MatchLibraryItemView,
    MatchOverviewView,
    build_match_hub,
    build_match_readiness,
)


def product_router(
    database_path: Path,
    *,
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024,
    max_batch_upload_bytes: int = 8 * 1024 * 1024 * 1024,
    sampling_interval_ticks: int = 16,
    max_queue_size: int = 16,
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
    economy_repository = DuckDBEconomyRepository(database_path)
    feature_repository = DuckDBRoundFeatureRepository(database_path)
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
    batch_repository = DuckDBImportBatchRepository(database_path)
    opponent_service = OpponentWorkspaceService(
        DuckDBOpponentRepository(database_path),
        match_repository,
        team_name_repository,
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
                recent_batches=tuple(
                    _batch_view(batch_repository, jobs, item.batch_id)
                    for item in batch_repository.list_recent(5)
                ),
                opponent_profiles=opponent_service.list_profiles(),
                match_context=None,
            )
        )

    @router.get("/ui/matches/{match_id}", response_class=HTMLResponse, include_in_schema=False)
    def match_overview(match_id: UUID) -> HTMLResponse:
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
        readiness = build_match_readiness(overview, map_overview, zone_summary)
        return HTMLResponse(
            render_template(
                "matches/overview.html",
                overview=overview,
                readiness=readiness,
                hub=build_match_hub(
                    overview,
                    readiness,
                    map_overview,
                    economy_available=economy_repository.get_summary(match_id) is not None,
                    features_available=feature_repository.get_summary(match_id) is not None,
                ),
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
                readiness=build_match_readiness(overview, map_overview, zone_summary),
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

    @router.post(
        "/api/import-batches",
        status_code=202,
        tags=["local-import"],
        response_model=None,
    )
    async def create_import_batch(
        request: Request,
        pool_name: Annotated[str, Form(min_length=1, max_length=100)],
        uploads: Annotated[list[UploadFile] | None, File()] = None,
        folder_demos: Annotated[list[UploadFile] | None, File()] = None,
        opponent_profile_id: Annotated[UUID | None, Form()] = None,
    ) -> Response:
        """Retain many demos safely, then submit one isolated job per demo."""

        _require_localhost(request)
        sources = tuple(uploads or ()) + tuple(folder_demos or ())
        if not sources:
            raise HTTPException(status_code=422, detail="Select .dem files, a folder or a ZIP.")
        if len(sources) > 32:
            raise HTTPException(status_code=413, detail="A batch accepts at most 32 sources.")
        upload_directory.mkdir(parents=True, exist_ok=True)
        retained, rejected = await _collect_batch_uploads(
            sources,
            upload_directory=upload_directory,
            max_demo_bytes=max_upload_bytes,
            max_batch_bytes=max_batch_upload_bytes,
            minimum_free_disk_bytes=minimum_free_disk_bytes,
            max_demo_count=32,
        )
        if not retained and not rejected:
            raise HTTPException(status_code=422, detail="No completed CS2 .dem files were found.")

        normalized_name = pool_name.strip()
        try:
            if opponent_profile_id is None:
                opponent = opponent_service.create_profile(normalized_name)
            else:
                opponent = opponent_service.get_workspace(opponent_profile_id).profile
        except OpponentConflictError as exc:
            _delete_retained(retained)
            raise HTTPException(
                status_code=409,
                detail="A profile with this name already exists. Select it in the form.",
            ) from exc
        except OpponentNotFoundError as exc:
            _delete_retained(retained)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OpponentSelectionError as exc:
            _delete_retained(retained)
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        now = datetime.now(UTC)
        batch = ImportBatchRecord(
            batch_id=uuid4(),
            display_name=normalized_name,
            opponent_profile_id=opponent.profile_id,
            created_at=now,
        )
        batch_repository.create(batch)
        item_index = 0
        for demo_file in retained:
            try:
                job = jobs.submit(
                    demo_file.path,
                    demo_file.original_name,
                    demo_sha256=demo_file.sha256,
                    file_size_bytes=demo_file.size_bytes,
                )
                item = ImportBatchItem(
                    batch_id=batch.batch_id,
                    item_index=item_index,
                    original_name=demo_file.original_name,
                    disposition=ImportBatchItemDisposition.QUEUED,
                    job_id=job.job_id,
                    message="Queued as an isolated demo import",
                    created_at=now,
                )
            except ImportDuplicateError as exc:
                demo_file.path.unlink(missing_ok=True)
                item = ImportBatchItem(
                    batch_id=batch.batch_id,
                    item_index=item_index,
                    original_name=demo_file.original_name,
                    disposition=ImportBatchItemDisposition.DUPLICATE,
                    job_id=exc.job_id,
                    existing_match_id=exc.match_id,
                    error_code=exc.error_code,
                    message="This demo is already present and was not imported twice",
                    created_at=now,
                )
            except ImportQueueFullError as exc:
                demo_file.path.unlink(missing_ok=True)
                item = ImportBatchItem(
                    batch_id=batch.batch_id,
                    item_index=item_index,
                    original_name=demo_file.original_name,
                    disposition=ImportBatchItemDisposition.REJECTED,
                    error_code=exc.error_code,
                    message="Import queue is full; this file was not retained",
                    created_at=now,
                )
            batch_repository.add_item(item)
            item_index += 1
        for rejection in rejected:
            batch_repository.add_item(
                ImportBatchItem(
                    batch_id=batch.batch_id,
                    item_index=item_index,
                    original_name=rejection.original_name,
                    disposition=ImportBatchItemDisposition.REJECTED,
                    error_code=rejection.error_code,
                    message=rejection.message,
                    created_at=now,
                )
            )
            item_index += 1

        view = _batch_view(batch_repository, jobs, batch.batch_id)
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/ui/import-batches/{batch.batch_id}", status_code=303)
        return JSONResponse(status_code=202, content=view.model_dump(mode="json"))

    @router.get("/api/import-batches/{batch_id}", tags=["local-import"])
    def import_batch(batch_id: UUID) -> dict[str, Any]:
        return _batch_view(batch_repository, jobs, batch_id).model_dump(mode="json")

    @router.get(
        "/ui/import-batches/{batch_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def import_batch_page(batch_id: UUID) -> HTMLResponse:
        view = _batch_view(batch_repository, jobs, batch_id)
        return HTMLResponse(
            render_template(
                "matches/batch.html",
                batch_view=view,
                match_context=None,
            )
        )

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


@dataclass(frozen=True, slots=True)
class _RetainedDemo:
    path: Path
    original_name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class _BatchRejection:
    original_name: str
    error_code: str
    message: str


async def _collect_batch_uploads(
    sources: tuple[UploadFile, ...],
    *,
    upload_directory: Path,
    max_demo_bytes: int,
    max_batch_bytes: int,
    minimum_free_disk_bytes: int,
    max_demo_count: int,
) -> tuple[tuple[_RetainedDemo, ...], tuple[_BatchRejection, ...]]:
    retained: list[_RetainedDemo] = []
    rejected: list[_BatchRejection] = []
    total_bytes = 0
    try:
        for source in sources:
            try:
                original_name = _safe_original_name(source.filename)
            except HTTPException:
                rejected.append(
                    _BatchRejection(
                        "invalid filename",
                        "invalid_original_name",
                        "The uploaded filename is unsafe",
                    )
                )
                continue
            suffix = Path(original_name).suffix.casefold()
            if suffix == ".dem":
                if len(retained) >= max_demo_count:
                    rejected.append(
                        _BatchRejection(
                            original_name,
                            "batch_file_limit",
                            f"A batch accepts at most {max_demo_count} demos",
                        )
                    )
                    continue
                path = (upload_directory / f"{uuid4()}.dem").resolve()
                try:
                    size, digest = await _retain_upload(
                        source,
                        path,
                        max_bytes=max_demo_bytes,
                        minimum_free_disk_bytes=minimum_free_disk_bytes,
                    )
                    if total_bytes + size > max_batch_bytes:
                        path.unlink(missing_ok=True)
                        raise ValueError("batch_total_limit")
                    _require_demo_signature(path)
                except ValueError as exc:
                    path.unlink(missing_ok=True)
                    code = str(exc)
                    rejected.append(
                        _BatchRejection(
                            original_name,
                            code,
                            _batch_error_message(code),
                        )
                    )
                    continue
                retained.append(_RetainedDemo(path, original_name, digest, size))
                total_bytes += size
                continue
            if suffix != ".zip":
                rejected.append(
                    _BatchRejection(
                        original_name,
                        "unsupported_batch_source",
                        "Only .dem files and ZIP archives are accepted",
                    )
                )
                continue

            archive_path = (upload_directory / f"{uuid4()}.zip").resolve()
            try:
                await _retain_upload(
                    source,
                    archive_path,
                    max_bytes=max_batch_bytes,
                    minimum_free_disk_bytes=minimum_free_disk_bytes,
                )
                archive_demos, archive_rejections = _extract_zip_demos(
                    archive_path,
                    upload_directory=upload_directory,
                    max_demo_bytes=max_demo_bytes,
                    remaining_batch_bytes=max_batch_bytes - total_bytes,
                    minimum_free_disk_bytes=minimum_free_disk_bytes,
                    remaining_demo_count=max_demo_count - len(retained),
                )
                if not archive_demos and not archive_rejections:
                    archive_rejections = (
                        _BatchRejection(
                            original_name,
                            "zip_without_demos",
                            "The ZIP archive contains no .dem files",
                        ),
                    )
                retained.extend(archive_demos)
                rejected.extend(archive_rejections)
                total_bytes += sum(item.size_bytes for item in archive_demos)
            except (BadZipFile, ValueError) as exc:
                code = str(exc) if isinstance(exc, ValueError) else "invalid_zip"
                rejected.append(_BatchRejection(original_name, code, _batch_error_message(code)))
            finally:
                archive_path.unlink(missing_ok=True)
    finally:
        for source in sources:
            await source.close()
    return tuple(retained), tuple(rejected)


async def _retain_upload(
    source: UploadFile,
    target: Path,
    *,
    max_bytes: int,
    minimum_free_disk_bytes: int,
) -> tuple[int, str]:
    written = 0
    digest = sha256()
    try:
        with target.open("xb") as stream:
            while chunk := await source.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("file_too_large")
                if disk_usage(target.parent).free < minimum_free_disk_bytes + len(chunk):
                    raise ValueError("insufficient_disk_space")
                stream.write(chunk)
                digest.update(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return written, digest.hexdigest()


def _extract_zip_demos(
    archive_path: Path,
    *,
    upload_directory: Path,
    max_demo_bytes: int,
    remaining_batch_bytes: int,
    minimum_free_disk_bytes: int,
    remaining_demo_count: int,
) -> tuple[tuple[_RetainedDemo, ...], tuple[_BatchRejection, ...]]:
    retained: list[_RetainedDemo] = []
    rejected: list[_BatchRejection] = []
    with ZipFile(archive_path) as archive:
        all_infos = archive.infolist()
        if len(all_infos) > 512:
            raise ValueError("zip_entry_limit")
        infos = tuple(
            info
            for info in all_infos
            if not info.is_dir() and info.filename.casefold().endswith(".dem")
        )
        if len(infos) > remaining_demo_count:
            raise ValueError("batch_file_limit")
        declared_total = sum(info.file_size for info in infos)
        if declared_total > remaining_batch_bytes:
            raise ValueError("batch_total_limit")
        for info in infos:
            try:
                original_name = _safe_original_name(info.filename)
            except HTTPException:
                rejected.append(
                    _BatchRejection(
                        "invalid filename",
                        "invalid_original_name",
                        "The ZIP entry filename is unsafe",
                    )
                )
                continue
            if info.flag_bits & 0x1:
                rejected.append(
                    _BatchRejection(
                        original_name,
                        "encrypted_zip_member",
                        "Encrypted demo entries are not supported",
                    )
                )
                continue
            if info.file_size > max_demo_bytes:
                rejected.append(
                    _BatchRejection(
                        original_name,
                        "file_too_large",
                        _batch_error_message("file_too_large"),
                    )
                )
                continue
            if info.file_size and info.file_size / max(info.compress_size, 1) > 200:
                rejected.append(
                    _BatchRejection(
                        original_name,
                        "unsafe_compression_ratio",
                        "The ZIP entry has an unsafe compression ratio",
                    )
                )
                continue
            target = (upload_directory / f"{uuid4()}.dem").resolve()
            try:
                size, digest = _retain_zip_member(
                    archive,
                    info,
                    target,
                    max_bytes=max_demo_bytes,
                    minimum_free_disk_bytes=minimum_free_disk_bytes,
                )
                _require_demo_signature(target)
            except (BadZipFile, NotImplementedError, OSError, RuntimeError, ValueError) as exc:
                target.unlink(missing_ok=True)
                code = str(exc) or "invalid_zip_member"
                rejected.append(_BatchRejection(original_name, code, _batch_error_message(code)))
                continue
            retained.append(_RetainedDemo(target, original_name, digest, size))
    return tuple(retained), tuple(rejected)


def _retain_zip_member(
    archive: ZipFile,
    info: Any,
    target: Path,
    *,
    max_bytes: int,
    minimum_free_disk_bytes: int,
) -> tuple[int, str]:
    written = 0
    digest = sha256()
    try:
        with archive.open(info, "r") as source, target.open("xb") as stream:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("file_too_large")
                if disk_usage(target.parent).free < minimum_free_disk_bytes + len(chunk):
                    raise ValueError("insufficient_disk_space")
                stream.write(chunk)
                digest.update(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return written, digest.hexdigest()


def _require_demo_signature(path: Path) -> None:
    with path.open("rb") as stream:
        if stream.read(7) != b"PBDEMS2":
            raise ValueError("invalid_demo_signature")


def _batch_error_message(code: str) -> str:
    return {
        "batch_file_limit": "The batch contains more demos than allowed",
        "batch_total_limit": "The batch exceeds the total upload limit",
        "file_too_large": "This file exceeds the per-demo upload limit",
        "insufficient_disk_space": "Not enough free disk space to retain this demo safely",
        "invalid_demo_signature": "This file is not a completed CS2 demo",
        "invalid_zip": "The ZIP archive is damaged or unsupported",
        "zip_entry_limit": "The ZIP archive contains too many entries",
    }.get(code, "The file could not be accepted safely")


def _delete_retained(items: tuple[_RetainedDemo, ...]) -> None:
    for item in items:
        item.path.unlink(missing_ok=True)


def _batch_view(
    repository: ImportBatchRepository,
    jobs: LocalImportJobManager,
    batch_id: UUID,
) -> ImportBatchView:
    batch = repository.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found.")
    items = tuple(
        ImportBatchItemView(
            item=item,
            job=(
                jobs.get(item.job_id)
                if item.disposition is ImportBatchItemDisposition.QUEUED and item.job_id is not None
                else None
            ),
        )
        for item in repository.list_items(batch_id)
    )
    return ImportBatchView.compose(batch, items)


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
