from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
from fastapi.testclient import TestClient

from stratweb import cli
from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.application.zone_assignments import (
    ComputeZoneAssignmentsService,
    ZoneAssignmentQueryService,
)
from stratweb.main import create_app
from stratweb.spatial.models import (
    SpatialAvailabilityStatus,
    SpatialExtraction,
    SpatialSourceSample,
)
from stratweb.zones.assignment_models import (
    ZoneAssignmentComputeStatus,
    ZoneAssignmentConfig,
    ZoneAssignmentStatus,
)
from stratweb.zones.assignments import ZoneAssignmentEngine
from stratweb.zones.definitions.overpass import OVERPASS_ZONE_SET


class ZoneFixtureExtractor:
    def __init__(self, players: tuple[Any, ...]) -> None:
        self._players = players

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        del demo_path
        return SpatialExtraction(
            parser_name="fixture",
            parser_version="1.0.0",
            source_demo_sha256=expected_sha256,
            requested_ticks=ticks,
            source_columns=("tick", "steamid", "X", "Y", "Z"),
            samples=tuple(
                SpatialSourceSample(
                    tick=tick,
                    steam_id=player.steam_id,
                    player_name=player.current_name,
                    x=-450.0 if index == 0 else 50_000.0,
                    y=-2_200.0 if index == 0 else 50_000.0,
                    z=0.0,
                )
                for tick in ticks
                for index, player in enumerate(self._players)
            ),
        )


def _fixture(tmp_path: Path, canonical_dataset_factory: Any) -> tuple[Path, Any, Any]:
    dataset = canonical_dataset_factory("zone-assignment")
    database = tmp_path / "zone-assignment.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)
    spatial_result = ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        ZoneFixtureExtractor(dataset.players),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    return database, dataset, spatial_result


def test_zone_assignments_are_versioned_deterministic_and_explicitly_unknown(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, spatial_result = _fixture(tmp_path, canonical_dataset_factory)
    spatial = DuckDBSpatialRepository(database)
    repository = DuckDBZoneAssignmentRepository(database)
    service = ComputeZoneAssignmentsService(spatial, repository)

    computed = service.compute(
        dataset.match.match_id,
        spatial_run_id=spatial_result.spatial_run_id,
    )
    repeated = service.compute(
        dataset.match.match_id,
        spatial_run_id=spatial_result.spatial_run_id,
    )
    query = ZoneAssignmentQueryService(repository)
    summary = query.get_summary(
        dataset.match.match_id, spatial_run_id=spatial_result.spatial_run_id
    )
    assignments = query.list_assignments(dataset.match.match_id, limit=10_000)

    assert computed.status is ZoneAssignmentComputeStatus.COMPUTED
    assert repeated.status is ZoneAssignmentComputeStatus.ALREADY_EXISTS
    assert repeated.zone_assignment_fingerprint == computed.zone_assignment_fingerprint
    assert summary.spatial_run_id == spatial_result.spatial_run_id
    assert summary.zone_set_fingerprint is not None
    assert summary.capability.status is SpatialAvailabilityStatus.PARTIAL
    assert summary.summary.resolved > 0
    assert summary.summary.unknown > 0
    assert summary.summary.unavailable == 0
    assert summary.summary.coverage == summary.summary.resolved / summary.summary.position_available
    assert {item.status for item in assignments} == {
        ZoneAssignmentStatus.RESOLVED,
        ZoneAssignmentStatus.UNKNOWN,
    }
    assert all(item.spatial_run_id == spatial_result.spatial_run_id for item in assignments)
    assert all(
        item.zone_id is None
        for item in assignments
        if item.status is not ZoneAssignmentStatus.RESOLVED
    )


def test_zone_assignment_cli_api_playback_and_spatial_cascade(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    capsys: Any,
) -> None:
    database, dataset, spatial_result = _fixture(tmp_path, canonical_dataset_factory)
    match_id = dataset.match.match_id

    assert (
        cli.main(
            [
                "zones",
                "compute",
                str(match_id),
                "--spatial-run",
                str(spatial_result.spatial_run_id),
                "--db",
                str(database),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "computed"
    assert cli.main(["zones", "status", str(match_id), "--db", str(database)]) == 0
    assert json.loads(capsys.readouterr().out)["zone_set_fingerprint"]

    client = TestClient(create_app(database))
    summary = client.get(f"/api/zones/{match_id}/summary")
    assignments = client.get(f"/api/zones/{match_id}/assignments?round=1&limit=20")
    playback = client.get(f"/api/spatial/{match_id}/rounds/1/playback?limit=4")
    viewer = client.get(f"/ui/spatial/{match_id}/rounds/1")
    assert summary.status_code == 200
    assert assignments.status_code == 200
    assert assignments.json()["count"] > 0
    assert playback.status_code == 200
    assert viewer.status_code == 200
    assert 'id="selectedZoneBadge"' in viewer.text
    assert 'id="playerPathLink"' in viewer.text
    assert playback.json()["zone_run"]["spatial_run_id"] == str(spatial_result.spatial_run_id)
    assert any(
        player["zone_assignment"] is not None
        for sample in playback.json()["samples"]
        for player in sample["players"]
    )

    assert DuckDBSpatialRepository(database).delete_spatial(match_id) == 1
    assert DuckDBZoneAssignmentRepository(database).get_summary(match_id) is None
    assert DuckDBMatchRepository(database).match_exists(match_id)


def test_proposed_zone_geometry_is_not_persisted_as_proven_evidence(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, _spatial_result = _fixture(tmp_path, canonical_dataset_factory)
    repository = DuckDBSpatialRepository(database)
    summary = repository.get_summary(dataset.match.match_id)
    assert summary is not None and summary.map_semantics is not None
    spatial = summary.model_copy(
        update={
            "map_model": summary.map_model.model_copy(update={"map_name": "de_overpass"}),
            "map_semantics": summary.map_semantics.model_copy(
                update={
                    "canonical_name": "de_overpass",
                    "selected_map_revision": OVERPASS_ZONE_SET.map_revision,
                }
            ),
        }
    )
    snapshots = tuple(
        item.model_copy(update={"map_name": "de_overpass"})
        for item in repository.list_snapshots(
            dataset.match.match_id,
            limit=10_000,
            spatial_run_id=summary.spatial_run_id,
        )
    )

    state = ZoneAssignmentEngine().compute(
        spatial,
        snapshots,
        OVERPASS_ZONE_SET,
        ZoneAssignmentConfig(),
    )

    assert state.capability.status is SpatialAvailabilityStatus.UNAVAILABLE
    assert state.summary.resolved == 0
    assert state.summary.unavailable == state.summary.snapshots
    assert "zone_geometry_unverified" in state.warnings
    assert "proposed_zones_excluded:36" in state.warnings


def test_default_zone_run_never_falls_back_to_an_older_spatial_run(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, spatial_result = _fixture(tmp_path, canonical_dataset_factory)
    spatial = DuckDBSpatialRepository(database)
    zones = DuckDBZoneAssignmentRepository(database)
    ComputeZoneAssignmentsService(spatial, zones).compute(dataset.match.match_id)
    assert zones.get_summary(dataset.match.match_id) is not None

    newer_run_id = uuid4()
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            """
            INSERT INTO spatial_runs BY NAME
            SELECT * REPLACE (
                ? AS spatial_run_id,
                ? AS spatial_fingerprint,
                ? AS spatial_config_hash,
                current_timestamp + INTERVAL 1 SECOND AS created_at
            )
            FROM spatial_runs WHERE spatial_run_id = ?
            """,
            [newer_run_id, "f" * 64, "e" * 64, spatial_result.spatial_run_id],
        )

    assert zones.get_summary(dataset.match.match_id) is None
    assert (
        zones.get_summary_for_spatial_run(dataset.match.match_id, spatial_result.spatial_run_id)
        is not None
    )
