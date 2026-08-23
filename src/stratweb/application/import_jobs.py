"""Durable, bounded and parser-isolated completed-demo import jobs."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, Event, Lock
from uuid import UUID, uuid4

from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBEconomyRepository,
    DuckDBImportJobRepository,
    DuckDBMatchRepository,
    DuckDBRoundFeatureRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.analytics.models import AnalyticsConfig
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.economy import ComputeEconomyService
from stratweb.application.import_job_models import ImportJobRecord, ImportJobStage, stage_progress
from stratweb.application.import_worker import (
    ParserWorkerRunner,
    WorkerEconomyExtractor,
    WorkerSpatialExtractor,
)
from stratweb.application.inspection import inspect_local_file
from stratweb.application.persistence import ImportCanonicalMatchService
from stratweb.application.persistence_models import ImportStatus, MatchQueryFilters
from stratweb.application.round_features import ComputeRoundFeaturesService
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.application.zone_assignments import ComputeZoneAssignmentsService
from stratweb.economy.models import EconomyConfig
from stratweb.exceptions import (
    ImportDuplicateError,
    ImportJobNotCancellableError,
    ImportJobNotFoundError,
    ImportJobNotRetryableError,
    ImportQueueFullError,
    ImportWorkerCancelledError,
)
from stratweb.features.models import RoundFeatureConfig
from stratweb.ports import ImportJobRepository
from stratweb.spatial.models import SpatialConfig
from stratweb.temporal.models import TemporalConfig


class LocalImportJobManager:
    """One DB writer plus bounded isolated parser subprocesses."""

    def __init__(
        self,
        database_path: Path,
        *,
        sampling_interval_ticks: int = 16,
        max_queue_size: int = 4,
        parser_timeout_seconds: int = 1800,
        parser_memory_limit_bytes: int = 4 * 1024 * 1024 * 1024,
        minimum_free_disk_bytes: int = 2 * 1024 * 1024 * 1024,
        cancel_grace_seconds: float = 5.0,
        repository: ImportJobRepository | None = None,
    ) -> None:
        self._database_path = database_path.expanduser().resolve()
        self._sampling_interval_ticks = sampling_interval_ticks
        self._repository = repository or DuckDBImportJobRepository(self._database_path)
        self._upload_directory = (self._database_path.parent / "uploads").resolve()
        self._artifact_root = (self._database_path.parent / "import_artifacts").resolve()
        self._parser_timeout_seconds = parser_timeout_seconds
        self._parser_memory_limit_bytes = parser_memory_limit_bytes
        self._minimum_free_disk_bytes = minimum_free_disk_bytes
        self._cancel_grace_seconds = cancel_grace_seconds
        self._lock = Lock()
        self._started = False
        self._capacity = BoundedSemaphore(max_queue_size + 1)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stratweb-import")
        self._cancel_events: dict[UUID, Event] = {}
        self._futures: dict[UUID, Future[None]] = {}

    def submit(
        self,
        demo_path: Path,
        original_name: str,
        *,
        demo_sha256: str | None = None,
        file_size_bytes: int | None = None,
    ) -> ImportJobRecord:
        self._ensure_started()
        if demo_sha256 is None or file_size_bytes is None:
            snapshot = inspect_local_file(demo_path)
            demo_sha256 = demo_sha256 or snapshot.sha256
            file_size_bytes = snapshot.size_bytes if file_size_bytes is None else file_size_bytes
        self._reject_duplicate(demo_sha256)
        if not self._capacity.acquire(blocking=False):
            raise ImportQueueFullError("Import queue is full. Wait for an active job to finish.")
        now = datetime.now(UTC)
        record = ImportJobRecord.create(
            job_id=uuid4(),
            original_name=original_name,
            internal_name=demo_path.name,
            demo_sha256=demo_sha256,
            file_size_bytes=file_size_bytes,
            now=now,
        )
        try:
            self._repository.create(record)
            self._schedule(record, demo_path)
        except Exception:
            self._capacity.release()
            raise
        return record

    def get(self, job_id: UUID) -> ImportJobRecord | None:
        self._ensure_started()
        return self._repository.get(job_id)

    def list_recent(self, limit: int = 10) -> tuple[ImportJobRecord, ...]:
        self._ensure_started()
        return self._repository.list_recent(limit)

    def shutdown(self) -> None:
        """Stop parser children and persist retryable cancellation on graceful shutdown."""

        with self._lock:
            events = tuple(self._cancel_events.items())
            futures = tuple(self._futures.values())
        for _job_id, event in events:
            event.set()
        for future in futures:
            future.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
        for job_id, _event in events:
            try:
                record = self._require_job(job_id)
                if not record.stage.terminal:
                    self._mark_cancelled(job_id)
            except ImportJobNotFoundError:
                pass
        with self._lock:
            self._cancel_events.clear()
            self._futures.clear()

    def retry(self, job_id: UUID) -> ImportJobRecord:
        self._ensure_started()
        previous = self._require_job(job_id)
        demo_path = self._demo_path(previous.internal_name)
        if (
            previous.stage not in {ImportJobStage.FAILED, ImportJobStage.CANCELLED}
            or not previous.recoverable
            or not demo_path.is_file()
        ):
            raise ImportJobNotRetryableError(
                "This import cannot be retried because its demo is unavailable "
                "or its state is invalid."
            )
        if not self._capacity.acquire(blocking=False):
            raise ImportQueueFullError("Import queue is full. Wait for an active job to finish.")
        queued = previous.model_copy(
            update={
                "stage": ImportJobStage.QUEUED,
                "message": "Waiting for the local import worker",
                "error_code": None,
                "attempt_count": previous.attempt_count + 1,
                "recoverable": False,
                "worker_version": "2.0",
                "worker_pid": None,
                "cancel_requested_at": None,
                "completed_at": None,
                "progress_percent": 0,
                "updated_at": datetime.now(UTC),
            }
        )
        try:
            self._repository.update(queued)
            self._schedule(queued, demo_path)
        except Exception:
            self._capacity.release()
            raise
        return queued

    def cancel(self, job_id: UUID) -> ImportJobRecord:
        self._ensure_started()
        previous = self._require_job(job_id)
        if previous.stage.terminal or previous.stage is ImportJobStage.CANCEL_REQUESTED:
            raise ImportJobNotCancellableError("This import is not currently cancellable.")
        now = datetime.now(UTC)
        self._repository.update(
            previous.model_copy(
                update={
                    "stage": ImportJobStage.CANCEL_REQUESTED,
                    "message": "Cancellation requested; stopping at a safe boundary",
                    "cancel_requested_at": now,
                    "updated_at": now,
                }
            )
        )
        with self._lock:
            event = self._cancel_events.get(job_id)
            future = self._futures.get(job_id)
        if event is not None:
            event.set()
        if future is not None and future.cancel():
            self._mark_cancelled(job_id)
            self._finish_slot(job_id)
        return self._require_job(job_id)

    def _schedule(self, record: ImportJobRecord, demo_path: Path) -> None:
        event = Event()
        with self._lock:
            self._cancel_events[record.job_id] = event
            self._futures[record.job_id] = self._executor.submit(
                self._run_and_release, record.job_id, demo_path, record.original_name, event
            )

    def _run_and_release(
        self, job_id: UUID, demo_path: Path, original_name: str, event: Event
    ) -> None:
        try:
            self._run(job_id, demo_path, original_name, event)
        finally:
            self._finish_slot(job_id)

    def _finish_slot(self, job_id: UUID) -> None:
        with self._lock:
            removed = self._cancel_events.pop(job_id, None)
            self._futures.pop(job_id, None)
        if removed is not None:
            self._capacity.release()

    def _run(self, job_id: UUID, demo_path: Path, original_name: str, event: Event) -> None:
        runner = ParserWorkerRunner(
            self._artifact_root / str(job_id),
            timeout_seconds=self._parser_timeout_seconds,
            memory_limit_bytes=self._parser_memory_limit_bytes,
            minimum_free_disk_bytes=self._minimum_free_disk_bytes,
            cancel_grace_seconds=self._cancel_grace_seconds,
            cancel_event=event,
            on_pid=lambda pid: self._worker_pid(job_id, pid),
            on_peak_memory=lambda value: self._peak_memory(job_id, value),
        )
        try:
            record = self._require_job(job_id)
            snapshot = inspect_local_file(demo_path)
            if record.demo_sha256 is not None and record.demo_sha256 != snapshot.sha256:
                raise RuntimeError("Retained demo SHA-256 changed since the job was created.")
            if record.file_size_bytes is not None and record.file_size_bytes != snapshot.size_bytes:
                raise RuntimeError("Retained demo size changed since the job was created.")
            if record.demo_sha256 is None or record.file_size_bytes is None:
                record = record.model_copy(
                    update={
                        "demo_sha256": snapshot.sha256,
                        "file_size_bytes": snapshot.size_bytes,
                        "updated_at": datetime.now(UTC),
                    }
                )
                self._repository.update(record)
            sha256 = record.demo_sha256
            if sha256 is None:  # model/database invariant guard
                raise RuntimeError("Import job does not have a demo SHA-256.")
            self._check_cancel(job_id, event)
            self._update(job_id, ImportJobStage.CANONICALIZING, "Parsing completed demo")
            dataset = runner.canonicalize(demo_path, sha256)
            self._checkpoint(job_id, ImportJobStage.CANONICALIZING)

            self._check_cancel(job_id, event)
            self._update(
                job_id,
                ImportJobStage.IMPORTING,
                "Persisting canonical evidence",
                match_id=dataset.match.match_id,
            )
            matches = DuckDBMatchRepository(self._database_path)
            result = ImportCanonicalMatchService(matches).import_dataset(
                dataset, source_original_name=original_name
            )
            if result.status is ImportStatus.FAILED:
                raise RuntimeError(result.warnings[-1] if result.warnings else "Import failed")
            self._checkpoint(job_id, ImportJobStage.IMPORTING)

            self._check_cancel(job_id, event)
            self._update(job_id, ImportJobStage.ECONOMY, "Capturing equipment and buys")
            economy_repository = DuckDBEconomyRepository(self._database_path)
            ComputeEconomyService(
                matches, economy_repository, WorkerEconomyExtractor(runner)
            ).compute(dataset.match.match_id, demo_path, config=EconomyConfig())
            self._checkpoint(job_id, ImportJobStage.ECONOMY)

            self._check_cancel(job_id, event)
            analytics = DuckDBAnalyticsRepository(self._database_path)
            self._update(job_id, ImportJobStage.ANALYTICS, "Computing deterministic analytics")
            ComputeMatchAnalyticsService(matches, analytics).compute(
                dataset.match.match_id, config=AnalyticsConfig()
            )
            self._checkpoint(job_id, ImportJobStage.ANALYTICS)

            self._check_cancel(job_id, event)
            temporal = DuckDBTemporalRepository(self._database_path)
            self._update(job_id, ImportJobStage.TEMPORAL, "Computing Temporal 1.1")
            ComputeTemporalStateService(matches, temporal, analytics_repository=analytics).compute(
                dataset.match.match_id, config=TemporalConfig()
            )
            self._checkpoint(job_id, ImportJobStage.TEMPORAL)

            self._check_cancel(job_id, event)
            self._update(job_id, ImportJobStage.SPATIAL, "Extracting spatial samples")
            spatial_repository = DuckDBSpatialRepository(self._database_path)
            spatial_result = ComputeSpatialStateService(
                matches, temporal, spatial_repository, WorkerSpatialExtractor(runner)
            ).compute(
                dataset.match.match_id,
                demo_path,
                config=SpatialConfig(sampling_interval_ticks=self._sampling_interval_ticks),
            )
            self._checkpoint(job_id, ImportJobStage.SPATIAL)

            self._check_cancel(job_id, event)
            self._update(job_id, ImportJobStage.ZONES, "Assigning version-pinned map zones")
            zone_repository = DuckDBZoneAssignmentRepository(self._database_path)
            ComputeZoneAssignmentsService(spatial_repository, zone_repository).compute(
                dataset.match.match_id, spatial_run_id=spatial_result.spatial_run_id
            )
            self._checkpoint(job_id, ImportJobStage.ZONES)

            self._check_cancel(job_id, event)
            self._update(job_id, ImportJobStage.FEATURES, "Materializing round facts")
            ComputeRoundFeaturesService(
                matches,
                analytics,
                temporal,
                spatial_repository,
                zone_repository,
                DuckDBRoundFeatureRepository(self._database_path),
                economy_repository=economy_repository,
            ).compute(dataset.match.match_id, config=RoundFeatureConfig())
            self._checkpoint(job_id, ImportJobStage.FEATURES)
            self._update(
                job_id,
                ImportJobStage.COMPLETE,
                "Match is ready",
                match_id=dataset.match.match_id,
                completed_at=datetime.now(UTC),
            )
        except ImportWorkerCancelledError:
            self._mark_cancelled(job_id)
        except Exception as exc:
            try:
                self._update(
                    job_id,
                    ImportJobStage.FAILED,
                    str(exc)[:400] or "Import failed",
                    error_code=str(getattr(exc, "error_code", "import_job_failed")),
                    recoverable=demo_path.is_file(),
                )
            except ImportJobNotFoundError:
                pass

    def _check_cancel(self, job_id: UUID, event: Event) -> None:
        if event.is_set() or self._require_job(job_id).stage is ImportJobStage.CANCEL_REQUESTED:
            raise ImportWorkerCancelledError("Import cancelled by the user.")

    def _checkpoint(self, job_id: UUID, stage: ImportJobStage) -> None:
        previous = self._require_job(job_id)
        self._repository.update(
            previous.model_copy(
                update={"last_completed_stage": stage, "updated_at": datetime.now(UTC)}
            )
        )

    def _worker_pid(self, job_id: UUID, pid: int | None) -> None:
        try:
            previous = self._require_job(job_id)
            self._repository.update(
                previous.model_copy(update={"worker_pid": pid, "updated_at": datetime.now(UTC)})
            )
        except ImportJobNotFoundError:
            pass

    def _peak_memory(self, job_id: UUID, value: int) -> None:
        try:
            previous = self._require_job(job_id)
            self._repository.update(
                previous.model_copy(
                    update={
                        "peak_worker_memory_bytes": max(
                            previous.peak_worker_memory_bytes or 0, value
                        ),
                        "updated_at": datetime.now(UTC),
                    }
                )
            )
        except ImportJobNotFoundError:
            pass

    def _mark_cancelled(self, job_id: UUID) -> None:
        try:
            record = self._require_job(job_id)
            self._update(
                job_id,
                ImportJobStage.CANCELLED,
                "Import cancelled; retained demo can be retried",
                error_code="import_worker_cancelled",
                recoverable=self._demo_path(record.internal_name).is_file(),
                completed_at=datetime.now(UTC),
            )
        except ImportJobNotFoundError:
            pass

    def _update(
        self,
        job_id: UUID,
        stage: ImportJobStage,
        message: str,
        *,
        match_id: UUID | None = None,
        error_code: str | None = None,
        recoverable: bool = False,
        completed_at: datetime | None = None,
    ) -> None:
        previous = self._require_job(job_id)
        self._repository.update(
            previous.model_copy(
                update={
                    "stage": stage,
                    "message": message,
                    "match_id": match_id if match_id is not None else previous.match_id,
                    "error_code": error_code,
                    "recoverable": recoverable,
                    "worker_pid": None,
                    "completed_at": completed_at,
                    "progress_percent": stage_progress(stage, previous.progress_percent),
                    "updated_at": datetime.now(UTC),
                }
            )
        )

    def _require_job(self, job_id: UUID) -> ImportJobRecord:
        record = self._repository.get(job_id)
        if record is None:
            raise ImportJobNotFoundError(f"Import job not found: {job_id}")
        return record

    def _reject_duplicate(self, sha256: str) -> None:
        existing = self._repository.find_by_sha256(sha256)
        if existing is not None:
            raise ImportDuplicateError(
                "This exact demo is already imported or queued.",
                job_id=existing.job_id,
                match_id=existing.match_id,
            )
        matches = DuckDBMatchRepository(self._database_path)
        found = matches.list_matches(MatchQueryFilters(source_demo_sha256=sha256, limit=1))
        if found:
            raise ImportDuplicateError(
                "This exact demo is already present in the match library.",
                match_id=found[0].match_id,
            )

    def _ensure_started(self) -> None:
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            self._repository.initialize()
            now = datetime.now(UTC)
            for record in self._repository.list_unfinished():
                demo_path = self._demo_path(record.internal_name)
                self._repository.update(
                    record.model_copy(
                        update={
                            "stage": ImportJobStage.FAILED,
                            "message": (
                                "Server stopped during import; retry reuses valid parser artifacts."
                            ),
                            "error_code": "import_interrupted",
                            "recoverable": demo_path.is_file(),
                            "worker_pid": None,
                            "updated_at": now,
                        }
                    )
                )
            self._started = True

    def _demo_path(self, internal_name: str) -> Path:
        candidate = (self._upload_directory / internal_name).resolve()
        if (
            candidate.parent != self._upload_directory
            or candidate.name != internal_name
            or candidate.suffix.casefold() != ".dem"
        ):
            raise ImportJobNotRetryableError("Stored import filename is unsafe.")
        return candidate


__all__ = ["LocalImportJobManager"]
