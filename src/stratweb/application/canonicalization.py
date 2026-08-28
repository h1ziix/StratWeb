"""Application service that builds one deterministic Canonical Match Dataset."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from stratweb.application.canonical_models import (
    CANONICAL_SCHEMA_VERSION,
    NORMALIZATION_RULE_VERSION,
    CanonicalMatch,
    CanonicalMatchDataset,
    NormalizationMetadata,
    ValidationIssue,
    ValidationSeverity,
)
from stratweb.application.gameplay_normalization import GameplayEventNormalizer
from stratweb.application.identity_resolution import PlayerResolver, TeamResolver
from stratweb.application.inspection import inspect_local_file
from stratweb.application.normalization_utils import canonical_json, optional_text
from stratweb.application.outcome_resolution import (
    OUTCOME_PARSE_PROPERTIES,
    OUTCOME_SOURCE_EVENTS,
    ROUND_END_REASON_FIELD,
    ROUND_WINNER_FIELD,
    TEAM_SCORE_FIELD,
)
from stratweb.application.round_assignment import RoundAssignmentService
from stratweb.application.round_resolution import RoundResolver
from stratweb.application.team_name_inference import (
    TEAM_NAME_INFERENCE_RULE_VERSION,
    apply_inferred_team_names,
)
from stratweb.application.validation import (
    CanonicalDatasetValidator,
    CanonicalEvent,
    ValidationInput,
)
from stratweb.contracts import ParsedDemo, ParseOptions, ParseRequest
from stratweb.exceptions import DemoFileUnreadableError, ParserContractError
from stratweb.ports import DemoParser

NORMALIZATION_EVENTS: tuple[str, ...] = (
    "player_death",
    "player_hurt",
    "weapon_fire",
    "round_prestart",
    "round_start",
    "round_poststart",
    "round_freeze_end",
    "round_end",
    "round_officially_ended",
    "announce_phase_end",
    "round_announce_last_round_half",
    "round_announce_final",
    "begin_new_match",
    "cs_win_panel_round",
    "cs_win_panel_match",
    "bomb_planted",
    "bomb_defused",
    "bomb_exploded",
    "smokegrenade_detonate",
    "smokegrenade_expired",
    "inferno_startburn",
    "inferno_expire",
    "flashbang_detonate",
    "hegrenade_detonate",
    "decoy_detonate",
    "player_spawn",
    "player_team",
    "player_connect_full",
    "player_disconnect",
)

_NORMALIZATION_CONFIG: dict[str, object] = {
    "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
    "normalization_rule_version": NORMALIZATION_RULE_VERSION,
    "round_start_precedence": [
        "round_prestart",
        "round_start",
        "round_poststart",
        "round_freeze_end",
    ],
    "round_end_precedence": ["round_end", "round_officially_ended"],
    "round_count_precedence": [
        "max_total_rounds_played",
        "canonical_round_end_count",
        "canonical_round_start_count",
    ],
    "round_assignment": "half_open_start_windows_v1",
    "player_identity": "steam_id_else_occurrence_scoped_v1",
    "team_identity": "first_observed_round_rosters_v1",
    "team_display_name_inference": TEAM_NAME_INFERENCE_RULE_VERSION,
    "overtime": "second_observed_physical_team_side_switch_v1",
    "round_outcome_sources": OUTCOME_SOURCE_EVENTS,
    "round_winner_field": ROUND_WINNER_FIELD,
    "round_end_reason_field": ROUND_END_REASON_FIELD,
    "round_score_field": TEAM_SCORE_FIELD,
}


class CanonicalMatchNormalizer:
    @property
    def schema_version(self) -> str:
        return CANONICAL_SCHEMA_VERSION

    def normalize(self, parsed: ParsedDemo, *, source_demo_sha256: str) -> CanonicalMatchDataset:
        match_id = uuid5(NAMESPACE_URL, f"stratweb:canonical-match:{source_demo_sha256}")
        round_result = RoundResolver().resolve(parsed, match_id)
        player_result = PlayerResolver().resolve(parsed, match_id)
        team_result = TeamResolver().resolve(
            match_id,
            player_result,
            round_result.rounds,
        )
        inferred_teams = apply_inferred_team_names(
            parsed,
            team_result.teams,
            team_result.rounds,
            player_result.players,
        )
        assignments = RoundAssignmentService(team_result.rounds)
        gameplay = GameplayEventNormalizer().normalize(
            parsed,
            match_id,
            assignments,
            player_result,
            team_result,
        )

        selected_count = round_result.selected_round_count or len(team_result.rounds)
        complete_count = sum(round_item.is_complete for round_item in team_result.rounds)
        incomplete_count = len(team_result.rounds) - complete_count
        candidate_values = set(round_result.round_count_candidates.values())
        match = CanonicalMatch(
            match_id=match_id,
            demo_file_id=parsed.demo_file_id,
            map_name=_header_text(parsed.header, "map_name", "map"),
            server_name=_header_text(parsed.header, "server_name"),
            round_count=len(team_result.rounds),
            complete_round_count=complete_count,
            incomplete_round_count=incomplete_count,
            round_count_candidates=round_result.round_count_candidates,
            selected_round_count=selected_count,
            selected_round_count_source=round_result.selected_round_count_source,
            round_count_disagreement=len(candidate_values) > 1,
        )

        selected_aliases = dict(round_result.selected_event_aliases)
        selected_aliases.update(
            {
                "CanonicalKill": _selected(parsed, "player_death"),
                "CanonicalDamage": _selected(parsed, "player_hurt"),
                "CanonicalShot": _selected(parsed, "weapon_fire"),
                "CanonicalGrenade": _selected_first(
                    parsed,
                    (
                        "smokegrenade_detonate",
                        "flashbang_detonate",
                        "hegrenade_detonate",
                        "decoy_detonate",
                        "inferno_startburn",
                    ),
                ),
                "CanonicalBombEvent": _selected_first(
                    parsed,
                    ("bomb_planted", "bomb_defused", "bomb_exploded"),
                ),
            }
        )
        for event_name in (
            "smokegrenade_detonate",
            "smokegrenade_expired",
            "inferno_startburn",
            "inferno_expire",
            "flashbang_detonate",
            "hegrenade_detonate",
            "decoy_detonate",
        ):
            selected_aliases[f"CanonicalGrenade:{event_name}"] = _selected(parsed, event_name)
        for event_name in ("bomb_planted", "bomb_defused", "bomb_exploded"):
            selected_aliases[f"CanonicalBombEvent:{event_name}"] = _selected(parsed, event_name)
        config_hash = hashlib.sha256(canonical_json(_NORMALIZATION_CONFIG).encode()).hexdigest()
        metadata_warnings = tuple(
            dict.fromkeys(
                (
                    *parsed.warnings,
                    *round_result.warnings,
                    *team_result.warnings,
                    *(f"{name}: {error}" for name, error in sorted(parsed.event_errors.items())),
                )
            )
        )
        metadata = NormalizationMetadata(
            parser_name=parsed.parser.name,
            parser_version=parsed.parser.version,
            normalization_config_hash=config_hash,
            source_demo_sha256=source_demo_sha256,
            source_event_counts={
                event_name: frame.height for event_name, frame in sorted(parsed.tables.items())
            },
            selected_event_aliases=selected_aliases,
            result_capabilities=round_result.result_capabilities,
            warnings=metadata_warnings,
        )

        event_list: list[CanonicalEvent] = []
        event_list.extend(gameplay.kills)
        event_list.extend(gameplay.damages)
        event_list.extend(gameplay.shots)
        event_list.extend(gameplay.grenades)
        event_list.extend(gameplay.bomb_events)
        all_events = tuple(sorted(event_list, key=lambda event: (event.tick, str(event.event_id))))
        preprocessing_issues = list(gameplay.issues)
        if any(warning.startswith("Alias disagreement") for warning in round_result.warnings):
            preprocessing_issues.append(
                ValidationIssue(
                    code="alias_disagreement",
                    severity=ValidationSeverity.WARNING,
                    entity_type="round",
                    message="Logical round alias counts disagree.",
                    evidence={},
                    rule_version=NORMALIZATION_RULE_VERSION,
                )
            )
        validation = CanonicalDatasetValidator().validate(
            ValidationInput(
                match=match,
                teams=inferred_teams,
                players=player_result.players,
                memberships=team_result.memberships,
                rounds=team_result.rounds,
                events=all_events,
                result_capabilities=round_result.result_capabilities,
                preprocessing_issues=tuple(preprocessing_issues),
            )
        )
        provisional = CanonicalMatchDataset(
            dataset_fingerprint="0" * 64,
            match=match,
            teams=inferred_teams,
            players=player_result.players,
            player_team_memberships=team_result.memberships,
            rounds=team_result.rounds,
            kills=gameplay.kills,
            damages=gameplay.damages,
            shots=gameplay.shots,
            grenades=gameplay.grenades,
            bomb_events=gameplay.bomb_events,
            validation_report=validation,
            normalization_metadata=metadata,
        )
        fingerprint = compute_dataset_fingerprint(provisional)
        return provisional.model_copy(update={"dataset_fingerprint": fingerprint})


class CanonicalizationService:
    """Hash, parse, normalize and validate one existing local completed demo."""

    def __init__(self, parser: DemoParser) -> None:
        self._parser = parser

    def normalize(self, demo_path: str | Path) -> CanonicalMatchDataset:
        snapshot = inspect_local_file(demo_path)
        request = ParseRequest(
            demo_file_id=uuid5(NAMESPACE_URL, f"stratweb:demo:{snapshot.sha256}"),
            sha256=snapshot.sha256,
            path=snapshot.path,
            options=ParseOptions(
                event_names=NORMALIZATION_EVENTS,
                player_properties=("team_name", "team_clan_name"),
                other_properties=(
                    "total_rounds_played",
                    "is_warmup_period",
                    *OUTCOME_PARSE_PROPERTIES,
                ),
                include_grenade_trajectories=False,
            ),
        )
        parsed = self._parser.parse(request)
        if parsed.demo_file_id != request.demo_file_id:
            raise ParserContractError("Parser returned data for a different demo ID.")
        if parsed.parser != self._parser.identity:
            raise ParserContractError("Parser identity changed while processing the demo.")
        try:
            current = snapshot.path.stat()
        except OSError as exc:
            raise DemoFileUnreadableError(
                "The demo became unavailable while it was being normalized."
            ) from exc
        if current.st_size != snapshot.size_bytes or current.st_mtime_ns != snapshot.modified_ns:
            raise DemoFileUnreadableError("The demo changed while it was being normalized.")
        return CanonicalMatchNormalizer().normalize(
            parsed,
            source_demo_sha256=snapshot.sha256,
        )


def _header_text(header: Mapping[str, Any], *keys: str) -> str | None:
    lookup = {str(key).casefold(): item for key, item in header.items()}
    return next(
        (text for key in keys if (text := optional_text(lookup.get(key.casefold()))) is not None),
        None,
    )


def _selected(parsed: ParsedDemo, event_name: str) -> str | None:
    frame = parsed.tables.get(event_name)
    return event_name if frame is not None and not frame.is_empty() else None


def _selected_first(parsed: ParsedDemo, event_names: tuple[str, ...]) -> str | None:
    return next((name for name in event_names if _selected(parsed, name)), None)


def compute_dataset_fingerprint(dataset: CanonicalMatchDataset) -> str:
    """Recompute the canonical content hash without trusting the stored fingerprint."""

    fingerprint_payload = dataset.model_dump(
        mode="json",
        exclude={"dataset_fingerprint"},
    )
    return hashlib.sha256(canonical_json(fingerprint_payload).encode()).hexdigest()
