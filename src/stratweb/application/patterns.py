"""Application services for deterministic opponent cross-match patterns."""

from __future__ import annotations

from time import perf_counter
from uuid import UUID

from stratweb.application.opponent_models import OpponentMatchSelection
from stratweb.domain.enums import Side
from stratweb.economy.models import BuyType
from stratweb.exceptions import (
    OpponentNotFoundError,
    PatternConfigurationError,
    PatternNotFoundError,
)
from stratweb.features.models import (
    ROUND_FEATURE_RULE_VERSION,
    ROUND_FEATURE_SCHEMA_VERSION,
    RoundFeature,
)
from stratweb.patterns.engine import CrossMatchPatternEngine
from stratweb.patterns.models import (
    PATTERN_RULE_VERSION,
    PATTERN_SCHEMA_VERSION,
    CrossMatchPattern,
    CrossMatchPatternInput,
    PatternAvailability,
    PatternComputeResult,
    PatternConfig,
    PatternInputStatus,
    PatternMatchInput,
    PatternPlayerIdentity,
    PatternRoundInput,
    PatternRunRecord,
    PatternRunSummary,
    PatternType,
)
from stratweb.ports import (
    MatchRepository,
    OpponentRepository,
    PatternRepository,
    RoundFeatureRepository,
)

_PAGE_SIZE = 5000


class ComputeCrossMatchPatternsService:
    def __init__(
        self,
        opponents: OpponentRepository,
        matches: MatchRepository,
        features: RoundFeatureRepository,
        patterns: PatternRepository,
        *,
        engine: CrossMatchPatternEngine | None = None,
    ) -> None:
        self._opponents = opponents
        self._matches = matches
        self._features = features
        self._patterns = patterns
        self._engine = engine or CrossMatchPatternEngine()

    def compute(
        self,
        profile_id: UUID,
        *,
        config: PatternConfig | None = None,
        replace: bool = False,
    ) -> PatternComputeResult:
        started = perf_counter()
        if self._opponents.get_profile(profile_id) is None:
            raise OpponentNotFoundError(f"Opponent profile not found: {profile_id}")
        selections = self._opponents.list_selections(profile_id)
        if not selections:
            raise PatternConfigurationError(
                "Stage 8.5 requires at least one user-confirmed opponent match team."
            )
        inputs = tuple(self._match_input(item) for item in selections)
        state = self._engine.compute(
            CrossMatchPatternInput(profile_id=profile_id, inputs=inputs),
            config,
        )
        saved = self._patterns.save_patterns(state, replace=replace)
        return PatternComputeResult(
            pattern_run_id=saved.pattern_run_id,
            pattern_fingerprint=saved.pattern_fingerprint,
            pattern_schema_version=PATTERN_SCHEMA_VERSION,
            pattern_rule_version=PATTERN_RULE_VERSION,
            profile_id=profile_id,
            status=saved.status,
            summary=state.summary,
            capabilities=state.capabilities,
            row_counts=saved.row_counts,
            warnings=state.warnings,
            duration_seconds=perf_counter() - started,
        )

    def _match_input(self, selection: OpponentMatchSelection) -> PatternMatchInput:
        stored = self._matches.get_match(selection.match_id)
        if stored is None:
            return PatternMatchInput(
                profile_id=selection.profile_id,
                match_id=selection.match_id,
                team_id=selection.team_id,
                map_name="unknown",
                status=PatternInputStatus.EXCLUDED,
                exclusion_reason="canonical_match_unavailable",
            )
        summary = self._features.get_summary(selection.match_id)
        if summary is None:
            return PatternMatchInput(
                profile_id=selection.profile_id,
                match_id=selection.match_id,
                team_id=selection.team_id,
                map_name=stored.map_name or "unknown",
                status=PatternInputStatus.EXCLUDED,
                exclusion_reason="compatible_feature_run_unavailable",
            )
        if (summary.feature_schema_version, summary.feature_rule_version) != (
            ROUND_FEATURE_SCHEMA_VERSION,
            ROUND_FEATURE_RULE_VERSION,
        ):
            return PatternMatchInput(
                profile_id=selection.profile_id,
                match_id=selection.match_id,
                team_id=selection.team_id,
                map_name=stored.map_name or "unknown",
                status=PatternInputStatus.EXCLUDED,
                exclusion_reason="feature_rule_incompatible",
            )
        selected_features = self._all_features(
            selection.match_id,
            selection.team_id,
            summary.feature_run_id,
        )
        by_round: dict[int, list[RoundFeature]] = {}
        for feature in selected_features:
            by_round.setdefault(feature.round_number, []).append(feature)
        round_inputs: list[PatternRoundInput] = []
        for round_item in self._matches.get_rounds(selection.match_id):
            if round_item.t_team_id == selection.team_id:
                side = Side.T
            elif round_item.ct_team_id == selection.team_id:
                side = Side.CT
            else:
                continue
            rows = tuple(
                sorted(
                    by_round.get(round_item.round_number, ()),
                    key=lambda item: str(item.feature_id),
                )
            )
            buy_types = {item.buy_type for item in rows if item.buy_type is not None}
            if len(buy_types) > 1:
                raise PatternConfigurationError(
                    f"Conflicting buy types in match {selection.match_id} round "
                    f"{round_item.round_number}."
                )
            opponent_won = None
            if round_item.winner_side in {Side.T, Side.CT}:
                opponent_won = round_item.winner_side is side
            round_inputs.append(
                PatternRoundInput(
                    match_id=selection.match_id,
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=selection.team_id,
                    side=side,
                    buy_type=next(iter(buy_types)) if buy_types else None,
                    is_warmup=round_item.is_warmup,
                    is_complete=round_item.is_complete,
                    opponent_won=opponent_won,
                    features=rows,
                )
            )
        return PatternMatchInput(
            profile_id=selection.profile_id,
            match_id=selection.match_id,
            team_id=selection.team_id,
            map_name=stored.map_name or "unknown",
            status=PatternInputStatus.INCLUDED,
            dataset_fingerprint=summary.dataset_fingerprint,
            feature_run_id=summary.feature_run_id,
            feature_fingerprint=summary.feature_fingerprint,
            feature_schema_version=summary.feature_schema_version,
            feature_rule_version=summary.feature_rule_version,
            players=self._player_identities(selection),
            rounds=tuple(round_inputs),
        )

    def _all_features(
        self,
        match_id: UUID,
        team_id: UUID,
        feature_run_id: UUID,
    ) -> tuple[RoundFeature, ...]:
        result: list[RoundFeature] = []
        offset = 0
        while True:
            page = self._features.list_features(
                match_id,
                feature_run_id=feature_run_id,
                team_id=team_id,
                limit=_PAGE_SIZE,
                offset=offset,
            )
            result.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += len(page)
        return tuple(result)

    def _player_identities(
        self, selection: OpponentMatchSelection
    ) -> tuple[PatternPlayerIdentity, ...]:
        team = next(
            (
                item
                for item in self._matches.get_teams(selection.match_id)
                if item.team_id == selection.team_id
            ),
            None,
        )
        if team is None:
            raise PatternConfigurationError(
                "Confirmed opponent team is unavailable in canonical match data."
            )
        ids = set(team.starting_player_ids)
        ids.update(
            item.player_id
            for item in self._matches.get_memberships(selection.match_id)
            if item.team_id == selection.team_id
        )
        players = {item.player_id: item for item in self._matches.get_players(selection.match_id)}
        return tuple(
            PatternPlayerIdentity(
                player_id=player_id,
                identity_key=(
                    f"steam:{players[player_id].steam_id}"
                    if players[player_id].steam_id is not None
                    else f"occurrence:{selection.match_id}:{player_id}"
                ),
                current_name=players[player_id].current_name,
                steam_id=players[player_id].steam_id,
                cross_match_resolved=players[player_id].steam_id is not None,
            )
            for player_id in sorted(ids & players.keys(), key=str)
        )


class PatternQueryService:
    def __init__(self, repository: PatternRepository) -> None:
        self._repository = repository

    def get_summary(
        self, profile_id: UUID, *, pattern_run_id: UUID | None = None
    ) -> PatternRunSummary:
        summary = (
            self._repository.get_summary_for_run(profile_id, pattern_run_id)
            if pattern_run_id is not None
            else self._repository.get_summary(profile_id)
        )
        if summary is None:
            raise PatternNotFoundError(
                f"Compatible Stage 8.5 pattern run not found for profile {profile_id}."
            )
        return summary

    def list_runs(self, profile_id: UUID) -> tuple[PatternRunRecord, ...]:
        return self._repository.list_runs(profile_id)

    def list_patterns(
        self,
        profile_id: UUID,
        *,
        pattern_run_id: UUID | None = None,
        map_name: str | None = None,
        side: Side | None = None,
        buy_type: BuyType | None = None,
        pattern_type: PatternType | None = None,
        availability: PatternAvailability | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> tuple[CrossMatchPattern, ...]:
        summary = self.get_summary(profile_id, pattern_run_id=pattern_run_id)
        return self._repository.list_patterns(
            profile_id,
            pattern_run_id=summary.pattern_run_id,
            map_name=map_name,
            side=side,
            buy_type=buy_type,
            pattern_type=pattern_type,
            availability=availability,
            limit=limit,
            offset=offset,
        )

    def delete(self, profile_id: UUID) -> int:
        return self._repository.delete_patterns(profile_id)


__all__ = ["ComputeCrossMatchPatternsService", "PatternQueryService"]
