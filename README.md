# tkzs_config_service

一个轻量级配置中心，解决多项目手动维护 `.env` 文件的烦恼。  
- **服务端**（Go）：通过 RSA 私钥鉴权，返回指定配置文件（支持任意二进制文件）。  
- **客户端**（Python）：从环境变量读取公钥和密码，安全获取配置并注入环境变量或写入本地文件。  

---

## 快速开始

### 1. 服务端部署

1. 准备 RSA 私钥文件 `server_private_key.pem`（PKCS#1 或 PKCS#8 格式）。  
2. 在 `.env` 文件中设置认证密码：  
   ```ini
   PASSWORD=your_strong_password
   ```
3. 将需要分发的配置文件（如 `mysql.env`、`app.toml`）放在服务端工作目录下。  
4. 启动服务（默认监听 `:8443`）：  
   ```bash
   go run main.go
   ```

> 生产环境建议使用 systemd 或容器运行，并配置 HTTPS 代理（如 Nginx）。

### 2. 客户端安装

```bash
# 使用 uv
uv add tkzs-config-service-client

# 使用 pip
pip install tkzs-config-service-client
```

### 3. 客户端环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `CONFIG_SERVICE_URL` | 配置服务地址 | `http://your-server:8443/get-config` |
| `CONFIG_SERVICE_PASSWORD` | 认证密码（需与服务端 `.env` 中一致） | `your_strong_password` |

公钥文件默认路径：`~/.ssl/client_public_key.pem`（与服务端私钥对应的公钥）。

### 4. 客户端使用示例

```python
from tkzs_config_service import ConfigServiceClient

# 获取配置并加载到环境变量（默认行为）
client = ConfigServiceClient(config_name="mysql.env")
client.load_config_settings("set_temp_env")

# 同时写入本地文件（前缀 received_）
client.load_config_settings("all")

# 自定义回调处理配置内容
def my_set_env():
    print(client.rsp.text)  # 原始配置内容

client = ConfigServiceClient(set_temp_env=my_set_env)
```

---

## 版本兼容性

> **重要**：客户端与服务端版本必须匹配。  
> - `v0.1.x` 协议使用 `SHA256(salt+password)` 认证，**与 v0.2.x 不兼容**。  
> - `v0.2.x` 协议升级为 `HMAC-SHA256` + 时间戳 + nonce 防重放，**与 v0.1.x 不兼容**。  

请确保客户端与服务端主版本号一致（例如都使用 `v0.2.x`）。

---

## 安全特性

### 传输安全
- 请求体使用 **RSA-2048 PKCS#1 v1.5** 加密（公钥加密，私钥解密）。  
- 建议服务端部署在 HTTPS 代理后方，避免中间人攻击。

### 防重放攻击
- 客户端生成随机 `salt`（16字节）和 `nonce`（16字节）。  
- 请求中包含 **Unix 时间戳**（允许 ±300 秒偏差）。  
- 服务端记录已使用的 `nonce`，有效期 10 分钟，拒绝重复请求。

### 认证完整性
- 使用 `HMAC-SHA256(password, salt:filename:timestamp:nonce)` 保证消息未被篡改。

### IP 动态限流（服务端）
| 触发条件 | 封禁时长 |
|----------|----------|
| 60 秒内认证失败 ≥5 次 | 30 分钟 |
| 86400 秒内认证失败 ≥10 次 | 24 小时 |

- 失败计数包括：解密失败、格式错误、时间戳无效、nonce重放、HMAC不匹配、文件不存在等。  
- 认证成功后自动清除该 IP 的失败计数。  
- 封禁数据持久化到 `ip_bans.json`，每分钟自动落盘。

### 错误信息保护
- 所有失败情况（密码错误、文件不存在、重放等）统一返回 HTTP `401 Unauthorized`。  
- 详细错误仅记录在服务端日志，不暴露给客户端。

---

## 配置示例

### 服务端目录结构
```
/path/to/server/
├── server_private_key.pem   # RSA 私钥
├── .env                     # PASSWORD=xxx
├── config.toml              # 可被请求的配置文件
├── mysql.env                # 可被请求的配置文件
└── ip_bans.json             # 自动生成，存储封禁数据
```

### 客户端公钥放置
```bash
mkdir -p ~/.ssl
cp client_public_key.pem ~/.ssl/
```

---

## 常见问题

**Q：客户端报 `SSL certificate validation failed`？**  
A：服务端未启用 HTTPS，请确认 `CONFIG_SERVICE_URL` 使用 `http://`，或设置 `verify=False`（不推荐生产环境）。  

**Q：服务端日志显示 `HMAC mismatch`？**  
A：检查客户端和服务端使用的 `PASSWORD` 是否一致。  

**Q：客户端一直返回 401 但密码正确？**  
A：可能是时间戳窗口问题，同步客户端与服务端系统时间；或检查 nonce 是否被重放（如短时间内重复启动客户端）。  

**Q：如何调整限流阈值？**  
A：修改服务端源码中的 `IPBanConfig` 默认值（`DefaultIPBanConfig` 函数），重新编译部署。

---

## 开发与贡献

- 服务端代码位于 `service/` 目录。  
- 客户端代码位于 `src/tkzs_config_service/` 目录。  
- 欢迎提交 Issue 和 PR。

---

## License

[LGPL-2.1](LICENSE)