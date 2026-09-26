# StratWeb 0.31.4 — восстановление карт и пакетная запись импорта

Релиз проверен на сохранённых настоящих FACEIT CS2-демках, включая загрузку по HTTP,
отмену, повтор и просмотр 2D-карты. Аналитические правила, координаты, fingerprints,
UUID runs и доказательная семантика не менялись. Новая миграция базы не требуется.

## Причины и исправления

Штатный Windows launcher выбирал `%LOCALAPPDATA%\StratWeb\map_overviews`, но
установщик по умолчанию писал в `data/map_overviews`, а прежний установленный пакет
остался в `%USERPROFILE%\StratWeb-data\map_overviews`. Рабочий каталог был пуст,
поэтому точные закреплённые изображения и метаданные не находились.

Теперь настройки приложения, установщик и launcher используют один Windows root.
Переменная `STRATWEB_MAP_OVERVIEW_DIR` сохраняет приоритет. Установщик без `--output`
пишет в `vpk-<SHA256 prefix>` внутри этого root, поэтому сохраняется соответствие
путям закреплённого VPK. Явный `--output` по-прежнему задаёт точный каталог ревизии.
Launcher восстанавливает только отсутствующие файлы старого пакета; существующие
файлы не перезаписывает. На этой машине восстановлены **22 файла**. Dust2, Mirage,
Nuke прошли проверку через `MapOverviewRegistry`: `available`.

Проверки SHA-256 PNG/метаданных, размеров и точного map pin сохранены. Неизвестный
VPK не переименовывается в известную ревизию. При отсутствии или несоответствии
ресурсов интерфейс объясняет проблему и направляет к `MAP_ASSETS.md`.

Длительный Spatial был вызван массовыми `executemany`: 90 370 снимков игроков,
4 906 снимков бомбы и остальные spatial entities записывались построчно. V1 затем
повторно сериализовал и построчно записывал снимки в lookup mirrors. Замер отделил
запись от вычисления: **131,78 с из 138,59 с Spatial** приходились на save.

Spatial и Temporal теперь регистрируют Polars relations пакетами до 16 384 строк
и выполняют `INSERT SELECT`. UUID явно передаются как строки с SQL-приведением к
исходным UUID-колонкам; JSON payload остаётся исходным сериализованным JSON.
V1 mirrors заполняются одним `INSERT SELECT` из только что сохранённых canonical
строк, включая те же payload и lookup keys. V2 использует прежние canonical indexes
и не требует mirrors. Все пакеты и lookup inserts находятся внутри прежней
транзакции целого run; SQL constraints, проверки источников и количества строк,
COMMIT/ROLLBACK и writer coordination сохранены.

Импорт логирует длительность каждого этапа, ожидание writer и длительность записи
с `job_id`. Ошибки логируются с исходной цепочкой исключений; пользователь получает
безопасное сообщение. Прогресс сообщает этап сохранения и безопасную границу отмены.
Исходные демки и проверенные parser artifacts сохраняются также после complete.

При просмотре карты во время импорта найден дополнительный дефект: кеш сохранял
`None` для ещё не созданного Zones run навсегда. Теперь кешируются только найденные
неизменяемые runs; следующий запрос видит завершившийся расчёт зон.

## Сравнительные измерения

Windows, Python 3.13.14, DuckDB 1.5.4, неизменные зависимости. Одна и та же настоящая
демка Dust2, 21 раунд, SHA-256
`9d783bb41789489c3fbb5bd912a61784ab115285f17fed7cffc054585df7099d`.
Оба запуска используют одинаковые сохранённые parser artifacts и отдельные новые
V1-базы, поэтому это **полный replay артефактов**, а не время первого native parsing.
Измерение canonical save включает создание схемы. Это единичные локальные замеры,
а не оценка распределения latency; baseline был снят до изменения persistence.

| Этап | 0.31.3, с | 0.31.4, с |
|---|---:|---:|
| Canonical artifact load | 0,029 | 0,024 |
| Canonical import | 1,402 | 1,845 |
| Economy | 0,101 | 0,107 |
| Analytics | 0,321 | 0,327 |
| Temporal | 3,607 | 1,043 |
| Spatial целиком | 138,588 | 12,830 |
| Только Spatial save, входит в строку выше | 131,777 | 6,033 |
| Zones | 12,400 | 13,182 |
| Features | 6,518 | 6,632 |
| Весь replay | 162,966 | 35,989 |

Spatial save ускорился **в 21,8 раза**, весь replay — **в 4,5 раза**.
Row counts в обеих новых базах совпадают: один spatial run, 90 370 player snapshots,
4 906 bomb snapshots, 276 projectiles, 9 905 projectile snapshots, 273 utility effects.

Сырые результаты: `.runtime/release-check/0.31.4/baseline.json` и `columnar.json`.
`scripts/benchmark_import.py` воспроизводит replay в новой базе и умеет
`--baseline-wheel` для сохранённого wheel 0.31.3. Параметры `--artifacts`, `--demo`,
`--sha256`, `--database`, `--output` задаются явно; существующую базу он не заменяет.

## Реальный пользовательский сценарий

Перед остановкой сервера проверены три задания: cancelled/Spatial, failed с
`persistence_error`, failed с `import_interrupted`. Активных заданий не было.
Незакоммиченные изменения 0.31.1–0.31.3 сохранены вместе с бинарным diff в
`.runtime/release-check/pre-0.31.4-worktree.zip`; база и WAL сохранены отдельно.
Предыдущие исправления блокировок, read sessions и connection pool сохранены.

Повтор `46c67a70-1b0b-461f-bd4e-54256085f22d` через HTTP завершился **complete**,
100%, `last_completed_stage=features`, attempt 3. От queued до complete — **28,55 с**.
Существующий spatial run `07e91823-18e7-5cd0-a539-d1ba2bb99d20` и fingerprint
сохранены; повтор использовал artifacts и уже сохранённые runs, затем завершил
Zones/Features. Дубликаты spatial snapshots не создавались.

Отдельный HTTP сервер на новой тестовой базе принял эту же настоящую демку
размером 257 793 179 байт: POST `/api/import-jobs` — **202**, upload **2,30 с**.
Job `c663e0f7-a96e-41ee-950d-4385f8bafda8` отменён на Spatial, затем POST retry
возобновил обработку до **complete**, attempt 2. От создания job до complete,
включая отмену и повтор — **47,57 с**. Parser artifacts от завершённых этапов
повторно использованы. Новая Spatial запись по HTTP заняла **6,07 с**.
Тестовая база, demo и artifacts сохранены; тестовый сервер после проверки остановлен.

Проверка upload/cancel/retry повторена после последнего изменения исходников на
ещё одной новой тестовой базе: job `ac7ae730-0e58-474c-beec-a47786c2dbf5`,
complete, attempt 2, один run и ровно 90 370 snapshots. Полный цикл job —
**47.97 с**, upload **2.64 с**. Spatial save — 6,70 с при параллельном release gate.

Оба других исходных задания также завершены через retry на актуальном сервере.
В частности, исторический `persistence_error` больше не воспроизвёлся. Исходная
цепочка той старой ошибки в прежнем manager не логировалась, поэтому её точная
причина не установлена; новая регрессия проверяет логирование этой цепочки.

Проверены HTTP 200: `/health`, `/ui`, import job page/status, обзор матча, Temporal,
карта раунда, spatial summary/map, maps registry, список ticks и последовательные
playback блоки с индексами 0/64/128. Проверены versioned PNG, SHA-256 и cache headers.
Во время обработки `/ui` и карта отвечали HTTP 200. Для artifact retry `/ui`:
медиана 601 мс, максимум 3,27 с при одновременном чтении карты; в upload/cancel/retry
сценарии медиана 45,5 мс, максимум 1,95 с. Без фоновой обработки `/ui` — 66 мс.
Ответы доступны, но интенсивный Python compute всё ещё влияет на latency.

В браузере проверены 10 игроков, событие смерти на тике 5843, его Temporal-карточка,
изменение alive state и отображение зон. Playback запущен пробелом и прошёл от
снимка 97 до 321 из 427 с загрузкой следующих блоков; ошибок JavaScript нет.
Снимок: `.runtime/release-check/0.31.4/map-event.png`.

## Проверки проекта

Регрессии покрывают пакетную запись UUID/JSON/lookup keys, SQL constraints,
откат предыдущих пакетов при ошибке, unregister relation после ошибки, восстановление
прежнего Spatial run при неудачном replace, V1/V2 и идемпотентный повтор,
ресурсные пути, non-overwrite recovery и сохранение unproven/checksum semantics,
исходную причину ошибки с job_id и появление Zones после раннего просмотра карты.

Окончательный `./scripts/release_check.ps1 -AllowDirty` прошёл:
**495 passed, 6 deselected**, **172,70 с**. Lockfile/frozen sync, dependency consistency,
Ruff format/lint (324 файла), strict mypy (247 source files), JavaScript syntax
(20 файлов), application/version check, HTTP smoke, Golden Corpus contract,
wheel build и Compose validation прошли. Отдельный прогон всех integration tests
с `STRATWEB_TEST_DEMO` на сохранённой настоящей демке: **6 passed**, **35,33 с**.
Проверки ожидания writer/отмены и import responsiveness на последнем коде:
**62 passed**, 42,77 с; новая регрессия отмены затем вошла в окончательные 495 tests.

Первый gate обнаружил ожидание удаления демки в старом responsiveness test;
оно обновлено на сохранение исходника. Первый integration run выявил устаревший
expected row count без уже существующей таблицы `blinds`; ожидание исправлено
на `len(dataset.blinds)`. Правила canonical/analytics при этом не менялись.

Логи: `.runtime/release-check/0.31.4/release-gate-release.log` и `integration-final.log`.
Wheel: `.runtime/release-check/dist/stratweb-0.31.4-py3-none-any.whl`.
SHA-256: `dd061dd65eb4bf68efb42f5e7c5fd2f3971c55e8dada1ca098f768e842fc7673`.
Проверено совпадение упакованных bulk/resource/import/cache исходников с workspace,
metadata/runtime/pyproject/lockfile 0.31.4 и `git diff --check`. Предыдущие изменения
connection manager, write coordinator, canonical persistence, worker и pinned JSON
fixture сохранены побайтно относительно исходного снимка.

## Ограничения

- Демка имеет patch version `14174`, а проверенный пакет карт — `1.41.7.1` /
  `d263aa1118fb`. Поэтому map selection остаётся **unproven** с предупреждением;
  отображение карты и SHA-256 ресурсов не доказывают соответствие ревизии демке.
- Coordination writer остаётся внутрипроцессной. Обязательная V2-миграция не введена.
- Отмена внутри атомарного save завершается на безопасной границе транзакции;
  уже выполняющийся SQL-пакет не обрывается посередине commit.
- Сохранение исходников и artifacts увеличивает дисковое потребление; автоматического
  удаления после complete теперь нет.
- Golden Corpus contract и техническая работоспособность не заменяют проверку
  аналитического качества по размеченному реальному корпусу.
