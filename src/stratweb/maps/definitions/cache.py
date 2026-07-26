from stratweb.maps.definitions._factory import (
    configured_definition,
    unsupported_historical_revision,
)

_ALIASES = ("de_cache", "cache")
DEFINITIONS = (
    configured_definition(
        canonical_name="de_cache",
        display_name="Cache",
        aliases=_ALIASES,
        origin_x=-2000,
        origin_y=3250,
        scale=5.5,
        image_sha256="94c058b3deaa5cc24be81006322da3af1ef0bbded116160a3fcdea6d87227967",
        metadata_sha256="4344e0364bc9ec31f9f3fc04fe24aacb465e5252f8c173e661cebec586b54c0d",
    ),
    unsupported_historical_revision(
        canonical_name="de_cache",
        display_name="Cache",
        aliases=_ALIASES,
        revision_id="cs2-historical-cache-layout-unresolved",
        notes=(
            "Historical Cache layouts are intentionally recorded without borrowed constants.",
            "Install a licensed asset and accepted calibration before selecting this revision.",
        ),
    ),
)
