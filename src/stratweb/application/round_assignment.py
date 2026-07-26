"""One authoritative event-to-round assignment policy."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from stratweb.application.canonical_models import CanonicalRound, EventPhase


@dataclass(frozen=True, slots=True)
class RoundAssignment:
    round_id: UUID | None
    round_number: int | None
    relative_tick: int | None
    phase: EventPhase


class RoundAssignmentService:
    """Assign by half-open round windows; never guess before the first start."""

    def __init__(self, rounds: tuple[CanonicalRound, ...]) -> None:
        self._rounds = tuple(
            round_item for round_item in rounds if round_item.start_tick is not None
        )
        self._starts = tuple(cast(int, round_item.start_tick) for round_item in self._rounds)

    def assign(self, tick: int) -> RoundAssignment:
        if tick < 0 or not self._rounds:
            return _unassigned()
        index = bisect_right(self._starts, tick) - 1
        if index < 0:
            return _unassigned()

        round_item = self._rounds[index]
        next_start = self._starts[index + 1] if index + 1 < len(self._starts) else None
        if next_start is not None and tick >= next_start:
            return _unassigned()

        start_tick = cast(int, round_item.start_tick)
        if round_item.freeze_end_tick is not None and tick < round_item.freeze_end_tick:
            phase = EventPhase.FREEZE_TIME
        elif round_item.end_tick is not None and tick >= round_item.end_tick:
            phase = EventPhase.POST_ROUND
        elif round_item.freeze_end_tick is not None and tick >= round_item.freeze_end_tick:
            phase = EventPhase.LIVE
        else:
            phase = EventPhase.UNKNOWN

        return RoundAssignment(
            round_id=round_item.round_id,
            round_number=round_item.round_number,
            relative_tick=tick - start_tick,
            phase=phase,
        )


def _unassigned() -> RoundAssignment:
    return RoundAssignment(
        round_id=None,
        round_number=None,
        relative_tick=None,
        phase=EventPhase.UNKNOWN,
    )
