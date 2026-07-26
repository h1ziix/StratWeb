"""Audit authoritative playback continuity and optional local HTTP chunk timings."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from stratweb.adapters.persistence import DuckDBSpatialRepository
from stratweb.application.playback import classify_motion
from stratweb.spatial.models import SpatialSnapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("match_id", type=UUID)
    parser.add_argument("round_number", type=int)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--run-id", type=UUID)
    parser.add_argument("--base-url", help="optional running server, e.g. http://127.0.0.1:8000")
    parser.add_argument("--chunk-limit", type=int, default=64)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="omit the per-authoritative-sample rows from stdout",
    )
    args = parser.parse_args()

    repository = DuckDBSpatialRepository(args.db)
    summary = (
        repository.get_summary_for_run(args.match_id, args.run_id)
        if args.run_id is not None
        else repository.get_summary(args.match_id)
    )
    if summary is None:
        parser.error("compatible Spatial run not found")
    ticks = repository.list_round_ticks(
        args.match_id,
        args.round_number,
        spatial_run_id=summary.spatial_run_id,
    )
    rows: list[SpatialSnapshot] = []
    for offset in range(0, len(ticks), 200):
        rows.extend(
            repository.get_playback_snapshots(
                args.match_id,
                args.round_number,
                ticks[offset : offset + 200],
                spatial_run_id=summary.spatial_run_id,
            )
        )
    by_player: dict[UUID, list[SpatialSnapshot]] = defaultdict(list)
    for row in rows:
        by_player[row.participant_id].append(row)
    classifications: Counter[str] = Counter()
    block_reasons: Counter[str] = Counter()
    tick_gaps: Counter[int] = Counter()
    repeated = 0
    suspicious = 0
    for player_rows in by_player.values():
        ordered = sorted(player_rows, key=lambda item: item.tick)
        for previous, following in zip(ordered, ordered[1:], strict=False):
            transition = classify_motion(previous, following)
            classifications[transition.classification.value] += 1
            if transition.interpolation.reason is not None:
                block_reasons[transition.interpolation.reason.value] += 1
            if transition.tick_gap is not None:
                tick_gaps[transition.tick_gap] += 1
            repeated += int(transition.repeated_identical_sample)
            suspicious += int("suspicious_spatial_jump" in transition.warnings)
    projectiles = repository.get_round_projectiles(
        args.match_id,
        args.round_number,
        spatial_run_id=summary.spatial_run_id,
    )
    projectile_samples = (
        repository.get_playback_projectile_snapshots(
            args.match_id,
            args.round_number,
            ticks[0],
            ticks[-1],
            spatial_run_id=summary.spatial_run_id,
        )
        if ticks
        else ()
    )
    utility_effects = (
        repository.get_playback_utility_effects(
            args.match_id,
            args.round_number,
            ticks[0],
            ticks[-1],
            spatial_run_id=summary.spatial_run_id,
        )
        if ticks
        else ()
    )
    rows_by_tick: dict[int, list[SpatialSnapshot]] = defaultdict(list)
    for row in rows:
        rows_by_tick[row.tick].append(row)
    sample_audit = []
    for index, tick in enumerate(ticks):
        current_rows = rows_by_tick.get(tick, [])
        next_tick = ticks[index + 1] if index + 1 < len(ticks) else None
        next_by_player = {item.participant_id: item for item in rows_by_tick.get(next_tick, [])}
        eligible = sum(
            classify_motion(row, next_by_player.get(row.participant_id)).interpolation.eligible
            for row in current_rows
        )
        reliable = sum(
            row.x is not None
            and row.y is not None
            and row.availability.position.value == "available"
            for row in current_rows
        )
        sample_audit.append(
            {
                "sample_index": index,
                "tick": tick,
                "next_tick": next_tick,
                "tick_gap": next_tick - tick if next_tick is not None else None,
                "player_count": len(current_rows),
                "reliable_position_count": reliable,
                "unavailable_position_count": len(current_rows) - reliable,
                "chunk_identifier": index // args.chunk_limit,
                "chunk_load_duration": None,
                "buffer_depth": None,
                "render_timestamp": None,
                "dropped_visual_frames": None,
                "interpolation_eligible_players": eligible,
            }
        )
    result: dict[str, Any] = {
        "match_id": str(args.match_id),
        "round_number": args.round_number,
        "spatial_run_id": str(summary.spatial_run_id),
        "spatial_schema_version": summary.spatial_schema_version,
        "spatial_rule_version": summary.spatial_rule_version,
        "authoritative_ticks": len(ticks),
        "authoritative_player_samples": len(rows),
        "players": len(by_player),
        "motion_classifications": dict(sorted(classifications.items())),
        "interpolation_block_reasons": dict(sorted(block_reasons.items())),
        "tick_gap_distribution": {str(key): value for key, value in sorted(tick_gaps.items())},
        "repeated_identical_samples": repeated,
        "suspicious_spatial_jumps": suspicious,
        "projectiles": len(projectiles),
        "projectile_samples": len(projectile_samples),
        "utility_effects": len(utility_effects),
        "projectile_capability_fingerprint": (
            summary.projectile_metadata.capability_fingerprint
            if summary.projectile_metadata is not None
            else None
        ),
        "runtime_only_metrics": (
            "buffer depth, render timestamp, dropped frames, FPS, and pending requests "
            "are instrumented in the Diagnostics drawer"
        ),
        "http_chunk_audit": (
            _http_audit(
                args.base_url,
                args.match_id,
                args.round_number,
                summary.spatial_run_id,
                len(ticks),
                args.chunk_limit,
            )
            if args.base_url
            else {"status": "not_requested"}
        ),
    }
    if not args.summary_only:
        result["authoritative_sample_audit"] = sample_audit
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _http_audit(
    base_url: str,
    match_id: UUID,
    round_number: int,
    run_id: UUID,
    total: int,
    limit: int,
) -> dict[str, Any]:
    durations: list[float] = []
    byte_counts: list[int] = []
    errors: list[str] = []
    for start in range(0, total, limit):
        query = urllib.parse.urlencode({"from_index": start, "limit": limit, "run_id": str(run_id)})
        url = (
            f"{base_url.rstrip('/')}/api/spatial/{match_id}/rounds/{round_number}/playback?{query}"
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310
                payload = response.read()
            durations.append(time.perf_counter() - started)
            byte_counts.append(len(payload))
        except Exception as exc:  # pragma: no cover - manual network audit
            errors.append(f"chunk:{start}:{type(exc).__name__}:{exc}")
    return {
        "status": "complete" if not errors else "partial",
        "requests": len(durations) + len(errors),
        "successful_requests": len(durations),
        "mean_seconds": sum(durations) / len(durations) if durations else None,
        "maximum_seconds": max(durations) if durations else None,
        "total_bytes": sum(byte_counts),
        "errors": errors,
    }


if __name__ == "__main__":
    raise SystemExit(main())
