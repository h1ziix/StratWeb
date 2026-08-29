from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import duckdb
import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBImportJobRepository, DuckDBMatchRepository
from stratweb.application.cs2_demo_bridge import CS2DemoBridgeError, CS2DemoBridgeService
from stratweb.application.import_job_models import ImportJobRecord, ImportJobStage
from stratweb.main import create_app


def test_bridge_prepares_verified_demo_and_exact_commands(
    tmp_path: Path, canonical_dataset_factory: Callable[..., Any]
) -> None:
    database, match_id, destination = _fixture(tmp_path, canonical_dataset_factory)
    service = CS2DemoBridgeService(database, destination)

    first = service.prepare(match_id, 45230)
    second = service.prepare(match_id, 45230)

    assert first.play_command == f'playdemo "StratWeb/stratweb_{match_id}.dem"'
    assert first.seek_command == "demo_gototick 45230; demo_pause"
    assert first.clipboard_text == f"{first.play_command}\n{first.seek_command}"
    assert first.reused_existing_file is False
    assert second.reused_existing_file is True
    assert (destination / f"stratweb_{match_id}.dem").read_bytes() == b"PBDEMS2bridge"


def test_product_endpoint_is_local_mutation_and_returns_copy_payload(
    tmp_path: Path, canonical_dataset_factory: Callable[..., Any]
) -> None:
    database, match_id, destination = _fixture(tmp_path, canonical_dataset_factory)

    with TestClient(create_app(database, cs2_demo_directory=destination)) as client:
        response = client.post(
            f"/api/matches/{match_id}/cs2-demo-command",
            params={"tick": 777},
        )

    assert response.status_code == 200
    assert response.json()["tick"] == 777
    assert response.json()["seek_command"] == "demo_gototick 777; demo_pause"


def test_bridge_rejects_a_retained_demo_that_no_longer_matches_sha256(
    tmp_path: Path, canonical_dataset_factory: Callable[..., Any]
) -> None:
    database, match_id, destination = _fixture(tmp_path, canonical_dataset_factory)
    source = next((database.parent / "uploads").glob("*.dem"))
    source.write_bytes(b"PBDEMS2changed")

    with pytest.raises(CS2DemoBridgeError, match="SHA-256"):
        CS2DemoBridgeService(database, destination).prepare(match_id, 1)


def _fixture(
    tmp_path: Path, canonical_dataset_factory: Callable[..., Any]
) -> tuple[Path, UUID, Path]:
    dataset = canonical_dataset_factory("cs2-bridge")
    database = tmp_path / "bridge.duckdb"
    matches = DuckDBMatchRepository(database)
    matches.save_match(dataset, source_original_name="faceit.dem")
    payload = b"PBDEMS2bridge"
    digest = sha256(payload).hexdigest()
    internal_name = f"{uuid4()}.dem"
    uploads = database.parent / "uploads"
    uploads.mkdir()
    (uploads / internal_name).write_bytes(payload)
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "UPDATE matches SET source_demo_sha256=? WHERE match_id=?",
            [digest, dataset.match.match_id],
        )
    now = datetime.now(UTC)
    job = ImportJobRecord.create(
        job_id=uuid4(),
        original_name="faceit.dem",
        internal_name=internal_name,
        demo_sha256=digest,
        file_size_bytes=len(payload),
        now=now,
    ).model_copy(
        update={
            "stage": ImportJobStage.COMPLETE,
            "match_id": dataset.match.match_id,
            "message": "Ready",
            "progress_percent": 100,
            "completed_at": now,
        }
    )
    DuckDBImportJobRepository(database).create(job)
    destination = tmp_path / "game" / "csgo" / "StratWeb"
    return database, dataset.match.match_id, destination
