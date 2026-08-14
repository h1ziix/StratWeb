"""Pure conversion of Stage 8.5 aggregates into evidence-preserving findings."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.findings.models import (
    FINDING_RULE_VERSION,
    FINDING_SCHEMA_VERSION,
    AnalysisFinding,
    AnalysisRun,
    EvidenceReference,
    FindingCategory,
    FindingConfig,
    FindingEngineInput,
    FindingSummary,
    FindingText,
    FindingTextAvailability,
)
from stratweb.patterns.models import CrossMatchPattern, PatternAvailability, PatternType

_CATEGORY = {
    PatternType.RECURRING_OPENING_PLAYER: FindingCategory.PLAYER_TENDENCY,
    PatternType.RECURRING_OPENING_DEATH: FindingCategory.PLAYER_TENDENCY,
    PatternType.OPENING_KILL_CONVERSION: FindingCategory.OUTCOME_ASSOCIATION,
    PatternType.RECOVERY_AFTER_OPENING_DEATH: FindingCategory.OUTCOME_ASSOCIATION,
    PatternType.LOST_MAN_ADVANTAGE: FindingCategory.ROUND_EVENT_FREQUENCY,
    PatternType.UNTRADED_DEATH: FindingCategory.ROUND_EVENT_FREQUENCY,
}


class AnalysisFindingEngine:
    def compute(self, data: FindingEngineInput, config: FindingConfig | None = None) -> AnalysisRun:
        selected = config or FindingConfig()
        if any(
            item.profile_id != data.profile_id or item.pattern_run_id != data.pattern_run_id
            for item in data.patterns
        ):
            raise ValueError("finding input contains a pattern outside the pinned run")
        source = tuple(
            item
            for item in sorted(data.patterns, key=lambda value: str(value.pattern_id))
            if (
                selected.include_partial_patterns
                or item.availability is PatternAvailability.AVAILABLE
            )
            and (selected.include_zero_frequency or item.numerator > 0)
        )
        config_hash = _sha256(selected.model_dump(mode="json"))
        draft_payload = [_finding_payload(item) for item in source]
        fingerprint = _sha256(
            {
                "schema": FINDING_SCHEMA_VERSION,
                "rule": FINDING_RULE_VERSION,
                "profile_id": str(data.profile_id),
                "pattern_run_id": str(data.pattern_run_id),
                "pattern_fingerprint": data.pattern_fingerprint,
                "config": selected.model_dump(mode="json"),
                "findings": draft_payload,
            }
        )
        run_id = uuid5(NAMESPACE_URL, f"stratweb:analysis-run:{fingerprint}")
        matches = {item.match_id: item for item in data.matches}
        findings = tuple(_materialize(run_id, data, item, matches) for item in source)
        included = sum(item.input_status.value == "included" for item in data.matches)
        summary = FindingSummary(
            selected_matches=len(data.matches),
            included_matches=included,
            excluded_matches=len(data.matches) - included,
            source_patterns=len(data.patterns),
            findings=len(findings),
            partial_findings=sum(
                item.source_availability is PatternAvailability.PARTIAL for item in findings
            ),
            small_sample_findings=sum(item.small_sample_warning for item in findings),
            evidence_references=sum(len(item.evidence_references) for item in findings),
            maps=tuple(sorted({item.scope.map_name for item in findings})),
        )
        warnings = list(data.pattern_warnings)
        if not selected.include_zero_frequency:
            skipped = sum(item.numerator == 0 for item in data.patterns)
            if skipped:
                warnings.append(f"zero_frequency_patterns_excluded:{skipped}")
        return AnalysisRun(
            analysis_run_id=run_id,
            analysis_fingerprint=fingerprint,
            configuration_hash=config_hash,
            profile_id=data.profile_id,
            workspace_fingerprint=data.workspace_fingerprint,
            source_pattern_run_id=data.pattern_run_id,
            source_pattern_fingerprint=data.pattern_fingerprint,
            source_pattern_schema_version=data.pattern_schema_version,
            source_pattern_rule_version=data.pattern_rule_version,
            config=selected,
            matches=data.matches,
            findings=findings,
            summary=summary,
            warnings=tuple(warnings),
        )


def _materialize(
    run_id: UUID,
    data: FindingEngineInput,
    pattern: CrossMatchPattern,
    matches: dict[UUID, Any],
) -> AnalysisFinding:
    finding_id = uuid5(run_id, f"finding:{pattern.pattern_id}")
    label = _value_label(pattern)
    scope = f"{pattern.scope.map_name}, {pattern.scope.side.value}, " + (
        pattern.scope.buy_type.value if pattern.scope.buy_type else "buy type unavailable"
    )
    observation = (
        f"{label}: observed in {pattern.numerator} of {pattern.denominator} eligible "
        f"rounds ({pattern.frequency * 100:.1f}%) within {scope}."
    )
    evidence = tuple(
        _evidence(run_id, finding_id, pattern, item, matches.get(item.match_id))
        for item in pattern.included_rounds
    )
    limitations = set(pattern.limitations)
    limitations.add("observation_does_not_prove_intent_or_causality")
    if data.corpus_below_minimum:
        limitations.add("opponent_corpus_below_configured_minimum")
    unavailable = FindingText(
        availability=FindingTextAvailability.UNAVAILABLE,
        reason="stage_8_7_counter_strategy_rules_not_computed",
    )
    return AnalysisFinding(
        finding_id=finding_id,
        analysis_run_id=run_id,
        profile_id=data.profile_id,
        source_pattern_run_id=data.pattern_run_id,
        source_pattern_id=pattern.pattern_id,
        rule_id=f"pattern_to_finding:{pattern.pattern_type.value}",
        category=_CATEGORY.get(pattern.pattern_type, FindingCategory.TEAM_TENDENCY),
        title=f"{_title(pattern.pattern_type)} — {label}",
        scope=pattern.scope,
        pattern_type=pattern.pattern_type,
        pattern_value=pattern.value,
        source_availability=pattern.availability,
        observation=FindingText(
            availability=FindingTextAvailability.AVAILABLE,
            text=observation,
        ),
        tactical_implication=unavailable,
        recommended_response=unavailable,
        avoid=unavailable,
        numerator=pattern.numerator,
        denominator=pattern.denominator,
        frequency=pattern.frequency,
        sample_size=pattern.sample_size,
        numerator_match_count=pattern.numerator_match_count,
        denominator_match_count=pattern.denominator_match_count,
        minimum_sample_size=pattern.minimum_sample_size,
        small_sample_warning=pattern.small_sample_warning,
        confidence=pattern.confidence,
        evidence_references=evidence,
        limitations=tuple(sorted(limitations)),
        warnings=pattern.warnings,
    )


def _evidence(
    run_id: UUID,
    finding_id: UUID,
    pattern: CrossMatchPattern,
    source: Any,
    match: Any,
) -> EvidenceReference:
    if match is None or match.demo_file_id is None or match.source_demo_sha256 is None:
        raise ValueError("finding evidence requires persisted source-demo provenance")
    key = canonical_json(source.model_dump(mode="json"))
    evidence_id = uuid5(finding_id, key)
    tick_query = f"?tick={source.tick}&mode=exact" if source.tick is not None else ""
    return EvidenceReference(
        evidence_id=evidence_id,
        analysis_run_id=run_id,
        finding_id=finding_id,
        source_pattern_id=pattern.pattern_id,
        demo_file_id=match.demo_file_id if match else None,
        demo_sha256=match.source_demo_sha256 if match else None,
        match_id=source.match_id,
        round_id=source.round_id,
        round_number=source.round_number,
        tick=source.tick,
        contributed_to_numerator=source.contributed_to_numerator,
        feature_ids=source.feature_ids,
        event_ids=source.event_ids,
        snapshot_ids=source.snapshot_ids,
        economy_snapshot_ids=source.economy_snapshot_ids,
        description=(
            "Round contributed to numerator"
            if source.contributed_to_numerator
            else "Round contributed to denominator only"
        ),
        map_href=(f"/ui/spatial/{source.match_id}/rounds/{source.round_number}{tick_query}"),
        timeline_href=(
            f"/ui/temporal/{source.match_id}/rounds/{source.round_number}/snapshots/{source.tick}"
            if source.tick is not None
            else f"/ui/temporal/{source.match_id}/rounds/{source.round_number}"
        ),
        limitations=source.limitations,
    )


def _value_label(pattern: CrossMatchPattern) -> str:
    value = pattern.value
    if hasattr(value, "label"):
        return str(value.label)
    if value.kind == "player":
        return value.current_name
    return pattern.pattern_type.value.replace("_", " ")


def _title(pattern_type: PatternType) -> str:
    return pattern_type.value.replace("_", " ").title()


def _finding_payload(pattern: CrossMatchPattern) -> dict[str, Any]:
    return pattern.model_dump(mode="json")


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["AnalysisFindingEngine"]
