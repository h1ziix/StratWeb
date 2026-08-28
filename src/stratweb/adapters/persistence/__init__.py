"""Persistence adapters for canonical datasets."""

from stratweb.adapters.persistence.analyst_notes_duckdb import DuckDBAnalystNoteRepository
from stratweb.adapters.persistence.analytics_duckdb import DuckDBAnalyticsRepository
from stratweb.adapters.persistence.counter_strategy_duckdb import (
    DuckDBCounterStrategyRepository,
)
from stratweb.adapters.persistence.critical_mistakes_duckdb import (
    DuckDBCriticalMistakesRepository,
)
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.adapters.persistence.economy_duckdb import DuckDBEconomyRepository
from stratweb.adapters.persistence.findings_duckdb import DuckDBAnalysisRepository
from stratweb.adapters.persistence.head_to_head_duckdb import DuckDBHeadToHeadRepository
from stratweb.adapters.persistence.import_batches_duckdb import DuckDBImportBatchRepository
from stratweb.adapters.persistence.import_jobs_duckdb import DuckDBImportJobRepository
from stratweb.adapters.persistence.opponents_duckdb import DuckDBOpponentRepository
from stratweb.adapters.persistence.patterns_duckdb import DuckDBPatternRepository
from stratweb.adapters.persistence.round_features_duckdb import DuckDBRoundFeatureRepository
from stratweb.adapters.persistence.spatial_duckdb import DuckDBSpatialRepository
from stratweb.adapters.persistence.statistical_trust_duckdb import (
    DuckDBStatisticalTrustRepository,
)
from stratweb.adapters.persistence.tactical_v2_duckdb import (
    DuckDBTacticalV2Repository,
    DuckDBTacticalV2SourceRepository,
)
from stratweb.adapters.persistence.team_names_duckdb import DuckDBTeamNameRepository
from stratweb.adapters.persistence.temporal_duckdb import DuckDBTemporalRepository
from stratweb.adapters.persistence.zone_assignments_duckdb import (
    DuckDBZoneAssignmentRepository,
)

__all__ = [
    "DuckDBAnalyticsRepository",
    "DuckDBAnalystNoteRepository",
    "DuckDBEconomyRepository",
    "DuckDBAnalysisRepository",
    "DuckDBCounterStrategyRepository",
    "DuckDBCriticalMistakesRepository",
    "DuckDBImportJobRepository",
    "DuckDBImportBatchRepository",
    "DuckDBHeadToHeadRepository",
    "DuckDBMatchRepository",
    "DuckDBOpponentRepository",
    "DuckDBPatternRepository",
    "DuckDBRoundFeatureRepository",
    "DuckDBSpatialRepository",
    "DuckDBStatisticalTrustRepository",
    "DuckDBTacticalV2Repository",
    "DuckDBTacticalV2SourceRepository",
    "DuckDBTemporalRepository",
    "DuckDBTeamNameRepository",
    "DuckDBZoneAssignmentRepository",
]
