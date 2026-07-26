"""Structural validation and coverage diagnostics for zone sets."""

from __future__ import annotations

from stratweb.maps.models import MapDefinition
from stratweb.zones.engine import polygon_area, resolve_zone
from stratweb.zones.models import (
    ZoneResolutionStatus,
    ZoneSetDefinition,
)


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
            if polygon_area(polygon.vertices) == 0.0:
                issues.append(f"zero_area_polygon:{zone.zone_id}:{index}")
            if (
                polygon.min_z is not None
                and polygon.max_z is not None
                and polygon.min_z > polygon.max_z
            ):
                issues.append(f"inverted_z_bounds:{zone.zone_id}:{index}")
    return tuple(issues)


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


__all__ = ["sampled_coverage", "validate_zone_set"]
