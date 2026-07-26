"""Authoritative, deterministic round outcome and score resolution."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from stratweb.application.canonical_models import (
    CanonicalRound,
    CapabilityCoverageStatus,
    DataAvailability,
    ResultCapabilities,
    ResultCapability,
    RoundOutcomeStatus,
)
from stratweb.application.normalization_utils import (
    ROUND_MARKER_COLUMNS,
    normalize_side,
    optional_non_negative_int,
    optional_text,
    stable_rows,
    value,
)
from stratweb.contracts import ParsedDemo
from stratweb.domain.enums import Side

ROUND_WINNER_FIELD = "CCSGameRulesProxy.CCSGameRules.m_iRoundEndWinnerTeam"
ROUND_END_REASON_FIELD = "CCSGameRulesProxy.CCSGameRules.m_eRoundEndReason"
TEAM_SCORE_FIELD = "CCSTeam.m_iScore"
T_SCORE_FIELD = "t_CCSTeam.m_iScore"
CT_SCORE_FIELD = "ct_CCSTeam.m_iScore"

OUTCOME_SOURCE_EVENTS: tuple[str, ...] = (
    "round_end",
    "round_officially_ended",
    "cs_win_panel_round",
    "cs_win_panel_match",
)

OUTCOME_PARSE_PROPERTIES: tuple[str, ...] = (
    ROUND_WINNER_FIELD,
    ROUND_END_REASON_FIELD,
    TEAM_SCORE_FIELD,
)

_WINNER_FIELDS = (
    ROUND_WINNER_FIELD,
    "winner",
    "winner_side",
    "winning_team",
    "winner_team",
)
_END_REASON_FIELDS = (
    ROUND_END_REASON_FIELD,
    "reason",
    "end_reason",
    "round_end_reason",
)


@dataclass(frozen=True, slots=True)
class RoundOutcomeResolutionResult:
    rounds: tuple[CanonicalRound, ...]
    capabilities: ResultCapabilities


@dataclass(frozen=True, slots=True)
class _Observation:
    source_event: str
    tick: int
    data: dict[str, Any]


class RoundOutcomeResolver:
    """Use only audited game-event fields or authoritative score deltas."""

    def resolve(
        self,
        parsed: ParsedDemo,
        rounds: tuple[CanonicalRound, ...],
    ) -> RoundOutcomeResolutionResult:
        observations = _collect_observations(parsed)
        detected_columns = _detected_columns(parsed)
        resolved: list[CanonicalRound] = []
        previous_score: tuple[int, int] | None = None

        for round_item in rounds:
            selected = _select_observations(round_item, observations)
            winner, outcome_status, outcome_source = _resolve_winner(selected)
            score_candidates = _score_candidates(selected)

            if winner is None and outcome_status is RoundOutcomeStatus.MISSING_FROM_SOURCE:
                derived = _winner_from_score_delta(previous_score, score_candidates)
                if derived is not None:
                    winner = derived
                    outcome_status = RoundOutcomeStatus.DERIVED_FROM_AUTHORITATIVE_SCORE_DELTA
                    outcome_source = _score_source(selected, derived=True)

            score_values, score_status, score_source = _resolve_score(
                score_candidates,
                previous_score=previous_score,
                winner=winner,
                selected=selected,
            )
            reason, reason_status, reason_source = _resolve_end_reason(selected)

            before_t: int | None
            before_ct: int | None
            after_t: int | None
            after_ct: int | None
            if score_status is DataAvailability.AVAILABLE and score_values is not None:
                before_t, before_ct, after_t, after_ct = score_values
                previous_score = (after_t, after_ct)
            else:
                before_t = before_ct = after_t = after_ct = None
                previous_score = None

            payload = round_item.model_dump()
            payload.update(
                {
                    "winner_side": winner,
                    "outcome_status": outcome_status,
                    "outcome_source": outcome_source,
                    "end_reason": reason,
                    "end_reason_status": reason_status,
                    "end_reason_source": reason_source,
                    "score_t_before": before_t,
                    "score_ct_before": before_ct,
                    "score_t_after": after_t,
                    "score_ct_after": after_ct,
                    "score_status": score_status,
                    "score_source": score_source,
                }
            )
            resolved.append(CanonicalRound.model_validate(payload))

        result = tuple(resolved)
        return RoundOutcomeResolutionResult(
            rounds=result,
            capabilities=_build_capabilities(result, detected_columns),
        )


def _collect_observations(
    parsed: ParsedDemo,
) -> dict[int, dict[str, tuple[_Observation, ...]]]:
    grouped: dict[tuple[int, str], list[_Observation]] = defaultdict(list)
    for source in OUTCOME_SOURCE_EVENTS:
        for row in stable_rows(source, parsed.tables.get(source)):
            if row.tick is None:
                continue
            marker = optional_non_negative_int(value(row.data, *ROUND_MARKER_COLUMNS))
            if marker is None or marker < 1:
                continue
            grouped[(marker, source)].append(
                _Observation(source_event=source, tick=row.tick, data=dict(row.data))
            )

    result: dict[int, dict[str, tuple[_Observation, ...]]] = defaultdict(dict)
    for (round_number, source), items in grouped.items():
        latest_tick = max(item.tick for item in items)
        latest = tuple(item for item in items if item.tick == latest_tick)
        result[round_number][source] = latest
    return dict(result)


def _select_observations(
    round_item: CanonicalRound,
    observations: dict[int, dict[str, tuple[_Observation, ...]]],
) -> tuple[_Observation, ...]:
    by_source = observations.get(round_item.round_number, {})
    preferred = (round_item.end_source or "").removeprefix("fallback:")
    precedence = tuple(dict.fromkeys((preferred, *OUTCOME_SOURCE_EVENTS)))
    return tuple(observation for source in precedence for observation in by_source.get(source, ()))


def _resolve_winner(
    selected: tuple[_Observation, ...],
) -> tuple[Side | None, RoundOutcomeStatus, str | None]:
    if not selected:
        return None, RoundOutcomeStatus.MISSING_FROM_SOURCE, None
    sides: set[Side] = set()
    observed_nonempty = False
    sources: set[str] = set()
    for observation in selected:
        raw, detected = _first_value(observation.data, _WINNER_FIELDS)
        if raw is None:
            continue
        observed_nonempty = True
        if detected is not None:
            sources.add(f"{observation.source_event}:{detected}")
        side = normalize_side(raw)
        if side in {Side.T, Side.CT}:
            sides.add(side)
    source = "|".join(sorted(sources)) or None
    if len(sides) == 1 and observed_nonempty:
        return next(iter(sides)), RoundOutcomeStatus.SOURCE_EVENT, source
    if observed_nonempty:
        return None, RoundOutcomeStatus.UNRESOLVED_CONFLICT, source
    return None, RoundOutcomeStatus.MISSING_FROM_SOURCE, source


def _score_candidates(selected: tuple[_Observation, ...]) -> set[tuple[int, int]]:
    candidates: set[tuple[int, int]] = set()
    for observation in selected:
        t_score = optional_non_negative_int(value(observation.data, T_SCORE_FIELD))
        ct_score = optional_non_negative_int(value(observation.data, CT_SCORE_FIELD))
        if t_score is not None and ct_score is not None:
            candidates.add((t_score, ct_score))
    return candidates


def _winner_from_score_delta(
    previous_score: tuple[int, int] | None,
    candidates: set[tuple[int, int]],
) -> Side | None:
    if previous_score is None:
        return None
    swapped_score = (previous_score[1], previous_score[0])
    derived = {
        winner
        for candidate in candidates
        for baseline in (previous_score, swapped_score)
        for winner in (
            Side.T
            if candidate == (baseline[0] + 1, baseline[1])
            else Side.CT
            if candidate == (baseline[0], baseline[1] + 1)
            else None,
        )
    }
    derived.discard(None)
    return next(iter(derived)) if len(derived) == 1 else None


def _resolve_score(
    candidates: set[tuple[int, int]],
    *,
    previous_score: tuple[int, int] | None,
    winner: Side | None,
    selected: tuple[_Observation, ...],
) -> tuple[tuple[int, int, int, int] | None, DataAvailability, str | None]:
    source = _score_source(selected, derived=False)
    if not candidates:
        return None, DataAvailability.MISSING_FROM_SOURCE, source
    if winner not in {Side.T, Side.CT}:
        return None, DataAvailability.UNRESOLVED, source

    chosen: tuple[int, int] | None = None
    baseline: tuple[int, int] | None = None
    if previous_score is not None:
        swapped_score = (previous_score[1], previous_score[0])
        matching = {
            (candidate, candidate_baseline)
            for candidate_baseline in (previous_score, swapped_score)
            for candidate in candidates
            if candidate
            == (
                (candidate_baseline[0] + 1, candidate_baseline[1])
                if winner is Side.T
                else (candidate_baseline[0], candidate_baseline[1] + 1)
            )
        }
        if len(matching) == 1:
            chosen, baseline = next(iter(matching))
    elif len(candidates) == 1:
        chosen = next(iter(candidates))

    if chosen is None:
        return None, DataAvailability.UNRESOLVED, source
    before = baseline or (
        (chosen[0] - 1, chosen[1]) if winner is Side.T else (chosen[0], chosen[1] - 1)
    )
    if min(before) < 0:
        return None, DataAvailability.UNRESOLVED, source
    suffixes = []
    if len(candidates) > 1:
        suffixes.append("resolved_by_authoritative_winner_delta")
    if previous_score is not None and baseline == (previous_score[1], previous_score[0]):
        suffixes.append("side_score_orientation_swapped")
    suffix = f"|{'|'.join(suffixes)}" if suffixes else ""
    return (*before, *chosen), DataAvailability.AVAILABLE, (source or "") + suffix


def _resolve_end_reason(
    selected: tuple[_Observation, ...],
) -> tuple[str | None, DataAvailability, str | None]:
    if not selected:
        return None, DataAvailability.MISSING_FROM_SOURCE, None
    reasons: set[str] = set()
    sources: set[str] = set()
    for observation in selected:
        raw, detected = _first_value(observation.data, _END_REASON_FIELDS)
        reason = optional_text(raw)
        if reason is not None:
            reasons.add(reason)
            if detected is not None:
                sources.add(f"{observation.source_event}:{detected}")
    source = "|".join(sorted(sources)) or None
    if len(reasons) == 1:
        return next(iter(reasons)), DataAvailability.AVAILABLE, source
    if reasons:
        return None, DataAvailability.UNRESOLVED, source
    return None, DataAvailability.MISSING_FROM_SOURCE, source


def _first_value(data: dict[str, Any], aliases: tuple[str, ...]) -> tuple[Any, str | None]:
    lookup = {str(key).casefold(): str(key) for key in data}
    for alias in aliases:
        original = lookup.get(alias.casefold())
        if original is not None:
            return data[original], original
    return None, None


def _score_source(selected: tuple[_Observation, ...], *, derived: bool) -> str | None:
    if not selected:
        return None
    sources = {
        f"{item.source_event}:{T_SCORE_FIELD}+{CT_SCORE_FIELD}"
        for item in selected
        if T_SCORE_FIELD.casefold() in {str(key).casefold() for key in item.data}
        and CT_SCORE_FIELD.casefold() in {str(key).casefold() for key in item.data}
    }
    if not sources:
        return None
    suffix = "|winner_derived_from_delta" if derived else ""
    return "|".join(sorted(sources)) + suffix


def _detected_columns(parsed: ParsedDemo) -> set[str]:
    return {
        column
        for source in OUTCOME_SOURCE_EVENTS
        if (frame := parsed.tables.get(source)) is not None
        for column in frame.columns
    }


def _build_capabilities(
    rounds: tuple[CanonicalRound, ...],
    detected_columns: set[str],
) -> ResultCapabilities:
    winner_detected = tuple(
        sorted(column for column in detected_columns if column in _WINNER_FIELDS)
    )
    score_detected = tuple(
        field for field in (T_SCORE_FIELD, CT_SCORE_FIELD) if field in detected_columns
    )
    reason_detected = tuple(
        sorted(column for column in detected_columns if column in _END_REASON_FIELDS)
    )
    winner_capability_fields = tuple(
        dict.fromkeys(
            (
                *winner_detected,
                *(
                    score_detected
                    if any(
                        round_item.outcome_status
                        is RoundOutcomeStatus.DERIVED_FROM_AUTHORITATIVE_SCORE_DELTA
                        for round_item in rounds
                    )
                    else ()
                ),
            )
        )
    )
    return ResultCapabilities(
        round_winner=_outcome_capability(rounds, winner_capability_fields),
        round_score=_availability_capability(
            tuple(round_item.score_status for round_item in rounds),
            score_detected,
        ),
        round_end_reason=_availability_capability(
            tuple(round_item.end_reason_status for round_item in rounds),
            reason_detected,
        ),
    )


def _outcome_capability(
    rounds: tuple[CanonicalRound, ...], detected_fields: tuple[str, ...]
) -> ResultCapability:
    available = sum(round_item.outcome_status.is_available for round_item in rounds)
    missing = sum(
        round_item.outcome_status is RoundOutcomeStatus.MISSING_FROM_SOURCE for round_item in rounds
    )
    unresolved = len(rounds) - available - missing
    return _capability(len(rounds), available, missing, unresolved, detected_fields)


def _availability_capability(
    statuses: tuple[DataAvailability, ...], detected_fields: tuple[str, ...]
) -> ResultCapability:
    available = statuses.count(DataAvailability.AVAILABLE)
    missing = statuses.count(DataAvailability.MISSING_FROM_SOURCE)
    unresolved = statuses.count(DataAvailability.UNRESOLVED)
    not_applicable = statuses.count(DataAvailability.NOT_APPLICABLE)
    if not_applicable:
        missing += not_applicable
    return _capability(len(statuses), available, missing, unresolved, detected_fields)


def _capability(
    total: int,
    available: int,
    missing: int,
    unresolved: int,
    detected_fields: tuple[str, ...],
) -> ResultCapability:
    if total == 0:
        status = CapabilityCoverageStatus.NOT_APPLICABLE
    elif available == total:
        status = CapabilityCoverageStatus.AVAILABLE
    elif available:
        status = CapabilityCoverageStatus.PARTIAL
    elif unresolved:
        status = CapabilityCoverageStatus.UNRESOLVED
    else:
        status = CapabilityCoverageStatus.MISSING_FROM_SOURCE
    return ResultCapability(
        status=status,
        source_events_checked=OUTCOME_SOURCE_EVENTS,
        detected_fields=detected_fields,
        authoritative_source_found=bool(detected_fields),
        total_round_count=total,
        rounds_available=available,
        rounds_missing=missing,
        rounds_unresolved=unresolved,
    )
