from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIA_", hide_input_in_errors=True)

    host: str = "127.0.0.1"
    port: int = 47831
    data_dir: Path = Path(".data")
    web_dir: Path = Path("apps/web/dist")
    auth_token: SecretStr = SecretStr("")
    auth_token_file: Path | None = None
    proxy_url: str = Field(default="socks5h://127.0.0.1:20170", repr=False)
    require_proxy: bool = True
    secure_cookie: bool = False  # HTTP only for loopback SSH tunnel; enable for HTTPS.
    max_file_bytes: int = Field(default=2 * 1024**3, ge=1024)
    reserve_bytes: int = Field(default=2 * 1024**3, ge=0)
    task_timeout: int = Field(default=1800, ge=5)
    retention_hours: int = Field(default=30 * 24, ge=1)
    library_max_bytes: int = Field(default=10 * 1024**3, ge=1024)
    temporary_retention_hours: int = Field(default=7 * 24, ge=1)
    temporary_max_bytes: int = Field(default=10 * 1024**3, ge=1024)
    max_jobs: int = Field(default=100, ge=1, le=1000)
    guard_port: int = Field(default=0, ge=0, le=65535)

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.auth_token_file:
            self.auth_token = SecretStr(self.auth_token_file.read_text().strip())
        if len(self.auth_token.get_secret_value()) < 24:
            raise ValueError("Set a random MEDIA_AUTH_TOKEN or token file (24+ characters)")
        proxy = urlsplit(self.proxy_url)
        if proxy.scheme != "socks5h" or not proxy.hostname or not proxy.port:
            raise ValueError("MEDIA_PROXY_URL must be a SOCKS5h endpoint")
        if proxy.username or proxy.password or proxy.path or proxy.query or proxy.fragment:
            raise ValueError("Authenticated proxies are not supported by this test version")
        if not self.require_proxy:
            raise ValueError("Direct network access is disabled in the test version")
        return self
