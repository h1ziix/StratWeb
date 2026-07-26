from __future__ import annotations

import os
from pathlib import Path

import pytest

from stratweb.adapters.parsers import Demoparser2Adapter, Demoparser2SpatialExtractor
from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
)
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.persistence import ImportCanonicalMatchService
from stratweb.application.spatial import ComputeSpatialStateService, SpatialQueryService
from stratweb.application.temporal import ComputeTemporalStateService


@pytest.mark.integration
def test_faceit_full_spatial_pipeline(tmp_path: Path) -> None:
    configured_path = os.environ.get("STRATWEB_TEST_DEMO")
    if not configured_path:
        pytest.skip("STRATWEB_TEST_DEMO is not set")
    demo = Path(configured_path)
    dataset = CanonicalizationService(Demoparser2Adapter()).normalize(demo)
    database = tmp_path / "faceit-spatial.duckdb"
    matches = DuckDBMatchRepository(database)
    temporal = DuckDBTemporalRepository(database)
    spatial = DuckDBSpatialRepository(database)
    ImportCanonicalMatchService(matches).import_dataset(dataset, source_original_name=demo.name)
    temporal_result = ComputeTemporalStateService(matches, temporal).compute(dataset.match.match_id)

    result = ComputeSpatialStateService(
        matches, temporal, spatial, Demoparser2SpatialExtractor()
    ).compute(dataset.match.match_id, demo)
    query = SpatialQueryService(spatial)
    snapshots = query.list_snapshots(dataset.match.match_id, limit=5000)

    assert result.temporal_run_id == temporal_result.temporal_run_id
    assert result.summary.rounds == len(dataset.rounds)
    assert result.summary.requested_ticks > 0
    assert result.summary.snapshots > 0
    assert snapshots
    assert all(item.temporal_run_id == temporal_result.temporal_run_id for item in snapshots)
    assert any(item.x is not None for item in snapshots)
    assert any(item.yaw is not None and item.pitch is not None for item in snapshots)
    assert result.capabilities.sampling_frequency.covered == result.summary.requested_ticks
