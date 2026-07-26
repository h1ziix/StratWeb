from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratweb.adapters.parsers import Demoparser2Adapter
from stratweb.application.inspection import DemoInspectionService
from stratweb.application.inspection_models import DemoInspectionReport


@pytest.mark.integration
def test_local_demo_inspection_from_environment() -> None:
    configured_path = os.environ.get("STRATWEB_TEST_DEMO")
    if not configured_path:
        pytest.skip("STRATWEB_TEST_DEMO is not set")

    report = DemoInspectionService(Demoparser2Adapter()).inspect(Path(configured_path))
    serialized = report.model_dump_json()

    assert serialized
    assert DemoInspectionReport.model_validate_json(serialized) == report
    assert set(report.canonical_events) == {"CanonicalRoundStart", "CanonicalRoundEnd"}
    has_round_counter = any(
        event.row_count > 0 and "total_rounds_played" in event.columns
        for event in report.events.values()
    )
    if has_round_counter:
        assert report.match.estimated_round_count is not None
