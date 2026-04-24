# tkzs_config_service 开发任务清单

## 项目概述
为配置中心服务添加用户注册、登录和配置管理功能，支持JWT鉴权和RSA+AES双重加密。

---

## 功能需求

### 1. 用户注册
- [x] **服务端**: POST `/api/register`
  - 输入: username, password, user_public_key (RSA PEM格式)
  - 密码使用bcrypt加密存储
  - 存储用户RSA公钥
  - 创建用户专属配置目录
  - 返回: user_id, message

- [x] **客户端**: `register()` 方法
  - 生成RSA-2048密钥对
  - 调用服务端注册API
  - 保存私钥到本地 `~/.ssl/user_private_key.pem`
  - 保存用户名供后续使用

### 2. 用户登录
- [x] **服务端**: POST `/api/login`
  - 输入: username, password
  - 验证密码(bcrypt)
  - 生成JWT token (包含user_id, username, exp)
  - 返回: access_token, expires_in

- [x] **客户端**: `login()` 方法
  - 调用登录API
  - 存储JWT token到 `~/.config/tkzs_service/token`
  - 提供获取token方法供其他API调用

### 3. 配置上传
- [x] **客户端**: `upload_config()` 方法
  - 用户选择本地配置文件
  - 生成随机AES-256密钥
  - 使用AES加密文件内容
  - 使用用户RSA公钥加密AES密钥
  - 发送: config_name, encrypted_content, encrypted_aes_key

- [x] **服务端**: POST `/api/config/upload`
  - JWT鉴权
  - 使用用户RSA公钥二次加密
  - 保存到用户目录: `configs/{user_id}/{config_name}`
  - 返回: config_id, message

### 4. 配置更新
- [x] **客户端**: `update_config()` 方法
  - 与上传类似，先本地AES加密
  - 发送更新请求

- [x] **服务端**: PUT `/api/config/{config_id}`
  - JWT鉴权
  - 验证配置归属(只能更新自己的)
  - 使用用户公钥二次加密
  - 返回: message

### 5. 配置删除
- [x] **客户端**: `delete_config()` 方法
  - 发送删除请求(含config_name)

- [x] **服务端**: DELETE `/api/config/{config_id}`
  - JWT鉴权
  - 验证配置归属
  - 删除文件
  - 返回: message

### 6. 配置获取/下载
- [x] **服务端**: GET `/api/config/{name}`
  - JWT鉴权
  - 验证配置归属
  - 返回: encrypted_content, encrypted_aes_key (已用用户公钥二次加密)

- [x] **客户端**: `get_config()` 方法
  - 接收加密数据
  - 使用RSA私钥解密AES密钥
  - 使用AES密钥解密内容
  - 保存/加载配置

### 7. 配置列表
- [x] **服务端**: GET `/api/configs`
  - JWT鉴权
  - 返回用户所有配置列表

- [x] **客户端**: `list_configs()` 方法
  - 获取配置列表
  - 显示配置名称和更新时间

---

## 数据库设计 (SQLite)

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    public_key TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    config_name TEXT NOT NULL,
    aes_key_encrypted_with_public_key BLOB NOT NULL,
    encrypted_content BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, config_name)
);
```

---

## 安全特性

### 密码安全
- 使用bcrypt加密密码，cost=12
- 不存储明文密码

### 传输安全
- HTTPS (生产环境建议)
- JWT token认证 (24小时有效期)

### 文件加密
1. 本地AES-256-GCM加密
2. RSA-OAEP加密AES密钥
3. 服务端使用用户公钥二次加密

---

## 服务端API端点

| 方法 | 端点 | 描述 | 鉴权 |
|------|------|------|------|
| POST | /api/register | 用户注册 | 无 |
| POST | /api/login | 用户登录 | 无 |
| GET | /api/configs | 获取配置列表 | JWT |
| POST | /api/config/upload | 上传配置 | JWT |
| GET | /api/config/{name} | 下载配置 | JWT |
| PUT | /api/config/{name} | 更新配置 | JWT |
| DELETE | /api/config/{name} | 删除配置 | JWT |

---

## 客户端使用示例

```python
from tkzs_config_service import ConfigServiceClient

# 初始化客户端
client = ConfigServiceClient()

# 注册(首次使用)
client.register("my_username", "my_password")

# 登录
client.login("my_username", "my_password")

# 上传配置 (v0.5.0: file_path在前，config_name在后)
client.upload_config("/path/to/mysql.env")
client.upload_config("/path/to/mysql.env", config_name="mysql.env")

# 获取配置列表
configs = client.list_configs()
print(configs)

# 下载配置
client.get_config("mysql.env", save_path="/tmp/mysql.env")

# 更新配置 (v0.5.0: file_path在前，config_name在后)
client.update_config("/path/to/new_mysql.env")
client.update_config("/path/to/new_mysql.env", config_name="mysql.env")

# 删除配置
client.delete_config("mysql.env")
```

---

## 文件夹结构

```
service/
├── main.go           # 主服务入口
├── database.go       # SQLite数据库操作
├── handlers.go      # HTTP处理器
├── auth.go          # JWT认证中间件
├── crypto.go        # 加密工具
└── configs/         # 用户配置文件目录
    ├── {user_id_1}/
    │   ├── config1.env
    │   └── config2.toml
    └── {user_id_2}/
        └── ...

src/tkzs_config_service_client/
├── client.py         # 主客户端类
├── auth.py           # JWT和密钥管理
├── crypto.py         # AES加密工具
└── api.py            # API调用封装
```

---

## 实现状态

- [x] 创建TODO清单
- [x] 服务端: SQLite数据库初始化
- [x] 服务端: 用户注册API
- [x] 服务端: 用户登录API + JWT
- [x] 服务端: 配置CRUD API
- [x] 客户端: 依赖更新
- [x] 客户端: 注册功能
- [x] 客户端: 登录功能
- [x] 客户端: 配置上传/更新/删除
- [x] 客户端: 配置下载解密
- [x] 更新文档
