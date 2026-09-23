from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import stratweb

_PROJECT_ROOT = Path(__file__).parents[1]


def test_release_version_is_consistent() -> None:
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lockfile = tomllib.loads((_PROJECT_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_project = next(
        package for package in lockfile["package"] if package["name"] == "stratweb"
    )

    assert pyproject["project"]["version"] == "0.30.0"
    assert locked_project["version"] == "0.30.0"
    assert stratweb.__version__ == "0.30.0"


def test_windows_launcher_uses_portable_runtime_defaults() -> None:
    launcher = (_PROJECT_ROOT / "scripts" / "start_server.ps1").read_text(encoding="utf-8")

    assert "C:\\Users\\" not in launcher
    assert "$env:STRATWEB_DUCKDB_PATH" in launcher
    assert "$env:STRATWEB_MAP_OVERVIEW_DIR" in launcher
    assert "$env:LOCALAPPDATA" in launcher


def test_primary_server_guide_has_no_private_user_path() -> None:
    guide = (_PROJECT_ROOT / "SERVER_GUIDE.md").read_text(encoding="utf-8")

    assert "C:\\Users\\rausa" not in guide
    assert "%LOCALAPPDATA%\\StratWeb" in guide


def test_http_smoke_script_checks_health_and_ui(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "scripts" / "smoke_http.py")],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "/health: 200" in result.stdout
    assert "/ui: 200" in result.stdout


def test_javascript_syntax_script_checks_static_assets() -> None:
    result = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "scripts" / "check_javascript.py")],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "JavaScript syntax:" in result.stdout


def test_release_gate_runs_http_smoke() -> None:
    release_gate = (_PROJECT_ROOT / "scripts" / "release_check.ps1").read_text(encoding="utf-8")

    assert 'Invoke-Checked "JavaScript syntax"' in release_gate
    assert "scripts/check_javascript.py" in release_gate
    assert 'Invoke-Checked "HTTP smoke"' in release_gate
    assert "scripts/smoke_http.py" in release_gate
