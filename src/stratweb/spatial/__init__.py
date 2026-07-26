"""Parser-independent Spatial Engine foundation."""

from stratweb.spatial.engine import SpatialEngine
from stratweb.spatial.models import SPATIAL_RULE_VERSION, SPATIAL_SCHEMA_VERSION

__all__ = ["SPATIAL_RULE_VERSION", "SPATIAL_SCHEMA_VERSION", "SpatialEngine"]
