import os
from pathlib import Path

from tkzs_config_service_client import ConfigServiceClient

SERVICE_URL: str = os.getenv("CASE_CONFIG_SERVICE_URL", "http://localhost:8443")
USERNAME: str = os.getenv("CASE_CONFIG_USER", "ergonomics_demo_user")
PASSWORD: str = os.getenv("CASE_CONFIG_PASSWORD", "demo_password_123")


def custom_temp_env_loader(data: bytes, config_name: str) -> None:
    """示例：用户可按自身格式扩展解析逻辑。"""
    os.environ["CUSTOM_LOADER_CONFIG_NAME"] = config_name
    os.environ["CUSTOM_LOADER_RAW_SIZE"] = str(len(data))


def main() -> None:
    client = ConfigServiceClient(config_service_url=SERVICE_URL)

    private_key_path = Path("./case/keys/ergonomics_demo_private.pem")
    if private_key_path.exists():
        client.register(
            USERNAME,
            PASSWORD,
            user_private_key_path=private_key_path,
        )
    else:
        client.register(USERNAME, PASSWORD)

    client.login(USERNAME, PASSWORD)

    # 单参数上传：配置名自动取文件名 template.env
    client.upload_config("./case/template.env")

    # 单参数更新：配置名同样自动取文件名
    client.update_config("./case/template.env")

    # 仅给 save_dir，保存路径自动推导为 ./case/downloads/template.env
    client.get_config("template.env", load_to_env="none", save_dir="./case/downloads")

    # 自定义 set_temp_env 逻辑（默认仅支持 .env/.toml，此处示例扩展入口）
    client.get_config(
        "template.env",
        load_to_env="set_temp_env",
        temp_env_loader=custom_temp_env_loader,
    )

    print("CUSTOM_LOADER_CONFIG_NAME =", os.getenv("CUSTOM_LOADER_CONFIG_NAME"))
    print("CUSTOM_LOADER_RAW_SIZE =", os.getenv("CUSTOM_LOADER_RAW_SIZE"))

    client.logout()


if __name__ == "__main__":
    main()
