import asyncio
import time

from fastapi.testclient import TestClient
from media_loader.api import create_app
from media_loader.config import Settings
from media_loader.manager import Manager
from media_loader.metadata_cache import MetadataCache
from media_loader.store import Store

TOKEN = "synthetic-token-at-least-24-chars"


def test_cache_success_ttl_generations_and_out_of_order(tmp_path):
    store = Store(tmp_path)
    cache = MetadataCache(ttl=300)
    old = store.create("probe", "https://example.org/synthetic")
    cache.begin(old)
    store.update(old["id"], state="failed", details={"title": "Error"})
    cache.put(store.get(old["id"]))
    assert cache.get(old["source"], store) is None
    newer = store.create("probe", old["source"])
    cache.begin(newer)
    store.update(newer["id"], state="completed", details={"title": "New", "formats": []})
    cache.put(store.get(newer["id"]))
    store.update(old["id"], state="completed", details={"title": "Old", "formats": []})
    cache.put(store.get(old["id"]))
    assert cache.get(old["source"], store)["id"] == newer["id"]
    cache.entries[old["source"]] = (newer["id"], time.monotonic() - 1)
    assert cache.get(old["source"], store) is None
    cache.invalidate()
    cache.put(store.get(newer["id"]))
    assert cache.get(old["source"], store) is None
    store.engine.dispose()


def test_api_force_retry_and_cookie_change_bypass_cache(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path, auth_token=TOKEN), run_manager=False)
    ) as client:
        client.post("/api/login", json={"token": TOKEN})
        source = {"url": "https://example.org/synthetic"}
        first = client.post("/api/probes", json=source).json()
        store, cache = client.app.state.store, client.app.state.metadata_cache
        store.update(
            first["id"], state="completed", title="Valid", details={"title": "Valid", "formats": []}
        )
        cache.put(store.get(first["id"]))
        hit = client.post("/api/probes", json=source).json()
        assert hit["state"] == "completed" and hit["title"] == "Valid"
        forced = client.post("/api/probes", json={**source, "force": True}).json()
        assert forced["state"] == "queued"
        store.update(forced["id"], state="failed")
        retried = client.post(f"/api/jobs/{forced['id']}/retry").json()
        assert retried["state"] == "queued"
        store.update(retried["id"], state="completed", details={"title": "Fresh", "formats": []})
        cache.put(store.get(retried["id"]))
        client.delete("/api/cookies")
        assert client.post("/api/probes", json=source).json()["state"] == "queued"
        cache.put(store.get(retried["id"]))
        assert cache.get(source["url"], store) is None


async def test_probes_do_not_wait_for_download_and_limit_parallelism(tmp_path, monkeypatch):
    store = Store(tmp_path)
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN)
    download = store.create("download", "https://example.org/video")
    probes = [store.create("probe", f"https://example.org/{i}") for i in range(3)]
    manager = Manager(settings, store, 1)
    running, started = set(), asyncio.Event()
    release = asyncio.Event()

    async def execute(job):
        store.update(job["id"], state="probing")
        running.add(job["id"])
        if len(running) == 3:
            started.set()
        await release.wait()

    monkeypatch.setattr(manager, "execute", execute)
    task = asyncio.create_task(manager.run())
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert download["id"] in running
        assert sum(job["id"] in running for job in probes) == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert not manager.current_ids
        store.engine.dispose()


def test_background_preview_reaches_cached_probe_and_child_without_extending_ttl(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token=TOKEN)
    store = Store(tmp_path)
    parent = store.create("probe", "https://example.org/synthetic")
    cached = store.create("probe", parent["source"])
    child = store.create("download", parent["source"])
    for job, details in [
        (parent, {}),
        (cached, {"source_probe_id": parent["id"]}),
        (child, {"source_probe_id": cached["id"]}),
    ]:
        (tmp_path / "jobs" / job["id"]).mkdir(parents=True)
        store.update(job["id"], state="completed", details=details)
    source = tmp_path / "jobs" / parent["id"] / "thumbnail.img"
    source.write_bytes(b"preview fixture")
    timestamp = store.get(child["id"])["updated"]
    Manager(settings, store, 1).propagate_thumbnail(parent["id"], source, "image/png")
    assert store.get(child["id"])["details"]["has_thumbnail"] is True
    assert (tmp_path / "jobs" / child["id"] / "thumbnail.img").read_bytes() == source.read_bytes()
    assert store.get(child["id"])["updated"] == timestamp
    store.engine.dispose()
