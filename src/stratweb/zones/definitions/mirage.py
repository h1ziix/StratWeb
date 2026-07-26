"""Proposed zone set for de_mirage, revision cs2-1.41.7.1-d263aa1118fb.

World coordinates were derived from normalized overview coordinates through
the calibrated transform (origin -3230/1713, scale 5.0, 1024 px) that
tests/test_maps_ground_truth.py pins against Valve spawn anchors and real
freeze-end demo positions. Bombsites and spawns are anchored to Valve's own
overview metadata (bombA/bombB/CTSpawn/TSpawn icons and the site markers
baked into the shipped asset); corridor boundaries are eyeballed from the
same asset and stay PROPOSED until the developer overlay review upgrades
them to OVERLAY_VERIFIED.
"""

from __future__ import annotations

from stratweb.zones.models import (
    ZoneDefinition,
    ZoneKind,
    ZonePolygon,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)

_MAP_NAME = "de_mirage"
_MAP_REVISION = "cs2-1.41.7.1-d263aa1118fb"


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
    source: str,
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
        source=source,
    )


MIRAGE_ZONE_SET = ZoneSetDefinition(
    map_name=_MAP_NAME,
    map_revision=_MAP_REVISION,
    source="Authored 2026-07-27 from the pinned VPK overview asset and Valve anchors.",
    zones=(
        _rect(
            "bombsite_a",
            "Bombsite A",
            ZoneKind.BOMBSITE,
            10,
            ((-823.6, -1819.8), (-55.6, -1819.8), (-55.6, -2485.4), (-823.6, -2485.4)),
            "Valve bombA anchor (0.54, 0.76) and the baked site marker on the pinned asset",
        ),
        _rect(
            "bombsite_b",
            "Bombsite B",
            ZoneKind.BOMBSITE,
            10,
            ((-2359.6, 637.8), (-1694.0, 637.8), (-1694.0, -27.8), (-2359.6, -27.8)),
            "Valve bombB anchor (0.23, 0.28) and the baked site marker on the pinned asset",
        ),
        _rect(
            "t_spawn",
            "T Spawn",
            ZoneKind.SPAWN,
            10,
            ((1019.6, 279.4), (1531.6, 279.4), (1531.6, -539.8), (1019.6, -539.8)),
            "Valve TSpawn anchor (0.87, 0.36); freeze-end T centroid of match e0f188cf "
            "projects to (0.862, 0.368)",
        ),
        _rect(
            "ct_spawn",
            "CT Spawn",
            ZoneKind.SPAWN,
            10,
            ((-1898.8, -1410.2), (-1335.6, -1410.2), (-1335.6, -2280.6), (-1898.8, -2280.6)),
            "Valve CTSpawn anchor (0.28, 0.70); freeze-end CT centroid of match e0f188cf "
            "projects to (0.296, 0.704)",
        ),
        _rect(
            "mid",
            "Mid",
            ZoneKind.PATHWAY,
            0,
            ((-1130.8, -27.8), (-465.2, -27.8), (-465.2, -1461.4), (-1130.8, -1461.4)),
            "Central corridor eyeballed on the pinned asset; pending overlay verification",
        ),
        _rect(
            "connector",
            "Connector",
            ZoneKind.CHOKEPOINT,
            5,
            ((-1489.2, -1051.8), (-977.2, -1051.8), (-977.2, -1666.2), (-1489.2, -1666.2)),
            "Mid-to-CT link eyeballed on the pinned asset; pending overlay verification",
        ),
        _rect(
            "palace",
            "Palace",
            ZoneKind.PATHWAY,
            0,
            ((-4.4, -1973.4), (917.2, -1973.4), (917.2, -2587.8), (-4.4, -2587.8)),
            "Covered building adjoining Bombsite A; pending overlay verification",
        ),
        _rect(
            "a_ramp",
            "A Ramp",
            ZoneKind.PATHWAY,
            0,
            ((558.8, -949.4), (1378.0, -949.4), (1378.0, -1871.0), (558.8, -1871.0)),
            "T-side approach to Bombsite A; pending overlay verification",
        ),
        _rect(
            "b_apartments",
            "B Apartments",
            ZoneKind.PATHWAY,
            0,
            ((-1591.6, 996.2), (456.4, 996.2), (456.4, 458.6), (-1591.6, 458.6)),
            "Top-edge apartment band eyeballed on the pinned asset; pending overlay "
            "verification",
        ),
        _rect(
            "underpass",
            "Underpass",
            ZoneKind.CHOKEPOINT,
            5,
            ((-1438.0, -437.4), (-1028.4, -437.4), (-1028.4, -1051.8), (-1438.0, -1051.8)),
            "Mid-to-apartments link eyeballed on the pinned asset; pending overlay "
            "verification",
        ),
        _rect(
            "market",
            "Market",
            ZoneKind.AREA,
            0,
            ((-1950.0, -437.4), (-1386.8, -437.4), (-1386.8, -1256.6), (-1950.0, -1256.6)),
            "Window/market rooms eyeballed on the pinned asset; pending overlay verification",
        ),
        _rect(
            "jungle",
            "Jungle",
            ZoneKind.AREA,
            0,
            ((-977.2, -1359.0), (-362.8, -1359.0), (-362.8, -1819.8), (-977.2, -1819.8)),
            "Stairs area above Bombsite A; pending overlay verification",
        ),
    ),
)

__all__ = ["MIRAGE_ZONE_SET"]
