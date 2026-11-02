import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yt_dlp
from media_loader.artifact import inspect_artifact
from media_loader.video import MP4VideoPP
from yt_dlp.postprocessor.ffmpeg import FFmpegVideoRemuxerPP
from yt_dlp.utils import PostProcessingError


@pytest.mark.parametrize("codec,expected", [("mpeg4", "mpeg4"), ("ffv1", "h264")])
def test_mp4_remux_and_transcoding_fallback(tmp_path, monkeypatch, codec, expected):
    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    ffmpeg = str(Path(location) / "ffmpeg") if location else shutil.which("ffmpeg")
    ffprobe = str(Path(location) / "ffprobe") if location else shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg/ffprobe required; run in Linux image")
    source = tmp_path / "media.mkv"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=128x72:r=10:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-c:v",
            codec,
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    if codec == "ffv1":
        # Container support differs across FFmpeg versions; force the fallback branch.
        def unsupported(*_args):
            raise PostProcessingError("Synthetic unsupported container codec")

        monkeypatch.setattr(FFmpegVideoRemuxerPP, "run", unsupported)
    with yt_dlp.YoutubeDL({"quiet": True, "ffmpeg_location": location}) as downloader:
        discarded, info = MP4VideoPP(downloader).run(
            {"filepath": str(source), "ext": "mkv", "vcodec": codec, "acodec": "aac"}
        )
    assert info["ext"] == "mp4" and Path(info["filepath"]).suffix == ".mp4"
    assert str(source) in discarded
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=format_name:stream=codec_name,codec_type",
            "-of",
            "json",
            info["filepath"],
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    media = json.loads(result.stdout)
    inspected = inspect_artifact(Path(info["filepath"]))
    assert inspected["media_type"] == "video"
    assert inspected["video_codec"] == expected
    assert inspected["audio_codec"] == "aac"
    assert inspected["width"] > 0 and inspected["height"] > 0
    assert inspected["fps"] > 0
    assert "mp4" in media["format"]["format_name"]
    assert {stream["codec_name"] for stream in media["streams"]} == {expected, "aac"}


def test_exact_audio_is_not_converted_to_video():
    with yt_dlp.YoutubeDL({"quiet": True}) as downloader:
        info = {"vcodec": "none", "ext": "m4a", "filepath": "synthetic.m4a"}
        discarded, result = MP4VideoPP(downloader).run(info)
    assert not discarded and result == info


def test_valid_magicyuv_transcodes_through_actual_fallback(tmp_path, monkeypatch):
    from media_loader.video import CompatibleMP4PP

    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    ffmpeg = str(Path(location) / "ffmpeg") if location else shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg required")
    source = tmp_path / "media.avi"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=32x32:rate=1:duration=1",
            "-c:v",
            "magicyuv",
            "-threads",
            "1",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    original = CompatibleMP4PP.run
    reached = []

    def tracked(self, info):
        reached.append(info["vcodec"])
        return original(self, info)

    monkeypatch.setattr(CompatibleMP4PP, "run", tracked)
    with yt_dlp.YoutubeDL({"quiet": True, "ffmpeg_location": location}) as downloader:
        _, result = MP4VideoPP(downloader).run(
            {"filepath": str(source), "ext": "avi", "vcodec": "magicyuv", "acodec": "none"}
        )
    assert reached == ["magicyuv"]
    assert inspect_artifact(Path(result["filepath"]))["video_codec"] == "h264"
