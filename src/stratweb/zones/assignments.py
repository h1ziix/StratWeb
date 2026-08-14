"""Pure deterministic engine assigning immutable spatial snapshots to authored zones."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any
from uuid import UUID, uuid5

from pydantic import TypeAdapter

from stratweb.application.normalization_utils import canonical_json
from stratweb.exceptions import ZoneAssignmentIntegrityError
from stratweb.maps.models import MapSelectionStatus
from stratweb.spatial.models import SpatialAvailabilityStatus, SpatialRunSummary, SpatialSnapshot
from stratweb.zones.assignment_models import (
    ZONE_ASSIGNMENT_RULE_VERSION,
    ZONE_ASSIGNMENT_SCHEMA_VERSION,
    ZoneAssignment,
    ZoneAssignmentCapability,
    ZoneAssignmentConfig,
    ZoneAssignmentState,
    ZoneAssignmentStatus,
    ZoneAssignmentSummary,
)
from stratweb.zones.engine import resolve_zone
from stratweb.zones.models import (
    ZONE_RESOLUTION_RULE_VERSION,
    ZONE_SCHEMA_VERSION,
    ZoneResolutionStatus,
    ZoneSetDefinition,
    ZoneVerificationStatus,
)
from stratweb.zones.validation import ZONE_VALIDATION_RULE_VERSION, validate_zone_set

_RUN_NAMESPACE = UUID("5197422c-bb08-4fa0-a2a7-f6205eb60b5f")
_ASSIGNMENT_NAMESPACE = UUID("f29c9c5f-e347-4b19-a3d2-945b23d676c4")


class ZoneAssignmentEngine:
    def compute(
        self,
        spatial: SpatialRunSummary,
        snapshots: Iterable[SpatialSnapshot],
        zone_set: ZoneSetDefinition | None,
        config: ZoneAssignmentConfig,
    ) -> ZoneAssignmentState:
        ordered = tuple(
            sorted(
                snapshots,
                key=lambda item: (
                    item.round_number,
                    item.tick,
                    str(item.participant_id),
                    str(item.snapshot_id),
                ),
            )
        )
        self._validate_input(spatial, ordered, zone_set)
        semantics = spatial.map_semantics
        map_name = semantics.canonical_name if semantics is not None else None
        map_revision = semantics.selected_map_revision if semantics is not None else None
        selection_status = semantics.selection_status if semantics is not None else None
        zone_set_fingerprint = zone_set.fingerprint() if zone_set is not None else None
        proposed_zone_count = (
            sum(zone.verification is ZoneVerificationStatus.PROPOSED for zone in zone_set.zones)
            if zone_set is not None
            else 0
        )
        effective_zone_set = (
            zone_set.model_copy(
                update={
                    "zones": tuple(
                        zone
                        for zone in zone_set.zones
                        if zone.verification is not ZoneVerificationStatus.PROPOSED
                    )
                }
            )
            if zone_set is not None
            else None
        )
        unavailable_reason = self._unavailable_reason(spatial, zone_set, config)
        zone_set_key = zone_set_fingerprint or f"unavailable:{unavailable_reason}"
        config_hash = hashlib.sha256(
            canonical_json(config.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()

        preliminary: list[dict[str, object]] = []
        for snapshot in ordered:
            preliminary.append(
                self._resolve_snapshot(
                    snapshot, spatial.spatial_run_id, effective_zone_set, unavailable_reason
                )
            )
        fingerprint = self._fingerprint(
            spatial,
            map_name,
            map_revision,
            zone_set_fingerprint,
            zone_set_key,
            config_hash,
            preliminary,
        )
        run_id = uuid5(_RUN_NAMESPACE, fingerprint)
        assignments = tuple(
            ZoneAssignment(
                assignment_id=uuid5(
                    _ASSIGNMENT_NAMESPACE, f"{run_id}:{item['spatial_snapshot_id']}"
                ),
                zone_assignment_run_id=run_id,
                **item,
            )
            for item in preliminary
        )
        position_available = sum(
            item.x is not None and item.y is not None and item.z is not None for item in ordered
        )
        resolved = sum(item.status is ZoneAssignmentStatus.RESOLVED for item in assignments)
        unknown = sum(item.status is ZoneAssignmentStatus.UNKNOWN for item in assignments)
        unavailable = sum(item.status is ZoneAssignmentStatus.UNAVAILABLE for item in assignments)
        warnings = self._warnings(
            spatial, unavailable_reason, selection_status, proposed_zone_count
        )
        capability_status = self._capability_status(
            len(assignments),
            resolved,
            unknown,
            unavailable,
            unavailable_reason,
            selection_status,
            proposed_zone_count,
        )
        capability = ZoneAssignmentCapability(
            status=capability_status,
            population=len(assignments),
            resolved=resolved,
            unknown=unknown,
            unavailable=unavailable,
            warnings=warnings,
        )
        summary = ZoneAssignmentSummary(
            snapshots=len(assignments),
            rounds=len({item.round_number for item in ordered}),
            participants=len({item.participant_id for item in ordered}),
            position_available=position_available,
            resolved=resolved,
            unknown=unknown,
            unavailable=unavailable,
            coverage=(resolved / position_available if position_available else None),
        )
        return ZoneAssignmentState(
            zone_assignment_run_id=run_id,
            zone_assignment_fingerprint=fingerprint,
            zone_assignment_config_hash=config_hash,
            match_id=spatial.match_id,
            dataset_fingerprint=spatial.dataset_fingerprint,
            spatial_run_id=spatial.spatial_run_id,
            spatial_fingerprint=spatial.spatial_fingerprint,
            spatial_schema_version=spatial.spatial_schema_version,
            spatial_rule_version=spatial.spatial_rule_version,
            canonical_map_name=map_name,
            selected_map_revision=map_revision,
            map_definition_fingerprint=(
                semantics.map_definition_fingerprint if semantics is not None else None
            ),
            map_revision_selection_status=selection_status,
            zone_set_fingerprint=zone_set_fingerprint,
            zone_set_key=zone_set_key,
            zone_schema_version=ZONE_SCHEMA_VERSION if zone_set is not None else None,
            zone_resolution_rule_version=(
                ZONE_RESOLUTION_RULE_VERSION if zone_set is not None else None
            ),
            zone_validation_rule_version=(
                ZONE_VALIDATION_RULE_VERSION if zone_set is not None else None
            ),
            config=config,
            capability=capability,
            summary=summary,
            assignments=assignments,
            warnings=warnings,
        )

    @staticmethod
    def _validate_input(
        spatial: SpatialRunSummary,
        snapshots: tuple[SpatialSnapshot, ...],
        zone_set: ZoneSetDefinition | None,
    ) -> None:
        if len(snapshots) != spatial.summary.snapshots:
            raise ZoneAssignmentIntegrityError(
                "Zone assignment input does not contain every Spatial snapshot."
            )
        if len({snapshot.snapshot_id for snapshot in snapshots}) != len(snapshots):
            raise ZoneAssignmentIntegrityError("Zone assignment input contains duplicates.")
        for snapshot in snapshots:
            if snapshot.match_id != spatial.match_id:
                raise ZoneAssignmentIntegrityError("Snapshot match does not match Spatial run.")
            if snapshot.temporal_run_id != spatial.temporal_run_id:
                raise ZoneAssignmentIntegrityError(
                    "Snapshot Temporal run does not match Spatial provenance."
                )
            if snapshot.map_name != spatial.map_model.map_name:
                raise ZoneAssignmentIntegrityError(
                    "Snapshot map does not match the Spatial map model."
                )
        if zone_set is None:
            return
        issues = validate_zone_set(zone_set)
        if issues:
            raise ZoneAssignmentIntegrityError(
                "Zone set failed structural validation: " + ", ".join(issues[:10])
            )
        semantics = spatial.map_semantics
        if semantics is None:
            raise ZoneAssignmentIntegrityError(
                "A zone set cannot be applied to a legacy Spatial run without map semantics."
            )
        if (zone_set.map_name, zone_set.map_revision) != (
            semantics.canonical_name,
            semantics.selected_map_revision,
        ):
            raise ZoneAssignmentIntegrityError(
                "Zone set map/revision does not match the pinned Spatial map semantics."
            )

    @staticmethod
    def _unavailable_reason(
        spatial: SpatialRunSummary,
        zone_set: ZoneSetDefinition | None,
        config: ZoneAssignmentConfig,
    ) -> str | None:
        semantics = spatial.map_semantics
        if semantics is None:
            return "legacy_map_semantics"
        if semantics.canonical_name is None or semantics.selected_map_revision is None:
            return "map_revision_unavailable"
        if zone_set is None:
            return "zone_set_unavailable"
        if all(zone.verification is ZoneVerificationStatus.PROPOSED for zone in zone_set.zones):
            return "zone_geometry_unverified"
        if (
            semantics.selection_status is MapSelectionStatus.UNPROVEN
            and not config.allow_unproven_map_revision
        ):
            return "unproven_map_revision_blocked"
        return None

    @staticmethod
    def _resolve_snapshot(
        snapshot: SpatialSnapshot,
        spatial_run_id: UUID,
        zone_set: ZoneSetDefinition | None,
        unavailable_reason: str | None,
    ) -> dict[str, object]:
        base: dict[str, object] = {
            "spatial_run_id": spatial_run_id,
            "spatial_snapshot_id": snapshot.snapshot_id,
            "match_id": snapshot.match_id,
            "round_id": snapshot.round_id,
            "round_number": snapshot.round_number,
            "tick": snapshot.tick,
            "participant_id": snapshot.participant_id,
        }
        if unavailable_reason is not None:
            return {
                **base,
                "status": ZoneAssignmentStatus.UNAVAILABLE,
                "warnings": (unavailable_reason,),
            }
        if snapshot.x is None or snapshot.y is None or snapshot.z is None:
            return {
                **base,
                "status": ZoneAssignmentStatus.UNAVAILABLE,
                "warnings": ("position_unavailable",),
            }
        assert zone_set is not None
        resolution = resolve_zone(zone_set, snapshot.x, snapshot.y, snapshot.z)
        if resolution.status is ZoneResolutionStatus.UNKNOWN:
            return {
                **base,
                "status": ZoneAssignmentStatus.UNKNOWN,
                "warnings": resolution.warnings,
            }
        return {
            **base,
            "status": ZoneAssignmentStatus.RESOLVED,
            "zone_id": resolution.zone_id,
            "zone_name": resolution.zone_name,
            "kind": resolution.kind,
            "level": resolution.level,
            "warnings": resolution.warnings,
        }

    @staticmethod
    def _fingerprint(
        spatial: SpatialRunSummary,
        map_name: str | None,
        map_revision: str | None,
        zone_set_fingerprint: str | None,
        zone_set_key: str,
        config_hash: str,
        preliminary: list[dict[str, object]],
    ) -> str:
        digest = hashlib.sha256()
        metadata = {
            "zone_assignment_schema_version": ZONE_ASSIGNMENT_SCHEMA_VERSION,
            "zone_assignment_rule_version": ZONE_ASSIGNMENT_RULE_VERSION,
            "spatial_fingerprint": spatial.spatial_fingerprint,
            "canonical_map_name": map_name,
            "selected_map_revision": map_revision,
            "zone_set_fingerprint": zone_set_fingerprint,
            "zone_set_key": zone_set_key,
            "config_hash": config_hash,
        }
        digest.update(canonical_json(metadata).encode("utf-8"))
        for item in preliminary:
            fingerprint_payload: Any = {
                key: value for key, value in item.items() if key != "spatial_run_id"
            }
            serializable = TypeAdapter(Any).dump_python(fingerprint_payload, mode="json")
            digest.update(b"\n")
            digest.update(canonical_json(serializable).encode("utf-8"))
        return digest.hexdigest()

    @staticmethod
    def _warnings(
        spatial: SpatialRunSummary,
        unavailable_reason: str | None,
        selection_status: MapSelectionStatus | None,
        proposed_zone_count: int,
    ) -> tuple[str, ...]:
        warnings = list(spatial.map_semantics.warnings if spatial.map_semantics else ())
        if unavailable_reason is not None:
            warnings.append(unavailable_reason)
        if selection_status is MapSelectionStatus.UNPROVEN:
            warnings.append("zone_assignments_use_unproven_map_revision")
        if proposed_zone_count:
            warnings.append(f"proposed_zones_excluded:{proposed_zone_count}")
        return tuple(dict.fromkeys(warnings))

    @staticmethod
    def _capability_status(
        population: int,
        resolved: int,
        unknown: int,
        unavailable: int,
        unavailable_reason: str | None,
        selection_status: MapSelectionStatus | None,
        proposed_zone_count: int,
    ) -> SpatialAvailabilityStatus:
        if population == 0 or unavailable_reason is not None:
            return SpatialAvailabilityStatus.UNAVAILABLE
        if (
            unknown
            or unavailable
            or proposed_zone_count
            or selection_status is not MapSelectionStatus.PROVEN
        ):
            return SpatialAvailabilityStatus.PARTIAL
        if resolved == population:
            return SpatialAvailabilityStatus.AVAILABLE
        return SpatialAvailabilityStatus.UNAVAILABLE


__all__ = ["ZoneAssignmentEngine"]
