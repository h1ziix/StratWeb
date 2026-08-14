"""Golden Corpus loading, hashing, file verification and readiness validation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from stratweb.application.normalization_utils import canonical_json

from .models import (
    CaseReviewStatus,
    CorpusIssue,
    CorpusIssueCode,
    CorpusIssueSeverity,
    CorpusReadinessStatus,
    DemoFileCheck,
    FindingLabelValue,
    GoldenCorpusAudit,
    GoldenCorpusCoverage,
    GoldenCorpusManifest,
    GoldenDemoCase,
    GoldenPredictionSet,
    ParserCompatibilityStatus,
)


class GoldenCorpusError(ValueError):
    """A manifest or prediction artifact could not be read safely."""


ModelT = TypeVar("ModelT", GoldenCorpusManifest, GoldenPredictionSet)


def load_manifest(path: Path) -> GoldenCorpusManifest:
    return _load_json_model(path, GoldenCorpusManifest, "Golden Corpus manifest")


def load_predictions(path: Path) -> GoldenPredictionSet:
    return _load_json_model(path, GoldenPredictionSet, "Golden prediction set")


def manifest_fingerprint(manifest: GoldenCorpusManifest) -> str:
    payload = manifest.model_dump(mode="json")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class GoldenCorpusValidator:
    def validate(
        self,
        manifest: GoldenCorpusManifest,
        *,
        demo_root: Path | None = None,
    ) -> GoldenCorpusAudit:
        issues: list[CorpusIssue] = []
        confirmed = tuple(
            item for item in manifest.cases if item.review_status is CaseReviewStatus.CONFIRMED
        )
        candidates = tuple(
            item for item in manifest.cases if item.review_status is CaseReviewStatus.CANDIDATE
        )
        rejected = tuple(
            item for item in manifest.cases if item.review_status is CaseReviewStatus.REJECTED
        )

        opponent_cases: tuple[GoldenDemoCase, ...]
        if manifest.target_opponent_id is None:
            issues.append(
                _blocker(
                    CorpusIssueCode.TARGET_OPPONENT_UNKNOWN,
                    "Target opponent is not explicitly identified.",
                )
            )
            opponent_cases = ()
        else:
            mismatched = tuple(
                item.case_id
                for item in confirmed
                if item.opponent_confirmed and item.opponent_id != manifest.target_opponent_id
            )
            if mismatched:
                issues.append(
                    _blocker(
                        CorpusIssueCode.OPPONENT_MISMATCH,
                        "Confirmed opponent labels disagree with target_opponent_id.",
                        mismatched,
                    )
                )
            opponent_cases = tuple(
                item
                for item in confirmed
                if item.opponent_confirmed and item.opponent_id == manifest.target_opponent_id
            )

        policy = manifest.policy
        if len(opponent_cases) < policy.minimum_confirmed_opponent_matches:
            issues.append(
                _blocker(
                    CorpusIssueCode.CONFIRMED_MATCHES_BELOW_MINIMUM,
                    "Confirmed matches for the target opponent are below the configured minimum: "
                    f"{len(opponent_cases)}/{policy.minimum_confirmed_opponent_matches}.",
                    tuple(item.case_id for item in opponent_cases),
                )
            )

        opponent_maps = tuple(
            sorted({item.expected.map_name for item in opponent_cases if item.expected.map_name})
        )
        if len(opponent_maps) < policy.minimum_distinct_opponent_maps:
            issues.append(
                _blocker(
                    CorpusIssueCode.MAP_COVERAGE_INCOMPLETE,
                    "Confirmed target-opponent map coverage is incomplete: "
                    f"{len(opponent_maps)}/{policy.minimum_distinct_opponent_maps}.",
                    tuple(item.case_id for item in opponent_cases),
                )
            )

        confirmed_sources = tuple(sorted({item.source for item in confirmed}, key=str))
        missing_sources = tuple(
            item for item in policy.required_sources if item not in confirmed_sources
        )
        if missing_sources:
            issues.append(
                _blocker(
                    CorpusIssueCode.SOURCE_COVERAGE_INCOMPLETE,
                    "Required demo sources are missing: "
                    + ", ".join(item.value for item in missing_sources)
                    + ".",
                )
            )

        confirmed_edge_cases = tuple(
            sorted({edge for item in confirmed for edge in item.edge_cases}, key=str)
        )
        missing_edges = tuple(
            item for item in policy.required_edge_cases if item not in confirmed_edge_cases
        )
        if missing_edges:
            issues.append(
                _blocker(
                    CorpusIssueCode.EDGE_CASE_COVERAGE_INCOMPLETE,
                    "Required edge cases are missing: "
                    + ", ".join(item.value for item in missing_edges)
                    + ".",
                )
            )

        determinate_labels = sum(
            item.value is not FindingLabelValue.INDETERMINATE for item in manifest.finding_labels
        )
        positive_labels = sum(
            item.value is FindingLabelValue.PRESENT for item in manifest.finding_labels
        )
        negative_labels = sum(
            item.value is FindingLabelValue.ABSENT for item in manifest.finding_labels
        )
        if (
            determinate_labels < policy.minimum_determinate_finding_labels
            or positive_labels < policy.minimum_positive_finding_labels
            or negative_labels < policy.minimum_negative_finding_labels
        ):
            issues.append(
                _blocker(
                    CorpusIssueCode.FINDING_LABELS_INCOMPLETE,
                    "Analyst finding labels are below configured determinate/positive/negative "
                    "minimums: "
                    f"{determinate_labels}/{policy.minimum_determinate_finding_labels}, "
                    f"{positive_labels}/{policy.minimum_positive_finding_labels}, "
                    f"{negative_labels}/{policy.minimum_negative_finding_labels}.",
                )
            )

        compatibility = {
            (item.case_id, item.parser_name, item.parser_version): item
            for item in manifest.parser_compatibility
        }
        missing_matrix: list[str] = []
        for case in confirmed:
            for parser in policy.required_parsers:
                record = compatibility.get(
                    (case.case_id, parser.parser_name, parser.parser_version)
                )
                if record is None or record.status is not ParserCompatibilityStatus.SUPPORTED:
                    missing_matrix.append(case.case_id)
        if missing_matrix:
            issues.append(
                _blocker(
                    CorpusIssueCode.PARSER_MATRIX_INCOMPLETE,
                    "Required parser compatibility records are incomplete.",
                    tuple(sorted(set(missing_matrix))),
                )
            )

        file_checks, file_issues = _check_files(manifest, demo_root)
        issues.extend(file_issues)
        coverage = GoldenCorpusCoverage(
            total_cases=len(manifest.cases),
            confirmed_cases=len(confirmed),
            candidate_cases=len(candidates),
            rejected_cases=len(rejected),
            confirmed_opponent_matches=len(opponent_cases),
            distinct_opponent_maps=opponent_maps,
            confirmed_sources=confirmed_sources,
            confirmed_edge_cases=confirmed_edge_cases,
            determinate_finding_labels=determinate_labels,
            positive_finding_labels=positive_labels,
            negative_finding_labels=negative_labels,
            parser_matrix_records=len(manifest.parser_compatibility),
            checked_demo_files=sum(item.exists is not None for item in file_checks),
            valid_demo_files=sum(item.sha256_matches is True for item in file_checks),
        )
        ordered_issues = tuple(
            sorted(issues, key=lambda item: (item.severity.value, item.code.value, item.message))
        )
        status = (
            CorpusReadinessStatus.BLOCKED
            if any(item.severity is CorpusIssueSeverity.BLOCKER for item in ordered_issues)
            else CorpusReadinessStatus.READY
        )
        return GoldenCorpusAudit(
            manifest_fingerprint=manifest_fingerprint(manifest),
            corpus_id=manifest.corpus_id,
            corpus_version=manifest.corpus_version,
            status=status,
            coverage=coverage,
            issues=ordered_issues,
            file_checks=file_checks,
        )


def _check_files(
    manifest: GoldenCorpusManifest,
    demo_root: Path | None,
) -> tuple[tuple[DemoFileCheck, ...], tuple[CorpusIssue, ...]]:
    if demo_root is None:
        return (), (
            CorpusIssue(
                code=CorpusIssueCode.DEMO_ROOT_NOT_CHECKED,
                severity=CorpusIssueSeverity.WARNING,
                message=(
                    "Demo files were not checked; provide --demo-root for byte-level verification."
                ),
            ),
        )
    root = demo_root.expanduser().resolve()
    checks: list[DemoFileCheck] = []
    issues: list[CorpusIssue] = []
    for case in sorted(manifest.cases, key=lambda item: item.case_id):
        path = root / f"{case.demo_sha256}.dem"
        if not path.is_file():
            checks.append(DemoFileCheck(case_id=case.case_id, path=str(path), exists=False))
            severity = (
                CorpusIssueSeverity.BLOCKER
                if case.review_status is CaseReviewStatus.CONFIRMED
                else CorpusIssueSeverity.WARNING
            )
            issues.append(
                CorpusIssue(
                    code=CorpusIssueCode.DEMO_FILE_MISSING,
                    severity=severity,
                    message=f"Corpus demo is missing for {case.case_id}.",
                    affected_case_ids=(case.case_id,),
                )
            )
            continue
        digest = _sha256_file(path)
        matches = digest == case.demo_sha256
        checks.append(
            DemoFileCheck(
                case_id=case.case_id,
                path=str(path),
                exists=True,
                sha256_matches=matches,
            )
        )
        if not matches:
            issues.append(
                _blocker(
                    CorpusIssueCode.DEMO_HASH_MISMATCH,
                    f"Corpus demo hash does not match manifest for {case.case_id}.",
                    (case.case_id,),
                )
            )
    return tuple(checks), tuple(issues)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _blocker(
    code: CorpusIssueCode,
    message: str,
    affected_case_ids: Iterable[str] = (),
) -> CorpusIssue:
    return CorpusIssue(
        code=code,
        severity=CorpusIssueSeverity.BLOCKER,
        message=message,
        affected_case_ids=tuple(affected_case_ids),
    )


def _load_json_model(
    path: Path,
    model_type: type[ModelT],
    label: str,
) -> ModelT:
    candidate = path.expanduser().resolve()
    try:
        payload = candidate.read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldenCorpusError(f"Could not read {label}: {candidate}") from exc
    try:
        return model_type.model_validate_json(payload)
    except ValidationError as exc:
        raise GoldenCorpusError(f"Invalid {label} {candidate}: {exc}") from exc


__all__ = [
    "GoldenCorpusError",
    "GoldenCorpusValidator",
    "load_manifest",
    "load_predictions",
    "manifest_fingerprint",
]
