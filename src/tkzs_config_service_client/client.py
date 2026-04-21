"""
配置服务客户端模块

提供从远程配置服务安全获取配置文件的功能。支持用户注册、登录、
配置的上传、更新、删除和下载。采用AES+RSA双重加密确保数据安全。

典型用法：
    from tkzs_config_service import ConfigServiceClient

    # 初始化客户端
    client = ConfigServiceClient()

    # 注册（首次使用）
    client.register("my_username", "my_password")

    # 登录
    client.login("my_username", "my_password")

    # 上传配置
    client.upload_config("mysql.env", "/path/to/mysql.env")

    # 获取配置列表
    configs = client.list_configs()
    print(configs)

    # 下载配置
    client.get_config("mysql.env", save_path="/tmp/mysql.env")

    # 更新配置
    client.update_config("mysql.env", "/path/to/new_mysql.env")

    # 删除配置
    client.delete_config("mysql.env")

依赖环境变量：
    CONFIG_SERVICE_URL    : 配置服务的URL地址（可选，构造函数可指定）
"""

import base64
import io
import logging
import os
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from dotenv import load_dotenv

from .api import APIClient, APIError
from .auth import TokenManager
from .crypto import RSACrypto, AESCrypto, save_private_key, load_private_key, CryptoError
from .config import DEFAULT_CLIENT_CONFIG


class ConfigServiceInitError(Exception):
    """配置服务客户端初始化错误"""
    pass


class ConfigServiceRuntimeError(Exception):
    """配置服务运行时错误（如请求失败、文件写入失败等）"""
    pass


class ConfigServiceResponseCodeError(Exception):
    """响应状态码错误"""
    pass


DEFAULT_SSL_DIR = DEFAULT_CLIENT_CONFIG.default_ssl_dir
DEFAULT_PRIVATE_KEY_PATH = DEFAULT_CLIENT_CONFIG.default_private_key_path
DEFAULT_PUBLIC_KEY_PATH = DEFAULT_CLIENT_CONFIG.default_public_key_path


def _flatten_toml(
        toml_data: dict,
        parent_key: str = "",
        sep: str = "_"
) -> dict:
    """
    递归扁平化TOML字典，将嵌套结构转换为单层键值对。

    例如：
        {"db": {"host": "localhost", "port": 3306}}
        转换为 {"DB_HOST": "localhost", "DB_PORT": "3306"}

    Args:
        toml_data: 待扁平化的TOML字典
        parent_key: 父级键名前缀（用于递归）
        sep: 层级分隔符，默认为下划线

    Returns:
        扁平化后的字典，键名转为大写，值统一转为字符串
    """
    items = []
    for k, v in toml_data.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k

        if isinstance(v, dict):
            items.extend(_flatten_toml(v, new_key, sep=sep).items())
        else:
            items.append((new_key.upper(), str(v)))
    return dict(items)


class ConfigServiceClient:
    """
    配置服务客户端，用于从远程服务安全管理配置文件。

    支持用户注册、登录、配置的上传、更新、删除和下载。
    所有配置文件采用AES+RSA双重加密确保安全。

    Attributes:
        config_service_url: 配置服务的URL
        private_key_path: 用户RSA私钥文件路径
        public_key_path: 用户RSA公钥文件路径
        api_client: API客户端实例
        token_manager: Token管理器实例
        logger: 日志记录器实例
        rsp: 最后一次成功请求的Response对象
    """

    def __init__(
            self,
            config_service_url: Optional[str] = None,
            private_key_path: Optional[Path] = None,
            public_key_path: Optional[Path] = None,
            token_dir: Optional[Path] = None,
            *,
            logger: Optional[logging.Logger] = None,
            default_logger_level: Literal['debug', 'info', 'warning', 'error'] = 'info',
            default_logger_print: bool = True
    ):
        """
        初始化配置服务客户端。

        Args:
            config_service_url: 配置服务的URL。若为None，则从环境变量CONFIG_SERVICE_URL读取
            private_key_path: 用户RSA私钥文件路径。
            public_key_path: 用户RSA公钥文件路径。
            token_dir: Token存储目录，默认为 ~/.config/tkzs_service
            logger: 外部传入的日志记录器
            default_logger_level: 默认logger的日志级别
            default_logger_print: 默认logger是否输出到控制台

        Raises:
            ConfigServiceInitError: 当必需的环境变量缺失或参数无效时抛出
        """
        # 加载.env文件
        load_dotenv()

        # 获取服务URL
        self.config_service_url: str = DEFAULT_CLIENT_CONFIG.get_service_url(config_service_url)

        # 密钥路径
        self.private_key_path = private_key_path or DEFAULT_PRIVATE_KEY_PATH
        self.public_key_path = public_key_path or DEFAULT_PUBLIC_KEY_PATH

        # 初始化组件
        self.token_manager = TokenManager(token_dir)
        self.api_client = APIClient(self.config_service_url, self.token_manager, logger)
        self.logger = logger or self._get_default_logger(default_logger_level, default_logger_print)

        # 响应对象
        self.rsp: Optional[Dict[str, Any]] = None

    @staticmethod
    def _normalize_username(username: str) -> str:
        safe_name = "".join(c if (c.isalnum() or c in ("-", "_", ".")) else "_" for c in username.strip())
        return safe_name or DEFAULT_CLIENT_CONFIG.key_file_prefix

    def _get_key_paths_for_user(self, username: str) -> tuple[Path, Path]:
        normalized = self._normalize_username(username)
        return (
            DEFAULT_CLIENT_CONFIG.private_key_path_for_user(normalized),
            DEFAULT_CLIENT_CONFIG.public_key_path_for_user(normalized),
        )

    def _get_default_logger(self, level: str, print_enabled: bool) -> logging.Logger:
        """获取默认日志记录器"""
        logger = logging.getLogger("config_service_client")
        logger.handlers.clear()
        logger.setLevel({
            'debug': logging.DEBUG,
            'info': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR
        }.get(level, logging.INFO))

        if print_enabled:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def register(self, username: str, password: str) -> Dict[str, Any]:
        """
        用户注册。

        自动生成RSA密钥对，调用服务端注册API，并保存私钥到本地。

        Args:
            username: 用户名
            password: 密码（至少6个字符）

        Returns:
            注册结果，包含user_id

        Raises:
            ConfigServiceInitError: 密钥生成失败
            ConfigServiceRuntimeError: 注册失败
        """
        if len(password) < 6:
            raise ConfigServiceInitError("Password must be at least 6 characters")
        if not username or not username.strip():
            raise ConfigServiceInitError("Username is required")

        self.logger.info(f"Starting registration for user: {username}")

        # 生成RSA密钥对
        try:
            private_pem, public_pem = RSACrypto.generate_keypair()
        except CryptoError as e:
            raise ConfigServiceInitError(f"Failed to generate RSA keypair: {e}")

        # 转换为字符串
        public_key_str = public_pem.decode('utf-8')

        # 调用注册API
        try:
            result = self.api_client.register(username, password, public_key_str)
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Registration failed: {e}")

        # 保存私钥到本地
        try:
            private_key_path, public_key_path = self._get_key_paths_for_user(username)
            save_private_key(private_pem, private_key_path)
            public_key_path.parent.mkdir(parents=True, exist_ok=True)
            public_key_path.write_bytes(public_pem)
            self.private_key_path = private_key_path
            self.public_key_path = public_key_path
            self.logger.info(f"Keys saved to {private_key_path} and {public_key_path}")
        except IOError as e:
            raise ConfigServiceRuntimeError(f"Failed to save keys: {e}")

        self.logger.info(f"✅ Registration successful for user: {username} (ID: {result.get('user_id')})")
        return result

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        用户登录。

        调用服务端登录API，保存JWT Token到本地。

        Args:
            username: 用户名
            password: 密码

        Returns:
            登录结果，包含access_token、expires_in等

        Raises:
            ConfigServiceRuntimeError: 登录失败
        """
        self.logger.info(f"Logging in user: {username}")

        try:
            result = self.api_client.login(username, password)
            private_key_path, public_key_path = self._get_key_paths_for_user(username)
            if private_key_path.exists() and public_key_path.exists():
                self.private_key_path = private_key_path
                self.public_key_path = public_key_path
            self.logger.info(f"✅ Login successful for user: {username}")
            return result
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Login failed: {e}")

    def logout(self) -> None:
        """退出登录，清除本地Token"""
        self.api_client.logout()
        self.logger.info("Logged out successfully")

    def is_authenticated(self) -> bool:
        """
        检查是否已登录

        Returns:
            是否已登录且Token有效
        """
        return self.token_manager.is_authenticated()

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        """
        获取当前用户信息

        Returns:
            包含user_id和username的字典，未登录返回None
        """
        return self.token_manager.get_user_info()

    # ============ 加密/解密辅助方法 ============

    def _encrypt_config_data(self, data: bytes) -> tuple:
        """
        加密配置数据。

        1. 生成随机AES密钥
        2. 使用AES加密数据
        3. 使用RSA公钥加密AES密钥

        Args:
            data: 原始配置数据

        Returns:
            (加密内容base64, 加密的AES密钥base64)
        """
        # 加载公钥
        if not self.public_key_path.exists():
            raise ConfigServiceInitError(f"Public key not found: {self.public_key_path}")

        public_key = RSACrypto.load_public_key(self.public_key_path.read_bytes())

        # 生成AES密钥
        aes_key = AESCrypto.generate_key()

        # AES加密内容
        encrypted_content = AESCrypto.encrypt(data, aes_key)

        # RSA加密AES密钥
        encrypted_aes_key = RSACrypto.encrypt(public_key, aes_key)

        # 返回base64编码
        return base64.b64encode(encrypted_content).decode(), base64.b64encode(encrypted_aes_key).decode()

    def _decrypt_config_data(self, encrypted_content_b64: str,
                              encrypted_aes_key_b64: str) -> bytes:
        """
        解密配置数据。

        1. Base64解码
        2. 使用RSA私钥解密AES密钥
        3. 使用AES密钥解密内容

        Args:
            encrypted_content_b64: Base64编码的加密内容
            encrypted_aes_key_b64: Base64编码的加密AES密钥

        Returns:
            解密后的原始数据
        """
        # 加载私钥
        if not self.private_key_path.exists():
            raise ConfigServiceInitError(f"Private key not found: {self.private_key_path}")

        private_key = RSACrypto.load_private_key(load_private_key(self.private_key_path))

        # Base64解码
        encrypted_content = base64.b64decode(encrypted_content_b64)
        encrypted_aes_key = base64.b64decode(encrypted_aes_key_b64)

        # RSA解密AES密钥
        aes_key = RSACrypto.decrypt(private_key, encrypted_aes_key)

        # AES解密内容
        plaintext = AESCrypto.decrypt(encrypted_content, aes_key)

        return plaintext

    # ============ 配置管理方法 ============

    def upload_config(self, config_name: str, file_path: Union[str, Path],
                      need_decrypt_response: bool = True) -> Dict[str, Any]:
        """
        上传配置文件。

        文件会先在本地使用AES加密，然后上传到服务端。

        Args:
            config_name: 配置名称（将保存到服务端的名称）
            file_path: 本地配置文件路径
            need_decrypt_response: 是否需要解密服务端返回的数据（用于验证）

        Returns:
            上传结果

        Raises:
            ConfigServiceRuntimeError: 上传失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        file_path = Path(file_path)
        if not file_path.exists():
            raise ConfigServiceRuntimeError(f"File not found: {file_path}")

        self.logger.info(f"Uploading config: {config_name} from {file_path}")

        # 读取并加密文件内容
        try:
            data = file_path.read_bytes()
            encrypted_content, encrypted_aes_key = self._encrypt_config_data(data)
        except CryptoError as e:
            raise ConfigServiceRuntimeError(f"Encryption failed: {e}")

        # 上传到服务端
        try:
            result = self.api_client.upload_config(config_name, encrypted_content, encrypted_aes_key)
            self.logger.info(f"✅ Config uploaded successfully: {config_name}")
            return result
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Upload failed: {e}")

    def list_configs(self) -> List[Dict[str, Any]]:
        """
        获取配置列表。

        Returns:
            配置列表，每个元素包含id、config_name、created_at、updated_at

        Raises:
            ConfigServiceRuntimeError: 获取失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        try:
            configs = self.api_client.list_configs()
            self.logger.info(f"Retrieved {len(configs)} configs")
            return configs
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Failed to list configs: {e}")

    def get_config(self, config_name: str, save_path: Optional[Union[str, Path]] = None,
                   load_to_env: Literal['set_temp_env', 'write_local_file', 'all', 'none'] = 'none',
                   need_decrypt: bool = True) -> Optional[bytes]:
        """
        获取并下载配置文件。

        自动解密服务端返回的加密数据，可选择保存到文件或加载到环境变量。

        Args:
            config_name: 配置名称
            save_path: 保存路径，若为None则根据config_name生成
            load_to_env: 是否加载到环境变量或文件：
                - 'set_temp_env': 解析并设置到环境变量
                - 'write_local_file': 写入本地文件（前缀received_）
                - 'all': 同时设置环境变量和写入文件
                - 'none': 不做任何处理，只返回解密后的数据
            need_decrypt: 是否解密数据（若为False则返回加密数据）

        Returns:
            解密后的配置数据，未指定save_path且load_to_env为'none'时返回

        Raises:
            ConfigServiceRuntimeError: 获取失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        self.logger.info(f"Getting config: {config_name}")

        # 从服务端获取
        try:
            data = self.api_client.get_config(config_name)
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Failed to get config: {e}")

        # 解密数据
        if need_decrypt:
            try:
                decrypted_data = self._decrypt_config_data(
                    data['encrypted_content'],
                    data['encrypted_aes_key']
                )
            except CryptoError as e:
                raise ConfigServiceRuntimeError(f"Decryption failed: {e}")
        else:
            decrypted_data = base64.b64decode(data['encrypted_content'])

        self.rsp = data

        # 处理解密后的数据
        normalized_save_path = Path(save_path) if save_path else None
        return self._load_settings(decrypted_data, config_name, normalized_save_path, load_to_env)

    def _load_settings(self, data: bytes, config_name: str,
                       save_path: Optional[Path],
                       model: Literal['set_temp_env', 'write_local_file', 'all', 'none']) -> Optional[bytes]:
        """
        根据指定模式应用配置数据

        Args:
            data: 解密后的配置数据
            config_name: 配置名称
            save_path: 保存路径
            model: 应用模式

        Returns:
            若model为'none'且指定了save_path，返回None；否则返回解密后的数据
        """
        suffix = Path(config_name).suffix.lower()

        if model == 'none':
            if save_path:
                Path(save_path).write_bytes(data)
                self.logger.info(f"Saved to: {save_path}")
            return None if save_path else data

        # 设置环境变量
        if model in ('set_temp_env', 'all'):
            self._set_temp_env(data, suffix)

        # 写入文件
        if model in ('write_local_file', 'all'):
            if save_path is None:
                save_path = Path(f"received_{config_name}")
            Path(save_path).write_bytes(data)
            self.logger.info(f"Saved to: {save_path}")

        return None if save_path else data

    def _set_temp_env(self, data: bytes, suffix: str) -> None:
        """设置环境变量"""
        try:
            if suffix == '.toml':
                content = tomllib.loads(data.decode('utf-8'))
                flatten_data = _flatten_toml(content)
                for key, value in flatten_data.items():
                    os.environ[key] = value
            elif suffix == '.env':
                from dotenv import dotenv_values
                env_vars = dotenv_values(stream=io.StringIO(data.decode("utf-8")))
                for key, value in env_vars.items():
                    if value:
                        os.environ[key] = value
            else:
                self.logger.warning(f"Unsupported file suffix for env loading: {suffix}")
        except Exception as e:
            self.logger.warning(f"Failed to set env vars: {e}")

    def update_config(self, config_name: str, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        更新配置文件。

        Args:
            config_name: 配置名称
            file_path: 本地配置文件路径

        Returns:
            更新结果

        Raises:
            ConfigServiceRuntimeError: 更新失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        file_path = Path(file_path)
        if not file_path.exists():
            raise ConfigServiceRuntimeError(f"File not found: {file_path}")

        self.logger.info(f"Updating config: {config_name}")

        # 读取并加密
        try:
            data = file_path.read_bytes()
            encrypted_content, encrypted_aes_key = self._encrypt_config_data(data)
        except CryptoError as e:
            raise ConfigServiceRuntimeError(f"Encryption failed: {e}")

        # 上传到服务端
        try:
            result = self.api_client.update_config(config_name, encrypted_content, encrypted_aes_key)
            self.logger.info(f"✅ Config updated successfully: {config_name}")
            return result
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Update failed: {e}")

    def delete_config(self, config_name: str) -> Dict[str, Any]:
        """
        删除配置文件。

        Args:
            config_name: 配置名称

        Returns:
            删除结果

        Raises:
            ConfigServiceRuntimeError: 删除失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        self.logger.info(f"Deleting config: {config_name}")

        try:
            result = self.api_client.delete_config(config_name)
            self.logger.info(f"✅ Config deleted successfully: {config_name}")
            return result
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Delete failed: {e}")

    # ============ 向后兼容方法 ============

    def load_config_settings(self, model: Literal['write_local_file', 'set_temp_env', 'all'] = "set_temp_env") -> None:
        """
        向后兼容方法：从服务端获取配置并应用。

        注意：此方法保留用于向后兼容。新代码请使用upload_config/get_config方法。

        Args:
            model: 应用模式（已被忽略，始终使用get_config获取）

        Raises:
            ConfigServiceRuntimeError: 获取失败
        """
        # 从rsp中获取config_name
        config_name = getattr(self, 'config_name', 'config.env')

        self.logger.warning(
            "load_config_settings is deprecated. "
            "Use get_config() with load_to_env parameter instead."
        )

        # 尝试从配置名获取
        if self.rsp:
            self.logger.info(f"Using response from previous request for: {config_name}")
        else:
            self.logger.info(f"Fetching config: {config_name}")
            self.get_config(config_name, load_to_env=model)


def _verify_env_settings(verify_dict: dict) -> None:
    """
    验证当前环境变量是否与期望的键值对完全匹配。

    Args:
        verify_dict: 期望的环境变量字典，键为变量名，值为期望值

    Raises:
        Exception: 当任何环境变量值与期望不符或缺失时
    """
    err = []
    for key, value in verify_dict.items():
        if not os.getenv(key) == value:
            err.append(f'key:{key},should be {value},but os was {os.getenv(key)}')
    if err:
        raise Exception(f"verify env setings fail:{'\n'.join(err)}")
    print('verify_env_success!')


# 导出
__all__ = [
    'ConfigServiceClient',
    'ConfigServiceInitError',
    'ConfigServiceRuntimeError',
    'ConfigServiceResponseCodeError',
    '_verify_env_settings'
]
