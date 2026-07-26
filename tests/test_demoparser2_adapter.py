from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import polars as pl
import pytest

from stratweb.adapters.parsers.demoparser2 import Demoparser2Adapter
from stratweb.contracts import ParseOptions, ParseRequest
from stratweb.exceptions import DemoParseError, ParserContractError, UnsupportedDemoError
from stratweb.ports import DemoParser


class FakeBackend:
    def __init__(self, _path: str) -> None:
        self.parse_calls: list[str] = []

    def parse_header(self) -> dict[str, str]:
        return {"map_name": "de_nuke"}

    def list_game_events(self) -> list[str]:
        return ["player_death"]

    def parse_event(
        self,
        event_name: str,
        *,
        player: Sequence[str] | None = None,
        other: Sequence[str] | None = None,
    ) -> pl.DataFrame:
        del player, other
        self.parse_calls.append(event_name)
        return pl.DataFrame({"tick": [123]})

    def parse_events(
        self,
        event_name: Sequence[str],
        *,
        player: Sequence[str] | None = None,
        other: Sequence[str] | None = None,
    ) -> list[tuple[str, pl.DataFrame]]:
        return [(name, self.parse_event(name, player=player, other=other)) for name in event_name]

    def parse_player_info(self) -> pl.DataFrame:
        return pl.DataFrame({"name": ["Player"], "steamid": ["76561198000000001"]})


class FailingHeaderBackend(FakeBackend):
    def parse_header(self) -> dict[str, str]:
        raise RuntimeError("third-party failure")


class UnknownFileBackend(FakeBackend):
    def parse_header(self) -> dict[str, str]:
        raise RuntimeError("UnknownFile")


def _request(path: Path) -> ParseRequest:
    return ParseRequest(
        demo_file_id=UUID("00000000-0000-0000-0000-000000000001"),
        sha256="0" * 64,
        path=path,
        options=ParseOptions(
            event_names=("player_death", "player_hurt"),
            player_properties=(),
            other_properties=(),
        ),
    )


def test_adapter_skips_event_absent_from_demo(fake_demo_path: Path) -> None:
    backend: FakeBackend | None = None

    def factory(path: str) -> FakeBackend:
        nonlocal backend
        backend = FakeBackend(path)
        return backend

    adapter = Demoparser2Adapter(parser_factory=factory, installed_version="0.41.4")
    result = adapter.parse(_request(fake_demo_path))

    assert isinstance(adapter, DemoParser)
    assert result.available_events == ("player_death",)
    assert set(result.tables) == {"player_death"}
    assert result.tables["player_death"].height == 1
    assert backend is not None
    assert backend.parse_calls == ["player_death"]


def test_adapter_translates_third_party_failure(fake_demo_path: Path) -> None:
    adapter = Demoparser2Adapter(
        parser_factory=FailingHeaderBackend,
        installed_version="0.41.4",
    )

    with pytest.raises(DemoParseError) as error:
        adapter.parse(_request(fake_demo_path))

    assert "RuntimeError" in str(error.value)
    assert str(fake_demo_path.resolve()) not in str(error.value)


def test_adapter_classifies_unknown_file(fake_demo_path: Path) -> None:
    adapter = Demoparser2Adapter(
        parser_factory=UnknownFileBackend,
        installed_version="0.41.4",
    )

    with pytest.raises(UnsupportedDemoError):
        adapter.parse(_request(fake_demo_path))


def test_adapter_rejects_unexpected_runtime_version() -> None:
    with pytest.raises(ParserContractError):
        Demoparser2Adapter(parser_factory=FakeBackend, installed_version="0.0.0")


def test_adapter_records_individual_event_failure(fake_demo_path: Path) -> None:
    class EventFailureBackend(FakeBackend):
        def parse_event(
            self,
            event_name: str,
            *,
            player: Sequence[str] | None = None,
            other: Sequence[str] | None = None,
        ) -> Any:
            del event_name, player, other
            raise RuntimeError("bad event")

    adapter = Demoparser2Adapter(
        parser_factory=EventFailureBackend,
        installed_version="0.41.4",
    )
    result = adapter.parse(_request(fake_demo_path))

    assert "player_death" in result.event_errors
    assert "player_death" not in result.tables
