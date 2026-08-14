"""Dependency-aware cleanup for immutable Stage 8.5 pattern runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb

from stratweb.adapters.persistence._analysis_cascade import (
    delete_analysis_for_pattern_runs,
)


def delete_pattern_runs(
    connection: duckdb.DuckDBPyConnection,
    *,
    pattern_run_ids: Sequence[Any],
) -> None:
    if not pattern_run_ids:
        return
    delete_analysis_for_pattern_runs(connection, pattern_run_ids)
    placeholders = ", ".join("?" for _ in pattern_run_ids)
    parameters = list(pattern_run_ids)
    for table in (
        "pattern_round_exclusions",
        "pattern_round_evidence",
        "cross_match_patterns",
        "pattern_run_inputs",
        "cross_match_pattern_runs",
    ):
        connection.execute(
            f"DELETE FROM {table} WHERE pattern_run_id IN ({placeholders})",
            parameters,
        )


def delete_patterns_for_feature_runs(
    connection: duckdb.DuckDBPyConnection,
    feature_run_ids: Sequence[Any],
) -> None:
    if not feature_run_ids:
        return
    placeholders = ", ".join("?" for _ in feature_run_ids)
    rows = connection.execute(
        f"SELECT DISTINCT pattern_run_id FROM pattern_run_inputs "
        f"WHERE feature_run_id IN ({placeholders})",
        list(feature_run_ids),
    ).fetchall()
    delete_pattern_runs(connection, pattern_run_ids=[row[0] for row in rows])


def delete_patterns_for_matches(
    connection: duckdb.DuckDBPyConnection,
    match_ids: Sequence[Any],
) -> None:
    if not match_ids:
        return
    placeholders = ", ".join("?" for _ in match_ids)
    rows = connection.execute(
        f"SELECT DISTINCT pattern_run_id FROM pattern_run_inputs "
        f"WHERE match_id IN ({placeholders})",
        list(match_ids),
    ).fetchall()
    delete_pattern_runs(connection, pattern_run_ids=[row[0] for row in rows])


def delete_patterns_for_profile(
    connection: duckdb.DuckDBPyConnection,
    profile_id: Any,
) -> None:
    rows = connection.execute(
        "SELECT pattern_run_id FROM cross_match_pattern_runs WHERE profile_id = ?",
        [profile_id],
    ).fetchall()
    delete_pattern_runs(connection, pattern_run_ids=[row[0] for row in rows])


__all__ = [
    "delete_pattern_runs",
    "delete_patterns_for_feature_runs",
    "delete_patterns_for_matches",
    "delete_patterns_for_profile",
]
