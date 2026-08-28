"""Isolated demoparser2 worker boundary for durable local imports."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypeVar

from pydantic import BaseModel

from stratweb.application.canonical_models import (
    NORMALIZATION_RULE_VERSION,
    CanonicalMatchDataset,
)
from stratweb.economy.models import EconomyExtraction
from stratweb.exceptions import (
    ImportDiskSpaceError,
    ImportWorkerCancelledError,
    ImportWorkerError,
    ImportWorkerMemoryError,
    ImportWorkerTimeoutError,
)
from stratweb.spatial.models import SpatialExtraction

WORKER_VERSION = "2.0"
ARTIFACT_VERSION = "1"
_ModelT = TypeVar("_ModelT", bound=BaseModel)


class ParserWorkerRunner:
    """Run native parsing outside the web process and validate atomic artifacts."""

    def __init__(
        self,
        artifact_directory: Path,
        *,
        timeout_seconds: int,
        memory_limit_bytes: int,
        minimum_free_disk_bytes: int,
        cancel_grace_seconds: float,
        cancel_event: Event,
        on_pid: Callable[[int | None], None] | None = None,
        on_peak_memory: Callable[[int], None] | None = None,
    ) -> None:
        self._directory = artifact_directory.resolve()
        self._timeout = timeout_seconds
        self._memory_limit = memory_limit_bytes
        self._minimum_free_disk = minimum_free_disk_bytes
        self._cancel_grace = cancel_grace_seconds
        self._cancel_event = cancel_event
        self._on_pid = on_pid or (lambda _pid: None)
        self._on_peak_memory = on_peak_memory or (lambda _value: None)

    def canonicalize(self, demo_path: Path, expected_sha256: str) -> CanonicalMatchDataset:
        result = self._invoke(
            "canonical",
            demo_path,
            CanonicalMatchDataset,
            expected_sha256=expected_sha256,
        )
        if result.normalization_metadata.source_demo_sha256 != expected_sha256:
            raise ImportWorkerError("Canonical artifact does not match the uploaded demo hash.")
        return result

    def economy(
        self, demo_path: Path, ticks: tuple[int, ...], expected_sha256: str
    ) -> EconomyExtraction:
        return self._invoke(
            "economy",
            demo_path,
            EconomyExtraction,
            expected_sha256=expected_sha256,
            ticks=ticks,
        )

    def spatial(
        self, demo_path: Path, ticks: tuple[int, ...], expected_sha256: str
    ) -> SpatialExtraction:
        return self._invoke(
            "spatial",
            demo_path,
            SpatialExtraction,
            expected_sha256=expected_sha256,
            ticks=ticks,
        )

    def _invoke(
        self,
        mode: str,
        demo_path: Path,
        model_type: type[_ModelT],
        *,
        expected_sha256: str,
        ticks: tuple[int, ...] = (),
    ) -> _ModelT:
        self._check_cancelled()
        self._check_disk_space()
        self._directory.mkdir(parents=True, exist_ok=True)
        artifact = self._directory / f"{mode}.json"
        cached = _load_artifact(artifact, model_type)
        if cached is not None and _artifact_matches(cached, expected_sha256, ticks):
            return cached

        request = self._directory / f"{mode}.request.json"
        request.write_text(
            json.dumps(
                {
                    "artifact_version": ARTIFACT_VERSION,
                    "mode": mode,
                    "demo_path": str(demo_path.resolve()),
                    "output_path": str(artifact),
                    "expected_sha256": expected_sha256,
                    "ticks": ticks,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        stderr_path = self._directory / f"{mode}.stderr.log"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with stderr_path.open("wb") as stderr_stream:
            process = subprocess.Popen(
                [sys.executable, "-m", "stratweb.worker_cli", str(request)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_stream,
                creationflags=creationflags,
            )
            self._on_pid(process.pid)
            started = time.monotonic()
            peak = 0
            try:
                while process.poll() is None:
                    if self._cancel_event.wait(0.1):
                        self._stop(process)
                        raise ImportWorkerCancelledError("Import cancelled by the user.")
                    if time.monotonic() - started > self._timeout:
                        self._stop(process)
                        raise ImportWorkerTimeoutError(
                            f"Parser worker exceeded the {self._timeout}s time limit."
                        )
                    memory = _process_memory_bytes(process.pid)
                    if memory is not None:
                        peak = max(peak, memory)
                        if memory > self._memory_limit:
                            self._stop(process)
                            raise ImportWorkerMemoryError(
                                "Parser worker exceeded its memory limit."
                            )
            finally:
                self._on_pid(None)
                if peak:
                    self._on_peak_memory(peak)
        if process.returncode != 0:
            details = _bounded_text(stderr_path, 400)
            raise ImportWorkerError(details or f"Parser worker exited with {process.returncode}.")
        parsed = _load_artifact(artifact, model_type)
        if parsed is None or not _artifact_matches(parsed, expected_sha256, ticks):
            raise ImportWorkerError("Parser worker produced an invalid or mismatched artifact.")
        return parsed

    def _stop(self, process: subprocess.Popen[bytes]) -> None:
        process.terminate()
        try:
            process.wait(timeout=self._cancel_grace)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise ImportWorkerCancelledError("Import cancelled by the user.")

    def _check_disk_space(self) -> None:
        probe = self._directory
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        free = shutil.disk_usage(probe).free
        if free < self._minimum_free_disk:
            raise ImportDiskSpaceError(
                f"Import paused: only {free} bytes are free on the data volume."
            )


class WorkerEconomyExtractor:
    def __init__(self, runner: ParserWorkerRunner) -> None:
        self._runner = runner

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> EconomyExtraction:
        return self._runner.economy(demo_path, ticks, expected_sha256)


class WorkerSpatialExtractor:
    def __init__(self, runner: ParserWorkerRunner) -> None:
        self._runner = runner

    def extract(
        self, demo_path: Path, ticks: tuple[int, ...], *, expected_sha256: str
    ) -> SpatialExtraction:
        return self._runner.spatial(demo_path, ticks, expected_sha256)


def _load_artifact(path: Path, model_type: type[_ModelT]) -> _ModelT | None:
    if not path.is_file():
        return None
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _artifact_matches(model: BaseModel, sha256: str, ticks: tuple[int, ...]) -> bool:
    source_sha = getattr(model, "source_demo_sha256", None)
    if source_sha is None:
        metadata = getattr(model, "normalization_metadata", None)
        source_sha = getattr(metadata, "source_demo_sha256", None)
    if source_sha != sha256:
        return False
    metadata = getattr(model, "normalization_metadata", None)
    if (
        metadata is not None
        and getattr(metadata, "normalization_rule_version", None) != NORMALIZATION_RULE_VERSION
    ):
        return False
    requested = getattr(model, "requested_ticks", None)
    return requested is None or tuple(requested) == ticks


def _bounded_text(path: Path, limit: int) -> str:
    try:
        value = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return value[-limit:]


def _process_memory_bytes(pid: int) -> int | None:
    if os.name == "nt":
        return _windows_process_memory_bytes(pid)
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="ascii")
        line = next(item for item in status.splitlines() if item.startswith("VmRSS:"))
        return int(line.split()[1]) * 1024
    except (OSError, StopIteration, ValueError):
        return None


def _windows_process_memory_bytes(pid: int) -> int | None:
    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)
    if not handle:
        return None
    try:
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    finally:
        kernel32.CloseHandle(handle)


__all__ = [
    "ARTIFACT_VERSION",
    "ParserWorkerRunner",
    "WORKER_VERSION",
    "WorkerEconomyExtractor",
    "WorkerSpatialExtractor",
]
