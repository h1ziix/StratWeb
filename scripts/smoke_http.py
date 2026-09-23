from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> int:
    with TemporaryDirectory(prefix="stratweb-smoke-") as temporary_directory:
        runtime_root = Path(temporary_directory)
        os.environ["STRATWEB_DUCKDB_PATH"] = str(runtime_root / "smoke.duckdb")
        os.environ["STRATWEB_MAP_OVERVIEW_DIR"] = str(runtime_root / "map_overviews")

        from fastapi.testclient import TestClient

        import stratweb
        from stratweb.main import create_app

        with TestClient(create_app()) as client:
            health_response = client.get("/health")
            if health_response.status_code != 200:
                raise RuntimeError(f"/health returned {health_response.status_code}")
            if health_response.json().get("version") != stratweb.__version__:
                raise RuntimeError("/health version does not match the installed package")
            print(f"/health: {health_response.status_code}")

            ui_response = client.get("/ui")
            if ui_response.status_code != 200:
                raise RuntimeError(f"/ui returned {ui_response.status_code}")
            print(f"/ui: {ui_response.status_code}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
