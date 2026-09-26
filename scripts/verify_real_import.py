"""Upload a retained real demo, cancel/retry it, and verify HTTP availability."""

from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    records: list[dict[str, object]] = []

    def call(path: str, method: str = "GET") -> dict[str, object]:
        started = time.perf_counter()
        with urllib.request.urlopen(
            urllib.request.Request(base + path, method=method), timeout=60
        ) as response:
            body = response.read()
            records.append(
                {
                    "path": path,
                    "status": response.status,
                    "seconds": time.perf_counter() - started,
                }
            )
            if "json" in response.headers.get("content-type", ""):
                return json.loads(body)
            return {}

    call("/health")
    boundary = "stratweb-real-demo-acceptance"
    prefix = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="demo"; '
        f'filename="{args.demo.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    connection = http.client.HTTPConnection("127.0.0.1", args.port, timeout=120)
    connection.putrequest("POST", "/api/import-jobs")
    connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
    connection.putheader(
        "Content-Length", str(len(prefix) + args.demo.stat().st_size + len(suffix))
    )
    connection.putheader("Accept", "application/json")
    connection.endheaders()
    started = time.perf_counter()
    connection.send(prefix)
    with args.demo.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            connection.send(chunk)
    connection.send(suffix)
    response = connection.getresponse()
    job = json.loads(response.read())
    assert response.status == 202, job
    records.append(
        {"path": "/api/import-jobs", "status": 202, "seconds": time.perf_counter() - started}
    )
    connection.close()
    job_id = str(job["job_id"])
    print("uploaded", job_id, flush=True)
    cancelled = False
    retried = False
    last = None
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        job = call(f"/api/import-jobs/{job_id}")
        if job["stage"] != last:
            print(job["stage"], job["message"], flush=True)
            last = job["stage"]
        call("/ui")
        call(f"/ui/import-jobs/{job_id}")
        if not cancelled and job["stage"] == "spatial":
            call(f"/api/import-jobs/{job_id}/cancel", "POST")
            cancelled = True
        elif cancelled and not retried and job["stage"] == "cancelled":
            call(f"/api/import-jobs/{job_id}/retry", "POST")
            retried = True
        elif job["stage"] == "complete":
            assert cancelled and retried
            match_id = str(job["match_id"])
            call(f"/ui/matches/{match_id}")
            call(f"/ui/spatial/{match_id}/rounds/1")
            result = call(f"/api/spatial/{match_id}/rounds/1/playback?from_index=0&limit=64")
            assert result["samples"]
            for index in (64, 128):
                call(f"/api/spatial/{match_id}/rounds/1/playback?from_index={index}&limit=64")
            break
        elif job["stage"] == "failed":
            raise RuntimeError(str(job))
        time.sleep(0.5)
    assert job["stage"] == "complete", job
    args.output.write_text(
        json.dumps({"job": job, "requests": records}, indent=2), encoding="utf-8"
    )
    print("complete", job_id, flush=True)


if __name__ == "__main__":
    main()
