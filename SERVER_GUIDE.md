# Запуск локального сервера StratWeb

Для приложения нужен только один процесс — backend FastAPI. Он одновременно отдаёт API,
HTML-интерфейс, JavaScript, CSS и изображения карт. Отдельный frontend-сервер, Docker и
запущенный CS2 не нужны.

## Обычный запуск в PowerShell

Откройте PowerShell и выполните:

```powershell
Set-Location "C:\Projects\StratWeb"
.\scripts\start_server.ps1
```

После строки `Uvicorn running on http://127.0.0.1:8000` откройте:

- библиотека матчей: <http://127.0.0.1:8000/ui>;
- проверяемый Overpass, раунд 1:
  <http://127.0.0.1:8000/ui/spatial/dba336bb-dc00-5974-bebe-3525d39a6ef4/rounds/1>.

Окно PowerShell должно оставаться открытым. Для остановки нажмите `Ctrl+C`.

Скрипт намеренно вызывает `.venv\Scripts\python.exe` и передаёт `src` как app directory.
Поэтому не требуется выполнять `Activate.ps1`, и случайный системный Python из
`WindowsApps` не используется даже после переноса проекта.

## Где лежат данные

Runtime-данные (DuckDB-база и изображения карт) хранятся **вне OneDrive** в
`C:\Users\rausa\StratWeb-data`, потому что конфликты синхронизации могут повредить
файлы DuckDB. Пути заданы в `.env` проекта и в параметрах `start_server.ps1`
(`-DatabasePath`, `-MapOverviewDir`).

## Режим разработки

Автоперезапуск после изменения Python-файлов:

```powershell
.\scripts\start_server.ps1 -Reload
```

Другой порт:

```powershell
.\scripts\start_server.ps1 -Port 8010
```

Тогда адрес будет <http://127.0.0.1:8010/ui>.

## Docker Compose

```powershell
docker compose up --build
```

Контейнер слушает `0.0.0.0` только внутри своей сети, а Compose публикует порт на
`127.0.0.1:8000`. Это намеренное ограничение: в версии 0.4.x нет пользовательской
аутентификации. Не меняйте host bind на `0.0.0.0`, не открывайте порт на роутере и не
пропускайте приложение через публичный tunnel. Подробности: [SECURITY.md](SECURITY.md).

## Если сервер не запускается

Проверить, занят ли порт:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen
```

Если команда показывает процесс, сервер уже работает либо порт занят. Сначала попробуйте открыть
<http://127.0.0.1:8000/ui>. Не запускайте второй экземпляр на том же порту.

Проверить проектный Python и `uvicorn`:

```powershell
.\.venv\Scripts\python.exe -c "import stratweb, uvicorn; print('imports OK')"
```

Типичная неправильная команда выглядит как `python -m uvicorn ...`, запущенная из
`C:\WINDOWS\system32`. В этом случае Windows выбирает глобальный Python без зависимостей проекта,
а относительные пути вроде `.\data` считаются от `system32`.
