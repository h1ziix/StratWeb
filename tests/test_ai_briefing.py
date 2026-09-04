from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from stratweb.adapters.ollama import OllamaBriefingClient
from stratweb.adapters.persistence import DuckDBAiBriefingRepository
from stratweb.ai_briefing.models import (
    AiBriefingArtifact,
    AiBriefingContent,
    AiBriefingPoint,
    BriefingSourceBundle,
    BriefingSourceItem,
)
from stratweb.web.scouting_report import scouting_report_router
from stratweb.web.view_models.ai_briefing import build_ai_briefing_page

SOURCE_ID = UUID("11111111-1111-1111-1111-111111111111")
FINDING_ID = UUID("22222222-2222-2222-2222-222222222222")
PROFILE_ID = UUID("33333333-3333-3333-3333-333333333333")
RUN_ID = UUID("44444444-4444-4444-4444-444444444444")
BRIEFING_ID = UUID("55555555-5555-5555-5555-555555555555")


def _source() -> BriefingSourceBundle:
    return BriefingSourceBundle(
        source_fingerprint="a" * 64,
        profile_id=PROFILE_ID,
        strategy_run_id=RUN_ID,
        strategy_fingerprint="b" * 64,
        display_name="Соперник",
        sources=(
            BriefingSourceItem(
                source_id=SOURCE_ID,
                finding_id=FINDING_ID,
                map_name="de_mirage",
                side="T",
                title="Контроль центра",
                observation="Команда часто начинает раунд с контроля центра.",
                tactical_interpretation="Соперник оставляет время на занятие центра.",
                recommended_response="Встретьте контакт парой под подготовленную флешку.",
                avoid="Не отдавайте одиночную раннюю дуэль без размена.",
                numerator=3,
                denominator=5,
                frequency=0.6,
                sample_size=5,
                evidence_match_count=3,
                evidence_count=5,
                limitations=("Малая выборка.",),
            ),
        ),
    )


def _content() -> AiBriefingContent:
    return AiBriefingContent(
        expect=(AiBriefingPoint(text="Ждите ранний контроль центра.", source_id=SOURCE_ID),),
        play=(AiBriefingPoint(text="Встречайте контакт вдвоём.", source_id=SOURCE_ID),),
        avoid=(AiBriefingPoint(text="Не выходите на одиночную дуэль.", source_id=SOURCE_ID),),
    )


def _artifact() -> AiBriefingArtifact:
    return AiBriefingArtifact(
        briefing_id=BRIEFING_ID,
        briefing_fingerprint="c" * 64,
        profile_id=PROFILE_ID,
        strategy_run_id=RUN_ID,
        model_name="qwen3:8b",
        model_digest="d" * 64,
        source=_source(),
        content=_content(),
        created_at=datetime(2026, 9, 4, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "unsafe_text",
    (
        "Они всегда выходят через центр.",
        "Так вы гарантированно выиграете раунд.",
    ),
)
def test_ai_content_rejects_absolute_claims(unsafe_text: str) -> None:
    with pytest.raises(ValidationError):
        AiBriefingContent(
            play=(AiBriefingPoint(text=unsafe_text, source_id=SOURCE_ID),),
        )


def test_artifact_rejects_number_absent_from_matching_source_field() -> None:
    payload = _artifact().model_dump()
    payload["content"] = AiBriefingContent(
        play=(
            AiBriefingPoint(
                text="Используйте этот ответ в 70 процентах раундов.",
                source_id=SOURCE_ID,
            ),
        )
    ).model_dump()
    with pytest.raises(ValidationError, match="introduced a number"):
        AiBriefingArtifact.model_validate(payload)


def test_artifact_rejects_reference_outside_pinned_source() -> None:
    payload = _artifact().model_dump()
    payload["content"] = AiBriefingContent(
        play=(
            AiBriefingPoint(
                text="Встречайте контакт вдвоём.",
                source_id=UUID("99999999-9999-9999-9999-999999999999"),
            ),
        )
    ).model_dump()
    with pytest.raises(ValidationError):
        AiBriefingArtifact.model_validate(payload)


def test_ai_briefing_repository_round_trip_and_page_links(tmp_path) -> None:
    repository = DuckDBAiBriefingRepository(tmp_path / "briefing.duckdb")
    artifact = _artifact()

    repository.save(artifact)
    repository.save(artifact)

    loaded = repository.get_compatible(
        PROFILE_ID,
        RUN_ID,
        source_fingerprint=artifact.source.source_fingerprint,
        model_name=artifact.model_name,
        model_digest=artifact.model_digest,
    )
    assert loaded == artifact
    assert repository.get_latest(PROFILE_ID, RUN_ID) == artifact
    page = build_ai_briefing_page(artifact)
    assert page.play[0].text == "Встречайте контакт вдвоём."
    assert str(FINDING_ID) in page.play[0].evidence_href
    assert str(RUN_ID) in page.play[0].evidence_href


def test_ollama_adapter_rejects_non_loopback_urls() -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaBriefingClient(base_url="https://example.com", model="qwen3:8b")


def test_invalid_optional_ollama_configuration_does_not_break_router(tmp_path) -> None:
    router = scouting_report_router(
        tmp_path / "optional-ai.duckdb",
        ollama_base_url="https://example.com",
    )
    assert router.routes


def test_ollama_adapter_uses_documented_structured_non_streaming_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = OllamaBriefingClient(model="qwen3:8b")
    seen_payload: dict[str, object] = {}

    def fake_request(
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if path == "/api/tags":
            return {
                "models": [
                    {
                        "name": "qwen3:8b",
                        "model": "qwen3:8b",
                        "digest": "d" * 64,
                    }
                ]
            }
        assert method == "POST"
        assert path == "/api/chat"
        assert payload is not None
        seen_payload.update(payload)
        return {"message": {"content": _content().model_dump_json()}}

    monkeypatch.setattr(client, "_request_json", fake_request)

    assert client.resolve_model().digest == "d" * 64
    assert client.generate(_source()) == _content()
    assert seen_payload["stream"] is False
    assert seen_payload["think"] is False
    assert seen_payload["format"] == AiBriefingContent.model_json_schema()
    prompt = json.dumps(seen_payload["messages"], ensure_ascii=False)
    assert '"numerator"' not in prompt
    assert '"denominator"' not in prompt
