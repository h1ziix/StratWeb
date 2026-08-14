"""Application composition for Stage 8.6 analysis findings."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.domain.enums import Side
from stratweb.exceptions import AnalysisFindingNotFoundError, PatternNotFoundError
from stratweb.findings.engine import AnalysisFindingEngine
from stratweb.findings.models import (
    FINDING_RULE_VERSION,
    FINDING_SCHEMA_VERSION,
    AnalysisComputeResult,
    AnalysisFinding,
    AnalysisRunRecord,
    AnalysisRunSummary,
    FindingCategory,
    FindingConfig,
    FindingEngineInput,
    FindingMatchInput,
)
from stratweb.patterns.models import CrossMatchPattern, PatternType
from stratweb.ports import AnalysisRepository, MatchRepository, PatternRepository


class ComputeAnalysisFindingsService:
    def __init__(
        self,
        patterns: PatternRepository,
        matches: MatchRepository,
        analysis: AnalysisRepository,
        *,
        engine: AnalysisFindingEngine | None = None,
    ) -> None:
        self._patterns = patterns
        self._matches = matches
        self._analysis = analysis
        self._engine = engine or AnalysisFindingEngine()

    def compute(
        self,
        profile_id: UUID,
        *,
        config: FindingConfig | None = None,
        replace: bool = False,
    ) -> AnalysisComputeResult:
        started = perf_counter()
        source = self._patterns.get_summary(profile_id)
        if source is None:
            raise PatternNotFoundError(
                f"Compatible Stage 8.5 pattern run not found for profile {profile_id}."
            )
        patterns: list[CrossMatchPattern] = []
        offset = 0
        while True:
            page = self._patterns.list_patterns(
                profile_id,
                pattern_run_id=source.pattern_run_id,
                limit=5000,
                offset=offset,
            )
            patterns.extend(page)
            if len(page) < 5000:
                break
            offset += len(page)
        inputs = self._patterns.list_inputs(profile_id, source.pattern_run_id)
        match_inputs = []
        for item in inputs:
            stored = self._matches.get_match(item.match_id)
            match_inputs.append(
                FindingMatchInput(
                    match_id=item.match_id,
                    team_id=item.team_id,
                    map_name=item.map_name,
                    input_status=item.input_status,
                    exclusion_reason=item.exclusion_reason,
                    demo_file_id=stored.demo_file_id if stored else None,
                    source_demo_sha256=stored.source_demo_sha256 if stored else None,
                    dataset_fingerprint=stored.dataset_fingerprint if stored else None,
                    feature_run_id=item.feature_run_id,
                    feature_fingerprint=item.feature_fingerprint,
                )
            )
        state = self._engine.compute(
            FindingEngineInput(
                profile_id=profile_id,
                pattern_run_id=source.pattern_run_id,
                pattern_fingerprint=source.pattern_fingerprint,
                pattern_schema_version=source.pattern_schema_version,
                pattern_rule_version=source.pattern_rule_version,
                workspace_fingerprint=source.workspace_fingerprint,
                corpus_below_minimum=source.summary.corpus_below_minimum,
                pattern_warnings=source.warnings,
                matches=tuple(match_inputs),
                patterns=tuple(patterns),
            ),
            config,
        )
        saved = self._analysis.save_analysis(state, replace=replace)
        return AnalysisComputeResult(
            analysis_run_id=saved.analysis_run_id,
            analysis_fingerprint=saved.analysis_fingerprint,
            analysis_schema_version=FINDING_SCHEMA_VERSION,
            analysis_rule_version=FINDING_RULE_VERSION,
            profile_id=profile_id,
            source_pattern_run_id=source.pattern_run_id,
            status=saved.status,
            summary=state.summary,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )


class AnalysisFindingQueryService:
    def __init__(self, patterns: PatternRepository, analysis: AnalysisRepository) -> None:
        self._patterns = patterns
        self._analysis = analysis

    def get_summary(
        self, profile_id: UUID, *, analysis_run_id: UUID | None = None
    ) -> AnalysisRunSummary:
        if analysis_run_id is not None:
            result = self._analysis.get_summary_for_run(profile_id, analysis_run_id)
        else:
            pattern = self._patterns.get_summary(profile_id)
            result = (
                self._analysis.get_summary(profile_id, source_pattern_run_id=pattern.pattern_run_id)
                if pattern is not None
                else None
            )
        if result is None:
            raise AnalysisFindingNotFoundError(
                f"Compatible Stage 8.6 analysis run not found for profile {profile_id}."
            )
        return result

    def list_runs(self, profile_id: UUID) -> tuple[AnalysisRunRecord, ...]:
        pattern = self._patterns.get_summary(profile_id)
        return self._analysis.list_runs(
            profile_id,
            current_pattern_run_id=pattern.pattern_run_id if pattern else None,
        )

    def list_findings(
        self,
        profile_id: UUID,
        *,
        analysis_run_id: UUID | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        category: FindingCategory | None = None,
        pattern_type: PatternType | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[AnalysisFinding, ...]:
        summary = self.get_summary(profile_id, analysis_run_id=analysis_run_id)
        return self._analysis.list_findings(
            profile_id,
            analysis_run_id=summary.analysis_run_id,
            map_name=map_name,
            side=side,
            category=category,
            pattern_type=pattern_type,
            limit=limit,
            offset=offset,
        )

    def get_finding(
        self, profile_id: UUID, finding_id: UUID, *, analysis_run_id: UUID | None = None
    ) -> AnalysisFinding:
        summary = self.get_summary(profile_id, analysis_run_id=analysis_run_id)
        result = self._analysis.get_finding(profile_id, summary.analysis_run_id, finding_id)
        if result is None:
            raise AnalysisFindingNotFoundError(f"Finding not found: {finding_id}")
        return result

    def delete(self, profile_id: UUID) -> int:
        return self._analysis.delete_analysis(profile_id)


__all__ = ["AnalysisFindingQueryService", "ComputeAnalysisFindingsService"]
