"""Local analyst annotations kept outside deterministic tactical evidence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ANALYST_NOTE_SCHEMA_VERSION = "1.0.0"
ANALYST_NOTE_MAX_LENGTH = 2_000


class AnalystNote(BaseModel):
    """One editable local note pinned to an exact Tactical V2 insight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: UUID
    profile_id: UUID
    tactical_run_id: UUID
    insight_id: UUID
    body: str = Field(min_length=1, max_length=ANALYST_NOTE_MAX_LENGTH)
    note_schema_version: str = ANALYST_NOTE_SCHEMA_VERSION
    created_at: datetime
    updated_at: datetime


def normalize_analyst_note(value: str) -> str:
    """Normalize line endings without inventing or rewording analyst content."""

    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in normalized:
        raise ValueError("Заметка не может содержать нулевой символ.")
    if not normalized:
        raise ValueError("Заметка не может быть пустой.")
    if len(normalized) > ANALYST_NOTE_MAX_LENGTH:
        raise ValueError(f"Заметка не может быть длиннее {ANALYST_NOTE_MAX_LENGTH} символов.")
    return normalized


__all__ = [
    "ANALYST_NOTE_MAX_LENGTH",
    "ANALYST_NOTE_SCHEMA_VERSION",
    "AnalystNote",
    "normalize_analyst_note",
]
