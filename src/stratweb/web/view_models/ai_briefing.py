"""Small product projection of a validated AI briefing artifact."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from stratweb.ai_briefing.models import AiBriefingArtifact, AiBriefingPoint
from stratweb.web.view_models.product import ViewModel


class AiBriefingPointView(ViewModel):
    text: str
    map_name: str
    side: str
    evidence_href: str


class AiBriefingPageView(ViewModel):
    briefing_id: UUID
    model_name: str
    created_at: datetime
    expect: tuple[AiBriefingPointView, ...] = Field(max_length=3)
    play: tuple[AiBriefingPointView, ...] = Field(max_length=3)
    avoid: tuple[AiBriefingPointView, ...] = Field(max_length=3)


def build_ai_briefing_page(artifact: AiBriefingArtifact) -> AiBriefingPageView:
    sources = {item.source_id: item for item in artifact.source.sources}

    def project(point: AiBriefingPoint) -> AiBriefingPointView:
        source = sources[point.source_id]
        return AiBriefingPointView(
            text=point.text,
            map_name=source.map_name,
            side=source.side,
            evidence_href=(
                f"/ui/opponents/{artifact.profile_id}/report/findings/{source.finding_id}"
                f"?run_id={artifact.strategy_run_id}"
            ),
        )

    return AiBriefingPageView(
        briefing_id=artifact.briefing_id,
        model_name=artifact.model_name,
        created_at=artifact.created_at,
        expect=tuple(project(item) for item in artifact.content.expect),
        play=tuple(project(item) for item in artifact.content.play),
        avoid=tuple(project(item) for item in artifact.content.avoid),
    )


__all__ = ["AiBriefingPageView", "AiBriefingPointView", "build_ai_briefing_page"]
