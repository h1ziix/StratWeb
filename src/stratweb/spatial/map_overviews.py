"""Pinned map assets plus an explicit compatibility path for legacy Spatial runs."""

from __future__ import annotations

import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from stratweb.maps.models import MapDefinition, MapLevel, MapSemanticsPin
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.maps.transforms import world_to_map
from stratweb.spatial.models import SpatialAvailabilityStatus
from stratweb.spatial.query_models import MapOverview, MapProjection

_MAP_NAME = re.compile(r"^de_[a-z0-9_]+$")
_PAIR = re.compile(r'^\s*"(?P<key>[^"]+)"\s+"(?P<value>[^"]+)"')
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class MapOverviewAsset:
    model: MapOverview
    image_path: Path | None
    lower_image_path: Path | None = None
    definition: MapDefinition | None = None

    def project(self, x: float, y: float, z: float | None = None) -> MapProjection | None:
        if self.definition is not None:
            result = world_to_map(self.definition, x, y, z)
            if result.pixel_x is None or result.pixel_y is None:
                return None
            assert result.normalized_x is not None
            assert result.normalized_y is not None
            return MapProjection(
                pixel_x=result.pixel_x,
                pixel_y=result.pixel_y,
                percent_x=result.normalized_x * 100,
                percent_y=result.normalized_y * 100,
                normalized_x=result.normalized_x,
                normalized_y=result.normalized_y,
                inside_image="out_of_map_bounds" not in result.warnings,
                level=result.level,
                warnings=result.warnings,
            )
        item = self.model
        if (
            item.status is not SpatialAvailabilityStatus.AVAILABLE
            or item.pos_x is None
            or item.pos_y is None
            or item.scale is None
            or item.width is None
            or item.height is None
            or item.rotate not in {0, None}
        ):
            return None
        pixel_x = (x - item.pos_x) / item.scale
        pixel_y = (item.pos_y - y) / item.scale
        return MapProjection(
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            percent_x=(pixel_x / item.width) * 100,
            percent_y=(pixel_y / item.height) * 100,
            normalized_x=pixel_x / item.width,
            normalized_y=pixel_y / item.height,
            inside_image=0 <= pixel_x <= item.width and 0 <= pixel_y <= item.height,
            warnings=("legacy_map_semantics",),
        )


class MapOverviewRegistry:
    """Resolve exact pinned definitions; never substitute another map or revision."""

    def __init__(self, asset_directory: Path, map_registry: MapRegistry | None = None) -> None:
        self.asset_directory = asset_directory.expanduser().resolve()
        self.map_registry = map_registry or DEFAULT_MAP_REGISTRY
        self._legacy_cache: dict[str, MapOverviewAsset] = {}
        self._definition_cache: dict[tuple[str, str], MapOverviewAsset] = {}

    def get(self, map_name: str) -> MapOverviewAsset:
        """Legacy Spatial 1.0/1.1 lookup, retained without revision backfill."""

        if map_name not in self._legacy_cache:
            self._legacy_cache[map_name] = self._load_legacy(map_name)
        return self._legacy_cache[map_name]

    def get_for_run(self, map_name: str, pin: MapSemanticsPin | None) -> MapOverviewAsset:
        if pin is None:
            return self.get(map_name)
        definition = self.map_registry.resolve_pin(pin)
        if definition is None:
            return _unavailable(
                map_name,
                "pinned_map_definition_unavailable_or_changed",
                pin=pin,
            )
        return self.get_definition(definition, pin=pin)

    def get_definition(
        self, definition: MapDefinition, *, pin: MapSemanticsPin | None = None
    ) -> MapOverviewAsset:
        # Public registry pages and run-pinned pages may resolve the same immutable
        # definition, but selection evidence/status/warnings belong to the run. Keeping
        # them in one fingerprint-only cache entry would let whichever request arrived
        # first erase or leak run semantics into the other response.
        pin_key = pin.model_dump_json() if pin is not None else "registry-definition"
        key = (definition.definition_fingerprint, pin_key)
        cached = self._definition_cache.get(key)
        if cached is not None:
            return cached
        loaded = self._load_definition(definition, pin=pin)
        self._definition_cache[key] = loaded
        return loaded

    def asset_for_route(
        self, canonical_name: str, revision_id: str, level: MapLevel
    ) -> tuple[Path, str] | None:
        definition = self.map_registry.get_revision(canonical_name, revision_id)
        if definition is None:
            return None
        loaded = self.get_definition(definition)
        if level is MapLevel.LOWER:
            reference = definition.lower_overview_asset
            path = loaded.lower_image_path
        else:
            reference = definition.overview_asset
            path = loaded.image_path
        if reference is None or path is None:
            return None
        return path, reference.sha256

    def _load_definition(
        self, definition: MapDefinition, *, pin: MapSemanticsPin | None
    ) -> MapOverviewAsset:
        reference = definition.overview_asset
        if reference is None:
            return _unavailable(
                definition.canonical_name,
                "overview_asset_not_configured_for_revision",
                definition=definition,
                pin=pin,
            )
        image = _safe_asset_path(self.asset_directory, reference.relative_path)
        metadata = image.with_name(f"{definition.canonical_name}.txt")
        warnings = list(definition.warnings)
        if not _valid_asset(image, reference.sha256, reference.width, reference.height):
            return _unavailable(
                definition.canonical_name,
                "pinned_overview_asset_missing_or_checksum_mismatch",
                definition=definition,
                pin=pin,
            )
        if not metadata.is_file() or _sha256(metadata) != reference.metadata_sha256:
            return _unavailable(
                definition.canonical_name,
                "pinned_overview_metadata_missing_or_checksum_mismatch",
                definition=definition,
                pin=pin,
            )
        lower_path: Path | None = None
        lower_url: str | None = None
        if definition.lower_overview_asset is not None:
            lower = definition.lower_overview_asset
            candidate = _safe_asset_path(self.asset_directory, lower.relative_path)
            if _valid_asset(candidate, lower.sha256, lower.width, lower.height):
                lower_path = candidate
                lower_url = _versioned_url(definition, MapLevel.LOWER, lower.sha256)
            else:
                warnings.append("pinned_lower_overview_missing_or_checksum_mismatch")
        selection_status = pin.selection_status if pin is not None else None
        selection_evidence = pin.selection_evidence if pin is not None else ()
        if pin is not None:
            warnings.extend(pin.warnings)
        result = MapOverviewAsset(
            model=MapOverview(
                map_name=definition.canonical_name,
                canonical_name=definition.canonical_name,
                display_name=definition.display_name,
                selected_revision=definition.map_revision.revision_id,
                revision_selection_status=selection_status,
                selection_evidence=selection_evidence,
                status=SpatialAvailabilityStatus.AVAILABLE,
                image_url=_versioned_url(definition, MapLevel.UPPER, reference.sha256),
                lower_image_url=lower_url,
                image_sha256=reference.sha256,
                metadata_sha256=reference.metadata_sha256,
                width=reference.width,
                height=reference.height,
                pos_x=definition.world_origin_x,
                pos_y=definition.world_origin_y,
                scale=definition.scale,
                rotate=definition.rotation,
                asset_version=definition.asset_version,
                map_definition_version=(pin.map_definition_version if pin is not None else None),
                map_definition_fingerprint=definition.definition_fingerprint,
                calibration_status=definition.calibration_status,
                validation_status=definition.validation_status,
                level_policy=definition.level_policy,
                source=definition.asset_source,
                warnings=tuple(dict.fromkeys(warnings)),
            ),
            image_path=image,
            lower_image_path=lower_path,
            definition=definition,
        )
        return result

    def _load_legacy(self, map_name: str) -> MapOverviewAsset:
        if not _MAP_NAME.fullmatch(map_name):
            return _unavailable(map_name, "invalid_map_name")
        image = self.asset_directory / f"{map_name}.png"
        metadata = self.asset_directory / f"{map_name}.txt"
        if not image.is_file() or not metadata.is_file():
            return _unavailable(
                map_name,
                "legacy official overview PNG or metadata is not installed",
            )
        try:
            values = _parse_overview(metadata)
            width, height = _png_dimensions(image)
            pos_x = float(values["pos_x"])
            pos_y = float(values["pos_y"])
            scale = float(values["scale"])
            rotate = int(values.get("rotate", "0"))
        except (KeyError, OSError, ValueError, struct.error) as exc:
            return _unavailable(map_name, f"overview_asset_invalid:{type(exc).__name__}")
        warnings = ["legacy_map_semantics"]
        status = SpatialAvailabilityStatus.AVAILABLE
        if rotate != 0:
            status = SpatialAvailabilityStatus.UNAVAILABLE
            warnings.append("legacy_rotated_overview_transform_unavailable")
        return MapOverviewAsset(
            model=MapOverview(
                map_name=map_name,
                status=status,
                image_url=f"/assets/map-overviews/{map_name}.png",
                image_sha256=_sha256(image),
                metadata_sha256=_sha256(metadata),
                width=width,
                height=height,
                pos_x=pos_x,
                pos_y=pos_y,
                scale=scale,
                rotate=rotate,
                source="local_cs2_vpk:legacy_unpinned",
                legacy_map_semantics=True,
                warnings=tuple(warnings),
            ),
            image_path=image,
        )


def _versioned_url(definition: MapDefinition, level: MapLevel, checksum: str) -> str:
    visual_level = "lower" if level is MapLevel.LOWER else "upper"
    return (
        f"/assets/map-overviews/{definition.canonical_name}/"
        f"{definition.map_revision.revision_id}/{visual_level}.png?v={checksum[:16]}"
    )


def _safe_asset_path(root: Path, relative_path: str) -> Path:
    candidate = (root / Path(relative_path)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("map asset escaped configured directory")
    return candidate


def _valid_asset(path: Path, checksum: str, width: int, height: int) -> bool:
    try:
        return (
            path.is_file()
            and _sha256(path) == checksum
            and _png_dimensions(path)
            == (
                width,
                height,
            )
        )
    except (OSError, ValueError, struct.error):
        return False


def _parse_overview(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = _PAIR.match(line)
        if match:
            values[match.group("key")] = match.group("value")
    return values


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("not a PNG with an IHDR header")
    return struct.unpack(">II", header[16:24])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _unavailable(
    map_name: str,
    warning: str,
    *,
    definition: MapDefinition | None = None,
    pin: MapSemanticsPin | None = None,
) -> MapOverviewAsset:
    return MapOverviewAsset(
        model=MapOverview(
            map_name=map_name,
            canonical_name=(
                definition.canonical_name
                if definition is not None
                else pin.canonical_name
                if pin is not None
                else None
            ),
            display_name=(definition.display_name if definition is not None else None),
            selected_revision=(
                definition.map_revision.revision_id
                if definition is not None
                else pin.selected_map_revision
                if pin is not None
                else None
            ),
            revision_selection_status=(pin.selection_status if pin is not None else None),
            selection_evidence=(pin.selection_evidence if pin is not None else ()),
            status=SpatialAvailabilityStatus.UNAVAILABLE,
            calibration_status=(
                definition.calibration_status
                if definition is not None
                else pin.calibration_status
                if pin is not None
                else None
            ),
            validation_status=(definition.validation_status if definition is not None else None),
            level_policy=(definition.level_policy if definition is not None else None),
            map_definition_version=(pin.map_definition_version if pin is not None else None),
            map_definition_fingerprint=(
                pin.map_definition_fingerprint if pin is not None else None
            ),
            source=(definition.asset_source if definition is not None else "local_cs2_vpk"),
            legacy_map_semantics=pin is None,
            warnings=tuple(dict.fromkeys((warning, *(pin.warnings if pin is not None else ())))),
        ),
        image_path=None,
        definition=definition,
    )
