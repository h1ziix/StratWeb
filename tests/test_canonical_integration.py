from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratweb.adapters.parsers import Demoparser2Adapter
from stratweb.application.canonicalization import CanonicalizationService


@pytest.mark.integration
def test_local_faceit_demo_builds_deterministic_canonical_dataset() -> None:
    configured_path = os.environ.get("STRATWEB_TEST_DEMO")
    if not configured_path:
        pytest.skip("STRATWEB_TEST_DEMO is not set")

    service = CanonicalizationService(Demoparser2Adapter())
    first = service.normalize(Path(configured_path))
    second = service.normalize(Path(configured_path))

    assert first.match.map_name.startswith("de_")
    assert first.match.round_count == len(first.rounds)
    assert first.match.round_count > 0
    assert len(first.players) == 10
    assert len(first.kills) > 0
    assert len(first.damages) > 0
    assert len(first.grenades) > 0
    assert first.validation_report.has_fatal_errors is False
    assert first.dataset_fingerprint
    assert second.dataset_fingerprint == first.dataset_fingerprint
