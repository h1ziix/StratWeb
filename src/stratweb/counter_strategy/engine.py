"""Pure deterministic rules over readiness-approved Stage 8.6 findings."""
# ruff: noqa: E501

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.findings.models import AnalysisFinding, FindingText, FindingTextAvailability
from stratweb.patterns.models import PatternType, PlayerPatternValue
from stratweb.readiness.models import FindingReadinessRecord, FindingReadinessStatus

from .models import (
    STRATEGY_RULE_VERSION,
    STRATEGY_SCHEMA_VERSION,
    CounterStrategyCategory,
    CounterStrategyConfig,
    CounterStrategyInput,
    CounterStrategyRecommendation,
    CounterStrategyRuleId,
    CounterStrategyRun,
    CounterStrategySummary,
    SkippedStrategyFinding,
    StrategySkipReason,
)


@dataclass(frozen=True, slots=True)
class _RuleText:
    rule_id: CounterStrategyRuleId
    category: CounterStrategyCategory
    title: str
    implication: str
    response: str
    avoid: str


class CounterStrategyEngine:
    def compute(
        self,
        data: CounterStrategyInput,
        config: CounterStrategyConfig | None = None,
    ) -> CounterStrategyRun:
        selected = config or CounterStrategyConfig()
        findings = tuple(
            sorted(
                (AnalysisFinding.model_validate(item) for item in data.findings),
                key=lambda item: str(item.finding_id),
            )
        )
        audit = data.readiness
        if audit.profile_id != data.profile_id:
            raise ValueError("readiness audit belongs to another opponent profile")
        if audit.source_analysis_fingerprint != data.analysis_fingerprint:
            raise ValueError("readiness audit does not pin the supplied Analysis run")
        if any(
            item.profile_id != data.profile_id
            or item.analysis_run_id != audit.source_analysis_run_id
            for item in findings
        ):
            raise ValueError("counter-strategy input mixes Analysis runs")
        readiness = {item.finding_id: item for item in audit.records}
        if set(readiness) != {item.finding_id for item in findings}:
            raise ValueError("readiness audit must cover every source finding exactly once")

        config_hash = _sha256(selected.model_dump(mode="json"))
        drafts: list[tuple[AnalysisFinding, _RuleText]] = []
        skipped: list[SkippedStrategyFinding] = []
        for finding in findings:
            gate = readiness[finding.finding_id]
            if gate.status is not FindingReadinessStatus.READY:
                skipped.append(_skip(finding, gate, StrategySkipReason.NOT_READY))
                continue
            rule, supported = _match_rule(finding, selected)
            if rule is None:
                skipped.append(
                    _skip(
                        finding,
                        gate,
                        StrategySkipReason.THRESHOLD_NOT_MET
                        if supported
                        else StrategySkipReason.NO_SUPPORTED_RULE,
                    )
                )
                continue
            drafts.append((finding, rule))

        fingerprint = _sha256(
            {
                "schema": STRATEGY_SCHEMA_VERSION,
                "rule": STRATEGY_RULE_VERSION,
                "profile_id": str(data.profile_id),
                "analysis_fingerprint": data.analysis_fingerprint,
                "readiness_fingerprint": audit.audit_fingerprint,
                "config": selected.model_dump(mode="json"),
                "drafts": [
                    {"finding_id": str(item.finding_id), "rule_id": rule.rule_id.value}
                    for item, rule in drafts
                ],
                "skipped": [item.model_dump(mode="json") for item in skipped],
            }
        )
        run_id = uuid5(NAMESPACE_URL, f"stratweb:counter-strategy:{fingerprint}")
        recommendations = tuple(
            _materialize(run_id, data.profile_id, finding, rule) for finding, rule in drafts
        )
        summary = CounterStrategySummary(
            source_findings=len(findings),
            ready_findings=sum(
                item.status is FindingReadinessStatus.READY for item in audit.records
            ),
            recommendations=len(recommendations),
            skipped_not_ready=sum(item.reason is StrategySkipReason.NOT_READY for item in skipped),
            skipped_no_rule=sum(
                item.reason is StrategySkipReason.NO_SUPPORTED_RULE for item in skipped
            ),
            skipped_threshold=sum(
                item.reason is StrategySkipReason.THRESHOLD_NOT_MET for item in skipped
            ),
            evidence_references=sum(len(item.evidence_references) for item in recommendations),
            maps=tuple(sorted({item.scope.map_name for item in recommendations})),
        )
        warnings = []
        if not audit.summary.stage_8_7_ready:
            warnings.append("readiness_gate_has_no_eligible_findings")
        if not recommendations:
            warnings.append("no_counter_strategy_recommendations_published")
        return CounterStrategyRun(
            strategy_run_id=run_id,
            strategy_fingerprint=fingerprint,
            configuration_hash=config_hash,
            profile_id=data.profile_id,
            source_analysis_run_id=audit.source_analysis_run_id,
            source_analysis_fingerprint=data.analysis_fingerprint,
            source_analysis_schema_version=data.analysis_schema_version,
            source_analysis_rule_version=data.analysis_rule_version,
            readiness_audit_id=audit.audit_id,
            readiness_fingerprint=audit.audit_fingerprint,
            readiness_schema_version=audit.readiness_schema_version,
            readiness_rule_version=audit.readiness_rule_version,
            readiness_config=audit.config,
            config=selected,
            recommendations=recommendations,
            skipped_findings=tuple(skipped),
            summary=summary,
            warnings=tuple(warnings),
        )


def _match_rule(
    finding: AnalysisFinding, config: CounterStrategyConfig
) -> tuple[_RuleText | None, bool]:
    value = _value_label(finding)
    frequency = finding.frequency
    percent = f"{frequency * 100:.1f}%"
    common = (
        f"This is an association across {finding.denominator_match_count} matches and "
        "does not prove intent or causality."
    )
    if finding.pattern_type is PatternType.SITE_PREFERENCE:
        if frequency < config.frequent_site_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.FREQUENT_SITE,
            CounterStrategyCategory.MAP_CONTROL,
            f"Prepare for the recurring {value} outcome",
            f"{value} accounted for {percent} of eligible proven plant outcomes. {common}",
            f"Keep information and rotation capacity for {value}; validate the tendency before committing the full team.",
            "Do not over-rotate from this frequency alone or treat an unobserved plant as proof of the opposite site.",
        ), True
    if finding.pattern_type in {
        PatternType.EARLY_ZONE_OCCUPATION,
        PatternType.FIRST_CONTACT_ZONE,
        PatternType.CT_STARTING_POSITION,
    }:
        if frequency < config.frequent_control_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.FREQUENT_EARLY_CONTROL,
            CounterStrategyCategory.MAP_CONTROL,
            f"Test and deny recurring control of {value}",
            f"Observable early/contact presence at {value} occurred in {percent} of eligible rounds. {common}",
            f"Prepare a tradeable utility-supported check of {value}, then adapt only after confirming the same setup in the match.",
            "Do not dry-peek the expected position repeatedly or assume the area is occupied when evidence is unavailable.",
        ), True
    if finding.pattern_type is PatternType.RECURRING_OPENING_PLAYER:
        if frequency < config.recurring_opening_player_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.RECURRING_OPENING_PLAYER,
            CounterStrategyCategory.PLAYER_SPECIFIC,
            f"Prepare for {value} in opening duels",
            f"{value} produced the observed opening kill in {percent} of eligible rounds. {common}",
            f"Use a tradeable anti-opening setup and early utility when the current round confirms {value}'s usual pressure.",
            "Do not repeatedly offer isolated opening duels or infer the player's location from identity alone.",
        ), True
    if finding.pattern_type is PatternType.RECURRING_OPENING_DEATH:
        if frequency < config.recurring_opening_death_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.RECURRING_OPENING_DEATH,
            CounterStrategyCategory.PLAYER_SPECIFIC,
            f"Test controlled early pressure against {value}",
            f"{value} was the observed opening victim in {percent} of eligible rounds. {common}",
            "Test a controlled, trade-supported early pressure only when live information confirms the relevant lane or setup.",
            "Do not hunt one player through unknown positions or sacrifice spacing merely because of this historical tendency.",
        ), True
    if finding.pattern_type is PatternType.OPENING_KILL_CONVERSION:
        if frequency > config.low_opening_conversion_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.LOW_OPENING_CONVERSION,
            CounterStrategyCategory.ROUND_MANAGEMENT,
            "Keep the round structured after conceding the opener",
            f"The opponent converted {percent} of eligible rounds after its observed opening kill. {common}",
            "Preserve trade structure, deny clean information, and test a measured recovery instead of treating the round as already lost.",
            "Do not force an immediate unsupported equalizer or assume every opening deficit is recoverable.",
        ), True
    if finding.pattern_type is PatternType.RECOVERY_AFTER_OPENING_DEATH:
        if frequency < config.opening_death_recovery_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.OPENING_DEATH_RECOVERY,
            CounterStrategyCategory.ROUND_MANAGEMENT,
            "Consolidate after gaining the opening advantage",
            f"The opponent recovered {percent} of eligible rounds after its observed opening death. {common}",
            "After gaining the opener, reset spacing, preserve trades, and deny the opponent isolated recovery fights.",
            "Do not relax, split into untradeable duels, or assume the opening kill has decided the round.",
        ), True
    if finding.pattern_type is PatternType.LOST_MAN_ADVANTAGE:
        if frequency < config.lost_advantage_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.LOST_MAN_ADVANTAGE,
            CounterStrategyCategory.ROUND_MANAGEMENT,
            "Keep pressure structured while the opponent is ahead",
            f"An observed man advantage was later lost in {percent} of eligible advantage states. {common}",
            "Keep the round active with tradeable pressure and information denial; make the opponent prove it can close the advantage.",
            "Do not turn this tendency into a reckless chase for an equalizer or ignore the current economy and positions.",
        ), True
    if finding.pattern_type is PatternType.UNTRADED_DEATH:
        if frequency < config.untraded_death_threshold:
            return None, True
        return _RuleText(
            CounterStrategyRuleId.UNTRADED_DEATH,
            CounterStrategyCategory.TRADE_STRUCTURE,
            "Use paired pressure against recurring isolated deaths",
            f"An opponent death remained untraded under the pinned trade rule in {percent} of eligible cases. {common}",
            "Favor paired, tradeable pressure and secure the gained space before extending beyond the first duel.",
            "Do not chase a second frag without support or claim the death was intentional baiting or poor communication.",
        ), True
    return None, False


def _materialize(
    run_id: UUID,
    profile_id: UUID,
    finding: AnalysisFinding,
    rule: _RuleText,
) -> CounterStrategyRecommendation:
    recommendation_id = uuid5(run_id, f"recommendation:{finding.finding_id}:{rule.rule_id}")
    limitations = set(finding.limitations)
    limitations.update(
        {
            "recommendation_is_a_prematch_hypothesis_to_validate",
            "historical_association_does_not_prove_future_behavior",
            "recommendation_does_not_claim_intent_or_causality",
        }
    )
    return CounterStrategyRecommendation(
        recommendation_id=recommendation_id,
        strategy_run_id=run_id,
        profile_id=profile_id,
        source_analysis_run_id=finding.analysis_run_id,
        source_finding_id=finding.finding_id,
        rule_id=rule.rule_id,
        category=rule.category,
        title=rule.title,
        scope=finding.scope,
        pattern_type=finding.pattern_type,
        pattern_value=finding.pattern_value,
        observation=finding.observation,
        tactical_interpretation=_available(rule.implication),
        recommendation=_available(rule.response),
        avoid=_available(rule.avoid),
        numerator=finding.numerator,
        denominator=finding.denominator,
        frequency=finding.frequency,
        sample_size=finding.sample_size,
        numerator_match_count=finding.numerator_match_count,
        denominator_match_count=finding.denominator_match_count,
        confidence=finding.confidence,
        evidence_references=finding.evidence_references,
        limitations=tuple(sorted(limitations)),
    )


def _skip(
    finding: AnalysisFinding,
    gate: FindingReadinessRecord,
    reason: StrategySkipReason,
) -> SkippedStrategyFinding:
    return SkippedStrategyFinding(
        finding_id=finding.finding_id,
        reason=reason,
        readiness_status=gate.status,
        readiness_blockers=gate.blocking_reasons,
        readiness_limitations=gate.limitations,
        pattern_type=finding.pattern_type,
        frequency=finding.frequency,
    )


def _value_label(finding: AnalysisFinding) -> str:
    value = finding.pattern_value
    return value.current_name if isinstance(value, PlayerPatternValue) else value.label


def _available(text: str) -> FindingText:
    return FindingText(availability=FindingTextAvailability.AVAILABLE, text=text)


def _sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["CounterStrategyEngine"]
