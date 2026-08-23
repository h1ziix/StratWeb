"""Application composition for deterministic Stage 9.4 statistical trust."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.exceptions import (
    PatternNotFoundError,
    StatisticalTrustConfigurationError,
    StatisticalTrustNotFoundError,
)
from stratweb.patterns.models import (
    PATTERN_RULE_VERSION,
    PATTERN_SCHEMA_VERSION,
    CrossMatchPattern,
)
from stratweb.ports import PatternRepository, StatisticalTrustRepository
from stratweb.statistical_trust.engine import StatisticalTrustEngine
from stratweb.statistical_trust.models import (
    STATISTICAL_TRUST_RULE_VERSION,
    STATISTICAL_TRUST_SCHEMA_VERSION,
    StatisticalTrustAssessment,
    StatisticalTrustComputeResult,
    StatisticalTrustConfig,
    StatisticalTrustInput,
    StatisticalTrustRunRecord,
    StatisticalTrustRunSummary,
    TrustDecision,
)

_PAGE_SIZE = 5000


class ComputeStatisticalTrustService:
    def __init__(
        self,
        patterns: PatternRepository,
        trust: StatisticalTrustRepository,
        *,
        engine: StatisticalTrustEngine | None = None,
    ) -> None:
        self._patterns = patterns
        self._trust = trust
        self._engine = engine or StatisticalTrustEngine()

    def compute(
        self,
        profile_id: UUID,
        *,
        config: StatisticalTrustConfig | None = None,
        replace: bool = False,
    ) -> StatisticalTrustComputeResult:
        started = perf_counter()
        source = self._patterns.get_summary(profile_id)
        if source is None:
            raise PatternNotFoundError(
                f"Compatible pattern run not found for opponent {profile_id}."
            )
        if (source.pattern_schema_version, source.pattern_rule_version) != (
            PATTERN_SCHEMA_VERSION,
            PATTERN_RULE_VERSION,
        ):
            raise StatisticalTrustConfigurationError(
                "Statistical Trust requires an exact compatible pattern run."
            )
        patterns: list[CrossMatchPattern] = []
        offset = 0
        while True:
            page = self._patterns.list_patterns(
                profile_id,
                pattern_run_id=source.pattern_run_id,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            patterns.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += len(page)
        state = self._engine.compute(
            StatisticalTrustInput(
                profile_id=profile_id,
                source_pattern_run_id=source.pattern_run_id,
                source_pattern_fingerprint=source.pattern_fingerprint,
                source_pattern_schema_version=source.pattern_schema_version,
                source_pattern_rule_version=source.pattern_rule_version,
                patterns=tuple(patterns),
            ),
            config,
        )
        saved = self._trust.save_trust(state, replace=replace)
        return StatisticalTrustComputeResult(
            trust_run_id=saved.trust_run_id,
            trust_fingerprint=saved.trust_fingerprint,
            trust_schema_version=STATISTICAL_TRUST_SCHEMA_VERSION,
            trust_rule_version=STATISTICAL_TRUST_RULE_VERSION,
            profile_id=profile_id,
            status=saved.status,
            summary=state.summary,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )


class StatisticalTrustQueryService:
    def __init__(self, patterns: PatternRepository, trust: StatisticalTrustRepository) -> None:
        self._patterns = patterns
        self._trust = trust

    def get_summary(
        self, profile_id: UUID, *, trust_run_id: UUID | None = None
    ) -> StatisticalTrustRunSummary:
        if trust_run_id is not None:
            result = self._trust.get_summary_for_run(profile_id, trust_run_id)
        else:
            source = self._patterns.get_summary(profile_id)
            result = (
                self._trust.get_summary(profile_id, source_pattern_run_id=source.pattern_run_id)
                if source is not None
                else None
            )
        if result is None:
            raise StatisticalTrustNotFoundError(
                f"Compatible statistical-trust run not found for opponent {profile_id}."
            )
        return result

    def list_runs(self, profile_id: UUID) -> tuple[StatisticalTrustRunRecord, ...]:
        source = self._patterns.get_summary(profile_id)
        return self._trust.list_runs(
            profile_id,
            current_pattern_run_id=source.pattern_run_id if source is not None else None,
        )

    def list_assessments(
        self,
        profile_id: UUID,
        *,
        trust_run_id: UUID | None = None,
        decision: TrustDecision | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[StatisticalTrustAssessment, ...]:
        summary = self.get_summary(profile_id, trust_run_id=trust_run_id)
        return self._trust.list_assessments(
            profile_id,
            trust_run_id=summary.trust_run_id,
            decision=decision,
            limit=limit,
            offset=offset,
        )


__all__ = ["ComputeStatisticalTrustService", "StatisticalTrustQueryService"]
