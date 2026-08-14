"""Zone set for de_ancient, revision cs2-1.41.7.1-d263aa1118fb.

Authored from the official callout reference supplied by the user, then
reviewed and adjusted by the user in the overlay editor (layout saved
2026-07-26T23:35:46.956259+00:00), which is the overlay verification step of the zone authoring
pipeline."""

from __future__ import annotations

from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)

_MAP_NAME = "de_ancient"
_MAP_REVISION = "cs2-1.41.7.1-d263aa1118fb"
_SOURCE = "user-reviewed layout from the overlay editor, saved 2026-07-26T23:35:46.956259+00:00"


def _zone(
    zone_id: str,
    zone_name: str,
    kind: ZoneKind,
    priority: int,
    vertices: tuple[tuple[float, float], ...],
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=zone_id,
        zone_name=zone_name,
        kind=kind,
        map_name=_MAP_NAME,
        map_revision=_MAP_REVISION,
        priority=priority,
        polygons=(ZonePolygon(vertices=vertices),),
        verification=ZoneVerificationStatus.OVERLAY_VERIFIED,
        source=_SOURCE,
    )


ANCIENT_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _zone(
            "ct_spawn",
            "CT SPAWN",
            ZoneKind.SPAWN,
            10,
            (
                (-674.5, 1780.0),
                (-60.0, 1780.0),
                (-60.0, 1012.0),
                (-674.5, 1012.0),
            ),
        ),
        _zone(
            "t_spawn",
            "T SPAWN",
            ZoneKind.SPAWN,
            10,
            (
                (-726.0, -1957.5),
                (-265.0, -1957.5),
                (-265.0, -2521.0),
                (-726.0, -2521.0),
            ),
        ),
        _zone(
            "bombsite_a",
            "Bombsite A",
            ZoneKind.BOMBSITE,
            10,
            (
                (-1622.0, 961.0),
                (-1186.5, 961.0),
                (-1186.5, 653.5),
                (-1622.0, 653.5),
            ),
        ),
        _zone(
            "bombsite_b",
            "Bombsite B",
            ZoneKind.BOMBSITE,
            10,
            (
                (605.5, 218.5),
                (1168.5, 218.5),
                (1168.5, -140.0),
                (605.5, -140.0),
            ),
        ),
        _zone(
            "temple",
            "TEMPLE",
            ZoneKind.AREA,
            0,
            (
                (-1519.5, 1575.0),
                (-726.0, 1575.0),
                (-726.0, 1217.0),
                (-1519.5, 1217.0),
            ),
        ),
        _zone(
            "ct",
            "CT",
            ZoneKind.AREA,
            0,
            (
                (-1238.0, 1217.0),
                (-905.0, 1217.0),
                (-905.0, 961.0),
                (-1238.0, 961.0),
            ),
        ),
        _zone(
            "plat",
            "PLAT",
            ZoneKind.AREA,
            0,
            (
                (-2210.5, 1319.0),
                (-1750.0, 1319.0),
                (-1750.0, 833.0),
                (-2210.5, 833.0),
            ),
        ),
        _zone(
            "big_box",
            "BIG BOX",
            ZoneKind.AREA,
            0,
            (
                (-2057.0, 1140.0),
                (-1622.0, 1140.0),
                (-1622.0, 756.0),
                (-2057.0, 756.0),
            ),
        ),
        _zone(
            "triple",
            "TRIPLE",
            ZoneKind.AREA,
            0,
            (
                (-1186.5, 1012.0),
                (-854.0, 1012.0),
                (-854.0, 679.0),
                (-1186.5, 679.0),
            ),
        ),
        _zone(
            "sniper_nest",
            "SNIPER NEST",
            ZoneKind.AREA,
            0,
            (
                (-726.0, 1012.0),
                (-239.5, 1012.0),
                (-239.5, 602.5),
                (-726.0, 602.5),
            ),
        ),
        _zone(
            "alley",
            "ALLEY",
            ZoneKind.AREA,
            0,
            (
                (-60.0, 1063.0),
                (784.5, 1063.0),
                (784.5, 756.0),
                (-60.0, 756.0),
            ),
        ),
        _zone(
            "back_alley",
            "BACK ALLEY",
            ZoneKind.AREA,
            0,
            (
                (836.0, 1114.5),
                (1655.0, 1114.5),
                (1655.0, 781.5),
                (836.0, 781.5),
            ),
        ),
        _zone(
            "short_b",
            "SHORT",
            ZoneKind.AREA,
            0,
            (
                (631.0, 730.5),
                (1143.0, 730.5),
                (1143.0, 397.5),
                (631.0, 397.5),
            ),
        ),
        _zone(
            "long",
            "LONG",
            ZoneKind.AREA,
            0,
            (
                (1322.0, 807.0),
                (1757.5, 807.0),
                (1757.5, 321.0),
                (1322.0, 321.0),
            ),
        ),
        _zone(
            "red",
            "RED",
            ZoneKind.AREA,
            0,
            (
                (-623.5, 577.0),
                (-265.0, 577.0),
                (-265.0, 269.5),
                (-623.5, 269.5),
            ),
        ),
        _zone(
            "tree",
            "TREE",
            ZoneKind.AREA,
            0,
            (
                (-2031.5, 628.0),
                (-1622.0, 628.0),
                (-1622.0, 295.0),
                (-2031.5, 295.0),
            ),
        ),
        _zone(
            "a_main",
            "A MAIN",
            ZoneKind.AREA,
            0,
            (
                (-2364.0, 397.5),
                (-1903.5, 397.5),
                (-1903.5, -140.0),
                (-2364.0, -140.0),
            ),
        ),
        _zone(
            "short_a",
            "SHORT",
            ZoneKind.AREA,
            0,
            (
                (-1545.0, 628.0),
                (-1186.5, 628.0),
                (-1186.5, 13.5),
                (-1545.0, 13.5),
            ),
        ),
        _zone(
            "top_mid",
            "TOP MID",
            ZoneKind.AREA,
            0,
            (
                (-700.0, 244.0),
                (-239.5, 244.0),
                (-239.5, -140.0),
                (-700.0, -140.0),
            ),
        ),
        _zone(
            "cave",
            "CAVE",
            ZoneKind.AREA,
            0,
            (
                (349.5, 321.0),
                (682.0, 321.0),
                (682.0, -140.0),
                (349.5, -140.0),
            ),
        ),
        _zone(
            "donut",
            "DONUT",
            ZoneKind.AREA,
            0,
            (
                (-1673.0, 13.5),
                (-1084.0, 13.5),
                (-1084.0, -421.5),
                (-1673.0, -421.5),
            ),
        ),
        _zone(
            "wood",
            "WOOD",
            ZoneKind.AREA,
            0,
            (
                (656.5, -140.0),
                (1143.0, -140.0),
                (1143.0, -524.0),
                (656.5, -524.0),
            ),
        ),
        _zone(
            "pit",
            "PIT",
            ZoneKind.AREA,
            0,
            (
                (-342.0, -37.5),
                (42.0, -37.5),
                (42.0, -370.5),
                (-342.0, -370.5),
            ),
        ),
        _zone(
            "mid",
            "MID",
            ZoneKind.AREA,
            0,
            (
                (-751.5, -165.5),
                (-137.0, -165.5),
                (-137.0, -729.0),
                (-751.5, -729.0),
            ),
        ),
        _zone(
            "cat_room",
            "CAT ROOM",
            ZoneKind.AREA,
            0,
            (
                (42.0, -268.0),
                (528.5, -268.0),
                (528.5, -626.5),
                (42.0, -626.5),
            ),
        ),
        _zone(
            "ramp",
            "RAMP",
            ZoneKind.AREA,
            0,
            (
                (1092.0, -268.0),
                (1655.0, -268.0),
                (1655.0, -908.0),
                (1092.0, -908.0),
            ),
        ),
        _zone(
            "lower_mid",
            "LOWER MID",
            ZoneKind.AREA,
            0,
            (
                (-1186.5, -524.0),
                (-649.0, -524.0),
                (-649.0, -908.0),
                (-1186.5, -908.0),
            ),
        ),
        _zone(
            "cat",
            "CAT",
            ZoneKind.AREA,
            0,
            (
                (-290.5, -626.5),
                (119.0, -626.5),
                (119.0, -959.0),
                (-290.5, -959.0),
            ),
        ),
    ),
)

__all__ = ["ANCIENT_ZONE_SET"]
