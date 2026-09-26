"""Reproducible HTTP read benchmark; SQL timing excludes Python model construction."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
from unittest.mock import patch
from zipfile import ZipFile

import duckdb
from fastapi.testclient import TestClient

# A retained wheel can reproduce the baseline without changing the environment.
_bootstrap = argparse.ArgumentParser(add_help=False)
_bootstrap.add_argument("--baseline-wheel", type=Path)
_bootstrap_args, _ = _bootstrap.parse_known_args()
_baseline_directory = None
if _bootstrap_args.baseline_wheel is not None:
    _baseline_directory = TemporaryDirectory(prefix="stratweb-baseline-")
    with ZipFile(_bootstrap_args.baseline_wheel) as _wheel:
        _wheel.extractall(_baseline_directory.name)
    sys.path.insert(0, _baseline_directory.name)

_test_directory = Path(__file__).resolve().parents[1] / "tests"
sys.path.insert(0, str(_test_directory))
# conftest's pool cleanup fixture is new in 0.31.3; load only the baseline-compatible
# fixture source when testing an older wheel.
if _baseline_directory is None:
    from conftest import canonical_dataset_factory
else:
    _fixture_source = (_test_directory / "conftest.py").read_text(encoding="utf-8")
    _fixture_source = _fixture_source.replace(
        "from stratweb.adapters.persistence._connections import close_database_connections", ""
    )
    _fixture_source = _fixture_source.replace("    close_database_connections()", "    pass")
    _fixture_namespace: dict[str, Any] = {}
    exec(compile(_fixture_source, str(_test_directory / "conftest.py"), "exec"), _fixture_namespace)
    canonical_dataset_factory = _fixture_namespace["canonical_dataset_factory"]

from test_spatial_queries import _fixture  # noqa: E402

from stratweb import __version__  # noqa: E402
from stratweb.adapters.persistence import DuckDBMatchRepository  # noqa: E402
from stratweb.main import create_app  # noqa: E402


class TimedConnection:
    def __init__(self, raw: Any, metrics: dict[str, Any]) -> None:
        self.raw = raw
        self.metrics = metrics

    def __enter__(self) -> TimedConnection:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        target = getattr(self.raw, name)
        if name not in {"execute", "executemany", "fetchall", "fetchone", "fetchmany", "pl"}:
            return target

        def timed(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            try:
                result = target(*args, **kwargs)
                return self if result is self.raw else result
            finally:
                self.metrics["sql_ms"] += (perf_counter() - started) * 1000
                if name in {"execute", "executemany"}:
                    self.metrics["statements"] += 1

        return timed

    def close(self) -> None:
        self.raw.close()
        self.metrics["closes"] += 1


def close_pool() -> None:
    try:
        from stratweb.adapters.persistence._connections import close_database_connections
    except ImportError:
        return
    close_database_connections()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--baseline-wheel", type=Path)
    args = parser.parse_args()
    metrics: dict[str, Any] = {}
    original = duckdb.connect

    def connect(*positional: Any, **kwargs: Any) -> TimedConnection:
        started = perf_counter()
        raw = original(*positional, **kwargs)
        metrics["connect_ms"] += (perf_counter() - started) * 1000
        metrics["connections"] += 1
        return TimedConnection(raw, metrics)

    report: dict[str, Any] = {
        "fixture": "8 matches; 2 rounds; analytics/temporal/spatial/projectiles on target",
        "runs": args.runs,
        "version": __version__,
        "python": sys.version,
        "duckdb": duckdb.__version__,
        "measured_at": datetime.now(UTC).isoformat(),
        "dependency_versions": tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["dependencies"],
    }
    with TemporaryDirectory(prefix="stratweb-benchmark-") as directory:
        root = Path(directory)
        factory = canonical_dataset_factory.__wrapped__()
        database, dataset, _, assets, registry = _fixture(root, factory)
        for index in range(7):
            DuckDBMatchRepository(database).save_match(factory(f"benchmark-{index}"))
        close_pool()
        endpoints = {
            "library": "/ui",
            "overview": f"/ui/matches/{dataset.match.match_id}",
            "playback": f"/api/spatial/{dataset.match.match_id}/rounds/1/playback?limit=64",
        }
        try:
            with (
                patch.object(duckdb, "connect", connect),
                TestClient(create_app(database, assets, map_registry=registry)) as client,
            ):
                for name, url in endpoints.items():
                    report[name] = {}
                    for mode in ("cold", "warm"):
                        close_pool()
                        samples = []
                        if mode == "warm":
                            metrics.update(
                                connections=0, closes=0, sql_ms=0.0, connect_ms=0.0, statements=0
                            )
                            assert client.get(url).status_code == 200
                        for _ in range(args.runs):
                            if mode == "cold":
                                close_pool()
                            metrics.update(
                                connections=0, closes=0, sql_ms=0.0, connect_ms=0.0, statements=0
                            )
                            started = perf_counter()
                            response = client.get(url)
                            elapsed = (perf_counter() - started) * 1000
                            assert response.status_code == 200, response.text
                            samples.append({"total_ms": elapsed, **metrics})
                        report[name][mode] = {
                            "median": {
                                key: statistics.median(row[key] for row in samples)
                                for key in samples[0]
                            },
                            "samples": samples,
                        }
        finally:
            close_pool()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                name: {mode: value["median"] for mode, value in report[name].items()}
                for name in endpoints
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
