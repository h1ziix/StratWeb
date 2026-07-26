"""Shared deterministic temporal definitions and capability helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from stratweb.application.normalization_utils import canonical_json

from .models import (
    TemporalAvailabilityStatus,
    TemporalCapability,
    TemporalConfig,
    TemporalConversionStatus,
    TemporalTime,
    TemporalUnavailableReason,
)


def temporal_config_hash(config: TemporalConfig) -> str:
    return hashlib.sha256(canonical_json(config.model_dump(mode="json")).encode()).hexdigest()


def first_available_tick(*values: int | None) -> int | None:
    """Return the first proven tick; tick zero is a valid value, not missing data."""
    return next((value for value in values if value is not None), None)


def temporal_time(tick: int, config: TemporalConfig) -> TemporalTime:
    if config.tickrate is None:
        return TemporalTime(
            tick=tick,
            conversion_status=TemporalConversionStatus.UNAVAILABLE,
        )
    return TemporalTime(
        tick=tick,
        seconds=tick / config.tickrate,
        conversion_status=TemporalConversionStatus.AVAILABLE,
        conversion_source=config.tickrate_source,
        tickrate=config.tickrate,
    )


def capability(
    population: int,
    covered: int,
    reasons: Iterable[TemporalUnavailableReason] = (),
    *,
    unresolved: bool = False,
) -> TemporalCapability:
    unique_reasons = tuple(dict.fromkeys(reasons))
    if population == 0:
        return TemporalCapability(
            status=TemporalAvailabilityStatus.UNAVAILABLE,
            reasons=(TemporalUnavailableReason.NO_POPULATION,),
            population=0,
            covered=0,
        )
    if unresolved:
        status = TemporalAvailabilityStatus.UNRESOLVED
    elif covered == population and not unique_reasons:
        status = TemporalAvailabilityStatus.AVAILABLE
    elif covered:
        status = TemporalAvailabilityStatus.PARTIAL
    else:
        status = TemporalAvailabilityStatus.UNAVAILABLE
    return TemporalCapability(
        status=status,
        reasons=() if status is TemporalAvailabilityStatus.AVAILABLE else unique_reasons,
        population=population,
        covered=covered,
    )


def aggregate_capabilities(capabilities: Iterable[TemporalCapability]) -> TemporalCapability:
    values = tuple(capabilities)
    population = sum(item.population for item in values)
    covered = sum(item.covered for item in values)
    reasons = tuple(reason for item in values for reason in item.reasons)
    return capability(
        population,
        covered,
        reasons,
        unresolved=any(item.status is TemporalAvailabilityStatus.UNRESOLVED for item in values),
    )
