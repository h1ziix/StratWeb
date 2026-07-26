from __future__ import annotations

import hashlib
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
)
from stratweb.analytics.models import AnalyticsConfig
from stratweb.application.analytics import ComputeMatchAnalyticsService
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.spatial_queries import SpatialExplorerService, _player_view
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.main import create_app
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.spatial.engine import SpatialEngine
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.spatial.models import SpatialExtraction, SpatialSourceSample
from stratweb.spatial.projectiles import (
    ProjectileAuthority,
    ProjectileAvailability,
    ProjectileCapabilities,
    ProjectileCapability,
    ProjectileExtraction,
    ProjectileLifecycle,
    ProjectileSourcePoint,
    ProjectileSourceTrack,
    ProjectileType,
    UtilityEffectSource,
    UtilityEffectType,
)
from stratweb.spatial.query_models import (
    EntityRenderStatus,
    SpatialEventMarkerKind,
    TickResolutionStatus,
)


class QueryFixtureExtractor:
    def __init__(self, players: tuple[Any, ...]) -> None:
        self.players = players

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        del demo_path
        available = ProjectileCapability(
            status=ProjectileAvailability.AVAILABLE,
            authority=ProjectileAuthority.PARSER_ENTITY,
            population=1,
            covered=1,
        )
        capabilities = ProjectileCapabilities(
            positions=available,
            owner=available,
            initial_velocity=available,
            throw_actions=available.model_copy(
                update={"authority": ProjectileAuthority.DERIVED_ASSOCIATION}
            ),
            lifecycle=available.model_copy(update={"authority": ProjectileAuthority.GAME_EVENT}),
            bounce_events=available,
            detonation_events=available.model_copy(
                update={"authority": ProjectileAuthority.GAME_EVENT}
            ),
            smoke_lifecycle=available.model_copy(
                update={"authority": ProjectileAuthority.GAME_EVENT}
            ),
            fire_lifecycle=available,
            decoy_lifecycle=available,
        )
        return SpatialExtraction(
            parser_name="demoparser2",
            parser_version="0.41.4",
            source_demo_sha256=expected_sha256,
            requested_ticks=ticks,
            source_columns=(
                "tick",
                "steamid",
                "X",
                "Y",
                "Z",
                "pitch",
                "yaw",
                "inventory_as_ids",
            ),
            samples=tuple(
                SpatialSourceSample(
                    tick=tick,
                    steam_id=player.steam_id,
                    player_name=player.current_name,
                    x=-1000.0 + tick + index * 30,
                    y=1000.0 - tick - index * 20,
                    z=10.0,
                    pitch=5.0,
                    yaw=90.0 + index * 90,
                    inventory_item_ids=(49,) if index == 0 else (),
                )
                for tick in ticks
                for index, player in enumerate(self.players)
            ),
            projectiles=ProjectileExtraction(
                tracks=(
                    ProjectileSourceTrack(
                        source_track_id="fixture-smoke",
                        source_entity_id=7,
                        raw_projectile_type="CSmokeGrenadeProjectile",
                        projectile_type=ProjectileType.SMOKE,
                        owner_steam_id=self.players[0].steam_id,
                        owner_name=self.players[0].current_name,
                        thrown_tick=110,
                        first_position_tick=112,
                        terminal_tick=120,
                        terminal_event="smokegrenade_detonate",
                        initial_velocity_x=100.0,
                        initial_velocity_y=50.0,
                        initial_velocity_z=20.0,
                        points=(
                            ProjectileSourcePoint(
                                tick=112,
                                x=-850.0,
                                y=850.0,
                                z=30.0,
                                bounce_count=0,
                                lifecycle=ProjectileLifecycle.IN_FLIGHT,
                                source="fixture:parser_entity",
                            ),
                            ProjectileSourcePoint(
                                tick=120,
                                x=-820.0,
                                y=820.0,
                                z=10.0,
                                bounce_count=1,
                                lifecycle=ProjectileLifecycle.DETONATED,
                                source="fixture:game_event",
                            ),
                        ),
                        availability=ProjectileAvailability.AVAILABLE,
                    ),
                ),
                effects=(
                    UtilityEffectSource(
                        source_effect_id="fixture-smoke-effect",
                        source_track_id="fixture-smoke",
                        source_entity_id=7,
                        effect_type=UtilityEffectType.SMOKE,
                        start_tick=120,
                        end_tick=140,
                        center_x=-820.0,
                        center_y=820.0,
                        center_z=10.0,
                        start_event="smokegrenade_detonate",
                        end_event="smokegrenade_expired",
                        availability=ProjectileAvailability.AVAILABLE,
                        source="fixture:game_event",
                    ),
                ),
                capabilities=capabilities,
            ),
        )


def _assets(tmp_path: Path) -> Path:
    assets = tmp_path / "overviews"
    assets.mkdir()
    (assets / "de_mirage.txt").write_text(
        '"de_mirage"\n{\n"pos_x" "-3230"\n"pos_y" "1713"\n"scale" "5"\n"rotate" "0"\n}\n',
        encoding="utf-8",
    )
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024)
    (assets / "de_mirage.png").write_bytes(header)
    return assets


def _registry(assets: Path) -> MapRegistry:
    base = DEFAULT_MAP_REGISTRY.preferred_definition("de_mirage")
    assert base is not None and base.overview_asset is not None
    image = assets / "de_mirage.png"
    metadata = assets / "de_mirage.txt"
    reference = base.overview_asset.model_copy(
        update={
            "asset_id": "de_mirage:test-fixture:upper",
            "relative_path": "de_mirage.png",
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
        }
    )
    return MapRegistry(
        (
            base.model_copy(
                update={
                    "overview_asset": reference,
                    "asset_version": "deterministic-test-fixture",
                }
            ),
        )
    )


def _fixture(
    tmp_path: Path, canonical_dataset_factory: Any
) -> tuple[Path, Any, SpatialExplorerService, Path, MapRegistry]:
    dataset = canonical_dataset_factory("spatial-query")
    database = tmp_path / "query.duckdb"
    matches = DuckDBMatchRepository(database)
    analytics = DuckDBAnalyticsRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    matches.save_match(dataset)
    ComputeMatchAnalyticsService(matches, analytics).compute(
        dataset.match.match_id, config=AnalyticsConfig()
    )
    ComputeTemporalStateService(matches, temporal, analytics_repository=analytics).compute(
        dataset.match.match_id
    )
    assets = _assets(tmp_path)
    registry = _registry(assets)
    ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        QueryFixtureExtractor(dataset.players),
        engine=SpatialEngine(registry),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    return (
        database,
        dataset,
        SpatialExplorerService(
            matches,
            temporal,
            spatial,
            MapOverviewRegistry(assets, registry),
            analytics_repository=analytics,
        ),
        assets,
        registry,
    )


def test_indexed_tick_team_path_nearest_and_bomb_queries(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, service, _, _ = _fixture(tmp_path, canonical_dataset_factory)
    match_id = dataset.match.match_id
    ticks = service.list_round_ticks(match_id, 1)

    assert {112, 115, 120, 130, 140}.issubset(ticks)
    tick = service.get_tick_snapshot(match_id, 1, 120)
    assert tick.navigation.status is TickResolutionStatus.EXACT
    assert len(tick.players) == 2
    assert all(item.projection is not None for item in tick.players)
    first_direction = tick.players[0].view_direction
    assert first_direction is not None
    assert abs(first_direction.end_pixel_x - first_direction.start_pixel_x) < 1e-9
    assert first_direction.end_pixel_y < first_direction.start_pixel_y
    assert tick.bomb_position is not None
    assert tick.bomb_carrier_id == dataset.players[0].player_id
    assert tick.bomb_projection == tick.players[0].projection
    assert SpatialEventMarkerKind.DEATH in {item.kind for item in tick.events}
    assert SpatialEventMarkerKind.OPENING_DUEL in {item.kind for item in tick.events}

    team = service.get_team_snapshot(match_id, 1, 120, dataset.teams[0].team_id)
    assert len(team.players) == 1
    assert team.players[0].snapshot.physical_team_id == dataset.teams[0].team_id
    path = service.get_player_path(match_id, 1, dataset.players[0].player_id)
    assert path.points
    assert [item.snapshot.tick for item in path.points] == sorted(
        item.snapshot.tick for item in path.points
    )
    nearest = service.nearest_players(match_id, 1, 115, dataset.players[0].player_id)
    assert nearest.players[0].participant_id == dataset.players[1].player_id
    assert nearest.players[0].distance_world_units > 0

    missing = service.get_tick_snapshot(match_id, 1, 119)
    assert missing.navigation.status is TickResolutionStatus.UNAVAILABLE
    assert missing.players == ()
    assert missing.navigation.previous_tick is not None
    assert missing.navigation.next_tick == 120

    with duckdb.connect(str(database), read_only=True) as connection:
        indexes = connection.execute(
            "SELECT index_name, expressions FROM duckdb_indexes() "
            "WHERE index_name LIKE 'idx_spatial_snapshots_%' ORDER BY index_name"
        ).fetchall()
    assert dict(indexes) == {
        "idx_spatial_snapshots_player_path": "[player_path_key]",
        "idx_spatial_snapshots_tick_lookup": "[tick_lookup_key]",
    }


def test_spatial_explorer_ui_api_and_temporal_links(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, service, assets, registry = _fixture(tmp_path, canonical_dataset_factory)
    match_id = dataset.match.match_id
    tick = 120
    client = TestClient(create_app(database, assets, map_registry=registry))

    page = client.get(f"/ui/spatial/{match_id}/rounds/1?tick={tick}")
    path = client.get(
        f"/ui/spatial/{match_id}/rounds/1/players/{dataset.players[0].player_id}/path"
    )
    tick_api = client.get(f"/api/spatial/{match_id}/rounds/1/ticks/{tick}")
    map_api = client.get(f"/api/spatial/{match_id}/map-snapshot?round=1&tick={tick}")
    team_api = client.get(
        f"/api/spatial/{match_id}/rounds/1/teams/{dataset.teams[0].team_id}/ticks/{tick}"
    )
    path_api = client.get(
        f"/api/spatial/{match_id}/rounds/1/players/{dataset.players[0].player_id}/path"
    )
    nearest_api = client.get(
        f"/api/spatial/{match_id}/rounds/1/ticks/{tick}/nearest"
        f"?player={dataset.players[0].player_id}"
    )
    temporal = client.get(f"/ui/temporal/{match_id}/rounds/1")
    playback = client.get(f"/api/spatial/{match_id}/rounds/1/playback?from_index=0&limit=10")
    player_js = client.get("/static/js/spatial-player.js")

    assert page.status_code == 200
    assert "card.innerHTML" not in page.text
    assert "/static/js/spatial-player.js?v=" in page.text
    assert "initialChunk" in page.text
    assert '"label_roster"' in page.text
    assert str(dataset.players[0].player_id) in page.text
    assert all(
        text in page.text
        for text in (
            "Match viewer",
            "scrubber",
            "Play",
            "Jump",
            "Diagnostics",
            "Smooth",
            "Exact",
            "Auto focus",
            "Medium",
            "Hidden",
        )
    )
    assert path.status_code == 200
    assert "Lines connect consecutive stored samples" in path.text
    assert "no route inference" in path.text
    assert all(
        response.status_code == 200
        for response in (tick_api, map_api, team_api, path_api, nearest_api)
    )
    assert tick_api.json()["overview"]["status"] == "available"
    assert tick_api.json()["players"][0]["projection"] is not None
    assert map_api.json() == tick_api.json()
    assert len(team_api.json()["players"]) == 1
    assert path_api.json()["points"]
    assert nearest_api.json()["players"]
    assert playback.status_code == 200
    assert playback.json()["visual_interpolation_included"] is False
    assert playback.json()["evidence_semantics"] == "authoritative_spatial_samples"
    assert playback.json()["schema_version"] == "1.2.0"
    assert "player_samples" not in playback.json()
    assert "event_markers" not in playback.json()
    assert playback.json()["clock"] == {
        "basis": "relative_demo_ticks",
        "tick_duration_ms": 15.625,
        "presentation_ticks_per_second": 64.0,
        "rate_source": "presentation_policy:not_canonical_tickrate",
        "canonical_tickrate_used": False,
        "event_density_independent": True,
    }
    assert playback.json()["projectile_samples"]
    assert playback.json()["utility_effects"]
    assert playback.json()["projectile_capabilities"]["positions"]["status"] == "available"
    assert [item["sample_index"] for item in playback.json()["samples"]] == list(range(10))
    assert player_js.status_code == 200
    assert player_js.headers["cache-control"] == "no-cache, must-revalidate"
    assert "requestAnimationFrame" in player_js.text
    assert "setInterval" not in player_js.text
    assert temporal.status_code == 200
    assert f"/ui/spatial/{match_id}/rounds/1?tick={tick}" in temporal.text
    assert (
        str(service.get_tick_snapshot(match_id, 1, tick).temporal_run_id)
        == (tick_api.json()["temporal_run_id"])
    )
    missing = client.get("/api/spatial/00000000-0000-0000-0000-000000000000/rounds/1/ticks/120")
    assert missing.status_code == 404


def test_spatial_explorer_handles_parallel_read_requests(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, _, assets, registry = _fixture(tmp_path, canonical_dataset_factory)
    match_id = dataset.match.match_id
    player_id = dataset.players[0].player_id
    client = TestClient(create_app(database, assets, map_registry=registry))
    urls = (
        f"/ui/spatial/{match_id}/rounds/1?tick=120",
        f"/api/spatial/{match_id}/rounds/1/ticks/120",
        f"/ui/spatial/{match_id}/rounds/1/players/{player_id}/path",
    )

    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        statuses = tuple(pool.map(lambda url: client.get(url).status_code, urls))

    assert statuses == (200, 200, 200)


def test_playback_chunk_pagination_filters_and_run_pinning(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, service, assets, registry = _fixture(tmp_path, canonical_dataset_factory)
    match_id = dataset.match.match_id
    summary = service.get_tick_snapshot(match_id, 1, 120)
    client = TestClient(create_app(database, assets, map_registry=registry))
    base = f"/api/spatial/{match_id}/rounds/1/playback"

    first = client.get(f"{base}?from_index=0&limit=2&run_id={summary.spatial_run_id}")
    second = client.get(f"{base}?from_index=2&limit=2&run_id={summary.spatial_run_id}")
    pinned_path = client.get(
        f"/api/spatial/{match_id}/rounds/1/players/{dataset.players[0].player_id}/path"
        f"?run_id={summary.spatial_run_id}"
    )
    filtered = client.get(f"{base}?from_index=0&limit=5&player={dataset.players[0].player_id}")
    invalid = client.get(f"{base}?from_index=9999&limit=2")
    unknown_run = client.get(
        f"{base}?from_index=0&limit=2&run_id=00000000-0000-0000-0000-000000000000"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["navigation"]["next_from_index"] == 2
    assert first.json()["ticks"][-1] < second.json()["ticks"][0]
    assert pinned_path.status_code == 200
    assert pinned_path.json()["spatial_run_id"] == str(summary.spatial_run_id)
    assert all(
        len(sample["players"]) == 1
        and sample["players"][0]["snapshot"]["participant_id"] == str(dataset.players[0].player_id)
        for sample in filtered.json()["samples"]
    )
    assert invalid.status_code == 416
    assert unknown_run.status_code == 404


def test_map_projection_uses_official_overview_transform(tmp_path: Path) -> None:
    assets = _assets(tmp_path)
    overview = MapOverviewRegistry(assets).get("de_mirage")
    upper_left = overview.project(-3230, 1713)
    one_pixel = overview.project(-3225, 1708)

    assert upper_left is not None
    assert (upper_left.pixel_x, upper_left.pixel_y) == (0, 0)
    assert one_pixel is not None
    assert (one_pixel.pixel_x, one_pixel.pixel_y) == (1, 1)
    assert overview.model.source.startswith("local_cs2_vpk")


def test_out_of_map_raw_coordinate_is_rejected_not_clamped(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database, dataset, _, assets, registry = _fixture(tmp_path, canonical_dataset_factory)
    repository = DuckDBSpatialRepository(database)
    row = repository.get_tick_snapshots(dataset.match.match_id, 1, 120)[0]
    overview = MapOverviewRegistry(assets, registry).get("de_mirage")

    view = _player_view(
        row.model_copy(update={"x": 999_999.0, "y": 999_999.0}),
        {row.participant_id: "Raw outlier"},
        {},
        overview,
    )

    assert view.projection is not None
    assert view.projection.inside_image is False
    assert view.render_status is EntityRenderStatus.REJECTED
    assert view.rejection_reasons == ("projection_outside_map_image",)
    assert view.projection.pixel_x != 0 or view.projection.pixel_y != 0
