"""DuckDB persistence for immutable Stage 8.7 counter-strategy runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence._counter_strategy_cascade import delete_strategy_runs
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.counter_strategy.models import (
    STRATEGY_RULE_VERSION,
    STRATEGY_SCHEMA_VERSION,
    CounterStrategyCategory,
    CounterStrategyRecommendation,
    CounterStrategyRun,
    CounterStrategyRunRecord,
    CounterStrategyRunSummary,
    CounterStrategySaveResult,
    SkippedStrategyFinding,
    StrategyComputeStatus,
)
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import PersistenceError
from stratweb.findings.models import AnalysisFinding


class DuckDBCounterStrategyRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_strategy(
        self, state: CounterStrategyRun, *, replace: bool = False
    ) -> CounterStrategySaveResult:
        self.initialize()
        expected = {
            "counter_strategy_runs": 1,
            "counter_strategy_recommendations": len(state.recommendations),
            "counter_strategy_skipped_findings": len(state.skipped_findings),
            "counter_strategy_evidence": sum(
                len(item.evidence_references) for item in state.recommendations
            ),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT strategy_run_id FROM counter_strategy_runs "
                        "WHERE strategy_fingerprint = ?",
                        [state.strategy_fingerprint],
                    ).fetchone()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return CounterStrategySaveResult(
                            strategy_run_id=run_id,
                            strategy_fingerprint=state.strategy_fingerprint,
                            status=StrategyComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if exact is not None:
                        delete_strategy_runs(connection, strategy_run_ids=[exact[0]])
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.strategy_run_id)
                    if actual != expected:
                        raise ValueError(f"strategy row counts differ: {actual} != {expected}")
                    connection.execute("COMMIT")
                    return CounterStrategySaveResult(
                        strategy_run_id=state.strategy_run_id,
                        strategy_fingerprint=state.strategy_fingerprint,
                        status=(
                            StrategyComputeStatus.REPLACED
                            if exact is not None
                            else StrategyComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except (duckdb.Error, ValueError) as exc:
            raise PersistenceError("Could not persist Stage 8.7 strategy run.") from exc

    def get_summary(
        self, profile_id: UUID, *, source_analysis_run_id: UUID
    ) -> CounterStrategyRunSummary | None:
        return self._summary_query(
            "profile_id = ? AND source_analysis_run_id = ? "
            "AND strategy_schema_version = ? AND strategy_rule_version = ?",
            [
                profile_id,
                source_analysis_run_id,
                STRATEGY_SCHEMA_VERSION,
                STRATEGY_RULE_VERSION,
            ],
        )

    def get_summary_for_run(
        self, profile_id: UUID, strategy_run_id: UUID
    ) -> CounterStrategyRunSummary | None:
        return self._summary_query(
            "profile_id = ? AND strategy_run_id = ?", [profile_id, strategy_run_id]
        )

    def _summary_query(
        self, where: str, parameters: list[object]
    ) -> CounterStrategyRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "counter strategies") as connection:
            cursor = connection.execute(
                f"SELECT * FROM counter_strategy_runs WHERE {where} "
                "ORDER BY created_at DESC, strategy_fingerprint DESC LIMIT 1",
                parameters,
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return _summary(dict(zip(columns, row, strict=True)))

    def list_runs(
        self, profile_id: UUID, *, current_analysis_run_id: UUID | None
    ) -> tuple[CounterStrategyRunRecord, ...]:
        self.initialize()
        with read_connection(self._database_path, "counter strategies") as connection:
            rows = connection.execute(
                "SELECT strategy_run_id, strategy_fingerprint, profile_id, "
                "source_analysis_run_id, strategy_schema_version, "
                "strategy_rule_version, created_at FROM counter_strategy_runs "
                "WHERE profile_id = ? ORDER BY created_at DESC, strategy_fingerprint DESC",
                [profile_id],
            ).fetchall()
        selected = next(
            (
                row[0]
                for row in rows
                if row[3] == current_analysis_run_id
                and (str(row[4]), str(row[5])) == (STRATEGY_SCHEMA_VERSION, STRATEGY_RULE_VERSION)
            ),
            None,
        )
        return tuple(
            CounterStrategyRunRecord(
                strategy_run_id=row[0],
                strategy_fingerprint=str(row[1]),
                profile_id=row[2],
                source_analysis_run_id=row[3],
                strategy_schema_version=str(row[4]),
                strategy_rule_version=str(row[5]),
                created_at=row[6],
                compatible=(
                    row[3] == current_analysis_run_id
                    and (str(row[4]), str(row[5]))
                    == (STRATEGY_SCHEMA_VERSION, STRATEGY_RULE_VERSION)
                ),
                selected_by_default=row[0] == selected,
            )
            for row in rows
        )

    def list_recommendations(
        self,
        profile_id: UUID,
        *,
        strategy_run_id: UUID,
        map_name: str | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        category: CounterStrategyCategory | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[CounterStrategyRecommendation, ...]:
        where = ["strategy_run_id = ?", "profile_id = ?"]
        parameters: list[object] = [strategy_run_id, profile_id]
        for column, value in (
            ("map_name", map_name),
            ("side", side.value if side else None),
            ("buy_type", buy_type.value if buy_type else None),
            ("category", category.value if category else None),
        ):
            if value is not None:
                where.append(f"{column} = ?")
                parameters.append(value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "counter strategies") as connection:
            rows = connection.execute(
                "SELECT payload FROM counter_strategy_recommendations WHERE "
                + " AND ".join(where)
                + " ORDER BY map_name, side, category, frequency DESC, recommendation_id "
                "LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(CounterStrategyRecommendation.model_validate(_json(row[0])) for row in rows)

    def get_recommendation(
        self, profile_id: UUID, strategy_run_id: UUID, recommendation_id: UUID
    ) -> CounterStrategyRecommendation | None:
        with read_connection(self._database_path, "counter strategies") as connection:
            row = connection.execute(
                "SELECT payload FROM counter_strategy_recommendations "
                "WHERE profile_id = ? AND strategy_run_id = ? AND recommendation_id = ?",
                [profile_id, strategy_run_id, recommendation_id],
            ).fetchone()
        return CounterStrategyRecommendation.model_validate(_json(row[0])) if row else None

    def list_skipped(self, strategy_run_id: UUID) -> tuple[SkippedStrategyFinding, ...]:
        with read_connection(self._database_path, "counter strategies") as connection:
            rows = connection.execute(
                "SELECT payload FROM counter_strategy_skipped_findings "
                "WHERE strategy_run_id = ? ORDER BY finding_id",
                [strategy_run_id],
            ).fetchall()
        return tuple(SkippedStrategyFinding.model_validate(_json(row[0])) for row in rows)

    def delete_strategies(self, profile_id: UUID) -> int:
        self.initialize()
        with duckdb.connect(str(self._database_path)) as connection:
            rows = connection.execute(
                "SELECT strategy_run_id FROM counter_strategy_runs WHERE profile_id = ?",
                [profile_id],
            ).fetchall()
            connection.execute("BEGIN TRANSACTION")
            try:
                delete_strategy_runs(connection, strategy_run_ids=[row[0] for row in rows])
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return len(rows)

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: CounterStrategyRun) -> None:
        row = connection.execute(
            "SELECT 1 FROM analysis_runs WHERE analysis_run_id = ? "
            "AND analysis_fingerprint = ? AND profile_id = ?",
            [
                state.source_analysis_run_id,
                state.source_analysis_fingerprint,
                state.profile_id,
            ],
        ).fetchone()
        if row is None:
            raise ValueError("strategy references a missing Analysis run")
        if any(
            item.strategy_run_id != state.strategy_run_id
            or item.profile_id != state.profile_id
            or item.source_analysis_run_id != state.source_analysis_run_id
            for item in state.recommendations
        ):
            raise ValueError("strategy child provenance is inconsistent")
        source_rows = connection.execute(
            "SELECT finding_id, payload FROM analysis_findings WHERE analysis_run_id = ?",
            [state.source_analysis_run_id],
        ).fetchall()
        source = {row[0]: AnalysisFinding.model_validate(_json(row[1])) for row in source_rows}
        child_ids = [item.source_finding_id for item in state.recommendations] + [
            item.finding_id for item in state.skipped_findings
        ]
        if len(child_ids) != len(set(child_ids)) or set(child_ids) != set(source):
            raise ValueError("strategy must classify every source finding exactly once")
        for item in state.recommendations:
            finding = source[item.source_finding_id]
            if (
                item.observation != finding.observation
                or item.numerator != finding.numerator
                or item.denominator != finding.denominator
                or item.frequency != finding.frequency
                or item.confidence != finding.confidence
                or tuple(ref.evidence_id for ref in item.evidence_references)
                != tuple(ref.evidence_id for ref in finding.evidence_references)
            ):
                raise ValueError("strategy recommendation differs from source finding evidence")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: CounterStrategyRun,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            "INSERT INTO counter_strategy_runs VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)",
            [
                state.strategy_run_id,
                state.strategy_fingerprint,
                state.strategy_schema_version,
                state.strategy_rule_version,
                state.configuration_hash,
                state.profile_id,
                state.source_analysis_run_id,
                state.source_analysis_fingerprint,
                state.source_analysis_schema_version,
                state.source_analysis_rule_version,
                state.readiness_audit_id,
                state.readiness_fingerprint,
                state.readiness_schema_version,
                state.readiness_rule_version,
                _payload(state.readiness_config),
                _payload(state.config),
                _payload(state.summary),
                canonical_json(row_counts),
                canonical_json(list(state.warnings)),
            ],
        )
        if state.recommendations:
            connection.executemany(
                "INSERT INTO counter_strategy_recommendations VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        state.strategy_run_id,
                        item.recommendation_id,
                        item.profile_id,
                        item.source_finding_id,
                        item.scope.map_name,
                        item.scope.side.value,
                        item.scope.buy_type.value if item.scope.buy_type else None,
                        item.category.value,
                        item.pattern_type.value,
                        item.rule_id.value,
                        item.numerator,
                        item.denominator,
                        item.frequency,
                        _payload(item),
                    ]
                    for item in state.recommendations
                ],
            )
        if state.skipped_findings:
            connection.executemany(
                "INSERT INTO counter_strategy_skipped_findings VALUES (?, ?, ?, ?, ?, ?)",
                [
                    [
                        state.strategy_run_id,
                        item.finding_id,
                        item.reason.value,
                        item.readiness_status.value,
                        item.pattern_type.value,
                        _payload(item),
                    ]
                    for item in state.skipped_findings
                ],
            )
        evidence = [
            [
                state.strategy_run_id,
                item.recommendation_id,
                ref.evidence_id,
                index,
                item.source_finding_id,
                ref.match_id,
                ref.round_id,
                ref.round_number,
                ref.tick,
                _payload(ref),
            ]
            for item in state.recommendations
            for index, ref in enumerate(item.evidence_references)
        ]
        if evidence:
            connection.executemany(
                "INSERT INTO counter_strategy_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                evidence,
            )

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "counter_strategy_runs",
            "counter_strategy_recommendations",
            "counter_strategy_skipped_findings",
            "counter_strategy_evidence",
        ):
            row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE strategy_run_id = ?", [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result


def _summary(row: dict[str, Any]) -> CounterStrategyRunSummary:
    return CounterStrategyRunSummary(
        strategy_schema_version=str(row["strategy_schema_version"]),
        strategy_rule_version=str(row["strategy_rule_version"]),
        strategy_run_id=row["strategy_run_id"],
        strategy_fingerprint=str(row["strategy_fingerprint"]),
        configuration_hash=str(row["configuration_hash"]),
        profile_id=row["profile_id"],
        source_analysis_run_id=row["source_analysis_run_id"],
        source_analysis_fingerprint=str(row["source_analysis_fingerprint"]),
        source_analysis_schema_version=str(row["source_analysis_schema_version"]),
        source_analysis_rule_version=str(row["source_analysis_rule_version"]),
        readiness_audit_id=row["readiness_audit_id"],
        readiness_fingerprint=str(row["readiness_fingerprint"]),
        readiness_schema_version=str(row["readiness_schema_version"]),
        readiness_rule_version=str(row["readiness_rule_version"]),
        readiness_config=_json(row["readiness_config"]),
        config=_json(row["config"]),
        summary=_json(row["summary"]),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _payload(value: Any) -> str:
    return canonical_json(value.model_dump(mode="json"))


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBCounterStrategyRepository"]
