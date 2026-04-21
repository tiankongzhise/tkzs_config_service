"""客户端配置集中管理模块。"""

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class ClientConfig:
    """配置服务客户端默认配置。"""

    service_url_env: str = "CONFIG_SERVICE_URL"
    default_service_url: str = "https://config-service.hnzzzsw.com"
    token_dir_name: str = "tkzs_service"
    ssl_dir_name: str = ".ssl"
    key_file_prefix: str = "user"
    private_key_suffix: str = "_private_key.pem"
    public_key_suffix: str = "_public_key.pem"
    request_timeout_seconds: int = 30

    @property
    def default_ssl_dir(self) -> Path:
        return Path.home() / self.ssl_dir_name

    @property
    def default_token_dir(self) -> Path:
        return Path.home() / ".config" / self.token_dir_name

    @property
    def default_private_key_path(self) -> Path:
        return self.default_ssl_dir / f"{self.key_file_prefix}{self.private_key_suffix}"

    @property
    def default_public_key_path(self) -> Path:
        return self.default_ssl_dir / f"{self.key_file_prefix}{self.public_key_suffix}"

    def get_service_url(self, override: str | None = None) -> str:
        return override or os.getenv(self.service_url_env, self.default_service_url)

    def private_key_path_for_user(self, username: str) -> Path:
        return self.default_ssl_dir / f"{username}{self.private_key_suffix}"

    def public_key_path_for_user(self, username: str) -> Path:
        return self.default_ssl_dir / f"{username}{self.public_key_suffix}"


DEFAULT_CLIENT_CONFIG = ClientConfig()
