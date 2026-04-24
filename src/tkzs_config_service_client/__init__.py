"""
tkzs-config-service-client

配置服务客户端，提供安全的配置文件管理功能。

主要功能：
- 用户注册和登录（JWT认证）
- 配置上传、更新、删除
- 配置文件加密传输（AES+RSA双重加密）
"""

from .client import (
    ConfigServiceClient,
    ConfigServiceInitError,
    ConfigServiceRuntimeError,
    ConfigServiceResponseCodeError,
    TempEnvLoader,
    _verify_env_settings
)
from .api import APIError, APIClient
from .auth import TokenManager, AuthError
from .crypto import RSACrypto, AESCrypto, CryptoError
from .config import ClientConfig, DEFAULT_CLIENT_CONFIG, configure_client, reset_client_config

__version__ = "0.5.1"

__all__ = [
    # 主客户端
    'ConfigServiceClient',
    'ConfigServiceInitError',
    'ConfigServiceRuntimeError',
    'ConfigServiceResponseCodeError',
    'TempEnvLoader',
    '_verify_env_settings',

    # API
    'APIError',
    'APIClient',

    # 认证
    'TokenManager',
    'AuthError',

    # 加密
    'RSACrypto',
    'AESCrypto',
    'CryptoError',
    'ClientConfig',
    'DEFAULT_CLIENT_CONFIG',
    'configure_client',
    'reset_client_config',
]
