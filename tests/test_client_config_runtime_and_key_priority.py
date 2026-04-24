import os
from pathlib import Path
from dataclasses import dataclass

import pytest

from tkzs_config_service_client import (
    ConfigServiceClient,
    ConfigServiceRuntimeError,
    configure_client,
    reset_client_config,
)
from tkzs_config_service_client.crypto import RSACrypto


@dataclass
class TestDevConfig:
    """测试环境配置，优先从环境变量获取，否则使用默认值。"""

    # 测试用服务 URL，优先从环境变量获取
    service_url: str = os.getenv("TEST_CONFIG_SERVICE_URL", "http://unit-test")
    runtime_config_url: str = os.getenv("TEST_RUNTIME_CONFIG_URL", "http://runtime-config-service")


TEST_DEV = TestDevConfig()


def _prepare_private_key(path: Path) -> None:
    private_pem, _ = RSACrypto.generate_keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(private_pem)


def _prepare_keypair(private_path: Path, public_path: Path) -> None:
    private_pem, public_pem = RSACrypto.generate_keypair()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)


def test_runtime_configure_client_affects_new_instance(tmp_path: Path):
    """验证 configure_client 全局配置能影响新实例"""
    reset_client_config()
    custom_ssl_dir = tmp_path / "custom_ssl"
    custom_token_dir = tmp_path / "custom_token"
    custom_private_key = custom_ssl_dir / "runtime_private.pem"

    configure_client(
        service_url=TEST_DEV.runtime_config_url,
        ssl_dir=custom_ssl_dir,
        token_dir=custom_token_dir,
        private_key_path=custom_private_key,
        request_timeout_seconds=17,
    )

    client = ConfigServiceClient()
    assert client.config_service_url == TEST_DEV.runtime_config_url
    assert client.private_key_path == custom_private_key
    assert client.token_manager.token_dir == custom_token_dir
    assert client.api_client.timeout == 17

    reset_client_config()


def test_login_rejects_mismatched_private_key_and_clears_token(tmp_path: Path):
    """验证当私钥与公钥不匹配时，login 会拒绝并清除 token"""
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    username = "security_user"
    # 公钥路径使用默认前缀 "user"，因为 configure_client(ssl_dir=...) 会设置默认路径
    public_path = ssl_dir / "user_public_key.pem"
    wrong_private = tmp_path / "keys" / "wrong_private.pem"
    token_dir = tmp_path / "token_dir"

    correct_private_pem, correct_public_pem = RSACrypto.generate_keypair()
    # 将匹配的私钥写入 login 方法会使用的默认路径
    default_private_path = ssl_dir / "user_private_key.pem"
    default_private_path.parent.mkdir(parents=True, exist_ok=True)
    default_private_path.write_bytes(correct_private_pem)
    public_path.write_bytes(correct_public_pem)
    _prepare_private_key(wrong_private)

    configure_client(ssl_dir=ssl_dir, token_dir=token_dir)
    client = ConfigServiceClient(config_service_url="http://unit-test")

    def _fake_login(_username: str, _password: str, _public_key: str):
        payload = {
            "access_token": "fake-token",
            "expires_in": 3600,
            "user_id": 1,
            "username": username,
        }
        client.token_manager.save_token(**payload)
        return payload

    client.api_client.login = _fake_login

    # 使用不匹配的私钥（wrong_private 与默认 public_path 不匹配）
    with pytest.raises(ConfigServiceRuntimeError, match="does not match"):
        client.login(username, "password123", private_key_path=wrong_private)

    assert client.token_manager.get_token() is None
    reset_client_config()


def test_login_derives_public_key_when_local_missing(tmp_path: Path):
    """
    验证当本地公钥缺失时，客户端会由私钥推导并保存公钥。

    准备私钥在用户推导路径（ssl_dir/derive_pub_user_private_key.pem），
    公钥也会被推导保存到对应的位置（ssl_dir/derive_pub_user_public_key.pem）。
    """
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    username = "derive_pub_user"
    # 私钥和公钥路径都使用用户名推导
    private_path = ssl_dir / "derive_pub_user_private_key.pem"
    public_path = ssl_dir / "derive_pub_user_public_key.pem"

    private_pem, public_pem = RSACrypto.generate_keypair()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private_pem)

    configure_client(ssl_dir=ssl_dir)
    client = ConfigServiceClient(config_service_url="http://unit-test")
    # 清空类属性，让 login 使用默认推导路径
    client.private_key_path = None
    client.public_key_path = None  # 也要清空公钥
    captured: dict = {}

    def _fake_login(_username: str, _password: str, _public_key: str):
        captured["username"] = _username
        captured["public_key"] = _public_key
        payload = {
            "access_token": "fake-token",
            "expires_in": 3600,
            "user_id": 1,
            "username": _username,
        }
        client.token_manager.save_token(**payload)
        return payload

    client.api_client.login = _fake_login
    client.login(username, "password123")

    assert captured["username"] == username
    assert captured["public_key"] == public_pem.decode("utf-8")
    assert public_path.exists()
    assert public_path.read_bytes() == public_pem

    # 验证加密时可以使用只有私钥的情况（公钥由私钥推导）
    reset_client_config()
    private_key_path = tmp_path / "only_private.pem"
    _prepare_private_key(private_key_path)

    client = ConfigServiceClient(
        config_service_url=TEST_DEV.service_url,
        private_key_path=private_key_path,
        public_key_path=tmp_path / "missing_public.pem",
    )

    encrypted_content, encrypted_aes_key = client._encrypt_config_data(b"hello")
    assert encrypted_content
    assert encrypted_aes_key

    reset_client_config()


def test_class_attribute_overrides_global_config(tmp_path: Path):
    """
    验证类属性（构造函数参数）优先级高于全局配置（configure_client）。

    优先级链：构造函数参数 > configure_client全局配置 > 默认值
    """
    reset_client_config()
    ssl_dir = tmp_path / "ssl"

    # 准备三种不同层级的私钥
    global_private = tmp_path / "global_private.pem"
    class_private = tmp_path / "class_private.pem"
    default_private = ssl_dir / "default_private.pem"

    _prepare_private_key(global_private)
    _prepare_private_key(class_private)
    _prepare_private_key(default_private)

    # 场景1：configure_client 设置全局配置
    configure_client(
        ssl_dir=ssl_dir,
        private_key_path=global_private,
    )

    # 场景2：构造函数参数应覆盖全局配置
    client = ConfigServiceClient(
        config_service_url=TEST_DEV.service_url,
        private_key_path=class_private,
    )
    # 类属性优先级高于全局配置
    assert client.private_key_path == class_private

    reset_client_config()


def test_login_uses_class_attribute_over_global_config(tmp_path: Path):
    """
    验证 login 方法中类属性优先级高于全局配置。

    优先级链：login参数 > 类属性 > configure_client全局配置 > 默认值
    """
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    username = "priority_test_user"

    # 准备不同层级的私钥
    global_private = tmp_path / "global_private.pem"
    class_private = tmp_path / "class_private.pem"
    default_private = ssl_dir / f"{username}_private_key.pem"
    default_public = ssl_dir / f"{username}_public_key.pem"

    # 为不同私钥准备匹配的公钥
    _prepare_keypair(global_private, default_public)
    _prepare_keypair(class_private, default_public)

    # 全局配置指向 global_private
    configure_client(
        ssl_dir=ssl_dir,
        private_key_path=global_private,
    )

    # 构造函数使用 class_private
    client = ConfigServiceClient(
        config_service_url=TEST_DEV.service_url,
        private_key_path=class_private,
    )
    client.api_client.login = lambda *_args, **_kwargs: {
        "access_token": "fake-token",
        "expires_in": 3600,
        "user_id": 1,
        "username": username,
    }

    # login 不传参数时，应使用类属性（class_private），而非全局配置（global_private）
    client.login(username, "password123")
    assert client.private_key_path == class_private, \
        f"Expected class_private, got {client.private_key_path}"

    reset_client_config()


def test_init_respects_global_config_when_no_constructor_arg(tmp_path: Path):
    """
    验证构造函数不传参数时，正确使用全局配置。
    """
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    global_private = ssl_dir / "global_default_private.pem"
    global_public = ssl_dir / "global_default_public.pem"

    _prepare_keypair(global_private, global_public)

    configure_client(
        ssl_dir=ssl_dir,
        private_key_path=global_private,
    )

    # 构造函数不传参数，应使用全局配置
    client = ConfigServiceClient(config_service_url=TEST_DEV.service_url)
    assert client.private_key_path == global_private

    reset_client_config()


def test_init_constructor_arg_overrides_global_config(tmp_path: Path):
    """
    验证构造函数参数优先级高于全局配置。
    """
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    global_private = ssl_dir / "global_private.pem"
    explicit_private = tmp_path / "explicit_private.pem"

    _prepare_private_key(global_private)
    _prepare_private_key(explicit_private)

    configure_client(
        ssl_dir=ssl_dir,
        private_key_path=global_private,
    )

    # 构造函数传参数，应覆盖全局配置
    client = ConfigServiceClient(
        config_service_url=TEST_DEV.service_url,
        private_key_path=explicit_private,
    )
    assert client.private_key_path == explicit_private

    reset_client_config()
