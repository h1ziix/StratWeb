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

from stratweb.adapters.parsers import Demoparser2Adapter, Demoparser2SpatialExtractor
from stratweb.adapters.persistence import (
    DuckDBAnalyticsRepository,
    DuckDBMatchRepository,
    DuckDBSpatialRepository,
    DuckDBTemporalRepository,
)
from stratweb.adapters.persistence.migrations import MIGRATIONS
from stratweb.application.analytics import (
    AnalyticsQueryService,
    ComputeMatchAnalyticsService,
    resolve_analytics_config,
)
from stratweb.application.canonical_models import CanonicalizationSummary
from stratweb.application.canonicalization import CanonicalizationService
from stratweb.application.inspection import DemoInspectionService
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
from stratweb.application.spatial import ComputeSpatialStateService, SpatialQueryService
from stratweb.application.temporal import ComputeTemporalStateService, TemporalQueryService
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
from stratweb.spatial.models import SpatialConfig
from stratweb.temporal.models import TemporalConfig

_EXIT_UNEXPECTED = 1
_EXIT_FILE_NOT_FOUND = 3
_EXIT_FILE_UNREADABLE = 4
_EXIT_UNSUPPORTED = 5
_EXIT_PARSE_OR_CONTRACT = 6
_EXIT_OUTPUT = 7
_EXIT_FATAL_VALIDATION = 8
_EXIT_PERSISTENCE = 9
_EXIT_CANONICAL_IMPORT = 10


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
        raise AssertionError(f"Unhandled CLI command: {args.command}")
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
