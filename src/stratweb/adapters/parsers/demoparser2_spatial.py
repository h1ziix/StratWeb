"""Spatial tick extractor for the pinned demoparser2 API."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from importlib import metadata
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, cast

from demoparser2 import DemoParser as NativeDemoParser

from stratweb.adapters.parsers.demoparser2 import EXPECTED_PARSER_VERSION, PARSER_NAME
from stratweb.exceptions import (
    DemoFileNotFoundError,
    DemoFileUnreadableError,
    DemoParseError,
    ParserContractError,
    UnsupportedDemoError,
)
from stratweb.maps.models import MapSelectionEvidence
from stratweb.spatial.models import SpatialExtraction, SpatialSourceSample

from .demoparser2_projectiles import extract_projectiles

_CS2_DEMO_STAMP = b"PBDEMS2"
_SPATIAL_PROPERTIES = (
    "X",
    "Y",
    "Z",
    "pitch",
    "yaw",
    "is_alive",
    "team_num",
    "inventory",
    "inventory_as_ids",
)


class _SpatialBackend(Protocol):
    def parse_header(self) -> Any: ...

    def parse_ticks(
        self,
        wanted_props: Sequence[str],
        *,
        players: Sequence[int] | None = None,
        ticks: Sequence[int] | None = None,
        prop_states: dict[str, Any] | None = None,
    ) -> Any: ...


SpatialParserFactory = Callable[[str], _SpatialBackend]


class Demoparser2SpatialExtractor:
    """Request only explicit sampled ticks and normalize parser values immediately."""

    def __init__(
        self,
        *,
        parser_factory: SpatialParserFactory | None = None,
        installed_version: str | None = None,
    ) -> None:
        version = installed_version or metadata.version(PARSER_NAME)
        if version != EXPECTED_PARSER_VERSION:
            raise ParserContractError(
                f"Expected {PARSER_NAME}=={EXPECTED_PARSER_VERSION}, found {version}."
            )
        self._version = version
        self._parser_factory = parser_factory or cast(SpatialParserFactory, NativeDemoParser)

    def extract(
        self,
        demo_path: Path,
        ticks: tuple[int, ...],
        *,
        expected_sha256: str,
    ) -> SpatialExtraction:
        path = _validate_demo(demo_path)
        actual_sha = _sha256(path)
        if actual_sha != expected_sha256:
            raise ParserContractError(
                "Spatial source demo SHA-256 does not match the imported canonical match."
            )
        try:
            backend = self._parser_factory(str(path))
            header = _header(backend)
            raw = backend.parse_ticks(_SPATIAL_PROPERTIES, ticks=ticks)
        except Exception as exc:
            raise DemoParseError(
                f"demoparser2 failed during spatial tick parsing: {type(exc).__name__}: {exc}"
            ) from exc
        if not hasattr(raw, "columns") or not hasattr(raw, "to_dict"):
            raise ParserContractError("demoparser2 parse_ticks() did not return a dataframe.")
        columns = tuple(str(item) for item in raw.columns)
        required = {"tick", "steamid", "name"}
        if not required.issubset(columns):
            missing = ", ".join(sorted(required - set(columns)))
            raise ParserContractError(
                f"Spatial tick output is missing required columns: {missing}."
            )
        records = raw.to_dict(orient="records")
        samples: list[SpatialSourceSample] = []
        nonfinite = 0
        for record in records:
            values: dict[str, float | None] = {}
            for column in ("X", "Y", "Z", "pitch", "yaw"):
                value, invalid = _optional_float(record.get(column))
                values[column] = value
                nonfinite += int(invalid)
            samples.append(
                SpatialSourceSample(
                    tick=int(record["tick"]),
                    steam_id=_identifier(record.get("steamid")),
                    player_name=_optional_string(record.get("name")),
                    x=values["X"],
                    y=values["Y"],
                    z=values["Z"],
                    pitch=values["pitch"],
                    yaw=values["yaw"],
                    source_alive=_optional_bool(record.get("is_alive")),
                    source_team_number=_optional_int(record.get("team_num")),
                    inventory_item_ids=_inventory(record.get("inventory_as_ids")),
                    inventory_names=_inventory_names(record.get("inventory")),
                )
            )
        warnings = []
        if nonfinite:
            warnings.append(f"nonfinite_spatial_values_coerced_to_unavailable:{nonfinite}")
        omitted = tuple(item for item in _SPATIAL_PROPERTIES if item not in columns)
        if omitted:
            warnings.append("demoparser2_omitted_requested_fields:" + ",".join(omitted))
        projectiles = extract_projectiles(backend)
        return SpatialExtraction(
            parser_name=PARSER_NAME,
            parser_version=self._version,
            source_demo_sha256=actual_sha,
            requested_ticks=ticks,
            samples=tuple(samples),
            source_columns=columns,
            invalid_numeric_value_count=nonfinite,
            map_selection_evidence=_map_evidence(header),
            projectiles=projectiles,
            warnings=tuple(warnings),
        )


def _validate_demo(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.exists():
        raise DemoFileNotFoundError(f"Demo file does not exist: {candidate}")
    if not candidate.is_file():
        raise DemoFileUnreadableError(f"Demo path is not a regular file: {candidate}")
    if candidate.suffix.casefold() != ".dem":
        raise UnsupportedDemoError("Only local files with the .dem extension are supported.")
    try:
        with candidate.open("rb") as stream:
            stamp = stream.read(len(_CS2_DEMO_STAMP))
    except OSError as exc:
        raise DemoFileUnreadableError(f"Could not read demo file: {candidate}") from exc
    if stamp != _CS2_DEMO_STAMP:
        raise UnsupportedDemoError("The file does not contain the CS2 PBDEMS2 demo stamp.")
    return candidate.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DemoFileUnreadableError(f"Could not hash demo file: {path}") from exc
    return digest.hexdigest()


def _optional_float(value: object) -> tuple[float | None, bool]:
    if value is None:
        return None, False
    try:
        result = float(cast(Any, value))
    except (TypeError, ValueError):
        return None, True
    return (result, False) if isfinite(result) else (None, True)


def _identifier(value: object) -> str | None:
    if value is None:
        return None
    try:
        numeric = int(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        text = str(value).strip()
        return text or None
    return str(numeric)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return bool(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None


def _inventory(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return None
    try:
        return tuple(int(item) for item in cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None


def _inventory_names(value: object) -> tuple[str, ...] | None:
    if value is None or isinstance(value, (str, bytes)):
        return None
    try:
        items = tuple(cast(Any, value))
    except TypeError:
        return None
    result: list[str] = []
    for item in items:
        normalized = _optional_string(item)
        if normalized is None:
            return None
        result.append(normalized)
    return tuple(result)


def _header(backend: _SpatialBackend) -> Mapping[str, object]:
    parser = getattr(backend, "parse_header", None)
    if parser is None:
        return {}
    value = parser()
    return value if isinstance(value, Mapping) else {}


def _map_evidence(header: Mapping[str, object]) -> MapSelectionEvidence | None:
    raw_map_name = _optional_string(header.get("map_name"))
    if raw_map_name is None:
        return None
    return MapSelectionEvidence(
        raw_map_name=raw_map_name,
        patch_version=_optional_string(header.get("patch_version")),
        map_crc=_optional_string(header.get("map_crc")),
    )
