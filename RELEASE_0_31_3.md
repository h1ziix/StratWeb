# StratWeb 0.31.3 — управляемые соединения DuckDB

Локальный релиз поверх рабочей версии 0.31.2. Миграций схемы и изменений зависимостей нет.
Существовавшие незакоммиченные изменения сохранены. Публикация и Git tag не выполнялись.

## Жизненный цикл и конкурентный доступ

Все persistence-репозитории используют один менеджер на нормализованный абсолютный путь.
Он выдаёт соединение исключительно одному выполняющемуся scope; одновременно работающие
потоки получают разные handles. Свободное соединение можно передать следующему потоку
только после завершения предыдущего scope. Общего DuckDB cursor для потоков нет.
До четырёх свободных соединений сохраняются для повторного использования. Число активных
соединений определяется текущим спросом: writer или schema owner не ожидает свободный слот,
который мог бы удерживать ожидающий этих же замков reader.

Все обычные соединения открываются с `read_only=False` через общий helper.
Read-only аудит и проверки storage migration выполняются в отдельном maintenance scope:
writer и schema gate исключают обычные операции, пул закрывается, временное read-only
соединение закрывается до снятия gate. Read-only backup использует такой же gate.
Поэтому разные конфигурации не сосуществуют для одного файла внутри приложения.

Записи всех репозиториев используют общий writer coordinator. Существующие атомарные
транзакции сохранения/удаления сохранены. Возврат соединения откатывает незавершённую
транзакцию; исключение из scope приводит к удалению handle из пула. После успешного
commit/reset handle может быть переиспользован. Данные материализуются внутри scope.

`DuckDBMatchRepository.read_session()` сначала обеспечивает готовность схемы, затем держит
одно соединение, schema read gate и одну MVCC-транзакцию для всех связанных чтений этого
потока, включая другие репозитории того же пути. Вложенные read-session используют тот же
handle и снимок. Полная сборка библиотеки, обзора и начального/следующего блока playback
обёрнута в такой scope. Restart recovery import jobs выполняется до снимка библиотеки,
поскольку может менять статусы. Repository writes и миграции из read scope отклоняются
до захвата writer: порядок reader → writer больше не может заблокировать миграцию.
Ожидающий миграцию reader получает текущий пул после открытия gate.

Пример синхронной композиции (scope нельзя переносить между потоками или через `await`):

```python
matches = DuckDBMatchRepository(database_path)
labels = DuckDBTeamNameRepository(database_path)
with matches.read_session():
    match = matches.get_match(match_id)
    players = matches.get_players(match_id)
    team_labels = labels.list_for_match(match_id)
```

`matches.close()` / `close_database_connections(path)` освобождают свободные handles сразу;
уже выданные handles закрываются при возврате, без прерывания выполняющегося SQL.
После явного закрытия следующее обращение может создать новый пул. Перед заменой файла
базы нужно закрыть пул. Shutdown приложения вызывает закрытие после import manager;
worker, завершившийся после ограниченного ожидания shutdown, закрывает и поздно открытые
соединения на своей конечной границе. На выходе процесса есть общий atexit cleanup.

## Сравнительные измерения

Первый baseline снят **до изменения исходников 0.31.2**. Тот же benchmark проверен
с сохранённым wheel 0.31.2; baseline воспроизводим без переустановки рабочего окружения.
Основные сравнительные числа: 7 HTTP-запросов в каждом режиме и медиана; Windows,
Python 3.13.14, DuckDB 1.5.4, неизменные зависимости. Настоящие FastAPI endpoints,
DuckDB и модели ответа, без подмены запросов или результатов.

Детерминированный fixture: 8 матчей по 2 раунда и 2 игрока; целевой матч имеет
Analytics, Temporal, Spatial, projectile и utility-effect данные. Playback запрашивает
первый блок с `limit=64`. Это замер накладных расходов сборки на небольшом fixture,
а не производительности полной реальной CS2 демки. Доступная локальная база содержит
2 матча без spatial query rows; её данные не изменялись и для playback не использовались.

`total_ms` включает сборку HTTP-ответа, Python-модели и HTML/JSON.
`sql_ms` — сумма времени DuckDB `execute`/`executemany` и материализации
`fetch*`/`pl`, без создания Pydantic-моделей и шаблонизации. Включены BEGIN/COMMIT
и очистка транзакции; открытие/закрытие соединений исключены из SQL.
`connect_ms` и число реальных вызовов `duckdb.connect` измеряются отдельно.
В warm режиме перед 7 запросами выполнен один непротоколируемый прогрев.
В cold режиме перед каждым запросом закрыт пул; это холодный пул при прогретой
схеме, приложении и файловом кеше, не полный холодный старт процесса/ОС.
Штатные application caches не сбрасываются ни в одной версии.

| Операция | Полный запрос, мс (0.31.2 → 0.31.3) | SQL, мс | Новые подключения | Ускорение |
| --- | ---: | ---: | ---: | ---: |
| Библиотека /ui | 3050.2 → 131.5 | 131.9 → 93.1 | 85 → 0 | 23.2× |
| Обзор матча | 986.9 → 58.8 | 58.8 → 43.0 | 27 → 0 | 16.8× |
| Playback, limit=64 | 183.0 → 11.6 | 8.7 → 5.2 | 5 → 0 | 15.8× |

| Операция, cold pool | Полный запрос, мс | SQL, мс | Новые подключения | Время открытия, мс |
| --- | ---: | ---: | ---: | ---: |
| Библиотека /ui | 3338.0 → 170.4 | 142.2 → 95.3 | 85 → 1 | 2830.6 → 33.7 |
| Обзор матча | 991.1 → 98.4 | 62.3 → 49.3 | 27 → 1 | 839.7 → 32.4 |
| Playback, limit=64 | 188.8 → 57.3 | 9.4 → 9.4 | 5 → 1 | 159.4 → 35.5 |

Время открытия соединений в warm режиме сократилось с 2645,3 / 835,3 / 153,4 мс
до 0 для библиотеки / обзора / playback. SQL statements: 85 → 89, 33 → 36, 7 → 10;
добавлены транзакционные границы и reset, число полезных запросов не сокращалось.
Закрытия внутри каждого запроса: 85/27/5 → 0; свободный handle освобождается
при закрытии пула/shutdown, активный — после возврата. Вызов закрытия перед cold
замером не включён в время запроса ни в одной версии.

Финальный замер 0.31.3 выполнен после завершения всех регрессий, без их фоновой
нагрузки. На этом fixture warm ускорение составляет 23,2× / 16,8× / 15,8×.
Основной выигрыш даёт устранение подключения на каждый repository method.

Сырые исходные замеры: `.runtime/release-check/connections-0.31.2.json`.
Сырые замеры новой версии: `.runtime/release-check/connections-0.31.3.json`.
Повтор baseline из wheel: `.runtime/release-check/connections-0.31.2-repeat.json`;
он выполнялся параллельно регрессиям и служит дополнительной проверкой счётчиков.
Каждый JSON хранит все 7 samples, число SQL statements, подключения/закрытия
и время подключения. Основная таблица использует исходный baseline.

Воспроизведение:

```powershell
.venv/Scripts/python.exe scripts/benchmark_connections.py --output .runtime/release-check/connections-0.31.3.json
.venv/Scripts/python.exe scripts/benchmark_connections.py --baseline-wheel .runtime/release-check/dist/stratweb-0.31.2-py3-none-any.whl --output .runtime/release-check/connections-0.31.2-repeat.json
```

## Проверки

Семь новых pytest-проверок покрывают переиспользование соединений несколькими
repository instances, nested read-session, единообразие конфигурации, предел idle pool,
rollback незавершённой транзакции и ошибки до commit, очистку thread-local после SQL error,
shutdown и освобождение файла, позднее завершение worker.

Event-controlled probe запускается в killable subprocess с 45-секундным пределом:
три reader одновременно удерживают разные соединения и видят старый снимок после commit
writer; новый scope видит новое значение. Шесть writers выполняют по 20 транзакций
над одной строкой без потерянных обновлений. Проверены атомарная замена canonical match
во время связанного чтения, ожидание полной read-session перед миграцией, закрытие при
активном reader, возврат к read-write режиму после maintenance и reader, ожидающий gate
при замене пула. Сохранены регрессии импорта, отмены, migrations и параллельных HTTP reads.

Модель конкурентного доступа согласуется с [документацией DuckDB Python](https://duckdb.org/docs/current/clients/python/overview) и [MVCC внутри одного процесса](https://duckdb.org/docs/current/connect/concurrency). Coordination является внутрипроцессной.


## Окончательный локальный release gate

Команда: `./scripts/release_check.ps1 -AllowDirty` — успешно.
**484 passed, 6 integration tests deselected**, **172.60 с**.
Прошли lockfile/frozen sync, dependency consistency, Ruff format/lint (319 файлов),
strict mypy (245 source files), JavaScript syntax (20 файлов), application/version
check, HTTP smoke (`/health: 200`, `/ui: 200`), Golden Corpus contract,
wheel build и Compose validation. Дополнительно проверены содержимое wheel,
metadata/runtime 0.31.3, актуальный lifecycle внутри wheel и `git diff --check`.

Шесть integration tests требуют внешние demo inputs и не запускались.
Golden Corpus contract валиден, product readiness остаётся `blocked`, как в 0.31.2.
Это не препятствие проверенному локальному техническому релизу и не подтверждение
продуктовой готовности на новых реальных демках.

Лог: `.runtime/release-check/0.31.3-gate-final.log`.
Wheel: `.runtime/release-check/dist/stratweb-0.31.3-py3-none-any.whl`.
SHA-256: `3cf5f173fa460ede375779a73ea05569581203f06ad9d1a0478d56bb35ba8b81`.
Рядом сохранён `stratweb-0.31.3-py3-none-any.whl.sha256`.
Версии pyproject, lockfile, runtime и wheel согласованы: **0.31.3**.
