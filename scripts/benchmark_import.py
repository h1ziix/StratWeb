"""Measure real artifact replay into a separate database, including Spatial writes."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from threading import Event
from time import perf_counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--demo", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-wheel", type=Path)
    args = parser.parse_args()
    baseline_directory = None
    if args.baseline_wheel is not None:
        baseline_directory = tempfile.TemporaryDirectory(prefix="stratweb-import-baseline-")
        with zipfile.ZipFile(args.baseline_wheel) as archive:
            archive.extractall(baseline_directory.name)
        sys.path.insert(0, baseline_directory.name)

    from stratweb.adapters.persistence import (
        DuckDBAnalyticsRepository,
        DuckDBEconomyRepository,
        DuckDBMatchRepository,
        DuckDBRoundFeatureRepository,
        DuckDBSpatialRepository,
        DuckDBTemporalRepository,
        DuckDBZoneAssignmentRepository,
    )
    from stratweb.application.analytics import ComputeMatchAnalyticsService
    from stratweb.application.economy import ComputeEconomyService
    from stratweb.application.import_worker import (
        ParserWorkerRunner,
        WorkerEconomyExtractor,
        WorkerSpatialExtractor,
    )
    from stratweb.application.persistence import ImportCanonicalMatchService
    from stratweb.application.round_features import ComputeRoundFeaturesService
    from stratweb.application.spatial import ComputeSpatialStateService
    from stratweb.application.temporal import ComputeTemporalStateService
    from stratweb.application.zone_assignments import ComputeZoneAssignmentsService

    if args.database.exists():
        parser.error("benchmark requires a new database; it never replaces existing data")
    runner = ParserWorkerRunner(
        args.artifacts,
        timeout_seconds=1800,
        memory_limit_bytes=4 * 1024**3,
        minimum_free_disk_bytes=0,
        cancel_grace_seconds=5,
        cancel_event=Event(),
    )
    times: dict[str, object] = {}

    def measured(name: str, operation: object) -> object:
        started = perf_counter()
        try:
            return operation()  # type: ignore[operator]
        finally:
            times[name] = perf_counter() - started
            print(name, times[name], flush=True)
            args.output.write_text(json.dumps(times, indent=2), encoding="utf-8")

    matches = DuckDBMatchRepository(args.database)
    economy = DuckDBEconomyRepository(args.database)
    analytics = DuckDBAnalyticsRepository(args.database)
    temporal = DuckDBTemporalRepository(args.database)
    spatial = DuckDBSpatialRepository(args.database)
    zones = DuckDBZoneAssignmentRepository(args.database)
    original_save = spatial.save_spatial

    def save(state: object, *, replace: bool = False) -> object:
        return measured("spatial_save", lambda: original_save(state, replace=replace))

    spatial.save_spatial = save  # type: ignore[method-assign,assignment]
    dataset = measured("canonicalizing", lambda: runner.canonicalize(args.demo, args.sha256))
    match_id = dataset.match.match_id
    measured("importing", lambda: ImportCanonicalMatchService(matches).import_dataset(dataset))
    measured(
        "economy",
        lambda: ComputeEconomyService(matches, economy, WorkerEconomyExtractor(runner)).compute(
            match_id, args.demo
        ),
    )
    measured(
        "analytics", lambda: ComputeMatchAnalyticsService(matches, analytics).compute(match_id)
    )
    measured(
        "temporal",
        lambda: ComputeTemporalStateService(
            matches, temporal, analytics_repository=analytics
        ).compute(match_id),
    )
    result = measured(
        "spatial",
        lambda: ComputeSpatialStateService(
            matches, temporal, spatial, WorkerSpatialExtractor(runner)
        ).compute(match_id, args.demo),
    )
    measured(
        "zones",
        lambda: ComputeZoneAssignmentsService(spatial, zones).compute(
            match_id, spatial_run_id=result.spatial_run_id
        ),
    )
    measured(
        "features",
        lambda: ComputeRoundFeaturesService(
            matches,
            analytics,
            temporal,
            spatial,
            zones,
            DuckDBRoundFeatureRepository(args.database),
            economy_repository=economy,
        ).compute(match_id),
    )
    times["row_counts"] = result.row_counts
    times["match_id"] = str(match_id)
    args.output.write_text(json.dumps(times, indent=2), encoding="utf-8")
    matches.close()
    if baseline_directory is not None:
        baseline_directory.cleanup()


if __name__ == "__main__":
    main()
