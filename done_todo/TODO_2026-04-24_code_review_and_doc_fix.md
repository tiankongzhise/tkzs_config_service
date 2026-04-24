# TODO (2026-04-24): 代码审查与文档一致性修正

## 背景

对项目进行了全面审查，对比 `d0.5.0` 之后的修改，检查 README、docs 和 case/ 测试用例是否与实际功能一致。

## 发现的问题

### 1. README.md 中的旧 API 示例

**问题位置：** README.md 快速开始部分

**修正内容：**
- `upload_config("mysql.env", "/path/to/mysql.env")` → `upload_config("/path/to/mysql.env", config_name="mysql.env")`
- `update_config("mysql.env", "/path/to/new_mysql.env")` → `update_config("/path/to/new_mysql.env", config_name="mysql.env")`

### 2. case/deactivate_re_register_case.py 中缺少上传调用

**问题位置：** case/deactivate_re_register_case.py

**修正内容：**
- 添加了缺失的 `upload_config` 调用
- 更新注释以反映 v0.5.0 的 API 变化

### 3. done_todo/ 历史文档中的旧 API 示例

**问题位置：** 
- `done_todo/TODO.md`
- `done_todo/TODO_2026-04-24_client_api_ergonomics.md`

**修正内容：**
- 更新历史文档中的 API 示例以反映 v0.5.0 的参数顺序变化
- 修正 API 签名描述

## 验证结果

### API 一致性检查

| 文件 | `upload_config` | `update_config` | `get_config` |
|------|-----------------|-----------------|--------------|
| README.md | ✅ 已修正 | ✅ 已修正 | ✅ 正确 |
| case/simple_case.py | ✅ 正确 | ✅ 正确 | ✅ 正确 |
| case/private_key_priority_case.py | ✅ 正确 | N/A | ✅ 正确 |
| case/client_api_ergonomics_case.py | ✅ 正确 | ✅ 正确 | ✅ 正确 |
| case/deactivate_re_register_case.py | ✅ 已修正 | N/A | ✅ 正确 |
| docs/configuration-priority.md | ✅ 正确 | ✅ 正确 | ✅ 正确 |
| tests/*.py | ✅ 正确 | ✅ 正确 | ✅ 正确 |
| done_todo/*.md | ✅ 已修正 | ✅ 已修正 | - |

### 功能验证

- ✅ 客户端代码可正常导入
- ✅ API 参数签名与文档描述一致
- ✅ `private_key_path` / `private_key_dir` 优先级链正确
- ✅ `configure_client` 全局配置与类属性优先级正确

## 已修正文件列表

1. `README.md` - 2处修正
2. `case/deactivate_re_register_case.py` - 1处修正
3. `done_todo/TODO.md` - 2处修正
4. `done_todo/TODO_2026-04-24_client_api_ergonomics.md` - 1处修正

## v0.5.0 API 变更摘要

### Breaking Changes

| 方法 | 变更 |
|------|------|
| `upload_config()` | `file_path` 移至第一位，`config_name` 移至第二位（可选） |
| `update_config()` | `file_path` 移至第一位，`config_name` 移至第二位（可选） |
| `get_config()` | `load_to_env` 语义调整，新增 `save_dir` 参数 |
| `temp_env_loader` | 用户回调抛出的异常现在会传播出去 |

### 推荐的调用方式

```python
# 上传配置（单参数，推荐）
client.upload_config("/path/to/mysql.env")

# 上传配置（双参数，显式指定名称）
client.upload_config("/path/to/mysql.env", config_name="custom.env")

# 更新配置（单参数，推荐）
client.update_config("/path/to/new_mysql.env")

# 更新配置（双参数，显式指定名称）
client.update_config("/path/to/new_mysql.env", config_name="custom.env")

# 下载配置到目录
client.get_config("mysql.env", load_to_env="none", save_dir="./tmp")

# 下载配置到完整路径
client.get_config("mysql.env", load_to_env="none", save_path="./tmp/mysql.env")

# 下载并加载到环境变量
client.get_config("app.toml", load_to_env="set_temp_env")
```

## 进度

- [x] 识别 README.md 中的旧 API 示例
- [x] 识别 case/ 目录中的过时注释
- [x] 识别 done_todo/ 目录中的旧 API 示例
- [x] 修正所有发现的文档不一致问题
- [x] 验证客户端代码可正常导入
- [x] 创建本记录文件
