from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    javascript_root = project_root / "src" / "stratweb" / "web" / "static" / "js"
    javascript_files = sorted(javascript_root.glob("*.js"))
    if not javascript_files:
        raise RuntimeError(f"No JavaScript files found in {javascript_root}")

    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for JavaScript syntax validation")

    for javascript_file in javascript_files:
        subprocess.run([node, "--check", str(javascript_file)], check=True)

    print(f"JavaScript syntax: {len(javascript_files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
