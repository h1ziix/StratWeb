"""Proposed zone set for de_overpass, revision cs2-1.41.7.1-d263aa1118fb.

Callout names and relative placement follow the official callout reference
supplied by the user on 2026-07-27. The reference is horizontally
compressed relative to the asset; a two-anchor site fit (A/B markers)
was validated against the T-spawn demo centroid (predicted 0.929 vs
measured 0.924). CT Spawn is absent from the reference and is placed
directly on the freeze-end CT centroid of match dba336bb. Status PROPOSED
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

_MAP_NAME = "de_overpass"
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


OVERPASS_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _rect(
            'bank',
            'BANK',
            ZoneKind.AREA,
            0,
            ((-1931.0, 893.7), (-1650.9, 893.7), (-1650.9, 624.7), (-1931.0, 624.7)),
        ),
        _rect(
            'van',
            'VAN',
            ZoneKind.AREA,
            0,
            ((-1749.0, 736.8), (-1524.9, 736.8), (-1524.9, 512.6), (-1749.0, 512.6)),
        ),
        _rect(
            'trash',
            'TRASH',
            ZoneKind.AREA,
            0,
            ((-1454.9, 848.9), (-1202.8, 848.9), (-1202.8, 579.9), (-1454.9, 579.9)),
        ),
        _rect(
            'close_left',
            'CLOSE LEFT',
            ZoneKind.AREA,
            0,
            ((-2281.1, 669.6), (-1973.0, 669.6), (-1973.0, 355.7), (-2281.1, 355.7)),
        ),
        _rect(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            ((-2071.0, 759.2), (-1734.9, 759.2), (-1734.9, 310.9), (-2071.0, 310.9)),
        ),
        _rect(
            'truck',
            'TRUCK',
            ZoneKind.AREA,
            0,
            ((-1538.9, 647.1), (-1314.8, 647.1), (-1314.8, 378.1), (-1538.9, 378.1)),
        ),
        _rect(
            'sign',
            'SIGN',
            ZoneKind.AREA,
            0,
            ((-1847.0, 490.2), (-1622.9, 490.2), (-1622.9, 266.0), (-1847.0, 266.0)),
        ),
        _rect(
            'heaven',
            'HEAVEN',
            ZoneKind.AREA,
            0,
            ((-1454.9, 490.2), (-1202.8, 490.2), (-1202.8, 221.2), (-1454.9, 221.2)),
        ),
        _rect(
            'barrels',
            'BARRELS',
            ZoneKind.AREA,
            0,
            ((-978.7, 512.6), (-726.6, 512.6), (-726.6, 243.6), (-978.7, 243.6)),
        ),
        _rect(
            'long',
            'LONG',
            ZoneKind.AREA,
            0,
            ((-2155.1, 355.7), (-1875.0, 355.7), (-1875.0, -3.0), (-2155.1, -3.0)),
        ),
        _rect(
            'a_main',
            'A MAIN',
            ZoneKind.AREA,
            0,
            ((-1889.0, 333.3), (-1636.9, 333.3), (-1636.9, 19.4), (-1889.0, 19.4)),
        ),
        _rect(
            'pit',
            'PIT',
            ZoneKind.AREA,
            0,
            ((-1398.8, 310.9), (-1174.8, 310.9), (-1174.8, 41.9), (-1398.8, 41.9)),
        ),
        _rect(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            ((-1258.8, 310.9), (-978.7, 310.9), (-978.7, -92.6), (-1258.8, -92.6)),
        ),
        _rect(
            'jail',
            'JAIL',
            ZoneKind.AREA,
            0,
            ((-726.6, 378.1), (-474.6, 378.1), (-474.6, 64.3), (-726.6, 64.3)),
        ),
        _rect(
            'long_boost',
            'LONG BOOST',
            ZoneKind.AREA,
            0,
            ((-2365.1, 41.9), (-2085.1, 41.9), (-2085.1, -227.1), (-2365.1, -227.1)),
        ),
        _rect(
            'bridge',
            'BRIDGE',
            ZoneKind.AREA,
            0,
            ((-1314.8, 86.7), (-1090.8, 86.7), (-1090.8, -182.3), (-1314.8, -182.3)),
        ),
        _rect(
            'monster',
            'MONSTER',
            ZoneKind.AREA,
            0,
            ((-894.7, 109.1), (-586.6, 109.1), (-586.6, -204.7), (-894.7, -204.7)),
        ),
        _rect(
            'short',
            'SHORT',
            ZoneKind.AREA,
            0,
            ((-1104.8, -70.2), (-852.7, -70.2), (-852.7, -339.2), (-1104.8, -339.2)),
        ),
        _rect(
            'abc',
            'ABC',
            ZoneKind.AREA,
            0,
            ((-1538.9, -47.8), (-1314.8, -47.8), (-1314.8, -316.8), (-1538.9, -316.8)),
        ),
        _rect(
            'water',
            'WATER',
            ZoneKind.AREA,
            0,
            ((-1328.8, -137.5), (-1076.7, -137.5), (-1076.7, -406.5), (-1328.8, -406.5)),
        ),
        _rect(
            'long_toilets',
            'LONG TOILETS',
            ZoneKind.AREA,
            0,
            ((-2379.1, -204.7), (-2071.0, -204.7), (-2071.0, -473.7), (-2379.1, -473.7)),
        ),
        _rect(
            'toilets',
            'TOILETS',
            ZoneKind.AREA,
            0,
            ((-1861.0, -249.6), (-1608.9, -249.6), (-1608.9, -518.6), (-1861.0, -518.6)),
        ),
        _rect(
            'tunnel',
            'TUNNEL',
            ZoneKind.AREA,
            0,
            ((-1160.8, -272.0), (-908.7, -272.0), (-908.7, -541.0), (-1160.8, -541.0)),
        ),
        _rect(
            'tracks',
            'TRACKS',
            ZoneKind.AREA,
            0,
            ((-754.7, -47.8), (-558.6, -47.8), (-558.6, -675.5), (-754.7, -675.5)),
        ),
        _rect(
            'mid',
            'MID',
            ZoneKind.AREA,
            0,
            ((-1973.0, -451.3), (-1720.9, -451.3), (-1720.9, -765.2), (-1973.0, -765.2)),
        ),
        _rect(
            'con',
            'CON',
            ZoneKind.AREA,
            0,
            ((-1636.9, -451.3), (-1440.9, -451.3), (-1440.9, -720.3), (-1636.9, -720.3)),
        ),
        _rect(
            'tree',
            'TREE',
            ZoneKind.AREA,
            0,
            ((-2645.2, -518.6), (-2421.2, -518.6), (-2421.2, -832.4), (-2645.2, -832.4)),
        ),
        _rect(
            'party',
            'PARTY',
            ZoneKind.AREA,
            0,
            ((-2211.1, -518.6), (-1959.0, -518.6), (-1959.0, -832.4), (-2211.1, -832.4)),
        ),
        _rect(
            'lower_con',
            'LOWER CON',
            ZoneKind.AREA,
            0,
            ((-1636.9, -675.5), (-1384.8, -675.5), (-1384.8, -944.5), (-1636.9, -944.5)),
        ),
        _rect(
            'alley',
            'ALLEY',
            ZoneKind.AREA,
            0,
            ((-1034.7, -518.6), (-782.7, -518.6), (-782.7, -1011.8), (-1034.7, -1011.8)),
        ),
        _rect(
            'rock',
            'ROCK',
            ZoneKind.AREA,
            0,
            ((-2239.1, -810.0), (-2015.0, -810.0), (-2015.0, -1079.0), (-2239.1, -1079.0)),
        ),
        _rect(
            'ladder',
            'LADDER',
            ZoneKind.AREA,
            0,
            ((-1468.9, -854.8), (-1244.8, -854.8), (-1244.8, -1123.8), (-1468.9, -1123.8)),
        ),
        _rect(
            'fountain',
            'FOUNTAIN',
            ZoneKind.AREA,
            0,
            ((-1875.0, -922.1), (-1594.9, -922.1), (-1594.9, -1280.8), (-1875.0, -1280.8)),
        ),
        _rect(
            't_spawn',
            'T SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-1538.9, -2962.1), (-1034.7, -2962.1), (-1034.7, -3365.6), (-1538.9, -3365.6)),
        ),
        _rect(
            'ct_spawn',
            'CT SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-2491.7, 1059.6), (-2015.6, 1059.6), (-2015.6, 521.6), (-2491.7, 521.6)),
        ),
    ),
)

__all__ = ["OVERPASS_ZONE_SET"]
