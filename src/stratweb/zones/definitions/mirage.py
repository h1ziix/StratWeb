"""Proposed zone set for de_mirage, revision cs2-1.41.7.1-d263aa1118fb.

World coordinates were derived from normalized overview coordinates through
the calibrated transform (origin -3230/1713, scale 5.0, 1024 px) that
tests/test_maps_ground_truth.py pins against Valve spawn anchors and real
freeze-end demo positions. Bombsites and spawns are anchored to Valve's own
overview metadata (bombA/bombB/CTSpawn/TSpawn icons and the site markers
baked into the shipped asset). Callout names and relative placement follow
the official callout reference supplied by the user on 2026-07-27; corridor
boundaries stay PROPOSED until the developer overlay review upgrades them to
OVERLAY_VERIFIED.
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
_CALLOUT_REFERENCE = "official callout reference supplied by the user (2026-07-27)"


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
    source=(
        "Authored 2026-07-27 from the pinned VPK overview asset, Valve anchors and the "
        "official callout reference supplied by the user."
    ),
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
            "b_apartments",
            "B Apartments",
            ZoneKind.PATHWAY,
            0,
            ((-1591.6, 996.2), (-567.6, 996.2), (-567.6, 458.6), (-1591.6, 458.6)),
            f"West half of the top band per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "t_apps",
            "T Apps",
            ZoneKind.PATHWAY,
            0,
            ((-567.6, 996.2), (456.4, 996.2), (456.4, 458.6), (-567.6, 458.6)),
            f"East half of the top band per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "mid",
            "Mid",
            ZoneKind.PATHWAY,
            0,
            ((-977.2, -27.8), (-414.0, -27.8), (-414.0, -1256.6), (-977.2, -1256.6)),
            f"Central corridor narrowed per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "top_mid",
            "Top Mid",
            ZoneKind.PATHWAY,
            0,
            ((-362.8, -232.6), (456.4, -232.6), (456.4, -949.4), (-362.8, -949.4)),
            f"Open area east of Mid toward T Spawn per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "window",
            "Window",
            ZoneKind.AREA,
            0,
            ((-1438.0, -437.4), (-1028.4, -437.4), (-1028.4, -1051.8), (-1438.0, -1051.8)),
            f"Room west of Mid per {_CALLOUT_REFERENCE} (previously mislabeled Underpass)",
        ),
        _rect(
            "underpass",
            "Underpass",
            ZoneKind.CHOKEPOINT,
            5,
            ((-1028.4, -437.4), (-670.0, -437.4), (-670.0, -847.0), (-1028.4, -847.0)),
            f"Tunnel under Catwalk per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "connector",
            "Connector",
            ZoneKind.CHOKEPOINT,
            5,
            ((-1079.6, -1103.0), (-567.6, -1103.0), (-567.6, -1512.6), (-1079.6, -1512.6)),
            f"Mid-to-Jungle link recentered per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "jungle",
            "Jungle",
            ZoneKind.AREA,
            0,
            ((-1386.8, -1461.4), (-874.8, -1461.4), (-874.8, -1871.0), (-1386.8, -1871.0)),
            f"Area above Bombsite A shifted west per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "palace",
            "Palace",
            ZoneKind.PATHWAY,
            0,
            ((-4.4, -1973.4), (917.2, -1973.4), (917.2, -2587.8), (-4.4, -2587.8)),
            f"Covered building adjoining Bombsite A per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "ramp",
            "Ramp",
            ZoneKind.PATHWAY,
            0,
            ((558.8, -949.4), (1378.0, -949.4), (1378.0, -1871.0), (558.8, -1871.0)),
            f"T-side approach to Bombsite A (Ramp/Shadow) per {_CALLOUT_REFERENCE}",
        ),
        _rect(
            "market",
            "Market",
            ZoneKind.AREA,
            0,
            ((-1950.0, -437.4), (-1386.8, -437.4), (-1386.8, -1256.6), (-1950.0, -1256.6)),
            f"Market/B Window rooms per {_CALLOUT_REFERENCE}",
        ),
    ),
)

__all__ = ["MIRAGE_ZONE_SET"]
