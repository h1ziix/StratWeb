"""Application orchestration for head-to-head tactical comparisons."""

from __future__ import annotations

from uuid import UUID

from stratweb.application.tactical_v2 import TacticalV2QueryService
from stratweb.exceptions import (
    HeadToHeadConfigurationError,
    HeadToHeadNotFoundError,
    OpponentNotFoundError,
    TacticalV2NotFoundError,
)
from stratweb.head_to_head.engine import HeadToHeadEngine
from stratweb.head_to_head.models import (
    HeadToHeadInput,
    HeadToHeadRun,
    HeadToHeadRunRecord,
    HeadToHeadSaveResult,
)
from stratweb.ports import HeadToHeadRepository, OpponentRepository


class HeadToHeadService:
    def __init__(
        self,
        opponents: OpponentRepository,
        tactical: TacticalV2QueryService,
        repository: HeadToHeadRepository,
        *,
        engine: HeadToHeadEngine | None = None,
    ) -> None:
        self._opponents = opponents
        self._tactical = tactical
        self._repository = repository
        self._engine = engine or HeadToHeadEngine()

    def compute(
        self, opponent_profile_id: UUID, our_profile_id: UUID
    ) -> tuple[HeadToHeadRun, HeadToHeadSaveResult]:
        self._validate_profiles(opponent_profile_id, our_profile_id)
        data = self._input(opponent_profile_id, our_profile_id)
        state = self._engine.compute(data)
        return state, self._repository.save(state)

    def get_current(
        self, opponent_profile_id: UUID, our_profile_id: UUID
    ) -> HeadToHeadRun:
        self._validate_profiles(opponent_profile_id, our_profile_id)
        data = self._input(opponent_profile_id, our_profile_id)
        result = self._repository.get_for_sources(
            opponent_profile_id,
            our_profile_id,
            data.opponent_summary.tactical_run_id,
            data.our_summary.tactical_run_id,
        )
        if result is None:
            raise HeadToHeadNotFoundError(
                "Для текущих разборов двух команд сравнение ещё не рассчитано."
            )
        return result

    def get_run(
        self, opponent_profile_id: UUID, our_profile_id: UUID, run_id: UUID
    ) -> HeadToHeadRun:
        self._validate_profiles(opponent_profile_id, our_profile_id)
        result = self._repository.get_run(opponent_profile_id, our_profile_id, run_id)
        if result is None:
            raise HeadToHeadNotFoundError("Сохранённое сравнение не найдено.")
        return result

    def list_runs(
        self, opponent_profile_id: UUID, our_profile_id: UUID
    ) -> tuple[HeadToHeadRunRecord, ...]:
        self._validate_profiles(opponent_profile_id, our_profile_id)
        return self._repository.list_runs(opponent_profile_id, our_profile_id)

    def _input(self, opponent_profile_id: UUID, our_profile_id: UUID) -> HeadToHeadInput:
        try:
            opponent_summary = self._tactical.get_summary(opponent_profile_id)
            our_summary = self._tactical.get_summary(our_profile_id)
        except TacticalV2NotFoundError as exc:
            raise HeadToHeadConfigurationError(
                "Сначала рассчитайте тактический обзор отдельно для обеих команд."
            ) from exc
        return HeadToHeadInput(
            opponent_profile_id=opponent_profile_id,
            our_profile_id=our_profile_id,
            opponent_summary=opponent_summary,
            our_summary=our_summary,
            opponent_insights=self._tactical.list_insights(
                opponent_profile_id,
                tactical_run_id=opponent_summary.tactical_run_id,
                limit=5000,
            ),
            our_insights=self._tactical.list_insights(
                our_profile_id,
                tactical_run_id=our_summary.tactical_run_id,
                limit=5000,
            ),
        )

    def _validate_profiles(self, opponent_profile_id: UUID, our_profile_id: UUID) -> None:
        if opponent_profile_id == our_profile_id:
            raise HeadToHeadConfigurationError(
                "Для сравнения выберите отдельный профиль нашей команды."
            )
        if self._opponents.get_profile(opponent_profile_id) is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {opponent_profile_id}")
        if self._opponents.get_profile(our_profile_id) is None:
            raise OpponentNotFoundError(f"Own-team profile not found: {our_profile_id}")


__all__ = ["HeadToHeadService"]
