"""Typed, immutable contracts for map revisions and coordinate semantics."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from stratweb.application.normalization_utils import canonical_json

MAP_DEFINITION_SCHEMA_VERSION = "1.0.0"
MAP_TRANSFORM_RULE_VERSION = "source2-overview-v1"
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class MapModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SupportedGame(StrEnum):
    CS2 = "cs2"
    CSGO_LEGACY = "csgo_legacy"


class MapRevisionKind(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"
    LEGACY = "legacy"


class CalibrationStatus(StrEnum):
    CONFIGURED = "configured"
    OFFICIAL_METADATA = "official_metadata"
    DEMO_VALIDATED = "demo_validated"
    UNSUPPORTED = "unsupported"


class MapValidationStatus(StrEnum):
    CONFIGURED = "configured"
    SYNTHETIC_VALIDATED = "synthetic_validated"
    DEMO_VALIDATED = "demo_validated"
    UNSUPPORTED = "unsupported"


class AxisOrientation(StrEnum):
    SOURCE_X_RIGHT_Y_UP_TO_IMAGE_X_RIGHT_Y_DOWN = "source_x_right_y_up_to_image_x_right_y_down"


class RotationApplication(StrEnum):
    BAKED_INTO_ASSET = "baked_into_asset"


class LevelPolicyKind(StrEnum):
    SINGLE_LEVEL = "single_level"
    ALTITUDE_SECTIONS = "altitude_sections"


class MapLevel(StrEnum):
    DEFAULT = "default"
    UPPER = "upper"
    LOWER = "lower"
    UNKNOWN = "unknown"


class MapCoordinateAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class MapSelectionStatus(StrEnum):
    PROVEN = "proven"
    UNPROVEN = "unproven"
    UNSUPPORTED = "unsupported"


class MapAssetReference(MapModel):
    """Internal asset reference. `relative_path` is never serialized by HTTP handlers."""

    asset_id: str
    relative_path: str
    sha256: Sha256
    metadata_sha256: Sha256
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_path: str


class CoordinateTransform(MapModel):
    rule_version: str = MAP_TRANSFORM_RULE_VERSION
    kind: str = "source2_overview_metadata"
    rotation_application: RotationApplication = RotationApplication.BAKED_INTO_ASSET


class MapLevelPolicy(MapModel):
    kind: LevelPolicyKind = LevelPolicyKind.SINGLE_LEVEL
    upper_min_z: FiniteFloat | None = None
    lower_max_z: FiniteFloat | None = None
    boundary_is_ambiguous: bool = False
    source: str


class MapRevision(MapModel):
    revision_id: str
    display_name: str
    kind: MapRevisionKind
    compatible_patch_versions: tuple[str, ...] = ()
    compatible_map_crcs: tuple[str, ...] = ()
    compatible_asset_versions: tuple[str, ...] = ()
    incompatible_layout_possible: bool = False
    selection_notes: tuple[str, ...] = ()


class MapDefinition(MapModel):
    canonical_name: str
    display_name: str
    aliases: tuple[str, ...]
    supported_game: SupportedGame
    map_revision: MapRevision
    overview_asset: MapAssetReference | None
    lower_overview_asset: MapAssetReference | None = None
    coordinate_transform: CoordinateTransform | None
    source_coordinate_system: str = "source2_world_units"
    image_width: int | None = Field(default=None, gt=0)
    image_height: int | None = Field(default=None, gt=0)
    world_origin_x: FiniteFloat | None = None
    world_origin_y: FiniteFloat | None = None
    scale: FiniteFloat | None = Field(default=None, gt=0)
    rotation: int | None = Field(default=None, ge=0, le=359)
    axis_orientation: AxisOrientation | None
    level_policy: MapLevelPolicy
    level_split_z: FiniteFloat | None = None
    asset_source: str
    asset_version: str
    calibration_status: CalibrationStatus
    validation_status: MapValidationStatus
    calibration_source: str
    validation_evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def definition_fingerprint(self) -> Sha256:
        serialized = canonical_json(self.model_dump(mode="json"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    @property
    def transform_available(self) -> bool:
        return all(
            value is not None
            for value in (
                self.coordinate_transform,
                self.image_width,
                self.image_height,
                self.world_origin_x,
                self.world_origin_y,
                self.scale,
                self.axis_orientation,
            )
        )


class MapSelectionEvidence(MapModel):
    raw_map_name: str
    patch_version: str | None = None
    map_crc: str | None = None
    asset_version: str | None = None
    manual_revision: str | None = None


class MapSelectionResult(MapModel):
    raw_map_name: str
    canonical_name: str | None
    display_name: str | None
    status: MapSelectionStatus
    selected_definition: MapDefinition | None
    evidence: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class MapSemanticsPin(MapModel):
    raw_map_name: str
    canonical_name: str | None
    selected_map_revision: str | None
    selection_status: MapSelectionStatus
    selection_evidence: tuple[str, ...] = ()
    map_definition_version: str = MAP_DEFINITION_SCHEMA_VERSION
    map_definition_fingerprint: Sha256 | None = None
    overview_checksum: Sha256 | None = None
    lower_overview_checksum: Sha256 | None = None
    transform_rule_version: str | None = None
    calibration_status: CalibrationStatus = CalibrationStatus.UNSUPPORTED
    warnings: tuple[str, ...] = ()


class MapCoordinateResult(MapModel):
    normalized_x: FiniteFloat | None = None
    normalized_y: FiniteFloat | None = None
    pixel_x: FiniteFloat | None = None
    pixel_y: FiniteFloat | None = None
    level: MapLevel = MapLevel.UNKNOWN
    availability: MapCoordinateAvailability
    warnings: tuple[str, ...] = ()


class MapValidationResult(MapModel):
    canonical_name: str
    revision_id: str
    definition_fingerprint: Sha256
    valid: bool
    checks: tuple[str, ...]
    warnings: tuple[str, ...] = ()
