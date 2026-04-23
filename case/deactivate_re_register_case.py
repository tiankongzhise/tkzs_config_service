import os
from pathlib import Path
from tkzs_config_service_client import ConfigServiceClient, ConfigServiceRuntimeError

# 测试环境配置，优先从环境变量获取，否则使用默认值
SERVICE_URL: str = os.getenv("CASE_CONFIG_SERVICE_URL", "http://localhost:8443")


def main() -> None:
    client = ConfigServiceClient(config_service_url=SERVICE_URL)
    username = "case_reactivate_user"
    password = "CasePassword123"
    config_name = "template.env"
    upload_file = Path("./case/template.env")
    download_file = Path("./case/tmp/downloaded_template.env")

    print("== 1) 首次注册并登录 ==")
    try:
        reg1 = client.register(username, password)
        print(f"首次注册成功, user_id={reg1.get('user_id')}")
    except ConfigServiceRuntimeError as exc:
        if "username already exists" in str(exc):
            print("用户已存在，跳过首次注册，直接登录")
        else:
            raise
    login1 = client.login(username, password)
    uid1 = login1.get("user_id")
    print(f"首次登录成功, user_id={uid1}")

    print("== 2) 上传并下载配置 ==")
    # client.upload_config(config_name, upload_file)
    client.get_config(config_name, save_path=download_file)
    print(f"配置下载成功: {download_file}")

    print("== 3) 注销当前用户（逻辑删除） ==")
    client.deactivate_user()
    print("用户已逻辑删除")

    print("== 4) 同名重新注册并登录（应获得新 user_id） ==")
    reg2 = client.register(username, password)
    uid2_reg = reg2.get("user_id")
    login2 = client.login(username, password)
    uid2_login = login2.get("user_id")
    print(f"重注册 user_id={uid2_reg}, 重登录 user_id={uid2_login}")

    if uid1 == uid2_login:
        raise RuntimeError("期望重注册后 user_id 变化，但实际未变化")

    print("✅ case 通过：同名可重注册，且 user_id 发生变化")


if __name__ == "__main__":
    main()
