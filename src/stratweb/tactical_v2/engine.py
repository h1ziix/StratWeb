"""Pure deterministic Tactical Intelligence V2 computations."""

from __future__ import annotations

import hashlib
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.tactical_v2.models import (
    TACTICAL_V2_CLUTCH_RULE,
    TACTICAL_V2_HEATMAP_RULE,
    TACTICAL_V2_ROTATION_RULE,
    TACTICAL_V2_ROUTE_RULE,
    TACTICAL_V2_RULE_VERSION,
    TACTICAL_V2_SCHEMA_VERSION,
    TACTICAL_V2_UTILITY_RULE,
    TacticalAvailability,
    TacticalCapability,
    TacticalDamageSample,
    TacticalEvidenceReference,
    TacticalInsight,
    TacticalInsightType,
    TacticalMatchInput,
    TacticalPlayerSample,
    TacticalRoundInput,
    TacticalV2Config,
    TacticalV2Input,
    TacticalV2Run,
    TacticalV2Summary,
)


@dataclass(frozen=True, slots=True)
class _Draft:
    insight_type: TacticalInsightType
    map_name: str
    side: Side
    key: str
    label: str
    numerator: int
    denominator: int
    metrics: dict[str, Any]
    evidence: tuple[TacticalEvidenceReference, ...]
    limitations: tuple[str, ...]
    availability: TacticalAvailability = TacticalAvailability.AVAILABLE


@dataclass(frozen=True, slots=True)
class _Occurrence:
    match_id: UUID
    map_name: str
    side: Side
    key: str
    label: str
    positive: bool
    evidence: TacticalEvidenceReference
    metrics: dict[str, float]


class TacticalV2Engine:
    """Create evidence-backed observations; never recommendations or causal claims."""

    def compute(
        self, data: TacticalV2Input, config: TacticalV2Config | None = None
    ) -> TacticalV2Run:
        selected = config or TacticalV2Config()
        matches = tuple(sorted(data.matches, key=lambda item: str(item.source.match_id)))
        if len({item.source.match_id for item in matches}) != len(matches):
            raise ValueError("tactical input contains duplicate matches")
        config_hash = hashlib.sha256(
            canonical_json(selected.model_dump(mode="json")).encode()
        ).hexdigest()
        families = (
            self._paths(matches, selected),
            self._executes(matches, selected),
            self._utility(matches, selected),
            self._spacing(matches, selected),
            self._entries(matches, selected),
            self._rotations(matches, selected),
            self._clutches(matches, selected),
            self._saves(matches, selected),
            self._heatmaps(matches, selected),
        )
        drafts = tuple(
            sorted(
                (draft for family, _capabilities in families for draft in family),
                key=lambda item: (
                    item.insight_type.value,
                    item.map_name,
                    item.side.value,
                    item.key,
                ),
            )
        )
        capabilities: dict[TacticalInsightType, TacticalCapability] = {}
        for _family, family_capabilities in families:
            capabilities.update(family_capabilities)
        warnings = set(data.warnings)
        warnings.update(limitation for match in matches for limitation in match.limitations)
        if len(matches) < selected.target_corpus_matches:
            warnings.add(f"small_corpus:{len(matches)}/{selected.target_corpus_matches}_matches")
        warnings.update(
            {
                "tactical_v2_observations_do_not_prove_intent_or_causality",
                "tick_windows_are_versioned_policies_not_inferred_seconds",
            }
        )
        payload = {
            "schema": TACTICAL_V2_SCHEMA_VERSION,
            "rules": TACTICAL_V2_RULE_VERSION,
            "configuration_hash": config_hash,
            "profile_id": str(data.profile_id),
            "sources": _json(tuple(item.source for item in matches)),
            "excluded_match_ids": tuple(str(item) for item in data.excluded_match_ids),
            "drafts": _json(drafts),
            "capabilities": _json(capabilities),
            "warnings": tuple(sorted(warnings)),
        }
        fingerprint = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        run_id = uuid5(NAMESPACE_URL, f"stratweb:tactical-v2:{fingerprint}")
        insights = tuple(
            TacticalInsight(
                insight_id=uuid5(
                    run_id,
                    f"insight:{draft.insight_type.value}:{draft.map_name}:"
                    f"{draft.side.value}:{draft.key}",
                ),
                tactical_run_id=run_id,
                profile_id=data.profile_id,
                insight_type=draft.insight_type,
                map_name=draft.map_name,
                side=draft.side,
                key=draft.key,
                label=draft.label,
                availability=draft.availability,
                numerator=draft.numerator,
                denominator=draft.denominator,
                frequency=draft.numerator / draft.denominator,
                sample_size=draft.denominator,
                match_count=len({item.match_id for item in draft.evidence}),
                small_sample_warning=(
                    len({item.match_id for item in draft.evidence}) < selected.target_corpus_matches
                ),
                metrics=draft.metrics,
                evidence_references=draft.evidence,
                limitations=draft.limitations,
            )
            for draft in drafts
        )
        counts = Counter(item.insight_type for item in insights)
        eligible_rounds = sum(
            not round_item.is_warmup and round_item.is_complete
            for item in matches
            for round_item in item.rounds
        )
        summary = TacticalV2Summary(
            selected_matches=len(matches) + len(data.excluded_match_ids),
            included_matches=len(matches),
            excluded_matches=len(data.excluded_match_ids),
            eligible_rounds=eligible_rounds,
            insights=len(insights),
            evidence_references=sum(len(item.evidence_references) for item in insights),
            insight_type_counts={kind: counts.get(kind, 0) for kind in TacticalInsightType},
            small_sample_insights=sum(item.small_sample_warning for item in insights),
        )
        return TacticalV2Run(
            tactical_run_id=run_id,
            tactical_fingerprint=fingerprint,
            configuration_hash=config_hash,
            profile_id=data.profile_id,
            config=selected,
            source_pins=tuple(item.source for item in matches),
            capabilities=capabilities,
            summary=summary,
            insights=insights,
            warnings=tuple(sorted(warnings)),
        )

    def _paths(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                eligible += 1
                checkpoints = []
                snapshot_ids: list[UUID] = []
                observed_ticks: list[int] = []
                unknown_player_zones = 0
                if round_item.live_start_tick is None:
                    continue
                complete = True
                for offset in config.checkpoint_offsets_ticks:
                    selected = _checkpoint_samples(round_item, offset, config)
                    known = tuple(item for item in selected if item.zone_id is not None)
                    if len(known) < config.minimum_players_for_formation:
                        complete = False
                        break
                    unknown_player_zones += len(selected) - len(known)
                    counts = Counter(item.zone_id for item in known if item.zone_id is not None)
                    checkpoint = "+".join(
                        f"{zone}*{count}" if count > 1 else zone
                        for zone, count in sorted(counts.items())
                    )
                    checkpoints.append(f"{offset}:{checkpoint}")
                    snapshot_ids.extend(item.snapshot_id for item in selected)
                    observed_ticks.extend(item.tick for item in selected)
                if not complete:
                    continue
                covered += 1
                key = "|".join(checkpoints)
                occurrences.append(
                    _Occurrence(
                        match_id=match.source.match_id,
                        map_name=match.source.map_name,
                        side=round_item.side,
                        key=key,
                        label="Повторяющаяся формация по контрольным точкам",
                        positive=True,
                        evidence=TacticalEvidenceReference(
                            match_id=match.source.match_id,
                            round_number=round_item.round_number,
                            tick_start=min(observed_ticks),
                            tick_end=max(observed_ticks),
                            snapshot_ids=tuple(sorted(set(snapshot_ids), key=str)),
                        ),
                        metrics={"unknown_player_zones": float(unknown_player_zones)},
                    )
                )
        drafts = _categorical_drafts(
            TacticalInsightType.PATH_CLUSTER,
            occurrences,
            (
                f"route_rule:{TACTICAL_V2_ROUTE_RULE}",
                "identical_checkpoint_formations_are_clustered_without_geometry_guessing",
                "checkpoints_with_fewer_than_two_known_player_zones_are_excluded",
            ),
        )
        return drafts, {
            TacticalInsightType.PATH_CLUSTER: _capability(
                eligible, covered, len(drafts), "complete_zone_formation_unavailable"
            )
        }

    def _executes(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                if round_item.side is not Side.T or round_item.plant is None:
                    continue
                eligible += 1
                plant = round_item.plant
                if plant.site not in {"A", "B"}:
                    continue
                effects = tuple(
                    item
                    for item in round_item.utility
                    if item.owner_team_id == match.source.team_id
                    and plant.tick - config.execute_window_ticks <= item.start_tick <= plant.tick
                )
                bundle = Counter(item.effect_type for item in effects)
                utility_key = (
                    "+".join(
                        f"{kind}*{count}" if count > 1 else kind
                        for kind, count in sorted(bundle.items())
                    )
                    or "no_observed_effect"
                )
                key = f"site:{plant.site}|{utility_key}"
                covered += 1
                occurrences.append(
                    _Occurrence(
                        match_id=match.source.match_id,
                        map_name=match.source.map_name,
                        side=round_item.side,
                        key=key,
                        label=f"Зафиксированный plant-пакет на {plant.site}",
                        positive=True,
                        evidence=TacticalEvidenceReference(
                            match_id=match.source.match_id,
                            round_number=round_item.round_number,
                            tick_start=max(0, plant.tick - config.execute_window_ticks),
                            tick_end=plant.tick,
                            event_ids=(plant.event_id,),
                            projectile_ids=tuple(
                                sorted(
                                    {item.projectile_id for item in effects if item.projectile_id},
                                    key=str,
                                )
                            ),
                            effect_ids=tuple(sorted({item.effect_id for item in effects}, key=str)),
                        ),
                        metrics={"observed_utility_effects": float(len(effects))},
                    )
                )
        drafts = _categorical_drafts(
            TacticalInsightType.EXECUTE_PACKAGE,
            occurrences,
            (
                "execute_population_is_t_side_rounds_with_proven_plant_site",
                "unplanted_executes_and_tactical_intent_are_not_inferred",
                "utility_bundle_uses_effect_start_inside_versioned_preplant_tick_window",
            ),
        )
        return drafts, {
            TacticalInsightType.EXECUTE_PACKAGE: _capability(
                eligible, covered, len(drafts), "plant_site_or_utility_provenance_unavailable"
            )
        }

    def _utility(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                effects = tuple(
                    effect
                    for effect in round_item.utility
                    if effect.owner_team_id == match.source.team_id
                    and effect.effect_type in {"he", "fire"}
                )
                eligible += len(effects)
                associated_by_effect: dict[UUID, list[TacticalDamageSample]] = defaultdict(list)
                for damage_event in round_item.damages:
                    candidates = tuple(
                        effect
                        for effect in effects
                        if effect.owner_player_id is not None
                        and damage_event.attacker_player_id == effect.owner_player_id
                        and damage_event.victim_team_id not in {None, match.source.team_id}
                        and effect.start_tick
                        <= damage_event.tick
                        <= (effect.end_tick if effect.end_tick is not None else effect.start_tick)
                        + config.utility_outcome_grace_ticks
                        and _weapon_matches_effect(damage_event.weapon, effect.effect_type)
                    )
                    if len(candidates) == 1:
                        associated_by_effect[candidates[0].effect_id].append(damage_event)
                for effect in effects:
                    if effect.owner_player_id is None:
                        continue
                    terminal = (
                        effect.end_tick if effect.end_tick is not None else effect.start_tick
                    ) + config.utility_outcome_grace_ticks
                    associated = tuple(associated_by_effect[effect.effect_id])
                    damage_total = sum(item.damage_health or 0 for item in associated)
                    covered += 1
                    occurrences.append(
                        _Occurrence(
                            match_id=match.source.match_id,
                            map_name=match.source.map_name,
                            side=round_item.side,
                            key=effect.effect_type,
                            label=f"{effect.effect_type.upper()}: связанный урон",
                            positive=damage_total > 0,
                            evidence=TacticalEvidenceReference(
                                match_id=match.source.match_id,
                                round_number=round_item.round_number,
                                tick_start=effect.start_tick,
                                tick_end=terminal,
                                event_ids=tuple(item.event_id for item in associated),
                                projectile_ids=(
                                    (effect.projectile_id,)
                                    if effect.projectile_id is not None
                                    else ()
                                ),
                                effect_ids=(effect.effect_id,),
                            ),
                            metrics={"damage_health": float(damage_total)},
                        )
                    )
        drafts = _binary_drafts(
            TacticalInsightType.UTILITY_OUTCOME,
            occurrences,
            (
                f"utility_rule:{TACTICAL_V2_UTILITY_RULE}",
                "damage_is_a_same_owner_weapon_time_association_not_proven_causality",
                "damage_matching_multiple_effect_windows_is_excluded_as_ambiguous",
                "flash_blindness_and_smoke_line_of_sight_effectiveness_are_unavailable",
            ),
        )
        return drafts, {
            TacticalInsightType.UTILITY_OUTCOME: _capability(
                eligible,
                covered,
                len(drafts),
                "utility_outcome_requires_unique_association_and_never_proves_causality",
                force_partial=covered > 0,
            )
        }

    def _spacing(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                if round_item.live_start_tick is None:
                    continue
                for offset in config.checkpoint_offsets_ticks:
                    eligible += 1
                    samples = _checkpoint_samples(round_item, offset, config)
                    if len(samples) < config.minimum_players_for_formation:
                        continue
                    distances = [
                        math.dist((left.x, left.y, left.z), (right.x, right.y, right.z))
                        for index, left in enumerate(samples)
                        for right in samples[index + 1 :]
                    ]
                    nearest = [
                        min(
                            math.dist((item.x, item.y, item.z), (other.x, other.y, other.z))
                            for other in samples
                            if other.player_id != item.player_id
                        )
                        for item in samples
                    ]
                    isolated = any(
                        value > config.isolated_player_distance_units for value in nearest
                    )
                    covered += 1
                    occurrences.append(
                        _Occurrence(
                            match_id=match.source.match_id,
                            map_name=match.source.map_name,
                            side=round_item.side,
                            key=f"checkpoint:{offset}",
                            label=f"Разрыв дистанции на +{offset} ticks",
                            positive=isolated,
                            evidence=TacticalEvidenceReference(
                                match_id=match.source.match_id,
                                round_number=round_item.round_number,
                                tick_start=min(item.tick for item in samples),
                                tick_end=max(item.tick for item in samples),
                                snapshot_ids=tuple(item.snapshot_id for item in samples),
                            ),
                            metrics={
                                "median_pairwise_distance": statistics.median(distances),
                                "maximum_nearest_teammate_distance": max(nearest),
                            },
                        )
                    )
        drafts = _binary_drafts(
            TacticalInsightType.SPACING_PROFILE,
            occurrences,
            (
                "distance_is_source2_world_units_not_a_tactical_quality_score",
                "checkpoint_sampling_does_not_prove_spacing_between_checkpoints",
            ),
        )
        return drafts, {
            TacticalInsightType.SPACING_PROFILE: _capability(
                eligible, covered, len(drafts), "insufficient_same_tick_player_positions"
            )
        }

    def _entries(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        del config
        entry_occurrences: list[_Occurrence] = []
        trade_occurrences: list[_Occurrence] = []
        eligible = covered = trade_eligible = trade_covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                valid = tuple(item for item in round_item.kills if _valid_enemy_kill(item))
                if not valid:
                    continue
                eligible += 1
                first_tick = min(item.tick for item in valid)
                candidates = tuple(item for item in valid if item.tick == first_tick)
                if len(candidates) != 1:
                    continue
                opening = candidates[0]
                covered += 1
                selected_won = opening.attacker_team_id == match.source.team_id
                evidence = TacticalEvidenceReference(
                    match_id=match.source.match_id,
                    round_number=round_item.round_number,
                    tick_start=opening.tick,
                    tick_end=opening.tick,
                    event_ids=(opening.event_id,),
                )
                entry_occurrences.append(
                    _Occurrence(
                        match_id=match.source.match_id,
                        map_name=match.source.map_name,
                        side=round_item.side,
                        key="opening_duel_success",
                        label="Победа в первом доказанном дуэле",
                        positive=selected_won,
                        evidence=evidence,
                        metrics={},
                    )
                )
                if opening.victim_team_id != match.source.team_id:
                    continue
                trade_eligible += 1
                trade = next(
                    (
                        item
                        for item in round_item.trades
                        if item.original_kill_event_id == opening.event_id
                        and item.team_id == match.source.team_id
                    ),
                    None,
                )
                trade_covered += 1
                trade_occurrences.append(
                    _Occurrence(
                        match_id=match.source.match_id,
                        map_name=match.source.map_name,
                        side=round_item.side,
                        key="opening_death_traded",
                        label="Размен первой смерти",
                        positive=trade is not None,
                        evidence=TacticalEvidenceReference(
                            match_id=match.source.match_id,
                            round_number=round_item.round_number,
                            tick_start=opening.tick,
                            tick_end=(opening.tick + trade.tick_delta if trade else opening.tick),
                            event_ids=(
                                (opening.event_id, trade.traded_kill_event_id)
                                if trade
                                else (opening.event_id,)
                            ),
                        ),
                        metrics={"trade_tick_delta": float(trade.tick_delta) if trade else 0.0},
                    )
                )
        entry_drafts = _binary_drafts(
            TacticalInsightType.ENTRY_STRUCTURE,
            entry_occurrences,
            (
                "same_tick_multiple_opening_kills_are_excluded_as_ambiguous",
                "opening_result_does_not_identify_called_entry_role",
            ),
        )
        trade_drafts = _binary_drafts(
            TacticalInsightType.TRADE_STRUCTURE,
            trade_occurrences,
            (
                "trade_uses_versioned_stage_5_trade_window",
                "absence_of_a_trade_event_is_not_proof_that_no_trade_was_attempted",
            ),
        )
        return (*entry_drafts, *trade_drafts), {
            TacticalInsightType.ENTRY_STRUCTURE: _capability(
                eligible, covered, len(entry_drafts), "opening_order_ambiguous_or_unavailable"
            ),
            TacticalInsightType.TRADE_STRUCTURE: _capability(
                trade_eligible,
                trade_covered,
                len(trade_drafts),
                "opening_death_or_trade_data_unavailable",
            ),
        }

    def _rotations(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                if round_item.side is not Side.CT:
                    continue
                contacts = [
                    (item.tick, item.event_id)
                    for item in round_item.damages
                    if (item.damage_health or 0) > 0
                    and item.attacker_team_id is not None
                    and item.victim_team_id is not None
                    and item.attacker_team_id != item.victim_team_id
                ]
                contacts.extend(
                    (item.tick, item.event_id)
                    for item in round_item.kills
                    if _valid_enemy_kill(item)
                )
                if not contacts:
                    continue
                eligible += 1
                contact_tick = min(item[0] for item in contacts)
                contact_ids = tuple(
                    sorted({event for tick, event in contacts if tick == contact_tick}, key=str)
                )
                round_edges = 0
                by_player: dict[UUID, list[TacticalPlayerSample]] = defaultdict(list)
                for sample in round_item.samples:
                    if (
                        contact_tick <= sample.tick <= contact_tick + config.rotation_window_ticks
                        and sample.zone_id is not None
                        and sample.alive is True
                    ):
                        by_player[sample.player_id].append(sample)
                for _player_id, samples in sorted(by_player.items(), key=lambda item: str(item[0])):
                    ordered = sorted(samples, key=lambda item: (item.tick, str(item.snapshot_id)))
                    previous = ordered[0]
                    for sample in ordered[1:]:
                        if sample.zone_id == previous.zone_id:
                            previous = sample
                            continue
                        round_edges += 1
                        key = f"{previous.zone_id}->{sample.zone_id}"
                        occurrences.append(
                            _Occurrence(
                                match_id=match.source.match_id,
                                map_name=match.source.map_name,
                                side=round_item.side,
                                key=key,
                                label=(
                                    "Переход после контакта: "
                                    f"{previous.zone_name or previous.zone_id} → "
                                    f"{sample.zone_name or sample.zone_id}"
                                ),
                                positive=True,
                                evidence=TacticalEvidenceReference(
                                    match_id=match.source.match_id,
                                    round_number=round_item.round_number,
                                    tick_start=previous.tick,
                                    tick_end=sample.tick,
                                    event_ids=contact_ids,
                                    snapshot_ids=(previous.snapshot_id, sample.snapshot_id),
                                ),
                                metrics={"player_transition": 1.0},
                            )
                        )
                        previous = sample
                if round_edges:
                    covered += 1
        drafts = _categorical_drafts(
            TacticalInsightType.ROTATION_TRANSITION,
            occurrences,
            (
                f"rotation_rule:{TACTICAL_V2_ROTATION_RULE}",
                "post_contact_movement_is_observed_transition_not_proven_rotation_intent",
                "transition_frequency_denominator_is_all_observed_zone_edges",
            ),
        )
        return drafts, {
            TacticalInsightType.ROTATION_TRANSITION: _capability(
                eligible, covered, len(drafts), "post_contact_zone_transitions_unavailable"
            )
        }

    def _clutches(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        del config
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                if (
                    len(round_item.selected_player_ids) < 2
                    or len(round_item.opponent_player_ids) < 2
                ):
                    continue
                selected_alive = set(round_item.selected_player_ids)
                opponent_alive = set(round_item.opponent_player_ids)
                trigger: tuple[int, tuple[UUID, ...]] | None = None
                grouped: dict[int, list[Any]] = defaultdict(list)
                for kill in round_item.kills:
                    if _valid_enemy_kill(kill):
                        grouped[kill.tick].append(kill)
                for tick in sorted(grouped):
                    event_ids = []
                    for kill in grouped[tick]:
                        event_ids.append(kill.event_id)
                        if kill.victim_player_id in selected_alive:
                            selected_alive.remove(kill.victim_player_id)
                        if kill.victim_player_id in opponent_alive:
                            opponent_alive.remove(kill.victim_player_id)
                    if len(selected_alive) == 1 and len(opponent_alive) >= 2:
                        trigger = (tick, tuple(sorted(event_ids, key=str)))
                        break
                if trigger is None or round_item.selected_team_won is None:
                    continue
                eligible += 1
                covered += 1
                occurrences.append(
                    _Occurrence(
                        match_id=match.source.match_id,
                        map_name=match.source.map_name,
                        side=round_item.side,
                        key="one_vs_many_conversion",
                        label="Реализация доказанной ситуации 1 против 2+",
                        positive=round_item.selected_team_won,
                        evidence=TacticalEvidenceReference(
                            match_id=match.source.match_id,
                            round_number=round_item.round_number,
                            tick_start=trigger[0],
                            tick_end=round_item.effective_end_tick or trigger[0],
                            event_ids=trigger[1],
                        ),
                        metrics={"opponents_alive_at_trigger": float(len(opponent_alive))},
                    )
                )
        drafts = _binary_drafts(
            TacticalInsightType.CLUTCH_BEHAVIOR,
            occurrences,
            (
                f"clutch_rule:{TACTICAL_V2_CLUTCH_RULE}",
                "alive_state_is_evaluated_after_the_complete_same_tick_kill_group",
                "clutch_attempt_intent_is_not_inferred_from_the_result",
            ),
        )
        return drafts, {
            TacticalInsightType.CLUTCH_BEHAVIOR: _capability(
                eligible, covered, len(drafts), "complete_roster_or_round_outcome_unavailable"
            )
        }

    def _saves(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        del config
        occurrences: list[_Occurrence] = []
        eligible = covered = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                if round_item.save_availability is TacticalAvailability.NOT_APPLICABLE:
                    continue
                eligible += 1
                if round_item.save_signal is None:
                    continue
                signal = round_item.save_signal
                covered += 1
                occurrences.append(
                    _Occurrence(
                        match_id=match.source.match_id,
                        map_name=match.source.map_name,
                        side=round_item.side,
                        key="save_observed",
                        label="Сохранение оружия в доказанном save-контексте",
                        positive=signal.saved,
                        evidence=TacticalEvidenceReference(
                            match_id=match.source.match_id,
                            round_number=round_item.round_number,
                            tick_start=signal.tick_start,
                            tick_end=signal.tick_end,
                            snapshot_ids=signal.snapshot_ids,
                            feature_ids=(signal.feature_id,),
                        ),
                        metrics={},
                    )
                )
        drafts = _binary_drafts(
            TacticalInsightType.SAVE_BEHAVIOR,
            occurrences,
            (
                "save_population_is_only_rounds_with_available_stage_8_4_save_exit_fact",
                "save_call_intent_and_economy_optimality_are_not_inferred",
            ),
        )
        return drafts, {
            TacticalInsightType.SAVE_BEHAVIOR: _capability(
                eligible, covered, len(drafts), "save_exit_fact_unavailable"
            )
        }

    def _heatmaps(
        self, matches: tuple[TacticalMatchInput, ...], config: TacticalV2Config
    ) -> tuple[tuple[_Draft, ...], dict[TacticalInsightType, TacticalCapability]]:
        occurrences: list[_Occurrence] = []
        eligible = covered = unknown_alive = 0
        for match in matches:
            for round_item in _eligible_rounds(match):
                alive_samples = tuple(item for item in round_item.samples if item.alive is True)
                eligible += len(alive_samples)
                covered += len(alive_samples)
                unknown_alive += sum(item.alive is None for item in round_item.samples)
                grouped: dict[tuple[int, int], list[TacticalPlayerSample]] = defaultdict(list)
                for sample in alive_samples:
                    cell = (
                        math.floor(sample.x / config.heatmap_cell_size_units),
                        math.floor(sample.y / config.heatmap_cell_size_units),
                    )
                    grouped[cell].append(sample)
                for (cell_x, cell_y), samples in grouped.items():
                    ordered = sorted(samples, key=lambda item: (item.tick, str(item.snapshot_id)))
                    occurrences.extend(
                        _Occurrence(
                            match_id=match.source.match_id,
                            map_name=match.source.map_name,
                            side=round_item.side,
                            key=f"cell:{cell_x}:{cell_y}",
                            label=f"Ячейка ({cell_x}, {cell_y})",
                            positive=True,
                            evidence=TacticalEvidenceReference(
                                match_id=match.source.match_id,
                                round_number=round_item.round_number,
                                tick_start=sample.tick,
                                tick_end=sample.tick,
                                snapshot_ids=(sample.snapshot_id,),
                            ),
                            metrics={
                                "cell_x": float(cell_x),
                                "cell_y": float(cell_y),
                                "sample_count": 1.0,
                            },
                        )
                        for sample in ordered
                    )
        drafts = _categorical_drafts(
            TacticalInsightType.HEATMAP_CELL,
            occurrences,
            (
                f"heatmap_rule:{TACTICAL_V2_HEATMAP_RULE}",
                "frequency_is_alive_spatial_sample_share_not_time_seconds_or_round_probability",
                "sampling_density_can_differ_between_versioned_spatial_runs",
            ),
            merge_duplicate_evidence=True,
        )
        return drafts, {
            TacticalInsightType.HEATMAP_CELL: _capability(
                eligible,
                covered,
                len(drafts),
                "authoritative_alive_position_unavailable",
                force_partial=unknown_alive > 0,
            )
        }


def _eligible_rounds(match: TacticalMatchInput) -> Iterable[TacticalRoundInput]:
    return (
        item
        for item in match.rounds
        if not item.is_warmup and item.is_complete and item.side in {Side.T, Side.CT}
    )


def _checkpoint_samples(
    round_item: TacticalRoundInput, offset: int, config: TacticalV2Config
) -> tuple[TacticalPlayerSample, ...]:
    assert round_item.live_start_tick is not None
    target = round_item.live_start_tick + offset
    by_player: dict[UUID, TacticalPlayerSample] = {}
    for sample in round_item.samples:
        if sample.tick > target or target - sample.tick > config.maximum_snapshot_age_ticks:
            continue
        if sample.alive is not True:
            continue
        previous = by_player.get(sample.player_id)
        if previous is None or (sample.tick, str(sample.snapshot_id)) > (
            previous.tick,
            str(previous.snapshot_id),
        ):
            by_player[sample.player_id] = sample
    return tuple(by_player[key] for key in sorted(by_player, key=str))


def _valid_enemy_kill(item: Any) -> bool:
    return bool(
        item.attacker_player_id is not None
        and item.victim_player_id is not None
        and item.attacker_team_id is not None
        and item.victim_team_id is not None
        and item.attacker_team_id != item.victim_team_id
        and item.is_teamkill is not True
        and item.is_suicide is not True
    )


def _weapon_matches_effect(weapon: str | None, effect_type: str) -> bool:
    normalized = (weapon or "").lower()
    if effect_type == "he":
        return "hegrenade" in normalized or normalized in {"he", "grenade"}
    if effect_type == "fire":
        return any(value in normalized for value in ("inferno", "molotov", "incgrenade"))
    return False


def _categorical_drafts(
    insight_type: TacticalInsightType,
    occurrences: list[_Occurrence],
    limitations: tuple[str, ...],
    *,
    merge_duplicate_evidence: bool = False,
) -> tuple[_Draft, ...]:
    scope_totals = Counter((item.map_name, item.side) for item in occurrences)
    grouped: dict[tuple[str, Side, str, str], list[_Occurrence]] = defaultdict(list)
    for item in occurrences:
        grouped[(item.map_name, item.side, item.key, item.label)].append(item)
    result = []
    for (map_name, side, key, label), values in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1].value, item[0][2])
    ):
        evidence = tuple(item.evidence for item in values)
        if merge_duplicate_evidence:
            evidence = _merge_evidence(evidence)
        metrics = _aggregate_metrics(values)
        availability = (
            TacticalAvailability.PARTIAL
            if insight_type is TacticalInsightType.PATH_CLUSTER
            and float(metrics.get("unknown_player_zones_total", 0.0)) > 0
            else TacticalAvailability.AVAILABLE
        )
        result.append(
            _Draft(
                insight_type=insight_type,
                map_name=map_name,
                side=side,
                key=key,
                label=label,
                numerator=len(values),
                denominator=scope_totals[(map_name, side)],
                metrics=metrics,
                evidence=evidence,
                limitations=limitations,
                availability=availability,
            )
        )
    return tuple(result)


def _binary_drafts(
    insight_type: TacticalInsightType,
    occurrences: list[_Occurrence],
    limitations: tuple[str, ...],
) -> tuple[_Draft, ...]:
    grouped: dict[tuple[str, Side, str, str], list[_Occurrence]] = defaultdict(list)
    for item in occurrences:
        grouped[(item.map_name, item.side, item.key, item.label)].append(item)
    return tuple(
        _Draft(
            insight_type=insight_type,
            map_name=map_name,
            side=side,
            key=key,
            label=label,
            numerator=sum(item.positive for item in values),
            denominator=len(values),
            metrics=_aggregate_metrics(values),
            evidence=_merge_evidence(tuple(item.evidence for item in values)),
            limitations=limitations,
            availability=(
                TacticalAvailability.PARTIAL
                if insight_type is TacticalInsightType.UTILITY_OUTCOME
                else TacticalAvailability.AVAILABLE
            ),
        )
        for (map_name, side, key, label), values in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1].value, item[0][2])
        )
    )


def _aggregate_metrics(values: list[_Occurrence]) -> dict[str, Any]:
    keys = sorted({key for item in values for key in item.metrics})
    result: dict[str, Any] = {}
    for key in keys:
        observed = [item.metrics[key] for item in values if key in item.metrics]
        if not observed:
            continue
        result[f"{key}_total"] = sum(observed)
        result[f"{key}_mean"] = sum(observed) / len(observed)
        result[f"{key}_median"] = statistics.median(observed)
    return result


def _merge_evidence(
    values: tuple[TacticalEvidenceReference, ...],
) -> tuple[TacticalEvidenceReference, ...]:
    grouped: dict[tuple[UUID, int], list[TacticalEvidenceReference]] = defaultdict(list)
    for item in values:
        grouped[(item.match_id, item.round_number)].append(item)
    result = []
    for (match_id, round_number), items in sorted(
        grouped.items(), key=lambda item: (str(item[0][0]), item[0][1])
    ):
        starts = [item.tick_start for item in items if item.tick_start is not None]
        ends = [item.tick_end for item in items if item.tick_end is not None]
        result.append(
            TacticalEvidenceReference(
                match_id=match_id,
                round_number=round_number,
                tick_start=min(starts) if starts else None,
                tick_end=max(ends) if ends else None,
                event_ids=_ids(item.event_ids for item in items),
                snapshot_ids=_ids(item.snapshot_ids for item in items),
                feature_ids=_ids(item.feature_ids for item in items),
                projectile_ids=_ids(item.projectile_ids for item in items),
                effect_ids=_ids(item.effect_ids for item in items),
            )
        )
    return tuple(result)


def _ids(values: Iterable[tuple[UUID, ...]]) -> tuple[UUID, ...]:
    return tuple(sorted({value for group in values for value in group}, key=str))


def _capability(
    eligible: int,
    covered: int,
    insight_count: int,
    reason: str,
    *,
    force_partial: bool = False,
) -> TacticalCapability:
    if eligible == 0:
        status = TacticalAvailability.UNAVAILABLE
    elif covered == 0:
        status = TacticalAvailability.UNAVAILABLE
    elif covered < eligible or force_partial:
        status = TacticalAvailability.PARTIAL
    else:
        status = TacticalAvailability.AVAILABLE
    return TacticalCapability(
        status=status,
        eligible_units=eligible,
        covered_units=covered,
        insight_count=insight_count,
        unavailable_reasons=(
            (reason,) if covered < eligible or eligible == 0 or force_partial else ()
        ),
    )


def _json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json(getattr(value, key)) for key in value.__dataclass_fields__}
    return value


__all__ = ["TacticalV2Engine"]
