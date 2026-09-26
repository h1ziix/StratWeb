"""Bounded columnar inserts on the caller's existing transaction and connection."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import duckdb
import polars as pl

_BATCH_SIZE = 16_384


def insert_rows(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
) -> None:
    """Keep SQL constraints/casts authoritative; never commit a partial batch."""
    if not rows:
        return
    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    relation = f"_stratweb_bulk_{table}"
    for start in range(0, len(rows), _BATCH_SIZE):
        values = [
            [str(value) if isinstance(value, UUID) else value for value in row]
            for row in rows[start : start + _BATCH_SIZE]
        ]
        frame = pl.DataFrame(values, schema=list(columns), orient="row", infer_schema_length=None)
        connection.register(relation, frame)
        try:
            connection.execute(
                f'INSERT INTO "{table}" ({quoted_columns}) '
                f'SELECT {quoted_columns} FROM "{relation}"'
            )
        finally:
            connection.unregister(relation)
