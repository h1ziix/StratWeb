"""Production adapter for the pinned demoparser2 Python API."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import Any, Protocol, cast

import polars as pl
from demoparser2 import DemoParser as NativeDemoParser

from stratweb.contracts import ParsedDemo, ParseRequest, ParserIdentity
from stratweb.exceptions import (
    DemoFileNotFoundError,
    DemoFileUnreadableError,
    DemoInspectionError,
    DemoParseError,
    ParserContractError,
    UnsupportedDemoError,
)

EXPECTED_PARSER_VERSION = "0.41.4"
PARSER_NAME = "demoparser2"
_CS2_DEMO_STAMP = b"PBDEMS2"
_MAX_EXTERNAL_ERROR_LENGTH = 400


class _ParserBackend(Protocol):
    def parse_header(self) -> Any: ...

    def list_game_events(self) -> Any: ...

    def parse_event(
        self,
        event_name: str,
        *,
        player: Sequence[str] | None = None,
        other: Sequence[str] | None = None,
    ) -> Any: ...

    def parse_events(
        self,
        event_name: Sequence[str],
        *,
        player: Sequence[str] | None = None,
        other: Sequence[str] | None = None,
    ) -> Any: ...

    def parse_player_info(self) -> Any: ...


ParserFactory = Callable[[str], _ParserBackend]


class Demoparser2Adapter:
    """Translate demoparser2 output and failures into StratWeb contracts."""

    def __init__(
        self,
        *,
        parser_factory: ParserFactory | None = None,
        installed_version: str | None = None,
    ) -> None:
        version = installed_version or metadata.version(PARSER_NAME)
        if version != EXPECTED_PARSER_VERSION:
            raise ParserContractError(
                f"Expected {PARSER_NAME}=={EXPECTED_PARSER_VERSION}, found {version}."
            )
        self._identity = ParserIdentity(name=PARSER_NAME, version=version)
        self._parser_factory = parser_factory or cast(ParserFactory, NativeDemoParser)

    @property
    def identity(self) -> ParserIdentity:
        return self._identity

    def parse(self, request: ParseRequest) -> ParsedDemo:
        path = self._validate_path(request.path)
        backend = self._create_backend(path)
        header = self._parse_header(backend, path)
        available_events = self._list_events(backend, path)

        tables: dict[str, pl.DataFrame] = {}
        event_errors: dict[str, str] = {}
        warnings: list[str] = []
        available_set = set(available_events)

        event_kwargs: dict[str, Sequence[str]] = {}
        if request.options.player_properties:
            event_kwargs["player"] = request.options.player_properties
        if request.options.other_properties:
            event_kwargs["other"] = request.options.other_properties

        target_events = tuple(
            event_name
            for event_name in dict.fromkeys(request.options.event_names)
            if event_name in available_set
        )
        if target_events:
            try:
                raw_batch = backend.parse_events(target_events, **event_kwargs)
            except Exception as exc:
                warnings.append(
                    "Batch event parsing failed; per-event fallback was used: "
                    + _safe_external_error(exc, path)
                )
                self._parse_events_individually(
                    backend,
                    target_events,
                    event_kwargs,
                    path,
                    tables,
                    event_errors,
                )
            else:
                self._collect_batch_events(
                    raw_batch,
                    target_events,
                    tables,
                    event_errors,
                )

        player_info: pl.DataFrame | None = None
        try:
            raw_player_info = backend.parse_player_info()
            player_info = _to_polars(raw_player_info, context="player info")
        except Exception as exc:
            warnings.append("Player info could not be parsed: " + _safe_external_error(exc, path))

        return ParsedDemo(
            demo_file_id=request.demo_file_id,
            parser=self.identity,
            header=header,
            tables=tables,
            available_events=available_events,
            player_info=player_info,
            event_errors=event_errors,
            warnings=tuple(warnings),
        )

    def _collect_batch_events(
        self,
        raw_batch: Any,
        requested: tuple[str, ...],
        tables: dict[str, pl.DataFrame],
        event_errors: dict[str, str],
    ) -> None:
        if isinstance(raw_batch, Mapping):
            items = list(raw_batch.items())
        elif isinstance(raw_batch, Sequence) and not isinstance(raw_batch, (str, bytes)):
            items = list(raw_batch)
        else:
            raise ParserContractError(
                "demoparser2 parse_events() returned an unsupported batch value."
            )

        requested_set = set(requested)
        returned: set[str] = set()
        for item in items:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
                raise ParserContractError(
                    "demoparser2 parse_events() returned an invalid event/table pair."
                )
            event_name, raw_event = item
            if not isinstance(event_name, str) or event_name not in requested_set:
                raise ParserContractError(
                    "demoparser2 parse_events() returned an unexpected event name."
                )
            if event_name in returned:
                raise ParserContractError(
                    "demoparser2 parse_events() returned a duplicate event table."
                )
            returned.add(event_name)
            try:
                tables[event_name] = _to_polars(raw_event, context=f"event {event_name}")
            except ParserContractError as exc:
                event_errors[event_name] = str(exc)

        for missing_event in requested_set - returned:
            event_errors[missing_event] = "parse_events() returned no table for this event."

    def _parse_events_individually(
        self,
        backend: _ParserBackend,
        event_names: tuple[str, ...],
        event_kwargs: Mapping[str, Sequence[str]],
        path: Path,
        tables: dict[str, pl.DataFrame],
        event_errors: dict[str, str],
    ) -> None:
        for event_name in event_names:
            try:
                raw_event = backend.parse_event(event_name, **event_kwargs)
                tables[event_name] = _to_polars(raw_event, context=f"event {event_name}")
            except Exception as exc:
                event_errors[event_name] = _safe_external_error(exc, path)

    def _validate_path(self, path: Path) -> Path:
        candidate = path.expanduser()
        if not candidate.exists():
            raise DemoFileNotFoundError(f"Demo file does not exist: {candidate}")
        if not candidate.is_file():
            raise DemoFileUnreadableError(f"Demo path is not a regular file: {candidate}")
        if candidate.suffix.casefold() != ".dem":
            raise UnsupportedDemoError("Only local files with the .dem extension are supported.")

        try:
            with candidate.open("rb") as stream:
                stamp = stream.read(len(_CS2_DEMO_STAMP))
        except PermissionError as exc:
            raise DemoFileUnreadableError(f"Demo file is not readable: {candidate}") from exc
        except OSError as exc:
            raise DemoFileUnreadableError(f"Could not read demo file: {candidate}") from exc

        if stamp != _CS2_DEMO_STAMP:
            raise UnsupportedDemoError("The file does not contain the CS2 PBDEMS2 demo stamp.")
        return candidate.resolve()

    def _create_backend(self, path: Path) -> _ParserBackend:
        try:
            return self._parser_factory(str(path))
        except Exception as exc:
            raise _translate_parser_error(exc, operation="initialization", path=path) from exc

    def _parse_header(self, backend: _ParserBackend, path: Path) -> Mapping[str, Any]:
        try:
            header = backend.parse_header()
        except Exception as exc:
            raise _translate_parser_error(exc, operation="header parsing", path=path) from exc
        if not isinstance(header, Mapping):
            raise ParserContractError("demoparser2 parse_header() did not return a mapping.")
        return {str(key): value for key, value in header.items()}

    def _list_events(self, backend: _ParserBackend, path: Path) -> tuple[str, ...]:
        try:
            raw_events = backend.list_game_events()
        except Exception as exc:
            raise _translate_parser_error(exc, operation="event discovery", path=path) from exc

        values: Iterable[Any]
        if isinstance(raw_events, Mapping):
            values = raw_events.keys()
        elif isinstance(raw_events, Sequence) and not isinstance(raw_events, (str, bytes)):
            values = raw_events
        else:
            raise ParserContractError(
                "demoparser2 list_game_events() returned an unsupported value."
            )

        events: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value:
                raise ParserContractError(
                    "demoparser2 list_game_events() returned a non-string event name."
                )
            events.append(value)
        return tuple(sorted(set(events)))


def _to_polars(value: Any, *, context: str) -> pl.DataFrame:
    if isinstance(value, pl.DataFrame):
        return value.clone()
    if value is None:
        raise ParserContractError(f"demoparser2 returned no dataframe for {context}.")

    if hasattr(value, "columns") and hasattr(value, "to_dict"):
        try:
            return pl.from_pandas(value)
        except Exception as exc:
            raise ParserContractError(
                f"Could not convert demoparser2 dataframe for {context} to Polars."
            ) from exc
    try:
        return pl.DataFrame(value)
    except Exception as exc:
        raise ParserContractError(
            f"demoparser2 returned an unsupported table for {context}."
        ) from exc


def _translate_parser_error(
    exc: Exception,
    *,
    operation: str,
    path: Path,
) -> DemoInspectionError:
    safe_message = _safe_external_error(exc, path)
    normalized = f"{type(exc).__name__} {exc}".casefold()
    if "unknownfile" in normalized or "unsupported" in normalized:
        return UnsupportedDemoError(
            f"demoparser2 rejected the file during {operation}: {safe_message}"
        )
    return DemoParseError(f"demoparser2 failed during {operation}: {safe_message}")


def _safe_external_error(exc: Exception, path: Path) -> str:
    message = str(exc).strip() or type(exc).__name__
    for candidate in {str(path), str(path.resolve())}:
        message = message.replace(candidate, "<demo>")
    message = " ".join(message.split())
    if len(message) > _MAX_EXTERNAL_ERROR_LENGTH:
        message = message[:_MAX_EXTERNAL_ERROR_LENGTH] + "…"
    return f"{type(exc).__name__}: {message}"
