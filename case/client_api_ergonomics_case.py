"""客户端 API 易用性示例（v0.5.0）

v0.5.0 Breaking Changes:
- upload_config(file_path, config_name=None): file_path 必填，config_name 可选
- update_config(file_path, config_name=None): 同上
- get_config(..., save_dir, save_path): save_dir 在前，save_path 在后但优先级更高
"""

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

    # 单参数上传：file_path 必填，config_name 自动取 basename
    client.upload_config("./case/template.env")

    # 双参数上传：显式指定 config_name
    client.upload_config("./case/template.env", config_name="custom_name.env")

    # 单参数更新：同上
    client.update_config("./case/template.env")

    # 仅给 save_dir（纯目录），保存路径自动推导为 ./case/downloads/template.env
    # 注意：config_name 应为纯文件名，不含路径
    client.get_config("template.env", load_to_env="none", save_dir="./case/downloads")

    # load_to_env='none' 且未指定路径：直接返回解密数据
    raw_data = client.get_config("template.env", load_to_env="none")
    print(f"Raw data size: {len(raw_data) if raw_data else 0} bytes")

    # 自定义 set_temp_env 逻辑
    # 若回调抛出异常，会传播给调用方
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
