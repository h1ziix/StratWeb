"""Prepare a report from existing round features without changing analytical policies."""

from __future__ import annotations

from uuid import UUID

from stratweb.application.counter_strategy import ComputeCounterStrategiesService
from stratweb.application.findings import ComputeAnalysisFindingsService
from stratweb.application.patterns import ComputeCrossMatchPatternsService
from stratweb.counter_strategy.models import CounterStrategyComputeResult
from stratweb.exceptions import PersistenceError


class ReportPreparationUnavailableError(PersistenceError):
    """No processed selected match can contribute to the report yet."""


class PrepareScoutingReportService:
    """Compose existing idempotent stages; never lower confidence/readiness thresholds."""

    def __init__(
        self,
        patterns: ComputeCrossMatchPatternsService,
        findings: ComputeAnalysisFindingsService,
        strategies: ComputeCounterStrategiesService,
    ) -> None:
        self._patterns = patterns
        self._findings = findings
        self._strategies = strategies

    def prepare(self, profile_id: UUID) -> CounterStrategyComputeResult:
        patterns = self._patterns.compute(profile_id)
        if patterns.summary.included_matches == 0:
            raise ReportPreparationUnavailableError(
                "No selected match has compatible round features."
            )
        self._findings.compute(profile_id)
        return self._strategies.compute(profile_id)
