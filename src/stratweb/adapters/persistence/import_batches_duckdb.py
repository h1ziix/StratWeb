"""DuckDB persistence for grouped multi-demo uploads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.application.import_batch_models import ImportBatchItem, ImportBatchRecord
from stratweb.exceptions import PersistenceError

from .duckdb import DuckDBMatchRepository


class DuckDBImportBatchRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        self._matches = DuckDBMatchRepository(self._database_path)

    def initialize(self) -> tuple[int, ...]:
        return self._matches.initialize()

    def create(self, record: ImportBatchRecord) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    "INSERT INTO import_batches VALUES (?, ?, ?, ?)",
                    [
                        record.batch_id,
                        record.display_name,
                        record.opponent_profile_id,
                        _utc_naive(record.created_at),
                    ],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Could not create import batch.") from exc

    def add_item(self, item: ImportBatchItem) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    """
                    INSERT INTO import_batch_items (
                        batch_id, item_index, original_name, disposition, job_id,
                        existing_match_id, error_code, message, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        item.batch_id,
                        item.item_index,
                        item.original_name,
                        item.disposition.value,
                        item.job_id,
                        item.existing_match_id,
                        item.error_code,
                        item.message,
                        _utc_naive(item.created_at),
                    ],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Could not add import-batch item.") from exc

    def get(self, batch_id: UUID) -> ImportBatchRecord | None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    "SELECT * FROM import_batches WHERE batch_id = ?", [batch_id]
                )
                row = _fetch_one(cursor)
        except duckdb.Error as exc:
            raise PersistenceError("Could not read import batch.") from exc
        return ImportBatchRecord.model_validate(_aware(row)) if row is not None else None

    def list_items(self, batch_id: UUID) -> tuple[ImportBatchItem, ...]:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    """
                    SELECT * FROM import_batch_items
                    WHERE batch_id = ? ORDER BY item_index
                    """,
                    [batch_id],
                )
                columns = tuple(item[0] for item in cursor.description)
                rows = tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
        except duckdb.Error as exc:
            raise PersistenceError("Could not list import-batch items.") from exc
        return tuple(ImportBatchItem.model_validate(_aware(row)) for row in rows)

    def list_recent(self, limit: int = 10) -> tuple[ImportBatchRecord, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    "SELECT * FROM import_batches ORDER BY created_at DESC, batch_id LIMIT ?",
                    [limit],
                )
                columns = tuple(item[0] for item in cursor.description)
                rows = tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
        except duckdb.Error as exc:
            raise PersistenceError("Could not list recent import batches.") from exc
        return tuple(ImportBatchRecord.model_validate(_aware(row)) for row in rows)


def _fetch_one(cursor: duckdb.DuckDBPyConnection) -> dict[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip((item[0] for item in cursor.description), row, strict=True))


def _aware(row: dict[str, object]) -> dict[str, object]:
    value = dict(row)
    timestamp = value.get("created_at")
    if isinstance(timestamp, datetime) and timestamp.tzinfo is None:
        value["created_at"] = timestamp.replace(tzinfo=UTC)
    return value


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = ["DuckDBImportBatchRepository"]
