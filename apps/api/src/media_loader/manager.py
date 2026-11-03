import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import time

from .library import Library
from .store import public_job
from .temporary import TemporaryFiles

ACTIVE = {"queued", "probing", "downloading", "processing"}


async def stop_process(process):
    if os.name == "posix":
        # Workers start a new session, so their PID is also their PGID.
        pgid = process.pid
        if pgid <= 1 or pgid == os.getpgrp():
            raise ValueError("Unsafe worker process group")
        try:
            os.killpg(pgid, signal.SIGTERM)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                os.killpg(pgid, 0)
                await asyncio.sleep(0.05)
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await process.wait()
        return

    if process.returncode is not None:
        return
    try:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
        await asyncio.wait_for(process.wait(), 5)
    except (TimeoutError, ProcessLookupError):
        if process.returncode is None:
            process.kill()
        await process.wait()


class Manager:
    def __init__(self, settings, store, guard_port, metadata_cache=None):
        self.settings, self.store, self.guard_port = settings, store, guard_port
        self.stopping = False
        self.current_ids = set()
        self.metadata_cache = metadata_cache

    def recover(self):
        for job in self.store.all():
            if job["state"] in ACTIVE - {"queued"}:
                self.store.update(
                    job["id"],
                    state="failed",
                    error_code="interrupted",
                    message="Работа прервана перезапуском. Можно повторить задачу.",
                )

    async def run(self):
        tasks = {}
        last_cleanup = 0.0

        async def execute(job):
            try:
                await self.execute(job)
            finally:
                self.current_ids.discard(job["id"])

        try:
            while not self.stopping:
                if time.monotonic() - last_cleanup >= 5:
                    self.expire()
                    last_cleanup = time.monotonic()
                for job_id in list(tasks):
                    task, _ = tasks[job_id]
                    if task.done():
                        try:
                            await task
                        except Exception:
                            logging.getLogger(__name__).exception(
                                "Task %s failed unexpectedly", job_id
                            )
                            try:
                                if self.store.get(job_id)["state"] in ACTIVE:
                                    self.store.update(
                                        job_id,
                                        state="failed",
                                        error_code="worker",
                                        message="Не удалось завершить обработку.",
                                    )
                            except Exception:
                                logging.getLogger(__name__).exception(
                                    "Could not record task failure"
                                )
                        finally:
                            del tasks[job_id]
                queued = [
                    job
                    for job in reversed(self.store.all())
                    if job["state"] == "queued" and job["id"] not in self.current_ids
                ]
                for job in queued:
                    kind = job["kind"]
                    limit = 2 if kind == "probe" else 1
                    if sum(entry[1] == kind for entry in tasks.values()) >= limit:
                        continue
                    self.current_ids.add(job["id"])
                    tasks[job["id"]] = (asyncio.create_task(execute(job)), kind)
                await asyncio.sleep(0.1)
        finally:
            for task, _ in tasks.values():
                task.cancel()
            await asyncio.gather(*(task for task, _ in tasks.values()), return_exceptions=True)
            self.current_ids.clear()

    def expire(self):
        Library(self.settings, self.store).enforce()
        TemporaryFiles(self.settings, self.store).enforce()
        cutoff = time.time() - self.settings.retention_hours * 3600
        for job in self.store.all():
            if job["kind"] == "download" and job["state"] == "completed" and job["artifact"]:
                continue  # Library owns media expiry and retries failed filesystem removals.
            if (
                job["kind"] == "download"
                and job["state"] == "failed"
                and not (job.get("details") or {}).get("_queue_hidden")
            ):
                continue
            if job["state"] not in ACTIVE and job["updated"] < cutoff:
                shutil.rmtree(self.settings.data_dir / "jobs" / job["id"], ignore_errors=True)
                if job["state"] != "expired":
                    self.store.update(
                        job["id"], state="expired", artifact=None, message="Срок хранения истёк"
                    )

    async def execute(self, job):
        job_id = job["id"]
        directory = (self.settings.data_dir / "jobs" / job_id).resolve()
        process = None
        spec_path = directory / "spec.json"
        try:
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Failed downloads resume in their existing directory; probes are new jobs.
            spec = {
                "kind": job["kind"],
                "url": job["source"],
                "preset": job["preset"],
                "directory": str(directory),
                "max_bytes": self.settings.max_file_bytes,
                "proxy": f"socks5h://127.0.0.1:{self.guard_port}",
                "use_cookies": (self.settings.data_dir / "secrets" / "cookies.enc").is_file(),
            }
            conversion_input = (job.get("details") or {}).get("conversion_input")
            if conversion_input:
                spec["conversion_input"] = conversion_input
            spec_path, result_path = directory / "spec.json", directory / "result.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            self.store.patch_details(
                job_id, {"queue_seconds": round(max(0, time.time() - job["created"]), 3)}
            )
            self.store.update(job_id, state="probing", message="Получение данных через прокси")
            if shutil.disk_usage(directory).free < self.settings.reserve_bytes:
                raise ValueError("disk")
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "media_loader.convert" if conversion_input else "media_loader.task",
                str(spec_path),
                str(result_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=os.name == "posix",
                limit=262144,
            )

            async def events():
                async for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if self.store.get(job_id)["state"] == "cancelled":
                        return
                    if event.get("event") == "metadata" and job["kind"] == "probe":
                        current = self.store.get(job_id)
                        self.store.update(
                            job_id,
                            state="completed",
                            title=event["details"]["title"],
                            details={**(current.get("details") or {}), **event["details"]},
                            message="Метаданные получены",
                        )
                        if self.metadata_cache:
                            self.metadata_cache.put(self.store.get(job_id))
                    elif event.get("event") == "progress":
                        self.store.update(job_id, progress=event["data"])
                    elif event.get("state") in {"downloading", "processing"}:
                        self.store.update(job_id, state=event["state"], message="Выполняется")

            reader = asyncio.create_task(events())
            deadline = time.monotonic() + self.settings.task_timeout
            try:
                while process.returncode is None:
                    if self.store.get(job_id)["state"] == "cancelled":
                        return
                    if time.monotonic() > deadline:
                        raise ValueError("timeout")
                    used = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                    if (
                        used > self.settings.max_file_bytes * 3
                        or shutil.disk_usage(directory).free < self.settings.reserve_bytes
                    ):
                        raise ValueError("disk")
                    await asyncio.sleep(0.25)
                await reader
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            if self.store.get(job_id)["state"] == "completed" and (
                process.returncode != 0 or not result_path.exists()
            ):
                return
            if process.returncode != 0 or not result_path.exists():
                raise ValueError("worker")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if not result["ok"]:
                if self.store.get(job_id)["state"] == "completed":
                    return
                self.store.update(
                    job_id,
                    state="failed",
                    error_code=result["error_code"],
                    message=result["message"],
                )
                return
            artifact = result.get("artifact")
            if artifact:
                path = (directory / artifact).resolve()
                if path.parent != directory or not path.is_file():
                    raise ValueError("worker")
            if self.store.get(job_id)["state"] != "cancelled":
                current_details = self.store.get(job_id).get("details") or {}
                if current_details.get("has_thumbnail") and (directory / "thumbnail.img").is_file():
                    result["details"].update(
                        has_thumbnail=True, thumbnail_mime=current_details.get("thumbnail_mime")
                    )
                self.store.update(
                    job_id,
                    state="completed",
                    title=result["details"].get("title", job["title"]),
                    details={**(self.store.get(job_id).get("details") or {}), **result["details"]},
                    artifact=artifact,
                    sha256=result.get("sha256"),
                    message="Файл готов на сервере" if artifact else "Метаданные получены",
                )
                if result["details"].get("has_thumbnail"):
                    self.propagate_thumbnail(
                        job_id, directory / "thumbnail.img", result["details"]["thumbnail_mime"]
                    )
                if self.metadata_cache:
                    self.metadata_cache.put(self.store.get(job_id))
        except asyncio.CancelledError:
            if self.store.get(job_id)["state"] == "completed":
                raise
            self.store.update(
                job_id,
                state="failed",
                error_code="interrupted",
                message="Сервис остановлен. Можно повторить задачу.",
            )
            raise
        except (OSError, ValueError, KeyError) as error:
            if self.store.get(job_id)["state"] == "completed":
                return
            reason = str(error) if isinstance(error, ValueError) else "worker"
            code, message = {
                "disk": ("disk_limit", "Недостаточно места или превышен лимит временных файлов."),
                "timeout": (
                    "timeout",
                    "Превышено время выполнения задачи. Можно продолжить загрузку.",
                ),
            }.get(reason, ("worker", "Не удалось завершить обработку. Можно повторить задачу."))
            self.store.update(job_id, state="failed", error_code=code, message=message)
        finally:
            if process:
                await stop_process(process)
            if spec_path.is_file():
                spec_path.unlink(missing_ok=True)
            current = self.store.get(job_id)
            if current["state"] != "completed" and not (
                current["kind"] == "download" and current["state"] == "failed"
            ):
                shutil.rmtree(directory, ignore_errors=True)

    def propagate_thumbnail(self, job_id, source, mime):
        parents = {job_id}
        pending = self.store.all()
        while pending:
            matched = [
                child
                for child in pending
                if (child.get("details") or {}).get("source_probe_id") in parents
                and child["id"] not in parents
            ]
            if not matched:
                break
            for child in matched:
                parents.add(child["id"])
                pending.remove(child)
                if child["state"] in {"cancelled", "expired"}:
                    continue
                target = self.settings.data_dir / "jobs" / child["id"]
                if not target.is_dir():
                    continue
                try:
                    shutil.copyfile(source, target / "thumbnail.img")
                    self.store.patch_details(
                        child["id"], {"has_thumbnail": True, "thumbnail_mime": mime}
                    )
                except OSError:
                    pass

    def snapshot(self):
        return [public_job(job) for job in self.store.visible()]
