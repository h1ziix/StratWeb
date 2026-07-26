from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from stratweb.application.inspection import compute_sha256, inspect_local_file
from stratweb.application.inspection_models import DemoInspectionReport, InspectionStatus
from stratweb.exceptions import DemoFileNotFoundError


def test_sha256_is_calculated_in_streaming_chunks(tmp_path: Path) -> None:
    payload = b"stratweb-demo" * 10_000
    path = tmp_path / "hash.dem"
    path.write_bytes(payload)

    assert compute_sha256(path, chunk_size=17) == hashlib.sha256(payload).hexdigest()


def test_missing_file_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(DemoFileNotFoundError):
        inspect_local_file(tmp_path / "missing.dem")


def test_inspection_json_matches_versioned_schema(
    inspection_report: DemoInspectionReport,
) -> None:
    serialized = inspection_report.model_dump_json()
    restored = DemoInspectionReport.model_validate_json(serialized)

    assert restored.schema_version == "1.1.0"
    assert restored.status is InspectionStatus.SUCCESS
    assert restored.match.map_name == "de_mirage"
    assert restored.match.estimated_round_count == 2
    assert restored.match.estimated_round_count_source == "max_total_rounds_played"
    assert restored.canonical_events["CanonicalRoundEnd"].count == 2
    assert restored.canonical_events["CanonicalRoundStart"].count == 0
    assert restored.match.player_count == 2
    assert restored.events["player_death"].row_count == 2
    assert restored.events["player_hurt"].available is False
    assert restored.events["player_hurt"].parsed is False
