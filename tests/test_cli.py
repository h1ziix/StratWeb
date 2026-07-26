from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from stratweb import cli
from stratweb.application.canonical_models import (
    CanonicalMatch,
    CanonicalMatchDataset,
    CapabilityCoverageStatus,
    NormalizationMetadata,
    ResultCapabilities,
    ResultCapability,
    ValidationReport,
    ValidationSeverity,
)
from stratweb.application.inspection_models import DemoInspectionReport
from stratweb.exceptions import DemoFileNotFoundError


class FakeService:
    def __init__(
        self,
        report: DemoInspectionReport | None = None,
        error: Exception | None = None,
    ) -> None:
        self.report = report
        self.error = error
        self.calls = 0

    def inspect(self, _path: Path) -> DemoInspectionReport:
        self.calls += 1
        if self.error:
            raise self.error
        assert self.report is not None
        return self.report


class FakeNormalizationService:
    def __init__(self, dataset: CanonicalMatchDataset) -> None:
        self.dataset = dataset

    def normalize(self, _path: Path) -> CanonicalMatchDataset:
        return self.dataset


def _canonical_dataset() -> CanonicalMatchDataset:
    match_id = UUID("00000000-0000-0000-0000-000000000001")
    return CanonicalMatchDataset(
        dataset_fingerprint="a" * 64,
        match=CanonicalMatch(
            match_id=match_id,
            demo_file_id=UUID("00000000-0000-0000-0000-000000000002"),
            map_name="de_mirage",
            round_count=0,
            complete_round_count=0,
            incomplete_round_count=0,
            round_count_candidates={},
        ),
        teams=(),
        players=(),
        player_team_memberships=(),
        rounds=(),
        kills=(),
        damages=(),
        shots=(),
        grenades=(),
        bomb_events=(),
        validation_report=ValidationReport(
            is_valid=True,
            has_fatal_errors=False,
            fatal_error_count=0,
            issue_counts={severity: 0 for severity in ValidationSeverity},
            unassigned_event_count=0,
            unknown_player_count=0,
            incomplete_round_count=0,
            issues=(),
        ),
        normalization_metadata=NormalizationMetadata(
            parser_name="demoparser2",
            parser_version="0.41.4",
            normalization_config_hash="b" * 64,
            source_demo_sha256="c" * 64,
            source_event_counts={},
            selected_event_aliases={},
            result_capabilities=ResultCapabilities(
                round_winner=ResultCapability(
                    status=CapabilityCoverageStatus.NOT_APPLICABLE,
                    source_events_checked=(),
                    detected_fields=(),
                    authoritative_source_found=False,
                    total_round_count=0,
                    rounds_available=0,
                    rounds_missing=0,
                    rounds_unresolved=0,
                ),
                round_score=ResultCapability(
                    status=CapabilityCoverageStatus.NOT_APPLICABLE,
                    source_events_checked=(),
                    detected_fields=(),
                    authoritative_source_found=False,
                    total_round_count=0,
                    rounds_available=0,
                    rounds_missing=0,
                    rounds_unresolved=0,
                ),
                round_end_reason=ResultCapability(
                    status=CapabilityCoverageStatus.NOT_APPLICABLE,
                    source_events_checked=(),
                    detected_fields=(),
                    authoritative_source_found=False,
                    total_round_count=0,
                    rounds_available=0,
                    rounds_missing=0,
                    rounds_unresolved=0,
                ),
            ),
        ),
    )


def test_cli_prints_valid_json_and_returns_zero(
    monkeypatch: Any,
    capsys: Any,
    fake_demo_path: Path,
    inspection_report: DemoInspectionReport,
) -> None:
    service = FakeService(inspection_report)
    monkeypatch.setattr(cli, "_build_service", lambda: service)

    exit_code = cli.main(["inspect", str(fake_demo_path), "--pretty"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["schema_version"] == "1.1.0"
    assert captured.err == ""


def test_cli_does_not_overwrite_output_without_force(
    monkeypatch: Any,
    capsys: Any,
    fake_demo_path: Path,
    inspection_report: DemoInspectionReport,
    tmp_path: Path,
) -> None:
    service = FakeService(inspection_report)
    monkeypatch.setattr(cli, "_build_service", lambda: service)
    output = tmp_path / "report.json"
    output.write_text("keep-me", encoding="utf-8")

    exit_code = cli.main(["inspect", str(fake_demo_path), "--output", str(output)])
    captured = capsys.readouterr()

    assert exit_code == 7
    assert service.calls == 0
    assert output.read_text(encoding="utf-8") == "keep-me"
    assert captured.out == ""
    assert "--force" in captured.err


def test_cli_force_writes_output(
    monkeypatch: Any,
    capsys: Any,
    fake_demo_path: Path,
    inspection_report: DemoInspectionReport,
    tmp_path: Path,
) -> None:
    service = FakeService(inspection_report)
    monkeypatch.setattr(cli, "_build_service", lambda: service)
    output = tmp_path / "report.json"
    output.write_text("replace-me", encoding="utf-8")

    exit_code = cli.main(["inspect", str(fake_demo_path), "--output", str(output), "--force"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "success"
    assert json.loads(captured.out)["status"] == "success"


def test_cli_returns_typed_exit_code_and_stderr(
    monkeypatch: Any,
    capsys: Any,
    fake_demo_path: Path,
) -> None:
    service = FakeService(error=DemoFileNotFoundError("missing"))
    monkeypatch.setattr(cli, "_build_service", lambda: service)

    exit_code = cli.main(["inspect", str(fake_demo_path)])
    captured = capsys.readouterr()

    assert exit_code == 3
    assert captured.out == ""
    assert "demo_file_not_found" in captured.err
    assert "Traceback" not in captured.err


def test_normalize_cli_summary_is_compact_json(
    monkeypatch: Any,
    capsys: Any,
    fake_demo_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "_build_normalization_service",
        lambda: FakeNormalizationService(_canonical_dataset()),
    )

    exit_code = cli.main(["normalize", str(fake_demo_path), "--summary-only", "--pretty"])
    captured = capsys.readouterr()
    result = json.loads(captured.out)

    assert exit_code == 0
    assert result["map_name"] == "de_mirage"
    assert result["dataset_fingerprint"] == "a" * 64
    assert "normalization_metadata" not in result
    assert captured.err == ""


def test_normalize_cli_warns_for_full_stdout(
    monkeypatch: Any,
    capsys: Any,
    fake_demo_path: Path,
) -> None:
    monkeypatch.setattr(
        cli,
        "_build_normalization_service",
        lambda: FakeNormalizationService(_canonical_dataset()),
    )

    exit_code = cli.main(["normalize", str(fake_demo_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(captured.out)["schema_version"] == "1.1.0"
    assert "may be large" in captured.err
