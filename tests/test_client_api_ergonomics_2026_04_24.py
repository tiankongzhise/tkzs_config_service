"""客户端 API 易用性（2026-04-24）：仅私钥注册、单路径上传/更新、get_config 路径与自定义 env loader。

v0.5.0 Breaking Changes:
- upload_config(): file_path 移至第一位，config_name 移至第二位
- update_config(): file_path 移至第一位，config_name 移至第二位
- get_config(): save_dir 移至 save_path 之前
- temp_env_loader 抛出的异常会传播出去
"""

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from tkzs_config_service_client import (
    ConfigServiceClient,
    ConfigServiceInitError,
    configure_client,
    reset_client_config,
)
from tkzs_config_service_client.crypto import RSACrypto


def _write_private_only(path: Path) -> bytes:
    private_pem, _ = RSACrypto.generate_keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(private_pem)
    return private_pem


def test_register_rejects_public_key_only(tmp_path: Path):
    reset_client_config()
    configure_client(ssl_dir=tmp_path / "ssl")
    pub_path = tmp_path / "only_pub.pem"
    _, public_pem = RSACrypto.generate_keypair()
    pub_path.write_bytes(public_pem)

    client = ConfigServiceClient(config_service_url="http://unit-test")
    with pytest.raises(ConfigServiceInitError, match="Register requires user_private_key_path"):
        client.register(
            "u1",
            "secret12",
            user_public_key_path=pub_path,
        )
    reset_client_config()


def test_register_private_key_only_derives_public(tmp_path: Path):
    reset_client_config()
    ssl_dir = tmp_path / "ssl"
    configure_client(ssl_dir=ssl_dir)
    priv_path = tmp_path / "priv.pem"
    private_pem = _write_private_only(priv_path)
    private_obj = RSACrypto.load_private_key(private_pem)
    expected_pub = private_obj.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    client = ConfigServiceClient(config_service_url="http://unit-test")

    def _fake_register(username: str, password: str, public_key: str):
        assert public_key == expected_pub.decode("utf-8")
        return {"user_id": 7, "username": username}

    client.api_client.register = _fake_register

    client.register("alice", "secret12", user_private_key_path=priv_path)

    pub_saved = ssl_dir / "alice_public_key.pem"
    assert pub_saved.exists()
    assert pub_saved.read_bytes() == expected_pub
    reset_client_config()


def test_upload_config_single_path_uses_basename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_client_config()
    local = tmp_path / "nested" / "myapp.env"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("K=v\n", encoding="utf-8")

    client = ConfigServiceClient(config_service_url="http://unit-test")
    captured: dict = {}

    def _fake_upload(config_name: str, encrypted_content: str, encrypted_aes_key: str):
        captured["name"] = config_name
        return {"ok": True}

    client.api_client.upload_config = _fake_upload
    monkeypatch.setattr(client, "_encrypt_config_data", lambda _data: ("enc-content", "enc-key"))
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    # 单参数调用：file_path 必填，config_name 自动取 basename
    client.upload_config(local)

    assert captured["name"] == "myapp.env"
    reset_client_config()


def test_upload_config_explicit_config_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """测试双参数调用：显式指定 config_name"""
    reset_client_config()
    local = tmp_path / "nested" / "myapp.env"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text("K=v\n", encoding="utf-8")

    client = ConfigServiceClient(config_service_url="http://unit-test")
    captured: dict = {}

    def _fake_upload(config_name: str, encrypted_content: str, encrypted_aes_key: str):
        captured["name"] = config_name
        return {"ok": True}

    client.api_client.upload_config = _fake_upload
    monkeypatch.setattr(client, "_encrypt_config_data", lambda _data: ("enc-content", "enc-key"))
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    # 双参数调用：file_path 在前，config_name 在后
    client.upload_config(local, config_name="custom_name.env")

    assert captured["name"] == "custom_name.env"
    reset_client_config()


def test_update_config_single_path_uses_basename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_client_config()
    local = tmp_path / "deep" / "svc.toml"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(b"[a]\n")

    client = ConfigServiceClient(config_service_url="http://unit-test")
    captured: dict = {}

    def _fake_update(config_name: str, encrypted_content: str, encrypted_aes_key: str):
        captured["name"] = config_name
        return {"ok": True}

    client.api_client.update_config = _fake_update
    monkeypatch.setattr(client, "_encrypt_config_data", lambda _data: ("enc-content", "enc-key"))
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    client.update_config(local)

    assert captured["name"] == "svc.toml"
    reset_client_config()


def test_get_config_save_dir_writes_expected_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_client_config()
    client = ConfigServiceClient(config_service_url="http://unit-test")
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    raw = {
        "encrypted_content": "e",
        "encrypted_aes_key": "k",
    }

    client.api_client.get_config = lambda config_name: raw
    monkeypatch.setattr(
        client,
        "_decrypt_config_data",
        lambda _c, _k: b"plain-bytes",
    )

    out_dir = tmp_path / "out"
    # save_dir 在前（v0.5.0 调整）
    client.get_config("remote.toml", load_to_env="none", save_dir=out_dir)
    target = out_dir / "remote.toml"
    assert target.exists()
    assert target.read_bytes() == b"plain-bytes"
    reset_client_config()


def test_get_config_load_to_env_none_returns_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """测试 load_to_env='none' 且未指定路径时直接返回数据"""
    reset_client_config()
    client = ConfigServiceClient(config_service_url="http://unit-test")
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    client.api_client.get_config = lambda config_name: {"encrypted_content": "e", "encrypted_aes_key": "k"}
    monkeypatch.setattr(client, "_decrypt_config_data", lambda _c, _k: b"raw-bytes")

    # load_to_env='none' 且未指定路径：应返回解密后的 bytes
    result = client.get_config("cfg.env", load_to_env="none")
    assert result == b"raw-bytes"
    reset_client_config()


def test_get_config_set_temp_env_uses_custom_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_client_config()
    client = ConfigServiceClient(config_service_url="http://unit-test")
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    client.api_client.get_config = lambda config_name: {"encrypted_content": "e", "encrypted_aes_key": "k"}
    monkeypatch.setattr(
        client,
        "_decrypt_config_data",
        lambda _c, _k: b"YAML: x: 1",
    )

    seen: dict = {}

    def _loader(data: bytes, name: str) -> None:
        seen["data"] = data
        seen["name"] = name

    client.get_config(
        "cfg.yaml",
        load_to_env="set_temp_env",
        temp_env_loader=_loader,
    )
    assert seen["data"] == b"YAML: x: 1"
    assert seen["name"] == "cfg.yaml"
    reset_client_config()


def test_get_config_temp_env_loader_exception_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """测试用户自定义 temp_env_loader 抛出的异常会传播出去"""
    reset_client_config()
    client = ConfigServiceClient(config_service_url="http://unit-test")
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    client.api_client.get_config = lambda config_name: {"encrypted_content": "e", "encrypted_aes_key": "k"}
    monkeypatch.setattr(client, "_decrypt_config_data", lambda _c, _k: b"data")

    class CustomError(Exception):
        pass

    def _failing_loader(data: bytes, name: str) -> None:
        raise CustomError("loader failed")

    with pytest.raises(CustomError, match="loader failed"):
        client.get_config(
            "cfg.yaml",
            load_to_env="set_temp_env",
            temp_env_loader=_failing_loader,
        )
    reset_client_config()


def test_get_config_save_path_priority_over_save_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reset_client_config()
    client = ConfigServiceClient(config_service_url="http://unit-test")
    monkeypatch.setattr(client.token_manager, "is_authenticated", lambda: True)

    client.api_client.get_config = lambda config_name: {"encrypted_content": "e", "encrypted_aes_key": "k"}
    monkeypatch.setattr(client, "_decrypt_config_data", lambda _c, _k: b"z")

    explicit = tmp_path / "explicit.env"
    other_dir = tmp_path / "other"
    # save_path 优先级高于 save_dir（v0.5.0 调整：save_dir 在前但 save_path 优先）
    client.get_config(
        "ignored_name.env",
        load_to_env="none",
        save_dir=other_dir,
        save_path=explicit,
    )
    assert explicit.exists()
    assert not (other_dir / "ignored_name.env").exists()
    reset_client_config()
