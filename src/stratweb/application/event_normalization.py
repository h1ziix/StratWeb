"""Parser-independent normalization of raw round lifecycle event aliases."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import polars as pl

from stratweb.application.inspection_models import CanonicalEventSummary
from stratweb.contracts import ParsedDemo


class CanonicalEventName(StrEnum):
    ROUND_START = "CanonicalRoundStart"
    ROUND_END = "CanonicalRoundEnd"


# Order is intentional: the first successfully parsed source is the preferred
# representative. Counts are never summed across aliases because one round may
# emit several lifecycle events.
CANONICAL_EVENT_ALIASES: Mapping[CanonicalEventName, tuple[str, ...]] = {
    CanonicalEventName.ROUND_START: (
        "round_freeze_end",
        "round_start",
        "round_poststart",
        "round_prestart",
    ),
    CanonicalEventName.ROUND_END: (
        "round_officially_ended",
        "round_end",
    ),
}

_ROUND_MARKER_COLUMNS = (
    "total_rounds_played",
    "round_number",
    "round_num",
    "round",
)
_WARMUP_COLUMNS = ("is_warmup_period", "is_warmup", "warmup")
_TICK_COLUMNS = ("tick", "event_tick")


@dataclass(frozen=True, slots=True)
class EventNormalizationResult:
    canonical_events: dict[str, CanonicalEventSummary]
    estimated_round_count: int | None
    estimated_round_count_source: str | None
    round_count_candidates: dict[str, int]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SourceObservation:
    row_count: int
    distinct_round_count: int


class InspectionEventNormalizer:
    """Normalize lifecycle aliases and derive a conservative round estimate."""

    def normalize(self, parsed: ParsedDemo) -> EventNormalizationResult:
        canonical: dict[str, CanonicalEventSummary] = {}

        for canonical_name, aliases in CANONICAL_EVENT_ALIASES.items():
            canonical[canonical_name.value] = self._normalize_family(parsed, aliases)

        candidates = self._round_count_candidates(parsed, canonical)
        estimate, source = self._select_round_count(candidates)
        warnings = self._round_count_warnings(candidates, estimate, source)

        return EventNormalizationResult(
            canonical_events=canonical,
            estimated_round_count=estimate,
            estimated_round_count_source=source,
            round_count_candidates=candidates,
            warnings=warnings,
        )

    def _normalize_family(
        self,
        parsed: ParsedDemo,
        aliases: tuple[str, ...],
    ) -> CanonicalEventSummary:
        available = set(parsed.available_events)
        observations: dict[str, _SourceObservation] = {}

        for alias in aliases:
            frame = parsed.tables.get(alias)
            if frame is None or alias in parsed.event_errors:
                continue
            observations[alias] = _observe_source(frame)

        selected = next(
            (alias for alias in aliases if observations.get(alias, _EMPTY_OBSERVATION).row_count),
            None,
        )
        count = observations[selected].distinct_round_count if selected else 0

        return CanonicalEventSummary(
            count=count,
            selected_source_event=selected,
            available_source_events=tuple(alias for alias in aliases if alias in available),
            source_row_counts={
                alias: observations[alias].row_count for alias in aliases if alias in observations
            },
        )

    def _round_count_candidates(
        self,
        parsed: ParsedDemo,
        canonical: Mapping[str, CanonicalEventSummary],
    ) -> dict[str, int]:
        candidates: dict[str, int] = {}
        total_rounds_max = _max_total_rounds_played(parsed.tables.values())
        if total_rounds_max is not None and total_rounds_max > 0:
            candidates["max_total_rounds_played"] = total_rounds_max

        end_count = canonical[CanonicalEventName.ROUND_END.value].count
        if end_count > 0:
            candidates["canonical_round_end_count"] = end_count

        start_count = canonical[CanonicalEventName.ROUND_START.value].count
        if start_count > 0:
            candidates["canonical_round_start_count"] = start_count

        return candidates

    @staticmethod
    def _select_round_count(candidates: Mapping[str, int]) -> tuple[int | None, str | None]:
        # `total_rounds_played` is a game-state counter and is more reliable than
        # lifecycle row counts, which can be absent, duplicated, or include warmup.
        for source in (
            "max_total_rounds_played",
            "canonical_round_end_count",
            "canonical_round_start_count",
        ):
            if source in candidates:
                return candidates[source], source
        return None, None

    @staticmethod
    def _round_count_warnings(
        candidates: Mapping[str, int],
        estimate: int | None,
        source: str | None,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if estimate is None:
            return ()
        if source != "max_total_rounds_played":
            warnings.append(
                "Round count is estimated from canonical lifecycle events because "
                "total_rounds_played is unavailable."
            )
        disagreements = {name: value for name, value in candidates.items() if value != estimate}
        if disagreements:
            details = ", ".join(f"{name}={value}" for name, value in sorted(disagreements.items()))
            warnings.append(
                f"Round count candidates disagree; selected {source}={estimate}; {details}."
            )
        return tuple(warnings)


_EMPTY_OBSERVATION = _SourceObservation(row_count=0, distinct_round_count=0)


def _observe_source(frame: pl.DataFrame) -> _SourceObservation:
    gameplay = _without_warmup(frame)
    if gameplay.is_empty():
        return _EMPTY_OBSERVATION

    marker_column = _find_column(gameplay.columns, _ROUND_MARKER_COLUMNS)
    if marker_column:
        markers = _non_negative_ints(gameplay[marker_column].to_list())
        if markers:
            return _SourceObservation(
                row_count=gameplay.height,
                distinct_round_count=len(set(markers)),
            )

    tick_column = _find_column(gameplay.columns, _TICK_COLUMNS)
    if tick_column:
        ticks = [value for value in gameplay[tick_column].to_list() if not _is_missing(value)]
        if ticks:
            return _SourceObservation(
                row_count=gameplay.height,
                distinct_round_count=len(set(ticks)),
            )

    return _SourceObservation(row_count=gameplay.height, distinct_round_count=gameplay.height)


def _max_total_rounds_played(frames: Iterable[pl.DataFrame]) -> int | None:
    maximum: int | None = None
    for frame in frames:
        gameplay = _without_warmup(frame)
        column = _find_column(gameplay.columns, ("total_rounds_played",))
        if column is None:
            continue
        values = _non_negative_ints(gameplay[column].to_list())
        if values:
            current = max(values)
            maximum = current if maximum is None else max(maximum, current)
    return maximum


def _without_warmup(frame: pl.DataFrame) -> pl.DataFrame:
    warmup_column = _find_column(frame.columns, _WARMUP_COLUMNS)
    if warmup_column is None or frame.is_empty():
        return frame
    keep = [not _is_truthy(value) for value in frame[warmup_column].to_list()]
    return frame.filter(pl.Series("keep", keep))


def _find_column(columns: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    lookup = {column.casefold(): column for column in columns}
    return next((lookup[alias.casefold()] for alias in aliases if alias.casefold() in lookup), None)


def _non_negative_ints(values: Iterable[Any]) -> list[int]:
    result: list[int] = []
    for value in values:
        if _is_missing(value):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed >= 0:
            result.append(parsed)
    return result


def _is_truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    return bool(value) if not _is_missing(value) else False


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False
