from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from stratweb.main import create_app
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY
from stratweb.zones.definitions import (
    ALL_ZONE_SETS,
    ANCIENT_ZONE_SET,
    ANUBIS_ZONE_SET,
    DUST2_ZONE_SET,
    INFERNO_ZONE_SET,
    MIRAGE_ZONE_SET,
    NUKE_ZONE_SET,
    OVERPASS_ZONE_SET,
    zone_set_for,
)
from stratweb.zones.engine import point_in_polygon, polygon_area, resolve_zone
from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneResolutionStatus,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)
from stratweb.zones.proposals import proposal_zone_set
from stratweb.zones.validation import sampled_coverage, validate_zone_set

_SQUARE = ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0))


def _zone(
    zone_id: str,
    vertices: tuple[tuple[float, float], ...] = _SQUARE,
    *,
    kind: ZoneKind = ZoneKind.AREA,
    priority: int = 0,
    min_z: float | None = None,
    max_z: float | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=zone_id,
        zone_name=zone_id.replace("_", " ").title(),
        kind=kind,
        map_name="de_test",
        map_revision="rev-1",
        priority=priority,
        polygons=(ZonePolygon(vertices=vertices, min_z=min_z, max_z=max_z),),
        verification=ZoneVerificationStatus.PROPOSED,
        source="unit fixture",
    )


def _zone_set(*zones: ZoneDefinition) -> ZoneSetDefinition:
    return ZoneSetDefinition(
        map_name="de_test",
        map_revision="rev-1",
        zones=zones,
        source="unit fixture",
    )


def test_point_in_polygon_interior_exterior_and_boundary() -> None:
    assert point_in_polygon(_SQUARE, 50.0, 50.0) is True
    assert point_in_polygon(_SQUARE, 150.0, 50.0) is False
    assert point_in_polygon(_SQUARE, 0.0, 0.0) is True  # vertex
    assert point_in_polygon(_SQUARE, 50.0, 0.0) is True  # edge
    assert point_in_polygon(_SQUARE, 100.0, 100.0) is True  # far vertex


def test_resolve_inside_and_outside() -> None:
    zone_set = _zone_set(_zone("site_a", kind=ZoneKind.BOMBSITE))
    inside = resolve_zone(zone_set, 10.0, 10.0, None)
    outside = resolve_zone(zone_set, 500.0, 500.0, None)

    assert inside.status is ZoneResolutionStatus.RESOLVED
    assert inside.zone_id == "site_a"
    assert inside.kind is ZoneKind.BOMBSITE
    assert inside.map_revision == "rev-1"
    assert outside.status is ZoneResolutionStatus.UNKNOWN
    assert outside.zone_id is None


def test_altitude_constrained_zone_requires_proven_z() -> None:
    zone_set = _zone_set(_zone("lower_ramp", min_z=-1000.0, max_z=-400.0))

    with_z = resolve_zone(zone_set, 50.0, 50.0, -500.0)
    wrong_z = resolve_zone(zone_set, 50.0, 50.0, 200.0)
    missing_z = resolve_zone(zone_set, 50.0, 50.0, None)

    assert with_z.status is ZoneResolutionStatus.RESOLVED
    assert wrong_z.status is ZoneResolutionStatus.UNKNOWN
    assert missing_z.status is ZoneResolutionStatus.UNKNOWN
    assert "zone_z_unproven:lower_ramp" in missing_z.warnings


def test_overlap_resolves_by_priority_then_area_then_id() -> None:
    small = ((40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0))
    by_priority = resolve_zone(
        _zone_set(_zone("wide", priority=0), _zone("choke", small, priority=5)),
        50.0,
        50.0,
        None,
    )
    by_area = resolve_zone(
        _zone_set(_zone("wide"), _zone("inner", small)),
        50.0,
        50.0,
        None,
    )
    by_id = resolve_zone(
        _zone_set(_zone("b_twin"), _zone("a_twin")),
        50.0,
        50.0,
        None,
    )

    assert by_priority.zone_id == "choke"
    assert "overlapping_zones_resolved_by_priority" in by_priority.warnings
    assert by_area.zone_id == "inner"
    assert by_id.zone_id == "a_twin"


def test_nonfinite_coordinates_are_unknown() -> None:
    zone_set = _zone_set(_zone("site_a"))
    result = resolve_zone(zone_set, float("nan"), 10.0, None)

    assert result.status is ZoneResolutionStatus.UNKNOWN
    assert result.warnings == ("nonfinite_world_coordinate",)


def test_fingerprint_is_stable_and_content_sensitive() -> None:
    zone_set = _zone_set(_zone("site_a"))
    same = _zone_set(_zone("site_a"))
    renamed = _zone_set(_zone("site_b"))

    assert zone_set.fingerprint() == same.fingerprint()
    assert zone_set.fingerprint() != renamed.fingerprint()


def test_validate_zone_set_reports_structural_issues() -> None:
    degenerate = ((0.0, 0.0), (100.0, 0.0), (200.0, 0.0))
    zone_set = ZoneSetDefinition(
        map_name="de_test",
        map_revision="rev-1",
        zones=(
            _zone("site_a"),
            _zone("site_a"),
            _zone("flat", degenerate),
            _zone("inverted", min_z=100.0, max_z=-100.0),
            ZoneDefinition(
                zone_id="foreign",
                zone_name="Foreign",
                kind=ZoneKind.AREA,
                map_name="de_other",
                map_revision="rev-2",
                polygons=(ZonePolygon(vertices=_SQUARE),),
                source="unit fixture",
            ),
        ),
        source="unit fixture",
    )

    issues = validate_zone_set(zone_set)

    assert "duplicate_zone_id:site_a" in issues
    assert "zero_area_polygon:flat:0" in issues
    assert "inverted_z_bounds:inverted:0" in issues
    assert "zone_map_mismatch:foreign" in issues
    assert "zone_revision_mismatch:foreign" in issues


def test_polygon_area_shoelace() -> None:
    assert polygon_area(_SQUARE) == 10000.0
    triangle = ((0.0, 0.0), (10.0, 0.0), (0.0, 10.0))
    assert polygon_area(triangle) == 50.0


def test_mirage_zone_set_is_structurally_valid_and_registered() -> None:
    assert validate_zone_set(MIRAGE_ZONE_SET) == ()
    assert len(MIRAGE_ZONE_SET.fingerprint()) == 64
    assert zone_set_for("de_mirage", "cs2-1.41.7.1-d263aa1118fb") is MIRAGE_ZONE_SET
    assert zone_set_for("de_mirage", "other-revision") is None
    assert zone_set_for("de_cache", "cs2-1.41.7.1-d263aa1118fb") is None


def test_mirage_zones_resolve_known_evidence_points() -> None:
    # Freeze-end side centroids of match e0f188cf round 1 (see
    # tests/test_maps_ground_truth.py) and Valve bombA/bombB overview anchors
    # converted to world through the pinned calibration (-3230/1713, scale 5).
    t_spawn = resolve_zone(MIRAGE_ZONE_SET, 1184.0, -171.4, None)
    ct_spawn = resolve_zone(MIRAGE_ZONE_SET, -1716.8, -1889.6, None)
    site_a = resolve_zone(MIRAGE_ZONE_SET, -465.2, -2178.2, None)
    site_b = resolve_zone(MIRAGE_ZONE_SET, -2052.4, 279.4, None)
    far_outside = resolve_zone(MIRAGE_ZONE_SET, 20_000.0, 20_000.0, None)

    assert t_spawn.zone_id == "t_spawn"
    assert ct_spawn.zone_id == "ct_spawn"
    assert site_a.zone_id == "bombsite_a"
    assert site_a.kind is ZoneKind.BOMBSITE
    assert site_b.zone_id == "bombsite_b"
    assert far_outside.status is ZoneResolutionStatus.UNKNOWN


def test_ancient_zone_set_is_valid_and_resolves_evidence_points() -> None:
    assert validate_zone_set(ANCIENT_ZONE_SET) == ()
    assert zone_set_for("de_ancient", "cs2-1.41.7.1-d263aa1118fb") is ANCIENT_ZONE_SET

    # Freeze-end side centroids of match 24708cef round 1 (tick 10705) and the
    # Valve bombA/bombB overview anchors converted through the pinned
    # calibration (-2953/2164, scale 5).
    ct_spawn = resolve_zone(ANCIENT_ZONE_SET, -345.6, 1702.4, None)
    t_spawn = resolve_zone(ANCIENT_ZONE_SET, -456.0, -2262.4, None)
    site_a = resolve_zone(ANCIENT_ZONE_SET, -1365.8, 884.0, None)
    site_b = resolve_zone(ANCIENT_ZONE_SET, 1143.0, 116.0, None)
    far_outside = resolve_zone(ANCIENT_ZONE_SET, 20_000.0, 20_000.0, None)

    assert ct_spawn.zone_id == "ct_spawn"
    assert t_spawn.zone_id == "t_spawn"
    assert site_a.zone_id == "bombsite_a"
    assert site_b.zone_id == "bombsite_b"
    assert far_outside.status is ZoneResolutionStatus.UNKNOWN


def test_all_authored_zone_sets_are_structurally_valid() -> None:
    for zone_set in ALL_ZONE_SETS:
        assert validate_zone_set(zone_set) == (), zone_set.map_name
        assert zone_set_for(zone_set.map_name, zone_set.map_revision) is zone_set


def test_dust2_zones_resolve_demo_and_anchor_evidence() -> None:
    # Freeze-end centroids of match 28492216 round 1 and Valve site anchors
    # through the rotation-baked dust2 calibration (-2476/3239, scale 4.4).
    assert resolve_zone(DUST2_ZONE_SET, -704.0, -796.0, None).zone_id == "t_spawn"
    assert resolve_zone(DUST2_ZONE_SET, 257.0, 2415.0, None).zone_id == "ct_spawn"
    assert resolve_zone(DUST2_ZONE_SET, 1128.5, 2518.1, None).zone_id == "bombsite_a"
    assert resolve_zone(DUST2_ZONE_SET, -1529.8, 2698.3, None).zone_id == "bombsite_b"


def test_overpass_zones_resolve_demo_evidence() -> None:
    # Sites are checked against where match dba336bb actually left the bomb:
    # rounds 2/8/23 cluster on A, rounds 1/7/9/13/14/18/21 on B. Spawns use the
    # freeze-end positions of round 1.
    assert resolve_zone(OVERPASS_ZONE_SET, -2549.0, 645.0, None).zone_id == "bombsite_a"
    assert resolve_zone(OVERPASS_ZONE_SET, -1166.0, -67.0, None).zone_id == "bombsite_b"
    assert resolve_zone(OVERPASS_ZONE_SET, -1430.8, -3137.1, None).zone_id == "t_spawn"
    # Every CT starts inside the spawn box even though it overlaps the A-site
    # outline on this radar; the smaller same-priority zone wins deterministically.
    for spawn_x, spawn_y in ((-2343.0, 797.0), (-2273.0, 770.0), (-2199.0, 740.0)):
        assert resolve_zone(OVERPASS_ZONE_SET, spawn_x, spawn_y, None).zone_id == "ct_spawn"


def test_overpass_zones_cover_only_walkable_space() -> None:
    # The boundaries are traced from the radar's walkable pixels, so points in
    # the void around the map resolve to unknown rather than to a nearby zone.
    for void_x, void_y in ((-4700.0, 1700.0), (300.0, -3000.0), (-4700.0, -3000.0)):
        assert resolve_zone(OVERPASS_ZONE_SET, void_x, void_y, None).status is (
            ZoneResolutionStatus.UNKNOWN
        )


def test_inferno_and_anubis_zones_resolve_valve_anchors() -> None:
    # No local demos yet: Valve overview anchors only.
    assert resolve_zone(INFERNO_ZONE_SET, 2428.8, 2113.9, None).zone_id == "ct_spawn"
    assert resolve_zone(INFERNO_ZONE_SET, -1585.2, 508.2, None).zone_id == "t_spawn"
    assert resolve_zone(INFERNO_ZONE_SET, 1977.3, 407.9, None).zone_id == "bombsite_a"
    assert resolve_zone(INFERNO_ZONE_SET, 371.6, 2766.1, None).zone_id == "bombsite_b"
    assert resolve_zone(ANUBIS_ZONE_SET, 464.6, 2152.0, None).zone_id == "ct_spawn"
    assert resolve_zone(ANUBIS_ZONE_SET, 304.3, -1643.1, None).zone_id == "t_spawn"


def test_nuke_zones_split_levels_by_proven_altitude() -> None:
    # The user placed one CT Spawn box per floor and the sites on their own
    # levels, so altitude is what separates them.
    assert resolve_zone(NUKE_ZONE_SET, -2018.4, -1058.2, None).zone_id == "t_spawn"
    assert resolve_zone(NUKE_ZONE_SET, 2356.2, -489.1, 0.0).zone_id == "ct_spawn_upper"
    assert resolve_zone(NUKE_ZONE_SET, 2362.0, -479.4, -700.0).zone_id == "ct_spawn_lower"
    assert resolve_zone(NUKE_ZONE_SET, 686.8, -731.0, 0.0).zone_id == "bombsite_a"
    assert resolve_zone(NUKE_ZONE_SET, 630.3, -1043.8, -700.0).zone_id == "bombsite_b"
    # A floor-bound zone never matches without a proven altitude.
    assert resolve_zone(NUKE_ZONE_SET, 630.3, -1043.8, None).status is ZoneResolutionStatus.UNKNOWN
    assert resolve_zone(NUKE_ZONE_SET, 630.3, -1043.8, 0.0).status is ZoneResolutionStatus.UNKNOWN


def test_nuke_proposal_preserves_altitude_semantics() -> None:
    from stratweb.maps.models import MapLevel

    square = [[500.0, -500.0], [900.0, -500.0], [900.0, -900.0], [500.0, -900.0]]
    payload = {
        "map_name": "de_nuke",
        "revision_id": _MIRAGE_REVISION,
        "saved_at": "2026-07-27T00:00:00+00:00",
        "zones": [
            {"zone_id": "bombsite_a", "polygon": square},
            {
                "zone_id": "kennels",
                "zone_name": "KENNELS",
                "kind": "area",
                "origin": "user",
                "level": "lower",
                "max_z": -495.0,
                "polygon": square,
            },
        ],
    }

    effective, issues = proposal_zone_set(payload, NUKE_ZONE_SET, "de_nuke", _MIRAGE_REVISION)

    assert effective is not None
    assert issues == ()
    site_a = next(zone for zone in effective.zones if zone.zone_id == "bombsite_a")
    assert site_a.level is MapLevel.UPPER
    assert site_a.polygons[0].min_z == -495.0
    user_zone = next(zone for zone in effective.zones if zone.zone_id == "kennels")
    assert user_zone.level is MapLevel.LOWER
    assert user_zone.polygons[0].max_z == -495.0


def test_zone_overlay_endpoints_are_disabled_without_developer_mode(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "zones.duckdb")) as client:
        page = client.get("/ui/dev/zones/de_mirage")
        data = client.get("/api/dev/zones/de_mirage")

    assert page.status_code == 404
    assert data.status_code == 404


_MIRAGE_REVISION = "cs2-1.41.7.1-d263aa1118fb"
_JUNGLE_POLYGON = [
    [-1386.8, -1461.4],
    [-874.8, -1461.4],
    [-874.8, -1871.0],
    [-1386.8, -1871.0],
]


def test_zone_proposal_endpoint_is_gated_validated_and_persisted(tmp_path: Path) -> None:
    overviews = tmp_path / "map_overviews"
    overviews.mkdir()
    valid = {
        "map_name": "de_mirage",
        "revision_id": _MIRAGE_REVISION,
        "zones": [
            {"zone_id": "jungle", "polygon": _JUNGLE_POLYGON},
            {
                "zone_id": "balkon",
                "zone_name": "Балкон",
                "kind": "chokepoint",
                "origin": "user",
                "polygon": [[-2000.0, 900.0], [-1800.0, 900.0], [-1900.0, 700.0]],
            },
        ],
    }

    with TestClient(create_app(tmp_path / "off.duckdb", overviews)) as client:
        blocked = client.post("/api/dev/zones/de_mirage/proposal", json=valid)

    with TestClient(
        create_app(tmp_path / "on.duckdb", overviews, map_developer_mode=True)
    ) as client:
        saved = client.post("/api/dev/zones/de_mirage/proposal", json=valid)
        nameless_new = client.post(
            "/api/dev/zones/de_mirage/proposal",
            json={
                **valid,
                "zones": [{"zone_id": "nope", "polygon": _JUNGLE_POLYGON}],
            },
        )
        bad_kind = client.post(
            "/api/dev/zones/de_mirage/proposal",
            json={
                **valid,
                "zones": [
                    {
                        "zone_id": "custom",
                        "zone_name": "Custom",
                        "kind": "heatmap",
                        "polygon": _JUNGLE_POLYGON,
                    }
                ],
            },
        )
        mismatch = client.post(
            "/api/dev/zones/de_mirage/proposal",
            json={**valid, "revision_id": "other-revision"},
        )
        overlay = client.get("/api/dev/zones/de_mirage")

    assert blocked.status_code == 404
    assert saved.status_code == 200
    assert saved.json() == {"saved": True, "file": "de_mirage.json", "zone_count": 2}
    proposal_file = tmp_path / "zone_proposals" / "de_mirage.json"
    stored = json.loads(proposal_file.read_text(encoding="utf-8"))
    assert stored["revision_id"] == _MIRAGE_REVISION
    assert {zone["zone_id"] for zone in stored["zones"]} == {"jungle", "balkon"}
    assert nameless_new.status_code == 422
    assert bad_kind.status_code == 422
    assert mismatch.status_code == 409

    # The saved layout replaces the authored set on the overlay endpoints.
    body = overlay.json()
    assert body["proposal_active"] is True
    assert {zone["zone_id"] for zone in body["zones"]} == {"jungle", "balkon"}
    by_id = {zone["zone_id"]: zone for zone in body["zones"]}
    assert by_id["balkon"]["origin"] == "user"
    assert by_id["balkon"]["zone_name"] == "Балкон"
    assert by_id["jungle"]["origin"] == "authored"
    assert by_id["jungle"]["verification"] == "overlay_verified"


def test_legacy_rect_proposal_is_converted_and_preferred(tmp_path: Path) -> None:
    overviews = tmp_path / "map_overviews"
    overviews.mkdir()
    proposals = tmp_path / "zone_proposals"
    proposals.mkdir()
    # Format written by the first editor version (two world corners).
    (proposals / "de_mirage.json").write_text(
        json.dumps(
            {
                "map_name": "de_mirage",
                "revision_id": _MIRAGE_REVISION,
                "saved_at": "2026-07-26T21:18:10+00:00",
                "zones": [
                    {"zone_id": "jungle", "x1": -1300.0, "y1": -1500.0, "x2": -900.0, "y2": -1800.0}
                ],
            }
        ),
        encoding="utf-8",
    )

    with TestClient(
        create_app(tmp_path / "legacy.duckdb", overviews, map_developer_mode=True)
    ) as client:
        overlay = client.get("/api/dev/zones/de_mirage")
        page = client.get("/ui/dev/zones/de_mirage")

    body = overlay.json()
    assert body["proposal_active"] is True
    assert [zone["zone_id"] for zone in body["zones"]] == ["jungle"]
    jungle = body["zones"][0]
    assert jungle["verification"] == "overlay_verified"
    assert len(jungle["polygons_px"][0]) == 4
    assert page.status_code == 200
    assert "zoneEditorData" in page.text

    # Geometry, not just vertex count: the rect interior resolves to the zone.
    effective, _ = proposal_zone_set(
        json.loads((proposals / "de_mirage.json").read_text(encoding="utf-8")),
        MIRAGE_ZONE_SET,
        "de_mirage",
        _MIRAGE_REVISION,
    )
    assert effective is not None
    center = resolve_zone(effective, -1100.0, -1650.0, None)
    outside = resolve_zone(effective, -2000.0, -1650.0, None)
    assert center.zone_id == "jungle"
    assert outside.status is ZoneResolutionStatus.UNKNOWN


def test_unusable_proposal_files_fall_back_with_issue(tmp_path: Path) -> None:
    overviews = tmp_path / "map_overviews"
    overviews.mkdir()
    proposals = tmp_path / "zone_proposals"
    proposals.mkdir()
    proposal_file = proposals / "de_mirage.json"

    with TestClient(
        create_app(tmp_path / "fallback.duckdb", overviews, map_developer_mode=True)
    ) as client:
        proposal_file.write_text("{ this is not json", encoding="utf-8")
        corrupt = client.get("/api/dev/zones/de_mirage")

        proposal_file.write_text(
            json.dumps(
                {
                    "map_name": "de_mirage",
                    "revision_id": "stale-revision",
                    "zones": [{"zone_id": "jungle", "polygon": _JUNGLE_POLYGON}],
                }
            ),
            encoding="utf-8",
        )
        stale = client.get("/api/dev/zones/de_mirage")

    corrupt_body = corrupt.json()
    assert corrupt.status_code == 200
    assert corrupt_body["proposal_active"] is False
    assert "proposal_file_unreadable" in corrupt_body["issues"]
    assert len(corrupt_body["zones"]) == len(MIRAGE_ZONE_SET.zones)

    stale_body = stale.json()
    assert stale.status_code == 200
    assert stale_body["proposal_active"] is False
    assert "proposal_map_or_revision_mismatch" in stale_body["issues"]
    assert len(stale_body["zones"]) == len(MIRAGE_ZONE_SET.zones)


def test_user_origin_zone_keeps_name_kind_and_priority_over_authored_id() -> None:
    payload = {
        "map_name": "de_mirage",
        "revision_id": _MIRAGE_REVISION,
        "saved_at": "2026-07-27T00:00:00+00:00",
        "zones": [
            {
                "zone_id": "mid",
                "zone_name": "Мид по-новому",
                "kind": "chokepoint",
                "origin": "user",
                "polygon": _JUNGLE_POLYGON,
            }
        ],
    }

    effective, issues = proposal_zone_set(
        payload, MIRAGE_ZONE_SET, "de_mirage", _MIRAGE_REVISION
    )

    assert effective is not None
    assert issues == ()
    zone = effective.zones[0]
    assert zone.zone_id == "mid"
    assert zone.zone_name == "Мид по-новому"
    assert zone.kind is ZoneKind.CHOKEPOINT
    assert zone.priority == 5


def test_proposal_zone_set_replaces_layout_and_reports_issues() -> None:
    payload = {
        "map_name": "de_mirage",
        "revision_id": _MIRAGE_REVISION,
        "saved_at": "2026-07-27T00:00:00+00:00",
        "zones": [
            {"zone_id": "jungle", "polygon": _JUNGLE_POLYGON},
            {"zone_id": "new_area", "polygon": _JUNGLE_POLYGON},
            {
                "zone_id": "named",
                "zone_name": "Named",
                "kind": "spawn",
                "polygon": [[0.0, 0.0], [1.0, 0.0]],
            },
        ],
    }

    effective, issues = proposal_zone_set(
        payload, MIRAGE_ZONE_SET, "de_mirage", _MIRAGE_REVISION
    )

    assert effective is not None
    assert [zone.zone_id for zone in effective.zones] == ["jungle"]
    jungle = effective.zones[0]
    assert jungle.verification is ZoneVerificationStatus.OVERLAY_VERIFIED
    assert jungle.zone_name == "JUNGLE"
    assert jungle.kind is ZoneKind.AREA
    assert "proposal_new_zone_missing_name:new_area" in issues
    assert "proposal_invalid_polygon:named" in issues

    mismatched, mismatch_issues = proposal_zone_set(
        {**payload, "revision_id": "other"},
        MIRAGE_ZONE_SET,
        "de_mirage",
        _MIRAGE_REVISION,
    )
    assert mismatched is None
    assert mismatch_issues == ("proposal_map_or_revision_mismatch",)


def test_sampled_coverage_against_real_map_definition() -> None:
    definition = DEFAULT_MAP_REGISTRY.preferred_definition("de_mirage")
    assert definition is not None
    assert definition.world_origin_x is not None
    assert definition.world_origin_y is not None
    assert definition.scale is not None
    assert definition.image_width is not None

    world_span = definition.image_width * definition.scale
    half = ZoneSetDefinition(
        map_name="de_mirage",
        map_revision=definition.map_revision.revision_id,
        zones=(
            ZoneDefinition(
                zone_id="left_half",
                zone_name="Left Half",
                kind=ZoneKind.AREA,
                map_name="de_mirage",
                map_revision=definition.map_revision.revision_id,
                polygons=(
                    ZonePolygon(
                        vertices=(
                            (definition.world_origin_x, definition.world_origin_y),
                            (definition.world_origin_x + world_span / 2, definition.world_origin_y),
                            (
                                definition.world_origin_x + world_span / 2,
                                definition.world_origin_y - world_span,
                            ),
                            (definition.world_origin_x, definition.world_origin_y - world_span),
                        )
                    ),
                ),
                source="unit fixture",
            ),
        ),
        source="unit fixture",
    )

    coverage = sampled_coverage(half, definition, samples_per_axis=16)

    assert abs(coverage - 0.5) < 0.05
