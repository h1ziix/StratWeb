#!/usr/bin/env python3
"""Install one official CS2 overview from the user's local game VPK."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

EXPECTED_VRF_VERSION = "Version: 19.2.6339+c72208352f5bf62f1482447ed166c548f303f8fa"
MAP_NAME = re.compile(r"^de_[a-z0-9_]+$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract an official radar PNG and overview transform from local CS2 files."
    )
    parser.add_argument("map_name", help="exact CS2 map name, for example de_ancient")
    parser.add_argument("--cs2-root", type=Path, required=True)
    parser.add_argument("--vrf-cli", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/map_overviews"))
    args = parser.parse_args()

    if MAP_NAME.fullmatch(args.map_name) is None:
        parser.error("map_name must match de_[a-z0-9_]+")
    cs2_root = args.cs2_root.expanduser().resolve()
    vrf_cli = args.vrf_cli.expanduser().resolve()
    output = args.output.expanduser().resolve()
    vpk = cs2_root / "game" / "csgo" / "pak01_dir.vpk"
    if not vpk.is_file():
        parser.error(f"CS2 VPK not found: {vpk}")
    if not vrf_cli.is_file():
        parser.error(f"Source2Viewer CLI not found: {vrf_cli}")
    version = subprocess.run(
        [vrf_cli, "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    if not version or version[0] != EXPECTED_VRF_VERSION:
        parser.error("unverified Source2Viewer CLI version; expected " + EXPECTED_VRF_VERSION)

    texture = f"panorama/images/overheadmaps/{args.map_name}_radar_psd.vtex_c"
    metadata = f"resource/overviews/{args.map_name}.txt"
    lower_texture = f"panorama/images/overheadmaps/{args.map_name}_lower_radar_psd.vtex_c"
    target_lower: Path | None = None
    with tempfile.TemporaryDirectory(prefix="stratweb-overview-") as temporary:
        extraction_root = Path(temporary)
        for internal_path in (texture, metadata):
            _extract(vrf_cli, vpk, extraction_root, internal_path)
        source_png = extraction_root.joinpath(*texture.removesuffix(".vtex_c").split("/"))
        source_png = source_png.with_suffix(".png")
        source_txt = extraction_root.joinpath(*metadata.split("/"))
        if not source_png.is_file() or not source_txt.is_file():
            parser.error("Source2Viewer did not produce the expected overview pair")
        source_lower: Path | None = None
        if '"lower"' in source_txt.read_text(encoding="utf-8-sig"):
            _extract(vrf_cli, vpk, extraction_root, lower_texture)
            lower_candidate = extraction_root.joinpath(
                *lower_texture.removesuffix(".vtex_c").split("/")
            ).with_suffix(".png")
            if not lower_candidate.is_file():
                parser.error("Overview declares a lower level but its texture was not extracted")
            source_lower = lower_candidate
        output.mkdir(parents=True, exist_ok=True)
        target_png = output / f"{args.map_name}.png"
        target_txt = output / f"{args.map_name}.txt"
        shutil.copy2(source_png, target_png)
        shutil.copy2(source_txt, target_txt)
        if source_lower is not None:
            target_lower = output / f"{args.map_name}_lower.png"
            shutil.copy2(source_lower, target_lower)

    print(f"installed {target_png} sha256={_sha256(target_png)}")
    print(f"installed {target_txt} sha256={_sha256(target_txt)}")
    if target_lower is not None:
        print(f"installed {target_lower} sha256={_sha256(target_lower)}")
    _update_manifest(
        output,
        map_name=args.map_name,
        vpk=vpk,
        cs2_root=cs2_root,
        image=target_png,
        metadata=target_txt,
        lower_image=target_lower,
    )
    return 0


def _extract(vrf_cli: Path, vpk: Path, output: Path, internal_path: str) -> None:
    subprocess.run(
        [
            vrf_cli,
            "--input",
            vpk,
            "--output",
            output,
            "--decompile",
            "--vpk_filepath",
            internal_path,
        ],
        check=True,
    )


def _update_manifest(
    output: Path,
    *,
    map_name: str,
    vpk: Path,
    cs2_root: Path,
    image: Path,
    metadata: Path,
    lower_image: Path | None,
) -> None:
    manifest_path = output / "manifest.json"
    manifest: dict[str, object] = {"schema_version": "1.0.0", "assets": {}}
    if manifest_path.is_file():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("assets"), dict):
            manifest = loaded
    assets = manifest["assets"]
    if not isinstance(assets, dict):
        raise ValueError("overview manifest assets must be an object")
    version_metadata = _read_steam_inf(cs2_root / "game" / "csgo" / "steam.inf")
    assets[map_name] = {
        "map_name": map_name,
        "source": "user_local_cs2_installation",
        "source_paths": [
            f"resource/overviews/{map_name}.txt",
            f"panorama/images/overheadmaps/{map_name}_radar_psd.vtex_c",
        ],
        "license_status": "Valve proprietary; local use only; redistribution not granted",
        "extractor": EXPECTED_VRF_VERSION,
        "vpk_sha256": _sha256(vpk),
        "game_build": version_metadata,
        "image": _asset_record(image),
        "metadata": _asset_record(metadata),
        "lower_image": _asset_record(lower_image) if lower_image is not None else None,
    }
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(manifest_path)
    print(f"updated {manifest_path}")


def _asset_record(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "filename": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }
    if path.suffix.casefold() == ".png":
        width, height = _png_dimensions(path)
        record.update({"width": width, "height": height})
    return record


def _read_steam_inf(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            result[key.strip()] = value.strip()
    return result


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) != 24 or header[:8] != _PNG_SIGNATURE or header[12:16] != b"IHDR":
        raise ValueError("not a PNG with an IHDR header")
    return struct.unpack(">II", header[16:24])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
