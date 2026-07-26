from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stratweb import cli
from stratweb.analytics.definitions import config_hash
from stratweb.analytics.models import (
    AnalyticsConfig,
    TickrateEvidence,
    TradeWindowConfig,
    TradeWindowMode,
)
from stratweb.application.analytics import resolve_analytics_config
from stratweb.exceptions import AnalyticsConfigurationError


def test_trade_window_modes_cannot_be_combined() -> None:
    with pytest.raises(ValidationError):
        TradeWindowConfig(
            mode=TradeWindowMode.TICKS,
            requested_ticks=320,
            requested_seconds=5.0,
            resolved_ticks=320,
        )


def test_resolver_defaults_to_320_authoritative_ticks() -> None:
    config = resolve_analytics_config(
        requested_ticks=None,
        requested_seconds=None,
        tickrate_evidence=None,
    )

    assert config.trade_window == TradeWindowConfig.ticks(320)


@pytest.mark.parametrize("ticks", [0, -1])
def test_invalid_ticks_are_rejected_instead_of_becoming_default(ticks: int) -> None:
    with pytest.raises(AnalyticsConfigurationError, match="greater than zero"):
        resolve_analytics_config(
            requested_ticks=ticks,
            requested_seconds=None,
            tickrate_evidence=None,
        )


def test_seconds_mode_requires_proven_tickrate() -> None:
    with pytest.raises(AnalyticsConfigurationError, match="proven canonical tickrate"):
        resolve_analytics_config(
            requested_ticks=None,
            requested_seconds=5.0,
            tickrate_evidence=None,
        )


def test_seconds_mode_uses_evidence_and_changes_config_identity() -> None:
    seconds = resolve_analytics_config(
        requested_ticks=None,
        requested_seconds=5.0,
        tickrate_evidence=TickrateEvidence(
            tickrate=64.0,
            source="canonical_metadata:test",
        ),
    )
    ticks = AnalyticsConfig(trade_window=TradeWindowConfig.ticks(320))

    assert seconds.trade_window.resolved_ticks == ticks.trade_window.resolved_ticks == 320
    assert seconds.trade_window.mode is TradeWindowMode.SECONDS
    assert config_hash(seconds) != config_hash(ticks)


def test_seconds_mode_rejects_conflicting_tickrate_evidence() -> None:
    with pytest.raises(AnalyticsConfigurationError, match="conflicting tickrate"):
        resolve_analytics_config(
            requested_ticks=None,
            requested_seconds=5.0,
            tickrate_evidence=TickrateEvidence(
                tickrate=64.0,
                source="canonical_metadata:a",
                conflicting_sources=("canonical_metadata:b",),
            ),
        )


def test_cli_rejects_seconds_without_proven_canonical_tickrate(tmp_path: Path, capsys: Any) -> None:
    result = cli.main(
        [
            "analytics",
            "compute",
            str(uuid4()),
            "--trade-window-seconds",
            "5",
            "--db",
            str(tmp_path / "analytics.duckdb"),
        ]
    )

    assert result == 9
    error = capsys.readouterr().err
    assert "analytics_configuration_error" in error
    assert "proven canonical tickrate" in error


def test_cli_flags_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        cli.build_argument_parser().parse_args(
            [
                "analytics",
                "compute",
                str(uuid4()),
                "--trade-window-ticks",
                "320",
                "--trade-window-seconds",
                "5",
            ]
        )
