# План реализации StratWeb

Документ описывает последовательность разработки. Наличие будущего шага в плане не
означает, что он уже реализован. Переход к следующему этапу возможен только после
явного подтверждения заказчика.

## Принципы выполнения

- Каждая вертикаль заканчивается тестируемым artifact-ом.
- Реальный parser API проверяется на зафиксированной версии до написания mapping.
- Новое поле появляется сначала в canonical contract/schema, затем в adapter-е.
- Ошибка одной демки не должна ломать batch или повреждать существующую БД.
- Ни один аналитический вывод не выпускается без evidence.
- Не добавлять frontend, LLM, heatmaps и сложное tactic recognition до прохождения
  базового parsing/normalization corpus.

## Этап 1 — фундамент (принят)

Статус: принят пользователем.

- [x] Сравнить Awpy 2.0.2 и demoparser2 0.41.4.
- [x] Выбрать demoparser2 и изолировать его портом.
- [x] Зафиксировать direct dependency versions.
- [x] Описать модульный монолит и поток `.dem -> evidence report`.
- [x] Создать parser-independent Pydantic entities.
- [x] Создать DTO и Protocol interfaces.
- [x] Создать FastAPI import scaffold и smoke-test.
- [x] Создать базовые Docker/env/Make configuration.
- [x] Получить явное подтверждение перехода к этапу 2.

## Этап 2 — local parser inspection и fixture workflow (принят)

Цель: предоставить read-only CLI inspection для одного локального файла и доказать
возможности `demoparser2==0.41.4` до canonical mapping/DuckDB/analytics.

Реализованный объём: production adapter, typed errors, compact JSON schema `1.1.0`,
fake-based unit tests и opt-in integration test через `STRATWEB_TEST_DEMO`. Реальный
support matrix всё ещё требует локального corpus.

- [x] Проверить сигнатуры установленного demoparser2 0.41.4.
- [x] Реализовать batch event extraction с per-event fallback.
- [x] Добавить header/event/player inspection без `parse_ticks`.
- [x] Добавить versioned Pydantic JSON и CLI `stratweb inspect`.
- [x] Добавить typed errors и контролируемые exit codes.
- [x] Добавить fake-based unit tests и opt-in integration test.
- [x] Подтвердить отсутствие imports demoparser2 во внутренних слоях.
- [x] Не считать `round_start`/`round_end` обязательными и добавить canonical lifecycle aliases.
- [x] Оценивать round count через глобальный `MAX(total_rounds_played)` с lifecycle fallback.
- [x] Проверить integration test на пользовательской демке через `STRATWEB_TEST_DEMO`.

1. Подготовить небольшой легальный corpus без хранения больших/чужих `.dem` в Git:
   Valve matchmaking/Premier, FACEIT/HLTV SourceTV и, при необходимости, POV.
2. Для каждого fixture сохранить sidecar metadata: SHA-256, source type, map,
   ожидаемые teams/round count, known edge cases и право использования.
3. Создать локальную command для диагностического вызова:
   - `parse_header()`;
   - `list_game_events()` и `list_updated_fields()`;
   - `parse_event`/`parse_events` для round, kill, damage, shot, bomb, smoke/inferno;
   - `parse_ticks` для Steam ID/team/position/economy fields;
   - `parse_grenades` для trajectory data.
4. Снять фактические columns/dtypes/nullability для каждого source type.
5. Проверить semantics `tick`, `game_time`, tick rate, team number, Steam IDs и
   coordinates сравнением с просмотром demo/scoreboard.
6. Зафиксировать parser contract tests и sanitized schema snapshots, не коммитя сами
   большие demos без отдельного решения.
7. Проверить wheels/install на Python 3.11 Linux container и Windows development.
8. Создать lockfile для полного dependency graph.

Критерий выхода: нет предположений об именах mandatory events/columns; существует
матрица поддержки source types и осознанный список unsupported/missing fields.

## Этап 3 — Canonical Match Dataset (принят)

Цель: детерминированно преобразовать `ParsedDemo` в публичный canonical contract до
начала хранения или аналитики.

- [x] Создать Pydantic `CanonicalMatchDataset` schema `1.0.0` без DataFrame в output.
- [x] Сохранить inspection JSON `1.1.0` отдельным облегчённым use case.
- [x] Реализовать FACEIT/Valve-like round aliases, marker deduplication и precedence.
- [x] Использовать глобальный `MAX(total_rounds_played)` и сохранять count candidates.
- [x] Добавить explicit terminal fallback при missing final official end.
- [x] Реализовать event-driven overtime detection через `announce_phase_end`.
- [x] Реализовать единый `RoundAssignmentService` и event phases.
- [x] Реализовать Steam-ID-first player resolution, rename/reconnect warnings.
- [x] Разделить physical team identity и per-tick/per-round T/CT side.
- [x] Нормализовать kill, damage, shot, grenade и bomb events без `parse_ticks`.
- [x] Добавить UUIDv5 IDs, config hash, dataset fingerprint и stable ordering.
- [x] Добавить независимый validation report и определить fatal rules.
- [x] Добавить `stratweb normalize` и `--summary-only`.
- [x] Добавить synthetic unit tests и opt-in FACEIT integration test.
- [x] Не начинать DuckDB, API, аналитику, LLM, frontend или tactic recognition.

Критерий выхода: текущая FACEIT fixture даёт 30 canonical rounds, 10 игроков, две
physical teams, назначенные gameplay events, zero fatal validation errors и одинаковый
fingerprint при двух прогонах.

## Этап 4 — DuckDB Persistence Layer (принят условно)

Цель: атомарно сохранять принятый `CanonicalMatchDataset 1.0.0` и предоставить
простые read-only запросы без аналитики и без утечки DuckDB types во внутренние слои.

- [x] Добавить application port `MatchRepository`; domain/application не импортируют
  `duckdb`.
- [x] Реализовать `DuckDBMatchRepository` с connection context managers и логически
  read-only query methods. Все in-process соединения используют одинаковую
  `read_only=False` конфигурацию DuckDB, чтобы UI-запросы не падали во время открытой
  import transaction; права на запись не выставляются через UI/API.
- [x] Создать migration history `schema_migrations` с version/name/time/SHA-256.
- [x] Применять каждую migration один раз и транзакционно; отклонять checksum mismatch
  и неизвестную migration version.
- [x] Создать normalized canonical tables для match, teams, players, memberships,
  rounds, gameplay events, validation и normalization provenance.
- [x] Добавить PK/UNIQUE/CHECK и query-oriented indexes; из-за DuckDB FK delete
  limitation проверять references до и после insert application/SQL checks.
- [x] Реализовать Polars batch insert, обязательный unregister временных relations и
  одну transaction на dataset.
- [x] Реализовать fingerprint dedup (`already_exists`) и atomic `--force` replace.
- [x] Повторно проверять schema/fingerprint/fatal validation/counts/references до DB.
- [x] Поддержать validated canonical JSON import без доверия embedded summaries.
- [x] Реализовать `MatchQueryService`: list/filter/get/summary/players/rounds/events,
  player kills/grenades, validation issues и counts.
- [x] Реализовать CLI `db init`, `import`, `matches`, `rounds`, confirmation delete и
  приоритет `--db > STRATWEB_DUCKDB_PATH/.env > default`.
- [x] Не сохранять raw parser payload и полный source path; игнорировать local
  `.dem`/JSON/DB/WAL/tmp/backup artifacts в Git.
- [x] Добавить synthetic unit tests и opt-in exact FACEIT persistence integration.
- [x] Не добавлять frontend, FastAPI persistence endpoints, LLM, tactics, analytics,
  heatmaps или `parse_ticks`.

Критерий выхода: migration idempotent/checksummed; импорт одной demo не оставляет
частичных строк; duplicate/replace воспроизводимы; query/delete не оставляют orphan;
реальная FACEIT fixture сохраняет точные canonical counts. Переход к этапу 5 только
после явной приёмки.

## Этап 4.5 — Result Availability Hardening (реализован)

Цель: не позволить будущей аналитике перепутать отсутствие result с
проигрышем, `UNKNOWN` или 0%, не начиная сами метрики.

- [x] Провести source audit реальной FACEIT demo через проверенные
  `demoparser2==0.41.4` API и `list_updated_fields()`.
- [x] Подключить прямые winner/reason/team-score netvars для outcome events; не
  использовать kill/alive/plant/team-order/round-count как winner-эвристику.
- [x] Перейти на `CanonicalMatchDataset 1.1.0`; добавить typed per-round
  `outcome_status/source`, `score_status/source`, `end_reason_status/source` и nullable winner.
- [x] Добавить typed match-level `result_capabilities` с source/field provenance и counts.
- [x] Добавить не более одной aggregate validation issue на result capability.
- [x] Реализовать conservative deterministic JSON upgrade 1.0.0 → 1.1.0 и явно
  отклонять иные versions.
- [x] Добавить transactional migration `002 round_result_availability` через table
  rebuild; не менять checksum migration 001 и не терять match/event rows.
- [x] Обновить repository mapping и CLI `matches show`, `rounds list/show`.
- [x] Добавить `evaluate_result_use_policy()` для winner/score eligibility без
  реализации win-based metrics.
- [x] Покрыть authoritative/missing/conflict/partial сценарии, fingerprint,
  JSON upgrade/import, corrupt metadata, migration, CLI и opt-in FACEIT integration.
- [x] Сохранить raw parser payload вне canonical JSON/DuckDB и не вызывать
  `parse_ticks`.
- [x] Не начинать Stage 5, gameplay analytics, FastAPI endpoints, frontend или LLM.

Критерий выхода: FACEIT fixture имеет 30/30 winner, score и end reason
available из прямых source fields, zero fatal validation; при другом source
unavailable остаётся явным и блокирует dependent consumers.

## Этап 5 — Gameplay Analytics Engine V1 (реализован)

Цель: детерминированные parser-independent gameplay metrics поверх typed canonical
1.1.0 и repository ports, без tactics/economy/clutch/positions.

- [x] Провести audit canonical damage, participation, bomb и tickrate fields на
  реальной FACEIT demo; зафиксировать effective damage и запрет silent 64 tick.
- [x] До кода формализовать valid kill, opening, trade/opportunity, survival, KAST,
  multikill, advantage, bomb, denominator/null и availability semantics в
  `ANALYTICS_DEFINITIONS.md`.
- [x] Добавить typed immutable `MatchAnalyticsInput`, player/team round/match records,
  opening/trade/alive timeline, config, availability, summary и validation issues.
- [x] Реализовать pure `AnalyticsEngine` без DuckDB, demoparser2, clocks, network, LLM
  и unordered iteration.
- [x] Считать enemy/team/effective damage, ADR, K/D/KPR/DPR/APR, headshots, survival,
  KAST, direct trades, multikills, opening и winner conversions.
- [x] Считать first/+2 man advantage только при равном доказанном initial lineup;
  сохранять transitions для enemy/teamkill/suicide/world/repeated death.
- [x] Реализовать event-based plant/defuse/explosion и conservative bomb capability;
  не нормализовать неизвестный site code в A/B.
- [x] Добавить независимый `AnalyticsValidator`; structural contradictions fatal,
  partial coverage — warning/capability.
- [x] Добавить отдельный `AnalyticsRepository` port и DuckDB migration `003` с
  normalized queryable analytics tables, uniqueness и indexes.
- [x] Реализовать transactional idempotent save/replace/delete analytics отдельно от
  canonical match и query после нового connection.
- [x] Добавить `ComputeMatchAnalyticsService` и read-only `AnalyticsQueryService`.
- [x] Добавить JSON CLI `analytics compute/show/players/player/teams/round/openings/
  trades/advantage`; tickrate или tick window задаются явно.
- [x] Покрыть opening/trade/KAST/multikill/survival/advantage/bomb/aggregation/
  fingerprint unit tests, persistence/CLI tests и opt-in FACEIT integration.
- [x] Проверить на FACEIT: 30 rounds, 10 players, canonical valid kill reconciliation,
  overtime, winner capability, queries, repeat `already_exists`, delete analytics при
  сохранении canonical match.
- [x] Не реализовывать Stage 6, FastAPI analytics endpoints, frontend, report/LLM,
  economy, clutch, positions, zones, pathing или tactical pattern detection.

Критерий выхода: одинаковые canonical fingerprint/config дают одинаковые ordered
records и analytics fingerprint; unavailable не становится 0%; migration сохраняет
canonical data; реальная demo проходит полный offline round-trip.

## Этап 5.1 — Trade Window Semantics Hardening (реализован)

- [x] Ввести typed `ticks|seconds` policy и default 320 ticks без ложного duration.
- [x] Требовать proven canonical tickrate для seconds mode; не принимать user-supplied
  tickrate как evidence и не предполагать 64 tick/s.
- [x] Формализовать deterministic round-half-up conversion и включить resolved policy
  в config hash/fingerprint; повысить analytics schema/rule до 1.1.0.
- [x] Сделать `seconds_delta` nullable с explicit conversion status/source; отразить
  tick policy в trade и KAST availability metadata.
- [x] Добавить migration 004 с физическими policy fields и безопасной маркировкой
  прежних runs/events как `legacy_ambiguous` без их пересчёта.
- [x] Обновить CLI contract, persistence round-trip, unit/migration/CLI/integration tests
  и нормативную документацию.
- [x] Не начинать Stage 6.

## Этап 6 — Temporal Round State Engine (реализован)

Цель: построить deterministic parser-independent временную модель каждого canonical
раунда без позиций, зон, tactics и предположений о tickrate.

- [x] До реализации зафиксировать normative [TEMPORAL_MODEL.md](TEMPORAL_MODEL.md):
  authoritative ticks, optional seconds, event priority, ambiguity, phase, participant,
  life/bomb state, snapshot, availability, validation и fingerprint semantics.
- [x] Добавить immutable typed contracts и pure modules `temporal/` без parser, DuckDB,
  CLI, network, clocks, LLM и raw payload dependencies.
- [x] Реализовать cross-family ordering `(round, tick, priority, stable event_id)`;
  конфликтный same-tick state не скрывать priority, а маркировать simultaneous group.
- [x] Строить полуоткрытые phase intervals из canonical boundaries, явно сохранять
  fallback end и partial/unresolved при недостающем source.
- [x] Определять per-round participants, physical team и side по membership/event
  evidence; не предполагать 10 игроков/5v5 и не считать неподтверждённого игрока alive.
- [x] Реализовать deterministic alive machine для enemy/teamkill/suicide/world/repeated
  death и исключить out-of-range death из final state.
- [x] Реализовать conservative bomb machine только для plant/defuse/explode; не
  синтезировать carried/dropped/defusing или A/B mapping.
- [x] Добавить replayed snapshots at tick/before/after/final с tick/nullable seconds,
  alive counts по side/physical team, availability и ambiguity flags.
- [x] Добавить independent temporal validation и optional Stage 5 opening/death-stream
  cross-check без использования analytics как source of truth.
- [x] Добавить `TemporalRepository`, migration `005 temporal_round_state`, normalized
  queryable tables и atomic idempotent save/replace/delete с сохранением canonical/
  analytics runs.
- [x] Добавить `ComputeTemporalStateService`, `TemporalQueryService` и JSON-first CLI
  `temporal compute/show/round/events/transitions/participants/snapshot/before-event/
  after-event/final/bomb/delete`.
- [x] Покрыть ordering/phases/participants/life/bomb/snapshots/time/validation/
  fingerprint, persistence, migration, CLI и opt-in FACEIT integration tests.
- [x] Не реализовывать positions, coordinates, zones, movement/utility paths, visibility,
  heatmaps, economy, tactics, reports, LLM, frontend или FastAPI temporal endpoints.

Критерий выхода: одинаковый canonical fingerprint/config даёт одинаковые immutable
timelines/fingerprint; seconds не появляются без tickrate evidence; uncertainty не
маскируется; Stage 5 cross-check проходит; migration/query/reopen/delete воспроизводимы;
реальная FACEIT fixture даёт 30 timelines и fallback final round. Переход к Stage 7 —
только после явной приёмки.

## Отложено — безопасная загрузка и job lifecycle

Этот поток не входит в этап 5 и потребует отдельного явного согласования: streaming
storage, upload catalog/status, API endpoints, serialized writes и security tests.

## Реализовано в этапе 2 — demoparser2 adapter

1. Реализовать только `adapters/parsers/demoparser2.py` как место импорта SDK.
2. Runtime-проверкой сверять установленную версию с `0.41.4`; mismatch — fatal
   configuration error, а не warning.
3. Реализовать `ParseRequest -> ParsedDemo`, используя проверенные stage-2 columns.
4. Немедленно конвертировать parser output в Polars и освободить pandas frames.
5. Записывать parser identity/warnings/elapsed metrics без source data в logs.
6. Ввести stable exception taxonomy: corrupt, unsupported protocol, missing mandatory
   event, resource limit, internal parser failure.
7. Запретить fallback на другой parser без явной configuration/version provenance.

Критерий выхода: adapter проходит contract tests на corpus и падение одного fixture
не прерывает обработку остальных.

## Будущее расширение canonical schema после этапа 3

Рекомендуемый порядок mapping:

1. Header, Match, Team, Player.
2. Round boundaries и per-round side assignments, включая overtime.
3. Kill/Damage/Shot/BombEvent.
4. Grenade/Smoke/Inferno lifecycles.
5. PlayerRound economy/stats.
6. Sparse PositionSample по configurable interval.

Для каждого mapping:

- определить raw columns, canonical units и null policy;
- не подменять missing значением `0`/`UNKNOWN`, если это меняет смысл;
- проверить round join по tick boundaries;
- присвоить `is_warmup`, `is_complete`, `exclusion_reason`;
- валидировать Pydantic/Polars schema;
- добавить golden expected rows и edge-case tests;
- увеличить schema version при semantic change.

Критерий выхода: одна demo атомарно превращается в согласованные canonical tables;
каждый event имеет match/round/tick и actor context настолько полно, насколько это
подтверждено source data.

## Отложено — AnalysisDataset и analysis provenance (заменено Stage 8.6)

> Раздел сохранён как история. Актуальная детализация — в
> [Stage 8.6 — Analysis Run, Finding and Evidence Persistence](#stage-86--analysis-run-finding-and-evidence-persistence-реализован).

1. Спроектировать immutable `AnalysisDataset` snapshot поверх сохранённых canonical
   rows, явно исключая warmup/incomplete/unassigned data.
2. Добавить отдельные migrations для analysis runs/findings/evidence, не изменяя
   применённую migration `001`.
3. Версионировать scope/config/rules и snapshot fingerprint.
4. Сохранять analysis run, findings и evidence одной transaction.
5. Добавить integrity tests для orphan evidence и воспроизводимости snapshot.

Критерий выхода: snapshot объясняет exclusions и повторяется для одинаковых
canonical fingerprints/config; этот этап не начат в рамках текущего задания.

## Отложено после Stage 7 — детерминированные tactical rules (заменено Stage 8.2–8.7)

> Раздел сохранён как история. Актуальная детализация — в Stage 8.2 (zones),
> 8.3 (economy), 8.4 (per-round features), 8.5 (cross-match patterns) и
> 8.7 (counter-strategy rules) ниже.

Начать с простых проверяемых patterns, а не «распознавания тактик»:

1. Частота открытия bombsite/зоны по side и временным окнам.
2. Повторяемое использование конкретных grenade types/areas.
3. First-death/first-damage exposure по player/side/area.
4. Late-round player positioning и save tendency при чёткой eligibility definition.
5. Bomb plant site/timing frequencies.

Для каждого rule создать specification:

- eligibility/denominator;
- numerator;
- map/side scope;
- minimum independent matches;
- deterministic confidence formula;
- evidence selection и stable ordering;
- allowed language for observation/implication/recommendation;
- confounders и limitations;
- unit/golden/property tests.

Finding ID и evidence IDs строить детерминированно. Rule не должен обращаться к
текущему времени, network, LLM или mutable database cursor.

Критерий выхода: повторный запуск на том же fingerprint/config даёт одинаковые
content fields и evidence; малые выборки явно предупреждаются.

## Отложено после Stage 7 — отчёт и API анализа (заменено Stage 8.8–8.9)

> Раздел сохранён как история. Актуальная детализация — в Stage 8.8 (Scouting
> Report UI) и Stage 8.9 (Report Export) ниже.

1. Реализовать JSON и Markdown renderer-ы.
2. В отчёте группировать findings по map/side/category, сохраняя отдельные sections
   observation, implication, response, avoid, limitations.
3. Показывать numerator/denominator/frequency/confidence method и sample warning.
4. Для evidence показывать source filename как display metadata, SHA prefix, match,
   round и ticks.
5. Добавить endpoint создания analysis run, получения status и выгрузки отчёта.
6. Snapshot-test renderer-а и тест запрета изменения чисел/evidence.

Критерий выхода: любой читатель может перейти от фразы отчёта к исходным раундам и
повторить вычисление.

## Этап 9 — hardening MVP (перенесён в Stage 10)

> Раздел сохранён как история. Актуальная детализация — в
> [Stage 10 — Corpus and Production Hardening](#stage-10--corpus-and-production-hardening-не-начат).
> Номер «Stage 9» теперь закреплён за Optional LLM Rephrasing.

1. Fuzz/negative tests для malformed demos и upload streams.
2. Resource limits: timeout, memory/disk budgets, cancellation/cleanup.
3. Structured local logs без исходных player data/path leakage.
4. Backup/export/retention policy для local DuckDB и demos.
5. CI: import, unit, integration, container build, dependency audit, fixture matrix.
6. Документировать support matrix и известные parser limitations.
7. Провести security review, performance profiling и пользовательскую проверку
   tactical wording.

## Отложено за пределы MVP

- Frontend.
- LLM rewriting (только после неизменяемого structured-report контракта).
- Heatmaps/visualization.
- Complex tactic recognition/ML.
- Distributed workers/multi-user auth/cloud storage.
- Любая live/in-game интеграция.

## Stage 6.1 — completed foundation

- Temporal schema/rule `1.1.0`: typed simultaneous groups and death-effect status.
- Bounded commutativity/conflict classification with deterministic group IDs.
- Group-aware before/after snapshots and post-tick semantics.
- Capability split for group, per-event, intermediate-order, and final alive state.
- DuckDB migration 006, repository queries, and `temporal groups/group` CLI.
- Stage 5 post-tick consistency check without changing Stage 5 definitions.
- FACEIT victimless-death source/canonical/persistence audit and regression tests.

Stage 7 was explicitly approved and is implemented as the non-analytic Spatial Engine
foundation below. Stage 8 is not started.

## Stage 6.5 — Temporal Engine 1.1 inspection UI (реализован)

- [x] Добавить server-rendered read-only FastAPI UI без parser/write/LLM вызовов.
- [x] Группировать state-affecting same-tick events и показывать ordering,
  intermediate/final state statuses, players, ambiguity reasons и pre/post projections.
- [x] Не рисовать единственный порядок внутри ambiguous group; показывать bounded
  possible intermediate states и deterministic post-group state отдельно.
- [x] Разделить before/after tick-group, before/after event, post-tick и final snapshots.
- [x] Показать capabilities отдельно для tick-group, per-event, intermediate ordering и
  final alive state.
- [x] Сохранить victimless death как unbound evidence без изменения alive count и дать
  переход в diagnostics.
- [x] Добавить шесть counters со списками точных round/group/event references и warnings.
- [x] Выбирать последний совместимый run, закреплять `temporal_run_id` во всех ссылках,
  показывать версии и список runs, не смешивать 1.0/1.1.
- [x] Для legacy 1.0 не заявлять 1.1 snapshot/group semantics; показывать typed
  unavailable и рекомендацию recompute.
- [x] Проверить через HTTP на реальной FACEIT базе round 1/opening/plant, round 10 tick
  70937, victimless deaths rounds 26/27, round 30 fallback и diagnostics.
- [x] Не включать spatial computation в Temporal UI/service; Stage 7 использует отдельный
  adapter, repository и read-only table.

Критерий выхода: все inspection-сценарии доступны без CLI, UI не превращает стабильный
ID в доказательство порядка, deterministic post-group state остаётся доступным, а каждый
warning/counter ведёт к выбранному изолированному run.

## Stage 7 — Spatial Engine Foundation (реализован)

- [x] Провести audit установленного `demoparser2==0.41.4`, upstream tag и реальной FACEIT
  demo; зафиксировать actual `parse_ticks` contract и классификацию spatial fields.
- [x] Добавить immutable parser-independent snapshots, map model, availability,
  capabilities, config, validation issues, summaries и versioned run contracts.
- [x] Использовать только live-round Temporal ticks; не использовать seconds и не создавать
  spatial row без существующей Temporal round/tick/participant связи.
- [x] Считать Temporal authoritative для alive/team/side; parser values использовать как
  cross-check. Помечать dead-pawn position/view как unreliable.
- [x] Получать `has_bomb` только из `inventory_as_ids` item 49; сохранять только derived
  carried-C4 origin, не выдумывать dropped/planted C4 position.
- [x] Валидировать tick ordering, duplicate/out-of-range rows, participant mapping,
  coordinate tuple, NaN/Infinity/overflow и source/Temporal disagreement.
- [x] Добавить migration 007, `SpatialRepository`, DuckDB adapter, atomic/idempotent
  save/replace/delete, multiple run history и exact compatible default selection.
- [x] Добавить application compute/query services и JSON-first CLI
  `spatial compute/status/show/runs/bombs/validate/delete` с file export для snapshots.
- [x] Интегрировать read-only Spatial table и JSON endpoints в FastAPI; не добавлять maps,
  paths, heatmaps, tactical labels или conclusions.
- [x] Добавить unit, adapter contract, repository/round-trip, validation, migration, CLI,
  UI и opt-in FACEIT full-pipeline tests.
- [x] Создать [SPATIAL_MODEL.md](SPATIAL_MODEL.md), обновить README/architecture и сохранить
  Stage 8 полностью вне scope.

Критерий выхода: одинаковые canonical/Temporal/source/config/rule inputs дают одинаковый
Spatial fingerprint; все rows привязаны к выбранному Temporal run; source limitations
видны в capabilities/warnings; persistence/query/UI/CLI проходят gates; ни одного
тактического вывода не существует. Stage 8 требует отдельного явного подтверждения.

## Stage 7.1 — Spatial Query & Visualization Layer (реализован)

- [x] Добавить parser-independent typed query models и application service для exact
  tick, player/round path, team/alive/C4 filters и nearest players.
- [x] Повысить Spatial rule до `1.1.0` и включить exact Temporal event ticks без
  интерполяции или предположения о seconds.
- [x] Добавить official local overview registry, SHA-256 provenance, проверенный Source 2
  transform и server-computed view direction.
- [x] Добавить read-only map UI, player path, team view, tick scrubber, previous/next,
  play/pause, jump-to-event и обычные evidence markers.
- [x] Связать Temporal event/snapshot и Spatial map в обе стороны одним закреплённым
  `temporal_run_id` и exact tick.
- [x] Добавить JSON endpoints для ticks, tick/map/team snapshot, player/round path и
  nearest players; missing run возвращает typed HTTP 404.
- [x] Добавить migrations `008`–`012`, single-column indexed query read-models и
  доказать `Index Scan` на реальной FACEIT базе без full payload-table read.
- [x] Исправить конкурентную initialization race DuckDB и добавить parallel HTTP
  regression test.
- [x] Проверить FACEIT rounds 1/10, view/C4/event markers, paths, filters и links;
  зафиксировать невозможность round 30 без отсутствующего exact source `.dem`.
- [x] Добавить [SPATIAL_QUERY_MODEL.md](SPATIAL_QUERY_MODEL.md), asset installer и
  screenshots; не начинать Stage 8.

Критерий выхода: пользователь может исследовать любой раунд существующего Spatial run,
каждый выбранный tick authoritative, map/Temporal links точны, пути не выдают линии за
доказанный маршрут, а UI не содержит зон, heatmaps или тактических выводов. Для полной
проверки 30-round fixture требуется восстановить соответствующий `.dem`.

## Stage 7.2 — Productization, Playback and UI Hardening (реализован)

- [x] Заменить UUID form на searchable/sortable persisted match library и empty state.
- [x] Добавить общий Jinja application shell, match context, overview, rounds, players и
  отдельный Diagnostics mode.
- [x] Вынести Spatial HTML/CSS/JS в templates/static modules без SPA/Node pipeline.
- [x] Добавить bounded playback chunk API с pagination, filters, explicit run pinning и
  запретом visual interpolation в evidence JSON.
- [x] Заменить `setInterval(fetch-per-sample)` на initial buffer, prefetch,
  `AbortController` и `requestAnimationFrame` state machine.
- [x] Добавить Smooth/Exact, 0.25×–4× playback policy, event/boundary navigation,
  keyboard controls и URL restoration.
- [x] Использовать persistent keyed SVG nodes; обновлять cards/events только на exact sample.
- [x] Добавить deterministic label candidates, initials/markers modes, leader lines,
  zoom/pan/reset/fit/fullscreen и responsive/reduced-motion UX.
- [x] Свернуть low-value Temporal events по умолчанию, сохранив raw evidence/API.
- [x] Добавить localhost-only safe `.dem` upload и single-worker reuse существующего
  canonical/analytics/Temporal/Spatial pipeline.
- [x] Добавить interpolation, playback API, product library, upload safety и regression tests.
- [x] Зафиксировать state machine, evidence boundary, instrumentation и product debt в
  [PLAYBACK_ARCHITECTURE.md](PLAYBACK_ARCHITECTURE.md).
- [x] Провести FACEIT manual acceptance, browser profiling, restart/run-isolation check и
  зафиксировать результаты в [STAGE_7_2_ACCEPTANCE.md](STAGE_7_2_ACCEPTANCE.md).

Критерий выхода: пользователь открывает persisted match без UUID, playback после buffering
не делает request на каждый visual frame, Smooth frames не становятся evidence, Exact и
Temporal navigation используют stored ticks, technical details отделены, а Stage 8 не начат.

## Stage 7.3 — Multi-map asset, versioning and calibration pack (реализован)

- [x] Ввести immutable `MapDefinition`, `MapRevision`, asset, transform, level,
  selection/pin/result contracts и data-driven registry.
- [x] Добавить exact aliases для восьми карт без fuzzy/fallback selection.
- [x] Определять revision только из manual/build/CRC/asset evidence; не угадывать
  по filesystem date и явно показывать unproven/incompatible layout.
- [x] Зафиксировать current и unsupported historical Cache/Overpass revisions; не
  подставлять current radar для исторической geometry.
- [x] Извлечь локальный versioned asset pack из pinned CS2 VPK, проверять
  checksum/dimensions/provenance/license и обслуживать offline с immutable cache.
- [x] Реализовать pure `world_to_map`, inverse validation, normalized/pixel results,
  typed availability/warnings и запрет silent clamp.
- [x] Добавить revision-owned Nuke upper/lower assets, Z policy, unknown boundary,
  automatic/manual/overlay UI.
- [x] Закреплять map revision/schema/fingerprint/checksums/transform в Spatial run;
  читать old runs как `legacy_map_semantics` без backfill.
- [x] Добавить read-only map/match APIs, local versioned asset routes, library thumbnails,
  explorer metadata/warnings и developer-only manual revision override.
- [x] Добавить non-persistent calibration workbench с backend candidate transform,
  comparison points и explicit unaccepted JSON export.
- [x] Покрыть aliases, transforms, orientation, bounds, Nuke levels, revisions, API/assets,
  persistence pin, legacy isolation, UI и playback regressions тестами.
- [x] Создать [MAP_MODEL.md](MAP_MODEL.md), [MAP_ASSETS.md](MAP_ASSETS.md),
  [MAP_CALIBRATION.md](MAP_CALIBRATION.md) и [MAP_FIXTURE_MATRIX.md](MAP_FIXTURE_MATRIX.md).

## Stage 7.4 — Playback Fidelity, Projectiles and Viewer Correction (implemented)

- [x] Instrument authoritative samples, motion gaps, browser frames, buffer and rejected entities.
- [x] Remove network awaits from `requestAnimationFrame`; prefetch at 60–70% consumption and add
  typed Paused/Playing/Buffering/End/no-next UX with retry.
- [x] Add tested normal/large/discontinuity/unavailable motion policy, shortest-yaw interpolation,
  and exact/interpolated/held/unavailable/dead/absent presentation semantics.
- [x] Reject out-of-map entities without clamp/fallback and add deterministic collision-aware
  full/short/marker-only labels.
- [x] Audit pinned demoparser2 0.41.4 and implement bounded projectile extraction with explicit
  requested fields/events, 4-tick sampling, lifecycle capabilities, and no physics simulation.
- [x] Add run-aware projectile/effect models, capability fingerprint, Migration 14 tables,
  transactional persistence, legacy-unavailable reads, and pinned queries.
- [x] Extend playback API 1.1 with separate player/projectile/effect/event collections and
  diagnostics; add persistent independent SVG layers and utility filters.
- [x] Validate Overpass and Ancient FACEIT demos and add parser, persistence/API, motion, yaw,
  label, bounds, lifecycle, and frontend regression tests.
- [x] Create [PLAYBACK_MODEL.md](PLAYBACK_MODEL.md),
  [PROJECTILE_MODEL.md](PROJECTILE_MODEL.md),
  [PROJECTILE_PARSER_AUDIT.md](PROJECTILE_PARSER_AUDIT.md), and
  [UTILITY_RENDERING.md](UTILITY_RENDERING.md).

Stage 8, tactics, control/zones, coaching, recommendations, projectile physics, and AI remain
explicitly outside this stage.

Ограничение acceptance: Ancient и Overpass имеют real-demo evidence. Для ещё
шести карт нужны matching demos; для historical Cache/Overpass нужны
authoritative revision evidence и matching assets. Эти пробелы не скрываются fallback-
константами. Stage 8 и все tactical/zone/heatmap/AI сущности остаются
вне scope до отдельного явного подтверждения.

## Stage 7.5 — Map Viewer rework (implemented; awaiting manual re-acceptance)

- [x] Reopen the stage after manual rejection and discard the incomplete
  JavaScript-only performance conclusion.
- [x] Capture comparable full DevTools traces for JS, Style, Layout, PrePaint, Paint,
  compositor, GPU, raster, DOM, sidebar, and event work.
- [x] Identify the shared moving SVG, full-document paint, event-node accumulation,
  hidden-chip CSS bug, per-sample history writes, and debug-heavy layout as root
  causes.
- [x] Replace the shared SVG with static map, independent compositor layers, a
  trail-only canvas, and fixed preallocated player/projectile/effect/event pools.
- [x] Prepare player transitions once per sample pair and restrict visual playback to
  guarded transform, direction, opacity, visibility, and selection updates.
- [x] Remove URL, diagnostics, unbounded events, labels, and sidebar work from the
  frame path.
- [x] Replace the page layout with a viewport-filling map, 196-pixel product sidebar,
  bounded current-event ribbon, integrated transport, and Diagnostics-only technical
  state.
- [x] Validate immediate label modes, player selection, utility filters, Auto Focus
  cancellation, responsive fit, pool stability, and Diagnostics isolation.
- [x] Record a stable 60.2-FPS fight with no interval above 34 ms, zero DOM
  additions/removals, no buffering, and no browser error.
- [x] Record the corrected RCA, traces, artifacts, limits, and rejected timer
  experiment in [STAGE_7_5_ACCEPTANCE.md](STAGE_7_5_ACCEPTANCE.md).

Exit condition for the implementation candidate: the real round-10 trace shows Paint
−97.6%, Layout −84.1%, RasterTask −96.4%, zero playback DOM allocation, and stable
60-FPS pacing. Final product acceptance remains a manual user decision. Stage 8 is
not started.

## Stage 7.6 — Density-independent Playback and Stable Labels (implemented; awaiting manual acceptance)

- [x] Reproduce the slowdown on the real FACEIT round-10 firefight and compare wall
  time with the duration implied by its tick span.
- [x] Identify the per-sample minimum duration, event-created sample density,
  one-sample-per-frame advance and discarded frame overshoot as clock root causes.
- [x] Replace transition-relative timing with an absolute monotonic relative-demo-tick
  playhead and binary sample bracketing.
- [x] Declare the `64 ticks/s` rate as a presentation policy
  (`not_canonical_tickrate`) and keep evidence/physical-time claims unchanged.
- [x] Allow one frame to advance across and account for multiple authoritative sample
  boundaries, committing the current bracket without stretching elapsed tick time.
- [x] Freeze the playhead on a typed buffer underrun and resume from the same tick.
- [x] Replace fixed sample-count prefetch with remaining-tick-time, speed-aware
  prefetch.
- [x] Raise playback API schema to `1.2.0`, publish clock metadata and remove duplicate
  top-level player/event collections.
- [x] Enable gzip for large FastAPI responses while preserving bounded chunks and run
  validation.
- [x] Cache projectile trail segment plans and rebuild them only when authoritative
  projectile evidence changes.
- [x] Build deterministic nickname anchors once from the full persisted roster so
  movement, deaths, C4, zoom and filters cannot make labels swap sides.
- [x] Add diagnostics for crossed samples, maximum catch-up per frame, label-plan
  builds and unexpected anchor changes.
- [x] Remove the 15-ms frame limiter and render every browser-delivered rAF callback,
  preventing refresh-rate aliasing at 75 Hz and 144 Hz.
- [x] Retain crossed exact events for 120 ms of wall time in 32 preallocated map slots
  without extending playback duration or inventing same-tick ordering.
- [x] Isolate filter-changing Back/Forward restoration by generation and clear the old
  buffer before loading restored filters.
- [x] Cancel stale prefetch/foreground work on exact or far seek so late chunks cannot
  repopulate an unrelated navigation target.
- [x] Make the async generation own loading state; superseding
  exact/filter/popstate navigation cancels both clients and cannot leave a stale loader.
- [x] Validate round-10 fight playback at 1× and 4×, a smoke/plant interval, buffer
  continuity, anchor stability and browser errors.
- [x] Replay complete round 10 at 4× and verify all 617 boundaries plus every one of
  214 unique renderable event links without buffering, long tasks, anchor flips or
  browser errors.
- [x] Record the RCA, measurements, evidence limits and manual checklist in
  [STAGE_7_6_ACCEPTANCE.md](STAGE_7_6_ACCEPTANCE.md).

Implementation-candidate exit evidence: ticks `67391–68093` changed from `21.114 s`
at 1× to approximately `11.005 s` against a `10.969 s` presentation target; 4× took
approximately `2.813 s`. Label audit changed from 132 anchor changes / 74 left-right
flips to zero. The final complete round-10 4× control run took `26.266 s` against a
`26.250 s` target, crossed all 617 boundaries, observed all 214 unique renderable event
links, peaked at 25 transient markers, and recorded zero buffering, anchor flips, long
tasks or errors. Maximum rAF interval was `24.9 ms`; maximum renderer duration was
`1.20 ms`. Final product acceptance remains a manual user decision. Stage 8 is not
started.

## Stage 8.0 — Correctness and Import Reliability (implemented; awaiting manual acceptance)

- [x] Render every round score in stable physical-team order across halftime/overtime
  side changes; show the physical winning team together with its observed side.
- [x] Add migration `015 durable_import_jobs` without changing canonical, analytics,
  Temporal or Spatial evidence schemas.
- [x] Persist every import pipeline checkpoint, attempt number, coarse pipeline
  progress, timestamps, retained internal filename and typed failure code.
- [x] Convert non-terminal jobs found after process restart into explicit
  `import_interrupted` failures; never claim that an interrupted in-memory operation
  continued.
- [x] Retain the safe uploaded demo and expose localhost-only Retry. A retry reruns the
  deterministic/idempotent pipeline and increments `attempt_count`.
- [x] Expose recent durable jobs in the match library and keep the job page reachable
  after a server restart.
- [x] Make browser polling distinguish temporary server unavailability from a failed
  import and resume polling automatically.
- [x] Render a controlled HTML/JSON `internal_server_error` boundary while logging the
  underlying exception server-side.
- [x] Add repository, restart recovery, retry, score orientation and migration
  regression tests.

Stage 8.0 does not implement opponent cohorts, zones, cross-match patterns,
recommendations, report generation or LLM integration. Those remain separate,
explicitly reviewed Stage 8 sections.

## Stage 8.1 — Opponent Workspace (implemented; awaiting manual acceptance)

- [x] Add schema `1.0.0` and migration `016 opponent_workspaces` for profiles and
  user-confirmed `(profile, match) -> physical team` selections.
- [x] Keep profile names independent from generic/source demo team labels.
- [x] Merge cross-match players only by canonical Steam ID; keep missing IDs as
  match-scoped occurrences and never merge nicknames.
- [x] Derive core/partial/unresolved roster roles and preserve nickname aliases.
- [x] Compute advisory candidate overlap with explicit numerator, denominator,
  frequency, missing-ID count and deterministic strength.
- [x] Require manual confirmation even for strong overlap; persist
  `selection_source=user_confirmed`.
- [x] Add opponent library/workspace HTML, JSON endpoints and localhost-only create,
  confirm, reassign and remove actions.
- [x] Reject cross-site browser mutation origins in addition to checking the loopback
  client address.
- [x] List player names for generic `TeamAlpha`/`TeamBravo` candidates so the user can
  identify the intended physical team.
- [x] Remove opponent selections transactionally when their canonical match is
  deleted; keep the profile.
- [x] Add repository, identity, alias, substitution, overlap, validation, API/UI and
  deletion regression tests.
- [x] Record normative behavior in [OPPONENT_MODEL.md](OPPONENT_MODEL.md).

Stage 8.1 produces evidence scope only. It does not implement zones, cross-match
gameplay patterns, findings, recommendations, reports or LLM integration.

## Stage 8.1.1 — Manual Acceptance и Workspace Polish (принят 2026-07-27)

Сценарий пройден на реальных данных (4 FACEIT матча) и принят пользователем
2026-07-27:

- [x] создать профиль соперника;
- [x] добавить первую демку;
- [x] выбрать команду по игрокам;
- [x] добавить вторую демку;
- [x] проверить overlap (1/5 shared Steam ID, strength weak, без автовыбора);
- [x] переназначить ошибочно выбранную команду;
- [x] удалить матч из профиля;
- [x] проверить игроков `core`, `partial`; `unresolved_identity`
  невоспроизводим на корпусе с полными Steam ID — покрыт
  `tests/test_opponents.py` (роль `UNRESOLVED_IDENTITY`);
- [x] проверить профиль после перезапуска сервера.

Улучшения по результатам приёмки:

- [x] переименование профиля (`POST /api/opponents/{id}/rename`, 409 при
  конфликте имён);
- [x] удаление пустого профиля с подтверждением (checkbox + 409, если в
  профиле остались матчи);
- [x] одношаговая перепривязка команды («Reassign to …» на подтверждённом
  матче поверх существующего upsert);
- [x] ссылка из match overview в Opponent Workspaces;
- [ ] фильтр кандидатов по карте (отложен — кандидатов пока мало);
- [x] визуальное разделение команд признано достаточным (карточки с рамками
  по силе overlap).

Технические долги аудита 2026-07-27, закрытые в этом этапе:

- [x] дефолт `host` в `config.py` → `127.0.0.1` (Docker задаёт `0.0.0.0` явно);
- [x] единый `require_localhost` c проверкой Origin для product и opponents
  маршрутов;
- [x] освежить README (вводная, дерево структуры, «Текущие ограничения»).

## Stage 8.2 — Map Zone Engine (Stage 8.2B реализован; ожидает ручной acceptance)

### Stage 8.2A — Trusted zone baseline

- [x] `simple_polygon_v1`: repeated vertices, zero-length edges и
  self-intersections имеют детерминированные issue codes;
- [x] developer editor отклоняет невалидный proposal до записи;
- [x] технические closing-точки/петли устранены во всех зарегистрированных
  authored sets, все наборы проходят строгую structural validation;
- [x] Anubis (34) и Cache (36) закреплены точной map revision, fingerprints,
  Valve anchors и дополнительными named-layout anchors;
- [x] Stage 8.2B — versioned Zone Assignment Run: результаты каждого Spatial
  snapshot материализуются в DuckDB и привязаны к точному Spatial run.

### Stage 8.2B — Versioned Zone Assignment Run

Реализовано 2026-08-02:

- [x] schema `1.0.0`, rule `snapshot_point_to_zone_v1`, DuckDB migration 017;
- [x] отдельный immutable run с SHA-256 по Spatial fingerprint, config, map
  revision, zone-set fingerprint и всем assignment outcomes;
- [x] три typed результата: `resolved`, `unknown`, `unavailable`; ближайшая
  зона никогда не подставляется;
- [x] сохранённые строки содержат точные ссылки на Spatial snapshot, match,
  round, tick и participant;
- [x] run закрепляет Spatial schema/rule/fingerprint, map definition
  fingerprint, map revision selection status, zone schema/rules/fingerprint;
- [x] map revision `unproven` допускается только явной версионированной
  конфигурацией по умолчанию и понижает capability до `partial`; CLI умеет
  включить строгий запрет;
- [x] повторный запуск идемпотентен, collision проверяется, старые runs не
  переинтерпретируются после правки зон;
- [x] вычисление встроено после Spatial в durable import job (`zones`, 94%);
- [x] CLI `zones compute/status/runs/show/delete`;
- [x] API `/api/zones/{match_id}/summary|runs|assignments`;
- [x] playback/tick/path JSON возвращает assignment для каждого игрока и
  provenance выбранного zone run; UI показывает зону выбранного игрока,
  tooltips, warnings и zone diagnostics;
- [x] удаление Spatial run или match каскадно удаляет зависимые zone runs.

Не сделано в 8.2B: агрегации времени в зоне, first-contact/early-control
features, heatmap, тактические выводы, рекомендации и LLM. Это входные данные
для Stage 8.4+, а не часть point-to-zone слоя.

Зафиксированные решения владельца продукта для следующих этапов:

- целевой минимальный corpus opponent analysis — около 20 матчей;
- T и CT получают одинаковое покрытие;
- economy taxonomy: `pistol / eco / force / semi / full / unknown`;
- исходные загруженные `.dem` можно сохранять.

Статус 2026-08-02: ядро реализовано (`src/stratweb/zones/`, нормативная
семантика в [ZONE_MODEL.md](ZONE_MODEL.md)) — версионированный
`ZoneSetDefinition` c fingerprint, `point_in_polygon_v1` c тотальной
границей, высотные `min_z`/`max_z` (этажи Nuke), `unknown` без догадок,
детерминированный приоритет при перекрытии, структурная валидация и
`sampled_coverage`. Также готово: developer overlay c ручным редактором
(`/ui/dev/zones/{map}`: перетаскивание, вершины, freehand-карандаш,
свои зоны с именами; сохранение в `zone_proposals/{map}.json`, которое
живьём заменяет авторскую разметку). В код закреплены принятые ручные наборы
`de_mirage` (33 зоны), `de_anubis` (34 зоны) и `de_cache` (36 зон), все со
статусом `OVERLAY_VERIFIED`, стабильным fingerprint и evidence-тестами для
доступных Valve-якорей/контрольных точек. Осталось: ручная проверка Stage 8.2B
на сохранённых реальных матчах и дальнейшая разметка карт по продуктовой
необходимости. Zone fingerprint уже закреплён в отдельном immutable run, а
выбранный игрок показывает сохранённую зону в UI.

Цель: преобразовать координаты в доказанные именованные области карты.

Входное условие (gate): ground-truth тест «известная точка мира → известный
пиксель» хотя бы для `de_dust2` (единственная карта с `rotation=90`,
проверенная только синтетическим round-trip) и для одной `DEMO_VALIDATED`
карты. Без него зоны наследуют непроверенную трансформацию координат.

- [x] Gate выполнен 2026-07-27: `tests/test_maps_ground_truth.py` сверяет
  freeze-end центроиды спавнов из реальных FACEIT демок (dust2, mirage,
  overpass, ancient) с независимыми Valve-якорями `CTSpawn`/`TSpawn` из VPK
  overview `.txt` той же ревизии; отклонения ≤0.08 при допуске 0.15, ошибка
  ориентации дала бы ≥0.3. Отдельный тест доказывает различающую силу якорей
  против axis-swap. Rotation dust2 подтверждён запечённым в PNG.

Реализовать:

- версионированный `ZoneDefinition`;
- полигоны областей;
- `zone_id`, `zone_name`, `map_name`, `map_revision`;
- верхний/нижний уровень для Nuke;
- bombsites, spawns, основные проходы и chokepoints;
- точное попадание координаты в полигон;
- результат `unknown`, если зона не доказана;
- ручной developer overlay для проверки границ;
- zone provenance и checksum;
- zone coverage diagnostics;
- unit tests для границ и этажей;
- проверку на реальных Mirage, Ancient, Overpass и Dust II;
- (желательно) определения `de_train` и `de_vertigo` в maps registry — обе
  карты в текущем Active Duty, сейчас демки на них дают `UNSUPPORTED`.

Не реализовывать: автоматическое распознавание тактик; heatmap; ближайшую
«предполагаемую» зону; рекомендации; LLM.

Acceptance:

- клик по игроку показывает доказанную зону;
- неизвестная координата остаётся `unknown`;
- версия зон закреплена в spatial/analysis run;
- смена map revision не изменяет старые результаты.

## Stage 8.3 — Economy and Equipment Context (реализован и принят на real demo)

Цель: не сравнивать pistol, eco, force и full-buy как одинаковые раунды.
Сначала провести аудит реальных полей `demoparser2==0.41.4` (по образцу
[PROJECTILE_PARSER_AUDIT.md](PROJECTILE_PARSER_AUDIT.md)).

Реализовать:

- equipment snapshots на freeze end;
- player/team equipment value;
- оружие, броню, defuse kits и utility;
- классификацию: pistol; eco; force; semi; full; unknown;
- сторону и физическую команду;
- score context;
- overtime context;
- availability и источник каждого значения;
- правила исключения раундов;
- версионированный Economy run.

Не придумывать цены или поля parser API. Любая таблица цен должна быть
версионированной.

Acceptance:

- каждый раунд получает доказанную buy-классификацию либо `unknown`;
- analytics может фильтровать раунды по buy type;
- отсутствие equipment не превращается в eco.

Реализовано:

- [x] отдельный `Demoparser2EconomyExtractor` для точных freeze-end ticks и
  `demoparser2==0.41.4`;
- [x] player/team equipment snapshots с typed availability и provenance каждого поля;
- [x] weapons, utility, armor, helmet, defuse kit, balance, spend и equipment value;
- [x] детерминированные `pistol|eco|force|semi|full|unknown` правила с versioned config;
- [x] физическая команда, T/CT, score-before и overtime context;
- [x] исключения warmup/incomplete/missing-freeze/unresolved-roster;
- [x] Economy run schema/rule/config/source-column fingerprint и DuckDB migration 018;
- [x] CLI/API фильтр team-round данных по `buy_type`, стороне и раунду;
- [x] автоматический Economy checkpoint для новых import jobs;
- [x] unit, persistence и HTTP contract tests.

Real-demo acceptance: повторно загруженная FACEIT demo дала 21 раунд, 210 player
snapshots, 42 team snapshots, 40 классифицированных team-round и coverage 95,2%; два
неизвестных результата оставлены `unknown`, а не угаданы. Контракт и аудит:
[ECONOMY_MODEL.md](ECONOMY_MODEL.md) и
[ECONOMY_PARSER_AUDIT.md](ECONOMY_PARSER_AUDIT.md).

### Stage 8.3.1 — Visual Economy UI (реализован)

- [x] отдельная read-only страница `/ui/matches/{match_id}/economy`;
- [x] coverage, classified/unknown counts и распределение buy types;
- [x] round-by-round T/CT cards с equipment value, spend, balance, helmets и kits;
- [x] раскрываемые player equipment snapshots без подстановки неизвестных значений;
- [x] фильтры по стороне, buy type и номеру раунда;
- [x] один pinned Economy run на страницу, видимые schema/rule/parser versions и JSON links;
- [x] переходы из общей навигации, match overview и diagnostics;
- [x] unit/HTTP и real FACEIT page-render проверки.

Stage 8.4 реализован; Stage 8.5 реализован отдельно ниже.

## Stage 8.4 — Per-Round Tactical Feature Engine (реализован)

Цель: извлечь факты одного раунда без межматчевых выводов.

Входные условия: решена семантика man-advantage (сейчас «первое преимущество»
засчитывается и за суицид/тимкилл соперника — решение зафиксировать в
[ANALYTICS_DEFINITIONS.md](ANALYTICS_DEFINITIONS.md)); резолвер участников не
копируется в третий раз (analytics и temporal уже содержат по независимой
реализации — выделить общую до расширения).

Примеры features:

- начальное распределение игроков по зонам;
- первый контакт: tick, зона и игроки;
- opening duel;
- первая utility: тип, зона и игрок;
- раннее присутствие в ключевых зонах;
- направление движения бомбы;
- bombsite;
- время plant;
- post-plant состав;
- первая CT rotation;
- потеря численного преимущества;
- непротрейженная смерть;
- retake attempt;
- save/exit, только если доказуемо;
- распределение игроков по зонам на заданных checkpoints.

Каждый feature должен содержать: `match_id`; `round_number`; `team_id`;
`side`; tick или tick range; zone; availability; rule version; evidence
event/snapshot IDs; limitations.

Не делать вывод «это execute/default». Пока только факты.

Реализовано:

- [x] parser-independent `RoundFeatureEngine` и строгие Pydantic contracts;
- [x] `available|partial|unavailable|not_applicable` без подстановки неизвестных данных;
- [x] immutable run, который закрепляет canonical, Analytics, Temporal, Spatial,
  Zone Assignment и optional Economy fingerprints/versions;
- [x] evidence IDs для canonical events, Spatial snapshots и Economy snapshots;
- [x] migration 019, атомарное DuckDB persistence, latest-compatible selection и
  dependency-aware child-first cleanup;
- [x] CLI `features compute|status|runs|show|delete`;
- [x] read-only API `/api/features/{match_id}/summary|runs|records`;
- [x] автоматический feature checkpoint в pipeline загрузки новых `.dem`;
- [x] интеграционные тесты детерминизма, evidence, фильтров и cascade;
- [x] real FACEIT validation: 21 eligible rounds, 1073 records, 713 available,
  196 partial, 77 unavailable, 87 not applicable, warnings отсутствуют.

Сознательно не реализованы общие CT rotation и save/exit: текущие данные не
доказывают роль/намерение. Retake V1 допускает только строгий положительный факт
входа живого CT в точную зону установленной бомбы. Межматчевые частоты и названия
тактик относятся только к Stage 8.5+.

### Stage 8.4.1 — Round Facts UI (реализован)

- [x] отдельная read-only страница `/ui/matches/{match_id}/features`;
- [x] карточки общей доступности и раскрываемое покрытие по типам фактов;
- [x] серверные фильтры round/team/side/type/availability/buy type;
- [x] постраничный вывод по 100 записей без загрузки всех тяжёлых payload в DOM;
- [x] понятное observation-представление поверх неизменённого typed payload;
- [x] раскрываемые event/spatial/economy evidence IDs, limitations и warnings;
- [x] переходы в exact map playback и Temporal timeline соответствующего раунда;
- [x] закрепление одного feature run на страницу и видимый provenance;
- [x] навигация из match overview, верхнего меню и diagnostics;
- [x] HTTP/UI tests и проверка рендера на real FACEIT run с 1073 facts.

Stage 8.4.1 не вычисляет новые факты и не меняет Stage 8.4 semantics. Это только
evidence-safe presentation layer.

## Stage 8.5 — Cross-Match Pattern Engine (реализован)

Цель: находить повторения внутри подтверждённого Opponent Workspace.

Группировать строго по: opponent profile; map; T/CT side; buy type;
полному/допустимому раунду; версии feature rules.

Первые паттерны:

- site preference;
- early zone occupation;
- recurring opening player;
- recurring opening death;
- first-contact zones;
- first utility;
- bomb routing;
- CT starting positions;
- early rotations;
- opening-kill conversion;
- recovery after opening death;
- lost man advantage;
- untraded deaths;
- plant timing;
- retake/save frequency.

Для каждого паттерна: numerator; denominator; frequency; sample size;
minimum sample size; confidence; confidence method; small-sample warning;
included и excluded rounds; limitations.

Использовать детерминированный confidence method (например, Wilson interval).
Не выдавать correlation за causation.

Реализовано:

- [x] pure parser-independent `CrossMatchPatternEngine` поверх pinned Stage 8.4 runs;
- [x] строгий scope: подтверждённый opponent profile, map, T/CT side, buy type и
  feature rule version;
- [x] только завершённые non-warmup rounds; недоступные входы и раунды сохраняют
  явную причину исключения;
- [x] 13 вычисляемых семейств: site preference, early zones, recurring opener/death,
  first contact/utility, bomb route, exact CT setup, opening conversion/recovery,
  lost advantage, untraded death и plant timing buckets;
- [x] `early_rotation`, `retake_frequency` и `save_frequency` представлены typed
  `unavailable`: Stage 8.4 не доказывает соответственно rotation, отрицательную
  retake opportunity и намерение save;
- [x] numerator, denominator, frequency, sample size, match counts, minimum sample,
  small-sample warning и детерминированный Wilson 95% interval для каждой записи;
- [x] evidence для каждого раунда числителя и полный список раундов знаменателя,
  включая `match_id`, `round_number`, tick и доступные feature/event/snapshot IDs;
- [x] Steam ID как единственный cross-match player key; отсутствие Steam ID остаётся
  match-scoped occurrence и никогда не объединяется по nickname;
- [x] immutable fingerprints/UUIDv5, schema/rule/config/workspace provenance;
- [x] migration 020 с normalized run/input/pattern/evidence/exclusion tables;
- [x] latest-compatible run selection без смешивания изменившихся workspace или
  feature runs и child-first cascade при удалении upstream данных;
- [x] CLI `patterns compute|status|runs|show|delete`;
- [x] localhost-only compute API и read-only summary/runs/pattern list API;
- [x] unit и сквозные persistence/CLI/API/cascade tests.

Минимальный корпус по умолчанию — 20 включённых матчей, а минимальный denominator
одной записи — 5. Недостаток данных не скрывает вычисленные значения, но всегда даёт
`corpus_below_minimum`/`small_sample_warning`. Wilson lower bound хранится как
консервативный `confidence.score`; это статистическая устойчивость частоты, не
вероятность причинности и не качество будущей рекомендации.

Контракт и точные denominators описаны в [PATTERN_MODEL.md](PATTERN_MODEL.md).
Stage 8.5 не создаёт `AnalysisFinding`, tactical interpretation, recommendation,
report UI или LLM text. Stage 8.6 реализован отдельно ниже.

## Stage 8.6 — Analysis Run, Finding and Evidence Persistence (реализован)

Цель: превратить агрегаты в воспроизводимые `AnalysisFinding`.

Реализовать:

- immutable `AnalysisRun`;
- configuration hash;
- dataset/profile fingerprint;
- selected match IDs;
- pinned input run versions;
- `AnalysisFinding`;
- `EvidenceReference`;
- atomic/idempotent persistence;
- несколько исторических runs;
- выбор последнего совместимого run;
- запрет смешивания runs;
- evidence API;
- переход finding → матч → раунд → tick → карта/timeline.

Обязательные поля finding: observation; tactical implication; recommended
response; avoid; numerator/denominator/frequency; confidence; evidence;
limitations; small-sample warning.

На этапе реализации Stage 8.6 рекомендации были оставлены typed-unavailable;
актуальный отдельный результат рекомендаций теперь хранит Stage 8.7.

Реализовано:

- [x] pure `AnalysisFindingEngine` поверх одного pinned Stage 8.5 pattern run;
- [x] immutable `AnalysisRun`, configuration hash, workspace/pattern fingerprints и
  точные match/team/demo/feature inputs;
- [x] `AnalysisFinding` с раздельными `observation`, `tactical_implication`,
  `recommended_response` и `avoid`;
- [x] observation формируется детерминированно; три поля Stage 8.7 имеют typed
  `unavailable`, а не выдуманный текст;
- [x] numerator, denominator, frequency, match counts, sample threshold, Wilson
  confidence и small-sample warning копируются без пересчёта из source pattern;
- [x] полный denominator хранится как `EvidenceReference`, включая match/round/tick,
  demo SHA-256, feature/event/spatial/economy IDs и exact map/timeline links;
- [x] migration 021, atomic/idempotent DuckDB persistence, historical runs,
  latest-compatible selection и child-first cascade от pattern run;
- [x] CLI `findings compute|status|runs|show|evidence|delete`;
- [x] localhost-only compute API, summary/runs/findings/detail/evidence API;
- [x] zero-frequency patterns по умолчанию не превращаются в утверждения; это
  fingerprinted config и видимый warning;
- [x] unit/integration/CLI/API/cascade tests.

Контракт описан в [FINDING_MODEL.md](FINDING_MODEL.md). Сам Stage 8.6 по-прежнему
не вычисляет тактические интерпретации: отдельный Stage 8.7 создаёт их только после
readiness gate и не изменяет исходный finding.

## Stage 8.6.1 — Finding Readiness Gate (завершён)

Цель: не допустить переход слабых или неполных Stage 8.6 findings в будущие
рекомендации.

- [x] typed `ready / limited / blocked` result для каждого finding;
- [x] явные blocking reasons и limitations без догадок о неизвестных данных;
- [x] минимальный корпус 20 матчей и минимум 2 матча в evidence finding;
- [x] блокировка small sample, partial source pattern и неизвестного buy type;
- [x] отдельная проверка покрытия evidence ticks;
- [x] versioned rule/schema/configuration hash и воспроизводимый UUIDv5 audit;
- [x] read-only CLI `readiness audit` и JSON API;
- [x] unit/integration/CLI/API проверки детерминизма;
- [x] контракт описан в `FINDING_READINESS.md`.

Stage 8.6.1 ничего не рекомендует и не начинает Stage 8.7.

## Stage 8.7 — Deterministic Counter-Strategy Rules (V1 реализован; corpus acceptance ожидается)

Цель: формировать рекомендации только из подтверждённых findings.

Разделять:

1. Observation — что регулярно происходило.
2. Tactical implication — почему это может быть важно.
3. Recommended response — что можно проверить против соперника.
4. Avoid — чего лучше не делать.
5. Limitations — почему рекомендация может не сработать.

Примеры rule families:

- повторяющийся ранний контроль зоны;
- слабая защита после opening death;
- низкая конверсия преимущества;
- часто непротрейженные entry;
- поздняя utility;
- повторяющиеся CT anchors;
- предсказуемое направление бомбы;
- слабый retake;
- частый save.

Запрещено: заявлять причинность; рекомендовать действие на одном раунде;
скрывать denominator; использовать LLM для расчёта; выдавать recommendation
без evidence.

Реализовано в V1:

- [x] pure `CounterStrategyEngine` поверх одного pinned Analysis run и точного
  Stage 8.6.1 readiness audit;
- [x] жёсткий запрет recommendation для `limited` и `blocked` findings;
- [x] отдельные observation, tactical interpretation, recommendation и avoid;
- [x] восемь консервативных rule families: site, early/contact control, opening
  player/victim, opening conversion/recovery, lost advantage, untraded death;
- [x] все thresholds находятся в versioned/fingerprinted config;
- [x] полное копирование numerator/denominator/frequency/confidence/evidence без
  текстового перерасчёта;
- [x] immutable run, migration 022, atomic/idempotent DuckDB persistence,
  historical/latest-compatible runs и cascade от Analysis run;
- [x] CLI `strategies compute|status|runs|show|skipped|evidence|delete`;
- [x] localhost-only compute API и read-only summary/runs/list/detail/evidence/skips;
- [x] real corpus validation: 155 findings, 0 ready, 0 recommendations,
  155 explicit skips при корпусе 1/20 — gate не обойдён;
- [x] контракт описан в `COUNTER_STRATEGY_MODEL.md`.

До полного content acceptance Stage 8.7 требуется корпус примерно из 20 матчей одного
соперника и ручная проверка опубликованных рекомендаций. UI Stage 8.8 реализован, но
не подменяет этот corpus gate.

### Stage 8.7.1 — Corpus and rule-quality acceptance audit (реализован)

- [x] pure read-only audit над одним immutable CounterStrategy run;
- [x] versioned config/schema/rules, canonical SHA-256 и UUIDv5 identity;
- [x] `passed|blocked|failed` без подмены недостатка корпуса ошибкой данных;
- [x] checks provenance, input counts, exact readiness reproduction и полной
  одноразовой классификации findings;
- [x] checks readiness gate, неизменности statistics/observation/evidence,
  принадлежности evidence корпусу, дубликатов и причинных формулировок;
- [x] coverage по матчам, картам, сторонам, закупам, findings, рекомендациям,
  evidence и правилам;
- [x] CLI `strategies validate` и read-only validation API;
- [x] synthetic 20-match acceptance fixture проходит; реальный профиль честно
  `blocked` при 1/20 матчей и 0 рекомендаций, integrity failures отсутствуют;
- [x] контракт описан в `COUNTER_STRATEGY_VALIDATION.md`.

Оставшиеся четыре импортированных матча не назначены текущему сопернику по догадке.
Для реального `passed` нужны явные owner-confirmed selections примерно 20 матчей и
ручная тактическая проверка появившихся рекомендаций.

## Stage 8.8 — Scouting Report UI (V1 реализован)

Цель: показать тренеру готовый предматчевый отчёт.

Разделы: Overview; Data quality; T-side tendencies; CT-side tendencies;
Individual tendencies; Recurring mistakes; Recommended responses; What to
avoid; Evidence appendix.

Фильтры: карта; сторона; buy type; временной диапазон; матчи; confidence;
минимальная выборка.

Каждая карточка должна открывать evidence:

```text
Finding
  → matches
  → rounds
  → ticks
  → map/timeline
  → calculation details
```

## Stage 8.8.4 — final product UI polish (completed)

- design-system contract upgraded to `1.1.0` with a global final polish layer;
- report, filters, fact grids, diagnostics and empty states hardened for phone widths;
- long evidence values and tables no longer force the complete page to overflow;
- remaining user-facing English accessibility labels and layer names translated to Russian;
- keyboard focus and reduced-motion behavior normalized across shared controls;
- analytics, evidence, parser, persistence and report calculations remain unchanged.

Добавить JSON export. PDF — отдельным подэтапом после принятия HTML.

Новые страницы строить только на современном стеке (Jinja templates +
autoescape + typed view models), не расширяя legacy f-string рендеринг
`web/temporal.py` / `web/spatial.py`.

Реализовано в V1:

- [x] read-only `ScoutingReportService` собирает один pinned Strategy/Analysis/
  Readiness/Validation bundle без смешивания runs;
- [x] versioned typed report и evidence-detail view models;
- [x] acceptance banner и все Stage 8.7.1 checks без ложного зелёного статуса;
- [x] T-side, CT-side, individual и outcome/risk observation sections;
- [x] отдельные observation, tactical interpretation, recommended response и avoid;
- [x] явный blocked/empty state, если readiness не пропустил рекомендации;
- [x] filters map/side/buy/pattern/minimum sample/minimum Wilson score без
  перерасчёта statistics;
- [x] полный denominator evidence drill-down до match/round/tick/map/timeline;
- [x] owner-confirmed corpus manifest, pagination и pinned run во всех ссылках;
- [x] responsive desktop/mobile UI и read-only versioned report JSON;
- [x] real-data review: 1/20, 155 findings, 0 ready/recommendations, 155 skips,
  498 source evidence references, status `blocked`, 14 deterministic checks;
- [x] контракт описан в `SCOUTING_REPORT_UI.md`.

Фильтр отдельных матчей и временного диапазона отложен: он меняет denominator и
должен создавать новый Analysis run, а не только скрывать строки UI. Остаётся ручное
product acceptance владельцем. Stage 8.9/PDF не начат.

## Stage 8.9 — Report Export (completed)

Реализовано:

- [x] стабильный versioned JSON contract без UI-фильтров и пагинации;
- [x] printable HTML с полным корпусом, findings и evidence appendix;
- [x] детерминированный PDF export с Unicode-шрифтом и нумерацией страниц;
- [x] сохранённые даты Analysis/Strategy run и полный scope анализа;
- [x] версии opponent/pattern/analysis/readiness/strategy/validation/export rules;
- [x] список демок, оригинальные имена и SHA-256 без небезопасных имён файлов;
- [x] проверки качества, ограничения выборки и неизвестные значения как `null`;
- [x] evidence appendix: match, round, tick and event IDs; complete feature/snapshot IDs in
  JSON/printable HTML and exact supporting counts in the compact server PDF;
- [x] одинаковый source run даёт одинаковый JSON fingerprint и PDF bytes.

PDF не содержит выводов, отсутствующих в сохранённом Analysis/Strategy run.

## Stage 9.0 — Release Baseline (завершён)

- [x] private source ZIP и Git bundle созданы до изменения рабочего дерева;
- [x] accepted Stage 8.2–8.9 зафиксированы отдельным baseline commit `8351d5a`;
- [x] версия проекта поднята до `0.4.0`;
- [x] добавлен cross-platform `uv.lock` contract и frozen install policy;
- [x] добавлен общий Windows/Linux release gate и GitHub Actions workflow;
- [x] добавлены changelog, release checklist и security deployment policy;
- [x] Docker Compose публикует HTTP только на host loopback по умолчанию;
- [x] полный local quality gate проходит после final self-review;
- [x] clean release commit помечен локальным tag `v0.4.0`.

Полный scope: [STAGE_9_0.md](STAGE_9_0.md).

## Stage 9.1 — Golden Corpus (tooling завершён; набор данных заблокирован)

- [x] версионированный manifest и внешний SHA-256 storage contract без `.dem` в Git;
- [x] candidate/confirmed/rejected lifecycle без автоматического угадывания соперника;
- [x] readiness gate для одного соперника, карт, источников и edge cases;
- [x] analyst-labelled findings, evidence и parser-version compatibility matrix;
- [x] deterministic precision/recall/false-positive evaluation без LLM;
- [x] пять реально импортированных FACEIT матчей зарегистрированы как candidates;
- [ ] минимум 20 явно подтверждённых матчей одного соперника;
- [ ] подтверждённые Valve, HLTV/GOTV и поддерживаемые POV demos;
- [ ] overtime, substitutions, missing Steam IDs, damaged/incomplete demos;
- [ ] analyst ground truth для positive/negative finding labels.

Полный scope и честные blockers: [STAGE_9_1.md](STAGE_9_1.md).

## Stage 9.2 — Storage Engine V2 (9.2a и 9.2b завершены)

### Stage 9.2a — read-only audit

- [x] измерение bytes/rows/indexes/blocks по таблицам;
- [x] точное сравнение canonical и lookup Spatial/Bomb payload;
- [x] representative warm-cache query benchmarks;
- [x] naive risk projection для 20/100/500 матчей с явными ограничениями;
- [x] аудит количества immutable runs без объявления их удаляемыми;
- [x] безопасный CLI и JSON contract, не изменяющие DuckDB.

Результаты: [STAGE_9_2A.md](STAGE_9_2A.md).

### Stage 9.2b — canonical single-source migration

- [x] verified `COPY FROM DATABASE` backup до первой V2 mutation;
- [x] canonical key indexes без второй JSON-копии для новых Spatial runs;
- [x] key/payload parity и migration rollback tests;
- [x] performance comparison с явным latency budget;
- [x] version-aware repository read switch и acceptance window;
- [x] Parquet evaluation: только будущий immutable archive, не interactive store;
- [x] dependency-aware retention policy спроектирована; automatic deletion запрещён;
- [ ] controlled disk reclamation только после отдельного подтверждения владельца.

Результаты: [STAGE_9_2B.md](STAGE_9_2B.md). Старые mirrors сохранены для rollback,
поэтому Stage 9.2b не обещает немедленное уменьшение существующего файла.

## Stage 9.3 — Import Worker V2 (завершён)

- [x] все вызовы native `demoparser2` изолированы в одноразовых subprocess;
- [x] parser artifacts записываются атомарно и проходят Pydantic/hash/tick validation;
- [x] DuckDB persistence остаётся у единственного application-process writer;
- [x] SHA-256 считается во время streaming upload, duplicate отклоняется до parsing;
- [x] очередь ограничена: один активный writer плюс настраиваемое число ожидающих задач;
- [x] cancellation работает для queued и running parser jobs через безопасные границы;
- [x] retry/restart переиспользует только совместимые артефакты стабильного `job_id`;
- [x] timeout, working-set memory, free-disk limits и typed backpressure;
- [x] migration 024 сохраняет hash, размер, checkpoint, worker и cancellation metadata;
- [x] crash/restart, duplicate, queue, cancel, artifact reuse, disk и timeout tests.

Результаты и ограничения: [STAGE_9_3.md](STAGE_9_3.md).

## Stage 9.4 — Statistical Trust (завершён)

- [x] round evidence агрегируется в независимые `match_id` clusters;
- [x] deterministic match-cluster bootstrap interval с hash-derived seed;
- [x] practical effect gate относительно заранее доказуемой null frequency;
- [x] exact match-cluster sign test и global Benjamini–Hochberg FDR correction;
- [x] minimum cluster, clustered lower-bound и leave-one-match-out stability gates;
- [x] typed `not_testable` для pattern families без корректного baseline;
- [x] patch/roster-period stability возвращает `unavailable`, пока нет match patch/time metadata;
- [x] deterministic evidence-reliability ranking не меняет observation/recommendation;
- [x] immutable DuckDB runs, migration 025, API и отдельный русский UI;
- [x] synthetic edge-case tests и read-only smoke на реальных 160 patterns.

Методика: [STATISTICAL_TRUST_MODEL.md](STATISTICAL_TRUST_MODEL.md). Acceptance evidence:
[STAGE_9_4.md](STAGE_9_4.md).

## Stage 9.5 — Tactical Intelligence V2 (завершён)

- [x] exact checkpoint-formation path clustering и planted execute packages;
- [x] typed HE/fire outcome association без выдуманной flash/smoke эффективности;
- [x] spacing checkpoints, unambiguous entry/trade structure;
- [x] post-contact CT transition edges без утверждения о намерении;
- [x] post-tick-group 1v2+ clutch и Stage 8.4 save-exit behaviour;
- [x] world-grid alive-sample heatmaps с явной sampling семантикой;
- [x] полная match/round/tick/event/snapshot/feature/projectile/effect lineage;
- [x] immutable DuckDB runs, migration 026, API и русский inspection UI;
- [x] synthetic all-family acceptance и persisted real FACEIT smoke с idempotency check.

Контракт: [TACTICAL_INTELLIGENCE_V2_MODEL.md](TACTICAL_INTELLIGENCE_V2_MODEL.md).
Acceptance evidence: [STAGE_9_5.md](STAGE_9_5.md).

## Stage 9.6 — Product UX and Localization (в работе)

### Stage 9.6.1 — Tactical V2 product view (завершён)

- [x] краткий обзор с одним репрезентативным наблюдением на семейство;
- [x] карточки вместо технической таблицы, без insight key/UUID в основном потоке;
- [x] server-side фильтры type/map/side и bounded pagination;
- [x] русские названия, ограничения и capability coverage;
- [x] responsive layout и сохранение полного provenance в сворачиваемом разделе;
- [x] доказать тестами, что UI-фильтры не изменяют persisted insight payload.

### Stage 9.6.2 — versioned locale contract (завершён)

- [x] request-local render context вместо изменяемой глобальной локали;
- [x] одинаковый набор стабильных ключей и placeholder contract для `ru` и `en`;
- [x] полный русский/английский Tactical V2 и общий shell без смешения языков;
- [x] явный `?lang=` → same-site cookie → русский default;
- [x] доказать тестом, что переключение языка не меняет JSON/API payload;
- [ ] испанский и китайский каталоги — отдельное расширение после полного перевода ключей.

### Stage 9.6.3 — HTML evidence drill-down (завершён)

- [x] отдельная ru/en страница каждого Tactical V2 observation;
- [x] ссылки на match, round, tick и individual Temporal event;
- [x] conditional links на post-tick snapshot, exact 2D и round facts;
- [x] каждый переход закрепляет source Temporal/Spatial/Feature run;
- [x] bounded lookup одного insight и пагинация по 24 evidence references;
- [x] технические UUID сохранены в disclosure, но убраны из основного чтения;
- [x] реальная FACEIT acceptance: event, snapshot и exact spatial links дают HTTP 200.

### Stage 9.6.4 — mobile states and analyst notes (завершён)

- [x] отдельные loading-состояния для вычисления Tactical V2 и сохранения/удаления заметки;
- [x] локализованные not-found и empty-evidence состояния без подмены unknown нулём;
- [x] адаптивные evidence actions, заголовок и note form для узких экранов;
- [x] одна локальная analyst note на точную пару Tactical run/insight;
- [x] migration 027, repository port, upsert/delete и dependency-aware cascade;
- [x] заметки отделены от immutable insights, evidence, fingerprints и analytics;
- [x] localhost/same-origin защита изменений, RU/EN locale schema 2.2.0;
- [x] unit, persistence, HTTP, locale и responsive contract tests.

### Stage 9.6.5 — Plain-Language Tactical UX (завершён)

- [x] провести аудит числового и технического шума основного Tactical V2 UI;
- [x] заменить T/CT, raw transition keys и координаты heatmap понятными формулировками;
- [x] добавить deterministic frequency bands и ясную оценку достаточности выборки;
- [x] сократить default view до одного представителя каждого раздела и трёх главных сигналов;
- [x] перенести проценты, дроби, counts, limitations, ticks и UUID во второй уровень;
- [x] оставить полный набор insights доступным через явный фильтр типа;
- [x] упростить evidence card до одного главного действия и скрыть специальные переходы;
- [x] добавить прямой путь к готовому отчёту с рекомендациями;
- [x] обновить RU/EN locale contract до 3.0.0 и проверить API invariance.

### Stage 9.6.6 — One-Tap UX & Visual Identity (завершён)

- [x] сделать простой режим отчёта маршрутом по умолчанию;
- [x] собрать шесть последовательных экранов с одной кнопкой запуска и одной основной кнопкой продолжения;
- [x] ограничить каждый раздел тремя детерминированно выбранными сигналами;
- [x] не превращать пустые риски или неготовые рекомендации в придуманный совет;
- [x] сохранить полный прежний отчёт в отдельном режиме аналитика;
- [x] сократить верхние действия профиля соперника до одной основной кнопки;
- [x] добавить touch swipe, keyboard/focus contract, no-JS и reduced-motion fallback;
- [x] заменить основную orange/blue палитру на graphite/mint design system 2.0.0;
- [x] обновить RU/EN locale contract до 3.1.0;
- [x] подтвердить неизменность analytical/API/evidence contracts.

Stage 9.7 не начат.

Acceptance evidence: [STAGE_9_6_6.md](STAGE_9_6_6.md).

## Stage 9.7 — Team/On-Prem Edition (не начат)

- users, roles, projects, authentication, HTTPS и audit log;
- metadata store и object storage boundary;
- tenant-safe API и controlled worker deployment.

## Stage 9.8 — Production Operations (не начат)

- readiness checks, structured logs, metrics and request/job IDs;
- migration rehearsal, disaster restore, security scanning и support matrix;
- performance budgets и release automation.

## Stage 9.9 — Interactive 2D Telestrator (завершён)

- [x] один компактный вход «Разметка» без перегрузки основного 2D viewer;
- [x] стрелка, карандаш, зона и текст с нормализованными координатами карты;
- [x] undo, clear, hide/show и явное сохранение одной доски на match/round;
- [x] versioned Pydantic contract и DuckDB migration 032;
- [x] optimistic revision: две вкладки не могут молча перезаписать друг друга;
- [x] отдельный SVG layer вне горячего playback render loop;
- [x] понятная маркировка: ручные заметки не являются demo evidence или finding;
- [x] localhost/same-origin mutation policy и адаптивная mobile panel.

Acceptance evidence: [TELESTRATOR.md](TELESTRATOR.md).

## Stage 9.10 — One-Page Match Cheat Sheet (завершён)

- [x] одна шпаргалка всегда ограничена одной выбранной картой;
- [x] надёжность считается по подтверждённым матчам этой карты, а не всему корпусу;
- [x] максимум два детерминированно выбранных сигнала на T, CT и риски;
- [x] максимум два готовых ответа с отдельными «сыграть» и «не делать»;
- [x] validation failure скрывает советы, unknown не заменяется догадкой;
- [x] каждый сигнал ведёт к полному evidence drill-down;
- [x] копирование plain text для Discord/team chat без внешней интеграции;
- [x] адаптивный экран и компактная A4 landscape печать.

Acceptance evidence: [MATCH_CHEAT_SHEET.md](MATCH_CHEAT_SHEET.md).

### Report preparation recovery — 0.24.2

- [x] действие «Подготовить план» выполняет существующие patterns → findings → strategies;
- [x] GET остаётся read-only, POST — localhost-only, повтор не создаёт одинаковые runs;
- [x] нет ложной надписи «готовый план», пока совместимый strategy run не существует;
- [x] вместо технического тупика — объяснение, повтор и ссылки на обработку матчей;
- [x] никакого ослабления evidence/readiness правил и автоматического повторного парсинга.

Это исправление перехода к плану, не полный автоматический pipeline обработки всех демо.

## Stage 9.11 — Optional LLM Rephrasing (не начат)

Только после corpus/statistical acceptance. LLM может сокращать, переводить и менять
стиль подтверждённого текста. LLM не может считать статистику, менять
numerator/denominator/confidence, создавать findings, выбирать evidence или удалять
limitations. Оригинальный deterministic finding всегда хранится рядом.

## Stage 10 — Cloud Scale (не начат)

- multi-tenant control plane;
- horizontally scalable parser/analytics workers;
- Postgres metadata, object storage и immutable analytical artifacts;
- quotas, billing boundary и operational SLO только после on-prem hardening.

## Рекомендуемый порядок после Stage 8.1

```text
8.1.1 Manual acceptance + polish
        ↓
8.2 Zone Engine (gate: ground-truth координаты dust2)
        ↓
8.3 Economy Context
        ↓
8.4 Per-Round Features (gate: семантика man-advantage)
        ↓
8.5 Cross-Match Patterns
        ↓
8.6 Findings + Evidence Persistence
        ↓
8.7 Counter-Strategy Rules
        ↓
8.8 Report UI
        ↓
8.9 Export
        ↓
9.0 Release Baseline
        ↓
9.1 Corpus → 9.2 Storage → 9.3 Workers → 9.4 Statistical Trust
        ↓
9.5 Tactical V2 → 9.6 UX → 9.7 On-Prem → 9.8 Operations
        ↓
9.9 Telestrator → 9.10 One-Page Cheat Sheet → 9.11 Optional LLM
        ↓
10 Cloud Scale
```

## Stage 8.8.1 — interface productization

- **8.8.1a completed:** versioned tokens, typography, surfaces, controls, data tables,
  evidence states and a local component reference.
- **8.8.1b completed:** two-level application shell, deterministic active navigation,
  current-match context and responsive navigation overflow.
- **8.8.1c completed:** product-first diagnostics, economy navigation and progressive
  disclosure for validation checks, versions, identifiers and raw exports.
- **8.8.1d pending:** safe local appearance preferences constrained by semantic roles.
- **8.8.1e pending:** visual regression matrix and final accessibility/performance pass.

## Stage 8.8.2 — Russian UX and clean match identity

- **completed:** русский язык основных страниц библиотеки, матча, диагностики, экономики,
  импорта и профилей соперников;
- **completed:** `TeamAlpha` / `TeamBravo` скрыты за нейтральными подписями;
- **completed:** исходные имена демо и UUID убраны из основного визуального потока и
  сохранены в сворачиваемых технических блоках;
- **completed:** migration 023 и отдельный repository для ручных/импортированных названий
  команд без изменения canonical identity;
- **completed:** отображаемое имя проходит через библиотеку, матч, экономику, opponent
  workspace и scouting report;
- **completed in 8.8.3:** перевод специализированного playback/temporal UI и текстов
  детерминированных findings;
- **pending follow-up:** английский, испанский и китайский каталоги не начаты.

## Stage 8.8.3 — Russian analytical workspace (completed)

- локализованы 2D playback, timeline/snapshots/simultaneous groups и temporal diagnostics;
- локализованы round facts, фильтры, статусы, закупы и evidence navigation;
- локализован scouting report, проверки качества, наблюдения, ответы и evidence appendix;
- presentation layer формирует русские описания по типизированным кодам и сохранённым
  числам, не меняя deterministic analytics, fingerprints или evidence;
- UUID и версии сохранены в раскрываемых технических блоках.

## Готовый prompt для Cloud-агента (Stage 8.2)

```text
Продолжай проект StratWeb.

Текущее состояние:
- Stage 1–7.6 завершены.
- Stage 8.0 завершён.
- Stage 8.1 Opponent Workspace завершён.
- DuckDB migration version: 016.
- Opponent schema: 1.0.0.
- Identity rule: steam_id_else_match_occurrence_v1.
- Overlap rule: candidate_known_steam_ids_v1.
- 230 tests collected: 224 passed, 6 skipped.
- demoparser2 pinned to 0.41.4.
- Проект под git (ветка main); коммить логическими шагами.
- Runtime-данные вне репозитория: пути задаёт .env (не коммитить и не менять).

Сначала прочитай:
- README.md
- ARCHITECTURE.md
- IMPLEMENTATION_PLAN.md
- OPPONENT_MODEL.md
- SPATIAL_MODEL.md
- MAP_MODEL.md
- MAP_ASSETS.md
- MAP_CALIBRATION.md

Выполняй только следующий этап: Stage 8.2 Map Zone Engine.

Главные ограничения:
- только офлайн завершённые .dem;
- не придумывать API parser-а;
- никакой live-функциональности;
- никакого LLM;
- не распознавать тактики;
- не делать heatmap;
- координата вне доказанного полигона должна давать unknown;
- зоны и map revision должны быть версионированы;
- старые runs нельзя молча переинтерпретировать;
- каждый результат должен сохранять provenance;
- сначала выполни входной gate: ground-truth тест координат de_dust2;
- не переходить к Stage 8.3 без явного подтверждения.

Перед изменениями:
1. Осмотри репозиторий и git status.
2. Проверь текущие migrations и тесты.
3. Составь краткий план.
4. Не удаляй пользовательские файлы.

После реализации:
1. Запусти targeted tests.
2. Запусти полный pytest.
3. Запусти Ruff и Mypy.
4. Проверь UI на реальных сохранённых матчах.
5. Проведи critical review.
6. Исправь серьёзные недостатки.
7. Обнови документацию.
8. Покажи версии, ограничения и acceptance evidence.
```
