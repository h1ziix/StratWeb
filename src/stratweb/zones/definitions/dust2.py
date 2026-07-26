"""Proposed zone set for de_dust2, revision cs2-1.41.7.1-d263aa1118fb.

Callout names and relative placement follow the official callout reference
supplied by the user on 2026-07-27; boundaries were fitted to the pinned
overview asset via a four-anchor linear mapping (both spawn boxes and both
site markers; near-identity fit, residuals <= 0.02). Evidence: freeze-end
side centroids of match 28492216 and the Valve bombA/bombB anchors resolve
to their zones. Status PROPOSED pending the user's overlay check.
"""

from __future__ import annotations

from stratweb.maps.models import MapLevel
from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)

_MAP_NAME = "de_dust2"
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
    level: MapLevel = MapLevel.DEFAULT,
    min_z: float | None = None,
    max_z: float | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=zone_id,
        zone_name=zone_name,
        kind=kind,
        map_name=_MAP_NAME,
        map_revision=_MAP_REVISION,
        level=level,
        priority=priority,
        polygons=(ZonePolygon(vertices=corners, min_z=min_z, max_z=max_z),),
        verification=ZoneVerificationStatus.PROPOSED,
        source=_SOURCE,
)


DUST2_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _rect(
            'back_plat',
            'BACK PLAT',
            ZoneKind.AREA,
            0,
            ((-2207.6, 3238.0), (-1723.3, 3238.0), (-1723.3, 2913.5), (-2207.6, 2913.5)),
        ),
        _rect(
            'back_site',
            'BACK SITE',
            ZoneKind.AREA,
            0,
            ((-1679.3, 3038.6), (-1327.2, 3038.6), (-1327.2, 2834.7), (-1679.3, 2834.7)),
        ),
        _rect(
            'window',
            'WINDOW',
            ZoneKind.AREA,
            0,
            ((-1349.2, 2913.5), (-1129.1, 2913.5), (-1129.1, 2728.1), (-1349.2, 2728.1)),
        ),
        _rect(
            'b_plat',
            'B PLAT',
            ZoneKind.AREA,
            0,
            ((-2251.6, 2983.0), (-1855.4, 2983.0), (-1855.4, 2565.8), (-2251.6, 2565.8)),
        ),
        _rect(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            ((-1811.4, 2913.5), (-1283.1, 2913.5), (-1283.1, 2468.5), (-1811.4, 2468.5)),
        ),
        _rect(
            'box',
            'BOX',
            ZoneKind.AREA,
            0,
            ((-1864.2, 2612.2), (-1600.1, 2612.2), (-1600.1, 2352.6), (-1864.2, 2352.6)),
        ),
        _rect(
            'fence',
            'FENCE',
            ZoneKind.AREA,
            0,
            ((-2339.6, 2426.8), (-1943.4, 2426.8), (-1943.4, 1963.2), (-2339.6, 1963.2)),
        ),
        _rect(
            'b_doors',
            'B DOORS',
            ZoneKind.AREA,
            0,
            ((-1547.3, 2320.2), (-1151.1, 2320.2), (-1151.1, 1995.7), (-1547.3, 1995.7)),
        ),
        _rect(
            'ct_mid',
            'CT MID',
            ZoneKind.AREA,
            0,
            ((-534.8, 2589.0), (-94.6, 2589.0), (-94.6, 2032.8), (-534.8, 2032.8)),
        ),
        _rect(
            'ct_spawn',
            'CT SPAWN',
            ZoneKind.SPAWN,
            10,
            ((81.5, 2565.8), (565.7, 2565.8), (565.7, 2102.3), (81.5, 2102.3)),
        ),
        _rect(
            'ninja',
            'NINJA',
            ZoneKind.AREA,
            0,
            ((367.6, 3029.4), (675.7, 3029.4), (675.7, 2751.2), (367.6, 2751.2)),
        ),
        _rect(
            'goose',
            'GOOSE',
            ZoneKind.AREA,
            0,
            ((873.8, 3214.8), (1226.0, 3214.8), (1226.0, 2890.3), (873.8, 2890.3)),
        ),
        _rect(
            'barrels',
            'BARRELS',
            ZoneKind.AREA,
            0,
            ((1358.0, 3122.1), (1666.2, 3122.1), (1666.2, 2797.6), (1358.0, 2797.6)),
        ),
        _rect(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            ((873.8, 2728.1), (1358.0, 2728.1), (1358.0, 2310.9), (873.8, 2310.9)),
        ),
        _rect(
            'ramp',
            'RAMP',
            ZoneKind.AREA,
            0,
            ((1327.2, 2751.2), (1635.4, 2751.2), (1635.4, 2287.7), (1327.2, 2287.7)),
        ),
        _rect(
            'boost',
            'BOOST',
            ZoneKind.AREA,
            0,
            ((807.8, 2426.8), (1071.9, 2426.8), (1071.9, 2195.0), (807.8, 2195.0)),
        ),
        _rect(
            'cross',
            'CROSS',
            ZoneKind.AREA,
            0,
            ((1093.9, 2310.9), (1446.1, 2310.9), (1446.1, 1986.4), (1093.9, 1986.4)),
        ),
        _rect(
            'car_a',
            'CAR',
            ZoneKind.AREA,
            0,
            ((1578.1, 2357.2), (1886.3, 2357.2), (1886.3, 1986.4), (1578.1, 1986.4)),
        ),
        _rect(
            'dog',
            'DOG',
            ZoneKind.AREA,
            0,
            ((-2339.6, 2079.1), (-2031.5, 2079.1), (-2031.5, 1708.3), (-2339.6, 1708.3)),
        ),
        _rect(
            'car_b',
            'CAR',
            ZoneKind.AREA,
            0,
            ((-1613.3, 1986.4), (-1305.2, 1986.4), (-1305.2, 1661.9), (-1613.3, 1661.9)),
        ),
        _rect(
            'closet',
            'CLOSET',
            ZoneKind.AREA,
            0,
            ((-1679.3, 1754.6), (-1327.2, 1754.6), (-1327.2, 1476.5), (-1679.3, 1476.5)),
        ),
        _rect(
            'lower_tunnels',
            'LOWER TUNNELS',
            ZoneKind.AREA,
            0,
            ((-1195.1, 1731.5), (-666.9, 1731.5), (-666.9, 1267.9), (-1195.1, 1267.9)),
        ),
        _rect(
            'mid_doors',
            'MID DOORS',
            ZoneKind.AREA,
            0,
            ((-622.8, 1847.3), (-270.7, 1847.3), (-270.7, 1430.2), (-622.8, 1430.2)),
        ),
        _rect(
            'stairs',
            'STAIRS',
            ZoneKind.AREA,
            0,
            ((147.5, 1916.9), (499.7, 1916.9), (499.7, 1592.4), (147.5, 1592.4)),
        ),
        _rect(
            'short',
            'SHORT',
            ZoneKind.AREA,
            0,
            ((37.4, 1638.8), (477.6, 1638.8), (477.6, 1267.9), (37.4, 1267.9)),
        ),
        _rect(
            'xbox',
            'XBOX',
            ZoneKind.AREA,
            0,
            ((-446.8, 1453.3), (-138.6, 1453.3), (-138.6, 1175.2), (-446.8, 1175.2)),
        ),
        _rect(
            'upper_tunnels',
            'UPPER TUNNELS',
            ZoneKind.AREA,
            0,
            ((-2009.5, 1430.2), (-1437.2, 1430.2), (-1437.2, 920.3), (-2009.5, 920.3)),
        ),
        _rect(
            'blue',
            'BLUE',
            ZoneKind.AREA,
            0,
            ((411.6, 1221.6), (675.7, 1221.6), (675.7, 943.5), (411.6, 943.5)),
        ),
        _rect(
            'long',
            'LONG',
            ZoneKind.AREA,
            0,
            ((1226.0, 1731.5), (1622.2, 1731.5), (1622.2, 897.1), (1226.0, 897.1)),
        ),
        _rect(
            'long_corner',
            'LONG CORNER',
            ZoneKind.AREA,
            0,
            ((917.8, 1314.3), (1314.0, 1314.3), (1314.0, 989.8), (917.8, 989.8)),
        ),
        _rect(
            'cat',
            'CAT',
            ZoneKind.AREA,
            0,
            ((-292.7, 1267.9), (15.4, 1267.9), (15.4, 711.7), (-292.7, 711.7)),
        ),
        _rect(
            'green',
            'GREEN',
            ZoneKind.AREA,
            0,
            ((-842.9, 688.5), (-490.8, 688.5), (-490.8, 317.7), (-842.9, 317.7)),
        ),
        _rect(
            'palm',
            'PALM',
            ZoneKind.AREA,
            0,
            ((-226.7, 734.9), (81.5, 734.9), (81.5, 410.4), (-226.7, 410.4)),
        ),
        _rect(
            'long_doors',
            'LONG DOORS',
            ZoneKind.AREA,
            0,
            ((411.6, 711.7), (763.8, 711.7), (763.8, 387.2), (411.6, 387.2)),
        ),
        _rect(
            'pit',
            'PIT',
            ZoneKind.AREA,
            0,
            ((1292.0, 711.7), (1732.2, 711.7), (1732.2, 248.1), (1292.0, 248.1)),
        ),
        _rect(
            'outside_tunnels',
            'OUTSIDE TUNNELS',
            ZoneKind.AREA,
            0,
            ((-1877.4, 410.4), (-1217.1, 410.4), (-1217.1, -99.5), (-1877.4, -99.5)),
        ),
        _rect(
            'outside_long',
            'OUTSIDE LONG',
            ZoneKind.AREA,
            0,
            ((235.5, 178.6), (851.8, 178.6), (851.8, -331.3), (235.5, -331.3)),
        ),
        _rect(
            'suicide',
            'SUICIDE',
            ZoneKind.AREA,
            0,
            ((-666.9, 16.4), (-226.7, 16.4), (-226.7, -447.2), (-666.9, -447.2)),
        ),
        _rect(
            't_spawn',
            'T SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-1063.0, -678.9), (-446.8, -678.9), (-446.8, -1096.1), (-1063.0, -1096.1)),
        ),
    ),
)

__all__ = ["DUST2_ZONE_SET"]
