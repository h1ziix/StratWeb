"""DuckDB persistence for user-owned telestrator boards."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import duckdb

from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.telestrator import (
    TelestratorBoard,
    TelestratorBoardUpdate,
    TelestratorConflictError,
    TelestratorRoundNotFoundError,
)
from stratweb.exceptions import PersistenceError


class DuckDBTelestratorRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def get(self, match_id: UUID, round_number: int) -> TelestratorBoard:
        self._initialize_and_validate_round(match_id, round_number)
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                row = connection.execute(
                    "SELECT payload FROM telestrator_boards WHERE match_id=? AND round_number=?",
                    [match_id, round_number],
                ).fetchone()
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось загрузить разметку карты.") from exc
        if row is None:
            return _empty_board(match_id, round_number)
        return TelestratorBoard.model_validate(_json(row[0]))

    def save(
        self,
        match_id: UUID,
        round_number: int,
        update: TelestratorBoardUpdate,
    ) -> TelestratorBoard:
        self._initialize_and_validate_round(match_id, round_number)
        now = datetime.now(UTC)
        board_id = _board_id(match_id, round_number)
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    existing = connection.execute(
                        "SELECT revision, created_at FROM telestrator_boards "
                        "WHERE match_id=? AND round_number=?",
                        [match_id, round_number],
                    ).fetchone()
                    revision = int(existing[0]) if existing is not None else 0
                    if revision != update.expected_revision:
                        raise TelestratorConflictError(
                            "Разметка уже изменена в другой вкладке. "
                            "Обновите доску перед сохранением."
                        )
                    created_at = _aware(existing[1]) if existing is not None else now
                    board = TelestratorBoard(
                        board_id=board_id,
                        match_id=match_id,
                        round_number=round_number,
                        revision=revision + 1,
                        annotations=update.annotations,
                        created_at=created_at,
                        updated_at=now,
                    )
                    connection.execute(
                        """INSERT INTO telestrator_boards (
                               board_id, match_id, round_number, schema_version,
                               revision, payload, created_at, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT (match_id, round_number) DO UPDATE SET
                               schema_version=excluded.schema_version,
                               revision=excluded.revision,
                               payload=excluded.payload,
                               updated_at=excluded.updated_at""",
                        [
                            board.board_id,
                            board.match_id,
                            board.round_number,
                            board.schema_version,
                            board.revision,
                            canonical_json(board.model_dump(mode="json")),
                            _naive(created_at),
                            _naive(now),
                        ],
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except TelestratorConflictError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось сохранить разметку карты.") from exc
        return board

    def _initialize_and_validate_round(self, match_id: UUID, round_number: int) -> None:
        if round_number < 1:
            raise ValueError("round_number must be positive")
        DuckDBMatchRepository(self._database_path).initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM rounds WHERE match_id=? AND round_number=?",
                    [match_id, round_number],
                ).fetchone()
        except duckdb.Error as exc:
            raise PersistenceError("Не удалось проверить раунд для разметки.") from exc
        if exists is None:
            raise TelestratorRoundNotFoundError("Раунд для разметки не найден.")


def _empty_board(match_id: UUID, round_number: int) -> TelestratorBoard:
    return TelestratorBoard(
        board_id=_board_id(match_id, round_number),
        match_id=match_id,
        round_number=round_number,
        revision=0,
        annotations=(),
    )


def _board_id(match_id: UUID, round_number: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"stratweb:telestrator:{match_id}:{round_number}")


def _aware(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise PersistenceError("Некорректное время создания разметки.")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBTelestratorRepository"]
