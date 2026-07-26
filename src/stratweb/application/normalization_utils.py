"""Shared deterministic helpers for canonical normalization services."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import polars as pl

from stratweb.domain.enums import Side

WARMUP_COLUMNS = ("is_warmup_period", "is_warmup", "warmup")
ROUND_MARKER_COLUMNS = ("total_rounds_played", "round_number", "round_num", "round")
TICK_COLUMNS = ("tick", "event_tick")


@dataclass(frozen=True, slots=True)
class StableRawRow:
    source_event: str
    row_key: str
    data: Mapping[str, Any]
    tick: int | None


def stable_rows(
    source_event: str,
    frame: pl.DataFrame | None,
    *,
    exclude_warmup: bool = True,
) -> tuple[StableRawRow, ...]:
    if frame is None or frame.is_empty():
        return ()
    sortable: list[tuple[int, str, Mapping[str, Any]]] = []
    for raw in frame.iter_rows(named=True):
        if exclude_warmup and is_truthy(value(raw, *WARMUP_COLUMNS)):
            continue
        payload = {str(key): json_scalar(item) for key, item in raw.items()}
        tick = optional_non_negative_int(value(payload, *TICK_COLUMNS))
        sort_tick = tick if tick is not None else 2**63 - 1
        encoded = canonical_json(payload)
        sortable.append((sort_tick, encoded, payload))
    sortable.sort(key=lambda item: (item[0], item[1]))

    duplicates: dict[str, int] = {}
    result: list[StableRawRow] = []
    for _sort_tick, encoded, result_payload in sortable:
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        duplicate_index = duplicates.get(digest, 0)
        duplicates[digest] = duplicate_index + 1
        result.append(
            StableRawRow(
                source_event=source_event,
                row_key=f"{digest}:{duplicate_index}",
                data=result_payload,
                tick=optional_non_negative_int(value(result_payload, *TICK_COLUMNS)),
            )
        )
    return tuple(result)


def canonical_json(value_to_encode: Any) -> str:
    return json.dumps(
        value_to_encode,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def json_scalar(raw: Any) -> str | int | float | bool | None:
    if is_missing(raw):
        return None
    if isinstance(raw, (str, int, bool)):
        return raw
    if isinstance(raw, float):
        return raw if math.isfinite(raw) else None
    if hasattr(raw, "item"):
        try:
            return json_scalar(raw.item())
        except (TypeError, ValueError):
            pass
    return str(raw)


def value(row: Mapping[str, Any], *aliases: str) -> Any:
    lookup = {str(key).casefold(): item for key, item in row.items()}
    for alias in aliases:
        if alias.casefold() in lookup:
            return lookup[alias.casefold()]
    return None


def find_column(columns: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    lookup = {column.casefold(): column for column in columns}
    return next((lookup[item.casefold()] for item in aliases if item.casefold() in lookup), None)


def optional_text(raw: Any) -> str | None:
    if is_missing(raw):
        return None
    result = str(raw).strip()
    return result or None


def optional_steam_id(raw: Any) -> str | None:
    text = optional_text(raw)
    if text is None:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if not text.isdigit() or int(text) <= 0 or len(text) > 32:
        return None
    return text


def optional_int(raw: Any) -> int | None:
    if is_missing(raw):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def optional_non_negative_int(raw: Any) -> int | None:
    parsed = optional_int(raw)
    return parsed if parsed is not None and parsed >= 0 else None


def optional_float(raw: Any) -> float | None:
    if is_missing(raw):
        return None
    try:
        parsed = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def optional_non_negative_float(raw: Any) -> float | None:
    parsed = optional_float(raw)
    return parsed if parsed is not None and parsed >= 0 else None


def optional_bool(raw: Any) -> bool | None:
    if is_missing(raw):
        return None
    if isinstance(raw, str):
        normalized = raw.strip().casefold()
        if normalized in {"1", "true", "yes", "y"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
        return None
    if isinstance(raw, (bool, int, float)):
        return bool(raw)
    return None


def is_truthy(raw: Any) -> bool:
    return optional_bool(raw) is True


def normalize_side(raw: Any) -> Side:
    if is_missing(raw):
        return Side.UNKNOWN
    normalized = str(raw).strip().casefold()
    if normalized in {"2", "t", "terrorist", "terrorists", "team_t"}:
        return Side.T
    if normalized in {"3", "ct", "counter-terrorist", "counter-terrorists", "team_ct"}:
        return Side.CT
    return Side.UNKNOWN


def is_missing(raw: Any) -> bool:
    if raw is None:
        return True
    try:
        return bool(raw != raw)
    except (TypeError, ValueError):
        return False


def role_values(row: Mapping[str, Any], role: str) -> tuple[str | None, str | None, Side, bool]:
    if role == "attacker":
        prefix = "attacker_"
    elif role == "victim":
        prefix = "user_"
    elif role == "assister":
        prefix = "assister_"
    else:
        prefix = "user_"

    steam = optional_steam_id(value(row, f"{prefix}steamid", f"{prefix}steam_id"))
    name = optional_text(value(row, f"{prefix}name"))
    side = normalize_side(value(row, f"{prefix}team_name", f"{prefix}team"))
    is_bot = is_truthy(value(row, f"{prefix}isbot", f"{prefix}is_bot"))

    if role == "user" and steam is None and name is None:
        steam = optional_steam_id(value(row, "steamid", "steam_id", "player_steamid"))
        name = optional_text(value(row, "name", "player_name"))
        side = normalize_side(value(row, "team_name", "team", "player_team"))
        is_bot = is_truthy(value(row, "isbot", "is_bot"))
    return steam, name, side, is_bot
