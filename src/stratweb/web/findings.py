"""JSON endpoints for immutable Stage 8.6 findings and evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request

from stratweb.adapters.persistence import (
    DuckDBAnalysisRepository,
    DuckDBMatchRepository,
    DuckDBPatternRepository,
)
from stratweb.application.findings import (
    AnalysisFindingQueryService,
    ComputeAnalysisFindingsService,
)
from stratweb.application.readiness import FindingReadinessService
from stratweb.domain.enums import Side
from stratweb.findings.models import FindingCategory, FindingConfig
from stratweb.patterns.models import PatternType
from stratweb.readiness.models import FindingReadinessConfig
from stratweb.web.context import require_localhost


def finding_router(database_path: Path) -> APIRouter:
    router = APIRouter()
    patterns = DuckDBPatternRepository(database_path)
    analysis = DuckDBAnalysisRepository(database_path)
    query = AnalysisFindingQueryService(patterns, analysis)
    compute = ComputeAnalysisFindingsService(
        patterns, DuckDBMatchRepository(database_path), analysis
    )
    readiness = FindingReadinessService(query)

    @router.post("/api/opponents/{profile_id}/analysis/compute", tags=["findings"])
    def compute_findings(
        request: Request,
        profile_id: UUID,
        include_partial_patterns: bool = True,
        include_zero_frequency: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        require_localhost(request, "Analysis finding computation")
        result = compute.compute(
            profile_id,
            config=FindingConfig(
                include_partial_patterns=include_partial_patterns,
                include_zero_frequency=include_zero_frequency,
            ),
            replace=force,
        )
        return result.model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/analysis/summary", tags=["findings"])
    def summary(profile_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return query.get_summary(profile_id, analysis_run_id=run_id).model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/analysis/runs", tags=["findings"])
    def runs(profile_id: UUID) -> dict[str, Any]:
        records = query.list_runs(profile_id)
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "runs": [item.model_dump(mode="json") for item in records],
        }

    @router.get("/api/opponents/{profile_id}/analysis/readiness", tags=["finding-readiness"])
    def readiness_audit(
        profile_id: UUID,
        run_id: UUID | None = None,
        minimum_corpus_matches: Annotated[int, Query(ge=1)] = 15,
        minimum_finding_matches: Annotated[int, Query(ge=1)] = 2,
        block_partial_source: bool = True,
        require_known_buy_type: bool = True,
        require_all_evidence_ticks: bool = False,
    ) -> dict[str, Any]:
        result = readiness.audit(
            profile_id,
            analysis_run_id=run_id,
            config=FindingReadinessConfig(
                minimum_corpus_matches=minimum_corpus_matches,
                minimum_finding_matches=minimum_finding_matches,
                block_partial_source=block_partial_source,
                require_known_buy_type=require_known_buy_type,
                require_all_evidence_ticks=require_all_evidence_ticks,
            ),
        )
        return result.model_dump(mode="json")

    @router.get("/api/opponents/{profile_id}/analysis/findings", tags=["findings"])
    def findings(
        profile_id: UUID,
        run_id: UUID | None = None,
        map_name: Annotated[str | None, Query(alias="map")] = None,
        side: Side | None = None,
        category: FindingCategory | None = None,
        pattern_type: Annotated[PatternType | None, Query(alias="type")] = None,
        limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        records = query.list_findings(
            profile_id,
            analysis_run_id=run_id,
            map_name=map_name,
            side=side,
            category=category,
            pattern_type=pattern_type,
            limit=limit,
            offset=offset,
        )
        return {
            "profile_id": str(profile_id),
            "count": len(records),
            "findings": [item.model_dump(mode="json") for item in records],
        }

    @router.get("/api/opponents/{profile_id}/analysis/findings/{finding_id}", tags=["findings"])
    def finding(profile_id: UUID, finding_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        return query.get_finding(profile_id, finding_id, analysis_run_id=run_id).model_dump(
            mode="json"
        )

    @router.get(
        "/api/opponents/{profile_id}/analysis/findings/{finding_id}/evidence",
        tags=["findings"],
    )
    def evidence(profile_id: UUID, finding_id: UUID, run_id: UUID | None = None) -> dict[str, Any]:
        record = query.get_finding(profile_id, finding_id, analysis_run_id=run_id)
        return {
            "analysis_run_id": str(record.analysis_run_id),
            "finding_id": str(record.finding_id),
            "count": len(record.evidence_references),
            "evidence": [item.model_dump(mode="json") for item in record.evidence_references],
        }

    return router


__all__ = ["finding_router"]
