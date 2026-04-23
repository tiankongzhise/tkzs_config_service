# tkzs_config_service

一个轻量级配置中心，解决多项目手动维护 `.env` 文件的烦恼。

- **服务端**（Go）：用户认证（JWT）+ 配置管理（CRUD）+ SQLite存储
- **客户端**（Python）：注册/登录 + 配置上传/下载 + AES+RSA双重加密

---

## 新版本 v0.5.0 更新

### 主要特性
- ✅ **用户注册/登录**：支持用户名密码注册，JWT Token认证
- ✅ **配置管理**：上传、更新、删除、下载配置文件
- ✅ **双重加密**：AES-256-GCM本地加密 + RSA-OAEP传输加密
- ✅ **权限隔离**：用户只能管理自己的配置文件

### 安全特性
- 密码使用bcrypt加密存储
- JWT Token认证（24小时有效期）
- 本地AES-256-GCM加密配置文件
- 服务端使用用户RSA公钥分块二次加密AES密钥
- 登录执行"三要素校验"：`username + password + public_key` 必须同时匹配

---

## 快速开始

### 1. 服务端部署

```bash
cd service

# 拉取依赖（首次或依赖变更后）
go mod tidy

# 运行服务
go run .

# 编译服务端
go build -ldflags="-s -w" -o ../tkzs-config-service .
```

> 当前服务端使用 `modernc.org/sqlite`（纯 Go 驱动），无需 CGO 即可构建。

服务将启动在 `http://0.0.0.0:8443`

**环境变量**（可选）：
```bash
export PORT=8080  # 自定义端口
```

### 2. 客户端安装

```bash
# 使用 uv
uv add tkzs-config-service-client

# 使用 pip
pip install tkzs-config-service-client
```

### 3. 客户端使用

```python
from tkzs_config_service_client import ConfigServiceClient, configure_client

# 可选：运行时修改全局默认配置（适用于 uv add / pip install 后）
configure_client(
    service_url="http://localhost:8443",
    private_key_path="D:/secure_keys/my_private.pem",  # 全局默认私钥路径
)

# 初始化客户端
client = ConfigServiceClient(
    config_service_url="http://localhost:8443"
)

# 注册（首次使用）
# 方式1：不提供密钥，客户端自动生成RSA密钥对
client.register("my_username", "my_password")

# 方式2：使用自备RSA公私钥（必须成对提供；会校验格式和匹配关系）
client.register(
    "my_username",
    "my_password",
    user_private_key_path="D:/secure_keys/my_username_private.pem",
    user_public_key_path="D:/secure_keys/my_username_public.pem",
)

# 登录（支持本次登录显式指定私钥路径，优先级最高）
client.login("my_username", "my_password", private_key_path="D:/secure_keys/my_private.pem")

# 上传配置
client.upload_config("mysql.env", "/path/to/mysql.env")

# 查看配置列表
configs = client.list_configs()
for cfg in configs:
    print(f"- {cfg['config_name']} (更新于 {cfg['updated_at']})")

# 下载配置到文件（会自动创建目录）
client.get_config("mysql.env", save_path="./tmp/mysql.env")

# 下载并加载到环境变量
client.get_config("app.toml", load_to_env="set_temp_env")

# 更新配置
client.update_config("mysql.env", "/path/to/new_mysql.env")

# 删除配置
client.delete_config("old_config.env")

# 注销当前登录用户（逻辑删除，不物理删除）
client.deactivate_user()

# 退出登录
client.logout()
```

### case 示例

- 基础流程示例：`case/simple_case.py`
- 注销重注册示例：`case/deactivate_re_register_case.py`
- 私钥优先级示例：`case/private_key_priority_case.py`

运行示例：

```bash
uv run python ./case/private_key_priority_case.py
```

### 登录私钥路径优先级

客户端登录前会先解析私钥，并据此确定本次登录上送服务端的公钥；私钥路径优先级如下：

1. `client.login(...)` 登录参数层（最高优先级）  
   - 同层规则：`private_key_path` > `private_key_dir`
2. `configure_client(...)` 全局配置层  
   - 同层规则：`private_key_path` > `private_key_dir`
3. 默认逻辑：`~/.ssl/{username}_private_key.pem`

`private_key_dir` 仅表示私钥文件父目录，文件名会按规则自动拼接：  
`{normalized_username}{private_key_suffix}`，默认后缀为 `_private_key.pem`。

登录时公钥处理规则：

1. 若本地已存在 `~/.ssl/{username}_public_key.pem`：  
   会校验"本地公钥"与"私钥推导公钥"是否一致；一致才继续登录。
2. 若本地不存在该公钥文件：  
   客户端会从私钥推导公钥并自动写入本地，再将该公钥发送给服务端。
3. 服务端登录校验：  
   只有 `username + password + public_key` 三者都与服务端记录一致，才会签发 token。

---

### 服务地址（URL）优先级

客户端最终使用的 `config_service_url` 优先级如下：

1. `ConfigServiceClient(config_service_url=...)` 构造参数（最高优先级）
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

---

## `encrypted_aes_key` 参数说明

`upload_config` / `update_config` 里的 `encrypted_aes_key` 不是"私钥"也不是"要上传的公钥"，而是：

1. 客户端每次上传时临时生成一个随机 AES 会话密钥；
2. 用 RSA 公钥加密这个 AES 会话密钥；
3. 将这个密文（Base64）作为 `encrypted_aes_key` 上传。

因此这个字段的本质是"被加密后的会话密钥密文"。  
客户端绝不会上传私钥；注册时上传的公钥用于服务端绑定用户身份和后续二次加密流程。

---

## API 端点

### 公开接口（无需认证）

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 用户登录 |
| GET | `/health` | 健康检查 |

### 认证接口（需JWT）

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/api/configs` | 获取配置列表 |
| DELETE | `/api/user/deactivate` | 注销当前用户（逻辑删除） |
| POST | `/api/config/upload` | 上传配置 |
| GET | `/api/config?name={name}` | 下载配置 |
| PUT | `/api/config?name={name}` | 更新配置 |
| DELETE | `/api/config?name={name}` | 删除配置 |

> 说明：配置读写接口同时兼容路径参数形式：`/api/config/{name}`（GET/PUT/DELETE）。

### 认证接口请求字段（关键）

- `POST /api/register`
  - `username`（必填）
  - `password`（必填，至少 6 位）
  - `public_key`（必填，RSA 公钥 PEM）
- `POST /api/login`
  - `username`（必填）
  - `password`（必填）
  - `public_key`（必填，必须与该账号注册公钥一致）

---

## 数据库

服务端使用SQLite存储数据（`tkzs_service.db`）：

```sql
-- 用户表
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    original_username TEXT,      -- 初始用户名（用于逻辑删除追溯）
    password_hash TEXT NOT NULL,  -- bcrypt加密
    public_key TEXT NOT NULL,     -- RSA公钥PEM
    is_deleted INTEGER NOT NULL DEFAULT 0,  -- 0:有效 1:已注销
    deleted_at TIMESTAMP NULL,    -- 注销时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 配置表
CREATE TABLE configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    config_name TEXT NOT NULL,
    aes_key_encrypted_with_public_key BLOB NOT NULL,  -- 二次加密的AES密钥
    encrypted_content BLOB NOT NULL,                    -- 加密的配置文件
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, config_name)
);
```

驱动说明：
- 使用 `modernc.org/sqlite`（纯 Go）
- 适合跨平台构建（如 Windows 构建 Linux 目标）

---

## 加密流程

### 上传配置

```
1. 客户端生成随机 AES-256 密钥
2. 使用 AES-GCM 加密文件内容
3. 使用客户端 RSA 公钥加密 AES 密钥
4. 上传到服务端（encrypted_content + encrypted_aes_key）
5. 服务端使用用户 RSA 公钥分块二次加密 AES 密钥
6. 服务端存储到 SQLite
```

### 下载配置

```
1. 服务端返回 (encrypted_content, double_encrypted_aes_key)
2. 客户端使用 RSA 私钥按块解密得到 first_encrypted_aes_key
3. 客户端再次使用 RSA 私钥解密得到 AES 密钥
4. 使用 AES 密钥解密文件内容并返回原始数据
```

## 客户端密钥文件说明

- 注册成功后会按用户名保存密钥文件，避免不同用户互相覆盖：
  - `~/.ssl/{username}_private_key.pem`
  - `~/.ssl/{username}_public_key.pem`
- 若注册时未提供RSA文件，客户端会自动生成并提示私钥保存位置，请务必离线备份。
- 若注册时提供自备RSA文件，必须同时提供公钥和私钥，客户端会校验PEM格式并校验公私钥是否匹配。
- 登录时若检测到该用户密钥文件，会自动切换到该用户密钥进行解密与登录校验。
- 若仅有账号密码但私钥缺失，登录会被拒绝（无法构造/验证登录公钥）。
- 若私钥与该用户公钥不匹配，登录会被拒绝。
- 更换设备时，必须同步配置原账号对应的私钥文件，否则无法解密历史配置。

## 用户注销（逻辑删除）

- 接口：`DELETE /api/user/deactivate`（需 JWT）
- 客户端调用：`client.deactivate_user()`
- 行为说明：
  - 用户不会被物理删除，而是标记为已注销
  - 已注销用户的旧 token 会失效（后续请求会被拒绝）
  - 同名可重新注册，且会分配新的 `user_id`

---

## 文件夹结构

```
tkzs_config_service/
├── service/                 # Go 服务端
│   ├── main.go             # 主入口
│   ├── database.go         # SQLite 数据库操作
│   ├── auth.go             # JWT 认证
│   ├── handlers.go         # HTTP 处理器
│   ├── crypto.go           # 加密工具
│   └── configs/            # 配置文件目录（按用户ID）
│       ├── 1/
│       │   ├── mysql.env
│       │   └── app.toml
│       └── 2/
│           └── ...
├── src/tkzs_config_service_client/  # Python 客户端
│   ├── __init__.py
│   ├── client.py           # 主客户端类
│   ├── api.py              # API 通信
│   ├── auth.py             # Token 管理
│   ├── crypto.py           # 加密工具
│   └── config.py           # 配置管理（运行时配置、默认值）
├── case/                   # 示例用例
│   ├── simple_case.py              # 基础流程示例
│   ├── private_key_priority_case.py # 私钥优先级示例
│   ├── deactivate_re_register_case.py # 注销重注册示例
│   └── template.env               # 示例配置文件
├── docs/
│   └── configuration-priority.md   # 配置优先级详细说明
├── pyproject.toml
└── README.md
```

---

## 环境变量

### 服务端

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `PORT` | 服务端口 | 8443 |

### 客户端

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CONFIG_SERVICE_URL` | 配置服务地址 | http://localhost:8443 |

### 测试环境变量（case 和 tests 目录）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CASE_CONFIG_SERVICE_URL` | case 示例服务地址 | http://localhost:8443 |
| `TEST_CONFIG_SERVICE_URL` | 测试服务地址 | http://unit-test |
| `TEST_RUNTIME_CONFIG_URL` | 测试运行时配置地址 | http://runtime-config-service |

---

## 版本历史

### v0.4.0 (2026)
- 登录增强为账号/密码/公钥三要素校验
- 客户端登录时支持"公钥缺失则由私钥推导并落盘"
- 完善 `private_key_path/private_key_dir` 的同层与跨层优先级
- 补充运行时配置 `configure_client(...)` 场景
- case 和测试支持环境变量配置服务地址（`CASE_CONFIG_SERVICE_URL` 等）

### v0.3.0 (2024)
- 新增用户注册/登录功能
- 新增配置上传/更新/删除功能
- 改用JWT Token认证
- 实现AES+RSA双重加密
- SQLite数据库存储

### v0.2.x
- HMAC-SHA256 + 时间戳 + nonce 防重放
- IP动态限流

### v0.1.x
- 基础RSA加密认证

---

## License

[LGPL-2.1](LICENSE)

---

更多配置优先级与加密参数说明见：`docs/configuration-priority.md`
