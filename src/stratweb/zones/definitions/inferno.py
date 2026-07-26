"""Proposed zone set for de_inferno, revision cs2-1.41.7.1-d263aa1118fb.

Callout names and relative placement follow the official callout reference
supplied by the user on 2026-07-27; boundaries were fitted to the pinned
overview asset via a four-anchor linear mapping (both spawn boxes and both
site markers; residuals <= 0.03). No local demo exists for inferno yet, so
the evidence check uses the Valve spawn/site anchors only. Status PROPOSED
pending the user's overlay check.
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

_MAP_NAME = "de_inferno"
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


INFERNO_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _rect(
            'garden',
            'GARDEN',
            ZoneKind.AREA,
            0,
            ((300.3, 3280.0), (817.7, 3280.0), (817.7, 3011.2), (300.3, 3011.2)),
        ),
        _rect(
            'dark',
            'DARK',
            ZoneKind.AREA,
            0,
            ((-320.5, 3033.6), (-10.1, 3033.6), (-10.1, 2809.6), (-320.5, 2809.6)),
        ),
        _rect(
            'coffins',
            'COFFINS',
            ZoneKind.AREA,
            0,
            ((41.7, 3123.2), (403.8, 3123.2), (403.8, 2899.2), (41.7, 2899.2)),
        ),
        _rect(
            'church',
            'CHURCH',
            ZoneKind.AREA,
            0,
            ((740.1, 3100.8), (1257.5, 3100.8), (1257.5, 2787.2), (740.1, 2787.2)),
        ),
        _rect(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            ((171.0, 2899.2), (688.4, 2899.2), (688.4, 2406.4), (171.0, 2406.4)),
        ),
        _rect(
            'pool',
            'POOL',
            ZoneKind.AREA,
            0,
            ((688.4, 2787.2), (1050.5, 2787.2), (1050.5, 2518.4), (688.4, 2518.4)),
        ),
        _rect(
            'fountain',
            'FOUNTAIN',
            ZoneKind.AREA,
            0,
            ((-10.1, 2540.8), (455.6, 2540.8), (455.6, 2316.8), (-10.1, 2316.8)),
        ),
        _rect(
            'ct',
            'CT',
            ZoneKind.AREA,
            0,
            ((1076.4, 2787.2), (1386.8, 2787.2), (1386.8, 2518.4), (1076.4, 2518.4)),
        ),
        _rect(
            'third',
            '3RD',
            ZoneKind.AREA,
            0,
            ((-372.2, 2428.8), (-61.8, 2428.8), (-61.8, 2160.0), (-372.2, 2160.0)),
        ),
        _rect(
            'second',
            '2ND',
            ZoneKind.AREA,
            0,
            ((67.5, 2294.4), (378.0, 2294.4), (378.0, 2070.4), (67.5, 2070.4)),
        ),
        _rect(
            'first',
            '1ST',
            ZoneKind.AREA,
            0,
            ((403.8, 2294.4), (714.2, 2294.4), (714.2, 2070.4), (403.8, 2070.4)),
        ),
        _rect(
            'boost',
            'BOOST',
            ZoneKind.AREA,
            0,
            ((1050.5, 2451.2), (1412.7, 2451.2), (1412.7, 2227.2), (1050.5, 2227.2)),
        ),
        _rect(
            'speedway',
            'SPEEDWAY',
            ZoneKind.AREA,
            0,
            ((1490.3, 2652.8), (1800.7, 2652.8), (1800.7, 1980.9), (1490.3, 1980.9)),
        ),
        _rect(
            'ct_spawn',
            'CT SPAWN',
            ZoneKind.SPAWN,
            10,
            ((2188.7, 2518.4), (2602.6, 2518.4), (2602.6, 1980.9), (2188.7, 1980.9)),
        ),
        _rect(
            'car',
            'CAR',
            ZoneKind.AREA,
            0,
            ((559.0, 2025.7), (921.2, 2025.7), (921.2, 1756.9), (559.0, 1756.9)),
        ),
        _rect(
            'banana',
            'BANANA',
            ZoneKind.AREA,
            0,
            ((326.2, 1846.5), (791.8, 1846.5), (791.8, 1488.1), (326.2, 1488.1)),
        ),
        _rect(
            'sandbag',
            'SANDBAG',
            ZoneKind.AREA,
            0,
            ((869.5, 1622.5), (1283.3, 1622.5), (1283.3, 1353.7), (869.5, 1353.7)),
        ),
        _rect(
            'loggs',
            'LOGGS',
            ZoneKind.AREA,
            0,
            ((-165.3, 1443.3), (248.6, 1443.3), (248.6, 1174.5), (-165.3, 1174.5)),
        ),
        _rect(
            'long_corner',
            'LONG CORNER',
            ZoneKind.AREA,
            0,
            ((947.1, 1420.9), (1516.2, 1420.9), (1516.2, 1152.1), (947.1, 1152.1)),
        ),
        _rect(
            'arch',
            'ARCH',
            ZoneKind.AREA,
            0,
            ((1800.7, 1420.9), (2162.9, 1420.9), (2162.9, 1152.1), (1800.7, 1152.1)),
        ),
        _rect(
            'long',
            'LONG',
            ZoneKind.AREA,
            0,
            ((1567.9, 1196.9), (1981.8, 1196.9), (1981.8, 883.3), (1567.9, 883.3)),
        ),
        _rect(
            'library',
            'LIBRARY',
            ZoneKind.AREA,
            0,
            ((2266.3, 1174.5), (2732.0, 1174.5), (2732.0, 905.7), (2266.3, 905.7)),
        ),
        _rect(
            'cubby',
            'CUBBY',
            ZoneKind.AREA,
            0,
            ((1697.2, 928.1), (2059.4, 928.1), (2059.4, 704.1), (1697.2, 704.1)),
        ),
        _rect(
            'moto',
            'MOTO',
            ZoneKind.AREA,
            0,
            ((2162.9, 905.7), (2525.0, 905.7), (2525.0, 636.9), (2162.9, 636.9)),
        ),
        _rect(
            't_spawn',
            'T SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-1805.3, 740.0), (-1422.5, 740.0), (-1422.5, 309.9), (-1805.3, 309.9)),
        ),
        _rect(
            'ramp',
            'RAMP',
            ZoneKind.AREA,
            0,
            ((-501.6, 860.9), (-87.7, 860.9), (-87.7, 592.1), (-501.6, 592.1)),
        ),
        _rect(
            'underpass',
            'UNDERPASS',
            ZoneKind.AREA,
            0,
            ((171.0, 905.7), (688.4, 905.7), (688.4, 636.9), (171.0, 636.9)),
        ),
        _rect(
            'mid',
            'MID',
            ZoneKind.AREA,
            0,
            ((222.7, 659.3), (636.6, 659.3), (636.6, 345.8), (222.7, 345.8)),
        ),
        _rect(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            ((1785.2, 547.3), (2178.4, 547.3), (2178.4, 189.0), (1785.2, 189.0)),
        ),
        _rect(
            'grave_yard',
            'GRAVE YARD',
            ZoneKind.AREA,
            0,
            ((2550.9, 569.7), (2964.8, 569.7), (2964.8, 166.6), (2550.9, 166.6)),
        ),
        _rect(
            'boiler',
            'BOILER',
            ZoneKind.AREA,
            0,
            ((895.3, 435.4), (1257.5, 435.4), (1257.5, 166.6), (895.3, 166.6)),
        ),
        _rect(
            'short',
            'SHORT',
            ZoneKind.AREA,
            0,
            ((1749.0, 233.8), (2162.9, 233.8), (2162.9, 9.8), (1749.0, 9.8)),
        ),
        _rect(
            'bridge',
            'BRIDGE',
            ZoneKind.AREA,
            0,
            ((-682.6, 99.4), (-268.8, 99.4), (-268.8, -169.4), (-682.6, -169.4)),
        ),
        _rect(
            'second_mid',
            'SECOND MID',
            ZoneKind.AREA,
            0,
            ((145.1, 99.4), (714.2, 99.4), (714.2, -169.4), (145.1, -169.4)),
        ),
        _rect(
            'bed_room',
            'BED ROOM',
            ZoneKind.AREA,
            0,
            ((972.9, 121.8), (1335.1, 121.8), (1335.1, -191.8), (972.9, -191.8)),
        ),
        _rect(
            'patio',
            'PATIO',
            ZoneKind.AREA,
            0,
            ((1309.2, 99.4), (1671.4, 99.4), (1671.4, -169.4), (1309.2, -169.4)),
        ),
        _rect(
            'pit',
            'PIT',
            ZoneKind.AREA,
            0,
            ((2473.3, 121.8), (2835.4, 121.8), (2835.4, -191.8), (2473.3, -191.8)),
        ),
        _rect(
            't_apps',
            'T APPS',
            ZoneKind.AREA,
            0,
            ((-217.0, -102.2), (300.3, -102.2), (300.3, -371.0), (-217.0, -371.0)),
        ),
        _rect(
            'halls',
            'HALLS',
            ZoneKind.AREA,
            0,
            ((1464.4, -79.8), (1826.6, -79.8), (1826.6, -303.8), (1464.4, -303.8)),
        ),
        _rect(
            'balcony',
            'BALCONY',
            ZoneKind.AREA,
            0,
            ((1179.9, -259.0), (1645.5, -259.0), (1645.5, -438.2), (1179.9, -438.2)),
        ),
        _rect(
            'mini_pit',
            'MINI PIT',
            ZoneKind.AREA,
            0,
            ((2369.8, -102.2), (2732.0, -102.2), (2732.0, -371.0), (2369.8, -371.0)),
        ),
        _rect(
            'back_alley',
            'BACK ALLEY',
            ZoneKind.AREA,
            0,
            ((352.1, -303.8), (972.9, -303.8), (972.9, -572.6), (352.1, -572.6)),
        ),
    ),
)

__all__ = ["INFERNO_ZONE_SET"]
