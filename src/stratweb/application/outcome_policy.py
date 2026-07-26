"""Safety policy for consumers that require authoritative round winners."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from stratweb.application.canonical_models import (
    CanonicalRound,
    CapabilityCoverageStatus,
    DataAvailability,
    RoundOutcomeStatus,
)
from stratweb.application.persistence_models import (
    DataUseCapability,
    OutcomeCapability,
    ResultUsePolicy,
)


def evaluate_result_use_policy(rounds: Sequence[CanonicalRound]) -> ResultUsePolicy:
    """Report whether winner- and score-dependent consumers may run safely."""

    return ResultUsePolicy(
        round_winner=evaluate_round_outcome_capability(rounds),
        round_score=evaluate_score_statuses(
            tuple(round_item.score_status for round_item in rounds)
        ),
    )


def evaluate_round_outcome_capability(
    rounds: Sequence[CanonicalRound],
) -> OutcomeCapability:
    """Block win-based consumers unless every round has an authoritative outcome."""

    return evaluate_outcome_statuses(tuple(round_item.outcome_status for round_item in rounds))


def evaluate_outcome_statuses(
    statuses: Sequence[RoundOutcomeStatus],
) -> OutcomeCapability:
    total = len(statuses)
    available = sum(status.is_available for status in statuses)
    unavailable = total - available
    coverage = available / total if total else 0.0
    can_compute = total > 0 and unavailable == 0

    if total == 0:
        status = CapabilityCoverageStatus.NOT_APPLICABLE
        reason = "no_rounds"
    elif can_compute:
        status = CapabilityCoverageStatus.AVAILABLE
        reason = None
    elif available:
        status = CapabilityCoverageStatus.PARTIAL
        reason = _unavailable_reason(statuses)
    elif any(
        item in {RoundOutcomeStatus.UNRESOLVED, RoundOutcomeStatus.UNRESOLVED_CONFLICT}
        for item in statuses
    ):
        status = CapabilityCoverageStatus.UNRESOLVED
        reason = _unavailable_reason(statuses)
    else:
        status = CapabilityCoverageStatus.MISSING_FROM_SOURCE
        reason = _unavailable_reason(statuses)

    return OutcomeCapability(
        status=status,
        available_rounds=available,
        unavailable_rounds=unavailable,
        coverage=coverage,
        can_compute_win_metrics=can_compute,
        unavailable_reason=reason,
    )


def evaluate_score_statuses(statuses: Sequence[DataAvailability]) -> DataUseCapability:
    total = len(statuses)
    available = statuses.count(DataAvailability.AVAILABLE)
    unavailable = total - available
    coverage = available / total if total else 0.0
    can_use = total > 0 and unavailable == 0
    if total == 0:
        status = CapabilityCoverageStatus.NOT_APPLICABLE
        reason = "no_rounds"
    elif can_use:
        status = CapabilityCoverageStatus.AVAILABLE
        reason = None
    elif available:
        status = CapabilityCoverageStatus.PARTIAL
        reason = _data_unavailable_reason(statuses)
    elif DataAvailability.UNRESOLVED in statuses:
        status = CapabilityCoverageStatus.UNRESOLVED
        reason = _data_unavailable_reason(statuses)
    elif all(item is DataAvailability.NOT_APPLICABLE for item in statuses):
        status = CapabilityCoverageStatus.NOT_APPLICABLE
        reason = _data_unavailable_reason(statuses)
    else:
        status = CapabilityCoverageStatus.MISSING_FROM_SOURCE
        reason = _data_unavailable_reason(statuses)
    return DataUseCapability(
        status=status,
        available_rounds=available,
        unavailable_rounds=unavailable,
        coverage=coverage,
        can_use=can_use,
        unavailable_reason=reason,
    )


def _unavailable_reason(statuses: Sequence[RoundOutcomeStatus]) -> str:
    counts = Counter(status.value for status in statuses if not status.is_available)
    return ",".join(f"{name}:{counts[name]}" for name in sorted(counts))


def _data_unavailable_reason(statuses: Sequence[DataAvailability]) -> str:
    counts = Counter(
        status.value for status in statuses if status is not DataAvailability.AVAILABLE
    )
    return ",".join(f"{name}:{counts[name]}" for name in sorted(counts))
