"""Safe, local-only bridge from retained demos to CS2 console commands."""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository


class CS2DemoCommand(BaseModel):
    """Prepared console commands; commands are copied, never executed by StratWeb."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    match_id: UUID
    tick: int = Field(ge=0)
    demo_name: str = Field(min_length=1)
    play_command: str = Field(min_length=1)
    seek_command: str = Field(min_length=1)
    clipboard_text: str = Field(min_length=1)
    reused_existing_file: bool


class CS2DemoBridgeError(RuntimeError):
    """Typed product error for unavailable or unsafe CS2 preparation."""


class CS2DemoBridgeService:
    def __init__(self, database_path: Path, cs2_demo_directory: Path | None) -> None:
        self._database_path = database_path.expanduser().resolve()
        self._upload_directory = (self._database_path.parent / "uploads").resolve()
        self._cs2_demo_directory = (
            cs2_demo_directory.expanduser().resolve() if cs2_demo_directory else None
        )

    def prepare(self, match_id: UUID, tick: int) -> CS2DemoCommand:
        if tick < 0:
            raise CS2DemoBridgeError("Tick не может быть отрицательным.")
        destination_root = self._validated_destination_root()
        source_path, expected_sha256 = self._retained_source(match_id)
        destination_name = f"stratweb_{match_id}.dem"
        destination = (destination_root / destination_name).resolve()
        if destination.parent != destination_root or destination.name != destination_name:
            raise CS2DemoBridgeError("Небезопасное имя файла для CS2 отклонено.")

        source_sha256 = _sha256(source_path)
        if source_sha256 != expected_sha256:
            raise CS2DemoBridgeError(
                "Сохранённая демка не совпадает с SHA-256 матча. Подготовка отменена."
            )
        reused = destination.is_file() and _sha256(destination) == expected_sha256
        if not reused:
            _install_demo(source_path, destination, expected_sha256)

        relative_demo = f"StratWeb/{destination_name}"
        play = f'playdemo "{relative_demo}"'
        seek = f"demo_gototick {tick}; demo_pause"
        return CS2DemoCommand(
            match_id=match_id,
            tick=tick,
            demo_name=relative_demo,
            play_command=play,
            seek_command=seek,
            clipboard_text=f"{play}\n{seek}",
            reused_existing_file=reused,
        )

    def _validated_destination_root(self) -> Path:
        if self._cs2_demo_directory is None:
            raise CS2DemoBridgeError(
                "Папка CS2 не настроена. Укажите STRATWEB_CS2_DEMO_DIR."
            )
        root = self._cs2_demo_directory
        if root.name.casefold() != "stratweb" or root.parent.name.casefold() != "csgo":
            raise CS2DemoBridgeError(
                "Папка экспорта должна называться StratWeb и находиться внутри game/csgo."
            )
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CS2DemoBridgeError("StratWeb не может создать папку демо в CS2.") from exc
        if not root.is_dir():
            raise CS2DemoBridgeError("Настроенная папка демо CS2 недоступна.")
        return root.resolve()

    def _retained_source(self, match_id: UUID) -> tuple[Path, str]:
        DuckDBMatchRepository(self._database_path).initialize()
        with read_connection(self._database_path, "CS2 demo bridge") as connection:
            row = connection.execute(
                """SELECT j.internal_name, m.source_demo_sha256
                   FROM matches m JOIN import_jobs j ON j.match_id=m.match_id
                   WHERE m.match_id=? AND j.stage='complete'
                   ORDER BY j.completed_at DESC NULLS LAST, j.updated_at DESC LIMIT 1""",
                [match_id],
            ).fetchone()
        if row is None:
            raise CS2DemoBridgeError(
                "Исходная демка этого матча не сохранена. Повторно загрузите .dem через StratWeb."
            )
        internal_name, expected_sha256 = str(row[0]), str(row[1])
        source = (self._upload_directory / internal_name).resolve()
        if (
            source.parent != self._upload_directory
            or source.name != internal_name
            or source.suffix.casefold() != ".dem"
            or not source.is_file()
        ):
            raise CS2DemoBridgeError("Сохранённый исходный .dem недоступен или небезопасен.")
        return source, expected_sha256


def _install_demo(source: Path, destination: Path, expected_sha256: str) -> None:
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        if _sha256(temporary) != expected_sha256:
            raise CS2DemoBridgeError("Копия демки для CS2 не прошла проверку SHA-256.")
        os.replace(temporary, destination)
    except CS2DemoBridgeError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CS2DemoBridgeError("Не удалось подготовить демку в папке CS2.") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CS2DemoBridgeError("Не удалось прочитать .dem для проверки SHA-256.") from exc
    return digest.hexdigest()


__all__ = ["CS2DemoBridgeError", "CS2DemoBridgeService", "CS2DemoCommand"]
