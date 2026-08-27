"""Pure deterministic Stage 8.6.1 readiness assessment."""

from __future__ import annotations

import hashlib
from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.findings.models import AnalysisFinding
from stratweb.patterns.models import PatternAvailability
from stratweb.readiness.models import (
    READINESS_RULE_VERSION,
    READINESS_SCHEMA_VERSION,
    FindingReadinessAudit,
    FindingReadinessConfig,
    FindingReadinessInput,
    FindingReadinessRecord,
    FindingReadinessStatus,
    FindingReadinessSummary,
    ReadinessReason,
    corpus_reliability,
)


class FindingReadinessEngine:
    def audit(
        self,
        data: FindingReadinessInput,
        config: FindingReadinessConfig | None = None,
    ) -> FindingReadinessAudit:
        selected = config or FindingReadinessConfig()
        analysis = data.analysis
        findings = tuple(sorted(data.findings, key=lambda item: str(item.finding_id)))
        if any(
            item.profile_id != analysis.profile_id
            or item.analysis_run_id != analysis.analysis_run_id
            for item in findings
        ):
            raise ValueError("readiness input mixes findings from different analysis runs")

        corpus_limited = analysis.summary.included_matches < selected.minimum_corpus_matches
        records = tuple(_assess(item, selected, corpus_limited=corpus_limited) for item in findings)
        reason_counts: Counter[ReadinessReason] = Counter()
        for item in records:
            reason_counts.update(item.blocking_reasons)
            reason_counts.update(item.limitations)
        ready = sum(item.status is FindingReadinessStatus.READY for item in records)
        limited = sum(item.status is FindingReadinessStatus.LIMITED for item in records)
        blocked = sum(item.status is FindingReadinessStatus.BLOCKED for item in records)
        reliability_tier, reliability_label, reliability_message = corpus_reliability(
            analysis.summary.included_matches
        )
        summary = FindingReadinessSummary(
            selected_matches=analysis.summary.selected_matches,
            included_matches=analysis.summary.included_matches,
            required_corpus_matches=selected.minimum_corpus_matches,
            corpus_reliability_tier=reliability_tier,
            corpus_reliability_label=reliability_label,
            corpus_reliability_message=reliability_message,
            findings=len(records),
            ready_findings=ready,
            limited_findings=limited,
            blocked_findings=blocked,
            eligible_for_stage_8_7=ready + limited,
            stage_8_7_ready=bool(records) and ready + limited > 0,
            reason_counts=dict(sorted(reason_counts.items(), key=lambda item: item[0].value)),
        )
        config_payload = selected.model_dump(mode="json")
        config_hash = _sha256(config_payload)
        payload = {
            "schema": READINESS_SCHEMA_VERSION,
            "rule": READINESS_RULE_VERSION,
            "analysis_fingerprint": analysis.analysis_fingerprint,
            "config": config_payload,
            "records": [item.model_dump(mode="json") for item in records],
        }
        fingerprint = _sha256(payload)
        warnings = []
        if corpus_limited:
            warnings.append(
                "corpus_below_high_reliability_threshold:"
                f"{analysis.summary.included_matches}/{selected.minimum_corpus_matches}"
            )
        if not records:
            warnings.append("no_findings_available_for_readiness_audit")
        if blocked:
            warnings.append(f"stage_8_7_blocked_findings:{blocked}")
        if limited:
            warnings.append(f"stage_8_7_limited_findings:{limited}")
        return FindingReadinessAudit(
            audit_id=uuid5(NAMESPACE_URL, f"stratweb:finding-readiness:{fingerprint}"),
            audit_fingerprint=fingerprint,
            configuration_hash=config_hash,
            profile_id=analysis.profile_id,
            source_analysis_run_id=analysis.analysis_run_id,
            source_analysis_fingerprint=analysis.analysis_fingerprint,
            source_analysis_schema_version=analysis.analysis_schema_version,
            source_analysis_rule_version=analysis.analysis_rule_version,
            config=selected,
            summary=summary,
            records=records,
            warnings=tuple(warnings),
        )


def _assess(
    item: AnalysisFinding,
    config: FindingReadinessConfig,
    *,
    corpus_limited: bool,
) -> FindingReadinessRecord:
    blockers: set[ReadinessReason] = set()
    limitations: set[ReadinessReason] = set()
    if corpus_limited:
        limitations.add(ReadinessReason.CORPUS_BELOW_MINIMUM)
    if item.denominator_match_count < config.minimum_finding_matches:
        limitations.add(ReadinessReason.FINDING_MATCHES_BELOW_MINIMUM)
    if item.small_sample_warning:
        limitations.add(ReadinessReason.FINDING_SAMPLE_BELOW_MINIMUM)
    if item.source_availability is PatternAvailability.PARTIAL:
        target = blockers if config.block_partial_source else limitations
        target.add(ReadinessReason.SOURCE_PATTERN_PARTIAL)
    if item.scope.buy_type is None:
        target = blockers if config.require_known_buy_type else limitations
        target.add(ReadinessReason.BUY_TYPE_UNAVAILABLE)
    evidence_with_tick = sum(ref.tick is not None for ref in item.evidence_references)
    if evidence_with_tick != len(item.evidence_references):
        target = blockers if config.require_all_evidence_ticks else limitations
        target.add(ReadinessReason.EVIDENCE_TICK_PARTIAL)
    status = (
        FindingReadinessStatus.BLOCKED
        if blockers
        else FindingReadinessStatus.LIMITED
        if limitations
        else FindingReadinessStatus.READY
    )
    return FindingReadinessRecord(
        finding_id=item.finding_id,
        status=status,
        eligible_for_stage_8_7=status is not FindingReadinessStatus.BLOCKED,
        blocking_reasons=tuple(sorted(blockers, key=lambda reason: reason.value)),
        limitations=tuple(sorted(limitations, key=lambda reason: reason.value)),
        numerator=item.numerator,
        denominator=item.denominator,
        denominator_match_count=item.denominator_match_count,
        evidence_with_tick=evidence_with_tick,
        evidence_total=len(item.evidence_references),
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["FindingReadinessEngine"]
