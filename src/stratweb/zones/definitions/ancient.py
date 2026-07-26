"""Proposed zone set for de_ancient, revision cs2-1.41.7.1-d263aa1118fb.

Callout names and relative placement follow the official callout reference
supplied by the user on 2026-07-27; boundaries were fitted to the pinned
overview asset through a four-anchor linear mapping (both spawn boxes and
both site markers are visible on the reference and the asset; y-fit residual
<= 0.005, x-fit <= 0.03). Evidence: freeze-end side centroids of match
24708cef and the Valve bombA/bombB anchors resolve to their zones. Status
PROPOSED pending the user's overlay check."""

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
_SOURCE = (
    "official callout reference supplied by the user (2026-07-27), fitted to the "
    "pinned overview asset via spawn/site anchors; pending overlay check"
)


def _rect(
    zone_id: str,
    zone_name: str,
    kind: ZoneKind,
    priority: int,
    corners: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ],
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=zone_id,
        zone_name=zone_name,
        kind=kind,
        map_name=_MAP_NAME,
        map_revision=_MAP_REVISION,
        priority=priority,
        polygons=(ZonePolygon(vertices=corners),),
        verification=ZoneVerificationStatus.PROPOSED,
        source=_SOURCE,
    )


ANCIENT_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _rect(
            'ct_spawn',
            'CT SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-674.6, 1780.0), (-60.2, 1780.0), (-60.2, 1012.0), (-674.6, 1012.0)),
        ),
        _rect(
            't_spawn',
            'T SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-725.8, -1957.6), (-265.0, -1957.6), (-265.0, -2520.8), (-725.8, -2520.8)),
        ),
        _rect(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            ((-1621.8, 960.8), (-1186.6, 960.8), (-1186.6, 653.6), (-1621.8, 653.6)),
        ),
        _rect(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            ((605.4, 218.4), (1168.6, 218.4), (1168.6, -140.0), (605.4, -140.0)),
        ),
        _rect(
            'temple',
            'TEMPLE',
            ZoneKind.AREA,
            0,
            ((-1519.4, 1575.2), (-725.8, 1575.2), (-725.8, 1216.8), (-1519.4, 1216.8)),
        ),
        _rect(
            'ct',
            'CT',
            ZoneKind.AREA,
            0,
            ((-1237.8, 1216.8), (-905.0, 1216.8), (-905.0, 960.8), (-1237.8, 960.8)),
        ),
        _rect(
            'plat',
            'PLAT',
            ZoneKind.AREA,
            0,
            ((-2210.6, 1319.2), (-1749.8, 1319.2), (-1749.8, 832.8), (-2210.6, 832.8)),
        ),
        _rect(
            'big_box',
            'BIG BOX',
            ZoneKind.AREA,
            0,
            ((-2057.0, 1140.0), (-1621.8, 1140.0), (-1621.8, 756.0), (-2057.0, 756.0)),
        ),
        _rect(
            'triple',
            'TRIPLE',
            ZoneKind.AREA,
            0,
            ((-1186.6, 1012.0), (-853.8, 1012.0), (-853.8, 679.2), (-1186.6, 679.2)),
        ),
        _rect(
            'sniper_nest',
            'SNIPER NEST',
            ZoneKind.AREA,
            0,
            ((-725.8, 1012.0), (-239.4, 1012.0), (-239.4, 602.4), (-725.8, 602.4)),
        ),
        _rect(
            'alley',
            'ALLEY',
            ZoneKind.AREA,
            0,
            ((-60.2, 1063.2), (784.6, 1063.2), (784.6, 756.0), (-60.2, 756.0)),
        ),
        _rect(
            'back_alley',
            'BACK ALLEY',
            ZoneKind.AREA,
            0,
            ((835.8, 1114.4), (1655.0, 1114.4), (1655.0, 781.6), (835.8, 781.6)),
        ),
        _rect(
            'short_b',
            'SHORT',
            ZoneKind.AREA,
            0,
            ((631.0, 730.4), (1143.0, 730.4), (1143.0, 397.6), (631.0, 397.6)),
        ),
        _rect(
            'long',
            'LONG',
            ZoneKind.AREA,
            0,
            ((1322.2, 807.2), (1757.4, 807.2), (1757.4, 320.8), (1322.2, 320.8)),
        ),
        _rect(
            'red',
            'RED',
            ZoneKind.AREA,
            0,
            ((-623.4, 576.8), (-265.0, 576.8), (-265.0, 269.6), (-623.4, 269.6)),
        ),
        _rect(
            'tree',
            'TREE',
            ZoneKind.AREA,
            0,
            ((-2031.4, 628.0), (-1621.8, 628.0), (-1621.8, 295.2), (-2031.4, 295.2)),
        ),
        _rect(
            'a_main',
            'A MAIN',
            ZoneKind.AREA,
            0,
            ((-2364.2, 397.6), (-1903.4, 397.6), (-1903.4, -140.0), (-2364.2, -140.0)),
        ),
        _rect(
            'short_a',
            'SHORT',
            ZoneKind.AREA,
            0,
            ((-1545.0, 628.0), (-1186.6, 628.0), (-1186.6, 13.6), (-1545.0, 13.6)),
        ),
        _rect(
            'top_mid',
            'TOP MID',
            ZoneKind.AREA,
            0,
            ((-700.2, 244.0), (-239.4, 244.0), (-239.4, -140.0), (-700.2, -140.0)),
        ),
        _rect(
            'cave',
            'CAVE',
            ZoneKind.AREA,
            0,
            ((349.4, 320.8), (682.2, 320.8), (682.2, -140.0), (349.4, -140.0)),
        ),
        _rect(
            'donut',
            'DONUT',
            ZoneKind.AREA,
            0,
            ((-1673.0, 13.6), (-1084.2, 13.6), (-1084.2, -421.6), (-1673.0, -421.6)),
        ),
        _rect(
            'wood',
            'WOOD',
            ZoneKind.AREA,
            0,
            ((656.6, -140.0), (1143.0, -140.0), (1143.0, -524.0), (656.6, -524.0)),
        ),
        _rect(
            'pit',
            'PIT',
            ZoneKind.AREA,
            0,
            ((-341.8, -37.6), (42.2, -37.6), (42.2, -370.4), (-341.8, -370.4)),
        ),
        _rect(
            'mid',
            'MID',
            ZoneKind.AREA,
            0,
            ((-751.4, -165.6), (-137.0, -165.6), (-137.0, -728.8), (-751.4, -728.8)),
        ),
        _rect(
            'cat_room',
            'CAT ROOM',
            ZoneKind.AREA,
            0,
            ((42.2, -268.0), (528.6, -268.0), (528.6, -626.4), (42.2, -626.4)),
        ),
        _rect(
            'ramp',
            'RAMP',
            ZoneKind.AREA,
            0,
            ((1091.8, -268.0), (1655.0, -268.0), (1655.0, -908.0), (1091.8, -908.0)),
        ),
        _rect(
            'lower_mid',
            'LOWER MID',
            ZoneKind.AREA,
            0,
            ((-1186.6, -524.0), (-649.0, -524.0), (-649.0, -908.0), (-1186.6, -908.0)),
        ),
        _rect(
            'cat',
            'CAT',
            ZoneKind.AREA,
            0,
            ((-290.6, -626.4), (119.0, -626.4), (119.0, -959.2), (-290.6, -959.2)),
        ),
    ),
)

__all__ = ["ANCIENT_ZONE_SET"]
