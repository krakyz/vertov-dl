import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import time
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import __version__
from .config import Settings
from .cookies import CookieError, CookieVault
from .filenames import download_filename
from .library import Library
from .manager import ACTIVE, Manager
from .metadata_cache import MetadataCache
from .network import Gateway
from .store import Store, public_job


class LeasedFileResponse(FileResponse):
    def __init__(self, *args, store, job_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job_id = store, job_id

    async def __call__(self, scope, receive, send):
        leases = self.store.deliveries
        leases[self.job_id] = leases.get(self.job_id, 0) + 1
        try:
            await super().__call__(scope, receive, send)
        finally:
            leases[self.job_id] -= 1
            if not leases[self.job_id]:
                del leases[self.job_id]


class Login(BaseModel):
    token: SecretStr


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=4096)
    force: bool = False


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid")
    probe_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    preset: Literal["360", "720", "1080", "best", "audio"] = "720"
    format_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,80}$")


def validate_url(value):
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 80, 443)
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Нужна HTTP(S)-ссылка без логина и нестандартного порта")
    return value


def create_app(settings: Settings, *, run_manager=True):
    started = time.monotonic()
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = Store(settings.data_dir)
    cookies = CookieVault(settings)
    library = Library(settings, store)
    metadata_cache = MetadataCache()

    key = hashlib.sha256(settings.auth_token.get_secret_value().encode()).digest()
    gateway = Gateway(settings.proxy_url)
    manager = None

    def signature(expires):
        return hmac.new(key, expires.encode(), "sha256").hexdigest()

    def authenticated(request: Request):
        value = request.cookies.get("media_session", "")
        if not re.fullmatch(r"[0-9]{1,12}\.[a-f0-9]{64}", value):
            raise HTTPException(401, "Требуется вход")
        expires, _, digest = value.partition(".")
        if (
            not expires.isdigit()
            or int(expires) <= time.time()
            or not hmac.compare_digest(signature(expires), digest)
        ):
            raise HTTPException(401, "Требуется вход")

    @asynccontextmanager
    async def lifespan(app):
        nonlocal manager
        task = None
        enrichment = None
        if run_manager:
            port = await gateway.start(settings.guard_port)
            manager = Manager(settings, store, port, metadata_cache)
            manager.recover()
            task = asyncio.create_task(manager.run())
            from .artifact import enrich_library

            enrichment = asyncio.create_task(enrich_library(settings, store))
        try:
            yield
        finally:
            if enrichment:
                enrichment.cancel()
                await asyncio.gather(enrichment, return_exceptions=True)
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await gateway.stop()
            store.engine.dispose()

    app = FastAPI(
        title="vertov-dl",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.metadata_cache = metadata_cache
    attempts = []

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.method in {"POST", "DELETE", "PUT", "PATCH"}:
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                return Response(status_code=403)
            length = request.headers.get("content-length", "0")
            limit = 2 * 1024**2 if request.url.path == "/api/cookies" else 16384
            if not length.isdigit() or int(length) > limit:
                return Response(status_code=413)
            # Also cap chunked bodies before JSON parsing.
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > limit:
                    return Response(status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": __version__}

    @app.post("/api/login")
    async def login(body: Login, response: Response):
        now = time.monotonic()
        attempts[:] = [when for when in attempts if now - when < 60]
        if len(attempts) >= 10:
            raise HTTPException(429, "Слишком много попыток. Подождите минуту.")
        attempts.append(now)
        if not hmac.compare_digest(
            body.token.get_secret_value().encode(), settings.auth_token.get_secret_value().encode()
        ):
            raise HTTPException(401, "Неверный ключ")
        expires = str(int(time.time()) + 12 * 3600)
        response.set_cookie(
            "media_session",
            f"{expires}.{signature(expires)}",
            httponly=True,
            samesite="strict",
            secure=settings.secure_cookie,
            max_age=12 * 3600,
        )
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response):
        response.delete_cookie("media_session")
        return {"ok": True}

    def get_job(job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise HTTPException(404, "Задача не найдена")
        job = store.get(job_id)
        if not job:
            raise HTTPException(404, "Задача не найдена")
        return job

    def capacity(exclude_id=None):
        if sum(job["id"] != exclude_id for job in store.visible()) >= settings.max_jobs:
            raise HTTPException(409, "Лимит истории. Удалите старые задачи.")
        if sum(job["state"] in ACTIVE for job in store.all()) >= 20:
            raise HTTPException(409, "Очередь заполнена")

    def inherit_metadata(created, parent):
        details = dict(parent.get("details") or {})
        details.pop("_queue_hidden", None)
        probe_id = parent["id"] if parent["kind"] == "probe" else details.get("source_probe_id")
        details["source_probe_id"] = probe_id
        source = settings.data_dir / "jobs" / parent["id"] / "thumbnail.img"
        if (
            not source.is_file()
            and isinstance(probe_id, str)
            and re.fullmatch(r"[a-f0-9]{32}", probe_id)
        ):
            source = settings.data_dir / "jobs" / probe_id / "thumbnail.img"
        details["has_thumbnail"] = False
        if source.is_file() and source.stat().st_size <= 2 * 1024**2:
            try:
                target = settings.data_dir / "jobs" / created["id"]
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                if source.resolve() != (target / "thumbnail.img").resolve():
                    shutil.copyfile(source, target / "thumbnail.img")
                details["has_thumbnail"] = True
            except OSError:
                pass
        store.update(created["id"], title=parent["title"], details=details)
        return public_job(store.get(created["id"]))

    auth = [Depends(authenticated)]

    @app.get("/api/status", dependencies=auth)
    async def status():
        return {
            "version": __version__,
            "uptime_seconds": int(time.monotonic() - started),
            "cookies": cookies.status(),
            "capabilities": {
                "exact_formats": True,
                "cookie_import": True,
                "queue_archive": True,
                "library": True,
            },
        }

    @app.put("/api/cookies", dependencies=auth)
    async def import_cookies(request: Request):
        try:
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"content"}:
                raise ValueError
            status = cookies.save(body["content"])
            metadata_cache.invalidate()
            return status
        except CookieError as error:
            raise HTTPException(422, str(error)) from None
        except (ValueError, UnicodeError, TypeError):
            raise HTTPException(422, "Нужен cookies.txt в формате Netscape") from None
        except OSError:
            raise HTTPException(503, "Не удалось сохранить cookies на сервере") from None

    @app.delete("/api/cookies", dependencies=auth)
    async def delete_cookies():
        cookies.delete()
        metadata_cache.invalidate()
        return cookies.status()

    @app.get("/api/jobs", dependencies=auth)
    async def list_jobs():
        return [public_job(job) for job in store.visible()]

    @app.post("/api/probes", status_code=202, dependencies=auth)
    async def probe(body: Source):
        capacity()
        source = validate_url(body.url)
        cached = None if body.force else metadata_cache.get(source, store)
        created = store.create("probe", source)
        if cached:
            inherit_metadata(created, cached)
            store.update(created["id"], state="completed", message="Метаданные из кэша")
        else:
            metadata_cache.begin(created)
        return public_job(store.get(created["id"]))

    @app.post("/api/downloads", status_code=202, dependencies=auth)
    async def download(body: Download):
        capacity()
        parent = get_job(body.probe_id)
        if parent["kind"] != "probe" or parent["state"] != "completed":
            raise HTTPException(409, "Сначала получите метаданные")
        preset = body.preset
        if body.format_id:
            if "preset" in body.model_fields_set:
                raise HTTPException(422, "Укажите format_id или preset, не оба поля")
            formats = (parent.get("details") or {}).get("formats", [])
            if not any(item.get("id") == body.format_id for item in formats):
                raise HTTPException(422, "Такого формата нет в ответе probe")
            preset = f"format:{body.format_id}"
        created = store.create("download", parent["source"], preset)
        result = inherit_metadata(created, parent)
        store.dismiss(parent["id"])
        return result

    @app.post("/api/jobs/{job_id}/cancel", dependencies=auth)
    async def cancel(job_id: str):
        job = get_job(job_id)
        if job["state"] not in ACTIVE:
            raise HTTPException(409, "Задача уже завершена")
        store.update(job_id, state="cancelled", message="Отменено пользователем")
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry", status_code=202, dependencies=auth)
    async def retry(job_id: str):
        capacity(job_id)
        job = get_job(job_id)
        if job["state"] not in {"failed", "cancelled", "expired"}:
            raise HTTPException(409, "Повтор недоступен")
        if job["kind"] == "download" and job["state"] == "failed":
            if manager and job_id in manager.current_ids:
                raise HTTPException(409, "Подождите завершения работы")
            if (job.get("details") or {}).get("_queue_hidden"):
                raise HTTPException(409, "Задача удалена")
            store.update(
                job_id,
                state="queued",
                error_code=None,
                progress=None,
                artifact=None,
                sha256=None,
                message="В очереди",
            )
            return inherit_metadata(store.get(job_id), job)
        created = store.create(job["kind"], job["source"], job["preset"])
        if job["kind"] == "probe":
            metadata_cache.begin(created)
        return inherit_metadata(created, job) if job["kind"] == "download" else public_job(created)

    @app.delete("/api/jobs/{job_id}", dependencies=auth)
    async def delete(job_id: str):
        job = get_job(job_id)
        if job["state"] in ACTIVE:
            raise HTTPException(409, "Сначала отмените задачу")
        if manager and job_id in manager.current_ids:
            raise HTTPException(409, "Подождите завершения отмены")
        if job["kind"] == "download" and job["state"] == "failed":
            try:
                shutil.rmtree(settings.data_dir / "jobs" / job_id)
            except FileNotFoundError:
                pass
            except OSError:
                raise HTTPException(503, "Не удалось удалить временные файлы") from None
        store.dismiss(job_id)
        return {"ok": True}

    @app.get("/api/library", dependencies=auth)
    async def list_library():
        return library.snapshot()

    @app.post("/api/library/{job_id}/audio", status_code=202, dependencies=auth)
    async def convert_audio(job_id: str):
        parent = get_job(job_id)
        media = (parent.get("details") or {}).get("artifact_media") or {}
        if (
            parent["kind"] != "download"
            or parent["state"] != "completed"
            or not parent["artifact"]
            or parent["preset"] == "audio"
            or media.get("media_type") == "audio"
        ):
            raise HTTPException(409, "Нужно готовое видео")
        if media.get("media_type") == "video" and not media.get("audio_codec"):
            raise HTTPException(409, "В видео нет аудиодорожки")
        for existing in store.all():
            if (existing.get("details") or {}).get("conversion_source") == job_id and existing[
                "state"
            ] in ACTIVE:
                return public_job(existing)
        capacity()
        source_dir = (settings.data_dir / "jobs" / job_id).resolve()
        source = (source_dir / parent["artifact"]).resolve()
        if source.parent != source_dir or not source.is_file():
            raise HTTPException(409, "Исходный файл удалён")
        created = store.create("download", parent["source"], "audio")
        folder = settings.data_dir / "jobs" / created["id"]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        input_name = "source" + source.suffix
        try:
            os.link(source, folder / input_name)
        except OSError:
            store.update(
                created["id"], state="failed", message="Не удалось подготовить локальный файл"
            )
            store.dismiss(created["id"])
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(503, "Не удалось подготовить локальный файл") from None
        inherit_metadata(created, parent)
        details = dict(store.get(created["id"])["details"])
        details.pop("artifact_media", None)
        details.update(conversion_source=job_id, conversion_input=input_name)
        store.update(created["id"], details=details, message="Конвертация в очереди")
        return public_job(store.get(created["id"]))

    @app.delete("/api/library/{job_id}", dependencies=auth)
    async def delete_library_file(job_id: str):
        job = get_job(job_id)
        conversion_failed = job["state"] == "failed" and (job.get("details") or {}).get(
            "conversion_source"
        )
        if not conversion_failed and (
            job["kind"] != "download" or job["state"] != "completed" or not job["artifact"]
        ):
            raise HTTPException(409, "Готового файла нет")
        if manager and job_id in manager.current_ids:
            raise HTTPException(409, "Подождите завершения обработки")
        if store.deliveries.get(job_id):
            raise HTTPException(409, "Файл сейчас передаётся браузеру. Повторите позже.")
        if not library.remove(job_id):
            raise HTTPException(503, "Не удалось удалить файл с сервера. Повторите позже.")
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/file", dependencies=auth)
    async def artifact(job_id: str):
        job = get_job(job_id)
        if job["state"] != "completed" or not job["artifact"]:
            raise HTTPException(409, "Готового файла нет")
        folder = (settings.data_dir / "jobs" / job_id).resolve()
        path = (folder / job["artifact"]).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(410, "Файл уже удалён")
        filename = download_filename(job["title"], path.suffix, job_id)
        return LeasedFileResponse(
            path,
            store=store,
            job_id=job_id,
            filename=filename,
            media_type="application/octet-stream",
            headers={"X-Artifact-SHA256": job["sha256"] or ""},
        )

    @app.get("/api/jobs/{job_id}/thumbnail", dependencies=auth)
    async def thumbnail(job_id: str):
        job = get_job(job_id)
        details = job.get("details") or {}
        mime = details.get("thumbnail_mime")
        if not details.get("has_thumbnail") or mime not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise HTTPException(404, "Превью отсутствует")
        path = settings.data_dir / "jobs" / job_id / "thumbnail.img"
        if not path.is_file():
            raise HTTPException(404, "Превью отсутствует")
        return FileResponse(path, media_type=mime)

    @app.get("/api/events", dependencies=auth)
    async def events(request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                # Reconnect always starts with a complete snapshot; no lost-state cursor.
                try:
                    authenticated(request)
                except HTTPException:
                    yield "event: session-expired\ndata: {}\n\n"
                    return
                snapshot = json.dumps(
                    [public_job(job) for job in store.visible()], ensure_ascii=False
                )
                if snapshot != previous:
                    yield f"event: jobs\ndata: {snapshot}\n\n"
                    previous = snapshot
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    if settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")
    return app
