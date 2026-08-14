"""DuckDB persistence for user-facing team labels."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.team_names import TeamDisplayLabel, TeamNameSource
from stratweb.exceptions import MatchNotFoundError, PersistenceError


class DuckDBTeamNameRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def list_for_match(self, match_id: UUID) -> tuple[TeamDisplayLabel, ...]:
        DuckDBMatchRepository(self._database_path).initialize()
        try:
            # DuckDB requires all in-process connections to one file to use the
            # same configuration. Import workers keep read-write connections open.
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                rows = connection.execute(
                    "SELECT match_id, team_id, display_name, source, source_reference, "
                    "updated_at FROM team_display_labels WHERE match_id = ? ORDER BY team_id",
                    [match_id],
                ).fetchall()
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось прочитать названия команд.") from exc
        return tuple(
            TeamDisplayLabel(
                match_id=row[0],
                team_id=row[1],
                display_name=row[2],
                source=TeamNameSource(row[3]),
                source_reference=row[4],
                updated_at=row[5],
            )
            for row in rows
        )

    def save(
        self,
        match_id: UUID,
        team_id: UUID,
        display_name: str,
        *,
        source: TeamNameSource = TeamNameSource.MANUAL,
        source_reference: str | None = None,
    ) -> TeamDisplayLabel:
        matches = DuckDBMatchRepository(self._database_path)
        matches.initialize()
        if matches.get_match(match_id) is None:
            raise MatchNotFoundError(f"Матч не найден: {match_id}")
        if team_id not in {item.team_id for item in matches.get_teams(match_id)}:
            raise MatchNotFoundError("Команда не принадлежит выбранному матчу.")
        now = datetime.now(UTC)
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    "INSERT INTO team_display_labels VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (match_id, team_id) DO UPDATE SET "
                    "display_name = excluded.display_name, source = excluded.source, "
                    "source_reference = excluded.source_reference, "
                    "updated_at = excluded.updated_at",
                    [match_id, team_id, display_name, source.value, source_reference, now],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось сохранить название команды.") from exc
        return TeamDisplayLabel(
            match_id=match_id,
            team_id=team_id,
            display_name=display_name,
            source=source,
            source_reference=source_reference,
            updated_at=now,
        )

    def delete(self, match_id: UUID, team_id: UUID) -> bool:
        DuckDBMatchRepository(self._database_path).initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                before = connection.execute(
                    "SELECT count(*) FROM team_display_labels WHERE match_id = ? AND team_id = ?",
                    [match_id, team_id],
                ).fetchone()
                connection.execute(
                    "DELETE FROM team_display_labels WHERE match_id = ? AND team_id = ?",
                    [match_id, team_id],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось удалить название команды.") from exc
        return bool(before and before[0])


__all__ = ["DuckDBTeamNameRepository"]
