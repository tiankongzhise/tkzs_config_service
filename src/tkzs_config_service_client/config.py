"""客户端配置集中管理模块。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
import os


@dataclass
class ClientConfig:
    """配置服务客户端默认配置。"""

    service_url_env: str = "CONFIG_SERVICE_URL"
    default_service_url: str = os.getenv("CONFIG_SERVICE_URL", "http://localhost:8443")
    token_dir_name: str = "tkzs_service"
    ssl_dir_name: str = ".ssl"
    key_file_prefix: str = "user"
    private_key_suffix: str = "_private_key.pem"
    public_key_suffix: str = "_public_key.pem"
    request_timeout_seconds: int = 30
    service_url_override: Optional[str] = None
    private_key_path_override: Optional[Path] = None
    private_key_dir_override: Optional[Path] = None
    public_key_path_override: Optional[Path] = None
    ssl_dir_override: Optional[Path] = None
    token_dir_override: Optional[Path] = None

    @property
    def default_ssl_dir(self) -> Path:
        return self.ssl_dir_override or (Path.home() / self.ssl_dir_name)

    @property
    def default_token_dir(self) -> Path:
        return self.token_dir_override or (Path.home() / ".config" / self.token_dir_name)

    @property
    def default_private_key_path(self) -> Path:
        return self.private_key_path_override or (self.default_ssl_dir / f"{self.key_file_prefix}{self.private_key_suffix}")

    @property
    def default_public_key_path(self) -> Path:
        return self.public_key_path_override or (self.default_ssl_dir / f"{self.key_file_prefix}{self.public_key_suffix}")

    def get_service_url(self, override: str | None = None) -> str:
        if override:
            return override
        if self.service_url_override:
            return self.service_url_override
        return os.getenv(self.service_url_env, self.default_service_url)

    def private_key_path_for_user(self, username: str) -> Path:
        return self.default_ssl_dir / f"{username}{self.private_key_suffix}"

    def public_key_path_for_user(self, username: str) -> Path:
        return self.default_ssl_dir / f"{username}{self.public_key_suffix}"


DEFAULT_CLIENT_CONFIG = ClientConfig()
_UNSET = object()


def configure_client(
        *,
        service_url: Any = _UNSET,
        request_timeout_seconds: Any = _UNSET,
        ssl_dir: Any = _UNSET,
        token_dir: Any = _UNSET,
        private_key_path: Any = _UNSET,
        private_key_dir: Any = _UNSET,
        public_key_path: Any = _UNSET,
) -> ClientConfig:
    """
    运行时更新全局客户端默认配置。

    适用于从PyPI安装后，通过函数动态修改默认配置，
    避免直接改包内源码。
    """
    if service_url is not _UNSET:
        DEFAULT_CLIENT_CONFIG.service_url_override = service_url
    if request_timeout_seconds is not _UNSET:
        DEFAULT_CLIENT_CONFIG.request_timeout_seconds = request_timeout_seconds if request_timeout_seconds is not None else DEFAULT_CLIENT_CONFIG.request_timeout_seconds
    if ssl_dir is not _UNSET:
        DEFAULT_CLIENT_CONFIG.ssl_dir_override = Path(ssl_dir) if ssl_dir is not None else None
    if token_dir is not _UNSET:
        DEFAULT_CLIENT_CONFIG.token_dir_override = Path(token_dir) if token_dir is not None else None
    if private_key_path is not _UNSET:
        DEFAULT_CLIENT_CONFIG.private_key_path_override = Path(private_key_path) if private_key_path is not None else None
    if private_key_dir is not _UNSET:
        DEFAULT_CLIENT_CONFIG.private_key_dir_override = Path(private_key_dir) if private_key_dir is not None else None
    if public_key_path is not _UNSET:
        DEFAULT_CLIENT_CONFIG.public_key_path_override = Path(public_key_path) if public_key_path is not None else None
    return DEFAULT_CLIENT_CONFIG


def reset_client_config() -> ClientConfig:
    """重置全局客户端默认配置到初始值。"""
    defaults = ClientConfig()
    DEFAULT_CLIENT_CONFIG.service_url_env = defaults.service_url_env
    DEFAULT_CLIENT_CONFIG.default_service_url = defaults.default_service_url
    DEFAULT_CLIENT_CONFIG.token_dir_name = defaults.token_dir_name
    DEFAULT_CLIENT_CONFIG.ssl_dir_name = defaults.ssl_dir_name
    DEFAULT_CLIENT_CONFIG.key_file_prefix = defaults.key_file_prefix
    DEFAULT_CLIENT_CONFIG.private_key_suffix = defaults.private_key_suffix
    DEFAULT_CLIENT_CONFIG.public_key_suffix = defaults.public_key_suffix
    DEFAULT_CLIENT_CONFIG.request_timeout_seconds = defaults.request_timeout_seconds
    DEFAULT_CLIENT_CONFIG.service_url_override = defaults.service_url_override
    DEFAULT_CLIENT_CONFIG.private_key_path_override = defaults.private_key_path_override
    DEFAULT_CLIENT_CONFIG.private_key_dir_override = defaults.private_key_dir_override
    DEFAULT_CLIENT_CONFIG.public_key_path_override = defaults.public_key_path_override
    DEFAULT_CLIENT_CONFIG.ssl_dir_override = defaults.ssl_dir_override
    DEFAULT_CLIENT_CONFIG.token_dir_override = defaults.token_dir_override
    return DEFAULT_CLIENT_CONFIG
