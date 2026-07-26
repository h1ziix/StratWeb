"""Structural and synthetic validation for immutable map definitions."""

from __future__ import annotations

from math import isclose

from stratweb.maps.models import MapDefinition, MapValidationResult
from stratweb.maps.transforms import map_to_world, world_to_map


def validate_definition(definition: MapDefinition) -> MapValidationResult:
    checks: list[str] = []
    warnings: list[str] = []
    if not definition.transform_available:
        return MapValidationResult(
            canonical_name=definition.canonical_name,
            revision_id=definition.map_revision.revision_id,
            definition_fingerprint=definition.definition_fingerprint,
            valid=definition.validation_status.value == "unsupported",
            checks=("unsupported_revision_is_explicit",),
            warnings=("map_transform_unavailable",),
        )
    assert definition.image_width is not None
    assert definition.image_height is not None
    points = (
        (0.0, 0.0),
        (definition.image_width / 2, definition.image_height / 2),
        (float(definition.image_width), float(definition.image_height)),
    )
    for pixel_x, pixel_y in points:
        world_x, world_y = map_to_world(definition, pixel_x, pixel_y)
        result = world_to_map(definition, world_x, world_y, 0.0)
        if result.pixel_x is None or result.pixel_y is None:
            warnings.append("round_trip_unavailable")
            continue
        if not isclose(result.pixel_x, pixel_x) or not isclose(result.pixel_y, pixel_y):
            warnings.append("round_trip_mismatch")
    if not warnings:
        checks.append("raw_coordinate_round_trip")
    origin = world_to_map(
        definition,
        definition.world_origin_x or 0.0,
        definition.world_origin_y or 0.0,
        0.0,
    )
    if origin.pixel_x == 0.0 and origin.pixel_y == 0.0:
        checks.append("upper_left_origin")
    else:
        warnings.append("origin_orientation_mismatch")
    right = world_to_map(
        definition,
        (definition.world_origin_x or 0.0) + (definition.scale or 1.0),
        definition.world_origin_y or 0.0,
        0.0,
    )
    down = world_to_map(
        definition,
        definition.world_origin_x or 0.0,
        (definition.world_origin_y or 0.0) - (definition.scale or 1.0),
        0.0,
    )
    if (
        right.pixel_x is not None
        and down.pixel_y is not None
        and isclose(right.pixel_x, 1.0)
        and isclose(down.pixel_y, 1.0)
    ):
        checks.append("axis_orientation_no_mirror")
    else:
        warnings.append("axis_orientation_mismatch")
    return MapValidationResult(
        canonical_name=definition.canonical_name,
        revision_id=definition.map_revision.revision_id,
        definition_fingerprint=definition.definition_fingerprint,
        valid=not warnings,
        checks=tuple(checks),
        warnings=tuple(warnings),
    )
