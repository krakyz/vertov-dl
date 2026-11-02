"""Finalize video as MP4, preserving codecs whenever the container supports them."""

from yt_dlp.postprocessor.ffmpeg import FFmpegVideoConvertorPP, FFmpegVideoRemuxerPP
from yt_dlp.utils import PostProcessingError


class CompatibleMP4PP(FFmpegVideoConvertorPP):
    @staticmethod
    def _options(target_ext):
        yield from (
            "-c:v",
            "libx264",
            "-crf",
            "20",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        )


class MP4VideoPP(FFmpegVideoRemuxerPP):
    def __init__(self, downloader):
        super().__init__(downloader, preferedformat="mp4")

    def run(self, info):
        if info.get("vcodec") == "none":
            return [], info
        try:
            return super().run(info)
        except PostProcessingError:
            # Unsupported codecs need actual transcoding rather than an extension change.
            return CompatibleMP4PP(self._downloader, preferedformat="mp4").run(info)
