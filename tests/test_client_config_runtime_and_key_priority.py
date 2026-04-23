from pathlib import Path

from tkzs_config_service_client import ConfigServiceClient, configure_client, reset_client_config
from tkzs_config_service_client.crypto import RSACrypto


def _prepare_private_key(path: Path) -> None:
    private_pem, _ = RSACrypto.generate_keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(private_pem)


def test_runtime_configure_client_affects_new_instance(tmp_path: Path):
    reset_client_config()
    custom_ssl_dir = tmp_path / "custom_ssl"
    custom_token_dir = tmp_path / "custom_token"
    custom_private_key = custom_ssl_dir / "runtime_private.pem"

    configure_client(
        service_url="http://runtime-config-service",
        ssl_dir=custom_ssl_dir,
        token_dir=custom_token_dir,
        private_key_path=custom_private_key,
        request_timeout_seconds=17,
    )

    client = ConfigServiceClient()
    assert client.config_service_url == "http://runtime-config-service"
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

    _prepare_private_key(login_arg_private)
    _prepare_private_key(config_private)
    private_pem, public_pem = RSACrypto.generate_keypair()
    default_private.parent.mkdir(parents=True, exist_ok=True)
    default_private.write_bytes(private_pem)
    default_public.write_bytes(public_pem)

    configure_client(ssl_dir=ssl_dir, private_key_path=config_private)
    client = ConfigServiceClient(config_service_url="http://unit-test")
    client.api_client.login = lambda *_args, **_kwargs: {
        "access_token": "fake-token",
        "expires_in": 3600,
        "user_id": 1,
        "username": username,
    }

    client.login(username, "password123", private_key_path=login_arg_private)
    assert client.private_key_path == login_arg_private

    client.login(username, "password123")
    assert client.private_key_path == config_private

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
    private_key_path = tmp_path / "only_private.pem"
    _prepare_private_key(private_key_path)

    client = ConfigServiceClient(
        config_service_url="http://unit-test",
        private_key_path=private_key_path,
        public_key_path=tmp_path / "missing_public.pem",
    )

    encrypted_content, encrypted_aes_key = client._encrypt_config_data(b"hello")
    assert encrypted_content
    assert encrypted_aes_key

    reset_client_config()
