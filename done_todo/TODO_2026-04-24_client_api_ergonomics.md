# TODO (2026-04-24): 客户端 API 易用性增强

## 背景

在保持安全语义不变的前提下，简化注册、上传/更新配置、以及 `get_config` 的调用方式，并支持自定义「下载后写入环境变量」的解析逻辑。

## 需求清单

### 1. 注册仅提供私钥

- [x] `register(..., user_private_key_path=..., user_public_key_path=None)` 合法：由私钥推导公钥并完成注册。
- [x] 若仅提供公钥、不提供私钥：明确报错（注册必须能落盘私钥供后续解密）。
- [x] 若同时提供公私钥：保持现有 PEM 规范化与「公私钥是否匹配」校验。
- [x] 更新 `register()` 文档字符串与 README「密钥文件说明」。

### 2. `upload_config` / `update_config` 仅提供本地路径

- [x] 支持单参数调用：`upload_config(config_path)` / `update_config(config_path)`，其中 `config_name` 自动取 `Path(config_path).name`（与服务端存储名一致）。
- [x] 保留双参数形式：`upload_config(file_path, config_name=...)` / `update_config(file_path, config_name=...)`。
- [x] 文档与示例说明两种调用方式。

### 3. `get_config` 形参顺序与语义

- [x] `load_to_env` 置于 `save_path` 之前（对外签名中）；`save_path` 及后续参数建议使用仅关键字（`*`）避免顺序误用。
- [x] `load_to_env='set_temp_env'` 时：**不**根据 `save_path` 写文件；`save_path` 仅作用于 `none` / `write_local_file` / `all` 中的文件分支（`set_temp_env` 纯环境、`write_local_file` 纯文件、`all` 两者都做）。
- [x] 修正 `_load_settings` 返回值语义：各模式下返回值与是否写文件一致、可测。

### 4. `save_dir` + `config_name` 推定保存路径

- [x] 支持 `get_config(..., save_dir=...)`：在未显式传入 `save_path` 时，保存路径为 `Path(save_dir) / Path(config_name)`（相对路径段随 `config_name` 保留；写入前 `mkdir(parents=True)`）。
- [x] `save_path` 与 `save_dir` 同时传入时：`save_path` 优先。

### 5. 自定义 `set_temp_env` 回调

- [x] 增加可选参数（例如 `temp_env_loader`）：在 `load_to_env` 为 `set_temp_env` 或 `all` 时，若提供则调用用户函数，否则走内置 `.env` / `.toml` 逻辑。
- [x] 约定回调签名为 `(data: bytes, config_name: str) -> None`（用户可根据 `config_name` 后缀自定义解析）。
- [x] 导出类型别名（如 `TempEnvLoader`）供类型标注（可选）。

## 验收标准

- [x] 上述行为均有单元测试覆盖。
- [x] `case/` 下新增或更新演示脚本，展示：仅私钥注册、单路径上传/更新、`save_dir` 下载、自定义 `temp_env_loader`。
- [x] `README.md` 与 `docs/configuration-priority.md`（如相关）已同步更新。

## 进度

（实现过程中将 `[ ]` 改为 `[x]`）
