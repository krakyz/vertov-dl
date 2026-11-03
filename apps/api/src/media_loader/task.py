"""One isolated yt-dlp invocation. stdout contains only sanitized JSON events."""

import hashlib
import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from .config import Settings
from .cookies import CookieError, CookieVault
from .video import MP4VideoPP


def prepare_selection(output, info):
    selection = [
        {"id": f.get("format_id"), "ext": f.get("ext")}
        for f in info.get("requested_formats") or [info]
    ]
    manifest = output / "selection.json"
    previous = json.loads(manifest.read_text()) if manifest.exists() else None
    if previous != selection:
        for old in output.glob("media.*"):
            if old.is_file():
                old.unlink()
    temporary = output / "selection.pending"
    temporary.write_text(json.dumps(selection), encoding="utf-8")
    temporary.replace(manifest)


def error_details(error):
    value = re.sub(r"https?://\S+", "[url]", str(error).lower())
    value = re.sub(r"(?:cookie|authorization):.*", "[secret]", value)
    if any(word in value for word in ["sign in", "login required", "cookies", "age-restricted"]):
        return "authentication", "Обновите файл cookies.txt в настройках и повторите загрузку."
    if any(
        word in value for word in ["captcha", "not a bot", "bot detection", "challenge required"]
    ):
        return "challenge", "Обновите файл cookies.txt в настройках и повторите загрузку."
    if "429" in value or "too many requests" in value:
        return "rate_limited", "Сервис ограничил запросы. Повторите позже."
    if "format" in value and ("not available" in value or "requested" in value):
        return "format", "Подходящий формат недоступен. Выберите другое ограничение качества."
    if "403" in value:
        return "access_denied", "Сервис отклонил запрос (403). Причина пока не определена."
    if any(
        word in value
        for word in ["timed out", "timeout", "proxy", "connection", "unable to download"]
    ):
        return "network", "Не удалось получить данные через прокси. Проверьте доступ и повторите."
    if any(word in value for word in ["private", "unavailable", "removed", "not available"]):
        return "unavailable", "Контент недоступен для текущей серверной сессии."
    return "unknown", "Загрузка завершилась ошибкой. Проверьте доступность и версию yt-dlp."


def restrict_python_network(proxy):
    allowed = urlsplit(proxy)
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def check(address):
        if not isinstance(address, tuple) or address[:2] != ("127.0.0.1", allowed.port):
            raise OSError("Direct network access blocked")

    def connect(sock, address):
        check(address)
        return original(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_ex(sock, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def format_selector(kind, preset):
    if kind == "probe":
        return "bestvideo*+bestaudio/best/bestvideo/bestaudio"
    if preset.startswith("format:"):
        format_id = preset.removeprefix("format:")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", format_id):
            raise ValueError("Invalid format ID")
        return format_id
    if preset == "audio":
        return "bestaudio/best[acodec!=none]"
    if preset == "best":
        return "bestvideo*+bestaudio/best"
    height = int(preset)
    return f"bestvideo*[height<={height}]+bestaudio/best[height<={height}]"


def save_thumbnail(downloader, info, output):
    cached = output / "thumbnail.img"
    if cached.is_file() and cached.stat().st_size <= 2 * 1024**2:
        with cached.open("rb") as stream:
            header = stream.read(12)
        if header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
            return "image/webp"
    url = info.get("thumbnail")
    if not url or not url.startswith(("https://", "http://")):
        return None
    try:
        with downloader.urlopen(url) as response:
            content = response.read(2 * 1024**2 + 1)
        if len(content) > 2 * 1024**2:
            return None
        if content.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif content.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            return None
        (output / "thumbnail.img").write_bytes(content)
        return mime
    except Exception:  # noqa: BLE001 -- an optional preview must not fail the media job
        return None


def execute(spec):
    import yt_dlp
    from yt_dlp.globals import plugin_dirs

    plugin_dirs.value = []
    restrict_python_network(spec["proxy"])
    if os.name == "posix":
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (spec["max_bytes"], spec["max_bytes"]))

    class QuietLogger:
        def debug(self, *_):
            pass

        def warning(self, *_):
            pass

        def error(self, *_):
            pass

    last_event = 0.0

    def progress(data):
        nonlocal last_event
        now = time.monotonic()
        if now - last_event < 0.5 and data.get("status") != "finished":
            return
        last_event = now
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        print(
            json.dumps(
                {
                    "event": "progress",
                    "data": {
                        "downloaded": data.get("downloaded_bytes", 0),
                        "total": total,
                        "speed": data.get("speed"),
                        "eta": data.get("eta"),
                    },
                }
            ),
            flush=True,
        )

    output = Path(spec["directory"]).resolve()
    options = {
        "proxy": spec["proxy"],
        "logger": QuietLogger(),
        "quiet": True,
        "noplaylist": True,
        "cachedir": False,
        "continuedl": True,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 1,
        "concurrent_fragment_downloads": 1,
        "max_filesize": spec["max_bytes"],
        "outtmpl": str(output / "media.%(ext)s"),
        "restrictfilenames": True,
        "progress_hooks": [progress],
        "merge_output_format": "mkv",
        "hls_prefer_native": True,
        "enable_file_urls": False,
        "js_runtimes": {"deno": {}},
    }
    if os.environ.get("MEDIA_FFMPEG_LOCATION"):
        options["ffmpeg_location"] = os.environ["MEDIA_FFMPEG_LOCATION"]
    if spec["kind"] == "download" and spec["preset"] == "audio":
        options["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
        ]

    if spec["kind"] == "download":

        def postprocess(data):
            if data.get("status") == "started":
                print(json.dumps({"event": "phase", "state": "processing"}), flush=True)

        options["postprocessor_hooks"] = [postprocess]
    options["format"] = format_selector(spec["kind"], spec["preset"])
    with yt_dlp.YoutubeDL(options) as downloader:
        if spec.get("use_cookies"):
            jar = CookieVault(Settings()).load()
            if jar is not None:
                for cookie in jar:
                    downloader.cookiejar.set_cookie(cookie)
        # Probe first even for downloads: no live streams/playlists in this version.
        extraction_started = time.monotonic()
        info = downloader.extract_info(spec["url"], download=False)
        if not info or info.get("_type") in {"playlist", "multi_video"}:
            raise ValueError("Playlists not available in test version")
        if info.get("is_live") or info.get("live_status") == "is_live":
            raise ValueError("Live streams not available in test version")
        details = {
            "extraction_seconds": round(time.monotonic() - extraction_started, 3),
            "title": str(info.get("title") or "Медиа")[:300],
            "duration": info.get("duration"),
            "uploader": info.get("uploader") or info.get("channel"),
            "extractor": info.get("extractor_key"),
            "formats": [
                {
                    "id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "height": f.get("height"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                    "abr": f.get("abr"),
                    "tbr": f.get("tbr"),
                    "asr": f.get("asr"),
                    "audio_channels": f.get("audio_channels"),
                    "filesize": f.get("filesize"),
                    "filesize_approx": f.get("filesize_approx"),
                    "protocol": f.get("protocol"),
                }
                for f in info.get("formats", [])[:250]
            ],
        }
        if spec["kind"] == "probe":
            details["has_thumbnail"] = False
            print(json.dumps({"event": "metadata", "details": details}), flush=True)
        thumbnail_started = time.monotonic()
        mime = save_thumbnail(downloader, info if spec["kind"] == "probe" else {}, output)
        details["thumbnail_seconds"] = round(time.monotonic() - thumbnail_started, 3)
        details["has_thumbnail"] = bool(mime)
        details["thumbnail_mime"] = mime
        if spec["kind"] == "probe":
            return {"ok": True, "details": details}
        # Never delegate network fetching to ffmpeg or external downloaders.
        for item in info.get("requested_formats") or [info]:
            if item.get("protocol") not in {"http", "https", "m3u8_native", "http_dash_segments"}:
                raise ValueError("Unsupported network protocol in test version")
        print(json.dumps({"event": "phase", "state": "downloading"}), flush=True)
        if spec["preset"] != "audio" and info.get("vcodec") != "none":
            downloader.add_post_processor(MP4VideoPP(downloader))
        prepare_selection(output, info)
        downloader.process_info(info)
    files = [
        p
        for p in output.glob("media.*")
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp", ".json"))
    ]
    if len(files) != 1:
        raise ValueError("No single final artifact")
    artifact = files[0]
    if artifact.stat().st_size > spec["max_bytes"]:
        raise ValueError("Artifact size limit exceeded")
    print(json.dumps({"event": "phase", "state": "processing"}), flush=True)
    for old in output.glob("media.*"):
        if old != artifact and old.is_file():
            old.unlink()
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"ok": True, "details": details, "artifact": artifact.name, "sha256": digest}


def main():
    spec_path, result_path = map(Path, sys.argv[1:3])
    try:
        result = execute(json.loads(spec_path.read_text()))
    except Exception as error:  # noqa: BLE001 -- process boundary; never expose raw exceptions
        code, message = error_details(error)
        if isinstance(error, CookieError):
            code, message = "cookies", str(error)
        elif isinstance(error, ValueError):
            code, message = (
                "unsupported",
                "Тип медиа или размер не поддерживается тестовой версией.",
            )
        result = {"ok": False, "error_code": code, "message": message}
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(result_path)


if __name__ == "__main__":
    main()
