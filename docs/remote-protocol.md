# HTTP API vertov-dl 0.1.0-alpha.1

Однопользовательская сессия с ключом. API под /api; /healthz публично сообщает status/version. Изменения требуют допустимого Origin; пути/исходные URL/CDN URL не выдаются. FileResponse поддерживает attachment/Range и X-Artifact-SHA256.

| Запрос | Назначение |
|---|---|
| POST /api/login {token}, POST /api/logout | Сессия |
| GET /api/status | Версия, uptime, cookies и capabilities |
| PUT /api/cookies {content}, DELETE /api/cookies | Импорт/удаление с инвалидированием кэша |
| POST /api/probes {url, force?:boolean} | Новая probe-задача или completed из кэша |
| POST /api/downloads {probe_id, preset} либо {probe_id, format_id} | Загрузка, скрытие исходного probe |
| GET /api/jobs | Видимая очередь/история |
| GET /api/events | SSE snapshots jobs, keepalive и session-expired |
| POST /api/jobs/{id}/cancel | Отмена с очисткой частей |
| POST /api/jobs/{id}/retry | Failed download: тот же ID/каталог/preset; остальные — новая задача |
| DELETE /api/jobs/{id} | Failed download: удалить части и скрыть; completed: только скрыть |
| GET /api/jobs/{id}/file | Выдача файла, нормализованное имя, аренда на время ответа |
| GET /api/jobs/{id}/thumbnail | Авторизованное превью |
| GET /api/library | items,total_bytes,max_bytes,retention_hours |
| POST /api/library/{id}/audio | Локальная конвертация видео в MP3; дубли активной задачи не создаются |
| DELETE /api/library/{id} | Удалить готовый файл или failed conversion с сервера |

Состояния: queued, probing, downloading, processing, completed, failed, cancelled, expired. details может быть частичным: поля метаданных и formats появляются только после успешного извлечения. Метрики queue_seconds/extraction_seconds/thumbnail_seconds числовые и не содержат сетевых секретов.

Кэш успехов 300 секунд в памяти, только для того же source. force/retry обходят его. Поколения cookies и номера запросов исключают поздние записи старых ответов. Перезапуск очищает кэш. Потоки перед скачиванием извлекаются заново.

В библиотеке готовые файлы и pending/failed conversion. У незавершённой конвертации size=0/expires_at=0, нужно учитывать state. details.artifact_media заполняется фоном: media_type,video_codec,audio_codec,width,height,fps. Отсутствие блока не означает ошибку загрузки. Обогащение не меняет updated/TTL. Технические details.conversion_source/conversion_input управляют локальной конвертацией.

Лимиты: MEDIA_LIBRARY_MAX_BYTES / MEDIA_RETENTION_HOURS (10 ГиБ/30 дней); MEDIA_TEMPORARY_MAX_BYTES / MEDIA_TEMPORARY_RETENTION_HOURS (10 ГиБ/7 дней). Очистка частей старых failed переводит задачу в expired. Активная HTTP-выдача защищена от удаления; между отдельными Range-запросами аренда не сохраняется.

HTTP: 401 вход, 403 Origin, 409 состояние/очередь/аренда, 410 отсутствующий файл, 413 тело, 422 параметры, 429 вход, 503 файловая ошибка. Сырые исключения и stderr не возвращаются.

Схема БД пока без миграций таблиц: расширения в существующем details JSON. Нет ack сохранения на диск, multi-user, idempotency keys и стабильного внешнего API-контракта.

### Повторный запуск отменённой загрузки

POST /api/downloads принимает необязательный replace_job_id. Он переиспользует только видимую cancelled-задачу download с тем же source, после завершения её worker. Выбранные preset/format_id валидируются по probe; ID и created сохраняются, progress/error/artifact/sha сбрасываются. Новая запись не создаётся. POST /api/jobs/{id}/retry для cancelled-download также сохраняет ID. Для failed сохраняется прежняя логика продолжения.
