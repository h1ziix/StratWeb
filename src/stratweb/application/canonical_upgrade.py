"""Deterministic, conservative upgrade of canonical JSON 1.0.0 to 1.1.0."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from typing import Any

from stratweb.application.canonical_models import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalMatchDataset,
    CapabilityCoverageStatus,
    DataAvailability,
    ResultCapabilities,
    ResultCapability,
    RoundOutcomeStatus,
    ValidationSeverity,
)
from stratweb.application.canonicalization import compute_dataset_fingerprint
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.outcome_resolution import OUTCOME_SOURCE_EVENTS
from stratweb.application.validation import result_availability_issues
from stratweb.exceptions import DatasetFingerprintMismatchError

LEGACY_CANONICAL_SCHEMA_VERSION = "1.0.0"


def upgrade_v1_payload(payload: dict[str, Any]) -> CanonicalMatchDataset:
    """Upgrade without claiming that legacy result values were authoritative."""

    _verify_legacy_fingerprint(payload)
    upgraded = copy.deepcopy(payload)
    winner_statuses: list[str] = []
    score_statuses: list[str] = []
    reason_statuses: list[str] = []
    for round_payload in upgraded.get("rounds", []):
        old_winner = round_payload.get("winner_side")
        outcome_status = (
            RoundOutcomeStatus.UNRESOLVED
            if old_winner in {"T", "CT"}
            else RoundOutcomeStatus.MISSING_FROM_SOURCE
        )
        winner_statuses.append(outcome_status.value)
        round_payload["winner_side"] = None
        round_payload["outcome_status"] = outcome_status.value
        round_payload["outcome_source"] = None

        score_fields = (
            "score_t_before",
            "score_ct_before",
            "score_t_after",
            "score_ct_after",
        )
        score_status = (
            DataAvailability.UNRESOLVED
            if any(round_payload.get(field) is not None for field in score_fields)
            else DataAvailability.MISSING_FROM_SOURCE
        )
        score_statuses.append(score_status.value)
        for field in score_fields:
            round_payload[field] = None
        round_payload["score_status"] = score_status.value
        round_payload["score_source"] = None

        reason_status = (
            DataAvailability.UNRESOLVED
            if round_payload.get("end_reason") is not None
            else DataAvailability.MISSING_FROM_SOURCE
        )
        reason_statuses.append(reason_status.value)
        round_payload["end_reason"] = None
        round_payload["end_reason_status"] = reason_status.value
        round_payload["end_reason_source"] = None

    capabilities = ResultCapabilities(
        round_winner=_legacy_outcome_capability(winner_statuses),
        round_score=_legacy_availability_capability(score_statuses),
        round_end_reason=_legacy_availability_capability(reason_statuses),
    )
    metadata = upgraded["normalization_metadata"]
    metadata["canonical_schema_version"] = CANONICAL_SCHEMA_VERSION
    metadata["result_capabilities"] = capabilities.model_dump(mode="json")
    metadata["warnings"] = list(
        dict.fromkeys(
            (
                *metadata.get("warnings", []),
                "Canonical JSON was upgraded from 1.0.0; legacy round-result "
                "provenance is unavailable and was classified conservatively.",
            )
        )
    )
    upgraded["schema_version"] = CANONICAL_SCHEMA_VERSION
    upgraded["dataset_fingerprint"] = "0" * 64
    dataset = CanonicalMatchDataset.model_validate(upgraded)

    existing = list(dataset.validation_report.issues)
    existing_codes = {issue.code for issue in existing}
    existing.extend(
        issue
        for issue in result_availability_issues(capabilities)
        if issue.code not in existing_codes
    )
    counts = Counter(issue.severity for issue in existing)
    fatal_count = sum(issue.is_fatal for issue in existing)
    report = dataset.validation_report.model_copy(
        update={
            "is_valid": counts[ValidationSeverity.ERROR] == 0,
            "has_fatal_errors": fatal_count > 0,
            "fatal_error_count": fatal_count,
            "issue_counts": {severity: counts[severity] for severity in ValidationSeverity},
            "issues": tuple(existing),
        }
    )
    provisional = dataset.model_copy(update={"validation_report": report})
    return provisional.model_copy(
        update={"dataset_fingerprint": compute_dataset_fingerprint(provisional)}
    )


def _verify_legacy_fingerprint(payload: dict[str, Any]) -> None:
    stored = payload.get("dataset_fingerprint")
    content = {key: value for key, value in payload.items() if key != "dataset_fingerprint"}
    recalculated = hashlib.sha256(canonical_json(content).encode()).hexdigest()
    if stored != recalculated:
        raise DatasetFingerprintMismatchError(
            "Legacy canonical dataset fingerprint does not match its content."
        )


def _legacy_outcome_capability(statuses: list[str]) -> ResultCapability:
    available = sum(RoundOutcomeStatus(status).is_available for status in statuses)
    missing = statuses.count(RoundOutcomeStatus.MISSING_FROM_SOURCE.value)
    unresolved = len(statuses) - available - missing
    return _legacy_capability(len(statuses), available, missing, unresolved)


def _legacy_availability_capability(statuses: list[str]) -> ResultCapability:
    available = statuses.count(DataAvailability.AVAILABLE.value)
    missing = statuses.count(DataAvailability.MISSING_FROM_SOURCE.value)
    unresolved = statuses.count(DataAvailability.UNRESOLVED.value)
    return _legacy_capability(len(statuses), available, missing, unresolved)


def _legacy_capability(
    total: int, available: int, missing: int, unresolved: int
) -> ResultCapability:
    if total == 0:
        status = CapabilityCoverageStatus.NOT_APPLICABLE
    elif available == total:
        status = CapabilityCoverageStatus.AVAILABLE
    elif available:
        status = CapabilityCoverageStatus.PARTIAL
    elif unresolved:
        status = CapabilityCoverageStatus.UNRESOLVED
    else:
        status = CapabilityCoverageStatus.MISSING_FROM_SOURCE
    return ResultCapability(
        status=status,
        source_events_checked=OUTCOME_SOURCE_EVENTS,
        detected_fields=(),
        authoritative_source_found=False,
        total_round_count=total,
        rounds_available=available,
        rounds_missing=missing,
        rounds_unresolved=unresolved,
    )
