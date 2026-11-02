#!/usr/local/bin/python
"""Prevent ffmpeg/ffprobe child processes from opening network protocols."""

import os
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
if tool == "ffprobe":
    args = ["-protocol_whitelist", "file,pipe,crypto", *args]
else:
    guarded = []
    for arg in args:
        if arg == "-i":
            guarded.extend(["-protocol_whitelist", "file,pipe,crypto"])
        guarded.append(arg)
    args = guarded
os.execv(f"/usr/bin/{tool}", [tool, *args])
