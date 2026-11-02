import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yt_dlp
from media_loader import task
from yt_dlp.postprocessor.ffmpeg import FFmpegExtractAudioPP


@pytest.mark.parametrize("preset,converted", [("audio", True), ("format:140", False)])
def test_only_audio_preset_converts_to_mp3(tmp_path, monkeypatch, capsys, preset, converted):
    captured = {}

    class Downloader:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def extract_info(self, *_args, **_kwargs):
            return {"title": "Fixture", "protocol": "https", "formats": [], "vcodec": "none"}

        def process_info(self, _info):
            for hook in captured.get("postprocessor_hooks", []):
                hook({"status": "started"})
            (tmp_path / ("media.mp3" if converted else "media.m4a")).write_bytes(b"fixture")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    monkeypatch.setattr(task, "restrict_python_network", lambda _: None)
    if os.name == "posix":
        import resource

        monkeypatch.setattr(resource, "setrlimit", lambda *_: None)
    result = task.execute(
        {
            "kind": "download",
            "url": "https://example.org/audio",
            "preset": preset,
            "directory": str(tmp_path),
            "proxy": "socks5://127.0.0.1:1",
            "max_bytes": 1024,
        }
    )
    assert "artifact_media" not in result["details"]
    assert result["artifact"] == ("media.mp3" if converted else "media.m4a")
    if converted:
        assert captured["postprocessors"] == [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
        ]
        events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert events[1] == {"event": "phase", "state": "processing"}
    else:
        assert "postprocessors" not in captured


def test_real_ffmpeg_extracts_mp3(tmp_path):
    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    ffmpeg = str(Path(location) / "ffmpeg") if location else shutil.which("ffmpeg")
    ffprobe = str(Path(location) / "ffprobe") if location else shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe required; run in the Linux image")
    source = tmp_path / "media.m4a"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    with yt_dlp.YoutubeDL({"quiet": True, "ffmpeg_location": location}) as downloader:
        processor = FFmpegExtractAudioPP(downloader, preferredcodec="mp3", preferredquality="0")
        _, info = processor.run({"filepath": str(source), "ext": "m4a", "vcodec": "none"})
    target = Path(info["filepath"])
    assert target.suffix == ".mp3" and target.stat().st_size > 0
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type",
            "-of",
            "json",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert json.loads(result.stdout)["streams"] == [{"codec_name": "mp3", "codec_type": "audio"}]


def test_resume_keeps_matching_parts_and_discards_changed_selection(tmp_path):
    first = {"format_id": "140", "ext": "m4a"}
    task.prepare_selection(tmp_path, first)
    part = tmp_path / "media.m4a.part"
    fragment = tmp_path / "media.m4a.ytdl"
    part.write_bytes(b"partial")
    fragment.write_bytes(b"fragment state")
    task.prepare_selection(tmp_path, first)
    assert part.exists() and fragment.exists()
    unrelated = tmp_path / "thumbnail.img"
    unrelated.write_bytes(b"preview")
    task.prepare_selection(tmp_path, {"format_id": "251", "ext": "webm"})
    assert not part.exists() and not fragment.exists()
    assert unrelated.exists()
