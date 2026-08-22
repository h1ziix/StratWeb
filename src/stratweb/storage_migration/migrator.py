"""Verified and reversible migration from payload mirrors to canonical indexes."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import duckdb

from stratweb.adapters.persistence.storage_layout import (
    STORAGE_LAYOUT_SCHEMA_VERSION,
    STORAGE_LAYOUT_V1,
    STORAGE_LAYOUT_V2,
    active_storage_layout,
)

from .models import (
    BackupVerification,
    LookupBenchmark,
    LookupParity,
    StorageLayoutCounts,
    StorageLayoutStatus,
    StorageMigrationConfig,
    StorageMigrationReport,
    StorageRollbackReport,
)


class StorageMigrationError(ValueError):
    """The requested storage transition cannot be proven safe."""


class DuckDBStorageMigrator:
    def status(self, database_path: Path) -> StorageLayoutStatus:
        path = _existing_database(database_path)
        try:
            connection = duckdb.connect(str(path), read_only=True)
        except duckdb.Error as exc:
            raise StorageMigrationError(f"Could not open DuckDB read-only: {path.name}") from exc
        try:
            return self._status_connection(connection)
        finally:
            connection.close()

    def migrate(
        self,
        database_path: Path,
        backup_path: Path,
        *,
        config: StorageMigrationConfig | None = None,
    ) -> StorageMigrationReport:
        selected = config or StorageMigrationConfig()
        source = _existing_database(database_path)
        backup = backup_path.expanduser().resolve()
        if source == backup:
            raise StorageMigrationError("Backup path must differ from the source database.")
        initial = self.status(source)
        if initial.active_layout == STORAGE_LAYOUT_V2:
            raise StorageMigrationError("Storage Engine V2 is already active.")

        started_at = datetime.now(UTC)
        source_size_before = source.stat().st_size
        verification = self._create_verified_backup(source, backup)

        self._install_v2_schema(source)

        migration_id = uuid4()
        try:
            with duckdb.connect(str(source)) as connection:
                version_row = connection.execute("PRAGMA version").fetchone()
                if version_row is None:  # pragma: no cover - DuckDB contract
                    raise StorageMigrationError("DuckDB did not report its version.")
                version = str(version_row[0])
                connection.execute(
                    """
                    INSERT INTO storage_layout_migration_runs (
                        migration_id, from_layout, to_layout, status, backup_sha256,
                        source_size_before
                    ) VALUES (?, ?, ?, 'backfilling', ?, ?)
                    """,
                    [
                        migration_id,
                        STORAGE_LAYOUT_V1,
                        STORAGE_LAYOUT_V2,
                        verification.backup_sha256,
                        source_size_before,
                    ],
                )
                parity = self._v2_parity(connection)
                connection.execute(
                    """
                    UPDATE storage_layout_state
                    SET status = 'shadow_ready', updated_at = current_timestamp,
                        details = ?
                    WHERE singleton_key = 1
                    """,
                    [_json_payload({"migration_id": str(migration_id), "parity": parity})],
                )
                benchmarks = self._benchmarks(connection, selected)
                parity_passed = all(item.passed for item in parity)
                benchmarks_passed = all(item.passed for item in benchmarks)
                activated = parity_passed and benchmarks_passed
                final_state = "active" if activated else "shadow_ready"
                if activated:
                    connection.execute(
                        """
                        UPDATE storage_layout_state
                        SET active_layout = ?, status = 'active',
                            activated_at = current_timestamp, updated_at = current_timestamp,
                            details = ?
                        WHERE singleton_key = 1
                        """,
                        [
                            STORAGE_LAYOUT_V2,
                            _json_payload(
                                {
                                    "migration_id": str(migration_id),
                                    "parity": parity,
                                    "benchmarks": benchmarks,
                                }
                            ),
                        ],
                    )
                source_size_after = source.stat().st_size
                connection.execute(
                    """
                    UPDATE storage_layout_migration_runs
                    SET status = ?, source_size_after = ?, parity = ?, benchmarks = ?,
                        completed_at = current_timestamp
                    WHERE migration_id = ?
                    """,
                    [
                        final_state,
                        source_size_after,
                        _json_payload(parity),
                        _json_payload(benchmarks),
                        migration_id,
                    ],
                )
                status = self._status_connection(connection)
        except duckdb.Error as exc:
            self._record_failure(source, migration_id, str(exc))
            raise StorageMigrationError(f"Storage migration failed: {exc}") from exc

        warnings = [
            "Legacy payload mirror tables were retained for rollback; "
            "no disk reclamation was performed."
        ]
        if not activated:
            warnings.append(
                "V2 was not activated because parity or the explicit latency budget failed."
            )
        return StorageMigrationReport(
            migration_id=str(migration_id),
            started_at=started_at,
            completed_at=datetime.now(UTC),
            duckdb_version=version,
            source_file_name=source.name,
            source_size_before=source_size_before,
            source_size_after=source.stat().st_size,
            backup=verification,
            config=selected,
            parity=parity,
            benchmarks=benchmarks,
            activated=activated,
            status=status,
            warnings=tuple(warnings),
        )

    def restore_to_new_database(
        self, backup_path: Path, destination_path: Path
    ) -> BackupVerification:
        """Restore a verified backup into a new file; existing targets are never replaced."""

        backup = _existing_database(backup_path)
        destination = destination_path.expanduser().resolve()
        if backup == destination:
            raise StorageMigrationError("Restore destination must differ from the backup.")
        return self._create_verified_backup(backup, destination)

    def rollback(self, database_path: Path) -> StorageRollbackReport:
        path = _existing_database(database_path)
        initial = self.status(path)
        if not initial.v2_schema_available:
            raise StorageMigrationError("The V2 shadow schema is not installed.")
        if initial.active_layout != STORAGE_LAYOUT_V2:
            raise StorageMigrationError("Storage Engine V2 is not active.")
        try:
            with duckdb.connect(str(path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    before_spatial = _count(connection, "spatial_snapshot_query_rows")
                    before_bomb = _count(connection, "bomb_position_query_rows")
                    connection.execute(
                        """
                        INSERT INTO spatial_snapshot_query_rows
                        SELECT canonical.spatial_run_id, canonical.snapshot_id,
                               canonical.round_number, canonical.tick,
                               canonical.participant_id, canonical.physical_team_id,
                               canonical.alive, canonical.has_bomb, canonical.x,
                               canonical.position_authority, canonical.tick_lookup_key,
                               canonical.player_path_key, canonical.payload, canonical.match_id
                        FROM spatial_snapshots AS canonical
                        LEFT JOIN spatial_snapshot_query_rows AS legacy
                          USING (spatial_run_id, snapshot_id)
                        WHERE legacy.snapshot_id IS NULL
                        """
                    )
                    connection.execute(
                        """
                        INSERT INTO bomb_position_query_rows
                        SELECT canonical.spatial_run_id, canonical.snapshot_id,
                               canonical.round_number, canonical.tick,
                               canonical.tick_lookup_key, canonical.payload, canonical.match_id
                        FROM bomb_position_snapshots AS canonical
                        LEFT JOIN bomb_position_query_rows AS legacy
                          USING (spatial_run_id, snapshot_id)
                        WHERE legacy.snapshot_id IS NULL
                        """
                    )
                    parity = self._legacy_parity(connection)
                    if not all(item.passed for item in parity):
                        raise StorageMigrationError(
                            "Legacy payload parity failed; rollback aborted."
                        )
                    connection.execute(
                        """
                        UPDATE storage_layout_state
                        SET active_layout = ?, status = 'rolled_back',
                            activated_at = NULL, updated_at = current_timestamp, details = ?
                        WHERE singleton_key = 1
                        """,
                        [STORAGE_LAYOUT_V1, _json_payload({"rollback_parity": parity})],
                    )
                    connection.execute(
                        """
                        UPDATE storage_layout_migration_runs SET status = 'rolled_back'
                        WHERE migration_id = (
                            SELECT migration_id FROM storage_layout_migration_runs
                            ORDER BY started_at DESC, migration_id DESC LIMIT 1
                        )
                        """
                    )
                    restored_spatial = (
                        _count(connection, "spatial_snapshot_query_rows") - before_spatial
                    )
                    restored_bomb = _count(connection, "bomb_position_query_rows") - before_bomb
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
                status = self._status_connection(connection)
        except StorageMigrationError:
            raise
        except duckdb.Error as exc:
            raise StorageMigrationError(f"Storage rollback failed: {exc}") from exc
        return StorageRollbackReport(
            completed_at=datetime.now(UTC),
            restored_spatial_rows=restored_spatial,
            restored_bomb_rows=restored_bomb,
            parity=parity,
            status=status,
            warnings=("V2 indexes were retained; rollback does not delete data.",),
        )

    def _create_verified_backup(self, source: Path, backup: Path) -> BackupVerification:
        if backup.exists():
            raise StorageMigrationError(f"Backup already exists: {backup}")
        backup.parent.mkdir(parents=True, exist_ok=True)
        partial = backup.with_name(f"{backup.name}.partial")
        if partial.exists():
            raise StorageMigrationError(f"Partial backup already exists: {partial}")
        connection = duckdb.connect()
        try:
            connection.execute(f"ATTACH {_literal(source)} AS source_db (READ_ONLY)")
            connection.execute(f"ATTACH {_literal(partial)} AS backup_db")
            connection.execute("COPY FROM DATABASE source_db TO backup_db")
            connection.execute("CHECKPOINT backup_db")
            connection.execute("DETACH backup_db")
            connection.execute("DETACH source_db")
        except duckdb.Error as exc:
            raise StorageMigrationError(f"Could not create DuckDB backup: {exc}") from exc
        finally:
            connection.close()
        partial.replace(backup)

        source_counts = _table_counts(source)
        backup_counts = _table_counts(backup)
        if source_counts != backup_counts:
            raise StorageMigrationError("Backup verification failed: table row counts differ.")
        migration_rows = source_counts.get("schema_migrations", 0)
        return BackupVerification(
            backup_file_name=backup.name,
            backup_sha256=_sha256(backup),
            source_size_bytes=source.stat().st_size,
            backup_size_bytes=backup.stat().st_size,
            source_tables=len(source_counts),
            verified_tables=len(backup_counts),
            verified_rows=sum(source_counts.values()),
            schema_migration_rows=migration_rows,
            verified=True,
        )

    def _v2_parity(self, connection: duckdb.DuckDBPyConnection) -> tuple[LookupParity, ...]:
        return (
            _canonical_key_parity(
                connection,
                relationship="spatial_canonical_index_keys",
                canonical_table="spatial_snapshots",
                key_predicate="tick_lookup_key IS NOT NULL AND player_path_key IS NOT NULL",
            ),
            _canonical_key_parity(
                connection,
                relationship="bomb_canonical_index_keys",
                canonical_table="bomb_position_snapshots",
                key_predicate="tick_lookup_key IS NOT NULL",
            ),
        )

    def _legacy_parity(self, connection: duckdb.DuckDBPyConnection) -> tuple[LookupParity, ...]:
        return (
            _parity(
                connection,
                relationship="spatial_snapshot_to_legacy_mirror",
                canonical_table="spatial_snapshots",
                lookup_table="spatial_snapshot_query_rows",
                field_predicate="canonical.payload IS NOT DISTINCT FROM lookup.payload",
            ),
            _parity(
                connection,
                relationship="bomb_position_to_legacy_mirror",
                canonical_table="bomb_position_snapshots",
                lookup_table="bomb_position_query_rows",
                field_predicate="canonical.payload IS NOT DISTINCT FROM lookup.payload",
            ),
        )

    def _benchmarks(
        self,
        connection: duckdb.DuckDBPyConnection,
        config: StorageMigrationConfig,
    ) -> tuple[LookupBenchmark, ...]:
        sample = connection.execute(
            """
            SELECT tick_lookup_key, player_path_key
            FROM spatial_snapshots
            ORDER BY spatial_run_id DESC, round_number, tick, participant_id LIMIT 1
            """
        ).fetchone()
        if sample is None:
            return ()
        definitions = (
            (
                "spatial_tick_lookup",
                "SELECT payload FROM spatial_snapshot_query_rows WHERE tick_lookup_key = ? "
                "ORDER BY participant_id",
                "SELECT payload FROM spatial_snapshots WHERE tick_lookup_key = ? "
                "ORDER BY participant_id",
                str(sample[0]),
            ),
            (
                "spatial_player_path",
                "SELECT payload FROM spatial_snapshot_query_rows WHERE player_path_key = ? "
                "AND x IS NOT NULL ORDER BY tick, snapshot_id",
                "SELECT payload FROM spatial_snapshots WHERE player_path_key = ? "
                "AND x IS NOT NULL ORDER BY tick, snapshot_id",
                str(sample[1]),
            ),
        )
        return tuple(
            _benchmark_pair(
                connection,
                query_id=query_id,
                legacy_sql=legacy_sql,
                v2_sql=v2_sql,
                parameter=parameter,
                config=config,
            )
            for query_id, legacy_sql, v2_sql, parameter in definitions
        )

    def _status_connection(self, connection: duckdb.DuckDBPyConnection) -> StorageLayoutStatus:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        available = "storage_layout_state" in tables
        v2_indexes = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT index_name FROM duckdb_indexes()
                WHERE index_name IN (
                    'idx_spatial_canonical_v2_tick',
                    'idx_spatial_canonical_v2_player',
                    'idx_bomb_canonical_v2_tick'
                )
                """
            ).fetchall()
        }
        layout = active_storage_layout(connection)
        status = "legacy"
        activated_at = None
        latest_id = None
        latest_status = None
        if available:
            row = connection.execute(
                """
                SELECT status, activated_at FROM storage_layout_state WHERE singleton_key = 1
                """
            ).fetchone()
            if row is not None:
                status, activated_at = str(row[0]), row[1]
            latest = connection.execute(
                """
                SELECT migration_id, status FROM storage_layout_migration_runs
                ORDER BY started_at DESC, migration_id DESC LIMIT 1
                """
            ).fetchone()
            if latest is not None:
                latest_id, latest_status = str(latest[0]), str(latest[1])
        return StorageLayoutStatus(
            schema_version=STORAGE_LAYOUT_SCHEMA_VERSION if available else "1.0.0",
            active_layout=layout,
            status=status,
            v2_schema_available=available,
            v2_index_count=len(v2_indexes),
            activated_at=activated_at,
            counts=StorageLayoutCounts(
                spatial_canonical=_count_if_exists(connection, tables, "spatial_snapshots"),
                spatial_legacy=_count_if_exists(connection, tables, "spatial_snapshot_query_rows"),
                bomb_canonical=_count_if_exists(connection, tables, "bomb_position_snapshots"),
                bomb_legacy=_count_if_exists(connection, tables, "bomb_position_query_rows"),
            ),
            latest_migration_id=latest_id,
            latest_migration_status=latest_status,
        )

    @staticmethod
    def _install_v2_schema(path: Path) -> None:
        try:
            with duckdb.connect(str(path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS storage_layout_state (
                        singleton_key INTEGER PRIMARY KEY CHECK (singleton_key = 1),
                        active_layout VARCHAR NOT NULL,
                        schema_version VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        activated_at TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                        details JSON NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO storage_layout_state
                        (singleton_key, active_layout, schema_version, status, details)
                    SELECT 1, ?, ?, 'legacy', '{}'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM storage_layout_state WHERE singleton_key = 1
                    )
                    """,
                    [STORAGE_LAYOUT_V1, STORAGE_LAYOUT_SCHEMA_VERSION],
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS storage_layout_migration_runs (
                        migration_id UUID PRIMARY KEY,
                        from_layout VARCHAR NOT NULL,
                        to_layout VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        backup_sha256 VARCHAR(64) NOT NULL,
                        source_size_before BIGINT NOT NULL,
                        source_size_after BIGINT,
                        parity JSON,
                        benchmarks JSON,
                        error_message VARCHAR,
                        started_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                        completed_at TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_spatial_canonical_v2_tick "
                    "ON spatial_snapshots(tick_lookup_key)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_spatial_canonical_v2_player "
                    "ON spatial_snapshots(player_path_key)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_bomb_canonical_v2_tick "
                    "ON bomb_position_snapshots(tick_lookup_key)"
                )
                connection.execute(
                    """
                    UPDATE storage_layout_state SET status = 'shadow_ready',
                        updated_at = current_timestamp WHERE singleton_key = 1
                    """
                )
        except duckdb.Error as exc:
            raise StorageMigrationError("Could not install the V2 canonical indexes.") from exc

    @staticmethod
    def _record_failure(path: Path, migration_id: UUID, message: str) -> None:
        try:
            with duckdb.connect(str(path)) as connection:
                connection.execute(
                    """
                    UPDATE storage_layout_migration_runs
                    SET status = 'failed', error_message = ?, completed_at = current_timestamp
                    WHERE migration_id = ?
                    """,
                    [message[:2000], migration_id],
                )
                connection.execute(
                    """
                    UPDATE storage_layout_state SET status = 'migration_failed',
                        updated_at = current_timestamp WHERE singleton_key = 1
                    """
                )
        except duckdb.Error:
            return


def _canonical_key_parity(
    connection: duckdb.DuckDBPyConnection,
    *,
    relationship: str,
    canonical_table: str,
    key_predicate: str,
) -> LookupParity:
    canonical_rows = _count(connection, canonical_table)
    resolvable_rows = _scalar_int(
        connection,
        f"SELECT count(*) FROM {canonical_table} WHERE {key_predicate}",
    )
    missing = canonical_rows - resolvable_rows
    return LookupParity(
        relationship=relationship,
        canonical_rows=canonical_rows,
        lookup_rows=resolvable_rows,
        resolved_payload_rows=resolvable_rows,
        missing_lookup_rows=missing,
        orphan_lookup_rows=0,
        field_mismatch_rows=missing,
        passed=missing == 0,
    )


def _parity(
    connection: duckdb.DuckDBPyConnection,
    *,
    relationship: str,
    canonical_table: str,
    lookup_table: str,
    field_predicate: str,
) -> LookupParity:
    canonical_rows = _count(connection, canonical_table)
    lookup_rows = _count(connection, lookup_table)
    resolved = _scalar_int(
        connection,
        f"""
            SELECT count(*) FROM {canonical_table} AS canonical
            JOIN {lookup_table} AS lookup USING (spatial_run_id, snapshot_id)
            """,
    )
    missing = _scalar_int(
        connection,
        f"""
            SELECT count(*) FROM {canonical_table} AS canonical
            LEFT JOIN {lookup_table} AS lookup USING (spatial_run_id, snapshot_id)
            WHERE lookup.snapshot_id IS NULL
            """,
    )
    orphan = _scalar_int(
        connection,
        f"""
            SELECT count(*) FROM {lookup_table} AS lookup
            LEFT JOIN {canonical_table} AS canonical USING (spatial_run_id, snapshot_id)
            WHERE canonical.snapshot_id IS NULL
            """,
    )
    mismatched = _scalar_int(
        connection,
        f"""
            SELECT count(*) FROM {canonical_table} AS canonical
            JOIN {lookup_table} AS lookup USING (spatial_run_id, snapshot_id)
            WHERE NOT ({field_predicate})
            """,
    )
    passed = (
        canonical_rows == lookup_rows == resolved
        and missing == 0
        and orphan == 0
        and mismatched == 0
    )
    return LookupParity(
        relationship=relationship,
        canonical_rows=canonical_rows,
        lookup_rows=lookup_rows,
        resolved_payload_rows=resolved,
        missing_lookup_rows=missing,
        orphan_lookup_rows=orphan,
        field_mismatch_rows=mismatched,
        passed=passed,
    )


def _benchmark_pair(
    connection: duckdb.DuckDBPyConnection,
    *,
    query_id: str,
    legacy_sql: str,
    v2_sql: str,
    parameter: str,
    config: StorageMigrationConfig,
) -> LookupBenchmark:
    connection.execute(legacy_sql, [parameter]).fetchall()
    connection.execute(v2_sql, [parameter]).fetchall()
    legacy_times: list[float] = []
    v2_times: list[float] = []
    legacy_rows: list[tuple[Any, ...]] = []
    v2_rows: list[tuple[Any, ...]] = []
    for _ in range(config.benchmark_iterations):
        start = time.perf_counter()
        legacy_rows = connection.execute(legacy_sql, [parameter]).fetchall()
        legacy_times.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        v2_rows = connection.execute(v2_sql, [parameter]).fetchall()
        v2_times.append((time.perf_counter() - start) * 1000)
    legacy_median = statistics.median(legacy_times)
    v2_median = statistics.median(v2_times)
    permitted = max(
        legacy_median * config.maximum_median_ratio,
        legacy_median + config.maximum_absolute_regression_ms,
    )
    payloads_equal = legacy_rows == v2_rows
    return LookupBenchmark(
        query_id=query_id,
        iterations=config.benchmark_iterations,
        returned_rows=len(legacy_rows),
        payloads_equal=payloads_equal,
        legacy_median_ms=legacy_median,
        v2_median_ms=v2_median,
        permitted_v2_median_ms=permitted,
        passed=payloads_equal and v2_median <= permitted,
    )


def _existing_database(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise StorageMigrationError(f"DuckDB file does not exist: {resolved}")
    return resolved


def _table_counts(path: Path) -> dict[str, int]:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
        ]
        return {table: _count(connection, table) for table in tables}
    finally:
        connection.close()


def _count(connection: duckdb.DuckDBPyConnection, table: str) -> int:
    row = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()
    return int(row[0]) if row is not None else 0


def _scalar_int(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    if row is None:  # pragma: no cover - aggregate query contract
        raise StorageMigrationError("DuckDB aggregate query returned no row.")
    return int(row[0])


def _count_if_exists(connection: duckdb.DuckDBPyConnection, tables: set[str], table: str) -> int:
    return _count(connection, table) if table in tables else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _json_payload(value: Any) -> str:
    if isinstance(value, tuple | list):
        serializable = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value
        ]
    elif hasattr(value, "model_dump"):
        serializable = value.model_dump(mode="json")
    else:
        serializable = value
    return json.dumps(serializable, sort_keys=True, separators=(",", ":"), default=str)
