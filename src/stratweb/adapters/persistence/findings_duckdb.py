"""DuckDB persistence for immutable Stage 8.6 analysis runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._analysis_cascade import delete_analysis_runs
from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.exceptions import PersistenceError
from stratweb.findings.models import (
    FINDING_RULE_VERSION,
    FINDING_SCHEMA_VERSION,
    AnalysisComputeStatus,
    AnalysisFinding,
    AnalysisRun,
    AnalysisRunRecord,
    AnalysisRunSummary,
    AnalysisSaveResult,
    EvidenceReference,
    FindingCategory,
)
from stratweb.patterns.models import PatternType


class DuckDBAnalysisRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_analysis(self, state: AnalysisRun, *, replace: bool = False) -> AnalysisSaveResult:
        self.initialize()
        expected = {
            "analysis_runs": 1,
            "analysis_run_inputs": len(state.matches),
            "analysis_findings": len(state.findings),
            "finding_evidence_references": sum(
                len(item.evidence_references) for item in state.findings
            ),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT analysis_run_id FROM analysis_runs WHERE analysis_fingerprint = ?",
                        [state.analysis_fingerprint],
                    ).fetchone()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return AnalysisSaveResult(
                            analysis_run_id=run_id,
                            analysis_fingerprint=state.analysis_fingerprint,
                            status=AnalysisComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if exact is not None:
                        delete_analysis_runs(connection, analysis_run_ids=[exact[0]])
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.analysis_run_id)
                    if actual != expected:
                        raise ValueError(f"analysis row counts differ: {actual} != {expected}")
                    connection.execute("COMMIT")
                    return AnalysisSaveResult(
                        analysis_run_id=state.analysis_run_id,
                        analysis_fingerprint=state.analysis_fingerprint,
                        status=(
                            AnalysisComputeStatus.REPLACED
                            if exact is not None
                            else AnalysisComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except (duckdb.Error, ValueError) as exc:
            raise PersistenceError("Could not persist Stage 8.6 analysis run.") from exc

    def get_summary(
        self, profile_id: UUID, *, source_pattern_run_id: UUID
    ) -> AnalysisRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "analysis findings") as connection:
            cursor = connection.execute(
                """
                SELECT * FROM analysis_runs
                WHERE profile_id = ? AND source_pattern_run_id = ?
                  AND analysis_schema_version = ? AND analysis_rule_version = ?
                ORDER BY created_at DESC, analysis_fingerprint DESC LIMIT 1
                """,
                [
                    profile_id,
                    source_pattern_run_id,
                    FINDING_SCHEMA_VERSION,
                    FINDING_RULE_VERSION,
                ],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
            inputs = _inputs(connection, row[0])
        return _summary(dict(zip(columns, row, strict=True)), inputs)

    def get_summary_for_run(
        self, profile_id: UUID, analysis_run_id: UUID
    ) -> AnalysisRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "analysis findings") as connection:
            cursor = connection.execute(
                "SELECT * FROM analysis_runs WHERE profile_id = ? AND analysis_run_id = ?",
                [profile_id, analysis_run_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
            inputs = _inputs(connection, row[0])
        return _summary(dict(zip(columns, row, strict=True)), inputs)

    def list_runs(
        self, profile_id: UUID, *, current_pattern_run_id: UUID | None
    ) -> tuple[AnalysisRunRecord, ...]:
        self.initialize()
        with read_connection(self._database_path, "analysis findings") as connection:
            rows = connection.execute(
                """
                SELECT analysis_run_id, analysis_fingerprint, profile_id,
                       source_pattern_run_id, analysis_schema_version,
                       analysis_rule_version, created_at
                FROM analysis_runs WHERE profile_id = ?
                ORDER BY created_at DESC, analysis_fingerprint DESC
                """,
                [profile_id],
            ).fetchall()
        selected = next(
            (
                row[0]
                for row in rows
                if row[3] == current_pattern_run_id
                and (str(row[4]), str(row[5])) == (FINDING_SCHEMA_VERSION, FINDING_RULE_VERSION)
            ),
            None,
        )
        return tuple(
            AnalysisRunRecord(
                analysis_run_id=row[0],
                analysis_fingerprint=str(row[1]),
                profile_id=row[2],
                source_pattern_run_id=row[3],
                analysis_schema_version=str(row[4]),
                analysis_rule_version=str(row[5]),
                created_at=row[6],
                compatible=(
                    row[3] == current_pattern_run_id
                    and (str(row[4]), str(row[5])) == (FINDING_SCHEMA_VERSION, FINDING_RULE_VERSION)
                ),
                selected_by_default=row[0] == selected,
            )
            for row in rows
        )

    def list_findings(
        self,
        profile_id: UUID,
        *,
        analysis_run_id: UUID,
        map_name: str | None = None,
        side: Side | None = None,
        category: FindingCategory | None = None,
        pattern_type: PatternType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[AnalysisFinding, ...]:
        where = ["analysis_run_id = ?", "profile_id = ?"]
        parameters: list[object] = [analysis_run_id, profile_id]
        for column, value in (
            ("map_name", map_name),
            ("side", side.value if side else None),
            ("category", category.value if category else None),
            ("pattern_type", pattern_type.value if pattern_type else None),
        ):
            if value is not None:
                where.append(f"{column} = ?")
                parameters.append(value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "analysis findings") as connection:
            rows = connection.execute(
                "SELECT payload FROM analysis_findings WHERE "
                + " AND ".join(where)
                + " ORDER BY map_name, side, category, pattern_type, frequency DESC, "
                + "finding_id LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(AnalysisFinding.model_validate(_json(row[0])) for row in rows)

    def get_finding(
        self, profile_id: UUID, analysis_run_id: UUID, finding_id: UUID
    ) -> AnalysisFinding | None:
        rows = self.list_findings(profile_id, analysis_run_id=analysis_run_id, limit=5000)
        return next((item for item in rows if item.finding_id == finding_id), None)

    def list_evidence(
        self, analysis_run_id: UUID, finding_id: UUID
    ) -> tuple[EvidenceReference, ...]:
        with read_connection(self._database_path, "analysis findings") as connection:
            rows = connection.execute(
                "SELECT payload FROM finding_evidence_references "
                "WHERE analysis_run_id = ? AND finding_id = ? ORDER BY evidence_index",
                [analysis_run_id, finding_id],
            ).fetchall()
        return tuple(EvidenceReference.model_validate(_json(row[0])) for row in rows)

    def delete_analysis(self, profile_id: UUID) -> int:
        self.initialize()
        with duckdb.connect(str(self._database_path)) as connection:
            rows = connection.execute(
                "SELECT analysis_run_id FROM analysis_runs WHERE profile_id = ?", [profile_id]
            ).fetchall()
            connection.execute("BEGIN TRANSACTION")
            try:
                delete_analysis_runs(connection, analysis_run_ids=[row[0] for row in rows])
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return len(rows)

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: AnalysisRun) -> None:
        row = connection.execute(
            "SELECT 1 FROM cross_match_pattern_runs WHERE pattern_run_id = ? "
            "AND pattern_fingerprint = ? AND profile_id = ?",
            [state.source_pattern_run_id, state.source_pattern_fingerprint, state.profile_id],
        ).fetchone()
        if row is None:
            raise ValueError("analysis references a missing pattern run")
        if any(
            item.analysis_run_id != state.analysis_run_id
            or item.profile_id != state.profile_id
            or item.source_pattern_run_id != state.source_pattern_run_id
            for item in state.findings
        ):
            raise ValueError("analysis child provenance is inconsistent")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: AnalysisRun,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO analysis_runs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp
            )
            """,
            [
                state.analysis_run_id,
                state.analysis_fingerprint,
                state.analysis_schema_version,
                state.analysis_rule_version,
                state.configuration_hash,
                state.profile_id,
                state.workspace_fingerprint,
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
        if state.matches:
            connection.executemany(
                "INSERT INTO analysis_run_inputs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        state.analysis_run_id,
                        item.match_id,
                        item.team_id,
                        item.map_name,
                        item.input_status.value,
                        item.exclusion_reason,
                        item.demo_file_id,
                        item.source_demo_sha256,
                        item.dataset_fingerprint,
                        item.feature_run_id,
                        item.feature_fingerprint,
                        _payload(item),
                    ]
                    for item in state.matches
                ],
            )
        if state.findings:
            connection.executemany(
                "INSERT INTO analysis_findings VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        state.analysis_run_id,
                        item.finding_id,
                        item.profile_id,
                        item.source_pattern_id,
                        item.scope.map_name,
                        item.scope.side.value,
                        item.scope.buy_type.value if item.scope.buy_type else None,
                        item.category.value,
                        item.pattern_type.value,
                        item.source_availability.value,
                        item.numerator,
                        item.denominator,
                        item.frequency,
                        item.confidence.score,
                        item.small_sample_warning,
                        _payload(item),
                    ]
                    for item in state.findings
                ],
            )
        evidence = [
            [
                state.analysis_run_id,
                item.finding_id,
                row.evidence_id,
                index,
                row.match_id,
                row.round_id,
                row.round_number,
                row.tick,
                row.contributed_to_numerator,
                _payload(row),
            ]
            for item in state.findings
            for index, row in enumerate(item.evidence_references)
        ]
        if evidence:
            connection.executemany(
                "INSERT INTO finding_evidence_references VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                evidence,
            )

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "analysis_runs",
            "analysis_run_inputs",
            "analysis_findings",
            "finding_evidence_references",
        ):
            row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE analysis_run_id = ?", [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row is not None else 0
        return result


def _summary(row: dict[str, Any], inputs: tuple[Any, ...]) -> AnalysisRunSummary:
    return AnalysisRunSummary(
        analysis_schema_version=str(row["analysis_schema_version"]),
        analysis_rule_version=str(row["analysis_rule_version"]),
        analysis_run_id=row["analysis_run_id"],
        analysis_fingerprint=str(row["analysis_fingerprint"]),
        configuration_hash=str(row["configuration_hash"]),
        profile_id=row["profile_id"],
        workspace_fingerprint=str(row["workspace_fingerprint"]),
        source_pattern_run_id=row["source_pattern_run_id"],
        source_pattern_fingerprint=str(row["source_pattern_fingerprint"]),
        source_pattern_schema_version=str(row["source_pattern_schema_version"]),
        source_pattern_rule_version=str(row["source_pattern_rule_version"]),
        config=_json(row["config"]),
        input_matches=inputs,
        summary=_json(row["summary"]),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _inputs(connection: duckdb.DuckDBPyConnection, analysis_run_id: UUID) -> tuple[Any, ...]:
    from stratweb.findings.models import FindingMatchInput

    rows = connection.execute(
        "SELECT payload FROM analysis_run_inputs WHERE analysis_run_id = ? ORDER BY match_id",
        [analysis_run_id],
    ).fetchall()
    return tuple(FindingMatchInput.model_validate(_json(row[0])) for row in rows)


def _payload(value: Any) -> str:
    return canonical_json(value.model_dump(mode="json"))


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBAnalysisRepository"]
