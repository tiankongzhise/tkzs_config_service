import os
from pathlib import Path

from tkzs_config_service_client import ConfigServiceClient, configure_client


# 测试环境配置，优先从环境变量获取，否则使用默认值
SERVICE_URL: str = os.getenv("CASE_CONFIG_SERVICE_URL", "http://localhost:8443")


def main() -> None:
    """
    演示私钥路径的完整优先级链（从高到低）：
    1) login 参数（最高）
    2) 类属性（构造函数参数）
    3) configure_client 全局配置
    4) 默认按用户名推导路径（最低）

    同层规则：private_key_path > private_key_dir
    """
    username = "my_username"
    password = "my_password"

    # === 第3层：设置全局默认 ===
    configure_client(
        private_key_dir="D:/secure_keys/global",
    )
    print("[配置] 全局配置已设置: private_key_dir=D:/secure_keys/global")

    # === 第2层：构造函数参数 ===
    client = ConfigServiceClient(config_service_url=SERVICE_URL)
    print(f"[初始化] client.private_key_path={client.private_key_path}")
    # 此时类属性未显式设置，使用全局配置推导的默认值

    # 场景1：login 参数最高优先级
    # 即使构造函数和全局配置都设置了，login 参数仍会覆盖
    print("\n--- 场景1: login 参数覆盖一切 ---")
    client.login(
        username,
        password,
        private_key_dir="D:/secure_keys/login_dir",  # 第1层参数
    )
    print(f"[login后] private_key_path={client.private_key_path}")

    # 场景2：login 同层同时传 private_key_path 和 private_key_dir，
    # private_key_path 优先
    print("\n--- 场景2: 同层优先级 private_key_path > private_key_dir ---")
    client.login(
        username,
        password,
        private_key_path="D:/secure_keys/login_override/custom_private.pem",
        private_key_dir="D:/secure_keys/login_dir_should_be_ignored",
    )
    print(f"[login后] private_key_path={client.private_key_path}")

    # 场景3：类属性（构造函数参数）优先于全局配置
    # 注意：由于 login 成功后会更新类属性，这里重新创建 client 来演示
    print("\n--- 场景3: 类属性 > 全局配置 ---")
    # 先设置一个不同的全局配置
    configure_client(private_key_path="D:/secure_keys/global_specific.pem")

    # 构造函数使用不同的私钥
    client2 = ConfigServiceClient(
        config_service_url=SERVICE_URL,
        private_key_path="D:/secure_keys/constructor_private.pem",  # 类属性
    )
    print(f"[client2初始化] private_key_path={client2.private_key_path}")
    # 类属性优先于全局配置，使用 constructor_private.pem

    # 场景4：若 login 层不传，回退到类属性
    print("\n--- 场景4: 回退到类属性 ---")
    client2.login(username, password)
    print(f"[login后] private_key_path={client2.private_key_path}")
    # 使用类属性 constructor_private.pem，而非全局配置

    # 场景5：若类属性未设置，回退到全局配置
    print("\n--- 场景5: 回退到全局配置 ---")
    # 创建没有显式设置私钥的 client
    client3 = ConfigServiceClient(config_service_url=SERVICE_URL)
    client3.login(username, password)
    print(f"[login后] private_key_path={client3.private_key_path}")
    # 使用全局配置 global_specific.pem

    # 下面可继续上传/下载配置验证私钥是否生效
    # v0.5.0: file_path 在前，config_name 在后
    sample_env = Path("./case/template.env")
    if sample_env.exists():
        client.upload_config(sample_env, config_name="priority_case_template.env")
        print("\nupload finished")

    print("\n=== 完整优先级链总结 ===")
    print("1. login(private_key_path=...)         # 最高")
    print("2. login(private_key_dir=...)")
    print("3. ConfigServiceClient(private_key_path=...)  # 类属性")
    print("4. configure_client(private_key_path=...)    # 全局配置")
    print("5. configure_client(private_key_dir=...)")
    print("6. 默认路径 ~/.ssl/{username}_private_key.pem  # 最低")


if __name__ == "__main__":
    main()
