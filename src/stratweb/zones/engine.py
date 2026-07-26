"""Deterministic point-to-zone resolution; no inference, no nearest-zone guessing."""

from __future__ import annotations

from math import isfinite

from stratweb.zones.models import (
    ZoneDefinition,
    ZoneResolution,
    ZoneResolutionStatus,
    ZoneSetDefinition,
)


def point_in_polygon(vertices: tuple[tuple[float, float], ...], x: float, y: float) -> bool:
    """Ray-casting containment test; points on an edge or vertex count as inside.

    Boundary inclusivity keeps the rule total and deterministic: a coordinate
    exactly on a shared border resolves to the higher-priority zone instead of
    depending on floating-point crossing direction.
    """

    if _on_boundary(vertices, x, y):
        return True
    inside = False
    count = len(vertices)
    j = count - 1
    for i in range(count):
        x_i, y_i = vertices[i]
        x_j, y_j = vertices[j]
        if (y_i > y) != (y_j > y):
            crossing_x = (x_j - x_i) * (y - y_i) / (y_j - y_i) + x_i
            if x < crossing_x:
                inside = not inside
        j = i
    return inside


def polygon_area(vertices: tuple[tuple[float, float], ...]) -> float:
    """Shoelace area; polygons are authored as simple rings."""

    total = 0.0
    count = len(vertices)
    j = count - 1
    for i in range(count):
        x_i, y_i = vertices[i]
        x_j, y_j = vertices[j]
        total += (x_j + x_i) * (y_j - y_i)
        j = i
    return abs(total) / 2.0


def zone_area(zone: ZoneDefinition) -> float:
    return sum(polygon_area(polygon.vertices) for polygon in zone.polygons)


def resolve_zone(
    zone_set: ZoneSetDefinition,
    x: float,
    y: float,
    z: float | None,
) -> ZoneResolution:
    """Resolve one world coordinate to a proven zone or an explicit unknown."""

    if not isfinite(x) or not isfinite(y) or (z is not None and not isfinite(z)):
        return _unknown(zone_set, ("nonfinite_world_coordinate",))

    warnings: list[str] = []
    matches: list[ZoneDefinition] = []
    for zone in zone_set.zones:
        matched, zone_warnings = _zone_contains(zone, x, y, z)
        warnings.extend(zone_warnings)
        if matched:
            matches.append(zone)

    if not matches:
        return _unknown(zone_set, tuple(warnings))

    if len(matches) > 1:
        warnings.append("overlapping_zones_resolved_by_priority")
    selected = min(matches, key=lambda zone: (-zone.priority, zone_area(zone), zone.zone_id))
    return ZoneResolution(
        status=ZoneResolutionStatus.RESOLVED,
        zone_id=selected.zone_id,
        zone_name=selected.zone_name,
        kind=selected.kind,
        level=selected.level,
        map_name=zone_set.map_name,
        map_revision=zone_set.map_revision,
        warnings=tuple(warnings),
    )


def _zone_contains(
    zone: ZoneDefinition,
    x: float,
    y: float,
    z: float | None,
) -> tuple[bool, tuple[str, ...]]:
    warnings: list[str] = []
    for polygon in zone.polygons:
        if not point_in_polygon(polygon.vertices, x, y):
            continue
        if polygon.min_z is None and polygon.max_z is None:
            return True, tuple(warnings)
        if z is None:
            # The polygon is altitude-constrained but the sample has no proven
            # z: the containment is not proven, so the zone must not match.
            warnings.append(f"zone_z_unproven:{zone.zone_id}")
            continue
        if (polygon.min_z is None or z >= polygon.min_z) and (
            polygon.max_z is None or z <= polygon.max_z
        ):
            return True, tuple(warnings)
    return False, tuple(warnings)


def _unknown(zone_set: ZoneSetDefinition, warnings: tuple[str, ...]) -> ZoneResolution:
    return ZoneResolution(
        status=ZoneResolutionStatus.UNKNOWN,
        map_name=zone_set.map_name,
        map_revision=zone_set.map_revision,
        warnings=warnings,
    )


def _on_boundary(vertices: tuple[tuple[float, float], ...], x: float, y: float) -> bool:
    count = len(vertices)
    j = count - 1
    for i in range(count):
        x_i, y_i = vertices[i]
        x_j, y_j = vertices[j]
        cross = (x_j - x_i) * (y - y_i) - (y_j - y_i) * (x - x_i)
        if (
            cross == 0.0
            and min(x_i, x_j) <= x <= max(x_i, x_j)
            and min(y_i, y_j) <= y <= max(y_i, y_j)
        ):
            return True
        j = i
    return False


__all__ = ["point_in_polygon", "polygon_area", "resolve_zone", "zone_area"]
