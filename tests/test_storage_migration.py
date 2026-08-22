from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import duckdb
import pytest

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBSpatialRepository
from stratweb.adapters.persistence.storage_layout import STORAGE_LAYOUT_V1, STORAGE_LAYOUT_V2
from stratweb.storage_migration import DuckDBStorageMigrator, StorageMigrationError
from stratweb.storage_migration.models import StorageMigrationConfig

RUN_ID = UUID("00000000-0000-0000-0000-000000009201")
MATCH_ID = UUID("00000000-0000-0000-0000-000000009202")
TEMPORAL_RUN_ID = UUID("00000000-0000-0000-0000-000000009203")
ROUND_ID = UUID("00000000-0000-0000-0000-000000009204")
PLAYER_ID = UUID("00000000-0000-0000-0000-000000009205")
TEAM_ID = UUID("00000000-0000-0000-0000-000000009206")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000009207")
BOMB_ID = UUID("00000000-0000-0000-0000-000000009208")


def _snapshot_payload() -> str:
    return json.dumps(
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "match_id": str(MATCH_ID),
            "temporal_run_id": str(TEMPORAL_RUN_ID),
            "round_id": str(ROUND_ID),
            "round_number": 1,
            "tick": 100,
            "participant_id": str(PLAYER_ID),
            "x": 10.0,
            "y": 20.0,
            "z": 30.0,
            "yaw": 90.0,
            "pitch": 0.0,
            "alive": True,
            "has_bomb": True,
            "physical_team_id": str(TEAM_ID),
            "side": "T",
            "map_name": "de_test",
            "source": "test",
            "position_authority": "demo_entity_derived",
            "view_angle_authority": "demo_entity_derived",
            "alive_source": "temporal_snapshot",
            "has_bomb_source": "test",
            "availability": {
                "position": "available",
                "view_angles": "available",
                "alive_link": "available",
                "has_bomb": "available",
                "warnings": [],
            },
        }
    )


def _bomb_payload() -> str:
    return json.dumps(
        {
            "snapshot_id": str(BOMB_ID),
            "match_id": str(MATCH_ID),
            "temporal_run_id": str(TEMPORAL_RUN_ID),
            "round_id": str(ROUND_ID),
            "round_number": 1,
            "tick": 100,
            "x": 10.0,
            "y": 20.0,
            "z": 30.0,
            "carrier_participant_id": str(PLAYER_ID),
            "position_authority": "derived",
            "source": "test",
        }
    )


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "storage.duckdb"
    DuckDBMatchRepository(database).initialize()
    tick_key = f"{RUN_ID}:1:100"
    player_key = f"{RUN_ID}:1:{PLAYER_ID}"
    snapshot_payload = _snapshot_payload()
    bomb_payload = _bomb_payload()
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO spatial_runs (
                spatial_run_id, spatial_fingerprint, match_id, dataset_fingerprint,
                temporal_run_id, temporal_fingerprint, source_demo_sha256,
                parser_name, parser_version, spatial_schema_version, spatial_rule_version,
                spatial_config_hash, config, map_model, capabilities, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'test', '1', '1.2.0', '1.3.0', ?,
                      '{}', '{}', '{}', '{}', '{}', '[]')
            """,
            [
                RUN_ID,
                "1" * 64,
                MATCH_ID,
                "2" * 64,
                TEMPORAL_RUN_ID,
                "3" * 64,
                "4" * 64,
                "5" * 64,
            ],
        )
        connection.execute(
            """
            INSERT INTO spatial_snapshots (
                spatial_run_id, snapshot_id, match_id, temporal_run_id, round_id,
                round_number, tick, participant_id, x, y, z, yaw, pitch, alive,
                has_bomb, physical_team_id, side, map_name, position_authority,
                availability, payload, tick_lookup_key, player_path_key
            ) VALUES (?, ?, ?, ?, ?, 1, 100, ?, 10, 20, 30, 90, 0, true,
                      true, ?, 'T', 'de_test', 'demo_entity_derived', '{}', ?, ?, ?)
            """,
            [
                RUN_ID,
                SNAPSHOT_ID,
                MATCH_ID,
                TEMPORAL_RUN_ID,
                ROUND_ID,
                PLAYER_ID,
                TEAM_ID,
                snapshot_payload,
                tick_key,
                player_key,
            ],
        )
        connection.execute(
            """
            INSERT INTO spatial_snapshot_query_rows VALUES (
                ?, ?, 1, 100, ?, ?, true, true, 10, 'demo_entity_derived', ?, ?, ?, ?
            )
            """,
            [
                RUN_ID,
                SNAPSHOT_ID,
                PLAYER_ID,
                TEAM_ID,
                tick_key,
                player_key,
                snapshot_payload,
                MATCH_ID,
            ],
        )
        connection.execute(
            """
            INSERT INTO bomb_position_snapshots (
                spatial_run_id, snapshot_id, match_id, temporal_run_id, round_id,
                round_number, tick, x, y, z, carrier_participant_id,
                position_authority, source, payload, tick_lookup_key
            ) VALUES (?, ?, ?, ?, ?, 1, 100, 10, 20, 30, ?, 'derived', 'test', ?, ?)
            """,
            [
                RUN_ID,
                BOMB_ID,
                MATCH_ID,
                TEMPORAL_RUN_ID,
                ROUND_ID,
                PLAYER_ID,
                bomb_payload,
                tick_key,
            ],
        )
        connection.execute(
            "INSERT INTO bomb_position_query_rows VALUES (?, ?, 1, 100, ?, ?, ?)",
            [RUN_ID, BOMB_ID, tick_key, bomb_payload, MATCH_ID],
        )
    return database


def test_verified_migration_activates_v2_and_repository_reads_canonical_payload(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    backup = tmp_path / "backups" / "storage-v1.duckdb"
    migrator = DuckDBStorageMigrator()

    before = migrator.status(database)
    assert before.active_layout == STORAGE_LAYOUT_V1
    assert not before.v2_schema_available

    report = migrator.migrate(
        database,
        backup,
        config=StorageMigrationConfig(benchmark_iterations=1),
    )

    assert report.backup.verified
    assert backup.is_file()
    assert report.activated
    assert all(item.passed for item in report.parity)
    assert all(item.passed for item in report.benchmarks)
    assert report.status.active_layout == STORAGE_LAYOUT_V2
    assert report.status.v2_index_count == 3

    with duckdb.connect(str(database)) as connection:
        connection.execute("DELETE FROM spatial_snapshot_query_rows")
        connection.execute("DELETE FROM bomb_position_query_rows")
    snapshots = DuckDBSpatialRepository(database).get_tick_snapshots(MATCH_ID, 1, 100)
    assert len(snapshots) == 1
    assert snapshots[0].snapshot_id == SNAPSHOT_ID
    assert snapshots[0].x == 10.0

    restored = tmp_path / "restored.duckdb"
    restore = migrator.restore_to_new_database(backup, restored)
    assert restore.verified
    assert restored.is_file()
    assert migrator.status(restored).active_layout == STORAGE_LAYOUT_V1


def test_rollback_restores_missing_legacy_rows_before_switching_layout(tmp_path: Path) -> None:
    database = _database(tmp_path)
    migrator = DuckDBStorageMigrator()
    migrator.migrate(
        database,
        tmp_path / "backup.duckdb",
        config=StorageMigrationConfig(benchmark_iterations=1),
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute("DELETE FROM spatial_snapshot_query_rows")
        connection.execute("DELETE FROM bomb_position_query_rows")

    result = migrator.rollback(database)

    assert result.restored_spatial_rows == 1
    assert result.restored_bomb_rows == 1
    assert all(item.passed for item in result.parity)
    assert result.status.active_layout == STORAGE_LAYOUT_V1
    assert result.status.status == "rolled_back"


def test_migration_refuses_existing_backup_and_requires_distinct_path(tmp_path: Path) -> None:
    database = _database(tmp_path)
    migrator = DuckDBStorageMigrator()
    existing = tmp_path / "existing.duckdb"
    existing.write_bytes(b"do not overwrite")

    with pytest.raises(StorageMigrationError, match="already exists"):
        migrator.migrate(database, existing)
    with pytest.raises(StorageMigrationError, match="must differ"):
        migrator.migrate(database, database)

    assert existing.read_bytes() == b"do not overwrite"


def test_parity_failure_keeps_legacy_layout_active(tmp_path: Path) -> None:
    database = _database(tmp_path)
    with duckdb.connect(str(database)) as connection:
        connection.execute("UPDATE spatial_snapshots SET tick_lookup_key = NULL")

    report = DuckDBStorageMigrator().migrate(
        database,
        tmp_path / "parity-failure-backup.duckdb",
        config=StorageMigrationConfig(benchmark_iterations=1),
    )

    assert not report.activated
    assert not report.parity[0].passed
    assert report.status.active_layout == STORAGE_LAYOUT_V1
    assert report.status.status == "shadow_ready"
