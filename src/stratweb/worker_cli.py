"""Private CLI entry point for one isolated demoparser2 extraction."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stratweb.adapters.parsers import (
    Demoparser2Adapter,
    Demoparser2EconomyExtractor,
    Demoparser2SpatialExtractor,
)
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.import_worker import ARTIFACT_VERSION


def main() -> int:
    if len(sys.argv) != 2:
        print("worker_request_missing", file=sys.stderr)
        return 2
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        if request.get("artifact_version") != ARTIFACT_VERSION:
            raise ValueError("Unsupported parser artifact request version.")
        demo_path = Path(request["demo_path"]).resolve(strict=True)
        output_path = Path(request["output_path"]).resolve()
        expected_sha256 = str(request["expected_sha256"])
        ticks = tuple(int(value) for value in request.get("ticks", ()))
        mode = request["mode"]
        result: BaseModel
        if mode == "canonical":
            result = CanonicalizationService(Demoparser2Adapter()).normalize(demo_path)
        elif mode == "economy":
            result = Demoparser2EconomyExtractor().extract(
                demo_path, ticks, expected_sha256=expected_sha256
            )
        elif mode == "spatial":
            result = Demoparser2SpatialExtractor().extract(
                demo_path, ticks, expected_sha256=expected_sha256
            )
        else:
            raise ValueError("Unknown parser worker mode.")
        _atomic_model_write(output_path, result)
        return 0
    except Exception as exc:
        payload: dict[str, Any] = {
            "error_code": getattr(exc, "error_code", "import_worker_failed"),
            "message": (str(exc) or type(exc).__name__)[:300],
        }
        print(json.dumps(payload, ensure_ascii=True), file=sys.stderr)
        return 1


def _atomic_model_write(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    try:
        temporary.write_text(model.model_dump_json(), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
