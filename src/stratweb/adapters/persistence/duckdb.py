"""DuckDB adapter for atomic persistence of CanonicalMatchDataset."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb
import polars as pl

from stratweb.adapters.persistence.migrations import MIGRATIONS, Migration
from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGameplayEvent,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalMatchDataset,
    CanonicalPlayer,
    CanonicalRound,
    CanonicalShot,
    CanonicalTeam,
    DataAvailability,
    EventPhase,
    PlayerTeamMembership,
    RoundOutcomeStatus,
    ValidationIssue,
    ValidationSeverity,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.outcome_policy import evaluate_outcome_statuses
from stratweb.application.persistence_models import (
    ImportStatus,
    MatchImportSummary,
    MatchQueryFilters,
    RepositorySaveResult,
    RoundEvents,
    StoredMatch,
)
from stratweb.domain.enums import Side
from stratweb.exceptions import (
    DatabaseInitializationError,
    DatasetIntegrityError,
    MigrationChecksumError,
    PersistenceError,
)

_MATCH_TABLES: tuple[str, ...] = (
    "teams",
    "players",
    "memberships",
    "rounds",
    "kills",
    "damages",
    "shots",
    "grenades",
    "bomb_events",
    "validation_issues",
    "normalization_metadata",
)

_DELETE_ORDER: tuple[str, ...] = (
    "opponent_match_selections",
    "bomb_position_query_rows",
    "spatial_snapshot_query_rows",
    "spatial_validation_issues",
    "spatial_utility_effects",
    "spatial_projectile_snapshots",
    "spatial_projectiles",
    "bomb_position_snapshots",
    "spatial_snapshots",
    "spatial_runs",
    "temporal_validation_issues",
    "temporal_simultaneous_groups",
    "bomb_transitions",
    "life_transitions",
    "participant_round_states",
    "temporal_transitions",
    "temporal_events",
    "phase_intervals",
    "round_timelines",
    "temporal_runs",
    "analytics_validation_issues",
    "man_advantage_transitions",
    "trade_events",
    "opening_duels",
    "team_match_analytics",
    "team_round_analytics",
    "player_match_analytics",
    "player_round_analytics",
    "analytics_runs",
    "normalization_metadata",
    "validation_issues",
    "bomb_events",
    "grenades",
    "shots",
    "damages",
    "kills",
    "rounds",
    "memberships",
    "players",
    "teams",
    "matches",
)

# match_id-bearing tables that intentionally survive match deletion:
# import_jobs keeps durable job history across deletes and re-imports.
_MATCH_DELETE_EXEMPT: frozenset[str] = frozenset({"import_jobs"})


def _match_scoped_tables(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT DISTINCT table_name FROM information_schema.columns "
        "WHERE table_schema = 'main' AND column_name = 'match_id' "
        "ORDER BY table_name"
    ).fetchall()
    return tuple(str(row[0]) for row in rows if str(row[0]) not in _MATCH_DELETE_EXEMPT)


_INITIALIZATION_LOCK = threading.Lock()
_INITIALIZED_DATABASES: dict[
    tuple[Path, tuple[tuple[int, str, str], ...]], tuple[int, int, int]
] = {}


def _database_identity(path: Path) -> tuple[int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns


class DuckDBMatchRepository:
    """Owns DuckDB connections; every canonical dataset is one transaction."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        migrations: Sequence[Migration] = MIGRATIONS,
    ) -> None:
        self._database_path = Path(database_path).expanduser().resolve()
        self._migrations = tuple(sorted(migrations, key=lambda item: item.version))

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        migration_key = tuple((item.version, item.name, item.checksum) for item in self._migrations)
        cache_key = (self._database_path, migration_key)
        with _INITIALIZATION_LOCK:
            current_identity = _database_identity(self._database_path)
            if current_identity is not None and _INITIALIZED_DATABASES.get(cache_key) == (
                current_identity
            ):
                return ()
            self._database_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with self._connect() as connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                            version INTEGER PRIMARY KEY,
                            name VARCHAR NOT NULL,
                            applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
                            checksum VARCHAR(64) NOT NULL
                        )
                        """
                    )
                    applied_rows = connection.execute(
                        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
                    ).fetchall()
                    applied = {int(row[0]): (str(row[1]), str(row[2])) for row in applied_rows}
                    known_versions = {migration.version for migration in self._migrations}
                    unknown_versions = sorted(set(applied) - known_versions)
                    if unknown_versions:
                        raise DatabaseInitializationError(
                            "Database contains migrations unknown to this application version: "
                            + ", ".join(str(version) for version in unknown_versions)
                        )
                    pending: list[Migration] = []
                    for migration in self._migrations:
                        existing = applied.get(migration.version)
                        if existing is None:
                            pending.append(migration)
                            continue
                        existing_name, existing_checksum = existing
                        if (
                            existing_name != migration.name
                            or existing_checksum != migration.checksum
                        ):
                            raise MigrationChecksumError(
                                f"Migration {migration.version} ({migration.name}) checksum "
                                "does not match the applied database migration."
                            )
                newly_applied: list[int] = []
                for migration in pending:
                    # A fresh connection is required between a backfill migration and
                    # a following ART-index migration in DuckDB.
                    with self._connect() as connection:
                        connection.execute("CHECKPOINT")
                        connection.execute("BEGIN TRANSACTION")
                        try:
                            connection.execute(migration.sql)
                            connection.execute(
                                """
                                INSERT INTO schema_migrations(version, name, checksum)
                                VALUES (?, ?, ?)
                                """,
                                [migration.version, migration.name, migration.checksum],
                            )
                            connection.execute("COMMIT")
                        except Exception:
                            connection.execute("ROLLBACK")
                            raise
                        newly_applied.append(migration.version)
                identity = _database_identity(self._database_path)
                if identity is not None:
                    _INITIALIZED_DATABASES[cache_key] = identity
                return tuple(newly_applied)
            except MigrationChecksumError:
                raise
            except duckdb.Error as exc:
                raise DatabaseInitializationError(
                    f"Could not initialize DuckDB database: {self._database_path}"
                ) from exc

    def save_match(
        self,
        dataset: CanonicalMatchDataset,
        *,
        source_original_name: str | None = None,
        replace: bool = False,
    ) -> RepositorySaveResult:
        self.initialize()
        match_id = dataset.match.match_id
        fingerprint = dataset.dataset_fingerprint
        try:
            with self._connect() as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    existing_rows = connection.execute(
                        """
                        SELECT match_id, dataset_fingerprint
                        FROM matches
                        WHERE match_id = ? OR dataset_fingerprint = ?
                        """,
                        [match_id, fingerprint],
                    ).fetchall()
                    existing_ids = {UUID(str(row[0])) for row in existing_rows}
                    matching_fingerprint_ids = {
                        UUID(str(row[0])) for row in existing_rows if str(row[1]) == fingerprint
                    }
                    match_id_collision = any(
                        UUID(str(row[0])) == match_id and str(row[1]) != fingerprint
                        for row in existing_rows
                    )
                    if match_id_collision and not replace:
                        raise DatasetIntegrityError(
                            f"Match ID {match_id} already exists with another fingerprint; "
                            "an explicit replace is required."
                        )
                    if matching_fingerprint_ids and not replace:
                        existing_id = next(iter(sorted(matching_fingerprint_ids, key=str)))
                        counts = self._table_counts(connection, existing_id)
                        connection.execute("ROLLBACK")
                        return RepositorySaveResult(
                            match_id=existing_id,
                            dataset_fingerprint=fingerprint,
                            status=ImportStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    for existing_id in sorted(existing_ids, key=str):
                        self._delete_match_in_connection(connection, existing_id)
                    self._insert_dataset(
                        connection,
                        dataset,
                        source_original_name=source_original_name,
                    )
                    expected = _expected_counts(dataset)
                    self._verify_persisted_integrity(connection, dataset, expected)
                    connection.execute("COMMIT")
                    return RepositorySaveResult(
                        match_id=match_id,
                        dataset_fingerprint=fingerprint,
                        status=(ImportStatus.REPLACED if existing_ids else ImportStatus.IMPORTED),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except PersistenceError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not persist canonical match {match_id}.") from exc

    def match_exists(self, match_id: UUID) -> bool:
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM matches WHERE match_id = ? LIMIT 1", [match_id]
            ).fetchone()
        return row is not None

    def get_match(self, match_id: UUID) -> StoredMatch | None:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                "SELECT * FROM matches WHERE match_id = ?",
                [match_id],
            )
        return _stored_match(rows[0]) if rows else None

    def get_match_by_fingerprint(self, fingerprint: str) -> StoredMatch | None:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                "SELECT * FROM matches WHERE dataset_fingerprint = ?",
                [fingerprint],
            )
        return _stored_match(rows[0]) if rows else None

    def list_matches(self, filters: MatchQueryFilters) -> tuple[StoredMatch, ...]:
        where: list[str] = []
        parameters: list[object] = []
        if filters.map_name is not None:
            where.append("map_name = ?")
            parameters.append(filters.map_name)
        if filters.source_demo_sha256 is not None:
            where.append("source_demo_sha256 = ?")
            parameters.append(filters.source_demo_sha256)
        if filters.parser_name is not None:
            where.append("parser_name = ?")
            parameters.append(filters.parser_name)
        clause = " WHERE " + " AND ".join(where) if where else ""
        parameters.extend((filters.limit, filters.offset))
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                "SELECT * FROM matches"
                + clause
                + " ORDER BY imported_at DESC, match_id LIMIT ? OFFSET ?",
                parameters,
            )
        return tuple(_stored_match(row) for row in rows)

    def delete_match(self, match_id: UUID) -> bool:
        self.initialize()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    exists = connection.execute(
                        "SELECT 1 FROM matches WHERE match_id = ?", [match_id]
                    ).fetchone()
                    if exists is None:
                        connection.execute("ROLLBACK")
                        return False
                    self._delete_match_in_connection(connection, match_id)
                    self._verify_match_absent(connection, match_id)
                    connection.execute("COMMIT")
                    return True
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except PersistenceError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError(f"Could not delete match {match_id}.") from exc

    def get_import_summary(self, match_id: UUID) -> MatchImportSummary | None:
        match = self.get_match(match_id)
        if match is None:
            return None
        with self._read_connection() as connection:
            issue_rows = connection.execute(
                """
                SELECT severity, count(*)
                FROM validation_issues
                WHERE match_id = ?
                GROUP BY severity
                ORDER BY severity
                """,
                [match_id],
            ).fetchall()
            issue_counts = {severity.value: 0 for severity in ValidationSeverity}
            issue_counts.update({str(row[0]): int(row[1]) for row in issue_rows})
            counts = self._table_counts(connection, match_id)
            outcome_rows = connection.execute(
                "SELECT outcome_status FROM rounds WHERE match_id = ? ORDER BY round_number",
                [match_id],
            ).fetchall()
            round_outcome = evaluate_outcome_statuses(
                tuple(RoundOutcomeStatus(str(row[0])) for row in outcome_rows)
            )
        return MatchImportSummary(
            match=match,
            row_counts=counts,
            validation_issue_counts=issue_counts,
            round_outcome=round_outcome,
        )

    def get_players(self, match_id: UUID) -> tuple[CanonicalPlayer, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                "SELECT * FROM players WHERE match_id = ? ORDER BY player_id",
                [match_id],
            )
        return tuple(_player_from_row(row) for row in rows)

    def get_teams(self, match_id: UUID) -> tuple[CanonicalTeam, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                "SELECT * FROM teams WHERE match_id = ? ORDER BY team_id",
                [match_id],
            )
        return tuple(_team_from_row(row) for row in rows)

    def get_memberships(self, match_id: UUID) -> tuple[PlayerTeamMembership, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                """
                SELECT * FROM memberships WHERE match_id = ?
                ORDER BY player_id, valid_from_tick, side, team_id
                """,
                [match_id],
            )
        return tuple(_membership_from_row(row) for row in rows)

    def get_rounds(self, match_id: UUID) -> tuple[CanonicalRound, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                "SELECT * FROM rounds WHERE match_id = ? ORDER BY round_number",
                [match_id],
            )
        return tuple(_round_from_row(row) for row in rows)

    def get_round_events(self, match_id: UUID, round_number: int) -> RoundEvents | None:
        with self._read_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM rounds WHERE match_id = ? AND round_number = ?",
                [match_id, round_number],
            ).fetchone()
            if exists is None:
                return None
            parameters: list[object] = [match_id, round_number]
            kills = tuple(
                _kill_from_row(row)
                for row in _fetch_dicts(
                    connection,
                    "SELECT * FROM kills WHERE match_id = ? AND round_number = ? "
                    "ORDER BY tick, event_id",
                    parameters,
                )
            )
            damages = tuple(
                _damage_from_row(row)
                for row in _fetch_dicts(
                    connection,
                    "SELECT * FROM damages WHERE match_id = ? AND round_number = ? "
                    "ORDER BY tick, event_id",
                    parameters,
                )
            )
            shots = tuple(
                _shot_from_row(row)
                for row in _fetch_dicts(
                    connection,
                    "SELECT * FROM shots WHERE match_id = ? AND round_number = ? "
                    "ORDER BY tick, event_id",
                    parameters,
                )
            )
            grenades = tuple(
                _grenade_from_row(row)
                for row in _fetch_dicts(
                    connection,
                    "SELECT * FROM grenades WHERE match_id = ? AND round_number = ? "
                    "ORDER BY tick, event_id",
                    parameters,
                )
            )
            bomb_events = tuple(
                _bomb_from_row(row)
                for row in _fetch_dicts(
                    connection,
                    "SELECT * FROM bomb_events WHERE match_id = ? AND round_number = ? "
                    "ORDER BY tick, event_id",
                    parameters,
                )
            )
        return RoundEvents(
            match_id=match_id,
            round_number=round_number,
            kills=kills,
            damages=damages,
            shots=shots,
            grenades=grenades,
            bomb_events=bomb_events,
        )

    def get_player_kills(self, match_id: UUID, player_id: UUID) -> tuple[CanonicalKill, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                """
                SELECT * FROM kills
                WHERE match_id = ? AND (
                    attacker_player_id = ? OR victim_player_id = ? OR assister_player_id = ?
                )
                ORDER BY tick, event_id
                """,
                [match_id, player_id, player_id, player_id],
            )
        return tuple(_kill_from_row(row) for row in rows)

    def get_player_grenades(self, match_id: UUID, player_id: UUID) -> tuple[CanonicalGrenade, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                """
                SELECT * FROM grenades
                WHERE match_id = ? AND player_id = ?
                ORDER BY tick, event_id
                """,
                [match_id, player_id],
            )
        return tuple(_grenade_from_row(row) for row in rows)

    def get_validation_issues(self, match_id: UUID) -> tuple[ValidationIssue, ...]:
        with self._read_connection() as connection:
            rows = _fetch_dicts(
                connection,
                """
                SELECT * FROM validation_issues
                WHERE match_id = ?
                ORDER BY issue_index
                """,
                [match_id],
            )
        return tuple(_validation_issue_from_row(row) for row in rows)

    def get_table_counts(self, match_id: UUID) -> dict[str, int]:
        with self._read_connection() as connection:
            return self._table_counts(connection, match_id)

    @contextmanager
    def _connect(self, *, read_only: bool = False) -> Iterator[duckdb.DuckDBPyConnection]:
        connection = duckdb.connect(str(self._database_path), read_only=read_only)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _read_connection(self) -> Iterator[duckdb.DuckDBPyConnection]:
        if not self._database_path.is_file():
            raise DatabaseInitializationError(
                f"DuckDB database does not exist: {self._database_path}"
            )
        try:
            # DuckDB requires every connection to one file in a process to use the
            # same configuration. Imports hold read-write connections, so query
            # connections must also use read-write configuration.
            with self._connect(read_only=False) as connection:
                yield connection
        except duckdb.Error as exc:
            raise PersistenceError(
                f"Could not read DuckDB database: {self._database_path}"
            ) from exc

    def _insert_dataset(
        self,
        connection: duckdb.DuckDBPyConnection,
        dataset: CanonicalMatchDataset,
        *,
        source_original_name: str | None,
    ) -> None:
        match = dataset.match
        metadata = dataset.normalization_metadata
        validation = dataset.validation_report
        self._batch_insert(
            connection,
            "matches",
            [
                {
                    "match_id": match.match_id,
                    "demo_file_id": match.demo_file_id,
                    "dataset_fingerprint": dataset.dataset_fingerprint,
                    "source_demo_sha256": metadata.source_demo_sha256,
                    "source_original_name": source_original_name,
                    "map_name": match.map_name,
                    "server_name": match.server_name,
                    "round_count": match.round_count,
                    "complete_round_count": match.complete_round_count,
                    "incomplete_round_count": match.incomplete_round_count,
                    "round_count_candidates": canonical_json(match.round_count_candidates),
                    "selected_round_count": match.selected_round_count,
                    "selected_round_count_source": match.selected_round_count_source,
                    "round_count_disagreement": match.round_count_disagreement,
                    "validation_is_valid": validation.is_valid,
                    "validation_has_fatal_errors": validation.has_fatal_errors,
                    "validation_fatal_error_count": validation.fatal_error_count,
                    "validation_unassigned_event_count": validation.unassigned_event_count,
                    "validation_unknown_player_count": validation.unknown_player_count,
                    "validation_incomplete_round_count": validation.incomplete_round_count,
                    "validation_issue_counts": canonical_json(
                        {
                            severity.value: count
                            for severity, count in validation.issue_counts.items()
                        }
                    ),
                    "parser_name": metadata.parser_name,
                    "parser_version": metadata.parser_version,
                    "canonical_schema_version": metadata.canonical_schema_version,
                    "normalization_rule_version": metadata.normalization_rule_version,
                    "normalization_config_hash": metadata.normalization_config_hash,
                }
            ],
        )
        self._batch_insert(
            connection,
            "teams",
            [
                {
                    "match_id": team.match_id,
                    "team_id": team.team_id,
                    "internal_name": team.internal_name,
                    "display_name": team.display_name,
                    "starting_player_ids": canonical_json(
                        [str(player_id) for player_id in team.starting_player_ids]
                    ),
                    "identity_confidence": team.identity_confidence,
                    "warnings": canonical_json(list(team.warnings)),
                }
                for team in dataset.teams
            ],
        )
        self._batch_insert(
            connection,
            "players",
            [
                {
                    "match_id": match.match_id,
                    "player_id": player.player_id,
                    "steam_id": player.steam_id,
                    "current_name": player.current_name,
                    "known_names": canonical_json(list(player.known_names)),
                    "is_bot": player.is_bot,
                    "warnings": canonical_json(list(player.warnings)),
                }
                for player in dataset.players
            ],
        )
        self._batch_insert(
            connection,
            "memberships",
            [
                {
                    "match_id": match.match_id,
                    "player_id": membership.player_id,
                    "team_id": membership.team_id,
                    "side": membership.side.value,
                    "valid_from_tick": membership.valid_from_tick,
                    "valid_to_tick": membership.valid_to_tick,
                    "source": membership.source,
                    "confidence": membership.confidence,
                }
                for membership in dataset.player_team_memberships
            ],
        )
        self._batch_insert(
            connection,
            "rounds",
            [_round_to_row(round_item) for round_item in dataset.rounds],
        )
        self._batch_insert(
            connection,
            "kills",
            [_kill_to_row(event) for event in dataset.kills],
        )
        self._batch_insert(
            connection,
            "damages",
            [_damage_to_row(event) for event in dataset.damages],
        )
        self._batch_insert(
            connection,
            "shots",
            [_shot_to_row(event) for event in dataset.shots],
        )
        self._batch_insert(
            connection,
            "grenades",
            [_grenade_to_row(event) for event in dataset.grenades],
        )
        self._batch_insert(
            connection,
            "bomb_events",
            [_bomb_to_row(event) for event in dataset.bomb_events],
        )
        self._batch_insert(
            connection,
            "validation_issues",
            [
                {
                    "match_id": match.match_id,
                    "issue_index": index,
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "is_fatal": issue.is_fatal,
                    "entity_type": issue.entity_type,
                    "entity_id": issue.entity_id,
                    "message": issue.message,
                    "evidence": canonical_json(issue.evidence),
                    "rule_version": issue.rule_version,
                }
                for index, issue in enumerate(validation.issues)
            ],
        )
        self._batch_insert(
            connection,
            "normalization_metadata",
            [
                {
                    "match_id": match.match_id,
                    "source_event_counts": canonical_json(metadata.source_event_counts),
                    "selected_event_aliases": canonical_json(metadata.selected_event_aliases),
                    "result_capabilities": canonical_json(
                        metadata.result_capabilities.model_dump(mode="json")
                    ),
                    "warnings": canonical_json(list(metadata.warnings)),
                }
            ],
        )

    def _batch_insert(
        self,
        connection: duckdb.DuckDBPyConnection,
        table: str,
        rows: Sequence[dict[str, object]],
    ) -> None:
        if not rows:
            return
        columns = tuple(rows[0])
        relation_name = f"_stratweb_batch_{table}"
        serializable_rows = [
            {
                column: str(value) if isinstance(value, UUID) else value
                for column, value in row.items()
            }
            for row in rows
        ]
        frame = pl.from_dicts(serializable_rows, infer_schema_length=None, strict=False)
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        connection.register(relation_name, frame)
        try:
            connection.execute(
                f'INSERT INTO "{table}" ({quoted_columns}) '
                f'SELECT {quoted_columns} FROM "{relation_name}"'
            )
        finally:
            connection.unregister(relation_name)

    def _table_counts(
        self, connection: duckdb.DuckDBPyConnection, match_id: UUID
    ) -> dict[str, int]:
        counts: dict[str, int] = {"matches": 0}
        match_count = connection.execute(
            "SELECT count(*) FROM matches WHERE match_id = ?", [match_id]
        ).fetchone()
        counts["matches"] = int(match_count[0]) if match_count else 0
        for table in _MATCH_TABLES:
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE match_id = ?', [match_id]
            ).fetchone()
            counts[table] = int(row[0]) if row else 0
        return counts

    def _verify_persisted_integrity(
        self,
        connection: duckdb.DuckDBPyConnection,
        dataset: CanonicalMatchDataset,
        expected: dict[str, int],
    ) -> None:
        actual = self._table_counts(connection, dataset.match.match_id)
        if actual != expected:
            raise DatasetIntegrityError(
                f"Persisted row counts differ from canonical dataset: {actual!r}."
            )
        row = connection.execute(
            "SELECT dataset_fingerprint FROM matches WHERE match_id = ?",
            [dataset.match.match_id],
        ).fetchone()
        if row is None or str(row[0]) != dataset.dataset_fingerprint:
            raise DatasetIntegrityError("Persisted dataset fingerprint does not match input.")
        orphan_checks: list[str] = [
            "SELECT count(*) FROM rounds r LEFT JOIN matches m USING(match_id) "
            "WHERE r.match_id = ? AND m.match_id IS NULL",
            "SELECT count(*) FROM memberships pm LEFT JOIN players p "
            "ON p.match_id = pm.match_id AND p.player_id = pm.player_id "
            "WHERE pm.match_id = ? AND p.player_id IS NULL",
            "SELECT count(*) FROM memberships pm LEFT JOIN teams t "
            "ON t.match_id = pm.match_id AND t.team_id = pm.team_id "
            "WHERE pm.match_id = ? AND pm.team_id IS NOT NULL AND t.team_id IS NULL",
            "SELECT count(*) FROM rounds r LEFT JOIN teams t "
            "ON t.match_id = r.match_id AND t.team_id = r.t_team_id "
            "WHERE r.match_id = ? AND r.t_team_id IS NOT NULL AND t.team_id IS NULL",
            "SELECT count(*) FROM rounds r LEFT JOIN teams t "
            "ON t.match_id = r.match_id AND t.team_id = r.ct_team_id "
            "WHERE r.match_id = ? AND r.ct_team_id IS NOT NULL AND t.team_id IS NULL",
        ]
        for table in ("kills", "damages", "shots", "grenades", "bomb_events"):
            orphan_checks.append(
                f'SELECT count(*) FROM "{table}" e LEFT JOIN rounds r '
                "ON r.match_id = e.match_id AND r.round_id = e.round_id "
                "WHERE e.match_id = ? AND e.round_id IS NOT NULL AND r.round_id IS NULL"
            )
        actor_references = {
            "kills": (
                ("attacker_player_id", "players", "player_id"),
                ("victim_player_id", "players", "player_id"),
                ("assister_player_id", "players", "player_id"),
                ("attacker_team_id", "teams", "team_id"),
                ("victim_team_id", "teams", "team_id"),
            ),
            "damages": (
                ("attacker_player_id", "players", "player_id"),
                ("victim_player_id", "players", "player_id"),
                ("attacker_team_id", "teams", "team_id"),
                ("victim_team_id", "teams", "team_id"),
            ),
            "shots": (
                ("player_id", "players", "player_id"),
                ("team_id", "teams", "team_id"),
            ),
            "grenades": (
                ("player_id", "players", "player_id"),
                ("team_id", "teams", "team_id"),
            ),
            "bomb_events": (
                ("player_id", "players", "player_id"),
                ("team_id", "teams", "team_id"),
            ),
        }
        for event_table, references in actor_references.items():
            for event_column, target_table, target_column in references:
                orphan_checks.append(
                    f'SELECT count(*) FROM "{event_table}" e '
                    f'LEFT JOIN "{target_table}" t '
                    f'ON t.match_id = e.match_id AND t."{target_column}" = '
                    f'e."{event_column}" WHERE e.match_id = ? '
                    f'AND e."{event_column}" IS NOT NULL AND t."{target_column}" IS NULL'
                )
        for query in orphan_checks:
            orphan_count = connection.execute(query, [dataset.match.match_id]).fetchone()
            if orphan_count and int(orphan_count[0]):
                raise DatasetIntegrityError("Orphan rows detected after canonical import.")

    def _delete_match_in_connection(
        self, connection: duckdb.DuckDBPyConnection, match_id: UUID
    ) -> None:
        for table in _DELETE_ORDER:
            connection.execute(f'DELETE FROM "{table}" WHERE match_id = ?', [match_id])

    def _verify_match_absent(self, connection: duckdb.DuckDBPyConnection, match_id: UUID) -> None:
        remaining: list[str] = []
        for table in _match_scoped_tables(connection):
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE match_id = ?', [match_id]
            ).fetchone()
            if row and int(row[0]):
                remaining.append(table)
        if remaining:
            raise DatasetIntegrityError(
                f"Rows remain after deleting match {match_id}: {', '.join(remaining)}."
            )


def _expected_counts(dataset: CanonicalMatchDataset) -> dict[str, int]:
    return {
        "matches": 1,
        "teams": len(dataset.teams),
        "players": len(dataset.players),
        "memberships": len(dataset.player_team_memberships),
        "rounds": len(dataset.rounds),
        "kills": len(dataset.kills),
        "damages": len(dataset.damages),
        "shots": len(dataset.shots),
        "grenades": len(dataset.grenades),
        "bomb_events": len(dataset.bomb_events),
        "validation_issues": len(dataset.validation_report.issues),
        "normalization_metadata": 1,
    }


def _round_to_row(round_item: CanonicalRound) -> dict[str, object]:
    return {
        "match_id": round_item.match_id,
        "round_id": round_item.round_id,
        "round_number": round_item.round_number,
        "start_tick": round_item.start_tick,
        "freeze_end_tick": round_item.freeze_end_tick,
        "end_tick": round_item.end_tick,
        "official_end_tick": round_item.official_end_tick,
        "start_source": round_item.start_source,
        "end_source": round_item.end_source,
        "t_team_id": round_item.t_team_id,
        "ct_team_id": round_item.ct_team_id,
        "winner_side": round_item.winner_side.value if round_item.winner_side else None,
        "outcome_status": round_item.outcome_status.value,
        "outcome_source": round_item.outcome_source,
        "end_reason": round_item.end_reason,
        "end_reason_status": round_item.end_reason_status.value,
        "end_reason_source": round_item.end_reason_source,
        "score_t_before": round_item.score_t_before,
        "score_ct_before": round_item.score_ct_before,
        "score_t_after": round_item.score_t_after,
        "score_ct_after": round_item.score_ct_after,
        "score_status": round_item.score_status.value,
        "score_source": round_item.score_source,
        "is_warmup": round_item.is_warmup,
        "is_overtime": round_item.is_overtime,
        "is_complete": round_item.is_complete,
        "exclusion_reason": round_item.exclusion_reason,
        "warnings": canonical_json(list(round_item.warnings)),
    }


def _event_to_row(event: CanonicalGameplayEvent) -> dict[str, object]:
    return {
        "match_id": event.match_id,
        "event_id": event.event_id,
        "round_id": event.round_id,
        "round_number": event.round_number,
        "tick": event.tick,
        "relative_tick": event.relative_tick,
        "phase": event.phase.value,
        "source_event": event.source_event,
        "warnings": canonical_json(list(event.warnings)),
    }


def _kill_to_row(event: CanonicalKill) -> dict[str, object]:
    row = _event_to_row(event)
    row.update(
        {
            "attacker_player_id": event.attacker_player_id,
            "victim_player_id": event.victim_player_id,
            "assister_player_id": event.assister_player_id,
            "attacker_team_id": event.attacker_team_id,
            "victim_team_id": event.victim_team_id,
            "attacker_side": event.attacker_side.value,
            "victim_side": event.victim_side.value,
            "weapon": event.weapon,
            "headshot": event.headshot,
            "penetrated": event.penetrated,
            "through_smoke": event.through_smoke,
            "no_scope": event.no_scope,
            "attacker_blind": event.attacker_blind,
            "distance": event.distance,
            "is_teamkill": event.is_teamkill,
            "is_suicide": event.is_suicide,
        }
    )
    return row


def _damage_to_row(event: CanonicalDamage) -> dict[str, object]:
    row = _event_to_row(event)
    row.update(
        {
            "attacker_player_id": event.attacker_player_id,
            "victim_player_id": event.victim_player_id,
            "attacker_team_id": event.attacker_team_id,
            "victim_team_id": event.victim_team_id,
            "attacker_side": event.attacker_side.value,
            "victim_side": event.victim_side.value,
            "weapon": event.weapon,
            "damage_health": event.damage_health,
            "damage_armor": event.damage_armor,
            "victim_health_after": event.victim_health_after,
            "hitgroup": event.hitgroup,
        }
    )
    return row


def _shot_to_row(event: CanonicalShot) -> dict[str, object]:
    row = _event_to_row(event)
    row.update(
        {
            "player_id": event.player_id,
            "team_id": event.team_id,
            "side": event.side.value,
            "weapon": event.weapon,
            "silenced": event.silenced,
        }
    )
    return row


def _grenade_to_row(event: CanonicalGrenade) -> dict[str, object]:
    row = _event_to_row(event)
    row.update(
        {
            "player_id": event.player_id,
            "team_id": event.team_id,
            "side": event.side.value,
            "grenade_type": event.grenade_type,
            "lifecycle_event": event.lifecycle_event,
            "entity_id": event.entity_id,
            "x": event.x,
            "y": event.y,
            "z": event.z,
        }
    )
    return row


def _bomb_to_row(event: CanonicalBombEvent) -> dict[str, object]:
    row = _event_to_row(event)
    row.update(
        {
            "player_id": event.player_id,
            "team_id": event.team_id,
            "side": event.side.value,
            "event_type": event.event_type,
            "site_raw": canonical_json(event.site_raw) if event.site_raw is not None else None,
            "site_normalized": event.site_normalized,
        }
    )
    return row


def _fetch_dicts(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: Sequence[object] = (),
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, list(parameters))
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _json_value(value: object) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _stored_match(row: dict[str, Any]) -> StoredMatch:
    return StoredMatch(
        match_id=row["match_id"],
        demo_file_id=row["demo_file_id"],
        dataset_fingerprint=row["dataset_fingerprint"],
        source_demo_sha256=row["source_demo_sha256"],
        source_original_name=row["source_original_name"],
        map_name=row["map_name"],
        server_name=row["server_name"],
        round_count=row["round_count"],
        complete_round_count=row["complete_round_count"],
        incomplete_round_count=row["incomplete_round_count"],
        validation_has_fatal_errors=row["validation_has_fatal_errors"],
        validation_fatal_error_count=row["validation_fatal_error_count"],
        parser_name=row["parser_name"],
        parser_version=row["parser_version"],
        canonical_schema_version=row["canonical_schema_version"],
        normalization_rule_version=row["normalization_rule_version"],
        normalization_config_hash=row["normalization_config_hash"],
        imported_at=row["imported_at"],
    )


def _player_from_row(row: dict[str, Any]) -> CanonicalPlayer:
    return CanonicalPlayer(
        player_id=row["player_id"],
        steam_id=row["steam_id"],
        current_name=row["current_name"],
        known_names=tuple(_json_value(row["known_names"])),
        is_bot=row["is_bot"],
        warnings=tuple(_json_value(row["warnings"])),
    )


def _team_from_row(row: dict[str, Any]) -> CanonicalTeam:
    return CanonicalTeam(
        team_id=row["team_id"],
        match_id=row["match_id"],
        internal_name=row["internal_name"],
        display_name=row["display_name"],
        starting_player_ids=tuple(UUID(value) for value in _json_value(row["starting_player_ids"])),
        identity_confidence=row["identity_confidence"],
        warnings=tuple(_json_value(row["warnings"])),
    )


def _membership_from_row(row: dict[str, Any]) -> PlayerTeamMembership:
    return PlayerTeamMembership(
        player_id=row["player_id"],
        team_id=row["team_id"],
        side=Side(row["side"]),
        valid_from_tick=row["valid_from_tick"],
        valid_to_tick=row["valid_to_tick"],
        source=row["source"],
        confidence=row["confidence"],
    )


def _round_from_row(row: dict[str, Any]) -> CanonicalRound:
    return CanonicalRound(
        round_id=row["round_id"],
        match_id=row["match_id"],
        round_number=row["round_number"],
        start_tick=row["start_tick"],
        freeze_end_tick=row["freeze_end_tick"],
        end_tick=row["end_tick"],
        official_end_tick=row["official_end_tick"],
        start_source=row["start_source"],
        end_source=row["end_source"],
        t_team_id=row["t_team_id"],
        ct_team_id=row["ct_team_id"],
        winner_side=Side(row["winner_side"]) if row["winner_side"] is not None else None,
        outcome_status=RoundOutcomeStatus(row["outcome_status"]),
        outcome_source=row["outcome_source"],
        end_reason=row["end_reason"],
        end_reason_status=DataAvailability(row["end_reason_status"]),
        end_reason_source=row["end_reason_source"],
        score_t_before=row["score_t_before"],
        score_ct_before=row["score_ct_before"],
        score_t_after=row["score_t_after"],
        score_ct_after=row["score_ct_after"],
        score_status=DataAvailability(row["score_status"]),
        score_source=row["score_source"],
        is_warmup=row["is_warmup"],
        is_overtime=row["is_overtime"],
        is_complete=row["is_complete"],
        exclusion_reason=row["exclusion_reason"],
        warnings=tuple(_json_value(row["warnings"])),
    )


def _event_kwargs(row: dict[str, Any]) -> dict[str, object]:
    return {
        "event_id": row["event_id"],
        "match_id": row["match_id"],
        "round_id": row["round_id"],
        "round_number": row["round_number"],
        "tick": row["tick"],
        "relative_tick": row["relative_tick"],
        "phase": EventPhase(row["phase"]),
        "source_event": row["source_event"],
        "warnings": tuple(_json_value(row["warnings"])),
    }


def _kill_from_row(row: dict[str, Any]) -> CanonicalKill:
    return CanonicalKill(
        **_event_kwargs(row),
        attacker_player_id=row["attacker_player_id"],
        victim_player_id=row["victim_player_id"],
        assister_player_id=row["assister_player_id"],
        attacker_team_id=row["attacker_team_id"],
        victim_team_id=row["victim_team_id"],
        attacker_side=Side(row["attacker_side"]),
        victim_side=Side(row["victim_side"]),
        weapon=row["weapon"],
        headshot=row["headshot"],
        penetrated=row["penetrated"],
        through_smoke=row["through_smoke"],
        no_scope=row["no_scope"],
        attacker_blind=row["attacker_blind"],
        distance=row["distance"],
        is_teamkill=row["is_teamkill"],
        is_suicide=row["is_suicide"],
    )


def _damage_from_row(row: dict[str, Any]) -> CanonicalDamage:
    return CanonicalDamage(
        **_event_kwargs(row),
        attacker_player_id=row["attacker_player_id"],
        victim_player_id=row["victim_player_id"],
        attacker_team_id=row["attacker_team_id"],
        victim_team_id=row["victim_team_id"],
        attacker_side=Side(row["attacker_side"]),
        victim_side=Side(row["victim_side"]),
        weapon=row["weapon"],
        damage_health=row["damage_health"],
        damage_armor=row["damage_armor"],
        victim_health_after=row["victim_health_after"],
        hitgroup=row["hitgroup"],
    )


def _shot_from_row(row: dict[str, Any]) -> CanonicalShot:
    return CanonicalShot(
        **_event_kwargs(row),
        player_id=row["player_id"],
        team_id=row["team_id"],
        side=Side(row["side"]),
        weapon=row["weapon"],
        silenced=row["silenced"],
    )


def _grenade_from_row(row: dict[str, Any]) -> CanonicalGrenade:
    return CanonicalGrenade(
        **_event_kwargs(row),
        player_id=row["player_id"],
        team_id=row["team_id"],
        side=Side(row["side"]),
        grenade_type=row["grenade_type"],
        lifecycle_event=row["lifecycle_event"],
        entity_id=row["entity_id"],
        x=row["x"],
        y=row["y"],
        z=row["z"],
    )


def _bomb_from_row(row: dict[str, Any]) -> CanonicalBombEvent:
    return CanonicalBombEvent(
        **_event_kwargs(row),
        player_id=row["player_id"],
        team_id=row["team_id"],
        side=Side(row["side"]),
        event_type=row["event_type"],
        site_raw=_json_value(row["site_raw"]) if row["site_raw"] is not None else None,
        site_normalized=row["site_normalized"],
    )


def _validation_issue_from_row(row: dict[str, Any]) -> ValidationIssue:
    return ValidationIssue(
        code=row["code"],
        severity=ValidationSeverity(row["severity"]),
        is_fatal=row["is_fatal"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        message=row["message"],
        evidence=_json_value(row["evidence"]),
        rule_version=row["rule_version"],
    )
