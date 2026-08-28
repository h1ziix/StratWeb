"""DuckDB source projection and immutable persistence for critical mistakes."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.analytics.models import ANALYTICS_RULE_VERSION, ANALYTICS_SCHEMA_VERSION
from stratweb.application.normalization_utils import canonical_json
from stratweb.critical_mistakes.models import (
    CRITICAL_MISTAKES_RULE_VERSION,
    CRITICAL_MISTAKES_SCHEMA_VERSION,
    EARLY_DEATH_WINDOW_SECONDS,
    CriticalCandidate,
    CriticalCapabilityStatus,
    CriticalEvidence,
    CriticalMistakesInput,
    CriticalMistakesRun,
    CriticalMistakeType,
    CriticalSaveResult,
    CriticalSaveStatus,
    CriticalSourcePin,
)
from stratweb.domain.enums import Side
from stratweb.economy.models import ECONOMY_RULE_VERSION, ECONOMY_SCHEMA_VERSION
from stratweb.exceptions import PersistenceError
from stratweb.temporal.models import (
    TEMPORAL_RULE_VERSION,
    TEMPORAL_SCHEMA_VERSION,
    SimultaneousEventGroup,
)


class DuckDBCriticalMistakesRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def build_input(self, profile_id: UUID) -> CriticalMistakesInput:
        self.initialize()
        candidates: list[CriticalCandidate] = []
        pins: list[CriticalSourcePin] = []
        eligible: defaultdict[CriticalMistakeType, int] = defaultdict(int)
        warnings: set[str] = set()
        source_counts: defaultdict[CriticalMistakeType, int] = defaultdict(int)
        selections_count = 0
        with read_connection(self._database_path, "critical mistakes") as connection:
            selections = connection.execute(
                "SELECT match_id, team_id FROM opponent_match_selections "
                "WHERE profile_id = ? ORDER BY match_id",
                [profile_id],
            ).fetchall()
            selections_count = len(selections)
            for match_raw, team_raw in selections:
                match_id, team_id = UUID(str(match_raw)), UUID(str(team_raw))
                projected = self._project_match(connection, match_id, team_id)
                if projected is None:
                    warnings.add(f"match_without_compatible_analysis:{match_id}")
                    continue
                pin, match_candidates, match_eligible, available_types = projected
                pins.append(pin)
                candidates.extend(match_candidates)
                for key, value in match_eligible.items():
                    eligible[key] += value
                for key in available_types:
                    source_counts[key] += 1

        capabilities: dict[CriticalMistakeType, CriticalCapabilityStatus] = {}
        limitations: dict[CriticalMistakeType, tuple[str, ...]] = {}
        descriptions = {
            CriticalMistakeType.LOST_PLUS_TWO: (
                "Не учитываются раунды, где итог одновременной группы смертей не доказан.",
            ),
            CriticalMistakeType.LOST_VS_FULL_ECO: (
                "Полным эко считается только подтверждённый тип покупки eco; "
                "force, semi и unknown исключены.",
            ),
            CriticalMistakeType.EARLY_UNTRADED_DEATH: (
                "Порог 15 секунд считается от начала live-фазы только при доказанном tickrate.",
                "Размен определяется сохранённым детерминированным правилом окна размена.",
            ),
        }
        for kind in CriticalMistakeType:
            covered = source_counts[kind]
            if covered == 0:
                capabilities[kind] = CriticalCapabilityStatus.UNAVAILABLE
            elif covered < selections_count:
                capabilities[kind] = CriticalCapabilityStatus.PARTIAL
            else:
                capabilities[kind] = CriticalCapabilityStatus.AVAILABLE
            limitations[kind] = descriptions[kind]
        if not selections:
            warnings.add("profile_has_no_selected_matches")
        return CriticalMistakesInput(
            profile_id=profile_id,
            source_pins=tuple(pins),
            eligible_counts=dict(eligible),
            candidates=tuple(candidates),
            capabilities=capabilities,
            limitations=limitations,
            warnings=tuple(sorted(warnings)),
        )

    def _project_match(
        self, connection: duckdb.DuckDBPyConnection, match_id: UUID, team_id: UUID
    ) -> (
        tuple[
            CriticalSourcePin,
            list[CriticalCandidate],
            dict[CriticalMistakeType, int],
            set[CriticalMistakeType],
        ]
        | None
    ):
        match = connection.execute(
            "SELECT dataset_fingerprint, COALESCE(map_name, 'unknown') "
            "FROM matches WHERE match_id = ?",
            [match_id],
        ).fetchone()
        analytics = connection.execute(
            """SELECT analytics_fingerprint, analytics_rule_version,
                      trade_window_tickrate, trade_window_tickrate_source
               FROM analytics_runs WHERE match_id = ?
                 AND analytics_schema_version = ? AND analytics_rule_version = ?
               ORDER BY created_at DESC, analytics_fingerprint DESC LIMIT 1""",
            [match_id, ANALYTICS_SCHEMA_VERSION, ANALYTICS_RULE_VERSION],
        ).fetchone()
        temporal = connection.execute(
            """SELECT temporal_run_id, temporal_fingerprint, temporal_rule_version
               FROM temporal_runs WHERE match_id = ?
                 AND temporal_schema_version = ? AND temporal_rule_version = ?
               ORDER BY created_at DESC, temporal_fingerprint DESC LIMIT 1""",
            [match_id, TEMPORAL_SCHEMA_VERSION, TEMPORAL_RULE_VERSION],
        ).fetchone()
        if match is None or analytics is None or temporal is None:
            return None
        economy = connection.execute(
            """SELECT economy_run_id, economy_fingerprint, economy_rule_version
               FROM economy_runs WHERE match_id = ?
                 AND economy_schema_version = ? AND economy_rule_version = ?
               ORDER BY created_at DESC, economy_fingerprint DESC LIMIT 1""",
            [match_id, ECONOMY_SCHEMA_VERSION, ECONOMY_RULE_VERSION],
        ).fetchone()
        map_name = str(match[1])
        analytics_fp = str(analytics[0])
        temporal_id = UUID(str(temporal[0]))
        tickrate = float(analytics[2]) if analytics[2] is not None else None
        pin = CriticalSourcePin(
            match_id=match_id,
            team_id=team_id,
            map_name=map_name,
            dataset_fingerprint=str(match[0]),
            analytics_fingerprint=analytics_fp,
            analytics_rule_version=str(analytics[1]),
            temporal_run_id=temporal_id,
            temporal_fingerprint=str(temporal[1]),
            temporal_rule_version=str(temporal[2]),
            economy_run_id=UUID(str(economy[0])) if economy else None,
            economy_fingerprint=str(economy[1]) if economy else None,
            economy_rule_version=str(economy[2]) if economy else None,
            tickrate=tickrate,
            tickrate_source=str(analytics[3]) if analytics[3] is not None else None,
        )
        team_rounds = connection.execute(
            """SELECT a.round_number, a.side, a.round_won, a.opponent_team_id
               FROM team_round_analytics a JOIN rounds r
                 ON r.match_id=a.match_id AND r.round_id=a.round_id
               WHERE a.analytics_fingerprint=? AND a.team_id=?
                 AND r.is_warmup=FALSE AND r.is_complete=TRUE
               ORDER BY a.round_number""",
            [analytics_fp, team_id],
        ).fetchall()
        names = {
            UUID(str(row[0])): str(row[1])
            for row in connection.execute(
                "SELECT player_id, current_name FROM players WHERE match_id=?", [match_id]
            ).fetchall()
        }
        candidates: list[CriticalCandidate] = []
        eligible: defaultdict[CriticalMistakeType, int] = defaultdict(int)
        available = {CriticalMistakeType.LOST_PLUS_TWO}
        groups_by_round: defaultdict[int, list[SimultaneousEventGroup]] = defaultdict(list)
        group_ticks: defaultdict[int, set[int]] = defaultdict(set)
        for payload_raw in connection.execute(
            "SELECT payload FROM temporal_simultaneous_groups WHERE temporal_run_id=?",
            [temporal_id],
        ).fetchall():
            group = SimultaneousEventGroup.model_validate(_json(payload_raw[0]))
            groups_by_round[group.round_number].append(group)
            group_ticks[group.round_number].add(group.tick)
        transitions = connection.execute(
            """SELECT round_number,tick,event_id,t_alive_after,ct_alive_after
               FROM man_advantage_transitions WHERE analytics_fingerprint=?
               ORDER BY round_number,tick,event_id""",
            [analytics_fp],
        ).fetchall()
        transitions_by_round: defaultdict[int, list[tuple[Any, ...]]] = defaultdict(list)
        for row in transitions:
            transitions_by_round[int(row[0])].append(row)

        for round_raw, side_raw, won_raw, opponent_raw in team_rounds:
            round_number, side = int(round_raw), Side(str(side_raw))
            if won_raw is None or side not in {Side.T, Side.CT}:
                continue
            advantage_evidence: CriticalEvidence | None = None
            for group in groups_by_round[round_number]:
                state = group.post_group_state
                if not group.post_group_snapshot_deterministic or state is None:
                    continue
                ours, theirs = (
                    (state.t_alive, state.ct_alive)
                    if side is Side.T
                    else (state.ct_alive, state.t_alive)
                )
                if ours - theirs >= 2:
                    advantage_evidence = CriticalEvidence(
                        match_id=match_id,
                        round_number=round_number,
                        tick=group.tick,
                        event_ids=group.ordered_event_ids,
                        temporal_group_id=group.group_id,
                        facts=(
                            f"После одновременных событий было {ours} в {theirs}.",
                            "Итог группы событий доказан Temporal Engine.",
                        ),
                    )
                    break
            if advantage_evidence is None:
                for row in transitions_by_round[round_number]:
                    tick = int(row[1])
                    if tick in group_ticks[round_number]:
                        continue
                    ours, theirs = (
                        (int(row[3]), int(row[4])) if side is Side.T else (int(row[4]), int(row[3]))
                    )
                    if ours - theirs >= 2:
                        advantage_evidence = CriticalEvidence(
                            match_id=match_id,
                            round_number=round_number,
                            tick=tick,
                            event_ids=(UUID(str(row[2])),),
                            facts=(
                                f"Команда получила преимущество {ours} в {theirs}.",
                                "Состояние взято после завершённого события.",
                            ),
                        )
                        break
            if advantage_evidence is not None:
                eligible[CriticalMistakeType.LOST_PLUS_TWO] += 1
                if not bool(won_raw):
                    candidates.append(_plus_two_candidate(map_name, side, advantage_evidence))

            if economy is not None:
                available.add(CriticalMistakeType.LOST_VS_FULL_ECO)
                eco_row = connection.execute(
                    """SELECT team_snapshot_id FROM team_economy_snapshots
                       WHERE economy_run_id=? AND round_number=? AND team_id=?
                         AND buy_type='eco' AND classification_availability='available'
                         AND eligible=TRUE LIMIT 1""",
                    [economy[0], round_number, opponent_raw],
                ).fetchone()
                if eco_row is not None:
                    eligible[CriticalMistakeType.LOST_VS_FULL_ECO] += 1
                    if not bool(won_raw):
                        evidence = CriticalEvidence(
                            match_id=match_id,
                            round_number=round_number,
                            economy_snapshot_id=UUID(str(eco_row[0])),
                            facts=(
                                "Покупка соперника подтверждена как полное эко.",
                                "Раунд проигран анализируемой командой.",
                            ),
                        )
                        candidates.append(_eco_candidate(map_name, side, evidence))

        if tickrate is not None and analytics[3] is not None:
            available.add(CriticalMistakeType.EARLY_UNTRADED_DEATH)
            deaths = connection.execute(
                """SELECT k.round_number,k.tick,(k.tick-r.freeze_end_tick) AS live_tick,
                          k.event_id,k.victim_player_id,
                          t.original_kill_event_id
                   FROM kills k JOIN rounds r ON r.match_id=k.match_id AND r.round_id=k.round_id
                   LEFT JOIN trade_events t ON t.analytics_fingerprint=?
                     AND t.original_kill_event_id=k.event_id AND t.team_id=?
                   WHERE k.match_id=? AND k.victim_team_id=?
                     AND k.attacker_team_id IS NOT NULL AND k.attacker_team_id<>k.victim_team_id
                     AND COALESCE(k.is_teamkill,FALSE)=FALSE AND COALESCE(k.is_suicide,FALSE)=FALSE
                     AND r.freeze_end_tick IS NOT NULL AND k.tick>=r.freeze_end_tick
                     AND r.is_warmup=FALSE AND r.is_complete=TRUE
                   ORDER BY k.round_number,k.tick,k.event_id""",
                [analytics_fp, team_id, match_id, team_id],
            ).fetchall()
            side_by_round = {int(row[0]): Side(str(row[1])) for row in team_rounds}
            for row in deaths:
                seconds = int(row[2]) / tickrate
                if seconds > EARLY_DEATH_WINDOW_SECONDS:
                    continue
                eligible[CriticalMistakeType.EARLY_UNTRADED_DEATH] += 1
                if row[5] is not None:
                    continue
                victim_id = UUID(str(row[4])) if row[4] is not None else None
                victim_name = names.get(victim_id, "Игрок") if victim_id else "Игрок"
                evidence = CriticalEvidence(
                    match_id=match_id,
                    round_number=int(row[0]),
                    tick=int(row[1]),
                    event_ids=(UUID(str(row[3])),),
                    victim_player_id=victim_id,
                    facts=(
                        f"{victim_name}: смерть через {seconds:.1f} с после начала раунда.",
                        "Подтверждённого размена в заданном окне нет.",
                    ),
                )
                candidates.append(
                    _early_candidate(
                        map_name, side_by_round[int(row[0])], evidence, victim_name, seconds
                    )
                )
        return pin, candidates, dict(eligible), available

    def save(self, state: CriticalMistakesRun) -> CriticalSaveResult:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path)) as connection:
                existing = connection.execute(
                    "SELECT critical_run_id FROM critical_mistake_runs "
                    "WHERE critical_fingerprint=?",
                    [state.critical_fingerprint],
                ).fetchone()
                if existing:
                    return CriticalSaveResult(
                        critical_run_id=UUID(str(existing[0])),
                        critical_fingerprint=state.critical_fingerprint,
                        status=CriticalSaveStatus.ALREADY_EXISTS,
                    )
                connection.execute(
                    "INSERT INTO critical_mistake_runs VALUES (?,?,?,?,?,?,current_timestamp)",
                    [
                        state.critical_run_id,
                        state.critical_fingerprint,
                        state.critical_schema_version,
                        state.critical_rule_version,
                        state.profile_id,
                        canonical_json(state.model_dump(mode="json")),
                    ],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist critical mistakes.") from exc
        return CriticalSaveResult(
            critical_run_id=state.critical_run_id,
            critical_fingerprint=state.critical_fingerprint,
            status=CriticalSaveStatus.COMPUTED,
        )

    def get_latest(self, profile_id: UUID) -> CriticalMistakesRun | None:
        self.initialize()
        with read_connection(self._database_path, "critical mistakes") as connection:
            row = connection.execute(
                """SELECT payload FROM critical_mistake_runs WHERE profile_id=?
                   AND critical_schema_version=? AND critical_rule_version=?
                   ORDER BY created_at DESC,critical_fingerprint DESC LIMIT 1""",
                [profile_id, CRITICAL_MISTAKES_SCHEMA_VERSION, CRITICAL_MISTAKES_RULE_VERSION],
            ).fetchone()
        return CriticalMistakesRun.model_validate(_json(row[0])) if row else None


def _plus_two_candidate(map_name: str, side: Side, evidence: CriticalEvidence) -> CriticalCandidate:
    return CriticalCandidate(
        mistake_type=CriticalMistakeType.LOST_PLUS_TWO,
        map_name=map_name,
        side=side,
        evidence=evidence,
        title="Упустили преимущество в двух игроков",
        observation="Команда вела минимум в двух игроков, но проиграла раунд.",
        tactical_interpretation="После численного преимущества раунд не был доведён до победы.",
        recommendation=(
            "Разберите решение сразу после получения преимущества: позиции, "
            "парные контакты и запрет одиночных дуэлей."
        ),
    )


def _eco_candidate(map_name: str, side: Side, evidence: CriticalEvidence) -> CriticalCandidate:
    return CriticalCandidate(
        mistake_type=CriticalMistakeType.LOST_VS_FULL_ECO,
        map_name=map_name,
        side=side,
        evidence=evidence,
        title="Проиграли против полного эко",
        observation="Раунд проигран сопернику с подтверждённой покупкой eco.",
        tactical_interpretation="Команда не реализовала преимущество в вооружении.",
        recommendation=(
            "Проверьте дистанции, сбор информации и размены; не отдавайте "
            "оружие в одиночных ближних контактах."
        ),
    )


def _early_candidate(
    map_name: str, side: Side, evidence: CriticalEvidence, player: str, seconds: float
) -> CriticalCandidate:
    return CriticalCandidate(
        mistake_type=CriticalMistakeType.EARLY_UNTRADED_DEATH,
        map_name=map_name,
        side=side,
        evidence=evidence,
        title=f"{player}: ранняя смерть без размена",
        observation=f"Игрок погиб через {seconds:.1f} секунды, подтверждённого размена нет.",
        tactical_interpretation="Команда рано осталась в меньшинстве без немедленной компенсации.",
        recommendation=(
            "Проверьте стартовую пару, дистанцию для размена и необходимость "
            "этого раннего контакта."
        ),
    )


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBCriticalMistakesRepository"]
