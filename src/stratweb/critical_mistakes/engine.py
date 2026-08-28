"""Pure deterministic aggregation of critical-round evidence."""

from __future__ import annotations

import hashlib
from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.critical_mistakes.models import (
    CRITICAL_MISTAKES_RULE_VERSION,
    CRITICAL_MISTAKES_SCHEMA_VERSION,
    CriticalMistake,
    CriticalMistakesInput,
    CriticalMistakesRun,
    CriticalMistakesSummary,
    CriticalMistakeType,
)


class CriticalMistakeEngine:
    """Aggregate only typed source candidates; never invent missing state."""

    def compute(self, data: CriticalMistakesInput) -> CriticalMistakesRun:
        counts = Counter(item.mistake_type for item in data.candidates)
        fingerprint_payload = {
            "schema": CRITICAL_MISTAKES_SCHEMA_VERSION,
            "rules": CRITICAL_MISTAKES_RULE_VERSION,
            "profile_id": str(data.profile_id),
            "sources": [item.model_dump(mode="json") for item in data.source_pins],
            "eligible_counts": {key.value: value for key, value in data.eligible_counts.items()},
            "candidates": [item.model_dump(mode="json") for item in data.candidates],
        }
        fingerprint = hashlib.sha256(canonical_json(fingerprint_payload).encode()).hexdigest()
        run_id = uuid5(NAMESPACE_URL, f"stratweb:critical:{fingerprint}")
        mistakes = []
        for candidate in sorted(
            data.candidates,
            key=lambda item: (
                item.evidence.match_id.hex,
                item.evidence.round_number,
                item.mistake_type.value,
                item.evidence.tick or -1,
            ),
        ):
            denominator = data.eligible_counts[candidate.mistake_type]
            numerator = counts[candidate.mistake_type]
            identity = canonical_json(candidate.model_dump(mode="json"))
            mistakes.append(
                CriticalMistake(
                    mistake_id=uuid5(NAMESPACE_URL, f"stratweb:critical:item:{identity}"),
                    critical_run_id=run_id,
                    mistake_type=candidate.mistake_type,
                    map_name=candidate.map_name,
                    side=candidate.side,
                    title=candidate.title,
                    observation=candidate.observation,
                    tactical_interpretation=candidate.tactical_interpretation,
                    recommendation=candidate.recommendation,
                    numerator=numerator,
                    denominator=denominator,
                    frequency=numerator / denominator,
                    sample_size=denominator,
                    evidence=candidate.evidence,
                    limitations=data.limitations.get(candidate.mistake_type, ()),
                )
            )
        summary = CriticalMistakesSummary(
            total=len(mistakes),
            lost_plus_two=counts[CriticalMistakeType.LOST_PLUS_TWO],
            lost_vs_full_eco=counts[CriticalMistakeType.LOST_VS_FULL_ECO],
            early_untraded_death=counts[CriticalMistakeType.EARLY_UNTRADED_DEATH],
        )
        return CriticalMistakesRun(
            critical_run_id=run_id,
            critical_fingerprint=fingerprint,
            profile_id=data.profile_id,
            source_pins=data.source_pins,
            capabilities=data.capabilities,
            mistakes=tuple(mistakes),
            summary=summary,
            warnings=tuple(sorted(set(data.warnings))),
        )


__all__ = ["CriticalMistakeEngine"]
