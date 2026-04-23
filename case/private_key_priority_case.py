import os
from pathlib import Path

from tkzs_config_service_client import ConfigServiceClient, configure_client


# 测试环境配置，优先从环境变量获取，否则使用默认值
SERVICE_URL: str = os.getenv("CASE_CONFIG_SERVICE_URL", "http://localhost:8443")


def main() -> None:
    """
    演示 private_key_path / private_key_dir 的同层与跨层优先级：
    1) login 层优先于 configure_client 层
    2) 同层中 private_key_path 优先于 private_key_dir
    """
    username = "my_username"
    password = "my_password"

    # 先配置全局默认：仅指定私钥目录（会自动按用户名拼接文件名）
    configure_client(
        private_key_dir="D:/secure_keys/global",
    )

    client = ConfigServiceClient(config_service_url=SERVICE_URL)

    # 场景1：仅传 login(private_key_dir)，会使用：
    # D:/secure_keys/login_dir/{normalized_username}_private_key.pem
    client.login(
        username,
        password,
        private_key_dir="D:/secure_keys/login_dir",
    )
    print(f"[case1] private_key_path={client.private_key_path}")

    # 场景2：login 同层同时传 private_key_path 和 private_key_dir，
    # private_key_path 优先
    client.login(
        username,
        password,
        private_key_path="D:/secure_keys/login_override/custom_private.pem",
        private_key_dir="D:/secure_keys/login_dir_should_be_ignored",
    )
    print(f"[case2] private_key_path={client.private_key_path}")

    # 场景3：若 login 层不传，回退到 configure_client 层
    client.login(username, password)
    print(f"[case3] private_key_path={client.private_key_path}")

    # 下面可继续上传/下载配置验证私钥是否生效
    sample_env = Path("./case/template.env")
    if sample_env.exists():
        client.upload_config("priority_case_template.env", sample_env)
        print("upload finished")


if __name__ == "__main__":
    main()
