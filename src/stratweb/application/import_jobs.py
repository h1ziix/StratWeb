"""Controlled single-process jobs for localhost completed-demo imports."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import UUID, uuid4

from stratweb.adapters.parsers import Demoparser2Adapter, Demoparser2SpatialExtractor
from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBImportJobRepository,
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
)
from stratweb.analytics.models import AnalyticsConfig
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.import_job_models import (
    ImportJobRecord,
    ImportJobStage,
    stage_progress,
)
from stratweb.application.persistence import ImportCanonicalMatchService
from stratweb.application.persistence_models import ImportStatus
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.exceptions import ImportJobNotFoundError, ImportJobNotRetryableError
from stratweb.ports import ImportJobRepository
from stratweb.spatial.models import SpatialConfig
from stratweb.temporal.models import TemporalConfig


class LocalImportJobManager:
    """One bounded worker backed by durable, retryable pipeline checkpoints."""

    def __init__(
        self,
        database_path: Path,
        *,
        sampling_interval_ticks: int = 16,
        repository: ImportJobRepository | None = None,
    ) -> None:
        self._database_path = database_path.expanduser().resolve()
        self._sampling_interval_ticks = sampling_interval_ticks
        self._repository = repository or DuckDBImportJobRepository(self._database_path)
        self._upload_directory = (self._database_path.parent / "uploads").resolve()
        self._lock = Lock()
        self._started = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stratweb-import")

    def submit(self, demo_path: Path, original_name: str) -> ImportJobRecord:
        self._ensure_started()
        job_id = uuid4()
        now = datetime.now(UTC)
        record = ImportJobRecord.create(
            job_id=job_id,
            original_name=original_name,
            internal_name=demo_path.name,
            now=now,
        )
        self._repository.create(record)
        self._executor.submit(self._run, job_id, demo_path, original_name)
        return record

    def get(self, job_id: UUID) -> ImportJobRecord | None:
        self._ensure_started()
        return self._repository.get(job_id)

    def list_recent(self, limit: int = 10) -> tuple[ImportJobRecord, ...]:
        self._ensure_started()
        return self._repository.list_recent(limit)

    def retry(self, job_id: UUID) -> ImportJobRecord:
        """Retry one failed durable job from its safely retained uploaded demo."""

        self._ensure_started()
        previous = self._repository.get(job_id)
        if previous is None:
            raise ImportJobNotFoundError(f"Import job not found: {job_id}")
        demo_path = self._demo_path(previous.internal_name)
        if (
            previous.stage is not ImportJobStage.FAILED
            or not previous.recoverable
            or not demo_path.is_file()
        ):
            raise ImportJobNotRetryableError(
                "This import cannot be retried because its uploaded demo is unavailable "
                "or the job is not failed."
            )
        now = datetime.now(UTC)
        queued = previous.model_copy(
            update={
                "stage": ImportJobStage.QUEUED,
                "message": "Waiting for the local import worker",
                "error_code": None,
                "attempt_count": previous.attempt_count + 1,
                "recoverable": False,
                "progress_percent": stage_progress(ImportJobStage.QUEUED),
                "updated_at": now,
            }
        )
        self._repository.update(queued)
        self._executor.submit(self._run, job_id, demo_path, previous.original_name)
        return queued

    def _run(self, job_id: UUID, demo_path: Path, original_name: str) -> None:
        try:
            self._update(job_id, ImportJobStage.CANONICALIZING, "Parsing completed demo")
            dataset = CanonicalizationService(Demoparser2Adapter()).normalize(demo_path)
            self._update(
                job_id,
                ImportJobStage.IMPORTING,
                "Persisting canonical evidence",
                match_id=dataset.match.match_id,
            )
            matches = DuckDBMatchRepository(self._database_path)
            result = ImportCanonicalMatchService(matches).import_dataset(
                dataset,
                source_original_name=original_name,
            )
            if result.status is ImportStatus.FAILED:
                raise RuntimeError(result.warnings[-1] if result.warnings else "Import failed")
            analytics = DuckDBAnalyticsRepository(self._database_path)
            self._update(job_id, ImportJobStage.ANALYTICS, "Computing deterministic analytics")
            ComputeMatchAnalyticsService(matches, analytics).compute(
                dataset.match.match_id,
                config=AnalyticsConfig(),
            )
            temporal = DuckDBTemporalRepository(self._database_path)
            self._update(job_id, ImportJobStage.TEMPORAL, "Computing Temporal 1.1")
            ComputeTemporalStateService(
                matches,
                temporal,
                analytics_repository=analytics,
            ).compute(dataset.match.match_id, config=TemporalConfig())
            self._update(job_id, ImportJobStage.SPATIAL, "Extracting authoritative spatial samples")
            ComputeSpatialStateService(
                matches,
                temporal,
                DuckDBSpatialRepository(self._database_path),
                Demoparser2SpatialExtractor(),
            ).compute(
                dataset.match.match_id,
                demo_path,
                config=SpatialConfig(sampling_interval_ticks=self._sampling_interval_ticks),
            )
            self._update(
                job_id,
                ImportJobStage.COMPLETE,
                "Match is ready",
                match_id=dataset.match.match_id,
                recoverable=False,
            )
        except Exception as exc:  # boundary converts parser/database failures to a job status
            error_code = getattr(exc, "error_code", "import_job_failed")
            try:
                self._update(
                    job_id,
                    ImportJobStage.FAILED,
                    str(exc)[:400] or "Import failed",
                    error_code=str(error_code),
                    recoverable=demo_path.is_file(),
                )
            except ImportJobNotFoundError:
                # The job row was removed concurrently; do not let the lookup
                # failure replace the original pipeline error in this thread.
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
    ) -> None:
        previous = self._repository.get(job_id)
        if previous is None:
            raise ImportJobNotFoundError(f"Import job not found: {job_id}")
        self._repository.update(
            previous.model_copy(
                update={
                    "stage": stage,
                    "message": message,
                    "match_id": match_id if match_id is not None else previous.match_id,
                    "error_code": error_code,
                    "recoverable": recoverable,
                    "progress_percent": stage_progress(stage, previous.progress_percent),
                    "updated_at": datetime.now(UTC),
                }
            )
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
                                "The server stopped before this import finished. "
                                "Retry continues safely from the retained demo."
                            ),
                            "error_code": "import_interrupted",
                            "recoverable": demo_path.is_file(),
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
