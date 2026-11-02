"""Verify the Debian security backport for CVE-2026-8461 in the runtime image."""

import json
import subprocess
from pathlib import Path

MINIMUM = "7:7.1.5-0+deb13u1"
PACKAGES = ("ffmpeg", "libavcodec61", "libavformat61", "libavutil59")
TRACKER = "https://security-tracker.debian.org/tracker/CVE-2026-8461"


def audit_native():
    release = dict(
        line.split("=", 1)
        for line in Path("/etc/os-release").read_text().splitlines()
        if "=" in line
    )
    if (
        release.get("ID", "").strip('"') != "debian"
        or release.get("VERSION_CODENAME", "").strip('"') != "trixie"
    ):
        raise RuntimeError("Native security policy requires Debian trixie")
    versions = {}
    for package in PACKAGES:
        query = subprocess.run(
            ["dpkg-query", "-W", "-f=${Version}", package],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = query.stdout.strip()
        comparison = subprocess.run(
            ["dpkg", "--compare-versions", version, "ge", MINIMUM],
            check=False,
            capture_output=True,
            timeout=10,
        )
        if comparison.returncode != 0:
            raise RuntimeError(
                f"{package} {version} does not meet CVE-2026-8461 policy ({MINIMUM})"
            )
        versions[package] = version
    if len(set(versions.values())) != 1:
        raise RuntimeError("FFmpeg runtime libraries must come from the same package version")
    return {
        "suite": "trixie",
        "packages": versions,
        "security_check": {
            "cve": "CVE-2026-8461",
            "method": "Debian trixie security-backport version floor checked with dpkg",
            "minimum_fixed": MINIMUM,
            "source": TRACKER,
        },
    }


if __name__ == "__main__":
    print(json.dumps(audit_native(), sort_keys=True))
