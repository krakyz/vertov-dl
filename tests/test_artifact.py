import json
from types import SimpleNamespace

from media_loader.artifact import inspect_artifact


def test_final_codec_and_cover_art_are_distinguished(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_FFMPEG_LOCATION", str(tmp_path))
    seen = []

    def run(args, **kwargs):
        seen.append(args)
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "mjpeg",
                            "disposition": {"attached_pic": 1},
                        },
                        {"codec_type": "audio", "codec_name": "mp3"},
                    ]
                }
            )
        )

    monkeypatch.setattr("media_loader.artifact.subprocess.run", run)
    result = inspect_artifact(tmp_path / "media.mp3")
    assert result == {
        "media_type": "audio",
        "video_codec": None,
        "audio_codec": "mp3",
        "width": None,
        "height": None,
        "fps": None,
    }
    assert "file,pipe,crypto" in seen[0]
    assert seen[0][-1] == str((tmp_path / "media.mp3").resolve())


def test_background_enrichment_does_not_delay_ready_or_extend_ttl(tmp_path, monkeypatch):
    import asyncio

    from media_loader.artifact import enrich_library
    from media_loader.config import Settings
    from media_loader.store import Store

    async def scenario():
        settings = Settings(data_dir=tmp_path, auth_token="synthetic-token-at-least-24-chars")
        store = Store(tmp_path)
        job = store.create("download", "https://example.org/synthetic")
        folder = tmp_path / "jobs" / job["id"]
        folder.mkdir(parents=True)
        (folder / "media.mp4").write_bytes(b"fixture")
        store.update(job["id"], state="completed", artifact="media.mp4")
        before = store.get(job["id"])["updated"]
        started, release = asyncio.Event(), asyncio.Event()
        media = {
            "media_type": "video",
            "video_codec": "h264",
            "width": 1920,
            "height": 1080,
            "fps": 29.97,
        }

        class Process:
            returncode = 0

            async def communicate(self):
                started.set()
                await release.wait()
                return json.dumps(media).encode(), b""

        async def create(*args, **kwargs):
            return Process()

        monkeypatch.setattr("media_loader.artifact.asyncio.create_subprocess_exec", create)
        worker = asyncio.create_task(enrich_library(settings, store))
        try:
            await asyncio.wait_for(started.wait(), 1)
            assert store.get(job["id"])["state"] == "completed"
            assert not store.get(job["id"])["details"]
            release.set()
            for _ in range(20):
                await asyncio.sleep(0)
                if store.get(job["id"])["details"]:
                    break
            result = store.get(job["id"])
            assert result["details"]["artifact_media"] == media
            assert result["updated"] == before
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            store.engine.dispose()

    asyncio.run(scenario())
