"""Zone set for de_dust2, revision cs2-1.41.7.1-d263aa1118fb.

Authored from the official callout reference supplied by the user, then
reviewed and adjusted by the user in the overlay editor (layout saved
2026-07-27T00:00:50.971199+00:00), which is the overlay verification step of the zone authoring
pipeline."""

from __future__ import annotations

from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)

_MAP_NAME = "de_dust2"
_MAP_REVISION = "cs2-1.41.7.1-d263aa1118fb"
_SOURCE = "user-reviewed layout from the overlay editor, saved 2026-07-27T00:00:50.971199+00:00"


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


DUST2_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _zone(
            'back_plat',
            'BACK PLAT',
            ZoneKind.AREA,
            0,
            (
                (-2139.4, 3164.6),
                (-1880.7, 3164.6),
                (-1875.4, 2950.4),
                (-2144.7, 2960.5),
            ),
        ),
        _zone(
            'back_site',
            'BACK SITE',
            ZoneKind.AREA,
            0,
            (
                (-1710.8, 2902.4),
                (-1358.8, 2902.4),
                (-1358.8, 2698.2),
                (-1710.8, 2698.2),
            ),
        ),
        _zone(
            'window',
            'WINDOW',
            ZoneKind.AREA,
            0,
            (
                (-1302.1, 2724.2),
                (-1082.1, 2724.2),
                (-1082.1, 2539.0),
                (-1302.1, 2539.0),
            ),
        ),
        _zone(
            'b_plat',
            'B PLAT',
            ZoneKind.AREA,
            0,
            (
                (-2141.2, 2961.8),
                (-1871.4, 2961.8),
                (-1866.2, 2555.2),
                (-2135.9, 2560.5),
            ),
        ),
        _zone(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            (
                (-1722.3, 2881.7),
                (-1356.6, 2866.3),
                (-1340.8, 2458.0),
                (-1732.8, 2484.4),
            ),
        ),
        _zone(
            'box',
            'BOX',
            ZoneKind.AREA,
            0,
            (
                (-1864.4, 2612.0),
                (-1757.5, 2617.3),
                (-1741.6, 2331.3),
                (-1859.1, 2320.7),
            ),
        ),
        _zone(
            'fence',
            'FENCE',
            ZoneKind.AREA,
            0,
            (
                (-2208.3, 2442.5),
                (-1996.1, 2442.5),
                (-2032.9, 2083.8),
                (-2213.6, 2078.5),
            ),
        ),
        _zone(
            'b_doors',
            'B DOORS',
            ZoneKind.AREA,
            0,
            (
                (-1510.4, 2378.0),
                (-1114.4, 2378.0),
                (-1114.4, 2053.3),
                (-1510.4, 2053.3),
            ),
        ),
        _zone(
            'ct_mid',
            'CT MID',
            ZoneKind.AREA,
            0,
            (
                (-534.7, 2589.1),
                (-94.7, 2589.1),
                (-100.0, 1996.2),
                (-540.0, 1996.2),
            ),
        ),
        _zone(
            'ct_spawn',
            'CT SPAWN',
            ZoneKind.SPAWN,
            10,
            (
                (81.3, 2565.8),
                (565.7, 2565.8),
                (565.7, 2102.5),
                (81.3, 2102.5),
            ),
        ),
        _zone(
            'ninja',
            'NINJA',
            ZoneKind.AREA,
            0,
            (
                (330.8, 2803.8),
                (591.7, 2772.2),
                (633.9, 2567.1),
                (325.9, 2567.1),
            ),
        ),
        _zone(
            'goose',
            'GOOSE',
            ZoneKind.AREA,
            0,
            (
                (989.4, 3089.0),
                (1173.8, 3083.7),
                (1179.1, 2864.1),
                (989.4, 2869.4),
            ),
        ),
        _zone(
            'barrels',
            'BARRELS',
            ZoneKind.AREA,
            0,
            (
                (1290.0, 3100.8),
                (1598.0, 3100.8),
                (1598.0, 2776.6),
                (1290.0, 2776.6),
            ),
        ),
        _zone(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            (
                (952.5, 2633.6),
                (1247.7, 2633.6),
                (1253.0, 2332.2),
                (947.2, 2337.4),
            ),
        ),
        _zone(
            'ramp',
            'RAMP',
            ZoneKind.AREA,
            0,
            (
                (1327.4, 2751.0),
                (1635.4, 2751.0),
                (1635.4, 2287.7),
                (1327.4, 2287.7),
            ),
        ),
        _zone(
            'boost',
            'BOOST',
            ZoneKind.AREA,
            0,
            (
                (545.0, 2400.4),
                (809.0, 2400.4),
                (809.0, 2168.5),
                (545.0, 2168.5),
            ),
        ),
        _zone(
            'cross',
            'CROSS',
            ZoneKind.AREA,
            0,
            (
                (1093.7, 2311.0),
                (1446.2, 2311.0),
                (1446.2, 2012.7),
                (1099.0, 2018.0),
            ),
        ),
        _zone(
            'car_a',
            'CAR',
            ZoneKind.AREA,
            0,
            (
                (1504.7, 2236.7),
                (1812.7, 2236.7),
                (1812.7, 1865.8),
                (1504.7, 1865.8),
            ),
        ),
        _zone(
            'dog',
            'DOG',
            ZoneKind.AREA,
            0,
            (
                (-2192.6, 2063.4),
                (-2036.9, 2068.7),
                (-2057.9, 1787.0),
                (-2176.8, 1787.0),
            ),
        ),
        _zone(
            'car_b',
            'CAR',
            ZoneKind.AREA,
            0,
            (
                (-1613.2, 1986.3),
                (-1305.2, 1986.3),
                (-1441.7, 1819.6),
                (-1550.1, 1709.3),
            ),
        ),
        _zone(
            'closet',
            'CLOSET',
            ZoneKind.AREA,
            0,
            (
                (-1631.9, 1964.5),
                (-1568.7, 1738.7),
                (-1600.2, 1597.1),
                (-1736.9, 1602.4),
            ),
        ),
        _zone(
            'lower_tunnels',
            'LOWER TUNNELS',
            ZoneKind.AREA,
            0,
            (
                (-1210.9, 1542.5),
                (-561.7, 1542.5),
                (-566.9, 1325.6),
                (-1221.4, 1330.8),
            ),
        ),
        _zone(
            'mid_doors',
            'MID DOORS',
            ZoneKind.AREA,
            0,
            (
                (-622.7, 1847.3),
                (-270.7, 1847.3),
                (-328.5, 1540.4),
                (-512.4, 1535.2),
            ),
        ),
        _zone(
            'stairs',
            'STAIRS',
            ZoneKind.AREA,
            0,
            (
                (226.0, 1911.5),
                (499.7, 1916.8),
                (510.2, 1555.8),
                (231.3, 1566.3),
            ),
        ),
        _zone(
            'short',
            'SHORT',
            ZoneKind.AREA,
            0,
            (
                (-62.5, 1544.2),
                (509.2, 1544.2),
                (498.7, 1351.8),
                (-62.5, 1325.6),
            ),
        ),
        _zone(
            'xbox',
            'XBOX',
            ZoneKind.AREA,
            0,
            (
                (-504.5, 1537.5),
                (-196.5, 1537.5),
                (-196.5, 1259.4),
                (-504.5, 1259.4),
            ),
        ),
        _zone(
            'upper_tunnels',
            'UPPER TUNNELS',
            ZoneKind.AREA,
            0,
            (
                (-2009.6, 1430.2),
                (-1447.7, 1430.2),
                (-1452.9, 1025.2),
                (-2020.1, 1035.7),
            ),
        ),
        _zone(
            'blue',
            'BLUE',
            ZoneKind.AREA,
            0,
            (
                (485.2, 1205.8),
                (749.2, 1205.8),
                (749.2, 927.7),
                (485.2, 927.7),
            ),
        ),
        _zone(
            'long',
            'LONG',
            ZoneKind.AREA,
            0,
            (
                (1226.2, 1731.6),
                (1622.2, 1731.6),
                (1622.2, 897.3),
                (1226.2, 897.3),
            ),
        ),
        _zone(
            'long_corner',
            'LONG CORNER',
            ZoneKind.AREA,
            0,
            (
                (917.7, 1219.8),
                (1214.3, 1225.1),
                (1224.8, 984.4),
                (917.7, 989.7),
            ),
        ),
        _zone(
            'cat',
            'CAT',
            ZoneKind.AREA,
            0,
            (
                (-292.7, 1257.3),
                (-131.8, 1257.3),
                (-126.5, 601.4),
                (-271.7, 585.6),
            ),
        ),
        _zone(
            'green',
            'GREEN',
            ZoneKind.AREA,
            0,
            (
                (-842.7, 688.3),
                (-511.7, 730.3),
                (-522.2, 197.1),
                (-690.4, 197.1),
            ),
        ),
        _zone(
            'palm',
            'PALM',
            ZoneKind.AREA,
            0,
            (
                (-221.5, 477.6),
                (107.5, 482.9),
                (102.3, 279.0),
                (-221.5, 279.0),
            ),
        ),
        _zone(
            'long_doors',
            'LONG DOORS',
            ZoneKind.AREA,
            0,
            (
                (501.0, 732.8),
                (774.3, 716.9),
                (774.3, 335.0),
                (516.9, 324.4),
            ),
        ),
        _zone(
            'pit',
            'PIT',
            ZoneKind.AREA,
            0,
            (
                (1265.9, 774.7),
                (1585.1, 769.4),
                (1585.1, 169.1),
                (1276.4, 174.4),
            ),
        ),
        _zone(
            'outside_tunnels',
            'OUTSIDE TUNNELS',
            ZoneKind.AREA,
            0,
            (
                (-1877.6, 410.2),
                (-1217.2, 410.2),
                (-1217.2, -99.3),
                (-1877.6, -99.3),
            ),
        ),
        _zone(
            'outside_long',
            'OUTSIDE LONG',
            ZoneKind.AREA,
            0,
            (
                (235.3, 178.8),
                (762.4, 178.8),
                (778.2, -404.6),
                (240.6, -415.2),
            ),
        ),
        _zone(
            'suicide',
            'SUICIDE',
            ZoneKind.AREA,
            0,
            (
                (-514.5, 27.0),
                (-373.7, 27.0),
                (-357.8, -583.7),
                (-514.5, -578.4),
            ),
        ),
        _zone(
            't_spawn',
            'T SPAWN',
            ZoneKind.SPAWN,
            10,
            (
                (-1183.7, -637.0),
                (-315.6, -647.1),
                (-320.9, -975.3),
                (-1183.7, -975.3),
            ),
        ),
    ),
)

__all__ = ["DUST2_ZONE_SET"]
