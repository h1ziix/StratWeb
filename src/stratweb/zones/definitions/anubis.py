"""Proposed zone set for de_anubis, revision cs2-1.41.7.1-d263aa1118fb.

Callout names and relative placement follow the official callout reference
supplied by the user on 2026-07-27; the reference was fitted through its
spawn emblems against the Valve CTSpawn/TSpawn anchors (uniform scale,
residuals <= 0.02). The VPK metadata carries no bomb site anchors for
anubis, so site boxes come from the reference markers only. Status
PROPOSED pending the user's overlay check.
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

_MAP_NAME = "de_anubis"
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


ANUBIS_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _rect(
            'sniper',
            'SNIPER',
            ZoneKind.AREA,
            0,
            ((-1452.2, 1920.1), (-1072.6, 1920.1), (-1072.6, 1624.9), (-1452.2, 1624.9)),
        ),
        _rect(
            'cave',
            'CAVE',
            ZoneKind.AREA,
            0,
            ((-1220.2, 1667.1), (-840.6, 1667.1), (-840.6, 1414.0), (-1220.2, 1414.0)),
        ),
        _rect(
            'street',
            'STREET',
            ZoneKind.AREA,
            0,
            ((-1473.3, 1603.8), (-1178.0, 1603.8), (-1178.0, 1097.7), (-1473.3, 1097.7)),
        ),
        _rect(
            'palace',
            'PALACE',
            ZoneKind.AREA,
            0,
            ((-840.6, 1540.5), (-461.1, 1540.5), (-461.1, 1245.3), (-840.6, 1245.3)),
        ),
        _rect(
            'mid',
            'MID',
            ZoneKind.AREA,
            0,
            ((-376.7, 1561.6), (-39.3, 1561.6), (-39.3, 1182.1), (-376.7, 1182.1)),
        ),
        _rect(
            'a_con',
            'A-CON',
            ZoneKind.AREA,
            0,
            ((66.1, 1519.5), (403.5, 1519.5), (403.5, 1224.2), (66.1, 1224.2)),
        ),
        _rect(
            'heaven',
            'HEAVEN',
            ZoneKind.AREA,
            0,
            ((403.5, 2025.5), (783.1, 2025.5), (783.1, 1772.5), (403.5, 1772.5)),
        ),
        _rect(
            'back_site_a',
            'BACK SITE',
            ZoneKind.AREA,
            0,
            ((1057.2, 2088.8), (1478.9, 2088.8), (1478.9, 1835.8), (1057.2, 1835.8)),
        ),
        _rect(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            ((846.3, 1899.0), (1310.2, 1899.0), (1310.2, 1519.5), (846.3, 1519.5)),
        ),
        _rect(
            'plateau',
            'PLATEAU',
            ZoneKind.AREA,
            0,
            ((698.7, 1646.0), (1078.3, 1646.0), (1078.3, 1392.9), (698.7, 1392.9)),
        ),
        _rect(
            'fountain',
            'FOUNTAIN',
            ZoneKind.AREA,
            0,
            ((1584.4, 1814.7), (1879.6, 1814.7), (1879.6, 1350.8), (1584.4, 1350.8)),
        ),
        _rect(
            'a_main',
            'A MAIN',
            ZoneKind.AREA,
            0,
            ((1542.2, 1371.8), (1879.6, 1371.8), (1879.6, 992.3), (1542.2, 992.3)),
        ),
        _rect(
            'corner',
            'CORNER',
            ZoneKind.AREA,
            0,
            ((-1620.9, 1266.4), (-1283.5, 1266.4), (-1283.5, 971.2), (-1620.9, 971.2)),
        ),
        _rect(
            'back_site_b',
            'BACK SITE',
            ZoneKind.AREA,
            0,
            ((-1135.9, 1224.2), (-756.3, 1224.2), (-756.3, 1013.4), (-1135.9, 1013.4)),
        ),
        _rect(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            ((-1325.6, 1118.8), (-903.9, 1118.8), (-903.9, 823.6), (-1325.6, 823.6)),
        ),
        _rect(
            'ninja',
            'NINJA',
            ZoneKind.AREA,
            0,
            ((-756.3, 1097.7), (-461.1, 1097.7), (-461.1, 844.7), (-756.3, 844.7)),
        ),
        _rect(
            'house',
            'HOUSE',
            ZoneKind.AREA,
            0,
            ((-229.1, 1245.3), (108.3, 1245.3), (108.3, 992.3), (-229.1, 992.3)),
        ),
        _rect(
            'headshot',
            'HEADSHOT',
            ZoneKind.AREA,
            0,
            ((382.4, 1245.3), (804.2, 1245.3), (804.2, 992.3), (382.4, 992.3)),
        ),
        _rect(
            'pillar',
            'PILLAR',
            ZoneKind.AREA,
            0,
            ((-1388.9, 886.8), (-1051.5, 886.8), (-1051.5, 633.8), (-1388.9, 633.8)),
        ),
        _rect(
            'b_con',
            'B-CON',
            ZoneKind.AREA,
            0,
            ((-967.2, 865.8), (-629.8, 865.8), (-629.8, 612.7), (-967.2, 612.7)),
        ),
        _rect(
            'doors',
            'DOORS',
            ZoneKind.AREA,
            0,
            ((-208.0, 1076.6), (129.4, 1076.6), (129.4, 865.8), (-208.0, 865.8)),
        ),
        _rect(
            'boat',
            'BOAT',
            ZoneKind.AREA,
            0,
            ((319.1, 1055.5), (614.4, 1055.5), (614.4, 802.5), (319.1, 802.5)),
        ),
        _rect(
            'water',
            'WATER',
            ZoneKind.AREA,
            0,
            ((-250.2, 886.8), (129.4, 886.8), (129.4, 633.8), (-250.2, 633.8)),
        ),
        _rect(
            'bridge',
            'BRIDGE',
            ZoneKind.AREA,
            0,
            ((-461.1, 950.1), (-208.0, 950.1), (-208.0, 528.4), (-461.1, 528.4)),
        ),
        _rect(
            'b_main',
            'B MAIN',
            ZoneKind.AREA,
            0,
            ((-1831.7, 781.4), (-1452.2, 781.4), (-1452.2, 444.0), (-1831.7, 444.0)),
        ),
        _rect(
            'stairs',
            'STAIRS',
            ZoneKind.AREA,
            0,
            ((150.5, 718.1), (487.8, 718.1), (487.8, 465.1), (150.5, 465.1)),
        ),
        _rect(
            'upper',
            'UPPER',
            ZoneKind.AREA,
            0,
            ((530.0, 823.6), (783.1, 823.6), (783.1, 401.8), (530.0, 401.8)),
        ),
        _rect(
            'ruins',
            'RUINS',
            ZoneKind.AREA,
            0,
            ((-1325.6, 549.4), (-903.9, 549.4), (-903.9, 212.0), (-1325.6, 212.0)),
        ),
        _rect(
            'top_mid',
            'TOP MID',
            ZoneKind.AREA,
            0,
            ((-440.0, 549.4), (-60.4, 549.4), (-60.4, 254.2), (-440.0, 254.2)),
        ),
        _rect(
            'alley',
            'ALLEY',
            ZoneKind.AREA,
            0,
            ((-144.8, 380.7), (234.8, 380.7), (234.8, 85.5), (-144.8, 85.5)),
        ),
        _rect(
            't_spawn',
            'T SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-123.7, -1348.4), (508.9, -1348.4), (508.9, -1728.0), (-123.7, -1728.0)),
        ),
        _rect(
            'ct_spawn',
            'CT SPAWN',
            ZoneKind.SPAWN,
            10,
            ((277.0, 2341.8), (867.4, 2341.8), (867.4, 1962.3), (277.0, 1962.3)),
        ),
    ),
)

__all__ = ["ANUBIS_ZONE_SET"]
