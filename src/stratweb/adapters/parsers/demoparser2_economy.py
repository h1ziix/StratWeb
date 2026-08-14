"""Freeze-end equipment extractor for the pinned demoparser2 API."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from importlib import metadata
from math import isfinite
from pathlib import Path
from typing import Any, Protocol, cast

from demoparser2 import DemoParser as NativeDemoParser

from stratweb.adapters.parsers.demoparser2 import EXPECTED_PARSER_VERSION, PARSER_NAME
from stratweb.economy.models import EconomyExtraction, EconomySourceSample
from stratweb.exceptions import (
    DemoFileNotFoundError,
    DemoFileUnreadableError,
    DemoParseError,
    ParserContractError,
    UnsupportedDemoError,
)

_CS2_DEMO_STAMP = b"PBDEMS2"
ECONOMY_PROPERTIES = (
    "current_equip_value",
    "round_start_equip_value",
    "cash_spent_this_round",
    "balance",
    "inventory",
    "inventory_as_ids",
    "armor_value",
    "has_helmet",
    "has_defuser",
    "team_num",
    "total_rounds_played",
)


class _EconomyBackend(Protocol):
    def parse_ticks(
        self,
        wanted_props: Sequence[str],
        *,
        players: Sequence[int] | None = None,
        ticks: Sequence[int] | None = None,
        prop_states: object | None = None,
    ) -> Any: ...


EconomyParserFactory = Callable[[str], _EconomyBackend]


class Demoparser2EconomyExtractor:
    """Request documented economy props only at canonical freeze-end ticks."""

    def __init__(
        self,
        *,
        parser_factory: EconomyParserFactory | None = None,
        installed_version: str | None = None,
    ) -> None:
        version = installed_version or metadata.version(PARSER_NAME)
        if version != EXPECTED_PARSER_VERSION:
            raise ParserContractError(
                f"Expected {PARSER_NAME}=={EXPECTED_PARSER_VERSION}, found {version}."
            )
        self._version = version
        self._parser_factory = parser_factory or cast(EconomyParserFactory, NativeDemoParser)

    def extract(
        self,
        demo_path: Path,
        ticks: tuple[int, ...],
        *,
        expected_sha256: str,
    ) -> EconomyExtraction:
        path = _validate_demo(demo_path)
        actual_sha = _sha256(path)
        if actual_sha != expected_sha256:
            raise ParserContractError(
                "Economy source demo SHA-256 does not match the imported canonical match."
            )
        requested_ticks = tuple(sorted(set(ticks)))
        try:
            backend = self._parser_factory(str(path))
            raw = backend.parse_ticks(ECONOMY_PROPERTIES, ticks=requested_ticks)
        except Exception as exc:
            raise DemoParseError(
                f"demoparser2 failed during freeze-end economy parsing: {type(exc).__name__}: {exc}"
            ) from exc
        if not hasattr(raw, "columns") or not hasattr(raw, "to_dict"):
            raise ParserContractError("demoparser2 parse_ticks() did not return a dataframe.")
        columns = tuple(str(item) for item in raw.columns)
        required = {"tick", "steamid", "name"}
        if not required.issubset(columns):
            missing = ", ".join(sorted(required - set(columns)))
            raise ParserContractError(
                f"Economy tick output is missing required identity columns: {missing}."
            )
        samples: list[EconomySourceSample] = []
        invalid_count = 0
        for record in raw.to_dict(orient="records"):
            invalid: list[str] = []
            integers: dict[str, int | None] = {}
            for field in (
                "current_equip_value",
                "round_start_equip_value",
                "cash_spent_this_round",
                "balance",
                "armor_value",
                "team_num",
                "total_rounds_played",
            ):
                value, is_invalid = _optional_non_negative_int(record.get(field))
                integers[field] = value
                if is_invalid:
                    invalid.append(field)
            booleans: dict[str, bool | None] = {}
            for field in ("has_helmet", "has_defuser"):
                value, is_invalid = _optional_bool(record.get(field))
                booleans[field] = value
                if is_invalid:
                    invalid.append(field)
            inventory, inventory_invalid = _string_sequence(record.get("inventory"))
            if inventory_invalid:
                invalid.append("inventory")
            inventory_ids, ids_invalid = _int_sequence(record.get("inventory_as_ids"))
            if ids_invalid:
                invalid.append("inventory_as_ids")
            invalid_count += len(invalid)
            samples.append(
                EconomySourceSample(
                    tick=int(record["tick"]),
                    steam_id=_identifier(record.get("steamid")),
                    player_name=_optional_string(record.get("name")),
                    current_equip_value=integers["current_equip_value"],
                    round_start_equip_value=integers["round_start_equip_value"],
                    cash_spent_this_round=integers["cash_spent_this_round"],
                    balance=integers["balance"],
                    inventory=inventory,
                    inventory_item_ids=inventory_ids,
                    armor_value=integers["armor_value"],
                    has_helmet=booleans["has_helmet"],
                    has_defuser=booleans["has_defuser"],
                    team_num=integers["team_num"],
                    total_rounds_played=integers["total_rounds_played"],
                    invalid_fields=tuple(invalid),
                )
            )
        warnings: list[str] = []
        omitted = tuple(item for item in ECONOMY_PROPERTIES if item not in columns)
        if omitted:
            warnings.append("demoparser2_omitted_economy_fields:" + ",".join(omitted))
        if invalid_count:
            warnings.append(f"invalid_economy_values_coerced_to_unavailable:{invalid_count}")
        return EconomyExtraction(
            parser_name=PARSER_NAME,
            parser_version=self._version,
            source_demo_sha256=actual_sha,
            requested_ticks=requested_ticks,
            samples=tuple(samples),
            requested_fields=ECONOMY_PROPERTIES,
            source_columns=columns,
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


def _optional_non_negative_int(value: object) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    try:
        numeric = float(cast(Any, value))
        if not isfinite(numeric) or not numeric.is_integer() or numeric < 0:
            return None, True
        return int(numeric), False
    except (TypeError, ValueError, OverflowError):
        return None, True


def _optional_bool(value: object) -> tuple[bool | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool):
        return value, False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value), False
    try:
        numeric = float(cast(Any, value))
    except (TypeError, ValueError, OverflowError):
        return None, True
    if numeric in {0.0, 1.0}:
        return bool(numeric), False
    return None, True


def _string_sequence(value: object) -> tuple[tuple[str, ...] | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, (str, bytes)):
        return None, True
    try:
        return tuple(str(item).strip() for item in cast(Any, value) if str(item).strip()), False
    except TypeError:
        return None, True


def _int_sequence(value: object) -> tuple[tuple[int, ...] | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, (str, bytes)):
        return None, True
    try:
        return tuple(int(item) for item in cast(Any, value)), False
    except (TypeError, ValueError, OverflowError):
        return None, True


def _identifier(value: object) -> str | None:
    if value is None:
        return None
    try:
        return str(int(cast(Any, value)))
    except (TypeError, ValueError, OverflowError):
        text = str(value).strip()
        return text or None


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["ECONOMY_PROPERTIES", "Demoparser2EconomyExtractor"]
