from tkzs_config_service_client import ConfigServiceClient, ConfigServiceRuntimeError
from pathlib import Path

def test_del_re_register_behaver():
    client = ConfigServiceClient()
    username = "test_del_re_register_behaver"
    password = "TestPassword123"
    # config_name = "template.env"
    # upload_file = Path("./tests/test_data/template.env")
    # download_file = Path("./tests/test_data/downloaded_template.env")

    # print("== 1) 首次注册并登录 ==")
    # try:
    #     reg1 = client.register(username, password)
    #     print(f"首次注册成功, user_id={reg1.get('user_id')}")
    # except ConfigServiceRuntimeError as exc:
    #     if "username already exists" in str(exc):
    #         print("用户已存在，跳过首次注册，直接登录")
    # login1 = client.login(username, password)
    # uid1 = login1.get("user_id")
    # print(f"首次登录成功, user_id={uid1}")

    # print("== 2) 上传并下载配置 ==")
    # client.upload_config(config_name, upload_file)
    # client.get_config(config_name, save_path=download_file)
    # print(f"配置下载成功: {download_file}")

    # print("== 3) 注销当前用户（逻辑删除） ==")
    # client.deactivate_user()
    # print("用户已逻辑删除")

    # print("== 4) 同名重新注册并登录（应获得新 user_id） ==")
    # reg2 = client.register(username, password)
    # uid2_reg = reg2.get("user_id")
    # login2 = client.login(username, password)
    # uid2_login = login2.get("user_id")
    # print(f"重注册 user_id={uid2_reg}, 重登录 user_id={uid2_login}")
    # if uid1 == uid2_login:
    #     raise RuntimeError("期望重注册后 user_id 变化，但实际未变化")
    # print("✅ case 通过：同名可重注册，且 user_id 发生变化")

    # print("✅ 尝试删除上一次注册的配置 ==")
    # try:
    #     client.delete_config(config_name)
    #     raise RuntimeError("删除配置成功，但应抛出异常")
    # except ConfigServiceRuntimeError as exc:
    #     print("✅ case 通过：删除配置失败，抛出异常")
    # print("✅ case 通过：删除配置失败，抛出异常")

    # print("尝试登出后注销账户 ==")
    # client.logout()
    # try:
    #     client.deactivate_user(username)
    #     raise RuntimeError("注销账户成功，但应抛出异常")
    # except ConfigServiceRuntimeError as exc:
    #     print("✅ case 通过：登出后注销账户失败，抛出异常")

    # print("注销测试账号，结束测试")
    # client.login(username, password)
    # client.deactivate_user()
    print("尝试登录已注销的测试账号，应抛出异常")
    try:
        client.login(username, password)
        raise RuntimeError("登录成功，但应抛出异常")
    except ConfigServiceRuntimeError as exc:
        print(f"✅ case 通过：注销后登录失败，抛出异常，exc={exc}")
    print("✅ 所有测试通过")

if __name__ == "__main__":
    test_del_re_register_behaver()