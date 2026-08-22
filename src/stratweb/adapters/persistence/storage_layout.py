"""Shared Storage Engine V2 layout identifiers and connection helpers."""

from __future__ import annotations

import duckdb

STORAGE_LAYOUT_SCHEMA_VERSION = "2.0.0"
STORAGE_LAYOUT_V1 = "legacy_payload_mirrors_v1"
STORAGE_LAYOUT_V2 = "canonical_key_indexes_v2"


def active_storage_layout(connection: duckdb.DuckDBPyConnection) -> str:
    """Return V1 for pre-migration databases and the persisted layout otherwise."""

    try:
        row = connection.execute(
            "SELECT active_layout FROM storage_layout_state WHERE singleton_key = 1"
        ).fetchone()
    except duckdb.CatalogException:
        return STORAGE_LAYOUT_V1
    return str(row[0]) if row is not None else STORAGE_LAYOUT_V1


def uses_canonical_index_layout(connection: duckdb.DuckDBPyConnection) -> bool:
    return active_storage_layout(connection) == STORAGE_LAYOUT_V2


__all__ = [
    "STORAGE_LAYOUT_SCHEMA_VERSION",
    "STORAGE_LAYOUT_V1",
    "STORAGE_LAYOUT_V2",
    "active_storage_layout",
    "uses_canonical_index_layout",
]
