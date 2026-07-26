"""Proposed zone set for de_nuke, revision cs2-1.41.7.1-d263aa1118fb.

Two official callout references supplied by the user on 2026-07-27 (A side
= upper level, B side = lower level). Upper zones carry min_z=-495 and
lower zones max_z=-495 per the calibrated level split; Ramp, Secret access
and both spawns span levels where the callout does. A-side coordinates come
from a three-anchor fit of the reference (T/CT spawn boxes + site A marker,
residuals <= 0.015); B-side rooms follow the reference's relative layout
under the same central building. No local demo exists for nuke yet, so the
evidence check uses the Valve anchors with level-appropriate altitudes.
Status PROPOSED pending the user's overlay check.
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

_MAP_NAME = "de_nuke"
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


NUKE_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source=_SOURCE,
    zones=(
        _rect(
            'ramp',
            'RAMP',
            ZoneKind.AREA,
            0,
            ((245.7, 2385.2), (919.5, 2385.2), (919.5, 1525.1), (245.7, 1525.1)),
        ),
        _rect(
            'boost',
            'BOOST',
            ZoneKind.AREA,
            0,
            ((245.7, 1345.9), (718.8, 1345.9), (718.8, 915.8), (245.7, 915.8)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'radio',
            'RADIO',
            ZoneKind.AREA,
            0,
            ((-471.1, 1023.3), (73.7, 1023.3), (73.7, 521.6), (-471.1, 521.6)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'heaven',
            'HEAVEN',
            ZoneKind.AREA,
            0,
            ((754.6, 1023.3), (1299.4, 1023.3), (1299.4, 593.2), (754.6, 593.2)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'ct_spawn',
            'CT-SPAWN',
            ZoneKind.SPAWN,
            10,
            ((1908.7, -87.7), (2926.5, -87.7), (2926.5, -804.5), (1908.7, -804.5)),
        ),
        _rect(
            'bombsite_a',
            'Bombsite A',
            ZoneKind.BOMBSITE,
            10,
            ((381.9, -123.6), (1055.7, -123.6), (1055.7, -840.4), (381.9, -840.4)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'locker',
            'LOCKER',
            ZoneKind.AREA,
            0,
            ((955.3, -231.1), (1428.4, -231.1), (1428.4, -732.8), (955.3, -732.8)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'ct_box',
            'CT BOX',
            ZoneKind.AREA,
            0,
            ((1808.3, -446.1), (2209.7, -446.1), (2209.7, -876.2), (1808.3, -876.2)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            't_spawn',
            'T-SPAWN',
            ZoneKind.SPAWN,
            10,
            ((-2607.2, -661.2), (-1589.3, -661.2), (-1589.3, -1234.6), (-2607.2, -1234.6)),
        ),
        _rect(
            'lobby',
            'LOBBY',
            ZoneKind.AREA,
            0,
            ((-471.1, -697.0), (73.7, -697.0), (73.7, -1270.4), (-471.1, -1270.4)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'hut',
            'HUT',
            ZoneKind.AREA,
            0,
            ((145.3, -804.5), (546.7, -804.5), (546.7, -1234.6), (145.3, -1234.6)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'blue_box',
            'BLUE BOX',
            ZoneKind.AREA,
            0,
            ((919.5, -840.4), (1464.2, -840.4), (1464.2, -1270.4), (919.5, -1270.4)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'squeaky',
            'SQUEAKY',
            ZoneKind.AREA,
            0,
            ((-263.2, -1198.8), (281.5, -1198.8), (281.5, -1557.2), (-263.2, -1557.2)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'silo',
            'SILO',
            ZoneKind.AREA,
            0,
            ((-334.9, -1485.5), (281.5, -1485.5), (281.5, -2058.9), (-334.9, -2058.9)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'main',
            'MAIN',
            ZoneKind.AREA,
            0,
            ((310.2, -1557.2), (855.0, -1557.2), (855.0, -1987.2), (310.2, -1987.2)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'garage',
            'GARAGE',
            ZoneKind.AREA,
            0,
            ((1392.6, -1557.2), (2009.0, -1557.2), (2009.0, -2130.6), (1392.6, -2130.6)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'outside',
            'OUTSIDE',
            ZoneKind.AREA,
            0,
            ((374.7, -1808.0), (1263.5, -1808.0), (1263.5, -2381.5), (374.7, -2381.5)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'red',
            'RED',
            ZoneKind.AREA,
            0,
            ((245.7, -2202.3), (718.8, -2202.3), (718.8, -2632.4), (245.7, -2632.4)),
            level=MapLevel.UPPER,
            min_z=-495.0,
        ),
        _rect(
            'bombsite_b',
            'Bombsite B',
            ZoneKind.BOMBSITE,
            10,
            ((310.2, -338.6), (1027.0, -338.6), (1027.0, -1055.4), (310.2, -1055.4)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'dark',
            'DARK',
            ZoneKind.AREA,
            0,
            ((238.5, -51.9), (668.6, -51.9), (668.6, -482.0), (238.5, -482.0)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'control',
            'CONTROL',
            ZoneKind.AREA,
            0,
            ((776.1, -51.9), (1349.6, -51.9), (1349.6, -482.0), (776.1, -482.0)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'double',
            'DOUBLE',
            ZoneKind.AREA,
            0,
            ((883.6, -482.0), (1385.4, -482.0), (1385.4, -912.0), (883.6, -912.0)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'single',
            'SINGLE',
            ZoneKind.AREA,
            0,
            ((-84.0, -840.4), (346.0, -840.4), (346.0, -1198.8), (-84.0, -1198.8)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'vents',
            'VENTS',
            ZoneKind.AREA,
            0,
            ((346.0, -876.2), (847.8, -876.2), (847.8, -1234.6), (346.0, -1234.6)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'back_vents',
            'BACK VENTS',
            ZoneKind.AREA,
            0,
            ((381.9, -1162.9), (955.3, -1162.9), (955.3, -1521.3), (381.9, -1521.3)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
        _rect(
            'secret',
            'SECRET',
            ZoneKind.AREA,
            0,
            ((883.6, -804.5), (1600.4, -804.5), (1600.4, -1378.0), (883.6, -1378.0)),
            level=MapLevel.LOWER,
            max_z=-495.0,
        ),
    ),
)

__all__ = ["NUKE_ZONE_SET"]
