# ADR-0002: WebUI, Python и существующий v2rayA

Дата: 2026-11-01. Статус: принято пользователем. Заменяет технологическую часть ADR-0001; серверное выполнение probe/download сохраняется.

## Решение

Целевой стек: React/TypeScript/Vite, Python/FastAPI/Pydantic, Python API yt-dlp в отдельных процессах, SQLite/SQLAlchemy/Alembic, SSE и Docker Compose. Rust/Tauri, трей, хоткеи и Explorer исключаются из целевой архитектуры. Текущий Rust/Tauri-каркас исторический и требует миграции до разработки загрузчика.

Redis/Celery/PostgreSQL не требуются для одного сервера. Очередь персистентная; FastAPI BackgroundTasks не заменяет её. Frontend собирается в статические файлы и раздаётся API. Выполнение задачи не зависит от открытой вкладки.

## Домашняя сеть

В существующем Compose v2rayA использует host network, прокси слушают loopback. Hook исключает Docker-интерфейсы из transparent proxy. Первый интеграционный профиль: Linux host network и явный SOCKS5 proxy 127.0.0.1:20170. Не переносить VPN-подписки, конфигурацию v2rayA или привилегии VPN в образ приложения. Для приложения не нужны privileged, NET_ADMIN, Docker socket и /dev/net/tun.

Host network уменьшает сетевую изоляцию. До download API обязательны авторизация, квоты и SSRF-защита. Для дальнейшей изоляции можно выделить bridge worker и контролируемый proxy relay; это отдельное решение и изменение инфраструктуры.

Явный proxy не должен иметь fallback в direct. Для полного fail-closed нужны сетевые меры для всех дочерних процессов. Существующий failover VPN не изменялся и не проверялся отключением узлов.

## Доставка в браузер

HTTP attachment/Range/ETag, потоковая выдача без загрузки всего файла в память JavaScript. Обычный браузер не даёт надёжного подтверждения сохранения и проверки файла на диске: прежний автоматический ack после доставки исключён. Удаление по TTL или вручную; HTTP-ответ не считается подтверждением локального сохранения.

## Источники

- https://docs.docker.com/engine/network/drivers/host/
- https://github.com/yt-dlp/yt-dlp#embedding-yt-dlp
- https://fastapi.tiangolo.com/tutorial/background-tasks/
