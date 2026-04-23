# 客户端配置优先级说明

本文档说明 `tkzs-config-service-client` 在多个配置来源同时存在时的最终取值顺序。

相关入口：
- 主文档：`README.md`
- 可运行示例：`case/private_key_priority_case.py`

## 1) 服务地址（config_service_url）优先级

最终使用的服务地址优先级如下（高到低）：

1. `ConfigServiceClient(config_service_url=...)` 构造参数
2. `configure_client(service_url=...)` 运行时全局配置
3. 环境变量 `CONFIG_SERVICE_URL`
4. 包内默认值

示例：

```python
from tkzs_config_service_client import ConfigServiceClient, configure_client

configure_client(service_url="http://global-service:8443")
client = ConfigServiceClient()  # 使用 http://global-service:8443

client2 = ConfigServiceClient(config_service_url="http://explicit-service:8443")
# client2 使用 http://explicit-service:8443（覆盖全局配置）
```

## 2) 登录私钥路径优先级

登录后用于解密配置的私钥路径优先级如下（高到低）：

1. `client.login(...)` 登录参数层
   - 同层规则：`private_key_path` > `private_key_dir`
2. `configure_client(...)` 运行时全局配置层
   - 同层规则：`private_key_path` > `private_key_dir`
3. 默认逻辑：`~/.ssl/{username}_private_key.pem`

说明：

- 私钥仅在客户端本地使用，不会上传到服务端。
- 若公钥文件缺失，客户端可由私钥动态推导公钥用于上传/更新流程。
- `private_key_dir` 只指定父目录，文件名按规则自动拼接：
  `{normalized_username}{private_key_suffix}`（默认后缀 `_private_key.pem`）。

可直接运行示例：

```bash
uv run python ./case/private_key_priority_case.py
```

## 3) `encrypted_aes_key` 的作用

`upload_config` / `update_config` 中的 `encrypted_aes_key` 是：

- “RSA 加密后的 AES 会话密钥密文（Base64）”

它不是私钥，也不是要上传的公钥。其目的是在混合加密中安全传递一次性 AES 密钥：

1. 客户端生成随机 AES 会话密钥
2. 使用 AES 加密配置内容
3. 使用 RSA 公钥加密 AES 会话密钥，得到 `encrypted_aes_key`
4. 下载时客户端用 RSA 私钥解开 `encrypted_aes_key`，再解密配置内容
