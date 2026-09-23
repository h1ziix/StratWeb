"""DuckDB persistence for durable local import-job checkpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.application.import_job_models import (
    ImportJobRecord,
    ImportJobStage,
    validate_stage_transition,
)
from stratweb.exceptions import (
    ImportDuplicateError,
    ImportJobTransitionConflictError,
    PersistenceError,
)

from .duckdb import DuckDBMatchRepository
from .write_coordinator import get_write_coordinator


class DuckDBImportJobRepository:
    """Store queue state separately from immutable match evidence."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        self._matches = DuckDBMatchRepository(self._database_path)
        self._writes = get_write_coordinator(self._database_path)

    def initialize(self) -> tuple[int, ...]:
        return self._matches.initialize()

    def create(self, record: ImportJobRecord) -> None:
        self.initialize()
        try:
            with self._writes.serialized():
                with duckdb.connect(str(self._database_path), read_only=False) as connection:
                    connection.execute(
                        """
                        INSERT INTO import_jobs (
                            job_id, stage, original_name, internal_name, match_id,
                            message, error_code, attempt_count, recoverable,
                            progress_percent, created_at, updated_at, demo_sha256,
                            file_size_bytes, last_completed_stage, worker_version,
                            worker_pid, peak_worker_memory_bytes, cancel_requested_at,
                            completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        _parameters(record),
                    )
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not create import job {record.job_id}.") from exc

    def create_if_sha256_absent(self, record: ImportJobRecord) -> None:
        self.initialize()
        if record.demo_sha256 is None:
            raise ValueError("Atomic import-job reservation requires a demo SHA-256.")
        try:
            with self._writes.serialized():
                with duckdb.connect(str(self._database_path), read_only=False) as connection:
                    connection.execute("BEGIN TRANSACTION")
                    try:
                        existing_job = connection.execute(
                            """
                            SELECT job_id, match_id FROM import_jobs
                            WHERE demo_sha256 = ? AND stage != 'cancelled'
                            ORDER BY updated_at DESC, job_id LIMIT 1
                            """,
                            [record.demo_sha256],
                        ).fetchone()
                        if existing_job is not None:
                            raise ImportDuplicateError(
                                "This exact demo is already imported or queued.",
                                job_id=existing_job[0],
                                match_id=existing_job[1],
                            )
                        existing_match = connection.execute(
                            """
                            SELECT match_id FROM matches
                            WHERE source_demo_sha256 = ? LIMIT 1
                            """,
                            [record.demo_sha256],
                        ).fetchone()
                        if existing_match is not None:
                            raise ImportDuplicateError(
                                "This exact demo is already present in the match library.",
                                match_id=existing_match[0],
                            )
                        connection.execute(
                            """
                            INSERT INTO import_jobs (
                                job_id, stage, original_name, internal_name, match_id,
                                message, error_code, attempt_count, recoverable,
                                progress_percent, created_at, updated_at, demo_sha256,
                                file_size_bytes, last_completed_stage, worker_version,
                                worker_pid, peak_worker_memory_bytes, cancel_requested_at,
                                completed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            _parameters(record),
                        )
                        connection.execute("COMMIT")
                    except Exception:
                        connection.execute("ROLLBACK")
                        raise
        except ImportDuplicateError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not reserve import job {record.job_id}.") from exc

    def get(self, job_id: UUID) -> ImportJobRecord | None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                row = connection.execute(
                    "SELECT * FROM import_jobs WHERE job_id = ?",
                    [job_id],
                )
                result = _fetch_one(row)
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not read import job {job_id}.") from exc
        return _record(result) if result is not None else None

    def update(
        self,
        record: ImportJobRecord,
        *,
        expected_stage: ImportJobStage | None = None,
    ) -> None:
        self.initialize()
        if expected_stage is not None:
            validate_stage_transition(expected_stage, record.stage)
        try:
            with self._writes.serialized():
                with duckdb.connect(str(self._database_path), read_only=False) as connection:
                    statement = """
                        UPDATE import_jobs SET
                            stage = ?, original_name = ?, internal_name = ?, match_id = ?,
                            message = ?, error_code = ?, attempt_count = ?, recoverable = ?,
                            progress_percent = ?, created_at = ?, updated_at = ?,
                            demo_sha256 = ?, file_size_bytes = ?, last_completed_stage = ?,
                            worker_version = ?, worker_pid = ?, peak_worker_memory_bytes = ?,
                            cancel_requested_at = ?, completed_at = ?
                        WHERE job_id = ?
                    """
                    parameters = [*_parameters(record)[1:], record.job_id]
                    if expected_stage is not None:
                        statement += " AND stage = ? RETURNING job_id"
                        parameters.append(expected_stage.value)
                    cursor = connection.execute(
                        statement,
                        parameters,
                    )
                    if expected_stage is not None and cursor.fetchone() is None:
                        raise ImportJobTransitionConflictError(
                            f"Import job {record.job_id} changed before the update completed."
                        )
        except ImportJobTransitionConflictError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not update import job {record.job_id}.") from exc

    def list_unfinished(self) -> tuple[ImportJobRecord, ...]:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    """
                    SELECT * FROM import_jobs
                    WHERE stage NOT IN ('complete', 'failed', 'cancelled')
                    ORDER BY created_at, job_id
                    """
                )
                columns = tuple(item[0] for item in cursor.description)
                rows = tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
        except duckdb.Error as exc:
            raise PersistenceError("Could not list unfinished import jobs.") from exc
        return tuple(_record(row) for row in rows)

    def list_recent(self, limit: int = 20) -> tuple[ImportJobRecord, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    """
                    SELECT * FROM import_jobs
                    ORDER BY updated_at DESC, job_id
                    LIMIT ?
                    """,
                    [limit],
                )
                columns = tuple(item[0] for item in cursor.description)
                rows = tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
        except duckdb.Error as exc:
            raise PersistenceError("Could not list recent import jobs.") from exc
        return tuple(_record(row) for row in rows)

    def find_by_sha256(self, sha256: str) -> ImportJobRecord | None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    """
                    SELECT * FROM import_jobs
                    WHERE demo_sha256 = ? AND stage != 'cancelled'
                    ORDER BY updated_at DESC, job_id
                    LIMIT 1
                    """,
                    [sha256],
                )
                row = _fetch_one(cursor)
        except duckdb.Error as exc:
            raise PersistenceError("Could not check import-job duplicate hash.") from exc
        return _record(row) if row is not None else None


def _parameters(record: ImportJobRecord) -> list[object]:
    return [
        record.job_id,
        record.stage.value,
        record.original_name,
        record.internal_name,
        record.match_id,
        record.message,
        record.error_code,
        record.attempt_count,
        record.recoverable,
        record.progress_percent,
        _utc_naive(record.created_at),
        _utc_naive(record.updated_at),
        record.demo_sha256,
        record.file_size_bytes,
        record.last_completed_stage.value if record.last_completed_stage is not None else None,
        record.worker_version,
        record.worker_pid,
        record.peak_worker_memory_bytes,
        _utc_naive(record.cancel_requested_at) if record.cancel_requested_at else None,
        _utc_naive(record.completed_at) if record.completed_at else None,
    ]


def _fetch_one(cursor: duckdb.DuckDBPyConnection) -> dict[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = tuple(item[0] for item in cursor.description)
    return dict(zip(columns, row, strict=True))


def _record(row: dict[str, object]) -> ImportJobRecord:
    value = dict(row)
    for field in ("created_at", "updated_at", "cancel_requested_at", "completed_at"):
        timestamp = value[field]
        if isinstance(timestamp, datetime) and timestamp.tzinfo is None:
            value[field] = timestamp.replace(tzinfo=UTC)
    return ImportJobRecord.model_validate(value)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = ["DuckDBImportJobRepository"]
