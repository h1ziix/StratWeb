"""DuckDB adapter for immutable, versioned zone-assignment runs."""

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
from stratweb.exceptions import PersistenceError, ZoneAssignmentIntegrityError
from stratweb.spatial.models import SPATIAL_RULE_VERSION, SPATIAL_SCHEMA_VERSION
from stratweb.zones.assignment_models import (
    ZONE_ASSIGNMENT_RULE_VERSION,
    ZONE_ASSIGNMENT_SCHEMA_VERSION,
    ZoneAssignment,
    ZoneAssignmentComputeStatus,
    ZoneAssignmentRunRecord,
    ZoneAssignmentRunSummary,
    ZoneAssignmentSaveResult,
    ZoneAssignmentState,
    ZoneAssignmentStatus,
)


class DuckDBZoneAssignmentRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_zone_assignments(
        self, state: ZoneAssignmentState, *, replace: bool = False
    ) -> ZoneAssignmentSaveResult:
        self.initialize()
        expected = {
            "zone_assignment_runs": 1,
            "zone_assignments": len(state.assignments),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT zone_assignment_run_id FROM zone_assignment_runs "
                        "WHERE zone_assignment_fingerprint = ?",
                        [state.zone_assignment_fingerprint],
                    ).fetchone()
                    collisions = connection.execute(
                        """
                        SELECT zone_assignment_run_id, zone_assignment_fingerprint
                        FROM zone_assignment_runs
                        WHERE spatial_fingerprint = ?
                          AND zone_assignment_rule_version = ?
                          AND zone_set_key = ?
                          AND zone_assignment_config_hash = ?
                        """,
                        [
                            state.spatial_fingerprint,
                            state.zone_assignment_rule_version,
                            state.zone_set_key,
                            state.zone_assignment_config_hash,
                        ],
                    ).fetchall()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return ZoneAssignmentSaveResult(
                            zone_assignment_run_id=run_id,
                            zone_assignment_fingerprint=state.zone_assignment_fingerprint,
                            status=ZoneAssignmentComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if (
                        collisions
                        and not replace
                        and all(
                            str(row[1]) != state.zone_assignment_fingerprint for row in collisions
                        )
                    ):
                        raise ZoneAssignmentIntegrityError(
                            "Same Spatial/zone/config input produced another fingerprint."
                        )
                    replacing = exact is not None or bool(collisions)
                    deleted: set[UUID] = set()
                    for run_id, _fingerprint in collisions:
                        parsed = UUID(str(run_id))
                        self._delete_run(connection, parsed)
                        deleted.add(parsed)
                    if exact is not None and UUID(str(exact[0])) not in deleted:
                        self._delete_run(connection, UUID(str(exact[0])))
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.zone_assignment_run_id)
                    if actual != expected:
                        raise ZoneAssignmentIntegrityError(
                            f"Zone assignment row counts differ: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return ZoneAssignmentSaveResult(
                        zone_assignment_run_id=state.zone_assignment_run_id,
                        zone_assignment_fingerprint=state.zone_assignment_fingerprint,
                        status=(
                            ZoneAssignmentComputeStatus.REPLACED
                            if replacing
                            else ZoneAssignmentComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except ZoneAssignmentIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist zone assignment run.") from exc

    def get_summary(self, match_id: UUID) -> ZoneAssignmentRunSummary | None:
        spatial_run_id = self._selected_spatial_run_id(match_id)
        if spatial_run_id is None:
            return None
        row = self._latest_run(match_id=match_id, spatial_run_id=spatial_run_id)
        return _summary(row) if row is not None else None

    def get_summary_for_spatial_run(
        self, match_id: UUID, spatial_run_id: UUID
    ) -> ZoneAssignmentRunSummary | None:
        row = self._latest_run(match_id=match_id, spatial_run_id=spatial_run_id)
        return _summary(row) if row is not None else None

    def get_summary_for_run(
        self, match_id: UUID, zone_assignment_run_id: UUID
    ) -> ZoneAssignmentRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "zone assignment") as connection:
            cursor = connection.execute(
                "SELECT * FROM zone_assignment_runs "
                "WHERE match_id = ? AND zone_assignment_run_id = ?",
                [match_id, zone_assignment_run_id],
            )
            value = cursor.fetchone()
            if value is None:
                return None
            columns = [item[0] for item in cursor.description]
        return _summary(dict(zip(columns, value, strict=True)))

    def list_runs(self, match_id: UUID) -> tuple[ZoneAssignmentRunRecord, ...]:
        self.initialize()
        spatial_run_id = self._selected_spatial_run_id(match_id)
        selected = (
            self._latest_run(match_id=match_id, spatial_run_id=spatial_run_id)
            if spatial_run_id is not None
            else None
        )
        selected_id = selected["zone_assignment_run_id"] if selected is not None else None
        with read_connection(self._database_path, "zone assignment") as connection:
            rows = connection.execute(
                """
                SELECT zone_assignment_run_id, zone_assignment_fingerprint, match_id,
                       spatial_run_id, zone_assignment_schema_version,
                       zone_assignment_rule_version, zone_set_fingerprint,
                       canonical_map_name, selected_map_revision, created_at
                FROM zone_assignment_runs
                WHERE match_id = ?
                ORDER BY created_at DESC, zone_assignment_fingerprint DESC
                """,
                [match_id],
            ).fetchall()
        return tuple(
            ZoneAssignmentRunRecord(
                zone_assignment_run_id=row[0],
                zone_assignment_fingerprint=str(row[1]),
                match_id=row[2],
                spatial_run_id=row[3],
                zone_assignment_schema_version=str(row[4]),
                zone_assignment_rule_version=str(row[5]),
                zone_set_fingerprint=str(row[6]) if row[6] is not None else None,
                canonical_map_name=str(row[7]) if row[7] is not None else None,
                selected_map_revision=str(row[8]) if row[8] is not None else None,
                created_at=row[9],
                compatible=(str(row[4]), str(row[5]))
                == (ZONE_ASSIGNMENT_SCHEMA_VERSION, ZONE_ASSIGNMENT_RULE_VERSION),
                selected_by_default=row[0] == selected_id,
            )
            for row in rows
        )

    def list_assignments(
        self,
        match_id: UUID,
        *,
        zone_assignment_run_id: UUID | None = None,
        round_number: int | None = None,
        status: ZoneAssignmentStatus | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[ZoneAssignment, ...]:
        summary = (
            self.get_summary_for_run(match_id, zone_assignment_run_id)
            if zone_assignment_run_id is not None
            else self.get_summary(match_id)
        )
        if summary is None:
            return ()
        where = ["zone_assignment_run_id = ?", "match_id = ?"]
        parameters: list[object] = [summary.zone_assignment_run_id, match_id]
        if round_number is not None:
            where.append("round_number = ?")
            parameters.append(round_number)
        if status is not None:
            where.append("status = ?")
            parameters.append(status.value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "zone assignment") as connection:
            rows = connection.execute(
                "SELECT * FROM zone_assignments WHERE "
                + " AND ".join(where)
                + " ORDER BY round_number, tick, participant_id LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
            columns = [item[0] for item in connection.description]
        return tuple(_assignment(dict(zip(columns, row, strict=True))) for row in rows)

    def get_assignments(
        self,
        zone_assignment_run_id: UUID,
        spatial_snapshot_ids: tuple[UUID, ...],
    ) -> tuple[ZoneAssignment, ...]:
        if not spatial_snapshot_ids:
            return ()
        self.initialize()
        placeholders = ", ".join("?" for _ in spatial_snapshot_ids)
        with read_connection(self._database_path, "zone assignment") as connection:
            cursor = connection.execute(
                "SELECT * FROM zone_assignments WHERE zone_assignment_run_id = ? "
                f"AND spatial_snapshot_id IN ({placeholders})",
                [zone_assignment_run_id, *spatial_snapshot_ids],
            )
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description]
        return tuple(_assignment(dict(zip(columns, row, strict=True))) for row in rows)

    def delete_zone_assignments(self, match_id: UUID) -> int:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    rows = connection.execute(
                        "SELECT zone_assignment_run_id FROM zone_assignment_runs "
                        "WHERE match_id = ?",
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
            raise PersistenceError("Could not delete zone assignment runs.") from exc

    def _latest_run(
        self, *, match_id: UUID, spatial_run_id: UUID | None = None
    ) -> dict[str, Any] | None:
        self.initialize()
        where = ["match_id = ?"]
        parameters: list[object] = [match_id]
        if spatial_run_id is not None:
            where.append("spatial_run_id = ?")
            parameters.append(spatial_run_id)
        parameters.extend([ZONE_ASSIGNMENT_SCHEMA_VERSION, ZONE_ASSIGNMENT_RULE_VERSION])
        with read_connection(self._database_path, "zone assignment") as connection:
            cursor = connection.execute(
                "SELECT * FROM zone_assignment_runs WHERE "
                + " AND ".join(where)
                + " ORDER BY CASE WHEN zone_assignment_schema_version = ? "
                "AND zone_assignment_rule_version = ? THEN 0 ELSE 1 END, "
                "created_at DESC, zone_assignment_fingerprint DESC LIMIT 1",
                parameters,
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    def _selected_spatial_run_id(self, match_id: UUID) -> UUID | None:
        self.initialize()
        with read_connection(self._database_path, "zone assignment") as connection:
            row = connection.execute(
                """
                SELECT spatial_run_id FROM spatial_runs
                WHERE match_id = ?
                ORDER BY CASE WHEN spatial_schema_version = ?
                                   AND spatial_rule_version = ?
                              THEN 0 ELSE 1 END,
                         created_at DESC, spatial_fingerprint DESC
                LIMIT 1
                """,
                [match_id, SPATIAL_SCHEMA_VERSION, SPATIAL_RULE_VERSION],
            ).fetchone()
        return UUID(str(row[0])) if row is not None else None

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: ZoneAssignmentState) -> None:
        spatial = connection.execute(
            "SELECT dataset_fingerprint, spatial_fingerprint, spatial_schema_version, "
            "spatial_rule_version, canonical_map_name, selected_map_revision, "
            "map_definition_fingerprint FROM spatial_runs "
            "WHERE spatial_run_id = ? AND match_id = ?",
            [state.spatial_run_id, state.match_id],
        ).fetchone()
        if spatial is None:
            raise ZoneAssignmentIntegrityError("Zone run references an unknown Spatial run.")
        expected = (
            state.dataset_fingerprint,
            state.spatial_fingerprint,
            state.spatial_schema_version,
            state.spatial_rule_version,
            state.canonical_map_name,
            state.selected_map_revision,
            state.map_definition_fingerprint,
        )
        actual = tuple(str(value) if value is not None else None for value in spatial)
        if actual != expected:
            raise ZoneAssignmentIntegrityError(
                "Zone run pins do not match the persisted Spatial run."
            )
        if any(
            item.zone_assignment_run_id != state.zone_assignment_run_id
            or item.spatial_run_id != state.spatial_run_id
            or item.match_id != state.match_id
            for item in state.assignments
        ):
            raise ZoneAssignmentIntegrityError("Zone assignment child pins are inconsistent.")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: ZoneAssignmentState,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO zone_assignment_runs (
                zone_assignment_run_id, zone_assignment_fingerprint,
                zone_assignment_schema_version, zone_assignment_rule_version,
                zone_assignment_config_hash, match_id, dataset_fingerprint,
                spatial_run_id, spatial_fingerprint, spatial_schema_version,
                spatial_rule_version, canonical_map_name, selected_map_revision,
                map_definition_fingerprint, map_revision_selection_status,
                zone_set_fingerprint, zone_set_key, zone_schema_version,
                zone_resolution_rule_version, zone_validation_rule_version,
                config, capability, summary, row_counts, warnings, created_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, current_timestamp
            )
            """,
            [
                state.zone_assignment_run_id,
                state.zone_assignment_fingerprint,
                state.zone_assignment_schema_version,
                state.zone_assignment_rule_version,
                state.zone_assignment_config_hash,
                state.match_id,
                state.dataset_fingerprint,
                state.spatial_run_id,
                state.spatial_fingerprint,
                state.spatial_schema_version,
                state.spatial_rule_version,
                state.canonical_map_name,
                state.selected_map_revision,
                state.map_definition_fingerprint,
                (
                    state.map_revision_selection_status.value
                    if state.map_revision_selection_status is not None
                    else None
                ),
                state.zone_set_fingerprint,
                state.zone_set_key,
                state.zone_schema_version,
                state.zone_resolution_rule_version,
                state.zone_validation_rule_version,
                _payload(state.config),
                _payload(state.capability),
                _payload(state.summary),
                canonical_json(row_counts),
                canonical_json(list(state.warnings)),
            ],
        )
        if state.assignments:
            rows = [
                {
                    "zone_assignment_run_id": str(item.zone_assignment_run_id),
                    "assignment_id": str(item.assignment_id),
                    "spatial_run_id": str(item.spatial_run_id),
                    "spatial_snapshot_id": str(item.spatial_snapshot_id),
                    "match_id": str(item.match_id),
                    "round_id": str(item.round_id),
                    "round_number": item.round_number,
                    "tick": item.tick,
                    "participant_id": str(item.participant_id),
                    "status": item.status.value,
                    "zone_id": item.zone_id,
                    "zone_name": item.zone_name,
                    "zone_kind": item.kind.value if item.kind is not None else None,
                    "map_level": item.level.value if item.level is not None else None,
                    "warnings": canonical_json(list(item.warnings)),
                }
                for item in state.assignments
            ]
            relation = "zone_assignment_batch"
            frame = pl.DataFrame(rows, strict=False)
            connection.register(relation, frame)
            try:
                connection.execute(
                    f'INSERT INTO zone_assignments BY NAME SELECT * FROM "{relation}"'
                )
            finally:
                connection.unregister(relation)

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        run = connection.execute(
            "SELECT count(*) FROM zone_assignment_runs WHERE zone_assignment_run_id = ?",
            [run_id],
        ).fetchone()
        assignments = connection.execute(
            "SELECT count(*) FROM zone_assignments WHERE zone_assignment_run_id = ?",
            [run_id],
        ).fetchone()
        return {
            "zone_assignment_runs": int(run[0]) if run else 0,
            "zone_assignments": int(assignments[0]) if assignments else 0,
        }

    @staticmethod
    def _delete_run(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> None:
        delete_dependent_feature_runs(connection, "zone_assignment_run_id", [run_id])
        connection.execute(
            "DELETE FROM zone_assignments WHERE zone_assignment_run_id = ?", [run_id]
        )
        connection.execute(
            "DELETE FROM zone_assignment_runs WHERE zone_assignment_run_id = ?", [run_id]
        )


def _summary(row: dict[str, Any]) -> ZoneAssignmentRunSummary:
    return ZoneAssignmentRunSummary(
        zone_assignment_run_id=row["zone_assignment_run_id"],
        zone_assignment_fingerprint=str(row["zone_assignment_fingerprint"]),
        zone_assignment_schema_version=str(row["zone_assignment_schema_version"]),
        zone_assignment_rule_version=str(row["zone_assignment_rule_version"]),
        zone_assignment_config_hash=str(row["zone_assignment_config_hash"]),
        match_id=row["match_id"],
        dataset_fingerprint=str(row["dataset_fingerprint"]),
        spatial_run_id=row["spatial_run_id"],
        spatial_fingerprint=str(row["spatial_fingerprint"]),
        spatial_schema_version=str(row["spatial_schema_version"]),
        spatial_rule_version=str(row["spatial_rule_version"]),
        canonical_map_name=(
            str(row["canonical_map_name"]) if row["canonical_map_name"] is not None else None
        ),
        selected_map_revision=(
            str(row["selected_map_revision"]) if row["selected_map_revision"] is not None else None
        ),
        map_definition_fingerprint=(
            str(row["map_definition_fingerprint"])
            if row["map_definition_fingerprint"] is not None
            else None
        ),
        map_revision_selection_status=row["map_revision_selection_status"],
        zone_set_fingerprint=(
            str(row["zone_set_fingerprint"]) if row["zone_set_fingerprint"] is not None else None
        ),
        zone_set_key=str(row["zone_set_key"]),
        zone_schema_version=(
            str(row["zone_schema_version"]) if row["zone_schema_version"] else None
        ),
        zone_resolution_rule_version=(
            str(row["zone_resolution_rule_version"])
            if row["zone_resolution_rule_version"]
            else None
        ),
        zone_validation_rule_version=(
            str(row["zone_validation_rule_version"])
            if row["zone_validation_rule_version"]
            else None
        ),
        config=_json(row["config"]),
        capability=_json(row["capability"]),
        summary=_json(row["summary"]),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _assignment(row: dict[str, Any]) -> ZoneAssignment:
    return ZoneAssignment(
        assignment_id=row["assignment_id"],
        zone_assignment_run_id=row["zone_assignment_run_id"],
        spatial_run_id=row["spatial_run_id"],
        spatial_snapshot_id=row["spatial_snapshot_id"],
        match_id=row["match_id"],
        round_id=row["round_id"],
        round_number=int(row["round_number"]),
        tick=int(row["tick"]),
        participant_id=row["participant_id"],
        status=row["status"],
        zone_id=str(row["zone_id"]) if row["zone_id"] is not None else None,
        zone_name=str(row["zone_name"]) if row["zone_name"] is not None else None,
        kind=row["zone_kind"],
        level=row["map_level"],
        warnings=tuple(_json(row["warnings"])),
    )


def _payload(value: Any) -> str:
    if isinstance(value, BaseException):  # pragma: no cover - defensive type guard
        raise TypeError("exceptions are not serializable")
    return canonical_json(value.model_dump(mode="json"))


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBZoneAssignmentRepository"]
