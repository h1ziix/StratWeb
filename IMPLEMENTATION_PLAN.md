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
> [Stage 8.6 — Analysis Run, Finding and Evidence Persistence](#stage-86--analysis-run-finding-and-evidence-persistence-не-начат).

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

## Stage 8.1.1 — Manual Acceptance и Workspace Polish (не начат)

Перед новой аналитикой проверить реальный пользовательский сценарий:

- [ ] создать профиль соперника;
- [ ] добавить первую демку;
- [ ] выбрать команду по игрокам;
- [ ] добавить вторую демку;
- [ ] проверить overlap;
- [ ] переназначить ошибочно выбранную команду;
- [ ] удалить матч из профиля;
- [ ] проверить игроков `core`, `partial`, `unresolved_identity`;
- [ ] проверить профиль после перезапуска сервера.

Допустимые небольшие улучшения (по результатам приёмки):

- переименование профиля;
- удаление пустого профиля с подтверждением;
- ссылка из match overview в Opponent Workspace;
- фильтр кандидатов по карте;
- более понятное визуальное разделение двух команд.

Технические долги аудита 2026-07-27, закрываемые в этом этапе:

- [ ] дефолт `host` в `config.py` → `127.0.0.1` (Docker задаёт `0.0.0.0` явно);
- [ ] единый `_require_localhost` c проверкой Origin для product и opponents
  маршрутов;
- [ ] освежить README (вводная, дерево структуры, «Текущие ограничения»).

Не начинать тактическую аналитику, пока сценарий не принят.

## Stage 8.2 — Map Zone Engine (не начат)

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

## Stage 8.3 — Economy and Equipment Context (не начат)

Цель: не сравнивать pistol, eco, force и full-buy как одинаковые раунды.
Сначала провести аудит реальных полей `demoparser2==0.41.4` (по образцу
[PROJECTILE_PARSER_AUDIT.md](PROJECTILE_PARSER_AUDIT.md)).

Реализовать:

- equipment snapshots на freeze end;
- player/team equipment value;
- оружие, броню, defuse kits и utility;
- классификацию: pistol; eco; force; partial buy; full buy; unknown;
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

## Stage 8.4 — Per-Round Tactical Feature Engine (не начат)

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

## Stage 8.5 — Cross-Match Pattern Engine (не начат)

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

## Stage 8.6 — Analysis Run, Finding and Evidence Persistence (не начат)

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

На этом этапе рекомендации можно оставить пустыми typed-unavailable, если
Stage 8.7 ещё не выполнен.

## Stage 8.7 — Deterministic Counter-Strategy Rules (не начат)

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

## Stage 8.8 — Scouting Report UI (не начат)

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

Добавить JSON export. PDF — отдельным подэтапом после принятия HTML.

Новые страницы строить только на современном стеке (Jinja templates +
autoescape + typed view models), не расширяя legacy f-string рендеринг
`web/temporal.py` / `web/spatial.py`.

## Stage 8.9 — Report Export (не начат)

Реализовать:

- стабильный JSON contract;
- printable HTML;
- PDF export;
- дату и scope анализа;
- версии всех rules;
- список демок;
- SHA-256;
- ограничения выборки;
- evidence appendix.

PDF не должен содержать выводов, отсутствующих в сохранённом Analysis run.

## Stage 9 — Optional LLM Rephrasing (не начат)

Только после принятия детерминированного отчёта.

LLM разрешено: сокращать текст; менять стиль; переводить; формировать
короткое executive summary.

LLM запрещено: считать статистику; менять numerator/denominator; создавать
findings; добавлять рекомендации без deterministic rule; удалять limitations;
выбирать evidence; повышать confidence.

Оригинальный deterministic finding всегда должен сохраняться рядом с
LLM-текстом.

## Stage 10 — Corpus and Production Hardening (не начат)

- реальные FACEIT fixtures разных карт;
- Valve demos;
- HLTV/GOTV demos;
- POV demos, если формат поддерживается;
- повреждённые и неполные demos;
- overtime;
- substitutions;
- отсутствующие Steam IDs;
- parser-version compatibility matrix;
- migration backup/restore;
- disk cleanup policy;
- import cancellation;
- crash/restart tests;
- performance benchmark на больших наборах;
- security review localhost API;
- fuzz/negative tests, resource limits, structured logs, CI и support matrix
  из бывшего «Этапа 9 — hardening MVP».

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
9 Optional LLM
        ↓
10 Hardening
```

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
