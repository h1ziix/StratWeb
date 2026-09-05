from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from stratweb.application.canonical_models import CanonicalPlayer
from stratweb.application.opponent_models import (
    OpponentMatchSelection,
    OpponentProfile,
    OpponentSelectionSource,
    OpponentSubjectType,
    OpponentWorkspace,
    SelectedOpponentMatch,
)
from stratweb.application.player_stratbook import PlayerMovementStratbookService
from stratweb.domain.enums import Side
from stratweb.features.models import (
    EarlyZonePresencePayload,
    FeatureAvailability,
    RoundFeature,
    RoundFeatureType,
)


def _id(value: int) -> UUID:
    return UUID(int=value)


class _Matches:
    def get_players(self, match_id: UUID) -> tuple[CanonicalPlayer, ...]:
        del match_id
        return (
            CanonicalPlayer(
                player_id=_id(5),
                steam_id="76561198000000001",
                current_name="Alpha",
                known_names=("Alpha",),
            ),
        )


class _Features:
    def get_summary(self, match_id: UUID) -> SimpleNamespace:
        del match_id
        return SimpleNamespace(feature_run_id=_id(8))

    def list_features(self, match_id: UUID, **kwargs: object) -> tuple[RoundFeature, ...]:
        del match_id, kwargs
        return (
            RoundFeature(
                feature_id=_id(9),
                feature_run_id=_id(8),
                feature_rule_version="per_round_facts_v1",
                match_id=_id(2),
                round_id=_id(10),
                round_number=3,
                team_id=_id(4),
                side=Side.T,
                feature_type=RoundFeatureType.EARLY_ZONE_PRESENCE,
                availability=FeatureAvailability.AVAILABLE,
                tick_start=1200,
                tick_end=1200,
                zone_id="long",
                zone_name="Long",
                payload=EarlyZonePresencePayload(
                    first_observed_tick=1200,
                    player_ids=(_id(5),),
                ),
                evidence_snapshot_ids=(_id(11),),
                limitations=("positive_presence_only_absence_not_proven",),
            ),
        )


def test_player_movement_chapter_is_steam_scoped_and_evidence_linked() -> None:
    now = datetime.now(UTC)
    profile = OpponentProfile(
        profile_id=_id(1),
        display_name="Alpha player",
        subject_type=OpponentSubjectType.PLAYER,
        target_steam_id="76561198000000001",
        target_player_name="Alpha",
        created_at=now,
        updated_at=now,
    )
    selection = OpponentMatchSelection(
        profile_id=profile.profile_id,
        match_id=_id(2),
        team_id=_id(4),
        selection_source=OpponentSelectionSource.USER_CONFIRMED,
        created_at=now,
    )
    workspace = OpponentWorkspace(
        profile=profile,
        selected_matches=(
            SelectedOpponentMatch(
                selection=selection,
                map_name="de_dust2",
                source_name="fixture.dem",
                round_count=24,
                team_name="Alpha team",
                player_names=("Alpha",),
                identified_player_count=1,
                unresolved_player_count=0,
            ),
        ),
        roster=(),
        candidates=(),
    )

    chapter = PlayerMovementStratbookService(_Matches(), _Features()).build(workspace)  # type: ignore[arg-type]

    assert chapter is not None
    assert chapter.target_player_name == "Alpha"
    assert chapter.source_feature_run_ids == (_id(8),)
    assert len(chapter.signals) == 1
    signal = chapter.signals[0]
    assert (signal.numerator, signal.denominator, signal.frequency) == (1, 1, 1.0)
    assert signal.zone_display_name == "лонг"
    assert signal.evidence[0].match_id == _id(2)
    assert signal.evidence[0].round_number == 3
    assert "mode=smooth" in signal.evidence[0].map_href

    other_map = PlayerMovementStratbookService(_Matches(), _Features()).build(  # type: ignore[arg-type]
        workspace,
        map_name="de_mirage",
    )
    assert other_map is not None
    assert other_map.signals == ()
    assert other_map.source_feature_run_ids == ()
