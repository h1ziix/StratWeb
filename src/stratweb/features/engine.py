"""Pure deterministic extraction of version-pinned facts inside one round."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from stratweb.analytics.definitions import Participant, classify_kill
from stratweb.analytics.models import (
    AdvantageState,
    AnalyticsRunSummary,
    RoundAnalyticsView,
)
from stratweb.application.canonical_models import (
    CanonicalBombEvent,
    CanonicalDamage,
    CanonicalGrenade,
    CanonicalKill,
    CanonicalRound,
    EventPhase,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.persistence_models import RoundEvents
from stratweb.domain.enums import Side
from stratweb.economy.models import EconomyRunSummary, TeamEconomySnapshot
from stratweb.features.models import (
    ROUND_FEATURE_RULE_VERSION,
    ROUND_FEATURE_SCHEMA_VERSION,
    BombRoutePayload,
    BombRouteStop,
    BombsitePayload,
    ContactCandidate,
    EarlyZonePresencePayload,
    FeatureAvailability,
    FeaturePayload,
    FeatureTypeCapability,
    FirstContactPayload,
    FirstUtilityPayload,
    LostAdvantagePayload,
    OpeningDuelPayload,
    PlantTimingPayload,
    PlayerZoneEvidence,
    PostPlantRosterPayload,
    RetakeAttemptPayload,
    RoundFeature,
    RoundFeatureConfig,
    RoundFeatureState,
    RoundFeatureSummary,
    RoundFeatureType,
    UntradedDeathPayload,
    UtilityCandidate,
    ZoneDistributionPayload,
)
from stratweb.spatial.models import SpatialRunSummary, SpatialSnapshot
from stratweb.temporal.models import (
    IntermediateStateStatus,
    ParticipationStatus,
    RoundTimeline,
    SnapshotStateStatus,
    TemporalRunSummary,
)
from stratweb.temporal.snapshots import SnapshotBuilder
from stratweb.zones.assignment_models import (
    ZoneAssignment,
    ZoneAssignmentRunSummary,
    ZoneAssignmentStatus,
)
from stratweb.zones.engine import resolve_zone
from stratweb.zones.models import ZoneKind, ZoneResolutionStatus, ZoneSetDefinition

_RUN_NAMESPACE = UUID("69d9748d-114e-4bc1-9aba-a2388964483b")
_FEATURE_NAMESPACE = UUID("6d937689-b71b-4578-89d4-58429a89c339")


@dataclass(frozen=True, slots=True)
class RoundFeatureMatchInput:
    match_id: UUID
    dataset_fingerprint: str
    map_name: str
    rounds: tuple[CanonicalRound, ...]
    events: dict[int, RoundEvents]
    analytics: AnalyticsRunSummary
    round_analytics: dict[int, RoundAnalyticsView]
    temporal: TemporalRunSummary
    timelines: dict[int, RoundTimeline]
    spatial: SpatialRunSummary
    snapshots: tuple[SpatialSnapshot, ...]
    zones: ZoneAssignmentRunSummary
    assignments: tuple[ZoneAssignment, ...]
    zone_set: ZoneSetDefinition | None
    economy: EconomyRunSummary | None = None
    economy_snapshots: tuple[TeamEconomySnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class _Draft:
    round_id: UUID
    round_number: int
    team_id: UUID
    side: Side
    feature_type: RoundFeatureType
    availability: FeatureAvailability
    tick_start: int | None = None
    tick_end: int | None = None
    zone_id: str | None = None
    zone_name: str | None = None
    payload: FeaturePayload | None = None
    evidence_event_ids: tuple[UUID, ...] = ()
    evidence_snapshot_ids: tuple[UUID, ...] = ()
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class RoundFeatureEngine:
    """Combine canonical evidence and pinned derived runs without parser access."""

    def compute(
        self,
        data: RoundFeatureMatchInput,
        config: RoundFeatureConfig | None = None,
    ) -> RoundFeatureState:
        selected_config = config or RoundFeatureConfig()
        self._validate_inputs(data)
        config_hash = hashlib.sha256(
            canonical_json(selected_config.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()
        assignment_by_snapshot = {item.spatial_snapshot_id: item for item in data.assignments}
        economy_by_team_round = {
            (item.round_number, item.team_id): item
            for item in data.economy_snapshots
            if item.team_id is not None
        }
        snapshots_by_round: dict[int, list[SpatialSnapshot]] = defaultdict(list)
        for snapshot in data.snapshots:
            snapshots_by_round[snapshot.round_number].append(snapshot)
        excluded_rounds = 0
        included_round_numbers: set[int] = set()
        drafts: list[_Draft] = []
        warnings: list[str] = []
        for round_item in sorted(data.rounds, key=lambda item: item.round_number):
            if round_item.is_warmup or (
                not selected_config.include_incomplete_rounds and not round_item.is_complete
            ):
                excluded_rounds += 1
                continue
            timeline = data.timelines.get(round_item.round_number)
            round_events = data.events.get(round_item.round_number)
            if timeline is None or round_events is None:
                warnings.append(f"round_{round_item.round_number}:required_input_missing")
                excluded_rounds += 1
                continue
            included_round_numbers.add(round_item.round_number)
            round_snapshots = tuple(
                sorted(
                    snapshots_by_round.get(round_item.round_number, ()),
                    key=lambda item: (item.tick, str(item.participant_id)),
                )
            )
            analytics = data.round_analytics.get(round_item.round_number)
            drafts.extend(
                self._round_features(
                    data,
                    round_item,
                    round_events,
                    timeline,
                    analytics,
                    round_snapshots,
                    assignment_by_snapshot,
                    selected_config,
                )
            )

        ordered_drafts = tuple(sorted(drafts, key=_draft_key))
        fingerprint = self._fingerprint(data, selected_config, ordered_drafts)
        run_id = uuid5(_RUN_NAMESPACE, fingerprint)
        features: list[RoundFeature] = []
        for ordinal, draft in enumerate(ordered_drafts):
            economy_snapshot = economy_by_team_round.get((draft.round_number, draft.team_id))
            features.append(
                RoundFeature(
                    feature_id=uuid5(_FEATURE_NAMESPACE, f"{run_id}:{ordinal}"),
                    feature_run_id=run_id,
                    feature_rule_version=ROUND_FEATURE_RULE_VERSION,
                    match_id=data.match_id,
                    round_id=draft.round_id,
                    round_number=draft.round_number,
                    team_id=draft.team_id,
                    side=draft.side,
                    feature_type=draft.feature_type,
                    availability=draft.availability,
                    tick_start=draft.tick_start,
                    tick_end=draft.tick_end,
                    zone_id=draft.zone_id,
                    zone_name=draft.zone_name,
                    buy_type=(economy_snapshot.buy_type if economy_snapshot else None),
                    payload=draft.payload,
                    evidence_event_ids=draft.evidence_event_ids,
                    evidence_snapshot_ids=draft.evidence_snapshot_ids,
                    evidence_economy_snapshot_ids=(
                        (economy_snapshot.team_snapshot_id,) if economy_snapshot else ()
                    ),
                    limitations=draft.limitations,
                    warnings=draft.warnings,
                )
            )
        feature_tuple = tuple(features)
        capabilities = _capabilities(feature_tuple)
        status_counts = Counter(item.availability for item in feature_tuple)
        type_counts = Counter(item.feature_type for item in feature_tuple)
        summary = RoundFeatureSummary(
            eligible_rounds=len(included_round_numbers),
            excluded_rounds=excluded_rounds,
            features=len(feature_tuple),
            available=status_counts[FeatureAvailability.AVAILABLE],
            partial=status_counts[FeatureAvailability.PARTIAL],
            unavailable=status_counts[FeatureAvailability.UNAVAILABLE],
            not_applicable=status_counts[FeatureAvailability.NOT_APPLICABLE],
            feature_type_counts={item: type_counts[item] for item in RoundFeatureType},
        )
        return RoundFeatureState(
            feature_run_id=run_id,
            feature_fingerprint=fingerprint,
            feature_config_hash=config_hash,
            match_id=data.match_id,
            dataset_fingerprint=data.dataset_fingerprint,
            analytics_fingerprint=data.analytics.analytics_fingerprint,
            analytics_rule_version=data.analytics.analytics_rule_version,
            temporal_run_id=data.temporal.temporal_run_id,
            temporal_fingerprint=data.temporal.temporal_fingerprint,
            temporal_rule_version=data.temporal.temporal_rule_version,
            spatial_run_id=data.spatial.spatial_run_id,
            spatial_fingerprint=data.spatial.spatial_fingerprint,
            spatial_rule_version=data.spatial.spatial_rule_version,
            zone_assignment_run_id=data.zones.zone_assignment_run_id,
            zone_assignment_fingerprint=data.zones.zone_assignment_fingerprint,
            zone_assignment_rule_version=data.zones.zone_assignment_rule_version,
            economy_run_id=(data.economy.economy_run_id if data.economy else None),
            economy_fingerprint=(data.economy.economy_fingerprint if data.economy else None),
            economy_rule_version=(data.economy.economy_rule_version if data.economy else None),
            config=selected_config,
            capabilities=capabilities,
            summary=summary,
            features=feature_tuple,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _round_features(
        self,
        data: RoundFeatureMatchInput,
        round_item: CanonicalRound,
        events: RoundEvents,
        timeline: RoundTimeline,
        analytics: RoundAnalyticsView | None,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
        config: RoundFeatureConfig,
    ) -> tuple[_Draft, ...]:
        teams = tuple(
            (team_id, side)
            for team_id, side in (
                (round_item.t_team_id, Side.T),
                (round_item.ct_team_id, Side.CT),
            )
            if team_id is not None
        )
        if not teams:
            return ()
        result: list[_Draft] = []
        result.extend(
            self._zone_distributions(
                round_item, timeline, snapshots, assignments, teams, config, data.spatial
            )
        )
        result.extend(self._first_contact(round_item, events, timeline, snapshots, assignments))
        result.extend(self._opening_duel(round_item, timeline, analytics, teams))
        result.extend(self._first_utility(round_item, events.grenades, teams, data.zone_set))
        result.extend(
            self._early_zone_presence(round_item, timeline, snapshots, assignments, teams, config)
        )
        result.extend(self._bomb_route(round_item, snapshots, assignments))
        result.extend(
            self._plant_features(
                data, round_item, events.bomb_events, timeline, snapshots, assignments, teams
            )
        )
        result.extend(self._lost_advantage(round_item, timeline, analytics))
        result.extend(self._untraded_deaths(data, round_item, events.kills, timeline, analytics))
        ct_team_id = round_item.ct_team_id
        if ct_team_id is not None:
            result.append(
                _unavailable(
                    round_item,
                    ct_team_id,
                    Side.CT,
                    RoundFeatureType.FIRST_CT_ROTATION,
                    "map_adjacency_and_site_role_semantics_not_available_v1",
                )
            )
        for team_id, side in teams:
            result.append(
                _unavailable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.SAVE_EXIT,
                    "survival_does_not_prove_save_or_exit_intent_v1",
                )
            )
        return tuple(result)

    def _zone_distributions(
        self,
        round_item: CanonicalRound,
        timeline: RoundTimeline,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
        teams: tuple[tuple[UUID, Side], ...],
        config: RoundFeatureConfig,
        spatial: SpatialRunSummary,
    ) -> tuple[_Draft, ...]:
        freeze_tick = round_item.freeze_end_tick
        if freeze_tick is None:
            return tuple(
                _unavailable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.STARTING_ZONE_DISTRIBUTION,
                    "freeze_end_tick_unavailable",
                )
                for team_id, side in teams
            )
        result: list[_Draft] = []
        checkpoints = (("freeze_end", 0),) + tuple(
            (f"freeze_end_plus_{offset}_ticks", offset)
            for offset in config.checkpoint_offsets_ticks
        )
        for label, offset in checkpoints:
            feature_type = (
                RoundFeatureType.STARTING_ZONE_DISTRIBUTION
                if offset == 0
                else RoundFeatureType.CHECKPOINT_ZONE_DISTRIBUTION
            )
            target = freeze_tick + offset
            if timeline.effective_end_tick is not None and target > timeline.effective_end_tick:
                for team_id, side in teams:
                    result.append(
                        _not_applicable(
                            round_item,
                            team_id,
                            side,
                            feature_type,
                            "checkpoint_after_round_end",
                        )
                    )
                continue
            observed_tick = _checkpoint_tick(
                snapshots, target, spatial.config.sampling_interval_ticks
            )
            for team_id, side in teams:
                if observed_tick is None:
                    result.append(
                        _unavailable(
                            round_item,
                            team_id,
                            side,
                            feature_type,
                            "spatial_checkpoint_unavailable",
                        )
                    )
                    continue
                participants = tuple(
                    item.player_id
                    for item in timeline.participants
                    if item.physical_team_id == team_id
                    and item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
                )
                player_evidence: list[PlayerZoneEvidence] = []
                evidence_ids: list[UUID] = []
                resolved = 0
                for player_id in sorted(participants, key=str):
                    snapshot = next(
                        (
                            item
                            for item in snapshots
                            if item.tick == observed_tick and item.participant_id == player_id
                        ),
                        None,
                    )
                    assignment = assignments.get(snapshot.snapshot_id) if snapshot else None
                    if snapshot is not None:
                        evidence_ids.append(snapshot.snapshot_id)
                    if (
                        assignment is not None
                        and assignment.status is ZoneAssignmentStatus.RESOLVED
                    ):
                        resolved += 1
                    player_evidence.append(
                        PlayerZoneEvidence(
                            player_id=player_id,
                            snapshot_id=snapshot.snapshot_id if snapshot else None,
                            tick=snapshot.tick if snapshot else None,
                            zone_id=assignment.zone_id if assignment else None,
                            zone_name=assignment.zone_name if assignment else None,
                            status=(assignment.status.value if assignment else "unavailable"),
                        )
                    )
                if not player_evidence or resolved == 0:
                    result.append(
                        _unavailable(
                            round_item,
                            team_id,
                            side,
                            feature_type,
                            "no_resolved_player_zones_at_checkpoint",
                            tick=observed_tick,
                            snapshot_ids=tuple(evidence_ids),
                        )
                    )
                    continue
                availability = (
                    FeatureAvailability.AVAILABLE
                    if resolved == len(player_evidence)
                    else FeatureAvailability.PARTIAL
                )
                result.append(
                    _Draft(
                        round_id=round_item.round_id,
                        round_number=round_item.round_number,
                        team_id=team_id,
                        side=side,
                        feature_type=feature_type,
                        availability=availability,
                        tick_start=observed_tick,
                        tick_end=observed_tick,
                        payload=ZoneDistributionPayload(
                            checkpoint_label=label,
                            requested_tick=target,
                            observed_tick=observed_tick,
                            players=tuple(player_evidence),
                        ),
                        evidence_snapshot_ids=tuple(evidence_ids),
                        limitations=(
                            ("partial_zone_coverage",)
                            if availability is FeatureAvailability.PARTIAL
                            else ()
                        ),
                    )
                )
        return tuple(result)

    def _first_contact(
        self,
        round_item: CanonicalRound,
        events: RoundEvents,
        timeline: RoundTimeline,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
    ) -> tuple[_Draft, ...]:
        participants = _analytics_participants(timeline)
        candidates: list[ContactCandidate] = []
        for damage_event in events.damages:
            candidate = _damage_contact(damage_event, participants)
            if candidate is not None:
                candidates.append(_contact_with_zones(candidate, snapshots, assignments))
        for kill_event in events.kills:
            classified = classify_kill(kill_event, participants)
            if classified.is_valid_enemy:
                candidate = _kill_contact(kill_event, participants)
                if candidate is not None:
                    candidates.append(_contact_with_zones(candidate, snapshots, assignments))
        if not candidates:
            return tuple(
                _unavailable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.FIRST_CONTACT,
                    "no_proven_enemy_contact",
                )
                for team_id, side in _round_teams(round_item)
            )
        first_tick = min(item.tick for item in candidates)
        first = tuple(
            sorted(
                (item for item in candidates if item.tick == first_tick),
                key=lambda item: str(item.event_id),
            )
        )
        result: list[_Draft] = []
        roles: dict[tuple[UUID, Side, str], list[ContactCandidate]] = defaultdict(list)
        for item in first:
            roles[(item.actor_team_id, item.actor_side, "initiator")].append(item)
            roles[(item.victim_team_id, item.victim_side, "receiver")].append(item)
        for (team_id, side, role), role_candidates in sorted(
            roles.items(), key=lambda item: (item[0][1].value, str(item[0][0]), item[0][2])
        ):
            zone_values = {
                (candidate.actor_zone_id, candidate.actor_zone_name)
                if role == "initiator"
                else (candidate.victim_zone_id, candidate.victim_zone_name)
                for candidate in role_candidates
            }
            proven_zones = {item for item in zone_values if item[0] is not None}
            zone_id, zone_name = (
                next(iter(proven_zones)) if len(proven_zones) == 1 else (None, None)
            )
            snapshot_ids = tuple(
                sorted(
                    {
                        snapshot_id
                        for candidate in role_candidates
                        for snapshot_id in (
                            candidate.actor_snapshot_id,
                            candidate.victim_snapshot_id,
                        )
                        if snapshot_id is not None
                    },
                    key=str,
                )
            )
            partial = len(first) > 1 or any(item[0] is None for item in zone_values)
            result.append(
                _Draft(
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=team_id,
                    side=side,
                    feature_type=RoundFeatureType.FIRST_CONTACT,
                    availability=(
                        FeatureAvailability.PARTIAL if partial else FeatureAvailability.AVAILABLE
                    ),
                    tick_start=first_tick,
                    tick_end=first_tick,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    payload=FirstContactPayload(
                        role=cast(Literal["initiator", "receiver"], role),
                        candidates=tuple(role_candidates),
                    ),
                    evidence_event_ids=tuple(item.event_id for item in role_candidates),
                    evidence_snapshot_ids=snapshot_ids,
                    limitations=tuple(
                        value
                        for condition, value in (
                            (len(first) > 1, "same_tick_contact_order_not_proven"),
                            (any(item[0] is None for item in zone_values), "contact_zone_partial"),
                        )
                        if condition
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _opening_duel(
        round_item: CanonicalRound,
        timeline: RoundTimeline,
        analytics: RoundAnalyticsView | None,
        teams: tuple[tuple[UUID, Side], ...],
    ) -> tuple[_Draft, ...]:
        opening = analytics.opening_duel if analytics is not None else None
        if opening is None:
            return tuple(
                _not_applicable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.OPENING_DUEL,
                    "no_valid_enemy_kill_observed",
                )
                for team_id, side in teams
            )
        group = next(
            (
                item
                for item in timeline.simultaneous_groups
                if opening.event_id in item.ordered_event_ids
            ),
            None,
        )
        ambiguous = (
            group is not None
            and group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
        )
        return tuple(
            _Draft(
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                team_id=team_id,
                side=side,
                feature_type=RoundFeatureType.OPENING_DUEL,
                availability=(
                    FeatureAvailability.PARTIAL if ambiguous else FeatureAvailability.AVAILABLE
                ),
                tick_start=opening.tick,
                tick_end=opening.tick,
                payload=OpeningDuelPayload(
                    role="winner" if team_id == opening.killer_team_id else "loser",
                    killer_player_id=opening.opening_killer_player_id,
                    victim_player_id=opening.opening_victim_player_id,
                    event_id=opening.event_id,
                    ordering_status=("same_tick_ambiguous" if ambiguous else "proven"),
                ),
                evidence_event_ids=(opening.event_id,),
                limitations=(
                    ("analytics_uuid_tiebreak_is_not_physical_order",) if ambiguous else ()
                ),
            )
            for team_id, side in teams
        )

    @staticmethod
    def _first_utility(
        round_item: CanonicalRound,
        grenades: tuple[CanonicalGrenade, ...],
        teams: tuple[tuple[UUID, Side], ...],
        zone_set: ZoneSetDefinition | None,
    ) -> tuple[_Draft, ...]:
        result: list[_Draft] = []
        for team_id, side in teams:
            values = tuple(
                item
                for item in grenades
                if item.phase is EventPhase.LIVE
                and item.team_id == team_id
                and item.player_id is not None
                and item.lifecycle_event != "expired"
            )
            if not values:
                result.append(
                    _unavailable(
                        round_item,
                        team_id,
                        side,
                        RoundFeatureType.FIRST_UTILITY,
                        "no_canonical_utility_observation",
                    )
                )
                continue
            first_tick = min(item.tick for item in values)
            first = tuple(
                sorted(
                    (item for item in values if item.tick == first_tick),
                    key=lambda item: str(item.event_id),
                )
            )
            candidates: list[UtilityCandidate] = []
            for item in first:
                resolution = (
                    resolve_zone(zone_set, item.x, item.y, item.z)
                    if zone_set is not None and item.x is not None and item.y is not None
                    else None
                )
                candidates.append(
                    UtilityCandidate(
                        event_id=item.event_id,
                        tick=item.tick,
                        player_id=item.player_id,
                        grenade_type=item.grenade_type,
                        lifecycle_event=item.lifecycle_event,
                        zone_id=(
                            resolution.zone_id
                            if resolution is not None
                            and resolution.status is ZoneResolutionStatus.RESOLVED
                            else None
                        ),
                        zone_name=(
                            resolution.zone_name
                            if resolution is not None
                            and resolution.status is ZoneResolutionStatus.RESOLVED
                            else None
                        ),
                    )
                )
            zone_values = {
                (item.zone_id, item.zone_name) for item in candidates if item.zone_id is not None
            }
            zone_id, zone_name = next(iter(zone_values)) if len(zone_values) == 1 else (None, None)
            thrown = all(item.lifecycle_event in {"thrown", "throw"} for item in first)
            result.append(
                _Draft(
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=team_id,
                    side=side,
                    feature_type=RoundFeatureType.FIRST_UTILITY,
                    availability=(
                        FeatureAvailability.AVAILABLE
                        if thrown and len(first) == 1 and zone_id is not None
                        else FeatureAvailability.PARTIAL
                    ),
                    tick_start=first_tick,
                    tick_end=first_tick,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    payload=FirstUtilityPayload(candidates=tuple(candidates)),
                    evidence_event_ids=tuple(item.event_id for item in first),
                    limitations=tuple(
                        value
                        for condition, value in (
                            (not thrown, "source_observes_effect_not_throw_tick"),
                            (len(first) > 1, "same_tick_utility_order_not_proven"),
                            (zone_id is None, "utility_zone_unresolved"),
                        )
                        if condition
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _early_zone_presence(
        round_item: CanonicalRound,
        timeline: RoundTimeline,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
        teams: tuple[tuple[UUID, Side], ...],
        config: RoundFeatureConfig,
    ) -> tuple[_Draft, ...]:
        if round_item.freeze_end_tick is None:
            return tuple(
                _unavailable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.EARLY_ZONE_PRESENCE,
                    "freeze_end_tick_unavailable",
                )
                for team_id, side in teams
            )
        end_tick = round_item.freeze_end_tick + config.early_window_ticks
        if timeline.effective_end_tick is not None:
            end_tick = min(end_tick, timeline.effective_end_tick)
        result: list[_Draft] = []
        for team_id, side in teams:
            first_by_zone: dict[
                str,
                tuple[ZoneAssignment, SpatialSnapshot, set[UUID], set[UUID]],
            ] = {}
            for snapshot in snapshots:
                if (
                    snapshot.physical_team_id != team_id
                    or snapshot.tick < round_item.freeze_end_tick
                    or snapshot.tick > end_tick
                ):
                    continue
                assignment = assignments.get(snapshot.snapshot_id)
                if assignment is None or assignment.status is not ZoneAssignmentStatus.RESOLVED:
                    continue
                assert assignment.zone_id is not None
                existing = first_by_zone.get(assignment.zone_id)
                if existing is None or snapshot.tick < existing[1].tick:
                    first_by_zone[assignment.zone_id] = (
                        assignment,
                        snapshot,
                        {snapshot.participant_id},
                        {snapshot.snapshot_id},
                    )
                elif snapshot.tick == existing[1].tick:
                    existing[2].add(snapshot.participant_id)
                    existing[3].add(snapshot.snapshot_id)
            if not first_by_zone:
                result.append(
                    _unavailable(
                        round_item,
                        team_id,
                        side,
                        RoundFeatureType.EARLY_ZONE_PRESENCE,
                        "no_resolved_early_zone_observation",
                        tick=round_item.freeze_end_tick,
                    )
                )
                continue
            for zone_id, (assignment, snapshot, players, evidence_ids) in sorted(
                first_by_zone.items()
            ):
                result.append(
                    _Draft(
                        round_id=round_item.round_id,
                        round_number=round_item.round_number,
                        team_id=team_id,
                        side=side,
                        feature_type=RoundFeatureType.EARLY_ZONE_PRESENCE,
                        availability=FeatureAvailability.AVAILABLE,
                        tick_start=snapshot.tick,
                        tick_end=snapshot.tick,
                        zone_id=zone_id,
                        zone_name=assignment.zone_name,
                        payload=EarlyZonePresencePayload(
                            first_observed_tick=snapshot.tick,
                            player_ids=tuple(sorted(players, key=str)),
                        ),
                        evidence_snapshot_ids=tuple(sorted(evidence_ids, key=str)),
                        limitations=("positive_presence_only_absence_not_proven",),
                    )
                )
        return tuple(result)

    @staticmethod
    def _bomb_route(
        round_item: CanonicalRound,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
    ) -> tuple[_Draft, ...]:
        if round_item.t_team_id is None:
            return ()
        bomb = tuple(item for item in snapshots if item.has_bomb is True)
        stops: list[BombRouteStop] = []
        unresolved = 0
        last_zone: str | None = None
        for snapshot in bomb:
            assignment = assignments.get(snapshot.snapshot_id)
            if assignment is None or assignment.status is not ZoneAssignmentStatus.RESOLVED:
                unresolved += 1
                continue
            assert assignment.zone_id is not None and assignment.zone_name is not None
            if assignment.zone_id == last_zone:
                continue
            stops.append(
                BombRouteStop(
                    tick=snapshot.tick,
                    zone_id=assignment.zone_id,
                    zone_name=assignment.zone_name,
                    carrier_player_id=snapshot.participant_id,
                    snapshot_id=snapshot.snapshot_id,
                )
            )
            last_zone = assignment.zone_id
        if not stops:
            return (
                _unavailable(
                    round_item,
                    round_item.t_team_id,
                    Side.T,
                    RoundFeatureType.BOMB_ROUTE,
                    "no_resolved_bomb_carrier_zone",
                    snapshot_ids=tuple(item.snapshot_id for item in bomb),
                ),
            )
        return (
            _Draft(
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                team_id=round_item.t_team_id,
                side=Side.T,
                feature_type=RoundFeatureType.BOMB_ROUTE,
                availability=(
                    FeatureAvailability.PARTIAL if unresolved else FeatureAvailability.AVAILABLE
                ),
                tick_start=stops[0].tick,
                tick_end=stops[-1].tick,
                zone_id=stops[-1].zone_id,
                zone_name=stops[-1].zone_name,
                payload=BombRoutePayload(stops=tuple(stops)),
                evidence_snapshot_ids=tuple(item.snapshot_id for item in bomb),
                limitations=(("bomb_route_has_zone_gaps",) if unresolved else ()),
            ),
        )

    def _plant_features(
        self,
        data: RoundFeatureMatchInput,
        round_item: CanonicalRound,
        bomb_events: tuple[CanonicalBombEvent, ...],
        timeline: RoundTimeline,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
        teams: tuple[tuple[UUID, Side], ...],
    ) -> tuple[_Draft, ...]:
        if round_item.t_team_id is None:
            return ()
        plants = tuple(
            sorted(
                (
                    item
                    for item in bomb_events
                    if item.phase is EventPhase.LIVE and item.event_type == "planted"
                ),
                key=lambda item: (item.tick, str(item.event_id)),
            )
        )
        if not plants:
            absent: list[_Draft] = [
                _not_applicable(
                    round_item,
                    round_item.t_team_id,
                    Side.T,
                    feature_type,
                    "no_plant_observed",
                )
                for feature_type in (
                    RoundFeatureType.BOMBSITE,
                    RoundFeatureType.PLANT_TIMING,
                )
            ]
            absent.extend(
                _not_applicable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.POST_PLANT_ROSTER,
                    "no_plant_observed",
                )
                for team_id, side in teams
            )
            if round_item.ct_team_id is not None:
                absent.append(
                    _not_applicable(
                        round_item,
                        round_item.ct_team_id,
                        Side.CT,
                        RoundFeatureType.RETAKE_ATTEMPT,
                        "no_plant_observed",
                    )
                )
            return tuple(absent)
        first_tick = plants[0].tick
        first = tuple(item for item in plants if item.tick == first_tick)
        plant = first[0]
        planter_snapshot, plant_assignment = _player_zone(
            plant.player_id, plant.tick, snapshots, assignments
        )
        canonical_site = (
            plant.site_normalized.upper()
            if plant.site_normalized and plant.site_normalized.upper() in {"A", "B"}
            else None
        )
        site = canonical_site or _site_from_assignment(plant_assignment)
        site_resolved = canonical_site is not None or (
            plant_assignment is not None and plant_assignment.kind is ZoneKind.BOMBSITE
        )
        zone_id = plant_assignment.zone_id if plant_assignment else None
        zone_name = plant_assignment.zone_name if plant_assignment else None
        ambiguity = len(first) > 1
        result: list[_Draft] = [
            _Draft(
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                team_id=round_item.t_team_id,
                side=Side.T,
                feature_type=RoundFeatureType.BOMBSITE,
                availability=(
                    FeatureAvailability.PARTIAL
                    if ambiguity or not site_resolved
                    else FeatureAvailability.AVAILABLE
                ),
                tick_start=plant.tick,
                tick_end=plant.tick,
                zone_id=zone_id,
                zone_name=zone_name,
                payload=BombsitePayload(
                    site=site,
                    plant_event_id=plant.event_id,
                    planter_player_id=plant.player_id,
                    resolution_source=(
                        "canonical_bomb_event.site_normalized"
                        if canonical_site is not None
                        else "pinned_zone_assignment"
                        if site_resolved
                        else "unresolved"
                    ),
                ),
                evidence_event_ids=tuple(item.event_id for item in first),
                evidence_snapshot_ids=((planter_snapshot.snapshot_id,) if planter_snapshot else ()),
                limitations=tuple(
                    value
                    for condition, value in (
                        (ambiguity, "multiple_same_tick_plant_events"),
                        (not site_resolved, "plant_site_unresolved"),
                    )
                    if condition
                ),
            )
        ]
        relative_tick = (
            plant.tick - round_item.freeze_end_tick
            if round_item.freeze_end_tick is not None and plant.tick >= round_item.freeze_end_tick
            else None
        )
        tickrate = data.temporal.config.tickrate
        seconds = relative_tick / tickrate if relative_tick is not None and tickrate else None
        result.append(
            _Draft(
                round_id=round_item.round_id,
                round_number=round_item.round_number,
                team_id=round_item.t_team_id,
                side=Side.T,
                feature_type=RoundFeatureType.PLANT_TIMING,
                availability=(
                    FeatureAvailability.AVAILABLE
                    if relative_tick is not None and not ambiguity
                    else FeatureAvailability.PARTIAL
                ),
                tick_start=plant.tick,
                tick_end=plant.tick,
                zone_id=zone_id,
                zone_name=zone_name,
                payload=PlantTimingPayload(
                    plant_event_id=plant.event_id,
                    planter_player_id=plant.player_id,
                    relative_tick=relative_tick,
                    seconds_from_freeze_end=seconds,
                    seconds_source=(
                        data.temporal.config.tickrate_source if seconds is not None else None
                    ),
                ),
                evidence_event_ids=tuple(item.event_id for item in first),
                evidence_snapshot_ids=((planter_snapshot.snapshot_id,) if planter_snapshot else ()),
                limitations=tuple(
                    value
                    for condition, value in (
                        (relative_tick is None, "freeze_end_relative_tick_unavailable"),
                        (seconds is None, "seconds_unavailable_without_proven_tickrate"),
                        (ambiguity, "multiple_same_tick_plant_events"),
                    )
                    if condition
                ),
            )
        )
        try:
            post_plant = SnapshotBuilder().at_tick(timeline, plant.tick, data.temporal.config)
        except ValueError:
            post_plant = None
        for team_id, side in teams:
            participants = {
                item.player_id
                for item in timeline.participants
                if item.physical_team_id == team_id
                and item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
            }
            if post_plant is None or post_plant.state_status is SnapshotStateStatus.UNAVAILABLE:
                result.append(
                    _unavailable(
                        round_item,
                        team_id,
                        side,
                        RoundFeatureType.POST_PLANT_ROSTER,
                        "post_plant_temporal_state_unavailable",
                        tick=plant.tick,
                        event_ids=(plant.event_id,),
                    )
                )
                continue
            alive = tuple(sorted(participants & set(post_plant.alive_players), key=str))
            dead = tuple(sorted(participants & set(post_plant.dead_players), key=str))
            unknown = tuple(sorted(participants & set(post_plant.unknown_players), key=str))
            result.append(
                _Draft(
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=team_id,
                    side=side,
                    feature_type=RoundFeatureType.POST_PLANT_ROSTER,
                    availability=(
                        FeatureAvailability.PARTIAL if unknown else FeatureAvailability.AVAILABLE
                    ),
                    tick_start=plant.tick,
                    tick_end=plant.tick,
                    zone_id=zone_id,
                    zone_name=zone_name,
                    payload=PostPlantRosterPayload(
                        alive_player_ids=alive,
                        dead_player_ids=dead,
                        unknown_player_ids=unknown,
                    ),
                    evidence_event_ids=(plant.event_id,),
                    limitations=(("participant_life_state_partial",) if unknown else ()),
                )
            )
        if round_item.ct_team_id is not None:
            result.append(
                self._retake_attempt(
                    round_item,
                    plant,
                    timeline,
                    snapshots,
                    assignments,
                    plant_assignment,
                )
            )
        return tuple(result)

    @staticmethod
    def _retake_attempt(
        round_item: CanonicalRound,
        plant: CanonicalBombEvent,
        timeline: RoundTimeline,
        snapshots: tuple[SpatialSnapshot, ...],
        assignments: dict[UUID, ZoneAssignment],
        plant_assignment: ZoneAssignment | None,
    ) -> _Draft:
        assert round_item.ct_team_id is not None
        if (
            plant_assignment is None
            or plant_assignment.status is not ZoneAssignmentStatus.RESOLVED
            or plant_assignment.kind is not ZoneKind.BOMBSITE
            or plant_assignment.zone_id is None
        ):
            return _unavailable(
                round_item,
                round_item.ct_team_id,
                Side.CT,
                RoundFeatureType.RETAKE_ATTEMPT,
                "planted_bombsite_zone_unresolved",
                tick=plant.tick,
                event_ids=(plant.event_id,),
            )
        ct_players = {
            item.player_id
            for item in timeline.participants
            if item.physical_team_id == round_item.ct_team_id
            and item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
        }
        initial: dict[UUID, tuple[str, UUID]] = {}
        for player_id in ct_players:
            snapshot, assignment = _player_zone(player_id, plant.tick, snapshots, assignments)
            if (
                snapshot is not None
                and snapshot.alive is True
                and assignment is not None
                and assignment.zone_id is not None
            ):
                initial[player_id] = (assignment.zone_id, snapshot.snapshot_id)
        entrants: dict[UUID, SpatialSnapshot] = {}
        for snapshot in snapshots:
            if (
                snapshot.tick <= plant.tick
                or snapshot.participant_id not in initial
                or snapshot.alive is not True
            ):
                continue
            if initial[snapshot.participant_id][0] == plant_assignment.zone_id:
                continue
            assignment = assignments.get(snapshot.snapshot_id)
            if assignment is not None and assignment.zone_id == plant_assignment.zone_id:
                entrants.setdefault(snapshot.participant_id, snapshot)
        if not entrants:
            return _unavailable(
                round_item,
                round_item.ct_team_id,
                Side.CT,
                RoundFeatureType.RETAKE_ATTEMPT,
                "negative_retake_not_proven_with_partial_zone_coverage",
                tick=plant.tick,
                event_ids=(plant.event_id,),
            )
        first_tick = min(item.tick for item in entrants.values())
        evidence = tuple(
            sorted(
                {
                    snapshot_id
                    for player_id, item in entrants.items()
                    for snapshot_id in (
                        initial[player_id][1],
                        item.snapshot_id,
                    )
                },
                key=str,
            )
        )
        return _Draft(
            round_id=round_item.round_id,
            round_number=round_item.round_number,
            team_id=round_item.ct_team_id,
            side=Side.CT,
            feature_type=RoundFeatureType.RETAKE_ATTEMPT,
            availability=FeatureAvailability.AVAILABLE,
            tick_start=plant.tick,
            tick_end=first_tick,
            zone_id=plant_assignment.zone_id,
            zone_name=plant_assignment.zone_name,
            payload=RetakeAttemptPayload(
                attempted=True,
                site_zone_id=plant_assignment.zone_id,
                entering_player_ids=tuple(sorted(entrants, key=str)),
            ),
            evidence_event_ids=(plant.event_id,),
            evidence_snapshot_ids=evidence,
            limitations=("positive_exact_site_entry_rule_v1",),
        )

    @staticmethod
    def _lost_advantage(
        round_item: CanonicalRound,
        timeline: RoundTimeline,
        analytics: RoundAnalyticsView | None,
    ) -> tuple[_Draft, ...]:
        if analytics is None:
            return tuple(
                _unavailable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.LOST_MAN_ADVANTAGE,
                    "pinned_analytics_round_unavailable",
                )
                for team_id, side in _round_teams(round_item)
            )
        result: list[_Draft] = []
        lost_by_team: set[UUID] = set()
        for transition in analytics.man_advantage_transitions:
            if transition.advantage_before is AdvantageState.T_ADVANTAGE:
                team_id, side = round_item.t_team_id, Side.T
                still_advantaged = transition.advantage_after is AdvantageState.T_ADVANTAGE
            elif transition.advantage_before is AdvantageState.CT_ADVANTAGE:
                team_id, side = round_item.ct_team_id, Side.CT
                still_advantaged = transition.advantage_after is AdvantageState.CT_ADVANTAGE
            else:
                continue
            if team_id is None or still_advantaged:
                continue
            lost_by_team.add(team_id)
            group = next(
                (item for item in timeline.simultaneous_groups if item.tick == transition.tick),
                None,
            )
            ambiguous = (
                group is not None
                and group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
            )
            result.append(
                _Draft(
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=team_id,
                    side=side,
                    feature_type=RoundFeatureType.LOST_MAN_ADVANTAGE,
                    availability=(
                        FeatureAvailability.PARTIAL if ambiguous else FeatureAvailability.AVAILABLE
                    ),
                    tick_start=transition.tick,
                    tick_end=transition.tick,
                    payload=LostAdvantagePayload(
                        event_id=transition.event_id,
                        t_alive_before=transition.t_alive_before,
                        t_alive_after=transition.t_alive_after,
                        ct_alive_before=transition.ct_alive_before,
                        ct_alive_after=transition.ct_alive_after,
                        advantage_before=transition.advantage_before.value,
                        advantage_after=transition.advantage_after.value,
                        event_classification=transition.event_classification.value,
                    ),
                    evidence_event_ids=(transition.event_id,),
                    limitations=tuple(
                        value
                        for condition, value in (
                            (ambiguous, "same_tick_intermediate_advantage_ambiguous"),
                            (
                                transition.event_classification.value
                                in {"teamkill", "suicide", "world"},
                                "advantage_includes_all_first_death_effects_by_analytics_rule",
                            ),
                        )
                        if condition
                    ),
                )
            )
        for team_id, side in _round_teams(round_item):
            if team_id not in lost_by_team:
                result.append(
                    _not_applicable(
                        round_item,
                        team_id,
                        side,
                        RoundFeatureType.LOST_MAN_ADVANTAGE,
                        "no_observed_advantage_loss",
                    )
                )
        return tuple(result)

    @staticmethod
    def _untraded_deaths(
        data: RoundFeatureMatchInput,
        round_item: CanonicalRound,
        kills: tuple[CanonicalKill, ...],
        timeline: RoundTimeline,
        analytics: RoundAnalyticsView | None,
    ) -> tuple[_Draft, ...]:
        if analytics is None or data.analytics.config.resolved_trade_window_ticks is None:
            return tuple(
                _unavailable(
                    round_item,
                    team_id,
                    side,
                    RoundFeatureType.UNTRADED_DEATH,
                    "pinned_trade_semantics_unavailable",
                )
                for team_id, side in _round_teams(round_item)
            )
        participants = _analytics_participants(timeline)
        traded = {item.original_kill_event_id for item in analytics.trade_events}
        window = data.analytics.config.resolved_trade_window_ticks
        result: list[_Draft] = []
        deaths_by_team: Counter[UUID] = Counter()
        for kill in sorted(kills, key=lambda item: (item.tick, str(item.event_id))):
            classified = classify_kill(kill, participants)
            if not classified.is_valid_enemy or kill.event_id in traded:
                continue
            assert kill.victim_player_id is not None and kill.attacker_player_id is not None
            victim = participants[kill.victim_player_id]
            deaths_by_team[victim.team_id] += 1
            group = next(
                (item for item in timeline.simultaneous_groups if item.tick == kill.tick),
                None,
            )
            ambiguous = (
                group is not None
                and group.intermediate_state_status is not IntermediateStateStatus.DETERMINISTIC
            )
            result.append(
                _Draft(
                    round_id=round_item.round_id,
                    round_number=round_item.round_number,
                    team_id=victim.team_id,
                    side=victim.side,
                    feature_type=RoundFeatureType.UNTRADED_DEATH,
                    availability=(
                        FeatureAvailability.PARTIAL if ambiguous else FeatureAvailability.AVAILABLE
                    ),
                    tick_start=kill.tick,
                    tick_end=kill.tick + window,
                    payload=UntradedDeathPayload(
                        kill_event_id=kill.event_id,
                        attacker_player_id=kill.attacker_player_id,
                        victim_player_id=kill.victim_player_id,
                        trade_window_ticks=window,
                    ),
                    evidence_event_ids=(kill.event_id,),
                    limitations=(("same_tick_trade_order_not_proven",) if ambiguous else ()),
                )
            )
        for team_id, side in _round_teams(round_item):
            if deaths_by_team[team_id] == 0:
                result.append(
                    _not_applicable(
                        round_item,
                        team_id,
                        side,
                        RoundFeatureType.UNTRADED_DEATH,
                        "no_untraded_enemy_death_under_pinned_trade_rule",
                    )
                )
        return tuple(result)

    @staticmethod
    def _validate_inputs(data: RoundFeatureMatchInput) -> None:
        fingerprints = {
            data.dataset_fingerprint,
            data.analytics.dataset_fingerprint,
            data.temporal.dataset_fingerprint,
            data.spatial.dataset_fingerprint,
            data.zones.dataset_fingerprint,
        }
        if data.economy is not None:
            fingerprints.add(data.economy.dataset_fingerprint)
        if len(fingerprints) != 1:
            raise ValueError("feature inputs do not share one canonical dataset fingerprint")
        if data.spatial.temporal_run_id != data.temporal.temporal_run_id:
            raise ValueError("spatial input is not derived from the pinned temporal run")
        if data.zones.spatial_run_id != data.spatial.spatial_run_id:
            raise ValueError("zone input is not derived from the pinned spatial run")
        if data.zone_set is not None:
            if data.zones.zone_set_fingerprint != data.zone_set.fingerprint():
                raise ValueError("loaded zone set does not match the pinned zone fingerprint")

    @staticmethod
    def _fingerprint(
        data: RoundFeatureMatchInput,
        config: RoundFeatureConfig,
        drafts: tuple[_Draft, ...],
    ) -> str:
        payload = {
            "feature_schema_version": ROUND_FEATURE_SCHEMA_VERSION,
            "feature_rule_version": ROUND_FEATURE_RULE_VERSION,
            "match_id": str(data.match_id),
            "dataset_fingerprint": data.dataset_fingerprint,
            "analytics_fingerprint": data.analytics.analytics_fingerprint,
            "temporal_fingerprint": data.temporal.temporal_fingerprint,
            "spatial_fingerprint": data.spatial.spatial_fingerprint,
            "zone_assignment_fingerprint": data.zones.zone_assignment_fingerprint,
            "economy_fingerprint": (data.economy.economy_fingerprint if data.economy else None),
            "config": config.model_dump(mode="json"),
            "features": [_draft_json(item) for item in drafts],
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _round_teams(round_item: CanonicalRound) -> tuple[tuple[UUID, Side], ...]:
    return tuple(
        (team_id, side)
        for team_id, side in (
            (round_item.t_team_id, Side.T),
            (round_item.ct_team_id, Side.CT),
        )
        if team_id is not None
    )


def _analytics_participants(timeline: RoundTimeline) -> dict[UUID, Participant]:
    return {
        item.player_id: Participant(item.player_id, item.physical_team_id, item.side)
        for item in timeline.participants
        if item.physical_team_id is not None
        and item.side in {Side.T, Side.CT}
        and item.participation_status is not ParticipationStatus.NOT_PARTICIPATING
    }


def _damage_contact(
    event: CanonicalDamage,
    participants: dict[UUID, Participant],
) -> ContactCandidate | None:
    if (
        event.phase is not EventPhase.LIVE
        or not event.damage_health
        or event.attacker_player_id not in participants
        or event.victim_player_id not in participants
    ):
        return None
    assert event.attacker_player_id is not None and event.victim_player_id is not None
    actor = participants[event.attacker_player_id]
    victim = participants[event.victim_player_id]
    if actor.team_id == victim.team_id:
        return None
    if event.attacker_team_id not in {None, actor.team_id}:
        return None
    if event.victim_team_id not in {None, victim.team_id}:
        return None
    return ContactCandidate(
        event_id=event.event_id,
        event_kind="damage",
        tick=event.tick,
        actor_player_id=actor.player_id,
        victim_player_id=victim.player_id,
        actor_team_id=actor.team_id,
        victim_team_id=victim.team_id,
        actor_side=actor.side,
        victim_side=victim.side,
    )


def _kill_contact(
    event: CanonicalKill,
    participants: dict[UUID, Participant],
) -> ContactCandidate | None:
    if event.attacker_player_id is None or event.victim_player_id is None:
        return None
    actor = participants[event.attacker_player_id]
    victim = participants[event.victim_player_id]
    return ContactCandidate(
        event_id=event.event_id,
        event_kind="death",
        tick=event.tick,
        actor_player_id=actor.player_id,
        victim_player_id=victim.player_id,
        actor_team_id=actor.team_id,
        victim_team_id=victim.team_id,
        actor_side=actor.side,
        victim_side=victim.side,
    )


def _contact_with_zones(
    candidate: ContactCandidate,
    snapshots: tuple[SpatialSnapshot, ...],
    assignments: dict[UUID, ZoneAssignment],
) -> ContactCandidate:
    actor_snapshot, actor_assignment = _player_zone(
        candidate.actor_player_id, candidate.tick, snapshots, assignments
    )
    victim_snapshot, victim_assignment = _player_zone(
        candidate.victim_player_id, candidate.tick, snapshots, assignments
    )
    return candidate.model_copy(
        update={
            "actor_zone_id": actor_assignment.zone_id if actor_assignment else None,
            "actor_zone_name": actor_assignment.zone_name if actor_assignment else None,
            "victim_zone_id": victim_assignment.zone_id if victim_assignment else None,
            "victim_zone_name": victim_assignment.zone_name if victim_assignment else None,
            "actor_snapshot_id": actor_snapshot.snapshot_id if actor_snapshot else None,
            "victim_snapshot_id": victim_snapshot.snapshot_id if victim_snapshot else None,
        }
    )


def _player_zone(
    player_id: UUID | None,
    tick: int,
    snapshots: tuple[SpatialSnapshot, ...],
    assignments: dict[UUID, ZoneAssignment],
) -> tuple[SpatialSnapshot | None, ZoneAssignment | None]:
    if player_id is None:
        return None, None
    snapshot = next(
        (item for item in snapshots if item.tick == tick and item.participant_id == player_id),
        None,
    )
    if snapshot is None:
        return None, None
    assignment = assignments.get(snapshot.snapshot_id)
    if assignment is None or assignment.status is not ZoneAssignmentStatus.RESOLVED:
        return snapshot, None
    return snapshot, assignment


def _site_from_assignment(assignment: ZoneAssignment | None) -> str | None:
    if assignment is None or assignment.kind is not ZoneKind.BOMBSITE:
        return None
    value = f"{assignment.zone_id or ''} {assignment.zone_name or ''}".casefold()
    tokens = set(value.replace("_", " ").replace("-", " ").split())
    if "a" in tokens:
        return "A"
    if "b" in tokens:
        return "B"
    return None


def _checkpoint_tick(
    snapshots: tuple[SpatialSnapshot, ...], target: int, tolerance: int
) -> int | None:
    ticks = sorted({item.tick for item in snapshots if item.tick >= target})
    if not ticks or ticks[0] - target > tolerance:
        return None
    return ticks[0]


def _unavailable(
    round_item: CanonicalRound,
    team_id: UUID,
    side: Side,
    feature_type: RoundFeatureType,
    reason: str,
    *,
    tick: int | None = None,
    event_ids: tuple[UUID, ...] = (),
    snapshot_ids: tuple[UUID, ...] = (),
) -> _Draft:
    return _Draft(
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        team_id=team_id,
        side=side,
        feature_type=feature_type,
        availability=FeatureAvailability.UNAVAILABLE,
        tick_start=tick,
        tick_end=tick,
        evidence_event_ids=event_ids,
        evidence_snapshot_ids=snapshot_ids,
        limitations=(reason,),
    )


def _not_applicable(
    round_item: CanonicalRound,
    team_id: UUID,
    side: Side,
    feature_type: RoundFeatureType,
    reason: str,
) -> _Draft:
    return _Draft(
        round_id=round_item.round_id,
        round_number=round_item.round_number,
        team_id=team_id,
        side=side,
        feature_type=feature_type,
        availability=FeatureAvailability.NOT_APPLICABLE,
        limitations=(reason,),
    )


def _draft_json(draft: _Draft) -> dict[str, Any]:
    return {
        "round_id": str(draft.round_id),
        "round_number": draft.round_number,
        "team_id": str(draft.team_id),
        "side": draft.side.value,
        "feature_type": draft.feature_type.value,
        "availability": draft.availability.value,
        "tick_start": draft.tick_start,
        "tick_end": draft.tick_end,
        "zone_id": draft.zone_id,
        "zone_name": draft.zone_name,
        "payload": draft.payload.model_dump(mode="json") if draft.payload else None,
        "evidence_event_ids": [str(item) for item in draft.evidence_event_ids],
        "evidence_snapshot_ids": [str(item) for item in draft.evidence_snapshot_ids],
        "limitations": draft.limitations,
        "warnings": draft.warnings,
    }


def _draft_key(draft: _Draft) -> tuple[object, ...]:
    return (
        draft.round_number,
        draft.side.value,
        str(draft.team_id),
        draft.feature_type.value,
        draft.tick_start if draft.tick_start is not None else -1,
        draft.tick_end if draft.tick_end is not None else -1,
        draft.zone_id or "",
        canonical_json(_draft_json(draft)),
    )


def _capabilities(
    features: tuple[RoundFeature, ...],
) -> dict[RoundFeatureType, FeatureTypeCapability]:
    result: dict[RoundFeatureType, FeatureTypeCapability] = {}
    for feature_type in RoundFeatureType:
        rows = tuple(item for item in features if item.feature_type is feature_type)
        counts = Counter(item.availability for item in rows)
        result[feature_type] = FeatureTypeCapability(
            population=len(rows),
            available=counts[FeatureAvailability.AVAILABLE],
            partial=counts[FeatureAvailability.PARTIAL],
            unavailable=counts[FeatureAvailability.UNAVAILABLE],
            not_applicable=counts[FeatureAvailability.NOT_APPLICABLE],
        )
    return result


__all__ = ["RoundFeatureEngine", "RoundFeatureMatchInput"]
