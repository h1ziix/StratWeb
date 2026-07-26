"""Transport contracts shared between application ports.

These objects are intentionally independent of FastAPI's ``UploadFile`` and of
demoparser2's concrete ``DemoParser`` class. Polars is the chosen in-process table
format, not a parser-specific dependency.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import polars as pl

from stratweb.domain.enums import CanonicalTable
from stratweb.domain.models import AnalysisFinding, DemoFile


@dataclass(frozen=True, slots=True)
class ParserIdentity:
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class StoredDemoFile:
    original_filename: str
    internal_filename: str
    path: Path
    storage_key: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    demo_file: DemoFile
    duplicate_of_id: UUID | None = None

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of_id is not None


@dataclass(frozen=True, slots=True)
class ParseOptions:
    """Requested source data; exact source columns are owned by the adapter."""

    event_names: tuple[str, ...]
    player_properties: tuple[str, ...]
    other_properties: tuple[str, ...]
    include_grenade_trajectories: bool = True
    position_sample_interval_ticks: int = 16


@dataclass(frozen=True, slots=True)
class ParseRequest:
    demo_file_id: UUID
    sha256: str
    path: Path
    options: ParseOptions


@dataclass(frozen=True, slots=True)
class ParsedDemo:
    """Raw parser output plus provenance, before canonical normalization."""

    demo_file_id: UUID
    parser: ParserIdentity
    header: Mapping[str, Any]
    tables: Mapping[str, pl.DataFrame]
    available_events: tuple[str, ...] = ()
    player_info: pl.DataFrame | None = None
    event_errors: Mapping[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisScope:
    match_ids: tuple[UUID, ...]
    opponent_team_ids: tuple[UUID, ...]
    map_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisDataset:
    """Immutable logical snapshot consumed by deterministic analysis rules."""

    scope: AnalysisScope
    dataset_fingerprint: str
    tables: Mapping[CanonicalTable, pl.DataFrame]


@dataclass(frozen=True, slots=True)
class AnalysisConfiguration:
    version: str
    sha256: str
    values: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReportRequest:
    title: str
    findings: tuple[AnalysisFinding, ...]
    format: str = "markdown"


@dataclass(frozen=True, slots=True)
class ReportArtifact:
    filename: str
    media_type: str
    content: bytes
    finding_ids: tuple[UUID, ...]
