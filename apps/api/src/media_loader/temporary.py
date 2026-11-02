"""Bounded retention of resumable failed downloads."""

import re
import shutil
import time


def folder_size(folder):
    if not folder.is_dir() or folder.is_symlink():
        return 0
    total = 0
    for file in folder.rglob("*"):
        if file.is_file() and not file.is_symlink():
            try:
                total += file.stat().st_size
            except FileNotFoundError:
                pass
    return total


class TemporaryFiles:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store

    def enforce(self, now=None):
        now = time.time() if now is None else now
        jobs = self.store.all()
        root = (self.settings.data_dir / "jobs").resolve()
        candidates = []
        total = 0
        for job in jobs:
            if job["kind"] != "download" or job["state"] in {"completed", "expired"}:
                continue
            folder = root / job["id"]
            size = folder_size(folder)
            total += size
            if job["state"] == "failed":
                candidates.append((job, folder, size))
        for job, folder, size in sorted(candidates, key=lambda entry: entry[0]["updated"]):
            expired = job["updated"] + self.settings.temporary_retention_hours * 3600 <= now
            if not expired and total <= self.settings.temporary_max_bytes:
                continue
            if (
                not re.fullmatch(r"[a-f0-9]{32}", job["id"])
                or folder.is_symlink()
                or folder.resolve().parent != root
            ):
                continue
            try:
                shutil.rmtree(folder)
            except FileNotFoundError:
                pass
            except OSError:
                continue
            total -= size
            self.store.update(
                job["id"],
                state="expired",
                artifact=None,
                message="Временные файлы удалены по сроку хранения"
                if expired
                else "Временные файлы удалены по лимиту хранения",
            )
