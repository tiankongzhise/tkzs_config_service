# 客户端配置优先级说明

本文档说明 `tkzs-config-service-client` 在多个配置来源同时存在时的最终取值顺序。

相关入口：
- 主文档：`README.md`
- 可运行示例：`case/private_key_priority_case.py`

## 配置优先级总览

客户端遵循以下优先级规则（从高到低）：

| 优先级 | 配置来源 | 说明 |
|:------:|----------|------|
| 1 | 函数/方法参数 | 最高优先级，如 `login(private_key_path=...)` |
| 2 | 类属性 | 构造函数参数，如 `ConfigServiceClient(private_key_path=...)` |
| 3 | 全局配置 | `configure_client(...)` 设置的运行时配置 |
| 4 | 默认值 | 包内默认值和环境变量 |

**注意**：同层配置中，具体参数规则（如 `private_key_path > private_key_dir`）也适用。

---

## 1) 服务地址（config_service_url）优先级

最终使用的服务地址优先级如下（高到低）：

1. `ConfigServiceClient(config_service_url=...)` 构造参数
2. `configure_client(service_url=...)` 运行时全局配置
3. 环境变量 `CONFIG_SERVICE_URL`
4. 包内默认值 `http://localhost:8443`

示例：

```python
from tkzs_config_service_client import ConfigServiceClient, configure_client

# 场景1：仅使用全局配置
configure_client(service_url="http://global-service:8443")
client = ConfigServiceClient()  # 使用 http://global-service:8443

# 场景2：构造函数参数覆盖全局配置
client2 = ConfigServiceClient(config_service_url="http://explicit-service:8443")
# client2 使用 http://explicit-service:8443（覆盖全局配置）
```

### 环境变量说明

可通过设置环境变量 `CONFIG_SERVICE_URL` 修改默认值：

```bash
# Linux/macOS
export CONFIG_SERVICE_URL="http://your-server:8443"

# Windows PowerShell
$env:CONFIG_SERVICE_URL="http://your-server:8443"
```

## 2) 登录私钥路径优先级

登录后用于解密配置的私钥路径优先级如下（高到低）：

1. `client.login(...)` 登录参数层（最高）
   - 同层规则：`private_key_path` > `private_key_dir`
2. **类属性层（构造函数参数）**
   - 即 `ConfigServiceClient(private_key_path=...)` 设置的值
3. `configure_client(...)` 运行时全局配置层
   - 同层规则：`private_key_path` > `private_key_dir`
4. 默认逻辑：`~/.ssl/{username}_private_key.pem`（最低）

### 完整的优先级链示例

```python
from tkzs_config_service_client import ConfigServiceClient, configure_client

# 第3层：设置全局默认私钥
configure_client(private_key_path="/path/to/global_private.pem")

# 第2层：构造函数参数（覆盖全局配置）
client = ConfigServiceClient(
    config_service_url="http://localhost:8443",
    private_key_path="/path/to/class_private.pem",  # 优先级高于全局配置
)

# 第1层：login 参数（最高优先级）
client.login(
    "username",
    "password",
    private_key_path="/path/to/login_private.pem",  # 最高优先级
)

# 结果：使用 login_private.pem
```

### 说明

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

## 4) 上传/更新 API 易用性 (v0.5.0 Breaking Changes)

`upload_config` / `update_config` 形参顺序调整（v0.5.0）：

- `file_path` 必填，位于第一位
- `config_name` 可选，位于第二位

两种调用方式：

1. **单参数（推荐）**：仅传本地路径，`config_name` 自动取文件名（`Path(path).name`）
   ```python
   client.upload_config("./path/app.env")
   client.update_config("./path/app.env")
   ```

2. **双参数**：显式指定 `config_name`
   ```python
   client.upload_config("./path/app.env", config_name="custom_name.env")
   client.update_config("./path/app.env", config_name="custom_name.env")
   ```

## 5) `get_config` 参数语义 (v0.5.0 Breaking Changes)

形参顺序（v0.5.0）：
```
config_name, *, load_to_env, save_dir, save_path, temp_env_loader, need_decrypt
```

- `load_to_env` 语义：
  - `"none"`: 不写环境变量；未指定 `save_dir`/`save_path` 时直接返回解密数据
  - `"set_temp_env"`: 仅写入环境变量，不落盘
  - `"write_local_file"`: 仅落盘
  - `"all"`: 先写环境变量，再落盘

- `save_dir`: 保存目录（纯目录路径），与 `config_name` 组合为 `Path(save_dir) / config_name`
  - 注意：`config_name` 应为纯文件名，不含路径
- `save_path`: 完整文件路径，优先级高于 `save_dir`

- 自定义 `temp_env_loader`（异常会传播）：
  ```python
  def my_loader(data: bytes, config_name: str) -> None:
      ...

  client.get_config(
      "app.yaml",
      load_to_env="set_temp_env",
      temp_env_loader=my_loader,
  )
  ```
