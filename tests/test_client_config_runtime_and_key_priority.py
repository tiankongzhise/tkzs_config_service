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


def test_login_private_key_priority(tmp_path: Path):
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    username = "priority_user"
    login_arg_private = tmp_path / "keys" / "login_arg_private.pem"
    config_private = tmp_path / "keys" / "config_private.pem"
    default_private = ssl_dir / f"{username}_private_key.pem"
    default_public = ssl_dir / f"{username}_public_key.pem"

    _prepare_keypair(login_arg_private, default_public)
    _prepare_private_key(config_private)
    private_pem, public_pem = RSACrypto.generate_keypair()
    default_private.parent.mkdir(parents=True, exist_ok=True)
    default_private.write_bytes(private_pem)

    configure_client(ssl_dir=ssl_dir, private_key_path=config_private)
    client = ConfigServiceClient(config_service_url=TEST_DEV.service_url)
    client.api_client.login = lambda *_args, **_kwargs: {
        "access_token": "fake-token",
        "expires_in": 3600,
        "user_id": 1,
        "username": username,
    }

    client.login(username, "password123", private_key_path=login_arg_private)
    assert client.private_key_path == login_arg_private

    # 改为 config 私钥来源时，同步更新该用户公钥以匹配 config 私钥
    _prepare_keypair(config_private, default_public)
    client.login(username, "password123")
    assert client.private_key_path == config_private

    # 改为默认私钥来源时，同步更新该用户公钥以匹配默认私钥
    default_public.write_bytes(public_pem)
    configure_client(private_key_path=None)
    client.login(username, "password123")
    assert client.private_key_path == default_private

    reset_client_config()


def test_login_private_key_path_beats_private_key_dir_in_same_level(tmp_path: Path):
    reset_client_config()
    username = "same_level_user"
    login_private = tmp_path / "login" / "explicit.pem"
    login_dir = tmp_path / "login_dir"
    login_dir_private = login_dir / f"{username}_private_key.pem"
    config_private = tmp_path / "config" / "config.pem"

    _prepare_private_key(login_private)
    _prepare_private_key(login_dir_private)
    _prepare_private_key(config_private)

    configure_client(private_key_path=config_private)
    client = ConfigServiceClient(config_service_url="http://unit-test")
    client.api_client.login = lambda *_args, **_kwargs: {
        "access_token": "fake-token",
        "expires_in": 3600,
        "user_id": 1,
        "username": username,
    }

    client.login(
        username,
        "password123",
        private_key_path=login_private,
        private_key_dir=login_dir,
    )
    assert client.private_key_path == login_private
    reset_client_config()


def test_login_level_priority_login_over_config_with_private_key_dir(tmp_path: Path):
    reset_client_config()
    username = "cross_level_user"
    config_dir = tmp_path / "config_dir"
    login_dir = tmp_path / "login_dir"
    config_private = config_dir / f"{username}_private_key.pem"
    login_private = login_dir / f"{username}_private_key.pem"

    _prepare_private_key(config_private)
    _prepare_private_key(login_private)

    configure_client(private_key_dir=config_dir)
    client = ConfigServiceClient(config_service_url="http://unit-test")
    client.api_client.login = lambda *_args, **_kwargs: {
        "access_token": "fake-token",
        "expires_in": 3600,
        "user_id": 1,
        "username": username,
    }

    client.login(username, "password123", private_key_dir=login_dir)
    assert client.private_key_path == login_private
    reset_client_config()


def test_encrypt_uses_private_key_when_public_missing(tmp_path: Path):
    reset_client_config()


def test_login_rejects_mismatched_private_key_and_clears_token(tmp_path: Path):
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    username = "security_user"
    correct_private = ssl_dir / f"{username}_private_key.pem"
    public_path = ssl_dir / f"{username}_public_key.pem"
    wrong_private = tmp_path / "keys" / "wrong_private.pem"
    token_dir = tmp_path / "token_dir"

    correct_private_pem, correct_public_pem = RSACrypto.generate_keypair()
    correct_private.parent.mkdir(parents=True, exist_ok=True)
    correct_private.write_bytes(correct_private_pem)
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

    with pytest.raises(ConfigServiceRuntimeError, match="does not match"):
        client.login(username, "password123", private_key_path=wrong_private)

    assert client.token_manager.get_token() is None
    reset_client_config()


def test_login_derives_public_key_when_local_missing(tmp_path: Path):
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    username = "derive_pub_user"
    private_path = ssl_dir / f"{username}_private_key.pem"
    public_path = ssl_dir / f"{username}_public_key.pem"

    private_pem, public_pem = RSACrypto.generate_keypair()
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private_path.write_bytes(private_pem)

    configure_client(ssl_dir=ssl_dir)
    client = ConfigServiceClient(config_service_url="http://unit-test")
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
