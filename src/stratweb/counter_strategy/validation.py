"""Pure deterministic Stage 8.7.1 corpus and recommendation validation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from uuid import NAMESPACE_URL, UUID, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.patterns.models import PatternInputStatus
from stratweb.readiness.models import FindingReadinessStatus

from .models import StrategySkipReason
from .validation_models import (
    VALIDATION_RULE_VERSION,
    VALIDATION_SCHEMA_VERSION,
    CorpusCoverage,
    CounterStrategyValidationAudit,
    CounterStrategyValidationInput,
    RuleCoverage,
    StrategyAcceptanceStatus,
    StrategyValidationConfig,
    ValidationCheck,
    ValidationCheckCode,
    ValidationCheckStatus,
)

_CAUSALITY_PHRASES = (
    "always does",
    "will always",
    "guarantees",
    "is caused by",
    "proves that",
    "definitely will",
)


class CounterStrategyValidationEngine:
    def validate(
        self,
        data: CounterStrategyValidationInput,
        config: StrategyValidationConfig | None = None,
    ) -> CounterStrategyValidationAudit:
        selected = config or StrategyValidationConfig()
        strategy = data.strategy
        analysis = data.analysis
        findings = {item.finding_id: item for item in data.findings}
        readiness = {item.finding_id: item for item in data.readiness.records}
        recommendations = tuple(
            sorted(data.recommendations, key=lambda item: str(item.recommendation_id))
        )
        skipped = tuple(sorted(data.skipped_findings, key=lambda item: str(item.finding_id)))
        checks: list[ValidationCheck] = []

        source_ok = (
            strategy.profile_id == analysis.profile_id == data.readiness.profile_id
            and strategy.source_analysis_run_id == analysis.analysis_run_id
            and strategy.source_analysis_fingerprint == analysis.analysis_fingerprint
            and all(
                item.analysis_run_id == analysis.analysis_run_id
                and item.profile_id == analysis.profile_id
                and item.source_pattern_run_id == analysis.source_pattern_run_id
                for item in findings.values()
            )
            and all(
                item.strategy_run_id == strategy.strategy_run_id
                and item.profile_id == strategy.profile_id
                and item.source_analysis_run_id == analysis.analysis_run_id
                for item in recommendations
            )
        )
        checks.append(
            _check(
                ValidationCheckCode.SOURCE_RUN_INTEGRITY,
                source_ok,
                "Strategy, readiness and findings pin the same immutable Analysis run.",
                "Strategy input provenance does not resolve to one Analysis run.",
                failure=True,
            )
        )
        included_inputs = tuple(
            item
            for item in analysis.input_matches
            if item.input_status is PatternInputStatus.INCLUDED
        )
        excluded_inputs = tuple(
            item
            for item in analysis.input_matches
            if item.input_status is PatternInputStatus.EXCLUDED
        )
        counts_ok = (
            analysis.summary.selected_matches == len(analysis.input_matches)
            and analysis.summary.included_matches == len(included_inputs)
            and analysis.summary.excluded_matches == len(excluded_inputs)
        )
        checks.append(
            _check(
                ValidationCheckCode.ANALYSIS_INPUT_COUNTS,
                counts_ok,
                "Analysis summary counts match its immutable input manifest.",
                "Analysis summary counts disagree with its immutable input manifest.",
                failure=True,
                observed=(
                    f"{analysis.summary.selected_matches}/"
                    f"{analysis.summary.included_matches}/"
                    f"{analysis.summary.excluded_matches}"
                ),
                required=(
                    f"{len(analysis.input_matches)}/{len(included_inputs)}/{len(excluded_inputs)}"
                ),
            )
        )
        readiness_ok = (
            strategy.readiness_audit_id == data.readiness.audit_id
            and strategy.readiness_fingerprint == data.readiness.audit_fingerprint
            and strategy.readiness_config == data.readiness.config
            and len(data.readiness.records) == len(readiness)
            and set(readiness) == set(findings)
        )
        checks.append(
            _check(
                ValidationCheckCode.READINESS_REPRODUCIBILITY,
                readiness_ok,
                "Pinned readiness audit reproduced exactly.",
                "Pinned readiness audit or configuration could not be reproduced.",
                failure=True,
            )
        )

        classified = [item.source_finding_id for item in recommendations] + [
            item.finding_id for item in skipped
        ]
        skip_counts = Counter(item.reason for item in skipped)
        classification_ok = (
            len(data.findings) == len(findings)
            and len(classified) == len(set(classified))
            and set(classified) == set(findings)
            and strategy.summary.source_findings == len(findings)
            and strategy.summary.recommendations == len(recommendations)
            and strategy.summary.skipped_not_ready == skip_counts[StrategySkipReason.NOT_READY]
            and strategy.summary.skipped_no_rule
            == skip_counts[StrategySkipReason.NO_SUPPORTED_RULE]
            and strategy.summary.skipped_threshold
            == skip_counts[StrategySkipReason.THRESHOLD_NOT_MET]
            and strategy.summary.evidence_references
            == sum(len(item.evidence_references) for item in recommendations)
        )
        checks.append(
            _check(
                ValidationCheckCode.COMPLETE_FINDING_CLASSIFICATION,
                classification_ok,
                "Every source finding is classified exactly once.",
                "Source findings are missing or multiply classified.",
                failure=True,
                observed=len(classified),
                required=len(findings),
            )
        )

        included_matches = len(included_inputs)
        corpus_ok = included_matches >= selected.minimum_corpus_matches
        checks.append(
            _check(
                ValidationCheckCode.CORPUS_SIZE,
                corpus_ok,
                "Confirmed opponent corpus meets the configured minimum.",
                "Confirmed opponent corpus is below the configured minimum.",
                blocked=True,
                observed=included_matches,
                required=selected.minimum_corpus_matches,
            )
        )

        sides = tuple(sorted({item.scope.side.value for item in findings.values()}))
        sides_ok = not selected.require_both_sides or set(sides) >= {Side.T.value, Side.CT.value}
        checks.append(
            _check(
                ValidationCheckCode.BOTH_SIDES_COVERED,
                sides_ok,
                "Both T and CT findings are represented.",
                "T/CT finding coverage is incomplete.",
                blocked=True,
                observed=",".join(sides) or "none",
                required="T,CT" if selected.require_both_sides else "not_required",
            )
        )

        unknown_buy = tuple(
            sorted(
                (item.finding_id for item in findings.values() if item.scope.buy_type is None),
                key=str,
            )
        )
        checks.append(
            ValidationCheck(
                code=ValidationCheckCode.BUY_CONTEXT_COVERAGE,
                status=(
                    ValidationCheckStatus.WARNING
                    if unknown_buy and selected.warn_unknown_buy_context
                    else ValidationCheckStatus.PASSED
                ),
                message=(
                    f"{len(unknown_buy)} source findings have unknown buy context."
                    if unknown_buy
                    else "All source findings preserve a known buy context."
                ),
                observed=len(unknown_buy),
                required=0,
                affected_ids=unknown_buy,
            )
        )

        recommendation_ok = (
            bool(recommendations) or not selected.require_at_least_one_recommendation
        )
        checks.append(
            _check(
                ValidationCheckCode.PUBLISHED_RECOMMENDATIONS,
                recommendation_ok,
                "At least one readiness-approved recommendation was published.",
                "No recommendation is available for real-corpus acceptance.",
                blocked=True,
                observed=len(recommendations),
                required=1 if selected.require_at_least_one_recommendation else 0,
            )
        )

        gate_violations = tuple(
            item.recommendation_id
            for item in recommendations
            if readiness.get(item.source_finding_id) is None
            or readiness[item.source_finding_id].status is not FindingReadinessStatus.READY
        )
        checks.append(
            _check(
                ValidationCheckCode.READY_GATE_ENFORCED,
                not gate_violations,
                "Every published recommendation passed the readiness gate.",
                "A recommendation bypassed the readiness gate.",
                failure=True,
                affected_ids=gate_violations,
            )
        )

        statistics_violations: list[UUID] = []
        evidence_violations: list[UUID] = []
        for item in recommendations:
            source = findings.get(item.source_finding_id)
            if source is None:
                statistics_violations.append(item.recommendation_id)
                evidence_violations.append(item.recommendation_id)
                continue
            if (
                item.numerator,
                item.denominator,
                item.frequency,
                item.sample_size,
                item.numerator_match_count,
                item.denominator_match_count,
                item.confidence,
                item.scope,
                item.pattern_type,
                item.pattern_value,
                item.observation,
            ) != (
                source.numerator,
                source.denominator,
                source.frequency,
                source.sample_size,
                source.numerator_match_count,
                source.denominator_match_count,
                source.confidence,
                source.scope,
                source.pattern_type,
                source.pattern_value,
                source.observation,
            ):
                statistics_violations.append(item.recommendation_id)
            if item.evidence_references != source.evidence_references:
                evidence_violations.append(item.recommendation_id)
        checks.extend(
            (
                _check(
                    ValidationCheckCode.STATISTICS_PRESERVED,
                    not statistics_violations,
                    "Published statistics and observation equal their source findings.",
                    "Published statistics or observation differ from source findings.",
                    failure=True,
                    affected_ids=tuple(statistics_violations),
                ),
                _check(
                    ValidationCheckCode.EVIDENCE_PRESERVED,
                    not evidence_violations,
                    "Complete ordered evidence is preserved for every recommendation.",
                    "Recommendation evidence differs from its source finding.",
                    failure=True,
                    affected_ids=tuple(evidence_violations),
                ),
            )
        )

        included_match_ids = {item.match_id for item in included_inputs}
        outside_corpus = tuple(
            sorted(
                {
                    item.recommendation_id
                    for item in recommendations
                    if any(
                        ref.match_id not in included_match_ids for ref in item.evidence_references
                    )
                },
                key=str,
            )
        )
        checks.append(
            _check(
                ValidationCheckCode.EVIDENCE_WITHIN_CORPUS,
                not outside_corpus,
                "Every evidence reference belongs to an included corpus match.",
                "Recommendation evidence points outside the included corpus.",
                failure=True,
                affected_ids=outside_corpus,
            )
        )

        signatures: defaultdict[tuple[str, str, str, str, str], list[UUID]] = defaultdict(list)
        for item in recommendations:
            signature = (
                item.rule_id.value,
                item.scope.map_name,
                item.scope.side.value,
                item.scope.buy_type.value if item.scope.buy_type else "unknown",
                canonical_json(item.pattern_value.model_dump(mode="json")),
            )
            signatures[signature].append(item.recommendation_id)
        duplicates = tuple(
            sorted(
                (item for ids in signatures.values() if len(ids) > 1 for item in ids),
                key=str,
            )
        )
        checks.append(
            _check(
                ValidationCheckCode.DUPLICATE_RECOMMENDATIONS,
                not duplicates,
                "No duplicate recommendation signatures were published.",
                "Duplicate recommendation signatures were published.",
                failure=True,
                affected_ids=duplicates,
            )
        )

        causal = tuple(
            item.recommendation_id
            for item in recommendations
            if any(
                phrase
                in " ".join(
                    (
                        item.tactical_interpretation.text or "",
                        item.recommendation.text or "",
                        item.avoid.text or "",
                    )
                ).casefold()
                for phrase in _CAUSALITY_PHRASES
            )
        )
        checks.append(
            _check(
                ValidationCheckCode.CAUSALITY_GUARD,
                not causal,
                "Published text contains no prohibited deterministic-causality phrases.",
                "Published text contains a prohibited deterministic-causality phrase.",
                failure=True,
                affected_ids=causal,
            )
        )

        evidence = tuple(ref for item in recommendations for ref in item.evidence_references)
        buy_types = tuple(
            sorted(
                {
                    item.scope.buy_type.value
                    for item in findings.values()
                    if item.scope.buy_type is not None
                }
            )
        )
        coverage = CorpusCoverage(
            selected_matches=analysis.summary.selected_matches,
            included_matches=included_matches,
            excluded_matches=analysis.summary.excluded_matches,
            maps=tuple(sorted({item.scope.map_name for item in findings.values()})),
            sides=sides,
            buy_types=buy_types,
            source_findings=len(findings),
            ready_findings=sum(
                item.status is FindingReadinessStatus.READY for item in readiness.values()
            ),
            recommendations=len(recommendations),
            skipped_findings=len(skipped),
            evidence_references=len(evidence),
            evidence_matches=len({item.match_id for item in evidence}),
            evidence_rounds=len({(item.match_id, item.round_id) for item in evidence}),
        )
        by_rule: Counter[str] = Counter(item.rule_id.value for item in recommendations)
        rule_coverage = tuple(
            RuleCoverage(
                rule_id=rule_id,
                recommendations=count,
                evidence_references=sum(
                    len(item.evidence_references)
                    for item in recommendations
                    if item.rule_id.value == rule_id
                ),
                evidence_matches=len(
                    {
                        ref.match_id
                        for item in recommendations
                        if item.rule_id.value == rule_id
                        for ref in item.evidence_references
                    }
                ),
            )
            for rule_id, count in sorted(by_rule.items())
        )
        failures = tuple(
            item.code for item in checks if item.status is ValidationCheckStatus.FAILED
        )
        blockers = tuple(
            item.code for item in checks if item.status is ValidationCheckStatus.BLOCKED
        )
        status = (
            StrategyAcceptanceStatus.FAILED
            if failures
            else StrategyAcceptanceStatus.BLOCKED
            if blockers
            else StrategyAcceptanceStatus.PASSED
        )
        config_hash = _sha256(selected.model_dump(mode="json"))
        fingerprint = _sha256(
            {
                "schema": VALIDATION_SCHEMA_VERSION,
                "rule": VALIDATION_RULE_VERSION,
                "strategy_fingerprint": strategy.strategy_fingerprint,
                "readiness_fingerprint": data.readiness.audit_fingerprint,
                "config": selected.model_dump(mode="json"),
                "coverage": coverage.model_dump(mode="json"),
                "checks": [item.model_dump(mode="json") for item in checks],
            }
        )
        warnings = tuple(
            item.message
            for item in checks
            if item.status in {ValidationCheckStatus.WARNING, ValidationCheckStatus.BLOCKED}
        )
        return CounterStrategyValidationAudit(
            validation_id=uuid5(
                NAMESPACE_URL, f"stratweb:counter-strategy-validation:{fingerprint}"
            ),
            validation_fingerprint=fingerprint,
            configuration_hash=config_hash,
            profile_id=strategy.profile_id,
            strategy_run_id=strategy.strategy_run_id,
            strategy_fingerprint=strategy.strategy_fingerprint,
            source_analysis_run_id=analysis.analysis_run_id,
            source_analysis_fingerprint=analysis.analysis_fingerprint,
            readiness_audit_id=data.readiness.audit_id,
            readiness_fingerprint=data.readiness.audit_fingerprint,
            config=selected,
            status=status,
            coverage=coverage,
            rule_coverage=rule_coverage,
            checks=tuple(checks),
            blockers=blockers,
            failures=failures,
            warnings=warnings,
        )


def _check(
    code: ValidationCheckCode,
    condition: bool,
    success: str,
    failure_message: str,
    *,
    blocked: bool = False,
    failure: bool = False,
    observed: int | float | str | bool | None = None,
    required: int | float | str | bool | None = None,
    affected_ids: tuple[UUID, ...] = (),
) -> ValidationCheck:
    failed_status = (
        ValidationCheckStatus.FAILED
        if failure
        else ValidationCheckStatus.BLOCKED
        if blocked
        else ValidationCheckStatus.WARNING
    )
    return ValidationCheck(
        code=code,
        status=ValidationCheckStatus.PASSED if condition else failed_status,
        message=success if condition else failure_message,
        observed=observed,
        required=required,
        affected_ids=affected_ids,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["CounterStrategyValidationEngine"]
