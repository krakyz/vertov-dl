"""Local-only audio conversion worker; never invokes yt-dlp."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def execute(spec):
    folder = Path(spec["directory"]).resolve()
    source = folder / spec["conversion_input"]
    if source.parent != folder or not source.is_file():
        raise ValueError("Missing local source")
    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    executable = str(Path(location) / "ffmpeg") if location else shutil.which("ffmpeg")
    if not executable:
        raise ValueError("Missing ffmpeg")
    target = folder / "media.mp3"
    print(json.dumps({"event": "phase", "state": "processing"}), flush=True)
    subprocess.run(
        [
            executable,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-protocol_whitelist",
            "file,pipe,crypto",
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "0",
            "-fs",
            str(spec["max_bytes"] + 1),
            str(target),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not target.is_file() or not 0 < target.stat().st_size <= spec["max_bytes"]:
        raise ValueError("Output exceeds limit")
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    source.unlink()
    return {"ok": True, "details": {}, "artifact": target.name, "sha256": digest}


if __name__ == "__main__":
    spec_path, result_path = map(Path, sys.argv[1:3])
    try:
        result = execute(json.loads(spec_path.read_text(encoding="utf-8")))
    except (OSError, ValueError, subprocess.SubprocessError):
        result = {
            "ok": False,
            "error_code": "conversion",
            "message": "Не удалось преобразовать файл в MP3. Возможно, в видео нет аудиодорожки.",
        }
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    temporary.replace(result_path)
