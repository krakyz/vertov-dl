import shutil
import time

from .store import public_job


class Library:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def items(self):
        result = []
        for job in self.store.all():
            if job["kind"] != "download" or job["state"] != "completed" or not job["artifact"]:
                continue
            folder = (self.settings.data_dir / "jobs" / job["id"]).resolve()
            path = (folder / job["artifact"]).resolve()
            if path.parent != folder or not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                continue
            result.append(
                {
                    **public_job(job),
                    "size": size,
                    "completed_at": job["updated"],
                    "expires_at": job["updated"] + self.settings.retention_hours * 3600,
                }
            )
        return sorted(result, key=lambda item: item["completed_at"], reverse=True)

    def snapshot(self):
        items = self.items()
        for job in self.store.all():
            if (
                (job.get("details") or {}).get("conversion_source")
                and job["state"] in {"queued", "probing", "processing", "failed"}
                and not (job.get("details") or {}).get("_queue_hidden")
            ):
                items.append(
                    {**public_job(job), "size": 0, "completed_at": job["created"], "expires_at": 0}
                )
        items.sort(key=lambda item: item["completed_at"], reverse=True)
        return {
            "items": items,
            "total_bytes": sum(item["size"] for item in items),
            "max_bytes": self.settings.library_max_bytes,
            "retention_hours": self.settings.retention_hours,
        }

    def remove(self, job_id, reason="Файл удалён из библиотеки"):
        if self.store.deliveries.get(job_id, 0):
            return False
        try:
            shutil.rmtree(self.settings.data_dir / "jobs" / job_id)
        except FileNotFoundError:
            pass
        except OSError:
            return False
        self.store.update(job_id, state="expired", artifact=None, message=reason)
        return True

    def enforce(self, now=None):
        now = time.time() if now is None else now
        items = self.items()
        total = sum(item["size"] for item in items)
        for item in sorted(items, key=lambda item: item["completed_at"]):
            expired = item["expires_at"] <= now
            if expired or total > self.settings.library_max_bytes:
                removed = self.remove(
                    item["id"], "Срок хранения истёк" if expired else "Удалено по лимиту библиотеки"
                )
                if removed:
                    total -= item["size"]
