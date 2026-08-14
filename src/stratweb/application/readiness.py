"""Application composition for Stage 8.6.1 readiness audits."""

from __future__ import annotations

from uuid import UUID

from stratweb.application.findings import AnalysisFindingQueryService
from stratweb.findings.models import AnalysisFinding
from stratweb.readiness.engine import FindingReadinessEngine
from stratweb.readiness.models import (
    FindingReadinessAudit,
    FindingReadinessConfig,
    FindingReadinessInput,
)


class FindingReadinessService:
    def __init__(
        self,
        findings: AnalysisFindingQueryService,
        *,
        engine: FindingReadinessEngine | None = None,
    ) -> None:
        self._findings = findings
        self._engine = engine or FindingReadinessEngine()

    def audit(
        self,
        profile_id: UUID,
        *,
        analysis_run_id: UUID | None = None,
        config: FindingReadinessConfig | None = None,
    ) -> FindingReadinessAudit:
        summary = self._findings.get_summary(profile_id, analysis_run_id=analysis_run_id)
        records: list[AnalysisFinding] = []
        offset = 0
        while True:
            page = self._findings.list_findings(
                profile_id,
                analysis_run_id=summary.analysis_run_id,
                limit=5000,
                offset=offset,
            )
            records.extend(page)
            if len(page) < 5000:
                break
            offset += len(page)
        return self._engine.audit(
            FindingReadinessInput(analysis=summary, findings=tuple(records)), config
        )


__all__ = ["FindingReadinessService"]
