from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import duckdb
import pytest

from stratweb.adapters.persistence import DuckDBMatchRepository
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.application.canonical_models import (
    CapabilityCoverageStatus,
    ResultCapability,
    ValidationIssue,
    ValidationSeverity,
)
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.persistence import (
    ImportCanonicalMatchService,
    MatchQueryService,
    load_canonical_dataset,
    resolve_database_path,
)
from stratweb.application.persistence_models import ImportStatus, MatchQueryFilters
from stratweb.exceptions import (
    CanonicalSchemaVersionError,
    DatasetFingerprintMismatchError,
    DatasetIntegrityError,
    FatalValidationError,
    MigrationChecksumError,
)
from stratweb.ports import MatchRepository


def test_database_initialization_and_migrations_are_idempotent(tmp_path: Path) -> None:
    repository = DuckDBMatchRepository(tmp_path / "nested" / "matches.duckdb")

    assert repository.initialize() == (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
    )
    assert repository.initialize() == ()

    with duckdb.connect(str(repository.database_path), read_only=True) as connection:
        rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
    assert len(rows) == 27
    assert rows[0][0:2] == (1, "canonical_match_schema")
    assert len(rows[0][2]) == 64
    assert rows[1][0:2] == (2, "round_result_availability")
    assert len(rows[1][2]) == 64
    assert rows[3][0:2] == (4, "trade_window_semantics")
    assert rows[4][0:2] == (5, "temporal_round_state")
    assert rows[5][0:2] == (6, "temporal_simultaneous_groups")
    assert rows[6][0:2] == (7, "spatial_engine_foundation")
    assert rows[7][0:2] == (8, "spatial_query_indexes")
    assert rows[8][0:2] == (9, "spatial_lookup_keys")
    assert rows[9][0:2] == (10, "spatial_lookup_key_indexes")
    assert rows[10][0:2] == (11, "spatial_lookup_backfill")
    assert rows[11][0:2] == (12, "spatial_lookup_match_scope")
    assert rows[12][0:2] == (13, "map_semantics_pin")
    assert rows[13][0:2] == (14, "spatial_projectile_layer")
    assert rows[14][0:2] == (15, "durable_import_jobs")
    assert rows[15][0:2] == (16, "opponent_workspaces")
    assert rows[16][0:2] == (17, "versioned_zone_assignments")
    assert rows[17][0:2] == (18, "economy_and_equipment_context")
    assert rows[18][0:2] == (19, "per_round_tactical_features")
    assert rows[19][0:2] == (20, "cross_match_pattern_engine")
    assert rows[20][0:2] == (21, "analysis_findings")
    assert rows[21][0:2] == (22, "counter_strategy_rules")
    assert rows[22][0:2] == (23, "team_display_labels")
    assert rows[23][0:2] == (24, "import_worker_v2")
    assert rows[24][0:2] == (25, "statistical_trust")
    assert rows[25][0:2] == (26, "tactical_intelligence_v2")
    assert rows[26][0:2] == (27, "local_analyst_notes")


def test_modified_applied_migration_checksum_is_rejected(tmp_path: Path) -> None:
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    repository.initialize()
    with duckdb.connect(str(repository.database_path)) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = ?", ["0" * 64])

    with pytest.raises(MigrationChecksumError):
        repository.initialize()


def test_stage4_database_migration_preserves_match_round_and_event_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "stage4.duckdb"
    stage4_repository = DuckDBMatchRepository(database, migrations=(MIGRATIONS[0],))
    assert stage4_repository.initialize() == (1,)
    match_id = "00000000-0000-0000-0000-000000000401"
    round_id = "00000000-0000-0000-0000-000000000402"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO matches (
                match_id, demo_file_id, dataset_fingerprint, source_demo_sha256,
                map_name, round_count, complete_round_count, incomplete_round_count,
                round_count_candidates, round_count_disagreement, validation_is_valid,
                validation_has_fatal_errors, validation_fatal_error_count,
                validation_unassigned_event_count, validation_unknown_player_count,
                validation_incomplete_round_count, validation_issue_counts, parser_name,
                parser_version, canonical_schema_version, normalization_rule_version,
                normalization_config_hash
            ) VALUES (?, ?, ?, ?, 'de_test', 1, 1, 0, '{}', false, true, false,
                0, 0, 0, 0, '{}', 'demoparser2', '0.41.4', '1.0.0', '1.0.0', ?)
            """,
            [match_id, match_id, "a" * 64, "b" * 64, "c" * 64],
        )
        connection.execute(
            """
            INSERT INTO rounds (
                match_id, round_id, round_number, winner_side, end_reason,
                score_t_before, score_ct_before, score_t_after, score_ct_after,
                is_warmup, is_overtime, is_complete, warnings
            ) VALUES (?, ?, 1, 'UNKNOWN', 'legacy', 0, 0, 1, 0,
                false, false, true, '[]')
            """,
            [match_id, round_id],
        )
        connection.execute(
            """
            INSERT INTO shots (
                match_id, event_id, round_id, round_number, tick, phase,
                source_event, warnings, side
            ) VALUES (?, ?, ?, 1, 150, 'live', 'weapon_fire', '[]', 'T')
            """,
            [match_id, "00000000-0000-0000-0000-000000000403", round_id],
        )
        connection.execute(
            "INSERT INTO normalization_metadata VALUES (?, '{}', '{}', '[]')",
            [match_id],
        )
        before = {}
        for table in ("matches", "rounds", "shots", "normalization_metadata"):
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert row is not None
            before[table] = row[0]

    repository = DuckDBMatchRepository(database)
    assert repository.initialize() == (
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        14,
        15,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        after = {}
        for table in before:
            row = connection.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert row is not None
            after[table] = row[0]
        migrated_round = connection.execute(
            """
            SELECT winner_side, outcome_status, end_reason, end_reason_status,
                   score_t_after, score_status
            FROM rounds
            """
        ).fetchone()
        capabilities_row = connection.execute(
            "SELECT result_capabilities FROM normalization_metadata"
        ).fetchone()
        assert capabilities_row is not None
        stored_capabilities = capabilities_row[0]

    assert after == before
    assert migrated_round == (
        None,
        "missing_from_source",
        None,
        "unresolved",
        None,
        "unresolved",
    )
    assert stored_capabilities is None
    assert repository.get_match(UUID(match_id)) is not None


def test_import_is_transactional_deduplicated_and_force_replace_works(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    service = ImportCanonicalMatchService(repository)

    first = service.import_dataset(
        dataset,
        source_original_name=r"C:\private\opponent.dem",
    )
    stored = repository.get_match(dataset.match.match_id)
    assert stored is not None
    assert stored.source_original_name == "opponent.dem"
    duplicate = service.import_dataset(dataset, source_original_name="renamed.dem")
    replaced = service.import_dataset(dataset, source_original_name="replacement.dem", replace=True)

    assert isinstance(repository, MatchRepository)
    assert first.status is ImportStatus.IMPORTED
    assert duplicate.status is ImportStatus.ALREADY_EXISTS
    assert replaced.status is ImportStatus.REPLACED
    assert first.row_counts == replaced.row_counts
    stored = repository.get_match(dataset.match.match_id)
    assert stored is not None
    assert stored.source_original_name == "replacement.dem"


def test_same_original_filename_with_different_fingerprints_is_not_a_duplicate(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    first_dataset = canonical_dataset_factory("first")
    second_dataset = canonical_dataset_factory("second")
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    service = ImportCanonicalMatchService(repository)

    first = service.import_dataset(first_dataset, source_original_name="same.dem")
    second = service.import_dataset(second_dataset, source_original_name="same.dem")

    assert first.status is ImportStatus.IMPORTED
    assert second.status is ImportStatus.IMPORTED
    assert len(repository.list_matches(MatchQueryFilters())) == 2


def test_same_match_id_with_changed_content_requires_force(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    changed_match = dataset.match.model_copy(update={"map_name": "de_nuke"})
    changed = _with_recalculated_fingerprint(dataset.model_copy(update={"match": changed_match}))
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    service = ImportCanonicalMatchService(repository)
    assert service.import_dataset(dataset).status is ImportStatus.IMPORTED

    conflict = service.import_dataset(changed)
    replaced = service.import_dataset(changed, replace=True)

    assert conflict.status is ImportStatus.FAILED
    assert replaced.status is ImportStatus.REPLACED
    stored = repository.get_match(dataset.match.match_id)
    assert stored is not None
    assert stored.map_name == "de_nuke"


def test_failure_before_commit_rolls_back_every_table(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    monkeypatch: Any,
) -> None:
    dataset = canonical_dataset_factory()
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")

    def fail_integrity(*_args: object, **_kwargs: object) -> None:
        raise DatasetIntegrityError("simulated post-insert failure")

    monkeypatch.setattr(repository, "_verify_persisted_integrity", fail_integrity)
    result = ImportCanonicalMatchService(repository).import_dataset(dataset)

    assert result.status is ImportStatus.FAILED
    assert repository.match_exists(dataset.match.match_id) is False
    assert all(count == 0 for count in repository.get_table_counts(dataset.match.match_id).values())


def test_query_service_exposes_counts_players_rounds_events_and_issues(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    ImportCanonicalMatchService(repository).import_dataset(dataset, source_original_name="safe.dem")
    query = MatchQueryService(repository)

    matches = query.list_matches(MatchQueryFilters(map_name="de_mirage"))
    summary = query.get_summary(dataset.match.match_id)
    players = query.get_players(dataset.match.match_id)
    rounds = query.get_rounds(dataset.match.match_id)
    events = query.get_round_events(dataset.match.match_id, 1)

    assert len(matches) == 1
    assert repository.get_match_by_fingerprint(dataset.dataset_fingerprint) is not None
    assert len(query.list_matches(MatchQueryFilters(parser_name="demoparser2"))) == 1
    assert summary.row_counts["kills"] == 1
    assert summary.validation_issue_counts == {"info": 0, "warning": 1, "error": 0}
    assert len(players) == 2
    assert len(rounds) == 1
    assert len(events.kills) == 1
    assert len(events.damages) == 1
    assert len(events.shots) == 1
    assert len(events.grenades) == 1
    assert len(events.bomb_events) == 1
    assert len(query.get_player_kills(dataset.match.match_id, players[0].player_id)) == 1
    grenade_player_id = dataset.grenades[0].player_id
    assert grenade_player_id is not None
    assert len(query.get_player_grenades(dataset.match.match_id, grenade_player_id)) == 1
    assert query.get_validation_issues(dataset.match.match_id)[0].code == "fixture_warning"


def test_delete_removes_match_and_all_children(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    ImportCanonicalMatchService(repository).import_dataset(dataset)

    assert repository.delete_match(dataset.match.match_id) is True
    assert repository.delete_match(dataset.match.match_id) is False
    assert all(count == 0 for count in repository.get_table_counts(dataset.match.match_id).values())


def test_delete_purges_every_match_scoped_table(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    database_path = tmp_path / "matches.duckdb"
    repository = DuckDBMatchRepository(database_path)
    ImportCanonicalMatchService(repository).import_dataset(dataset)

    match_id = dataset.match.match_id
    run_id = uuid4()
    temporal_run_id = uuid4()
    round_id = dataset.rounds[0].round_id
    connection = duckdb.connect(str(database_path))
    try:
        connection.execute(
            "INSERT INTO spatial_projectiles "
            "VALUES (?, ?, ?, ?, ?, 1, 100, 200, 'smoke', NULL, '{}')",
            [run_id, uuid4(), match_id, temporal_run_id, round_id],
        )
        connection.execute(
            "INSERT INTO spatial_projectile_snapshots "
            "VALUES (?, ?, ?, ?, ?, ?, 1, 150, 'AIRBORNE', '{}')",
            [run_id, uuid4(), uuid4(), match_id, temporal_run_id, round_id],
        )
        connection.execute(
            "INSERT INTO spatial_utility_effects "
            "VALUES (?, ?, NULL, ?, ?, ?, 1, 150, 250, 'smoke', '{}')",
            [run_id, uuid4(), match_id, temporal_run_id, round_id],
        )
    finally:
        connection.close()

    assert repository.delete_match(match_id) is True

    connection = duckdb.connect(str(database_path))
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT table_name FROM information_schema.columns "
                "WHERE table_schema = 'main' AND column_name = 'match_id' "
                "AND table_name != 'import_jobs' ORDER BY table_name"
            ).fetchall()
        ]
        assert "spatial_projectiles" in tables
        assert "spatial_projectile_snapshots" in tables
        assert "spatial_utility_effects" in tables
        leftovers = {
            table: connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE match_id = ?', [match_id]
            ).fetchone()
            for table in tables
        }
    finally:
        connection.close()

    assert {table: row[0] if row else None for table, row in leftovers.items()} == {
        table: 0 for table in tables
    }


def test_delete_failure_rolls_back_and_preserves_match(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    monkeypatch: Any,
) -> None:
    dataset = canonical_dataset_factory()
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    ImportCanonicalMatchService(repository).import_dataset(dataset)

    def fail_after_delete(*_args: object, **_kwargs: object) -> None:
        raise DatasetIntegrityError("simulated delete verification failure")

    monkeypatch.setattr(repository, "_verify_match_absent", fail_after_delete)
    with pytest.raises(DatasetIntegrityError):
        repository.delete_match(dataset.match.match_id)

    assert repository.match_exists(dataset.match.match_id) is True
    assert repository.get_table_counts(dataset.match.match_id)["kills"] == 1


def test_canonical_json_is_validated_and_fingerprint_is_recalculated(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    valid_path = tmp_path / "canonical.json"
    valid_path.write_text(dataset.model_dump_json(), encoding="utf-8")
    assert load_canonical_dataset(valid_path) == dataset

    payload = json.loads(dataset.model_dump_json())
    payload["match"]["map_name"] = "de_nuke"
    modified_path = tmp_path / "modified.json"
    modified_path.write_text(json.dumps(payload), encoding="utf-8")
    modified = load_canonical_dataset(modified_path)

    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    with pytest.raises(DatasetFingerprintMismatchError):
        ImportCanonicalMatchService(repository).import_dataset(modified)


def test_json_with_corrupted_result_capability_is_rejected(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    corrupted_winner = ResultCapability(
        status=CapabilityCoverageStatus.MISSING_FROM_SOURCE,
        source_events_checked=("round_end",),
        detected_fields=(),
        authoritative_source_found=False,
        total_round_count=1,
        rounds_available=0,
        rounds_missing=1,
        rounds_unresolved=0,
    )
    corrupted_metadata = dataset.normalization_metadata.model_copy(
        update={
            "result_capabilities": dataset.normalization_metadata.result_capabilities.model_copy(
                update={"round_winner": corrupted_winner}
            )
        }
    )
    corrupted = _with_recalculated_fingerprint(
        dataset.model_copy(update={"normalization_metadata": corrupted_metadata})
    )
    artifact = tmp_path / "corrupted-capability.json"
    artifact.write_text(corrupted.model_dump_json(), encoding="utf-8")
    loaded = load_canonical_dataset(artifact)

    with pytest.raises(DatasetIntegrityError, match="capability counts"):
        ImportCanonicalMatchService(
            DuckDBMatchRepository(tmp_path / "matches.duckdb")
        ).import_dataset(loaded)


def test_schema_version_and_fatal_validation_are_rejected(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    repository = DuckDBMatchRepository(tmp_path / "matches.duckdb")
    service = ImportCanonicalMatchService(repository)
    wrong_metadata = dataset.normalization_metadata.model_copy(
        update={"canonical_schema_version": "99.0.0"}
    )
    wrong_schema = dataset.model_copy(
        update={
            "schema_version": "99.0.0",
            "normalization_metadata": wrong_metadata,
            "dataset_fingerprint": "0" * 64,
        }
    )
    wrong_schema = wrong_schema.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(wrong_schema)}
    )
    with pytest.raises(CanonicalSchemaVersionError):
        service.import_dataset(wrong_schema)

    fatal_issue = ValidationIssue(
        code="fixture_fatal",
        severity=ValidationSeverity.ERROR,
        is_fatal=True,
        entity_type="dataset",
        message="Synthetic fatal issue.",
        rule_version="1.0.0",
    )
    report = dataset.validation_report.model_copy(
        update={
            "is_valid": False,
            "has_fatal_errors": True,
            "fatal_error_count": 1,
            "issue_counts": {
                ValidationSeverity.INFO: 0,
                ValidationSeverity.WARNING: 1,
                ValidationSeverity.ERROR: 1,
            },
            "issues": (*dataset.validation_report.issues, fatal_issue),
        }
    )
    fatal = _with_recalculated_fingerprint(dataset.model_copy(update={"validation_report": report}))
    with pytest.raises(FatalValidationError):
        service.import_dataset(fatal)


def test_missing_parent_and_duplicate_event_id_are_rejected(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory()
    service = ImportCanonicalMatchService(DuckDBMatchRepository(tmp_path / "matches.duckdb"))

    broken_kill = dataset.kills[0].model_copy(update={"attacker_player_id": uuid4()})
    broken = _with_recalculated_fingerprint(dataset.model_copy(update={"kills": (broken_kill,)}))
    with pytest.raises(DatasetIntegrityError):
        service.import_dataset(broken)

    duplicate = _with_recalculated_fingerprint(
        dataset.model_copy(update={"kills": (dataset.kills[0], dataset.kills[0])})
    )
    with pytest.raises(DatasetIntegrityError):
        service.import_dataset(duplicate)


def test_database_path_precedence(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.duckdb"
    environment = tmp_path / "environment.duckdb"
    default = tmp_path / "default.duckdb"

    assert (
        resolve_database_path(
            explicit,
            environ={"STRATWEB_DUCKDB_PATH": str(environment)},
            default=default,
        )
        == explicit.resolve()
    )
    assert (
        resolve_database_path(
            None,
            environ={"STRATWEB_DUCKDB_PATH": str(environment)},
            default=default,
        )
        == environment.resolve()
    )
    assert resolve_database_path(None, environ={}, default=default) == default.resolve()


def _with_recalculated_fingerprint(dataset: Any):  # type: ignore[no-untyped-def]
    provisional = dataset.model_copy(update={"dataset_fingerprint": "0" * 64})
    return provisional.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
    )
