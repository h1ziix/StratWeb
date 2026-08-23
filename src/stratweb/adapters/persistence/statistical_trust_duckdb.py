"""DuckDB persistence for immutable Stage 9.4 statistical-trust runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
from pydantic import BaseModel

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import PersistenceError, StatisticalTrustIntegrityError
from stratweb.statistical_trust.models import (
    STATISTICAL_TRUST_RULE_VERSION,
    STATISTICAL_TRUST_SCHEMA_VERSION,
    StatisticalTrustAssessment,
    StatisticalTrustComputeStatus,
    StatisticalTrustRun,
    StatisticalTrustRunRecord,
    StatisticalTrustRunSummary,
    StatisticalTrustSaveResult,
    TrustDecision,
)


class DuckDBStatisticalTrustRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_trust(
        self, state: StatisticalTrustRun, *, replace: bool = False
    ) -> StatisticalTrustSaveResult:
        self.initialize()
        expected = {
            "statistical_trust_runs": 1,
            "statistical_trust_assessments": len(state.assessments),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT trust_run_id FROM statistical_trust_runs "
                        "WHERE trust_fingerprint = ?",
                        [state.trust_fingerprint],
                    ).fetchone()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return StatisticalTrustSaveResult(
                            trust_run_id=run_id,
                            trust_fingerprint=state.trust_fingerprint,
                            status=StatisticalTrustComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if exact is not None:
                        self._delete_runs(connection, [exact[0]])
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.trust_run_id)
                    if actual != expected:
                        raise StatisticalTrustIntegrityError(
                            f"Statistical trust row counts differ: {actual} != {expected}."
                        )
                    connection.execute("COMMIT")
                    return StatisticalTrustSaveResult(
                        trust_run_id=state.trust_run_id,
                        trust_fingerprint=state.trust_fingerprint,
                        status=(
                            StatisticalTrustComputeStatus.REPLACED
                            if exact is not None
                            else StatisticalTrustComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except StatisticalTrustIntegrityError:
            raise
        except (duckdb.Error, ValueError) as exc:
            raise PersistenceError("Could not persist statistical-trust run.") from exc

    def get_summary(
        self, profile_id: UUID, *, source_pattern_run_id: UUID
    ) -> StatisticalTrustRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "statistical trust") as connection:
            cursor = connection.execute(
                """
                SELECT * FROM statistical_trust_runs
                WHERE profile_id = ? AND source_pattern_run_id = ?
                  AND trust_schema_version = ? AND trust_rule_version = ?
                ORDER BY created_at DESC, trust_fingerprint DESC LIMIT 1
                """,
                [
                    profile_id,
                    source_pattern_run_id,
                    STATISTICAL_TRUST_SCHEMA_VERSION,
                    STATISTICAL_TRUST_RULE_VERSION,
                ],
            )
            return _fetch_summary(cursor)

    def get_summary_for_run(
        self, profile_id: UUID, trust_run_id: UUID
    ) -> StatisticalTrustRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "statistical trust") as connection:
            cursor = connection.execute(
                "SELECT * FROM statistical_trust_runs WHERE profile_id = ? AND trust_run_id = ?",
                [profile_id, trust_run_id],
            )
            return _fetch_summary(cursor)

    def list_runs(
        self, profile_id: UUID, *, current_pattern_run_id: UUID | None
    ) -> tuple[StatisticalTrustRunRecord, ...]:
        self.initialize()
        with read_connection(self._database_path, "statistical trust") as connection:
            rows = connection.execute(
                """
                SELECT trust_run_id, trust_fingerprint, profile_id,
                       source_pattern_run_id, trust_schema_version,
                       trust_rule_version, created_at
                FROM statistical_trust_runs WHERE profile_id = ?
                ORDER BY created_at DESC, trust_fingerprint DESC
                """,
                [profile_id],
            ).fetchall()
        selected = next(
            (
                row[0]
                for row in rows
                if row[3] == current_pattern_run_id
                and (str(row[4]), str(row[5]))
                == (STATISTICAL_TRUST_SCHEMA_VERSION, STATISTICAL_TRUST_RULE_VERSION)
            ),
            None,
        )
        return tuple(
            StatisticalTrustRunRecord(
                trust_run_id=row[0],
                trust_fingerprint=str(row[1]),
                profile_id=row[2],
                source_pattern_run_id=row[3],
                trust_schema_version=str(row[4]),
                trust_rule_version=str(row[5]),
                created_at=row[6],
                compatible=(
                    row[3] == current_pattern_run_id
                    and (str(row[4]), str(row[5]))
                    == (STATISTICAL_TRUST_SCHEMA_VERSION, STATISTICAL_TRUST_RULE_VERSION)
                ),
                selected_by_default=row[0] == selected,
            )
            for row in rows
        )

    def list_assessments(
        self,
        profile_id: UUID,
        *,
        trust_run_id: UUID,
        decision: TrustDecision | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[StatisticalTrustAssessment, ...]:
        where = ["trust_run_id = ?", "profile_id = ?"]
        parameters: list[object] = [trust_run_id, profile_id]
        if decision is not None:
            where.append("decision = ?")
            parameters.append(decision.value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "statistical trust") as connection:
            rows = connection.execute(
                "SELECT payload FROM statistical_trust_assessments WHERE "
                + " AND ".join(where)
                + " ORDER BY reliability_rank NULLS LAST, source_pattern_id LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(StatisticalTrustAssessment.model_validate(_json(row[0])) for row in rows)

    def delete_trust(self, profile_id: UUID) -> int:
        self.initialize()
        with duckdb.connect(str(self._database_path)) as connection:
            rows = connection.execute(
                "SELECT trust_run_id FROM statistical_trust_runs WHERE profile_id = ?",
                [profile_id],
            ).fetchall()
            connection.execute("BEGIN TRANSACTION")
            try:
                self._delete_runs(connection, [row[0] for row in rows])
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return len(rows)

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: StatisticalTrustRun) -> None:
        source = connection.execute(
            "SELECT 1 FROM cross_match_pattern_runs WHERE pattern_run_id = ? "
            "AND pattern_fingerprint = ? AND profile_id = ?",
            [state.source_pattern_run_id, state.source_pattern_fingerprint, state.profile_id],
        ).fetchone()
        if source is None:
            raise ValueError("statistical trust references a missing pattern run")
        if any(
            item.trust_run_id != state.trust_run_id
            or item.profile_id != state.profile_id
            or item.source_pattern_run_id != state.source_pattern_run_id
            for item in state.assessments
        ):
            raise StatisticalTrustIntegrityError(
                "statistical trust child provenance is inconsistent"
            )

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: StatisticalTrustRun,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO statistical_trust_runs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp
            )
            """,
            [
                state.trust_run_id,
                state.trust_fingerprint,
                state.trust_schema_version,
                state.trust_rule_version,
                state.configuration_hash,
                state.profile_id,
                state.source_pattern_run_id,
                state.source_pattern_fingerprint,
                state.source_pattern_schema_version,
                state.source_pattern_rule_version,
                _payload(state.config),
                _payload(state.summary),
                canonical_json(row_counts),
                canonical_json(list(state.warnings)),
            ],
        )
        if state.assessments:
            connection.executemany(
                "INSERT INTO statistical_trust_assessments VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        state.trust_run_id,
                        item.assessment_id,
                        item.profile_id,
                        item.source_pattern_id,
                        item.scope.map_name,
                        item.scope.side.value,
                        item.scope.buy_type.value if item.scope.buy_type else None,
                        item.source_pattern_type.value,
                        item.decision.value,
                        item.reliability_rank,
                        item.reliability_score,
                        item.denominator_match_count,
                        _payload(item),
                    ]
                    for item in state.assessments
                ],
            )

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result = {}
        for table in ("statistical_trust_runs", "statistical_trust_assessments"):
            row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE trust_run_id = ?", [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row is not None else 0
        return result

    @staticmethod
    def _delete_runs(connection: duckdb.DuckDBPyConnection, run_ids: list[Any]) -> None:
        if not run_ids:
            return
        placeholders = ", ".join("?" for _ in run_ids)
        connection.execute(
            f"DELETE FROM statistical_trust_assessments WHERE trust_run_id IN ({placeholders})",
            run_ids,
        )
        connection.execute(
            f"DELETE FROM statistical_trust_runs WHERE trust_run_id IN ({placeholders})",
            run_ids,
        )


def _fetch_summary(cursor: duckdb.DuckDBPyConnection) -> StatisticalTrustRunSummary | None:
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [item[0] for item in cursor.description]
    value = dict(zip(columns, row, strict=True))
    return StatisticalTrustRunSummary(
        trust_schema_version=str(value["trust_schema_version"]),
        trust_rule_version=str(value["trust_rule_version"]),
        trust_run_id=value["trust_run_id"],
        trust_fingerprint=str(value["trust_fingerprint"]),
        configuration_hash=str(value["configuration_hash"]),
        profile_id=value["profile_id"],
        source_pattern_run_id=value["source_pattern_run_id"],
        source_pattern_fingerprint=str(value["source_pattern_fingerprint"]),
        source_pattern_schema_version=str(value["source_pattern_schema_version"]),
        source_pattern_rule_version=str(value["source_pattern_rule_version"]),
        config=_json(value["config"]),
        summary=_json(value["summary"]),
        row_counts=_json(value["row_counts"]),
        warnings=tuple(_json(value["warnings"])),
    )


def _payload(model: BaseModel) -> str:
    return canonical_json(model.model_dump(mode="json"))


def _json(value: object) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


__all__ = ["DuckDBStatisticalTrustRepository"]
