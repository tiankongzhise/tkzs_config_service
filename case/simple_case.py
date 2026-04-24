import os
from tkzs_config_service_client import ConfigServiceClient

# 测试环境配置，优先从环境变量获取，否则使用默认值
SERVICE_URL: str = os.getenv("CASE_CONFIG_SERVICE_URL", "http://localhost:8443")

# 初始化客户端
client = ConfigServiceClient(config_service_url=SERVICE_URL)

# 注册（首次使用，自动生成RSA密钥）
client.register("testuser", "testpassword123")

# 登录
client.login("testuser", "testpassword123")

# 上传配置
client.upload_config("template1.env", "./case/template1.env")
# 单参数上传（config_name 自动取 template1.env）
client.upload_config("./case/template1.env")

# 查看配置列表
configs = client.list_configs()
for cfg in configs:
    print(f"- {cfg['config_name']} (更新于 {cfg['updated_at']})")

# 下载配置到文件
client.get_config("template.env", load_to_env="none", save_path="./case/received_template.env")
# 仅给目录，自动推导为 ./case/template.env
client.get_config("template.env", load_to_env="none", save_dir="./case")

# 下载并加载到环境变量
client.get_config("template.env", load_to_env="set_temp_env")

print(f"TEMPLATE_ENV: {os.getenv('TEMPLATE_ENV')} should be 66069854")

# 更新配置
client.update_config("template.env", "./case/template.env")
# 单参数更新（config_name 自动取 template.env）
client.update_config("./case/template.env")

# # 删除配置
client.delete_config("template.env")

# 退出登录
client.logout()
