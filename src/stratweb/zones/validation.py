"""Structural validation and coverage diagnostics for zone sets."""

from __future__ import annotations

from stratweb.maps.models import MapDefinition
from stratweb.zones.engine import polygon_area, resolve_zone
from stratweb.zones.models import (
    ZoneResolutionStatus,
    ZoneSetDefinition,
)

Point = tuple[float, float]
ZONE_VALIDATION_RULE_VERSION = "simple_polygon_v1"


def validate_zone_set(zone_set: ZoneSetDefinition) -> tuple[str, ...]:
    """Return deterministic issue codes; an empty tuple means structurally valid."""

    issues: list[str] = []
    seen: set[str] = set()
    for zone in zone_set.zones:
        if zone.zone_id in seen:
            issues.append(f"duplicate_zone_id:{zone.zone_id}")
        seen.add(zone.zone_id)
        if zone.map_name != zone_set.map_name:
            issues.append(f"zone_map_mismatch:{zone.zone_id}")
        if zone.map_revision != zone_set.map_revision:
            issues.append(f"zone_revision_mismatch:{zone.zone_id}")
        for index, polygon in enumerate(zone.polygons):
            vertices = polygon.vertices
            if polygon_area(vertices) == 0.0:
                issues.append(f"zero_area_polygon:{zone.zone_id}:{index}")
            for first, second in _repeated_vertices(vertices):
                issues.append(f"repeated_vertex:{zone.zone_id}:{index}:{first}:{second}")
            for edge in _zero_length_edges(vertices):
                issues.append(f"zero_length_edge:{zone.zone_id}:{index}:{edge}")
            for first_edge, second_edge in _self_intersections(vertices):
                issues.append(
                    f"self_intersection:{zone.zone_id}:{index}:{first_edge}:{second_edge}"
                )
            if (
                polygon.min_z is not None
                and polygon.max_z is not None
                and polygon.min_z > polygon.max_z
            ):
                issues.append(f"inverted_z_bounds:{zone.zone_id}:{index}")
    return tuple(issues)


def _repeated_vertices(vertices: tuple[Point, ...]) -> tuple[tuple[int, int], ...]:
    """Return repeated vertex indexes without treating the ring as explicitly closed."""

    return tuple(
        (first, second)
        for first in range(len(vertices))
        for second in range(first + 1, len(vertices))
        if vertices[first] == vertices[second]
    )


def _zero_length_edges(vertices: tuple[Point, ...]) -> tuple[int, ...]:
    count = len(vertices)
    return tuple(
        index for index in range(count) if vertices[index] == vertices[(index + 1) % count]
    )


def _self_intersections(vertices: tuple[Point, ...]) -> tuple[tuple[int, int], ...]:
    """Return pairs of non-adjacent edges that touch, cross, or overlap.

    ``ZonePolygon.vertices`` stores an implicit closing edge. Adjacent edges
    necessarily share one endpoint and are excluded; any contact between
    non-adjacent edges means the authored ring is not a simple polygon.
    """

    intersections: list[tuple[int, int]] = []
    count = len(vertices)
    for first in range(count):
        for second in range(first + 1, count):
            if second == first + 1 or (first == 0 and second == count - 1):
                continue
            if _segments_intersect(
                vertices[first],
                vertices[(first + 1) % count],
                vertices[second],
                vertices[(second + 1) % count],
            ):
                intersections.append((first, second))
    return tuple(intersections)


def _segments_intersect(first: Point, second: Point, third: Point, fourth: Point) -> bool:
    first_orientation = _orientation(first, second, third)
    second_orientation = _orientation(first, second, fourth)
    third_orientation = _orientation(third, fourth, first)
    fourth_orientation = _orientation(third, fourth, second)

    if (
        (first_orientation > 0.0 > second_orientation)
        or (first_orientation < 0.0 < second_orientation)
    ) and (
        (third_orientation > 0.0 > fourth_orientation)
        or (third_orientation < 0.0 < fourth_orientation)
    ):
        return True

    return (
        (first_orientation == 0.0 and _point_on_segment(first, second, third))
        or (second_orientation == 0.0 and _point_on_segment(first, second, fourth))
        or (third_orientation == 0.0 and _point_on_segment(third, fourth, first))
        or (fourth_orientation == 0.0 and _point_on_segment(third, fourth, second))
    )


def _orientation(first: Point, second: Point, third: Point) -> float:
    return (second[0] - first[0]) * (third[1] - first[1]) - (second[1] - first[1]) * (
        third[0] - first[0]
    )


def _point_on_segment(first: Point, second: Point, point: Point) -> bool:
    return min(first[0], second[0]) <= point[0] <= max(first[0], second[0]) and min(
        first[1], second[1]
    ) <= point[1] <= max(first[1], second[1])


def sampled_coverage(
    zone_set: ZoneSetDefinition,
    definition: MapDefinition,
    samples_per_axis: int = 64,
) -> float:
    """Fraction of a deterministic world-space grid resolving to any zone.

    The grid spans the world rectangle covered by the map image (derived from
    the calibrated origin/scale), so the number is a diagnostic of authoring
    progress, not a claim that unresolved space is walkable.
    """

    if (
        definition.world_origin_x is None
        or definition.world_origin_y is None
        or definition.scale is None
        or definition.image_width is None
        or definition.image_height is None
    ):
        raise ValueError("Map definition has no calibrated transform for coverage sampling.")
    width_world = definition.image_width * definition.scale
    height_world = definition.image_height * definition.scale
    resolved = 0
    total = samples_per_axis * samples_per_axis
    for row in range(samples_per_axis):
        for column in range(samples_per_axis):
            x = definition.world_origin_x + width_world * (column + 0.5) / samples_per_axis
            y = definition.world_origin_y - height_world * (row + 0.5) / samples_per_axis
            result = resolve_zone(zone_set, x, y, None)
            if result.status is ZoneResolutionStatus.RESOLVED:
                resolved += 1
    return resolved / total


__all__ = [
    "ZONE_VALIDATION_RULE_VERSION",
    "sampled_coverage",
    "validate_zone_set",
]
