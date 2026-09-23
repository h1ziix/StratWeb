# Release 0.29.2 — Release Integrity

## Цель

Сделать локальный релиз воспроизводимым до начала следующих продуктовых изменений. Эта версия
не меняет аналитику, API-контракты, схему DuckDB или сохранённые пользовательские данные.

## Исправления

- regression-тест upgrade `canonical schema 1.0.0 → 1.2.0` использует committed fixture из
  `tests/fixtures` и не зависит от текущей рабочей директории;
- `scripts/start_server.ps1` больше не содержит пути конкретного пользователя;
- launcher выбирает runtime paths в порядке: явный параметр, переменная окружения, default в
  `%LOCALAPPDATA%\StratWeb`;
- каталоги базы и map assets создаются автоматически; пустой каталог map assets допустим;
- версии в package metadata, runtime и lockfile синхронизированы как `0.29.2`.

## Release gate

`scripts/release_check.ps1` проверяет:

1. lockfile и frozen environment;
2. dependency consistency;
3. Ruff format/lint и strict mypy;
4. синтаксис всех frontend JavaScript-файлов через `node --check`;
5. полный набор non-integration pytest;
6. import application и совпадение package/runtime version;
7. HTTP smoke `/health` и `/ui` на изолированной временной базе;
8. Golden Corpus manifest contract;
9. wheel build;
10. Docker Compose validation, если проверка контейнера не отключена явно.

CI запускает gate на Windows и Linux, а отдельный job валидирует Compose и собирает Docker image.

## Ограничение Golden Corpus

Manifest может быть технически валиден при product status `blocked`. Release 0.29.2 не объявляет
real-data аналитику принятой: для acceptance по-прежнему нужны подтверждённые матчи, обязательное
source/edge-case coverage и analyst labels.
