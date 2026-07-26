from stratweb.maps.definitions._factory import (
    configured_definition,
    unsupported_historical_revision,
)
from stratweb.maps.models import MapValidationStatus

_ALIASES = ("de_overpass", "overpass")
DEFINITIONS = (
    configured_definition(
        canonical_name="de_overpass",
        display_name="Overpass",
        aliases=_ALIASES,
        origin_x=-4831,
        origin_y=1781,
        scale=5.2,
        image_sha256="2a59b62668e80037b5a88e980f56af360269f5ea581d52eb0669d78a981f0d96",
        metadata_sha256="23b44305d79a15dc9feea71528a7015d6f3612044a8367f29b20c65aec2e7897",
        validation_status=MapValidationStatus.DEMO_VALIDATED,
        validation_evidence=(
            "FACEIT demo sha256 1d62bcbc0f4bc5d8ae1c4f4a28c71d1742cddbdde6074cfe929e06c8d43bb050",
            "110886 reliable alive samples across 30 rounds; zero projected out of bounds",
            "first-live spawn bands align with overview CT/T spawn annotations",
            "7730 carried-C4 samples remain within the overview",
        ),
    ),
    unsupported_historical_revision(
        canonical_name="de_overpass",
        display_name="Overpass",
        aliases=_ALIASES,
        revision_id="cs2-historical-overpass-layout-unresolved",
        notes=(
            "Historical Overpass layouts can be incompatible with the installed current radar.",
            "No date-based selection or current-radar fallback is allowed.",
        ),
    ),
)
