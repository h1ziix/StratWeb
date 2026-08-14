"""DuckDB persistence for immutable versioned economy runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
import polars as pl

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence._feature_cascade import delete_dependent_feature_runs
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.economy.models import (
    ECONOMY_RULE_VERSION,
    ECONOMY_SCHEMA_VERSION,
    BuyType,
    EconomyComputeStatus,
    EconomyRunRecord,
    EconomyRunSummary,
    EconomySaveResult,
    EconomyState,
    PlayerEquipmentSnapshot,
    TeamEconomySnapshot,
)
from stratweb.exceptions import EconomyIntegrityError, PersistenceError


class DuckDBEconomyRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_economy(self, state: EconomyState, *, replace: bool = False) -> EconomySaveResult:
        self.initialize()
        expected = {
            "economy_runs": 1,
            "player_equipment_snapshots": len(state.player_snapshots),
            "team_economy_snapshots": len(state.team_snapshots),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT economy_run_id FROM economy_runs WHERE economy_fingerprint = ?",
                        [state.economy_fingerprint],
                    ).fetchone()
                    collisions = connection.execute(
                        """
                        SELECT economy_run_id, economy_fingerprint
                        FROM economy_runs
                        WHERE dataset_fingerprint = ?
                          AND source_demo_sha256 = ?
                          AND parser_name = ? AND parser_version = ?
                          AND economy_rule_version = ?
                          AND economy_config_hash = ?
                        """,
                        [
                            state.dataset_fingerprint,
                            state.source_demo_sha256,
                            state.parser_name,
                            state.parser_version,
                            state.economy_rule_version,
                            state.economy_config_hash,
                        ],
                    ).fetchall()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return EconomySaveResult(
                            economy_run_id=run_id,
                            economy_fingerprint=state.economy_fingerprint,
                            status=EconomyComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if (
                        collisions
                        and not replace
                        and all(str(row[1]) != state.economy_fingerprint for row in collisions)
                    ):
                        raise EconomyIntegrityError(
                            "The same economy inputs produced another fingerprint."
                        )
                    replacing = exact is not None or bool(collisions)
                    deleted: set[UUID] = set()
                    for run_id, _ in collisions:
                        parsed = UUID(str(run_id))
                        self._delete_run(connection, parsed)
                        deleted.add(parsed)
                    if exact is not None and UUID(str(exact[0])) not in deleted:
                        self._delete_run(connection, UUID(str(exact[0])))
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.economy_run_id)
                    if actual != expected:
                        raise EconomyIntegrityError(
                            f"Economy row counts differ: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return EconomySaveResult(
                        economy_run_id=state.economy_run_id,
                        economy_fingerprint=state.economy_fingerprint,
                        status=(
                            EconomyComputeStatus.REPLACED
                            if replacing
                            else EconomyComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except EconomyIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist economy run.") from exc

    def get_summary(self, match_id: UUID) -> EconomyRunSummary | None:
        row = self._latest_run(match_id)
        return _summary(row) if row is not None else None

    def get_summary_for_run(self, match_id: UUID, economy_run_id: UUID) -> EconomyRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "economy") as connection:
            cursor = connection.execute(
                "SELECT * FROM economy_runs WHERE match_id = ? AND economy_run_id = ?",
                [match_id, economy_run_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return _summary(dict(zip(columns, row, strict=True)))

    def list_runs(self, match_id: UUID) -> tuple[EconomyRunRecord, ...]:
        self.initialize()
        selected = self._latest_run(match_id)
        selected_id = selected["economy_run_id"] if selected else None
        with read_connection(self._database_path, "economy") as connection:
            rows = connection.execute(
                """
                SELECT economy_run_id, economy_fingerprint, match_id,
                       economy_schema_version, economy_rule_version,
                       parser_name, parser_version, created_at
                FROM economy_runs WHERE match_id = ?
                ORDER BY created_at DESC, economy_fingerprint DESC
                """,
                [match_id],
            ).fetchall()
        return tuple(
            EconomyRunRecord(
                economy_run_id=row[0],
                economy_fingerprint=str(row[1]),
                match_id=row[2],
                economy_schema_version=str(row[3]),
                economy_rule_version=str(row[4]),
                parser_name=str(row[5]),
                parser_version=str(row[6]),
                created_at=row[7],
                compatible=(str(row[3]), str(row[4]))
                == (ECONOMY_SCHEMA_VERSION, ECONOMY_RULE_VERSION),
                selected_by_default=row[0] == selected_id,
            )
            for row in rows
        )

    def list_team_snapshots(
        self,
        match_id: UUID,
        *,
        economy_run_id: UUID | None = None,
        round_number: int | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[TeamEconomySnapshot, ...]:
        summary = self._resolve_summary(match_id, economy_run_id)
        if summary is None:
            return ()
        where = ["economy_run_id = ?", "match_id = ?"]
        parameters: list[object] = [summary.economy_run_id, match_id]
        if round_number is not None:
            where.append("round_number = ?")
            parameters.append(round_number)
        if side is not None:
            where.append("side = ?")
            parameters.append(side.value)
        if buy_type is not None:
            where.append("buy_type = ?")
            parameters.append(buy_type.value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "economy") as connection:
            rows = connection.execute(
                "SELECT payload FROM team_economy_snapshots WHERE "
                + " AND ".join(where)
                + " ORDER BY round_number, side LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(TeamEconomySnapshot.model_validate(_json(row[0])) for row in rows)

    def list_player_snapshots(
        self,
        match_id: UUID,
        *,
        economy_run_id: UUID | None = None,
        round_number: int | None = None,
        participant_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[PlayerEquipmentSnapshot, ...]:
        summary = self._resolve_summary(match_id, economy_run_id)
        if summary is None:
            return ()
        where = ["economy_run_id = ?", "match_id = ?"]
        parameters: list[object] = [summary.economy_run_id, match_id]
        if round_number is not None:
            where.append("round_number = ?")
            parameters.append(round_number)
        if participant_id is not None:
            where.append("participant_id = ?")
            parameters.append(participant_id)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "economy") as connection:
            rows = connection.execute(
                "SELECT payload FROM player_equipment_snapshots WHERE "
                + " AND ".join(where)
                + " ORDER BY round_number, side, participant_id LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(PlayerEquipmentSnapshot.model_validate(_json(row[0])) for row in rows)

    def delete_economy(self, match_id: UUID) -> int:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    rows = connection.execute(
                        "SELECT economy_run_id FROM economy_runs WHERE match_id = ?",
                        [match_id],
                    ).fetchall()
                    for row in rows:
                        self._delete_run(connection, UUID(str(row[0])))
                    connection.execute("COMMIT")
                    return len(rows)
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not delete economy runs.") from exc

    def _resolve_summary(
        self, match_id: UUID, economy_run_id: UUID | None
    ) -> EconomyRunSummary | None:
        return (
            self.get_summary_for_run(match_id, economy_run_id)
            if economy_run_id is not None
            else self.get_summary(match_id)
        )

    def _latest_run(self, match_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with read_connection(self._database_path, "economy") as connection:
            cursor = connection.execute(
                "SELECT * FROM economy_runs WHERE match_id = ? "
                "ORDER BY CASE WHEN economy_schema_version = ? AND economy_rule_version = ? "
                "THEN 0 ELSE 1 END, created_at DESC, economy_fingerprint DESC LIMIT 1",
                [match_id, ECONOMY_SCHEMA_VERSION, ECONOMY_RULE_VERSION],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: EconomyState) -> None:
        row = connection.execute(
            "SELECT dataset_fingerprint, source_demo_sha256 FROM matches WHERE match_id = ?",
            [state.match_id],
        ).fetchone()
        if row is None:
            raise EconomyIntegrityError("Economy run references an unknown match.")
        actual = tuple(str(value) for value in row)
        expected = (
            state.dataset_fingerprint,
            state.source_demo_sha256,
        )
        if actual != expected:
            raise EconomyIntegrityError(
                "Economy provenance does not match the persisted canonical match."
            )
        player_inconsistent = any(
            item.economy_run_id != state.economy_run_id or item.match_id != state.match_id
            for item in state.player_snapshots
        )
        team_inconsistent = any(
            item.economy_run_id != state.economy_run_id or item.match_id != state.match_id
            for item in state.team_snapshots
        )
        if player_inconsistent or team_inconsistent:
            raise EconomyIntegrityError("Economy child-row provenance is inconsistent.")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: EconomyState,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO economy_runs (
                economy_run_id, economy_fingerprint, economy_schema_version,
                economy_rule_version, item_category_version, value_policy_version,
                economy_config_hash, match_id, dataset_fingerprint, source_demo_sha256,
                parser_name, parser_version, config, capability, summary, source_columns,
                row_counts, warnings, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            """,
            [
                state.economy_run_id,
                state.economy_fingerprint,
                state.economy_schema_version,
                state.economy_rule_version,
                state.item_category_version,
                state.value_policy_version,
                state.economy_config_hash,
                state.match_id,
                state.dataset_fingerprint,
                state.source_demo_sha256,
                state.parser_name,
                state.parser_version,
                _payload(state.config),
                _payload(state.capability),
                _payload(state.summary),
                canonical_json(list(state.source_columns)),
                canonical_json(row_counts),
                canonical_json(list(state.warnings)),
            ],
        )
        if state.player_snapshots:
            frame = pl.DataFrame(
                [
                    {
                        "economy_run_id": str(item.economy_run_id),
                        "player_snapshot_id": str(item.player_snapshot_id),
                        "match_id": str(item.match_id),
                        "round_id": str(item.round_id),
                        "round_number": item.round_number,
                        "freeze_end_tick": item.freeze_end_tick,
                        "participant_id": str(item.participant_id),
                        "steam_id": item.steam_id,
                        "team_id": str(item.team_id) if item.team_id else None,
                        "side": item.side.value,
                        "eligible": item.eligible,
                        "payload": _payload(item),
                    }
                    for item in state.player_snapshots
                ],
                strict=False,
            )
            connection.register("economy_player_batch", frame)
            try:
                connection.execute(
                    "INSERT INTO player_equipment_snapshots BY NAME "
                    "SELECT * FROM economy_player_batch"
                )
            finally:
                connection.unregister("economy_player_batch")
        if state.team_snapshots:
            frame = pl.DataFrame(
                [
                    {
                        "economy_run_id": str(item.economy_run_id),
                        "team_snapshot_id": str(item.team_snapshot_id),
                        "match_id": str(item.match_id),
                        "round_id": str(item.round_id),
                        "round_number": item.round_number,
                        "freeze_end_tick": item.freeze_end_tick,
                        "team_id": str(item.team_id) if item.team_id else None,
                        "side": item.side.value,
                        "buy_type": item.buy_type.value,
                        "classification_availability": item.classification_availability.value,
                        "eligible": item.eligible,
                        "payload": _payload(item),
                    }
                    for item in state.team_snapshots
                ],
                strict=False,
            )
            connection.register("economy_team_batch", frame)
            try:
                connection.execute(
                    "INSERT INTO team_economy_snapshots BY NAME SELECT * FROM economy_team_batch"
                )
            finally:
                connection.unregister("economy_team_batch")

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "economy_runs",
            "player_equipment_snapshots",
            "team_economy_snapshots",
        ):
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE economy_run_id = ?', [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result

    @staticmethod
    def _delete_run(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> None:
        delete_dependent_feature_runs(connection, "economy_run_id", [run_id])
        connection.execute(
            "DELETE FROM player_equipment_snapshots WHERE economy_run_id = ?", [run_id]
        )
        connection.execute("DELETE FROM team_economy_snapshots WHERE economy_run_id = ?", [run_id])
        connection.execute("DELETE FROM economy_runs WHERE economy_run_id = ?", [run_id])


def _summary(row: dict[str, Any]) -> EconomyRunSummary:
    return EconomyRunSummary(
        economy_run_id=row["economy_run_id"],
        economy_fingerprint=str(row["economy_fingerprint"]),
        economy_schema_version=str(row["economy_schema_version"]),
        economy_rule_version=str(row["economy_rule_version"]),
        item_category_version=str(row["item_category_version"]),
        value_policy_version=str(row["value_policy_version"]),
        economy_config_hash=str(row["economy_config_hash"]),
        match_id=row["match_id"],
        dataset_fingerprint=str(row["dataset_fingerprint"]),
        source_demo_sha256=str(row["source_demo_sha256"]),
        parser_name=str(row["parser_name"]),
        parser_version=str(row["parser_version"]),
        config=_json(row["config"]),
        capability=_json(row["capability"]),
        summary=_json(row["summary"]),
        source_columns=tuple(_json(row["source_columns"])),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _payload(value: Any) -> str:
    return canonical_json(value.model_dump(mode="json"))


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBEconomyRepository"]
