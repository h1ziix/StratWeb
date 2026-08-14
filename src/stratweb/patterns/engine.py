"""Pure deterministic aggregation of version-pinned per-round facts."""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.features.models import (
    BombRoutePayload,
    BombsitePayload,
    EarlyZonePresencePayload,
    FeatureAvailability,
    FirstContactPayload,
    FirstUtilityPayload,
    OpeningDuelPayload,
    PlantTimingPayload,
    RoundFeature,
    RoundFeatureType,
    ZoneDistributionPayload,
)
from stratweb.patterns.models import (
    PATTERN_RULE_VERSION,
    PATTERN_SCHEMA_VERSION,
    BinaryPatternValue,
    CategoricalPatternValue,
    CrossMatchPattern,
    CrossMatchPatternInput,
    PatternAvailability,
    PatternCapability,
    PatternConfig,
    PatternInputStatus,
    PatternMatchInput,
    PatternPlayerIdentity,
    PatternRoundEvidence,
    PatternRoundExclusion,
    PatternRoundInput,
    PatternScope,
    PatternState,
    PatternSummary,
    PatternType,
    PatternValue,
    PlayerPatternValue,
    RoutePatternValue,
    SetupPatternValue,
    TimingBucketPatternValue,
    WilsonConfidence,
    ZoneCount,
)

_UNSUPPORTED: dict[PatternType, str] = {
    PatternType.EARLY_ROTATION: "stage_8_4_first_ct_rotation_is_not_proven",
    PatternType.RETAKE_FREQUENCY: "negative_retake_attempt_is_not_proven",
    PatternType.SAVE_FREQUENCY: "save_intent_is_not_proven",
}


@dataclass(slots=True)
class _Observation:
    included: bool
    values: tuple[PatternValue, ...] = ()
    registered_values: tuple[PatternValue, ...] = ()
    features: tuple[RoundFeature, ...] = ()
    partial: bool = False
    reason: str | None = None
    limitations: tuple[str, ...] = ()


@dataclass(slots=True)
class _Opportunity:
    round_input: PatternRoundInput
    values: frozenset[str]
    evidence: PatternRoundEvidence
    partial: bool


@dataclass(slots=True)
class _Population:
    pattern_type: PatternType
    scope: PatternScope
    opportunities: list[_Opportunity] = field(default_factory=list)
    exclusions: list[PatternRoundExclusion] = field(default_factory=list)
    values: dict[str, PatternValue] = field(default_factory=dict)
    limitations: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class _Draft:
    pattern_type: PatternType
    scope: PatternScope
    value: PatternValue
    availability: PatternAvailability
    numerator: int
    denominator: int
    frequency: float
    confidence: WilsonConfidence
    numerator_match_count: int
    denominator_match_count: int
    evidence: tuple[PatternRoundEvidence, ...]
    included: tuple[PatternRoundEvidence, ...]
    excluded: tuple[PatternRoundExclusion, ...]
    limitations: tuple[str, ...]
    warnings: tuple[str, ...]


class CrossMatchPatternEngine:
    """Aggregate facts without inferring intent, causality, or recommendations."""

    def compute(
        self,
        data: CrossMatchPatternInput,
        config: PatternConfig | None = None,
    ) -> PatternState:
        selected_config = config or PatternConfig()
        inputs = tuple(sorted(data.inputs, key=lambda item: str(item.match_id)))
        if any(item.profile_id != data.profile_id for item in inputs):
            raise ValueError("pattern inputs do not share the requested opponent profile")

        populations: dict[tuple[str, str, str, str, str], _Population] = {}
        eligible_round_keys: set[tuple[UUID, int]] = set()
        for match in inputs:
            if match.status is PatternInputStatus.EXCLUDED:
                continue
            identities = {item.player_id: item for item in match.players}
            for round_input in sorted(match.rounds, key=lambda item: item.round_number):
                if round_input.is_warmup or not round_input.is_complete:
                    continue
                if round_input.team_id != match.team_id:
                    raise ValueError("round input team differs from confirmed opponent team")
                eligible_round_keys.add((round_input.match_id, round_input.round_number))
                assert match.feature_rule_version is not None
                scope = PatternScope(
                    map_name=match.map_name,
                    side=round_input.side,
                    buy_type=round_input.buy_type,
                    feature_rule_version=match.feature_rule_version,
                )
                for pattern_type, observation in self._round_observations(
                    round_input,
                    identities,
                    selected_config,
                ):
                    population = populations.setdefault(
                        _population_key(pattern_type, scope),
                        _Population(pattern_type=pattern_type, scope=scope),
                    )
                    for value in (*observation.registered_values, *observation.values):
                        population.values[_value_key(value)] = value
                    population.limitations.update(observation.limitations)
                    if not observation.included:
                        population.exclusions.append(
                            PatternRoundExclusion(
                                match_id=round_input.match_id,
                                round_id=round_input.round_id,
                                round_number=round_input.round_number,
                                reason=observation.reason or "pattern_evidence_unavailable",
                                feature_ids=tuple(
                                    sorted(
                                        (item.feature_id for item in observation.features),
                                        key=str,
                                    )
                                ),
                            )
                        )
                        continue
                    value_keys = frozenset(_value_key(item) for item in observation.values)
                    evidence = _evidence(round_input, observation.features, False)
                    population.opportunities.append(
                        _Opportunity(
                            round_input=round_input,
                            values=value_keys,
                            evidence=evidence,
                            partial=observation.partial,
                        )
                    )

        drafts = self._drafts(populations, selected_config)
        workspace_fingerprint = _sha256(
            {
                "profile_id": str(data.profile_id),
                "selections": [
                    {"match_id": str(item.match_id), "team_id": str(item.team_id)}
                    for item in inputs
                ],
            }
        )
        config_hash = _sha256(selected_config.model_dump(mode="json"))
        fingerprint = _sha256(
            {
                "schema": PATTERN_SCHEMA_VERSION,
                "rule": PATTERN_RULE_VERSION,
                "profile_id": str(data.profile_id),
                "workspace_fingerprint": workspace_fingerprint,
                "config": selected_config.model_dump(mode="json"),
                "inputs": [_input_fingerprint_payload(item) for item in inputs],
                "patterns": [_draft_payload(item) for item in drafts],
            }
        )
        run_id = uuid5(NAMESPACE_URL, f"stratweb:pattern-run:{fingerprint}")
        patterns = tuple(
            _materialize(run_id, data.profile_id, item, selected_config) for item in drafts
        )
        capabilities = _capabilities(populations, patterns)
        included_matches = sum(item.status is PatternInputStatus.INCLUDED for item in inputs)
        excluded_matches = len(inputs) - included_matches
        corpus_below = included_matches < selected_config.minimum_corpus_matches
        warnings: list[str] = []
        if corpus_below:
            warnings.append(
                "opponent_corpus_below_minimum:"
                f"{included_matches}/{selected_config.minimum_corpus_matches}"
            )
        warnings.extend(
            f"match_excluded:{item.match_id}:{item.exclusion_reason}"
            for item in inputs
            if item.status is PatternInputStatus.EXCLUDED
        )
        summary = PatternSummary(
            selected_matches=len(inputs),
            included_matches=included_matches,
            excluded_matches=excluded_matches,
            eligible_rounds=len(eligible_round_keys),
            patterns=len(patterns),
            available_patterns=sum(
                item.availability is PatternAvailability.AVAILABLE for item in patterns
            ),
            partial_patterns=sum(
                item.availability is PatternAvailability.PARTIAL for item in patterns
            ),
            maps=tuple(
                sorted(
                    {item.map_name for item in inputs if item.status is PatternInputStatus.INCLUDED}
                )
            ),
            corpus_below_minimum=corpus_below,
        )
        return PatternState(
            pattern_run_id=run_id,
            pattern_fingerprint=fingerprint,
            pattern_config_hash=config_hash,
            workspace_fingerprint=workspace_fingerprint,
            profile_id=data.profile_id,
            config=selected_config,
            inputs=inputs,
            capabilities=capabilities,
            summary=summary,
            patterns=patterns,
            warnings=tuple(warnings),
        )

    def _round_observations(
        self,
        round_input: PatternRoundInput,
        identities: dict[UUID, PatternPlayerIdentity],
        config: PatternConfig,
    ) -> tuple[tuple[PatternType, _Observation], ...]:
        features: dict[RoundFeatureType, tuple[RoundFeature, ...]] = defaultdict(tuple)
        grouped: dict[RoundFeatureType, list[RoundFeature]] = defaultdict(list)
        for feature in round_input.features:
            if feature.match_id != round_input.match_id or feature.round_id != round_input.round_id:
                raise ValueError("feature is outside its pattern round input")
            if feature.team_id != round_input.team_id or feature.side is not round_input.side:
                raise ValueError("feature is outside the confirmed opponent team/side")
            grouped[feature.feature_type].append(feature)
        features = {
            key: tuple(sorted(value, key=lambda item: str(item.feature_id)))
            for key, value in grouped.items()
        }
        result: list[tuple[PatternType, _Observation]] = []
        if round_input.side is Side.T:
            result.extend(
                (
                    (PatternType.SITE_PREFERENCE, _site(features, config)),
                    (
                        PatternType.BOMB_ROUTING,
                        _bomb_route(features, config),
                    ),
                    (
                        PatternType.PLANT_TIMING,
                        _plant_timing(features, config),
                    ),
                )
            )
        if round_input.side is Side.CT:
            result.append(
                (
                    PatternType.CT_STARTING_POSITION,
                    _ct_starting_setup(features, config),
                )
            )
        result.extend(
            (
                (
                    PatternType.EARLY_ZONE_OCCUPATION,
                    _early_zones(features, config),
                ),
                (
                    PatternType.RECURRING_OPENING_PLAYER,
                    _opening_player(features, identities, "winner", config),
                ),
                (
                    PatternType.RECURRING_OPENING_DEATH,
                    _opening_player(features, identities, "loser", config),
                ),
                (
                    PatternType.FIRST_CONTACT_ZONE,
                    _first_contact(features, config),
                ),
                (PatternType.FIRST_UTILITY, _first_utility(features, config)),
                (
                    PatternType.OPENING_KILL_CONVERSION,
                    _opening_outcome(features, round_input.opponent_won, "winner", config),
                ),
                (
                    PatternType.RECOVERY_AFTER_OPENING_DEATH,
                    _opening_outcome(features, round_input.opponent_won, "loser", config),
                ),
                (
                    PatternType.LOST_MAN_ADVANTAGE,
                    _binary_feature(
                        features,
                        RoundFeatureType.LOST_MAN_ADVANTAGE,
                        BinaryPatternValue(
                            key="round_contains_lost_man_advantage",
                            label="Round contained a lost man advantage",
                        ),
                        config,
                    ),
                ),
                (
                    PatternType.UNTRADED_DEATH,
                    _binary_feature(
                        features,
                        RoundFeatureType.UNTRADED_DEATH,
                        BinaryPatternValue(
                            key="round_contains_untraded_death",
                            label="Round contained an untraded death",
                        ),
                        config,
                    ),
                ),
            )
        )
        return tuple(result)

    @staticmethod
    def _drafts(
        populations: dict[tuple[str, str, str, str, str], _Population],
        config: PatternConfig,
    ) -> tuple[_Draft, ...]:
        result: list[_Draft] = []
        for population in sorted(populations.values(), key=_population_sort_key):
            denominator = len(population.opportunities)
            if denominator == 0:
                continue
            for value_key, value in sorted(population.values.items()):
                numerator_rows = tuple(
                    item for item in population.opportunities if value_key in item.values
                )
                numerator = len(numerator_rows)
                included = tuple(
                    item.evidence.model_copy(
                        update={"contributed_to_numerator": value_key in item.values}
                    )
                    for item in population.opportunities
                )
                evidence = tuple(
                    item.evidence.model_copy(update={"contributed_to_numerator": True})
                    for item in numerator_rows
                )
                partial = any(item.partial for item in population.opportunities)
                if population.scope.buy_type is None:
                    partial = True
                    population.limitations.add("buy_type_unavailable_group_kept_separate")
                if isinstance(value, PlayerPatternValue) and not value.cross_match_resolved:
                    partial = True
                    population.limitations.add(
                        "player_identity_is_match_occurrence_only_not_nickname_merged"
                    )
                warnings = ("small_sample",) if denominator < config.minimum_sample_size else ()
                result.append(
                    _Draft(
                        pattern_type=population.pattern_type,
                        scope=population.scope,
                        value=value,
                        availability=(
                            PatternAvailability.PARTIAL
                            if partial
                            else PatternAvailability.AVAILABLE
                        ),
                        numerator=numerator,
                        denominator=denominator,
                        frequency=numerator / denominator,
                        confidence=wilson_confidence(numerator, denominator),
                        numerator_match_count=len(
                            {item.round_input.match_id for item in numerator_rows}
                        ),
                        denominator_match_count=len(
                            {item.round_input.match_id for item in population.opportunities}
                        ),
                        evidence=evidence,
                        included=included,
                        excluded=tuple(
                            sorted(
                                population.exclusions,
                                key=lambda item: (
                                    str(item.match_id),
                                    item.round_number,
                                    item.reason,
                                ),
                            )
                        ),
                        limitations=tuple(sorted(population.limitations)),
                        warnings=warnings,
                    )
                )
        return tuple(result)


def wilson_confidence(numerator: int, denominator: int) -> WilsonConfidence:
    if denominator <= 0 or numerator < 0 or numerator > denominator:
        raise ValueError("Wilson interval requires 0 <= numerator <= denominator")
    z = 1.959963984540054
    proportion = numerator / denominator
    z_squared = z * z
    divisor = 1 + z_squared / denominator
    center = (proportion + z_squared / (2 * denominator)) / divisor
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator
            + z_squared / (4 * denominator * denominator)
        )
        / divisor
    )
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return WilsonConfidence(score=lower, lower_bound=lower, upper_bound=upper)


def _site(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.BOMBSITE, ())
    usable = _usable(rows, config)
    registered: tuple[PatternValue, ...] = tuple(
        CategoricalPatternValue(key=f"site:{site}", label=f"Bombsite {site}") for site in ("A", "B")
    )
    for row in usable:
        if isinstance(row.payload, BombsitePayload) and row.payload.site is not None:
            return _included(
                (
                    CategoricalPatternValue(
                        key=f"site:{row.payload.site}",
                        label=f"Bombsite {row.payload.site}",
                        zone_id=row.zone_id,
                        zone_name=row.zone_name,
                    ),
                ),
                usable,
                registered=registered,
            )
    return _excluded(rows, "plant_site_unavailable", registered=registered)


def _early_zones(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.EARLY_ZONE_PRESENCE, ())
    usable = _usable(rows, config)
    values: dict[str, PatternValue] = {}
    for row in usable:
        if isinstance(row.payload, EarlyZonePresencePayload) and row.zone_id and row.zone_name:
            value = CategoricalPatternValue(
                key=f"zone:{row.zone_id}",
                label=row.zone_name,
                zone_id=row.zone_id,
                zone_name=row.zone_name,
            )
            values[_value_key(value)] = value
    if values:
        return _included(
            tuple(values.values()),
            usable,
            extra_limitations=("frequency_is_conditional_on_observable_early_zone_rounds",),
        )
    return _excluded(rows, "early_zone_evidence_unavailable")


def _opening_player(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]],
    identities: dict[UUID, PatternPlayerIdentity],
    role: str,
    config: PatternConfig,
) -> _Observation:
    rows = features.get(RoundFeatureType.OPENING_DUEL, ())
    usable = _usable(rows, config)
    for row in usable:
        payload = row.payload
        if not isinstance(payload, OpeningDuelPayload) or payload.role != role:
            continue
        player_id = payload.killer_player_id if role == "winner" else payload.victim_player_id
        identity = identities.get(player_id)
        if identity is None:
            return _excluded(rows, "opening_player_identity_unavailable")
        value = PlayerPatternValue(
            identity_key=identity.identity_key,
            current_name=identity.current_name,
            steam_id=identity.steam_id,
            role="opening_killer" if role == "winner" else "opening_victim",
            cross_match_resolved=identity.cross_match_resolved,
        )
        return _included((value,), (row,))
    return _excluded(rows, f"opponent_opening_{role}_not_observed")


def _first_contact(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.FIRST_CONTACT, ())
    usable = _usable(rows, config)
    values: dict[str, PatternValue] = {}
    for row in usable:
        if not isinstance(row.payload, FirstContactPayload):
            continue
        role = row.payload.role
        for candidate in row.payload.candidates:
            zone_id = candidate.actor_zone_id if role == "initiator" else candidate.victim_zone_id
            zone_name = (
                candidate.actor_zone_name if role == "initiator" else candidate.victim_zone_name
            )
            if zone_id is None or zone_name is None:
                continue
            value = CategoricalPatternValue(
                key=f"{role}:zone:{zone_id}",
                label=f"{role} at {zone_name}",
                zone_id=zone_id,
                zone_name=zone_name,
                role=role,
            )
            values[_value_key(value)] = value
    if values:
        return _included(tuple(values.values()), usable)
    return _excluded(rows, "first_contact_zone_unresolved")


def _first_utility(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.FIRST_UTILITY, ())
    usable = _usable(rows, config)
    values: dict[str, PatternValue] = {}
    for row in usable:
        if not isinstance(row.payload, FirstUtilityPayload):
            continue
        for candidate in row.payload.candidates:
            zone_key = candidate.zone_id or "unresolved"
            zone_label = candidate.zone_name or "zone unavailable"
            value = CategoricalPatternValue(
                key=f"utility:{candidate.grenade_type}:zone:{zone_key}",
                label=f"{candidate.grenade_type} · {zone_label}",
                zone_id=candidate.zone_id,
                zone_name=candidate.zone_name,
                grenade_type=candidate.grenade_type,
            )
            values[_value_key(value)] = value
    if values:
        limitations = (
            ("utility_zone_unresolved_is_an_explicit_category",)
            if any(
                isinstance(item, CategoricalPatternValue) and item.zone_id is None
                for item in values.values()
            )
            else ()
        )
        return _included(tuple(values.values()), usable, extra_limitations=limitations)
    return _excluded(rows, "first_utility_unavailable")


def _bomb_route(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.BOMB_ROUTE, ())
    usable = _usable(rows, config)
    for row in usable:
        if isinstance(row.payload, BombRoutePayload):
            ids = tuple(item.zone_id for item in row.payload.stops)
            names = tuple(item.zone_name for item in row.payload.stops)
            return _included(
                (
                    RoutePatternValue(
                        zone_ids=ids,
                        zone_names=names,
                        label=" → ".join(names),
                    ),
                ),
                (row,),
            )
    return _excluded(rows, "bomb_route_unavailable")


def _ct_starting_setup(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.STARTING_ZONE_DISTRIBUTION, ())
    usable = tuple(
        item for item in _usable(rows, config) if item.availability is FeatureAvailability.AVAILABLE
    )
    for row in usable:
        if not isinstance(row.payload, ZoneDistributionPayload):
            continue
        counts: Counter[tuple[str, str]] = Counter()
        for player in row.payload.players:
            if player.zone_id is None or player.zone_name is None:
                return _excluded(rows, "ct_starting_setup_has_unresolved_player_zone")
            counts[(player.zone_id, player.zone_name)] += 1
        positions = tuple(
            ZoneCount(zone_id=key[0], zone_name=key[1], player_count=count)
            for key, count in sorted(counts.items())
        )
        if positions:
            return _included(
                (
                    SetupPatternValue(
                        positions=positions,
                        label=" · ".join(
                            f"{item.zone_name} ×{item.player_count}" for item in positions
                        ),
                    ),
                ),
                (row,),
                extra_limitations=("exact_five_player_setup_requires_complete_zone_coverage",),
            )
    return _excluded(rows, "complete_ct_starting_setup_unavailable")


def _opening_outcome(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]],
    opponent_won: bool | None,
    required_role: str,
    config: PatternConfig,
) -> _Observation:
    rows = features.get(RoundFeatureType.OPENING_DUEL, ())
    usable = tuple(
        item
        for item in _usable(rows, config)
        if isinstance(item.payload, OpeningDuelPayload) and item.payload.role == required_role
    )
    value = BinaryPatternValue(
        key=(
            "converted_opening_kill"
            if required_role == "winner"
            else "recovered_after_opening_death"
        ),
        label=(
            "Won round after winning opening duel"
            if required_role == "winner"
            else "Won round after losing opening duel"
        ),
    )
    if not usable:
        return _excluded(
            rows,
            f"opening_{required_role}_opportunity_unavailable",
            registered=(value,),
        )
    if opponent_won is None:
        return _excluded(usable, "round_outcome_unavailable", registered=(value,))
    return _included(
        (value,) if opponent_won else (),
        usable,
        registered=(value,),
        extra_limitations=("association_is_not_a_causal_claim",),
    )


def _binary_feature(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]],
    feature_type: RoundFeatureType,
    value: BinaryPatternValue,
    config: PatternConfig,
) -> _Observation:
    rows = features.get(feature_type, ())
    usable = _usable(rows, config)
    positives = tuple(
        item
        for item in usable
        if item.availability in {FeatureAvailability.AVAILABLE, FeatureAvailability.PARTIAL}
    )
    negative = tuple(
        item for item in rows if item.availability is FeatureAvailability.NOT_APPLICABLE
    )
    if positives:
        return _included((value,), positives, registered=(value,))
    if negative:
        return _included((), negative, registered=(value,))
    return _excluded(rows, f"{feature_type.value}_availability_unproven", registered=(value,))


def _plant_timing(
    features: dict[RoundFeatureType, tuple[RoundFeature, ...]], config: PatternConfig
) -> _Observation:
    rows = features.get(RoundFeatureType.PLANT_TIMING, ())
    buckets = _timing_buckets(config)
    usable = _usable(rows, config)
    for row in usable:
        if not isinstance(row.payload, PlantTimingPayload):
            continue
        seconds = row.payload.seconds_from_freeze_end
        if seconds is None:
            return _excluded(rows, "plant_seconds_unavailable", registered=buckets)
        selected = next(
            item
            for item in buckets
            if seconds >= item.lower_seconds
            and (item.upper_seconds is None or seconds < item.upper_seconds)
        )
        return _included((selected,), (row,), registered=buckets)
    return _excluded(rows, "plant_timing_unavailable", registered=buckets)


def _timing_buckets(config: PatternConfig) -> tuple[TimingBucketPatternValue, ...]:
    starts = (0.0, *config.plant_timing_bucket_seconds)
    ends = (*config.plant_timing_bucket_seconds, None)
    return tuple(
        TimingBucketPatternValue(
            lower_seconds=lower,
            upper_seconds=upper,
            label=(f"{lower:g}–{upper:g}s" if upper is not None else f"{lower:g}s+"),
        )
        for lower, upper in zip(starts, ends, strict=True)
    )


def _usable(rows: tuple[RoundFeature, ...], config: PatternConfig) -> tuple[RoundFeature, ...]:
    accepted = {FeatureAvailability.AVAILABLE}
    if config.include_partial_features:
        accepted.add(FeatureAvailability.PARTIAL)
    return tuple(item for item in rows if item.availability in accepted)


def _included(
    values: tuple[PatternValue, ...],
    features: tuple[RoundFeature, ...],
    *,
    registered: tuple[PatternValue, ...] = (),
    extra_limitations: tuple[str, ...] = (),
) -> _Observation:
    limitations = tuple(
        dict.fromkeys(
            (
                *(value for item in features for value in item.limitations),
                *extra_limitations,
            )
        )
    )
    return _Observation(
        included=True,
        values=values,
        registered_values=registered,
        features=features,
        partial=any(item.availability is FeatureAvailability.PARTIAL for item in features),
        limitations=limitations,
    )


def _excluded(
    features: tuple[RoundFeature, ...],
    reason: str,
    *,
    registered: tuple[PatternValue, ...] = (),
) -> _Observation:
    return _Observation(
        included=False,
        registered_values=registered,
        features=features,
        reason=reason,
        limitations=tuple(dict.fromkeys(value for item in features for value in item.limitations)),
    )


def _evidence(
    round_input: PatternRoundInput,
    features: tuple[RoundFeature, ...],
    contributed: bool,
) -> PatternRoundEvidence:
    ticks = [item.tick_start for item in features if item.tick_start is not None]
    availability = (
        FeatureAvailability.PARTIAL
        if any(item.availability is FeatureAvailability.PARTIAL for item in features)
        else FeatureAvailability.AVAILABLE
        if any(item.availability is FeatureAvailability.AVAILABLE for item in features)
        else FeatureAvailability.NOT_APPLICABLE
        if features
        else None
    )
    return PatternRoundEvidence(
        match_id=round_input.match_id,
        round_id=round_input.round_id,
        round_number=round_input.round_number,
        tick=min(ticks) if ticks else None,
        contributed_to_numerator=contributed,
        feature_ids=tuple(sorted((item.feature_id for item in features), key=str)),
        event_ids=tuple(
            sorted({value for item in features for value in item.evidence_event_ids}, key=str)
        ),
        snapshot_ids=tuple(
            sorted({value for item in features for value in item.evidence_snapshot_ids}, key=str)
        ),
        economy_snapshot_ids=tuple(
            sorted(
                {value for item in features for value in item.evidence_economy_snapshot_ids},
                key=str,
            )
        ),
        feature_availability=availability,
        limitations=tuple(dict.fromkeys(value for item in features for value in item.limitations)),
    )


def _materialize(
    run_id: UUID,
    profile_id: UUID,
    draft: _Draft,
    config: PatternConfig,
) -> CrossMatchPattern:
    identity = canonical_json(
        {
            "type": draft.pattern_type.value,
            "scope": draft.scope.model_dump(mode="json"),
            "value": draft.value.model_dump(mode="json"),
        }
    )
    pattern_id = uuid5(run_id, identity)
    return CrossMatchPattern(
        pattern_id=pattern_id,
        pattern_run_id=run_id,
        profile_id=profile_id,
        pattern_type=draft.pattern_type,
        scope=draft.scope,
        value=draft.value,
        availability=draft.availability,
        numerator=draft.numerator,
        denominator=draft.denominator,
        frequency=draft.frequency,
        sample_size=draft.denominator,
        minimum_sample_size=config.minimum_sample_size,
        small_sample_warning=draft.denominator < config.minimum_sample_size,
        confidence=draft.confidence,
        numerator_match_count=draft.numerator_match_count,
        denominator_match_count=draft.denominator_match_count,
        evidence_references=draft.evidence,
        included_rounds=draft.included,
        excluded_rounds=draft.excluded,
        limitations=draft.limitations,
        warnings=draft.warnings,
    )


def _capabilities(
    populations: dict[tuple[str, str, str, str, str], _Population],
    patterns: tuple[CrossMatchPattern, ...],
) -> dict[PatternType, PatternCapability]:
    result: dict[PatternType, PatternCapability] = {}
    for pattern_type in PatternType:
        related = tuple(item for item in populations.values() if item.pattern_type is pattern_type)
        rows = tuple(item for item in patterns if item.pattern_type is pattern_type)
        unsupported = _UNSUPPORTED.get(pattern_type)
        limitations = {unsupported} if unsupported is not None else set()
        limitations.discard("")
        limitations.update(value for item in related for value in item.limitations)
        eligible = sum(len(item.opportunities) for item in related)
        excluded = sum(len(item.exclusions) for item in related)
        if pattern_type in _UNSUPPORTED or eligible == 0:
            availability = PatternAvailability.UNAVAILABLE
        elif any(item.availability is PatternAvailability.PARTIAL for item in rows):
            availability = PatternAvailability.PARTIAL
        else:
            availability = PatternAvailability.AVAILABLE
        result[pattern_type] = PatternCapability(
            pattern_type=pattern_type,
            availability=availability,
            eligible_rounds=eligible,
            excluded_rounds=excluded,
            scope_count=len(related),
            pattern_count=len(rows),
            limitations=tuple(sorted(limitations)),
        )
    return result


def _population_key(
    pattern_type: PatternType, scope: PatternScope
) -> tuple[str, str, str, str, str]:
    return (
        pattern_type.value,
        scope.map_name,
        scope.side.value,
        scope.buy_type.value if scope.buy_type is not None else "<unavailable>",
        scope.feature_rule_version,
    )


def _population_sort_key(population: _Population) -> tuple[str, str, str, str, str]:
    return _population_key(population.pattern_type, population.scope)


def _value_key(value: PatternValue) -> str:
    if isinstance(value, CategoricalPatternValue):
        identity: Any = (value.kind, value.key)
    elif isinstance(value, PlayerPatternValue):
        identity = (value.kind, value.identity_key, value.role)
    elif isinstance(value, RoutePatternValue):
        identity = (value.kind, value.zone_ids)
    elif isinstance(value, SetupPatternValue):
        identity = (
            value.kind,
            tuple(
                (item.zone_id, item.player_count)
                for item in sorted(value.positions, key=lambda item: item.zone_id)
            ),
        )
    elif isinstance(value, TimingBucketPatternValue):
        identity = (value.kind, value.lower_seconds, value.upper_seconds)
    else:
        identity = (value.kind, value.key)
    return canonical_json(identity)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _input_fingerprint_payload(value: PatternMatchInput) -> dict[str, Any]:
    return {
        "match_id": str(value.match_id),
        "team_id": str(value.team_id),
        "map_name": value.map_name,
        "status": value.status.value,
        "exclusion_reason": value.exclusion_reason,
        "dataset_fingerprint": value.dataset_fingerprint,
        "feature_run_id": str(value.feature_run_id) if value.feature_run_id else None,
        "feature_fingerprint": value.feature_fingerprint,
        "feature_schema_version": value.feature_schema_version,
        "feature_rule_version": value.feature_rule_version,
    }


def _draft_payload(value: _Draft) -> dict[str, Any]:
    return {
        "pattern_type": value.pattern_type.value,
        "scope": value.scope.model_dump(mode="json"),
        "value": value.value.model_dump(mode="json"),
        "availability": value.availability.value,
        "numerator": value.numerator,
        "denominator": value.denominator,
        "frequency": value.frequency,
        "confidence": value.confidence.model_dump(mode="json"),
        "included": [item.model_dump(mode="json") for item in value.included],
        "excluded": [item.model_dump(mode="json") for item in value.excluded],
        "limitations": value.limitations,
        "warnings": value.warnings,
    }


__all__ = ["CrossMatchPatternEngine", "wilson_confidence"]
