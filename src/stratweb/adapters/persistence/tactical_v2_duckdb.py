"""DuckDB source loading and immutable persistence for Tactical Intelligence V2."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence._tactical_v2_cascade import delete_tactical_v2_runs
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.opponent_models import OpponentMatchSelection
from stratweb.domain.enums import Side
from stratweb.exceptions import PersistenceError
from stratweb.features.models import (
    ROUND_FEATURE_RULE_VERSION,
    ROUND_FEATURE_SCHEMA_VERSION,
    BombsitePayload,
    RoundFeature,
    SaveExitPayload,
)
from stratweb.spatial.projectiles import SpatialProjectile, UtilityEffect
from stratweb.tactical_v2.models import (
    TACTICAL_V2_RULE_VERSION,
    TACTICAL_V2_SCHEMA_VERSION,
    TacticalAvailability,
    TacticalComputeStatus,
    TacticalDamageSample,
    TacticalEvidenceReference,
    TacticalInsight,
    TacticalInsightType,
    TacticalKillSample,
    TacticalMatchInput,
    TacticalPlantSample,
    TacticalPlayerSample,
    TacticalRoundInput,
    TacticalSaveSignal,
    TacticalSourcePin,
    TacticalTradeSample,
    TacticalUtilitySample,
    TacticalV2Config,
    TacticalV2Input,
    TacticalV2Run,
    TacticalV2RunRecord,
    TacticalV2RunSummary,
    TacticalV2SaveResult,
    TacticalV2Summary,
)


class DuckDBTacticalV2SourceRepository:
    """Load one exact, internally consistent feature/spatial lineage per selected match."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def load_input(
        self, profile_id: UUID, selections: tuple[OpponentMatchSelection, ...]
    ) -> TacticalV2Input:
        self.initialize()
        included: list[TacticalMatchInput] = []
        excluded: list[UUID] = []
        warnings: list[str] = []
        with read_connection(self._database_path, "tactical V2 sources") as connection:
            for selection in sorted(selections, key=lambda item: str(item.match_id)):
                try:
                    source = self._source_pin(connection, selection)
                    match = self._load_match(connection, source) if source is not None else None
                except (duckdb.Error, ValueError) as exc:
                    excluded.append(selection.match_id)
                    warnings.append(
                        f"match_excluded_invalid_tactical_sources:{selection.match_id}:"
                        f"{type(exc).__name__}"
                    )
                    continue
                if source is None:
                    excluded.append(selection.match_id)
                    warnings.append(
                        f"match_excluded_missing_compatible_sources:{selection.match_id}"
                    )
                    continue
                if match is None or not match.rounds:
                    excluded.append(selection.match_id)
                    warnings.append(
                        f"match_excluded_selected_team_has_no_rounds:{selection.match_id}"
                    )
                    continue
                included.append(match)
        return TacticalV2Input(
            profile_id=profile_id,
            matches=tuple(included),
            excluded_match_ids=tuple(excluded),
            warnings=tuple(sorted(warnings)),
        )

    @staticmethod
    def _source_pin(
        connection: duckdb.DuckDBPyConnection, selection: OpponentMatchSelection
    ) -> TacticalSourcePin | None:
        cursor = connection.execute(
            """
            SELECT f.match_id, ? AS team_id, m.map_name, f.dataset_fingerprint,
                   f.analytics_fingerprint, f.analytics_rule_version,
                   f.temporal_run_id, f.temporal_fingerprint, f.temporal_rule_version,
                   f.spatial_run_id, f.spatial_fingerprint, f.spatial_rule_version,
                   f.zone_assignment_run_id, f.zone_assignment_fingerprint,
                   f.zone_assignment_rule_version, f.feature_run_id,
                   f.feature_fingerprint, f.feature_rule_version
            FROM round_feature_runs f
            JOIN matches m ON m.match_id = f.match_id
            JOIN analytics_runs a
              ON a.match_id = f.match_id
             AND a.analytics_fingerprint = f.analytics_fingerprint
            JOIN temporal_runs t
              ON t.match_id = f.match_id AND t.temporal_run_id = f.temporal_run_id
             AND t.temporal_fingerprint = f.temporal_fingerprint
            JOIN spatial_runs s
              ON s.match_id = f.match_id AND s.spatial_run_id = f.spatial_run_id
             AND s.spatial_fingerprint = f.spatial_fingerprint
            JOIN zone_assignment_runs z
              ON z.match_id = f.match_id
             AND z.zone_assignment_run_id = f.zone_assignment_run_id
             AND z.zone_assignment_fingerprint = f.zone_assignment_fingerprint
            WHERE f.match_id = ?
              AND f.feature_schema_version = ? AND f.feature_rule_version = ?
            ORDER BY f.created_at DESC, f.feature_fingerprint DESC
            LIMIT 1
            """,
            [
                selection.team_id,
                selection.match_id,
                ROUND_FEATURE_SCHEMA_VERSION,
                ROUND_FEATURE_RULE_VERSION,
            ],
        )
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [item[0] for item in cursor.description]
        return TacticalSourcePin.model_validate(dict(zip(columns, row, strict=True)))

    def _load_match(
        self, connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> TacticalMatchInput:
        round_rows = _rows(
            connection.execute(
                """
                SELECT r.round_id, r.round_number, r.t_team_id, r.ct_team_id,
                       r.winner_side, r.is_warmup, r.is_complete,
                       timeline.live_start_tick, timeline.effective_end_tick
                FROM rounds r
                LEFT JOIN round_timelines timeline
                  ON timeline.temporal_run_id = ? AND timeline.round_id = r.round_id
                WHERE r.match_id = ? ORDER BY r.round_number
                """,
                [source.temporal_run_id, source.match_id],
            )
        )
        participant_rows = _rows(
            connection.execute(
                """
                SELECT round_number, player_id, physical_team_id
                FROM participant_round_states
                WHERE temporal_run_id = ? AND match_id = ?
                ORDER BY round_number, player_id
                """,
                [source.temporal_run_id, source.match_id],
            )
        )
        participants: dict[int, dict[UUID, list[UUID]]] = defaultdict(lambda: defaultdict(list))
        for row in participant_rows:
            if row["physical_team_id"] is not None:
                participants[int(row["round_number"])][UUID(str(row["physical_team_id"]))].append(
                    UUID(str(row["player_id"]))
                )
        samples = self._samples(connection, source)
        kills = self._kills(connection, source)
        damages = self._damages(connection, source)
        trades = self._trades(connection, source)
        utility = self._utility(connection, source)
        plants = self._plants(connection, source)
        saves, save_availability, ambiguous_save_rounds = self._saves(connection, source)
        rounds = []
        limitations: set[str] = set()
        limitations.update(
            f"ambiguous_multiple_save_exit_features:round_{number}"
            for number in ambiguous_save_rounds
        )
        for row in round_rows:
            number = int(row["round_number"])
            t_team = _uuid(row["t_team_id"])
            ct_team = _uuid(row["ct_team_id"])
            if t_team == source.team_id:
                side = Side.T
                opponent_team = ct_team
            elif ct_team == source.team_id:
                side = Side.CT
                opponent_team = t_team
            else:
                continue
            winner = str(row["winner_side"]) if row["winner_side"] is not None else None
            selected_won = winner == side.value if winner in {"T", "CT"} else None
            plant_values = plants.get(number, ())
            if len(plant_values) > 1:
                limitations.add(f"ambiguous_multiple_plant_events:round_{number}")
            rounds.append(
                TacticalRoundInput(
                    match_id=source.match_id,
                    round_id=UUID(str(row["round_id"])),
                    round_number=number,
                    side=side,
                    selected_team_won=selected_won,
                    is_warmup=bool(row["is_warmup"]),
                    is_complete=bool(row["is_complete"]),
                    live_start_tick=_int(row["live_start_tick"]),
                    effective_end_tick=_int(row["effective_end_tick"]),
                    selected_player_ids=tuple(
                        sorted(participants[number].get(source.team_id, ()), key=str)
                    ),
                    opponent_player_ids=tuple(
                        sorted(participants[number].get(opponent_team, ()), key=str)
                        if opponent_team is not None
                        else (),
                    ),
                    samples=tuple(samples.get(number, ())),
                    kills=tuple(kills.get(number, ())),
                    damages=tuple(damages.get(number, ())),
                    trades=tuple(trades.get(number, ())),
                    utility=tuple(utility.get(number, ())),
                    plant=plant_values[0] if len(plant_values) == 1 else None,
                    save_availability=save_availability.get(
                        number, TacticalAvailability.UNAVAILABLE
                    ),
                    save_signal=saves.get(number),
                )
            )
        return TacticalMatchInput(
            source=source,
            rounds=tuple(rounds),
            limitations=tuple(sorted(limitations)),
        )

    @staticmethod
    def _samples(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> dict[int, list[TacticalPlayerSample]]:
        rows = _rows(
            connection.execute(
                """
                SELECT sample.snapshot_id, sample.round_number, sample.tick,
                       sample.participant_id, sample.x, sample.y, sample.z,
                       sample.alive, sample.side, zone.zone_id, zone.zone_name
                FROM spatial_snapshots sample
                LEFT JOIN zone_assignments zone
                  ON zone.zone_assignment_run_id = ?
                 AND zone.spatial_snapshot_id = sample.snapshot_id
                WHERE sample.spatial_run_id = ? AND sample.match_id = ?
                  AND sample.physical_team_id = ?
                  AND sample.x IS NOT NULL AND sample.y IS NOT NULL AND sample.z IS NOT NULL
                ORDER BY sample.round_number, sample.tick, sample.participant_id
                """,
                [
                    source.zone_assignment_run_id,
                    source.spatial_run_id,
                    source.match_id,
                    source.team_id,
                ],
            )
        )
        result: dict[int, list[TacticalPlayerSample]] = defaultdict(list)
        for row in rows:
            result[int(row["round_number"])].append(
                TacticalPlayerSample(
                    snapshot_id=UUID(str(row["snapshot_id"])),
                    player_id=UUID(str(row["participant_id"])),
                    tick=int(row["tick"]),
                    x=float(row["x"]),
                    y=float(row["y"]),
                    z=float(row["z"]),
                    alive=bool(row["alive"]) if row["alive"] is not None else None,
                    side=Side(str(row["side"])),
                    zone_id=str(row["zone_id"]) if row["zone_id"] is not None else None,
                    zone_name=str(row["zone_name"]) if row["zone_name"] is not None else None,
                )
            )
        return result

    @staticmethod
    def _kills(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> dict[int, list[TacticalKillSample]]:
        rows = _rows(
            connection.execute(
                """
                SELECT round_number, event_id, tick, attacker_player_id, victim_player_id,
                       attacker_team_id, victim_team_id, is_teamkill, is_suicide
                FROM kills WHERE match_id = ? AND round_number IS NOT NULL
                ORDER BY round_number, tick, event_id
                """,
                [source.match_id],
            )
        )
        result: dict[int, list[TacticalKillSample]] = defaultdict(list)
        for row in rows:
            round_number = int(row.pop("round_number"))
            result[round_number].append(TacticalKillSample.model_validate(row))
        return result

    @staticmethod
    def _damages(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> dict[int, list[TacticalDamageSample]]:
        rows = _rows(
            connection.execute(
                """
                SELECT round_number, event_id, tick, attacker_player_id, victim_player_id,
                       attacker_team_id, victim_team_id, weapon, damage_health
                FROM damages WHERE match_id = ? AND round_number IS NOT NULL
                ORDER BY round_number, tick, event_id
                """,
                [source.match_id],
            )
        )
        result: dict[int, list[TacticalDamageSample]] = defaultdict(list)
        for row in rows:
            round_number = int(row.pop("round_number"))
            result[round_number].append(TacticalDamageSample.model_validate(row))
        return result

    @staticmethod
    def _trades(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> dict[int, list[TacticalTradeSample]]:
        rows = _rows(
            connection.execute(
                """
                SELECT round_number, traded_kill_event_id, original_kill_event_id,
                       tick_delta, team_id
                FROM trade_events WHERE analytics_fingerprint = ? AND match_id = ?
                ORDER BY round_number, tick_delta, traded_kill_event_id
                """,
                [source.analytics_fingerprint, source.match_id],
            )
        )
        result: dict[int, list[TacticalTradeSample]] = defaultdict(list)
        for row in rows:
            round_number = int(row.pop("round_number"))
            result[round_number].append(TacticalTradeSample.model_validate(row))
        return result

    @staticmethod
    def _utility(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> dict[int, list[TacticalUtilitySample]]:
        projectiles = {
            item.projectile_id: item
            for item in (
                SpatialProjectile.model_validate(_json(row[0]))
                for row in connection.execute(
                    "SELECT payload FROM spatial_projectiles WHERE spatial_run_id = ?",
                    [source.spatial_run_id],
                ).fetchall()
            )
        }
        result: dict[int, list[TacticalUtilitySample]] = defaultdict(list)
        for row in connection.execute(
            "SELECT payload FROM spatial_utility_effects WHERE spatial_run_id = ? "
            "ORDER BY round_number, start_tick, effect_id",
            [source.spatial_run_id],
        ).fetchall():
            effect = UtilityEffect.model_validate(_json(row[0]))
            projectile = projectiles.get(effect.projectile_id) if effect.projectile_id else None
            result[effect.round_number].append(
                TacticalUtilitySample(
                    effect_id=effect.effect_id,
                    projectile_id=effect.projectile_id,
                    owner_player_id=projectile.owner_participant_id if projectile else None,
                    owner_team_id=projectile.owner_physical_team_id if projectile else None,
                    effect_type=effect.effect_type.value,
                    start_tick=effect.start_tick,
                    end_tick=effect.end_tick,
                    center_x=effect.center_x,
                    center_y=effect.center_y,
                    center_z=effect.center_z,
                )
            )
        return result

    @staticmethod
    def _plants(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> dict[int, tuple[TacticalPlantSample, ...]]:
        result: dict[int, list[TacticalPlantSample]] = defaultdict(list)
        sites_by_event: dict[UUID, str] = {}
        if source.feature_run_id is not None:
            for payload_row in connection.execute(
                "SELECT payload FROM round_features WHERE feature_run_id = ? "
                "AND feature_type = 'bombsite' AND availability = 'available'",
                [source.feature_run_id],
            ).fetchall():
                feature = RoundFeature.model_validate(_json(payload_row[0]))
                if isinstance(feature.payload, BombsitePayload) and feature.payload.site:
                    sites_by_event[feature.payload.plant_event_id] = feature.payload.site
        rows = _rows(
            connection.execute(
                """
                SELECT round_number, event_id, tick, site_normalized, player_id, event_type
                FROM bomb_events WHERE match_id = ? AND round_number IS NOT NULL
                ORDER BY round_number, tick, event_id
                """,
                [source.match_id],
            )
        )
        for row in rows:
            event_type = str(row["event_type"]).lower()
            if "plant" not in event_type or "abort" in event_type or "begin" in event_type:
                continue
            event_id = UUID(str(row["event_id"]))
            result[int(row["round_number"])].append(
                TacticalPlantSample(
                    event_id=event_id,
                    tick=int(row["tick"]),
                    site=(
                        str(row["site_normalized"]).upper()
                        if row["site_normalized"] is not None
                        else sites_by_event.get(event_id)
                    ),
                    player_id=_uuid(row["player_id"]),
                )
            )
        return {key: tuple(value) for key, value in result.items()}

    @staticmethod
    def _saves(
        connection: duckdb.DuckDBPyConnection, source: TacticalSourcePin
    ) -> tuple[
        dict[int, TacticalSaveSignal],
        dict[int, TacticalAvailability],
        tuple[int, ...],
    ]:
        if source.feature_run_id is None:
            return {}, {}, ()
        result: dict[int, TacticalSaveSignal] = {}
        availability: dict[int, TacticalAvailability] = {}
        grouped: dict[int, list[RoundFeature]] = defaultdict(list)
        for row in connection.execute(
            """
            SELECT payload FROM round_features
            WHERE feature_run_id = ? AND team_id = ?
              AND feature_type = 'save_exit'
            ORDER BY round_number, feature_id
            """,
            [source.feature_run_id, source.team_id],
        ).fetchall():
            feature = RoundFeature.model_validate(_json(row[0]))
            grouped[feature.round_number].append(feature)
        ambiguous: list[int] = []
        for round_number, features in sorted(grouped.items()):
            if len(features) != 1:
                availability[round_number] = TacticalAvailability.UNAVAILABLE
                ambiguous.append(round_number)
                continue
            feature = features[0]
            status = TacticalAvailability(feature.availability.value)
            availability[round_number] = status
            if status is not TacticalAvailability.AVAILABLE or not isinstance(
                feature.payload, SaveExitPayload
            ):
                continue
            result[round_number] = TacticalSaveSignal(
                feature_id=feature.feature_id,
                saved=feature.payload.saved,
                tick_start=feature.tick_start,
                tick_end=feature.tick_end,
                snapshot_ids=feature.evidence_snapshot_ids,
            )
        return result, availability, tuple(ambiguous)


class DuckDBTacticalV2Repository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save(self, state: TacticalV2Run, *, replace: bool = False) -> TacticalV2SaveResult:
        self.initialize()
        expected = {
            "tactical_v2_runs": 1,
            "tactical_v2_run_inputs": len(state.source_pins),
            "tactical_v2_insights": len(state.insights),
            "tactical_v2_evidence": sum(len(item.evidence_references) for item in state.insights),
        }
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    self._preflight(connection, state)
                    exact = connection.execute(
                        "SELECT tactical_run_id FROM tactical_v2_runs "
                        "WHERE tactical_fingerprint = ?",
                        [state.tactical_fingerprint],
                    ).fetchone()
                    if exact is not None and not replace:
                        run_id = UUID(str(exact[0]))
                        counts = self._counts(connection, run_id)
                        connection.execute("COMMIT")
                        return TacticalV2SaveResult(
                            tactical_run_id=run_id,
                            tactical_fingerprint=state.tactical_fingerprint,
                            status=TacticalComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    replacing = exact is not None
                    if exact is not None:
                        self._delete_run(connection, UUID(str(exact[0])))
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, state.tactical_run_id)
                    if actual != expected:
                        raise PersistenceError(
                            f"Tactical V2 row counts differ: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return TacticalV2SaveResult(
                        tactical_run_id=state.tactical_run_id,
                        tactical_fingerprint=state.tactical_fingerprint,
                        status=(
                            TacticalComputeStatus.REPLACED
                            if replacing
                            else TacticalComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except PersistenceError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist Tactical V2 run.") from exc

    def get_summary(self, profile_id: UUID) -> TacticalV2RunSummary | None:
        row = self._latest(profile_id)
        return _summary(row) if row is not None else None

    def get_summary_for_run(
        self, profile_id: UUID, tactical_run_id: UUID
    ) -> TacticalV2RunSummary | None:
        self.initialize()
        with read_connection(self._database_path, "Tactical V2") as connection:
            cursor = connection.execute(
                "SELECT * FROM tactical_v2_runs WHERE profile_id = ? AND tactical_run_id = ?",
                [profile_id, tactical_run_id],
            )
            rows = _rows(cursor)
            if rows:
                _attach_source_pins(connection, rows[0])
        return _summary(rows[0]) if rows else None

    def list_runs(self, profile_id: UUID) -> tuple[TacticalV2RunRecord, ...]:
        self.initialize()
        selected = self._latest(profile_id)
        selected_id = selected["tactical_run_id"] if selected else None
        with read_connection(self._database_path, "Tactical V2") as connection:
            rows = _rows(
                connection.execute(
                    """
                    SELECT tactical_run_id, tactical_fingerprint, profile_id,
                           tactical_schema_version, tactical_rule_version, created_at
                    FROM tactical_v2_runs WHERE profile_id = ?
                    ORDER BY created_at DESC, tactical_fingerprint DESC
                    """,
                    [profile_id],
                )
            )
        return tuple(
            TacticalV2RunRecord(
                **row,
                compatible=(str(row["tactical_schema_version"]), str(row["tactical_rule_version"]))
                == (TACTICAL_V2_SCHEMA_VERSION, TACTICAL_V2_RULE_VERSION),
                selected_by_default=row["tactical_run_id"] == selected_id,
            )
            for row in rows
        )

    def list_insights(
        self,
        profile_id: UUID,
        *,
        tactical_run_id: UUID | None = None,
        insight_type: TacticalInsightType | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[TacticalInsight, ...]:
        summary = (
            self.get_summary_for_run(profile_id, tactical_run_id)
            if tactical_run_id
            else self.get_summary(profile_id)
        )
        if summary is None:
            return ()
        where = ["tactical_run_id = ?", "profile_id = ?"]
        params: list[object] = [summary.tactical_run_id, profile_id]
        if insight_type is not None:
            where.append("insight_type = ?")
            params.append(insight_type.value)
        if map_name is not None:
            where.append("map_name = ?")
            params.append(map_name)
        if side is not None:
            where.append("side = ?")
            params.append(side.value)
        params.extend([limit, offset])
        with read_connection(self._database_path, "Tactical V2") as connection:
            rows = connection.execute(
                "SELECT payload FROM tactical_v2_insights WHERE "
                + " AND ".join(where)
                + " ORDER BY frequency DESC, denominator DESC, insight_type, insight_key "
                "LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return tuple(TacticalInsight.model_validate(_json(row[0])) for row in rows)

    def list_evidence(
        self, profile_id: UUID, insight_id: UUID, *, tactical_run_id: UUID | None = None
    ) -> tuple[TacticalEvidenceReference, ...]:
        summary = (
            self.get_summary_for_run(profile_id, tactical_run_id)
            if tactical_run_id
            else self.get_summary(profile_id)
        )
        if summary is None:
            return ()
        with read_connection(self._database_path, "Tactical V2") as connection:
            rows = connection.execute(
                "SELECT payload FROM tactical_v2_evidence "
                "WHERE tactical_run_id = ? AND insight_id = ? ORDER BY evidence_index",
                [summary.tactical_run_id, insight_id],
            ).fetchall()
        return tuple(TacticalEvidenceReference.model_validate(_json(row[0])) for row in rows)

    def delete(self, profile_id: UUID) -> int:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    rows = connection.execute(
                        "SELECT tactical_run_id FROM tactical_v2_runs WHERE profile_id = ?",
                        [profile_id],
                    ).fetchall()
                    delete_tactical_v2_runs(connection, [row[0] for row in rows])
                    connection.execute("COMMIT")
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
            return len(rows)
        except duckdb.Error as exc:
            raise PersistenceError("Could not delete Tactical V2 runs.") from exc

    def _latest(self, profile_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with read_connection(self._database_path, "Tactical V2") as connection:
            cursor = connection.execute(
                """
                SELECT * FROM tactical_v2_runs
                WHERE profile_id = ? AND tactical_schema_version = ?
                  AND tactical_rule_version = ?
                  AND (
                    SELECT count(*) FROM tactical_v2_run_inputs input
                    WHERE input.tactical_run_id = tactical_v2_runs.tactical_run_id
                  ) = (
                    SELECT count(*) FROM opponent_match_selections selection
                    WHERE selection.profile_id = ?
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM opponent_match_selections selection
                    WHERE selection.profile_id = ? AND NOT EXISTS (
                      SELECT 1 FROM tactical_v2_run_inputs input
                      WHERE input.tactical_run_id = tactical_v2_runs.tactical_run_id
                        AND input.match_id = selection.match_id
                        AND input.team_id = selection.team_id
                    )
                  )
                ORDER BY created_at DESC, tactical_fingerprint DESC LIMIT 1
                """,
                [
                    profile_id,
                    TACTICAL_V2_SCHEMA_VERSION,
                    TACTICAL_V2_RULE_VERSION,
                    profile_id,
                    profile_id,
                ],
            )
            rows = _rows(cursor)
            if rows:
                _attach_source_pins(connection, rows[0])
        return rows[0] if rows else None

    @staticmethod
    def _preflight(connection: duckdb.DuckDBPyConnection, state: TacticalV2Run) -> None:
        if (
            connection.execute(
                "SELECT 1 FROM opponent_profiles WHERE profile_id = ?", [state.profile_id]
            ).fetchone()
            is None
        ):
            raise PersistenceError("Tactical V2 profile does not exist.")
        for source in state.source_pins:
            checks = (
                (
                    "SELECT 1 FROM analytics_runs WHERE match_id = ? AND analytics_fingerprint = ?",
                    [source.match_id, source.analytics_fingerprint],
                ),
                (
                    "SELECT 1 FROM temporal_runs WHERE match_id = ? AND temporal_run_id = ? "
                    "AND temporal_fingerprint = ?",
                    [source.match_id, source.temporal_run_id, source.temporal_fingerprint],
                ),
                (
                    "SELECT 1 FROM spatial_runs WHERE match_id = ? AND spatial_run_id = ? "
                    "AND spatial_fingerprint = ?",
                    [source.match_id, source.spatial_run_id, source.spatial_fingerprint],
                ),
                (
                    "SELECT 1 FROM zone_assignment_runs WHERE match_id = ? "
                    "AND zone_assignment_run_id = ? AND zone_assignment_fingerprint = ?",
                    [
                        source.match_id,
                        source.zone_assignment_run_id,
                        source.zone_assignment_fingerprint,
                    ],
                ),
            )
            if any(connection.execute(sql, params).fetchone() is None for sql, params in checks):
                raise PersistenceError("Tactical V2 source lineage is incompatible.")
            if source.feature_run_id is not None:
                feature_row = connection.execute(
                    "SELECT 1 FROM round_feature_runs WHERE match_id = ? "
                    "AND feature_run_id = ? AND feature_fingerprint = ?",
                    [source.match_id, source.feature_run_id, source.feature_fingerprint],
                ).fetchone()
                if feature_row is None:
                    raise PersistenceError("Tactical V2 feature lineage is incompatible.")

    @staticmethod
    def _insert(
        connection: duckdb.DuckDBPyConnection,
        state: TacticalV2Run,
        row_counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO tactical_v2_runs (
                tactical_run_id, tactical_fingerprint, tactical_schema_version,
                tactical_rule_version, configuration_hash, profile_id, config,
                capabilities, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                state.tactical_run_id,
                state.tactical_fingerprint,
                state.tactical_schema_version,
                state.tactical_rule_version,
                state.configuration_hash,
                state.profile_id,
                _payload(state.config),
                canonical_json(
                    {
                        key.value: value.model_dump(mode="json")
                        for key, value in state.capabilities.items()
                    }
                ),
                _payload(state.summary),
                canonical_json(row_counts),
                canonical_json(state.warnings),
            ],
        )
        connection.executemany(
            """
            INSERT INTO tactical_v2_run_inputs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    state.tactical_run_id,
                    item.match_id,
                    item.team_id,
                    item.map_name,
                    item.dataset_fingerprint,
                    item.analytics_fingerprint,
                    item.temporal_run_id,
                    item.spatial_run_id,
                    item.zone_assignment_run_id,
                    item.feature_run_id,
                    _payload(item),
                ]
                for item in state.source_pins
            ],
        )
        connection.executemany(
            """
            INSERT INTO tactical_v2_insights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                [
                    state.tactical_run_id,
                    item.insight_id,
                    item.profile_id,
                    item.insight_type.value,
                    item.map_name,
                    item.side.value,
                    item.key,
                    item.availability.value,
                    item.numerator,
                    item.denominator,
                    item.frequency,
                    item.match_count,
                    item.small_sample_warning,
                    _payload(item),
                ]
                for item in state.insights
            ],
        )
        evidence_rows = [
            [
                state.tactical_run_id,
                insight.insight_id,
                index,
                evidence.match_id,
                evidence.round_number,
                evidence.tick_start,
                evidence.tick_end,
                _payload(evidence),
            ]
            for insight in state.insights
            for index, evidence in enumerate(insight.evidence_references)
        ]
        if evidence_rows:
            connection.executemany(
                "INSERT INTO tactical_v2_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                evidence_rows,
            )

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> dict[str, int]:
        result = {}
        for table in (
            "tactical_v2_runs",
            "tactical_v2_run_inputs",
            "tactical_v2_insights",
            "tactical_v2_evidence",
        ):
            row = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE tactical_run_id = ?', [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row is not None else 0
        return result

    @staticmethod
    def _delete_run(connection: duckdb.DuckDBPyConnection, run_id: UUID) -> None:
        delete_tactical_v2_runs(connection, [run_id])


def _summary(row: dict[str, Any]) -> TacticalV2RunSummary:
    capabilities = {
        TacticalInsightType(key): value for key, value in _json(row["capabilities"]).items()
    }
    inputs = row.get("source_pins")
    if inputs is None:
        raise PersistenceError("Tactical V2 summary requires loaded source pins.")
    return TacticalV2RunSummary(
        tactical_schema_version=str(row["tactical_schema_version"]),
        tactical_rule_version=str(row["tactical_rule_version"]),
        tactical_run_id=UUID(str(row["tactical_run_id"])),
        tactical_fingerprint=str(row["tactical_fingerprint"]),
        configuration_hash=str(row["configuration_hash"]),
        profile_id=UUID(str(row["profile_id"])),
        config=TacticalV2Config.model_validate(_json(row["config"])),
        source_pins=tuple(TacticalSourcePin.model_validate(item) for item in inputs),
        capabilities=capabilities,
        summary=TacticalV2Summary.model_validate(_json(row["summary"])),
        row_counts=_json(row["row_counts"]),
        warnings=tuple(_json(row["warnings"])),
    )


def _attach_source_pins(connection: duckdb.DuckDBPyConnection, row: dict[str, Any]) -> None:
    values = connection.execute(
        "SELECT payload FROM tactical_v2_run_inputs WHERE tactical_run_id = ? ORDER BY match_id",
        [row["tactical_run_id"]],
    ).fetchall()
    row["source_pins"] = tuple(_json(item[0]) for item in values)


def _rows(cursor: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _payload(value: Any) -> str:
    return canonical_json(value.model_dump(mode="json"))


def _uuid(value: Any) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _int(value: Any) -> int | None:
    return int(value) if value is not None else None


__all__ = [
    "DuckDBTacticalV2Repository",
    "DuckDBTacticalV2SourceRepository",
]
