"""Shared overview installation root and non-destructive legacy resource recovery."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def default_map_overview_dir() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "StratWeb" / "map_overviews"
        return Path.home() / "AppData" / "Local" / "StratWeb" / "map_overviews"
    return Path("data/map_overviews")


def restore_map_resources(source: Path, target: Path) -> int:
    """Copy missing files only. Registry validation remains mandatory at read time."""
    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    if source == target or not source.is_dir():
        return 0
    copied = 0
    for original in sorted(source.rglob("*")):
        if not original.is_file() or original.is_symlink():
            continue
        relative = original.relative_to(source)
        destination = target / relative
        if target not in destination.resolve().parents:
            raise ValueError("map recovery target escaped configured directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as output, original.open("rb") as input_file:
                while chunk := input_file.read(1024 * 1024):
                    output.write(chunk)
        except FileExistsError:
            continue
        copied += 1
    return copied


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=default_map_overview_dir())
    parser.add_argument("--source", type=Path, default=Path.home() / "StratWeb-data/map_overviews")
    args = parser.parse_args()
    print(f"Recovered {restore_map_resources(args.source, args.target)} missing map resource files")


if __name__ == "__main__":
    main()
