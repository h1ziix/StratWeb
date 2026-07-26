from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from stratweb.adapters.parsers.demoparser2_spatial import Demoparser2SpatialExtractor


class FakeFrame:
    columns = (
        "tick",
        "steamid",
        "name",
        "X",
        "Y",
        "Z",
        "pitch",
        "yaw",
        "is_alive",
        "team_num",
        "inventory_as_ids",
    )

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return [
            {
                "tick": 110,
                "steamid": "76561198000000001",
                "name": "Alpha",
                "X": 12.5,
                "Y": -7.0,
                "Z": 4.0,
                "pitch": 3.0,
                "yaw": 91.0,
                "is_alive": True,
                "team_num": 2,
                "inventory_as_ids": [7, 49],
            }
        ]


class FakeBackend:
    def __init__(self) -> None:
        self.props: tuple[str, ...] = ()
        self.ticks: tuple[int, ...] = ()

    def parse_ticks(self, wanted_props: Any, *, ticks: Any, **_: Any) -> FakeFrame:
        self.props = tuple(wanted_props)
        self.ticks = tuple(ticks)
        return FakeFrame()


def test_demoparser2_spatial_adapter_uses_pinned_real_parse_ticks_contract(
    tmp_path: Path,
) -> None:
    demo = tmp_path / "contract.dem"
    demo.write_bytes(b"PBDEMS2\x00spatial-contract")
    sha = hashlib.sha256(demo.read_bytes()).hexdigest()
    backend = FakeBackend()
    extractor = Demoparser2SpatialExtractor(
        parser_factory=lambda _: backend,
        installed_version="0.41.4",
    )

    result = extractor.extract(demo, (110,), expected_sha256=sha)

    assert backend.ticks == (110,)
    assert backend.props == (
        "X",
        "Y",
        "Z",
        "pitch",
        "yaw",
        "is_alive",
        "team_num",
        "inventory_as_ids",
    )
    assert result.parser_version == "0.41.4"
    assert result.samples[0].inventory_item_ids == (7, 49)
    assert result.samples[0].x == 12.5


def test_demoparser2_spatial_adapter_reports_nonfinite_values(tmp_path: Path) -> None:
    demo = tmp_path / "nonfinite.dem"
    demo.write_bytes(b"PBDEMS2\x00nonfinite")
    sha = hashlib.sha256(demo.read_bytes()).hexdigest()
    backend = FakeBackend()
    frame = FakeFrame()
    original = frame.to_dict

    def records(*, orient: str) -> list[dict[str, Any]]:
        rows = original(orient=orient)
        rows[0]["X"] = float("nan")
        rows[0]["yaw"] = float("inf")
        return rows

    frame.to_dict = records  # type: ignore[method-assign]
    backend.parse_ticks = lambda *args, **kwargs: frame  # type: ignore[method-assign]
    result = Demoparser2SpatialExtractor(
        parser_factory=lambda _: backend, installed_version="0.41.4"
    ).extract(demo, (110,), expected_sha256=sha)

    assert result.invalid_numeric_value_count == 2
    assert result.samples[0].x is None
    assert result.samples[0].yaw is None
    assert result.warnings == ("nonfinite_spatial_values_coerced_to_unavailable:2",)
