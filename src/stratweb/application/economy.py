"""Application services for versioned economy and equipment context."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.economy.engine import EconomyEngine
from stratweb.economy.models import (
    ECONOMY_RULE_VERSION,
    ECONOMY_SCHEMA_VERSION,
    BuyType,
    DeleteEconomyResult,
    EconomyComputeResult,
    EconomyConfig,
    EconomyRunRecord,
    EconomyRunSummary,
    PlayerEquipmentSnapshot,
    TeamEconomySnapshot,
)
from stratweb.exceptions import EconomyNotFoundError, MatchNotFoundError
from stratweb.ports import EconomyExtractor, EconomyRepository, MatchRepository


class ComputeEconomyService:
    def __init__(
        self,
        match_repository: MatchRepository,
        economy_repository: EconomyRepository,
        extractor: EconomyExtractor,
        *,
        engine: EconomyEngine | None = None,
    ) -> None:
        self._matches = match_repository
        self._economy = economy_repository
        self._extractor = extractor
        self._engine = engine or EconomyEngine()

    def compute(
        self,
        match_id: UUID,
        demo_path: Path,
        *,
        config: EconomyConfig | None = None,
        replace: bool = False,
    ) -> EconomyComputeResult:
        started = perf_counter()
        match = self._matches.get_match(match_id)
        if match is None:
            raise MatchNotFoundError(f"Match not found: {match_id}")
        rounds = self._matches.get_rounds(match_id)
        ticks = tuple(
            sorted({item.freeze_end_tick for item in rounds if item.freeze_end_tick is not None})
        )
        extraction = self._extractor.extract(
            demo_path,
            ticks,
            expected_sha256=match.source_demo_sha256,
        )
        state = self._engine.compute(
            match,
            rounds,
            self._matches.get_players(match_id),
            self._matches.get_memberships(match_id),
            extraction,
            config or EconomyConfig(),
        )
        saved = self._economy.save_economy(state, replace=replace)
        return EconomyComputeResult(
            economy_run_id=saved.economy_run_id,
            economy_fingerprint=saved.economy_fingerprint,
            economy_schema_version=ECONOMY_SCHEMA_VERSION,
            economy_rule_version=ECONOMY_RULE_VERSION,
            match_id=match_id,
            status=saved.status,
            capability=state.capability,
            summary=state.summary,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
            database_path=self._economy.database_path,
        )


class EconomyQueryService:
    def __init__(self, repository: EconomyRepository) -> None:
        self._repository = repository

    def get_summary(
        self, match_id: UUID, *, economy_run_id: UUID | None = None
    ) -> EconomyRunSummary:
        value = (
            self._repository.get_summary_for_run(match_id, economy_run_id)
            if economy_run_id is not None
            else self._repository.get_summary(match_id)
        )
        if value is None:
            raise EconomyNotFoundError(f"Economy run not found for match: {match_id}")
        return value

    def list_runs(self, match_id: UUID) -> tuple[EconomyRunRecord, ...]:
        return self._repository.list_runs(match_id)

    def list_team_snapshots(
        self,
        match_id: UUID,
        *,
        economy_run_id: UUID | None = None,
        round_number: int | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[TeamEconomySnapshot, ...]:
        self.get_summary(match_id, economy_run_id=economy_run_id)
        return self._repository.list_team_snapshots(
            match_id,
            economy_run_id=economy_run_id,
            round_number=round_number,
            side=side,
            buy_type=buy_type,
            limit=limit,
            offset=offset,
        )

    def list_player_snapshots(
        self,
        match_id: UUID,
        *,
        economy_run_id: UUID | None = None,
        round_number: int | None = None,
        participant_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[PlayerEquipmentSnapshot, ...]:
        self.get_summary(match_id, economy_run_id=economy_run_id)
        return self._repository.list_player_snapshots(
            match_id,
            economy_run_id=economy_run_id,
            round_number=round_number,
            participant_id=participant_id,
            limit=limit,
            offset=offset,
        )

    def delete(self, match_id: UUID) -> DeleteEconomyResult:
        runs = self._repository.delete_economy(match_id)
        return DeleteEconomyResult(match_id=match_id, deleted=runs > 0, deleted_runs=runs)


__all__ = ["ComputeEconomyService", "EconomyQueryService"]
