# StratWeb

StratWeb — локальное backend-приложение для доказательного предматчевого анализа
завершённых Counter-Strike 2 demo-файлов (`.dem`). Оно должно находить повторяемые
командные и индивидуальные паттерны, но каждый вывод обязан ссылаться на конкретные
демки, матчи и раунды.

Реализованы этапы 1–8.9, release baseline Stage 9.0 и Golden Corpus tooling Stage 9.1: inspection и canonical dataset (`demoparser2==0.41.4`
за портом), DuckDB persistence (миграции 001–023), `Gameplay Analytics Engine V1`
(opening/trade/KAST/multikill/advantage/bomb метрики), `Temporal Round State
Engine 1.1.0` (immutable timeline, snapshots — [TEMPORAL_MODEL.md](TEMPORAL_MODEL.md)),
Spatial Engine с playback viewer ([SPATIAL_MODEL.md](SPATIAL_MODEL.md),
[PLAYBACK_MODEL.md](PLAYBACK_MODEL.md)), карты с версионированными overview
([MAP_MODEL.md](MAP_MODEL.md)), локальный upload `.dem` с durable import jobs,
Opponent Workspace ([OPPONENT_MODEL.md](OPPONENT_MODEL.md)), versioned Zone
Assignment Runs ([ZONE_MODEL.md](ZONE_MODEL.md)), Economy Context и детерминированные
per-round tactical facts ([ROUND_FEATURE_MODEL.md](ROUND_FEATURE_MODEL.md)) и
cross-match patterns ([PATTERN_MODEL.md](PATTERN_MODEL.md)) и воспроизводимые findings
([FINDING_MODEL.md](FINDING_MODEL.md)). Основные продуктовые страницы имеют русский
presentation-слой, а проверенные вручную названия команд хранятся отдельно от canonical
identity ([UI_LOCALIZATION.md](UI_LOCALIZATION.md)). Детерминированные рекомендации,
evidence-first UI и стабильные JSON/PDF/printable exports описаны в
[SCOUTING_REPORT_UI.md](SCOUTING_REPORT_UI.md) и [REPORT_EXPORT.md](REPORT_EXPORT.md).
Все движки parser-independent и детерминированы; tick — authoritative единица времени.
Дальнейшее production hardening — в [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Безопасная область продукта

Проект предназначен исключительно для офлайн-анализа уже завершённых матчей. В нём
не предполагаются чтение памяти CS2, внедрение в процесс игры, live radar/overlay,
подсказки во время активного матча или автоматизация игрового ввода.

## Выбор парсера

Основной parser для MVP — `demoparser2==0.41.4`, подключаемый через собственный
порт `DemoParser`. `Awpy==2.0.2` изучен как более высокоуровневая альтернатива, но не
включён в runtime: Awpy сам использует demoparser2, тянет ненужные backend-MVP
зависимости визуализации/научного стека и применяет готовые преобразования, которые
сложнее включить в прозрачную цепочку evidence.

Подробное сравнение, проверенные сигнатуры и решение находятся в
[ARCHITECTURE.md](ARCHITECTURE.md). Последовательность будущей реализации — в
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Структура

```text
src/stratweb/
├── adapters/          # adapters demoparser2 и DuckDB persistence (+ migrations)
├── analytics/         # pure Gameplay Analytics Engine V1 и validation
├── temporal/          # pure Temporal Round State Engine и snapshots
├── spatial/           # pure Spatial Engine, projectiles и map overview queries
├── economy/           # freeze-end equipment evidence и buy classification
├── features/          # pure deterministic Stage 8.4 per-round facts
├── patterns/          # pure deterministic Stage 8.5 cross-match aggregates
├── findings/          # pure deterministic Stage 8.6 findings + evidence
├── readiness/         # Stage 8.6.1 quality gate before recommendations
├── counter_strategy/  # Stage 8.7 deterministic recommendation rules
├── maps/              # версионированные map definitions, transforms и registry
├── application/       # inspection, normalization, import/query, playback,
│                      # opponents, economy, features, patterns и import jobs use cases
├── web/               # FastAPI routers, Jinja templates, static JS/CSS viewer
├── domain/            # parser-independent модели и enum
├── reporting/         # стабильный JSON contract и HTML/PDF presentation
├── config.py          # настройки окружения (.env, префикс STRATWEB_)
├── contracts.py       # DTO между портами
├── exceptions.py      # typed inspection/import/persistence errors
├── cli.py             # inspect/normalize/db/import/matches/rounds/analytics/
│                      # temporal/spatial/features/patterns commands
├── main.py            # FastAPI-приложение и composition root
└── ports.py           # интерфейсы модулей
tests/                 # 43 модуля: unit, integration, UI и frontend tests
```

Запуск локального сервера описан в [SERVER_GUIDE.md](SERVER_GUIDE.md)
(`scripts/start_server.ps1`).

## Локальная установка

Требуется CPython 3.11–3.14. Release baseline использует `uv==0.11.16` и
закреплённый `uv.lock`:

```bash
uv sync --frozen --extra dev
uv run --frozen pytest
uv run --frozen python -c "from stratweb.main import app; print(app.title)"
```

Fallback без uv остаётся доступен для локальной разработки:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
python -c "from stratweb.main import app; print(app.title)"
```

Полная локальная проверка релиза:

```powershell
.\scripts\release_check.ps1
```

История версии находится в [CHANGELOG.md](CHANGELOG.md), процедура восстановления — в
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), ограничения сетевого запуска — в
[SECURITY.md](SECURITY.md).

## Локальная инспекция `.dem`

Команда читает demo только локально, считает SHA-256 потоково, запрашивает header,
список событий, поддерживаемые event tables и player info. Полный raw event payload
в JSON не включается, `parse_ticks` не вызывается.

```powershell
# Через module entry point
python -m stratweb.cli inspect "C:\path\to\match.dem" --pretty

# Эквивалентный console script
stratweb inspect "C:\path\to\match.dem" --pretty

# Сохранить JSON и одновременно вывести его в stdout
stratweb inspect "C:\path\to\match.dem" --output report.json --pretty

# Явно разрешить замену существующего JSON
stratweb inspect "C:\path\to\match.dem" --output report.json --force

# Показать traceback при контролируемой ошибке
stratweb inspect "C:\path\to\broken.dem" --debug
```

Без `--force` существующий output не изменяется. Ошибки печатаются в stderr и дают
ненулевой exit code; успешный или частичный inspection возвращает `0` и валидный JSON
schema version `1.1.0`.

`round_start` и `round_end` не считаются обязательными. Inspection автоматически
сопоставляет доступные lifecycle aliases:

- `round_start`, `round_poststart`, `round_prestart`, `round_freeze_end` →
  `CanonicalRoundStart`;
- `round_end`, `round_officially_ended` → `CanonicalRoundEnd`.

Алиасы не суммируются: для каждого canonical event выбирается наиболее надёжный
доступный source, а строки одного source дедуплицируются по round marker или tick.
`estimated_round_count` сначала использует глобальный `MAX(total_rounds_played)` по
всем разобранным gameplay events, затем `CanonicalRoundEnd`, затем
`CanonicalRoundStart`. В JSON сохраняются источник оценки и все candidates; warmup
строки исключаются, когда parser предоставляет `is_warmup_period`.

## Canonical Match Dataset

Отдельная команда строит полный versioned canonical JSON:

```powershell
# Компактный результат для терминала
stratweb normalize "C:\path\to\match.dem" --summary-only --pretty

# Полный dataset в файл; JSON также остаётся в stdout
stratweb normalize "C:\path\to\match.dem" --output canonical-match.json --pretty

# Явная замена существующего результата
stratweb normalize "C:\path\to\match.dem" --output canonical-match.json --force
```

Без `--output` и `--summary-only` CLI предупреждает в stderr, что полный JSON может
быть большим. Canonical contract `1.1.0` содержит match, физические команды, игроков,
membership intervals, раунды, kills/damages/shots/grenades/bomb events, validation
report и normalization metadata. Наружу не выходят pandas/Polars DataFrame или raw
parser payload.

### Доступность result data

Для winner, score и end reason значение и его provenance хранятся раздельно:

- `available` — значение получено из проверенного authoritative source;
- `missing_from_source` — нужного поля/строки не было в parser source;
- `unresolved`/`unresolved_conflict` — source был, но безопасно разрешить его нельзя;
- `not_applicable` — данные намеренно неприменимы;
- `derived_from_authoritative_score_delta` — winner получен только из однозначного
  приращения прямого authoritative score, а не из gameplay-эвристики.

Отсутствие round winner не является проигрышем, ничьей или стороной
`UNKNOWN`: `winner_side` в этом случае равен `null`, а причина видна в
`outcome_status`. Метрика, требующая исхода раунда, должна возвращать
`unavailable`, а не `0%`, если coverage неполное. Минимальный
`evaluate_result_use_policy()` даёт такой gate; сами метрики на этапе 4.5 не
реализованы.

На FACEIT fixture аудит `demoparser2==0.41.4` подтвердил прямые netvar-поля
`m_iRoundEndWinnerTeam`, `m_eRoundEndReason` и `CCSTeam.m_iScore` в
`round_officially_ended`/`cs_win_panel_match`. Raw reason code сохраняется без
непроверенной семантической расшифровки. Raw parser payload в dataset/DB не
сохраняется.

Round resolution использует event semantics, а не обязательность конкретного alias:

- start boundary: `round_prestart` → `round_start` → `round_poststart` →
  `round_freeze_end`;
- freeze boundary: `round_freeze_end`;
- end boundary: `round_end` → `round_officially_ended`;
- terminal fallback для missing final official end: реальный `cs_win_panel_match`,
  если он присутствует и его `total_rounds_played` совпадает с выбранным count.

Строки одного marker дедуплицируются по последнему tick. На FACEIT это удаляет
knife/reset start и превращает 58 duplicate official-end rows в 29 наблюдаемых
завершений. Overtime начинается после второго фактически наблюдаемого
`announce_phase_end`; фиксированное число regulation rounds не предполагается.

`RoundAssignmentService` един для всех событий. Окна полуоткрытые по start tick;
поддерживаются `freeze_time`, `live`, `post_round`, `unknown`. События до первого
подтверждённого round start сохраняются unassigned и учитываются validation report.

Steam ID — единственный безусловный ключ игрока. Nickname changes/reconnect не создают
нового игрока; actors без Steam ID получают occurrence-scoped identity и не
объединяются только по имени. `TeamAlpha`/`TeamBravo` обозначают физические составы,
а T/CT хранится как изменяемая membership/round side. Side switches выводятся из
наблюдаемых event-side значений.

UUIDv5, стабильная сортировка, rule/config versions и canonical JSON hashing дают
одинаковые IDs и `dataset_fingerprint` при повторном прогоне. Текущее время,
randomness, сеть и LLM в fingerprint не участвуют.

Validation severities: `info`, `warning`, `error`. Fatal считаются только нарушения
структурной целостности — overlap/невалидные round windows, broken references,
negative canonical ticks, duplicate IDs и нестабильная сортировка. Missing final
official end, incomplete/unassigned rows и uncertainty сохраняются как warnings.

## DuckDB persistence и CLI

Путь к embedded database разрешается в строгом порядке:

1. `--db C:\path\to\matches.duckdb` для конкретной команды;
2. `STRATWEB_DUCKDB_PATH` из process environment или `.env`;
3. `data/stratweb.duckdb`.

Инициализация применяет только отсутствующие migrations и проверяет SHA-256 уже
применённых SQL definitions:

```powershell
stratweb db init --db .\data\stratweb.duckdb --pretty
```

Импорт `.dem` сначала выполняет существующую canonicalization, затем сохраняет весь
dataset одной transaction. Повторный fingerprint даёт `already_exists`; `--force`
выполняет atomic replace. Stdout содержит только compact `ImportResult`, а не полный
canonical payload:

```powershell
stratweb import "C:\path\to\match.dem" --db .\data\stratweb.duckdb --pretty
stratweb import "C:\path\to\match.dem" --db .\data\stratweb.duckdb --force
```

Готовый canonical JSON можно импортировать без повторного parser run. Его Pydantic
schema, schema version, fingerprint, fatal validation, counts и references
перепроверяются; embedded summary не считается доверенным источником:

```powershell
stratweb import --canonical-json .\canonical-match.json --db .\data\stratweb.duckdb
```

Базовые read-only запросы и удаление:

```powershell
stratweb matches list --db .\data\stratweb.duckdb --map-name de_mirage --pretty
stratweb matches show MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb rounds list MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb rounds show MATCH_ID 1 --db .\data\stratweb.duckdb --pretty

# Запрашивает подтверждение; --yes предназначен для scripts/tests.
stratweb matches delete MATCH_ID --db .\data\stratweb.duckdb
stratweb matches delete MATCH_ID --db .\data\stratweb.duckdb --yes
```

### Gameplay Analytics Engine V1

Сначала импортируйте canonical match, затем вычислите отдельный analytics run:

```powershell
# Authoritative ticks mode; это также default, если flag не указан.
stratweb analytics compute MATCH_ID --db .\data\stratweb.duckdb `
  --trade-window-ticks 320 --pretty

# Seconds mode разрешён только когда canonical dataset содержит доказанный tickrate.
# Текущий canonical contract его не предоставляет, поэтому команда вернёт
# controlled analytics_configuration_error, а не предположит 64 tick/s.
stratweb analytics compute MATCH_ID --db .\data\stratweb.duckdb `
  --trade-window-seconds 5 --pretty

stratweb analytics show MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb analytics players MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb analytics player MATCH_ID PLAYER_ID --db .\data\stratweb.duckdb --pretty
stratweb analytics teams MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb analytics round MATCH_ID 1 --db .\data\stratweb.duckdb --pretty
stratweb analytics openings MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb analytics trades MATCH_ID --round 1 --db .\data\stratweb.duckdb --pretty
stratweb analytics advantage MATCH_ID 1 --db .\data\stratweb.duckdb --pretty
```

Trade window по умолчанию — `320 ticks`; StratWeb не называет его пятью секундами.
CLI JSON хранит mode, requested value, resolved ticks, tickrate и source. В ticks
mode `requested_seconds`, `tickrate` и `seconds_delta` равны `null`; KAST доступен,
но его capability явно помечен как основанный на tick window. Seconds mode требует
canonical tickrate evidence и при его отсутствии отклоняет весь compute.
Повторный dataset/rule/config возвращает `already_exists` и тот же
`analytics_fingerprint`; `--force` выполняет безопасный atomic replace.

Migration `003 gameplay_analytics_v1` хранит queryable normalized results отдельно
от canonical rows. Удалить только analytics можно командой
`stratweb analytics delete MATCH_ID --yes`; canonical match останется. Нормативные
формулы, denominators и null semantics описаны в
[ANALYTICS_DEFINITIONS.md](ANALYTICS_DEFINITIONS.md).

Migration `004 trade_window_semantics` добавляет физические policy/conversion поля.
Старые analytics runs не переписываются и отображаются как `legacy_ambiguous`, поэтому
их прежнее seconds значение не считается authoritative. Новые runs используют analytics
schema/rule `1.1.0`; из-за нового config contract их fingerprints закономерно отличаются.

### Temporal Round State Engine

После canonical import можно вычислить и запросить temporal run:

```powershell
stratweb temporal compute MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb temporal show MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb temporal round MATCH_ID 1 --db .\data\stratweb.duckdb --pretty
stratweb temporal events MATCH_ID 1 --db .\data\stratweb.duckdb --pretty
stratweb temporal transitions MATCH_ID 1 --db .\data\stratweb.duckdb --pretty
stratweb temporal participants MATCH_ID 1 --db .\data\stratweb.duckdb --pretty
stratweb temporal snapshot MATCH_ID 1 --tick 12000 --db .\data\stratweb.duckdb
stratweb temporal before-event MATCH_ID EVENT_ID --db .\data\stratweb.duckdb
stratweb temporal after-event MATCH_ID EVENT_ID --db .\data\stratweb.duckdb
stratweb temporal final MATCH_ID 1 --db .\data\stratweb.duckdb
stratweb temporal bomb MATCH_ID 1 --db .\data\stratweb.duckdb
```

`compute` использует только typed canonical rows. Если в той же БД есть Stage 5 run,
opening и man-advantage death stream дополнительно сверяются с ним, но analytics не
становится источником temporal state. Повторный запуск возвращает `already_exists`;
`--force` атомарно заменяет только совпадающий temporal run. Удаление
`stratweb temporal delete MATCH_ID --yes` сохраняет canonical и analytics данные.

Migration `005 temporal_round_state` хранит run, timelines, intervals, ordered events,
participants, life/bomb/normalized transitions и validation issues в queryable таблицах.
Snapshots на каждый tick не материализуются: произвольный snapshot воспроизводится из
immutable participant state и transitions. При отсутствии доказанного tickrate JSON
показывает tick, `seconds: null` и `conversion_status: unavailable`.

В таблицах находятся canonical matches/teams/players/memberships/rounds, пять
gameplay event families, validation issues и normalization metadata. Raw parser
payload не сохраняется. Steam ID хранится строкой. JSON используется только для
вложенных canonical values. Основной duplicate key — `dataset_fingerprint`; source
demo SHA хранится отдельно и индексируется для provenance.

Применённые migrations нельзя редактировать: checksum mismatch блокирует открытие на
запись. Перед backup нужно завершить все StratWeb-процессы и скопировать закрытый
`.duckdb` file; восстановленную копию проверяет `stratweb db init`. DB/WAL/tmp/backup,
`.dem` и canonical JSON artifacts исключены из Git. В БД хранится только basename
исходной демки, не её полный локальный path.

### Локальный integration fixture

Demo пользователя не копируется и не добавляется в репозиторий. Путь задаётся только
через окружение:

```powershell
$env:STRATWEB_TEST_DEMO="C:\path\to\match.dem"
python -m pytest -m integration
```

Если переменная не задана, integration-test автоматически пропускается. Обычные
unit-тесты используют fake parser и не требуют настоящих demo-файлов.

Read-only Temporal UI использует ту же локальную DuckDB и не запускает parser или
analytics. Путь задаётся через `STRATWEB_DUCKDB_PATH`, после чего приложение доступно на
`/ui`; match открывается по адресу `/ui/temporal/MATCH_ID`:

```powershell
$env:STRATWEB_DUCKDB_PATH=".\data\stratweb.duckdb"
python -m uvicorn stratweb.main:app --reload --host 127.0.0.1 --port 8000
# http://127.0.0.1:8000/ui
```

UI показывает round timeline, event/group/tick/final snapshots, шесть диагностических
счётчиков и warnings. Все ссылки закрепляют `temporal_run_id`: по умолчанию выбирается
последний совместимый run 1.1, Temporal 1.0 виден как изолированный legacy run и не
получает group/per-event semantics версии 1.1. JSON-представления доступны в
`/api/temporal/{match_id}/summary`, `/api/temporal/{match_id}/rounds/{round_number}` и
`/api/temporal/{match_id}/diagnostics`.

### Совместимость result contract

Migration `002 round_result_availability` транзакционно пересоздаёт `rounds`,
делает winner nullable и добавляет status/source. Старые значения 1.0.0 не
помечаются `available` без provenance. Canonical JSON 1.0.0 детерминированно
обновляется в 1.1.0 с консервативными `missing_from_source`/`unresolved`.

Новая schema меняет fingerprint. Match с тем же ID и другим fingerprint
по-прежнему требует явный `--force`; silent replace нет.

## Docker

Текущий контейнер также запускает только минимальный API-каркас. Будущий способ
локального запуска pipeline:

```bash
cp .env.example .env
docker compose up --build
```

На Windows вместо `cp` можно выполнить `Copy-Item .env.example .env`. DuckDB и
загруженные файлы будут находиться в локальном каталоге `data/`, который исключён из
Git. Отдельный сервер БД не нужен: DuckDB является embedded database.

## Принципы данных и аналитики

- Загруженный файл получает случайное внутреннее имя; исходное имя хранится только
  как metadata.
- SHA-256 является ключом обнаружения дубликатов.
- Parser name/version и версия канонической схемы сохраняются вместе с матчем.
- Сторона определяется для каждого раунда, а не навсегда привязывается к команде.
- Warmup и неполные раунды сохраняют диагностический статус и исключаются из
  стандартной аналитической выборки.
- Статистику вычисляет только детерминированный код. Будущий LLM сможет лишь
  переформулировать уже подтверждённые поля и не сможет менять числа/evidence.
- `observation`, `tactical_implication`, `recommended_response` и `avoid` — разные
  поля; корреляция не описывается как причинность.
- Любой `AnalysisFinding` обязан содержать evidence и ограничения применимости.

## Текущие ограничения

Реализованы локальный upload `.dem` с durable import jobs (Stage 7.2/8.0),
playback viewer, Opponent Workspace (Stage 8.1) и детерминированное ядро Map
Zone Engine; write-действия ограничены loopback. Принятые ручные наборы
Anubis, Cache и Mirage закреплены в коде. Stage 8.2B материализует точный
`resolved|unknown|unavailable` для каждого Spatial snapshot в отдельном
versioned run; playback показывает сохранённую зону выбранного игрока. Stage 8.3
добавляет versioned freeze-end Economy runs: equipment/spend/inventory evidence и
консервативные `pistol|eco|force|semi|full|unknown` labels отдельно для T/CT. Stage 8.4
сохраняет атомарные факты каждого раунда: расстановки и раннее присутствие по зонам,
первые контакты/utility, opening duel, путь бомбы, plant/post-plant, потерю
преимущества и непротрейженные смерти. Stage 8.5 находит только доказательные
повторения и не называет их execute/default, не объясняет причины и не рекомендует
контрстратегию. Stage 8.6 сохраняет observation/findings и полный evidence, но не
добавляет coaching semantics. Stage 8.7 формирует только прошедшие readiness gate
контрстратегии, а Stage 8.8 показывает pinned evidence-first отчёт. LLM отсутствует.
Не реализованы clutch, heatmaps, path clustering и spacing; tactical interpretation
появляется только у опубликованной deterministic recommendation.
`parse_ticks` вызывается Spatial extractor-ом для заранее выбранных Temporal ticks и
Economy extractor-ом только для canonical freeze-end ticks.
DuckDB workflow рассчитан на одного локального writer process. FACEIT fixture
проверена; полноценные Valve/HLTV/POV fixtures остаются ограничением corpus.
Полноценные Stage 8.5 corpus-проверки на 20+ матчах одного соперника ещё требуются.

### Spatial Engine Foundation

После canonical import и Temporal 1.1 run Spatial 1.0 вычисляется только из той же
завершённой демки (SHA-256 должен совпасть):

```powershell
stratweb spatial compute MATCH_ID "C:\path\to\match.dem" --db .\data\stratweb.duckdb --pretty
stratweb spatial status MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb spatial show MATCH_ID --round 1 --limit 500 --db .\data\stratweb.duckdb --pretty
stratweb spatial show MATCH_ID --player PLAYER_ID --output snapshots.json --db .\data\stratweb.duckdb
stratweb spatial validate MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb spatial runs MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb spatial delete MATCH_ID --yes --db .\data\stratweb.duckdb
```

### Versioned Zone Assignment Runs

После Spatial run детерминированный слой назначает каждой сохранённой позиции
доказанную именованную зону либо сохраняет `unknown`/`unavailable`:

```powershell
stratweb zones compute MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb zones status MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb zones runs MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb zones show MATCH_ID --round 1 --status unknown --limit 100 --db .\data\stratweb.duckdb --pretty
```

`zones compute` выбирает последний совместимый Spatial run. Для точного
исторического запуска используйте `--spatial-run UUID`. Флаг
`--require-proven-map-revision` запрещает назначения, если ревизия карты не
доказана метаданными демки. По умолчанию такие назначения разрешены, но run
маркируется `partial` и сохраняет warning — это не скрытая догадка.

JSON API: `GET /api/zones/{match_id}/summary`, `/runs`, `/assignments`.

### Economy and Equipment Context

Экономический слой требует точную исходную демку с тем же SHA-256 и сохраняет
доказательный снимок закупа отдельно для каждой стороны:

```powershell
stratweb economy compute MATCH_ID "C:\path\to\match.dem" --db .\data\stratweb.duckdb --pretty
stratweb economy status MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb economy teams MATCH_ID --buy-type full --side CT --db .\data\stratweb.duckdb --pretty
stratweb economy players MATCH_ID --round 1 --db .\data\stratweb.duckdb --pretty
```

Семантика, provenance и ограничения описаны в
[ECONOMY_MODEL.md](ECONOMY_MODEL.md); проверенный API парсера — в
[ECONOMY_PARSER_AUDIT.md](ECONOMY_PARSER_AUDIT.md).

Визуальная Economy-страница: `/ui/matches/MATCH_ID/economy`. Она показывает coverage,
закупы T/CT по раундам, деньги и раскрываемую экипировку игроков; фильтры не смешивают
разные Economy runs. JSON остаётся доступен через `/api/economy/{match_id}/summary`,
`/teams` и `/players`.

### Per-Round Tactical Features

Stage 8.4 объединяет только совместимые сохранённые Analytics, Temporal, Spatial,
Zone Assignment и optional Economy runs. Он не распознаёт названия тактик и не
сравнивает матчи:

```powershell
stratweb features compute MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb features status MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb features runs MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb features show MATCH_ID --round 10 --side T --type first_contact --db .\data\stratweb.duckdb --pretty
stratweb features delete MATCH_ID --yes --db .\data\stratweb.duckdb
```

Read-only JSON API: `/api/features/{match_id}/summary`, `/runs` и `/records`.
`records` фильтруется по `round`, `team_id`, `side`, `type`, `availability` и
`buy_type`. Семантика и честные ограничения V1 описаны в
[ROUND_FEATURE_MODEL.md](ROUND_FEATURE_MODEL.md).

Визуальная Stage 8.4.1 страница: `/ui/matches/MATCH_ID/features`. Она показывает
карточки coverage, таблицу по раундам, фильтры, раскрываемые typed payload/evidence и
переходы на map/timeline. Страница закрепляет один feature run и выводит не более 100
записей за раз. Она не вычисляет паттерны — данные предназначены для следующего
cross-match слоя.

### Cross-Match Opponent Patterns

Stage 8.5 агрегирует только матчи и физические команды, которые пользователь явно
закрепил в одном Opponent Workspace. Он не объединяет соперника по названию команды
или nickname и не смешивает map, сторону, тип закупа или версии feature rules:

```powershell
stratweb patterns compute PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb patterns status PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb patterns runs PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb patterns show PROFILE_ID --map de_mirage --side T --buy-type full `
  --type site_preference --db .\data\stratweb.duckdb --pretty
stratweb patterns delete PROFILE_ID --yes --db .\data\stratweb.duckdb
```

По умолчанию предупреждение о маленьком корпусе действует до 20 включённых матчей,
а для отдельной частоты — при denominator меньше 5. Каждая запись возвращает
numerator/denominator/frequency, Wilson 95% interval, полный denominator и точные
evidence-ссылки для числителя. Неизвестное не превращается в отрицательный факт.

JSON API: `POST /api/opponents/{profile_id}/patterns/compute` (только localhost),
`GET /api/opponents/{profile_id}/patterns/summary`, `/runs` и `/patterns`. У list API
есть фильтры `map`, `side`, `buy_type`, `type` и `availability`. Отдельного pattern UI
нет: patterns представлены через evidence-first report Stage 8.8.
Точные denominators и ограничения описаны в [PATTERN_MODEL.md](PATTERN_MODEL.md).

### Reproducible Analysis Findings

Stage 8.6 закрепляет один совместимый pattern run и материализует observation вместе с
полным evidence appendix. Эти исходные findings остаются неизменными и
typed-unavailable; Stage 8.7 хранит рекомендации отдельным run:

```powershell
stratweb findings compute PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb findings status PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb findings runs PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb findings show PROFILE_ID --side T --type site_preference `
  --db .\data\stratweb.duckdb --pretty
stratweb findings evidence PROFILE_ID FINDING_ID --db .\data\stratweb.duckdb --pretty
```

Stage 8.6.1 проверяет, какие findings вообще допустимо передавать будущим правилам
рекомендаций. По умолчанию нужны 20 матчей в корпусе, минимум два матча в evidence,
неpartial источник и известный buy type:

```powershell
stratweb readiness audit PROFILE_ID --db .\data\stratweb.duckdb --summary-only --pretty
```

Результат `ready|limited|blocked` и каждая причина вычисляются детерминированно;
Stage 8.6.1 не создаёт рекомендаций. Контракт: [FINDING_READINESS.md](FINDING_READINESS.md).

Stage 8.7 публикует рекомендации только для `ready` findings и сохраняет каждый
непройденный finding с точной причиной:

```powershell
stratweb strategies compute PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies status PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies show PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies skipped PROFILE_ID --db .\data\stratweb.duckdb --pretty
stratweb strategies validate PROFILE_ID --db .\data\stratweb.duckdb --pretty
```

Текущий профиль содержит один матч, поэтому правильный production-результат — ноль
рекомендаций и `blocked` acceptance с явными причинами: корпус 1/20 и 0 готовых
рекомендаций. Контракты: [COUNTER_STRATEGY_MODEL.md](COUNTER_STRATEGY_MODEL.md) и
[COUNTER_STRATEGY_VALIDATION.md](COUNTER_STRATEGY_VALIDATION.md).

JSON API находится под `/api/opponents/{profile_id}/analysis`: `/summary`, `/runs`,
`/findings`, `/findings/{finding_id}` и `/findings/{finding_id}/evidence`; compute —
localhost-only `POST /compute`. Контракт описан в
[FINDING_MODEL.md](FINDING_MODEL.md).

### Evidence-First Scouting Report

Stage 8.8 показывает один pinned Strategy run как предматчевый отчёт:

```text
/ui/opponents/PROFILE_ID/report
/api/opponents/PROFILE_ID/report
```

В отчёте есть acceptance/data quality, T-side и CT-side observations, individual и
risk signals, отдельные tactical interpretation/recommended response/avoid,
подтверждённый corpus manifest и полный evidence drill-down до match/round/tick/map/
timeline. Фильтры не пересчитывают статистику. Если corpus gate не пройден, UI явно
показывает `blocked`, а не маскирует результат под готовую рекомендацию. Контракт:
[SCOUTING_REPORT_UI.md](SCOUTING_REPORT_UI.md).

UI table: `/ui/spatial/MATCH_ID`; JSON: `/api/spatial/{match_id}/summary`,
`/api/spatial/{match_id}/snapshots` и `/api/spatial/{match_id}/validation`. Таблица
показывает только ticks, игроков, raw coordinates, view angles, alive/C4/team/side и
availability. Эта foundation-таблица не строит карты или выводы; отдельный Stage 7.1
explorer описан ниже. Нормативная модель, audit
`demoparser2==0.41.4` и ограничения описаны в [SPATIAL_MODEL.md](SPATIAL_MODEL.md).

### Spatial explorer Stage 7.1

Explorer выбирает последний совместимый Spatial schema `1.0.0` / rule `1.1.0` run,
показывает official local overview, игроков, view direction, подтверждённого C4 carrier и
обычные event markers. Tick не округляется и не переводится в seconds. Player path
соединяет только сохранённые reliable alive samples и прямо предупреждает, что линия не
доказывает точный маршрут.

Official overview нужно извлечь из собственной локальной установки CS2 проверенным
Source2Viewer CLI `19.2.6339+c72208352f5bf62f1482447ed166c548f303f8fa`:

```powershell
python .\scripts\install_map_overview.py de_ancient `
  --cs2-root "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive" `
  --vrf-cli "C:\path\to\Source2Viewer-CLI.exe"
```

Локальный запуск из корня проекта:

```powershell
$env:STRATWEB_DUCKDB_PATH = ".\data\stratweb.duckdb"
$env:STRATWEB_MAP_OVERVIEW_DIR = ".\data\map_overviews"
python -m uvicorn stratweb.main:app --host 127.0.0.1 --port 8000
```

Открыть:

```text
http://127.0.0.1:8000/ui/spatial/MATCH_ID/rounds/1
```

JSON endpoints покрывают ticks, exact tick/map/team snapshot, player/round path и nearest
players. Temporal timeline и map связаны в обе стороны одним `temporal_run_id` и tick.
Migrations `008`–`012` создают indexed query read-models; реальные exact-tick и player
path планы используют DuckDB `Index Scan`. Полный контракт и ограничения находятся в
[SPATIAL_QUERY_MODEL.md](SPATIAL_QUERY_MODEL.md).

### Product UI and buffered playback Stage 7.2

Главная страница `http://127.0.0.1:8000/ui` теперь показывает library сохранённых
матчей, поэтому UUID вручную вводить не нужно. Match overview объединяет rounds,
players, observed event counts и data health; fingerprints, run IDs и JSON links вынесены
в Diagnostics.

Spatial viewer загружает authoritative samples пакетами по 64, заранее подкачивает
следующий chunk и рисует visual frames через `requestAnimationFrame`. `Smooth` выполняет
только client-side interpolation между двумя безопасными stored samples; `Exact` её
полностью выключает. Evidence API никогда не возвращает интерполированную позицию:

```text
GET /api/spatial/{match_id}/rounds/{round}/playback?from_index=0&limit=64&run_id=...
```

Кнопки Previous/Next, scrubber release, event jumps и Temporal navigation всегда
останавливаются на exact stored sample. Скорости являются playback policy, а не заявлением
о physical match time. Полная state machine, eligibility rules и profiling counters
описаны в [PLAYBACK_ARCHITECTURE.md](PLAYBACK_ARCHITECTURE.md).

Match library также принимает завершённый `.dem` только с localhost. Upload проверяет
extension, размер и CS2 signature, сохраняет UUID internal filename и запускает существующий
canonical → analytics → Temporal → Spatial pipeline одним локальным background worker.

Результаты browser profiling, screenshots, FACEIT manual acceptance и финальных quality
gates собраны в [STAGE_7_2_ACCEPTANCE.md](STAGE_7_2_ACCEPTANCE.md).

### Temporal simultaneous groups

Temporal schema/rule `1.1.0` keeps unknown same-tick physical order separate from a
deterministic post-group state. Query the result with:

```powershell
stratweb temporal show MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb temporal groups MATCH_ID --db .\data\stratweb.duckdb --pretty
stratweb temporal groups MATCH_ID --round 10 --db .\data\stratweb.duckdb --pretty
stratweb temporal group MATCH_ID GROUP_ID --db .\data\stratweb.duckdb --pretty
```

At a grouped tick, `temporal snapshot` returns the state after the whole group.
Per-event snapshots inside an ambiguous group are explicitly ambiguous. Victimless
death events are retained with `death_effect_status=unavailable` and never change life
state.

### Temporal inspection UI

Timeline визуально объединяет state-affecting события одного tick. Группа показывает
tick, event count, ordering/intermediate/final statuses, участников, причины
неоднозначности, pre/post state и множество возможных intermediate states. Вертикальный
порядок элементов не трактуется как физический порядок. Snapshot в tick всегда означает
post-group state; before/after отдельного события внутри ambiguous group возвращает typed
`ambiguous`, а deterministic post-group state не заражает последующие snapshots.

Victimless death остаётся evidence как `world/unknown-victim death`, не прикрепляется к
игроку, имеет `death_effect_status=unavailable`, не меняет alive count и ведёт в
diagnostics. Diagnostics раздельно перечисляет simultaneous, ambiguous-order,
ambiguous-intermediate, ambiguous-final, conflicting groups и deaths without victim;
каждый counter открывает конкретные раунды и события.

### Multi-map pack Stage 7.3

Spatial schema `1.1.0` / rule `1.2.0` supports exact, typed definitions for Mirage,
Nuke, Ancient, Anubis, Dust II, Inferno, Cache, and Overpass. The registry uses explicit
aliases and revision evidence; an unknown map or incompatible historical revision never
falls back to another/current radar. Every new Spatial run pins its definition
fingerprint, revision, overview checksum, and transform rule. Older runs remain visibly
`legacy_map_semantics` until recomputed.

Official overviews are extracted locally from the user's CS2 installation and are not
committed. Install them as described in [MAP_ASSETS.md](MAP_ASSETS.md), then run:

```powershell
$env:STRATWEB_DUCKDB_PATH = ".\data\stratweb.duckdb"
$env:STRATWEB_MAP_OVERVIEW_DIR = ".\data\map_overviews"
python -m uvicorn stratweb.main:app --host 127.0.0.1 --port 8000
```

Map metadata is available at `GET /api/maps`; a match's pinned map contract is available
at `GET /api/spatial/{match_id}/map`. Nuke provides automatic Z-based upper/lower
selection, explicit level selection, and a diagnostic two-layer overlay. Out-of-bounds
coordinates are warned and never clamped.

For the non-persistent developer workbench set
`STRATWEB_MAP_DEVELOPER_MODE=true` and open `/ui/maps/calibration`. Ordinary product pages
do not expose origins, scales, hashes, or filesystem details. See
[MAP_MODEL.md](MAP_MODEL.md), [MAP_CALIBRATION.md](MAP_CALIBRATION.md), and the honest
[MAP_FIXTURE_MATRIX.md](MAP_FIXTURE_MATRIX.md) for contracts and validation coverage.

The reproducible gate output, real FACEIT run, screenshots, and critical review are in
[STAGE_7_3_ACCEPTANCE.md](STAGE_7_3_ACCEPTANCE.md).

Stage 7.3 adds no zones, named locations, heatmaps, tactical interpretation, coaching, or
AI analysis. Stage 8 has not started.

### Stage 7.4 playback and projectile layer

Current Spatial schema/rule is `1.2.0` / `1.3.0`; playback API schema is `1.2.0`.
The viewer uses a fetch-independent frame clock, early chunk prefetch, explicit Buffering,
gap-aware player interpolation, rejected-coordinate diagnostics, collision-aware labels, and
separate projectile/effect/event layers.

Projectile extraction is pinned to the real `demoparser2==0.41.4` contracts and requests only
`Grenade.m_nBounces` and `Grenade.m_vInitialVelocity` plus a fixed lifecycle event list. Stored
trails contain parser samples only. Initial velocity is not treated as per-tick velocity; missing
trajectory and effect radius are never simulated. Old Spatial runs remain readable with explicit
legacy/unavailable projectile capability.

```powershell
.\.venv\Scripts\python.exe scripts\audit_playback.py <match-id> 1 `
  --db .stage7-manual\faceit-spatial.duckdb
```

Normative details: [PLAYBACK_MODEL.md](PLAYBACK_MODEL.md),
[PROJECTILE_MODEL.md](PROJECTILE_MODEL.md),
[PROJECTILE_PARSER_AUDIT.md](PROJECTILE_PARSER_AUDIT.md), and
[UTILITY_RENDERING.md](UTILITY_RENDERING.md). Stage 8 and all tactical/zone/coaching/AI work remain
out of scope.

### Stage 7.5 map-first multi-layer viewer

After the first Stage 7.5 submission failed manual testing, the shared moving SVG was
replaced with isolated HTML compositor layers for players, projectiles, effects,
events, labels, and selection. Projectile trails use one exact-evidence canvas.
Fixed slot pools are created before playback, so the validated mass-fight run adds
and removes zero DOM nodes.

The compact sidebar contains only Round, Team, Player, Utility, Jump, and Playback.
Technical sample state, buffers, capabilities, run IDs, and counters are visible only
in Diagnostics. The square evidence map consumes all available vertical space without
distortion and uses a static dimmed backdrop for residual widescreen space.

A full Chrome trace on the real FACEIT round 10 reduced Paint from 2,704 to 64 ms,
RasterTask from 361 to 13 ms, Layout from 364 to 58 ms, and document nodes from
1,620 to 665. The final transform cadence is 60.2 FPS with p99 18.2 ms, no interval
above 34 ms, no buffering, and no console error. The superseding RCA, trace method,
screenshots, video, limitations, and manual-retest status are in
[STAGE_7_5_ACCEPTANCE.md](STAGE_7_5_ACCEPTANCE.md). Evidence contracts are unchanged,
and Stage 8 has not started.

### Stage 7.6 density-independent playback and stable labels

Stage 7.6 corrects a presentation-clock defect that was still visible during dense
firefights and utility usage. Playback no longer assigns a minimum duration to every
stored sample. An absolute monotonic playhead advances over relative demo ticks at the
explicit presentation rate of 64 ticks/s (`15.625 ms/tick`) and can cross several
authoritative samples in one browser frame. This rate is a UI policy, **not** a detected
or canonical demo tickrate. Event-heavy intervals therefore do not become slower merely
because shots, damage or utility add more stored samples.

Prefetch is based on buffered playback time and selected speed. A real underrun freezes
the playhead and resumes it from the same tick after data arrives. Exact/far navigation
invalidates stale prefetch, while Back/Forward with changed filters clears the old buffer
before loading the restored filter generation. Projectile trails use cached evidence-only
segment plans rather than rescanning complete histories on each frame.

Rendering now follows every callback delivered by `requestAnimationFrame`; there is no
manual 15-ms frame gate that can alias a 75-Hz display down to 37.5 updates/s or a 144-Hz
display down to 48 updates/s. Exact events crossed between two callbacks enter a bounded
120-ms wall-time presentation buffer backed by 32 preallocated map-marker slots. This
keeps short combat evidence visible without delaying the demo-tick clock and without
claiming a physical order for events sharing one tick.

Playback API `1.2.0` publishes its clock metadata, returns players only inside
`samples[].players` and events only inside `samples[].events`, and removes the old
top-level duplicate collections. FastAPI gzip compression is enabled for large responses.
The evidence boundary is unchanged: interpolation remains browser-only and cannot become
stored or API evidence.

Nickname anchors are planned once from the full persisted roster and remain attached to
the participant across movement, death, C4 state, filters and zoom. The labels still move
with their players, but no longer choose a different side of the marker from sample to
sample. Diagnostics expose crossed-sample catch-up, maximum samples crossed per frame,
label-plan builds and unexpected anchor changes.

On the real FACEIT round-10 fight at ticks `67391–68093`, the 1× wall time changed from
`21.114 s` to approximately `11.005 s` (presentation target `10.969 s`); 4× completed in
approximately `2.813 s`. The earlier audit found 132 anchor changes and 74 left/right
flips; the corrected run recorded zero. A final complete round-10 run at 4× reached all
617 boundaries in `26.266 s` against a `26.250 s` target. All 214 unique renderable event
links were observed, with a peak of 25 simultaneous transient markers, zero buffering,
anchor flips, long tasks or browser errors, a 24.9-ms maximum rAF interval and a 1.20-ms
maximum renderer duration. Full RCA, measurements, limitations and the manual acceptance
checklist are in
[STAGE_7_6_ACCEPTANCE.md](STAGE_7_6_ACCEPTANCE.md).

Stage 7.6 is a corrective playback/viewer stage only. Stage 8, tactical inference,
zones, coaching, recommendations and AI have not started.

### Stage 8.0 correctness and import reliability

Round cards now keep a stable physical-team score order across side switches and name
the winning physical team plus its observed T/CT side. This changes presentation only;
canonical side-oriented score evidence is unchanged.

Upload jobs are durable DuckDB records. The match library shows recent imports, the job
page shows checkpoint progress and attempt count, and a server restart converts an
unfinished job into an explicit retryable `import_interrupted` state when its safe
UUID-named upload is still present. Retry remains localhost-only and reruns the
idempotent canonical → analytics → Temporal → Spatial pipeline.

Stage 8.0 does not add opponent identity, zones, pattern inference, recommendations,
reports or LLM behavior.

### Stage 8.1 opponent workspaces

Open `http://127.0.0.1:8000/ui/opponents`, create a named opponent workspace, and
explicitly confirm which physical team represents the opponent in each imported match.
The profile name is independent from demo labels such as `TeamAlpha`.

After the first confirmation, remaining match teams show advisory Steam ID overlap.
Strong overlap still does not auto-select a team. Players merge across matches only by
Steam ID; missing IDs remain separate occurrences even when their nicknames match.
The roster distinguishes core, partial/substitute and unresolved identities.

JSON endpoints:

```text
GET  /api/opponents
GET  /api/opponents/{profile_id}
POST /api/opponents
POST /api/opponents/{profile_id}/matches
POST /api/opponents/{profile_id}/matches/{match_id}/remove
```

The contract is documented in [OPPONENT_MODEL.md](OPPONENT_MODEL.md). Stage 8.1 does
not add zones, tactical patterns, findings, recommendations, reports or LLM behavior.

### Stage 8.8.1a visual foundation

All server-rendered pages now share a versioned visual foundation for typography,
semantic colors, surfaces, controls, tables, statuses, focus and responsive behavior.
Open `http://127.0.0.1:8000/ui/style-guide` to inspect the component reference. The
contract and extension rules are documented in [UI_DESIGN_SYSTEM.md](UI_DESIGN_SYSTEM.md).
This presentation-only stage does not change evidence or analytics.

Stage 8.8.1b adds a two-level application shell. Product navigation and current-match
tools no longer compete in one crowded row, the active destination is visible, and the
match navigation remains usable on narrow screens.

Stage 8.8.1c gives diagnostics, economy and scouting reports a product-first reading
order: summary and warnings first, supporting details next, raw runs and JSON exports
on demand. No evidence or deterministic calculation is hidden or changed.

Stage 8.8.3 completes the Russian presentation pass for the main analytical workflow:
round facts, 2D playback, temporal timelines and evidence-first opponent reports. Raw
codes and identifiers remain available in diagnostics, while stored calculations and
evidence are unchanged. See [STAGE_8_8_3.md](STAGE_8_8_3.md).

Stage 8.8.4 upgrades the shared visual contract to 1.1.0 and finishes the product-wide
polish pass. Reports, cards, filters, tables and technical disclosures now remain readable
on narrow screens; keyboard focus, long-value wrapping and reduced-motion behavior are
consistent across the application. This stage changes presentation only. See
[STAGE_8_8_4.md](STAGE_8_8_4.md).

### Stage 8.9 evidence report export

The opponent report now exports one complete pinned source bundle in three formats:
stable JSON, printable HTML and a generated PDF. Export does not apply screen filters or
pagination and does not recalculate findings. It includes persisted run dates, every rule
version, the demo manifest with original names and SHA-256 values, quality checks, sample
limitations, findings, recommendations and the complete evidence denominator.

Open an opponent report and expand the reproducibility section, or use:

```text
GET /api/opponents/{profile_id}/report/export.json?run_id={strategy_run_id}
GET /ui/opponents/{profile_id}/report/print?run_id={strategy_run_id}
GET /api/opponents/{profile_id}/report/export.pdf?run_id={strategy_run_id}
```

The generated attachment name uses internal UUIDs rather than the original demo or opponent
name. JSON and PDF responses expose the same export fingerprint through `ETag`. See
[REPORT_EXPORT.md](REPORT_EXPORT.md).

### Stage 9.1 Golden Corpus

Golden Corpus metadata is stored in `corpus/golden-corpus-v1.json`; raw demos stay outside
Git and are addressed only as `<sha256>.dem`. Validate the manifest without pretending that
the current candidate inventory is production-ready:

```powershell
uv run --frozen stratweb corpus validate --manifest corpus/golden-corpus-v1.json --pretty
```

Use `--demo-root <external-directory>` for byte-level file verification and
`--require-ready` only in a real-corpus acceptance job. The current manifest is expected to
report `blocked`: five FACEIT candidates exist, but no target opponent or analyst finding
labels have been confirmed and the 20-match minimum has not been met. See
[corpus/README.md](corpus/README.md) for the review workflow.

### Stage 9.2a read-only storage audit

Inspect DuckDB growth, table blocks, mirrored payload and representative query timings
without modifying the database:

```powershell
uv run --frozen stratweb storage audit `
  --db C:\Users\<user>\StratWeb-data\faceit-spatial.duckdb `
  --output .runtime\storage-audit.json `
  --pretty
```

The current five-match database proves complete JSON duplication in the Spatial and bomb
lookup mirrors. Stage 9.2a only measured the problem. See [STAGE_9_2A.md](STAGE_9_2A.md).

### Stage 9.2b Storage Engine V2

Inspect the active layout without changing the database:

```powershell
uv run --frozen stratweb storage status --db <database.duckdb> --pretty
```

The explicit migration command creates and verifies a full backup before installing canonical
lookup indexes. It activates V2 only when every key resolves and the measured query latency
stays inside the configured budget:

```powershell
uv run --frozen stratweb storage migrate-v2 `
  --db <database.duckdb> `
  --backup <new-backup.duckdb> `
  --output .runtime\storage-migration.json `
  --pretty --yes
```

V2 reads payload from `spatial_snapshots` and `bomb_position_snapshots` directly. New runs do
not write a second payload mirror. Existing mirrors remain available for verified rollback:

```powershell
uv run --frozen stratweb storage rollback-v1 --db <database.duckdb> --pretty --yes
```

A backup can be restore-tested only into a new destination; existing files are refused:

```powershell
uv run --frozen stratweb storage restore-backup `
  --backup <backup.duckdb> `
  --destination <new-restored.duckdb> `
  --pretty --yes
```

No existing mirror is dropped and no disk reclamation occurs in this stage. See
[STAGE_9_2B.md](STAGE_9_2B.md).
