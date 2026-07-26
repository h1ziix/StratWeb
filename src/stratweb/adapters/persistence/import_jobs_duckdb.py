"""DuckDB persistence for durable local import-job checkpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.application.import_job_models import ImportJobRecord
from stratweb.exceptions import PersistenceError

from .duckdb import DuckDBMatchRepository


class DuckDBImportJobRepository:
    """Store queue state separately from immutable match evidence."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        self._matches = DuckDBMatchRepository(self._database_path)

    def initialize(self) -> tuple[int, ...]:
        return self._matches.initialize()

    def create(self, record: ImportJobRecord) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    """
                    INSERT INTO import_jobs (
                        job_id, stage, original_name, internal_name, match_id,
                        message, error_code, attempt_count, recoverable,
                        progress_percent, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _parameters(record),
                )
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not create import job {record.job_id}.") from exc

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

    def update(self, record: ImportJobRecord) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    """
                    UPDATE import_jobs SET
                        stage = ?, original_name = ?, internal_name = ?, match_id = ?,
                        message = ?, error_code = ?, attempt_count = ?, recoverable = ?,
                        progress_percent = ?, created_at = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    [*_parameters(record)[1:], record.job_id],
                )
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not update import job {record.job_id}.") from exc

    def list_unfinished(self) -> tuple[ImportJobRecord, ...]:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    """
                    SELECT * FROM import_jobs
                    WHERE stage NOT IN ('complete', 'failed')
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
    ]


def _fetch_one(cursor: duckdb.DuckDBPyConnection) -> dict[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = tuple(item[0] for item in cursor.description)
    return dict(zip(columns, row, strict=True))


def _record(row: dict[str, object]) -> ImportJobRecord:
    value = dict(row)
    for field in ("created_at", "updated_at"):
        timestamp = value[field]
        if isinstance(timestamp, datetime) and timestamp.tzinfo is None:
            value[field] = timestamp.replace(tzinfo=UTC)
    return ImportJobRecord.model_validate(value)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = ["DuckDBImportJobRepository"]
