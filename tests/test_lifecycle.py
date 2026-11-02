from media_loader.config import Settings
from media_loader.manager import Manager
from media_loader.store import Store
from media_loader.task import error_details


def test_recovery_preserves_queued_and_fails_interrupted(tmp_path):
    settings = Settings(data_dir=tmp_path, auth_token="test-token-only-123456789012345")
    store = Store(tmp_path)
    queued = store.create("probe", "https://example.org/a")
    interrupted = store.create("download", "https://example.org/b")
    store.update(interrupted["id"], state="downloading")
    Manager(settings, store, 1).recover()
    assert store.get(queued["id"])["state"] == "queued"
    assert store.get(interrupted["id"])["error_code"] == "interrupted"


def test_errors_do_not_leak_signed_urls_or_cookies():
    secret = "https://example.org/?secret=value Cookie: session=private"
    code, message = error_details("HTTP Error 403 " + secret)
    assert code == "access_denied"
    assert "secret" not in message and "private" not in message
