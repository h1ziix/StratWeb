"""DuckDB adapter for atomic, versioned spatial runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence._feature_cascade import delete_dependent_feature_runs
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import PersistenceError, SpatialIntegrityError
from stratweb.spatial.models import (
    SPATIAL_RULE_VERSION,
    SPATIAL_SCHEMA_VERSION,
    BombPositionSnapshot,
    SpatialComputeStatus,
    SpatialMatchState,
    SpatialRunRecord,
    SpatialRunSummary,
    SpatialSaveResult,
    SpatialSnapshot,
    SpatialValidationIssue,
)
from stratweb.spatial.projectiles import (
    ProjectileSnapshot,
    SpatialProjectile,
    UtilityEffect,
    unavailable_projectile_capabilities,
)

_CHILD_TABLES = (
    "spatial_validation_issues",
    "spatial_utility_effects",
    "spatial_projectile_snapshots",
    "spatial_projectiles",
    "bomb_position_snapshots",
    "spatial_snapshots",
)

_QUERY_TABLES = (
    "bomb_position_query_rows",
    "spatial_snapshot_query_rows",
)


class DuckDBSpatialRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_spatial(self, state: SpatialMatchState, *, replace: bool = False) -> SpatialSaveResult:
        self.initialize()
        expected = _row_counts(state)
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    match = connection.execute(
                        "SELECT dataset_fingerprint, source_demo_sha256 FROM matches "
                        "WHERE match_id = ?",
                        [state.match_id],
                    ).fetchone()
                    if match is None or str(match[0]) != state.dataset_fingerprint:
                        raise SpatialIntegrityError(
                            "Spatial input does not match persisted canonical dataset."
                        )
                    if str(match[1]) != state.source_demo_sha256:
                        raise SpatialIntegrityError(
                            "Spatial source SHA does not match persisted canonical source."
                        )
                    temporal = connection.execute(
                        "SELECT temporal_fingerprint FROM temporal_runs "
                        "WHERE temporal_run_id = ? AND match_id = ?",
                        [state.temporal_run_id, state.match_id],
                    ).fetchone()
                    if temporal is None or str(temporal[0]) != state.temporal_fingerprint:
                        raise SpatialIntegrityError(
                            "Spatial run references an unknown Temporal run."
                        )
                    exact = connection.execute(
                        "SELECT spatial_run_id FROM spatial_runs WHERE spatial_fingerprint = ?",
                        [state.spatial_fingerprint],
                    ).fetchone()
                    collisions = connection.execute(
                        """
                        SELECT spatial_run_id, spatial_fingerprint FROM spatial_runs
                        WHERE dataset_fingerprint = ? AND temporal_fingerprint = ?
                          AND spatial_rule_version = ? AND spatial_config_hash = ?
                          AND source_demo_sha256 = ?
                        """,
                        [
                            state.dataset_fingerprint,
                            state.temporal_fingerprint,
                            state.spatial_rule_version,
                            state.spatial_config_hash,
                            state.source_demo_sha256,
                        ],
                    ).fetchall()
                    if exact is not None and not replace:
                        counts = self._counts_in_connection(connection, UUID(str(exact[0])))
                        connection.execute("COMMIT")
                        return SpatialSaveResult(
                            spatial_run_id=UUID(str(exact[0])),
                            spatial_fingerprint=state.spatial_fingerprint,
                            status=SpatialComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if (
                        collisions
                        and not replace
                        and all(str(item[1]) != state.spatial_fingerprint for item in collisions)
                    ):
                        raise SpatialIntegrityError(
                            "Same spatial input/config produced another fingerprint."
                        )
                    replacing = exact is not None or bool(collisions)
                    for run_id, _ in collisions:
                        self._delete_run(connection, UUID(str(run_id)))
                    if exact is not None and not collisions:
                        self._delete_run(connection, UUID(str(exact[0])))
                    self._insert(connection, state, expected)
                    actual = self._counts_in_connection(connection, state.spatial_run_id)
                    if actual != expected:
                        raise SpatialIntegrityError(
                            f"Spatial row counts differ after insert: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return SpatialSaveResult(
                        spatial_run_id=state.spatial_run_id,
                        spatial_fingerprint=state.spatial_fingerprint,
                        status=(
                            SpatialComputeStatus.REPLACED
                            if replacing
                            else SpatialComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except SpatialIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist spatial run.") from exc

    def get_summary(self, match_id: UUID) -> SpatialRunSummary | None:
        row = self._latest_run(match_id)
        if row is None:
            return None
        return _summary(row)

    def get_summary_for_run(self, match_id: UUID, spatial_run_id: UUID) -> SpatialRunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "spatial") as connection:
            cursor = connection.execute(
                """
                SELECT * FROM spatial_runs
                WHERE match_id = ? AND spatial_run_id = ?
                """,
                [match_id, spatial_run_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return _summary(dict(zip(columns, row, strict=True)))

    def list_runs(self, match_id: UUID) -> tuple[SpatialRunRecord, ...]:
        self.initialize()
        latest = self._latest_run(match_id)
        latest_id = UUID(str(latest["spatial_run_id"])) if latest else None
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                """
                SELECT spatial_run_id, spatial_fingerprint, match_id, temporal_run_id,
                       spatial_schema_version, spatial_rule_version, created_at,
                       canonical_map_name, selected_map_revision, map_definition_version
                FROM spatial_runs WHERE match_id = ?
                ORDER BY created_at DESC, spatial_fingerprint DESC
                """,
                [match_id],
            ).fetchall()
        return tuple(
            SpatialRunRecord(
                spatial_run_id=row[0],
                spatial_fingerprint=str(row[1]),
                match_id=row[2],
                temporal_run_id=row[3],
                spatial_schema_version=str(row[4]),
                spatial_rule_version=str(row[5]),
                created_at=row[6],
                compatible=(str(row[4]), str(row[5]))
                == (SPATIAL_SCHEMA_VERSION, SPATIAL_RULE_VERSION),
                selected_by_default=row[0] == latest_id,
                canonical_map_name=(str(row[7]) if row[7] is not None else None),
                selected_map_revision=(str(row[8]) if row[8] is not None else None),
                map_definition_version=(str(row[9]) if row[9] is not None else None),
                legacy_map_semantics=row[7] is None,
            )
            for row in rows
        )

    def list_snapshots(
        self,
        match_id: UUID,
        *,
        round_number: int | None = None,
        participant_id: UUID | None = None,
        limit: int = 1000,
        offset: int = 0,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]:
        run_id = spatial_run_id or self._latest_run_id(match_id)
        if run_id is None:
            return ()
        where = ["spatial_run_id = ?", "match_id = ?"]
        params: list[object] = [run_id, match_id]
        if round_number is not None:
            where.append("round_number = ?")
            params.append(round_number)
        if participant_id is not None:
            where.append("participant_id = ?")
            params.append(participant_id)
        params.extend([limit, offset])
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                "SELECT payload FROM spatial_snapshots WHERE "
                + " AND ".join(where)
                + " ORDER BY round_number, tick, participant_id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return tuple(SpatialSnapshot.model_validate(_json(row[0])) for row in rows)

    def list_bomb_positions(
        self, match_id: UUID, *, round_number: int | None = None
    ) -> tuple[BombPositionSnapshot, ...]:
        run_id = self._latest_run_id(match_id)
        if run_id is None:
            return ()
        sql = "SELECT payload FROM bomb_position_snapshots WHERE spatial_run_id = ?"
        params: list[object] = [run_id]
        if round_number is not None:
            sql += " AND round_number = ?"
            params.append(round_number)
        sql += " ORDER BY round_number, tick, snapshot_id"
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(BombPositionSnapshot.model_validate(_json(row[0])) for row in rows)

    def list_round_ticks(
        self,
        match_id: UUID,
        round_number: int,
        *,
        spatial_run_id: UUID | None = None,
    ) -> tuple[int, ...]:
        run_id = spatial_run_id or self._latest_run_id(match_id)
        if run_id is None:
            return ()
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT tick FROM spatial_snapshots
                WHERE spatial_run_id = ? AND round_number = ?
                ORDER BY tick
                """,
                [run_id, round_number],
            ).fetchall()
        return tuple(int(row[0]) for row in rows)

    def get_tick_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        *,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        bomb_carrier_only: bool = False,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]:
        run_id = spatial_run_id or self._latest_run_id(match_id)
        if run_id is None:
            return ()
        where = ["tick_lookup_key = ?"]
        params: list[object] = [_tick_lookup_key(run_id, round_number, tick)]
        if physical_team_id is not None:
            where.append("physical_team_id = ?")
            params.append(physical_team_id)
        if participant_id is not None:
            where.append("participant_id = ?")
            params.append(participant_id)
        if alive_only:
            where.append("alive = true")
        if bomb_carrier_only:
            where.append("has_bomb = true")
        return self._snapshot_query(
            where, params, "participant_id", table="spatial_snapshot_query_rows"
        )

    def get_player_path(
        self,
        match_id: UUID,
        round_number: int,
        participant_id: UUID,
        *,
        reliable_alive_only: bool = True,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]:
        run_id = spatial_run_id or self._latest_run_id(match_id)
        if run_id is None:
            return ()
        where = ["player_path_key = ?", "x IS NOT NULL"]
        if reliable_alive_only:
            where.extend(["alive = true", "position_authority <> 'unreliable'"])
        return self._snapshot_query(
            where,
            [_player_path_key(run_id, round_number, participant_id)],
            "tick, snapshot_id",
            table="spatial_snapshot_query_rows",
        )

    def get_round_path(
        self,
        match_id: UUID,
        round_number: int,
        *,
        physical_team_id: UUID | None = None,
        participant_id: UUID | None = None,
        alive_only: bool = False,
        spatial_run_id: UUID | None = None,
    ) -> tuple[SpatialSnapshot, ...]:
        run_id = spatial_run_id or self._latest_run_id(match_id)
        if run_id is None:
            return ()
        where: list[str]
        params: list[object]
        if participant_id is not None:
            where = ["player_path_key = ?", "x IS NOT NULL"]
            params = [_player_path_key(run_id, round_number, participant_id)]
        else:
            where = ["spatial_run_id = ?", "round_number = ?", "x IS NOT NULL"]
            params = [run_id, round_number]
        if physical_team_id is not None:
            where.append("physical_team_id = ?")
            params.append(physical_team_id)
        if alive_only:
            where.append("alive = true")
        return self._snapshot_query(
            where,
            params,
            "tick, participant_id",
            table=(
                "spatial_snapshot_query_rows" if participant_id is not None else "spatial_snapshots"
            ),
        )

    def get_bomb_position_at_tick(
        self,
        match_id: UUID,
        round_number: int,
        tick: int,
        *,
        spatial_run_id: UUID | None = None,
    ) -> BombPositionSnapshot | None:
        run_id = spatial_run_id or self._latest_run_id(match_id)
        if run_id is None:
            return None
        with read_connection(self._database_path, "spatial") as connection:
            row = connection.execute(
                """
                SELECT payload FROM bomb_position_query_rows
                WHERE tick_lookup_key = ?
                ORDER BY snapshot_id LIMIT 1
                """,
                [_tick_lookup_key(run_id, round_number, tick)],
            ).fetchone()
        return BombPositionSnapshot.model_validate(_json(row[0])) if row else None

    def get_playback_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        ticks: tuple[int, ...],
        *,
        spatial_run_id: UUID,
    ) -> tuple[SpatialSnapshot, ...]:
        if not ticks:
            return ()
        keys = [_tick_lookup_key(spatial_run_id, round_number, tick) for tick in ticks]
        placeholders = ",".join("?" for _ in keys)
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                f"""
                SELECT payload FROM spatial_snapshot_query_rows
                WHERE match_id = ? AND spatial_run_id = ?
                  AND tick_lookup_key IN ({placeholders})
                ORDER BY tick, participant_id
                """,
                [match_id, spatial_run_id, *keys],
            ).fetchall()
        return tuple(SpatialSnapshot.model_validate(_json(row[0])) for row in rows)

    def get_playback_bomb_positions(
        self,
        match_id: UUID,
        round_number: int,
        ticks: tuple[int, ...],
        *,
        spatial_run_id: UUID,
    ) -> tuple[BombPositionSnapshot, ...]:
        if not ticks:
            return ()
        keys = [_tick_lookup_key(spatial_run_id, round_number, tick) for tick in ticks]
        placeholders = ",".join("?" for _ in keys)
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                f"""
                SELECT payload FROM bomb_position_query_rows
                WHERE match_id = ? AND spatial_run_id = ?
                  AND tick_lookup_key IN ({placeholders})
                ORDER BY tick, snapshot_id
                """,
                [match_id, spatial_run_id, *keys],
            ).fetchall()
        return tuple(BombPositionSnapshot.model_validate(_json(row[0])) for row in rows)

    def get_round_projectiles(
        self,
        match_id: UUID,
        round_number: int,
        *,
        spatial_run_id: UUID,
    ) -> tuple[SpatialProjectile, ...]:
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                """
                SELECT payload FROM spatial_projectiles
                WHERE match_id = ? AND spatial_run_id = ? AND round_number = ?
                ORDER BY first_position_tick, projectile_id
                """,
                [match_id, spatial_run_id, round_number],
            ).fetchall()
        return tuple(SpatialProjectile.model_validate(_json(row[0])) for row in rows)

    def get_playback_projectile_snapshots(
        self,
        match_id: UUID,
        round_number: int,
        start_tick: int,
        end_tick: int,
        *,
        spatial_run_id: UUID,
    ) -> tuple[ProjectileSnapshot, ...]:
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                """
                SELECT payload FROM spatial_projectile_snapshots
                WHERE match_id = ? AND spatial_run_id = ? AND round_number = ?
                  AND tick BETWEEN ? AND ?
                ORDER BY tick, projectile_id
                """,
                [match_id, spatial_run_id, round_number, start_tick, end_tick],
            ).fetchall()
        return tuple(ProjectileSnapshot.model_validate(_json(row[0])) for row in rows)

    def get_playback_utility_effects(
        self,
        match_id: UUID,
        round_number: int,
        start_tick: int,
        end_tick: int,
        *,
        spatial_run_id: UUID,
    ) -> tuple[UtilityEffect, ...]:
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                """
                SELECT payload FROM spatial_utility_effects
                WHERE match_id = ? AND spatial_run_id = ? AND round_number = ?
                  AND start_tick <= ? AND (end_tick IS NULL OR end_tick >= ?)
                ORDER BY start_tick, effect_id
                """,
                [match_id, spatial_run_id, round_number, end_tick, start_tick],
            ).fetchall()
        return tuple(UtilityEffect.model_validate(_json(row[0])) for row in rows)

    def list_validation_issues(self, match_id: UUID) -> tuple[SpatialValidationIssue, ...]:
        run_id = self._latest_run_id(match_id)
        if run_id is None:
            return ()
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(
                "SELECT payload FROM spatial_validation_issues WHERE spatial_run_id = ? "
                "ORDER BY issue_index",
                [run_id],
            ).fetchall()
        return tuple(SpatialValidationIssue.model_validate(_json(row[0])) for row in rows)

    def delete_spatial(self, match_id: UUID) -> int:
        self.initialize()
        with duckdb.connect(str(self._database_path)) as connection:
            runs = connection.execute(
                "SELECT spatial_run_id FROM spatial_runs WHERE match_id = ?", [match_id]
            ).fetchall()
            for row in runs:
                self._delete_run(connection, UUID(str(row[0])))
        return len(runs)

    def _snapshot_query(
        self,
        where: list[str],
        params: list[object],
        order_by: str,
        *,
        table: str = "spatial_snapshots",
    ) -> tuple[SpatialSnapshot, ...]:
        if table == "spatial_snapshot_query_rows":
            key_filter, *remaining_filters = where
            sql = (
                f'WITH selected AS MATERIALIZED (SELECT * FROM "{table}" '
                f"WHERE {key_filter}) SELECT payload FROM selected"
            )
            if remaining_filters:
                sql += " WHERE " + " AND ".join(remaining_filters)
            sql += f" ORDER BY {order_by}"
        else:
            sql = (
                f'SELECT payload FROM "{table}" WHERE '
                + " AND ".join(where)
                + f" ORDER BY {order_by}"
            )
        with read_connection(self._database_path, "spatial") as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(SpatialSnapshot.model_validate(_json(row[0])) for row in rows)

    def _insert(
        self,
        connection: duckdb.DuckDBPyConnection,
        state: SpatialMatchState,
        counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO spatial_runs (
                spatial_run_id, spatial_fingerprint, match_id, dataset_fingerprint,
                temporal_run_id, temporal_fingerprint, source_demo_sha256,
                parser_name, parser_version, spatial_schema_version, spatial_rule_version,
                spatial_config_hash, config, map_model, capabilities, summary, row_counts, warnings,
                canonical_map_name, selected_map_revision, map_definition_version,
                overview_checksum, transform_rule_version, map_definition_fingerprint,
                map_semantics, projectile_metadata, projectile_capabilities
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            [
                state.spatial_run_id,
                state.spatial_fingerprint,
                state.match_id,
                state.dataset_fingerprint,
                state.temporal_run_id,
                state.temporal_fingerprint,
                state.source_demo_sha256,
                state.parser_name,
                state.parser_version,
                state.spatial_schema_version,
                state.spatial_rule_version,
                state.spatial_config_hash,
                _payload(state.config),
                _payload(state.map_model),
                _payload(state.capabilities),
                _payload(state.summary),
                canonical_json(counts),
                canonical_json(state.warnings),
                state.map_semantics.canonical_name if state.map_semantics is not None else None,
                (
                    state.map_semantics.selected_map_revision
                    if state.map_semantics is not None
                    else None
                ),
                (
                    state.map_semantics.map_definition_version
                    if state.map_semantics is not None
                    else None
                ),
                (
                    state.map_semantics.overview_checksum
                    if state.map_semantics is not None
                    else None
                ),
                (
                    state.map_semantics.transform_rule_version
                    if state.map_semantics is not None
                    else None
                ),
                (
                    state.map_semantics.map_definition_fingerprint
                    if state.map_semantics is not None
                    else None
                ),
                _payload(state.map_semantics) if state.map_semantics is not None else None,
                _payload(state.projectile_metadata),
                _payload(state.projectile_capabilities),
            ],
        )
        if state.snapshots:
            connection.executemany(
                """
                INSERT INTO spatial_snapshots (
                    spatial_run_id, snapshot_id, match_id, temporal_run_id, round_id,
                    round_number, tick, participant_id, x, y, z, yaw, pitch, alive,
                    has_bomb, physical_team_id, side, map_name, position_authority,
                    availability, payload, tick_lookup_key, player_path_key
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    [
                        state.spatial_run_id,
                        snapshot.snapshot_id,
                        snapshot.match_id,
                        snapshot.temporal_run_id,
                        snapshot.round_id,
                        snapshot.round_number,
                        snapshot.tick,
                        snapshot.participant_id,
                        snapshot.x,
                        snapshot.y,
                        snapshot.z,
                        snapshot.yaw,
                        snapshot.pitch,
                        snapshot.alive,
                        snapshot.has_bomb,
                        snapshot.physical_team_id,
                        snapshot.side.value,
                        snapshot.map_name,
                        snapshot.position_authority.value,
                        _payload(snapshot.availability),
                        _payload(snapshot),
                        _tick_lookup_key(
                            state.spatial_run_id, snapshot.round_number, snapshot.tick
                        ),
                        _player_path_key(
                            state.spatial_run_id,
                            snapshot.round_number,
                            snapshot.participant_id,
                        ),
                    ]
                    for snapshot in state.snapshots
                ],
            )
            connection.executemany(
                """
                INSERT INTO spatial_snapshot_query_rows (
                    spatial_run_id, snapshot_id, round_number, tick, participant_id,
                    physical_team_id, alive, has_bomb, x, position_authority,
                    tick_lookup_key, player_path_key, payload, match_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.spatial_run_id,
                        snapshot.snapshot_id,
                        snapshot.round_number,
                        snapshot.tick,
                        snapshot.participant_id,
                        snapshot.physical_team_id,
                        snapshot.alive,
                        snapshot.has_bomb,
                        snapshot.x,
                        snapshot.position_authority.value,
                        _tick_lookup_key(
                            state.spatial_run_id, snapshot.round_number, snapshot.tick
                        ),
                        _player_path_key(
                            state.spatial_run_id,
                            snapshot.round_number,
                            snapshot.participant_id,
                        ),
                        _payload(snapshot),
                        snapshot.match_id,
                    ]
                    for snapshot in state.snapshots
                ],
            )
        if state.bomb_positions:
            connection.executemany(
                """
                INSERT INTO bomb_position_snapshots (
                    spatial_run_id, snapshot_id, match_id, temporal_run_id, round_id,
                    round_number, tick, x, y, z, carrier_participant_id,
                    position_authority, source, payload, tick_lookup_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.spatial_run_id,
                        bomb.snapshot_id,
                        bomb.match_id,
                        bomb.temporal_run_id,
                        bomb.round_id,
                        bomb.round_number,
                        bomb.tick,
                        bomb.x,
                        bomb.y,
                        bomb.z,
                        bomb.carrier_participant_id,
                        bomb.position_authority.value,
                        bomb.source,
                        _payload(bomb),
                        _tick_lookup_key(state.spatial_run_id, bomb.round_number, bomb.tick),
                    ]
                    for bomb in state.bomb_positions
                ],
            )
            connection.executemany(
                """
                INSERT INTO bomb_position_query_rows (
                    spatial_run_id, snapshot_id, round_number, tick,
                    tick_lookup_key, payload, match_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.spatial_run_id,
                        bomb.snapshot_id,
                        bomb.round_number,
                        bomb.tick,
                        _tick_lookup_key(state.spatial_run_id, bomb.round_number, bomb.tick),
                        _payload(bomb),
                        bomb.match_id,
                    ]
                    for bomb in state.bomb_positions
                ],
            )
        if state.projectiles:
            connection.executemany(
                """
                INSERT INTO spatial_projectiles (
                    spatial_run_id, projectile_id, match_id, temporal_run_id, round_id,
                    round_number, first_position_tick, terminal_tick, projectile_type,
                    owner_participant_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.spatial_run_id,
                        projectile.projectile_id,
                        projectile.match_id,
                        projectile.temporal_run_id,
                        projectile.round_id,
                        projectile.round_number,
                        projectile.first_position_tick,
                        projectile.terminal_tick,
                        projectile.projectile_type.value,
                        projectile.owner_participant_id,
                        _payload(projectile),
                    ]
                    for projectile in state.projectiles
                ],
            )
        if state.projectile_snapshots:
            connection.executemany(
                """
                INSERT INTO spatial_projectile_snapshots (
                    spatial_run_id, snapshot_id, projectile_id, match_id,
                    temporal_run_id, round_id, round_number, tick, lifecycle, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.spatial_run_id,
                        snapshot.snapshot_id,
                        snapshot.projectile_id,
                        snapshot.match_id,
                        snapshot.temporal_run_id,
                        snapshot.round_id,
                        snapshot.round_number,
                        snapshot.tick,
                        snapshot.lifecycle.value,
                        _payload(snapshot),
                    ]
                    for snapshot in state.projectile_snapshots
                ],
            )
        if state.utility_effects:
            connection.executemany(
                """
                INSERT INTO spatial_utility_effects (
                    spatial_run_id, effect_id, projectile_id, match_id,
                    temporal_run_id, round_id, round_number, start_tick, end_tick,
                    effect_type, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    [
                        state.spatial_run_id,
                        effect.effect_id,
                        effect.projectile_id,
                        effect.match_id,
                        effect.temporal_run_id,
                        effect.round_id,
                        effect.round_number,
                        effect.start_tick,
                        effect.end_tick,
                        effect.effect_type.value,
                        _payload(effect),
                    ]
                    for effect in state.utility_effects
                ],
            )
        if state.validation_issues:
            connection.executemany(
                "INSERT INTO spatial_validation_issues VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        state.spatial_run_id,
                        index,
                        state.match_id,
                        issue.code,
                        issue.severity.value,
                        issue.is_fatal,
                        issue.entity_type,
                        issue.entity_id,
                        _payload(issue),
                    ]
                    for index, issue in enumerate(state.validation_issues)
                ],
            )

    def _latest_run(self, match_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with read_connection(self._database_path, "spatial") as connection:
            cursor = connection.execute(
                """
                SELECT * FROM spatial_runs WHERE match_id = ?
                ORDER BY
                    CASE WHEN spatial_schema_version = ? AND spatial_rule_version = ?
                         THEN 0 ELSE 1 END,
                    created_at DESC, spatial_fingerprint DESC LIMIT 1
                """,
                [match_id, SPATIAL_SCHEMA_VERSION, SPATIAL_RULE_VERSION],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    def _latest_run_id(self, match_id: UUID) -> UUID | None:
        row = self._latest_run(match_id)
        return UUID(str(row["spatial_run_id"])) if row else None

    def _counts(self, run_id: UUID) -> dict[str, int]:
        with read_connection(self._database_path, "spatial") as connection:
            return self._counts_in_connection(connection, run_id)

    @staticmethod
    def _counts_in_connection(
        connection: duckdb.DuckDBPyConnection, run_id: UUID
    ) -> dict[str, int]:
        run = connection.execute(
            "SELECT count(*) FROM spatial_runs WHERE spatial_run_id = ?", [run_id]
        ).fetchone()
        result = {"spatial_runs": int(run[0]) if run else 0}
        for table in _CHILD_TABLES:
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE spatial_run_id = ?', [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result

    @staticmethod
    def _delete_run(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> None:
        delete_dependent_feature_runs(connection, "spatial_run_id", [run_id])
        zone_runs = connection.execute(
            "SELECT zone_assignment_run_id FROM zone_assignment_runs WHERE spatial_run_id = ?",
            [run_id],
        ).fetchall()
        for zone_run in zone_runs:
            connection.execute(
                "DELETE FROM zone_assignments WHERE zone_assignment_run_id = ?",
                [zone_run[0]],
            )
        connection.execute("DELETE FROM zone_assignment_runs WHERE spatial_run_id = ?", [run_id])
        for table in _QUERY_TABLES:
            connection.execute(f'DELETE FROM "{table}" WHERE spatial_run_id = ?', [run_id])
        for table in _CHILD_TABLES:
            connection.execute(f'DELETE FROM "{table}" WHERE spatial_run_id = ?', [run_id])
        connection.execute("DELETE FROM spatial_runs WHERE spatial_run_id = ?", [run_id])


def _summary(row: dict[str, Any]) -> SpatialRunSummary:
    return SpatialRunSummary(
        spatial_run_id=row["spatial_run_id"],
        spatial_fingerprint=row["spatial_fingerprint"],
        spatial_schema_version=row["spatial_schema_version"],
        spatial_rule_version=row["spatial_rule_version"],
        spatial_config_hash=row["spatial_config_hash"],
        match_id=row["match_id"],
        dataset_fingerprint=row["dataset_fingerprint"],
        temporal_run_id=row["temporal_run_id"],
        temporal_fingerprint=row["temporal_fingerprint"],
        source_demo_sha256=row["source_demo_sha256"],
        parser_name=row["parser_name"],
        parser_version=row["parser_version"],
        config=_json(row["config"]),
        map_model=_json(row["map_model"]),
        map_semantics=(
            _json(row["map_semantics"]) if row.get("map_semantics") is not None else None
        ),
        legacy_map_semantics=row.get("map_semantics") is None,
        capabilities=_json(row["capabilities"]),
        projectile_metadata=(
            _json(row["projectile_metadata"])
            if row.get("projectile_metadata") is not None
            else None
        ),
        projectile_capabilities=(
            _json(row["projectile_capabilities"])
            if row.get("projectile_capabilities") is not None
            else unavailable_projectile_capabilities(legacy=True)
        ),
        summary=_json(row["summary"]),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _row_counts(state: SpatialMatchState) -> dict[str, int]:
    return {
        "spatial_runs": 1,
        "spatial_snapshots": len(state.snapshots),
        "bomb_position_snapshots": len(state.bomb_positions),
        "spatial_projectiles": len(state.projectiles),
        "spatial_projectile_snapshots": len(state.projectile_snapshots),
        "spatial_utility_effects": len(state.utility_effects),
        "spatial_validation_issues": len(state.validation_issues),
    }


def _payload(value: Any) -> str:
    return canonical_json(value.model_dump(mode="json"))


def _json(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _tick_lookup_key(run_id: UUID, round_number: int, tick: int) -> str:
    return f"{run_id}:{round_number}:{tick}"


def _player_path_key(run_id: UUID, round_number: int, participant_id: UUID) -> str:
    return f"{run_id}:{round_number}:{participant_id}"
