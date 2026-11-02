"""Real yt-dlp HTTP downloader resumes a partial file across process restarts."""

import hashlib
import http.server
import subprocess
import sys
import threading


def test_http_partial_resume_across_process_restart(tmp_path):
    payload = bytes(range(256)) * 8192
    ranges = []
    first = True

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            nonlocal first
            header = self.headers.get("Range")
            ranges.append(header)
            offset = int(header.split("=")[1].split("-")[0]) if header else 0
            self.send_response(206 if header else 200)
            self.send_header("Content-Length", str(len(payload) - offset))
            if header:
                self.send_header(
                    "Content-Range", f"bytes {offset}-{len(payload) - 1}/{len(payload)}"
                )
            self.end_headers()
            if first:
                first = False
                self.wfile.write(payload[: len(payload) // 2])
                self.wfile.flush()
                self.close_connection = True
            else:
                self.wfile.write(payload[offset:])

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "media.bin"
    code = """
import sys,yt_dlp
from yt_dlp.downloader.http import HttpFD
with yt_dlp.YoutubeDL({'quiet':True,'noprogress':True,'retries':0,'continuedl':True,'proxy':''}) as ydl:
    result = HttpFD(ydl,ydl.params).download(sys.argv[2], {'url':sys.argv[1], 'ext':'bin', 'http_headers':{}})
    raise SystemExit(0 if result[0] else 1)
"""
    args = [sys.executable, "-c", code, f"http://127.0.0.1:{server.server_port}/media", str(output)]
    try:
        first_run = subprocess.run(args, capture_output=True, timeout=20, check=False)
        assert first_run.returncode != 0
        part = tmp_path / "media.bin.part"
        assert 0 < part.stat().st_size < len(payload)
        second_run = subprocess.run(args, capture_output=True, timeout=20, check=False)
        assert second_run.returncode == 0, second_run.stderr.decode(errors="replace")
        assert hashlib.sha256(output.read_bytes()).digest() == hashlib.sha256(payload).digest()
        assert any(value and int(value.split("=")[1].split("-")[0]) > 0 for value in ranges)
        assert not part.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
