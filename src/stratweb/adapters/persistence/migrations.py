"""Ordered, path-independent DuckDB migrations with content checksums."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


INITIAL_SCHEMA = r"""
CREATE TABLE matches (
    match_id UUID PRIMARY KEY,
    demo_file_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    source_demo_sha256 VARCHAR(64) NOT NULL,
    source_original_name VARCHAR,
    map_name VARCHAR,
    server_name VARCHAR,
    round_count INTEGER NOT NULL CHECK (round_count >= 0),
    complete_round_count INTEGER NOT NULL CHECK (complete_round_count >= 0),
    incomplete_round_count INTEGER NOT NULL CHECK (incomplete_round_count >= 0),
    round_count_candidates JSON NOT NULL,
    selected_round_count INTEGER CHECK (selected_round_count >= 0),
    selected_round_count_source VARCHAR,
    round_count_disagreement BOOLEAN NOT NULL,
    validation_is_valid BOOLEAN NOT NULL,
    validation_has_fatal_errors BOOLEAN NOT NULL,
    validation_fatal_error_count INTEGER NOT NULL CHECK (validation_fatal_error_count >= 0),
    validation_unassigned_event_count INTEGER NOT NULL
        CHECK (validation_unassigned_event_count >= 0),
    validation_unknown_player_count INTEGER NOT NULL CHECK (validation_unknown_player_count >= 0),
    validation_incomplete_round_count INTEGER NOT NULL
        CHECK (validation_incomplete_round_count >= 0),
    validation_issue_counts JSON NOT NULL,
    parser_name VARCHAR NOT NULL,
    parser_version VARCHAR NOT NULL,
    canonical_schema_version VARCHAR NOT NULL,
    normalization_rule_version VARCHAR NOT NULL,
    normalization_config_hash VARCHAR(64) NOT NULL,
    imported_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE teams (
    match_id UUID NOT NULL,
    team_id UUID NOT NULL,
    internal_name VARCHAR NOT NULL,
    display_name VARCHAR,
    starting_player_ids JSON NOT NULL,
    identity_confidence DOUBLE NOT NULL
        CHECK (identity_confidence >= 0 AND identity_confidence <= 1),
    warnings JSON NOT NULL,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE players (
    match_id UUID NOT NULL,
    player_id UUID NOT NULL,
    steam_id VARCHAR,
    current_name VARCHAR NOT NULL,
    known_names JSON NOT NULL,
    is_bot BOOLEAN NOT NULL,
    warnings JSON NOT NULL,
    PRIMARY KEY (match_id, player_id)
);

CREATE TABLE memberships (
    match_id UUID NOT NULL,
    player_id UUID NOT NULL,
    team_id UUID,
    side VARCHAR NOT NULL,
    valid_from_tick BIGINT NOT NULL CHECK (valid_from_tick >= 0),
    valid_to_tick BIGINT CHECK (valid_to_tick >= 0),
    source VARCHAR NOT NULL,
    confidence DOUBLE NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    PRIMARY KEY (match_id, player_id, side, valid_from_tick)
);

CREATE TABLE rounds (
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL CHECK (round_number >= 1),
    start_tick BIGINT CHECK (start_tick >= 0),
    freeze_end_tick BIGINT CHECK (freeze_end_tick >= 0),
    end_tick BIGINT CHECK (end_tick >= 0),
    official_end_tick BIGINT CHECK (official_end_tick >= 0),
    start_source VARCHAR,
    end_source VARCHAR,
    t_team_id UUID,
    ct_team_id UUID,
    winner_side VARCHAR NOT NULL,
    end_reason VARCHAR,
    score_t_before INTEGER CHECK (score_t_before >= 0),
    score_ct_before INTEGER CHECK (score_ct_before >= 0),
    score_t_after INTEGER CHECK (score_t_after >= 0),
    score_ct_after INTEGER CHECK (score_ct_after >= 0),
    is_warmup BOOLEAN NOT NULL,
    is_overtime BOOLEAN NOT NULL,
    is_complete BOOLEAN NOT NULL,
    exclusion_reason VARCHAR,
    warnings JSON NOT NULL,
    PRIMARY KEY (match_id, round_id),
    UNIQUE (match_id, round_number)
);

CREATE TABLE kills (
    match_id UUID NOT NULL,
    event_id UUID NOT NULL,
    round_id UUID,
    round_number INTEGER,
    tick BIGINT NOT NULL CHECK (tick >= 0),
    relative_tick BIGINT CHECK (relative_tick >= 0),
    phase VARCHAR NOT NULL,
    source_event VARCHAR NOT NULL,
    warnings JSON NOT NULL,
    attacker_player_id UUID,
    victim_player_id UUID,
    assister_player_id UUID,
    attacker_team_id UUID,
    victim_team_id UUID,
    attacker_side VARCHAR NOT NULL,
    victim_side VARCHAR NOT NULL,
    weapon VARCHAR,
    headshot BOOLEAN,
    penetrated INTEGER CHECK (penetrated >= 0),
    through_smoke BOOLEAN,
    no_scope BOOLEAN,
    attacker_blind BOOLEAN,
    distance DOUBLE CHECK (distance >= 0),
    is_teamkill BOOLEAN,
    is_suicide BOOLEAN,
    PRIMARY KEY (match_id, event_id)
);

CREATE TABLE damages (
    match_id UUID NOT NULL,
    event_id UUID NOT NULL,
    round_id UUID,
    round_number INTEGER,
    tick BIGINT NOT NULL CHECK (tick >= 0),
    relative_tick BIGINT CHECK (relative_tick >= 0),
    phase VARCHAR NOT NULL,
    source_event VARCHAR NOT NULL,
    warnings JSON NOT NULL,
    attacker_player_id UUID,
    victim_player_id UUID,
    attacker_team_id UUID,
    victim_team_id UUID,
    attacker_side VARCHAR NOT NULL,
    victim_side VARCHAR NOT NULL,
    weapon VARCHAR,
    damage_health INTEGER CHECK (damage_health >= 0),
    damage_armor INTEGER CHECK (damage_armor >= 0),
    victim_health_after INTEGER CHECK (victim_health_after >= 0),
    hitgroup VARCHAR,
    PRIMARY KEY (match_id, event_id)
);

CREATE TABLE shots (
    match_id UUID NOT NULL,
    event_id UUID NOT NULL,
    round_id UUID,
    round_number INTEGER,
    tick BIGINT NOT NULL CHECK (tick >= 0),
    relative_tick BIGINT CHECK (relative_tick >= 0),
    phase VARCHAR NOT NULL,
    source_event VARCHAR NOT NULL,
    warnings JSON NOT NULL,
    player_id UUID,
    team_id UUID,
    side VARCHAR NOT NULL,
    weapon VARCHAR,
    silenced BOOLEAN,
    PRIMARY KEY (match_id, event_id)
);

CREATE TABLE grenades (
    match_id UUID NOT NULL,
    event_id UUID NOT NULL,
    round_id UUID,
    round_number INTEGER,
    tick BIGINT NOT NULL CHECK (tick >= 0),
    relative_tick BIGINT CHECK (relative_tick >= 0),
    phase VARCHAR NOT NULL,
    source_event VARCHAR NOT NULL,
    warnings JSON NOT NULL,
    player_id UUID,
    team_id UUID,
    side VARCHAR NOT NULL,
    grenade_type VARCHAR NOT NULL,
    lifecycle_event VARCHAR NOT NULL,
    entity_id BIGINT CHECK (entity_id >= 0),
    x DOUBLE,
    y DOUBLE,
    z DOUBLE,
    PRIMARY KEY (match_id, event_id)
);

CREATE TABLE bomb_events (
    match_id UUID NOT NULL,
    event_id UUID NOT NULL,
    round_id UUID,
    round_number INTEGER,
    tick BIGINT NOT NULL CHECK (tick >= 0),
    relative_tick BIGINT CHECK (relative_tick >= 0),
    phase VARCHAR NOT NULL,
    source_event VARCHAR NOT NULL,
    warnings JSON NOT NULL,
    player_id UUID,
    team_id UUID,
    side VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL,
    site_raw JSON,
    site_normalized VARCHAR,
    PRIMARY KEY (match_id, event_id)
);

CREATE TABLE validation_issues (
    match_id UUID NOT NULL,
    issue_index INTEGER NOT NULL CHECK (issue_index >= 0),
    code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    is_fatal BOOLEAN NOT NULL,
    entity_type VARCHAR NOT NULL,
    entity_id VARCHAR,
    message VARCHAR NOT NULL,
    evidence JSON NOT NULL,
    rule_version VARCHAR NOT NULL,
    PRIMARY KEY (match_id, issue_index)
);

CREATE TABLE normalization_metadata (
    match_id UUID PRIMARY KEY,
    source_event_counts JSON NOT NULL,
    selected_event_aliases JSON NOT NULL,
    warnings JSON NOT NULL
);

CREATE INDEX idx_matches_map_imported ON matches(map_name, imported_at);
CREATE INDEX idx_matches_source_sha ON matches(source_demo_sha256);
CREATE INDEX idx_players_steam_id ON players(steam_id);
CREATE INDEX idx_rounds_match_number ON rounds(match_id, round_number);
CREATE INDEX idx_kills_match_round_tick ON kills(match_id, round_number, tick);
CREATE INDEX idx_kills_match_attacker ON kills(match_id, attacker_player_id);
CREATE INDEX idx_kills_match_victim ON kills(match_id, victim_player_id);
CREATE INDEX idx_damages_match_round_tick ON damages(match_id, round_number, tick);
CREATE INDEX idx_shots_match_round_tick ON shots(match_id, round_number, tick);
CREATE INDEX idx_grenades_match_round_tick ON grenades(match_id, round_number, tick);
CREATE INDEX idx_grenades_match_player_type ON grenades(match_id, player_id, grenade_type);
CREATE INDEX idx_bomb_events_match_round_tick ON bomb_events(match_id, round_number, tick);
CREATE INDEX idx_validation_match_severity ON validation_issues(match_id, severity);
"""


RESULT_AVAILABILITY_SCHEMA = r"""
CREATE TABLE rounds_v2 (
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL CHECK (round_number >= 1),
    start_tick BIGINT CHECK (start_tick >= 0),
    freeze_end_tick BIGINT CHECK (freeze_end_tick >= 0),
    end_tick BIGINT CHECK (end_tick >= 0),
    official_end_tick BIGINT CHECK (official_end_tick >= 0),
    start_source VARCHAR,
    end_source VARCHAR,
    t_team_id UUID,
    ct_team_id UUID,
    winner_side VARCHAR,
    outcome_status VARCHAR NOT NULL,
    outcome_source VARCHAR,
    end_reason VARCHAR,
    end_reason_status VARCHAR NOT NULL,
    end_reason_source VARCHAR,
    score_t_before INTEGER CHECK (score_t_before >= 0),
    score_ct_before INTEGER CHECK (score_ct_before >= 0),
    score_t_after INTEGER CHECK (score_t_after >= 0),
    score_ct_after INTEGER CHECK (score_ct_after >= 0),
    score_status VARCHAR NOT NULL,
    score_source VARCHAR,
    is_warmup BOOLEAN NOT NULL,
    is_overtime BOOLEAN NOT NULL,
    is_complete BOOLEAN NOT NULL,
    exclusion_reason VARCHAR,
    warnings JSON NOT NULL,
    PRIMARY KEY (match_id, round_id),
    UNIQUE (match_id, round_number)
);

INSERT INTO rounds_v2 (
    match_id, round_id, round_number, start_tick, freeze_end_tick, end_tick,
    official_end_tick, start_source, end_source, t_team_id, ct_team_id,
    winner_side, outcome_status, outcome_source, end_reason,
    end_reason_status, end_reason_source, score_t_before, score_ct_before,
    score_t_after, score_ct_after, score_status, score_source, is_warmup,
    is_overtime, is_complete, exclusion_reason, warnings
)
SELECT
    match_id, round_id, round_number, start_tick, freeze_end_tick, end_tick,
    official_end_tick, start_source, end_source, t_team_id, ct_team_id,
    NULL,
    CASE
        WHEN winner_side IN ('T', 'CT') THEN 'unresolved'
        ELSE 'missing_from_source'
    END,
    NULL,
    NULL,
    CASE
        WHEN end_reason IS NOT NULL THEN 'unresolved'
        ELSE 'missing_from_source'
    END,
    NULL,
    NULL, NULL, NULL, NULL,
    CASE
        WHEN score_t_before IS NOT NULL OR score_ct_before IS NOT NULL
          OR score_t_after IS NOT NULL OR score_ct_after IS NOT NULL
        THEN 'unresolved'
        ELSE 'missing_from_source'
    END,
    NULL,
    is_warmup, is_overtime, is_complete, exclusion_reason, warnings
FROM rounds;

DROP TABLE rounds;
ALTER TABLE rounds_v2 RENAME TO rounds;
CREATE INDEX idx_rounds_match_number ON rounds(match_id, round_number);
ALTER TABLE normalization_metadata ADD COLUMN result_capabilities JSON;
"""


ANALYTICS_SCHEMA = r"""
CREATE TABLE analytics_runs (
    analytics_fingerprint VARCHAR(64) PRIMARY KEY,
    match_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    analytics_schema_version VARCHAR NOT NULL,
    analytics_rule_version VARCHAR NOT NULL,
    analytics_config_hash VARCHAR(64) NOT NULL,
    config JSON NOT NULL,
    availability JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (dataset_fingerprint, analytics_rule_version, analytics_config_hash)
);

CREATE TABLE player_round_analytics (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    player_id UUID NOT NULL, team_id UUID NOT NULL, side VARCHAR NOT NULL,
    kills INTEGER NOT NULL, deaths INTEGER NOT NULL, assists INTEGER NOT NULL,
    headshots INTEGER NOT NULL, damage INTEGER NOT NULL, enemy_damage INTEGER NOT NULL,
    team_damage INTEGER NOT NULL, shots INTEGER NOT NULL, survived BOOLEAN NOT NULL,
    traded_kills INTEGER, traded_deaths INTEGER,
    trade_opportunities INTEGER, successful_trades INTEGER,
    opening_kill BOOLEAN NOT NULL, opening_death BOOLEAN NOT NULL,
    multikill_count INTEGER NOT NULL, multikill_category VARCHAR NOT NULL,
    kast_k BOOLEAN NOT NULL, kast_a BOOLEAN NOT NULL, kast_s BOOLEAN NOT NULL,
    kast_t BOOLEAN, kast BOOLEAN, teamkill_count INTEGER NOT NULL,
    suicide_count INTEGER NOT NULL, plants INTEGER NOT NULL, defuses INTEGER NOT NULL,
    PRIMARY KEY (analytics_fingerprint, round_id, player_id)
);

CREATE TABLE player_match_analytics (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, player_id UUID NOT NULL, current_name VARCHAR NOT NULL,
    steam_id VARCHAR, rounds_played INTEGER NOT NULL, kills INTEGER NOT NULL,
    deaths INTEGER NOT NULL, assists INTEGER NOT NULL, kd_ratio DOUBLE,
    kill_differential INTEGER NOT NULL, adr DOUBLE, kpr DOUBLE, dpr DOUBLE, apr DOUBLE,
    headshots INTEGER NOT NULL, headshot_percentage DOUBLE, total_damage INTEGER NOT NULL,
    enemy_damage INTEGER NOT NULL, team_damage INTEGER NOT NULL, shots INTEGER NOT NULL,
    survival_rounds INTEGER NOT NULL, survival_percentage DOUBLE,
    opening_kills INTEGER NOT NULL, opening_deaths INTEGER NOT NULL,
    opening_duel_attempts INTEGER NOT NULL, opening_duel_success_percentage DOUBLE,
    opening_kill_round_wins INTEGER, opening_kill_conversion_percentage DOUBLE,
    traded_kills INTEGER, traded_deaths INTEGER,
    trade_opportunities INTEGER, successful_trades INTEGER, trade_success_percentage DOUBLE,
    traded_death_percentage DOUBLE, multikill_rounds INTEGER NOT NULL,
    two_k_rounds INTEGER NOT NULL, three_k_rounds INTEGER NOT NULL,
    four_k_rounds INTEGER NOT NULL, five_k_rounds INTEGER NOT NULL,
    five_plus_rounds INTEGER NOT NULL, kast_rounds INTEGER,
    kast_percentage DOUBLE, kast_k_rounds INTEGER NOT NULL,
    kast_a_rounds INTEGER NOT NULL, kast_s_rounds INTEGER NOT NULL,
    kast_t_rounds INTEGER, teamkills INTEGER NOT NULL, suicides INTEGER NOT NULL,
    plants INTEGER NOT NULL, defuses INTEGER NOT NULL,
    PRIMARY KEY (analytics_fingerprint, player_id)
);

CREATE TABLE team_round_analytics (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    team_id UUID NOT NULL, opponent_team_id UUID NOT NULL, side VARCHAR NOT NULL,
    participant_count INTEGER NOT NULL, lineup_valid BOOLEAN NOT NULL, round_won BOOLEAN,
    kills INTEGER NOT NULL, deaths INTEGER NOT NULL, assists INTEGER NOT NULL,
    enemy_damage INTEGER NOT NULL, opening_kill BOOLEAN NOT NULL,
    opening_death BOOLEAN NOT NULL, opening_kill_converted BOOLEAN,
    recovered_after_opening_death BOOLEAN, trade_opportunities INTEGER,
    successful_trades INTEGER, traded_deaths INTEGER, untraded_deaths INTEGER,
    gained_first_advantage BOOLEAN NOT NULL,
    first_advantage_size INTEGER NOT NULL, lost_first_advantage BOOLEAN NOT NULL,
    converted_first_advantage BOOLEAN, recovered_after_first_disadvantage BOOLEAN,
    reached_plus_two BOOLEAN NOT NULL, converted_plus_two BOOLEAN,
    max_advantage INTEGER NOT NULL, final_alive INTEGER NOT NULL,
    plants INTEGER NOT NULL, defuses INTEGER NOT NULL, explosions INTEGER NOT NULL,
    planted_round BOOLEAN NOT NULL, post_plant_won BOOLEAN,
    bomb_outcome_observed BOOLEAN NOT NULL,
    PRIMARY KEY (analytics_fingerprint, round_id, team_id)
);

CREATE TABLE team_match_analytics (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, team_id UUID NOT NULL, internal_name VARCHAR NOT NULL,
    display_name VARCHAR, rounds_played INTEGER NOT NULL, round_wins INTEGER,
    t_rounds INTEGER NOT NULL, ct_rounds INTEGER NOT NULL,
    t_round_wins INTEGER, ct_round_wins INTEGER, kills INTEGER NOT NULL,
    deaths INTEGER NOT NULL, assists INTEGER NOT NULL, enemy_damage INTEGER NOT NULL,
    adr DOUBLE, opening_kills INTEGER NOT NULL, opening_deaths INTEGER NOT NULL,
    opening_kill_conversions INTEGER, opening_conversion_percentage DOUBLE,
    opening_death_recoveries INTEGER, opening_death_recovery_percentage DOUBLE,
    trade_opportunities INTEGER, successful_trades INTEGER, trade_percentage DOUBLE,
    traded_deaths INTEGER, untraded_deaths INTEGER,
    first_advantage_rounds INTEGER NOT NULL, first_advantage_conversions INTEGER,
    first_advantage_conversion_percentage DOUBLE, first_disadvantage_rounds INTEGER NOT NULL,
    first_disadvantage_recoveries INTEGER, first_disadvantage_recovery_percentage DOUBLE,
    plus_two_rounds INTEGER NOT NULL, plus_two_conversions INTEGER,
    plus_two_conversion_percentage DOUBLE, plants INTEGER NOT NULL, defuses INTEGER NOT NULL,
    explosions INTEGER NOT NULL, rounds_with_plant INTEGER NOT NULL,
    rounds_with_defuse INTEGER NOT NULL, rounds_with_explosion INTEGER NOT NULL,
    post_plant_wins INTEGER, post_plant_conversion_percentage DOUBLE,
    bomb_outcome_coverage_percentage DOUBLE, ct_defuse_success_percentage DOUBLE,
    PRIMARY KEY (analytics_fingerprint, team_id)
);

CREATE TABLE opening_duels (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    opening_killer_player_id UUID NOT NULL, opening_victim_player_id UUID NOT NULL,
    killer_team_id UUID NOT NULL, victim_team_id UUID NOT NULL,
    killer_side VARCHAR NOT NULL, victim_side VARCHAR NOT NULL, tick BIGINT NOT NULL,
    relative_tick BIGINT, event_id UUID NOT NULL, round_winner VARCHAR,
    opening_team_won_round BOOLEAN, seconds_from_freeze_end DOUBLE,
    PRIMARY KEY (analytics_fingerprint, round_id)
);

CREATE TABLE trade_events (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    traded_kill_event_id UUID NOT NULL, original_kill_event_id UUID NOT NULL,
    trader_player_id UUID NOT NULL, traded_player_id UUID NOT NULL,
    traded_enemy_player_id UUID NOT NULL, tick_delta BIGINT NOT NULL,
    seconds_delta DOUBLE, team_id UUID NOT NULL, side VARCHAR NOT NULL,
    PRIMARY KEY (analytics_fingerprint, traded_kill_event_id),
    UNIQUE (analytics_fingerprint, original_kill_event_id)
);

CREATE TABLE man_advantage_transitions (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL, event_id UUID NOT NULL, t_alive_before INTEGER NOT NULL,
    t_alive_after INTEGER NOT NULL, ct_alive_before INTEGER NOT NULL,
    ct_alive_after INTEGER NOT NULL, signed_advantage_before INTEGER NOT NULL,
    signed_advantage_after INTEGER NOT NULL, advantage_before VARCHAR NOT NULL,
    advantage_after VARCHAR NOT NULL, causing_killer_player_id UUID,
    causing_victim_player_id UUID NOT NULL, event_classification VARCHAR NOT NULL,
    PRIMARY KEY (analytics_fingerprint, event_id)
);

CREATE TABLE analytics_validation_issues (
    analytics_fingerprint VARCHAR(64) NOT NULL,
    issue_index INTEGER NOT NULL, match_id UUID NOT NULL, code VARCHAR NOT NULL,
    severity VARCHAR NOT NULL, is_fatal BOOLEAN NOT NULL, entity_type VARCHAR NOT NULL,
    entity_id VARCHAR, message VARCHAR NOT NULL, evidence JSON NOT NULL,
    PRIMARY KEY (analytics_fingerprint, issue_index)
);

CREATE INDEX idx_analytics_runs_match ON analytics_runs(match_id, created_at);
CREATE INDEX idx_player_analytics_match ON player_match_analytics(match_id, player_id);
CREATE INDEX idx_team_analytics_match ON team_match_analytics(match_id, team_id);
CREATE INDEX idx_player_round_analytics_round ON player_round_analytics(match_id, round_number);
CREATE INDEX idx_team_round_analytics_round ON team_round_analytics(match_id, round_number);
CREATE INDEX idx_opening_duels_match_round ON opening_duels(match_id, round_number);
CREATE INDEX idx_trade_events_match_round ON trade_events(match_id, round_number);
CREATE INDEX idx_advantage_match_round ON man_advantage_transitions(match_id, round_number, tick);
"""


TRADE_WINDOW_SEMANTICS_SCHEMA = r"""
ALTER TABLE analytics_runs ADD COLUMN trade_window_mode VARCHAR DEFAULT 'legacy_ambiguous';
ALTER TABLE analytics_runs ADD COLUMN trade_window_requested_ticks BIGINT;
ALTER TABLE analytics_runs ADD COLUMN trade_window_requested_seconds DOUBLE;
ALTER TABLE analytics_runs ADD COLUMN trade_window_resolved_ticks BIGINT;
ALTER TABLE analytics_runs ADD COLUMN trade_window_tickrate DOUBLE;
ALTER TABLE analytics_runs ADD COLUMN trade_window_tickrate_source VARCHAR;
ALTER TABLE analytics_runs
    ADD COLUMN trade_window_resolution_source VARCHAR DEFAULT 'legacy_ambiguous';

ALTER TABLE trade_events ADD COLUMN seconds_delta_status VARCHAR DEFAULT 'legacy_ambiguous';
ALTER TABLE trade_events ADD COLUMN seconds_delta_source VARCHAR;
"""


TEMPORAL_STATE_SCHEMA = r"""
CREATE TABLE temporal_runs (
    temporal_run_id UUID PRIMARY KEY,
    temporal_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    match_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    temporal_schema_version VARCHAR NOT NULL,
    temporal_rule_version VARCHAR NOT NULL,
    temporal_config_hash VARCHAR(64) NOT NULL,
    config JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (dataset_fingerprint, temporal_rule_version, temporal_config_hash)
);

CREATE TABLE round_timelines (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, start_tick BIGINT, freeze_end_tick BIGINT,
    live_start_tick BIGINT, end_tick BIGINT, official_end_tick BIGINT,
    effective_end_tick BIGINT, end_source VARCHAR, complete BOOLEAN NOT NULL,
    overtime BOOLEAN NOT NULL, final_bomb_state VARCHAR NOT NULL,
    availability JSON NOT NULL, ambiguity_flags JSON NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, round_id)
);

CREATE TABLE phase_intervals (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, interval_id UUID NOT NULL, phase VARCHAR NOT NULL,
    start_tick BIGINT NOT NULL, end_tick BIGINT, status VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, interval_id)
);

CREATE TABLE temporal_events (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, event_id UUID NOT NULL, tick BIGINT NOT NULL,
    seconds DOUBLE, conversion_status VARCHAR NOT NULL, kind VARCHAR NOT NULL,
    event_type VARCHAR NOT NULL, priority INTEGER NOT NULL,
    ordering_status VARCHAR NOT NULL, simultaneous_group_id UUID, payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, event_id)
);

CREATE TABLE temporal_transitions (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, transition_id UUID NOT NULL, tick BIGINT NOT NULL,
    transition_type VARCHAR NOT NULL, event_id UUID, status VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, transition_id)
);

CREATE TABLE participant_round_states (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, player_id UUID NOT NULL, physical_team_id UUID,
    side VARCHAR NOT NULL, participation_status VARCHAR NOT NULL,
    initial_alive_status VARCHAR NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, round_id, player_id)
);

CREATE TABLE life_transitions (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, transition_id UUID NOT NULL, event_id UUID NOT NULL,
    tick BIGINT NOT NULL, player_id UUID NOT NULL, before_status VARCHAR NOT NULL,
    after_status VARCHAR NOT NULL, death_classification VARCHAR NOT NULL,
    status VARCHAR NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, transition_id)
);

CREATE TABLE bomb_transitions (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, transition_id UUID NOT NULL, event_id UUID,
    tick BIGINT NOT NULL, before_state VARCHAR NOT NULL, after_state VARCHAR NOT NULL,
    status VARCHAR NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, transition_id)
);

CREATE TABLE temporal_validation_issues (
    temporal_run_id UUID NOT NULL, issue_index INTEGER NOT NULL, match_id UUID NOT NULL,
    round_id UUID, code VARCHAR NOT NULL, severity VARCHAR NOT NULL,
    is_fatal BOOLEAN NOT NULL, entity_type VARCHAR NOT NULL, entity_id VARCHAR,
    payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, issue_index)
);

CREATE INDEX idx_temporal_runs_match ON temporal_runs(match_id, created_at);
CREATE INDEX idx_round_timelines_match ON round_timelines(match_id, round_number);
CREATE INDEX idx_temporal_events_round ON temporal_events(match_id, round_number, tick);
CREATE INDEX idx_temporal_transitions_round
    ON temporal_transitions(match_id, round_number, tick);
CREATE INDEX idx_temporal_participants_round
    ON participant_round_states(match_id, round_number);
CREATE INDEX idx_temporal_bomb_round ON bomb_transitions(match_id, round_number, tick);
"""


TEMPORAL_SIMULTANEOUS_GROUPS_SCHEMA = r"""
ALTER TABLE temporal_events ADD COLUMN death_effect_status VARCHAR;

CREATE TABLE temporal_simultaneous_groups (
    temporal_run_id UUID NOT NULL, match_id UUID NOT NULL, round_id UUID NOT NULL,
    round_number INTEGER NOT NULL, group_id UUID NOT NULL, tick BIGINT NOT NULL,
    event_count INTEGER NOT NULL, ordering_status VARCHAR NOT NULL,
    intermediate_state_status VARCHAR NOT NULL, final_state_status VARCHAR NOT NULL,
    post_group_snapshot_deterministic BOOLEAN NOT NULL,
    ambiguity_reasons JSON NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (temporal_run_id, group_id)
);

CREATE INDEX idx_temporal_groups_match
    ON temporal_simultaneous_groups(match_id, round_number, tick);
"""


SPATIAL_FOUNDATION_SCHEMA = r"""
CREATE TABLE spatial_runs (
    spatial_run_id UUID PRIMARY KEY,
    spatial_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    match_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    temporal_run_id UUID NOT NULL,
    temporal_fingerprint VARCHAR(64) NOT NULL,
    source_demo_sha256 VARCHAR(64) NOT NULL,
    parser_name VARCHAR NOT NULL,
    parser_version VARCHAR NOT NULL,
    spatial_schema_version VARCHAR NOT NULL,
    spatial_rule_version VARCHAR NOT NULL,
    spatial_config_hash VARCHAR(64) NOT NULL,
    config JSON NOT NULL,
    map_model JSON NOT NULL,
    capabilities JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (dataset_fingerprint, temporal_fingerprint, spatial_rule_version,
            spatial_config_hash, source_demo_sha256)
);

CREATE TABLE spatial_snapshots (
    spatial_run_id UUID NOT NULL, snapshot_id UUID NOT NULL, match_id UUID NOT NULL,
    temporal_run_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL, participant_id UUID NOT NULL, x DOUBLE, y DOUBLE, z DOUBLE,
    yaw DOUBLE, pitch DOUBLE, alive BOOLEAN, has_bomb BOOLEAN, physical_team_id UUID,
    side VARCHAR NOT NULL, map_name VARCHAR NOT NULL, position_authority VARCHAR NOT NULL,
    availability JSON NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, snapshot_id),
    UNIQUE (spatial_run_id, round_id, tick, participant_id)
);

CREATE TABLE bomb_position_snapshots (
    spatial_run_id UUID NOT NULL, snapshot_id UUID NOT NULL, match_id UUID NOT NULL,
    temporal_run_id UUID NOT NULL, round_id UUID NOT NULL, round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL, x DOUBLE NOT NULL, y DOUBLE NOT NULL, z DOUBLE NOT NULL,
    carrier_participant_id UUID NOT NULL, position_authority VARCHAR NOT NULL,
    source VARCHAR NOT NULL, payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, snapshot_id)
);

CREATE TABLE spatial_validation_issues (
    spatial_run_id UUID NOT NULL, issue_index INTEGER NOT NULL, match_id UUID NOT NULL,
    code VARCHAR NOT NULL, severity VARCHAR NOT NULL, is_fatal BOOLEAN NOT NULL,
    entity_type VARCHAR NOT NULL, entity_id VARCHAR, payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, issue_index)
);

CREATE INDEX idx_spatial_runs_match ON spatial_runs(match_id, created_at);
CREATE INDEX idx_spatial_snapshots_round
    ON spatial_snapshots(match_id, round_number, tick, participant_id);
CREATE INDEX idx_spatial_bomb_round
    ON bomb_position_snapshots(match_id, round_number, tick);
CREATE INDEX idx_spatial_issues_match ON spatial_validation_issues(match_id, code);
"""


SPATIAL_QUERY_INDEXES_SCHEMA = r"""
CREATE INDEX idx_spatial_snapshots_tick_lookup
    ON spatial_snapshots(spatial_run_id, round_number, tick, participant_id);
CREATE INDEX idx_spatial_snapshots_player_path
    ON spatial_snapshots(spatial_run_id, round_number, participant_id, tick);
CREATE INDEX idx_spatial_snapshots_team_tick
    ON spatial_snapshots(spatial_run_id, round_number, physical_team_id, tick);
CREATE INDEX idx_spatial_bomb_tick_lookup
    ON bomb_position_snapshots(spatial_run_id, round_number, tick);
"""


SPATIAL_LOOKUP_KEYS_SCHEMA = r"""
DROP INDEX idx_spatial_snapshots_tick_lookup;
DROP INDEX idx_spatial_snapshots_player_path;
DROP INDEX idx_spatial_snapshots_team_tick;
DROP INDEX idx_spatial_bomb_tick_lookup;
DROP INDEX idx_spatial_snapshots_round;
DROP INDEX idx_spatial_bomb_round;

ALTER TABLE spatial_snapshots ADD COLUMN tick_lookup_key VARCHAR;
ALTER TABLE spatial_snapshots ADD COLUMN player_path_key VARCHAR;
ALTER TABLE bomb_position_snapshots ADD COLUMN tick_lookup_key VARCHAR;

UPDATE spatial_snapshots
SET tick_lookup_key = spatial_run_id::VARCHAR || ':' || round_number::VARCHAR
        || ':' || tick::VARCHAR,
    player_path_key = spatial_run_id::VARCHAR || ':' || round_number::VARCHAR
        || ':' || participant_id::VARCHAR;
UPDATE bomb_position_snapshots
SET tick_lookup_key = spatial_run_id::VARCHAR || ':' || round_number::VARCHAR
    || ':' || tick::VARCHAR;

"""


SPATIAL_LOOKUP_INDEXES_SCHEMA = r"""
CREATE TABLE spatial_snapshot_query_rows (
    spatial_run_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL,
    participant_id UUID NOT NULL,
    physical_team_id UUID,
    alive BOOLEAN,
    has_bomb BOOLEAN,
    x DOUBLE,
    position_authority VARCHAR NOT NULL,
    tick_lookup_key VARCHAR NOT NULL,
    player_path_key VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, snapshot_id)
);

CREATE TABLE bomb_position_query_rows (
    spatial_run_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL,
    tick_lookup_key VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, snapshot_id)
);

CREATE INDEX idx_spatial_snapshots_tick_lookup
    ON spatial_snapshot_query_rows(tick_lookup_key);
CREATE INDEX idx_spatial_snapshots_player_path
    ON spatial_snapshot_query_rows(player_path_key);
CREATE INDEX idx_spatial_bomb_tick_lookup
    ON bomb_position_query_rows(tick_lookup_key);
"""


SPATIAL_LOOKUP_BACKFILL_SCHEMA = r"""
INSERT INTO spatial_snapshot_query_rows
SELECT spatial_run_id, snapshot_id, round_number, tick, participant_id,
       physical_team_id, alive, has_bomb, x, position_authority,
       tick_lookup_key, player_path_key, payload
FROM spatial_snapshots;

INSERT INTO bomb_position_query_rows
SELECT spatial_run_id, snapshot_id, round_number, tick, tick_lookup_key, payload
FROM bomb_position_snapshots;
"""


SPATIAL_LOOKUP_MATCH_SCOPE_SCHEMA = r"""
ALTER TABLE spatial_snapshot_query_rows ADD COLUMN match_id UUID;
ALTER TABLE bomb_position_query_rows ADD COLUMN match_id UUID;

UPDATE spatial_snapshot_query_rows AS query
SET match_id = run.match_id
FROM spatial_runs AS run
WHERE query.spatial_run_id = run.spatial_run_id;

UPDATE bomb_position_query_rows AS query
SET match_id = run.match_id
FROM spatial_runs AS run
WHERE query.spatial_run_id = run.spatial_run_id;
"""


MAP_SEMANTICS_PIN_SCHEMA = r"""
ALTER TABLE spatial_runs ADD COLUMN canonical_map_name VARCHAR;
ALTER TABLE spatial_runs ADD COLUMN selected_map_revision VARCHAR;
ALTER TABLE spatial_runs ADD COLUMN map_definition_version VARCHAR;
ALTER TABLE spatial_runs ADD COLUMN overview_checksum VARCHAR(64);
ALTER TABLE spatial_runs ADD COLUMN transform_rule_version VARCHAR;
ALTER TABLE spatial_runs ADD COLUMN map_definition_fingerprint VARCHAR(64);
ALTER TABLE spatial_runs ADD COLUMN map_semantics JSON;

CREATE INDEX idx_spatial_runs_map_revision
    ON spatial_runs(canonical_map_name, selected_map_revision, created_at);
"""


SPATIAL_PROJECTILE_SCHEMA = r"""
ALTER TABLE spatial_runs ADD COLUMN projectile_metadata JSON;
ALTER TABLE spatial_runs ADD COLUMN projectile_capabilities JSON;

CREATE TABLE spatial_projectiles (
    spatial_run_id UUID NOT NULL,
    projectile_id UUID NOT NULL,
    match_id UUID NOT NULL,
    temporal_run_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    first_position_tick BIGINT NOT NULL,
    terminal_tick BIGINT NOT NULL,
    projectile_type VARCHAR NOT NULL,
    owner_participant_id UUID,
    payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, projectile_id)
);

CREATE TABLE spatial_projectile_snapshots (
    spatial_run_id UUID NOT NULL,
    snapshot_id UUID NOT NULL,
    projectile_id UUID NOT NULL,
    match_id UUID NOT NULL,
    temporal_run_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL,
    lifecycle VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, snapshot_id)
);

CREATE TABLE spatial_utility_effects (
    spatial_run_id UUID NOT NULL,
    effect_id UUID NOT NULL,
    projectile_id UUID,
    match_id UUID NOT NULL,
    temporal_run_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    start_tick BIGINT NOT NULL,
    end_tick BIGINT,
    effect_type VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (spatial_run_id, effect_id)
);

CREATE INDEX idx_spatial_projectiles_round
    ON spatial_projectiles(spatial_run_id, round_number, first_position_tick);
CREATE INDEX idx_spatial_projectile_snapshots_tick
    ON spatial_projectile_snapshots(spatial_run_id, round_number, tick, projectile_id);
CREATE INDEX idx_spatial_utility_effects_tick
    ON spatial_utility_effects(spatial_run_id, round_number, start_tick, end_tick);
"""

IMPORT_JOB_SCHEMA = r"""
CREATE TABLE import_jobs (
    job_id UUID PRIMARY KEY,
    stage VARCHAR NOT NULL,
    original_name VARCHAR NOT NULL,
    internal_name VARCHAR NOT NULL,
    match_id UUID,
    message VARCHAR NOT NULL,
    error_code VARCHAR,
    attempt_count INTEGER NOT NULL CHECK (attempt_count >= 1),
    recoverable BOOLEAN NOT NULL,
    progress_percent INTEGER NOT NULL
        CHECK (progress_percent >= 0 AND progress_percent <= 100),
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_import_jobs_stage_updated
    ON import_jobs(stage, updated_at);
"""

OPPONENT_WORKSPACE_SCHEMA = r"""
CREATE TABLE opponent_profiles (
    profile_id UUID PRIMARY KEY,
    display_name VARCHAR NOT NULL UNIQUE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE opponent_match_selections (
    profile_id UUID NOT NULL,
    match_id UUID NOT NULL,
    team_id UUID NOT NULL,
    selection_source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (profile_id, match_id)
);

CREATE INDEX idx_opponent_selections_match
    ON opponent_match_selections(match_id, profile_id);
"""


ZONE_ASSIGNMENT_SCHEMA = r"""
CREATE TABLE zone_assignment_runs (
    zone_assignment_run_id UUID PRIMARY KEY,
    zone_assignment_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    zone_assignment_schema_version VARCHAR NOT NULL,
    zone_assignment_rule_version VARCHAR NOT NULL,
    zone_assignment_config_hash VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    spatial_run_id UUID NOT NULL,
    spatial_fingerprint VARCHAR(64) NOT NULL,
    spatial_schema_version VARCHAR NOT NULL,
    spatial_rule_version VARCHAR NOT NULL,
    canonical_map_name VARCHAR,
    selected_map_revision VARCHAR,
    map_definition_fingerprint VARCHAR(64),
    map_revision_selection_status VARCHAR,
    zone_set_fingerprint VARCHAR(64),
    zone_set_key VARCHAR NOT NULL,
    zone_schema_version VARCHAR,
    zone_resolution_rule_version VARCHAR,
    zone_validation_rule_version VARCHAR,
    config JSON NOT NULL,
    capability JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (
        spatial_fingerprint,
        zone_assignment_rule_version,
        zone_set_key,
        zone_assignment_config_hash
    )
);

CREATE TABLE zone_assignments (
    zone_assignment_run_id UUID NOT NULL,
    assignment_id UUID NOT NULL,
    spatial_run_id UUID NOT NULL,
    spatial_snapshot_id UUID NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT NOT NULL,
    participant_id UUID NOT NULL,
    status VARCHAR NOT NULL,
    zone_id VARCHAR,
    zone_name VARCHAR,
    zone_kind VARCHAR,
    map_level VARCHAR,
    warnings JSON NOT NULL,
    PRIMARY KEY (zone_assignment_run_id, spatial_snapshot_id),
    UNIQUE (zone_assignment_run_id, assignment_id)
);

CREATE INDEX idx_zone_assignment_runs_match
    ON zone_assignment_runs(match_id, created_at);
CREATE INDEX idx_zone_assignment_runs_spatial
    ON zone_assignment_runs(spatial_run_id, created_at);
CREATE INDEX idx_zone_assignments_snapshot
    ON zone_assignments(zone_assignment_run_id, spatial_snapshot_id);
CREATE INDEX idx_zone_assignments_round_status
    ON zone_assignments(zone_assignment_run_id, round_number, status, tick);
CREATE INDEX idx_zone_assignments_match
    ON zone_assignments(match_id, round_number, tick);
"""


ECONOMY_CONTEXT_SCHEMA = r"""
CREATE TABLE economy_runs (
    economy_run_id UUID PRIMARY KEY,
    economy_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    economy_schema_version VARCHAR NOT NULL,
    economy_rule_version VARCHAR NOT NULL,
    item_category_version VARCHAR NOT NULL,
    value_policy_version VARCHAR NOT NULL,
    economy_config_hash VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    source_demo_sha256 VARCHAR(64) NOT NULL,
    parser_name VARCHAR NOT NULL,
    parser_version VARCHAR NOT NULL,
    config JSON NOT NULL,
    capability JSON NOT NULL,
    summary JSON NOT NULL,
    source_columns JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (
        dataset_fingerprint,
        source_demo_sha256,
        parser_name,
        parser_version,
        economy_rule_version,
        economy_config_hash
    )
);

CREATE TABLE player_equipment_snapshots (
    economy_run_id UUID NOT NULL,
    player_snapshot_id UUID NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    freeze_end_tick BIGINT,
    participant_id UUID NOT NULL,
    steam_id VARCHAR,
    team_id UUID,
    side VARCHAR NOT NULL,
    eligible BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (economy_run_id, player_snapshot_id)
);

CREATE TABLE team_economy_snapshots (
    economy_run_id UUID NOT NULL,
    team_snapshot_id UUID NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    freeze_end_tick BIGINT,
    team_id UUID,
    side VARCHAR NOT NULL,
    buy_type VARCHAR NOT NULL,
    classification_availability VARCHAR NOT NULL,
    eligible BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (economy_run_id, team_snapshot_id)
);

CREATE INDEX idx_economy_runs_match
    ON economy_runs(match_id, created_at);
CREATE INDEX idx_player_equipment_round
    ON player_equipment_snapshots(economy_run_id, round_number, side);
CREATE INDEX idx_player_equipment_participant
    ON player_equipment_snapshots(economy_run_id, participant_id, round_number);
CREATE INDEX idx_team_economy_filter
    ON team_economy_snapshots(economy_run_id, buy_type, side, round_number);
CREATE INDEX idx_team_economy_match
    ON team_economy_snapshots(match_id, round_number, side);
"""


ROUND_FEATURE_SCHEMA = r"""
CREATE TABLE round_feature_runs (
    feature_run_id UUID PRIMARY KEY,
    feature_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    feature_schema_version VARCHAR NOT NULL,
    feature_rule_version VARCHAR NOT NULL,
    feature_config_hash VARCHAR(64) NOT NULL,
    match_id UUID NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    analytics_fingerprint VARCHAR(64) NOT NULL,
    analytics_rule_version VARCHAR NOT NULL,
    temporal_run_id UUID NOT NULL,
    temporal_fingerprint VARCHAR(64) NOT NULL,
    temporal_rule_version VARCHAR NOT NULL,
    spatial_run_id UUID NOT NULL,
    spatial_fingerprint VARCHAR(64) NOT NULL,
    spatial_rule_version VARCHAR NOT NULL,
    zone_assignment_run_id UUID NOT NULL,
    zone_assignment_fingerprint VARCHAR(64) NOT NULL,
    zone_assignment_rule_version VARCHAR NOT NULL,
    economy_run_id UUID,
    economy_fingerprint VARCHAR(64),
    economy_rule_version VARCHAR,
    config JSON NOT NULL,
    capabilities JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (
        dataset_fingerprint,
        analytics_fingerprint,
        temporal_fingerprint,
        spatial_fingerprint,
        zone_assignment_fingerprint,
        economy_fingerprint,
        feature_rule_version,
        feature_config_hash
    )
);

CREATE TABLE round_features (
    feature_run_id UUID NOT NULL,
    feature_id UUID NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    team_id UUID NOT NULL,
    side VARCHAR NOT NULL,
    feature_type VARCHAR NOT NULL,
    availability VARCHAR NOT NULL,
    tick_start BIGINT,
    tick_end BIGINT,
    zone_id VARCHAR,
    zone_name VARCHAR,
    buy_type VARCHAR,
    payload JSON NOT NULL,
    PRIMARY KEY (feature_run_id, feature_id)
);

CREATE INDEX idx_round_feature_runs_match
    ON round_feature_runs(match_id, created_at);
CREATE INDEX idx_round_features_round
    ON round_features(feature_run_id, round_number, side);
CREATE INDEX idx_round_features_type
    ON round_features(feature_run_id, feature_type, availability, side);
CREATE INDEX idx_round_features_zone
    ON round_features(feature_run_id, zone_id, feature_type);
CREATE INDEX idx_round_features_buy
    ON round_features(feature_run_id, buy_type, side, feature_type);
"""


CROSS_MATCH_PATTERN_SCHEMA = r"""
CREATE TABLE cross_match_pattern_runs (
    pattern_run_id UUID PRIMARY KEY,
    pattern_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    pattern_schema_version VARCHAR NOT NULL,
    pattern_rule_version VARCHAR NOT NULL,
    confidence_method VARCHAR NOT NULL,
    pattern_config_hash VARCHAR(64) NOT NULL,
    workspace_fingerprint VARCHAR(64) NOT NULL,
    profile_id UUID NOT NULL,
    config JSON NOT NULL,
    capabilities JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE pattern_run_inputs (
    pattern_run_id UUID NOT NULL,
    match_id UUID NOT NULL,
    team_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    input_status VARCHAR NOT NULL,
    exclusion_reason VARCHAR,
    feature_run_id UUID,
    feature_fingerprint VARCHAR(64),
    feature_rule_version VARCHAR,
    payload JSON NOT NULL,
    PRIMARY KEY (pattern_run_id, match_id)
);

CREATE TABLE cross_match_patterns (
    pattern_run_id UUID NOT NULL,
    pattern_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    buy_type VARCHAR,
    feature_rule_version VARCHAR NOT NULL,
    pattern_type VARCHAR NOT NULL,
    pattern_key VARCHAR NOT NULL,
    availability VARCHAR NOT NULL,
    numerator INTEGER NOT NULL,
    denominator INTEGER NOT NULL,
    frequency DOUBLE NOT NULL,
    confidence_lower DOUBLE NOT NULL,
    confidence_upper DOUBLE NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (pattern_run_id, pattern_id)
);

CREATE TABLE pattern_round_evidence (
    pattern_run_id UUID NOT NULL,
    pattern_id UUID NOT NULL,
    evidence_index INTEGER NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT,
    contributed_to_numerator BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (pattern_run_id, pattern_id, evidence_index)
);

CREATE TABLE pattern_round_exclusions (
    pattern_run_id UUID NOT NULL,
    pattern_id UUID NOT NULL,
    exclusion_index INTEGER NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    reason VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (pattern_run_id, pattern_id, exclusion_index)
);

CREATE INDEX idx_pattern_runs_profile
    ON cross_match_pattern_runs(profile_id, created_at);
CREATE INDEX idx_pattern_inputs_match
    ON pattern_run_inputs(match_id, feature_run_id);
CREATE INDEX idx_patterns_scope
    ON cross_match_patterns(pattern_run_id, map_name, side, buy_type, pattern_type);
CREATE INDEX idx_pattern_evidence_round
    ON pattern_round_evidence(match_id, round_number, tick);
"""


ANALYSIS_FINDING_SCHEMA = r"""
CREATE TABLE analysis_runs (
    analysis_run_id UUID PRIMARY KEY,
    analysis_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    analysis_schema_version VARCHAR NOT NULL,
    analysis_rule_version VARCHAR NOT NULL,
    configuration_hash VARCHAR(64) NOT NULL,
    profile_id UUID NOT NULL,
    workspace_fingerprint VARCHAR(64) NOT NULL,
    source_pattern_run_id UUID NOT NULL,
    source_pattern_fingerprint VARCHAR(64) NOT NULL,
    source_pattern_schema_version VARCHAR NOT NULL,
    source_pattern_rule_version VARCHAR NOT NULL,
    config JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE analysis_run_inputs (
    analysis_run_id UUID NOT NULL,
    match_id UUID NOT NULL,
    team_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    input_status VARCHAR NOT NULL,
    exclusion_reason VARCHAR,
    demo_file_id UUID,
    source_demo_sha256 VARCHAR(64),
    dataset_fingerprint VARCHAR(64),
    feature_run_id UUID,
    feature_fingerprint VARCHAR(64),
    payload JSON NOT NULL,
    PRIMARY KEY (analysis_run_id, match_id)
);

CREATE TABLE analysis_findings (
    analysis_run_id UUID NOT NULL,
    finding_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    source_pattern_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    buy_type VARCHAR,
    category VARCHAR NOT NULL,
    pattern_type VARCHAR NOT NULL,
    source_availability VARCHAR NOT NULL,
    numerator INTEGER NOT NULL,
    denominator INTEGER NOT NULL,
    frequency DOUBLE NOT NULL,
    confidence_score DOUBLE NOT NULL,
    small_sample_warning BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (analysis_run_id, finding_id)
);

CREATE TABLE finding_evidence_references (
    analysis_run_id UUID NOT NULL,
    finding_id UUID NOT NULL,
    evidence_id UUID NOT NULL,
    evidence_index INTEGER NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT,
    contributed_to_numerator BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (analysis_run_id, finding_id, evidence_id)
);

CREATE INDEX idx_analysis_runs_profile
    ON analysis_runs(profile_id, created_at);
CREATE INDEX idx_analysis_runs_pattern
    ON analysis_runs(source_pattern_run_id);
CREATE INDEX idx_analysis_findings_scope
    ON analysis_findings(analysis_run_id, map_name, side, buy_type, category, pattern_type);
CREATE INDEX idx_finding_evidence_round
    ON finding_evidence_references(match_id, round_number, tick);
"""


COUNTER_STRATEGY_SCHEMA = """
CREATE TABLE counter_strategy_runs (
    strategy_run_id UUID PRIMARY KEY,
    strategy_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    strategy_schema_version VARCHAR NOT NULL,
    strategy_rule_version VARCHAR NOT NULL,
    configuration_hash VARCHAR(64) NOT NULL,
    profile_id UUID NOT NULL,
    source_analysis_run_id UUID NOT NULL,
    source_analysis_fingerprint VARCHAR(64) NOT NULL,
    source_analysis_schema_version VARCHAR NOT NULL,
    source_analysis_rule_version VARCHAR NOT NULL,
    readiness_audit_id UUID NOT NULL,
    readiness_fingerprint VARCHAR(64) NOT NULL,
    readiness_schema_version VARCHAR NOT NULL,
    readiness_rule_version VARCHAR NOT NULL,
    readiness_config JSON NOT NULL,
    config JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE counter_strategy_recommendations (
    strategy_run_id UUID NOT NULL,
    recommendation_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    source_finding_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    buy_type VARCHAR,
    category VARCHAR NOT NULL,
    pattern_type VARCHAR NOT NULL,
    rule_id VARCHAR NOT NULL,
    numerator INTEGER NOT NULL,
    denominator INTEGER NOT NULL,
    frequency DOUBLE NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (strategy_run_id, recommendation_id)
);

CREATE TABLE counter_strategy_skipped_findings (
    strategy_run_id UUID NOT NULL,
    finding_id UUID NOT NULL,
    reason VARCHAR NOT NULL,
    readiness_status VARCHAR NOT NULL,
    pattern_type VARCHAR NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (strategy_run_id, finding_id)
);

CREATE TABLE counter_strategy_evidence (
    strategy_run_id UUID NOT NULL,
    recommendation_id UUID NOT NULL,
    evidence_id UUID NOT NULL,
    evidence_index INTEGER NOT NULL,
    source_finding_id UUID NOT NULL,
    match_id UUID NOT NULL,
    round_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick BIGINT,
    payload JSON NOT NULL,
    PRIMARY KEY (strategy_run_id, recommendation_id, evidence_id)
);

CREATE INDEX idx_counter_strategy_profile
    ON counter_strategy_runs(profile_id, created_at);
CREATE INDEX idx_counter_strategy_analysis
    ON counter_strategy_runs(source_analysis_run_id);
CREATE INDEX idx_counter_strategy_scope
    ON counter_strategy_recommendations(strategy_run_id, map_name, side, buy_type, category);
CREATE INDEX idx_counter_strategy_evidence_round
    ON counter_strategy_evidence(match_id, round_number, tick);
"""


TEAM_DISPLAY_LABEL_SCHEMA = """
CREATE TABLE team_display_labels (
    match_id UUID NOT NULL,
    team_id UUID NOT NULL,
    display_name VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    source_reference VARCHAR,
    updated_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (match_id, team_id)
);

CREATE INDEX idx_team_display_labels_match
    ON team_display_labels(match_id, updated_at);
"""


IMPORT_WORKER_V2_SCHEMA = r"""
ALTER TABLE import_jobs ADD COLUMN demo_sha256 VARCHAR;
ALTER TABLE import_jobs ADD COLUMN file_size_bytes BIGINT;
ALTER TABLE import_jobs ADD COLUMN last_completed_stage VARCHAR;
ALTER TABLE import_jobs ADD COLUMN worker_version VARCHAR;
ALTER TABLE import_jobs ADD COLUMN worker_pid BIGINT;
ALTER TABLE import_jobs ADD COLUMN peak_worker_memory_bytes BIGINT;
ALTER TABLE import_jobs ADD COLUMN cancel_requested_at TIMESTAMP;
ALTER TABLE import_jobs ADD COLUMN completed_at TIMESTAMP;

CREATE INDEX idx_import_jobs_demo_sha256
    ON import_jobs(demo_sha256, updated_at);
"""


STATISTICAL_TRUST_SCHEMA = r"""
CREATE TABLE statistical_trust_runs (
    trust_run_id UUID PRIMARY KEY,
    trust_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    trust_schema_version VARCHAR NOT NULL,
    trust_rule_version VARCHAR NOT NULL,
    configuration_hash VARCHAR(64) NOT NULL,
    profile_id UUID NOT NULL,
    source_pattern_run_id UUID NOT NULL,
    source_pattern_fingerprint VARCHAR(64) NOT NULL,
    source_pattern_schema_version VARCHAR NOT NULL,
    source_pattern_rule_version VARCHAR NOT NULL,
    config JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE statistical_trust_assessments (
    trust_run_id UUID NOT NULL,
    assessment_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    source_pattern_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    buy_type VARCHAR,
    pattern_type VARCHAR NOT NULL,
    decision VARCHAR NOT NULL,
    reliability_rank INTEGER,
    reliability_score DOUBLE,
    denominator_match_count INTEGER NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (trust_run_id, assessment_id)
);

CREATE INDEX idx_statistical_trust_runs_profile
    ON statistical_trust_runs(profile_id, created_at);
CREATE INDEX idx_statistical_trust_assessments_rank
    ON statistical_trust_assessments(trust_run_id, decision, reliability_rank);
CREATE INDEX idx_statistical_trust_assessments_pattern
    ON statistical_trust_assessments(source_pattern_id, trust_run_id);
"""


TACTICAL_INTELLIGENCE_V2_SCHEMA = r"""
CREATE TABLE tactical_v2_runs (
    tactical_run_id UUID PRIMARY KEY,
    tactical_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    tactical_schema_version VARCHAR NOT NULL,
    tactical_rule_version VARCHAR NOT NULL,
    configuration_hash VARCHAR(64) NOT NULL,
    profile_id UUID NOT NULL,
    config JSON NOT NULL,
    capabilities JSON NOT NULL,
    summary JSON NOT NULL,
    row_counts JSON NOT NULL,
    warnings JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (profile_id, tactical_rule_version, configuration_hash, tactical_fingerprint)
);

CREATE TABLE tactical_v2_run_inputs (
    tactical_run_id UUID NOT NULL,
    match_id UUID NOT NULL,
    team_id UUID NOT NULL,
    map_name VARCHAR NOT NULL,
    dataset_fingerprint VARCHAR(64) NOT NULL,
    analytics_fingerprint VARCHAR(64) NOT NULL,
    temporal_run_id UUID NOT NULL,
    spatial_run_id UUID NOT NULL,
    zone_assignment_run_id UUID NOT NULL,
    feature_run_id UUID,
    payload JSON NOT NULL,
    PRIMARY KEY (tactical_run_id, match_id)
);

CREATE TABLE tactical_v2_insights (
    tactical_run_id UUID NOT NULL,
    insight_id UUID NOT NULL,
    profile_id UUID NOT NULL,
    insight_type VARCHAR NOT NULL,
    map_name VARCHAR NOT NULL,
    side VARCHAR NOT NULL,
    insight_key VARCHAR NOT NULL,
    availability VARCHAR NOT NULL,
    numerator BIGINT NOT NULL,
    denominator BIGINT NOT NULL,
    frequency DOUBLE NOT NULL,
    match_count INTEGER NOT NULL,
    small_sample_warning BOOLEAN NOT NULL,
    payload JSON NOT NULL,
    PRIMARY KEY (tactical_run_id, insight_id),
    UNIQUE (tactical_run_id, insight_type, map_name, side, insight_key)
);

CREATE TABLE tactical_v2_evidence (
    tactical_run_id UUID NOT NULL,
    insight_id UUID NOT NULL,
    evidence_index INTEGER NOT NULL,
    match_id UUID NOT NULL,
    round_number INTEGER NOT NULL,
    tick_start BIGINT,
    tick_end BIGINT,
    payload JSON NOT NULL,
    PRIMARY KEY (tactical_run_id, insight_id, evidence_index)
);

CREATE INDEX idx_tactical_v2_runs_profile
    ON tactical_v2_runs(profile_id, created_at);
CREATE INDEX idx_tactical_v2_inputs_match
    ON tactical_v2_run_inputs(match_id, tactical_run_id);
CREATE INDEX idx_tactical_v2_insights_scope
    ON tactical_v2_insights(tactical_run_id, insight_type, map_name, side, frequency);
CREATE INDEX idx_tactical_v2_evidence_round
    ON tactical_v2_evidence(match_id, round_number, tick_start);
"""


ANALYST_NOTES_SCHEMA = r"""
CREATE TABLE analyst_notes (
    note_id UUID PRIMARY KEY,
    profile_id UUID NOT NULL,
    tactical_run_id UUID NOT NULL,
    insight_id UUID NOT NULL,
    body VARCHAR NOT NULL,
    note_schema_version VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE (tactical_run_id, insight_id)
);

CREATE INDEX idx_analyst_notes_profile
    ON analyst_notes(profile_id, updated_at);
"""


BULK_IMPORT_SCHEMA = r"""
CREATE TABLE import_batches (
    batch_id UUID PRIMARY KEY,
    display_name VARCHAR NOT NULL,
    opponent_profile_id UUID NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE import_batch_items (
    batch_id UUID NOT NULL,
    item_index INTEGER NOT NULL CHECK (item_index >= 0),
    original_name VARCHAR NOT NULL,
    disposition VARCHAR NOT NULL,
    job_id UUID,
    existing_match_id UUID,
    error_code VARCHAR,
    message VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (batch_id, item_index)
);

CREATE INDEX idx_import_batches_opponent
    ON import_batches(opponent_profile_id, created_at);
CREATE INDEX idx_import_batch_items_job
    ON import_batch_items(job_id, batch_id);
"""


UTILITY_ROI_EVIDENCE_SCHEMA = r"""
ALTER TABLE kills ADD COLUMN game_time DOUBLE;
ALTER TABLE damages ADD COLUMN game_time DOUBLE;
ALTER TABLE shots ADD COLUMN game_time DOUBLE;
ALTER TABLE grenades ADD COLUMN game_time DOUBLE;
ALTER TABLE grenades ADD COLUMN round_start_time DOUBLE;
ALTER TABLE bomb_events ADD COLUMN game_time DOUBLE;

CREATE TABLE blinds (
    match_id UUID NOT NULL,
    event_id UUID NOT NULL,
    round_id UUID,
    round_number INTEGER,
    tick BIGINT NOT NULL CHECK (tick >= 0),
    relative_tick BIGINT CHECK (relative_tick >= 0),
    phase VARCHAR NOT NULL,
    source_event VARCHAR NOT NULL,
    game_time DOUBLE,
    warnings JSON NOT NULL,
    attacker_player_id UUID,
    victim_player_id UUID,
    attacker_team_id UUID,
    victim_team_id UUID,
    attacker_side VARCHAR NOT NULL,
    victim_side VARCHAR NOT NULL,
    duration_seconds DOUBLE CHECK (duration_seconds >= 0),
    entity_id BIGINT CHECK (entity_id >= 0),
    PRIMARY KEY (match_id, event_id)
);

CREATE INDEX idx_blinds_match_round_tick
    ON blinds(match_id, round_number, tick);
CREATE INDEX idx_blinds_match_attacker
    ON blinds(match_id, attacker_player_id, tick);
"""


HEAD_TO_HEAD_SCHEMA = r"""
CREATE TABLE head_to_head_runs (
    head_to_head_run_id UUID PRIMARY KEY,
    head_to_head_fingerprint VARCHAR NOT NULL UNIQUE,
    head_to_head_schema_version VARCHAR NOT NULL,
    head_to_head_rule_version VARCHAR NOT NULL,
    opponent_profile_id UUID NOT NULL,
    our_profile_id UUID NOT NULL,
    opponent_tactical_run_id UUID NOT NULL,
    our_tactical_run_id UUID NOT NULL,
    payload JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    CHECK (opponent_profile_id <> our_profile_id)
);

CREATE INDEX idx_head_to_head_profiles
    ON head_to_head_runs(opponent_profile_id, our_profile_id, created_at);
CREATE INDEX idx_head_to_head_sources
    ON head_to_head_runs(opponent_tactical_run_id, our_tactical_run_id);
"""


CRITICAL_MISTAKES_SCHEMA = r"""
CREATE TABLE critical_mistake_runs (
    critical_run_id UUID PRIMARY KEY,
    critical_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    critical_schema_version VARCHAR NOT NULL,
    critical_rule_version VARCHAR NOT NULL,
    profile_id UUID NOT NULL,
    payload JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE INDEX idx_critical_mistake_runs_profile
    ON critical_mistake_runs(profile_id, created_at);
"""


TELESTRATOR_SCHEMA = r"""
CREATE TABLE telestrator_boards (
    board_id UUID PRIMARY KEY,
    match_id UUID NOT NULL,
    round_number INTEGER NOT NULL CHECK (round_number >= 1),
    schema_version VARCHAR NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    payload JSON NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE (match_id, round_number)
);

CREATE INDEX idx_telestrator_boards_round
    ON telestrator_boards(match_id, round_number);
"""


AI_BRIEFING_SCHEMA = r"""
CREATE TABLE ai_briefings (
    briefing_id UUID PRIMARY KEY,
    briefing_fingerprint VARCHAR(64) NOT NULL UNIQUE,
    briefing_schema_version VARCHAR NOT NULL,
    briefing_rule_version VARCHAR NOT NULL,
    prompt_version VARCHAR NOT NULL,
    profile_id UUID NOT NULL,
    strategy_run_id UUID NOT NULL,
    source_fingerprint VARCHAR(64) NOT NULL,
    provider VARCHAR NOT NULL,
    model_name VARCHAR NOT NULL,
    model_digest VARCHAR(64) NOT NULL,
    payload JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE INDEX idx_ai_briefings_source
    ON ai_briefings(profile_id, strategy_run_id, created_at);
CREATE INDEX idx_ai_briefings_compatibility
    ON ai_briefings(source_fingerprint, model_name, model_digest, prompt_version);
"""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(version=1, name="canonical_match_schema", sql=INITIAL_SCHEMA),
    Migration(version=2, name="round_result_availability", sql=RESULT_AVAILABILITY_SCHEMA),
    Migration(version=3, name="gameplay_analytics_v1", sql=ANALYTICS_SCHEMA),
    Migration(
        version=4,
        name="trade_window_semantics",
        sql=TRADE_WINDOW_SEMANTICS_SCHEMA,
    ),
    Migration(version=5, name="temporal_round_state", sql=TEMPORAL_STATE_SCHEMA),
    Migration(
        version=6,
        name="temporal_simultaneous_groups",
        sql=TEMPORAL_SIMULTANEOUS_GROUPS_SCHEMA,
    ),
    Migration(version=7, name="spatial_engine_foundation", sql=SPATIAL_FOUNDATION_SCHEMA),
    Migration(version=8, name="spatial_query_indexes", sql=SPATIAL_QUERY_INDEXES_SCHEMA),
    Migration(version=9, name="spatial_lookup_keys", sql=SPATIAL_LOOKUP_KEYS_SCHEMA),
    Migration(
        version=10,
        name="spatial_lookup_key_indexes",
        sql=SPATIAL_LOOKUP_INDEXES_SCHEMA,
    ),
    Migration(
        version=11,
        name="spatial_lookup_backfill",
        sql=SPATIAL_LOOKUP_BACKFILL_SCHEMA,
    ),
    Migration(
        version=12,
        name="spatial_lookup_match_scope",
        sql=SPATIAL_LOOKUP_MATCH_SCOPE_SCHEMA,
    ),
    Migration(version=13, name="map_semantics_pin", sql=MAP_SEMANTICS_PIN_SCHEMA),
    Migration(version=14, name="spatial_projectile_layer", sql=SPATIAL_PROJECTILE_SCHEMA),
    Migration(version=15, name="durable_import_jobs", sql=IMPORT_JOB_SCHEMA),
    Migration(version=16, name="opponent_workspaces", sql=OPPONENT_WORKSPACE_SCHEMA),
    Migration(version=17, name="versioned_zone_assignments", sql=ZONE_ASSIGNMENT_SCHEMA),
    Migration(version=18, name="economy_and_equipment_context", sql=ECONOMY_CONTEXT_SCHEMA),
    Migration(version=19, name="per_round_tactical_features", sql=ROUND_FEATURE_SCHEMA),
    Migration(version=20, name="cross_match_pattern_engine", sql=CROSS_MATCH_PATTERN_SCHEMA),
    Migration(version=21, name="analysis_findings", sql=ANALYSIS_FINDING_SCHEMA),
    Migration(version=22, name="counter_strategy_rules", sql=COUNTER_STRATEGY_SCHEMA),
    Migration(version=23, name="team_display_labels", sql=TEAM_DISPLAY_LABEL_SCHEMA),
    Migration(version=24, name="import_worker_v2", sql=IMPORT_WORKER_V2_SCHEMA),
    Migration(version=25, name="statistical_trust", sql=STATISTICAL_TRUST_SCHEMA),
    Migration(
        version=26,
        name="tactical_intelligence_v2",
        sql=TACTICAL_INTELLIGENCE_V2_SCHEMA,
    ),
    Migration(version=27, name="local_analyst_notes", sql=ANALYST_NOTES_SCHEMA),
    Migration(version=28, name="bulk_training_pool_imports", sql=BULK_IMPORT_SCHEMA),
    Migration(version=29, name="utility_roi_evidence", sql=UTILITY_ROI_EVIDENCE_SCHEMA),
    Migration(version=30, name="head_to_head_comparisons", sql=HEAD_TO_HEAD_SCHEMA),
    Migration(version=31, name="critical_mistake_filters", sql=CRITICAL_MISTAKES_SCHEMA),
    Migration(version=32, name="interactive_2d_telestrator", sql=TELESTRATOR_SCHEMA),
    Migration(version=33, name="optional_local_ai_briefings", sql=AI_BRIEFING_SCHEMA),
)
