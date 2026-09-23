# Release 0.30.0 — Product Truth

## Цель

Пользовательский статус не должен быть сильнее фактов, подтверждённых импортом, структурной
валидацией, аналитическими слоями, evidence и corpus acceptance.

## Каноническая policy

Единственный нормативный источник — [STAGE_9_7_2.md](STAGE_9_7_2.md) и соответствующее правило
`finding_readiness_v2`. Product Truth различает импорт, структурную валидность,
Analytics/Temporal/Spatial availability, достаточность evidence, recommendation eligibility и
real-data corpus acceptance.

Библиотека получает явные `status`, `severity`, `reasons`, `missing_layers` и `next_action` из
backend view model. Jinja больше не выводит готовность из `warning_count`.

## Ограничения

- `limited` recommendation остаётся гипотезой и обязана показывать reliability limitation;
- `blocked` finding не создаёт рекомендацию;
- Golden Corpus manifest технически валиден, но real-data acceptance остаётся `blocked`:
  подтверждённых матчей и analyst labels нет.

## Вне scope

Релиз не меняет Tactical V2 500→404, глобальную обработку API exceptions, DuckDB writer
coordination, atomic batch creation, analytics semantics, authentication, tenants, mobile redesign
или performance architecture. Эти задачи оставлены для 0.31+.
