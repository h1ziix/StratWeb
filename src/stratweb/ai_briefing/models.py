"""Versioned contracts for optional, source-bound AI rephrasing."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from stratweb.application.canonical_models import Sha256

AI_BRIEFING_SCHEMA_VERSION: Final = "1.0.0"
AI_BRIEFING_RULE_VERSION: Final = "source_bound_rephrasing_v1"
AI_BRIEFING_PROMPT_VERSION: Final = "coach_briefing_ru_v3"

_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")
_ABSOLUTE_CLAIMS = (
    "всегда",
    "никогда",
    "гарантирован",
    "точно выигра",
    "обязательно выигра",
)
_BANNED_TRANSLATIONS = (
    "утилит",
    "вращени",
    "вращай",
    "живых данных",
    "живые данные",
    "играй на равенство",
    "переусердств",
)


class AiBriefingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BriefingSourceItem(AiBriefingModel):
    """One immutable deterministic recommendation offered for rephrasing."""

    source_id: UUID
    finding_id: UUID
    map_name: str = Field(min_length=1, max_length=100)
    side: Literal["T", "CT", "UNKNOWN"]
    title: str = Field(min_length=1, max_length=300)
    observation: str = Field(min_length=1, max_length=1200)
    tactical_interpretation: str = Field(min_length=1, max_length=1200)
    recommended_response: str = Field(min_length=1, max_length=1200)
    avoid: str = Field(min_length=1, max_length=1200)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=1)
    frequency: float = Field(ge=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    evidence_match_count: int = Field(ge=1)
    evidence_count: int = Field(ge=1)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_statistics(self) -> BriefingSourceItem:
        if self.numerator > self.denominator:
            raise ValueError("source numerator cannot exceed denominator")
        if self.sample_size != self.denominator:
            raise ValueError("source sample size must equal denominator")
        if abs(self.frequency - self.numerator / self.denominator) > 1e-12:
            raise ValueError("source frequency must match its ratio")
        return self


class BriefingSourceBundle(AiBriefingModel):
    """Pinned source facts; the LLM receives text but never owns their calculations."""

    source_fingerprint: Sha256
    profile_id: UUID
    strategy_run_id: UUID
    strategy_fingerprint: Sha256
    display_name: str = Field(min_length=1, max_length=100)
    locale: Literal["ru"] = "ru"
    sources: tuple[BriefingSourceItem, ...] = Field(min_length=1, max_length=6)


class AiBriefingPoint(AiBriefingModel):
    """A short rephrasing tied to exactly one deterministic source."""

    text: str = Field(min_length=5, max_length=360)
    source_id: UUID


class AiBriefingContent(AiBriefingModel):
    """Constrained model output. Numbers remain outside free-form AI text."""

    expect: tuple[AiBriefingPoint, ...] = Field(default=(), max_length=3)
    play: tuple[AiBriefingPoint, ...] = Field(default=(), max_length=3)
    avoid: tuple[AiBriefingPoint, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def reject_unsafe_language(self) -> AiBriefingContent:
        points = (*self.expect, *self.play, *self.avoid)
        if not points:
            raise ValueError("briefing must contain at least one point")
        for point in points:
            normalized = point.text.casefold()
            if any(claim in normalized for claim in _ABSOLUTE_CLAIMS):
                raise ValueError("AI briefing text cannot make absolute claims")
            if any(term in normalized for term in _BANNED_TRANSLATIONS):
                raise ValueError("AI briefing text contains an unnatural CS2 translation")
        return self


class AiBriefingArtifact(AiBriefingModel):
    """Persisted, reproducible AI draft plus the original deterministic source."""

    briefing_schema_version: str = AI_BRIEFING_SCHEMA_VERSION
    briefing_rule_version: str = AI_BRIEFING_RULE_VERSION
    prompt_version: str = AI_BRIEFING_PROMPT_VERSION
    briefing_id: UUID
    briefing_fingerprint: Sha256
    profile_id: UUID
    strategy_run_id: UUID
    provider: Literal["ollama"] = "ollama"
    model_name: str = Field(min_length=1)
    model_digest: Sha256
    temperature: float = Field(default=0, ge=0, le=0)
    source: BriefingSourceBundle
    content: AiBriefingContent
    created_at: datetime

    @model_validator(mode="after")
    def validate_source_links(self) -> AiBriefingArtifact:
        if self.profile_id != self.source.profile_id:
            raise ValueError("briefing profile differs from source profile")
        if self.strategy_run_id != self.source.strategy_run_id:
            raise ValueError("briefing strategy run differs from source run")
        allowed = {item.source_id for item in self.source.sources}
        sources = {item.source_id: item for item in self.source.sources}
        referenced = {
            point.source_id
            for point in (*self.content.expect, *self.content.play, *self.content.avoid)
        }
        if not referenced.issubset(allowed):
            raise ValueError("AI briefing references a source outside the pinned bundle")
        sections = (
            (self.content.expect, "observation"),
            (self.content.play, "recommended_response"),
            (self.content.avoid, "avoid"),
        )
        for points, field_name in sections:
            for point in points:
                source = sources[point.source_id]
                source_text = " ".join(
                    (source.map_name, source.title, str(getattr(source, field_name)))
                )
                allowed_numbers = set(_NUMBER_PATTERN.findall(source_text))
                output_numbers = set(_NUMBER_PATTERN.findall(point.text))
                if not output_numbers.issubset(allowed_numbers):
                    raise ValueError("AI briefing introduced a number absent from its source text")
        return self


__all__ = [name for name in globals() if not name.startswith("_")]
