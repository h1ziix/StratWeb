"""Persistence adapters for canonical datasets."""

from stratweb.adapters.persistence.analytics_duckdb import DuckDBAnalyticsRepository
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.adapters.persistence.import_jobs_duckdb import DuckDBImportJobRepository
from stratweb.adapters.persistence.opponents_duckdb import DuckDBOpponentRepository
from stratweb.adapters.persistence.spatial_duckdb import DuckDBSpatialRepository
from stratweb.adapters.persistence.temporal_duckdb import DuckDBTemporalRepository

__all__ = [
    "DuckDBAnalyticsRepository",
    "DuckDBImportJobRepository",
    "DuckDBMatchRepository",
    "DuckDBOpponentRepository",
    "DuckDBSpatialRepository",
    "DuckDBTemporalRepository",
]
