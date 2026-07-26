"""Pure deterministic world/overview transforms; no rendering side effects."""

from __future__ import annotations

from math import isfinite

from stratweb.maps.models import (
    LevelPolicyKind,
    MapCoordinateAvailability,
    MapCoordinateResult,
    MapDefinition,
    MapLevel,
)


def world_to_map(
    definition: MapDefinition,
    x: float,
    y: float,
    z: float | None,
) -> MapCoordinateResult:
    """Project Source 2 world coordinates without clamping or inferred correction."""

    if not isfinite(x) or not isfinite(y) or (z is not None and not isfinite(z)):
        return MapCoordinateResult(
            availability=MapCoordinateAvailability.UNAVAILABLE,
            warnings=("nonfinite_world_coordinate",),
        )
    if not definition.transform_available:
        return MapCoordinateResult(
            availability=MapCoordinateAvailability.UNAVAILABLE,
            warnings=("map_transform_unavailable",),
        )
    assert definition.world_origin_x is not None
    assert definition.world_origin_y is not None
    assert definition.scale is not None
    assert definition.image_width is not None
    assert definition.image_height is not None

    # Valve overview metadata describes the upper-left world coordinate. `rotate`
    # describes image preparation and is already baked into the shipped radar texture.
    pixel_x = (x - definition.world_origin_x) / definition.scale
    pixel_y = (definition.world_origin_y - y) / definition.scale
    normalized_x = pixel_x / definition.image_width
    normalized_y = pixel_y / definition.image_height
    warnings: list[str] = []
    availability = MapCoordinateAvailability.AVAILABLE
    if not (0.0 <= normalized_x <= 1.0 and 0.0 <= normalized_y <= 1.0):
        warnings.append("out_of_map_bounds")
        availability = MapCoordinateAvailability.PARTIAL
    level, level_warnings = _resolve_level(definition, z)
    warnings.extend(level_warnings)
    if (
        level is MapLevel.UNKNOWN
        and definition.level_policy.kind is not LevelPolicyKind.SINGLE_LEVEL
    ):
        availability = MapCoordinateAvailability.PARTIAL
    return MapCoordinateResult(
        normalized_x=normalized_x,
        normalized_y=normalized_y,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        level=level,
        availability=availability,
        warnings=tuple(warnings),
    )


def map_to_world(definition: MapDefinition, pixel_x: float, pixel_y: float) -> tuple[float, float]:
    """Inverse of the planar transform, used by deterministic validation."""

    if not definition.transform_available:
        raise ValueError("map transform is unavailable")
    if not isfinite(pixel_x) or not isfinite(pixel_y):
        raise ValueError("pixel coordinates must be finite")
    assert definition.world_origin_x is not None
    assert definition.world_origin_y is not None
    assert definition.scale is not None
    return (
        definition.world_origin_x + pixel_x * definition.scale,
        definition.world_origin_y - pixel_y * definition.scale,
    )


def _resolve_level(definition: MapDefinition, z: float | None) -> tuple[MapLevel, tuple[str, ...]]:
    policy = definition.level_policy
    if policy.kind is LevelPolicyKind.SINGLE_LEVEL:
        return MapLevel.DEFAULT, ()
    if z is None:
        return MapLevel.UNKNOWN, ("map_level_unavailable_without_z",)
    upper_min = policy.upper_min_z
    lower_max = policy.lower_max_z
    if upper_min is None or lower_max is None:
        return MapLevel.UNKNOWN, ("map_level_policy_incomplete",)
    if policy.boundary_is_ambiguous and z == upper_min == lower_max:
        return MapLevel.UNKNOWN, ("map_level_boundary_ambiguous",)
    if z > upper_min or (z == upper_min and not policy.boundary_is_ambiguous):
        return MapLevel.UPPER, ()
    if z < lower_max or (z == lower_max and not policy.boundary_is_ambiguous):
        return MapLevel.LOWER, ()
    return MapLevel.UNKNOWN, ("map_level_not_covered_by_policy",)
