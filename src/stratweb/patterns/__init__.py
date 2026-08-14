"""Deterministic cross-match pattern engine contracts."""

from stratweb.patterns.engine import CrossMatchPatternEngine
from stratweb.patterns.models import (
    PATTERN_CONFIDENCE_METHOD,
    PATTERN_RULE_VERSION,
    PATTERN_SCHEMA_VERSION,
    CrossMatchPattern,
    PatternConfig,
    PatternType,
)

__all__ = [
    "PATTERN_CONFIDENCE_METHOD",
    "PATTERN_RULE_VERSION",
    "PATTERN_SCHEMA_VERSION",
    "CrossMatchPattern",
    "CrossMatchPatternEngine",
    "PatternConfig",
    "PatternType",
]
