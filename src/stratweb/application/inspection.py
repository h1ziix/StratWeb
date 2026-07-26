"""Parser-agnostic use case for inspecting one local completed CS2 demo."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import polars as pl
from pydantic import JsonValue

from stratweb.application.event_normalization import InspectionEventNormalizer
from stratweb.application.inspection_models import (
    ColumnSummary,
    DemoInspectionReport,
    EventSummary,
    InspectedFile,
    InspectionStatus,
    MatchSummary,
    ParserSummary,
    PlayerSummary,
    TeamSummary,
)
from stratweb.contracts import ParsedDemo, ParseOptions, ParseRequest
from stratweb.exceptions import (
    DemoFileNotFoundError,
    DemoFileUnreadableError,
    ParserContractError,
)
from stratweb.ports import DemoParser

SUPPORTED_EVENTS: tuple[str, ...] = (
    "player_death",
    "player_hurt",
    "weapon_fire",
    "round_prestart",
    "round_start",
    "round_poststart",
    "round_freeze_end",
    "round_end",
    "round_officially_ended",
    "bomb_planted",
    "bomb_defused",
    "bomb_exploded",
    "smokegrenade_detonate",
    "smokegrenade_expired",
    "inferno_startburn",
    "inferno_expire",
    "flashbang_detonate",
    "hegrenade_detonate",
    "decoy_detonate",
    "player_spawn",
    "player_team",
)

_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_PLAYER_PREVIEW = 128
_MAX_EVENT_PLAYER_SCAN_ROWS = 5_000
_MAX_HEADER_DEPTH = 4
_MAX_HEADER_ITEMS = 256
_MAX_HEADER_STRING_LENGTH = 4_096


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    size_bytes: int
    modified_ns: int
    sha256: str


class DemoInspectionService:
    """Build a compact report without normalizing gameplay or writing to DuckDB."""

    def __init__(self, parser: DemoParser) -> None:
        self._parser = parser

    def inspect(self, demo_path: str | Path) -> DemoInspectionReport:
        snapshot = inspect_local_file(demo_path)
        request = ParseRequest(
            demo_file_id=uuid5(NAMESPACE_URL, f"stratweb:demo:{snapshot.sha256}"),
            sha256=snapshot.sha256,
            path=snapshot.path,
            options=ParseOptions(
                event_names=SUPPORTED_EVENTS,
                player_properties=(),
                other_properties=("total_rounds_played", "is_warmup_period"),
                include_grenade_trajectories=False,
            ),
        )
        parsed = self._parser.parse(request)
        self._validate_parser_result(request, parsed)
        self._ensure_file_unchanged(snapshot)
        return self._build_report(snapshot, parsed)

    def _build_report(
        self,
        snapshot: _FileSnapshot,
        parsed: ParsedDemo,
    ) -> DemoInspectionReport:
        warnings = list(parsed.warnings)
        errors: list[str] = []
        events: dict[str, EventSummary] = {}

        available = set(parsed.available_events)
        for event_name in SUPPORTED_EVENTS:
            frame = parsed.tables.get(event_name)
            event_error = parsed.event_errors.get(event_name)
            is_available = event_name in available

            if event_error:
                errors.append(f"{event_name}: {event_error}")
            elif is_available and frame is None:
                event_error = "Parser declared the event but returned no table."
                errors.append(f"{event_name}: {event_error}")

            events[event_name] = _summarize_event(
                available=is_available,
                frame=frame,
                error=event_error,
            )

        safe_header = {
            str(key): _json_safe(value)
            for key, value in sorted(parsed.header.items(), key=lambda item: str(item[0]))
        }
        map_name = _optional_text(_header_value(parsed.header, "map_name", "map"))
        server_name = _optional_text(_header_value(parsed.header, "server_name"))
        client_name = _optional_text(_header_value(parsed.header, "client_name"))
        demo_type = _optional_text(_header_value(parsed.header, "demo_type", "demo_version_name"))
        playback_ticks = _optional_non_negative_int(
            _header_value(parsed.header, "playback_ticks", "playback_frames", "ticks")
        )
        playback_time = _optional_non_negative_float(
            _header_value(parsed.header, "playback_time", "playback_time_seconds", "duration")
        )

        players, teams, player_count, player_warnings = _summarize_players(parsed)
        warnings.extend(player_warnings)
        normalization = InspectionEventNormalizer().normalize(parsed)
        warnings.extend(normalization.warnings)
        estimated_round_count = normalization.estimated_round_count

        _warn_if_missing(warnings, map_name, "Map name is not available.")
        _warn_if_missing(warnings, server_name, "Server name is not available.")
        if client_name is None and demo_type is None:
            warnings.append("Client name and demo type are not available.")
        _warn_if_missing(warnings, playback_ticks, "Playback tick count is not available.")
        _warn_if_missing(warnings, playback_time, "Playback time is not available.")
        _warn_if_missing(
            warnings,
            estimated_round_count,
            "An approximate round count could not be derived.",
        )

        warnings = list(dict.fromkeys(warnings))
        status = InspectionStatus.PARTIAL if warnings or errors else InspectionStatus.SUCCESS

        return DemoInspectionReport(
            status=status,
            file=InspectedFile(
                original_name=snapshot.path.name,
                size_bytes=snapshot.size_bytes,
                sha256=snapshot.sha256,
            ),
            parser=ParserSummary(
                name=parsed.parser.name,
                version=parsed.parser.version,
                available_game_events=tuple(sorted(parsed.available_events)),
            ),
            header=safe_header,
            match=MatchSummary(
                map_name=map_name,
                server_name=server_name,
                client_name=client_name,
                demo_type=demo_type,
                playback_ticks=playback_ticks,
                playback_time=playback_time,
                estimated_round_count=estimated_round_count,
                estimated_round_count_source=normalization.estimated_round_count_source,
                round_count_candidates=normalization.round_count_candidates,
                player_count=player_count,
                players=players,
                teams=teams,
            ),
            events=events,
            canonical_events=normalization.canonical_events,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def _validate_parser_result(self, request: ParseRequest, parsed: ParsedDemo) -> None:
        if parsed.demo_file_id != request.demo_file_id:
            raise ParserContractError("Parser returned data for a different demo ID.")
        if parsed.parser != self._parser.identity:
            raise ParserContractError("Parser identity changed while processing the demo.")

    def _ensure_file_unchanged(self, snapshot: _FileSnapshot) -> None:
        try:
            current = snapshot.path.stat()
        except OSError as exc:
            raise DemoFileUnreadableError(
                "The demo became unavailable while it was being inspected."
            ) from exc
        if current.st_size != snapshot.size_bytes or current.st_mtime_ns != snapshot.modified_ns:
            raise DemoFileUnreadableError("The demo changed while it was being inspected.")


def inspect_local_file(demo_path: str | Path) -> _FileSnapshot:
    """Validate metadata and hash a local file using bounded memory."""

    path = Path(demo_path).expanduser()
    if not path.exists():
        raise DemoFileNotFoundError(f"Demo file does not exist: {path}")
    if not path.is_file():
        raise DemoFileUnreadableError(f"Demo path is not a regular file: {path}")

    try:
        before = path.stat()
        digest = compute_sha256(path)
        after = path.stat()
    except PermissionError as exc:
        raise DemoFileUnreadableError(f"Demo file is not readable: {path}") from exc
    except OSError as exc:
        raise DemoFileUnreadableError(f"Could not read demo file: {path}") from exc

    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise DemoFileUnreadableError("The demo changed while its SHA-256 was calculated.")

    return _FileSnapshot(
        path=path.resolve(),
        size_bytes=after.st_size,
        modified_ns=after.st_mtime_ns,
        sha256=digest,
    )


def compute_sha256(path: Path, *, chunk_size: int = _HASH_CHUNK_SIZE) -> str:
    """Calculate SHA-256 without loading the entire file into memory."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _summarize_event(
    *,
    available: bool,
    frame: pl.DataFrame | None,
    error: str | None,
) -> EventSummary:
    if frame is None:
        return EventSummary(
            available=available,
            parsed=False,
            row_count=0,
            columns=(),
            column_schema=(),
            error=error,
        )
    return EventSummary(
        available=available,
        parsed=error is None,
        row_count=frame.height,
        columns=tuple(frame.columns),
        column_schema=tuple(
            ColumnSummary(name=name, dtype=str(dtype)) for name, dtype in frame.schema.items()
        ),
        error=error,
    )


def _summarize_players(
    parsed: ParsedDemo,
) -> tuple[tuple[PlayerSummary, ...], tuple[TeamSummary, ...], int, list[str]]:
    warnings: list[str] = []
    candidates: dict[str, PlayerSummary] = {}
    fallback_count = 0

    if parsed.player_info is not None:
        fallback_count = parsed.player_info.height
        _collect_players_from_frame(parsed.player_info, candidates)
    else:
        warnings.append("Player info is not available from the parser.")

    for frame in parsed.tables.values():
        _collect_players_from_event_frame(frame, candidates)

    ordered = sorted(
        candidates.values(),
        key=lambda player: (player.team or "", player.steam_id or "", player.name or ""),
    )
    player_count = len(ordered) or fallback_count
    if len(ordered) > _MAX_PLAYER_PREVIEW:
        warnings.append(
            f"Player preview was limited to {_MAX_PLAYER_PREVIEW} of {len(ordered)} entries."
        )
    preview = tuple(ordered[:_MAX_PLAYER_PREVIEW])

    team_members: dict[str, list[PlayerSummary]] = {}
    for player in ordered:
        if player.team:
            team_members.setdefault(player.team, []).append(player)
    teams = tuple(
        TeamSummary(
            name=team,
            player_count=len(members),
            steam_ids=tuple(sorted({p.steam_id for p in members if p.steam_id})),
        )
        for team, members in sorted(team_members.items())
    )
    return preview, teams, player_count, warnings


def _collect_players_from_frame(
    frame: pl.DataFrame,
    target: dict[str, PlayerSummary],
) -> None:
    name_column = _find_column(frame.columns, ("name", "player_name"))
    steam_column = _find_column(
        frame.columns,
        ("steamid", "steam_id", "player_steamid", "xuid"),
    )
    team_column = _find_column(
        frame.columns,
        ("team_name", "team", "team_num", "team_number"),
    )
    if name_column is None and steam_column is None:
        return

    for row in frame.head(_MAX_PLAYER_PREVIEW * 4).iter_rows(named=True):
        _add_player(
            target,
            name=_optional_text(row.get(name_column)) if name_column else None,
            steam_id=_optional_identifier(row.get(steam_column)) if steam_column else None,
            team=_normalize_team(row.get(team_column)) if team_column else None,
        )


def _collect_players_from_event_frame(
    frame: pl.DataFrame,
    target: dict[str, PlayerSummary],
) -> None:
    lower_to_original = {column.casefold(): column for column in frame.columns}
    steam_columns = [
        (lower, original)
        for lower, original in lower_to_original.items()
        if lower == "steamid" or lower.endswith("_steamid") or lower.endswith("_steam_id")
    ]
    if not steam_columns:
        return

    for row in frame.head(_MAX_EVENT_PLAYER_SCAN_ROWS).iter_rows(named=True):
        for lower, steam_column in steam_columns:
            if lower == "steamid":
                prefix = ""
            elif lower.endswith("_steamid"):
                prefix = lower[: -len("steamid")]
            else:
                prefix = lower[: -len("steam_id")]
            name_column = lower_to_original.get(f"{prefix}name")
            team_column = lower_to_original.get(f"{prefix}team_name") or lower_to_original.get(
                f"{prefix}team"
            )
            _add_player(
                target,
                name=_optional_text(row.get(name_column)) if name_column else None,
                steam_id=_optional_identifier(row.get(steam_column)),
                team=_normalize_team(row.get(team_column)) if team_column else None,
            )


def _add_player(
    target: dict[str, PlayerSummary],
    *,
    name: str | None,
    steam_id: str | None,
    team: str | None,
) -> None:
    if name is None and steam_id is None:
        return
    if steam_id:
        key = f"steam:{steam_id}"
    else:
        key = f"name:{(name or '').casefold()}|team:{(team or '').casefold()}"
    existing = target.get(key)
    target[key] = PlayerSummary(
        name=(existing.name if existing else None) or name,
        steam_id=(existing.steam_id if existing else None) or steam_id,
        team=(existing.team if existing else None) or team,
    )


def _find_column(columns: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    lookup = {column.casefold(): column for column in columns}
    for alias in aliases:
        if alias.casefold() in lookup:
            return lookup[alias.casefold()]
    return None


def _header_value(header: Mapping[str, Any], *keys: str) -> Any:
    lookup = {str(key).casefold(): value for key, value in header.items()}
    for key in keys:
        if key.casefold() in lookup:
            return lookup[key.casefold()]
    return None


def _optional_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _optional_identifier(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() or None


def _normalize_team(value: Any) -> str | None:
    if _is_missing(value):
        return None
    if value in (2, "2"):
        return "T"
    if value in (3, "3"):
        return "CT"
    return _optional_text(value)


def _optional_non_negative_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _optional_non_negative_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


def _warn_if_missing(warnings: list[str], value: object | None, message: str) -> None:
    if value is None:
        warnings.append(message)


def _json_safe(value: Any, *, depth: int = 0) -> JsonValue:
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and len(value) > _MAX_HEADER_STRING_LENGTH:
            return value[:_MAX_HEADER_STRING_LENGTH] + "…"
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, bytes):
        return value[:_MAX_HEADER_STRING_LENGTH].hex()
    if depth >= _MAX_HEADER_DEPTH:
        return str(value)[:_MAX_HEADER_STRING_LENGTH]
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:_MAX_HEADER_ITEMS]
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in list(value)[:_MAX_HEADER_ITEMS]]
    return str(value)[:_MAX_HEADER_STRING_LENGTH]
