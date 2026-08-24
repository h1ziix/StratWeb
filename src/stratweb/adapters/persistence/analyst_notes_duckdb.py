"""DuckDB persistence for local, non-evidentiary analyst notes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb

from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.analyst_notes import (
    ANALYST_NOTE_SCHEMA_VERSION,
    AnalystNote,
    normalize_analyst_note,
)
from stratweb.exceptions import PersistenceError, TacticalV2NotFoundError


class DuckDBAnalystNoteRepository:
    """Stores one user-owned note per exact Tactical run and insight."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def get(self, profile_id: UUID, tactical_run_id: UUID, insight_id: UUID) -> AnalystNote | None:
        DuckDBMatchRepository(self._database_path).initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                row = connection.execute(
                    "SELECT note_id, profile_id, tactical_run_id, insight_id, body, "
                    "note_schema_version, created_at, updated_at FROM analyst_notes "
                    "WHERE profile_id = ? AND tactical_run_id = ? AND insight_id = ?",
                    [profile_id, tactical_run_id, insight_id],
                ).fetchone()
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось прочитать заметку аналитика.") from exc
        return _to_note(row) if row is not None else None

    def save(
        self,
        profile_id: UUID,
        tactical_run_id: UUID,
        insight_id: UUID,
        body: str,
    ) -> AnalystNote:
        normalized = normalize_analyst_note(body)
        DuckDBMatchRepository(self._database_path).initialize()
        note_id = uuid5(
            NAMESPACE_URL,
            f"stratweb:analyst-note:{tactical_run_id}:{insight_id}",
        )
        now = datetime.now(UTC)
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM tactical_v2_insights "
                    "WHERE profile_id = ? AND tactical_run_id = ? AND insight_id = ?",
                    [profile_id, tactical_run_id, insight_id],
                ).fetchone()
                if exists is None:
                    raise TacticalV2NotFoundError(
                        "Наблюдение не найдено в выбранном тактическом расчёте."
                    )
                connection.execute(
                    "INSERT INTO analyst_notes VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (tactical_run_id, insight_id) DO UPDATE SET "
                    "body = excluded.body, note_schema_version = excluded.note_schema_version, "
                    "updated_at = excluded.updated_at",
                    [
                        note_id,
                        profile_id,
                        tactical_run_id,
                        insight_id,
                        normalized,
                        ANALYST_NOTE_SCHEMA_VERSION,
                        now,
                        now,
                    ],
                )
                row = connection.execute(
                    "SELECT note_id, profile_id, tactical_run_id, insight_id, body, "
                    "note_schema_version, created_at, updated_at FROM analyst_notes "
                    "WHERE tactical_run_id = ? AND insight_id = ?",
                    [tactical_run_id, insight_id],
                ).fetchone()
        except TacticalV2NotFoundError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось сохранить заметку аналитика.") from exc
        if row is None:  # pragma: no cover - defensive database invariant
            raise PersistenceError("Сохранённая заметка аналитика не найдена.")
        return _to_note(row)

    def delete(self, profile_id: UUID, tactical_run_id: UUID, insight_id: UUID) -> bool:
        DuckDBMatchRepository(self._database_path).initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                before = connection.execute(
                    "SELECT count(*) FROM analyst_notes WHERE profile_id = ? "
                    "AND tactical_run_id = ? AND insight_id = ?",
                    [profile_id, tactical_run_id, insight_id],
                ).fetchone()
                connection.execute(
                    "DELETE FROM analyst_notes WHERE profile_id = ? "
                    "AND tactical_run_id = ? AND insight_id = ?",
                    [profile_id, tactical_run_id, insight_id],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось удалить заметку аналитика.") from exc
        return bool(before and before[0])


def _to_note(row: tuple[object, ...]) -> AnalystNote:
    return AnalystNote(
        note_id=row[0],
        profile_id=row[1],
        tactical_run_id=row[2],
        insight_id=row[3],
        body=str(row[4]),
        note_schema_version=str(row[5]),
        created_at=row[6],
        updated_at=row[7],
    )


__all__ = ["DuckDBAnalystNoteRepository"]
