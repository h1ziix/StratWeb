"""Typed, immutable contracts for versioned named map areas.

Zones are authored in Source 2 world coordinates, not image pixels: world
coordinates are physical match evidence, so a map-revision or asset change
never reinterprets an already-computed zone result.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from stratweb.application.normalization_utils import canonical_json
from stratweb.maps.models import MapLevel

ZONE_SCHEMA_VERSION = "1.0.0"
ZONE_RESOLUTION_RULE_VERSION = "point_in_polygon_v1"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
ZoneSlug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_]{0,63}$")]


class ZoneModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ZoneKind(StrEnum):
    BOMBSITE = "bombsite"
    SPAWN = "spawn"
    PATHWAY = "pathway"
    CHOKEPOINT = "chokepoint"
    AREA = "area"


class ZoneVerificationStatus(StrEnum):
    """How the polygon boundaries were proven, mirroring map validation tiers."""

    PROPOSED = "proposed"
    OVERLAY_VERIFIED = "overlay_verified"
    DEMO_VALIDATED = "demo_validated"


class ZonePolygon(ZoneModel):
    """One simple polygon in world x/y, optionally constrained by altitude."""

    vertices: tuple[tuple[FiniteFloat, FiniteFloat], ...] = Field(min_length=3)
    min_z: FiniteFloat | None = None
    max_z: FiniteFloat | None = None


class ZoneDefinition(ZoneModel):
    zone_id: ZoneSlug
    zone_name: str = Field(min_length=1, max_length=100)
    kind: ZoneKind
    map_name: str
    map_revision: str
    level: MapLevel = MapLevel.DEFAULT
    # Higher priority wins when polygons overlap (e.g. a chokepoint inside a
    # larger pathway). Ties resolve deterministically by smaller area, then id.
    priority: int = 0
    polygons: tuple[ZonePolygon, ...] = Field(min_length=1)
    verification: ZoneVerificationStatus = ZoneVerificationStatus.PROPOSED
    source: str = Field(min_length=1)


class ZoneSetDefinition(ZoneModel):
    """Versioned, checksummed collection of zones for one map revision."""

    schema_version: str = ZONE_SCHEMA_VERSION
    map_name: str
    map_revision: str
    zones: tuple[ZoneDefinition, ...]
    source: str = Field(min_length=1)

    def fingerprint(self) -> str:
        payload = canonical_json(self.model_dump(mode="json"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ZoneResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


class ZoneResolution(ZoneModel):
    """Outcome of projecting one world coordinate onto a zone set."""

    status: ZoneResolutionStatus
    zone_id: str | None = None
    zone_name: str | None = None
    kind: ZoneKind | None = None
    level: MapLevel | None = None
    map_name: str | None = None
    map_revision: str | None = None
    rule_version: str = ZONE_RESOLUTION_RULE_VERSION
    warnings: tuple[str, ...] = ()


__all__ = [
    "ZONE_RESOLUTION_RULE_VERSION",
    "ZONE_SCHEMA_VERSION",
    "ZoneDefinition",
    "ZoneKind",
    "ZonePolygon",
    "ZoneResolution",
    "ZoneResolutionStatus",
    "ZoneSetDefinition",
    "ZoneVerificationStatus",
]
