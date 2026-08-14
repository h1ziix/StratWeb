"""Presentation-only team labels kept separate from canonical team identity."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TeamNameSource(StrEnum):
    MANUAL = "manual"
    FACEIT_METADATA = "faceit_metadata"


class TeamDisplayLabel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    match_id: UUID
    team_id: UUID
    display_name: str = Field(min_length=1, max_length=100)
    source: TeamNameSource
    source_reference: str | None = Field(default=None, max_length=500)
    updated_at: datetime


def normalize_team_display_name(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Название команды не может быть пустым.")
    if len(normalized) > 100:
        raise ValueError("Название команды не может быть длиннее 100 символов.")
    return normalized


__all__ = ["TeamDisplayLabel", "TeamNameSource", "normalize_team_display_name"]
