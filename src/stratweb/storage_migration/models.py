"""Typed Stage 9.2b Storage Engine V2 migration contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

STORAGE_MIGRATION_SCHEMA_VERSION = "1.0.0"
STORAGE_MIGRATION_RULE_VERSION = "canonical_index_migration_v1"


class StorageMigrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StorageMigrationConfig(StorageMigrationModel):
    benchmark_iterations: int = Field(default=5, ge=1, le=20)
    maximum_median_ratio: float = Field(default=2.0, ge=1.0, le=10.0)
    maximum_absolute_regression_ms: float = Field(default=10.0, ge=0.0, le=1000.0)


class StorageLayoutCounts(StorageMigrationModel):
    spatial_canonical: int = Field(ge=0)
    spatial_legacy: int = Field(ge=0)
    bomb_canonical: int = Field(ge=0)
    bomb_legacy: int = Field(ge=0)


class StorageLayoutStatus(StorageMigrationModel):
    schema_version: str
    active_layout: str
    status: str
    v2_schema_available: bool
    v2_index_count: int = Field(ge=0)
    activated_at: datetime | None = None
    counts: StorageLayoutCounts
    latest_migration_id: str | None = None
    latest_migration_status: str | None = None


class BackupVerification(StorageMigrationModel):
    backup_file_name: str
    backup_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size_bytes: int = Field(ge=0)
    backup_size_bytes: int = Field(ge=0)
    source_tables: int = Field(ge=0)
    verified_tables: int = Field(ge=0)
    verified_rows: int = Field(ge=0)
    schema_migration_rows: int = Field(ge=0)
    verified: bool


class LookupParity(StorageMigrationModel):
    relationship: str
    canonical_rows: int = Field(ge=0)
    lookup_rows: int = Field(ge=0)
    resolved_payload_rows: int = Field(ge=0)
    missing_lookup_rows: int = Field(ge=0)
    orphan_lookup_rows: int = Field(ge=0)
    field_mismatch_rows: int = Field(ge=0)
    passed: bool


class LookupBenchmark(StorageMigrationModel):
    query_id: str
    iterations: int = Field(ge=1)
    returned_rows: int = Field(ge=0)
    payloads_equal: bool
    legacy_median_ms: float = Field(ge=0.0)
    v2_median_ms: float = Field(ge=0.0)
    permitted_v2_median_ms: float = Field(ge=0.0)
    passed: bool


class StorageMigrationReport(StorageMigrationModel):
    schema_version: str = STORAGE_MIGRATION_SCHEMA_VERSION
    rule_version: str = STORAGE_MIGRATION_RULE_VERSION
    migration_id: str
    started_at: datetime
    completed_at: datetime
    duckdb_version: str
    source_file_name: str
    source_size_before: int = Field(ge=0)
    source_size_after: int = Field(ge=0)
    backup: BackupVerification
    config: StorageMigrationConfig
    parity: tuple[LookupParity, ...]
    benchmarks: tuple[LookupBenchmark, ...]
    activated: bool
    status: StorageLayoutStatus
    warnings: tuple[str, ...]


class StorageRollbackReport(StorageMigrationModel):
    schema_version: str = STORAGE_MIGRATION_SCHEMA_VERSION
    rule_version: str = STORAGE_MIGRATION_RULE_VERSION
    completed_at: datetime
    restored_spatial_rows: int = Field(ge=0)
    restored_bomb_rows: int = Field(ge=0)
    parity: tuple[LookupParity, ...]
    status: StorageLayoutStatus
    warnings: tuple[str, ...]
