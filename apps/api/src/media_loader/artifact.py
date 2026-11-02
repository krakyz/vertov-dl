"""Inspect only the finalized local artifact, never extractor codec guesses."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path


def inspect_artifact(path: Path):
    location = os.environ.get("MEDIA_FFMPEG_LOCATION")
    executable = str(Path(location) / "ffprobe") if location else shutil.which("ffprobe")
    if not executable:
        raise ValueError("ffprobe unavailable")
    try:
        result = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe,crypto",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,avg_frame_rate:stream_disposition=attached_pic",
                "-of",
                "json",
                str(path.resolve()),
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )
        streams = json.loads(result.stdout).get("streams", [])
        video = next(
            (
                s
                for s in streams
                if s.get("codec_type") == "video"
                and not s.get("disposition", {}).get("attached_pic")
            ),
            None,
        )
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if not video and not audio:
            raise ValueError("No media streams")
        rate = (video or {}).get("avg_frame_rate", "0/1")
        try:
            numerator, denominator = map(float, rate.split("/"))
            fps = round(numerator / denominator, 3) if denominator else None
        except (ValueError, AttributeError):
            fps = None
        return {
            "media_type": "video" if video else "audio",
            "video_codec": video.get("codec_name") if video else None,
            "audio_codec": audio.get("codec_name") if audio else None,
            "width": video.get("width") if video else None,
            "height": video.get("height") if video else None,
            "fps": fps if video else None,
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise ValueError("Cannot inspect final artifact") from error


async def enrich_library(settings, store):
    from .manager import stop_process

    attempted = set()
    while True:
        for job in store.all():
            media = (job.get("details") or {}).get("artifact_media")
            if (
                job["kind"] != "download"
                or job["state"] != "completed"
                or not job["artifact"]
                or (media and "fps" in media)
                or job["id"] in attempted
            ):
                continue
            attempted.add(job["id"])
            directory = (settings.data_dir / "jobs" / job["id"]).resolve()
            path = (directory / job["artifact"]).resolve()
            if path.parent != directory or not path.is_file():
                continue
            process = None
            try:
                import sys

                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "media_loader.artifact",
                    str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=os.name == "posix",
                )
                output, _ = await asyncio.wait_for(process.communicate(), 35)
                if process.returncode == 0:
                    current = store.get(job["id"])
                    if current and current["state"] == "completed" and path.is_file():
                        store.patch_details(job["id"], {"artifact_media": json.loads(output)})
            except (OSError, ValueError, TimeoutError):
                pass
            finally:
                if process:
                    await stop_process(process)
            await asyncio.sleep(0)
        await asyncio.sleep(2)


if __name__ == "__main__":
    import sys

    print(json.dumps(inspect_artifact(Path(sys.argv[1]))))
