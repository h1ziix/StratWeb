"""DuckDB persistence for immutable head-to-head comparison runs."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import PersistenceError
from stratweb.head_to_head.models import (
    HEAD_TO_HEAD_RULE_VERSION,
    HEAD_TO_HEAD_SCHEMA_VERSION,
    HeadToHeadRun,
    HeadToHeadRunRecord,
    HeadToHeadSaveResult,
    HeadToHeadSaveStatus,
)


class DuckDBHeadToHeadRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save(self, state: HeadToHeadRun) -> HeadToHeadSaveResult:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    _preflight(connection, state)
                    existing = connection.execute(
                        "SELECT head_to_head_run_id FROM head_to_head_runs "
                        "WHERE head_to_head_fingerprint = ?",
                        [state.head_to_head_fingerprint],
                    ).fetchone()
                    if existing is not None:
                        connection.execute("COMMIT")
                        return HeadToHeadSaveResult(
                            head_to_head_run_id=UUID(str(existing[0])),
                            head_to_head_fingerprint=state.head_to_head_fingerprint,
                            status=HeadToHeadSaveStatus.ALREADY_EXISTS,
                        )
                    connection.execute(
                        """
                        INSERT INTO head_to_head_runs (
                            head_to_head_run_id, head_to_head_fingerprint,
                            head_to_head_schema_version, head_to_head_rule_version,
                            opponent_profile_id, our_profile_id,
                            opponent_tactical_run_id, our_tactical_run_id, payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            state.head_to_head_run_id,
                            state.head_to_head_fingerprint,
                            state.head_to_head_schema_version,
                            state.head_to_head_rule_version,
                            state.opponent_profile_id,
                            state.our_profile_id,
                            state.opponent_tactical_run_id,
                            state.our_tactical_run_id,
                            canonical_json(state.model_dump(mode="json")),
                        ],
                    )
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except PersistenceError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist head-to-head comparison.") from exc
        return HeadToHeadSaveResult(
            head_to_head_run_id=state.head_to_head_run_id,
            head_to_head_fingerprint=state.head_to_head_fingerprint,
            status=HeadToHeadSaveStatus.COMPUTED,
        )

    def get_for_sources(
        self,
        opponent_profile_id: UUID,
        our_profile_id: UUID,
        opponent_tactical_run_id: UUID,
        our_tactical_run_id: UUID,
    ) -> HeadToHeadRun | None:
        self.initialize()
        with read_connection(self._database_path, "head-to-head") as connection:
            row = connection.execute(
                """
                SELECT payload FROM head_to_head_runs
                WHERE opponent_profile_id = ? AND our_profile_id = ?
                  AND opponent_tactical_run_id = ? AND our_tactical_run_id = ?
                  AND head_to_head_schema_version = ? AND head_to_head_rule_version = ?
                ORDER BY created_at DESC, head_to_head_fingerprint DESC LIMIT 1
                """,
                [
                    opponent_profile_id,
                    our_profile_id,
                    opponent_tactical_run_id,
                    our_tactical_run_id,
                    HEAD_TO_HEAD_SCHEMA_VERSION,
                    HEAD_TO_HEAD_RULE_VERSION,
                ],
            ).fetchone()
        return HeadToHeadRun.model_validate(_json(row[0])) if row is not None else None

    def get_run(
        self, opponent_profile_id: UUID, our_profile_id: UUID, run_id: UUID
    ) -> HeadToHeadRun | None:
        self.initialize()
        with read_connection(self._database_path, "head-to-head") as connection:
            row = connection.execute(
                "SELECT payload FROM head_to_head_runs WHERE head_to_head_run_id = ? "
                "AND opponent_profile_id = ? AND our_profile_id = ?",
                [run_id, opponent_profile_id, our_profile_id],
            ).fetchone()
        return HeadToHeadRun.model_validate(_json(row[0])) if row is not None else None

    def list_runs(
        self, opponent_profile_id: UUID, our_profile_id: UUID
    ) -> tuple[HeadToHeadRunRecord, ...]:
        self.initialize()
        with read_connection(self._database_path, "head-to-head") as connection:
            cursor = connection.execute(
                """
                SELECT head_to_head_run_id, head_to_head_fingerprint,
                       opponent_profile_id, our_profile_id,
                       opponent_tactical_run_id, our_tactical_run_id,
                       head_to_head_schema_version, head_to_head_rule_version, created_at
                FROM head_to_head_runs
                WHERE opponent_profile_id = ? AND our_profile_id = ?
                ORDER BY created_at DESC, head_to_head_fingerprint DESC
                """,
                [opponent_profile_id, our_profile_id],
            )
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        return tuple(
            HeadToHeadRunRecord(
                **dict(zip(columns, row, strict=True)),
                compatible=(str(row[6]), str(row[7]))
                == (HEAD_TO_HEAD_SCHEMA_VERSION, HEAD_TO_HEAD_RULE_VERSION),
            )
            for row in rows
        )


def _preflight(connection: duckdb.DuckDBPyConnection, state: HeadToHeadRun) -> None:
    for profile_id in (state.opponent_profile_id, state.our_profile_id):
        if (
            connection.execute(
                "SELECT 1 FROM opponent_profiles WHERE profile_id = ?", [profile_id]
            ).fetchone()
            is None
        ):
            raise PersistenceError("Head-to-head profile does not exist.")
    source_rows = (
        (state.opponent_tactical_run_id, state.opponent_profile_id),
        (state.our_tactical_run_id, state.our_profile_id),
    )
    for tactical_run_id, profile_id in source_rows:
        if (
            connection.execute(
                "SELECT 1 FROM tactical_v2_runs WHERE tactical_run_id = ? AND profile_id = ?",
                [tactical_run_id, profile_id],
            ).fetchone()
            is None
        ):
            raise PersistenceError("Head-to-head Tactical V2 source does not exist.")


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBHeadToHeadRepository"]
