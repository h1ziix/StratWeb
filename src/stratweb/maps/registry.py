"""Exact-alias, revision-aware map registry without fuzzy fallback."""

from __future__ import annotations

from collections import defaultdict

from stratweb.maps.definitions import ALL_DEFINITIONS
from stratweb.maps.models import (
    CalibrationStatus,
    MapDefinition,
    MapRevisionKind,
    MapSelectionEvidence,
    MapSelectionResult,
    MapSelectionStatus,
    MapSemanticsPin,
    MapValidationStatus,
)


class MapRegistry:
    def __init__(self, definitions: tuple[MapDefinition, ...]) -> None:
        if not definitions:
            raise ValueError("map registry requires at least one definition")
        by_map: dict[str, list[MapDefinition]] = defaultdict(list)
        aliases: dict[str, str] = {}
        fingerprints: dict[str, MapDefinition] = {}
        for definition in definitions:
            by_map[definition.canonical_name].append(definition)
            fingerprints[definition.definition_fingerprint] = definition
            for raw_alias in definition.aliases:
                alias = _alias_key(raw_alias)
                existing = aliases.get(alias)
                if existing is not None and existing != definition.canonical_name:
                    raise ValueError(f"map alias collision: {raw_alias}")
                aliases[alias] = definition.canonical_name
        for canonical_name, revisions in by_map.items():
            revision_ids = [item.map_revision.revision_id for item in revisions]
            if len(revision_ids) != len(set(revision_ids)):
                raise ValueError(f"duplicate map revision: {canonical_name}")
        self._by_map = {
            key: tuple(sorted(value, key=_revision_sort_key)) for key, value in by_map.items()
        }
        self._aliases = aliases
        self._fingerprints = fingerprints

    def canonicalize(self, raw_map_name: str) -> str | None:
        """Apply only whitespace/case normalization followed by an exact alias lookup."""

        return self._aliases.get(_alias_key(raw_map_name))

    def list_maps(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_map))

    def revisions(self, canonical_or_alias: str) -> tuple[MapDefinition, ...]:
        canonical = self.canonicalize(canonical_or_alias)
        return self._by_map.get(canonical, ()) if canonical is not None else ()

    def get_revision(self, canonical_or_alias: str, revision_id: str) -> MapDefinition | None:
        return next(
            (
                item
                for item in self.revisions(canonical_or_alias)
                if item.map_revision.revision_id == revision_id
            ),
            None,
        )

    def definition_by_fingerprint(self, fingerprint: str) -> MapDefinition | None:
        return self._fingerprints.get(fingerprint)

    def preferred_definition(self, canonical_or_alias: str) -> MapDefinition | None:
        configured = tuple(
            item
            for item in self.revisions(canonical_or_alias)
            if item.validation_status is not MapValidationStatus.UNSUPPORTED
            and item.map_revision.kind is MapRevisionKind.CURRENT
        )
        return configured[0] if len(configured) == 1 else None

    def select(self, evidence: MapSelectionEvidence) -> MapSelectionResult:
        canonical = self.canonicalize(evidence.raw_map_name)
        if canonical is None:
            return MapSelectionResult(
                raw_map_name=evidence.raw_map_name,
                canonical_name=None,
                display_name=None,
                status=MapSelectionStatus.UNSUPPORTED,
                selected_definition=None,
                warnings=("unsupported_map",),
            )
        revisions = self._by_map[canonical]
        display_name = revisions[0].display_name
        if evidence.manual_revision is not None:
            selected = self.get_revision(canonical, evidence.manual_revision)
            if selected is None:
                return MapSelectionResult(
                    raw_map_name=evidence.raw_map_name,
                    canonical_name=canonical,
                    display_name=display_name,
                    status=MapSelectionStatus.UNSUPPORTED,
                    selected_definition=None,
                    evidence=(f"manual_revision:{evidence.manual_revision}",),
                    warnings=("manual_revision_unknown",),
                )
            warnings = ["manual_revision_override"]
            if not selected.transform_available:
                warnings.append("selected_revision_calibration_unavailable")
            return MapSelectionResult(
                raw_map_name=evidence.raw_map_name,
                canonical_name=canonical,
                display_name=display_name,
                status=MapSelectionStatus.PROVEN,
                selected_definition=selected,
                evidence=(f"manual_revision:{selected.map_revision.revision_id}",),
                warnings=tuple(warnings),
            )
        selectors = (
            ("patch_version", evidence.patch_version, "compatible_patch_versions"),
            ("map_crc", evidence.map_crc, "compatible_map_crcs"),
            ("asset_version", evidence.asset_version, "compatible_asset_versions"),
        )
        selector_matches: list[tuple[str, str, tuple[MapDefinition, ...]]] = []
        for label, value, attribute in selectors:
            if value is None:
                continue
            matches = tuple(
                item for item in revisions if value in getattr(item.map_revision, attribute)
            )
            if len(matches) > 1:
                return MapSelectionResult(
                    raw_map_name=evidence.raw_map_name,
                    canonical_name=canonical,
                    display_name=display_name,
                    status=MapSelectionStatus.UNSUPPORTED,
                    selected_definition=None,
                    evidence=(f"{label}:{value}",),
                    warnings=("map_revision_evidence_ambiguous",),
                )
            selector_matches.append((label, value, matches))
        matched_definitions = {
            matches[0].definition_fingerprint
            for _, _, matches in selector_matches
            if len(matches) == 1
        }
        if len(matched_definitions) > 1:
            return MapSelectionResult(
                raw_map_name=evidence.raw_map_name,
                canonical_name=canonical,
                display_name=display_name,
                status=MapSelectionStatus.UNSUPPORTED,
                selected_definition=None,
                evidence=tuple(
                    f"{label}:{value}->{matches[0].map_revision.revision_id}"
                    for label, value, matches in selector_matches
                    if len(matches) == 1
                ),
                warnings=("map_revision_evidence_conflict",),
            )
        if len(matched_definitions) == 1:
            selected = next(matches[0] for _, _, matches in selector_matches if len(matches) == 1)
            unmatched = tuple(
                f"unmatched_{label}:{value}"
                for label, value, matches in selector_matches
                if not matches
            )
            selector_warnings: tuple[str, ...] = ()
            if unmatched:
                selector_warnings = ("map_revision_evidence_partially_unmatched",)
            if not selected.transform_available:
                selector_warnings = (
                    *selector_warnings,
                    "selected_revision_calibration_unavailable",
                )
            return MapSelectionResult(
                raw_map_name=evidence.raw_map_name,
                canonical_name=canonical,
                display_name=display_name,
                status=MapSelectionStatus.PROVEN,
                selected_definition=selected,
                evidence=(
                    *(
                        f"{label}:{value}"
                        for label, value, matches in selector_matches
                        if len(matches) == 1
                    ),
                    *unmatched,
                ),
                warnings=selector_warnings,
            )
        candidate = self.preferred_definition(canonical)
        if candidate is None:
            return MapSelectionResult(
                raw_map_name=evidence.raw_map_name,
                canonical_name=canonical,
                display_name=display_name,
                status=MapSelectionStatus.UNSUPPORTED,
                selected_definition=None,
                warnings=("map_revision_unproven", "no_single_configured_revision_candidate"),
            )
        warnings = ["map_revision_unproven"]
        if candidate.map_revision.incompatible_layout_possible:
            warnings.append("map_layout_may_be_incompatible")
        return MapSelectionResult(
            raw_map_name=evidence.raw_map_name,
            canonical_name=canonical,
            display_name=display_name,
            status=MapSelectionStatus.UNPROVEN,
            selected_definition=candidate,
            evidence=tuple(
                f"unmatched_{label}:{value}" for label, value, _ in selectors if value is not None
            ),
            warnings=tuple(warnings),
        )

    def pin(self, selection: MapSelectionResult) -> MapSemanticsPin:
        definition = selection.selected_definition
        return MapSemanticsPin(
            raw_map_name=selection.raw_map_name,
            canonical_name=selection.canonical_name,
            selected_map_revision=(
                definition.map_revision.revision_id if definition is not None else None
            ),
            selection_status=selection.status,
            selection_evidence=selection.evidence,
            map_definition_fingerprint=(
                definition.definition_fingerprint if definition is not None else None
            ),
            overview_checksum=(
                definition.overview_asset.sha256
                if definition is not None and definition.overview_asset is not None
                else None
            ),
            lower_overview_checksum=(
                definition.lower_overview_asset.sha256
                if definition is not None and definition.lower_overview_asset is not None
                else None
            ),
            transform_rule_version=(
                definition.coordinate_transform.rule_version
                if definition is not None and definition.coordinate_transform is not None
                else None
            ),
            calibration_status=(
                definition.calibration_status
                if definition is not None
                else CalibrationStatus.UNSUPPORTED
            ),
            warnings=selection.warnings,
        )

    def resolve_pin(self, pin: MapSemanticsPin) -> MapDefinition | None:
        if pin.map_definition_fingerprint is None:
            return None
        definition = self.definition_by_fingerprint(pin.map_definition_fingerprint)
        if definition is None:
            return None
        if (
            definition.canonical_name != pin.canonical_name
            or definition.map_revision.revision_id != pin.selected_map_revision
            or (
                definition.overview_asset is not None
                and definition.overview_asset.sha256 != pin.overview_checksum
            )
        ):
            return None
        return definition


def _alias_key(value: str) -> str:
    return value.strip().casefold()


def _revision_sort_key(definition: MapDefinition) -> tuple[int, str]:
    order = {
        MapRevisionKind.CURRENT: 0,
        MapRevisionKind.HISTORICAL: 1,
        MapRevisionKind.LEGACY: 2,
    }
    return order[definition.map_revision.kind], definition.map_revision.revision_id


DEFAULT_MAP_REGISTRY = MapRegistry(ALL_DEFINITIONS)
