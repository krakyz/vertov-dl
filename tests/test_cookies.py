import json
import os
import time
import urllib.request

import pytest
from fastapi.testclient import TestClient
from media_loader.api import create_app
from media_loader.config import Settings
from media_loader.cookies import MAX_COOKIE_BYTES, CookieError, CookieVault, parse_cookies

TOKEN = "synthetic-cookie-test-key-123456789012345"
HEADER = "# Netscape HTTP Cookie File\n"
CONTENT = HEADER + "#HttpOnly_.example.org\tTRUE\t/\tTRUE\t0\tsession\tsynthetic-value\n"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, auth_token=TOKEN)


def test_vault_encrypts_and_authenticates_content(settings):
    vault = CookieVault(settings)
    result = vault.save(CONTENT)
    assert result["state"] == "configured"
    assert result["session_count"] == 1 and result["expires_at"] is None
    assert b"synthetic-value" not in vault.path.read_bytes()
    assert b"example.org" not in vault.path.read_bytes()
    if os.name == "posix":
        assert vault.path.stat().st_mode & 0o777 == 0o600
        assert vault.directory.stat().st_mode & 0o777 == 0o700
    jar = vault.load()
    request = urllib.request.Request("https://www.example.org/video")
    jar.add_cookie_header(request)
    assert request.get_header("Cookie") == "session=synthetic-value"
    other = urllib.request.Request("https://other.example/video")
    jar.add_cookie_header(other)
    assert other.get_header("Cookie") is None
    blob = vault.path.read_bytes()
    vault.path.write_bytes(blob[:-1] + bytes([blob[-1] ^ 1]))
    with pytest.raises(CookieError, match="расшифровать"):
        vault.load()
    assert vault.status()["state"] == "error"
    vault.save(CONTENT)
    wrong_key = CookieVault(Settings(data_dir=settings.data_dir, auth_token=TOKEN + "different"))
    assert wrong_key.status()["state"] == "error"
    vault.delete()
    assert vault.status()["state"] == "not_configured"


def test_expiry_is_not_a_guaranteed_session_lifetime():
    now = int(time.time())
    text = (
        HEADER
        + "\n".join(
            f".example.org\tTRUE\t/\tTRUE\t{expiry}\tc{index}\tsynthetic"
            for index, expiry in enumerate([now - 100, now + 100, now + 200, 0])
        )
        + "\n"
    )
    status = CookieVault.describe(parse_cookies(text))
    assert status == {
        "state": "configured",
        "count": 4,
        "valid_count": 3,
        "session_count": 1,
        "expires_at": now + 100,
    }
    expired = parse_cookies(HEADER + ".example.org\tTRUE\t/\tTRUE\t1\told\tsynthetic\n")
    assert CookieVault.describe(expired)["state"] == "expired"


@pytest.mark.parametrize(
    "content",
    [
        "[]",
        HEADER,
        HEADER + "bad-row\n",
        CONTENT.replace("TRUE", "MAYBE", 1),
        CONTENT.replace("\t0\t", "\tnot-a-date\t"),
        CONTENT.replace("synthetic-value", "unsafe\x00value"),
        "x" * (MAX_COOKIE_BYTES + 1),
    ],
)
def test_invalid_files_are_rejected_without_echoing_contents(content):
    with pytest.raises(CookieError) as error:
        parse_cookies(content)
    assert "synthetic-value" not in str(error.value)


def test_import_auth_replacement_deletion_and_no_secret_echo(settings):
    with TestClient(create_app(settings, run_manager=False)) as client:
        assert client.put("/api/cookies", json={"content": CONTENT}).status_code == 401
        assert client.delete("/api/cookies").status_code == 401
        client.post("/api/login", json={"token": TOKEN})
        assert (
            client.put(
                "/api/cookies",
                json={"content": CONTENT},
                headers={"Origin": "https://other.example"},
            ).status_code
            == 403
        )
        assert client.put("/api/cookies", content=b"x" * (2 * 1024**2 + 1)).status_code == 413
        imported = client.put("/api/cookies", json={"content": CONTENT})
        assert imported.status_code == 200 and imported.json()["count"] == 1
        status = client.get("/api/status")
        assert status.json()["capabilities"]["cookie_import"] is True
        assert "synthetic-value" not in status.text and "example.org" not in status.text
        bad = client.put("/api/cookies", json={"content": CONTENT + "synthetic-secret\n"})
        assert bad.status_code == 422 and "synthetic-secret" not in bad.text
        assert CookieVault(settings).status()["count"] == 1
        new = CONTENT.replace("session\t", "new\t")
        assert client.put("/api/cookies", json={"content": new}).status_code == 200
        assert [cookie.name for cookie in CookieVault(settings).load()] == ["new"]
        assert client.delete("/api/cookies").json()["state"] == "not_configured"


def test_worker_uses_decrypted_cookies_in_memory(settings, monkeypatch, capsys):
    import http.cookiejar

    import yt_dlp
    from media_loader import task

    CookieVault(settings).save(CONTENT)
    captured = {}

    class Downloader:
        def __init__(self, options):
            captured.update(options)
            self.cookiejar = http.cookiejar.CookieJar()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def extract_info(self, *_args, **_kwargs):
            assert [cookie.value for cookie in self.cookiejar] == ["synthetic-value"]
            return {"title": "Synthetic", "formats": []}

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Downloader)
    monkeypatch.setattr(task, "Settings", lambda: settings)
    monkeypatch.setattr(task, "restrict_python_network", lambda _: None)
    if os.name == "posix":
        import resource

        monkeypatch.setattr(resource, "setrlimit", lambda *_: None)
    result = task.execute(
        {
            "kind": "probe",
            "preset": "best",
            "use_cookies": True,
            "directory": str(settings.data_dir),
            "max_bytes": 1024,
            "proxy": "socks5://127.0.0.1:1",
            "url": "https://example.org/video",
        }
    )
    assert result["ok"] and "cookiefile" not in captured
    assert "synthetic-value" not in json.dumps(result)
    assert "synthetic-value" not in capsys.readouterr().out
    assert not list(settings.data_dir.rglob("*.txt"))
