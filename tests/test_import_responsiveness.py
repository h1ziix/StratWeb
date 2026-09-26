from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from time import perf_counter
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBEconomyRepository,
    DuckDBMatchRepository,
    DuckDBRoundFeatureRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.analytics.engine import AnalyticsEngine
from stratweb.application.import_job_models import ImportJobStage
from stratweb.application.import_jobs import LocalImportJobManager
from stratweb.application.import_worker import ParserWorkerRunner
from stratweb.economy.engine import EconomyEngine
from stratweb.economy.models import EconomyExtraction
from stratweb.exceptions import (
    AnalyticsIntegrityError,
    EconomyIntegrityError,
    ImportWorkerCancelledError,
    RoundFeatureIntegrityError,
    SpatialIntegrityError,
    TemporalIntegrityError,
    ZoneAssignmentIntegrityError,
)
from stratweb.features.engine import RoundFeatureEngine
from stratweb.main import create_app
from stratweb.spatial.engine import SpatialEngine
from stratweb.spatial.models import SpatialExtraction, SpatialSourceSample
from stratweb.temporal.engine import TemporalEngine
from stratweb.zones.assignments import ZoneAssignmentEngine


def _fake_parser(monkeypatch: pytest.MonkeyPatch, dataset: Any) -> None:
    monkeypatch.setattr(ParserWorkerRunner, "canonicalize", lambda *_args: dataset)
    monkeypatch.setattr(
        ParserWorkerRunner,
        "economy",
        lambda _self, _path, ticks, sha: EconomyExtraction(
            parser_name="fixture",
            parser_version="1",
            source_demo_sha256=sha,
            requested_ticks=ticks,
            samples=(),
            requested_fields=(),
            source_columns=(),
        ),
    )
    monkeypatch.setattr(
        ParserWorkerRunner,
        "spatial",
        lambda _self, _path, ticks, sha: SpatialExtraction(
            parser_name="fixture",
            parser_version="1",
            source_demo_sha256=sha,
            requested_ticks=ticks,
            source_columns=("tick", "steamid", "X", "Y", "Z"),
            samples=tuple(
                SpatialSourceSample(
                    tick=tick,
                    steam_id=player.steam_id,
                    player_name=player.current_name,
                    x=100.0,
                    y=100.0,
                    z=0.0,
                )
                for tick in ticks
                for player in dataset.players
            ),
        ),
    )


_SAVE_METHODS = (
    (DuckDBEconomyRepository, "save_economy", EconomyIntegrityError),
    (DuckDBAnalyticsRepository, "save_analytics", AnalyticsIntegrityError),
    (DuckDBTemporalRepository, "save_temporal", TemporalIntegrityError),
    (DuckDBSpatialRepository, "save_spatial", SpatialIntegrityError),
    (DuckDBZoneAssignmentRepository, "save_zone_assignments", ZoneAssignmentIntegrityError),
    (DuckDBRoundFeatureRepository, "save_features", RoundFeatureIntegrityError),
)


def test_long_pipeline_pages_progress_locks_and_stale_sources(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    seed = "responsive-pipeline"
    dataset = canonical_dataset_factory(seed)
    database = tmp_path / "matches.duckdb"
    upload = tmp_path / "uploads"
    upload.mkdir()
    demo = upload / "retained.dem"
    demo.write_bytes(seed.encode())
    _fake_parser(monkeypatch, dataset)
    manager = LocalImportJobManager(database, minimum_free_disk_bytes=0)
    # Share the active manager with HTTP endpoints; no independent restart recovery.
    monkeypatch.setattr(
        "stratweb.web.routers.product.LocalImportJobManager", lambda *a, **k: manager
    )
    checkpoints: Queue[tuple[str, Event]] = Queue()
    captured: dict[str, Any] = {}
    metrics: list[dict[str, Any]] = []
    caplog.set_level(logging.DEBUG, logger="stratweb.adapters.persistence.write_coordinator")

    def pause(stage: str) -> None:
        release = Event()
        checkpoints.put((stage, release))
        assert release.wait(15), "Measurement did not release the computation"

    for cls, method, stage in (
        (ParserWorkerRunner, "canonicalize", "canonicalizing"),
        (ParserWorkerRunner, "economy", "economy"),
        (EconomyEngine, "compute", "economy"),
        (AnalyticsEngine, "compute", "analytics"),
        (TemporalEngine, "compute", "temporal"),
        (ParserWorkerRunner, "spatial", "spatial"),
        (SpatialEngine, "compute", "spatial"),
        (ZoneAssignmentEngine, "compute", "zones"),
        (RoundFeatureEngine, "compute", "features"),
    ):
        original = getattr(cls, method)

        def blocked(*args: Any, _original: Any = original, _stage: str = stage, **kw: Any) -> Any:
            pause(_stage)
            return _original(*args, **kw)

        monkeypatch.setattr(cls, method, blocked)

    for cls, method, _error in _SAVE_METHODS:
        original = getattr(cls, method)

        def capture(
            self: Any, state: Any, *, _method: str = method, _original: Any = original, **kw: Any
        ) -> Any:
            captured[_method] = state
            return _original(self, state, **kw)

        monkeypatch.setattr(cls, method, capture)

    with TestClient(create_app(database)) as client:
        job = manager.submit(demo, "retained.dem")
        future = manager._futures[job.job_id]
        for index in range(9):
            stage, release = checkpoints.get(timeout=15)
            try:
                started = perf_counter()
                # Another writer is free throughout extraction/computation.
                acquired = Event()

                def acquire_writer(acquired: Event = acquired) -> None:
                    with manager._write_coordinator.serialized():
                        acquired.set()

                writer = Thread(target=acquire_writer, daemon=True)
                writer.start()
                assert acquired.wait(2), f"Writer held during {stage}"
                writer.join(2)
                latency: dict[str, float] = {}
                # A busy ordinary writer also cannot block cached initialization or reads.
                with manager._write_coordinator.serialized():
                    paths = [
                        "/ui",
                        f"/ui/import-jobs/{job.job_id}",
                        f"/api/import-jobs/{job.job_id}",
                    ]
                    if index:
                        paths.append(f"/ui/matches/{dataset.match.match_id}")
                    for path in paths:
                        before = perf_counter()
                        response = client.get(path)
                        latency[path] = perf_counter() - before
                        assert response.status_code == 200, response.text[:200]
                        if path.startswith("/api/"):
                            assert response.json()["stage"] == stage
                            assert response.json()["progress_percent"] > 0
                # Keep this stage running for >=1s, independent of HTTP duration.
                Event().wait(max(0.0, 1.0 - (perf_counter() - started)))
                metrics.append(
                    {
                        "stage": stage,
                        "pause_seconds": perf_counter() - started,
                        "http_seconds": latency,
                    }
                )
            finally:
                release.set()
        future.result(timeout=15)
        assert manager.get(job.job_id).stage is ImportJobStage.COMPLETE
        assert demo.exists()

    holds = [
        record.args[1]
        for record in caplog.records
        if record.msg.startswith("database_writer")
        and record.threadName.startswith("stratweb-import")
    ]
    report = {
        "scenario": "fixture pipeline with nine >=1s pauses; real DuckDB and HTTP",
        "stages": metrics,
        "worker_lock_hold_seconds": holds,
    }
    output = Path(__file__).resolve().parents[1] / ".runtime/release-check/import-latency.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert holds and max(holds) < 1.0, report

    # Source removal after computation must be rejected by every atomic save.
    matches = DuckDBMatchRepository(database)
    assert matches.delete_match(dataset.match.match_id)
    for cls, method, error in _SAVE_METHODS:
        with pytest.raises(error):
            getattr(cls(database), method)(captured[method])
    assert matches.get_match(dataset.match.match_id) is None


def test_cancel_signal_and_shutdown_do_not_wait_for_status_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload = tmp_path / "uploads"
    upload.mkdir()
    demo = upload / "retained.dem"
    demo.write_bytes(b"PBDEMS2fixture")
    manager = LocalImportJobManager(database, shutdown_timeout_seconds=0.2)
    started, stopped, launch, spawned = Event(), Event(), Event(), Event()
    original_popen = subprocess.Popen
    processes: list[Any] = []

    def popen(_args: Any, **kw: Any) -> Any:
        process = original_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kw)
        processes.append(process)
        spawned.set()
        return process

    monkeypatch.setattr("stratweb.application.import_worker.subprocess.Popen", popen)

    def run(_job: Any, _path: Any, _name: Any, event: Event) -> None:
        started.set()
        assert launch.wait(5)
        runner = ParserWorkerRunner(
            tmp_path / "artifacts",
            timeout_seconds=120,
            memory_limit_bytes=2**32,
            minimum_free_disk_bytes=0,
            cancel_grace_seconds=0.1,
            cancel_event=event,
            on_pid=lambda pid: manager._worker_pid(_job, pid),
            on_peak_memory=lambda peak: manager._peak_memory(_job, peak),
        )
        try:
            runner.canonicalize(_path, "a" * 64)
        except ImportWorkerCancelledError:
            assert processes[0].poll() is not None
            stopped.set()
            manager._mark_cancelled(_job)

    monkeypatch.setattr(manager, "_run", run)
    job = manager.submit(demo, "retained.dem")
    assert started.wait(3)
    future = manager._futures[job.job_id]
    errors: list[BaseException] = []

    def cancel() -> None:
        try:
            manager.cancel(job.job_id)
        except BaseException as exc:
            errors.append(exc)

    with manager._write_coordinator.serialized():
        launch.set()
        assert spawned.wait(3)
        thread = Thread(target=cancel, daemon=True)
        before = perf_counter()
        thread.start()
        assert stopped.wait(1), "Signal was blocked by status persistence"
        signal_seconds = perf_counter() - before
        assert thread.is_alive(), "Cancel status should still be waiting for the writer"
        before = perf_counter()
        manager.shutdown()
        shutdown_seconds = perf_counter() - before
        assert shutdown_seconds < 0.8
        assert demo.exists()
    thread.join(5)
    future.result(timeout=5)
    assert not thread.is_alive()
    assert not errors
    assert manager.get(job.job_id).stage is ImportJobStage.CANCELLED
    output = Path(__file__).resolve().parents[1] / ".runtime/release-check/cancel-latency.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "signal_seconds": signal_seconds,
                "shutdown_seconds": shutdown_seconds,
                "shutdown_budget_seconds": 0.2,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_cancel_while_waiting_for_save_lock_does_not_save(tmp_path: Path) -> None:
    manager = LocalImportJobManager(tmp_path / "jobs.duckdb")
    event, started, finished = Event(), Event(), Event()
    saved: list[bool] = []

    def compute_then_save() -> None:
        started.set()
        with pytest.raises(ImportWorkerCancelledError):
            with manager._database_write(event=event):
                saved.append(True)
        finished.set()

    with manager._write_coordinator.serialized():
        thread = Thread(target=compute_then_save, daemon=True)
        thread.start()
        assert started.wait(1)
        event.set()
        assert finished.wait(1)
    thread.join(2)
    assert saved == []
    manager.shutdown()


def test_schema_gate_excludes_reads_but_allows_concurrent_queries(tmp_path: Path) -> None:
    manager = LocalImportJobManager(tmp_path / "jobs.duckdb")
    coordinator = manager._write_coordinator
    entered, finished = Event(), Event()

    def read() -> None:
        entered.set()
        with coordinator.schema_read():
            finished.set()

    with coordinator.serialized(), coordinator.schema_change():
        thread = Thread(target=read, daemon=True)
        thread.start()
        assert entered.wait(1)
        assert not finished.wait(0.1)
    thread.join(2)
    assert finished.is_set()
    finished.clear()
    with coordinator.schema_read():
        thread = Thread(target=read, daemon=True)
        thread.start()
        assert finished.wait(1)
    thread.join(2)
    manager.shutdown()


def test_shutdown_timeout_does_not_publish_cancellation_before_safe_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "jobs.duckdb"
    upload = tmp_path / "uploads"
    upload.mkdir()
    demo = upload / "retained.dem"
    demo.write_bytes(b"PBDEMS2fixture")
    manager = LocalImportJobManager(database, shutdown_timeout_seconds=0.1)
    entered, release = Event(), Event()

    def compute(job_id: Any, _path: Any, _name: Any, _event: Event) -> None:
        entered.set()
        assert release.wait(5)
        manager._mark_cancelled(job_id)

    monkeypatch.setattr(manager, "_run", compute)
    job = manager.submit(demo, "retained.dem")
    assert entered.wait(3)
    future = manager._futures[job.job_id]
    try:
        manager.shutdown()
        assert not future.done()
        assert manager.get(job.job_id).stage is ImportJobStage.QUEUED
    finally:
        release.set()
    future.result(timeout=5)
    assert manager.get(job.job_id).stage is ImportJobStage.CANCELLED
    assert demo.exists()


@pytest.mark.parametrize(
    "engine, repository, stage",
    [
        (EconomyEngine, DuckDBEconomyRepository, "economy"),
        (AnalyticsEngine, DuckDBAnalyticsRepository, "analytics"),
        (TemporalEngine, DuckDBTemporalRepository, "temporal"),
        (SpatialEngine, DuckDBSpatialRepository, "spatial"),
        (ZoneAssignmentEngine, DuckDBZoneAssignmentRepository, "zones"),
        (RoundFeatureEngine, DuckDBRoundFeatureRepository, "features"),
    ],
)
def test_cancel_during_compute_retains_input_without_saving_current_layer(
    tmp_path: Path,
    canonical_dataset_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    engine: Any,
    repository: Any,
    stage: str,
) -> None:
    seed = "cancel-compute-" + stage
    dataset = canonical_dataset_factory(seed)
    database = tmp_path / "jobs.duckdb"
    upload = tmp_path / "uploads"
    upload.mkdir()
    demo = upload / "retained.dem"
    demo.write_bytes(seed.encode())
    _fake_parser(monkeypatch, dataset)
    manager = LocalImportJobManager(database, minimum_free_disk_bytes=0)
    monkeypatch.setattr(
        "stratweb.web.routers.product.LocalImportJobManager", lambda *a, **k: manager
    )
    entered, release = Event(), Event()
    original = engine.compute

    def compute(*args: Any, **kw: Any) -> Any:
        entered.set()
        assert release.wait(15)
        return original(*args, **kw)

    monkeypatch.setattr(engine, "compute", compute)
    with TestClient(create_app(database)) as client:
        job = manager.submit(demo, "retained.dem")
        future = manager._futures[job.job_id]
        try:
            assert entered.wait(15)
            response = client.post(
                f"/api/import-jobs/{job.job_id}/cancel", headers={"Accept": "application/json"}
            )
            assert response.status_code == 202, response.text
            assert response.json()["stage"] == "cancel_requested"
        finally:
            release.set()
        future.result(timeout=15)
        assert manager.get(job.job_id).stage is ImportJobStage.CANCELLED
        assert demo.exists()
        assert repository(database).get_summary(dataset.match.match_id) is None
