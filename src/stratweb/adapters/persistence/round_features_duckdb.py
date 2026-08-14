"""DuckDB persistence for immutable version-pinned per-round facts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
import polars as pl

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence._pattern_cascade import delete_patterns_for_feature_runs
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import PersistenceError, RoundFeatureIntegrityError
from stratweb.features.models import (
    ROUND_FEATURE_RULE_VERSION,
    ROUND_FEATURE_SCHEMA_VERSION,
    FeatureAvailability,
    FeatureComputeStatus,
    RoundFeature,
    RoundFeatureRunRecord,
    RoundFeatureRunSummary,
    RoundFeatureSaveResult,
    RoundFeatureState,
    RoundFeatureType,
)


class DuckDBRoundFeatureRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_features(
        self, state: RoundFeatureState, *, replace: bool = False
    ) -> RoundFeatureSaveResult:
        self.initialize()
        expected = {"round_feature_runs": 1, "round_features": len(state.features)}
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT feature_run_id FROM round_feature_runs "
                        "WHERE feature_fingerprint = ?",
                        [state.feature_fingerprint],
                    ).fetchone()
                    collisions = connection.execute(
                        """
                        SELECT feature_run_id, feature_fingerprint
                        FROM round_feature_runs
                        WHERE dataset_fingerprint = ?
                          AND analytics_fingerprint = ?
                          AND temporal_fingerprint = ?
                          AND spatial_fingerprint = ?
                          AND zone_assignment_fingerprint = ?
                          AND economy_fingerprint IS NOT DISTINCT FROM ?
                          AND feature_rule_version = ?
                          AND feature_config_hash = ?
                        """,
                        [
                            state.dataset_fingerprint,
                            state.analytics_fingerprint,
                            state.temporal_fingerprint,
                            state.spatial_fingerprint,
                            state.zone_assignment_fingerprint,
                            state.economy_fingerprint,
                            state.feature_rule_version,
                            state.feature_config_hash,
                        ],
                    ).fetchall()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return RoundFeatureSaveResult(
                            feature_run_id=run_id,
                            feature_fingerprint=state.feature_fingerprint,
                            status=FeatureComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if (
                        collisions
                        and not replace
                        and all(str(row[1]) != state.feature_fingerprint for row in collisions)
                    ):
                        raise RoundFeatureIntegrityError(
                            "The same per-round inputs produced another fingerprint."
                        )
                    replacing = exact is not None or bool(collisions)
                    deleted: set[UUID] = set()
                    for feature_run_id, _ in collisions:
                        parsed = UUID(str(feature_run_id))
                        self._delete_run(connection, parsed)
                        deleted.add(parsed)
                    if exact is not None and UUID(str(exact[0])) not in deleted:
                        self._delete_run(connection, UUID(str(exact[0])))
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.feature_run_id)
                    if actual != expected:
                        raise RoundFeatureIntegrityError(
                            f"Round feature row counts differ: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return RoundFeatureSaveResult(
                        feature_run_id=state.feature_run_id,
                        feature_fingerprint=state.feature_fingerprint,
                        status=(
                            FeatureComputeStatus.REPLACED
                            if replacing
                            else FeatureComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except RoundFeatureIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist round feature run.") from exc

    def get_summary(self, match_id: UUID) -> RoundFeatureRunSummary | None:
        row = self._latest_run(match_id)
        return _summary(row) if row is not None else None

    def get_summary_for_run(
        self, match_id: UUID, feature_run_id: UUID
    ) -> RoundFeatureRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "round features") as connection:
            cursor = connection.execute(
                "SELECT * FROM round_feature_runs WHERE match_id = ? AND feature_run_id = ?",
                [match_id, feature_run_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return _summary(dict(zip(columns, row, strict=True)))

    def list_runs(self, match_id: UUID) -> tuple[RoundFeatureRunRecord, ...]:
        self.initialize()
        selected = self._latest_run(match_id)
        selected_id = selected["feature_run_id"] if selected else None
        with read_connection(self._database_path, "round features") as connection:
            rows = connection.execute(
                """
                SELECT feature_run_id, feature_fingerprint, match_id,
                       feature_schema_version, feature_rule_version, created_at,
                       EXISTS (
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
                       ) AS inputs_exist
                FROM round_feature_runs f
                WHERE match_id = ?
                ORDER BY created_at DESC, feature_fingerprint DESC
                """,
                [match_id],
            ).fetchall()
        return tuple(
            RoundFeatureRunRecord(
                feature_run_id=row[0],
                feature_fingerprint=str(row[1]),
                match_id=row[2],
                feature_schema_version=str(row[3]),
                feature_rule_version=str(row[4]),
                created_at=row[5],
                compatible=(
                    (str(row[3]), str(row[4]))
                    == (ROUND_FEATURE_SCHEMA_VERSION, ROUND_FEATURE_RULE_VERSION)
                    and bool(row[6])
                ),
                selected_by_default=row[0] == selected_id,
            )
            for row in rows
        )

    def list_features(
        self,
        match_id: UUID,
        *,
        feature_run_id: UUID | None = None,
        round_number: int | None = None,
        team_id: UUID | None = None,
        side: Side | None = None,
        feature_type: RoundFeatureType | None = None,
        availability: FeatureAvailability | None = None,
        buy_type: BuyType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[RoundFeature, ...]:
        summary = self._resolve_summary(match_id, feature_run_id)
        if summary is None:
            return ()
        where = ["feature_run_id = ?", "match_id = ?"]
        parameters: list[object] = [summary.feature_run_id, match_id]
        for column, value in (
            ("round_number", round_number),
            ("team_id", team_id),
            ("side", side.value if side else None),
            ("feature_type", feature_type.value if feature_type else None),
            ("availability", availability.value if availability else None),
            ("buy_type", buy_type.value if buy_type else None),
        ):
            if value is not None:
                where.append(f"{column} = ?")
                parameters.append(value)
        parameters.extend([limit, offset])
        with read_connection(self._database_path, "round features") as connection:
            rows = connection.execute(
                "SELECT payload FROM round_features WHERE "
                + " AND ".join(where)
                + " ORDER BY round_number, side, feature_type, tick_start, feature_id "
                + "LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        return tuple(RoundFeature.model_validate(_json(row[0])) for row in rows)

    def delete_features(self, match_id: UUID) -> int:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    rows = connection.execute(
                        "SELECT feature_run_id FROM round_feature_runs WHERE match_id = ?",
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
            raise PersistenceError("Could not delete round feature runs.") from exc

    def _resolve_summary(
        self, match_id: UUID, feature_run_id: UUID | None
    ) -> RoundFeatureRunSummary | None:
        return (
            self.get_summary_for_run(match_id, feature_run_id)
            if feature_run_id is not None
            else self.get_summary(match_id)
        )

    def _latest_run(self, match_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with read_connection(self._database_path, "round features") as connection:
            cursor = connection.execute(
                """
                SELECT f.* FROM round_feature_runs f
                WHERE f.match_id = ?
                  AND f.feature_schema_version = ?
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
                ORDER BY created_at DESC, feature_fingerprint DESC
                LIMIT 1
                """,
                [match_id, ROUND_FEATURE_SCHEMA_VERSION, ROUND_FEATURE_RULE_VERSION],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: RoundFeatureState) -> None:
        checks: tuple[tuple[str, list[object], str], ...] = (
            (
                "SELECT 1 FROM matches WHERE match_id = ? AND dataset_fingerprint = ?",
                [state.match_id, state.dataset_fingerprint],
                "canonical match",
            ),
            (
                "SELECT 1 FROM analytics_runs WHERE match_id = ? AND analytics_fingerprint = ?",
                [state.match_id, state.analytics_fingerprint],
                "analytics run",
            ),
            (
                "SELECT 1 FROM temporal_runs WHERE match_id = ? AND temporal_run_id = ? "
                "AND temporal_fingerprint = ?",
                [state.match_id, state.temporal_run_id, state.temporal_fingerprint],
                "temporal run",
            ),
            (
                "SELECT 1 FROM spatial_runs WHERE match_id = ? AND spatial_run_id = ? "
                "AND spatial_fingerprint = ?",
                [state.match_id, state.spatial_run_id, state.spatial_fingerprint],
                "spatial run",
            ),
            (
                "SELECT 1 FROM zone_assignment_runs WHERE match_id = ? "
                "AND zone_assignment_run_id = ? AND zone_assignment_fingerprint = ?",
                [
                    state.match_id,
                    state.zone_assignment_run_id,
                    state.zone_assignment_fingerprint,
                ],
                "zone assignment run",
            ),
        )
        for sql, parameters, label in checks:
            if connection.execute(sql, parameters).fetchone() is None:
                raise RoundFeatureIntegrityError(
                    f"Round feature run references an incompatible {label}."
                )
        if state.economy_run_id is not None:
            economy = connection.execute(
                "SELECT 1 FROM economy_runs WHERE match_id = ? AND economy_run_id = ? "
                "AND economy_fingerprint = ?",
                [state.match_id, state.economy_run_id, state.economy_fingerprint],
            ).fetchone()
            if economy is None:
                raise RoundFeatureIntegrityError(
                    "Round feature run references an incompatible economy run."
                )
        inconsistent = any(
            item.feature_run_id != state.feature_run_id or item.match_id != state.match_id
            for item in state.features
        )
        if inconsistent:
            raise RoundFeatureIntegrityError("Round feature child-row provenance is inconsistent.")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: RoundFeatureState,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO round_feature_runs (
                feature_run_id, feature_fingerprint, feature_schema_version,
                feature_rule_version, feature_config_hash, match_id, dataset_fingerprint,
                analytics_fingerprint, analytics_rule_version,
                temporal_run_id, temporal_fingerprint, temporal_rule_version,
                spatial_run_id, spatial_fingerprint, spatial_rule_version,
                zone_assignment_run_id, zone_assignment_fingerprint,
                zone_assignment_rule_version, economy_run_id, economy_fingerprint,
                economy_rule_version, config, capabilities, summary, row_counts,
                warnings, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      ?, ?, ?, ?, ?, current_timestamp)
            """,
            [
                state.feature_run_id,
                state.feature_fingerprint,
                state.feature_schema_version,
                state.feature_rule_version,
                state.feature_config_hash,
                state.match_id,
                state.dataset_fingerprint,
                state.analytics_fingerprint,
                state.analytics_rule_version,
                state.temporal_run_id,
                state.temporal_fingerprint,
                state.temporal_rule_version,
                state.spatial_run_id,
                state.spatial_fingerprint,
                state.spatial_rule_version,
                state.zone_assignment_run_id,
                state.zone_assignment_fingerprint,
                state.zone_assignment_rule_version,
                state.economy_run_id,
                state.economy_fingerprint,
                state.economy_rule_version,
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
        if not state.features:
            return
        frame = pl.DataFrame(
            [
                {
                    "feature_run_id": str(item.feature_run_id),
                    "feature_id": str(item.feature_id),
                    "match_id": str(item.match_id),
                    "round_id": str(item.round_id),
                    "round_number": item.round_number,
                    "team_id": str(item.team_id),
                    "side": item.side.value,
                    "feature_type": item.feature_type.value,
                    "availability": item.availability.value,
                    "tick_start": item.tick_start,
                    "tick_end": item.tick_end,
                    "zone_id": item.zone_id,
                    "zone_name": item.zone_name,
                    "buy_type": item.buy_type.value if item.buy_type else None,
                    "payload": _payload(item),
                }
                for item in state.features
            ],
            strict=False,
        )
        connection.register("round_feature_batch", frame)
        try:
            connection.execute(
                "INSERT INTO round_features BY NAME SELECT * FROM round_feature_batch"
            )
        finally:
            connection.unregister("round_feature_batch")

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("round_feature_runs", "round_features"):
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE feature_run_id = ?', [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result

    @staticmethod
    def _delete_run(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> None:
        delete_patterns_for_feature_runs(connection, [run_id])
        connection.execute("DELETE FROM round_features WHERE feature_run_id = ?", [run_id])
        connection.execute("DELETE FROM round_feature_runs WHERE feature_run_id = ?", [run_id])


def _summary(row: dict[str, Any]) -> RoundFeatureRunSummary:
    return RoundFeatureRunSummary(
        feature_schema_version=str(row["feature_schema_version"]),
        feature_rule_version=str(row["feature_rule_version"]),
        feature_run_id=row["feature_run_id"],
        feature_fingerprint=str(row["feature_fingerprint"]),
        feature_config_hash=str(row["feature_config_hash"]),
        match_id=row["match_id"],
        dataset_fingerprint=str(row["dataset_fingerprint"]),
        analytics_fingerprint=str(row["analytics_fingerprint"]),
        analytics_rule_version=str(row["analytics_rule_version"]),
        temporal_run_id=row["temporal_run_id"],
        temporal_fingerprint=str(row["temporal_fingerprint"]),
        temporal_rule_version=str(row["temporal_rule_version"]),
        spatial_run_id=row["spatial_run_id"],
        spatial_fingerprint=str(row["spatial_fingerprint"]),
        spatial_rule_version=str(row["spatial_rule_version"]),
        zone_assignment_run_id=row["zone_assignment_run_id"],
        zone_assignment_fingerprint=str(row["zone_assignment_fingerprint"]),
        zone_assignment_rule_version=str(row["zone_assignment_rule_version"]),
        economy_run_id=row["economy_run_id"],
        economy_fingerprint=(
            str(row["economy_fingerprint"]) if row["economy_fingerprint"] is not None else None
        ),
        economy_rule_version=(
            str(row["economy_rule_version"]) if row["economy_rule_version"] is not None else None
        ),
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


__all__ = ["DuckDBRoundFeatureRepository"]
