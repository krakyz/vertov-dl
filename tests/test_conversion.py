import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from media_loader.api import create_app
from media_loader.config import Settings
from media_loader.convert import execute


def test_conversion_enqueue_keeps_source_and_exposes_pending_card(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token="synthetic-token-at-least-24-chars")
    with TestClient(create_app(settings, run_manager=False)) as client:
        store = client.app.state.store
        job = store.create("download", "https://example.org/synthetic", "best")
        folder = tmp_path / "jobs" / job["id"]
        folder.mkdir(parents=True)
        source = folder / "media.mp4"
        source.write_bytes(b"source fixture")
        store.update(
            job["id"],
            state="completed",
            artifact=source.name,
            title="Original",
            details={
                "duration": 12,
                "artifact_media": {"media_type": "video", "audio_codec": "aac"},
            },
        )
        endpoint = f"/api/library/{job['id']}/audio"
        assert client.post(endpoint).status_code == 401
        client.post("/api/login", json={"token": settings.auth_token.get_secret_value()})
        response = client.post(endpoint)
        assert response.status_code == 202
        child = response.json()
        assert child["preset"] == "audio" and child["title"] == "Original"
        assert "artifact_media" not in child["details"]
        pinned = tmp_path / "jobs" / child["id"] / child["details"]["conversion_input"]
        assert pinned.read_bytes() == source.read_bytes()
        assert client.post(endpoint).json()["id"] == child["id"]
        items = client.get("/api/library").json()["items"]
        assert {item["id"] for item in items} == {job["id"], child["id"]}
        assert client.delete(f"/api/library/{child['id']}").status_code == 409
        assert client.delete(f"/api/library/{job['id']}").status_code == 200
        assert pinned.exists()
        store.update(child["id"], state="failed")
        assert client.delete(f"/api/library/{child['id']}").status_code == 200
        assert not pinned.exists()


@pytest.mark.parametrize("with_audio", [True, False])
def test_real_local_conversion(tmp_path, with_audio):
    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    ffmpeg = str(Path(location) / "ffmpeg") if location else shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg required")
    source = tmp_path / "source.mp4"
    args = [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=size=32x32:duration=1"]
    if with_audio:
        args += ["-f", "lavfi", "-i", "sine=duration=1", "-c:a", "aac"]
    subprocess.run(
        [*args, "-c:v", "mpeg4", str(source)], check=True, capture_output=True, timeout=20
    )
    spec = {"directory": str(tmp_path), "conversion_input": source.name, "max_bytes": 1024 * 1024}
    if with_audio:
        result = execute(spec)
        assert result["artifact"] == "media.mp3" and len(result["sha256"]) == 64
        from media_loader.artifact import inspect_artifact

        assert inspect_artifact(tmp_path / "media.mp3")["audio_codec"] == "mp3"
    else:
        with pytest.raises(subprocess.CalledProcessError):
            execute(spec)
        assert source.exists()


def test_manager_accepts_conversion_result_without_extractor_title(tmp_path):
    import asyncio

    from media_loader.manager import Manager
    from media_loader.store import Store

    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    ffmpeg = str(Path(location) / "ffmpeg") if location else shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg required")
    settings = Settings(
        data_dir=tmp_path, reserve_bytes=0, auth_token="synthetic-token-at-least-24-chars"
    )
    store = Store(tmp_path)
    job = store.create("download", "https://example.org/synthetic", "audio")
    folder = tmp_path / "jobs" / job["id"]
    folder.mkdir(parents=True)
    subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(folder / "source.wav")],
        check=True,
        capture_output=True,
        timeout=20,
    )
    store.update(
        job["id"],
        title="Original title",
        details={"conversion_input": "source.wav", "conversion_source": "synthetic"},
    )
    try:
        asyncio.run(Manager(settings, store, 1).execute(store.get(job["id"])))
        result = store.get(job["id"])
        assert result["state"] == "completed"
        assert result["title"] == "Original title"
        assert result["artifact"] == "media.mp3"
        assert (folder / "media.mp3").is_file()
        assert result["sha256"]
    finally:
        store.engine.dispose()


@pytest.mark.parametrize("state", ["cancelled", "expired"])
@pytest.mark.parametrize("source_exists", [True, False])
def test_retry_conversion_recreates_local_input(tmp_path, state, source_exists):
    settings = Settings(data_dir=tmp_path, auth_token="synthetic-token-at-least-24-chars")
    with TestClient(create_app(settings, run_manager=False)) as client:
        client.post("/api/login", json={"token": settings.auth_token.get_secret_value()})
        store = client.app.state.store
        parent = store.create("download", "https://example.org/synthetic", "best")
        source = tmp_path / "jobs" / parent["id"] / "media.mp4"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"source fixture")
        store.update(parent["id"], state="completed", artifact=source.name)
        created = client.post(f"/api/library/{parent['id']}/audio").json()
        job_id = created["id"]
        folder = tmp_path / "jobs" / job_id
        shutil.rmtree(folder)
        store.update(job_id, state=state)
        if not source_exists:
            source.unlink()
        response = client.post(f"/api/jobs/{job_id}/retry")
        assert response.status_code == (202 if source_exists else 409)
        assert len(store.all()) == 2
        if source_exists:
            job = response.json()
            assert job["id"] == job_id and job["state"] == "queued"
            assert (folder / job["details"]["conversion_input"]).read_bytes() == b"source fixture"
        else:
            assert store.get(job_id)["state"] == state
