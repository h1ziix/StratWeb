"""Sequential, failure-isolated execution of external Golden Corpus demos."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from stratweb.application.canonical_models import CanonicalMatchDataset
from stratweb.exceptions import DemoInspectionError, ParserContractError

from .manifest import manifest_fingerprint
from .models import (
    CaseReviewStatus,
    CorpusCaseRunStatus,
    ExpectedMatchFacts,
    ExpectedParseStatus,
    GoldenCaseRunResult,
    GoldenCorpusManifest,
    GoldenCorpusRunReport,
    GoldenDemoCase,
)


class CanonicalNormalizer(Protocol):
    def normalize(self, path: Path) -> CanonicalMatchDataset: ...


class GoldenCorpusRunner:
    def __init__(
        self,
        normalizer: CanonicalNormalizer,
        *,
        parser_name: str,
        parser_version: str,
    ) -> None:
        self._normalizer = normalizer
        self._parser_name = parser_name
        self._parser_version = parser_version

    def run(
        self,
        manifest: GoldenCorpusManifest,
        demo_root: Path,
        *,
        include_candidates: bool = False,
    ) -> GoldenCorpusRunReport:
        selected = tuple(
            item
            for item in sorted(manifest.cases, key=lambda case: case.case_id)
            if item.review_status is CaseReviewStatus.CONFIRMED
            or (include_candidates and item.review_status is CaseReviewStatus.CANDIDATE)
        )
        root = demo_root.expanduser().resolve()
        results = tuple(self._run_case(case, root) for case in selected)
        passed_cases = sum(item.status is CorpusCaseRunStatus.PASSED for item in results)
        failed_cases = sum(item.status is CorpusCaseRunStatus.FAILED for item in results)
        unavailable_cases = sum(item.status is CorpusCaseRunStatus.UNAVAILABLE for item in results)
        complete = bool(results) and unavailable_cases == 0
        return GoldenCorpusRunReport(
            manifest_fingerprint=manifest_fingerprint(manifest),
            parser_name=self._parser_name,
            parser_version=self._parser_version,
            selected_cases=len(results),
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            unavailable_cases=unavailable_cases,
            complete=complete,
            passed=complete and failed_cases == 0,
            results=results,
        )

    def _run_case(self, case: GoldenDemoCase, root: Path) -> GoldenCaseRunResult:
        path = root / f"{case.demo_sha256}.dem"
        if not path.is_file() or _sha256_file(path) != case.demo_sha256:
            return GoldenCaseRunResult(
                case_id=case.case_id,
                status=CorpusCaseRunStatus.UNAVAILABLE,
                expected_parse_status=case.expected_parse_status,
                mismatches=("demo_missing_or_sha256_mismatch",),
            )
        try:
            dataset = self._normalizer.normalize(path)
        except DemoInspectionError as exc:
            expected_rejection = (
                case.expected_parse_status is ExpectedParseStatus.REJECTED
                and not isinstance(exc, ParserContractError)
            )
            return GoldenCaseRunResult(
                case_id=case.case_id,
                status=(
                    CorpusCaseRunStatus.PASSED if expected_rejection else CorpusCaseRunStatus.FAILED
                ),
                expected_parse_status=case.expected_parse_status,
                parser_error_code=exc.error_code,
                mismatches=() if expected_rejection else ("unexpected_parser_error",),
            )
        except Exception as exc:  # one damaged fixture must not abort the remaining corpus
            return GoldenCaseRunResult(
                case_id=case.case_id,
                status=CorpusCaseRunStatus.FAILED,
                expected_parse_status=case.expected_parse_status,
                parser_error_code=type(exc).__name__,
                mismatches=("unexpected_runner_error",),
            )

        observed = ExpectedMatchFacts(
            match_id=dataset.match.match_id,
            dataset_fingerprint=dataset.dataset_fingerprint,
            map_name=dataset.match.map_name,
            round_count=dataset.match.round_count,
            complete_round_count=dataset.match.complete_round_count,
            incomplete_round_count=dataset.match.incomplete_round_count,
            canonical_schema_version=dataset.schema_version,
            normalization_rule_version=dataset.normalization_metadata.normalization_rule_version,
        )
        mismatches = list(_fact_mismatches(case.expected, observed))
        if case.expected_parse_status is ExpectedParseStatus.REJECTED:
            mismatches.append("expected_rejection_but_parse_succeeded")
        if (
            case.expected_parse_status is ExpectedParseStatus.SUCCESS
            and dataset.validation_report.has_fatal_errors
        ):
            mismatches.append("fatal_validation_errors")
        return GoldenCaseRunResult(
            case_id=case.case_id,
            status=(CorpusCaseRunStatus.FAILED if mismatches else CorpusCaseRunStatus.PASSED),
            expected_parse_status=case.expected_parse_status,
            observed=observed,
            mismatches=tuple(sorted(mismatches)),
        )


def _fact_mismatches(
    expected: ExpectedMatchFacts,
    observed: ExpectedMatchFacts,
) -> tuple[str, ...]:
    expected_values = expected.model_dump()
    observed_values = observed.model_dump()
    return tuple(
        sorted(
            key
            for key, value in expected_values.items()
            if value is not None and observed_values[key] != value
        )
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = ["CanonicalNormalizer", "GoldenCorpusRunner"]
