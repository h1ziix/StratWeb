from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import DuckDBMatchRepository, DuckDBTeamNameRepository
from stratweb.application.import_jobs import LocalImportJobManager
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
    assert "Загрузить демки соперника" in empty.text
    assert 'action="/api/import-batches"' in empty.text
    assert "Выбрать папку" in empty.text

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
    assert "Главное — в одном месте" in overview.text
    assert "Выберите, что хотите посмотреть" in overview.text
    assert "Настройки и служебные данные" in overview.text
    assert "Технические сведения" in overview.text
    assert "/static/css/match-hub.css?v=" in overview.text
    assert 'class="match-nav-more"' in overview.text
    assert '<details class="match-hub-service product-disclosure" open>' not in overview.text
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


def test_bulk_upload_groups_multiple_files_and_zip_in_one_opponent_pool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "bulk.duckdb"
    DuckDBMatchRepository(database).initialize()
    monkeypatch.setattr(LocalImportJobManager, "_schedule", lambda *_args: None)
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("practice/day-one/third.dem", b"PBDEMS2third")
        bundle.writestr("notes.txt", b"ignored")
    application = FastAPI()
    application.include_router(
        product_router(database, max_queue_size=10, minimum_free_disk_bytes=0)
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/import-batches",
            data={"pool_name": "Practice vs Falcons", "opponent_profile_id": ""},
            files=[
                ("uploads", ("first.dem", b"PBDEMS2first", "application/octet-stream")),
                (
                    "folder_demos",
                    ("folder/second.dem", b"PBDEMS2second", "application/octet-stream"),
                ),
                ("uploads", ("practice.zip", archive.getvalue(), "application/zip")),
            ],
            headers={"Accept": "application/json"},
        )
        batch_page = client.get(f"/ui/import-batches/{response.json()['batch']['batch_id']}")

    assert response.status_code == 202
    payload = response.json()
    assert payload["total_count"] == 3
    assert payload["queued_count"] == 3
    assert payload["rejected_count"] == 0
    assert payload["batch"]["display_name"] == "Practice vs Falcons"
    assert batch_page.status_code == 200
    assert "Тренировочный пул" in batch_page.text
    assert "Practice vs Falcons" in batch_page.text
    assert "third.dem" in batch_page.text
    assert sorted(entry["item"]["original_name"] for entry in payload["items"]) == [
        "first.dem",
        "second.dem",
        "third.dem",
    ]
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM import_batches").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM import_batch_items").fetchone() == (3,)
        assert connection.execute("SELECT count(*) FROM opponent_profiles").fetchone() == (1,)
    retained = tuple((tmp_path / "uploads").glob("*"))
    assert len(retained) == 3
    assert all(
        path.suffix == ".dem" and path.name not in {"first.dem", "second.dem"} for path in retained
    )


def test_bulk_upload_isolates_invalid_demo_and_blocks_zip_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "bulk-partial.duckdb"
    DuckDBMatchRepository(database).initialize()
    monkeypatch.setattr(LocalImportJobManager, "_schedule", lambda *_args: None)
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("../../outside.dem", b"PBDEMS2safe")
        bundle.writestr("broken.dem", b"not-a-demo")
    application = FastAPI()
    application.include_router(
        product_router(database, max_queue_size=10, minimum_free_disk_bytes=0)
    )

    with TestClient(application) as client:
        response = client.post(
            "/api/import-batches",
            data={"pool_name": "Safe archive"},
            files={"uploads": ("bundle.zip", archive.getvalue(), "application/zip")},
            headers={"Accept": "application/json"},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["queued_count"] == 1
    assert payload["rejected_count"] == 1
    assert {entry["item"]["original_name"] for entry in payload["items"]} == {
        "outside.dem",
        "broken.dem",
    }
    assert not (tmp_path.parent / "outside.dem").exists()


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
