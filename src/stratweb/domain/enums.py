"""Small, stable vocabularies used by the canonical domain schema."""

from enum import StrEnum


class Side(StrEnum):
    T = "T"
    CT = "CT"
    UNKNOWN = "UNKNOWN"


class FindingSide(StrEnum):
    T = "T"
    CT = "CT"
    BOTH = "BOTH"


class DemoStatus(StrEnum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class GrenadeAction(StrEnum):
    THROWN = "thrown"
    BOUNCED = "bounced"
    DETONATED = "detonated"
    EXPIRED = "expired"


class BombAction(StrEnum):
    PICKUP = "pickup"
    DROP = "drop"
    PLANT_START = "plant_start"
    PLANT_ABORT = "plant_abort"
    PLANTED = "planted"
    DEFUSE_START = "defuse_start"
    DEFUSE_ABORT = "defuse_abort"
    DEFUSED = "defused"
    EXPLODED = "exploded"


class CanonicalTable(StrEnum):
    DEMO_FILES = "demo_files"
    MATCHES = "matches"
    TEAMS = "teams"
    PLAYERS = "players"
    ROUNDS = "rounds"
    PLAYER_ROUNDS = "player_rounds"
    KILLS = "kills"
    DAMAGES = "damages"
    SHOTS = "shots"
    GRENADES = "grenades"
    SMOKES = "smokes"
    INFERNOS = "infernos"
    BOMB_EVENTS = "bomb_events"
    POSITION_SAMPLES = "position_samples"
    ANALYSIS_RUNS = "analysis_runs"
    ANALYSIS_FINDINGS = "analysis_findings"
    EVIDENCE_REFERENCES = "evidence_references"
