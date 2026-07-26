"""Shared DuckDB connection helper for adapter read paths."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from stratweb.exceptions import PersistenceError


@contextmanager
def read_connection(database_path: Path, subsystem: str) -> Iterator[duckdb.DuckDBPyConnection]:
    """Open a query connection and translate driver errors to PersistenceError.

    read_only=False matches every other connection in the process: DuckDB
    requires a uniform configuration for all connections to the same file.
    """

    try:
        with duckdb.connect(str(database_path), read_only=False) as connection:
            yield connection
    except duckdb.Error as exc:
        raise PersistenceError(f"Could not read {subsystem} data.") from exc
