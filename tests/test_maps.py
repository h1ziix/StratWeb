from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

import duckdb
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
)
from stratweb.application.spatial import ComputeSpatialStateService
from stratweb.application.temporal import ComputeTemporalStateService
from stratweb.main import create_app
from stratweb.maps.models import (
    MapCoordinateAvailability,
    MapLevel,
    MapRevisionKind,
    MapSelectionEvidence,
    MapSelectionStatus,
)
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.maps.transforms import map_to_world, world_to_map
from stratweb.maps.validation import validate_definition
from stratweb.spatial.engine import SpatialEngine
from stratweb.spatial.map_overviews import MapOverviewRegistry
from stratweb.spatial.models import SpatialExtraction, SpatialSourceSample


class _Extractor:
    def __init__(self, players: tuple[Any, ...]) -> None:
        self._players = players

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        del demo_path
        return SpatialExtraction(
            parser_name="demoparser2",
            parser_version="0.41.4",
            source_demo_sha256=expected_sha256,
            requested_ticks=ticks,
            samples=tuple(
                SpatialSourceSample(
                    tick=tick,
                    steam_id=player.steam_id,
                    player_name=player.current_name,
                    x=-3200 + index * 10,
                    y=1700 - index * 10,
                    z=0,
                    inventory_item_ids=(),
                )
                for tick in ticks
                for index, player in enumerate(self._players)
            ),
            source_columns=("tick", "steamid", "name", "X", "Y", "Z"),
            map_selection_evidence=MapSelectionEvidence(
                raw_map_name="de_mirage", patch_version="14171"
            ),
        )


def _asset_fixture(tmp_path: Path) -> tuple[Path, MapRegistry]:
    assets = tmp_path / "overviews"
    version = assets / "fixture-v1"
    version.mkdir(parents=True)
    image = version / "de_mirage.png"
    metadata = version / "de_mirage.txt"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1024, 1024)
    )
    metadata.write_text(
        '"de_mirage"\n{\n"pos_x" "-3230"\n"pos_y" "1713"\n"scale" "5"\n}\n',
        encoding="utf-8",
    )
    base = DEFAULT_MAP_REGISTRY.preferred_definition("de_mirage")
    assert base is not None and base.overview_asset is not None
    reference = base.overview_asset.model_copy(
        update={
            "asset_id": "de_mirage:fixture-v1:upper",
            "relative_path": "fixture-v1/de_mirage.png",
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
        }
    )
    definition = base.model_copy(
        update={"overview_asset": reference, "asset_version": "fixture-v1"}
    )
    return assets, MapRegistry((definition,))


def test_registry_exact_aliases_unknown_and_revision_selection() -> None:
    assert DEFAULT_MAP_REGISTRY.list_maps() == (
        "de_ancient",
        "de_anubis",
        "de_cache",
        "de_dust2",
        "de_inferno",
        "de_mirage",
        "de_nuke",
        "de_overpass",
    )
    assert DEFAULT_MAP_REGISTRY.canonicalize("dust_2") == "de_dust2"
    assert DEFAULT_MAP_REGISTRY.canonicalize(" MIRAGE ") == "de_mirage"
    assert DEFAULT_MAP_REGISTRY.canonicalize("mirag") is None
    unknown = DEFAULT_MAP_REGISTRY.select(MapSelectionEvidence(raw_map_name="de_train"))
    assert unknown.status is MapSelectionStatus.UNSUPPORTED
    assert unknown.selected_definition is None

    proven = DEFAULT_MAP_REGISTRY.select(
        MapSelectionEvidence(raw_map_name="overpass", patch_version="14171")
    )
    assert proven.status is MapSelectionStatus.PROVEN
    assert proven.evidence == ("patch_version:14171",)
    unproven = DEFAULT_MAP_REGISTRY.select(
        MapSelectionEvidence(raw_map_name="de_overpass", patch_version="14164")
    )
    assert unproven.status is MapSelectionStatus.UNPROVEN
    assert "map_layout_may_be_incompatible" in unproven.warnings
    manual = DEFAULT_MAP_REGISTRY.select(
        MapSelectionEvidence(
            raw_map_name="de_overpass",
            manual_revision="cs2-historical-overpass-layout-unresolved",
        )
    )
    assert manual.status is MapSelectionStatus.PROVEN
    assert manual.selected_definition is not None
    assert manual.selected_definition.transform_available is False


def test_revision_selection_rejects_conflicting_authoritative_evidence() -> None:
    base = DEFAULT_MAP_REGISTRY.preferred_definition("de_mirage")
    assert base is not None
    revision_a = base.model_copy(
        update={
            "map_revision": base.map_revision.model_copy(
                update={
                    "revision_id": "revision-a",
                    "compatible_patch_versions": ("patch-a",),
                    "compatible_map_crcs": ("crc-a",),
                }
            )
        }
    )
    revision_b = base.model_copy(
        update={
            "map_revision": base.map_revision.model_copy(
                update={
                    "revision_id": "revision-b",
                    "kind": MapRevisionKind.HISTORICAL,
                    "compatible_patch_versions": ("patch-b",),
                    "compatible_map_crcs": ("crc-b",),
                }
            )
        }
    )
    registry = MapRegistry((revision_a, revision_b))

    consistent = registry.select(
        MapSelectionEvidence(raw_map_name="de_mirage", patch_version="patch-a", map_crc="crc-a")
    )
    conflict = registry.select(
        MapSelectionEvidence(raw_map_name="de_mirage", patch_version="patch-a", map_crc="crc-b")
    )

    assert consistent.status is MapSelectionStatus.PROVEN
    assert consistent.selected_definition == revision_a
    assert conflict.status is MapSelectionStatus.UNSUPPORTED
    assert conflict.selected_definition is None
    assert conflict.warnings == ("map_revision_evidence_conflict",)


def test_all_configured_transforms_are_deterministic_not_mirrored_or_clamped() -> None:
    for canonical_name in DEFAULT_MAP_REGISTRY.list_maps():
        definition = DEFAULT_MAP_REGISTRY.preferred_definition(canonical_name)
        assert definition is not None
        validation = validate_definition(definition)
        assert validation.valid, (canonical_name, validation.warnings)
        assert "axis_orientation_no_mirror" in validation.checks
        assert definition.image_width is not None and definition.image_height is not None
        center_world = map_to_world(
            definition, definition.image_width / 2, definition.image_height / 2
        )
        center = world_to_map(definition, *center_world, 0)
        assert center.normalized_x == 0.5
        assert center.normalized_y == 0.5
        outside_world = map_to_world(definition, -10, -20)
        outside = world_to_map(definition, *outside_world, 0)
        assert outside.pixel_x is not None and abs(outside.pixel_x + 10) < 1e-9
        assert outside.pixel_y is not None and abs(outside.pixel_y + 20) < 1e-9
        assert outside.availability is MapCoordinateAvailability.PARTIAL
        assert outside.warnings == ("out_of_map_bounds",)


def test_nuke_level_policy_handles_upper_lower_missing_z_and_boundary() -> None:
    nuke = DEFAULT_MAP_REGISTRY.preferred_definition("de_nuke")
    assert nuke is not None
    assert world_to_map(nuke, -3453, 2887, 100).level is MapLevel.UPPER
    assert world_to_map(nuke, -3453, 2887, -600).level is MapLevel.LOWER
    missing = world_to_map(nuke, -3453, 2887, None)
    boundary = world_to_map(nuke, -3453, 2887, -495)
    assert missing.level is MapLevel.UNKNOWN
    assert "map_level_unavailable_without_z" in missing.warnings
    assert boundary.level is MapLevel.UNKNOWN
    assert "map_level_boundary_ambiguous" in boundary.warnings


def test_map_api_assets_cache_headers_and_no_filesystem_paths(tmp_path: Path) -> None:
    assets, registry = _asset_fixture(tmp_path)
    client = TestClient(
        create_app(
            tmp_path / "maps.duckdb",
            assets,
            map_registry=registry,
            map_developer_mode=True,
        )
    )
    listing = client.get("/api/maps")
    detail = client.get("/api/maps/de_mirage")
    revisions = client.get("/api/maps/de_mirage/revisions")
    transformed = client.get("/api/maps/de_mirage/transform?x=-3230&y=1713&z=0")
    assert listing.status_code == detail.status_code == revisions.status_code == 200
    assert transformed.json()["result"]["pixel_x"] == 0
    serialized = listing.text
    assert "relative_path" not in serialized
    assert str(tmp_path) not in serialized
    image_url = detail.json()["revisions"][0]["overview_urls"]["upper"]
    response = client.get(image_url)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"].startswith('"')
    assert client.get("/api/maps/de_train").status_code == 404
    assert (
        client.get("/assets/map-overviews/de_train/unknown-revision/upper.png").status_code == 404
    )
    assert client.get("/ui/maps/calibration?map_name=de_mirage").status_code == 200
    disabled = TestClient(create_app(tmp_path / "disabled.duckdb", assets, map_registry=registry))
    assert disabled.get("/ui/maps/calibration").status_code == 404


def test_registry_asset_cache_does_not_erase_run_selection_evidence(tmp_path: Path) -> None:
    assets, registry = _asset_fixture(tmp_path)
    definitions = MapOverviewRegistry(assets, registry)
    definition = registry.preferred_definition("de_mirage")
    assert definition is not None

    public = definitions.get_definition(definition)
    selection = registry.select(
        MapSelectionEvidence(raw_map_name="de_mirage", patch_version="unmatched-build")
    )
    pin = registry.pin(selection)
    pinned = definitions.get_for_run("de_mirage", pin)

    assert public.model.revision_selection_status is None
    assert pinned.model.revision_selection_status is MapSelectionStatus.UNPROVEN
    assert pinned.model.selection_evidence == ("unmatched_patch_version:unmatched-build",)
    assert "map_revision_unproven" in pinned.model.warnings


def test_spatial_run_pins_definition_and_registry_edits_do_not_reproject(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    assets, registry = _asset_fixture(tmp_path)
    dataset = canonical_dataset_factory("map-pin")
    database = tmp_path / "pin.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)
    ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        _Extractor(dataset.players),
        engine=SpatialEngine(registry),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    summary = spatial.get_summary(dataset.match.match_id)
    assert summary is not None and summary.map_semantics is not None
    assert summary.map_semantics.selection_status is MapSelectionStatus.PROVEN
    assert summary.legacy_map_semantics is False
    with duckdb.connect(str(database), read_only=True) as connection:
        persisted = connection.execute(
            "SELECT canonical_map_name, selected_map_revision, map_definition_version, "
            "overview_checksum, transform_rule_version, map_definition_fingerprint "
            "FROM spatial_runs"
        ).fetchone()
    assert persisted is not None and all(value is not None for value in persisted)

    original = registry.preferred_definition("de_mirage")
    assert original is not None and original.scale is not None
    edited_registry = MapRegistry((original.model_copy(update={"scale": original.scale + 1}),))
    unavailable = MapOverviewRegistry(assets, edited_registry).get_for_run(
        summary.map_model.map_name, summary.map_semantics
    )
    assert unavailable.image_path is None
    assert "pinned_map_definition_unavailable_or_changed" in unavailable.model.warnings


def test_legacy_spatial_run_is_read_without_backfilled_revision(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    _, registry = _asset_fixture(tmp_path)
    dataset = canonical_dataset_factory("legacy-map-run")
    database = tmp_path / "legacy.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    matches.save_match(dataset)
    ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)
    ComputeSpatialStateService(
        matches,
        temporal,
        spatial,
        _Extractor(dataset.players),
        engine=SpatialEngine(registry),
    ).compute(dataset.match.match_id, tmp_path / "ignored.dem")
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE spatial_runs SET spatial_schema_version='1.0.0', "
            "spatial_rule_version='1.1.0', canonical_map_name=NULL, "
            "selected_map_revision=NULL, map_definition_version=NULL, "
            "overview_checksum=NULL, transform_rule_version=NULL, "
            "map_definition_fingerprint=NULL, map_semantics=NULL"
        )
    summary = DuckDBSpatialRepository(database).get_summary(dataset.match.match_id)
    assert summary is not None
    assert summary.map_semantics is None
    assert summary.legacy_map_semantics is True
    run = DuckDBSpatialRepository(database).list_runs(dataset.match.match_id)[0]
    assert run.compatible is False
    assert run.legacy_map_semantics is True
    assert run.selected_by_default is True
