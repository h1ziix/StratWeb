"""Deterministic reconstruction of logical competitive rounds from event aliases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from stratweb.application.canonical_models import CanonicalRound, ResultCapabilities
from stratweb.application.event_normalization import InspectionEventNormalizer
from stratweb.application.normalization_utils import (
    ROUND_MARKER_COLUMNS,
    StableRawRow,
    optional_non_negative_int,
    stable_rows,
    value,
)
from stratweb.application.outcome_resolution import RoundOutcomeResolver
from stratweb.contracts import ParsedDemo

_START_BOUNDARY_PRECEDENCE = (
    "round_prestart",
    "round_start",
    "round_poststart",
    "round_freeze_end",
)
_END_BOUNDARY_PRECEDENCE = ("round_end", "round_officially_ended")


@dataclass(frozen=True, slots=True)
class RoundResolutionResult:
    rounds: tuple[CanonicalRound, ...]
    result_capabilities: ResultCapabilities
    round_count_candidates: dict[str, int]
    selected_round_count: int | None
    selected_round_count_source: str | None
    selected_event_aliases: dict[str, str | None]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Boundary:
    source: str
    tick: int
    data: dict[str, Any]


class RoundResolver:
    """Resolve rounds without requiring Valve-style round_start/round_end."""

    def resolve(self, parsed: ParsedDemo, match_id: UUID) -> RoundResolutionResult:
        inspection = InspectionEventNormalizer().normalize(parsed)
        starts = {
            source: _boundaries(parsed, source, boundary_type="start")
            for source in _START_BOUNDARY_PRECEDENCE
        }
        ends = {
            source: _boundaries(parsed, source, boundary_type="end")
            for source in _END_BOUNDARY_PRECEDENCE
        }

        observed_round_numbers = {
            round_number
            for mapping in (*starts.values(), *ends.values())
            for round_number in mapping
        }
        selected_count = inspection.estimated_round_count
        if selected_count is None and observed_round_numbers:
            selected_count = max(observed_round_numbers)
        terminal = _terminal_boundary(parsed, selected_count)
        overtime_from_round = _overtime_start_round(parsed)

        warnings = list(inspection.warnings)
        warnings.extend(_alias_disagreement_warnings("round start", starts))
        warnings.extend(_alias_disagreement_warnings("round end", ends))
        rounds: list[CanonicalRound] = []
        for round_number in range(1, (selected_count or 0) + 1):
            start = _first_boundary(starts, _START_BOUNDARY_PRECEDENCE, round_number)
            freeze = starts["round_freeze_end"].get(round_number)
            end = _first_boundary(ends, _END_BOUNDARY_PRECEDENCE, round_number)
            official = ends["round_officially_ended"].get(round_number)
            if end is None and round_number == selected_count and terminal is not None:
                end = terminal

            round_warnings: list[str] = []
            exclusion_reason: str | None = None
            if start is None:
                exclusion_reason = "missing_round_start"
                round_warnings.append("No supported start boundary was observed.")
            if end is None:
                exclusion_reason = (
                    "missing_final_round_end"
                    if round_number == selected_count
                    else "missing_round_end"
                )
                round_warnings.append("No supported end boundary was observed.")
            elif end.source.startswith("fallback:"):
                round_warnings.append(
                    f"Round end uses explicitly marked {end.source} because no "
                    "round-end alias exists."
                )

            is_complete = start is not None and end is not None
            rounds.append(
                CanonicalRound(
                    round_id=uuid5(match_id, f"round:{round_number}"),
                    match_id=match_id,
                    round_number=round_number,
                    start_tick=start.tick if start else None,
                    freeze_end_tick=freeze.tick if freeze else None,
                    end_tick=end.tick if end else None,
                    official_end_tick=official.tick if official else None,
                    start_source=start.source if start else None,
                    end_source=end.source if end else None,
                    is_complete=is_complete,
                    is_overtime=(
                        overtime_from_round is not None and round_number >= overtime_from_round
                    ),
                    exclusion_reason=exclusion_reason,
                    warnings=tuple(round_warnings),
                )
            )

        outcome_result = RoundOutcomeResolver().resolve(parsed, tuple(rounds))
        rounds = list(outcome_result.rounds)
        if rounds and rounds[-1].official_end_tick is None:
            warnings.append("The final round has no observed official end event.")

        selected_aliases = {
            "CanonicalRoundStart": _first_populated(starts, _START_BOUNDARY_PRECEDENCE),
            "CanonicalRoundFreezeEnd": ("round_freeze_end" if starts["round_freeze_end"] else None),
            "CanonicalRoundEnd": _first_populated(ends, _END_BOUNDARY_PRECEDENCE),
            "CanonicalRoundOfficialEnd": (
                "round_officially_ended" if ends["round_officially_ended"] else None
            ),
            "CanonicalMatchTerminal": terminal.source if terminal else None,
            "OvertimePhaseBoundary": (
                "announce_phase_end" if overtime_from_round is not None else None
            ),
        }
        return RoundResolutionResult(
            rounds=tuple(rounds),
            result_capabilities=outcome_result.capabilities,
            round_count_candidates=inspection.round_count_candidates,
            selected_round_count=selected_count,
            selected_round_count_source=inspection.estimated_round_count_source,
            selected_event_aliases=selected_aliases,
            warnings=tuple(dict.fromkeys(warnings)),
        )


def _boundaries(
    parsed: ParsedDemo,
    source: str,
    *,
    boundary_type: str,
) -> dict[int, _Boundary]:
    rows = stable_rows(source, parsed.tables.get(source))
    with_marker: list[tuple[int, int, StableRawRow]] = []
    without_marker: list[StableRawRow] = []
    for row in rows:
        if row.tick is None:
            continue
        total_rounds = optional_non_negative_int(value(row.data, "total_rounds_played"))
        explicit_round = optional_non_negative_int(
            value(row.data, "round_number", "round_num", "round")
        )
        if total_rounds is None and explicit_round is None:
            without_marker.append(row)
            continue
        if total_rounds is not None:
            round_number = total_rounds + 1 if boundary_type == "start" else total_rounds
        else:
            # Explicit round-number fields are treated as 1-based identities;
            # only the game-state counter has before/after-round semantics.
            round_number = explicit_round or 0
        if round_number > 0:
            with_marker.append((round_number, row.tick, row))

    result: dict[int, _Boundary] = {}
    for round_number, tick, row in with_marker:
        current = result.get(round_number)
        # The latest duplicate marker skips pre-match/knife-round reset rows and
        # collapses duplicate officially-ended emissions on FACEIT SourceTV demos.
        if current is None or tick > current.tick:
            result[round_number] = _Boundary(source, tick, dict(row.data))

    if not with_marker:
        unique_ticks = sorted({row.tick for row in without_marker if row.tick is not None})
        for index, tick in enumerate(unique_ticks, start=1):
            result[index] = _Boundary(source, tick, {})
    return result


def _first_boundary(
    mappings: dict[str, dict[int, _Boundary]],
    precedence: tuple[str, ...],
    round_number: int,
) -> _Boundary | None:
    return next(
        (
            mappings[source][round_number]
            for source in precedence
            if round_number in mappings[source]
        ),
        None,
    )


def _first_populated(
    mappings: dict[str, dict[int, _Boundary]],
    precedence: tuple[str, ...],
) -> str | None:
    return next((source for source in precedence if mappings[source]), None)


def _terminal_boundary(parsed: ParsedDemo, selected_count: int | None) -> _Boundary | None:
    if selected_count is None:
        return None
    candidates: list[StableRawRow] = []
    for source in ("cs_win_panel_match", "round_announce_final"):
        for row in stable_rows(source, parsed.tables.get(source)):
            marker = optional_non_negative_int(value(row.data, *ROUND_MARKER_COLUMNS))
            if row.tick is not None and marker == selected_count:
                candidates.append(row)
        if candidates:
            selected = max(candidates, key=lambda item: item.tick or -1)
            return _Boundary(f"fallback:{source}", selected.tick or 0, dict(selected.data))
    return None


def _overtime_start_round(parsed: ParsedDemo) -> int | None:
    phase_markers = sorted(
        {
            marker
            for row in stable_rows("announce_phase_end", parsed.tables.get("announce_phase_end"))
            if (marker := optional_non_negative_int(value(row.data, *ROUND_MARKER_COLUMNS)))
            is not None
            and marker > 0
        }
    )
    # Two observed completed match phases establish regulation without assuming
    # MR12/MR15. Any round after the second phase boundary belongs to overtime.
    return phase_markers[1] + 1 if len(phase_markers) >= 2 else None


def _alias_disagreement_warnings(
    family: str,
    mappings: dict[str, dict[int, _Boundary]],
) -> tuple[str, ...]:
    counts = {source: len(rows) for source, rows in mappings.items() if rows}
    if len(set(counts.values())) <= 1:
        return ()
    details = ", ".join(f"{source}={count}" for source, count in sorted(counts.items()))
    return (f"Alias disagreement for {family}: {details}.",)
