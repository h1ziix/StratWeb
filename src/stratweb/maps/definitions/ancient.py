from stratweb.maps.definitions._factory import configured_definition
from stratweb.maps.models import MapValidationStatus

DEFINITIONS = (
    configured_definition(
        canonical_name="de_ancient",
        display_name="Ancient",
        aliases=("de_ancient", "ancient"),
        origin_x=-2953,
        origin_y=2164,
        scale=5.0,
        image_sha256="cb6adca45e32ecff0b131f742c129324ba5e2dd695247f61d2d21d85ef2c581c",
        metadata_sha256="f6b420a983e2702c3c0d903a901483b6bc61fcf5eef2b6fb62da485ba93eb3c1",
        validation_status=MapValidationStatus.DEMO_VALIDATED,
        validation_evidence=(
            "FACEIT demo sha256 3957844f5eb46645b342718422775674c69c73957014068792caf43e9f0d56d0",
            "Stage 7.1 playback: spawn movement, event jumps, C4 carrier and full-round paths",
        ),
    ),
)
