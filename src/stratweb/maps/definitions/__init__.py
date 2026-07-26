from stratweb.maps.definitions.ancient import DEFINITIONS as ANCIENT
from stratweb.maps.definitions.anubis import DEFINITIONS as ANUBIS
from stratweb.maps.definitions.cache import DEFINITIONS as CACHE
from stratweb.maps.definitions.dust2 import DEFINITIONS as DUST2
from stratweb.maps.definitions.inferno import DEFINITIONS as INFERNO
from stratweb.maps.definitions.mirage import DEFINITIONS as MIRAGE
from stratweb.maps.definitions.nuke import DEFINITIONS as NUKE
from stratweb.maps.definitions.overpass import DEFINITIONS as OVERPASS

ALL_DEFINITIONS = MIRAGE + NUKE + ANCIENT + ANUBIS + DUST2 + INFERNO + CACHE + OVERPASS

__all__ = ["ALL_DEFINITIONS"]
