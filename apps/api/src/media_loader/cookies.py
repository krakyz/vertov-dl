"""Encrypted Netscape cookie storage; plaintext lives only in process memory."""

import hashlib
import hmac
import http.cookiejar
import io
import os
import re
import tempfile
import time
import warnings

from Cryptodome.Cipher import AES

MAX_COOKIE_BYTES = 256 * 1024


class CookieError(ValueError):
    pass


def parse_cookies(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_COOKIE_BYTES:
        raise CookieError("Файл cookies.txt должен быть не больше 256 КиБ.")
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    lines = text.splitlines()
    if not lines or lines[0] not in {"# Netscape HTTP Cookie File", "# HTTP Cookie File"}:
        raise CookieError("Нужен cookies.txt в формате Netscape, не JSON.")
    normalized = ["# Netscape HTTP Cookie File"]
    for line in lines[1:]:
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
        elif line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            raise CookieError("Некорректная строка cookies.txt: ожидаются 7 полей через Tab.")
        domain, subdomains, path, secure, expires, name, value = parts
        if (
            not re.fullmatch(r"\.?[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", domain)
            or subdomains not in {"TRUE", "FALSE"}
            or (subdomains == "TRUE") != domain.startswith(".")
            or secure not in {"TRUE", "FALSE"}
            or not path.startswith("/")
            or (expires and (not expires.isdigit() or len(expires) > 12))
            or not name
            or any(ord(char) < 32 or ord(char) == 127 for char in path + name + value)
        ):
            raise CookieError("Некорректные поля cookies.txt.")
        # MozillaCookieJar treats an empty expiry as a session cookie.
        parts[4] = "" if expires == "0" else expires
        normalized.append("\t".join(parts))
        if len(normalized) > 5001:
            raise CookieError("В файле больше 5000 cookies.")
    jar = http.cookiejar.MozillaCookieJar()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            jar._really_load(io.StringIO("\n".join(normalized) + "\n"), "cookies.txt", True, True)
    except (http.cookiejar.LoadError, ValueError, AssertionError, OverflowError):
        raise CookieError("Не удалось прочитать Netscape cookies.txt.") from None
    if not len(jar):
        raise CookieError("Файл не содержит cookies.")
    return jar


class CookieVault:
    def __init__(self, settings):
        self.directory = settings.data_dir / "secrets"
        self.path = self.directory / "cookies.enc"
        self.key = hmac.new(
            settings.auth_token.get_secret_value().encode(),
            b"media-loader/cookies/v1",
            hashlib.sha256,
        ).digest()

    def load(self):
        try:
            data = self.path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            if not data.startswith(b"MLC1") or len(data) > MAX_COOKIE_BYTES + 36:
                raise ValueError
            cipher = AES.new(self.key, AES.MODE_GCM, nonce=data[4:20])
            cipher.update(b"media-loader/cookies/v1")
            text = cipher.decrypt_and_verify(data[36:], data[20:36]).decode("utf-8")
            return parse_cookies(text)
        except (ValueError, UnicodeError, KeyError, IndexError):
            raise CookieError("Не удалось расшифровать cookies. Импортируй файл заново.") from None

    def save(self, text):
        jar = parse_cookies(text)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        cipher = AES.new(self.key, AES.MODE_GCM)
        cipher.update(b"media-loader/cookies/v1")
        ciphertext, tag = cipher.encrypt_and_digest(text.encode("utf-8"))
        descriptor, temporary = tempfile.mkstemp(prefix="cookies-", dir=self.directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"MLC1" + cipher.nonce + tag + ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.describe(jar)

    def delete(self):
        self.path.unlink(missing_ok=True)

    @staticmethod
    def describe(jar):
        if jar is None:
            return {
                "state": "not_configured",
                "expires_at": None,
                "count": 0,
                "valid_count": 0,
                "session_count": 0,
            }
        valid = [cookie for cookie in jar if not cookie.is_expired(time.time())]
        expiries = [cookie.expires for cookie in valid if cookie.expires is not None]
        return {
            "state": "configured" if valid else "expired",
            "count": len(jar),
            "valid_count": len(valid),
            "session_count": sum(c.expires is None for c in valid),
            "expires_at": min(expiries, default=None),
        }

    def status(self):
        try:
            return self.describe(self.load())
        except CookieError:
            return {
                "state": "error",
                "expires_at": None,
                "count": 0,
                "valid_count": 0,
                "session_count": 0,
            }
