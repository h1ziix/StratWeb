"""Authored zone sets per map revision.

Zone sets are keyed by (map_name, map_revision); a map without an authored
set simply has no zones, and every resolution against it stays unknown.
"""

from __future__ import annotations

from stratweb.zones.definitions.ancient import ANCIENT_ZONE_SET
from stratweb.zones.definitions.mirage import MIRAGE_ZONE_SET
from stratweb.zones.models import ZoneSetDefinition

ALL_ZONE_SETS: tuple[ZoneSetDefinition, ...] = (MIRAGE_ZONE_SET, ANCIENT_ZONE_SET)


def zone_set_for(map_name: str, map_revision: str) -> ZoneSetDefinition | None:
    for zone_set in ALL_ZONE_SETS:
        if zone_set.map_name == map_name and zone_set.map_revision == map_revision:
            return zone_set
    return None


__all__ = ["ALL_ZONE_SETS", "ANCIENT_ZONE_SET", "MIRAGE_ZONE_SET", "zone_set_for"]
