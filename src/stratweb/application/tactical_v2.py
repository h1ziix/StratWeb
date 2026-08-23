"""Application services for Tactical Intelligence V2."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.exceptions import (
    OpponentNotFoundError,
    TacticalV2ConfigurationError,
    TacticalV2NotFoundError,
)
from stratweb.ports import OpponentRepository, TacticalV2Repository, TacticalV2SourceRepository
from stratweb.tactical_v2.engine import TacticalV2Engine
from stratweb.tactical_v2.models import (
    TACTICAL_V2_RULE_VERSION,
    TACTICAL_V2_SCHEMA_VERSION,
    TacticalEvidenceReference,
    TacticalInsight,
    TacticalInsightType,
    TacticalV2ComputeResult,
    TacticalV2Config,
    TacticalV2RunRecord,
    TacticalV2RunSummary,
)


class ComputeTacticalV2Service:
    def __init__(
        self,
        opponents: OpponentRepository,
        sources: TacticalV2SourceRepository,
        repository: TacticalV2Repository,
        *,
        engine: TacticalV2Engine | None = None,
    ) -> None:
        self._opponents = opponents
        self._sources = sources
        self._repository = repository
        self._engine = engine or TacticalV2Engine()

    def compute(
        self,
        profile_id: UUID,
        *,
        config: TacticalV2Config | None = None,
        replace: bool = False,
    ) -> TacticalV2ComputeResult:
        started = perf_counter()
        if self._opponents.get_profile(profile_id) is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
        selections = self._opponents.list_selections(profile_id)
        if not selections:
            raise TacticalV2ConfigurationError(
                "Tactical V2 requires at least one user-confirmed opponent match team."
            )
        data = self._sources.load_input(profile_id, selections)
        if not data.matches:
            raise TacticalV2ConfigurationError(
                "No selected match has one compatible Stage 8.4 feature lineage."
            )
        state = self._engine.compute(data, config)
        saved = self._repository.save(state, replace=replace)
        return TacticalV2ComputeResult(
            tactical_run_id=saved.tactical_run_id,
            tactical_fingerprint=saved.tactical_fingerprint,
            tactical_schema_version=TACTICAL_V2_SCHEMA_VERSION,
            tactical_rule_version=TACTICAL_V2_RULE_VERSION,
            profile_id=profile_id,
            status=saved.status,
            summary=state.summary,
            capabilities=state.capabilities,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )


class TacticalV2QueryService:
    def __init__(self, repository: TacticalV2Repository) -> None:
        self._repository = repository

    def get_summary(
        self, profile_id: UUID, *, tactical_run_id: UUID | None = None
    ) -> TacticalV2RunSummary:
        result = (
            self._repository.get_summary_for_run(profile_id, tactical_run_id)
            if tactical_run_id is not None
            else self._repository.get_summary(profile_id)
        )
        if result is None:
            raise TacticalV2NotFoundError(
                f"Compatible Tactical V2 run not found for opponent {profile_id}."
            )
        return result

    def list_runs(self, profile_id: UUID) -> tuple[TacticalV2RunRecord, ...]:
        return self._repository.list_runs(profile_id)

    def list_insights(
        self,
        profile_id: UUID,
        *,
        tactical_run_id: UUID | None = None,
        insight_type: TacticalInsightType | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[TacticalInsight, ...]:
        summary = self.get_summary(profile_id, tactical_run_id=tactical_run_id)
        return self._repository.list_insights(
            profile_id,
            tactical_run_id=summary.tactical_run_id,
            insight_type=insight_type,
            map_name=map_name,
            side=side,
            limit=limit,
            offset=offset,
        )

    def list_evidence(
        self,
        profile_id: UUID,
        insight_id: UUID,
        *,
        tactical_run_id: UUID | None = None,
    ) -> tuple[TacticalEvidenceReference, ...]:
        summary = self.get_summary(profile_id, tactical_run_id=tactical_run_id)
        return self._repository.list_evidence(
            profile_id, insight_id, tactical_run_id=summary.tactical_run_id
        )


__all__ = ["ComputeTacticalV2Service", "TacticalV2QueryService"]
