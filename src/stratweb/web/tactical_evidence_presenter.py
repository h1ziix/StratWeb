"""Read-only Tactical V2 evidence navigation projection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlencode
from uuid import UUID

from stratweb.tactical_v2.models import (
    TacticalEvidenceReference,
    TacticalInsight,
    TacticalSourcePin,
    TacticalV2RunSummary,
)
from stratweb.web.tactical_v2_presenter import (
    TacticalInsightCard,
    build_tactical_insight_card,
)

TACTICAL_EVIDENCE_PAGE_SIZE = 24


@dataclass(frozen=True, slots=True)
class TacticalEvidenceEventLink:
    event_id: UUID
    href: str


@dataclass(frozen=True, slots=True)
class TacticalEvidenceItem:
    source: TacticalEvidenceReference
    match_number: int | None
    map_name: str | None
    lineage_available: bool
    match_href: str
    temporal_round_href: str | None
    temporal_tick_href: str | None
    snapshot_href: str | None
    spatial_href: str | None
    feature_href: str | None
    event_links: tuple[TacticalEvidenceEventLink, ...]


@dataclass(frozen=True, slots=True)
class TacticalEvidencePage:
    insight: TacticalInsight
    insight_card: TacticalInsightCard
    items: tuple[TacticalEvidenceItem, ...]
    total_count: int
    page: int
    page_count: int
    previous_href: str | None
    next_href: str | None
    back_href: str


def build_tactical_evidence_page(
    summary: TacticalV2RunSummary,
    insight: TacticalInsight,
    evidence: tuple[TacticalEvidenceReference, ...],
    *,
    page: int,
) -> TacticalEvidencePage:
    if insight.tactical_run_id != summary.tactical_run_id:
        raise ValueError("Tactical insight and summary run IDs do not match")
    pins = {item.match_id: item for item in summary.source_pins}
    match_numbers = {item.match_id: index for index, item in enumerate(summary.source_pins, 1)}
    ordered = tuple(
        sorted(
            evidence,
            key=lambda item: (
                match_numbers.get(item.match_id, len(match_numbers) + 1),
                item.round_number,
                item.tick_start if item.tick_start is not None else -1,
                item.tick_end if item.tick_end is not None else -1,
            ),
        )
    )
    page_count = max(1, math.ceil(len(ordered) / TACTICAL_EVIDENCE_PAGE_SIZE))
    selected_page = min(page, page_count)
    start = (selected_page - 1) * TACTICAL_EVIDENCE_PAGE_SIZE
    visible = ordered[start : start + TACTICAL_EVIDENCE_PAGE_SIZE]
    base_path = (
        f"/ui/opponents/{summary.profile_id}/tactical-v2/insights/{insight.insight_id}/evidence"
    )
    return TacticalEvidencePage(
        insight=insight,
        insight_card=build_tactical_insight_card(insight),
        items=tuple(
            _evidence_item(item, pins.get(item.match_id), match_numbers.get(item.match_id))
            for item in visible
        ),
        total_count=len(ordered),
        page=selected_page,
        page_count=page_count,
        previous_href=(
            _page_href(base_path, summary.tactical_run_id, selected_page - 1)
            if selected_page > 1
            else None
        ),
        next_href=(
            _page_href(base_path, summary.tactical_run_id, selected_page + 1)
            if selected_page < page_count
            else None
        ),
        back_href=(
            f"/ui/opponents/{summary.profile_id}/tactical-v2?"
            + urlencode({"run_id": str(summary.tactical_run_id)})
        ),
    )


def _evidence_item(
    evidence: TacticalEvidenceReference,
    pin: TacticalSourcePin | None,
    match_number: int | None,
) -> TacticalEvidenceItem:
    match_href = f"/ui/matches/{evidence.match_id}#rounds"
    if pin is None:
        return TacticalEvidenceItem(
            source=evidence,
            match_number=match_number,
            map_name=None,
            lineage_available=False,
            match_href=match_href,
            temporal_round_href=None,
            temporal_tick_href=None,
            snapshot_href=None,
            spatial_href=None,
            feature_href=None,
            event_links=(),
        )

    temporal_path = f"/ui/temporal/{evidence.match_id}/rounds/{evidence.round_number}"
    temporal_query = urlencode({"run_id": str(pin.temporal_run_id)})
    temporal_round_href = f"{temporal_path}?{temporal_query}"
    temporal_tick_href = (
        f"{temporal_round_href}#tick-{evidence.tick_start}"
        if evidence.tick_start is not None
        else None
    )
    event_links = tuple(
        TacticalEvidenceEventLink(
            event_id=event_id,
            href=(
                f"{temporal_path}/events/{event_id}?"
                + urlencode({"run_id": str(pin.temporal_run_id)})
            ),
        )
        for event_id in evidence.event_ids
    )
    single_event_tick = (
        evidence.tick_start
        if evidence.event_ids
        and evidence.tick_start is not None
        and evidence.tick_start == evidence.tick_end
        else None
    )
    snapshot_href = (
        f"{temporal_path}/snapshots/{single_event_tick}?{temporal_query}"
        if single_event_tick is not None
        else None
    )
    spatial_href = None
    if evidence.snapshot_ids and evidence.tick_start is not None:
        spatial_href = (
            f"/ui/spatial/{evidence.match_id}/rounds/{evidence.round_number}?"
            + urlencode(
                {
                    "tick": evidence.tick_start,
                    "run_id": str(pin.spatial_run_id),
                    "mode": "exact",
                }
            )
        )
    feature_href = None
    if evidence.feature_ids and pin.feature_run_id is not None:
        feature_href = f"/ui/matches/{evidence.match_id}/features?" + urlencode(
            {
                "run_id": str(pin.feature_run_id),
                "round": evidence.round_number,
            }
        )
    return TacticalEvidenceItem(
        source=evidence,
        match_number=match_number,
        map_name=pin.map_name,
        lineage_available=True,
        match_href=match_href,
        temporal_round_href=temporal_round_href,
        temporal_tick_href=temporal_tick_href,
        snapshot_href=snapshot_href,
        spatial_href=spatial_href,
        feature_href=feature_href,
        event_links=event_links,
    )


def _page_href(base_path: str, run_id: UUID, page: int) -> str:
    return f"{base_path}?{urlencode({'run_id': str(run_id), 'page': page})}"


__all__ = [
    "TACTICAL_EVIDENCE_PAGE_SIZE",
    "TacticalEvidenceEventLink",
    "TacticalEvidenceItem",
    "TacticalEvidencePage",
    "build_tactical_evidence_page",
]
