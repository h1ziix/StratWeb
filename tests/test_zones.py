from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from stratweb.main import create_app
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY
from stratweb.zones.definitions import MIRAGE_ZONE_SET, zone_set_for
from stratweb.zones.engine import point_in_polygon, polygon_area, resolve_zone
from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneResolutionStatus,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)
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
    assert zone_set_for("de_dust2", "cs2-1.41.7.1-d263aa1118fb") is None


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


def test_zone_overlay_endpoints_are_disabled_without_developer_mode(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "zones.duckdb")) as client:
        page = client.get("/ui/dev/zones/de_mirage")
        data = client.get("/api/dev/zones/de_mirage")

    assert page.status_code == 404
    assert data.status_code == 404


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
