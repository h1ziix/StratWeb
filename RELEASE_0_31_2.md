# StratWeb 0.31.2 — короткие границы записи при импорте

Локальный релиз поверх существующей рабочей версии 0.31.1. Новых миграций базы нет.

## Изменения

`LocalImportJobManager` больше не удерживает общий writer на всём вызове compute.
Сервисы принимают отдельный `save_context`: загрузка данных, ожидание parser worker,
вычисления и проверка результата происходят до его входа. Это относится к Economy,
Analytics, Temporal, Spatial, Zones и Round Features; canonical validation также
вынесена за границу сохранения.

Перед входом в save manager проверяет Event отмены, опрашивает доступность writer
с интервалом 100 мс и повторяет проверку после захвата. Внутри этой границы адаптер
открывает транзакцию, проверяет canonical fingerprint, SHA и ссылки на исходные runs,
записывает строки, проверяет их количество и делает commit/rollback. Save/delete
шести слоёв используют тот же coordinator, что и замена/удаление canonical match.
Удаление источника между вычислением и сохранением приводит к integrity error и
не оставляет частично записанный слой.

Чтения canonical, аналитических слоёв и import jobs открывают независимые MVCC
connections без writer. Настройка соединений остаётся `read_only=False`, поскольку
DuckDB требует одинаковой конфигурации подключения к одному файлу. Отдельный schema
gate допускает параллельные чтения и исключает их на всём протяжении миграций.
Cache hit в initialize не ждёт обычную запись; cache miss соблюдает порядок
writer → schema gate → initialization/cache lock и повторно проверяет кеш.

`cancel()` сначала устанавливает Event активного job и только затем обращается
к базе. Поэтому ожидание записи CANCEL_REQUESTED не мешает дочернему процессу
получить сигнал. Изменения статусов выполняются как сериализованный read/modify/write
с compare-and-set; cancellation/terminal outcome не затирается checkpoint или PID.
PID/memory callbacks пропускают занятую запись, сохраняя работу цикла контроля
дочернего процесса. Ошибка callback после запуска также приводит к остановке child.

`shutdown()` немедленно сигнализирует все jobs, отменяет очередь и использует один
общий бюджет ожидания: по умолчанию grace + 6 секунд, то есть 11 секунд. В тестах
бюджет задаётся через `shutdown_timeout_seconds`. Отмена работающего вычисления
публикуется только после безопасной границы; истечение бюджета не открывает retry
поверх ещё работающей задачи. Запись отмены для удалённых из очереди jobs может
завершиться в daemon cleanup после возврата shutdown. Работающий job завершает
свою отмену сам. Исходная демка сохраняется; recovery после рестарта остаётся доступен.
Долгий чистый compute останавливается на границе сохранения, а не внутри engine.
Возврат метода shutdown ограничен бюджетом; это не принудительное завершение
Python-потока или гарантия срока выхода интерпретатора при внешней блокировке базы.

DEBUG logger `stratweb.adapters.persistence.write_coordinator` выводит
`database_writer wait_seconds=... hold_seconds=...`. Учитывается внешняя граница;
вложенные reentrant вызовы не дублируют время удержания.

## Проверки и методика измерений

`tests/test_import_responsiveness.py` выполняет настоящий pipeline и настоящие
DuckDB/HTTP операции на небольшом детерминированном canonical fixture. Вместо
парсинга реальной демки используются fixture extraction artifacts. Девять точек
pipeline задерживаются Event минимум на секунду: canonical parser, economy parser
и engine, Analytics, Temporal, spatial parser и engine, Zones, Round Features.
В каждой точке другой writer получает coordinator, а `/ui`, страница job, API
прогресса и страница матча (после canonical import) отвечают HTTP 200 даже при
удерживаемом другим потоком writer. Проверяются стадия и ненулевой прогресс.

После успешного полного импорта исходный match удаляется. Попытки сохранить
ранее вычисленные результаты всех шести слоёв отклоняются соответствующими
integrity exceptions. Отдельные проверки отменяют каждый из шести engines
во время вычисления: текущий слой не записывается, статус становится CANCELLED,
входной файл сохраняется.

Проверка отмены запускает настоящий Python subprocess, который должен спать
60 секунд. Пока writer удерживается другим потоком, запрос cancel ждёт запись
статуса, но child завершается по Event. Проверка shutdown при занятой базе
использует бюджет 200 мс. После освобождения writer статус становится CANCELLED.
Также покрыты отмена во время захвата save lock, истечение shutdown до безопасной
границы, исключение чтений на миграциях и параллельные query connections.

Регрессии 0.31.1 для конкурентных initialize/import/read на свежей и legacy базе
сохранены в killable subprocess. Uninitialized/legacy reader сначала проверяет
миграции; обычный reader готовой базы уже не должен ждать writer.

Измерения этого fixture не являются измерением производительности реальной
длительной CS2 демки. Реальный child подтверждает остановку процесса, но не
корректность demoparser2 на новом реальном матче. Golden Corpus product acceptance
остаётся в прежнем состоянии.

## Измерения окончательного прогона

| Операция | Замеров | Минимум, мс | Медиана, мс | Максимум, мс |
| --- | ---: | ---: | ---: | ---: |
| Библиотека /ui | 9 | 252.3 | 710.3 | 766.3 |
| Страница задачи | 9 | 47.4 | 53.4 | 61.4 |
| API прогресса | 9 | 44.7 | 48.4 | 63.4 |
| Страница матча | 8 | 943.7 | 1263.2 | 1347.0 |
| Удержание writer (worker, внешние границы) | 24 | 121.7 | 131.1 | 311.9 |

Суммарное время управляемых пауз: 16.870 с;
в эти паузы общий writer свободен. Паузы включают HTTP-запросы и ожидание до
минимальной секунды, но не время записи между стадиями. Это не полная длительность
импорта и не оценка throughput на настоящей демке.

Отправка cancel → остановка настоящего child при занятом writer:
**5.03 мс**. Возврат shutdown при бюджете 200 мс:
**200.47 мс**. Запрос cancel при этом продолжал ждать
сохранения статуса; измерено именно прекращение child, а не HTTP-ответ cancel.
После освобождения writer проверен итоговый CANCELLED.

Сырые измерения: `.runtime/release-check/import-latency.json` и
`.runtime/release-check/cancel-latency.json`.

## Итоговые результаты

Команда: `./scripts/release_check.ps1 -AllowDirty` — **успешно**, Windows,
Python 3.13.14. Полная non-integration регрессия: **477 passed, 6 deselected**,
**665.40 с**. Это 466 тестов baseline 0.31.1 и 11 новых регрессий.

Прошли lockfile validation, frozen environment sync, dependency consistency,
Ruff format/lint (316 файлов), строгий mypy (245 source files), JavaScript syntax
(20 файлов), application import/version check, HTTP smoke (`/health: 200`,
`/ui: 200`), Golden Corpus contract validation, wheel build и Compose validation.
Дополнительно проверены version metadata и runtime version внутри собранного wheel,
а также `git diff --check`.

Шесть integration tests не запускались: для них нужны внешние demo inputs.
Проверка Golden Corpus подтвердила корректность контракта; readiness остаётся
`blocked` из-за отсутствия подтверждённых матчей и analyst labels, как в baseline.

Полный лог: `.runtime/release-check/0.31.2-gate-final.log`.

Wheel: `.runtime/release-check/dist/stratweb-0.31.2-py3-none-any.whl`.

SHA-256: `9d5504437c9b188abb51747d9bb9162c00e6395ecccea876825f7db64d6bf3a9`.

Рядом сохранён checksum-файл `stratweb-0.31.2-py3-none-any.whl.sha256`.
Версии `pyproject.toml`, `uv.lock`, runtime и metadata wheel согласованы: 0.31.2.
Изменения 0.31.1 и существующие незакоммиченные файлы сохранены; релиз подготовлен
локально без публикации и Git tag.
