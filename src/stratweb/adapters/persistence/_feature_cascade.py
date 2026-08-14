"""Dependency-aware cleanup helpers for Stage 8.4 materializations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb

from stratweb.adapters.persistence._pattern_cascade import delete_patterns_for_feature_runs

_DEPENDENCY_COLUMNS = frozenset(
    {
        "analytics_fingerprint",
        "temporal_run_id",
        "spatial_run_id",
        "zone_assignment_run_id",
        "economy_run_id",
    }
)


def delete_dependent_feature_runs(
    connection: duckdb.DuckDBPyConnection,
    dependency_column: str,
    dependency_values: Sequence[Any],
) -> None:
    """Delete feature rows pinned to inputs that are about to be removed."""

    if dependency_column not in _DEPENDENCY_COLUMNS:
        raise ValueError(f"Unsupported round-feature dependency: {dependency_column}")
    if not dependency_values:
        return
    placeholders = ", ".join("?" for _ in dependency_values)
    run_rows = connection.execute(
        f"SELECT feature_run_id FROM round_feature_runs "
        f"WHERE {dependency_column} IN ({placeholders})",
        list(dependency_values),
    ).fetchall()
    run_ids = [row[0] for row in run_rows]
    if not run_ids:
        return
    delete_patterns_for_feature_runs(connection, run_ids)
    run_placeholders = ", ".join("?" for _ in run_ids)
    connection.execute(
        f"DELETE FROM round_features WHERE feature_run_id IN ({run_placeholders})",
        run_ids,
    )
    connection.execute(
        f"DELETE FROM round_feature_runs WHERE feature_run_id IN ({run_placeholders})",
        run_ids,
    )


__all__ = ["delete_dependent_feature_runs"]
