import time

from fastapi.testclient import TestClient
from media_loader.api import create_app
from media_loader.config import Settings
from media_loader.library import Library
from media_loader.store import Store, jobs
from sqlalchemy import update

TOKEN = "synthetic-library-token-123456789012345"


def media(store, directory, size, completed):
    job = store.create("download", "https://example.org/synthetic")
    folder = directory / "jobs" / job["id"]
    folder.mkdir(parents=True)
    (folder / "media.mp4").write_bytes(b"x" * size)
    store.update(job["id"], state="completed", artifact="media.mp4", title="Synthetic")
    with store.engine.begin() as connection:
        connection.execute(update(jobs).where(jobs.c.id == job["id"]).values(updated=completed))
    return job["id"], folder


def test_quota_evicts_oldest_media_even_when_hidden_from_queue(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN, library_max_bytes=1024)
    store = Store(tmp_path)
    now = time.time()
    oldest, old_folder = media(store, tmp_path, 600, now - 200)
    newest, new_folder = media(store, tmp_path, 600, now - 100)
    store.dismiss(oldest)
    assert store.get(oldest)["updated"] == now - 200
    library = Library(settings, store)
    library.enforce(now)
    assert not old_folder.exists() and new_folder.exists()
    assert [item["id"] for item in library.items()] == [newest]
    assert library.snapshot()["total_bytes"] == 600
    assert store.get(oldest)["message"] == "Удалено по лимиту библиотеки"


def test_thirty_day_ttl_and_queue_clear_preserve_age(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN)
    assert settings.retention_hours == 720 and settings.library_max_bytes == 10 * 1024**3
    store = Store(tmp_path)
    now = time.time()
    old, old_folder = media(store, tmp_path, 10, now - 31 * 86400)
    recent, new_folder = media(store, tmp_path, 10, now - 29 * 86400)
    store.dismiss(recent)
    library = Library(settings, store)
    library.enforce(now)
    assert not old_folder.exists() and new_folder.exists()
    assert store.get(old)["state"] == "expired"
    assert library.items()[0]["expires_at"] == now + 86400


def test_hidden_jobs_do_not_fill_queue_or_hide_new_downloads(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN, max_jobs=1)
    with TestClient(create_app(settings, run_manager=False)) as client:
        assert client.get("/api/library").status_code == 401
        assert client.delete("/api/library/" + "a" * 32).status_code == 401
        client.post("/api/login", json={"token": TOKEN})
        store = client.app.state.store
        parent = store.create("probe", "https://example.org/synthetic")
        store.update(parent["id"], state="completed", details={"formats": []})
        assert client.delete(f"/api/jobs/{parent['id']}").status_code == 200
        response = client.post("/api/downloads", json={"probe_id": parent["id"], "preset": "best"})
        assert response.status_code == 202
        assert [job["id"] for job in client.get("/api/jobs").json()] == [response.json()["id"]]
        assert "_queue_hidden" not in response.text
        assert client.delete(f"/api/jobs/{response.json()['id']}").status_code == 409


def test_failed_filesystem_removal_does_not_lose_library_record(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN)
    store = Store(tmp_path)
    job_id, folder = media(store, tmp_path, 10, time.time())

    def denied(*_args, **_kwargs):
        raise PermissionError("Synthetic access denied")

    monkeypatch.setattr("media_loader.library.shutil.rmtree", denied)
    library = Library(settings, store)
    assert library.remove(job_id) is False
    assert folder.exists() and library.snapshot()["total_bytes"] == 10
    assert store.get(job_id)["state"] == "completed"


def test_active_file_delivery_defers_ttl_and_manual_removal(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN)
    store = Store(tmp_path)
    job_id, folder = media(store, tmp_path, 10, time.time() - 31 * 86400)
    library = Library(settings, store)
    store.deliveries[job_id] = 1
    library.enforce()
    assert folder.exists() and library.remove(job_id) is False
    store.deliveries.clear()
    library.enforce()
    assert not folder.exists() and store.get(job_id)["state"] == "expired"
    store.engine.dispose()
