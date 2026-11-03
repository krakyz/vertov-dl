import io

import pytest
from fastapi.testclient import TestClient
from media_loader.api import create_app
from media_loader.config import Settings
from media_loader.task import format_selector, save_thumbnail

TOKEN = "test-only-format-key-123456789012345"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, auth_token=TOKEN), run_manager=False)
    with TestClient(app) as client:
        client.post("/api/login", json={"token": TOKEN})
        yield client


def test_exact_download_requires_a_format_from_probe(client):
    store = client.app.state.store
    parent = store.create("probe", "https://example.org/video")
    store.update(
        parent["id"], state="completed", details={"formats": [{"id": "140"}, {"id": "18"}]}
    )
    response = client.post("/api/downloads", json={"probe_id": parent["id"], "format_id": "140"})
    assert response.status_code == 202
    assert store.get(response.json()["id"])["preset"] == "format:140"
    assert (
        client.post(
            "/api/downloads", json={"probe_id": parent["id"], "format_id": "999"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/downloads", json={"probe_id": parent["id"], "format_id": "18", "preset": "best"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/downloads", json={"probe_id": parent["id"], "format_id": "18/best"}
        ).status_code
        == 422
    )


def test_exact_format_has_no_quality_fallback():
    assert format_selector("download", "format:140") == "140"
    assert format_selector("download", "format:139-drc") == "139-drc"
    with pytest.raises(ValueError):
        format_selector("download", "format:18/best")


def test_thumbnail_type_and_size_are_checked(tmp_path):
    class Downloader:
        body = b""

        def urlopen(self, url):
            return io.BytesIO(self.body)

    downloader = Downloader()
    downloader.body = b'<svg onload="alert(1)"></svg>'
    assert save_thumbnail(downloader, {"thumbnail": "https://example.org/image"}, tmp_path) is None
    assert not (tmp_path / "thumbnail.img").exists()
    downloader.body = b"\xff\xd8\xff" + b"x" * (2 * 1024**2)
    assert save_thumbnail(downloader, {"thumbnail": "https://example.org/image"}, tmp_path) is None
    downloader.body = b"\x89PNG\r\n\x1a\n" + b"fixture"
    assert (
        save_thumbnail(downloader, {"thumbnail": "https://example.org/image"}, tmp_path)
        == "image/png"
    )
    assert (tmp_path / "thumbnail.img").read_bytes() == downloader.body


def test_status_reports_real_capabilities_and_thumbnail_is_authenticated(client, tmp_path):
    assert client.get("/api/status").json()["capabilities"]["exact_formats"] is True
    store = client.app.state.store
    job = store.create("probe", "https://example.org/video")
    store.update(
        job["id"], state="completed", details={"has_thumbnail": True, "thumbnail_mime": "image/png"}
    )
    folder = tmp_path / "jobs" / job["id"]
    folder.mkdir(parents=True)
    (folder / "thumbnail.img").write_bytes(b"png-fixture")
    url = f"/api/jobs/{job['id']}/thumbnail"
    assert client.get(url).headers["content-type"].startswith("image/png")
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_download_inherits_the_probe_metadata_and_preview(client, tmp_path):
    store = client.app.state.store
    parent = store.create("probe", "https://example.org/video")
    store.update(
        parent["id"],
        state="completed",
        title="Example",
        details={
            "uploader": "Creator",
            "duration": 19,
            "formats": [{"id": "18"}],
            "has_thumbnail": True,
            "thumbnail_mime": "image/png",
        },
    )
    folder = tmp_path / "jobs" / parent["id"]
    folder.mkdir(parents=True)
    image = b"\x89PNG\r\n\x1a\nfixture"
    (folder / "thumbnail.img").write_bytes(image)
    result = client.post(
        "/api/downloads", json={"probe_id": parent["id"], "format_id": "18"}
    ).json()
    assert result["details"]["uploader"] == "Creator"
    assert result["details"]["source_probe_id"] == parent["id"]
    assert client.get(f"/api/jobs/{result['id']}/thumbnail").content == image
    store.update(result["id"], state="failed")
    (tmp_path / "jobs" / result["id"] / "thumbnail.img").unlink()
    retry = client.post(f"/api/jobs/{result['id']}/retry").json()
    assert client.get(f"/api/jobs/{retry['id']}/thumbnail").content == image


def test_cached_thumbnail_does_not_make_another_network_request(tmp_path):
    class Offline:
        def urlopen(self, url):
            raise AssertionError("Cached preview must not be re-fetched")

    (tmp_path / "thumbnail.img").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    assert (
        save_thumbnail(Offline(), {"thumbnail": "https://example.org/image"}, tmp_path)
        == "image/png"
    )


@pytest.mark.parametrize(
    ("kind", "preset", "tracks", "selected"),
    [
        ("download", "audio", ["muxed"], "muxed"),
        ("download", "audio", ["muxed", "audio"], "audio"),
        ("probe", "720", ["video", "audio"], "video+audio"),
        ("download", "720", ["video", "audio"], "video+audio"),
        ("probe", "720", ["muxed"], "muxed"),
        ("probe", "720", ["video"], "video"),
        ("probe", "720", ["audio"], "audio"),
    ],
)
def test_selector_accepts_supported_stream_layouts(kind, preset, tracks, selected):
    from yt_dlp import YoutubeDL

    formats = [
        {
            "format_id": track,
            "url": f"https://example.org/{track}.mp4",
            "ext": "mp4",
            "vcodec": "none" if track == "audio" else "h264",
            "acodec": "none" if track == "video" else "aac",
            "height": 720 if track != "audio" else None,
        }
        for track in tracks
    ]
    with YoutubeDL({"quiet": True, "format": format_selector(kind, preset)}) as downloader:
        result = downloader.process_ie_result(
            {"id": "synthetic", "title": "Synthetic", "formats": formats}, download=False
        )
    assert result["format_id"] == selected
    assert {item["format_id"] for item in result["formats"]} == set(tracks)
