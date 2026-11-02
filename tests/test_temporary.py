import time

from media_loader.config import Settings
from media_loader.store import Store
from media_loader.temporary import TemporaryFiles

TOKEN = "synthetic-token-at-least-24-chars"


def test_temporary_quota_removes_oldest_failure_not_active_or_library(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN, temporary_max_bytes=1024)
    store = Store(tmp_path)
    jobs = []
    for state in ["failed", "failed", "downloading", "completed"]:
        job = store.create("download", "https://example.org/synthetic")
        folder = tmp_path / "jobs" / job["id"]
        folder.mkdir(parents=True)
        (folder / "media.part").write_bytes(b"x" * 500)
        store.update(job["id"], state=state)
        jobs.append(job)
    TemporaryFiles(settings, store).enforce()
    assert store.get(jobs[0]["id"])["state"] == "expired"
    assert not (tmp_path / "jobs" / jobs[0]["id"]).exists()
    assert (tmp_path / "jobs" / jobs[1]["id"]).is_dir()
    assert store.get(jobs[2]["id"])["state"] == "downloading"
    assert store.get(jobs[3]["id"])["state"] == "completed"
    store.engine.dispose()


def test_expired_parts_clear_but_filesystem_failure_retains_record(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN, temporary_retention_hours=1)
    store = Store(tmp_path)
    job = store.create("download", "https://example.org/synthetic")
    folder = tmp_path / "jobs" / job["id"]
    folder.mkdir(parents=True)
    store.update(job["id"], state="failed")
    now = time.time() + 7200
    import shutil

    original = shutil.rmtree

    def denied(*args, **kwargs):
        raise PermissionError("fixture")

    monkeypatch.setattr("media_loader.temporary.shutil.rmtree", denied)
    TemporaryFiles(settings, store).enforce(now)
    assert store.get(job["id"])["state"] == "failed"
    monkeypatch.setattr("media_loader.temporary.shutil.rmtree", original)
    TemporaryFiles(settings, store).enforce(now)
    assert store.get(job["id"])["state"] == "expired"
    assert not folder.exists()
    store.engine.dispose()
