from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
from fastapi.testclient import TestClient

from stratweb import cli
from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
)
from stratweb.application.spatial import ComputeSpatialStateService, SpatialQueryService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.main import create_app
from stratweb.spatial.models import (
    SpatialAvailabilityStatus,
    SpatialComputeStatus,
    SpatialExtraction,
    SpatialSourceSample,
)


class FakeSpatialExtractor:
    def __init__(self, players: tuple[Any, ...], *, overflow: bool = False) -> None:
        self._players = players
        self._overflow = overflow

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        del demo_path
        samples = []
        for tick in ticks:
            for index, player in enumerate(self._players):
                samples.append(
                    SpatialSourceSample(
                        tick=tick,
                        steam_id=player.steam_id,
                        player_name=player.current_name,
                        x=2_000_000.0 if self._overflow and index == 0 else tick + index,
                        y=20.0 + index,
                        z=5.0,
                        pitch=3.5,
                        yaw=90.0,
                        inventory_item_ids=(49,) if index == 0 else (),
                    )
                )
        return SpatialExtraction(
            parser_name="demoparser2",
            parser_version="0.41.4",
            source_demo_sha256=expected_sha256,
            requested_ticks=ticks,
            samples=tuple(samples),
            source_columns=(
                "tick",
                "steamid",
                "name",
                "X",
                "Y",
                "Z",
                "pitch",
                "yaw",
                "inventory_as_ids",
            ),
        )


def _compute_fixture(
    tmp_path: Path, canonical_dataset_factory: Any, *, seed: str = "spatial"
) -> tuple[Path, Any, Any]:
    dataset = canonical_dataset_factory(seed)
    database = tmp_path / f"{seed}.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)
    service = ComputeSpatialStateService(
        matches, temporal, spatial, FakeSpatialExtractor(dataset.players)
    )
    result = service.compute(dataset.match.match_id, tmp_path / "ignored.dem")
    return database, dataset, result


def test_spatial_round_trip_is_deterministic_and_temporal_linked(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, computed = _compute_fixture(tmp_path, canonical_dataset_factory)
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    repository = DuckDBSpatialRepository(database)
    repeated = ComputeSpatialStateService(
        matches, temporal, repository, FakeSpatialExtractor(dataset.players)
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    query = SpatialQueryService(repository)
    summary = query.get_summary(dataset.match.match_id)
    rows = query.list_snapshots(dataset.match.match_id, round_number=1)
    bombs = query.list_bomb_positions(dataset.match.match_id, round_number=1)

    assert computed.status is SpatialComputeStatus.COMPUTED
    assert repeated.status is SpatialComputeStatus.ALREADY_EXISTS
    assert repeated.spatial_fingerprint == computed.spatial_fingerprint
    assert summary.temporal_run_id == computed.temporal_run_id
    assert rows and all(item.temporal_run_id == summary.temporal_run_id for item in rows)
    assert [item.tick for item in rows] == sorted(item.tick for item in rows)
    assert all(item.alive_source == "temporal_snapshot" for item in rows)
    assert bombs and all(item.source.startswith("derived:confirmed_c4") for item in bombs)
    assert summary.map_model.bounds is None
    assert summary.capabilities.map_metadata.status is SpatialAvailabilityStatus.PARTIAL
    assert query.list_runs(dataset.match.match_id)[0].selected_by_default is True


def test_spatial_validation_rejects_coordinate_overflow_without_storing_false_position(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("spatial-overflow")
    database = tmp_path / "overflow.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)
    ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        FakeSpatialExtractor(dataset.players, overflow=True),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    query = SpatialQueryService(spatial)

    issues = query.validate(dataset.match.match_id)
    affected = [item for item in query.list_snapshots(dataset.match.match_id) if item.x is None]
    assert any(item.code == "invalid_or_overflow_coordinate" for item in issues)
    assert affected
    assert all(
        item.availability.position is SpatialAvailabilityStatus.UNAVAILABLE for item in affected
    )


def test_spatial_cli_and_ui_contract(
    tmp_path: Path, canonical_dataset_factory: Any, monkeypatch: Any, capsys: Any
) -> None:
    dataset = canonical_dataset_factory("spatial-cli")
    database = tmp_path / "cli.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)
    monkeypatch.setattr(
        cli, "Demoparser2SpatialExtractor", lambda: FakeSpatialExtractor(dataset.players)
    )
    match_id = str(dataset.match.match_id)
    compute = [
        "spatial",
        "compute",
        match_id,
        str(tmp_path / "ignored.dem"),
        "--db",
        str(database),
    ]

    assert cli.main(compute) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "computed"
    for action in ("status", "runs", "validate", "bombs"):
        assert cli.main(["spatial", action, match_id, "--db", str(database)]) == 0
        assert json.loads(capsys.readouterr().out) is not None
    output = tmp_path / "snapshots.json"
    assert (
        cli.main(
            [
                "spatial",
                "show",
                match_id,
                "--round",
                "1",
                "--limit",
                "5",
                "--output",
                str(output),
                "--db",
                str(database),
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown == json.loads(output.read_text(encoding="utf-8"))
    assert len(shown) == 5

    client = TestClient(create_app(database))
    page = client.get(f"/ui/spatial/{match_id}?round=1&limit=5")
    api = client.get(f"/api/spatial/{match_id}/snapshots?round=1&limit=5")
    assert page.status_code == 200
    assert "No zone, trajectory, heatmap, or tactical meaning is inferred" in page.text
    assert "Spatial schema 1.3.0" in page.text
    assert api.status_code == 200
    assert api.json()["spatial_rule_version"] == "1.4.0"
    assert len(api.json()["snapshots"]) == 5

    assert cli.main(["spatial", "delete", match_id, "--yes", "--db", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["deleted"] is True
    assert matches.match_exists(dataset.match.match_id)
    assert temporal.get_summary(dataset.match.match_id) is not None


def test_migrations_007_through_014_preserve_canonical_and_temporal_rows(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    dataset = canonical_dataset_factory("spatial-migration")
    database = tmp_path / "migration-007.duckdb"
    repository = DuckDBMatchRepository(database)
    repository.save_match(dataset)
    ComputeTemporalStateService(repository, DuckDBTemporalRepository(database)).compute(
        dataset.match.match_id
    )
    temporal_count_before: tuple[int] | None
    with duckdb.connect(str(database), read_only=True) as connection:
        temporal_count_before = connection.execute("SELECT count(*) FROM temporal_runs").fetchone()

    with duckdb.connect(str(database)) as connection:
        for table in (
            "spatial_utility_effects",
            "spatial_projectile_snapshots",
            "spatial_projectiles",
            "bomb_position_query_rows",
            "spatial_snapshot_query_rows",
            "spatial_validation_issues",
            "bomb_position_snapshots",
            "spatial_snapshots",
            "spatial_runs",
        ):
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute(
            "DELETE FROM schema_migrations WHERE version IN (7, 8, 9, 10, 11, 12, 13, 14)"
        )

    assert DuckDBMatchRepository(database).initialize() == (7, 8, 9, 10, 11, 12, 13, 14)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM matches").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM temporal_runs").fetchone() == (
            temporal_count_before
        )
        tables = connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name IN ('spatial_runs','spatial_snapshots',"
            "'bomb_position_snapshots','spatial_validation_issues',"
            "'spatial_projectiles','spatial_projectile_snapshots',"
            "'spatial_utility_effects')"
        ).fetchone()
    assert tables == (7,)


def test_spatial_source_sha_is_part_of_deterministic_fixture(
    canonical_dataset_factory: Any,
) -> None:
    dataset = canonical_dataset_factory("spatial-sha")
    assert (
        dataset.normalization_metadata.source_demo_sha256
        == hashlib.sha256(b"spatial-sha").hexdigest()
    )
