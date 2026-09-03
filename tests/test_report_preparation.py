from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from stratweb.application.counter_strategy import ComputeCounterStrategiesService
from stratweb.application.findings import ComputeAnalysisFindingsService
from stratweb.application.patterns import ComputeCrossMatchPatternsService
from stratweb.application.report_preparation import (
    PrepareScoutingReportService,
    ReportPreparationUnavailableError,
)
from stratweb.exceptions import PersistenceError


def test_preparation_composes_existing_stages_in_order_without_policy_overrides() -> None:
    patterns = Mock(spec=ComputeCrossMatchPatternsService)
    findings = Mock(spec=ComputeAnalysisFindingsService)
    strategies = Mock(spec=ComputeCounterStrategiesService)
    calls = Mock()
    calls.attach_mock(patterns, "patterns")
    calls.attach_mock(findings, "findings")
    calls.attach_mock(strategies, "strategies")
    patterns.compute.return_value = SimpleNamespace(summary=SimpleNamespace(included_matches=3))
    profile_id = uuid4()

    result = PrepareScoutingReportService(patterns, findings, strategies).prepare(profile_id)

    assert result is strategies.compute.return_value
    assert [call[0] for call in calls.mock_calls] == [
        "patterns.compute",
        "findings.compute",
        "strategies.compute",
    ]
    for stage in (patterns, findings, strategies):
        stage.compute.assert_called_once_with(profile_id)


def test_preparation_stops_when_no_matches_are_ready() -> None:
    patterns = Mock(spec=ComputeCrossMatchPatternsService)
    findings = Mock(spec=ComputeAnalysisFindingsService)
    strategies = Mock(spec=ComputeCounterStrategiesService)
    patterns.compute.return_value = SimpleNamespace(summary=SimpleNamespace(included_matches=0))

    with pytest.raises(ReportPreparationUnavailableError):
        PrepareScoutingReportService(patterns, findings, strategies).prepare(uuid4())

    findings.compute.assert_not_called()
    strategies.compute.assert_not_called()


def test_preparation_does_not_publish_strategy_after_failed_findings() -> None:
    patterns = Mock(spec=ComputeCrossMatchPatternsService)
    findings = Mock(spec=ComputeAnalysisFindingsService)
    strategies = Mock(spec=ComputeCounterStrategiesService)
    patterns.compute.return_value = SimpleNamespace(summary=SimpleNamespace(included_matches=1))
    findings.compute.side_effect = PersistenceError("fixture failure")

    with pytest.raises(PersistenceError, match="fixture failure"):
        PrepareScoutingReportService(patterns, findings, strategies).prepare(uuid4())

    strategies.compute.assert_not_called()
