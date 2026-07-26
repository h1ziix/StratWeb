"""DuckDB adapter for atomic, queryable analytics runs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

import duckdb
import polars as pl
from pydantic import BaseModel

from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.analytics.models import (
    AnalyticsAvailability,
    AnalyticsAvailabilitySummary,
    AnalyticsComputeStatus,
    AnalyticsConfig,
    AnalyticsRunSummary,
    AnalyticsSaveResult,
    AnalyticsSummary,
    AnalyticsUnavailableReason,
    ManAdvantageTransition,
    MatchAnalytics,
    OpeningDuel,
    PlayerMatchAnalytics,
    PlayerRoundAnalytics,
    RoundAnalyticsView,
    TeamMatchAnalytics,
    TeamRoundAnalytics,
    TradeEvent,
    TradePolicyCapability,
    TradeWindowConfig,
    TradeWindowMode,
    TradeWindowResolutionSource,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import AnalyticsIntegrityError, PersistenceError

_T = TypeVar("_T", bound=BaseModel)
_COUNT_TABLES: tuple[str, ...] = (
    "player_round_analytics",
    "player_match_analytics",
    "team_round_analytics",
    "team_match_analytics",
    "opening_duels",
    "trade_events",
    "man_advantage_transitions",
    "analytics_validation_issues",
)
_CHILD_TABLES: tuple[str, ...] = (
    "analytics_validation_issues",
    "man_advantage_transitions",
    "trade_events",
    "opening_duels",
    "team_match_analytics",
    "team_round_analytics",
    "player_match_analytics",
    "player_round_analytics",
)


class DuckDBAnalyticsRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_analytics(
        self, analytics: MatchAnalytics, *, replace: bool = False
    ) -> AnalyticsSaveResult:
        self.initialize()
        fingerprint = analytics.analytics_fingerprint
        expected = _row_counts(analytics)
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    match = connection.execute(
                        "SELECT dataset_fingerprint FROM matches WHERE match_id = ?",
                        [analytics.match_id],
                    ).fetchone()
                    if match is None or str(match[0]) != analytics.dataset_fingerprint:
                        raise AnalyticsIntegrityError(
                            "Analytics input does not match the persisted canonical dataset."
                        )
                    exact = connection.execute(
                        "SELECT 1 FROM analytics_runs WHERE analytics_fingerprint = ?",
                        [fingerprint],
                    ).fetchone()
                    collision_rows = connection.execute(
                        """
                        SELECT analytics_fingerprint FROM analytics_runs
                        WHERE dataset_fingerprint = ? AND analytics_rule_version = ?
                          AND analytics_config_hash = ?
                        """,
                        [
                            analytics.dataset_fingerprint,
                            analytics.analytics_rule_version,
                            analytics.analytics_config_hash,
                        ],
                    ).fetchall()
                    collision_fingerprints = {str(row[0]) for row in collision_rows}
                    if exact is not None and not replace:
                        counts = self._counts(connection, fingerprint)
                        connection.execute("ROLLBACK")
                        return AnalyticsSaveResult(
                            analytics_fingerprint=fingerprint,
                            status=AnalyticsComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if (
                        collision_fingerprints
                        and fingerprint not in collision_fingerprints
                        and not replace
                    ):
                        raise AnalyticsIntegrityError(
                            "The same dataset/rule/config produced another analytics fingerprint."
                        )
                    replacing = exact is not None or bool(collision_fingerprints)
                    for existing in sorted(
                        collision_fingerprints | ({fingerprint} if exact else set())
                    ):
                        self._delete_fingerprint(connection, existing)
                    self._insert(connection, analytics, expected)
                    actual = self._counts(connection, fingerprint)
                    if actual != expected:
                        raise AnalyticsIntegrityError(
                            f"Analytics row counts differ after insert: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return AnalyticsSaveResult(
                        analytics_fingerprint=fingerprint,
                        status=(
                            AnalyticsComputeStatus.REPLACED
                            if replacing
                            else AnalyticsComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except AnalyticsIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist analytics run.") from exc

    def get_summary(self, match_id: UUID) -> AnalyticsRunSummary | None:
        self.initialize()
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            row = _fetch_one(
                connection,
                """
                SELECT * FROM analytics_runs WHERE match_id = ?
                ORDER BY created_at DESC, analytics_fingerprint DESC LIMIT 1
                """,
                [match_id],
            )
        if row is None:
            return None
        legacy = row["trade_window_mode"] == TradeWindowMode.LEGACY_AMBIGUOUS
        if legacy:
            config = AnalyticsConfig(trade_window=TradeWindowConfig.legacy_ambiguous())
            availability = _legacy_availability(_json_value(row["availability"]))
            summary = _legacy_summary(_json_value(row["summary"]))
        else:
            config = AnalyticsConfig.model_validate(_json_value(row["config"]))
            availability = AnalyticsAvailabilitySummary.model_validate(
                _json_value(row["availability"])
            )
            summary = AnalyticsSummary.model_validate(_json_value(row["summary"]))
        return AnalyticsRunSummary(
            analytics_schema_version=row["analytics_schema_version"],
            analytics_rule_version=row["analytics_rule_version"],
            analytics_config_hash=row["analytics_config_hash"],
            analytics_fingerprint=row["analytics_fingerprint"],
            match_id=row["match_id"],
            dataset_fingerprint=row["dataset_fingerprint"],
            config=config,
            availability=availability,
            summary=summary,
            row_counts=_json_value(row["row_counts"]),
            warnings=tuple(_json_value(row["warnings"])),
        )

    def list_player_stats(self, match_id: UUID) -> tuple[PlayerMatchAnalytics, ...]:
        return self._model_rows(
            match_id,
            "player_match_analytics",
            PlayerMatchAnalytics,
            "kills DESC, player_id",
        )

    def get_player_stats(self, match_id: UUID, player_id: UUID) -> PlayerMatchAnalytics | None:
        rows = tuple(
            item for item in self.list_player_stats(match_id) if item.player_id == player_id
        )
        return rows[0] if rows else None

    def list_team_stats(self, match_id: UUID) -> tuple[TeamMatchAnalytics, ...]:
        return self._model_rows(
            match_id,
            "team_match_analytics",
            TeamMatchAnalytics,
            "team_id",
        )

    def get_round_analytics(self, match_id: UUID, round_number: int) -> RoundAnalyticsView | None:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return None
        players = self._model_rows_for_fingerprint(
            fingerprint,
            "player_round_analytics",
            PlayerRoundAnalytics,
            "player_id",
            round_number,
        )
        teams = self._model_rows_for_fingerprint(
            fingerprint,
            "team_round_analytics",
            TeamRoundAnalytics,
            "team_id",
            round_number,
        )
        if not players and not teams:
            return None
        openings = self._model_rows_for_fingerprint(
            fingerprint, "opening_duels", OpeningDuel, "event_id", round_number
        )
        trades = self._model_rows_for_fingerprint(
            fingerprint, "trade_events", TradeEvent, "traded_kill_event_id", round_number
        )
        transitions = self._model_rows_for_fingerprint(
            fingerprint,
            "man_advantage_transitions",
            ManAdvantageTransition,
            "tick, event_id",
            round_number,
        )
        return RoundAnalyticsView(
            match_id=match_id,
            round_number=round_number,
            player_rounds=players,
            team_rounds=teams,
            opening_duel=openings[0] if openings else None,
            trade_events=trades,
            man_advantage_transitions=transitions,
        )

    def list_opening_duels(self, match_id: UUID) -> tuple[OpeningDuel, ...]:
        return self._model_rows(
            match_id, "opening_duels", OpeningDuel, "round_number, tick, event_id"
        )

    def list_trade_events(
        self, match_id: UUID, round_number: int | None = None
    ) -> tuple[TradeEvent, ...]:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return ()
        return self._model_rows_for_fingerprint(
            fingerprint,
            "trade_events",
            TradeEvent,
            "round_number, tick_delta, traded_kill_event_id",
            round_number,
        )

    def get_man_advantage_timeline(
        self, match_id: UUID, round_number: int
    ) -> tuple[ManAdvantageTransition, ...]:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return ()
        return self._model_rows_for_fingerprint(
            fingerprint,
            "man_advantage_transitions",
            ManAdvantageTransition,
            "tick, event_id",
            round_number,
        )

    def delete_analytics(self, match_id: UUID) -> bool:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    exists = connection.execute(
                        "SELECT 1 FROM analytics_runs WHERE match_id = ? LIMIT 1", [match_id]
                    ).fetchone()
                    if exists is None:
                        connection.execute("ROLLBACK")
                        return False
                    for table in _CHILD_TABLES:
                        connection.execute(f'DELETE FROM "{table}" WHERE match_id = ?', [match_id])
                    connection.execute("DELETE FROM analytics_runs WHERE match_id = ?", [match_id])
                    connection.execute("COMMIT")
                    return True
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not delete analytics runs.") from exc

    def _insert(
        self,
        connection: duckdb.DuckDBPyConnection,
        analytics: MatchAnalytics,
        counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO analytics_runs (
                analytics_fingerprint, match_id, dataset_fingerprint,
                analytics_schema_version, analytics_rule_version, analytics_config_hash,
                config, availability, summary, row_counts, warnings,
                trade_window_mode, trade_window_requested_ticks,
                trade_window_requested_seconds, trade_window_resolved_ticks,
                trade_window_tickrate, trade_window_tickrate_source,
                trade_window_resolution_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                analytics.analytics_fingerprint,
                analytics.match_id,
                analytics.dataset_fingerprint,
                analytics.analytics_schema_version,
                analytics.analytics_rule_version,
                analytics.analytics_config_hash,
                canonical_json(analytics.config.model_dump(mode="json")),
                canonical_json(analytics.availability.model_dump(mode="json")),
                canonical_json(analytics.summary.model_dump(mode="json")),
                canonical_json(counts),
                canonical_json(list(analytics.warnings)),
                analytics.config.trade_window.mode.value,
                analytics.config.trade_window.requested_ticks,
                analytics.config.trade_window.requested_seconds,
                analytics.config.trade_window.resolved_ticks,
                analytics.config.trade_window.tickrate,
                analytics.config.trade_window.tickrate_source,
                analytics.config.trade_window.resolution_source.value,
            ],
        )
        for table, models in (
            ("player_round_analytics", analytics.player_rounds),
            ("player_match_analytics", analytics.player_matches),
            ("team_round_analytics", analytics.team_rounds),
            ("team_match_analytics", analytics.team_matches),
            ("opening_duels", analytics.opening_duels),
            ("trade_events", analytics.trade_events),
            ("man_advantage_transitions", analytics.man_advantage_transitions),
        ):
            self._batch_insert(connection, table, analytics.analytics_fingerprint, models)
        issue_rows = []
        for index, issue in enumerate(analytics.validation_issues):
            row = issue.model_dump(mode="json")
            row.update(
                {
                    "analytics_fingerprint": analytics.analytics_fingerprint,
                    "issue_index": index,
                    "match_id": analytics.match_id,
                    "evidence": canonical_json(row["evidence"]),
                }
            )
            issue_rows.append(row)
        self._batch_rows(connection, "analytics_validation_issues", issue_rows)

    @staticmethod
    def _batch_insert(
        connection: duckdb.DuckDBPyConnection,
        table: str,
        fingerprint: str,
        models: Sequence[BaseModel],
    ) -> None:
        rows = [
            {"analytics_fingerprint": fingerprint, **model.model_dump(mode="json")}
            for model in models
        ]
        DuckDBAnalyticsRepository._batch_rows(connection, table, rows)

    @staticmethod
    def _batch_rows(
        connection: duckdb.DuckDBPyConnection,
        table: str,
        rows: list[dict[str, object]],
    ) -> None:
        if not rows:
            return
        relation = f"analytics_batch_{table}"
        frame = pl.DataFrame(rows, strict=False)
        connection.register(relation, frame)
        try:
            connection.execute(f'INSERT INTO "{table}" BY NAME SELECT * FROM "{relation}"')
        finally:
            connection.unregister(relation)

    def _model_rows(
        self,
        match_id: UUID,
        table: str,
        model: type[_T],
        order_by: str,
    ) -> tuple[_T, ...]:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return ()
        return self._model_rows_for_fingerprint(fingerprint, table, model, order_by, None)

    def _model_rows_for_fingerprint(
        self,
        fingerprint: str,
        table: str,
        model: type[_T],
        order_by: str,
        round_number: int | None,
    ) -> tuple[_T, ...]:
        where = "analytics_fingerprint = ?"
        parameters: list[object] = [fingerprint]
        if round_number is not None:
            where += " AND round_number = ?"
            parameters.append(round_number)
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            rows = _fetch_all(
                connection,
                f'SELECT * EXCLUDE (analytics_fingerprint) FROM "{table}" '
                f"WHERE {where} ORDER BY {order_by}",
                parameters,
            )
        if model is TradeEvent:
            rows = tuple(_safe_trade_time_row(row) for row in rows)
        return tuple(model.model_validate(row) for row in rows)

    def _latest_fingerprint(self, match_id: UUID) -> str | None:
        self.initialize()
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            row = connection.execute(
                """
                SELECT analytics_fingerprint FROM analytics_runs WHERE match_id = ?
                ORDER BY created_at DESC, analytics_fingerprint DESC LIMIT 1
                """,
                [match_id],
            ).fetchone()
        return str(row[0]) if row else None

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, fingerprint: str) -> dict[str, int]:
        result = {"analytics_runs": 1}
        for table in _COUNT_TABLES:
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE analytics_fingerprint = ?',
                [fingerprint],
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result

    @staticmethod
    def _delete_fingerprint(connection: duckdb.DuckDBPyConnection, fingerprint: str) -> None:
        for table in _CHILD_TABLES:
            connection.execute(
                f'DELETE FROM "{table}" WHERE analytics_fingerprint = ?', [fingerprint]
            )
        connection.execute(
            "DELETE FROM analytics_runs WHERE analytics_fingerprint = ?", [fingerprint]
        )


def _row_counts(analytics: MatchAnalytics) -> dict[str, int]:
    return {
        "analytics_runs": 1,
        "player_round_analytics": len(analytics.player_rounds),
        "player_match_analytics": len(analytics.player_matches),
        "team_round_analytics": len(analytics.team_rounds),
        "team_match_analytics": len(analytics.team_matches),
        "opening_duels": len(analytics.opening_duels),
        "trade_events": len(analytics.trade_events),
        "man_advantage_transitions": len(analytics.man_advantage_transitions),
        "analytics_validation_issues": len(analytics.validation_issues),
    }


def _fetch_one(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object],
) -> dict[str, Any] | None:
    cursor = connection.execute(query, parameters)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [item[0] for item in cursor.description]
    return dict(zip(columns, row, strict=True))


def _fetch_all(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object],
) -> tuple[dict[str, Any], ...]:
    cursor = connection.execute(query, parameters)
    columns = [item[0] for item in cursor.description]
    return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())


def _json_value(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _safe_trade_time_row(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("seconds_delta_status") != "legacy_ambiguous":
        return row
    return {**row, "seconds_delta": None, "seconds_delta_source": None}


def _legacy_availability(value: dict[str, Any]) -> AnalyticsAvailabilitySummary:
    trade_value = value.get("trade_metrics", {})
    population = int(trade_value.get("population", 0))
    covered = int(trade_value.get("covered", 0))
    status = AnalyticsAvailability.PARTIAL if covered > 0 else AnalyticsAvailability.UNAVAILABLE
    legacy_trade = TradePolicyCapability(
        status=status,
        reasons=(AnalyticsUnavailableReason.LEGACY_AMBIGUOUS,),
        population=population,
        covered=covered,
        trade_window_mode=TradeWindowMode.LEGACY_AMBIGUOUS,
        resolution_source=TradeWindowResolutionSource.LEGACY_AMBIGUOUS,
    )
    adapted = dict(value)
    adapted["trade_metrics"] = legacy_trade
    adapted["kast_metrics"] = legacy_trade
    return AnalyticsAvailabilitySummary.model_validate(adapted)


def _legacy_summary(value: dict[str, Any]) -> AnalyticsSummary:
    return AnalyticsSummary(
        rounds=value["rounds"],
        players=value["players"],
        teams=value["teams"],
        valid_enemy_kills=value["valid_enemy_kills"],
        excluded_teamkills=value["excluded_teamkills"],
        excluded_suicides=value["excluded_suicides"],
        excluded_world_kills=value["excluded_world_kills"],
        opening_duels=value["opening_duels"],
        trade_events=value["trade_events"],
        trade_window_mode=TradeWindowMode.LEGACY_AMBIGUOUS,
        trade_window_resolution_source=TradeWindowResolutionSource.LEGACY_AMBIGUOUS,
        rounds_with_plant=value["rounds_with_plant"],
        winner_covered_rounds=value["winner_covered_rounds"],
    )
