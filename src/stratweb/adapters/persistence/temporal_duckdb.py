"""DuckDB adapter for atomic, queryable temporal state runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

import duckdb
from pydantic import BaseModel

from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import PersistenceError, TemporalIntegrityError
from stratweb.temporal.models import (
    TEMPORAL_RULE_VERSION,
    TEMPORAL_SCHEMA_VERSION,
    BombTransition,
    ParticipantRoundState,
    RoundTimeline,
    SimultaneousEventGroup,
    TemporalComputeStatus,
    TemporalEvent,
    TemporalMatchState,
    TemporalRunRecord,
    TemporalRunSummary,
    TemporalSaveResult,
    TemporalTransition,
)

_T = TypeVar("_T", bound=BaseModel)
_COUNT_TABLES: tuple[str, ...] = (
    "round_timelines",
    "phase_intervals",
    "temporal_events",
    "temporal_simultaneous_groups",
    "temporal_transitions",
    "participant_round_states",
    "life_transitions",
    "bomb_transitions",
    "temporal_validation_issues",
)
_CHILD_TABLES: tuple[str, ...] = tuple(reversed(_COUNT_TABLES))


class DuckDBTemporalRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    @property
    def database_path(self) -> Path:
        return self._database_path

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def save_temporal(
        self, state: TemporalMatchState, *, replace: bool = False
    ) -> TemporalSaveResult:
        self.initialize()
        fingerprint = state.temporal_fingerprint
        expected = _row_counts(state)
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    match = connection.execute(
                        "SELECT dataset_fingerprint FROM matches WHERE match_id = ?",
                        [state.match_id],
                    ).fetchone()
                    if match is None or str(match[0]) != state.dataset_fingerprint:
                        raise TemporalIntegrityError(
                            "Temporal input does not match the persisted canonical dataset."
                        )
                    exact = connection.execute(
                        "SELECT 1 FROM temporal_runs WHERE temporal_fingerprint = ?",
                        [fingerprint],
                    ).fetchone()
                    collision_rows = connection.execute(
                        """
                        SELECT temporal_fingerprint FROM temporal_runs
                        WHERE dataset_fingerprint = ? AND temporal_rule_version = ?
                          AND temporal_config_hash = ?
                        """,
                        [
                            state.dataset_fingerprint,
                            state.temporal_rule_version,
                            state.temporal_config_hash,
                        ],
                    ).fetchall()
                    collisions = {str(row[0]) for row in collision_rows}
                    if exact is not None and not replace:
                        counts = self._counts(connection, fingerprint)
                        connection.execute("ROLLBACK")
                        return TemporalSaveResult(
                            temporal_fingerprint=fingerprint,
                            temporal_run_id=state.temporal_run_id,
                            status=TemporalComputeStatus.ALREADY_EXISTS,
                            row_counts=counts,
                        )
                    if collisions and fingerprint not in collisions and not replace:
                        raise TemporalIntegrityError(
                            "The same dataset/rule/config produced another temporal fingerprint."
                        )
                    replacing = exact is not None or bool(collisions)
                    for existing in sorted(collisions | ({fingerprint} if exact else set())):
                        self._delete_fingerprint(connection, existing)
                    self._insert(connection, state, expected)
                    actual = self._counts(connection, fingerprint)
                    if actual != expected:
                        raise TemporalIntegrityError(
                            f"Temporal row counts differ after insert: {actual!r} != {expected!r}."
                        )
                    connection.execute("COMMIT")
                    return TemporalSaveResult(
                        temporal_fingerprint=fingerprint,
                        temporal_run_id=state.temporal_run_id,
                        status=(
                            TemporalComputeStatus.REPLACED
                            if replacing
                            else TemporalComputeStatus.COMPUTED
                        ),
                        row_counts=expected,
                    )
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except TemporalIntegrityError:
            raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist temporal state run.") from exc

    def get_summary(self, match_id: UUID) -> TemporalRunSummary | None:
        row = self._latest_run(match_id)
        return self._summary_from_row(row)

    def list_runs(self, match_id: UUID) -> tuple[TemporalRunRecord, ...]:
        self.initialize()
        default = self._latest_run(match_id)
        default_id = UUID(str(default["temporal_run_id"])) if default is not None else None
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            cursor = connection.execute(
                """
                SELECT temporal_run_id, temporal_fingerprint, match_id,
                       dataset_fingerprint, temporal_schema_version,
                       temporal_rule_version, created_at
                FROM temporal_runs WHERE match_id = ?
                ORDER BY created_at DESC, temporal_fingerprint DESC
                """,
                [match_id],
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            schema_version = str(row[4])
            rule_version = str(row[5])
            current = (
                schema_version == TEMPORAL_SCHEMA_VERSION and rule_version == TEMPORAL_RULE_VERSION
            )
            legacy = schema_version == "1.0.0" and rule_version == "1.0.0"
            result.append(
                TemporalRunRecord(
                    temporal_run_id=row[0],
                    temporal_fingerprint=str(row[1]),
                    match_id=row[2],
                    dataset_fingerprint=str(row[3]),
                    temporal_schema_version=schema_version,
                    temporal_rule_version=rule_version,
                    created_at=row[6],
                    compatible=current or legacy,
                    legacy=legacy,
                    selected_by_default=row[0] == default_id,
                )
            )
        return tuple(result)

    def get_summary_for_run(
        self, match_id: UUID, temporal_run_id: UUID
    ) -> TemporalRunSummary | None:
        row = self._run(match_id, temporal_run_id)
        if row is None or not _is_compatible_run(row):
            return None
        return self._summary_from_row(row)

    @staticmethod
    def _summary_from_row(row: dict[str, Any] | None) -> TemporalRunSummary | None:
        if row is None:
            return None
        return TemporalRunSummary(
            temporal_schema_version=row["temporal_schema_version"],
            temporal_rule_version=row["temporal_rule_version"],
            temporal_config_hash=row["temporal_config_hash"],
            temporal_fingerprint=row["temporal_fingerprint"],
            temporal_run_id=row["temporal_run_id"],
            match_id=row["match_id"],
            dataset_fingerprint=row["dataset_fingerprint"],
            config=_json_value(row["config"]),
            summary=_json_value(row["summary"]),
            row_counts=_json_value(row["row_counts"]),
            warnings=tuple(_json_value(row["warnings"])),
        )

    def get_round_timeline(self, match_id: UUID, round_number: int) -> RoundTimeline | None:
        run = self._latest_run(match_id)
        if run is None:
            return None
        return self.get_round_timeline_for_run(
            match_id, UUID(str(run["temporal_run_id"])), round_number
        )

    def get_round_timeline_for_run(
        self, match_id: UUID, temporal_run_id: UUID, round_number: int
    ) -> RoundTimeline | None:
        run = self._run(match_id, temporal_run_id)
        if run is None or not _is_compatible_run(run):
            return None
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            row = connection.execute(
                """
                SELECT payload FROM round_timelines
                WHERE temporal_run_id = ? AND match_id = ? AND round_number = ?
                """,
                [temporal_run_id, match_id, round_number],
            ).fetchone()
        return RoundTimeline.model_validate(_json_value(row[0])) if row else None

    def list_round_events(self, match_id: UUID, round_number: int) -> tuple[TemporalEvent, ...]:
        return self._payload_models(
            match_id,
            round_number,
            "temporal_events",
            TemporalEvent,
            "tick, priority, event_id",
        )

    def list_round_transitions(
        self, match_id: UUID, round_number: int
    ) -> tuple[TemporalTransition, ...]:
        return self._payload_models(
            match_id,
            round_number,
            "temporal_transitions",
            TemporalTransition,
            "tick, transition_type, transition_id",
        )

    def list_simultaneous_groups(
        self, match_id: UUID, round_number: int | None = None
    ) -> tuple[SimultaneousEventGroup, ...]:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return ()
        where = " AND child.round_number = ?" if round_number is not None else ""
        parameters: list[object] = [fingerprint]
        if round_number is not None:
            parameters.append(round_number)
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            rows = connection.execute(
                f"""
                SELECT child.payload FROM temporal_simultaneous_groups child
                JOIN temporal_runs tr USING (temporal_run_id)
                WHERE tr.temporal_fingerprint = ?{where}
                ORDER BY child.round_number, child.tick, child.group_id
                """,
                parameters,
            ).fetchall()
        return tuple(SimultaneousEventGroup.model_validate(_json_value(row[0])) for row in rows)

    def get_simultaneous_group(
        self, match_id: UUID, group_id: UUID
    ) -> SimultaneousEventGroup | None:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return None
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            row = connection.execute(
                """
                SELECT child.payload FROM temporal_simultaneous_groups child
                JOIN temporal_runs tr USING (temporal_run_id)
                WHERE tr.temporal_fingerprint = ? AND child.group_id = ?
                """,
                [fingerprint, group_id],
            ).fetchone()
        return SimultaneousEventGroup.model_validate(_json_value(row[0])) if row else None

    def list_round_participants(
        self, match_id: UUID, round_number: int
    ) -> tuple[ParticipantRoundState, ...]:
        return self._payload_models(
            match_id,
            round_number,
            "participant_round_states",
            ParticipantRoundState,
            "player_id",
        )

    def list_bomb_transitions(
        self, match_id: UUID, round_number: int
    ) -> tuple[BombTransition, ...]:
        return self._payload_models(
            match_id,
            round_number,
            "bomb_transitions",
            BombTransition,
            "tick, transition_id",
        )

    def find_event(self, match_id: UUID, event_id: UUID) -> tuple[int, TemporalEvent] | None:
        run = self._latest_run(match_id)
        if run is None:
            return None
        return self.find_event_for_run(match_id, UUID(str(run["temporal_run_id"])), event_id)

    def find_event_for_run(
        self, match_id: UUID, temporal_run_id: UUID, event_id: UUID
    ) -> tuple[int, TemporalEvent] | None:
        run = self._run(match_id, temporal_run_id)
        if run is None or not _is_compatible_run(run):
            return None
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            row = connection.execute(
                """
                SELECT round_number, payload FROM temporal_events
                WHERE temporal_run_id = ? AND match_id = ? AND event_id = ?
                """,
                [temporal_run_id, match_id, event_id],
            ).fetchone()
        if row is None:
            return None
        return int(row[0]), TemporalEvent.model_validate(_json_value(row[1]))

    def delete_temporal(self, match_id: UUID) -> bool:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                connection.execute("BEGIN TRANSACTION")
                try:
                    exists = connection.execute(
                        "SELECT 1 FROM temporal_runs WHERE match_id = ? LIMIT 1",
                        [match_id],
                    ).fetchone()
                    if exists is None:
                        connection.execute("ROLLBACK")
                        return False
                    for table in _CHILD_TABLES:
                        connection.execute(f'DELETE FROM "{table}" WHERE match_id = ?', [match_id])
                    connection.execute("DELETE FROM temporal_runs WHERE match_id = ?", [match_id])
                    connection.execute("COMMIT")
                    return True
                except Exception:
                    connection.execute("ROLLBACK")
                    raise
        except duckdb.Error as exc:
            raise PersistenceError("Could not delete temporal state runs.") from exc

    def _insert(
        self,
        connection: duckdb.DuckDBPyConnection,
        state: TemporalMatchState,
        counts: dict[str, int],
    ) -> None:
        connection.execute(
            """
            INSERT INTO temporal_runs (
                temporal_run_id, temporal_fingerprint, match_id, dataset_fingerprint,
                temporal_schema_version, temporal_rule_version, temporal_config_hash,
                config, summary, row_counts, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                state.temporal_run_id,
                state.temporal_fingerprint,
                state.match_id,
                state.dataset_fingerprint,
                state.temporal_schema_version,
                state.temporal_rule_version,
                state.temporal_config_hash,
                canonical_json(state.config.model_dump(mode="json")),
                canonical_json(state.summary.model_dump(mode="json")),
                canonical_json(counts),
                canonical_json(list(state.warnings)),
            ],
        )
        rows: dict[str, list[dict[str, object]]] = {table: [] for table in _COUNT_TABLES}
        for timeline in state.timelines:
            common = {
                "temporal_run_id": state.temporal_run_id,
                "match_id": timeline.match_id,
                "round_id": timeline.round_id,
                "round_number": timeline.round_number,
            }
            rows["round_timelines"].append(
                {
                    **common,
                    "start_tick": timeline.start_tick,
                    "freeze_end_tick": timeline.freeze_end_tick,
                    "live_start_tick": timeline.live_start_tick,
                    "end_tick": timeline.end_tick,
                    "official_end_tick": timeline.official_end_tick,
                    "effective_end_tick": timeline.effective_end_tick,
                    "end_source": timeline.end_source,
                    "complete": timeline.complete,
                    "overtime": timeline.overtime,
                    "final_bomb_state": timeline.final_bomb_state.value,
                    "availability": canonical_json(timeline.availability.model_dump(mode="json")),
                    "ambiguity_flags": canonical_json(list(timeline.ambiguity_flags)),
                    "payload": _payload(timeline),
                }
            )
            for phase_item in timeline.phase_intervals:
                rows["phase_intervals"].append(
                    {
                        **common,
                        "interval_id": phase_item.interval_id,
                        "phase": phase_item.phase.value,
                        "start_tick": phase_item.start_tick,
                        "end_tick": phase_item.end_tick,
                        "status": phase_item.status.value,
                        "payload": _payload(phase_item),
                    }
                )
            for event_item in timeline.ordered_events:
                rows["temporal_events"].append(
                    {
                        **common,
                        "event_id": event_item.event_id,
                        "tick": event_item.time.tick,
                        "seconds": event_item.time.seconds,
                        "conversion_status": event_item.time.conversion_status.value,
                        "kind": event_item.kind.value,
                        "event_type": event_item.event_type,
                        "priority": event_item.priority,
                        "ordering_status": event_item.ordering_status.value,
                        "simultaneous_group_id": event_item.simultaneous_group_id,
                        "death_effect_status": (
                            event_item.death_effect_status.value
                            if event_item.death_effect_status is not None
                            else None
                        ),
                        "payload": _payload(event_item),
                    }
                )
            for group_item in timeline.simultaneous_groups:
                rows["temporal_simultaneous_groups"].append(
                    {
                        **common,
                        "group_id": group_item.group_id,
                        "tick": group_item.tick,
                        "event_count": group_item.event_count,
                        "ordering_status": group_item.ordering_status.value,
                        "intermediate_state_status": group_item.intermediate_state_status.value,
                        "final_state_status": group_item.final_state_status.value,
                        "post_group_snapshot_deterministic": (
                            group_item.post_group_snapshot_deterministic
                        ),
                        "ambiguity_reasons": canonical_json(list(group_item.ambiguity_reasons)),
                        "payload": _payload(group_item),
                    }
                )
            for transition_item in timeline.state_transitions:
                rows["temporal_transitions"].append(
                    {
                        **common,
                        "transition_id": transition_item.transition_id,
                        "tick": transition_item.time.tick,
                        "transition_type": transition_item.transition_type.value,
                        "event_id": transition_item.event_id,
                        "status": transition_item.status.value,
                        "payload": _payload(transition_item),
                    }
                )
            for participant_item in timeline.participants:
                rows["participant_round_states"].append(
                    {
                        **common,
                        "player_id": participant_item.player_id,
                        "physical_team_id": participant_item.physical_team_id,
                        "side": participant_item.side.value,
                        "participation_status": participant_item.participation_status.value,
                        "initial_alive_status": participant_item.initial_alive_status.value,
                        "payload": _payload(participant_item),
                    }
                )
            for life_item in timeline.life_transitions:
                rows["life_transitions"].append(
                    {
                        **common,
                        "transition_id": life_item.transition_id,
                        "event_id": life_item.event_id,
                        "tick": life_item.time.tick,
                        "player_id": life_item.player_id,
                        "before_status": life_item.before.value,
                        "after_status": life_item.after.value,
                        "death_classification": life_item.death_classification.value,
                        "status": life_item.status.value,
                        "payload": _payload(life_item),
                    }
                )
            for bomb_item in timeline.bomb_transitions:
                rows["bomb_transitions"].append(
                    {
                        **common,
                        "transition_id": bomb_item.transition_id,
                        "event_id": bomb_item.event_id,
                        "tick": bomb_item.time.tick,
                        "before_state": bomb_item.before.value,
                        "after_state": bomb_item.after.value,
                        "status": bomb_item.status.value,
                        "payload": _payload(bomb_item),
                    }
                )
        round_ids = {str(timeline.round_id): timeline.round_id for timeline in state.timelines}
        for index, issue in enumerate(state.validation_issues):
            round_id = round_ids.get(issue.entity_id) if issue.entity_id else None
            rows["temporal_validation_issues"].append(
                {
                    "temporal_run_id": state.temporal_run_id,
                    "issue_index": index,
                    "match_id": state.match_id,
                    "round_id": round_id,
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "is_fatal": issue.is_fatal,
                    "entity_type": issue.entity_type,
                    "entity_id": issue.entity_id,
                    "payload": _payload(issue),
                }
            )
        for table, table_rows in rows.items():
            self._batch_rows(connection, table, table_rows)

    @staticmethod
    def _batch_rows(
        connection: duckdb.DuckDBPyConnection,
        table: str,
        rows: list[dict[str, object]],
    ) -> None:
        if not rows:
            return
        columns = tuple(rows[0])
        if any(tuple(row) != columns for row in rows):
            raise TemporalIntegrityError(f"Temporal batch for {table!r} has inconsistent columns.")
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        values = [[row[column] for column in columns] for row in rows]
        connection.executemany(
            f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})', values
        )

    def _payload_models(
        self,
        match_id: UUID,
        round_number: int,
        table: str,
        model: type[_T],
        order_by: str,
    ) -> tuple[_T, ...]:
        fingerprint = self._latest_fingerprint(match_id)
        if fingerprint is None:
            return ()
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            rows = connection.execute(
                f"""
                SELECT child.payload FROM "{table}" child
                JOIN temporal_runs tr USING (temporal_run_id)
                WHERE tr.temporal_fingerprint = ? AND child.round_number = ?
                ORDER BY {order_by}
                """,
                [fingerprint, round_number],
            ).fetchall()
        return tuple(model.model_validate(_json_value(row[0])) for row in rows)

    def _latest_run(self, match_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            cursor = connection.execute(
                """
                SELECT * FROM temporal_runs
                WHERE match_id = ? AND (
                    (temporal_schema_version = ? AND temporal_rule_version = ?)
                    OR (temporal_schema_version = '1.0.0' AND temporal_rule_version = '1.0.0')
                )
                ORDER BY
                    CASE WHEN temporal_schema_version = ? AND temporal_rule_version = ?
                         THEN 0 ELSE 1 END,
                    created_at DESC, temporal_fingerprint DESC
                LIMIT 1
                """,
                [
                    match_id,
                    TEMPORAL_SCHEMA_VERSION,
                    TEMPORAL_RULE_VERSION,
                    TEMPORAL_SCHEMA_VERSION,
                    TEMPORAL_RULE_VERSION,
                ],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    def _run(self, match_id: UUID, temporal_run_id: UUID) -> dict[str, Any] | None:
        self.initialize()
        with duckdb.connect(str(self._database_path), read_only=False) as connection:
            cursor = connection.execute(
                "SELECT * FROM temporal_runs WHERE match_id = ? AND temporal_run_id = ?",
                [match_id, temporal_run_id],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row, strict=True))

    def _latest_fingerprint(self, match_id: UUID) -> str | None:
        row = self._latest_run(match_id)
        return str(row["temporal_fingerprint"]) if row else None

    @staticmethod
    def _counts(connection: duckdb.DuckDBPyConnection, fingerprint: str) -> dict[str, int]:
        run = connection.execute(
            "SELECT temporal_run_id FROM temporal_runs WHERE temporal_fingerprint = ?",
            [fingerprint],
        ).fetchone()
        if run is None:
            return {"temporal_runs": 0, **{table: 0 for table in _COUNT_TABLES}}
        run_id = run[0]
        result = {"temporal_runs": 1}
        for table in _COUNT_TABLES:
            row = connection.execute(
                f'SELECT count(1) FROM "{table}" WHERE temporal_run_id = ?', [run_id]
            ).fetchone()
            result[table] = int(row[0]) if row else 0
        return result

    @staticmethod
    def _delete_fingerprint(connection: duckdb.DuckDBPyConnection, fingerprint: str) -> None:
        row = connection.execute(
            "SELECT temporal_run_id FROM temporal_runs WHERE temporal_fingerprint = ?",
            [fingerprint],
        ).fetchone()
        if row is None:
            return
        run_id = row[0]
        for table in _CHILD_TABLES:
            connection.execute(f'DELETE FROM "{table}" WHERE temporal_run_id = ?', [run_id])
        connection.execute("DELETE FROM temporal_runs WHERE temporal_run_id = ?", [run_id])


def _row_counts(state: TemporalMatchState) -> dict[str, int]:
    return {
        "temporal_runs": 1,
        "round_timelines": len(state.timelines),
        "phase_intervals": sum(len(item.phase_intervals) for item in state.timelines),
        "temporal_events": sum(len(item.ordered_events) for item in state.timelines),
        "temporal_simultaneous_groups": sum(
            len(item.simultaneous_groups) for item in state.timelines
        ),
        "temporal_transitions": sum(len(item.state_transitions) for item in state.timelines),
        "participant_round_states": sum(len(item.participants) for item in state.timelines),
        "life_transitions": sum(len(item.life_transitions) for item in state.timelines),
        "bomb_transitions": sum(len(item.bomb_transitions) for item in state.timelines),
        "temporal_validation_issues": len(state.validation_issues),
    }


def _payload(model: BaseModel) -> str:
    return canonical_json(model.model_dump(mode="json"))


def _json_value(value: object) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _is_compatible_run(row: dict[str, Any]) -> bool:
    versions = (str(row["temporal_schema_version"]), str(row["temporal_rule_version"]))
    return versions in {
        (TEMPORAL_SCHEMA_VERSION, TEMPORAL_RULE_VERSION),
        ("1.0.0", "1.0.0"),
    }
