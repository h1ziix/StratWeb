"""Pure deterministic Spatial Engine over typed parser and Temporal inputs."""

from __future__ import annotations

import hashlib
from math import isfinite
from uuid import UUID, uuid5

from pydantic import JsonValue

from stratweb.application.canonical_models import CanonicalPlayer, ValidationSeverity
from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.maps.models import MapSelectionEvidence
from stratweb.maps.registry import DEFAULT_MAP_REGISTRY, MapRegistry
from stratweb.temporal.models import (
    ParticipantRoundState,
    RoundSnapshot,
    RoundTimeline,
    SnapshotStateStatus,
)
from stratweb.temporal.snapshots import SnapshotBuilder

from .models import (
    SPATIAL_RULE_VERSION,
    SPATIAL_SCHEMA_VERSION,
    BombPositionSnapshot,
    SnapshotAvailability,
    SpatialAuthority,
    SpatialAvailabilityStatus,
    SpatialCapabilities,
    SpatialCapability,
    SpatialConfig,
    SpatialMapModel,
    SpatialMatchInput,
    SpatialMatchState,
    SpatialSnapshot,
    SpatialSourceSample,
    SpatialSummary,
    SpatialValidationIssue,
)
from .projectiles import (
    ProjectileCapabilities,
    ProjectileRunMetadata,
    ProjectileSnapshot,
    SpatialProjectile,
    UtilityEffect,
)

_C4_ITEM_DEFINITION_INDEX = 49
_SOURCE = "demoparser2:parse_ticks"


class SpatialEngine:
    """Attach decoded coordinates to authoritative Temporal ticks without analysis."""

    def __init__(self, map_registry: MapRegistry | None = None) -> None:
        self._maps = map_registry or DEFAULT_MAP_REGISTRY

    def compute(
        self, source: SpatialMatchInput, config: SpatialConfig | None = None
    ) -> SpatialMatchState:
        resolved = config or SpatialConfig()
        issues: list[SpatialValidationIssue] = []
        target_by_tick = {item.tick: item for item in source.tick_targets}
        timeline_by_round = {item.round_number: item for item in source.timelines}
        player_by_steam = {
            item.steam_id: item for item in source.players if item.steam_id is not None
        }
        participant_by_round = {
            timeline.round_number: {item.player_id: item for item in timeline.participants}
            for timeline in source.timelines
        }
        requested = tuple(item.tick for item in source.tick_targets)
        if source.extraction.requested_ticks != requested:
            issues.append(
                _issue(
                    "requested_tick_contract_mismatch",
                    ValidationSeverity.ERROR,
                    "spatial_extraction",
                    None,
                    "Extractor requested ticks differ from authoritative Temporal targets.",
                    {
                        "target_count": len(requested),
                        "extraction_count": len(source.extraction.requested_ticks),
                    },
                    fatal=True,
                )
            )
        if source.extraction.invalid_numeric_value_count:
            issues.append(
                _issue(
                    "nonfinite_source_values",
                    ValidationSeverity.WARNING,
                    "spatial_extraction",
                    None,
                    "NaN or Infinity source values were coerced to unavailable.",
                    {"count": source.extraction.invalid_numeric_value_count},
                )
            )
        self._validate_source_order(source, issues)
        snapshots: list[SpatialSnapshot] = []
        bombs: list[BombPositionSnapshot] = []
        seen: set[tuple[int, UUID]] = set()
        temporal_cache: dict[tuple[int, int], RoundSnapshot] = {}

        for sample in source.extraction.samples:
            target = target_by_tick.get(sample.tick)
            if target is None:
                issues.append(
                    _issue(
                        "snapshot_outside_requested_temporal_ticks",
                        ValidationSeverity.ERROR,
                        "source_sample",
                        f"{sample.steam_id}:{sample.tick}",
                        "Spatial source returned a tick not requested from Temporal.",
                        {"tick": sample.tick},
                    )
                )
                continue
            player = player_by_steam.get(sample.steam_id) if sample.steam_id is not None else None
            if player is None:
                issues.append(
                    _issue(
                        "participant_not_mapped",
                        ValidationSeverity.WARNING,
                        "source_sample",
                        f"{sample.steam_id}:{sample.tick}",
                        "Source row could not be mapped to a canonical player.",
                        {"tick": sample.tick, "steam_id": sample.steam_id},
                    )
                )
                continue
            participant = participant_by_round.get(target.round_number, {}).get(player.player_id)
            if participant is None:
                issues.append(
                    _issue(
                        "participant_missing_from_temporal_round",
                        ValidationSeverity.ERROR,
                        "player",
                        str(player.player_id),
                        "Canonical player is not a Temporal participant at this tick.",
                        {"tick": sample.tick, "round_number": target.round_number},
                    )
                )
                continue
            key = (sample.tick, player.player_id)
            if key in seen:
                issues.append(
                    _issue(
                        "duplicate_spatial_snapshot",
                        ValidationSeverity.ERROR,
                        "player",
                        str(player.player_id),
                        "More than one source row exists for participant and tick.",
                        {"tick": sample.tick},
                        fatal=True,
                    )
                )
                continue
            seen.add(key)
            timeline = timeline_by_round[target.round_number]
            cache_key = (target.round_number, sample.tick)
            temporal_snapshot = temporal_cache.get(cache_key)
            if temporal_snapshot is None:
                temporal_snapshot = SnapshotBuilder().at_tick(
                    timeline, sample.tick, source.temporal.config
                )
                temporal_cache[cache_key] = temporal_snapshot
            alive = _temporal_alive(temporal_snapshot, player.player_id)
            alive_status = (
                SpatialAvailabilityStatus.AVAILABLE
                if alive is not None
                else SpatialAvailabilityStatus.UNAVAILABLE
            )
            if (
                sample.source_alive is not None
                and alive is not None
                and sample.source_alive != alive
            ):
                issues.append(
                    _issue(
                        "source_alive_temporal_mismatch",
                        ValidationSeverity.WARNING,
                        "player",
                        str(player.player_id),
                        "Parser alive value differs from authoritative Temporal state.",
                        {
                            "tick": sample.tick,
                            "source_alive": sample.source_alive,
                            "temporal_alive": alive,
                        },
                    )
                )
            expected_team = (
                2 if participant.side is Side.T else 3 if participant.side is Side.CT else None
            )
            if (
                expected_team is not None
                and sample.source_team_number is not None
                and sample.source_team_number != expected_team
            ):
                issues.append(
                    _issue(
                        "source_team_temporal_side_mismatch",
                        ValidationSeverity.WARNING,
                        "player",
                        str(player.player_id),
                        "Parser team number differs from Temporal side membership.",
                        {
                            "tick": sample.tick,
                            "source_team_number": sample.source_team_number,
                            "temporal_side": participant.side.value,
                        },
                    )
                )
            coordinates, position_status = _validated_coordinates(sample, resolved, issues)
            angles, angle_status = _validated_angles(sample, issues)
            inventory_available = sample.inventory_item_ids is not None
            utility_inventory = _utility_inventory(sample.inventory_names)
            utility_inventory_status = (
                SpatialAvailabilityStatus.AVAILABLE
                if sample.inventory_names is not None
                else SpatialAvailabilityStatus.UNAVAILABLE
            )
            has_bomb = (
                _C4_ITEM_DEFINITION_INDEX in sample.inventory_item_ids
                if sample.inventory_item_ids is not None
                else None
            )
            bomb_status = (
                SpatialAvailabilityStatus.AVAILABLE
                if inventory_available
                else SpatialAvailabilityStatus.UNAVAILABLE
            )
            snapshot_warnings: list[str] = []
            position_authority = SpatialAuthority.DEMO_ENTITY_DERIVED
            if alive is False and position_status is SpatialAvailabilityStatus.AVAILABLE:
                position_status = SpatialAvailabilityStatus.UNRELIABLE
                position_authority = SpatialAuthority.UNRELIABLE
                snapshot_warnings.append("dead_pawn_position_is_not_player_location")
            elif position_status is SpatialAvailabilityStatus.UNAVAILABLE:
                position_authority = SpatialAuthority.UNAVAILABLE
            view_angle_authority = (
                SpatialAuthority.DEMO_ENTITY_DERIVED
                if angle_status is not SpatialAvailabilityStatus.UNAVAILABLE
                else SpatialAuthority.UNAVAILABLE
            )
            if alive is False and angle_status is not SpatialAvailabilityStatus.UNAVAILABLE:
                angle_status = SpatialAvailabilityStatus.UNRELIABLE
                view_angle_authority = SpatialAuthority.UNRELIABLE
                snapshot_warnings.append("dead_pawn_view_angle_is_not_player_view")
            snapshot_id = uuid5(
                source.match_id,
                f"spatial:{source.temporal.temporal_run_id}:{target.round_id}:{sample.tick}:{player.player_id}",
            )
            snapshot = SpatialSnapshot(
                snapshot_id=snapshot_id,
                match_id=source.match_id,
                temporal_run_id=source.temporal.temporal_run_id,
                round_id=target.round_id,
                round_number=target.round_number,
                tick=sample.tick,
                participant_id=player.player_id,
                x=coordinates[0],
                y=coordinates[1],
                z=coordinates[2],
                pitch=angles[0],
                yaw=angles[1],
                alive=alive,
                has_bomb=has_bomb,
                utility_inventory=utility_inventory,
                physical_team_id=participant.physical_team_id,
                side=participant.side,
                map_name=source.map_name,
                source=_SOURCE,
                position_authority=position_authority,
                view_angle_authority=view_angle_authority,
                has_bomb_source=(
                    "derived:inventory_as_ids_contains_49" if inventory_available else None
                ),
                utility_inventory_source=(
                    "demoparser2:parse_ticks:inventory"
                    if sample.inventory_names is not None
                    else None
                ),
                availability=SnapshotAvailability(
                    position=position_status,
                    view_angles=angle_status,
                    alive_link=alive_status,
                    has_bomb=bomb_status,
                    utility_inventory=utility_inventory_status,
                    warnings=tuple(snapshot_warnings),
                ),
            )
            snapshots.append(snapshot)
            x, y, z = coordinates
            if (
                has_bomb is True
                and alive is True
                and x is not None
                and y is not None
                and z is not None
            ):
                bombs.append(
                    BombPositionSnapshot(
                        snapshot_id=uuid5(snapshot_id, "bomb:carried"),
                        match_id=source.match_id,
                        temporal_run_id=source.temporal.temporal_run_id,
                        round_id=target.round_id,
                        round_number=target.round_number,
                        tick=sample.tick,
                        x=x,
                        y=y,
                        z=z,
                        carrier_participant_id=player.player_id,
                    )
                )

        ordered = tuple(
            sorted(
                snapshots, key=lambda item: (item.round_number, item.tick, str(item.participant_id))
            )
        )
        ordered_bombs = tuple(
            sorted(bombs, key=lambda item: (item.round_number, item.tick, str(item.snapshot_id)))
        )
        projectiles, projectile_snapshots, utility_effects = _projectile_state(
            source,
            resolved,
            player_by_steam,
            participant_by_round,
            issues,
        )
        projectile_capabilities = source.extraction.projectiles.capabilities
        projectile_capability_fingerprint = hashlib.sha256(
            canonical_json(
                {
                    "rule_version": source.extraction.projectiles.rule_version,
                    "requested_properties": source.extraction.projectiles.requested_properties,
                    "requested_events": source.extraction.projectiles.requested_events,
                    "sampling_interval_ticks": (
                        source.extraction.projectiles.sampling_interval_ticks
                    ),
                    "capabilities": projectile_capabilities.model_dump(mode="json"),
                }
            ).encode()
        ).hexdigest()
        projectile_metadata = ProjectileRunMetadata(
            extraction_rule_version=source.extraction.projectiles.rule_version,
            requested_properties=source.extraction.projectiles.requested_properties,
            requested_events=source.extraction.projectiles.requested_events,
            sampling_interval_ticks=source.extraction.projectiles.sampling_interval_ticks,
            capability_fingerprint=projectile_capability_fingerprint,
        )
        capabilities = _capabilities(ordered, ordered_bombs, resolved, source)
        extraction_evidence = source.extraction.map_selection_evidence
        selection = self._maps.select(
            MapSelectionEvidence(
                raw_map_name=source.map_name,
                patch_version=(
                    extraction_evidence.patch_version if extraction_evidence is not None else None
                ),
                map_crc=(extraction_evidence.map_crc if extraction_evidence is not None else None),
                asset_version=(
                    extraction_evidence.asset_version if extraction_evidence is not None else None
                ),
            )
        )
        map_semantics = self._maps.pin(selection)
        map_model = SpatialMapModel(
            map_name=source.map_name,
            warnings=(
                "demoparser2 provides map name but no authoritative bounds metadata",
                "spawn locations and bomb-site coordinates are not provided",
            ),
        )
        summary = SpatialSummary(
            rounds=len(source.timelines),
            requested_ticks=len(source.extraction.requested_ticks),
            source_rows=len(source.extraction.samples),
            snapshots=len(ordered),
            participants=len({item.participant_id for item in ordered}),
            bomb_position_snapshots=len(ordered_bombs),
            projectiles=len(projectiles),
            projectile_snapshots=len(projectile_snapshots),
            utility_effects=len(utility_effects),
            validation_issue_count=len(issues),
        )
        state_warnings = tuple(
            dict.fromkeys(
                (
                    *source.extraction.warnings,
                    *source.extraction.projectiles.warnings,
                    *map_model.warnings,
                    *map_semantics.warnings,
                    *_capability_warnings(capabilities),
                    *_projectile_capability_warnings(projectile_capabilities),
                )
            )
        )
        config_hash = hashlib.sha256(
            canonical_json(resolved.model_dump(mode="json")).encode()
        ).hexdigest()
        fingerprint_payload = {
            "spatial_schema_version": SPATIAL_SCHEMA_VERSION,
            "spatial_rule_version": SPATIAL_RULE_VERSION,
            "config": resolved.model_dump(mode="json"),
            "dataset_fingerprint": source.dataset_fingerprint,
            "temporal_fingerprint": source.temporal.temporal_fingerprint,
            "source_demo_sha256": source.extraction.source_demo_sha256,
            "parser": [source.extraction.parser_name, source.extraction.parser_version],
            "map_model": map_model.model_dump(mode="json"),
            "map_semantics": map_semantics.model_dump(mode="json"),
            "capabilities": capabilities.model_dump(mode="json"),
            "projectile_metadata": projectile_metadata.model_dump(mode="json"),
            "projectile_capabilities": projectile_capabilities.model_dump(mode="json"),
            "snapshots": [item.model_dump(mode="json") for item in ordered],
            "bomb_positions": [item.model_dump(mode="json") for item in ordered_bombs],
            "projectiles": [item.model_dump(mode="json") for item in projectiles],
            "projectile_snapshots": [item.model_dump(mode="json") for item in projectile_snapshots],
            "utility_effects": [item.model_dump(mode="json") for item in utility_effects],
            "validation_issues": [item.model_dump(mode="json") for item in issues],
        }
        fingerprint = hashlib.sha256(canonical_json(fingerprint_payload).encode()).hexdigest()
        return SpatialMatchState(
            spatial_run_id=uuid5(source.match_id, f"spatial-run:{fingerprint}"),
            spatial_fingerprint=fingerprint,
            spatial_config_hash=config_hash,
            match_id=source.match_id,
            dataset_fingerprint=source.dataset_fingerprint,
            temporal_run_id=source.temporal.temporal_run_id,
            temporal_fingerprint=source.temporal.temporal_fingerprint,
            source_demo_sha256=source.extraction.source_demo_sha256,
            parser_name=source.extraction.parser_name,
            parser_version=source.extraction.parser_version,
            config=resolved,
            map_model=map_model,
            map_semantics=map_semantics,
            capabilities=capabilities,
            projectile_metadata=projectile_metadata,
            projectile_capabilities=projectile_capabilities,
            summary=summary,
            snapshots=ordered,
            bomb_positions=ordered_bombs,
            projectiles=projectiles,
            projectile_snapshots=projectile_snapshots,
            utility_effects=utility_effects,
            validation_issues=tuple(issues),
            warnings=state_warnings,
        )

    @staticmethod
    def _validate_source_order(
        source: SpatialMatchInput, issues: list[SpatialValidationIssue]
    ) -> None:
        last_by_steam: dict[str, int] = {}
        for sample in source.extraction.samples:
            if sample.steam_id is None:
                continue
            previous = last_by_steam.get(sample.steam_id)
            if previous is not None and sample.tick < previous:
                issues.append(
                    _issue(
                        "non_monotonic_source_ticks",
                        ValidationSeverity.ERROR,
                        "source_sample",
                        sample.steam_id,
                        "Source ticks are not monotonic for one player.",
                        {"previous_tick": previous, "tick": sample.tick},
                        fatal=True,
                    )
                )
            last_by_steam[sample.steam_id] = sample.tick


def _projectile_state(
    source: SpatialMatchInput,
    config: SpatialConfig,
    player_by_steam: dict[str, CanonicalPlayer],
    participant_by_round: dict[int, dict[UUID, ParticipantRoundState]],
    issues: list[SpatialValidationIssue],
) -> tuple[
    tuple[SpatialProjectile, ...],
    tuple[ProjectileSnapshot, ...],
    tuple[UtilityEffect, ...],
]:
    projectiles: list[SpatialProjectile] = []
    snapshots: list[ProjectileSnapshot] = []
    effects: list[UtilityEffect] = []
    projectile_by_track: dict[str, tuple[UUID, RoundTimeline]] = {}
    for track in source.extraction.projectiles.tracks:
        timeline = _timeline_at_tick(source.timelines, track.first_position_tick)
        if timeline is None:
            issues.append(
                _issue(
                    "projectile_outside_temporal_round",
                    ValidationSeverity.WARNING,
                    "projectile",
                    track.source_track_id,
                    "Projectile track could not be assigned to a Temporal round.",
                    {"first_position_tick": track.first_position_tick},
                )
            )
            continue
        player = (
            player_by_steam.get(track.owner_steam_id) if track.owner_steam_id is not None else None
        )
        participant = (
            participant_by_round.get(timeline.round_number, {}).get(player.player_id)
            if player is not None
            else None
        )
        warnings = list(track.warnings)
        if participant is None:
            warnings.append("projectile_owner_participant_unmapped")
            issues.append(
                _issue(
                    "projectile_owner_unmapped",
                    ValidationSeverity.WARNING,
                    "projectile",
                    track.source_track_id,
                    "Projectile owner could not be mapped to the Temporal round participant.",
                    {
                        "owner_steam_id": track.owner_steam_id,
                        "round_number": timeline.round_number,
                    },
                )
            )
        projectile_id = uuid5(
            source.match_id,
            f"projectile:{source.temporal.temporal_run_id}:{track.source_track_id}",
        )
        projectile_by_track[track.source_track_id] = (projectile_id, timeline)
        projectiles.append(
            SpatialProjectile(
                projectile_id=projectile_id,
                match_id=source.match_id,
                temporal_run_id=source.temporal.temporal_run_id,
                round_id=timeline.round_id,
                round_number=timeline.round_number,
                source_track_id=track.source_track_id,
                source_entity_id=track.source_entity_id,
                projectile_type=track.projectile_type,
                raw_projectile_type=track.raw_projectile_type,
                owner_participant_id=(player.player_id if player is not None else None),
                owner_physical_team_id=(
                    participant.physical_team_id if participant is not None else None
                ),
                owner_side=participant.side if participant is not None else Side.UNKNOWN,
                thrown_tick=track.thrown_tick,
                first_position_tick=track.first_position_tick,
                terminal_tick=track.terminal_tick,
                terminal_event=track.terminal_event,
                initial_velocity_x=track.initial_velocity_x,
                initial_velocity_y=track.initial_velocity_y,
                initial_velocity_z=track.initial_velocity_z,
                availability=track.availability,
                source=track.source,
                warnings=tuple(warnings),
            )
        )
        for point in track.points:
            coordinates = (point.x, point.y, point.z)
            if any(
                not isfinite(value) or abs(value) > config.max_abs_coordinate
                for value in coordinates
            ):
                issues.append(
                    _issue(
                        "invalid_entity_coordinate",
                        ValidationSeverity.WARNING,
                        "projectile_snapshot",
                        f"{track.source_track_id}:{point.tick}",
                        "Projectile coordinate is non-finite or exceeds the safety bound.",
                        {"tick": point.tick},
                    )
                )
                continue
            snapshots.append(
                ProjectileSnapshot(
                    snapshot_id=uuid5(projectile_id, f"snapshot:{point.tick}"),
                    projectile_id=projectile_id,
                    match_id=source.match_id,
                    temporal_run_id=source.temporal.temporal_run_id,
                    round_id=timeline.round_id,
                    round_number=timeline.round_number,
                    tick=point.tick,
                    x=point.x,
                    y=point.y,
                    z=point.z,
                    bounce_count=point.bounce_count,
                    lifecycle=point.lifecycle,
                    availability=point.availability,
                    source=point.source,
                    warnings=point.warnings,
                )
            )
    for source_effect in source.extraction.projectiles.effects:
        linked = (
            projectile_by_track.get(source_effect.source_track_id)
            if source_effect.source_track_id is not None
            else None
        )
        timeline = (
            linked[1]
            if linked is not None
            else _timeline_at_tick(source.timelines, source_effect.start_tick)
        )
        if timeline is None:
            issues.append(
                _issue(
                    "utility_effect_outside_temporal_round",
                    ValidationSeverity.WARNING,
                    "utility_effect",
                    source_effect.source_effect_id,
                    "Utility effect could not be assigned to a Temporal round.",
                    {"start_tick": source_effect.start_tick},
                )
            )
            continue
        center = (source_effect.center_x, source_effect.center_y, source_effect.center_z)
        if any(value is None for value in center):
            center = (None, None, None)
        elif any(
            not isfinite(value) or abs(value) > config.max_abs_coordinate
            for value in center
            if value is not None
        ):
            center = (None, None, None)
        linked_projectile_id = linked[0] if linked is not None else None
        effects.append(
            UtilityEffect(
                effect_id=uuid5(
                    source.match_id,
                    f"utility-effect:{source.temporal.temporal_run_id}:"
                    f"{source_effect.source_effect_id}",
                ),
                projectile_id=linked_projectile_id,
                match_id=source.match_id,
                temporal_run_id=source.temporal.temporal_run_id,
                round_id=timeline.round_id,
                round_number=timeline.round_number,
                effect_type=source_effect.effect_type,
                start_tick=source_effect.start_tick,
                end_tick=source_effect.end_tick,
                center_x=center[0],
                center_y=center[1],
                center_z=center[2],
                radius=None,
                availability=source_effect.availability,
                source=source_effect.source,
                warnings=(
                    *source_effect.warnings,
                    "effect_radius_unavailable_not_rendered_as_gameplay_radius",
                ),
            )
        )
    return (
        tuple(
            sorted(
                projectiles,
                key=lambda item: (
                    item.round_number,
                    item.first_position_tick,
                    str(item.projectile_id),
                ),
            )
        ),
        tuple(
            sorted(
                snapshots,
                key=lambda item: (
                    item.round_number,
                    item.tick,
                    str(item.projectile_id),
                ),
            )
        ),
        tuple(
            sorted(
                effects,
                key=lambda item: (
                    item.round_number,
                    item.start_tick,
                    str(item.effect_id),
                ),
            )
        ),
    )


def _timeline_at_tick(timelines: tuple[RoundTimeline, ...], tick: int) -> RoundTimeline | None:
    candidates = []
    for timeline in timelines:
        start = timeline.live_start_tick or timeline.freeze_end_tick or timeline.start_tick
        end = timeline.effective_end_tick or timeline.official_end_tick or timeline.end_tick
        if start is not None and end is not None and start <= tick <= end:
            candidates.append(timeline)
    return min(candidates, key=lambda item: item.round_number) if candidates else None


def _temporal_alive(snapshot: RoundSnapshot, player_id: UUID) -> bool | None:
    if snapshot.state_status is not SnapshotStateStatus.AVAILABLE:
        return None
    if player_id in snapshot.alive_players:
        return True
    if player_id in snapshot.dead_players:
        return False
    if player_id in snapshot.unknown_players:
        return None
    return None


def _validated_coordinates(
    sample: SpatialSourceSample,
    config: SpatialConfig,
    issues: list[SpatialValidationIssue],
) -> tuple[tuple[float | None, float | None, float | None], SpatialAvailabilityStatus]:
    values = (sample.x, sample.y, sample.z)
    if any(value is None for value in values):
        if any(value is not None for value in values):
            issues.append(
                _issue(
                    "incomplete_coordinate_tuple",
                    ValidationSeverity.WARNING,
                    "source_sample",
                    f"{sample.steam_id}:{sample.tick}",
                    "Position has only part of the required X/Y/Z tuple.",
                    {"tick": sample.tick},
                )
            )
        return (None, None, None), SpatialAvailabilityStatus.UNAVAILABLE
    x, y, z = values
    assert x is not None and y is not None and z is not None
    coordinates = (x, y, z)
    if any(not isfinite(value) or abs(value) > config.max_abs_coordinate for value in coordinates):
        issues.append(
            _issue(
                "invalid_or_overflow_coordinate",
                ValidationSeverity.ERROR,
                "source_sample",
                f"{sample.steam_id}:{sample.tick}",
                "Coordinate is non-finite or exceeds the configured safety bound.",
                {"tick": sample.tick},
            )
        )
        return (None, None, None), SpatialAvailabilityStatus.UNAVAILABLE
    return coordinates, SpatialAvailabilityStatus.AVAILABLE


def _validated_angles(
    sample: SpatialSourceSample,
    issues: list[SpatialValidationIssue],
) -> tuple[tuple[float | None, float | None], SpatialAvailabilityStatus]:
    values = (sample.pitch, sample.yaw)
    if all(value is None for value in values):
        return values, SpatialAvailabilityStatus.UNAVAILABLE
    if any(value is not None and not isfinite(value) for value in values):
        issues.append(
            _issue(
                "invalid_view_angle",
                ValidationSeverity.WARNING,
                "source_sample",
                f"{sample.steam_id}:{sample.tick}",
                "View angle is non-finite.",
                {"tick": sample.tick},
            )
        )
        return (None, None), SpatialAvailabilityStatus.UNAVAILABLE
    return values, (
        SpatialAvailabilityStatus.AVAILABLE
        if all(value is not None for value in values)
        else SpatialAvailabilityStatus.PARTIAL
    )


def _capabilities(
    snapshots: tuple[SpatialSnapshot, ...],
    bombs: tuple[BombPositionSnapshot, ...],
    config: SpatialConfig,
    source: SpatialMatchInput,
) -> SpatialCapabilities:
    population = len(snapshots)
    position_covered = sum(
        item.availability.position is SpatialAvailabilityStatus.AVAILABLE for item in snapshots
    )
    angle_covered = sum(
        item.availability.view_angles is SpatialAvailabilityStatus.AVAILABLE for item in snapshots
    )
    angle_any = sum(
        item.availability.view_angles
        in {SpatialAvailabilityStatus.AVAILABLE, SpatialAvailabilityStatus.UNRELIABLE}
        for item in snapshots
    )
    position_any = sum(
        item.availability.position
        in {SpatialAvailabilityStatus.AVAILABLE, SpatialAvailabilityStatus.UNRELIABLE}
        for item in snapshots
    )
    return SpatialCapabilities(
        positions=SpatialCapability(
            status=_coverage_status(position_covered, population),
            authority=SpatialAuthority.DEMO_ENTITY_DERIVED,
            population=population,
            covered=position_covered,
            source_fields=("X", "Y", "Z"),
            sampling_interval_ticks=config.sampling_interval_ticks,
            warnings=(
                f"{position_any - position_covered} dead-pawn positions excluded "
                "from reliable coverage",
            )
            if position_any != position_covered
            else (),
        ),
        view_angles=SpatialCapability(
            status=_coverage_status(angle_covered, population),
            authority=SpatialAuthority.DEMO_ENTITY_DERIVED,
            population=population,
            covered=angle_covered,
            source_fields=("pitch", "yaw"),
            sampling_interval_ticks=config.sampling_interval_ticks,
            warnings=(
                f"{angle_any - angle_covered} dead-pawn view angles excluded "
                "from reliable coverage",
            )
            if angle_any != angle_covered
            else (),
        ),
        bomb_positions=SpatialCapability(
            status=(
                SpatialAvailabilityStatus.PARTIAL
                if bombs
                else SpatialAvailabilityStatus.UNAVAILABLE
            ),
            authority=(SpatialAuthority.DERIVED if bombs else SpatialAuthority.UNAVAILABLE),
            population=len(source.extraction.requested_ticks),
            covered=len({item.tick for item in bombs}),
            source_fields=("inventory_as_ids", "X", "Y", "Z"),
            sampling_interval_ticks=config.sampling_interval_ticks,
            warnings=(
                "only carried C4 position is derived; dropped/planted C4 entity "
                "position unavailable",
            ),
        ),
        map_metadata=SpatialCapability(
            status=SpatialAvailabilityStatus.PARTIAL,
            authority=SpatialAuthority.DEMO_ENTITY_DERIVED,
            population=4,
            covered=1,
            source_fields=("header.map_name",),
            warnings=("bounds, spawns and bomb-site coordinates unavailable",),
        ),
        sampling_frequency=SpatialCapability(
            status=SpatialAvailabilityStatus.AVAILABLE,
            authority=SpatialAuthority.TEMPORAL_AUTHORITATIVE,
            population=len(source.extraction.requested_ticks),
            covered=len(source.extraction.requested_ticks),
            sampling_interval_ticks=config.sampling_interval_ticks,
            source_fields=("tick",),
        ),
    )


def _coverage_status(covered: int, population: int) -> SpatialAvailabilityStatus:
    if population == 0 or covered == 0:
        return SpatialAvailabilityStatus.UNAVAILABLE
    return (
        SpatialAvailabilityStatus.AVAILABLE
        if covered == population
        else SpatialAvailabilityStatus.PARTIAL
    )


def _utility_inventory(items: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if items is None:
        return None
    aliases = {
        "flashbang": "flashbang",
        "smokegrenade": "smoke",
        "hegrenade": "he_grenade",
        "molotov": "molotov",
        "incgrenade": "incendiary",
        "incendiarygrenade": "incendiary",
        "decoy": "decoy",
        "decoygrenade": "decoy",
    }
    result = []
    for item in items:
        key = item.casefold().replace("weapon_", "").replace(" ", "").replace("_", "")
        if normalized := aliases.get(key):
            result.append(normalized)
    return tuple(result)


def _capability_warnings(capabilities: SpatialCapabilities) -> tuple[str, ...]:
    result: list[str] = []
    for name in SpatialCapabilities.model_fields:
        capability = getattr(capabilities, name)
        result.extend(f"{name}:{item}" for item in capability.warnings)
    return tuple(result)


def _projectile_capability_warnings(
    capabilities: ProjectileCapabilities,
) -> tuple[str, ...]:
    result: list[str] = []
    for name in ProjectileCapabilities.model_fields:
        capability = getattr(capabilities, name)
        result.extend(f"projectile_{name}:{item}" for item in capability.warnings)
    return tuple(result)


def _issue(
    code: str,
    severity: ValidationSeverity,
    entity_type: str,
    entity_id: str | None,
    message: str,
    evidence: dict[str, JsonValue],
    *,
    fatal: bool = False,
) -> SpatialValidationIssue:
    return SpatialValidationIssue(
        code=code,
        severity=severity,
        is_fatal=fatal,
        entity_type=entity_type,
        entity_id=entity_id,
        message=message,
        evidence=evidence,
    )
