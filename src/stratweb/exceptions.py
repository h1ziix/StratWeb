"""Stable application exceptions for local demo inspection."""


class DemoInspectionError(Exception):
    """Base class for controlled, user-facing inspection failures."""

    error_code = "demo_inspection_error"


class DemoFileNotFoundError(DemoInspectionError):
    error_code = "demo_file_not_found"


class DemoFileUnreadableError(DemoInspectionError):
    error_code = "demo_file_unreadable"


class DemoParseError(DemoInspectionError):
    error_code = "demo_parse_error"


class UnsupportedDemoError(DemoInspectionError):
    error_code = "unsupported_demo"


class ParserContractError(DemoInspectionError):
    error_code = "parser_contract_error"


class InspectionOutputError(DemoInspectionError):
    error_code = "inspection_output_error"


class InspectionOutputExistsError(InspectionOutputError):
    error_code = "inspection_output_exists"


class PersistenceError(DemoInspectionError):
    """Base class for controlled database and import failures."""

    error_code = "persistence_error"


class ImportJobNotFoundError(PersistenceError):
    error_code = "import_job_not_found"


class ImportJobNotRetryableError(PersistenceError):
    error_code = "import_job_not_retryable"


class OpponentWorkspaceError(PersistenceError):
    error_code = "opponent_workspace_error"


class OpponentNotFoundError(OpponentWorkspaceError):
    error_code = "opponent_not_found"


class OpponentConflictError(OpponentWorkspaceError):
    error_code = "opponent_conflict"


class OpponentSelectionError(OpponentWorkspaceError):
    error_code = "opponent_selection_error"


class DatabaseInitializationError(PersistenceError):
    error_code = "database_initialization_error"


class MigrationChecksumError(DatabaseInitializationError):
    error_code = "migration_checksum_mismatch"


class CanonicalImportError(PersistenceError):
    error_code = "canonical_import_error"


class CanonicalSchemaVersionError(CanonicalImportError):
    error_code = "canonical_schema_version_error"


class DatasetFingerprintMismatchError(CanonicalImportError):
    error_code = "dataset_fingerprint_mismatch"


class FatalValidationError(CanonicalImportError):
    error_code = "fatal_validation_error"


class DatasetIntegrityError(CanonicalImportError):
    error_code = "dataset_integrity_error"


class MatchNotFoundError(PersistenceError):
    error_code = "match_not_found"


class AnalyticsError(PersistenceError):
    error_code = "analytics_error"


class AnalyticsNotFoundError(AnalyticsError):
    error_code = "analytics_not_found"


class AnalyticsIntegrityError(AnalyticsError):
    error_code = "analytics_integrity_error"


class AnalyticsConfigurationError(AnalyticsError):
    error_code = "analytics_configuration_error"


class TemporalError(PersistenceError):
    error_code = "temporal_error"


class TemporalNotFoundError(TemporalError):
    error_code = "temporal_not_found"


class TemporalIntegrityError(TemporalError):
    error_code = "temporal_integrity_error"


class TemporalConfigurationError(TemporalError):
    error_code = "temporal_configuration_error"


class TemporalSnapshotError(TemporalError):
    error_code = "temporal_snapshot_error"


class SpatialError(PersistenceError):
    error_code = "spatial_error"


class SpatialNotFoundError(SpatialError):
    error_code = "spatial_not_found"


class SpatialIntegrityError(SpatialError):
    error_code = "spatial_integrity_error"


class SpatialConfigurationError(SpatialError):
    error_code = "spatial_configuration_error"


class PlaybackIndexError(SpatialError):
    error_code = "playback_index_out_of_range"
