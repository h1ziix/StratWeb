"""User zone-layout proposals: hand-placed boundaries layered over authored sets.

A proposal is the user's manual layout saved by the developer overlay editor.
When present it fully replaces the authored zone list for its map revision:
zones the user kept or drew are rendered and resolved with their hand-placed
polygons (verification OVERLAY_VERIFIED — manual placement is the overlay
review), and authored zones absent from the proposal are treated as deleted.
"""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path
from typing import Any

from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)

_DEFAULT_PRIORITY: dict[ZoneKind, int] = {
    ZoneKind.BOMBSITE: 10,
    ZoneKind.SPAWN: 10,
    ZoneKind.CHOKEPOINT: 5,
}


def load_zone_proposal(path: Path) -> dict[str, Any] | None:
    """Read a saved proposal file; any structural failure means no proposal."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def proposal_zone_set(
    payload: dict[str, Any],
    base: ZoneSetDefinition | None,
    map_name: str,
    map_revision: str,
) -> tuple[ZoneSetDefinition | None, tuple[str, ...]]:
    """Build the effective zone set from a proposal payload.

    Returns (zone_set, issues). A `None` zone set means the proposal was
    unusable and the caller should fall back to the authored set. Individual
    invalid entries are skipped with deterministic issue codes instead of
    discarding the user's whole layout.
    """

    if payload.get("map_name") != map_name or payload.get("revision_id") != map_revision:
        return None, ("proposal_map_or_revision_mismatch",)
    raw_zones = payload.get("zones")
    if not isinstance(raw_zones, list) or not raw_zones:
        return None, ("proposal_zones_missing",)

    base_by_id = {zone.zone_id: zone for zone in base.zones} if base is not None else {}
    zones: list[ZoneDefinition] = []
    issues: list[str] = []
    seen: set[str] = set()
    for entry in raw_zones:
        if not isinstance(entry, dict):
            issues.append("proposal_entry_not_object")
            continue
        zone_id = entry.get("zone_id")
        if not isinstance(zone_id, str) or not zone_id:
            issues.append("proposal_entry_missing_zone_id")
            continue
        if zone_id in seen:
            issues.append(f"proposal_duplicate_zone_id:{zone_id}")
            continue
        vertices = _entry_vertices(entry)
        if vertices is None:
            issues.append(f"proposal_invalid_polygon:{zone_id}")
            continue
        authored = base_by_id.get(zone_id)
        # A zone the editor marked origin="user" keeps its own name/kind even
        # when its slug matches a deleted authored zone id.
        use_authored = authored is not None and entry.get("origin") != "user"
        if use_authored:
            assert authored is not None
            zone_name = authored.zone_name
            kind = authored.kind
            priority = authored.priority
            level = authored.level
        else:
            raw_name = entry.get("zone_name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                issues.append(f"proposal_new_zone_missing_name:{zone_id}")
                continue
            zone_name = " ".join(raw_name.split())[:100]
            kind = _parse_kind(entry.get("kind"))
            priority = _DEFAULT_PRIORITY.get(kind, 0)
            level = ZoneDefinition.model_fields["level"].default
        try:
            zones.append(
                ZoneDefinition(
                    zone_id=zone_id,
                    zone_name=zone_name,
                    kind=kind,
                    map_name=map_name,
                    map_revision=map_revision,
                    level=level,
                    priority=priority,
                    polygons=(ZonePolygon(vertices=vertices),),
                    verification=ZoneVerificationStatus.OVERLAY_VERIFIED,
                    source=_zone_source(payload, use_authored),
                )
            )
        except ValueError:
            issues.append(f"proposal_invalid_zone:{zone_id}")
            continue
        seen.add(zone_id)
    if not zones:
        return None, tuple(issues) or ("proposal_zones_missing",)
    return (
        ZoneSetDefinition(
            map_name=map_name,
            map_revision=map_revision,
            zones=tuple(zones),
            source=_zone_source(payload, True),
        ),
        tuple(issues),
    )


def _entry_vertices(entry: dict[str, Any]) -> tuple[tuple[float, float], ...] | None:
    polygon = entry.get("polygon")
    if polygon is not None:
        if not isinstance(polygon, list) or len(polygon) < 3 or len(polygon) > 200:
            return None
        vertices: list[tuple[float, float]] = []
        for point in polygon:
            if not isinstance(point, list | tuple) or len(point) != 2:
                return None
            x, y = point
            if not isinstance(x, int | float) or not isinstance(y, int | float):
                return None
            if not isfinite(float(x)) or not isfinite(float(y)):
                return None
            vertices.append((float(x), float(y)))
        return tuple(vertices)
    # Legacy rectangle entries from the first editor version: two world
    # corners in any order.
    corner_values: list[float] = []
    for key in ("x1", "y1", "x2", "y2"):
        value = entry.get(key)
        if not isinstance(value, int | float):
            return None
        corner_values.append(float(value))
    x1, y1, x2, y2 = corner_values
    if not all(isfinite(value) for value in (x1, y1, x2, y2)):
        return None
    low_x, high_x = sorted((x1, x2))
    low_y, high_y = sorted((y1, y2))
    if low_x == high_x or low_y == high_y:
        return None
    return ((low_x, high_y), (high_x, high_y), (high_x, low_y), (low_x, low_y))


def _parse_kind(value: Any) -> ZoneKind:
    if isinstance(value, str):
        try:
            return ZoneKind(value)
        except ValueError:
            return ZoneKind.AREA
    return ZoneKind.AREA


def _zone_source(payload: dict[str, Any], known: bool) -> str:
    saved_at = payload.get("saved_at")
    stamp = saved_at if isinstance(saved_at, str) else "unknown time"
    base = "user hand-placed layout" if known else "user hand-drawn zone"
    return f"{base} saved {stamp}"


__all__ = ["load_zone_proposal", "proposal_zone_set"]
