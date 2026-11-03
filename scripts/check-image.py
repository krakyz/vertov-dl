"""Smoke-test a built image without source mounts, VPN or external network."""

import subprocess
import sys
import time
import uuid

image = sys.argv[1] if len(sys.argv) > 1 else "vertov-dl:0.1.0-alpha.2"
name = "vertov-dl-smoke-" + uuid.uuid4().hex[:8]
try:
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m,mode=1777",
            "--tmpfs",
            "/data:rw,nosuid,uid=10001,gid=10001,mode=0700",
            "-e",
            "MEDIA_AUTH_TOKEN=synthetic-smoke-test-token-at-least-24",
            image,
        ],
        check=True,
        capture_output=True,
    )
    native = subprocess.run(
        ["docker", "exec", name, "python", "/opt/media-tools/check-native.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    print(native.stdout.strip())
    check = "import json,urllib.request; r=json.load(urllib.request.urlopen('http://127.0.0.1:47831/healthz',timeout=2)); assert r['version']=='0.1.0-alpha.2'; assert 'vertov-dl' in urllib.request.urlopen('http://127.0.0.1:47831/').read().decode(); print(json.dumps(r))"
    for attempt in range(30):
        result = subprocess.run(
            ["docker", "exec", name, "python", "-c", check], capture_output=True, check=False
        )
        if result.returncode == 0:
            print(result.stdout.decode().strip())
            break
        time.sleep(1)
    else:
        raise RuntimeError("Image health/UI smoke failed")
finally:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
