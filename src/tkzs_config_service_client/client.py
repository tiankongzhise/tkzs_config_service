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

    # 上传配置（两种写法，v0.5.0: file_path 在前，config_name 在后）
    client.upload_config("/path/to/mysql.env")  # config_name 自动取 mysql.env
    client.upload_config("/path/to/mysql.env", config_name="mysql.env")

    # 获取配置列表
    configs = client.list_configs()
    print(configs)

    # 下载配置
    client.get_config("mysql.env", load_to_env="none", save_dir="/tmp")  # 保存到 /tmp/mysql.env
    client.get_config("mysql.env", load_to_env="none", save_path="/tmp/mysql.env")  # 完整路径

    # 更新配置（两种写法，v0.5.0: file_path 在前，config_name 在后）
    client.update_config("/path/to/new_mysql.env")
    client.update_config("/path/to/new_mysql.env", config_name="mysql.env")

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
from typing import Any, Callable, Dict, List, Literal, Optional, Union

TempEnvLoader = Callable[[bytes, str], None]

from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization

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

        # 密钥路径：构造函数参数 > 全局配置 > 默认值
        if private_key_path is not None:
            self.private_key_path = Path(private_key_path)
        elif DEFAULT_CLIENT_CONFIG.private_key_path_override is not None:
            self.private_key_path = DEFAULT_CLIENT_CONFIG.private_key_path_override
        else:
            self.private_key_path = DEFAULT_CLIENT_CONFIG.default_private_key_path

        if public_key_path is not None:
            self.public_key_path = Path(public_key_path)
        elif DEFAULT_CLIENT_CONFIG.public_key_path_override is not None:
            self.public_key_path = DEFAULT_CLIENT_CONFIG.public_key_path_override
        else:
            self.public_key_path = DEFAULT_CLIENT_CONFIG.default_public_key_path

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

    def _resolve_login_public_key(
            self,
            username: str,
            private_key_path: Path,
            public_key_path: Path,
    ) -> bytes:
        """
        解析登录要上送服务端的公钥（用于账号/密码/公钥三要素校验）。

        规则：
        1) 私钥文件必须存在且可解析；
        2) 若本地已有公钥，要求与私钥推导公钥一致，返回本地公钥；
        3) 若本地无公钥，则由私钥推导生成，并落盘后返回。
        """
        if not private_key_path.exists():
            raise ConfigServiceRuntimeError(
                f"Private key not found for user '{username}': {private_key_path}. "
                "Login is rejected because public key cannot be generated for server verification."
            )

        try:
            private_key_obj = RSACrypto.load_private_key(load_private_key(private_key_path))
            derived_public_pem = private_key_obj.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as e:
            raise ConfigServiceRuntimeError(
                f"Invalid RSA private key format in {private_key_path}: {e}"
            )

        if public_key_path.exists():
            try:
                expected_public_obj = RSACrypto.load_public_key(public_key_path.read_bytes())
                expected_public_pem = expected_public_obj.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            except Exception as e:
                raise ConfigServiceRuntimeError(
                    f"Invalid RSA public key format in {public_key_path}: {e}"
                )

            if expected_public_pem != derived_public_pem:
                raise ConfigServiceRuntimeError(
                    "The provided private key does not match the user's public key. "
                    "Login is rejected for security reasons."
                )
            return expected_public_pem

        try:
            public_key_path.parent.mkdir(parents=True, exist_ok=True)
            public_key_path.write_bytes(derived_public_pem)
        except IOError as e:
            raise ConfigServiceRuntimeError(
                f"Failed to persist derived public key to {public_key_path}: {e}"
            )

        self.logger.info(
            "Public key not found locally for user '%s'; derived from private key and saved to: %s",
            username,
            public_key_path
        )
        return derived_public_pem

    def _load_or_generate_register_keys(
            self,
            user_private_key_path: Optional[Union[str, Path]] = None,
            user_public_key_path: Optional[Union[str, Path]] = None,
    ) -> tuple[bytes, bytes, str]:
        """
        读取用户提供的RSA密钥对（可选）或自动生成。

        返回:
            (private_pem, public_pem, source)
            source: "provided" or "generated"
        """
        if user_private_key_path is None and user_public_key_path is None:
            try:
                private_pem, public_pem = RSACrypto.generate_keypair()
                return private_pem, public_pem, "generated"
            except CryptoError as e:
                raise ConfigServiceInitError(f"Failed to generate RSA keypair: {e}")

        if user_private_key_path is None and user_public_key_path is not None:
            raise ConfigServiceInitError(
                "Register requires user_private_key_path (public key alone is not sufficient "
                "to decrypt configs on this client)."
            )

        private_path = Path(user_private_key_path)
        if not private_path.exists():
            raise ConfigServiceInitError(f"Private key file not found: {private_path}")

        try:
            provided_private_pem = private_path.read_bytes()
            private_key_obj = RSACrypto.load_private_key(provided_private_pem)
            normalized_private_pem = private_key_obj.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            derived_public_pem = private_key_obj.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as e:
            raise ConfigServiceInitError(
                f"Invalid RSA private key format in {private_path}: {e}"
            )

        if user_public_key_path is None:
            return normalized_private_pem, derived_public_pem, "provided"

        public_path = Path(user_public_key_path)
        if not public_path.exists():
            raise ConfigServiceInitError(f"Public key file not found: {public_path}")
        try:
            provided_public_pem = public_path.read_bytes()
            public_key_obj = RSACrypto.load_public_key(provided_public_pem)
            normalized_public_pem = public_key_obj.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        except Exception as e:
            raise ConfigServiceInitError(
                f"Invalid RSA public key format in {public_path}: {e}"
            )
        if normalized_public_pem != derived_public_pem:
            raise ConfigServiceInitError(
                "Provided RSA public key does not match the provided private key"
            )

        return normalized_private_pem, derived_public_pem, "provided"

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

    def register(
            self,
            username: str,
            password: str,
            user_private_key_path: Optional[Union[str, Path]] = None,
            user_public_key_path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        用户注册。

        支持三种方式：
        1) 用户不提供密钥：客户端自动生成RSA密钥对
        2) 仅提供RSA私钥：客户端由私钥推导公钥并完成注册
        3) 成对提供RSA私钥和公钥：校验PEM格式并校验两者是否匹配

        注册时会将该用户密钥写入客户端默认目录，供后续上传/下载/更新时使用。

        Args:
            username: 用户名
            password: 密码（至少6个字符）
            user_private_key_path: 用户自备RSA私钥文件路径（PEM，可选）
            user_public_key_path: 用户自备RSA公钥文件路径（PEM，可选；省略时由私钥推导）

        Returns:
            注册结果，包含user_id

        Raises:
            ConfigServiceInitError: 密钥生成失败或用户提供的密钥格式不正确
            ConfigServiceRuntimeError: 注册失败
        """
        if len(password) < 6:
            raise ConfigServiceInitError("Password must be at least 6 characters")
        if not username or not username.strip():
            raise ConfigServiceInitError("Username is required")

        self.logger.info(f"Starting registration for user: {username}")

        private_pem, public_pem, key_source = self._load_or_generate_register_keys(
            user_private_key_path=user_private_key_path,
            user_public_key_path=user_public_key_path,
        )

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

        if key_source == "generated":
            self.logger.warning(
                "RSA private key auto-generated and saved at: %s. "
                "Please back up this private key securely. "
                "When switching devices, copy and configure the same private key for this account, "
                "otherwise upload/download/update operations will fail even with correct username/password.",
                private_key_path
            )
        else:
            self.logger.info(
                "Using user-provided RSA private key (validated) and synchronized to: %s",
                private_key_path
            )

        self.logger.info(f"✅ Registration successful for user: {username} (ID: {result.get('user_id')})")
        return result

    def login(
            self,
            username: str,
            password: str,
            private_key_path: Optional[Union[str, Path]] = None,
            private_key_dir: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """
        用户登录。

        调用服务端登录API，保存JWT Token到本地。

        Args:
            username: 用户名
            password: 密码
            private_key_path: 登录时指定RSA私钥路径。优先级最高
            private_key_dir: 登录时指定RSA私钥目录。若同层同时指定private_key_path，则private_key_path优先

        Returns:
            登录结果，包含access_token、expires_in等

        Raises:
            ConfigServiceRuntimeError: 登录失败
        """
        self.logger.info(f"Logging in user: {username}")

        try:
            normalized_username = self._normalize_username(username)

            # 私钥路径优先级（跨层，从高到低）：
            # 1) login参数（同层: private_key_path > private_key_dir）
            # 2) 类属性（self.private_key_path，即构造时传入的值）
            # 3) configure_client全局配置（同层: private_key_path > private_key_dir）
            # 4) 默认按用户名推导路径
            if private_key_path is not None:
                resolved_private_key_path = Path(private_key_path)
            elif private_key_dir is not None:
                resolved_private_key_path = Path(private_key_dir) / (
                        f"{normalized_username}{DEFAULT_CLIENT_CONFIG.private_key_suffix}"
                )
            elif self.private_key_path is not None:
                # 类属性优先级高于全局配置
                resolved_private_key_path = self.private_key_path
            elif DEFAULT_CLIENT_CONFIG.private_key_path_override is not None:
                resolved_private_key_path = DEFAULT_CLIENT_CONFIG.private_key_path_override
            elif DEFAULT_CLIENT_CONFIG.private_key_dir_override is not None:
                resolved_private_key_path = DEFAULT_CLIENT_CONFIG.private_key_dir_override / (
                        f"{normalized_username}{DEFAULT_CLIENT_CONFIG.private_key_suffix}"
                )
            else:
                resolved_private_key_path, _ = self._get_key_paths_for_user(username)

            # 公钥路径：优先使用类属性，否则按用户名推导
            if self.public_key_path is not None:
                public_key_path = self.public_key_path
            else:
                _, public_key_path = self._get_key_paths_for_user(username)

            login_public_key_pem = self._resolve_login_public_key(
                username,
                resolved_private_key_path,
                public_key_path,
            )

            result = self.api_client.login(
                username,
                password,
                login_public_key_pem.decode("utf-8"),
            )
            self.private_key_path = resolved_private_key_path
            self.public_key_path = public_key_path

            self.logger.info(f"✅ Login successful for user: {username}")
            return result
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Login failed: {e}")

    def logout(self) -> None:
        """退出登录，清除本地Token"""
        self.api_client.logout()
        self.logger.info("Logged out successfully")

    def deactivate_user(self, username: Optional[str] = None) -> Dict[str, Any]:
        """
        注销用户（逻辑删除，不物理删除）
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        target_username = username or (self.get_user_info() or {}).get("username")
        if not target_username:
            raise ConfigServiceRuntimeError("Username is required to deactivate user")

        try:
            result = self.api_client.deactivate_user(target_username)
            self.logger.info(f"✅ User deactivated successfully: {target_username}")
            return result
        except APIError as e:
            raise ConfigServiceRuntimeError(f"Deactivate user failed: {e}")

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
        # 优先使用公钥文件；若缺失则从私钥动态推导公钥，避免必须额外提供公钥路径
        if self.public_key_path.exists():
            public_key = RSACrypto.load_public_key(self.public_key_path.read_bytes())
        elif self.private_key_path.exists():
            private_key = RSACrypto.load_private_key(load_private_key(self.private_key_path))
            public_key = private_key.public_key()
        else:
            raise ConfigServiceInitError(
                f"Public key not found: {self.public_key_path} and private key not found: {self.private_key_path}. "
                "Please make sure the RSA key files are configured for this account."
            )

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
            raise ConfigServiceInitError(
                f"Private key not found: {self.private_key_path}. "
                "Without the correct private key, encrypted configs cannot be decrypted. "
                "If you switched devices, copy your original private key to this device."
            )

        private_key = RSACrypto.load_private_key(load_private_key(self.private_key_path))

        # Base64解码
        encrypted_content = base64.b64decode(encrypted_content_b64)
        encrypted_aes_key = base64.b64decode(encrypted_aes_key_b64)

        # 兼容两种格式：
        # 1) 单层RSA加密AES密钥（旧数据）
        # 2) 服务端二次分块RSA加密后的AES密钥（新数据）
        try:
            aes_key = RSACrypto.decrypt(private_key, encrypted_aes_key)
            if len(aes_key) != AESCrypto.KEY_SIZE:
                raise CryptoError("Unexpected AES key length after single RSA decrypt")
        except Exception:
            inner_encrypted_aes_key = RSACrypto.decrypt_chunked(private_key, encrypted_aes_key)
            aes_key = RSACrypto.decrypt(private_key, inner_encrypted_aes_key)

        # AES解密内容
        plaintext = AESCrypto.decrypt(encrypted_content, aes_key)

        return plaintext

    # ============ 配置管理方法 ============

    def upload_config(
            self,
            file_path: Union[str, Path],
            config_name: Optional[str] = None,
            need_decrypt_response: bool = True,
    ) -> Dict[str, Any]:
        """
        上传配置文件。

        文件会先在本地使用AES加密，然后上传到服务端。

        Args:
            file_path: 本地配置文件路径（必填）。
            config_name: 服务端上的配置名称（可选）。若为 None，则自动取
                ``Path(file_path).name``（与源文件名一致）。
            need_decrypt_response: 是否需要解密服务端返回的数据（用于验证）

        Returns:
            上传结果

        Raises:
            ConfigServiceRuntimeError: 上传失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        resolved_path = Path(file_path)
        if not resolved_path.exists():
            raise ConfigServiceRuntimeError(f"File not found: {resolved_path.resolve().absolute()}")

        if config_name is None:
            config_name = resolved_path.name

        self.logger.info(f"Uploading config: {config_name} from {resolved_path}")

        # 读取并加密文件内容
        try:
            data = resolved_path.read_bytes()
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

    @staticmethod
    def _resolve_get_config_file_target(
            config_name: str,
            save_dir: Optional[Union[str, Path]],
            save_path: Optional[Union[str, Path]],
            load_to_env: Literal['set_temp_env', 'write_local_file', 'all', 'none'],
    ) -> Optional[Path]:
        """
        解析「写文件」目标路径。``set_temp_env`` 模式不使用磁盘落盘语义，固定返回 None。
        ``load_to_env='none'`` 模式若未指定路径则返回 None（由调用方处理返回值）。
        """
        if load_to_env == "set_temp_env":
            return None
        if save_path is not None:
            return Path(save_path)
        if save_dir is not None:
            return Path(save_dir) / Path(config_name)
        return None

    def get_config(
            self,
            config_name: str,
            *,
            load_to_env: Literal['set_temp_env', 'write_local_file', 'all', 'none'] = 'none',
            save_dir: Optional[Union[str, Path]] = None,
            save_path: Optional[Union[str, Path]] = None,
            temp_env_loader: Optional[TempEnvLoader] = None,
            need_decrypt: bool = True,
    ) -> Optional[bytes]:
        """
        获取并下载配置文件。

        自动解密服务端返回的加密数据，可选择保存到文件或加载到环境变量。

        Args:
            config_name: 配置名称（服务端上的逻辑名，应为纯文件名，如 ``mysql.env``）
            load_to_env: 应用解密结果的方式：
                - ``none``: 不写环境变量；未指定 ``save_dir`` / ``save_path`` 时直接返回解密数据
                - ``set_temp_env``: 仅解析并写入当前进程环境变量
                - ``write_local_file``: 仅写入本地文件
                - ``all``: 先写入环境变量，再写入文件
            save_dir: 保存目录（纯目录路径）；与 ``config_name`` 组合为 ``Path(save_dir) / config_name``
                作为保存路径（``save_path`` 未指定时）。需确保 ``config_name`` 为纯文件名。
            save_path: 本地保存文件的完整路径；优先级高于 ``save_dir``
            temp_env_loader: 当 ``load_to_env`` 为 ``set_temp_env`` 或 ``all`` 时，若传入则
                用该可调用对象替代内置的 ``.env`` / ``.toml`` 解析逻辑；签名为
                ``(decrypted_data: bytes, config_name: str) -> None``。若回调抛出异常，将传播出去。
            need_decrypt: 是否解密数据（若为 False 则按加密载荷处理）

        Returns:
            - ``load_to_env='none'`` 且未指定路径：返回解密后的 ``bytes``
            - ``load_to_env='none'`` 且指定路径：写入文件后返回 ``None``
            - ``load_to_env='set_temp_env'``：返回解密后的 ``bytes``
            - ``write_local_file`` / ``all``：写入文件后返回 ``None``

        Raises:
            ConfigServiceRuntimeError: 获取失败
            用户 ``temp_env_loader`` 抛出的异常
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

        file_target = self._resolve_get_config_file_target(config_name, save_dir, save_path, load_to_env)
        return self._load_settings(
            decrypted_data,
            config_name,
            load_to_env,
            file_target,
            temp_env_loader,
        )

    def _load_settings(
            self,
            data: bytes,
            config_name: str,
            load_to_env: Literal['set_temp_env', 'write_local_file', 'all', 'none'],
            file_target: Optional[Path],
            temp_env_loader: Optional[TempEnvLoader],
    ) -> Optional[bytes]:
        """
        根据指定模式应用解密后的配置数据。

        Args:
            temp_env_loader: 若用户提供了自定义回调，异常将传播给调用方。
        """

        def _apply_env() -> None:
            if temp_env_loader is not None:
                # 用户自定义回调，异常直接传播
                temp_env_loader(data, config_name)
            else:
                suffix = Path(config_name).suffix.lower()
                self._set_temp_env(data, suffix)

        if load_to_env == "none":
            # load_to_env='none' 时：若未指定路径，直接返回数据
            if file_target is None:
                return data
            file_target.parent.mkdir(parents=True, exist_ok=True)
            file_target.write_bytes(data)
            self.logger.info(f"Saved to: {file_target}")
            return None

        if load_to_env == "set_temp_env":
            _apply_env()
            return data

        if load_to_env == "write_local_file":
            out_path = file_target if file_target is not None else Path(f"received_{config_name}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            self.logger.info(f"Saved to: {out_path}")
            return None

        if load_to_env == "all":
            _apply_env()
            out_path = file_target if file_target is not None else Path(f"received_{config_name}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(data)
            self.logger.info(f"Saved to: {out_path}")
            return None

        raise ConfigServiceRuntimeError(f"Unknown load_to_env mode: {load_to_env}")

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

    def update_config(
            self,
            file_path: Union[str, Path],
            config_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        更新配置文件。

        Args:
            file_path: 本地配置文件路径（必填）。
            config_name: 服务端上的配置名称（可选）。若为 None，则自动取
                ``Path(file_path).name``。

        Returns:
            更新结果

        Raises:
            ConfigServiceRuntimeError: 更新失败
        """
        if not self.is_authenticated():
            raise ConfigServiceRuntimeError("Not authenticated. Please login first.")

        resolved_path = Path(file_path)
        if not resolved_path.exists():
            raise ConfigServiceRuntimeError(f"File not found: {resolved_path.resolve().absolute()}")

        if config_name is None:
            config_name = resolved_path.name

        self.logger.info(f"Updating config: {config_name}")

        # 读取并加密
        try:
            data = resolved_path.read_bytes()
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
    'TempEnvLoader',
    '_verify_env_settings'
]
