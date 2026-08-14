# Analysis Finding Model — Stage 8.6

## Граница этапа

Stage 8.6 превращает сохранённые Stage 8.5 aggregates в воспроизводимые записи для
будущего отчёта. Он не вычисляет контрстратегию и не использует LLM.

`observation` доступен и формируется детерминированным шаблоном. Поля
`tactical_implication`, `recommended_response` и `avoid` существуют отдельно, но до
Stage 8.7 имеют:

```json
{
  "availability": "unavailable",
  "text": null,
  "reason": "stage_8_7_counter_strategy_rules_not_computed"
}
```

## AnalysisRun

Immutable run закрепляет:

- `analysis_schema_version = 1.0.0`;
- `analysis_rule_version = analysis_findings_v1`;
- configuration hash;
- opponent profile и workspace fingerprint;
- точный Stage 8.5 run ID/fingerprint/schema/rule;
- все selected match/team IDs;
- demo file ID, demo SHA-256 и canonical dataset fingerprint;
- pinned feature run/fingerprint или typed exclusion;
- summary, row counts и warnings.

Повторный идентичный расчёт возвращает `already_exists`. UUIDv5 и fingerprint не
содержат текущее время. По умолчанию выбирается только run, основанный на текущем
совместимом Stage 8.5 run; historical run доступен по явному UUID.

## AnalysisFinding

Каждый finding хранит source pattern ID/type/value/scope и без изменения переносит:

- numerator/denominator/frequency;
- sample size и match counts;
- minimum sample size и small-sample flag;
- полный Wilson confidence contract;
- source availability, limitations и warnings.

Default config включает partial patterns, потому что их ограничения видны, и исключает
zero-frequency bins, чтобы отсутствие наблюдения не выдавалось за положительное
утверждение. Обе настройки участвуют в configuration hash.

Пример observation:

```json
{
  "availability": "available",
  "text": "Bombsite A: observed in 12 of 18 eligible rounds (66.7%) within de_anubis, T, full.",
  "reason": null
}
```

Округление есть только в тексте; authoritative `frequency` остаётся полным `double`.

## EvidenceReference

Finding хранит ровно denominator ссылок. Каждая содержит:

- `demo_file_id`, `demo_sha256`, `match_id`, `round_id`, `round_number`;
- nullable tick без предположения времени;
- `contributed_to_numerator`;
- upstream feature/event/spatial/economy IDs;
- limitations;
- exact `map_href` и `timeline_href`.

Validator требует, чтобы число evidence равнялось denominator, а число ссылок с
`contributed_to_numerator=true` равнялось numerator.

## DuckDB migration 021

- `analysis_runs` — immutable provenance;
- `analysis_run_inputs` — точный corpus и pinned inputs;
- `analysis_findings` — queryable scope/statistics и полный typed payload;
- `finding_evidence_references` — normalized evidence appendix.

Удаление source pattern run удаляет findings child-first. Данные двух analysis runs не
объединяются одним запросом.

## Ограничения

- Finding пока является доказательным наблюдением, а не советом.
- Высокая frequency не доказывает намерение или причинность.
- Маленький corpus и denominator остаются видимыми.
- Partial source pattern остаётся partial finding.
- Отсутствующий tick не заменяется расчётным значением.
- Stage 8.7 обязан использовать эти immutable числа/evidence и не менять их.
