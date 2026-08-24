from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBTeamNameRepository
from stratweb.application.product import _physical_round_score, _physical_winner_label
from stratweb.application.team_names import TeamNameSource
from stratweb.domain.enums import Side
from stratweb.main import create_app
from stratweb.web.routers import product_router


def test_match_library_empty_and_persisted_match_navigation(
    tmp_path: Path, canonical_dataset_factory: Any
) -> None:
    database = tmp_path / "product.duckdb"
    repository = DuckDBMatchRepository(database)
    repository.initialize()
    with TestClient(create_app(database)) as client:
        empty = client.get("/ui")
    assert empty.status_code == 200
    assert "Библиотека матчей" in empty.text
    assert "Матчи не найдены" in empty.text

    dataset = canonical_dataset_factory("product-library")
    repository.save_match(dataset, source_original_name="faceit.dem")
    with TestClient(create_app(database)) as client:
        library = client.get("/ui")
        search = client.get("/ui?search=faceit.dem&sort=map")
        css = client.get("/static/css/tokens.css")
        overview = client.get(f"/ui/matches/{dataset.match.match_id}")
        diagnostics = client.get(f"/ui/matches/{dataset.match.match_id}/diagnostics")

    assert library.status_code == 200
    assert "faceit.dem" in library.text
    assert str(dataset.match.match_id).split("-")[0] in library.text
    assert f"/ui/matches/{dataset.match.match_id}" in library.text
    assert search.status_code == 200 and "faceit.dem" in search.text
    assert css.status_code == 200 and "--accent" in css.text
    assert overview.status_code == 200
    assert "Обзор матча" in overview.text
    assert "Технические сведения" in overview.text
    assert diagnostics.status_code == 200
    assert "Качество демки" in diagnostics.text
    assert "Разбор готов" in diagnostics.text
    assert "Разбор без технического шума" in diagnostics.text
    assert "Технические детали" in diagnostics.text
    assert "dataset_fingerprint" in diagnostics.text
    assert "Исходные данные JSON" in diagnostics.text
    assert '<details class="developer-details" open>' not in diagnostics.text


def test_manual_faceit_team_label_is_persisted_and_rendered(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "team-names.duckdb"
    repository = DuckDBMatchRepository(database)
    dataset = canonical_dataset_factory("team-names")
    repository.save_match(dataset, source_original_name="faceit.dem")
    team_id = dataset.teams[0].team_id

    with TestClient(create_app(database)) as client:
        response = client.post(
            f"/api/matches/{dataset.match.match_id}/teams/{team_id}/display-name",
            data={
                "display_name": "  team_fizik  ",
                "source_reference": "FACEIT match page",
            },
            headers={"Accept": "application/json"},
        )
        overview = client.get(f"/ui/matches/{dataset.match.match_id}")
        library = client.get("/ui")

    assert response.status_code == 200
    assert response.json()["display_name"] == "team_fizik"
    assert "team_fizik" in overview.text
    assert "Игроки: Alpha" in overview.text
    assert "team_fizik" in library.text
    saved = DuckDBTeamNameRepository(database).list_for_match(dataset.match.match_id)
    assert len(saved) == 1
    assert saved[0].source is TeamNameSource.MANUAL
    assert saved[0].source_reference == "FACEIT match page"


def test_product_ui_remains_readable_while_import_writer_connection_is_open(
    tmp_path: Path,
    canonical_dataset_factory: Any,
) -> None:
    database = tmp_path / "concurrent-import.duckdb"
    repository = DuckDBMatchRepository(database)
    repository.initialize()
    dataset = canonical_dataset_factory("concurrent-import")
    repository.save_match(dataset, source_original_name="existing.dem")
    application = create_app(database)

    with duckdb.connect(str(database), read_only=False) as writer:
        writer.execute("BEGIN TRANSACTION")
        with TestClient(application) as client:
            library = client.get("/ui")
            overview = client.get(f"/ui/matches/{dataset.match.match_id}")
            diagnostics = client.get(f"/ui/matches/{dataset.match.match_id}/diagnostics")
        writer.execute("ROLLBACK")

    assert library.status_code == 200
    assert overview.status_code == 200
    assert diagnostics.status_code == 200


def test_round_strip_keeps_physical_team_order_after_side_switch() -> None:
    team_alpha = uuid4()
    team_bravo = uuid4()
    switched_round = SimpleNamespace(
        t_team_id=team_bravo,
        ct_team_id=team_alpha,
        winner_side=Side.CT,
        score_t_after=3,
        score_ct_after=10,
    )

    assert _physical_round_score(switched_round, (team_alpha, team_bravo)) == "10:3"
    assert (
        _physical_winner_label(
            switched_round,
            {team_alpha: "TeamAlpha", team_bravo: "TeamBravo"},
        )
        == "TeamAlpha · CT"
    )


def test_local_upload_rejects_unsafe_type_and_invalid_demo(
    tmp_path: Path,
) -> None:
    database = tmp_path / "upload.duckdb"
    DuckDBMatchRepository(database).initialize()
    with TestClient(create_app(database)) as client:
        wrong_extension = client.post(
            "/api/import-jobs",
            files={"demo": ("notes.txt", b"PBDEMS2payload", "text/plain")},
            headers={"Accept": "application/json"},
        )
        invalid_signature = client.post(
            "/api/import-jobs",
            files={"demo": ("../../unsafe.dem", b"not-a-demo", "application/octet-stream")},
            headers={"Accept": "application/json"},
        )

    assert wrong_extension.status_code == 415
    assert invalid_signature.status_code == 415
    uploaded = tuple((tmp_path / "uploads").glob("*"))
    assert uploaded == ()


def test_local_upload_enforces_streaming_size_limit(tmp_path: Path) -> None:
    database = tmp_path / "bounded-upload.duckdb"
    DuckDBMatchRepository(database).initialize()
    application = FastAPI()
    application.include_router(product_router(database, max_upload_bytes=8))

    with TestClient(application) as client:
        response = client.post(
            "/api/import-jobs",
            files={"demo": ("large.dem", b"PBDEMS2payload", "application/octet-stream")},
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 413
    assert tuple((tmp_path / "uploads").glob("*")) == ()


def test_local_upload_refuses_low_disk_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "disk-guard.duckdb"
    DuckDBMatchRepository(database).initialize()
    application = FastAPI()
    application.include_router(product_router(database, minimum_free_disk_bytes=100))
    monkeypatch.setattr(
        "stratweb.web.routers.product.disk_usage",
        lambda _path: type("Usage", (), {"free": 50})(),
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/import-jobs",
            files={"demo": ("match.dem", b"PBDEMS2payload", "application/octet-stream")},
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 507
    assert tuple((tmp_path / "uploads").glob("*")) == ()


def test_unexpected_ui_failure_uses_controlled_error_page(tmp_path: Path) -> None:
    application = create_app(tmp_path / "errors.duckdb")

    @application.get("/ui/test-unexpected-error")
    def fail() -> None:
        raise RuntimeError("private implementation detail")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/ui/test-unexpected-error")

    assert response.status_code == 500
    assert "Непредвиденная ошибка сервера" in response.text
    assert "internal_server_error" in response.text
    assert "private implementation detail" not in response.text
