"""Application service for critical mistake filters."""

from uuid import UUID

from stratweb.adapters.persistence.critical_mistakes_duckdb import DuckDBCriticalMistakesRepository
from stratweb.critical_mistakes.engine import CriticalMistakeEngine
from stratweb.critical_mistakes.models import CriticalMistakesRun, CriticalSaveResult


class CriticalMistakesService:
    def __init__(self, repository: DuckDBCriticalMistakesRepository) -> None:
        self._repository = repository
        self._engine = CriticalMistakeEngine()

    def compute(self, profile_id: UUID) -> tuple[CriticalMistakesRun, CriticalSaveResult]:
        state = self._engine.compute(self._repository.build_input(profile_id))
        return state, self._repository.save(state)

    def get_latest(self, profile_id: UUID) -> CriticalMistakesRun | None:
        saved = self._repository.get_latest(profile_id)
        if saved is None:
            return None
        current = self._engine.compute(self._repository.build_input(profile_id))
        return saved if saved.critical_fingerprint == current.critical_fingerprint else None


__all__ = ["CriticalMistakesService"]
