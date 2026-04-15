"""
配置服务客户端模块

提供从远程配置服务安全获取配置文件的功能。客户端使用RSA公钥加密认证信息，
请求指定的配置文件（支持.toml或.env格式），获取后可根据需要：
- 将配置项设置到当前进程的环境变量中（支持TOML扁平化或.env加载）
- 将配置文件内容写入本地文件

典型用法：
    config_client = ConfigServiceClient()
    config_client.load_config_settings('set_temp_env')

依赖环境变量：
    CONFIG_SERVICE_URL    : 配置服务的URL地址
    CONFIG_SERVICE_PASSWORD : 用于生成认证哈希的密码
"""

from pathlib import Path
import os 
import requests
import hashlib
import secrets
import tomllib
from typing import Any, Callable, Literal
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv
import io
import logging
from typing import Protocol

class ConfigServiceInitError(Exception):
    """配置服务客户端初始化错误"""
    pass

class ConfigServiceRuntimeError(Exception):
    """配置服务运行时错误（如请求失败、文件写入失败等）"""
    pass

class ConfigServiceResponeseCodeError(Exception):
    pass

class LoggerProtocol(Protocol):
    """日志记录器协议，定义了客户端所需的日志方法"""
    def debug(self,*args,**kwargs):
        ...
    def info(self,*args,**kwargs):
        ...
    def warning(self,*args,**kwargs):
        ...
    def error(self,*args,**kwargs):
        ...
    def log(self,*args,**kwargs):
        ...

def _flatten_toml(
        toml_data: dict[str, Any],
        parent_key: str = "",
        sep: str = "_"
    ) -> dict[str, str]:
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
            # 转成字符串（环境变量只能存字符串）
            items.append((new_key.upper(), str(v)))
    return dict(items)

def get_logger(name: str, 
               default_level: Literal['debug','info','warning','error'], 
               is_print: bool) -> logging.Logger:
    """
    获取并配置一个简单的控制台日志记录器。

    Args:
        name: 日志记录器名称
        default_level: 默认日志级别，可选 'debug', 'info', 'warning', 'error'
        is_print: 是否输出到控制台；若为True则添加StreamHandler，否则不添加任何处理器

    Returns:
        配置好的logging.Logger实例
    """
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger_level_map = {
        'debug':logging.DEBUG,
        "info":logging.INFO,
        "warning":logging.WARNING,
        "error":logging.ERROR

    }
    logger_level = logger_level_map[default_level]
    if is_print:
        if not logger.handlers:  # 避免重复添加处理器
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logger_level)  # 默认级别
    return logger

class ConfigServiceClient:
    """
    配置服务客户端，用于从远程服务安全获取配置文件并应用。

    客户端使用RSA公钥加密认证信息（包含盐值、密码哈希和配置名），
    请求成功后根据配置文件类型（.toml或.env）将配置加载到环境变量，
    或写入本地文件。

    环境变量要求：
        - CONFIG_SERVICE_URL: 配置服务的URL（若未通过参数提供）
        - CONFIG_SERVICE_PASSWORD: 用于认证的密码（若未通过参数提供）

    Attributes:
        config_name: 要获取的配置文件名
        config_service_url: 配置服务的URL
        public_key: RSA公钥文件路径
        password: 认证密码
        set_temp_env: 用于设置环境变量的回调函数
        logger: 日志记录器实例
        rsp: 最后一次成功请求的Response对象（在load_config_settings后可用）
    """

    def __init__(self,
                 config_name: str = 'mysql.env',
                 config_service_url: str | None = None,
                 public_key: str | Path | None = None,
                 password: str | None = None,
                 set_temp_env: Callable | None = None,
                 *,
                 logger: LoggerProtocol | None = None,
                 default_logger_level: Literal['debug','info','warning','error'] = 'info',
                 default_logger_print: bool = True):
        """
        初始化配置服务客户端。

        Args:
            config_name: 要获取的配置文件名，默认为'config.toml'
            config_service_url: 配置服务的URL。若为None，则从环境变量CONFIG_SERVICE_URL读取
            public_key: RSA公钥文件路径。若为None，默认使用 ~/.ssl/client_public_key.pem
            password: 认证密码。若为None，则从环境变量CONFIG_SERVICE_PASSWORD读取
            set_temp_env: 自定义的设置环境变量回调函数。若不提供，则根据文件扩展名使用内置逻辑
            logger: 外部传入的日志记录器，需符合LoggerProtocol协议。若为None则创建默认logger
            default_logger_level: 默认logger的日志级别
            default_logger_print: 默认logger是否输出到控制台

        Raises:
            ConfigServiceInitError: 当必需的环境变量缺失、公钥文件不存在或参数无效时抛出
        """
        self.config_name = config_name
        self.config_service_url: str = config_service_url or self._safe_get_env('CONFIG_SERVICE_URL')
        self.public_key = self._safe_public_key(public_key)
        self.password: str = password or self._safe_get_env('CONFIG_SERVICE_PASSWORD')
        self.set_temp_env = self._safe_set_temp_env(set_temp_env)
        self.logger = self._safe_logger(logger, default_logger_level, default_logger_print)

    def _safe_logger(self, 
                     logger: LoggerProtocol | None, 
                     default_logger_level: Literal['debug','info','warning','error'], 
                     default_logger_print: bool) -> LoggerProtocol:
        """
        安全获取日志记录器。若未提供外部logger，则创建默认logger。

        Args:
            logger: 外部传入的logger或None
            default_logger_level: 默认logger的级别
            default_logger_print: 默认logger是否打印到控制台

        Returns:
            可用的LoggerProtocol实例
        """
        if logger is None:
            safe_logger = get_logger("config_service_default_logger", default_logger_level, default_logger_print)
        else:
            safe_logger = logger
        return safe_logger
    
    def _safe_set_temp_env(self, set_temp_env: Callable | None) -> Callable:
        """
        安全处理set_temp_env回调。若未提供或不可调用，则使用默认实现。

        Args:
            set_temp_env: 自定义回调或None

        Returns:
            有效的回调函数（默认实现或用户提供的可调用对象）
        """
        if set_temp_env is None:
            return self._default_set_temp_env
        if not callable(set_temp_env):
            return self._default_set_temp_env
        return set_temp_env

    def _toml_to_temp_env(self) -> None:
        """
        将响应内容（TOML格式）解析并设置到环境变量。
        使用_flatten_toml将嵌套结构扁平化，键名转为大写后存入os.environ。
        """
        data = tomllib.loads(self.rsp.text)
        flatten_data = _flatten_toml(data)
        for key, value in flatten_data.items():
            os.environ[key] = value

    def _env_to_temp_env(self) -> None:
        """
        将响应内容（.env格式）通过python-dotenv加载到环境变量。
        """
        load_dotenv(stream=io.StringIO(self.rsp.text))

    def _default_set_temp_env(self) -> None:
        """
        默认的环境变量设置逻辑。
        根据self.config_name的后缀名判断：
            - .toml: 调用_toml_to_temp_env
            - .env : 调用_env_to_temp_env
        其他后缀则记录警告且不做任何操作。
        """
        temp_file = Path(self.config_name)
        suffix = '.'.join(temp_file.suffixes)
        if suffix == '.toml':
            self._toml_to_temp_env()
        elif suffix == '.env':
            self._env_to_temp_env()
        else:
            self.logger.info(f"warning:set temp env is not geving or Callable,and config file is {suffix} not .toml or .env ,default function just support .toml and .env,nothing will be done")

    def _safe_get_env(self, env_name: str) -> str:
        """
        安全获取环境变量，若不存在则抛出初始化错误。

        Args:
            env_name: 环境变量名

        Returns:
            环境变量的值

        Raises:
            ConfigServiceInitError: 当环境变量未设置时
        """
        value = os.getenv(env_name)
        if value:
            return value
        else:
            raise ConfigServiceInitError(f'{env_name} not found!')

    def _safe_public_key(self, public_key: str | Path | None = None) -> Path:
        """
        确定公钥文件路径并检查其存在性。

        Args:
            public_key: 用户指定的公钥路径，可为None、字符串或Path对象

        Returns:
            有效的公钥文件Path对象

        Raises:
            ConfigServiceInitError: 当公钥文件不存在时
        """
        if public_key is None:
            safe_public_key = Path.home() / ".ssl" / "client_public_key.pem"
        else:
            safe_public_key = Path(public_key)
        if not safe_public_key.exists():
            raise ConfigServiceInitError(f"public_key:{safe_public_key} is not exists!")
        return safe_public_key

    def _encrypt_with_rsa(self, data: bytes) -> bytes:
        """
        使用RSA公钥对数据进行PKCS#1 v1.5填充加密。

        Args:
            data: 待加密的字节数据

        Returns:
            加密后的密文字节

        Raises:
            可能抛出cryptography相关的异常（如公钥格式错误）
        """
        with open(self.public_key, "rb") as f:
            public_key = serialization.load_pem_public_key(
                f.read(),
                backend=default_backend()
            )
        return public_key.encrypt(data, padding.PKCS1v15())

    def _write_local_file(self) -> str:
        """
        将响应内容（配置文件）写入本地文件。
        文件名格式为 received_{self.config_name}，保存在当前工作目录。

        Returns:
            写入的本地文件名
        """
        local_file_name = f"received_{self.config_name}"
        with open(local_file_name, "wb") as f:
            f.write(self.rsp.content)
        return local_file_name

    def _load_settings(self, model: Literal['write_local_file','set_temp_env','all']) -> None:
        """
        根据指定的模式应用配置（设置环境变量和/或写入文件）。

        Args:
            model: 操作模式
                - 'set_temp_env': 仅调用set_temp_env将配置加载到环境变量
                - 'write_local_file': 仅将响应内容写入本地文件
                - 'all': 同时执行上述两项操作

        Raises:
            ConfigServiceRuntimeError: 当执行过程中发生任何异常时，将原始异常包装后抛出
        """
        try:
            if model == 'set_temp_env':
                self.set_temp_env()
            elif model == "write_local_file":
                self._write_local_file()
            elif model == 'all':
                self.set_temp_env()
                self._write_local_file()
            else:
                raise ConfigServiceRuntimeError(f"load_config_settings model get unsupport key:{model},check input ")
        except Exception as e:
            raise ConfigServiceRuntimeError(f'load config fail at model:{model},exception:{e}') from e

    def load_config_settings(self, model: Literal['write_local_file','set_temp_env','all'] = "set_temp_env") -> None:
        """
        向配置服务发起请求，获取配置文件并根据模型应用配置。

        工作流程：
            1. 生成随机盐值，计算 (salt + password) 的SHA256哈希
            2. 构造明文字符串 "{salt}:{hash}:{config_name}" 并用RSA公钥加密
            3. 向配置服务URL发送POST请求，携带加密数据
            4. 若响应状态码为200，则根据model参数调用_load_settings应用配置
            5. 记录成功或失败信息到日志

        Args:
            model: 应用模式，默认为'set_temp_env'。可选值：
                - 'set_temp_env': 将配置加载到当前进程的环境变量
                - 'write_local_file': 将配置写入本地文件（前缀received_）
                - 'all': 同时进行环境变量加载和文件写入

        Note:
            该方法会设置self.rsp属性为成功的响应对象，供内部方法使用。
            请求时默认启用SSL证书验证（verify=True），若证书验证失败会记录错误。
        """
        salt = secrets.token_hex(8)
        m = hashlib.sha256()
        m.update((salt + self.password).encode('utf-8'))
        client_hash = m.hexdigest()

        plain_text = f"{salt}:{client_hash}:{self.config_name}".encode('utf-8')
        encrypted = self._encrypt_with_rsa(plain_text)

        # 客户端默认验证服务器证书（CA 签发）
        # 若使用自签名证书测试，可设置 verify=False 或指定 CA 包
        try:
            response = requests.post(self.config_service_url, data=encrypted, verify=True)  # 生产环境 verify=True
            if response.status_code == 200:
                self.logger.info(f"✅ Got config '{self.config_name}':")
                self.rsp = response
                self._load_settings(model)
                self.logger.info(f'load_config_settings success at model:{model}')

            elif response.status_code == 401:
                self.logger.info("❌ Password error")
                raise ConfigServiceResponeseCodeError("❌ Password error")
            elif response.status_code == 404:
                self.logger.info(f"❌ Config file '{self.config_name}' not found")
                raise ConfigServiceResponeseCodeError(f"❌ Config file '{self.config_name}' not found")
            else:
                self.logger.info(f"⚠️  Server returned {response.status_code}")
                raise ConfigServiceResponeseCodeError(f"⚠️  Server returned {response.status_code}")
        except requests.exceptions.SSLError:
            self.logger.info("❌ SSL certificate validation failed. Are you using a CA-signed certificate?")
            raise requests.exceptions.SSLError
        except Exception as e:
            self.logger.info(f"❌ Request failed: {e}")
            raise e


def _verify_env_setings(verify_dict: dict) -> None:
    """
    验证当前环境变量是否与期望的键值对完全匹配。

    Args:
        verify_dict: 期望的环境变量字典，键为变量名，值为期望值

    Raises:
        Exception: 当任何环境变量值与期望不符或缺失时，汇总所有差异并抛出异常
    """
    err = []
    for key, value in verify_dict.items():
        if not os.getenv(key) == value:
            err.append(f'key:{key},should be {value},but os was {os.getenv(key)}')
    if err:
        raise Exception(f"verify env setings fail:{'\n'.join(err)}")
    print('verify_env_success!')

if __name__ == "__main__":
    # 示例：验证从配置服务获取的特定环境变量
    verify_dict = {
        "DB_HOST":"rm-7xv8ckj51yk3tvssryo.mysql.rds.aliyuncs.com",
        "DB_PORT":'3306',
        "DB_NAME":"object_backup_test_new",
        "DB_USER":"ali_mysql",
        "DB_PASSWORD":"Xc_3kyi1JG9dMSv6",
        "BAIDU_PAN_TOKEN":"121.e0acb6c57fbfc46a2bb5d62212a7ed4b.YGkbJzF7HHuUtuwW7E976xf5Rg4uDk5jLmllSww.AhJzuA"
    }

    config_service = ConfigServiceClient()
    try:
        config_service.load_config_settings('all')
        _verify_env_setings(verify_dict)
    except Exception as e:
        raise e