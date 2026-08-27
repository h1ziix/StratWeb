"""Deterministic builder and JSON renderer for Stage 8.9 exports."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stratweb.application.opponent_models import OpponentWorkspace
from stratweb.application.scouting_reports import ScoutingReportSource
from stratweb.counter_strategy.models import CounterStrategyRecommendation
from stratweb.findings.models import AnalysisFinding
from stratweb.readiness.models import corpus_reliability
from stratweb.reporting.models import (
    REPORT_EXPORT_RULE_VERSION,
    REPORT_EXPORT_SCHEMA_VERSION,
    ReportExportCorpusMatch,
    ReportExportScope,
    ReportExportVersions,
    ScoutingReportExport,
)


class ScoutingReportExporter:
    """Build a complete export without applying presentation filters or recomputation."""

    def build(
        self,
        source: ScoutingReportSource,
        workspace: OpponentWorkspace,
    ) -> ScoutingReportExport:
        selected = {item.selection.match_id: item for item in workspace.selected_matches}
        findings = tuple(
            sorted((_sorted_finding(item) for item in source.findings), key=_finding_key)
        )
        recommendations = tuple(
            sorted(
                (_sorted_recommendation(item) for item in source.recommendations),
                key=lambda item: str(item.recommendation_id),
            )
        )
        skipped = tuple(sorted(source.skipped_findings, key=lambda item: str(item.finding_id)))
        reliability_tier, reliability_label, reliability_message = corpus_reliability(
            source.validation.coverage.included_matches
        )
        corpus = tuple(
            ReportExportCorpusMatch(
                match_id=item.match_id,
                demo_file_id=item.demo_file_id,
                original_file_name=(
                    selected[item.match_id].source_name if item.match_id in selected else None
                ),
                demo_sha256=item.source_demo_sha256,
                map_name=item.map_name,
                opponent_team_name=(
                    selected[item.match_id].team_name if item.match_id in selected else None
                ),
                round_count=(
                    selected[item.match_id].round_count if item.match_id in selected else None
                ),
                input_status=item.input_status.value,
                exclusion_reason=item.exclusion_reason,
            )
            for item in sorted(source.analysis.input_matches, key=lambda value: str(value.match_id))
        )
        validation = source.validation.model_copy(
            update={
                "checks": tuple(sorted(source.validation.checks, key=lambda item: item.code.value)),
                "rule_coverage": tuple(
                    sorted(source.validation.rule_coverage, key=lambda item: item.rule_id)
                ),
            }
        )
        readiness = source.readiness.model_copy(
            update={
                "records": tuple(
                    sorted(source.readiness.records, key=lambda item: str(item.finding_id))
                )
            }
        )
        sample_limitations = tuple(
            dict.fromkeys(
                item.message
                for item in validation.checks
                if item.status.value in {"warning", "blocked", "failed"}
            )
        )
        warnings = tuple(
            dict.fromkeys(
                (
                    *source.analysis.warnings,
                    *source.readiness.warnings,
                    *source.strategy.warnings,
                    *source.validation.warnings,
                )
            )
        )
        values: dict[str, Any] = {
            "export_schema_version": REPORT_EXPORT_SCHEMA_VERSION,
            "export_rule_version": REPORT_EXPORT_RULE_VERSION,
            "profile_id": source.strategy.profile_id,
            "display_name": workspace.profile.display_name,
            "analysis_created_at": source.analysis_created_at,
            "strategy_created_at": source.strategy_created_at,
            "analysis_run_id": source.analysis.analysis_run_id,
            "analysis_fingerprint": source.analysis.analysis_fingerprint,
            "strategy_run_id": source.strategy.strategy_run_id,
            "strategy_fingerprint": source.strategy.strategy_fingerprint,
            "acceptance_status": validation.status.value,
            "versions": ReportExportVersions(
                opponent_schema_version=workspace.opponent_schema_version,
                opponent_identity_rule_version=workspace.identity_rule_version,
                opponent_overlap_rule_version=workspace.overlap_rule_version,
                analysis_schema_version=source.analysis.analysis_schema_version,
                analysis_rule_version=source.analysis.analysis_rule_version,
                source_pattern_schema_version=source.analysis.source_pattern_schema_version,
                source_pattern_rule_version=source.analysis.source_pattern_rule_version,
                readiness_schema_version=source.readiness.readiness_schema_version,
                readiness_rule_version=source.readiness.readiness_rule_version,
                strategy_schema_version=source.strategy.strategy_schema_version,
                strategy_rule_version=source.strategy.strategy_rule_version,
                validation_schema_version=validation.validation_schema_version,
                validation_rule_version=validation.validation_rule_version,
            ),
            "scope": ReportExportScope(
                selected_matches=validation.coverage.selected_matches,
                included_matches=validation.coverage.included_matches,
                excluded_matches=validation.coverage.excluded_matches,
                required_matches=validation.config.minimum_corpus_matches,
                corpus_reliability_tier=reliability_tier.value,
                corpus_reliability_label=reliability_label,
                corpus_reliability_message=reliability_message,
                maps=tuple(sorted(validation.coverage.maps)),
                sides=tuple(sorted(validation.coverage.sides)),
                buy_types=tuple(sorted(validation.coverage.buy_types)),
                source_findings=validation.coverage.source_findings,
                ready_findings=validation.coverage.ready_findings,
                recommendations=validation.coverage.recommendations,
                evidence_references=sum(len(item.evidence_references) for item in findings),
            ),
            "corpus": corpus,
            "validation": validation,
            "readiness": readiness,
            "findings": findings,
            "recommendations": recommendations,
            "skipped_findings": skipped,
            "sample_limitations": sample_limitations,
            "warnings": warnings,
        }
        draft = ScoutingReportExport(export_fingerprint="0" * 64, **values)
        fingerprint = hashlib.sha256(
            _canonical_json(draft.model_dump(mode="json", exclude={"export_fingerprint"}))
        ).hexdigest()
        return draft.model_copy(update={"export_fingerprint": fingerprint})

    @staticmethod
    def render_json(report: ScoutingReportExport) -> bytes:
        payload = report.model_dump(mode="json")
        return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )


def _canonical_json(values: dict[str, Any]) -> bytes:
    return json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _finding_key(item: AnalysisFinding) -> tuple[str, str, str, str, str]:
    return (
        item.scope.map_name,
        item.scope.side.value,
        item.scope.buy_type.value if item.scope.buy_type else "",
        item.pattern_type.value,
        str(item.finding_id),
    )


def _sorted_finding(item: AnalysisFinding) -> AnalysisFinding:
    return item.model_copy(
        update={
            "evidence_references": tuple(
                sorted(
                    item.evidence_references,
                    key=lambda value: (
                        str(value.match_id),
                        value.round_number,
                        value.tick if value.tick is not None else -1,
                        str(value.evidence_id),
                    ),
                )
            )
        }
    )


def _sorted_recommendation(
    item: CounterStrategyRecommendation,
) -> CounterStrategyRecommendation:
    return item.model_copy(
        update={
            "evidence_references": tuple(
                sorted(
                    item.evidence_references,
                    key=lambda value: (
                        str(value.match_id),
                        value.round_number,
                        value.tick if value.tick is not None else -1,
                        str(value.evidence_id),
                    ),
                )
            )
        }
    )


__all__ = ["ScoutingReportExporter"]
