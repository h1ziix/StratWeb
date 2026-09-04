"""Immutable DuckDB persistence for validated local-AI briefing artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import duckdb

from stratweb.adapters.persistence._connections import read_connection
from stratweb.adapters.persistence.duckdb import DuckDBMatchRepository
from stratweb.ai_briefing.models import (
    AI_BRIEFING_PROMPT_VERSION,
    AI_BRIEFING_RULE_VERSION,
    AI_BRIEFING_SCHEMA_VERSION,
    AiBriefingArtifact,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import PersistenceError


class DuckDBAiBriefingRepository:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path).expanduser().resolve()

    def initialize(self) -> tuple[int, ...]:
        return DuckDBMatchRepository(self._database_path).initialize()

    def get_compatible(
        self,
        profile_id: UUID,
        strategy_run_id: UUID,
        *,
        source_fingerprint: str,
        model_name: str,
        model_digest: str,
    ) -> AiBriefingArtifact | None:
        self.initialize()
        with read_connection(self._database_path, "AI briefing") as connection:
            row = connection.execute(
                """SELECT payload FROM ai_briefings
                   WHERE profile_id=? AND strategy_run_id=?
                     AND source_fingerprint=? AND model_name=? AND model_digest=?
                     AND briefing_schema_version=? AND briefing_rule_version=?
                     AND prompt_version=?
                   ORDER BY created_at DESC, briefing_fingerprint DESC LIMIT 1""",
                [
                    profile_id,
                    strategy_run_id,
                    source_fingerprint,
                    model_name,
                    model_digest,
                    AI_BRIEFING_SCHEMA_VERSION,
                    AI_BRIEFING_RULE_VERSION,
                    AI_BRIEFING_PROMPT_VERSION,
                ],
            ).fetchone()
        return AiBriefingArtifact.model_validate(_json(row[0])) if row else None

    def get_latest(
        self,
        profile_id: UUID,
        strategy_run_id: UUID,
    ) -> AiBriefingArtifact | None:
        self.initialize()
        with read_connection(self._database_path, "AI briefing") as connection:
            row = connection.execute(
                """SELECT payload FROM ai_briefings
                   WHERE profile_id=? AND strategy_run_id=?
                     AND briefing_schema_version=? AND briefing_rule_version=?
                     AND prompt_version=?
                   ORDER BY created_at DESC, briefing_fingerprint DESC LIMIT 1""",
                [
                    profile_id,
                    strategy_run_id,
                    AI_BRIEFING_SCHEMA_VERSION,
                    AI_BRIEFING_RULE_VERSION,
                    AI_BRIEFING_PROMPT_VERSION,
                ],
            ).fetchone()
        return AiBriefingArtifact.model_validate(_json(row[0])) if row else None

    def save(self, artifact: AiBriefingArtifact) -> None:
        self.initialize()
        try:
            with duckdb.connect(str(self._database_path), read_only=False) as connection:
                connection.execute(
                    """INSERT INTO ai_briefings VALUES (
                           ?,?,?,?,?,?,?,?,?,?,?,?,?
                       ) ON CONFLICT (briefing_id) DO NOTHING""",
                    [
                        artifact.briefing_id,
                        artifact.briefing_fingerprint,
                        artifact.briefing_schema_version,
                        artifact.briefing_rule_version,
                        artifact.prompt_version,
                        artifact.profile_id,
                        artifact.strategy_run_id,
                        artifact.source.source_fingerprint,
                        artifact.provider,
                        artifact.model_name,
                        artifact.model_digest,
                        canonical_json(artifact.model_dump(mode="json")),
                        artifact.created_at.replace(tzinfo=None),
                    ],
                )
        except duckdb.Error as exc:
            raise PersistenceError("Could not persist AI briefing.") from exc


def _json(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


__all__ = ["DuckDBAiBriefingRepository"]
