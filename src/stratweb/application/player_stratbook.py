"""Evidence-preserving individual movement chapter for player stratbooks."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from stratweb.application.normalization_utils import canonical_json
from stratweb.application.opponent_models import OpponentSubjectType, OpponentWorkspace
from stratweb.domain.enums import Side
from stratweb.features.models import EarlyZonePresencePayload, RoundFeatureType
from stratweb.ports import MatchRepository, RoundFeatureRepository

PLAYER_STRATBOOK_SCHEMA_VERSION = "1.0.0"
PLAYER_STRATBOOK_RULE_VERSION = "steam_scoped_early_zone_presence_v1"


class PlayerStratbookModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlayerMovementEvidence(PlayerStratbookModel):
    match_id: UUID
    round_number: int = Field(ge=1)
    tick: int = Field(ge=0)
    feature_id: UUID
    snapshot_ids: tuple[UUID, ...]
    map_href: str


class PlayerMovementSignal(PlayerStratbookModel):
    map_name: str
    side: Side
    zone_id: str
    zone_name: str
    zone_display_name: str
    numerator: int = Field(ge=1)
    denominator: int = Field(ge=1)
    frequency: float = Field(gt=0, le=1, allow_inf_nan=False)
    sample_size: int = Field(ge=1)
    match_count: int = Field(ge=1)
    observation: str
    tactical_interpretation: str
    recommendation: str
    avoid: str
    evidence: tuple[PlayerMovementEvidence, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)


class PlayerMovementChapter(PlayerStratbookModel):
    schema_version: str = PLAYER_STRATBOOK_SCHEMA_VERSION
    rule_version: str = PLAYER_STRATBOOK_RULE_VERSION
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_id: UUID
    target_steam_id: str
    target_player_name: str
    source_feature_run_ids: tuple[UUID, ...]
    signals: tuple[PlayerMovementSignal, ...]
    warnings: tuple[str, ...] = ()


class PlayerMovementStratbookService:
    """Aggregate only target-observed early zones from immutable feature runs."""

    def __init__(
        self,
        matches: MatchRepository,
        features: RoundFeatureRepository,
    ) -> None:
        self._matches = matches
        self._features = features

    def build(self, workspace: OpponentWorkspace) -> PlayerMovementChapter | None:
        profile = workspace.profile
        if (
            profile.subject_type is not OpponentSubjectType.PLAYER
            or profile.target_steam_id is None
            or profile.target_player_name is None
        ):
            return None

        observed_rounds: dict[tuple[str, Side], set[tuple[UUID, int]]] = defaultdict(set)
        zone_rounds: dict[tuple[str, Side, str, str], set[tuple[UUID, int]]] = defaultdict(set)
        zone_evidence: dict[tuple[str, Side, str, str], list[PlayerMovementEvidence]] = defaultdict(
            list
        )
        source_run_ids: list[UUID] = []
        warnings: list[str] = []

        for selected in workspace.selected_matches:
            selection = selected.selection
            target = next(
                (
                    player
                    for player in self._matches.get_players(selection.match_id)
                    if player.steam_id == profile.target_steam_id
                ),
                None,
            )
            if target is None:
                warnings.append(f"target_missing_in_match:{selection.match_id}")
                continue
            summary = self._features.get_summary(selection.match_id)
            if summary is None:
                warnings.append(f"feature_run_unavailable:{selection.match_id}")
                continue
            source_run_ids.append(summary.feature_run_id)
            rows = self._features.list_features(
                selection.match_id,
                feature_run_id=summary.feature_run_id,
                team_id=selection.team_id,
                feature_type=RoundFeatureType.EARLY_ZONE_PRESENCE,
                limit=5000,
            )
            for feature in rows:
                payload = feature.payload
                if (
                    not isinstance(payload, EarlyZonePresencePayload)
                    or target.player_id not in payload.player_ids
                    or feature.zone_id is None
                    or feature.zone_name is None
                    or feature.tick_start is None
                ):
                    continue
                scope = (selected.map_name, feature.side)
                occurrence = (selection.match_id, feature.round_number)
                key = (*scope, feature.zone_id, feature.zone_name)
                observed_rounds[scope].add(occurrence)
                zone_rounds[key].add(occurrence)
                zone_evidence[key].append(
                    PlayerMovementEvidence(
                        match_id=selection.match_id,
                        round_number=feature.round_number,
                        tick=feature.tick_start,
                        feature_id=feature.feature_id,
                        snapshot_ids=feature.evidence_snapshot_ids,
                        map_href=(
                            f"/ui/spatial/{selection.match_id}/rounds/{feature.round_number}"
                            f"?tick={feature.tick_start}&mode=smooth"
                        ),
                    )
                )

        signals: list[PlayerMovementSignal] = []
        for key, positives in zone_rounds.items():
            map_name, side, zone_id, zone_name = key
            if zone_name.replace("_", " ").strip().upper() in {"T SPAWN", "CT SPAWN"}:
                continue
            display_zone = _player_zone_name(zone_name)
            denominator = len(observed_rounds[(map_name, side)])
            if denominator == 0:
                continue
            numerator = len(positives)
            evidence = tuple(
                sorted(
                    zone_evidence[key],
                    key=lambda item: (str(item.match_id), item.round_number, item.tick),
                )
            )
            signals.append(
                PlayerMovementSignal(
                    map_name=map_name,
                    side=side,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    zone_display_name=display_zone,
                    numerator=numerator,
                    denominator=denominator,
                    frequency=numerator / denominator,
                    sample_size=denominator,
                    match_count=len({item.match_id for item in evidence}),
                    observation=(
                        f"{profile.target_player_name} был замечен в зоне «{display_zone}» "
                        f"в {numerator} из {denominator} раундов с доступной ранней позицией."
                    ),
                    tactical_interpretation=(
                        "Это повторяющаяся ранняя точка присутствия, а не доказательство "
                        "заранее выбранной тактики."
                    ),
                    recommendation=(
                        f"На подготовке отметьте возможный ранний контакт в зоне «{display_zone}» "
                        "и проверяйте его безопасной гранатой или парным контактом."
                    ),
                    avoid=(
                        "Не считайте позицию гарантированной и не перестраивайте весь раунд "
                        "без подтверждения информации."
                    ),
                    evidence=evidence,
                    limitations=(
                        "denominator_contains_only_rounds_with_observed_target_early_zone",
                        "positive_presence_does_not_prove_absence_from_other_zones",
                        "historical_position_does_not_prove_future_intent",
                    ),
                )
            )

        ranked = tuple(
            sorted(
                signals,
                key=lambda item: (
                    item.map_name,
                    -item.frequency,
                    -item.sample_size,
                    item.side.value,
                    item.zone_display_name.casefold(),
                ),
            )
        )
        values = {
            "schema_version": PLAYER_STRATBOOK_SCHEMA_VERSION,
            "rule_version": PLAYER_STRATBOOK_RULE_VERSION,
            "profile_id": str(profile.profile_id),
            "target_steam_id": profile.target_steam_id,
            "target_player_name": profile.target_player_name,
            "source_feature_run_ids": tuple(str(item) for item in source_run_ids),
            "signals": tuple(item.model_dump(mode="json") for item in ranked),
            "warnings": tuple(sorted(set(warnings))),
        }
        fingerprint = hashlib.sha256(canonical_json(values).encode("utf-8")).hexdigest()
        return PlayerMovementChapter(
            fingerprint=fingerprint,
            profile_id=profile.profile_id,
            target_steam_id=profile.target_steam_id,
            target_player_name=profile.target_player_name,
            source_feature_run_ids=tuple(source_run_ids),
            signals=ranked,
            warnings=tuple(sorted(set(warnings))),
        )


__all__ = [
    "PLAYER_STRATBOOK_RULE_VERSION",
    "PLAYER_STRATBOOK_SCHEMA_VERSION",
    "PlayerMovementChapter",
    "PlayerMovementEvidence",
    "PlayerMovementSignal",
    "PlayerMovementStratbookService",
]


_PLAYER_ZONE_NAMES = {
    "BOOST": "буст",
    "CT MID": "мид защиты",
    "MID DOORS": "двери мида",
    "LONG": "лонг",
    "LONG DOORS": "двери лонга",
    "LONG CORNER": "угол лонга",
    "SHORT": "шорт",
    "A SHORT": "шорт A",
    "B DOORS": "двери B",
    "UPPER TUNNELS": "верхние туннели",
    "LOWER TUNNELS": "нижние туннели",
    "A MAIN": "мейн A",
    "B MAIN": "мейн B",
    "CONNECTOR": "коннектор",
    "HEAVEN": "хэвен",
    "WATER": "вода",
    "BRIDGE": "мост",
}


def _player_zone_name(value: str) -> str:
    normalized = " ".join(value.replace("_", " ").split()).upper()
    return _PLAYER_ZONE_NAMES.get(normalized, " ".join(value.replace("_", " ").split()))
