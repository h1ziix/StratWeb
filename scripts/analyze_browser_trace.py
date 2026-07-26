"""Summarize Chrome DevTools trace events without loading the whole trace in memory."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def _trace_events(path: Path) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as trace_file:
        buffer = ""
        while '"traceEvents":[' not in buffer:
            chunk = trace_file.read(1024 * 1024)
            if not chunk:
                raise ValueError("traceEvents array not found")
            buffer += chunk
        buffer = buffer.split('"traceEvents":[', maxsplit=1)[1]
        offset = 0
        while True:
            while True:
                while offset < len(buffer) and buffer[offset] in " \r\n\t,":
                    offset += 1
                if offset < len(buffer):
                    break
                buffer = trace_file.read(1024 * 1024)
                offset = 0
                if not buffer:
                    return
            if buffer[offset] == "]":
                return
            try:
                event, next_offset = decoder.raw_decode(buffer, offset)
            except json.JSONDecodeError:
                buffer = buffer[offset:] + trace_file.read(1024 * 1024)
                offset = 0
                continue
            offset = next_offset
            if offset > 4 * 1024 * 1024:
                buffer = buffer[offset:]
                offset = 0
            if isinstance(event, dict):
                yield event


def _event_detail(event: dict[str, Any]) -> str:
    data = event.get("args", {}).get("data", {})
    name = event.get("name", "unknown")
    if name == "FunctionCall":
        return " · ".join(
            str(value)
            for value in (
                data.get("functionName") or "(anonymous)",
                data.get("url") or "(inline)",
                data.get("lineNumber"),
            )
            if value is not None
        )
    if name == "EventDispatch":
        return str(data.get("type") or "unknown")
    if name == "Paint":
        return str(data.get("nodeName") or "unknown")
    return ""


def _top_rows(
    totals: dict[str, float],
    counts: dict[str, int],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "total_ms": round(duration / 1000, 3),
            "count": counts[name],
            "mean_ms": round(duration / counts[name] / 1000, 4),
        }
        for name, duration in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def summarize(path: Path, *, limit: int) -> dict[str, Any]:
    event_totals: dict[str, float] = defaultdict(float)
    event_counts: dict[str, int] = defaultdict(int)
    detail_totals: dict[str, float] = defaultdict(float)
    detail_counts: dict[str, int] = defaultdict(int)
    cpu_nodes: dict[tuple[int, int], dict[int, str]] = defaultdict(dict)
    cpu_totals: dict[str, float] = defaultdict(float)
    cpu_counts: dict[str, int] = defaultdict(int)
    traced_events = 0

    for event in _trace_events(path):
        traced_events += 1
        name = str(event.get("name") or "unknown")
        duration = float(event.get("dur") or 0)
        if event.get("ph") == "X":
            event_totals[name] += duration
            event_counts[name] += 1
            detail = _event_detail(event)
            if detail:
                key = f"{name}: {detail}"
                detail_totals[key] += duration
                detail_counts[key] += 1

        if name != "ProfileChunk":
            continue
        profile_data = event.get("args", {}).get("data", {})
        cpu_profile = profile_data.get("cpuProfile", {})
        thread_key = (int(event.get("pid") or 0), int(event.get("tid") or 0))
        node_lookup = cpu_nodes[thread_key]
        for node in cpu_profile.get("nodes", []):
            frame = node.get("callFrame", {})
            node_lookup[int(node["id"])] = " · ".join(
                str(value)
                for value in (
                    frame.get("functionName") or "(anonymous)",
                    frame.get("url") or "(inline)",
                    frame.get("lineNumber"),
                )
                if value is not None
            )
        samples = cpu_profile.get("samples", [])
        deltas = profile_data.get("timeDeltas", [])
        for node_id, delta in zip(samples, deltas, strict=False):
            frame_name = node_lookup.get(int(node_id), f"node:{node_id}")
            cpu_totals[frame_name] += float(delta)
            cpu_counts[frame_name] += 1

    selected_names = (
        "FunctionCall",
        "UpdateLayoutTree",
        "Layout",
        "PrePaint",
        "Paint",
        "Commit",
        "Layerize",
        "CompositeLayers",
        "RasterTask",
    )
    selected_events = {
        name: {
            "total_ms": round(event_totals[name] / 1000, 3),
            "count": event_counts[name],
            "mean_ms": round(
                event_totals[name] / event_counts[name] / 1000,
                4,
            )
            if event_counts[name]
            else 0,
        }
        for name in selected_names
    }
    return {
        "trace": str(path),
        "trace_bytes": path.stat().st_size,
        "events": traced_events,
        "selected_pipeline_events": selected_events,
        "top_duration_events": _top_rows(event_totals, event_counts, limit=limit),
        "top_function_and_paint_details": _top_rows(
            detail_totals,
            detail_counts,
            limit=limit,
        ),
        "top_cpu_samples": _top_rows(cpu_totals, cpu_counts, limit=limit),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(summarize(args.trace, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
