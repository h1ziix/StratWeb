from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stratweb.adapters.persistence import (
    DuckDBMatchRepository,
    DuckDBTelestratorRepository,
)
from stratweb.application.telestrator import (
    NormalizedPoint,
    TelestratorAnnotation,
    TelestratorBoardUpdate,
    TelestratorConflictError,
    TelestratorTool,
)
from stratweb.main import create_app


def _arrow() -> TelestratorAnnotation:
    return TelestratorAnnotation(
        annotation_id=uuid4(),
        tool=TelestratorTool.ARROW,
        points=(NormalizedPoint(x=0.1, y=0.2), NormalizedPoint(x=0.8, y=0.7)),
        color="#63f2cc",
        width=5,
    )


def test_annotation_geometry_is_strict_and_does_not_guess() -> None:
    with pytest.raises(ValidationError):
        TelestratorAnnotation(
            annotation_id=uuid4(),
            tool=TelestratorTool.TEXT,
            points=(NormalizedPoint(x=0.5, y=0.5),),
            color="#ffffff",
            width=4,
            text=None,
        )
    with pytest.raises(ValidationError):
        NormalizedPoint(x=1.1, y=0.5)


def test_board_round_trip_revision_conflict_and_match_cascade(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "telestrator.duckdb"
    dataset = canonical_dataset_factory("telestrator-round-trip")
    matches = DuckDBMatchRepository(database)
    matches.save_match(dataset)
    repository = DuckDBTelestratorRepository(database)

    empty = repository.get(dataset.match.match_id, 1)
    assert empty.revision == 0
    assert empty.annotations == ()

    stored = repository.save(
        dataset.match.match_id,
        1,
        TelestratorBoardUpdate(expected_revision=0, annotations=(_arrow(),)),
    )
    assert stored.revision == 1
    assert repository.get(dataset.match.match_id, 1) == stored
    with pytest.raises(TelestratorConflictError):
        repository.save(
            dataset.match.match_id,
            1,
            TelestratorBoardUpdate(expected_revision=0, annotations=()),
        )

    assert matches.delete_match(dataset.match.match_id) is True
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM telestrator_boards").fetchone() == (0,)


def test_telestrator_api_load_save_and_conflict(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "telestrator-api.duckdb"
    dataset = canonical_dataset_factory("telestrator-api")
    DuckDBMatchRepository(database).save_match(dataset)
    match_id = dataset.match.match_id

    with TestClient(create_app(database)) as client:
        empty = client.get(f"/api/matches/{match_id}/rounds/1/telestrator")
        assert empty.status_code == 200
        assert empty.json()["revision"] == 0
        assert client.get(f"/api/matches/{match_id}/rounds/0/telestrator").status_code == 422

        payload = {"expected_revision": 0, "annotations": [_arrow().model_dump(mode="json")]}
        saved = client.put(f"/api/matches/{match_id}/rounds/1/telestrator", json=payload)
        assert saved.status_code == 200
        assert saved.json()["revision"] == 1
        conflict = client.put(f"/api/matches/{match_id}/rounds/1/telestrator", json=payload)
        assert conflict.status_code == 409


def test_spatial_template_contains_compact_telestrator_controls() -> None:
    template = (
        Path(__file__).parents[1]
        / "src"
        / "stratweb"
        / "web"
        / "templates"
        / "spatial"
        / "explorer.html"
    ).read_text(encoding="utf-8")

    assert 'id="telestratorToggle"' in template
    assert 'id="telestratorLayer"' in template
    assert "js/telestrator.js" in template
    assert "Заметки тренера, не игровые доказательства" in template
