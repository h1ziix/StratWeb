# Cross-Match Pattern Model — Stage 8.5

## Назначение и границы

Stage 8.5 находит повторяющиеся наблюдаемые факты в матчах одного подтверждённого
Opponent Workspace. Источник — только сохранённые Stage 8.4 `RoundFeature`; parser,
LLM, UI и свободный текст в расчёте не участвуют.

Паттерн — статистический агрегат, а не `AnalysisFinding`. Он не содержит tactical
interpretation, recommendation или утверждение о причине. Эти сущности нельзя
достраивать из высокой частоты автоматически.

## Строгий scope

Каждая population разделяется по:

- `profile_id` подтверждённого пользователем соперника;
- `map_name`;
- физической стороне соперника в конкретном раунде: `T` или `CT`;
- `buy_type`: `pistol|eco|force|semi|full|unknown`, либо отдельный `null` scope,
  если Economy context недоступен;
- `feature_rule_version`;
- завершённому non-warmup раунду.

Разные карты, стороны, закупы, версии или opponent profiles не попадают в один
denominator. Смена сторон обрабатывается через canonical physical-team membership
каждого раунда.

## Статистический контракт

Каждый `CrossMatchPattern` хранит:

- `numerator` — число включённых раундов с конкретным значением;
- `denominator`/`sample_size` — число доказуемых opportunities этого типа в точном
  scope;
- `frequency = numerator / denominator`;
- `numerator_match_count` и `denominator_match_count`;
- `minimum_sample_size` и `small_sample_warning`;
- `confidence.method = wilson_score_95_v1`, lower/upper bounds и консервативный
  `score = lower_bound`;
- `evidence_references` — ровно одна ссылка на каждый положительный раунд;
- `included_rounds` — весь denominator с флагом участия в numerator;
- `excluded_rounds` — раунды, где opportunity нельзя доказать, и причина;
- `limitations` и `warnings`.

Настройка по умолчанию требует 20 включённых матчей для корпуса и denominator 5 для
отдельной записи. Расчёт на меньшем наборе сохраняется, но маркируется предупреждением.
Wilson interval измеряет устойчивость наблюдаемой доли при данной выборке. Он не
доказывает причинность, намерение команды или полезность будущей рекомендации.

## Denominators V1

| Pattern | Scope | Denominator | Positive value |
|---|---|---|---|
| `site_preference` | T | раунды с доказанным plant site | A или B |
| `early_zone_occupation` | T/CT | раунды с наблюдаемой early-zone feature | зона присутствовала |
| `recurring_opening_player` | T/CT | opening duels, выигранные соперником | Steam/occurrence игрок |
| `recurring_opening_death` | T/CT | opening duels, проигранные соперником | Steam/occurrence игрок |
| `first_contact_zone` | T/CT | раунды с доказанной зоной first contact | роль + зона |
| `first_utility` | T/CT | раунды с first utility evidence | grenade type + зона/explicit unresolved |
| `bomb_routing` | T | раунды с доказанной последовательностью bomb zones | точная последовательность зон |
| `ct_starting_position` | CT | раунды с полной starting-zone coverage | точная 5-player zone distribution |
| `opening_kill_conversion` | T/CT | соперник выиграл opening duel, outcome известен | затем выигран раунд |
| `recovery_after_opening_death` | T/CT | соперник проиграл opening duel, outcome известен | затем выигран раунд |
| `lost_man_advantage` | T/CT | доказанный positive либо `not_applicable` Stage 8.4 fact | факт наблюдался |
| `untraded_death` | T/CT | доказанный positive либо `not_applicable` Stage 8.4 fact | факт наблюдался |
| `plant_timing` | T | раунды с доказанным временем plant от freeze end | configured time bucket |

`early_rotation`, `retake_frequency` и `save_frequency` в V1 имеют capability
`unavailable`: отсутствие положительного Stage 8.4 события не доказывает отрицательную
opportunity, rotation semantics или намерение save.

## Pydantic contracts

Основные immutable-модели находятся в `stratweb.patterns.models`:

- `PatternConfig`, `PatternScope`;
- `PatternMatchInput`, `PatternRoundInput`, `PatternPlayerIdentity`;
- discriminated `PatternValue` (`categorical|player|route|setup|timing_bucket|binary`);
- `PatternRoundEvidence`, `PatternRoundExclusion`;
- `WilsonConfidence`, `CrossMatchPattern`;
- `PatternCapability`, `PatternState`, `PatternRunSummary`.

Validators запрещают `numerator > denominator`, несовпадение frequency, sample size и
denominator, неверный small-sample flag и отсутствие одной numerator evidence-ссылки
на каждый положительный раунд. Неизвестные значения nullable или typed unavailable;
они не заменяются нулём, проигрышем, зоной или игроком.

Пример сокращённой записи:

```json
{
  "pattern_type": "site_preference",
  "scope": {
    "map_name": "de_anubis",
    "side": "T",
    "buy_type": "full",
    "feature_rule_version": "per_round_facts_v1"
  },
  "value": {"kind": "categorical", "key": "site:A", "label": "Bombsite A"},
  "availability": "available",
  "numerator": 12,
  "denominator": 18,
  "frequency": 0.6666666666666666,
  "sample_size": 18,
  "minimum_sample_size": 5,
  "small_sample_warning": false,
  "confidence": {
    "method": "wilson_score_95_v1",
    "level": 0.95,
    "score": 0.4379,
    "lower_bound": 0.4379,
    "upper_bound": 0.8372
  },
  "evidence_references": [
    {
      "match_id": "00000000-0000-0000-0000-000000000001",
      "round_id": "00000000-0000-0000-0000-000000000002",
      "round_number": 7,
      "tick": 31415,
      "contributed_to_numerator": true,
      "feature_ids": ["00000000-0000-0000-0000-000000000003"],
      "event_ids": ["00000000-0000-0000-0000-000000000004"]
    }
  ],
  "limitations": []
}
```

Полный payload дополнительно содержит UUID run/pattern/profile, match counts, весь
`included_rounds`, exclusions, snapshot/economy evidence IDs и warnings.

## DuckDB migration 020

| Table | Назначение |
|---|---|
| `cross_match_pattern_runs` | immutable version/config/workspace fingerprints, capabilities, summary |
| `pattern_run_inputs` | выбранные match/team и pinned feature run либо exclusion reason |
| `cross_match_patterns` | фильтруемые scope/stat columns + полный typed JSON payload |
| `pattern_round_evidence` | нормализованный denominator каждого pattern value |
| `pattern_round_exclusions` | исключённые раунды и причины |

Run fingerprint включает schema/rule/config, точный workspace, feature fingerprints и
полученные aggregates. UUIDv5, canonical JSON и стабильная сортировка обеспечивают
идемпотентность. Latest-compatible выбор требует, чтобы текущие selections совпадали и
все включённые feature runs всё ещё существовали. Upstream delete выполняет child-first
cascade; исторические несовместимые runs не смешиваются с выбранным run.

## Известные ограничения и типичные ошибки

- Маленький corpus может дать высокую raw frequency; читать её без Wilson interval и
  warnings нельзя.
- Большое число раундов одного матча не заменяет независимость нескольких матчей,
  поэтому отдельно показаны match counts.
- Early-zone паттерны условны относительно раундов, где зона наблюдаема; это не доля
  всех выбранных раундов.
- Exact bomb routes и CT setups чувствительны к granularity/version zone set, поэтому
  downstream finding обязан сохранять pinned provenance.
- Игрок без Steam ID не может быть честно объединён между матчами по nickname.
- `not_applicable` допустим как отрицательная opportunity только для Stage 8.4
  feature types, чья rule прямо гарантирует эту семантику.
- Нельзя интерпретировать association opening duel → round result как причину победы.
- Нельзя сравнивать или объединять записи из разных runs без нового детерминированного
  расчёта.
