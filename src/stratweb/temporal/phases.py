"""Authoritative round phase-interval construction."""

from __future__ import annotations

from uuid import uuid5

from stratweb.application.canonical_models import CanonicalRound

from .definitions import first_available_tick
from .models import (
    PhaseInterval,
    PhaseIntervalStatus,
    RoundPhase,
)


def build_phase_intervals(round_item: CanonicalRound) -> tuple[PhaseInterval, ...]:
    start = round_item.start_tick
    if start is None:
        return ()
    freeze = round_item.freeze_end_tick
    live_end = first_available_tick(round_item.end_tick, round_item.official_end_tick)
    effective_end = first_available_tick(round_item.official_end_tick, round_item.end_tick)
    result: list[PhaseInterval] = []

    if freeze is None:
        result.append(
            _interval(
                round_item,
                RoundPhase.UNKNOWN,
                start,
                effective_end,
                round_item.start_source or "canonical:start_tick",
                round_item.end_source,
                PhaseIntervalStatus.PARTIAL,
            )
        )
    else:
        result.append(
            _interval(
                round_item,
                RoundPhase.FREEZE_TIME,
                start,
                freeze,
                round_item.start_source or "canonical:start_tick",
                "canonical:freeze_end_tick",
                PhaseIntervalStatus.AVAILABLE,
            )
        )
        result.append(
            _interval(
                round_item,
                RoundPhase.LIVE,
                freeze,
                live_end,
                "canonical:freeze_end_tick",
                round_item.end_source,
                (
                    PhaseIntervalStatus.AVAILABLE
                    if live_end is not None
                    else PhaseIntervalStatus.PARTIAL
                ),
            )
        )

    if (
        round_item.end_tick is not None
        and round_item.official_end_tick is not None
        and round_item.official_end_tick > round_item.end_tick
    ):
        result.append(
            _interval(
                round_item,
                RoundPhase.POST_ROUND,
                round_item.end_tick,
                round_item.official_end_tick,
                round_item.end_source or "canonical:end_tick",
                "canonical:official_end_tick",
                PhaseIntervalStatus.AVAILABLE,
            )
        )
    if effective_end is not None:
        result.append(
            _interval(
                round_item,
                RoundPhase.ENDED,
                effective_end,
                None,
                round_item.end_source or "canonical:effective_end",
                None,
                (
                    PhaseIntervalStatus.INFERRED_AUTHORITATIVELY
                    if (round_item.end_source or "").startswith("fallback:")
                    else PhaseIntervalStatus.AVAILABLE
                ),
            )
        )
    return tuple(result)


def phase_at_tick(intervals: tuple[PhaseInterval, ...], tick: int) -> RoundPhase:
    if intervals and tick < intervals[0].start_tick:
        return RoundPhase.PRESTART
    for interval in intervals:
        if tick < interval.start_tick:
            continue
        if interval.end_tick is None or tick < interval.end_tick:
            return interval.phase
    return RoundPhase.UNKNOWN


def _interval(
    round_item: CanonicalRound,
    phase: RoundPhase,
    start_tick: int,
    end_tick: int | None,
    start_source: str,
    end_source: str | None,
    status: PhaseIntervalStatus,
) -> PhaseInterval:
    return PhaseInterval(
        interval_id=uuid5(
            round_item.round_id,
            f"temporal:phase:{phase.value}:{start_tick}:{end_tick}",
        ),
        match_id=round_item.match_id,
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        phase=phase,
        start_tick=start_tick,
        end_tick=end_tick,
        start_source=start_source,
        end_source=end_source,
        status=status,
    )
