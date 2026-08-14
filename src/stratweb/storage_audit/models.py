"""Typed Stage 9.2a storage-audit contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

STORAGE_AUDIT_SCHEMA_VERSION = "1.0.0"
STORAGE_AUDIT_RULE_VERSION = "duckdb_storage_audit_v1"


class StorageAuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StorageAuditConfig(StorageAuditModel):
    exact_row_counts: bool = True
    scan_json_payload_bytes: bool = True
    benchmark_iterations: int = Field(default=5, ge=1, le=20)
    run_benchmarks: bool = True
    projection_match_counts: tuple[int, ...] = (20, 100, 500)

    @model_validator(mode="after")
    def validate_projections(self) -> StorageAuditConfig:
        if not self.projection_match_counts:
            raise ValueError("at least one projection match count is required")
        if any(item < 1 for item in self.projection_match_counts):
            raise ValueError("projection match counts must be positive")
        if tuple(sorted(set(self.projection_match_counts))) != self.projection_match_counts:
            raise ValueError("projection match counts must be unique and sorted")
        return self


class DatabaseStorageMetrics(StorageAuditModel):
    file_name: str
    file_size_bytes: int = Field(ge=0)
    database_size_text: str
    wal_size_text: str
    block_size_bytes: int = Field(gt=0)
    total_blocks: int = Field(ge=0)
    used_blocks: int = Field(ge=0)
    free_blocks: int = Field(ge=0)
    used_block_bytes: int = Field(ge=0)
    free_block_bytes: int = Field(ge=0)
    table_referenced_unique_blocks: int = Field(ge=0)
    unattributed_used_blocks: int = Field(ge=0)


class TableStorageMetrics(StorageAuditModel):
    schema_name: str
    table_name: str
    estimated_rows: int = Field(ge=0)
    exact_rows: int | None = Field(default=None, ge=0)
    column_count: int = Field(ge=0)
    index_count: int = Field(ge=0)
    storage_segments: int = Field(ge=0)
    compression_segments: dict[str, int]
    referenced_blocks: int = Field(ge=0)
    exclusive_blocks: int = Field(ge=0)
    shared_blocks: int = Field(ge=0)
    approximate_referenced_bytes: int = Field(ge=0)
    json_payload_bytes: int | None = Field(default=None, ge=0)


class StorageRelationshipKind(StrEnum):
    MIRROR = "mirror"
    DERIVED = "derived"


class StorageRelationshipAudit(StorageAuditModel):
    relationship_id: str
    kind: StorageRelationshipKind
    source_table: str
    target_table: str
    available: bool
    source_rows: int | None = Field(default=None, ge=0)
    target_rows: int | None = Field(default=None, ge=0)
    matched_rows: int | None = Field(default=None, ge=0)
    source_only_rows: int | None = Field(default=None, ge=0)
    target_only_rows: int | None = Field(default=None, ge=0)
    source_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    payload_equal_rows: int | None = Field(default=None, ge=0)
    duplicated_payload_bytes: int | None = Field(default=None, ge=0)
    duplicated_columns: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class RunTableAudit(StorageAuditModel):
    table_name: str
    scope_column: str
    total_runs: int = Field(ge=0)
    distinct_scopes: int = Field(ge=0)
    scopes_with_multiple_runs: int = Field(ge=0)
    additional_runs_within_scope: int = Field(ge=0)
    deletion_safe: bool = False
    limitation: str


class QueryBenchmark(StorageAuditModel):
    query_id: str
    query_shape: str
    available: bool
    iterations: int = Field(ge=0)
    returned_rows: int | None = Field(default=None, ge=0)
    minimum_ms: float | None = Field(default=None, ge=0.0)
    median_ms: float | None = Field(default=None, ge=0.0)
    p95_ms: float | None = Field(default=None, ge=0.0)
    maximum_ms: float | None = Field(default=None, ge=0.0)
    limitation: str | None = None


class ScaleProjection(StorageAuditModel):
    match_count: int = Field(ge=1)
    projected_file_size_bytes: int | None = Field(default=None, ge=0)
    method: str
    limitation: str


class StorageAuditSummary(StorageAuditModel):
    tables: int = Field(ge=0)
    secondary_indexes: int = Field(ge=0)
    reported_indexes_including_constraints: int = Field(ge=0)
    matches: int = Field(ge=0)
    exact_rows: int | None = Field(default=None, ge=0)
    json_payload_bytes: int | None = Field(default=None, ge=0)
    relationships_available: int = Field(ge=0)
    benchmark_queries_available: int = Field(ge=0)


class StorageAuditReport(StorageAuditModel):
    schema_version: str = STORAGE_AUDIT_SCHEMA_VERSION
    rule_version: str = STORAGE_AUDIT_RULE_VERSION
    observed_at: datetime
    duckdb_version: str
    config: StorageAuditConfig
    database: DatabaseStorageMetrics
    summary: StorageAuditSummary
    tables: tuple[TableStorageMetrics, ...]
    relationships: tuple[StorageRelationshipAudit, ...]
    run_tables: tuple[RunTableAudit, ...]
    benchmarks: tuple[QueryBenchmark, ...]
    projections: tuple[ScaleProjection, ...]
    warnings: tuple[str, ...]


__all__ = [name for name in globals() if not name.startswith("_")]
