"""Child-first cleanup for Stage 8.6 analysis runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb

from stratweb.adapters.persistence._counter_strategy_cascade import (
    delete_strategies_for_analysis_runs,
)


def delete_analysis_runs(
    connection: duckdb.DuckDBPyConnection, *, analysis_run_ids: Sequence[Any]
) -> None:
    if not analysis_run_ids or not _table_exists(connection, "analysis_runs"):
        return
    placeholders = ", ".join("?" for _ in analysis_run_ids)
    parameters = list(analysis_run_ids)
    delete_strategies_for_analysis_runs(connection, analysis_run_ids)
    for table in (
        "finding_evidence_references",
        "analysis_findings",
        "analysis_run_inputs",
        "analysis_runs",
    ):
        connection.execute(
            f"DELETE FROM {table} WHERE analysis_run_id IN ({placeholders})",
            parameters,
        )


def delete_analysis_for_pattern_runs(
    connection: duckdb.DuckDBPyConnection, pattern_run_ids: Sequence[Any]
) -> None:
    if not pattern_run_ids or not _table_exists(connection, "analysis_runs"):
        return
    placeholders = ", ".join("?" for _ in pattern_run_ids)
    rows = connection.execute(
        f"SELECT analysis_run_id FROM analysis_runs "
        f"WHERE source_pattern_run_id IN ({placeholders})",
        list(pattern_run_ids),
    ).fetchall()
    delete_analysis_runs(connection, analysis_run_ids=[row[0] for row in rows])


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
    ).fetchone()
    return row is not None


__all__ = ["delete_analysis_for_pattern_runs", "delete_analysis_runs"]
