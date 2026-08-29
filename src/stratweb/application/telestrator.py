"""Versioned, non-evidentiary coach drawings for the 2D map."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TELESTRATOR_SCHEMA_VERSION = "1.0.0"
TELESTRATOR_MAX_ANNOTATIONS = 200
TELESTRATOR_MAX_TOTAL_POINTS = 10_000


class TelestratorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TelestratorTool(StrEnum):
    PENCIL = "pencil"
    ARROW = "arrow"
    ZONE = "zone"
    TEXT = "text"


class NormalizedPoint(TelestratorModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class TelestratorAnnotation(TelestratorModel):
    annotation_id: UUID
    tool: TelestratorTool
    points: tuple[NormalizedPoint, ...] = Field(min_length=1, max_length=512)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    width: float = Field(ge=1, le=12, allow_inf_nan=False)
    text: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_geometry(self) -> TelestratorAnnotation:
        if self.tool is TelestratorTool.PENCIL and len(self.points) < 2:
            raise ValueError("pencil annotation requires at least two points")
        if self.tool in {TelestratorTool.ARROW, TelestratorTool.ZONE} and len(self.points) != 2:
            raise ValueError("arrow and zone annotations require exactly two points")
        if self.tool is TelestratorTool.TEXT:
            if len(self.points) != 1 or not self.text or not self.text.strip():
                raise ValueError("text annotation requires one point and non-empty text")
        elif self.text is not None:
            raise ValueError("only text annotations may contain text")
        return self


class TelestratorBoardUpdate(TelestratorModel):
    expected_revision: int = Field(ge=0)
    annotations: tuple[TelestratorAnnotation, ...] = Field(max_length=TELESTRATOR_MAX_ANNOTATIONS)

    @model_validator(mode="after")
    def validate_total_points(self) -> TelestratorBoardUpdate:
        if sum(len(item.points) for item in self.annotations) > TELESTRATOR_MAX_TOTAL_POINTS:
            raise ValueError("telestrator board has too many total points")
        return self


class TelestratorBoard(TelestratorModel):
    board_id: UUID
    match_id: UUID
    round_number: int = Field(ge=1)
    schema_version: Literal["1.0.0"] = TELESTRATOR_SCHEMA_VERSION
    revision: int = Field(ge=0)
    annotations: tuple[TelestratorAnnotation, ...] = Field(max_length=TELESTRATOR_MAX_ANNOTATIONS)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_total_points(self) -> TelestratorBoard:
        if sum(len(item.points) for item in self.annotations) > TELESTRATOR_MAX_TOTAL_POINTS:
            raise ValueError("telestrator board has too many total points")
        return self


class TelestratorConflictError(RuntimeError):
    """Raised instead of silently overwriting edits from another browser tab."""


class TelestratorRoundNotFoundError(RuntimeError):
    """Raised when a board points to a round that does not exist."""


__all__ = [
    "NormalizedPoint",
    "TELESTRATOR_MAX_ANNOTATIONS",
    "TELESTRATOR_MAX_TOTAL_POINTS",
    "TELESTRATOR_SCHEMA_VERSION",
    "TelestratorAnnotation",
    "TelestratorBoard",
    "TelestratorBoardUpdate",
    "TelestratorConflictError",
    "TelestratorRoundNotFoundError",
    "TelestratorTool",
]
