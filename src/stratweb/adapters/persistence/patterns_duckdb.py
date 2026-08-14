"""DuckDB persistence for immutable cross-match pattern runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence._pattern_cascade import delete_pattern_runs
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import PatternIntegrityError, PersistenceError
from stratweb.features.models import ROUND_FEATURE_RULE_VERSION, ROUND_FEATURE_SCHEMA_VERSION
from stratweb.patterns.models import (
    PATTERN_RULE_VERSION,
    PATTERN_SCHEMA_VERSION,
    CrossMatchPattern,
    PatternAvailability,
    PatternComputeStatus,
    PatternInputStatus,
    PatternRunInputRecord,
    PatternRunRecord,
    PatternRunSummary,
    PatternSaveResult,
    PatternState,
    PatternType,
)


class DuckDBPatternRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_patterns(self, state: PatternState, *, replace: bool = False) -> PatternSaveResult:
        self.initialize()
        expected = {
            "cross_match_pattern_runs": 1,
            "pattern_run_inputs": len(state.inputs),
            "cross_match_patterns": len(state.patterns),
            "pattern_round_evidence": sum(len(item.included_rounds) for item in state.patterns),
            "pattern_round_exclusions": sum(len(item.excluded_rounds) for item in state.patterns),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT pattern_run_id FROM cross_match_pattern_runs "
                        "WHERE pattern_fingerprint = ?",
                        [state.pattern_fingerprint],
                    ).fetchone()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return PatternSaveResult(
                            pattern_run_id=run_id,
                            pattern_fingerprint=state.pattern_fingerprint,
                            status=PatternComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    replacing = exact is not None
                    if exact is not None:
                        delete_pattern_runs(connection, pattern_run_ids=[exact[0]])
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.pattern_run_id)
                    if actual != expected:
                        raise PatternIntegrityError(
                            f"Pattern row counts differ: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return PatternSaveResult(
                        pattern_run_id=state.pattern_run_id,
                        pattern_fingerprint=state.pattern_fingerprint,
                        status=(
                            PatternComputeStatus.REPLACED
                            if replacing
                            else PatternComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except PatternIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist cross-match pattern run.") from exc

    def get_summary(self, profile_id: UUID) -> PatternRunSummary | None:
        row = self._latest_run(profile_id)
        return _summary(row) if row is not None else None

    def get_summary_for_run(
        self, profile_id: UUID, pattern_run_id: UUID
    ) -> PatternRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "cross-match patterns") as connection:
            cursor = connection.execute(
                "SELECT * FROM cross_match_pattern_runs "
                "WHERE profile_id = ? AND pattern_run_id = ?",
                [profile_id, pattern_run_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return _summary(dict(zip(columns, row, strict=True)))

    def list_runs(self, profile_id: UUID) -> tuple[PatternRunRecord, ...]:
        self.initialize()
        selected = self._latest_run(profile_id)
        selected_id = selected["pattern_run_id"] if selected else None
        with read_connection(self._database_path, "cross-match patterns") as connection:
            rows = connection.execute(
                """
                SELECT pattern_run_id, pattern_fingerprint, profile_id,
                       pattern_schema_version, pattern_rule_version, created_at
                FROM cross_match_pattern_runs
                WHERE profile_id = ?
                ORDER BY created_at DESC, pattern_fingerprint DESC
                """,
                [profile_id],
            ).fetchall()
            compatibility = {
                row[0]: self._compatible(connection, row[0], profile_id) for row in rows
            }
        return tuple(
            PatternRunRecord(
                pattern_run_id=row[0],
                pattern_fingerprint=str(row[1]),
                profile_id=row[2],
                pattern_schema_version=str(row[3]),
                pattern_rule_version=str(row[4]),
                created_at=row[5],
                compatible=(
                    (str(row[3]), str(row[4])) == (PATTERN_SCHEMA_VERSION, PATTERN_RULE_VERSION)
                    and compatibility[row[0]]
                ),
                selected_by_default=row[0] == selected_id,
            )
            for row in rows
        )

    def list_inputs(
        self, profile_id: UUID, pattern_run_id: UUID
    ) -> tuple[PatternRunInputRecord, ...]:
        if self.get_summary_for_run(profile_id, pattern_run_id) is None:
            return ()
        with read_connection(self._database_path, "cross-match patterns") as connection:
            rows = connection.execute(
                """
                SELECT pattern_run_id, match_id, team_id, map_name, input_status,
                       exclusion_reason, feature_run_id, feature_fingerprint,
                       feature_rule_version
                FROM pattern_run_inputs
                WHERE pattern_run_id = ?
                ORDER BY match_id
                """,
                [pattern_run_id],
            ).fetchall()
        return tuple(
            PatternRunInputRecord(
                pattern_run_id=row[0],
                match_id=row[1],
                team_id=row[2],
                map_name=str(row[3]),
                input_status=PatternInputStatus(str(row[4])),
                exclusion_reason=str(row[5]) if row[5] is not None else None,
                feature_run_id=row[6],
                feature_fingerprint=str(row[7]) if row[7] is not None else None,
                feature_rule_version=str(row[8]) if row[8] is not None else None,
            )
            for row in rows
        )

    def list_patterns(
        self,
        profile_id: UUID,
        *,
        pattern_run_id: UUID | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        pattern_type: PatternType | None = None,
        availability: PatternAvailability | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[CrossMatchPattern, ...]:
        summary = (
            self.get_summary_for_run(profile_id, pattern_run_id)
            if pattern_run_id is not None
            else self.get_summary(profile_id)
        )
        if summary is None:
            return ()
        where = ["pattern_run_id = ?", "profile_id = ?"]
        parameters: list[object] = [summary.pattern_run_id, profile_id]
        for column, value in (
            ("map_name", map_name),
            ("side", side.value if side else None),
            ("buy_type", buy_type.value if buy_type else None),
            ("pattern_type", pattern_type.value if pattern_type else None),
            ("availability", availability.value if availability else None),
        ):
            if value is not None:
                where.append(f"{column} = ?")
                parameters.append(value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "cross-match patterns") as connection:
            rows = connection.execute(
                "SELECT payload FROM cross_match_patterns WHERE "
                + " AND ".join(where)
                + " ORDER BY map_name, side, buy_type, pattern_type, frequency DESC, "
                + "pattern_key, pattern_id LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(CrossMatchPattern.model_validate(_json(row[0])) for row in rows)

    def delete_patterns(self, profile_id: UUID) -> int:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                rows = connection.execute(
                    "SELECT pattern_run_id FROM cross_match_pattern_runs WHERE profile_id = ?",
                    [profile_id],
                ).fetchall()
                connection.execute("BEGIN TRANSACTION")
                try:
                    delete_pattern_runs(
                        connection,
                        pattern_run_ids=[row[0] for row in rows],
                    )
                    connection.execute("COMMIT")
                    return len(rows)
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not delete cross-match pattern runs.") from exc

    def _latest_run(self, profile_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with read_connection(self._database_path, "cross-match patterns") as connection:
            cursor = connection.execute(
                """
                WITH compatible_features AS (
                    SELECT f.match_id, f.feature_run_id, f.feature_fingerprint,
                           row_number() OVER (
                               PARTITION BY f.match_id
                               ORDER BY f.created_at DESC, f.feature_fingerprint DESC
                           ) AS compatibility_rank
                    FROM round_feature_runs f
                    WHERE f.feature_schema_version = ?
                      AND f.feature_rule_version = ?
                      AND EXISTS (
                          SELECT 1 FROM analytics_runs a
                          WHERE a.analytics_fingerprint = f.analytics_fingerprint
                            AND a.match_id = f.match_id
                      )
                      AND EXISTS (
                          SELECT 1 FROM temporal_runs t
                          WHERE t.temporal_run_id = f.temporal_run_id
                            AND t.temporal_fingerprint = f.temporal_fingerprint
                      )
                      AND EXISTS (
                          SELECT 1 FROM spatial_runs s
                          WHERE s.spatial_run_id = f.spatial_run_id
                            AND s.spatial_fingerprint = f.spatial_fingerprint
                      )
                      AND EXISTS (
                          SELECT 1 FROM zone_assignment_runs z
                          WHERE z.zone_assignment_run_id = f.zone_assignment_run_id
                            AND z.zone_assignment_fingerprint =
                                f.zone_assignment_fingerprint
                      )
                      AND (
                          f.economy_run_id IS NULL OR EXISTS (
                              SELECT 1 FROM economy_runs e
                              WHERE e.economy_run_id = f.economy_run_id
                                AND e.economy_fingerprint = f.economy_fingerprint
                          )
                      )
                )
                SELECT * FROM cross_match_pattern_runs run
                WHERE profile_id = ? AND pattern_schema_version = ?
                  AND pattern_rule_version = ?
                  AND (
                    SELECT count(*) FROM pattern_run_inputs input
                    WHERE input.pattern_run_id = run.pattern_run_id
                  ) = (
                    SELECT count(*) FROM opponent_match_selections selection
                    WHERE selection.profile_id = run.profile_id
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM pattern_run_inputs input
                    WHERE input.pattern_run_id = run.pattern_run_id
                      AND NOT EXISTS (
                        SELECT 1 FROM opponent_match_selections selection
                        WHERE selection.profile_id = run.profile_id
                          AND selection.match_id = input.match_id
                          AND selection.team_id = input.team_id
                      )
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM pattern_run_inputs input
                    LEFT JOIN compatible_features current_feature
                      ON current_feature.match_id = input.match_id
                     AND current_feature.compatibility_rank = 1
                    WHERE input.pattern_run_id = run.pattern_run_id
                      AND (
                        (
                          input.input_status = 'included'
                          AND (
                            input.feature_run_id IS DISTINCT FROM
                                current_feature.feature_run_id
                            OR input.feature_fingerprint IS DISTINCT FROM
                                current_feature.feature_fingerprint
                          )
                        )
                        OR (
                          input.input_status = 'excluded'
                          AND current_feature.feature_run_id IS NOT NULL
                        )
                      )
                  )
                ORDER BY created_at DESC, pattern_fingerprint DESC
                LIMIT 1
                """,
                [
                    ROUND_FEATURE_SCHEMA_VERSION,
                    ROUND_FEATURE_RULE_VERSION,
                    profile_id,
                    PATTERN_SCHEMA_VERSION,
                    PATTERN_RULE_VERSION,
                ],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    @staticmethod
    def _compatible(
        connection: duckdb.DuckDBPyConnection,
        pattern_run_id: UUID,
        profile_id: UUID,
    ) -> bool:
        row = connection.execute(
            """
            WITH compatible_features AS (
                SELECT f.match_id, f.feature_run_id, f.feature_fingerprint,
                       row_number() OVER (
                           PARTITION BY f.match_id
                           ORDER BY f.created_at DESC, f.feature_fingerprint DESC
                       ) AS compatibility_rank
                FROM round_feature_runs f
                WHERE f.feature_schema_version = ?
                  AND f.feature_rule_version = ?
                  AND EXISTS (
                      SELECT 1 FROM analytics_runs a
                      WHERE a.analytics_fingerprint = f.analytics_fingerprint
                        AND a.match_id = f.match_id
                  )
                  AND EXISTS (
                      SELECT 1 FROM temporal_runs t
                      WHERE t.temporal_run_id = f.temporal_run_id
                        AND t.temporal_fingerprint = f.temporal_fingerprint
                  )
                  AND EXISTS (
                      SELECT 1 FROM spatial_runs s
                      WHERE s.spatial_run_id = f.spatial_run_id
                        AND s.spatial_fingerprint = f.spatial_fingerprint
                  )
                  AND EXISTS (
                      SELECT 1 FROM zone_assignment_runs z
                      WHERE z.zone_assignment_run_id = f.zone_assignment_run_id
                        AND z.zone_assignment_fingerprint = f.zone_assignment_fingerprint
                  )
                  AND (
                      f.economy_run_id IS NULL OR EXISTS (
                          SELECT 1 FROM economy_runs e
                          WHERE e.economy_run_id = f.economy_run_id
                            AND e.economy_fingerprint = f.economy_fingerprint
                      )
                  )
            )
            SELECT
              (SELECT count(*) FROM pattern_run_inputs WHERE pattern_run_id = ?) =
              (SELECT count(*) FROM opponent_match_selections WHERE profile_id = ?)
              AND NOT EXISTS (
                SELECT 1 FROM pattern_run_inputs input
                WHERE input.pattern_run_id = ? AND NOT EXISTS (
                  SELECT 1 FROM opponent_match_selections selection
                  WHERE selection.profile_id = ? AND selection.match_id = input.match_id
                    AND selection.team_id = input.team_id
                )
              )
              AND NOT EXISTS (
                SELECT 1
                FROM pattern_run_inputs input
                LEFT JOIN compatible_features current_feature
                  ON current_feature.match_id = input.match_id
                 AND current_feature.compatibility_rank = 1
                WHERE input.pattern_run_id = ?
                  AND (
                    (
                      input.input_status = 'included'
                      AND (
                        input.feature_run_id IS DISTINCT FROM current_feature.feature_run_id
                        OR input.feature_fingerprint IS DISTINCT FROM
                            current_feature.feature_fingerprint
                      )
                    )
                    OR (
                      input.input_status = 'excluded'
                      AND current_feature.feature_run_id IS NOT NULL
                    )
                  )
              )
            """,
            [
                ROUND_FEATURE_SCHEMA_VERSION,
                ROUND_FEATURE_RULE_VERSION,
                pattern_run_id,
                profile_id,
                pattern_run_id,
                profile_id,
                pattern_run_id,
            ],
        ).fetchone()
        return bool(row and row[0])

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: PatternState) -> None:
        if (
            connection.execute(
                "SELECT 1 FROM opponent_profiles WHERE profile_id = ?", [state.profile_id]
            ).fetchone()
            is None
        ):
            raise PatternIntegrityError("Pattern run references a missing opponent profile.")
        for item in state.inputs:
            selected = connection.execute(
                "SELECT 1 FROM opponent_match_selections "
                "WHERE profile_id = ? AND match_id = ? AND team_id = ?",
                [state.profile_id, item.match_id, item.team_id],
            ).fetchone()
            if selected is None:
                raise PatternIntegrityError(
                    "Pattern input is not a current user-confirmed opponent selection."
                )
            if item.status.value == "included":
                feature = connection.execute(
                    "SELECT 1 FROM round_feature_runs WHERE match_id = ? "
                    "AND feature_run_id = ? AND feature_fingerprint = ?",
                    [item.match_id, item.feature_run_id, item.feature_fingerprint],
                ).fetchone()
                if feature is None:
                    raise PatternIntegrityError(
                        "Pattern input references an incompatible feature run."
                    )
        if any(
            item.pattern_run_id != state.pattern_run_id or item.profile_id != state.profile_id
            for item in state.patterns
        ):
            raise PatternIntegrityError("Pattern child-row provenance is inconsistent.")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: PatternState,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO cross_match_pattern_runs (
                pattern_run_id, pattern_fingerprint, pattern_schema_version,
                pattern_rule_version, confidence_method, pattern_config_hash,
                workspace_fingerprint, profile_id, config, capabilities, summary,
                row_counts, warnings, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            """,
            [
                state.pattern_run_id,
                state.pattern_fingerprint,
                state.pattern_schema_version,
                state.pattern_rule_version,
                state.confidence_method,
                state.pattern_config_hash,
                state.workspace_fingerprint,
                state.profile_id,
                _payload(state.config),
                canonical_json(
                    {
                        key.value: value.model_dump(mode="json")
                        for key, value in state.capabilities.items()
                    }
                ),
                _payload(state.summary),
                canonical_json(row_counts),
                canonical_json(list(state.warnings)),
            ],
        )
        if state.inputs:
            connection.executemany(
                """
                INSERT INTO pattern_run_inputs (
                    pattern_run_id, match_id, team_id, map_name, input_status,
                    exclusion_reason, feature_run_id, feature_fingerprint,
                    feature_rule_version, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.pattern_run_id,
                        item.match_id,
                        item.team_id,
                        item.map_name,
                        item.status.value,
                        item.exclusion_reason,
                        item.feature_run_id,
                        item.feature_fingerprint,
                        item.feature_rule_version,
                        canonical_json(item.model_dump(mode="json", exclude={"players", "rounds"})),
                    ]
                    for item in state.inputs
                ],
            )
        if state.patterns:
            connection.executemany(
                """
                INSERT INTO cross_match_patterns (
                    pattern_run_id, pattern_id, profile_id, map_name, side, buy_type,
                    feature_rule_version, pattern_type, pattern_key, availability,
                    numerator, denominator, frequency, confidence_lower,
                    confidence_upper, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        item.pattern_run_id,
                        item.pattern_id,
                        item.profile_id,
                        item.scope.map_name,
                        item.scope.side.value,
                        item.scope.buy_type.value if item.scope.buy_type else None,
                        item.scope.feature_rule_version,
                        item.pattern_type.value,
                        canonical_json(item.value.model_dump(mode="json")),
                        item.availability.value,
                        item.numerator,
                        item.denominator,
                        item.frequency,
                        item.confidence.lower_bound,
                        item.confidence.upper_bound,
                        _payload(item),
                    ]
                    for item in state.patterns
                ],
            )
        evidence_rows = [
            [
                item.pattern_run_id,
                item.pattern_id,
                index,
                evidence.match_id,
                evidence.round_id,
                evidence.round_number,
                evidence.tick,
                evidence.contributed_to_numerator,
                _payload(evidence),
            ]
            for item in state.patterns
            for index, evidence in enumerate(item.included_rounds)
        ]
        if evidence_rows:
            connection.executemany(
                "INSERT INTO pattern_round_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                evidence_rows,
            )
        exclusion_rows = [
            [
                item.pattern_run_id,
                item.pattern_id,
                index,
                exclusion.match_id,
                exclusion.round_id,
                exclusion.round_number,
                exclusion.reason,
                _payload(exclusion),
            ]
            for item in state.patterns
            for index, exclusion in enumerate(item.excluded_rounds)
        ]
        if exclusion_rows:
            connection.executemany(
                "INSERT INTO pattern_round_exclusions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                exclusion_rows,
            )

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "cross_match_pattern_runs",
            "pattern_run_inputs",
            "cross_match_patterns",
            "pattern_round_evidence",
            "pattern_round_exclusions",
        ):
            row = connection.execute(
                f"SELECT count(*) FROM {table} WHERE pattern_run_id = ?", [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result


def _summary(row: dict[str, Any]) -> PatternRunSummary:
    return PatternRunSummary(
        pattern_schema_version=str(row["pattern_schema_version"]),
        pattern_rule_version=str(row["pattern_rule_version"]),
        confidence_method=str(row["confidence_method"]),
        pattern_run_id=row["pattern_run_id"],
        pattern_fingerprint=str(row["pattern_fingerprint"]),
        pattern_config_hash=str(row["pattern_config_hash"]),
        workspace_fingerprint=str(row["workspace_fingerprint"]),
        profile_id=row["profile_id"],
        config=_json(row["config"]),
        capabilities=_json(row["capabilities"]),
        summary=_json(row["summary"]),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _payload(value: Any) -> str:
    return canonical_json(value.model_dump(mode="json"))


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBPatternRepository"]
