"""Command-line entry point for offline inspection and canonical persistence."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, TypeAdapter

from stratweb.adapters.parsers import (
    Demoparser2Adapter,
    Demoparser2EconomyExtractor,
    Demoparser2SpatialExtractor,
)
from stratweb.adapters.persistence import (
    DuckDBAnalysisRepository,
    DuckDBAnalyticsRepository,
    DuckDBCounterStrategyRepository,
    DuckDBEconomyRepository,
    DuckDBMatchRepository,
    DuckDBOpponentRepository,
    DuckDBPatternRepository,
    DuckDBRoundFeatureRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
    DuckDBZoneAssignmentRepository,
)
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.application.analytics import (
    AnalyticsQueryService,
    ComputeMatchAnalyticsService,
    resolve_analytics_config,
)
from stratweb.application.canonical_models import CanonicalizationSummary
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.counter_strategy import (
    ComputeCounterStrategiesService,
    CounterStrategyQueryService,
    ValidateCounterStrategiesService,
)
from stratweb.application.economy import ComputeEconomyService, EconomyQueryService
from stratweb.application.findings import (
    AnalysisFindingQueryService,
    ComputeAnalysisFindingsService,
)
from stratweb.application.inspection import DemoInspectionService
from stratweb.application.patterns import (
    ComputeCrossMatchPatternsService,
    PatternQueryService,
)
from stratweb.application.persistence import (
    ImportCanonicalMatchService,
    MatchQueryService,
    resolve_database_path,
)
from stratweb.application.persistence_models import (
    DatabaseInitResult,
    DeleteMatchResult,
    ImportStatus,
    MatchQueryFilters,
)
from stratweb.application.readiness import FindingReadinessService
from stratweb.application.round_features import (
    ComputeRoundFeaturesService,
    RoundFeatureQueryService,
)
from stratweb.application.spatial import ComputeSpatialStateService, SpatialQueryService
from stratweb.application.temporal import ComputeTemporalStateService, TemporalQueryService
from stratweb.application.zone_assignments import (
    ComputeZoneAssignmentsService,
    ZoneAssignmentQueryService,
)
from stratweb.counter_strategy.models import CounterStrategyCategory, CounterStrategyConfig
from stratweb.counter_strategy.validation_models import StrategyValidationConfig
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType, EconomyConfig
from stratweb.exceptions import (
    CanonicalImportError,
    DemoFileNotFoundError,
    DemoFileUnreadableError,
    DemoInspectionError,
    InspectionOutputError,
    InspectionOutputExistsError,
    ParserContractError,
    PersistenceError,
    UnsupportedDemoError,
)
from stratweb.features.models import (
    FeatureAvailability,
    RoundFeatureConfig,
    RoundFeatureType,
)
from stratweb.findings.models import FindingCategory, FindingConfig
from stratweb.golden_corpus.evaluation import GoldenFindingEvaluator
from stratweb.golden_corpus.manifest import (
    GoldenCorpusError,
    GoldenCorpusValidator,
    load_manifest,
    load_predictions,
)
from stratweb.golden_corpus.runner import GoldenCorpusRunner
from stratweb.patterns.models import PatternAvailability, PatternConfig, PatternType
from stratweb.readiness.models import FindingReadinessConfig
from stratweb.spatial.models import SpatialConfig
from stratweb.temporal.models import TemporalConfig
from stratweb.zones.assignment_models import ZoneAssignmentConfig, ZoneAssignmentStatus

_EXIT_UNEXPECTED = 1
_EXIT_FILE_NOT_FOUND = 3
_EXIT_FILE_UNREADABLE = 4
_EXIT_UNSUPPORTED = 5
_EXIT_PARSE_OR_CONTRACT = 6
_EXIT_OUTPUT = 7
_EXIT_FATAL_VALIDATION = 8
_EXIT_PERSISTENCE = 9
_EXIT_CANONICAL_IMPORT = 10
_EXIT_CORPUS = 11


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stratweb",
        description="Offline tools for completed Counter-Strike 2 demos.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_inspect_command(subparsers)
    _add_normalize_command(subparsers)
    _add_database_commands(subparsers)
    _add_import_command(subparsers)
    _add_match_commands(subparsers)
    _add_round_commands(subparsers)
    _add_analytics_commands(subparsers)
    _add_temporal_commands(subparsers)
    _add_spatial_commands(subparsers)
    _add_zone_assignment_commands(subparsers)
    _add_economy_commands(subparsers)
    _add_round_feature_commands(subparsers)
    _add_pattern_commands(subparsers)
    _add_finding_commands(subparsers)
    _add_readiness_commands(subparsers)
    _add_counter_strategy_commands(subparsers)
    _add_golden_corpus_commands(subparsers)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    debug = bool(getattr(args, "debug", False))
    try:
        if args.command in {"inspect", "normalize"}:
            return _run_demo_output_command(args)
        if args.command == "db":
            return _run_db_command(args)
        if args.command == "import":
            return _run_import_command(args)
        if args.command == "matches":
            return _run_matches_command(args)
        if args.command == "rounds":
            return _run_rounds_command(args)
        if args.command == "analytics":
            return _run_analytics_command(args)
        if args.command == "temporal":
            return _run_temporal_command(args)
        if args.command == "spatial":
            return _run_spatial_command(args)
        if args.command == "zones":
            return _run_zone_assignment_command(args)
        if args.command == "economy":
            return _run_economy_command(args)
        if args.command == "features":
            return _run_round_feature_command(args)
        if args.command == "patterns":
            return _run_pattern_command(args)
        if args.command == "findings":
            return _run_finding_command(args)
        if args.command == "readiness":
            return _run_readiness_command(args)
        if args.command == "strategies":
            return _run_counter_strategy_command(args)
        if args.command == "corpus":
            return _run_golden_corpus_command(args)
        raise AssertionError(f"Unhandled CLI command: {args.command}")
    except GoldenCorpusError as exc:
        print(f"error [golden_corpus]: {exc}", file=sys.stderr)
        if debug:
            traceback.print_exc(file=sys.stderr)
        return _EXIT_CORPUS
    except DemoInspectionError as exc:
        print(f"error [{exc.error_code}]: {exc}", file=sys.stderr)
        if debug:
            traceback.print_exc(file=sys.stderr)
        return _exit_code_for(exc)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"error [unexpected_error]: {exc}", file=sys.stderr)
        if debug:
            traceback.print_exc(file=sys.stderr)
        return _EXIT_UNEXPECTED


def _add_inspect_command(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "inspect",
        help="inspect one local .dem and print a compact JSON summary",
    )
    command.add_argument("demo", type=Path, help="path to a completed local .dem file")
    _add_output_options(command)


def _add_normalize_command(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "normalize",
        help="build a deterministic canonical match dataset from one local .dem",
    )
    command.add_argument("demo", type=Path, help="path to a completed local .dem file")
    _add_output_options(command)
    command.add_argument(
        "--summary-only",
        action="store_true",
        help="emit only compact counts, validation totals and fingerprint",
    )


def _add_database_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("db", help="manage the local DuckDB schema")
    actions = command.add_subparsers(dest="db_command", required=True)
    init_command = actions.add_parser("init", help="initialize or migrate the database")
    _add_database_options(init_command)


def _add_import_command(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "import",
        help="canonicalize a .dem or validate and import canonical JSON",
    )
    sources = command.add_mutually_exclusive_group(required=True)
    sources.add_argument("demo", type=Path, nargs="?", help="completed local .dem file")
    sources.add_argument(
        "--canonical-json",
        type=Path,
        help="existing CanonicalMatchDataset JSON artifact",
    )
    command.add_argument(
        "--force",
        action="store_true",
        help="atomically replace a matching match/fingerprint",
    )
    command.add_argument(
        "--summary-only",
        action="store_true",
        help="reserved compact mode; import output is already summary-only",
    )
    _add_database_options(command)


def _add_match_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("matches", help="query or delete imported matches")
    actions = command.add_subparsers(dest="matches_command", required=True)
    list_command = actions.add_parser("list", help="list imported matches")
    list_command.add_argument("--map-name")
    list_command.add_argument("--source-sha256")
    list_command.add_argument("--parser-name")
    list_command.add_argument("--limit", type=int, default=100)
    list_command.add_argument("--offset", type=int, default=0)
    _add_database_options(list_command)
    show_command = actions.add_parser("show", help="show match metadata and row counts")
    show_command.add_argument("match_id", type=UUID)
    _add_database_options(show_command)
    delete_command = actions.add_parser("delete", help="delete one match and all child rows")
    delete_command.add_argument("match_id", type=UUID)
    delete_command.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete_command)


def _add_round_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("rounds", help="query canonical rounds")
    actions = command.add_subparsers(dest="rounds_command", required=True)
    list_command = actions.add_parser("list", help="list rounds for one match")
    list_command.add_argument("match_id", type=UUID)
    _add_database_options(list_command)
    show_command = actions.add_parser("show", help="show one round and its events")
    show_command.add_argument("match_id", type=UUID)
    show_command.add_argument("round_number", type=int)
    _add_database_options(show_command)


def _add_analytics_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("analytics", help="compute or query gameplay analytics V1")
    actions = command.add_subparsers(dest="analytics_command", required=True)

    compute = actions.add_parser("compute", help="compute analytics for one imported match")
    compute.add_argument("match_id", type=UUID)
    compute.add_argument("--force", action="store_true", help="atomically replace the same run")
    trade_window = compute.add_mutually_exclusive_group()
    trade_window.add_argument(
        "--trade-window-seconds",
        type=float,
        help="window in seconds; requires proven canonical tickrate metadata",
    )
    trade_window.add_argument(
        "--trade-window-ticks",
        type=int,
        help="authoritative window in ticks (default: 320)",
    )
    _add_database_options(compute)

    for name, help_text in (
        ("show", "show compact analytics metadata and capability summary"),
        ("players", "list player match analytics"),
        ("teams", "list team match analytics"),
        ("openings", "list opening duels"),
    ):
        query = actions.add_parser(name, help=help_text)
        query.add_argument("match_id", type=UUID)
        _add_database_options(query)

    player = actions.add_parser("player", help="show one player's match analytics")
    player.add_argument("match_id", type=UUID)
    player.add_argument("player_id", type=UUID)
    _add_database_options(player)

    round_command = actions.add_parser("round", help="show one round analytics view")
    round_command.add_argument("match_id", type=UUID)
    round_command.add_argument("round_number", type=int)
    _add_database_options(round_command)

    trades = actions.add_parser("trades", help="list direct trade events")
    trades.add_argument("match_id", type=UUID)
    trades.add_argument("--round", dest="round_number", type=int)
    _add_database_options(trades)

    advantage = actions.add_parser("advantage", help="show the alive-count timeline")
    advantage.add_argument("match_id", type=UUID)
    advantage.add_argument("round_number", type=int)
    _add_database_options(advantage)

    delete = actions.add_parser("delete", help="delete analytics without deleting canonical data")
    delete.add_argument("match_id", type=UUID)
    delete.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete)


def _add_temporal_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("temporal", help="compute or query temporal round state")
    actions = command.add_subparsers(dest="temporal_command", required=True)

    compute = actions.add_parser("compute", help="compute temporal state for one match")
    compute.add_argument("match_id", type=UUID)
    compute.add_argument("--force", action="store_true", help="atomically replace the same run")
    _add_database_options(compute)

    show = actions.add_parser("show", help="show temporal run summary and capabilities")
    show.add_argument("match_id", type=UUID)
    _add_database_options(show)

    for name, help_text in (
        ("round", "show one immutable round timeline"),
        ("events", "list ordered temporal events"),
        ("transitions", "list normalized state transitions"),
        ("participants", "list participant round states"),
        ("bomb", "list bomb state transitions"),
        ("final", "show the final round snapshot"),
    ):
        query = actions.add_parser(name, help=help_text)
        query.add_argument("match_id", type=UUID)
        query.add_argument("round_number", type=int)
        _add_database_options(query)

    snapshot = actions.add_parser("snapshot", help="show state after events through one tick")
    snapshot.add_argument("match_id", type=UUID)
    snapshot.add_argument("round_number", type=int)
    snapshot.add_argument("--tick", type=int, required=True)
    _add_database_options(snapshot)

    for name in ("before-event", "after-event"):
        query = actions.add_parser(name, help=f"show snapshot {name.replace('-', ' ')}")
        query.add_argument("match_id", type=UUID)
        query.add_argument("event_id", type=UUID)
        _add_database_options(query)

    groups = actions.add_parser("groups", help="list simultaneous state-event groups")
    groups.add_argument("match_id", type=UUID)
    groups.add_argument("--round", dest="round_number", type=int)
    _add_database_options(groups)

    group = actions.add_parser("group", help="show one simultaneous state-event group")
    group.add_argument("match_id", type=UUID)
    group.add_argument("group_id", type=UUID)
    _add_database_options(group)

    delete = actions.add_parser("delete", help="delete temporal state only")
    delete.add_argument("match_id", type=UUID)
    delete.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete)


def _add_spatial_commands(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "spatial", help="compute or inspect parser-independent spatial snapshots"
    )
    actions = command.add_subparsers(dest="spatial_command", required=True)

    compute = actions.add_parser("compute", help="compute Spatial 1.0 for one match")
    compute.add_argument("match_id", type=UUID)
    compute.add_argument("demo", type=Path, help="the exact imported completed .dem")
    compute.add_argument("--interval-ticks", type=int, default=16)
    compute.add_argument("--force", action="store_true", help="replace the same run atomically")
    _add_database_options(compute)

    for name, help_text in (
        ("status", "show selected compatible run, capabilities and counts"),
        ("runs", "list persisted Spatial runs and compatibility"),
        ("validate", "list spatial validation issues"),
        ("bombs", "list derived carried-C4 positions"),
    ):
        query = actions.add_parser(name, help=help_text)
        query.add_argument("match_id", type=UUID)
        if name == "bombs":
            query.add_argument("--round", dest="round_number", type=int)
        _add_database_options(query)

    show = actions.add_parser("show", help="list immutable player spatial snapshots as JSON")
    show.add_argument("match_id", type=UUID)
    show.add_argument("--round", dest="round_number", type=int)
    show.add_argument("--player", dest="participant_id", type=UUID)
    show.add_argument("--limit", type=int, default=1000)
    show.add_argument("--offset", type=int, default=0)
    show.add_argument("--output", type=Path, help="also save the JSON result")
    show.add_argument("--force", action="store_true", help="replace an existing output file")
    _add_database_options(show)

    delete = actions.add_parser("delete", help="delete Spatial runs only")
    delete.add_argument("match_id", type=UUID)
    delete.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete)


def _add_zone_assignment_commands(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "zones", help="compute or inspect versioned spatial-to-zone assignments"
    )
    actions = command.add_subparsers(dest="zones_command", required=True)

    compute = actions.add_parser("compute", help="assign one exact Spatial run to zones")
    compute.add_argument("match_id", type=UUID)
    compute.add_argument("--spatial-run", dest="spatial_run_id", type=UUID)
    compute.add_argument(
        "--require-proven-map-revision",
        action="store_true",
        help="mark assignments unavailable when the demo cannot prove the map revision",
    )
    compute.add_argument("--force", action="store_true", help="replace the same run atomically")
    _add_database_options(compute)

    status = actions.add_parser("status", help="show selected run, coverage and provenance")
    status.add_argument("match_id", type=UUID)
    status.add_argument("--spatial-run", dest="spatial_run_id", type=UUID)
    _add_database_options(status)

    runs = actions.add_parser("runs", help="list persisted zone assignment runs")
    runs.add_argument("match_id", type=UUID)
    _add_database_options(runs)

    show = actions.add_parser("show", help="list immutable snapshot zone assignments")
    show.add_argument("match_id", type=UUID)
    show.add_argument("--run", dest="zone_assignment_run_id", type=UUID)
    show.add_argument("--round", dest="round_number", type=int)
    show.add_argument("--status", choices=tuple(item.value for item in ZoneAssignmentStatus))
    show.add_argument("--limit", type=int, default=1000)
    show.add_argument("--offset", type=int, default=0)
    _add_database_options(show)

    delete = actions.add_parser("delete", help="delete zone runs but preserve Spatial data")
    delete.add_argument("match_id", type=UUID)
    delete.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete)


def _add_economy_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("economy", help="compute or inspect freeze-end economy context")
    actions = command.add_subparsers(dest="economy_command", required=True)

    compute = actions.add_parser("compute", help="compute one versioned Economy run")
    compute.add_argument("match_id", type=UUID)
    compute.add_argument("demo", type=Path, help="the exact imported completed .dem")
    compute.add_argument("--force", action="store_true", help="replace the same run atomically")
    _add_database_options(compute)

    for name, help_text in (
        ("status", "show selected Economy run and coverage"),
        ("runs", "list persisted Economy runs"),
    ):
        query = actions.add_parser(name, help=help_text)
        query.add_argument("match_id", type=UUID)
        _add_database_options(query)

    teams = actions.add_parser("teams", help="list team-round buy classifications")
    teams.add_argument("match_id", type=UUID)
    teams.add_argument("--run", dest="economy_run_id", type=UUID)
    teams.add_argument("--round", dest="round_number", type=int)
    teams.add_argument("--side", choices=(Side.T.value, Side.CT.value))
    teams.add_argument("--buy-type", choices=tuple(item.value for item in BuyType))
    teams.add_argument("--limit", type=int, default=1000)
    teams.add_argument("--offset", type=int, default=0)
    _add_database_options(teams)

    players = actions.add_parser("players", help="list player freeze-end equipment")
    players.add_argument("match_id", type=UUID)
    players.add_argument("--run", dest="economy_run_id", type=UUID)
    players.add_argument("--round", dest="round_number", type=int)
    players.add_argument("--player", dest="participant_id", type=UUID)
    players.add_argument("--limit", type=int, default=1000)
    players.add_argument("--offset", type=int, default=0)
    _add_database_options(players)

    delete = actions.add_parser("delete", help="delete Economy runs only")
    delete.add_argument("match_id", type=UUID)
    delete.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete)


def _add_round_feature_commands(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "features", help="compute or inspect version-pinned per-round tactical facts"
    )
    actions = command.add_subparsers(dest="features_command", required=True)

    compute = actions.add_parser("compute", help="compute one Stage 8.4 feature run")
    compute.add_argument("match_id", type=UUID)
    compute.add_argument(
        "--checkpoint-offset-ticks",
        type=int,
        nargs="+",
        default=None,
        help="strictly increasing freeze-end tick offsets",
    )
    compute.add_argument("--early-window-ticks", type=int, default=1280)
    compute.add_argument("--include-incomplete", action="store_true")
    compute.add_argument("--force", action="store_true", help="replace the same run atomically")
    _add_database_options(compute)

    for name, help_text in (
        ("status", "show selected Stage 8.4 run and capability counts"),
        ("runs", "list persisted Stage 8.4 runs"),
    ):
        query = actions.add_parser(name, help=help_text)
        query.add_argument("match_id", type=UUID)
        _add_database_options(query)

    show = actions.add_parser("show", help="list atomic per-round feature records")
    show.add_argument("match_id", type=UUID)
    show.add_argument("--run", dest="feature_run_id", type=UUID)
    show.add_argument("--round", dest="round_number", type=int)
    show.add_argument("--team", dest="team_id", type=UUID)
    show.add_argument("--side", choices=(Side.T.value, Side.CT.value))
    show.add_argument(
        "--type",
        dest="feature_type",
        choices=tuple(item.value for item in RoundFeatureType),
    )
    show.add_argument("--availability", choices=tuple(item.value for item in FeatureAvailability))
    show.add_argument("--buy-type", choices=tuple(item.value for item in BuyType))
    show.add_argument("--limit", type=int, default=1000)
    show.add_argument("--offset", type=int, default=0)
    _add_database_options(show)

    delete = actions.add_parser("delete", help="delete Stage 8.4 runs only")
    delete.add_argument("match_id", type=UUID)
    delete.add_argument("--yes", action="store_true", help="skip confirmation")
    _add_database_options(delete)


def _add_pattern_commands(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "patterns", help="compute or inspect Stage 8.5 opponent cross-match patterns"
    )
    actions = command.add_subparsers(dest="patterns_command", required=True)

    compute = actions.add_parser("compute", help="compute one versioned pattern run")
    compute.add_argument("profile_id", type=UUID)
    compute.add_argument("--minimum-corpus-matches", type=int, default=20)
    compute.add_argument("--minimum-sample-size", type=int, default=5)
    compute.add_argument(
        "--plant-timing-buckets",
        type=float,
        nargs="+",
        default=None,
        help="strictly increasing plant-time bucket boundaries in proven seconds",
    )
    compute.add_argument(
        "--exclude-partial-features",
        action="store_true",
        help="exclude Stage 8.4 partial payloads from denominators",
    )
    compute.add_argument("--force", action="store_true")
    _add_database_options(compute)

    for name, help_text in (
        ("status", "show the selected Stage 8.5 run"),
        ("runs", "list persisted Stage 8.5 runs"),
    ):
        query = actions.add_parser(name, help=help_text)
        query.add_argument("profile_id", type=UUID)
        _add_database_options(query)

    show = actions.add_parser("show", help="list cross-match pattern records")
    show.add_argument("profile_id", type=UUID)
    show.add_argument("--run", dest="pattern_run_id", type=UUID)
    show.add_argument("--map", dest="map_name")
    show.add_argument("--side", choices=(Side.T.value, Side.CT.value))
    show.add_argument("--buy-type", choices=tuple(item.value for item in BuyType))
    show.add_argument(
        "--type",
        dest="pattern_type",
        choices=tuple(item.value for item in PatternType),
    )
    show.add_argument("--availability", choices=tuple(item.value for item in PatternAvailability))
    show.add_argument("--limit", type=int, default=1000)
    show.add_argument("--offset", type=int, default=0)
    _add_database_options(show)

    delete = actions.add_parser("delete", help="delete Stage 8.5 runs for one profile")
    delete.add_argument("profile_id", type=UUID)
    delete.add_argument("--yes", action="store_true")
    _add_database_options(delete)


def _add_finding_commands(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "findings", help="compute or inspect Stage 8.6 analysis findings"
    )
    actions = command.add_subparsers(dest="findings_command", required=True)

    compute = actions.add_parser("compute", help="materialize one immutable analysis run")
    compute.add_argument("profile_id", type=UUID)
    compute.add_argument("--exclude-partial-patterns", action="store_true")
    compute.add_argument("--include-zero-frequency", action="store_true")
    compute.add_argument("--force", action="store_true")
    _add_database_options(compute)

    for name in ("status", "runs"):
        query = actions.add_parser(name)
        query.add_argument("profile_id", type=UUID)
        _add_database_options(query)

    show = actions.add_parser("show", help="list immutable findings")
    show.add_argument("profile_id", type=UUID)
    show.add_argument("--run", dest="analysis_run_id", type=UUID)
    show.add_argument("--map", dest="map_name")
    show.add_argument("--side", choices=(Side.T.value, Side.CT.value))
    show.add_argument("--category", choices=tuple(item.value for item in FindingCategory))
    show.add_argument(
        "--type", dest="pattern_type", choices=tuple(item.value for item in PatternType)
    )
    show.add_argument("--limit", type=int, default=1000)
    show.add_argument("--offset", type=int, default=0)
    _add_database_options(show)

    evidence = actions.add_parser("evidence", help="show one finding and its evidence")
    evidence.add_argument("profile_id", type=UUID)
    evidence.add_argument("finding_id", type=UUID)
    evidence.add_argument("--run", dest="analysis_run_id", type=UUID)
    _add_database_options(evidence)

    delete = actions.add_parser("delete", help="delete Stage 8.6 runs for one profile")
    delete.add_argument("profile_id", type=UUID)
    delete.add_argument("--yes", action="store_true")
    _add_database_options(delete)


def _add_readiness_commands(subparsers: Any) -> None:
    command = subparsers.add_parser("readiness", help="audit Stage 8.6 findings before Stage 8.7")
    actions = command.add_subparsers(dest="readiness_command", required=True)
    audit = actions.add_parser("audit", help="run a deterministic read-only audit")
    audit.add_argument("profile_id", type=UUID)
    audit.add_argument("--run", dest="analysis_run_id", type=UUID)
    audit.add_argument("--minimum-corpus-matches", type=int, default=20)
    audit.add_argument("--minimum-finding-matches", type=int, default=2)
    audit.add_argument("--allow-partial-source", action="store_true")
    audit.add_argument("--allow-unknown-buy-type", action="store_true")
    audit.add_argument("--require-all-evidence-ticks", action="store_true")
    audit.add_argument("--summary-only", action="store_true")
    _add_database_options(audit)


def _add_counter_strategy_commands(subparsers: Any) -> None:
    command = subparsers.add_parser(
        "strategies", help="compute or inspect deterministic Stage 8.7 recommendations"
    )
    actions = command.add_subparsers(dest="strategies_command", required=True)
    compute = actions.add_parser("compute", help="materialize one immutable strategy run")
    compute.add_argument("profile_id", type=UUID)
    compute.add_argument("--minimum-corpus-matches", type=int, default=20)
    compute.add_argument("--minimum-finding-matches", type=int, default=2)
    compute.add_argument("--force", action="store_true")
    _add_database_options(compute)

    for name in ("status", "runs", "skipped"):
        query = actions.add_parser(name)
        query.add_argument("profile_id", type=UUID)
        if name == "skipped":
            query.add_argument("--run", dest="strategy_run_id", type=UUID)
        _add_database_options(query)

    validate = actions.add_parser(
        "validate", help="run the Stage 8.7.1 corpus and rule-quality audit"
    )
    validate.add_argument("profile_id", type=UUID)
    validate.add_argument("--run", dest="strategy_run_id", type=UUID)
    validate.add_argument("--minimum-corpus-matches", type=int, default=20)
    validate.add_argument("--allow-single-side", action="store_true")
    validate.add_argument("--allow-zero-recommendations", action="store_true")
    _add_database_options(validate)

    show = actions.add_parser("show", help="list published recommendations")
    show.add_argument("profile_id", type=UUID)
    show.add_argument("--run", dest="strategy_run_id", type=UUID)
    show.add_argument("--map", dest="map_name")
    show.add_argument("--side", choices=(Side.T.value, Side.CT.value))
    show.add_argument("--buy-type", choices=tuple(item.value for item in BuyType))
    show.add_argument("--category", choices=tuple(item.value for item in CounterStrategyCategory))
    show.add_argument("--limit", type=int, default=1000)
    show.add_argument("--offset", type=int, default=0)
    _add_database_options(show)

    evidence = actions.add_parser("evidence", help="show a recommendation and evidence")
    evidence.add_argument("profile_id", type=UUID)
    evidence.add_argument("recommendation_id", type=UUID)
    evidence.add_argument("--run", dest="strategy_run_id", type=UUID)
    _add_database_options(evidence)

    delete = actions.add_parser("delete", help="delete Stage 8.7 runs for one profile")
    delete.add_argument("profile_id", type=UUID)
    delete.add_argument("--yes", action="store_true")
    _add_database_options(delete)


def _add_golden_corpus_commands(subparsers: Any) -> None:
    corpus = subparsers.add_parser(
        "corpus",
        help="validate the versioned Stage 9.1 Golden Corpus",
    )
    actions = corpus.add_subparsers(dest="corpus_action", required=True)

    validate = actions.add_parser(
        "validate",
        help="validate manifest coverage and optionally verify external demo files",
    )
    validate.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    validate.add_argument(
        "--demo-root",
        type=Path,
        help="external directory containing demos named <sha256>.dem",
    )
    validate.add_argument(
        "--require-ready",
        action="store_true",
        help="return exit code 11 when corpus readiness is blocked",
    )
    validate.add_argument("--pretty", action="store_true")
    validate.add_argument("--debug", action="store_true")

    evaluate = actions.add_parser(
        "evaluate",
        help="measure finding precision/recall against analyst labels",
    )
    evaluate.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    evaluate.add_argument("--predictions", type=Path, required=True)
    evaluate.add_argument(
        "--require-complete",
        action="store_true",
        help="return exit code 11 when some determinate labels cannot be evaluated",
    )
    evaluate.add_argument("--pretty", action="store_true")
    evaluate.add_argument("--debug", action="store_true")

    run = actions.add_parser(
        "run",
        help="parse external corpus demos and compare reviewed canonical facts",
    )
    run.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    run.add_argument("--demo-root", type=Path, required=True)
    run.add_argument("--include-candidates", action="store_true")
    run.add_argument(
        "--require-pass",
        action="store_true",
        help="return exit code 11 unless every selected case passes",
    )
    run.add_argument("--pretty", action="store_true")
    run.add_argument("--debug", action="store_true")


def _add_output_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    command.add_argument("--output", type=Path, help="also save JSON to this file")
    command.add_argument(
        "--force",
        action="store_true",
        help="allow replacing an existing output file",
    )
    command.add_argument("--debug", action="store_true", help="show a traceback on failure")


def _add_database_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--db", type=Path, help="DuckDB path (overrides environment)")
    command.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    command.add_argument("--debug", action="store_true", help="show a traceback on failure")


def _run_demo_output_command(args: argparse.Namespace) -> int:
    output_path = _preflight_output(args.demo, args.output, force=bool(args.force))
    if args.command == "inspect":
        report = _build_service().inspect(args.demo)
        serialized = report.model_dump_json(indent=2 if args.pretty else None)
        fatal_validation = False
    else:
        dataset = _build_normalization_service().normalize(args.demo)
        artifact = CanonicalizationSummary.from_dataset(dataset) if args.summary_only else dataset
        serialized = artifact.model_dump_json(indent=2 if args.pretty else None)
        fatal_validation = dataset.validation_report.has_fatal_errors
        if args.output is None and not args.summary_only:
            print(
                "warning: full canonical JSON may be large; use --output or --summary-only.",
                file=sys.stderr,
            )
    if output_path is not None:
        _write_output(output_path, serialized, force=bool(args.force))
    print(serialized)
    return _EXIT_FATAL_VALIDATION if fatal_validation else 0


def _run_db_command(args: argparse.Namespace) -> int:
    repository = _build_repository(args.db)
    applied = repository.initialize()
    current_version = max((migration.version for migration in MIGRATIONS), default=0)
    result = DatabaseInitResult(
        database_path=repository.database_path,
        applied_migrations=applied,
        current_version=current_version,
    )
    _print_model(result, pretty=args.pretty)
    return 0


def _run_import_command(args: argparse.Namespace) -> int:
    repository = _build_repository(args.db)
    service = ImportCanonicalMatchService(repository)
    if args.canonical_json is not None:
        result = service.import_canonical_json(args.canonical_json, replace=bool(args.force))
    else:
        dataset = _build_normalization_service().normalize(args.demo)
        result = service.import_dataset(
            dataset,
            source_original_name=args.demo.name,
            replace=bool(args.force),
        )
    _print_model(result, pretty=args.pretty)
    if result.status is ImportStatus.FAILED:
        message = result.warnings[-1] if result.warnings else "Canonical import failed."
        print(f"error [persistence_error]: {message}", file=sys.stderr)
        return _EXIT_PERSISTENCE
    return 0


def _run_matches_command(args: argparse.Namespace) -> int:
    service = MatchQueryService(_build_repository(args.db))
    if args.matches_command == "list":
        matches = service.list_matches(
            MatchQueryFilters(
                map_name=args.map_name,
                source_demo_sha256=args.source_sha256,
                parser_name=args.parser_name,
                limit=args.limit,
                offset=args.offset,
            )
        )
        _print_value(matches, pretty=args.pretty)
        return 0
    if args.matches_command == "show":
        _print_model(service.get_summary(args.match_id), pretty=args.pretty)
        return 0
    if not args.yes and not _confirm_delete(args.match_id):
        _print_value(
            {"match_id": str(args.match_id), "status": "cancelled"},
            pretty=args.pretty,
        )
        return 0
    result = DeleteMatchResult(
        match_id=args.match_id,
        deleted=service.delete_match(args.match_id),
    )
    _print_model(result, pretty=args.pretty)
    return 0


def _run_rounds_command(args: argparse.Namespace) -> int:
    service = MatchQueryService(_build_repository(args.db))
    if args.rounds_command == "list":
        _print_value(service.get_rounds(args.match_id), pretty=args.pretty)
    else:
        _print_model(
            service.get_round_details(args.match_id, args.round_number),
            pretty=args.pretty,
        )
    return 0


def _run_analytics_command(args: argparse.Namespace) -> int:
    match_repository = _build_repository(args.db)
    analytics_repository = _build_analytics_repository(args.db)
    if args.analytics_command == "compute":
        config = resolve_analytics_config(
            requested_ticks=args.trade_window_ticks,
            requested_seconds=args.trade_window_seconds,
            tickrate_evidence=None,
        )
        result = ComputeMatchAnalyticsService(match_repository, analytics_repository).compute(
            args.match_id, config=config, replace=bool(args.force)
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = AnalyticsQueryService(analytics_repository)
    if args.analytics_command == "show":
        value: Any = service.get_analytics_summary(args.match_id)
    elif args.analytics_command == "players":
        value = service.list_player_stats(args.match_id)
    elif args.analytics_command == "player":
        value = service.get_player_stats(args.match_id, args.player_id)
    elif args.analytics_command == "teams":
        value = service.list_team_stats(args.match_id)
    elif args.analytics_command == "round":
        value = service.get_round_analytics(args.match_id, args.round_number)
    elif args.analytics_command == "openings":
        value = service.list_opening_duels(args.match_id)
    elif args.analytics_command == "trades":
        value = service.list_trade_events(args.match_id, args.round_number)
    elif args.analytics_command == "advantage":
        value = service.get_man_advantage_timeline(args.match_id, args.round_number)
    elif args.analytics_command == "delete":
        if not args.yes and not _confirm_analytics_delete(args.match_id):
            _print_value(
                {"match_id": str(args.match_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = service.delete_analytics(args.match_id)
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled analytics command: {args.analytics_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_temporal_command(args: argparse.Namespace) -> int:
    match_repository = _build_repository(args.db)
    temporal_repository = _build_temporal_repository(args.db)
    if args.temporal_command == "compute":
        result = ComputeTemporalStateService(
            match_repository,
            temporal_repository,
            analytics_repository=_build_analytics_repository(args.db),
        ).compute(
            args.match_id,
            config=TemporalConfig(),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = TemporalQueryService(temporal_repository)
    if args.temporal_command == "show":
        value: Any = service.get_match_temporal_summary(args.match_id)
    elif args.temporal_command == "round":
        value = service.get_round_timeline(args.match_id, args.round_number)
    elif args.temporal_command == "events":
        value = service.get_round_events(args.match_id, args.round_number)
    elif args.temporal_command == "transitions":
        value = service.get_round_transitions(args.match_id, args.round_number)
    elif args.temporal_command == "participants":
        value = service.get_round_participants(args.match_id, args.round_number)
    elif args.temporal_command == "groups":
        value = service.get_simultaneous_groups(args.match_id, args.round_number)
    elif args.temporal_command == "group":
        value = service.get_simultaneous_group(args.match_id, args.group_id)
    elif args.temporal_command == "snapshot":
        value = service.get_snapshot(args.match_id, args.round_number, args.tick)
    elif args.temporal_command == "before-event":
        value = service.get_snapshot_before_event(args.match_id, args.event_id)
    elif args.temporal_command == "after-event":
        value = service.get_snapshot_after_event(args.match_id, args.event_id)
    elif args.temporal_command == "final":
        value = service.get_final_snapshot(args.match_id, args.round_number)
    elif args.temporal_command == "bomb":
        value = service.get_bomb_timeline(args.match_id, args.round_number)
    elif args.temporal_command == "delete":
        if not args.yes and not _confirm_temporal_delete(args.match_id):
            _print_value(
                {"match_id": str(args.match_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = service.delete_temporal(args.match_id)
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled temporal command: {args.temporal_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_spatial_command(args: argparse.Namespace) -> int:
    repository = _build_spatial_repository(args.db)
    if args.spatial_command == "compute":
        result = ComputeSpatialStateService(
            _build_repository(args.db),
            _build_temporal_repository(args.db),
            repository,
            Demoparser2SpatialExtractor(),
        ).compute(
            args.match_id,
            args.demo,
            config=SpatialConfig(sampling_interval_ticks=args.interval_ticks),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = SpatialQueryService(repository)
    if args.spatial_command == "status":
        value: Any = service.get_status(args.match_id)
    elif args.spatial_command == "runs":
        value = service.list_runs(args.match_id)
    elif args.spatial_command == "show":
        value = service.list_snapshots(
            args.match_id,
            round_number=args.round_number,
            participant_id=args.participant_id,
            limit=args.limit,
            offset=args.offset,
        )
        serialized = (
            TypeAdapter(Any).dump_json(value, indent=2 if args.pretty else None).decode("utf-8")
        )
        if args.output is not None:
            output = _preflight_json_output(args.output, force=bool(args.force))
            _write_output(output, serialized, force=bool(args.force))
        print(serialized)
        return 0
    elif args.spatial_command == "bombs":
        value = service.list_bomb_positions(args.match_id, round_number=args.round_number)
    elif args.spatial_command == "validate":
        value = service.validate(args.match_id)
    elif args.spatial_command == "delete":
        if not args.yes and not _confirm_spatial_delete(args.match_id):
            _print_value(
                {"match_id": str(args.match_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = service.delete(args.match_id)
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled spatial command: {args.spatial_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_zone_assignment_command(args: argparse.Namespace) -> int:
    spatial_repository = _build_spatial_repository(args.db)
    zone_repository = _build_zone_assignment_repository(args.db)
    if args.zones_command == "compute":
        result = ComputeZoneAssignmentsService(spatial_repository, zone_repository).compute(
            args.match_id,
            spatial_run_id=args.spatial_run_id,
            config=ZoneAssignmentConfig(
                allow_unproven_map_revision=not args.require_proven_map_revision
            ),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = ZoneAssignmentQueryService(zone_repository)
    if args.zones_command == "status":
        value: Any = service.get_summary(args.match_id, spatial_run_id=args.spatial_run_id)
    elif args.zones_command == "runs":
        value = service.list_runs(args.match_id)
    elif args.zones_command == "show":
        value = service.list_assignments(
            args.match_id,
            zone_assignment_run_id=args.zone_assignment_run_id,
            round_number=args.round_number,
            status=ZoneAssignmentStatus(args.status) if args.status is not None else None,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.zones_command == "delete":
        if not args.yes and not _confirm_zone_assignment_delete(args.match_id):
            _print_value(
                {"match_id": str(args.match_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = service.delete(args.match_id)
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled zone command: {args.zones_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_economy_command(args: argparse.Namespace) -> int:
    repository = _build_economy_repository(args.db)
    if args.economy_command == "compute":
        result = ComputeEconomyService(
            _build_repository(args.db),
            repository,
            Demoparser2EconomyExtractor(),
        ).compute(
            args.match_id,
            args.demo,
            config=EconomyConfig(),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = EconomyQueryService(repository)
    if args.economy_command == "status":
        value: Any = service.get_summary(args.match_id)
    elif args.economy_command == "runs":
        value = service.list_runs(args.match_id)
    elif args.economy_command == "teams":
        value = service.list_team_snapshots(
            args.match_id,
            economy_run_id=args.economy_run_id,
            round_number=args.round_number,
            side=Side(args.side) if args.side else None,
            buy_type=BuyType(args.buy_type) if args.buy_type else None,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.economy_command == "players":
        value = service.list_player_snapshots(
            args.match_id,
            economy_run_id=args.economy_run_id,
            round_number=args.round_number,
            participant_id=args.participant_id,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.economy_command == "delete":
        if not args.yes and not _confirm_economy_delete(args.match_id):
            _print_value(
                {"match_id": str(args.match_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = service.delete(args.match_id)
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled economy command: {args.economy_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_round_feature_command(args: argparse.Namespace) -> int:
    repository = _build_round_feature_repository(args.db)
    if args.features_command == "compute":
        offsets = (
            tuple(args.checkpoint_offset_ticks)
            if args.checkpoint_offset_ticks is not None
            else RoundFeatureConfig().checkpoint_offsets_ticks
        )
        result = ComputeRoundFeaturesService(
            _build_repository(args.db),
            _build_analytics_repository(args.db),
            _build_temporal_repository(args.db),
            _build_spatial_repository(args.db),
            _build_zone_assignment_repository(args.db),
            repository,
            economy_repository=_build_economy_repository(args.db),
        ).compute(
            args.match_id,
            config=RoundFeatureConfig(
                checkpoint_offsets_ticks=offsets,
                early_window_ticks=args.early_window_ticks,
                include_incomplete_rounds=bool(args.include_incomplete),
            ),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = RoundFeatureQueryService(repository)
    if args.features_command == "status":
        value: Any = service.get_summary(args.match_id)
    elif args.features_command == "runs":
        value = service.list_runs(args.match_id)
    elif args.features_command == "show":
        value = service.list_features(
            args.match_id,
            feature_run_id=args.feature_run_id,
            round_number=args.round_number,
            team_id=args.team_id,
            side=Side(args.side) if args.side else None,
            feature_type=(RoundFeatureType(args.feature_type) if args.feature_type else None),
            availability=(FeatureAvailability(args.availability) if args.availability else None),
            buy_type=BuyType(args.buy_type) if args.buy_type else None,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.features_command == "delete":
        if not args.yes and not _confirm_round_feature_delete(args.match_id):
            _print_value(
                {"match_id": str(args.match_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = service.delete(args.match_id)
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled features command: {args.features_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_pattern_command(args: argparse.Namespace) -> int:
    repository = _build_pattern_repository(args.db)
    if args.patterns_command == "compute":
        defaults = PatternConfig()
        buckets = (
            tuple(args.plant_timing_buckets)
            if args.plant_timing_buckets is not None
            else defaults.plant_timing_bucket_seconds
        )
        result = ComputeCrossMatchPatternsService(
            _build_opponent_repository(args.db),
            _build_repository(args.db),
            _build_round_feature_repository(args.db),
            repository,
        ).compute(
            args.profile_id,
            config=PatternConfig(
                minimum_corpus_matches=args.minimum_corpus_matches,
                minimum_sample_size=args.minimum_sample_size,
                plant_timing_bucket_seconds=buckets,
                include_partial_features=not bool(args.exclude_partial_features),
            ),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = PatternQueryService(repository)
    if args.patterns_command == "status":
        value: Any = service.get_summary(args.profile_id)
    elif args.patterns_command == "runs":
        value = service.list_runs(args.profile_id)
    elif args.patterns_command == "show":
        value = service.list_patterns(
            args.profile_id,
            pattern_run_id=args.pattern_run_id,
            map_name=args.map_name,
            side=Side(args.side) if args.side else None,
            buy_type=BuyType(args.buy_type) if args.buy_type else None,
            pattern_type=PatternType(args.pattern_type) if args.pattern_type else None,
            availability=(PatternAvailability(args.availability) if args.availability else None),
            limit=args.limit,
            offset=args.offset,
        )
    elif args.patterns_command == "delete":
        if not args.yes and not _confirm_pattern_delete(args.profile_id):
            _print_value(
                {"profile_id": str(args.profile_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = {"profile_id": args.profile_id, "deleted_runs": service.delete(args.profile_id)}
    else:  # pragma: no cover - argparse enforces this set
        raise AssertionError(f"Unhandled patterns command: {args.patterns_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_finding_command(args: argparse.Namespace) -> int:
    patterns = _build_pattern_repository(args.db)
    repository = _build_analysis_repository(args.db)
    if args.findings_command == "compute":
        result = ComputeAnalysisFindingsService(
            patterns, _build_repository(args.db), repository
        ).compute(
            args.profile_id,
            config=FindingConfig(
                include_partial_patterns=not bool(args.exclude_partial_patterns),
                include_zero_frequency=bool(args.include_zero_frequency),
            ),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = AnalysisFindingQueryService(patterns, repository)
    if args.findings_command == "status":
        value: Any = service.get_summary(args.profile_id)
    elif args.findings_command == "runs":
        value = service.list_runs(args.profile_id)
    elif args.findings_command == "show":
        value = service.list_findings(
            args.profile_id,
            analysis_run_id=args.analysis_run_id,
            map_name=args.map_name,
            side=Side(args.side) if args.side else None,
            category=FindingCategory(args.category) if args.category else None,
            pattern_type=PatternType(args.pattern_type) if args.pattern_type else None,
            limit=args.limit,
            offset=args.offset,
        )
    elif args.findings_command == "evidence":
        value = service.get_finding(
            args.profile_id,
            args.finding_id,
            analysis_run_id=args.analysis_run_id,
        )
    elif args.findings_command == "delete":
        if not args.yes and not _confirm_finding_delete(args.profile_id):
            _print_value(
                {"profile_id": str(args.profile_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = {
            "profile_id": args.profile_id,
            "deleted_runs": service.delete(args.profile_id),
        }
    else:  # pragma: no cover
        raise AssertionError(f"Unhandled findings command: {args.findings_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_readiness_command(args: argparse.Namespace) -> int:
    if args.readiness_command != "audit":  # pragma: no cover - argparse enforces this
        raise AssertionError(f"Unhandled readiness command: {args.readiness_command}")
    patterns = _build_pattern_repository(args.db)
    analysis = _build_analysis_repository(args.db)
    result = FindingReadinessService(AnalysisFindingQueryService(patterns, analysis)).audit(
        args.profile_id,
        analysis_run_id=args.analysis_run_id,
        config=FindingReadinessConfig(
            minimum_corpus_matches=args.minimum_corpus_matches,
            minimum_finding_matches=args.minimum_finding_matches,
            block_partial_source=not bool(args.allow_partial_source),
            require_known_buy_type=not bool(args.allow_unknown_buy_type),
            require_all_evidence_ticks=bool(args.require_all_evidence_ticks),
        ),
    )
    if args.summary_only:
        _print_value(
            {
                "readiness_schema_version": result.readiness_schema_version,
                "readiness_rule_version": result.readiness_rule_version,
                "audit_id": result.audit_id,
                "audit_fingerprint": result.audit_fingerprint,
                "source_analysis_run_id": result.source_analysis_run_id,
                "config": result.config,
                "summary": result.summary,
                "warnings": result.warnings,
            },
            pretty=args.pretty,
        )
    else:
        _print_model(result, pretty=args.pretty)
    return 0


def _run_counter_strategy_command(args: argparse.Namespace) -> int:
    patterns = _build_pattern_repository(args.db)
    analysis = _build_analysis_repository(args.db)
    finding_query = AnalysisFindingQueryService(patterns, analysis)
    repository = _build_counter_strategy_repository(args.db)
    if args.strategies_command == "compute":
        result = ComputeCounterStrategiesService(finding_query, repository).compute(
            args.profile_id,
            readiness_config=FindingReadinessConfig(
                minimum_corpus_matches=args.minimum_corpus_matches,
                minimum_finding_matches=args.minimum_finding_matches,
            ),
            strategy_config=CounterStrategyConfig(),
            replace=bool(args.force),
        )
        _print_model(result, pretty=args.pretty)
        return 0

    service = CounterStrategyQueryService(finding_query, repository)
    if args.strategies_command == "status":
        value: Any = service.get_summary(args.profile_id)
    elif args.strategies_command == "runs":
        value = service.list_runs(args.profile_id)
    elif args.strategies_command == "show":
        value = service.list_recommendations(
            args.profile_id,
            strategy_run_id=args.strategy_run_id,
            map_name=args.map_name,
            side=Side(args.side) if args.side else None,
            buy_type=BuyType(args.buy_type) if args.buy_type else None,
            category=(CounterStrategyCategory(args.category) if args.category else None),
            limit=args.limit,
            offset=args.offset,
        )
    elif args.strategies_command == "skipped":
        value = service.list_skipped(args.profile_id, strategy_run_id=args.strategy_run_id)
    elif args.strategies_command == "validate":
        value = ValidateCounterStrategiesService(finding_query, service).validate(
            args.profile_id,
            strategy_run_id=args.strategy_run_id,
            config=StrategyValidationConfig(
                minimum_corpus_matches=args.minimum_corpus_matches,
                require_both_sides=not bool(args.allow_single_side),
                require_at_least_one_recommendation=not bool(args.allow_zero_recommendations),
            ),
        )
    elif args.strategies_command == "evidence":
        value = service.get_recommendation(
            args.profile_id,
            args.recommendation_id,
            strategy_run_id=args.strategy_run_id,
        )
    elif args.strategies_command == "delete":
        if not args.yes and not _confirm_strategy_delete(args.profile_id):
            _print_value(
                {"profile_id": str(args.profile_id), "status": "cancelled"},
                pretty=args.pretty,
            )
            return 0
        value = {
            "profile_id": args.profile_id,
            "deleted_runs": service.delete(args.profile_id),
        }
    else:  # pragma: no cover
        raise AssertionError(f"Unhandled strategies command: {args.strategies_command}")
    _print_value(value, pretty=args.pretty)
    return 0


def _run_golden_corpus_command(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    if args.corpus_action == "validate":
        audit = GoldenCorpusValidator().validate(manifest, demo_root=args.demo_root)
        _print_model(audit, pretty=args.pretty)
        return _EXIT_CORPUS if args.require_ready and audit.status.value != "ready" else 0
    if args.corpus_action == "evaluate":
        predictions = load_predictions(args.predictions)
        evaluation_report = GoldenFindingEvaluator().evaluate(manifest, predictions)
        _print_model(evaluation_report, pretty=args.pretty)
        return _EXIT_CORPUS if args.require_complete and not evaluation_report.complete else 0
    if args.corpus_action == "run":
        adapter = Demoparser2Adapter()
        run_report = GoldenCorpusRunner(
            CanonicalizationService(adapter),
            parser_name=adapter.identity.name,
            parser_version=adapter.identity.version,
        ).run(
            manifest,
            args.demo_root,
            include_candidates=bool(args.include_candidates),
        )
        _print_model(run_report, pretty=args.pretty)
        return _EXIT_CORPUS if args.require_pass and not run_report.passed else 0
    raise AssertionError(f"Unhandled corpus command: {args.corpus_action}")


def _build_service() -> DemoInspectionService:
    return DemoInspectionService(Demoparser2Adapter())


def _build_normalization_service() -> CanonicalizationService:
    return CanonicalizationService(Demoparser2Adapter())


def _build_repository(database_path: Path | None) -> DuckDBMatchRepository:
    return DuckDBMatchRepository(resolve_database_path(database_path))


def _build_analytics_repository(database_path: Path | None) -> DuckDBAnalyticsRepository:
    return DuckDBAnalyticsRepository(resolve_database_path(database_path))


def _build_temporal_repository(database_path: Path | None) -> DuckDBTemporalRepository:
    return DuckDBTemporalRepository(resolve_database_path(database_path))


def _build_spatial_repository(database_path: Path | None) -> DuckDBSpatialRepository:
    return DuckDBSpatialRepository(resolve_database_path(database_path))


def _build_zone_assignment_repository(
    database_path: Path | None,
) -> DuckDBZoneAssignmentRepository:
    return DuckDBZoneAssignmentRepository(resolve_database_path(database_path))


def _build_economy_repository(database_path: Path | None) -> DuckDBEconomyRepository:
    return DuckDBEconomyRepository(resolve_database_path(database_path))


def _build_round_feature_repository(
    database_path: Path | None,
) -> DuckDBRoundFeatureRepository:
    return DuckDBRoundFeatureRepository(resolve_database_path(database_path))


def _build_opponent_repository(
    database_path: Path | None,
) -> DuckDBOpponentRepository:
    return DuckDBOpponentRepository(resolve_database_path(database_path))


def _build_pattern_repository(database_path: Path | None) -> DuckDBPatternRepository:
    return DuckDBPatternRepository(resolve_database_path(database_path))


def _build_analysis_repository(database_path: Path | None) -> DuckDBAnalysisRepository:
    return DuckDBAnalysisRepository(resolve_database_path(database_path))


def _build_counter_strategy_repository(
    database_path: Path | None,
) -> DuckDBCounterStrategyRepository:
    return DuckDBCounterStrategyRepository(resolve_database_path(database_path))


def _print_model(model: BaseModel, *, pretty: bool) -> None:
    print(model.model_dump_json(indent=2 if pretty else None))


def _print_value(value: Any, *, pretty: bool) -> None:
    serialized = TypeAdapter(Any).dump_json(value, indent=2 if pretty else None)
    print(serialized.decode("utf-8"))


def _confirm_delete(match_id: UUID) -> bool:
    print(f"Delete match {match_id} and all child rows? [y/N]", file=sys.stderr)
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_analytics_delete(match_id: UUID) -> bool:
    print(
        f"Delete analytics for match {match_id}, preserving canonical data? [y/N]", file=sys.stderr
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_temporal_delete(match_id: UUID) -> bool:
    print(
        f"Delete temporal state for match {match_id}, preserving canonical and analytics? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_spatial_delete(match_id: UUID) -> bool:
    print(
        f"Delete spatial runs for match {match_id}, preserving canonical and temporal data? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_zone_assignment_delete(match_id: UUID) -> bool:
    print(
        f"Delete zone assignment runs for match {match_id}, preserving Spatial data? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_economy_delete(match_id: UUID) -> bool:
    print(
        f"Delete Economy runs for match {match_id}, preserving canonical data? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_round_feature_delete(match_id: UUID) -> bool:
    print(
        f"Delete Stage 8.4 features for match {match_id}, preserving all input runs? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_pattern_delete(profile_id: UUID) -> bool:
    print(
        f"Delete Stage 8.5 pattern runs for opponent profile {profile_id}? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_finding_delete(profile_id: UUID) -> bool:
    print(
        f"Delete Stage 8.6 analysis runs for opponent profile {profile_id}? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _confirm_strategy_delete(profile_id: UUID) -> bool:
    print(
        f"Delete Stage 8.7 strategy runs for opponent profile {profile_id}? [y/N]",
        file=sys.stderr,
    )
    try:
        return input().strip().casefold() in {"y", "yes"}
    except EOFError:
        return False


def _preflight_output(demo: Path, output: Path | None, *, force: bool) -> Path | None:
    if output is None:
        return None
    candidate = output.expanduser().resolve()
    if candidate == demo.expanduser().resolve():
        raise InspectionOutputError("The JSON output path must not replace the input demo.")
    if not candidate.parent.exists() or not candidate.parent.is_dir():
        raise InspectionOutputError(f"Output directory does not exist: {candidate.parent}")
    if candidate.exists() and not force:
        raise InspectionOutputExistsError(
            f"Output file already exists; use --force to replace it: {candidate}"
        )
    return candidate


def _preflight_json_output(output: Path, *, force: bool) -> Path:
    candidate = output.expanduser().resolve()
    if not candidate.parent.exists() or not candidate.parent.is_dir():
        raise InspectionOutputError(f"Output directory does not exist: {candidate.parent}")
    if candidate.exists() and not force:
        raise InspectionOutputExistsError(
            f"Output file already exists; use --force to replace it: {candidate}"
        )
    return candidate


def _write_output(path: Path, serialized: str, *, force: bool) -> None:
    mode = "w" if force else "x"
    try:
        with path.open(mode, encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.write("\n")
    except FileExistsError as exc:
        raise InspectionOutputExistsError(
            f"Output file already exists; use --force to replace it: {path}"
        ) from exc
    except OSError as exc:
        raise InspectionOutputError(f"Could not write JSON output: {path}") from exc


def _exit_code_for(exc: DemoInspectionError) -> int:
    if isinstance(exc, DemoFileNotFoundError):
        return _EXIT_FILE_NOT_FOUND
    if isinstance(exc, DemoFileUnreadableError):
        return _EXIT_FILE_UNREADABLE
    if isinstance(exc, UnsupportedDemoError):
        return _EXIT_UNSUPPORTED
    if isinstance(exc, InspectionOutputError):
        return _EXIT_OUTPUT
    if isinstance(exc, CanonicalImportError):
        return _EXIT_CANONICAL_IMPORT
    if isinstance(exc, PersistenceError):
        return _EXIT_PERSISTENCE
    if isinstance(exc, ParserContractError):
        return _EXIT_PARSE_OR_CONTRACT
    return _EXIT_PARSE_OR_CONTRACT


if __name__ == "__main__":
    raise SystemExit(main())
