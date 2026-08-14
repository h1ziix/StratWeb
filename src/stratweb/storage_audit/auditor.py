"""DuckDB 1.5 read-only storage audit and bounded representative benchmarks."""

from __future__ import annotations

import math
import statistics
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from .models import (
    DatabaseStorageMetrics,
    QueryBenchmark,
    RunTableAudit,
    ScaleProjection,
    StorageAuditConfig,
    StorageAuditReport,
    StorageAuditSummary,
    StorageRelationshipAudit,
    StorageRelationshipKind,
    TableStorageMetrics,
)


class StorageAuditError(ValueError):
    """The requested database cannot be audited safely."""


_RUN_TABLES = (
    ("analytics_runs", "match_id"),
    ("temporal_runs", "match_id"),
    ("spatial_runs", "match_id"),
    ("zone_assignment_runs", "match_id"),
    ("economy_runs", "match_id"),
    ("round_feature_runs", "match_id"),
    ("cross_match_pattern_runs", "profile_id"),
    ("analysis_runs", "profile_id"),
    ("counter_strategy_runs", "profile_id"),
)


class DuckDBStorageAuditor:
    def audit(
        self,
        database_path: Path,
        *,
        config: StorageAuditConfig | None = None,
    ) -> StorageAuditReport:
        selected = config or StorageAuditConfig()
        path = database_path.expanduser().resolve()
        if not path.is_file():
            raise StorageAuditError(f"DuckDB file does not exist: {path}")
        try:
            connection = duckdb.connect(str(path), read_only=True)
        except duckdb.Error as exc:
            raise StorageAuditError(f"Could not open DuckDB read-only: {path.name}") from exc
        try:
            return self._audit_connection(connection, path, selected)
        except duckdb.Error as exc:
            raise StorageAuditError(f"DuckDB storage audit failed: {exc}") from exc
        finally:
            connection.close()

    def _audit_connection(
        self,
        connection: duckdb.DuckDBPyConnection,
        path: Path,
        config: StorageAuditConfig,
    ) -> StorageAuditReport:
        version = str(_fetchone(connection, "PRAGMA version")[0])
        database_row = _fetchone(connection, "PRAGMA database_size")
        block_size = int(database_row[2])
        used_blocks = int(database_row[4])
        table_rows = connection.execute(
            """
            SELECT schema_name, table_name, estimated_size, column_count, index_count
            FROM duckdb_tables()
            WHERE NOT internal AND NOT temporary
            ORDER BY schema_name, table_name
            """
        ).fetchall()
        payload_tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT table_name FROM duckdb_columns()
                WHERE NOT internal AND column_name = 'payload'
                """
            ).fetchall()
        }

        table_blocks: dict[str, set[int]] = {}
        storage_rows: dict[str, list[tuple[Any, ...]]] = {}
        for row in table_rows:
            table_name = str(row[1])
            segments = connection.execute(
                """
                SELECT compression, block_id, additional_block_ids
                FROM pragma_storage_info(?)
                """,
                [table_name],
            ).fetchall()
            storage_rows[table_name] = segments
            blocks: set[int] = set()
            for _compression, block_id, additional in segments:
                if block_id is not None and int(block_id) >= 0:
                    blocks.add(int(block_id))
                if additional:
                    blocks.update(int(item) for item in additional if int(item) >= 0)
            table_blocks[table_name] = blocks

        block_references = Counter(block for blocks in table_blocks.values() for block in blocks)
        unique_table_blocks = set(block_references)
        table_metrics: list[TableStorageMetrics] = []
        for schema_name, table_name_raw, estimated, columns, indexes in table_rows:
            table_name = str(table_name_raw)
            segments = storage_rows[table_name]
            blocks = table_blocks[table_name]
            compression = Counter(str(row[0]) for row in segments)
            exact_rows = (
                int(
                    _fetchone(
                        connection,
                        f"SELECT count(*) FROM {_identifier(str(schema_name))}."
                        f"{_identifier(table_name)}",
                    )[0]
                )
                if config.exact_row_counts
                else None
            )
            payload_bytes = (
                _payload_bytes(connection, str(schema_name), table_name)
                if config.scan_json_payload_bytes and table_name in payload_tables
                else None
            )
            exclusive = sum(block_references[item] == 1 for item in blocks)
            shared = len(blocks) - exclusive
            table_metrics.append(
                TableStorageMetrics(
                    schema_name=str(schema_name),
                    table_name=table_name,
                    estimated_rows=max(0, int(estimated)),
                    exact_rows=exact_rows,
                    column_count=int(columns),
                    index_count=int(indexes),
                    storage_segments=len(segments),
                    compression_segments=dict(sorted(compression.items())),
                    referenced_blocks=len(blocks),
                    exclusive_blocks=exclusive,
                    shared_blocks=shared,
                    approximate_referenced_bytes=len(blocks) * block_size,
                    json_payload_bytes=payload_bytes,
                )
            )
        table_metrics.sort(
            key=lambda item: (
                -item.approximate_referenced_bytes,
                -(item.exact_rows if item.exact_rows is not None else item.estimated_rows),
                item.table_name,
            )
        )
        table_names = {item.table_name for item in table_metrics}
        relationships = _relationships(
            connection,
            table_names,
            scan_payload=config.scan_json_payload_bytes,
        )
        run_tables = _run_tables(connection, table_names)
        benchmarks = (
            _benchmarks(connection, table_names, config.benchmark_iterations)
            if config.run_benchmarks
            else ()
        )
        match_count = _table_count(connection, "matches") if "matches" in table_names else 0
        projections = _projections(path.stat().st_size, match_count, config)
        secondary_index_count = int(
            _fetchone(connection, "SELECT count(*) FROM duckdb_indexes()")[0]
        )
        reported_index_count = sum(item.index_count for item in table_metrics)
        exact_total = (
            sum(item.exact_rows or 0 for item in table_metrics) if config.exact_row_counts else None
        )
        payload_total = (
            sum(item.json_payload_bytes or 0 for item in table_metrics)
            if config.scan_json_payload_bytes
            else None
        )
        warnings = (
            "Per-table block bytes are approximate and are not additive when DuckDB blocks "
            "are shared.",
            "Unattributed used blocks can contain indexes, metadata or storage not exposed "
            "by table storage_info.",
            "Timing benchmarks are observations from this machine, not deterministic analytics.",
            "Scale projections are naive linear estimates and are not capacity guarantees.",
            "Additional immutable runs are not deletion-safe until compatibility keys and "
            "evidence references are audited.",
        )
        return StorageAuditReport(
            observed_at=datetime.now(UTC),
            duckdb_version=version,
            config=config,
            database=DatabaseStorageMetrics(
                file_name=path.name,
                file_size_bytes=path.stat().st_size,
                database_size_text=str(database_row[1]),
                wal_size_text=str(database_row[6]),
                block_size_bytes=block_size,
                total_blocks=int(database_row[3]),
                used_blocks=used_blocks,
                free_blocks=int(database_row[5]),
                used_block_bytes=used_blocks * block_size,
                free_block_bytes=int(database_row[5]) * block_size,
                table_referenced_unique_blocks=len(unique_table_blocks),
                unattributed_used_blocks=max(0, used_blocks - len(unique_table_blocks)),
            ),
            summary=StorageAuditSummary(
                tables=len(table_metrics),
                secondary_indexes=secondary_index_count,
                reported_indexes_including_constraints=reported_index_count,
                matches=match_count,
                exact_rows=exact_total,
                json_payload_bytes=payload_total,
                relationships_available=sum(item.available for item in relationships),
                benchmark_queries_available=sum(item.available for item in benchmarks),
            ),
            tables=tuple(table_metrics),
            relationships=relationships,
            run_tables=run_tables,
            benchmarks=benchmarks,
            projections=projections,
            warnings=warnings,
        )


def _payload_bytes(
    connection: duckdb.DuckDBPyConnection,
    schema_name: str,
    table_name: str,
) -> int:
    value = _fetchone(
        connection,
        f"SELECT coalesce(sum(octet_length(encode(CAST(payload AS VARCHAR)))), 0) "
        f"FROM {_identifier(schema_name)}.{_identifier(table_name)}",
    )[0]
    return int(value)


def _relationships(
    connection: duckdb.DuckDBPyConnection,
    table_names: set[str],
    *,
    scan_payload: bool,
) -> tuple[StorageRelationshipAudit, ...]:
    definitions = (
        (
            "spatial_snapshot_query_mirror",
            StorageRelationshipKind.MIRROR,
            "spatial_snapshots",
            "spatial_snapshot_query_rows",
            ("spatial_run_id", "snapshot_id"),
            (
                "spatial_run_id",
                "snapshot_id",
                "match_id",
                "round_number",
                "tick",
                "participant_id",
                "physical_team_id",
                "alive",
                "has_bomb",
                "x",
                "position_authority",
                "tick_lookup_key",
                "player_path_key",
                "payload",
            ),
            True,
        ),
        (
            "bomb_position_query_mirror",
            StorageRelationshipKind.MIRROR,
            "bomb_position_snapshots",
            "bomb_position_query_rows",
            ("spatial_run_id", "snapshot_id"),
            (
                "spatial_run_id",
                "snapshot_id",
                "match_id",
                "round_number",
                "tick",
                "tick_lookup_key",
                "payload",
            ),
            True,
        ),
        (
            "zone_assignment_from_spatial_snapshot",
            StorageRelationshipKind.DERIVED,
            "spatial_snapshot_query_rows",
            "zone_assignments",
            ("spatial_run_id", "snapshot_id=spatial_snapshot_id"),
            ("spatial_run_id", "match_id", "round_number", "tick", "participant_id"),
            False,
        ),
    )
    result: list[StorageRelationshipAudit] = []
    for relationship_id, kind, source, target, keys, duplicated, compare_payload in definitions:
        if source not in table_names or target not in table_names:
            result.append(
                StorageRelationshipAudit(
                    relationship_id=relationship_id,
                    kind=kind,
                    source_table=source,
                    target_table=target,
                    available=False,
                    limitations=("required_table_missing",),
                )
            )
            continue
        join_parts = []
        for key in keys:
            if "=" in key:
                left, right = key.split("=", 1)
            else:
                left = right = key
            join_parts.append(f"s.{_identifier(left)} = t.{_identifier(right)}")
        join_sql = " AND ".join(join_parts)
        source_rows = _table_count(connection, source)
        target_rows = _table_count(connection, target)
        matched_source = int(
            _fetchone(
                connection,
                f"SELECT count(*) FROM {_identifier(source)} s WHERE EXISTS ("
                f"SELECT 1 FROM {_identifier(target)} t WHERE {join_sql})",
            )[0]
        )
        reverse_join_sql = join_sql.replace("s.", "source.").replace("t.", "target.")
        matched_target = int(
            _fetchone(
                connection,
                f"SELECT count(*) FROM {_identifier(target)} target WHERE EXISTS ("
                f"SELECT 1 FROM {_identifier(source)} source WHERE {reverse_join_sql})",
            )[0]
        )
        payload_equal: int | None = None
        duplicated_payload_bytes: int | None = None
        limitations: list[str] = []
        if compare_payload and scan_payload:
            payload_equal, duplicated_payload_bytes = _fetchone(
                connection,
                f"""
                SELECT
                    count(*) FILTER (WHERE CAST(s.payload AS VARCHAR) = CAST(t.payload AS VARCHAR)),
                    coalesce(sum(
                        CASE WHEN CAST(s.payload AS VARCHAR) = CAST(t.payload AS VARCHAR)
                        THEN octet_length(encode(CAST(t.payload AS VARCHAR))) ELSE 0 END
                    ), 0)
                FROM {_identifier(source)} s
                JOIN {_identifier(target)} t ON {join_sql}
                """,
            )
            payload_equal = int(payload_equal)
            duplicated_payload_bytes = int(duplicated_payload_bytes)
        elif compare_payload:
            limitations.append("payload_equality_not_scanned")
        result.append(
            StorageRelationshipAudit(
                relationship_id=relationship_id,
                kind=kind,
                source_table=source,
                target_table=target,
                available=True,
                source_rows=source_rows,
                target_rows=target_rows,
                matched_rows=matched_source,
                source_only_rows=max(0, source_rows - matched_source),
                target_only_rows=max(0, target_rows - matched_target),
                source_coverage=(matched_source / source_rows if source_rows else None),
                payload_equal_rows=payload_equal,
                duplicated_payload_bytes=duplicated_payload_bytes,
                duplicated_columns=duplicated,
                limitations=tuple(limitations),
            )
        )
    return tuple(result)


def _run_tables(
    connection: duckdb.DuckDBPyConnection,
    table_names: set[str],
) -> tuple[RunTableAudit, ...]:
    result: list[RunTableAudit] = []
    for table, scope in _RUN_TABLES:
        if table not in table_names:
            continue
        total, distinct_scopes = _fetchone(
            connection,
            f"SELECT count(*), count(DISTINCT {_identifier(scope)}) FROM {_identifier(table)}",
        )
        multiple = _fetchone(
            connection,
            f"SELECT count(*) FROM (SELECT {_identifier(scope)} FROM {_identifier(table)} "
            f"GROUP BY {_identifier(scope)} HAVING count(*) > 1)",
        )[0]
        result.append(
            RunTableAudit(
                table_name=table,
                scope_column=scope,
                total_runs=int(total),
                distinct_scopes=int(distinct_scopes),
                scopes_with_multiple_runs=int(multiple),
                additional_runs_within_scope=max(0, int(total) - int(distinct_scopes)),
                limitation=(
                    "Multiple runs can represent different schema, rule or config versions; "
                    "this count is not a deletion recommendation."
                ),
            )
        )
    return tuple(result)


def _benchmarks(
    connection: duckdb.DuckDBPyConnection,
    table_names: set[str],
    iterations: int,
) -> tuple[QueryBenchmark, ...]:
    queries: list[tuple[str, str, str, Sequence[object]] | None] = []
    queries.append(
        (
            "recent_matches",
            "recent imported matches ordered by imported_at",
            (
                "SELECT match_id, map_name, round_count FROM matches "
                "ORDER BY imported_at DESC LIMIT 50"
            ),
            (),
        )
        if "matches" in table_names
        else None
    )
    queries.append(
        _keyed_query(
            connection,
            table_names,
            query_id="spatial_tick_lookup",
            table="spatial_snapshot_query_rows",
            key="tick_lookup_key",
            order="participant_id",
        )
    )
    queries.append(
        _keyed_query(
            connection,
            table_names,
            query_id="spatial_player_path",
            table="spatial_snapshot_query_rows",
            key="player_path_key",
            order="tick",
        )
    )
    queries.append(
        _round_query(
            connection,
            table_names,
            query_id="temporal_round_events",
            table="temporal_events",
            run_column="temporal_run_id",
            order="tick, priority, event_id",
        )
    )
    queries.append(
        _round_query(
            connection,
            table_names,
            query_id="zone_round_assignments",
            table="zone_assignments",
            run_column="zone_assignment_run_id",
            order="tick, participant_id",
        )
    )
    result: list[QueryBenchmark] = []
    ids = (
        "recent_matches",
        "spatial_tick_lookup",
        "spatial_player_path",
        "temporal_round_events",
        "zone_round_assignments",
    )
    for query_id, query in zip(ids, queries, strict=True):
        if query is None:
            result.append(
                QueryBenchmark(
                    query_id=query_id,
                    query_shape="unavailable",
                    available=False,
                    iterations=0,
                    limitation="required_table_or_sample_key_missing",
                )
            )
            continue
        _, shape, sql, params = query
        result.append(_time_query(connection, query_id, shape, sql, params, iterations))
    return tuple(result)


def _keyed_query(
    connection: duckdb.DuckDBPyConnection,
    table_names: set[str],
    *,
    query_id: str,
    table: str,
    key: str,
    order: str,
) -> tuple[str, str, str, Sequence[object]] | None:
    if table not in table_names:
        return None
    sample = connection.execute(
        f"SELECT {_identifier(key)} FROM {_identifier(table)} "
        f"WHERE {_identifier(key)} IS NOT NULL LIMIT 1"
    ).fetchone()
    if sample is None:
        return None
    return (
        query_id,
        f"{table} equality lookup by {key}",
        f"SELECT payload FROM {_identifier(table)} WHERE {_identifier(key)} = ? ORDER BY {order}",
        (sample[0],),
    )


def _round_query(
    connection: duckdb.DuckDBPyConnection,
    table_names: set[str],
    *,
    query_id: str,
    table: str,
    run_column: str,
    order: str,
) -> tuple[str, str, str, Sequence[object]] | None:
    if table not in table_names:
        return None
    sample = connection.execute(
        f"SELECT {_identifier(run_column)}, round_number FROM {_identifier(table)} LIMIT 1"
    ).fetchone()
    if sample is None:
        return None
    return (
        query_id,
        f"{table} one-run one-round scan",
        f"SELECT * FROM {_identifier(table)} WHERE {_identifier(run_column)} = ? "
        f"AND round_number = ? ORDER BY {order}",
        (sample[0], sample[1]),
    )


def _time_query(
    connection: duckdb.DuckDBPyConnection,
    query_id: str,
    shape: str,
    sql: str,
    params: Sequence[object],
    iterations: int,
) -> QueryBenchmark:
    connection.execute(sql, params).fetchall()
    durations: list[float] = []
    returned_rows = 0
    for _ in range(iterations):
        started = time.perf_counter()
        rows = connection.execute(sql, params).fetchall()
        durations.append((time.perf_counter() - started) * 1000)
        returned_rows = len(rows)
    ordered = sorted(durations)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return QueryBenchmark(
        query_id=query_id,
        query_shape=shape,
        available=True,
        iterations=iterations,
        returned_rows=returned_rows,
        minimum_ms=round(min(ordered), 3),
        median_ms=round(statistics.median(ordered), 3),
        p95_ms=round(ordered[p95_index], 3),
        maximum_ms=round(max(ordered), 3),
        limitation="Warm-cache local observation; hardware and cache state affect timing.",
    )


def _projections(
    file_size: int,
    match_count: int,
    config: StorageAuditConfig,
) -> tuple[ScaleProjection, ...]:
    return tuple(
        ScaleProjection(
            match_count=target,
            projected_file_size_bytes=(
                round(file_size / match_count * target) if match_count else None
            ),
            method="naive_linear_file_size_per_imported_match",
            limitation=(
                "Includes current run history, indexes and free blocks; ignores future "
                "compression, retention and workload differences."
            ),
        )
        for target in config.projection_match_counts
    )


def _table_count(connection: duckdb.DuckDBPyConnection, table_name: str) -> int:
    return int(_fetchone(connection, f"SELECT count(*) FROM {_identifier(table_name)}")[0])


def _fetchone(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[object] = (),
) -> tuple[Any, ...]:
    row = connection.execute(sql, params).fetchone()
    if row is None:
        raise StorageAuditError("Storage audit query returned no row")
    return row


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


__all__ = ["DuckDBStorageAuditor", "StorageAuditError"]
