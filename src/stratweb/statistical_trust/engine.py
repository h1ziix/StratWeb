"""Pure deterministic statistical trust assessment over persisted patterns."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from stratweb.application.normalization_utils import canonical_json
from stratweb.patterns.models import (
    BinaryPatternValue,
    CategoricalPatternValue,
    CrossMatchPattern,
    PatternAvailability,
)
from stratweb.statistical_trust.models import (
    STATISTICAL_TRUST_RULE_VERSION,
    STATISTICAL_TRUST_SCHEMA_VERSION,
    GateStatus,
    MatchClusterEstimate,
    MatchContribution,
    MultipleComparisonResult,
    StabilityAssessment,
    StabilityDimension,
    StatisticalTrustAssessment,
    StatisticalTrustConfig,
    StatisticalTrustInput,
    StatisticalTrustRun,
    StatisticalTrustSummary,
    TrustAvailability,
    TrustDecision,
    TrustGates,
)


@dataclass(frozen=True, slots=True)
class _Draft:
    pattern: CrossMatchPattern
    contributions: tuple[MatchContribution, ...]
    interval: MatchClusterEstimate
    match_stability: StabilityAssessment
    null_frequency: float | None
    effect_size: float | None
    raw_p_value: float | None
    tested_cluster_count: int
    not_testable_reason: str | None


class StatisticalTrustEngine:
    """Measure evidence reliability without producing tactical text or causal claims."""

    def compute(
        self,
        data: StatisticalTrustInput,
        config: StatisticalTrustConfig | None = None,
    ) -> StatisticalTrustRun:
        selected = config or StatisticalTrustConfig()
        patterns = tuple(sorted(data.patterns, key=lambda item: str(item.pattern_id)))
        if any(
            item.profile_id != data.profile_id or item.pattern_run_id != data.source_pattern_run_id
            for item in patterns
        ):
            raise ValueError("statistical trust input contains a pattern outside the pinned run")
        config_hash = hashlib.sha256(
            canonical_json(selected.model_dump(mode="json")).encode()
        ).hexdigest()
        drafts = tuple(self._draft(item, selected, config_hash) for item in patterns)
        adjusted = _benjamini_hochberg(
            tuple(
                (item.pattern.pattern_id, item.raw_p_value)
                for item in drafts
                if item.raw_p_value is not None
            )
        )
        family_size = len(adjusted)
        provisional = tuple(
            self._assessment_payload(item, selected, adjusted, family_size) for item in drafts
        )
        ranked = _rank(provisional)
        payload = {
            "schema": STATISTICAL_TRUST_SCHEMA_VERSION,
            "rules": STATISTICAL_TRUST_RULE_VERSION,
            "config_hash": config_hash,
            "profile_id": str(data.profile_id),
            "source_pattern_run_id": str(data.source_pattern_run_id),
            "source_pattern_fingerprint": data.source_pattern_fingerprint,
            "assessments": _json_value(ranked),
        }
        fingerprint = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        run_id = uuid5(NAMESPACE_URL, f"stratweb:statistical-trust:{fingerprint}")
        assessments = tuple(
            StatisticalTrustAssessment(
                assessment_id=uuid5(run_id, f"assessment:{item['source_pattern_id']}"),
                trust_run_id=run_id,
                profile_id=data.profile_id,
                source_pattern_run_id=data.source_pattern_run_id,
                **item,
            )
            for item in ranked
        )
        summary = StatisticalTrustSummary(
            source_patterns=len(assessments),
            testable_patterns=sum(
                item.decision is not TrustDecision.NOT_TESTABLE for item in assessments
            ),
            supported_patterns=sum(
                item.decision is TrustDecision.SUPPORTED for item in assessments
            ),
            not_supported_patterns=sum(
                item.decision is TrustDecision.NOT_SUPPORTED for item in assessments
            ),
            insufficient_data_patterns=sum(
                item.decision is TrustDecision.INSUFFICIENT_DATA for item in assessments
            ),
            not_testable_patterns=sum(
                item.decision is TrustDecision.NOT_TESTABLE for item in assessments
            ),
            patch_stability_available=sum(
                item.patch_stability.availability is TrustAvailability.AVAILABLE
                for item in assessments
            ),
            roster_period_stability_available=sum(
                item.roster_period_stability.availability is TrustAvailability.AVAILABLE
                for item in assessments
            ),
        )
        warnings = []
        if assessments and summary.patch_stability_available == 0:
            warnings.append("patch_stability_unavailable_no_match_patch_metadata")
        if assessments and summary.roster_period_stability_available == 0:
            warnings.append("roster_period_stability_unavailable_no_match_time_periods")
        return StatisticalTrustRun(
            trust_run_id=run_id,
            trust_fingerprint=fingerprint,
            configuration_hash=config_hash,
            profile_id=data.profile_id,
            source_pattern_run_id=data.source_pattern_run_id,
            source_pattern_fingerprint=data.source_pattern_fingerprint,
            source_pattern_schema_version=data.source_pattern_schema_version,
            source_pattern_rule_version=data.source_pattern_rule_version,
            config=selected,
            assessments=assessments,
            summary=summary,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _draft(
        pattern: CrossMatchPattern,
        config: StatisticalTrustConfig,
        config_hash: str,
    ) -> _Draft:
        contributions = _match_contributions(pattern)
        interval = _cluster_interval(pattern, contributions, config, config_hash)
        stability = _match_stability(contributions, config)
        null, reason = _null_hypothesis(pattern, config)
        effect = pattern.frequency - null if null is not None else None
        p_value, tested_clusters = (
            _match_cluster_sign_test(contributions, null) if null is not None else (None, 0)
        )
        return _Draft(
            pattern=pattern,
            contributions=contributions,
            interval=interval,
            match_stability=stability,
            null_frequency=null,
            effect_size=effect,
            raw_p_value=p_value,
            tested_cluster_count=tested_clusters,
            not_testable_reason=reason,
        )

    @staticmethod
    def _assessment_payload(
        draft: _Draft,
        config: StatisticalTrustConfig,
        adjusted: dict[UUID, float],
        family_size: int,
    ) -> dict[str, Any]:
        pattern = draft.pattern
        testable = draft.null_frequency is not None and draft.raw_p_value is not None
        if testable:
            q_value = adjusted[pattern.pattern_id]
            multiple = MultipleComparisonResult(
                availability=TrustAvailability.AVAILABLE,
                family_size=family_size,
                tested_cluster_count=draft.tested_cluster_count,
                raw_p_value=draft.raw_p_value,
                adjusted_q_value=q_value,
                alpha=config.false_discovery_rate,
            )
        else:
            q_value = None
            multiple = MultipleComparisonResult(
                availability=TrustAvailability.UNAVAILABLE,
                family_size=family_size,
                tested_cluster_count=0,
                alpha=config.false_discovery_rate,
                unavailable_reason=draft.not_testable_reason,
            )
        cluster_gate = (
            GateStatus.PASS
            if pattern.denominator_match_count >= config.minimum_cluster_matches
            else GateStatus.FAIL
        )
        effect_gate = (
            GateStatus.PASS
            if draft.effect_size is not None
            and draft.effect_size + 1e-12 >= config.minimum_effect_size
            else GateStatus.FAIL
            if testable
            else GateStatus.UNAVAILABLE
        )
        lower_gate = (
            GateStatus.PASS
            if draft.interval.lower_bound is not None
            and draft.null_frequency is not None
            and draft.interval.lower_bound > draft.null_frequency
            else (
                GateStatus.FAIL
                if draft.interval.availability is TrustAvailability.AVAILABLE and testable
                else GateStatus.UNAVAILABLE
            )
        )
        multiple_gate = (
            GateStatus.PASS
            if q_value is not None and q_value <= config.false_discovery_rate
            else GateStatus.FAIL
            if testable
            else GateStatus.UNAVAILABLE
        )
        stability_gate = (
            GateStatus.PASS
            if draft.match_stability.stable is True
            else (
                GateStatus.FAIL
                if draft.match_stability.availability is TrustAvailability.AVAILABLE
                else GateStatus.UNAVAILABLE
            )
        )
        gates = TrustGates(
            source_quality=(
                GateStatus.PASS
                if pattern.availability is PatternAvailability.AVAILABLE
                else GateStatus.FAIL
            ),
            cluster_count=cluster_gate,
            practical_effect=effect_gate,
            clustered_lower_bound=lower_gate,
            multiple_comparison=multiple_gate,
            match_stability=stability_gate,
        )
        if not testable:
            decision = TrustDecision.NOT_TESTABLE
        elif cluster_gate is GateStatus.FAIL or stability_gate is GateStatus.UNAVAILABLE:
            decision = TrustDecision.INSUFFICIENT_DATA
        elif all(
            value is GateStatus.PASS
            for value in (
                gates.cluster_count,
                gates.source_quality,
                gates.practical_effect,
                gates.clustered_lower_bound,
                gates.multiple_comparison,
                gates.match_stability,
            )
        ):
            decision = TrustDecision.SUPPORTED
        else:
            decision = TrustDecision.NOT_SUPPORTED
        score = _reliability_score(draft, config, decision)
        limitations = set(pattern.limitations)
        limitations.update(
            {
                "rounds_within_one_match_are_not_treated_as_independent_clusters",
                "patch_stability_unavailable_no_match_patch_metadata",
                "roster_period_stability_unavailable_no_match_time_periods",
                "statistical_support_does_not_prove_causality_or_tactical_value",
            }
        )
        if draft.not_testable_reason:
            limitations.add(draft.not_testable_reason)
        if pattern.availability is not PatternAvailability.AVAILABLE:
            limitations.add("source_pattern_availability_is_partial")
        return {
            "source_pattern_id": pattern.pattern_id,
            "source_pattern_type": pattern.pattern_type,
            "source_availability": pattern.availability,
            "scope": pattern.scope,
            "numerator": pattern.numerator,
            "denominator": pattern.denominator,
            "frequency": pattern.frequency,
            "denominator_match_count": pattern.denominator_match_count,
            "match_contributions": draft.contributions,
            "clustered_interval": draft.interval,
            "null_frequency": draft.null_frequency,
            "effect_size": draft.effect_size,
            "multiple_comparison": multiple,
            "match_stability": draft.match_stability,
            "patch_stability": _unavailable_stability(
                StabilityDimension.PATCH, "match_patch_metadata_unavailable"
            ),
            "roster_period_stability": _unavailable_stability(
                StabilityDimension.ROSTER_PERIOD,
                "match_time_and_versioned_roster_periods_unavailable",
            ),
            "gates": gates,
            "decision": decision,
            "reliability_score": score,
            "reliability_rank": None,
            "limitations": tuple(sorted(limitations)),
        }


def _match_contributions(pattern: CrossMatchPattern) -> tuple[MatchContribution, ...]:
    grouped: dict[UUID, list[bool]] = {}
    for item in pattern.included_rounds:
        grouped.setdefault(item.match_id, []).append(item.contributed_to_numerator)
    return tuple(
        MatchContribution(
            match_id=match_id,
            numerator=sum(values),
            denominator=len(values),
            frequency=sum(values) / len(values),
        )
        for match_id, values in sorted(grouped.items(), key=lambda item: str(item[0]))
    )


def _cluster_interval(
    pattern: CrossMatchPattern,
    contributions: tuple[MatchContribution, ...],
    config: StatisticalTrustConfig,
    config_hash: str,
) -> MatchClusterEstimate:
    if len(contributions) < 2:
        return MatchClusterEstimate(
            availability=TrustAvailability.UNAVAILABLE,
            confidence_level=config.confidence_level,
            cluster_count=len(contributions),
            bootstrap_iterations=0,
            unavailable_reason="at_least_two_match_clusters_required",
        )
    seed_material = f"{pattern.pattern_id}:{config_hash}"
    seed = hashlib.sha256(seed_material.encode()).digest()
    estimates = []
    counter = 0
    for _iteration in range(config.bootstrap_iterations):
        sample = []
        for _cluster in contributions:
            index = _deterministic_index(seed, counter, len(contributions))
            counter += 1
            sample.append(contributions[index])
        estimates.append(
            sum(item.numerator for item in sample) / sum(item.denominator for item in sample)
        )
    estimates.sort()
    alpha = (1 - config.confidence_level) / 2
    lower = estimates[int(alpha * (len(estimates) - 1))]
    upper = estimates[int((1 - alpha) * (len(estimates) - 1))]
    return MatchClusterEstimate(
        availability=TrustAvailability.AVAILABLE,
        confidence_level=config.confidence_level,
        point_estimate=pattern.frequency,
        lower_bound=min(lower, pattern.frequency),
        upper_bound=max(upper, pattern.frequency),
        cluster_count=len(contributions),
        bootstrap_iterations=config.bootstrap_iterations,
    )


def _deterministic_index(seed: bytes, counter: int, size: int) -> int:
    digest = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
    return int.from_bytes(digest[:8], "big") % size


def _match_stability(
    contributions: tuple[MatchContribution, ...], config: StatisticalTrustConfig
) -> StabilityAssessment:
    if len(contributions) < config.minimum_stability_matches:
        return StabilityAssessment(
            dimension=StabilityDimension.MATCH,
            availability=TrustAvailability.UNAVAILABLE,
            group_count=len(contributions),
            unavailable_reason="insufficient_match_clusters_for_stability",
            limitations=(f"requires_at_least_{config.minimum_stability_matches}_match_clusters",),
        )
    total_n = sum(item.numerator for item in contributions)
    total_d = sum(item.denominator for item in contributions)
    leave_one_out = tuple(
        (total_n - item.numerator) / (total_d - item.denominator)
        for item in contributions
        if total_d > item.denominator
    )
    minimum = min(leave_one_out)
    maximum = max(leave_one_out)
    spread = maximum - minimum
    direction = sum(item.frequency > config.null_frequency for item in contributions) / len(
        contributions
    )
    stable = (
        spread <= config.maximum_leave_one_out_range
        and direction >= config.minimum_direction_consistency
    )
    return StabilityAssessment(
        dimension=StabilityDimension.MATCH,
        availability=TrustAvailability.AVAILABLE,
        stable=stable,
        group_count=len(contributions),
        leave_one_out_min=minimum,
        leave_one_out_max=maximum,
        leave_one_out_range=spread,
        direction_consistency=direction,
        limitations=("stability_is_descriptive_not_causal",),
    )


def _unavailable_stability(dimension: StabilityDimension, reason: str) -> StabilityAssessment:
    return StabilityAssessment(
        dimension=dimension,
        availability=TrustAvailability.UNAVAILABLE,
        group_count=0,
        unavailable_reason=reason,
    )


def _null_hypothesis(
    pattern: CrossMatchPattern, config: StatisticalTrustConfig
) -> tuple[float | None, str | None]:
    if isinstance(pattern.value, BinaryPatternValue):
        return config.null_frequency, None
    if isinstance(pattern.value, CategoricalPatternValue) and pattern.value.key in {
        "site:A",
        "site:B",
    }:
        return 0.5, None
    return None, "no_pre_registered_null_for_pattern_value"


def _binomial_upper_tail(successes: int, trials: int, probability: float) -> float:
    return min(
        1.0,
        sum(
            math.comb(trials, value) * probability**value * (1 - probability) ** (trials - value)
            for value in range(successes, trials + 1)
        ),
    )


def _match_cluster_sign_test(
    contributions: tuple[MatchContribution, ...], null_frequency: float
) -> tuple[float, int]:
    above = sum(item.frequency > null_frequency for item in contributions)
    below = sum(item.frequency < null_frequency for item in contributions)
    tested = above + below
    if tested == 0:
        return 1.0, 0
    return _binomial_upper_tail(above, tested, 0.5), tested


def _benjamini_hochberg(values: tuple[tuple[UUID, float], ...]) -> dict[UUID, float]:
    ordered = sorted(values, key=lambda item: (item[1], str(item[0])))
    count = len(ordered)
    result: dict[UUID, float] = {}
    running = 1.0
    for rank in range(count, 0, -1):
        pattern_id, p_value = ordered[rank - 1]
        running = min(running, p_value * count / rank)
        result[pattern_id] = min(1.0, running)
    return result


def _reliability_score(
    draft: _Draft, config: StatisticalTrustConfig, decision: TrustDecision
) -> float | None:
    if decision is not TrustDecision.SUPPORTED:
        return None
    if (
        draft.interval.lower_bound is None
        or draft.effect_size is None
        or draft.match_stability.direction_consistency is None
    ):
        return None
    lower_support = max(0.0, draft.interval.lower_bound - config.null_frequency)
    effect = max(0.0, draft.effect_size)
    direction = draft.match_stability.direction_consistency
    return min(1.0, lower_support * 0.5 + effect * 0.3 + direction * 0.2)


def _rank(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    eligible = sorted(
        (row for row in rows if row["reliability_score"] is not None),
        key=lambda row: (
            row["decision"] is not TrustDecision.SUPPORTED,
            -row["reliability_score"],
            -row["denominator_match_count"],
            str(row["source_pattern_id"]),
        ),
    )
    ranks = {row["source_pattern_id"]: index + 1 for index, row in enumerate(eligible)}
    return tuple({**row, "reliability_rank": ranks.get(row["source_pattern_id"])} for row in rows)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


__all__ = ["StatisticalTrustEngine"]
