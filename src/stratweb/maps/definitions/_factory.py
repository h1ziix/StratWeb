"""Small constructor helpers for reviewed, immutable map definition modules."""

from __future__ import annotations

from stratweb.maps.models import (
    AxisOrientation,
    CalibrationStatus,
    CoordinateTransform,
    LevelPolicyKind,
    MapAssetReference,
    MapDefinition,
    MapLevelPolicy,
    MapRevision,
    MapRevisionKind,
    MapValidationStatus,
    SupportedGame,
)

ASSET_DIRECTORY = "vpk-d263aa1118fb"
ASSET_VERSION = "cs2-1.41.7.1-vpk-d263aa1118fb"
ASSET_SOURCE = (
    "user-local CS2 pak01_dir.vpk sha256 "
    "d263aa1118fb692baf83d44a7e20526eb6d6917fab26296ed410455f506d6aec"
)
REVISION_ID = "cs2-1.41.7.1-d263aa1118fb"
METADATA_SOURCE = "Valve resource/overviews metadata from the pinned local VPK"


def configured_definition(
    *,
    canonical_name: str,
    display_name: str,
    aliases: tuple[str, ...],
    origin_x: float,
    origin_y: float,
    scale: float,
    image_sha256: str,
    metadata_sha256: str,
    rotation: int = 0,
    lower_sha256: str | None = None,
    level_split_z: float | None = None,
    validation_status: MapValidationStatus = MapValidationStatus.SYNTHETIC_VALIDATED,
    validation_evidence: tuple[str, ...] = (),
) -> MapDefinition:
    level_policy = (
        MapLevelPolicy(
            kind=LevelPolicyKind.ALTITUDE_SECTIONS,
            upper_min_z=level_split_z,
            lower_max_z=level_split_z,
            boundary_is_ambiguous=True,
            source=f"{METADATA_SOURCE}: verticalsections",
        )
        if level_split_z is not None
        else MapLevelPolicy(source=f"{METADATA_SOURCE}: single overview")
    )
    upper = MapAssetReference(
        asset_id=f"{canonical_name}:{REVISION_ID}:upper",
        relative_path=f"{ASSET_DIRECTORY}/{canonical_name}.png",
        sha256=image_sha256,
        metadata_sha256=metadata_sha256,
        width=1024,
        height=1024,
        source_path=f"panorama/images/overheadmaps/{canonical_name}_radar_psd.vtex_c",
    )
    lower = (
        MapAssetReference(
            asset_id=f"{canonical_name}:{REVISION_ID}:lower",
            relative_path=f"{ASSET_DIRECTORY}/{canonical_name}_lower.png",
            sha256=lower_sha256,
            metadata_sha256=metadata_sha256,
            width=1024,
            height=1024,
            source_path=(f"panorama/images/overheadmaps/{canonical_name}_lower_radar_psd.vtex_c"),
        )
        if lower_sha256 is not None
        else None
    )
    return MapDefinition(
        canonical_name=canonical_name,
        display_name=display_name,
        aliases=aliases,
        supported_game=SupportedGame.CS2,
        map_revision=MapRevision(
            revision_id=REVISION_ID,
            display_name="Local CS2 1.41.7.1 asset revision",
            kind=MapRevisionKind.CURRENT,
            compatible_patch_versions=("14171", "1.41.7.1", "2000876"),
            compatible_asset_versions=(ASSET_VERSION,),
            incompatible_layout_possible=canonical_name in {"de_overpass", "de_cache"},
            selection_notes=(
                "A demo build must match explicitly; demo file dates are never selectors.",
            ),
        ),
        overview_asset=upper,
        lower_overview_asset=lower,
        coordinate_transform=CoordinateTransform(),
        image_width=1024,
        image_height=1024,
        world_origin_x=origin_x,
        world_origin_y=origin_y,
        scale=scale,
        rotation=rotation,
        axis_orientation=AxisOrientation.SOURCE_X_RIGHT_Y_UP_TO_IMAGE_X_RIGHT_Y_DOWN,
        level_policy=level_policy,
        level_split_z=level_split_z,
        asset_source=ASSET_SOURCE,
        asset_version=ASSET_VERSION,
        calibration_status=(
            CalibrationStatus.DEMO_VALIDATED
            if validation_status is MapValidationStatus.DEMO_VALIDATED
            else CalibrationStatus.OFFICIAL_METADATA
        ),
        validation_status=validation_status,
        calibration_source=METADATA_SOURCE,
        validation_evidence=validation_evidence,
        warnings=(("source_rotate_flag_baked_into_asset",) if rotation else ()),
    )


def unsupported_historical_revision(
    *,
    canonical_name: str,
    display_name: str,
    aliases: tuple[str, ...],
    revision_id: str,
    notes: tuple[str, ...],
) -> MapDefinition:
    return MapDefinition(
        canonical_name=canonical_name,
        display_name=display_name,
        aliases=aliases,
        supported_game=SupportedGame.CS2,
        map_revision=MapRevision(
            revision_id=revision_id,
            display_name="Historical layout (calibration not installed)",
            kind=MapRevisionKind.HISTORICAL,
            incompatible_layout_possible=True,
            selection_notes=notes,
        ),
        overview_asset=None,
        lower_overview_asset=None,
        coordinate_transform=None,
        image_width=None,
        image_height=None,
        world_origin_x=None,
        world_origin_y=None,
        scale=None,
        rotation=None,
        axis_orientation=None,
        level_policy=MapLevelPolicy(
            source="Historical revision recorded without an accepted calibration."
        ),
        asset_source="not installed",
        asset_version="unavailable",
        calibration_status=CalibrationStatus.UNSUPPORTED,
        validation_status=MapValidationStatus.UNSUPPORTED,
        calibration_source="none",
        warnings=("historical_revision_asset_unavailable",),
    )
