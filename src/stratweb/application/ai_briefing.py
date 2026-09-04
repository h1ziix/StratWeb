"""Safe orchestration for optional Ollama rephrasing of verified report facts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, ValidationError

from stratweb.ai_briefing.models import (
    AI_BRIEFING_PROMPT_VERSION,
    AI_BRIEFING_RULE_VERSION,
    AI_BRIEFING_SCHEMA_VERSION,
    AiBriefingArtifact,
    AiBriefingContent,
    BriefingSourceBundle,
    BriefingSourceItem,
)
from stratweb.application.normalization_utils import canonical_json
from stratweb.application.opponent_models import OpponentWorkspace
from stratweb.application.scouting_reports import ScoutingReportSource
from stratweb.counter_strategy.validation_models import StrategyAcceptanceStatus
from stratweb.patterns.models import PatternType
from stratweb.reporting.coach_presentation import coach_pattern_text, is_useful_coach_signal

_PATTERN_PRIORITY = {
    PatternType.SITE_PREFERENCE: 0,
    PatternType.FIRST_CONTACT_ZONE: 1,
    PatternType.FIRST_UTILITY: 2,
    PatternType.BOMB_ROUTING: 3,
    PatternType.RECURRING_OPENING_DEATH: 4,
    PatternType.LOST_MAN_ADVANTAGE: 5,
    PatternType.UNTRADED_DEATH: 6,
    PatternType.EARLY_ROTATION: 7,
    PatternType.RECOVERY_AFTER_OPENING_DEATH: 8,
    PatternType.OPENING_KILL_CONVERSION: 9,
}


class AiBriefingError(RuntimeError):
    """Base error safe to translate into a product-facing availability state."""


class AiBriefingUnavailableError(AiBriefingError):
    """The deterministic source cannot safely support an AI briefing."""


class AiBriefingProviderError(AiBriefingError):
    """The configured local provider or model is unavailable."""


class OllamaModelInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    digest: str


class AiBriefingProvider(Protocol):
    def resolve_model(self) -> OllamaModelInfo: ...

    def generate(self, source: BriefingSourceBundle) -> AiBriefingContent: ...


class AiBriefingRepository(Protocol):
    def get_compatible(
        self,
        profile_id: UUID,
        strategy_run_id: UUID,
        *,
        source_fingerprint: str,
        model_name: str,
        model_digest: str,
    ) -> AiBriefingArtifact | None: ...

    def save(self, artifact: AiBriefingArtifact) -> None: ...


class AiBriefingSourceBuilder:
    """Select a small deterministic set of already-published recommendations."""

    def build(
        self,
        source: ScoutingReportSource,
        workspace: OpponentWorkspace,
    ) -> BriefingSourceBundle:
        if source.validation.status is StrategyAcceptanceStatus.FAILED:
            raise AiBriefingUnavailableError(
                "Проверка целостности плана не пройдена; AI-пересказ отключён."
            )
        useful = tuple(
            item
            for item in source.recommendations
            if is_useful_coach_signal(item.pattern_type, item.pattern_value)
        )
        ranked = sorted(
            useful,
            key=lambda item: (
                _PATTERN_PRIORITY.get(item.pattern_type, 99),
                -item.denominator_match_count,
                -item.sample_size,
                -item.frequency,
                item.scope.map_name,
                item.scope.side.value,
                str(item.recommendation_id),
            ),
        )
        selected = []
        seen_scopes: set[tuple[str, str, PatternType]] = set()
        for item in ranked:
            key = (item.scope.map_name, item.scope.side.value, item.pattern_type)
            if key in seen_scopes:
                continue
            seen_scopes.add(key)
            selected.append(item)
            if len(selected) == 6:
                break
        if not selected:
            raise AiBriefingUnavailableError(
                "В плане пока нет проверенных рекомендаций для безопасного пересказа."
            )
        items = tuple(
            BriefingSourceItem(
                source_id=item.recommendation_id,
                finding_id=item.source_finding_id,
                map_name=item.scope.map_name,
                side=item.scope.side.value,
                title=coach_pattern_text(item.pattern_type, item.pattern_value).title,
                observation=_required_text(item.observation.text),
                tactical_interpretation=_required_text(item.tactical_interpretation.text),
                recommended_response=_required_text(item.recommendation.text),
                avoid=_required_text(item.avoid.text),
                numerator=item.numerator,
                denominator=item.denominator,
                frequency=item.frequency,
                sample_size=item.sample_size,
                evidence_match_count=item.denominator_match_count,
                evidence_count=len(item.evidence_references),
                limitations=item.limitations,
            )
            for item in selected
        )
        source_payload = {
            "profile_id": str(source.strategy.profile_id),
            "strategy_run_id": str(source.strategy.strategy_run_id),
            "strategy_fingerprint": source.strategy.strategy_fingerprint,
            "display_name": workspace.profile.display_name,
            "locale": "ru",
            "sources": [item.model_dump(mode="json") for item in items],
            "prompt_version": AI_BRIEFING_PROMPT_VERSION,
        }
        fingerprint = hashlib.sha256(canonical_json(source_payload).encode("utf-8")).hexdigest()
        return BriefingSourceBundle(
            source_fingerprint=fingerprint,
            profile_id=source.strategy.profile_id,
            strategy_run_id=source.strategy.strategy_run_id,
            strategy_fingerprint=source.strategy.strategy_fingerprint,
            display_name=workspace.profile.display_name,
            sources=items,
        )


class GenerateAiBriefingService:
    """Generate once per pinned source/model and persist only validated output."""

    def __init__(
        self,
        repository: AiBriefingRepository,
        provider: AiBriefingProvider,
        *,
        source_builder: AiBriefingSourceBuilder | None = None,
    ) -> None:
        self._repository = repository
        self._provider = provider
        self._source_builder = source_builder or AiBriefingSourceBuilder()

    def generate(
        self,
        source: ScoutingReportSource,
        workspace: OpponentWorkspace,
    ) -> AiBriefingArtifact:
        bundle = self._source_builder.build(source, workspace)
        model = self._provider.resolve_model()
        existing = self._repository.get_compatible(
            bundle.profile_id,
            bundle.strategy_run_id,
            source_fingerprint=bundle.source_fingerprint,
            model_name=model.name,
            model_digest=model.digest,
        )
        if existing is not None:
            return existing
        content = self._provider.generate(bundle)
        artifact_payload = {
            "schema_version": AI_BRIEFING_SCHEMA_VERSION,
            "rule_version": AI_BRIEFING_RULE_VERSION,
            "prompt_version": AI_BRIEFING_PROMPT_VERSION,
            "provider": "ollama",
            "model_name": model.name,
            "model_digest": model.digest,
            "temperature": 0,
            "source_fingerprint": bundle.source_fingerprint,
            "content": content.model_dump(mode="json"),
        }
        fingerprint = hashlib.sha256(canonical_json(artifact_payload).encode("utf-8")).hexdigest()
        try:
            artifact = AiBriefingArtifact(
                briefing_id=uuid5(NAMESPACE_URL, f"stratweb:ai-briefing:{fingerprint}"),
                briefing_fingerprint=fingerprint,
                profile_id=bundle.profile_id,
                strategy_run_id=bundle.strategy_run_id,
                model_name=model.name,
                model_digest=model.digest,
                source=bundle,
                content=content,
                created_at=datetime.now(UTC),
            )
        except ValidationError as exc:
            raise AiBriefingProviderError(
                "AI-ответ сослался на данные вне проверенного источника."
            ) from exc
        self._repository.save(artifact)
        return artifact


def _required_text(value: str | None) -> str:
    if value is None or not value.strip():
        raise AiBriefingUnavailableError("Проверенный исходный текст недоступен.")
    return value.strip()


__all__ = [name for name in globals() if not name.startswith("_")]
