# Stage 9.6.4 — Mobile states and analyst notes

Дата завершения: 2026-08-24. Версия приложения: `0.10.4`. Locale schema: `2.2.0`.
DuckDB migration: `027 local_analyst_notes`. Note schema: `1.0.0`.

## Что изменилось

- Tactical V2 и формы заметок показывают явное состояние выполнения и блокируют повторную
  отправку до ответа сервера.
- Страница доказательств имеет отдельные RU/EN состояния для отсутствующего observation и для
  observation без доступных episode references.
- На экранах до 700 px заголовок, evidence actions и элементы заметки перестраиваются в одну или
  две колонки; до 460 px все evidence actions становятся одноколоночными.
- У каждого observation появилась одна редактируемая личная заметка аналитика.

## Граница доверия

Заметка — это пользовательский контекст, а не вывод системы. Она хранится отдельно в
`analyst_notes` и закреплена за точными `profile_id`, `tactical_run_id` и `insight_id`. Она не
меняет и не дополняет:

- numerator, denominator, frequency или sample size;
- Tactical insight/evidence payload;
- fingerprint, capability или source lineage;
- finding, tactical interpretation или recommendation;
- JSON evidence API.

Новая версия Tactical run не получает заметку от старой версии автоматически. Удаление run
каскадно удаляет только его собственные заметки. Изменения разрешены только loopback-клиенту;
браузерный cross-origin запрос отклоняется.

## Acceptance

- normalization: CRLF приводится к LF, содержимое не переформулируется; пустой текст и NUL
  отклоняются; предел — 2000 символов;
- persistence: deterministic note ID, повторное сохранение обновляет запись, exact lineage
  проверяется перед записью, cascade не оставляет orphan rows;
- HTTP: save/delete redirect возвращает на тот же evidence run, RU/EN error page имеет 404,
  hostile Origin получает 403;
- UI contract: loading script, локализованные состояния и phone breakpoints проверяются тестами;
- существующие Tactical V2 данные и API остаются неизменными.

## Ограничения

- Это локальная однопользовательская заметка без истории правок, совместного доступа и аудита.
- Remote read-only просмотр может видеть сохранённую заметку, но remote-клиент не может её менять.
- Полная матрица реальных iOS/Android браузеров остаётся ручной продуктовой проверкой; серверные,
  HTML/CSS и responsive contracts покрыты автоматическими тестами.
- Stage 9.7, роли, авторизация и командная работа не реализованы.
