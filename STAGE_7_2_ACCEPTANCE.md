# Stage 7.2 — Acceptance report

Дата проверки: 2026-07-18. Среда: Windows, локальный Microsoft Edge в headless-режиме,
FastAPI/Uvicorn на `127.0.0.1:8000`, реальная завершённая FACEIT demo и DuckDB.

## Scope

Проверен только Stage 7.2: product shell, match library, безопасный локальный import,
Temporal UI cleanup, пакетный Spatial playback и UI hardening. Tactical analytics, zones,
map control, rotations, heatmaps, coaching, recommendations и AI не реализовывались.

## Обнаруженные проблемы исходного UI

- Playback использовал `setInterval(300 ms)`, один HTTP request на sample и полную пересборку
  SVG/карточек после ответа.
- Не было initial buffer, prefetch, `requestAnimationFrame`, Smooth/Exact или безопасной
  визуальной интерполяции.
- Главная страница требовала ручной UUID; страницы имели разные shell/CSS и показывали
  технические идентификаторы как основной контент.
- URL update терял остальные filters; подписи игроков пересекались на spawn.
- Timeline по умолчанию показывал слишком много низкоценных событий.

В ходе self-review Stage 7.2 дополнительно найдены и исправлены:

- race между prefetch старого и нового filter generation;
- перекрывающиеся prefetch range на скорости 4×;
- потеря pinned run и filters при смене раунда;
- восстановление неправильного round select из browser BFCache;
- недоступные event ticks в map jump list;
- переход player path на latest run вместо page-pinned run;
- отображение side score после side swap вместо physical-team score;
- пустой `img src` при недоступном overview;
- недостаточно явный victimless-death heading;
- лишний browser 404 для favicon.

## Frontend и playback architecture

Нормативное описание находится в [PLAYBACK_ARCHITECTURE.md](PLAYBACK_ARCHITECTURE.md).
Server-rendered слой использует Jinja, общий application shell, CSS tokens/components и
малые JS-модули. React/Vue/Electron/Node build pipeline не добавлены.

Playback state:

```text
initial chunk -> paused exact sample -> Play -> requestAnimationFrame visual frames
                      ^                  |                 |
                      |                  |          authoritative boundary
event/scrub/prev/next +------------------+                 |
                                                         prefetch -> next chunk
```

`SpatialPlaybackChunk` содержит только сохранённые authoritative samples и всегда сообщает
`visual_interpolation_included=false`. Smooth blend существует только в браузере и не
сохраняется. Exact, scrubber release, event jump, Previous/Next и Temporal links всегда
останавливаются на сохранённом tick.

## Performance: до и после

| Метрика | Stage 7.1 | Stage 7.2 |
|---|---:|---:|
| Network policy | 1 request/sample | 64 samples/chunk + contiguous prefetch |
| Warm server cost | 185.9 ms/exact sample | 581–603 ms/64-sample chunk |
| Amortized warm server cost | ~185.9 ms/sample | ~9.3 ms/sample |
| Buffered exact transition | network-bound | 1.4 ms, 0 requests |
| Render loop | 300 ms interval | `requestAnimationFrame` |
| Measured renderer | not instrumented | 0.11–0.13 ms average |
| Dropped frames in acceptance run | not instrumented | 0 |
| DOM nodes in viewer | rebuilt after response | 94 persistent/keyed nodes |
| Spawn labels | fixed overlapping offset | 10 visible, 0 intersections |

Первый cold 64-sample response занял 1494.1 ms; прогретые ответы — 581.0–603.0 ms.
Размер FACEIT Round 1 chunk — 874251 bytes. При проверке границы buffer на 4× playback
перешёл с sample 49 к sample 80, выполнил ровно один prefetch и расширил buffer с 64 до
128 samples. Эти значения являются локальным profiling result, а не универсальной CI SLA.

## FACEIT manual acceptance

Match: `24708cef-d95e-53f6-9f96-d6deb6a85e7e`, `de_ancient`, 17 раундов.
Spatial run: `04a85475-654a-5c6c-9ee7-8436c47f6a0f`.
Temporal 1.1 run: `e164aa3d-639c-5726-bb06-c60877d8a2ad`.

| Проверка | Результат |
|---|---|
| Запуск и health | PASS, `0.2.0` |
| Match library / open without UUID | PASS, 1 card, UUID input отсутствует |
| Overview / physical score / players | PASS, `TeamBravo 13:4 TeamAlpha`, 10 players |
| Round 1 map | PASS, 460 authoritative samples |
| Smooth / Exact / 0.25×–4× | PASS |
| Scrubber / Previous / Next / event jump | PASS |
| Label layout near spawn | PASS, 10 labels, 0 intersections |
| Death transition | PASS, victim `alive true -> false`, interpolation blocked |
| Simultaneous group | PASS, R3 tick 24548, ambiguous intermediate, deterministic post-state `2T/3CT` |
| Victimless death | PASS, R1 tick 8042, unbound, unavailable effect, alive `5T/3CT -> 5T/3CT` |
| Final snapshot | PASS, `0T/1CT`, bomb defused |
| Temporal ↔ Spatial links | PASS, authoritative tick/run pinned |
| Diagnostics and run history | PASS, counters clickable, 1.1 and legacy 1.0 shown separately |
| Back/Forward / round BFCache | PASS, tick, mode, filters, round and run restored |
| Restart persistence | PASS, Spatial/Temporal run IDs unchanged |
| Browser errors | PASS, 0 console errors, 0 failed requests |

Screenshots:

- `.stage7-manual/screenshots/stage7-2-library.png`;
- `.stage7-manual/screenshots/stage7-2-overview.png`;
- `.stage7-manual/screenshots/stage7-2-playback.png`;
- `.stage7-manual/screenshots/stage7-2-diagnostics.png`;
- `.stage7-manual/screenshots/stage7-2-simultaneous.png`;
- `.stage7-manual/screenshots/stage7-2-victimless.png`.

## Quality gates

- `ruff format`: PASS, 113 files;
- `ruff check`: PASS;
- `mypy --strict`: PASS, 81 source files;
- `pytest -m "not integration"`: PASS, 192 tests;
- FACEIT integration: PASS, 6 tests in 159.76 s;
- `pip check`: PASS;
- import smoke: PASS, `StratWeb 0.2.0`;
- `docker compose config --quiet`: PASS;
- wheel build: PASS, templates/static/favicon включены в `stratweb-0.2.0-py3-none-any.whl`;
- Edge manual acceptance: PASS, без console errors и failed requests.

## Product debt перед отдельным Stage 8

- Temporal details и raw Spatial table ещё используют compatibility renderer для старых
  evidence-safe HTML fragments внутри общего Jinja shell. CSS/JavaScript из Python удалены,
  но полная миграция этих fragments в component templates остаётся отдельным cleanup.
- Process-local import jobs не переживают restart и не поддерживают resume; уже завершённые
  persisted runs переживают restart.
- Web delete намеренно не добавлен: repository умеет удалять, но безопасного orchestration
  service с invalidation долгоживущих read caches пока нет.
- 64-sample JSON chunk на реальной демке занимает около 0.87 MB; локальная сеть приемлема,
  но compression/columnar compact payload остаются возможной оптимизацией.
- Playback использует UI policy `260 ms/sample`, пока canonical tickrate не доказан.
- Browser behavior проверяется лёгкими pure-JS unit tests и ручным Edge acceptance; тяжёлый
  browser framework не добавлен в обязательные project dependencies.
- Overview assets требуют локально извлечённых официальных CS2 файлов; rotated transforms
  остаются unavailable.
- Текущая Spatial evidence подтверждает carried C4, но не dropped/planted C4 coordinates.

Stage 8 не начат.
