"""DuckDB persistence for user-confirmed opponent workspaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.application.opponent_models import (
    OpponentMatchSelection,
    OpponentProfile,
)
from stratweb.exceptions import OpponentConflictError, PersistenceError

from .duckdb import DuckDBMatchRepository


class DuckDBOpponentRepository:
    """Persist profile scope without deriving cross-match identity in SQL."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        self._matches = DuckDBMatchRepository(self._database_path)

    def initialize(self) -> tuple[int, ...]:
        return self._matches.initialize()

    def create_profile(self, profile: OpponentProfile) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    """
                    INSERT INTO opponent_profiles (
                        profile_id, display_name, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        profile.profile_id,
                        profile.display_name,
                        _utc_naive(profile.created_at),
                        _utc_naive(profile.updated_at),
                    ],
                )
        except duckdb.ConstraintException as exc:
            raise OpponentConflictError(
                f"An opponent profile named {profile.display_name!r} already exists."
            ) from exc
        except duckdb.Error as exc:
            raise PersistenceError("Could not create opponent profile.") from exc

    def get_profile(self, profile_id: UUID) -> OpponentProfile | None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    "SELECT * FROM opponent_profiles WHERE profile_id = ?",
                    [profile_id],
                )
                row = _fetch_one(cursor)
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not read opponent profile {profile_id}.") from exc
        return _profile(row) if row is not None else None

    def list_profiles(self) -> tuple[OpponentProfile, ...]:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    "SELECT * FROM opponent_profiles ORDER BY display_name, profile_id"
                )
                rows = _fetch_all(cursor)
        except duckdb.Error as exc:
            raise PersistenceError("Could not list opponent profiles.") from exc
        return tuple(_profile(row) for row in rows)

    def rename_profile(self, profile_id: UUID, display_name: str, updated_at: datetime) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    "UPDATE opponent_profiles SET display_name = ?, updated_at = ? "
                    "WHERE profile_id = ?",
                    [display_name, _utc_naive(updated_at), profile_id],
                )
        except duckdb.ConstraintException as exc:
            raise OpponentConflictError(
                f"An opponent profile named {display_name!r} already exists."
            ) from exc
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not rename opponent profile {profile_id}.") from exc

    def delete_profile(self, profile_id: UUID) -> bool:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                existing = connection.execute(
                    "SELECT 1 FROM opponent_profiles WHERE profile_id = ?",
                    [profile_id],
                ).fetchone()
                if existing is None:
                    return False
                connection.execute("BEGIN TRANSACTION")
                try:
                    connection.execute(
                        "DELETE FROM opponent_match_selections WHERE profile_id = ?",
                        [profile_id],
                    )
                    connection.execute(
                        "DELETE FROM opponent_profiles WHERE profile_id = ?",
                        [profile_id],
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                return True
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not delete opponent profile {profile_id}.") from exc

    def save_selection(self, selection: OpponentMatchSelection) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    connection.execute(
                        """
                        INSERT INTO opponent_match_selections (
                            profile_id, match_id, team_id, selection_source, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT (profile_id, match_id) DO UPDATE SET
                            team_id = excluded.team_id,
                            selection_source = excluded.selection_source,
                            created_at = excluded.created_at
                        """,
                        [
                            selection.profile_id,
                            selection.match_id,
                            selection.team_id,
                            selection.selection_source.value,
                            _utc_naive(selection.created_at),
                        ],
                    )
                    connection.execute(
                        "UPDATE opponent_profiles SET updated_at = ? WHERE profile_id = ?",
                        [_utc_naive(selection.created_at), selection.profile_id],
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not save opponent match selection.") from exc

    def list_selections(self, profile_id: UUID) -> tuple[OpponentMatchSelection, ...]:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                cursor = connection.execute(
                    """
                    SELECT * FROM opponent_match_selections
                    WHERE profile_id = ?
                    ORDER BY created_at, match_id
                    """,
                    [profile_id],
                )
                rows = _fetch_all(cursor)
        except duckdb.Error as exc:
            raise PersistenceError("Could not list opponent match selections.") from exc
        return tuple(_selection(row) for row in rows)

    def remove_selection(self, profile_id: UUID, match_id: UUID) -> bool:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                existing = connection.execute(
                    """
                    SELECT 1 FROM opponent_match_selections
                    WHERE profile_id = ? AND match_id = ?
                    """,
                    [profile_id, match_id],
                ).fetchone()
                if existing is None:
                    return False
                connection.execute("BEGIN TRANSACTION")
                try:
                    connection.execute(
                        """
                        DELETE FROM opponent_match_selections
                        WHERE profile_id = ? AND match_id = ?
                        """,
                        [profile_id, match_id],
                    )
                    connection.execute(
                        "UPDATE opponent_profiles SET updated_at = ? WHERE profile_id = ?",
                        [_utc_naive(datetime.now(UTC)), profile_id],
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                return True
        except duckdb.Error as exc:
            raise PersistenceError("Could not remove opponent match selection.") from exc


def _fetch_one(cursor: duckdb.DuckDBPyConnection) -> dict[str, object] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = tuple(item[0] for item in cursor.description)
    return dict(zip(columns, row, strict=True))


def _fetch_all(cursor: duckdb.DuckDBPyConnection) -> tuple[dict[str, object], ...]:
    columns = tuple(item[0] for item in cursor.description)
    return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())


def _profile(row: dict[str, object]) -> OpponentProfile:
    return OpponentProfile.model_validate(_aware_timestamps(row))


def _selection(row: dict[str, object]) -> OpponentMatchSelection:
    return OpponentMatchSelection.model_validate(_aware_timestamps(row))


def _aware_timestamps(row: dict[str, object]) -> dict[str, object]:
    value = dict(row)
    for field in ("created_at", "updated_at"):
        timestamp = value.get(field)
        if isinstance(timestamp, datetime) and timestamp.tzinfo is None:
            value[field] = timestamp.replace(tzinfo=UTC)
    return value


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


__all__ = ["DuckDBOpponentRepository"]
