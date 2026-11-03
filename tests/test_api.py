import time

import pytest
from fastapi.testclient import TestClient
from media_loader.api import create_app
from media_loader.config import Settings

TOKEN = "test-only-not-a-real-token-123456789"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, auth_token=TOKEN), run_manager=False)
    with TestClient(app) as client:
        yield client


def login(client):
    assert client.post("/api/login", json={"token": TOKEN}).status_code == 200


def test_auth_and_cookie_tampering(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/jobs").status_code == 401
    login(client)
    assert "HttpOnly" in client.post("/api/login", json={"token": TOKEN}).headers["set-cookie"]
    assert client.get("/api/jobs").status_code == 200
    client.cookies.clear()
    client.cookies.set("media_session", f"{int(time.time()) + 1000}.forged")
    assert client.get("/api/jobs").status_code == 401


def test_csrf_and_body_limit(client):
    login(client)
    assert (
        client.post(
            "/api/probes",
            json={"url": "https://example.org/video"},
            headers={"Origin": "https://malicious.example"},
        ).status_code
        == 403
    )
    assert client.post("/api/probes", content=b"x" * 17000).status_code == 413


def test_malformed_session_is_rejected_without_server_error(client):
    for value in ["9" * 5000 + ".forged", "123.invalid", "123." + "f" * 65]:
        client.cookies.clear()
        client.cookies.set("media_session", value)
        assert client.get("/api/jobs").status_code == 401


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.org/a",
        "http://example.org:22/a",
        "--exec=bad",
    ],
)
def test_rejects_unsafe_input(client, url):
    login(client)
    assert client.post("/api/probes", json={"url": url}).status_code == 422


def test_queue_cancel_retry_and_source_redaction(client):
    login(client)
    result = client.post("/api/probes", json={"url": "https://example.org/video?private=test"})
    assert result.status_code == 202
    job = result.json()
    assert "source" not in job and "private=test" not in result.text
    assert client.post("/api/downloads", json={"probe_id": job["id"]}).status_code == 409
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    retry = client.post(f"/api/jobs/{job['id']}/retry")
    assert retry.status_code == 202 and retry.json()["id"] != job["id"]


def test_range_delivery_and_deletion(client):
    login(client)
    store = client.app.state.store
    job = store.create("download", "https://example.org/video")
    directory = store.engine.url.database
    from pathlib import Path

    folder = Path(directory).parent / "jobs" / job["id"]
    folder.mkdir(parents=True)
    (folder / "media.mp4").write_bytes(b"0123456789")
    store.update(job["id"], state="completed", artifact="media.mp4", title="Test", sha256="test")
    url = f"/api/jobs/{job['id']}/file"
    response = client.get(url, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206 and response.content == b"2345"
    assert "attachment" in response.headers["content-disposition"]
    assert not store.deliveries
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert folder.exists()
    assert client.get(url).status_code == 200
    assert not any(item["id"] == job["id"] for item in client.get("/api/jobs").json())
    assert any(item["id"] == job["id"] for item in client.get("/api/library").json()["items"])
    assert client.delete(f"/api/library/{job['id']}").status_code == 200
    assert not folder.exists()
    assert client.get(url).status_code == 409


def test_path_traversal_in_database_does_not_escape(client):
    login(client)
    job = client.app.state.store.create("download", "https://example.org/video")
    client.app.state.store.update(job["id"], state="completed", artifact="../../queue.sqlite3")
    assert client.get(f"/api/jobs/{job['id']}/file").status_code == 410


@pytest.mark.parametrize(
    "selection", [{"preset": "best"}, {"preset": "audio"}, {"format_id": "18"}]
)
def test_download_replaces_probe_in_visible_queue(client, selection):
    login(client)
    store = client.app.state.store
    parent = store.create("probe", "https://example.org/synthetic")
    store.update(parent["id"], state="completed", details={"formats": [{"id": "18"}]})
    invalid = client.post("/api/downloads", json={"probe_id": parent["id"], "format_id": "missing"})
    assert invalid.status_code == 422
    assert [job["id"] for job in client.get("/api/jobs").json()] == [parent["id"]]
    response = client.post("/api/downloads", json={"probe_id": parent["id"], **selection})
    assert response.status_code == 202
    assert [job["id"] for job in client.get("/api/jobs").json()] == [response.json()["id"]]
    assert store.get(parent["id"])["state"] == "completed"
    assert response.json()["details"]["source_probe_id"] == parent["id"]


def test_resume_failed_preserves_parts_and_delete_removes_them(client, tmp_path):
    login(client)
    store = client.app.state.store
    job = store.create("download", "https://example.org/synthetic", "audio")
    folder = tmp_path / "jobs" / job["id"]
    folder.mkdir(parents=True)
    part = folder / "media.webm.part"
    part.write_bytes(b"partial")
    store.update(job["id"], state="failed")
    response = client.post(f"/api/jobs/{job['id']}/retry")
    assert response.status_code == 202
    assert response.json()["id"] == job["id"]
    assert response.json()["preset"] == "audio"
    assert part.read_bytes() == b"partial"
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 409
    store.update(job["id"], state="failed")
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert not folder.exists()
    assert client.get("/api/jobs").json() == []
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409


@pytest.mark.parametrize(
    "original,selected", [("audio", "720"), ("720", "audio"), ("audio", "audio")]
)
def test_cancelled_download_reuses_task_when_selecting_media(client, original, selected):
    login(client)
    store = client.app.state.store
    parent = store.create("probe", "https://example.org/restart")
    store.update(parent["id"], state="completed", details={"formats": []})
    old = store.create("download", parent["source"], original)
    store.update(old["id"], state="cancelled", progress={"downloaded": 5}, error_code="old")
    count = len(store.all())
    response = client.post(
        "/api/downloads",
        json={"probe_id": parent["id"], "replace_job_id": old["id"], "preset": selected},
    )
    assert response.status_code == 202
    assert response.json()["id"] == old["id"]
    assert len(store.all()) == count
    result = store.get(old["id"])
    assert result["preset"] == selected and result["state"] == "queued"
    assert result["progress"] is None and result["error_code"] is None
    assert (
        client.post(
            "/api/downloads",
            json={"probe_id": parent["id"], "replace_job_id": old["id"], "preset": selected},
        ).status_code
        == 409
    )


def test_cancelled_download_retry_keeps_id(client):
    login(client)
    store = client.app.state.store
    old = store.create("download", "https://example.org/retry", "audio")
    store.update(old["id"], state="cancelled")
    response = client.post(f"/api/jobs/{old['id']}/retry")
    assert response.status_code == 202
    assert response.json()["id"] == old["id"]


def test_full_history_allows_download_to_replace_visible_probe(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, auth_token=TOKEN, max_jobs=1), run_manager=False)
    with TestClient(app) as client:
        login(client)
        store = app.state.store
        probe = store.create("probe", "https://example.org/video")
        store.update(probe["id"], state="completed", details={"formats": []})
        response = client.post("/api/downloads", json={"probe_id": probe["id"]})
        assert response.status_code == 202
        assert [job["id"] for job in store.visible()] == [response.json()["id"]]
        assert client.post("/api/downloads", json={"probe_id": probe["id"]}).status_code == 409
