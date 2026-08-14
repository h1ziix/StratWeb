"""Parser adapters for completed demo files."""

from stratweb.adapters.parsers.demoparser2 import Demoparser2Adapter
from stratweb.adapters.parsers.demoparser2_economy import Demoparser2EconomyExtractor
from stratweb.adapters.parsers.demoparser2_spatial import Demoparser2SpatialExtractor

__all__ = [
    "Demoparser2Adapter",
    "Demoparser2EconomyExtractor",
    "Demoparser2SpatialExtractor",
]
