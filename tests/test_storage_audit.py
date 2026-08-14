from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from stratweb import cli
from stratweb.storage_audit import DuckDBStorageAuditor, StorageAuditError
from stratweb.storage_audit.models import StorageAuditConfig, StorageRelationshipKind


def _database(path: Path) -> Path:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE matches (
                match_id UUID PRIMARY KEY,
                map_name VARCHAR,
                round_count INTEGER,
                imported_at TIMESTAMP
            );
            CREATE TABLE spatial_snapshots (
                spatial_run_id UUID,
                snapshot_id UUID,
                payload JSON
            );
            CREATE TABLE spatial_snapshot_query_rows (
                spatial_run_id UUID,
                snapshot_id UUID,
                match_id UUID,
                round_number INTEGER,
                tick BIGINT,
                participant_id UUID,
                tick_lookup_key VARCHAR,
                player_path_key VARCHAR,
                payload JSON
            );
            CREATE INDEX idx_spatial_tick ON spatial_snapshot_query_rows(tick_lookup_key);
            CREATE TABLE bomb_position_snapshots (
                spatial_run_id UUID,
                snapshot_id UUID,
                payload JSON
            );
            CREATE TABLE bomb_position_query_rows (
                spatial_run_id UUID,
                snapshot_id UUID,
                payload JSON
            );
            CREATE TABLE zone_assignments (
                zone_assignment_run_id UUID,
                spatial_run_id UUID,
                spatial_snapshot_id UUID,
                round_number INTEGER,
                tick BIGINT,
                participant_id UUID
            );
            CREATE TABLE temporal_events (
                temporal_run_id UUID,
                round_number INTEGER,
                tick BIGINT,
                priority INTEGER,
                event_id UUID,
                payload JSON
            );
            CREATE TABLE analytics_runs (match_id UUID);

            INSERT INTO matches VALUES
                ('00000000-0000-0000-0000-000000000001', 'de_mirage', 20, '2026-01-01'),
                ('00000000-0000-0000-0000-000000000002', 'de_ancient', 21, '2026-01-02');
            INSERT INTO spatial_snapshots VALUES
                ('10000000-0000-0000-0000-000000000001',
                 '20000000-0000-0000-0000-000000000001', '{"x":1}'),
                ('10000000-0000-0000-0000-000000000001',
                 '20000000-0000-0000-0000-000000000002', '{"x":2}');
            INSERT INTO spatial_snapshot_query_rows VALUES
                ('10000000-0000-0000-0000-000000000001',
                 '20000000-0000-0000-0000-000000000001',
                 '00000000-0000-0000-0000-000000000001', 1, 100,
                 '30000000-0000-0000-0000-000000000001', 'tick-100', 'path-1', '{"x":1}'),
                ('10000000-0000-0000-0000-000000000001',
                 '20000000-0000-0000-0000-000000000002',
                 '00000000-0000-0000-0000-000000000001', 1, 101,
                 '30000000-0000-0000-0000-000000000001', 'tick-101', 'path-1', '{"x":2}');
            INSERT INTO bomb_position_snapshots VALUES
                ('10000000-0000-0000-0000-000000000001',
                 '40000000-0000-0000-0000-000000000001', '{"x":3}');
            INSERT INTO bomb_position_query_rows VALUES
                ('10000000-0000-0000-0000-000000000001',
                 '40000000-0000-0000-0000-000000000001', '{"x":3}');
            INSERT INTO zone_assignments VALUES
                ('50000000-0000-0000-0000-000000000001',
                 '10000000-0000-0000-0000-000000000001',
                 '20000000-0000-0000-0000-000000000001', 1, 100,
                 '30000000-0000-0000-0000-000000000001');
            INSERT INTO temporal_events VALUES
                ('60000000-0000-0000-0000-000000000001', 1, 100, 1,
                 '70000000-0000-0000-0000-000000000001', '{"type":"start"}');
            INSERT INTO analytics_runs VALUES
                ('00000000-0000-0000-0000-000000000001'),
                ('00000000-0000-0000-0000-000000000001'),
                ('00000000-0000-0000-0000-000000000002');
            """
        )
    return path


def test_storage_audit_is_read_only_and_measures_mirrors(tmp_path: Path) -> None:
    database = _database(tmp_path / "audit.duckdb")
    before = database.stat()

    report = DuckDBStorageAuditor().audit(
        database,
        config=StorageAuditConfig(benchmark_iterations=2),
    )

    after = database.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert report.database.file_name == "audit.duckdb"
    assert report.summary.matches == 2
    assert report.summary.tables == 8
    assert report.summary.secondary_indexes == 1
    assert report.summary.reported_indexes_including_constraints == 2
    assert report.summary.json_payload_bytes is not None
    assert report.summary.json_payload_bytes > 0
    spatial = next(
        item
        for item in report.relationships
        if item.relationship_id == "spatial_snapshot_query_mirror"
    )
    assert spatial.kind is StorageRelationshipKind.MIRROR
    assert spatial.source_rows == spatial.target_rows == spatial.matched_rows == 2
    assert spatial.payload_equal_rows == 2
    assert spatial.source_coverage == 1.0
    assert report.summary.benchmark_queries_available == 5
    assert all(item.iterations == 2 for item in report.benchmarks if item.available)
    assert report.projections[0].match_count == 20
    assert report.projections[0].projected_file_size_bytes == before.st_size * 10
    runs = next(item for item in report.run_tables if item.table_name == "analytics_runs")
    assert runs.total_runs == 3
    assert runs.scopes_with_multiple_runs == 1
    assert runs.additional_runs_within_scope == 1
    assert runs.deletion_safe is False


def test_optional_expensive_scans_are_explicitly_absent(tmp_path: Path) -> None:
    database = _database(tmp_path / "fast-audit.duckdb")
    report = DuckDBStorageAuditor().audit(
        database,
        config=StorageAuditConfig(
            exact_row_counts=False,
            scan_json_payload_bytes=False,
            run_benchmarks=False,
        ),
    )

    assert report.summary.exact_rows is None
    assert report.summary.json_payload_bytes is None
    assert report.benchmarks == ()
    assert all(item.exact_rows is None for item in report.tables)
    assert all(item.json_payload_bytes is None for item in report.tables)
    mirror = report.relationships[0]
    assert mirror.payload_equal_rows is None
    assert mirror.limitations == ("payload_equality_not_scanned",)


def test_missing_database_is_rejected_without_creating_a_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.duckdb"

    with pytest.raises(StorageAuditError, match="does not exist"):
        DuckDBStorageAuditor().audit(missing)

    assert not missing.exists()


def test_cli_outputs_json_and_cannot_replace_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = _database(tmp_path / "cli.duckdb")
    original = database.read_bytes()
    output = tmp_path / "audit.json"

    exit_code = cli.main(
        [
            "storage",
            "audit",
            "--db",
            str(database),
            "--output",
            str(output),
            "--skip-payload-scan",
            "--skip-benchmarks",
            "--pretty",
        ]
    )
    stdout = json.loads(capsys.readouterr().out)
    destructive_exit = cli.main(
        [
            "storage",
            "audit",
            "--db",
            str(database),
            "--output",
            str(database),
            "--force",
        ]
    )
    error = capsys.readouterr().err

    assert exit_code == 0
    assert stdout["summary"]["matches"] == 2
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["tables"] == 8
    assert destructive_exit == 12
    assert "cannot replace" in error
    assert database.read_bytes() == original
