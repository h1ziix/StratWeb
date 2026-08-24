"""Dependency-aware cleanup for profile-scoped Tactical V2 runs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import duckdb


def delete_tactical_v2_runs(connection: duckdb.DuckDBPyConnection, run_ids: Sequence[Any]) -> None:
    if not run_ids or not _table_exists(connection, "tactical_v2_runs"):
        return
    placeholders = ", ".join("?" for _ in run_ids)
    for table in (
        "analyst_notes",
        "tactical_v2_evidence",
        "tactical_v2_insights",
        "tactical_v2_run_inputs",
        "tactical_v2_runs",
    ):
        if _table_exists(connection, table):
            connection.execute(
                f"DELETE FROM {table} WHERE tactical_run_id IN ({placeholders})", list(run_ids)
            )


def delete_tactical_v2_for_matches(
    connection: duckdb.DuckDBPyConnection, match_ids: Sequence[Any]
) -> None:
    if not match_ids or not _table_exists(connection, "tactical_v2_runs"):
        return
    placeholders = ", ".join("?" for _ in match_ids)
    rows = connection.execute(
        f"SELECT DISTINCT tactical_run_id FROM tactical_v2_run_inputs "
        f"WHERE match_id IN ({placeholders})",
        list(match_ids),
    ).fetchall()
    delete_tactical_v2_runs(connection, [row[0] for row in rows])


def delete_tactical_v2_for_profile(connection: duckdb.DuckDBPyConnection, profile_id: Any) -> None:
    if not _table_exists(connection, "tactical_v2_runs"):
        return
    rows = connection.execute(
        "SELECT tactical_run_id FROM tactical_v2_runs WHERE profile_id = ?", [profile_id]
    ).fetchall()
    delete_tactical_v2_runs(connection, [row[0] for row in rows])


def delete_tactical_v2_for_feature_runs(
    connection: duckdb.DuckDBPyConnection, feature_run_ids: Sequence[Any]
) -> None:
    if not feature_run_ids or not _table_exists(connection, "tactical_v2_runs"):
        return
    placeholders = ", ".join("?" for _ in feature_run_ids)
    rows = connection.execute(
        f"SELECT DISTINCT tactical_run_id FROM tactical_v2_run_inputs "
        f"WHERE feature_run_id IN ({placeholders})",
        list(feature_run_ids),
    ).fetchall()
    delete_tactical_v2_runs(connection, [row[0] for row in rows])


def _table_exists(connection: duckdb.DuckDBPyConnection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [table]
        ).fetchone()
        is not None
    )


__all__ = [
    "delete_tactical_v2_for_feature_runs",
    "delete_tactical_v2_for_matches",
    "delete_tactical_v2_for_profile",
    "delete_tactical_v2_runs",
]
