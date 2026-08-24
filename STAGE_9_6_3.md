# Stage 9.6.3 — Tactical V2 HTML evidence drill-down

Дата завершения: 2026-08-24. Версия приложения: `0.10.3`. Locale schema: `2.1.0`.
Миграция DuckDB и изменение analytical rules не требуются.

## Результат

У каждой карточки Tactical V2 появилась кнопка «Показать доказательства». Отдельная страница
показывает конкретные матчи, раунды и доказанный tick/range, вошедшие в наблюдение. Страница
доступна на русском и английском и использует не raw diagnostic table, а product-first карточки.

## Доступные переходы

- обзор исходного матча;
- точный Temporal round из закреплённого run;
- якорь нужного тика в timeline;
- individual Temporal event с typed before/after состояниями;
- post-tick snapshot, только когда evidence подтверждает один event tick;
- Spatial 2D в `mode=exact`, только при наличии snapshot IDs;
- round facts, только при наличии feature IDs и закреплённого Feature run.

Тип перехода не показывается, если соответствующий artifact не указан. При отсутствии source pin
остаётся только безопасная match-level ссылка и явное предупреждение.

## Архитектурные гарантии

- detail route получает один insight по `(profile_id, tactical_run_id, insight_id)`;
- evidence пагинируется по 24 ссылки и не загружается без ограничения в HTML;
- source pins определяют точные Temporal, Spatial и Feature runs;
- сортировка стабильна: corpus match order → round → tick range;
- UUID и artifact IDs находятся в сворачиваемом техническом блоке;
- переходы read-only и не запускают parser, analytics или persistence writes;
- observation numerator, denominator, frequency, evidence и fingerprint не изменяются.

## Автоматическая и реальная acceptance

- неизвестный insight в выбранном run возвращает 404;
- ru/en страницы рендерятся без смешения product labels;
- persistence lookup не возвращает insight другого run/profile;
- pagination имеет фиксированный размер и стабильные run-pinned URL;
- Temporal timeline содержит `tick-*` и `event-*` anchors;
- реальный профиль `hanak1ri`: 191 insights, 24 evidence actions на первой странице;
- реальный event detail, post-tick snapshot и exact Spatial 2D возвращают HTTP 200;
- server error log после проверки пуст.

## Осознанные ограничения

Projectile/effect IDs пока не имеют отдельного HTML viewer и остаются в техническом disclosure.
Полная ручная mobile/visual acceptance и analyst notes относятся к Stage 9.6.4. Испанская и
китайская локали остаются выключенными до полного покрытия каталогов.

Stage 9.6.4 этим этапом не начат.
