"""Child-first cleanup for Stage 8.7 counter-strategy runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb


def delete_strategy_runs(
    connection: duckdb.DuckDBPyConnection, *, strategy_run_ids: Sequence[Any]
) -> None:
    if not strategy_run_ids or not _table_exists(connection, "counter_strategy_runs"):
        return
    placeholders = ", ".join("?" for _ in strategy_run_ids)
    parameters = list(strategy_run_ids)
    for table in (
        "counter_strategy_evidence",
        "counter_strategy_recommendations",
        "counter_strategy_skipped_findings",
        "counter_strategy_runs",
    ):
        connection.execute(
            f"DELETE FROM {table} WHERE strategy_run_id IN ({placeholders})",
            parameters,
        )


def delete_strategies_for_analysis_runs(
    connection: duckdb.DuckDBPyConnection, analysis_run_ids: Sequence[Any]
) -> None:
    if not analysis_run_ids or not _table_exists(connection, "counter_strategy_runs"):
        return
    placeholders = ", ".join("?" for _ in analysis_run_ids)
    rows = connection.execute(
        f"SELECT strategy_run_id FROM counter_strategy_runs "
        f"WHERE source_analysis_run_id IN ({placeholders})",
        list(analysis_run_ids),
    ).fetchall()
    delete_strategy_runs(connection, strategy_run_ids=[row[0] for row in rows])


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        is not None
    )


__all__ = ["delete_strategies_for_analysis_runs", "delete_strategy_runs"]
