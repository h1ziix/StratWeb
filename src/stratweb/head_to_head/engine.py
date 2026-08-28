"""Pure deterministic matching of opponent habits against own-team habits."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from stratweb.application.normalization_utils import canonical_json
from stratweb.domain.enums import Side
from stratweb.head_to_head.models import (
    HEAD_TO_HEAD_RULE_VERSION,
    HEAD_TO_HEAD_SCHEMA_VERSION,
    HeadToHeadComparison,
    HeadToHeadInput,
    HeadToHeadReliability,
    HeadToHeadRiskLevel,
    HeadToHeadRule,
    HeadToHeadRun,
    HeadToHeadSummary,
)
from stratweb.tactical_v2.models import TacticalInsight, TacticalInsightType


@dataclass(frozen=True, slots=True)
class _Draft:
    rule: HeadToHeadRule
    map_name: str
    opponent_side: Side
    our_side: Side
    score: float
    title: str
    observation: str
    interpretation: str
    recommendation: str
    opponent: TacticalInsight
    ours: TacticalInsight
    limitations: tuple[str, ...]


class HeadToHeadEngine:
    """Pair exact compatible evidence; never infer calls, intent or causality."""

    def compute(self, data: HeadToHeadInput) -> HeadToHeadRun:
        drafts = tuple(
            sorted(
                (*self._opening_vs_trade(data), *self._opening_vs_spacing(data)),
                key=lambda item: (
                    -item.score,
                    item.map_name,
                    item.opponent_side.value,
                    item.rule.value,
                ),
            )
        )
        common_maps = tuple(
            sorted(
                {item.map_name for item in data.opponent_insights}
                & {item.map_name for item in data.our_insights}
            )
        )
        warnings = {
            "head_to_head_is_historical_alignment_not_proven_causality",
            "profiles_may_cover_different_dates_and_opponents",
            "economy_and_zone_specific_matchups_require_matching_typed_evidence",
        }
        if not common_maps:
            warnings.add("no_common_maps_in_compatible_tactical_runs")
        if not drafts:
            warnings.add("no_compatible_opposite_side_insight_pairs")
        fingerprint_payload = {
            "schema": HEAD_TO_HEAD_SCHEMA_VERSION,
            "rules": HEAD_TO_HEAD_RULE_VERSION,
            "opponent_profile_id": str(data.opponent_profile_id),
            "our_profile_id": str(data.our_profile_id),
            "opponent_tactical_fingerprint": data.opponent_summary.tactical_fingerprint,
            "our_tactical_fingerprint": data.our_summary.tactical_fingerprint,
            "drafts": [
                {
                    "rule": item.rule.value,
                    "map": item.map_name,
                    "opponent_side": item.opponent_side.value,
                    "our_side": item.our_side.value,
                    "score": item.score,
                    "opponent_insight_id": str(item.opponent.insight_id),
                    "our_insight_id": str(item.ours.insight_id),
                }
                for item in drafts
            ],
            "warnings": sorted(warnings),
        }
        fingerprint = hashlib.sha256(
            canonical_json(fingerprint_payload).encode("utf-8")
        ).hexdigest()
        run_id = uuid5(NAMESPACE_URL, f"stratweb:head-to-head:{fingerprint}")
        comparisons = tuple(
            HeadToHeadComparison(
                comparison_id=uuid5(
                    run_id,
                    f"comparison:{item.rule.value}:{item.map_name}:"
                    f"{item.opponent_side.value}",
                ),
                head_to_head_run_id=run_id,
                rule=item.rule,
                map_name=item.map_name,
                opponent_side=item.opponent_side,
                our_side=item.our_side,
                risk_score=item.score,
                risk_level=_risk_level(item.score),
                reliability=_reliability(
                    min(item.opponent.match_count, item.ours.match_count)
                ),
                sample_match_count=min(item.opponent.match_count, item.ours.match_count),
                title=item.title,
                observation=item.observation,
                tactical_interpretation=item.interpretation,
                recommendation=item.recommendation,
                opponent_insight=item.opponent,
                our_insight=item.ours,
                limitations=item.limitations,
            )
            for item in drafts
        )
        levels = Counter(item.risk_level for item in comparisons)
        return HeadToHeadRun(
            head_to_head_run_id=run_id,
            head_to_head_fingerprint=fingerprint,
            opponent_profile_id=data.opponent_profile_id,
            our_profile_id=data.our_profile_id,
            opponent_tactical_run_id=data.opponent_summary.tactical_run_id,
            opponent_tactical_fingerprint=data.opponent_summary.tactical_fingerprint,
            our_tactical_run_id=data.our_summary.tactical_run_id,
            our_tactical_fingerprint=data.our_summary.tactical_fingerprint,
            comparisons=comparisons,
            summary=HeadToHeadSummary(
                comparison_count=len(comparisons),
                high_risk_count=levels[HeadToHeadRiskLevel.HIGH],
                medium_risk_count=levels[HeadToHeadRiskLevel.MEDIUM],
                low_risk_count=levels[HeadToHeadRiskLevel.LOW],
                common_maps=common_maps,
            ),
            warnings=tuple(sorted(warnings)),
        )

    @staticmethod
    def _opening_vs_trade(data: HeadToHeadInput) -> tuple[_Draft, ...]:
        opponent = _index(
            data.opponent_insights,
            TacticalInsightType.ENTRY_STRUCTURE,
            "opening_duel_success",
        )
        ours = _index(
            data.our_insights,
            TacticalInsightType.TRADE_STRUCTURE,
            "opening_death_traded",
        )
        result = []
        for (map_name, opponent_side), opponent_insight in opponent.items():
            if opponent_side not in {Side.T, Side.CT}:
                continue
            our_side = _opposite(opponent_side)
            own_insight = ours.get((map_name, our_side))
            if own_insight is None:
                continue
            score = opponent_insight.frequency * (1.0 - own_insight.frequency)
            level = _risk_level(score)
            result.append(
                _Draft(
                    rule=HeadToHeadRule.OPENING_VS_TRADE,
                    map_name=map_name,
                    opponent_side=opponent_side,
                    our_side=our_side,
                    score=score,
                    title="Первые контакты соперника против наших разменов",
                    observation=(
                        f"Соперник выигрывал первый доказанный контакт "
                        f"{opponent_insight.numerator} из {opponent_insight.denominator} раз. "
                        f"Мы разменивали первую смерть {own_insight.numerator} из "
                        f"{own_insight.denominator} раз."
                    ),
                    interpretation=_trade_interpretation(level),
                    recommendation=_trade_recommendation(level),
                    opponent=opponent_insight,
                    ours=own_insight,
                    limitations=_limitations(opponent_insight, own_insight),
                )
            )
        return tuple(result)

    @staticmethod
    def _opening_vs_spacing(data: HeadToHeadInput) -> tuple[_Draft, ...]:
        opponent = _index(
            data.opponent_insights,
            TacticalInsightType.ENTRY_STRUCTURE,
            "opening_duel_success",
        )
        spacing = _earliest_spacing(data.our_insights)
        result = []
        for (map_name, opponent_side), opponent_insight in opponent.items():
            if opponent_side not in {Side.T, Side.CT}:
                continue
            our_side = _opposite(opponent_side)
            own_insight = spacing.get((map_name, our_side))
            if own_insight is None:
                continue
            score = opponent_insight.frequency * own_insight.frequency
            level = _risk_level(score)
            result.append(
                _Draft(
                    rule=HeadToHeadRule.OPENING_VS_SPACING,
                    map_name=map_name,
                    opponent_side=opponent_side,
                    our_side=our_side,
                    score=score,
                    title="Их первые дуэли против нашей ранней расстановки",
                    observation=(
                        f"Соперник выигрывал первый доказанный контакт "
                        f"{opponent_insight.numerator} из {opponent_insight.denominator} раз. "
                        f"У нас ранняя изоляция игрока фиксировалась "
                        f"{own_insight.numerator} из {own_insight.denominator} раз."
                    ),
                    interpretation=_spacing_interpretation(level),
                    recommendation=_spacing_recommendation(level),
                    opponent=opponent_insight,
                    ours=own_insight,
                    limitations=_limitations(opponent_insight, own_insight),
                )
            )
        return tuple(result)


def _index(
    insights: tuple[TacticalInsight, ...],
    insight_type: TacticalInsightType,
    key: str,
) -> dict[tuple[str, Side], TacticalInsight]:
    return {
        (item.map_name, item.side): item
        for item in insights
        if item.insight_type is insight_type
        and item.key == key
        and item.side in {Side.T, Side.CT}
    }


def _earliest_spacing(
    insights: tuple[TacticalInsight, ...],
) -> dict[tuple[str, Side], TacticalInsight]:
    grouped: dict[tuple[str, Side], list[TacticalInsight]] = {}
    for item in insights:
        if item.insight_type is not TacticalInsightType.SPACING_PROFILE:
            continue
        if item.side not in {Side.T, Side.CT}:
            continue
        grouped.setdefault((item.map_name, item.side), []).append(item)
    result = {}
    for scope, values in grouped.items():
        result[scope] = min(values, key=lambda item: (_checkpoint(item.key), item.key))
    return result


def _checkpoint(key: str) -> int:
    try:
        return int(key.partition(":")[2])
    except ValueError:
        return 2**31 - 1


def _opposite(side: Side) -> Side:
    if side is Side.T:
        return Side.CT
    if side is Side.CT:
        return Side.T
    raise ValueError("cannot pair an unknown side")


def _risk_level(score: float) -> HeadToHeadRiskLevel:
    if score >= 0.45:
        return HeadToHeadRiskLevel.HIGH
    if score >= 0.25:
        return HeadToHeadRiskLevel.MEDIUM
    return HeadToHeadRiskLevel.LOW


def _reliability(matches: int) -> HeadToHeadReliability:
    if matches >= 15:
        return HeadToHeadReliability.HIGH
    if matches >= 8:
        return HeadToHeadReliability.STABLE_TREND
    if matches >= 3:
        return HeadToHeadReliability.TACTICAL_TREND
    return HeadToHeadReliability.GAME_FACTS


def _limitations(
    opponent: TacticalInsight, ours: TacticalInsight
) -> tuple[str, ...]:
    values = {
        "comparison_combines_separate_historical_samples_not_the_same_rounds",
        "alignment_does_not_prove_the_opponent_will_repeat_or_cause_our_result",
        "only_exact_map_and_opposite_side_evidence_is_paired",
        *opponent.limitations,
        *ours.limitations,
    }
    if min(opponent.match_count, ours.match_count) < 3:
        values.add("one_or_both_samples_contain_only_one_or_two_matches")
    return tuple(sorted(values))


def _trade_interpretation(level: HeadToHeadRiskLevel) -> str:
    if level is HeadToHeadRiskLevel.HIGH:
        return "Исторически их сильный первый контакт совпадает с нашей слабой страховкой размена."
    if level is HeadToHeadRiskLevel.MEDIUM:
        return (
            "Есть заметное пересечение их силы в первом контакте "
            "и неполной надёжности наших разменов."
        )
    return "По доступной выборке наша структура размена в основном компенсирует их первые контакты."


def _trade_recommendation(level: HeadToHeadRiskLevel) -> str:
    if level is HeadToHeadRiskLevel.HIGH:
        return "Первые контакты играть парами и заранее назначить второго игрока на быстрый размен."
    if level is HeadToHeadRiskLevel.MEDIUM:
        return "На ключевых первых контактах держать дистанцию для гарантированного размена."
    return "Сохранить текущую структуру размена и отдельно проверить её на свежих раундах."


def _spacing_interpretation(level: HeadToHeadRiskLevel) -> str:
    if level is HeadToHeadRiskLevel.HIGH:
        return (
            "Их успешные первые дуэли совпадают с нашей привычкой "
            "оставлять игрока без близкой поддержки."
        )
    if level is HeadToHeadRiskLevel.MEDIUM:
        return (
            "Ранняя дистанция между нашими игроками может дать сопернику "
            "удобный одиночный контакт."
        )
    return "Доказательств системной уязвимости ранней расстановки перед их первыми дуэлями мало."


def _spacing_recommendation(level: HeadToHeadRiskLevel) -> str:
    if level is HeadToHeadRiskLevel.HIGH:
        return (
            "Не оставлять первого игрока одного: дать флешку, "
            "второй контакт или немедленный размен."
        )
    if level is HeadToHeadRiskLevel.MEDIUM:
        return "Сократить раннюю дистанцию в зоне предполагаемого первого контакта."
    return (
        "Не ломать дефолт только по этому сигналу; "
        "использовать его как пункт для проверки на сервере."
    )


__all__ = ["HeadToHeadEngine"]
