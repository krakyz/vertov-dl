"""Create a new local access secret; never overwrite or print an existing key."""

import os
import secrets
from pathlib import Path

folder = Path(__file__).resolve().parents[1] / "deploy" / "secrets"
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
path = folder / "media_auth_token.txt"
with path.open("x", encoding="utf-8") as stream:
    stream.write(secrets.token_urlsafe(32))
if os.name == "posix":
    folder.chmod(0o700)
    path.chmod(0o444)
print("Created deploy/secrets/media_auth_token.txt; read it locally to sign in.")
