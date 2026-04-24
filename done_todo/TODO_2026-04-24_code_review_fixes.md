# TODO (2026-04-24): Code Review 修改 - v0.5.0 API 形参顺序调整

## 背景

根据 CODE_REVIEW_2026-04-24.md 审核意见，对 v0.5.0 的 API 设计进行修正，消除形参歧义、明确语义。

## 需求清单

### 1. 修正 `upload_config` / `update_config` 形参顺序

- [x] 形参顺序调整为：`file_path` 必填且在第一位，`config_name` 可选在第二位
- [x] 消除原 `config_name_or_path` 的多重含义歧义
- [x] 单参数调用时 `config_name` 自动取 `Path(file_path).name`
- [x] 更新 docstring 和文档说明

### 2. 修正 `get_config` 形参顺序

- [x] `save_dir` 移至 `save_path` 之前（因为可以只设置 `save_dir`）
- [x] `save_path` 保持更高优先级
- [x] docstring 中明确 `save_dir` 为纯目录路径
- [x] `config_name` 应为纯文件名，不含路径

### 3. `temp_env_loader` 异常传播

- [x] 用户自定义回调抛出的异常直接传播出去（不再仅记录日志）
- [x] 在 docstring 中注明异常传播行为

### 4. `load_to_env='none'` 行为简化

- [x] 当未指定 `save_dir`/`save_path` 时，直接返回解密后的 `bytes`
- [x] 移除不必要的路径判断逻辑

### 5. 更新文档

- [x] `README.md` 添加 Breaking Changes 说明表格
- [x] 修正示例代码中的形参顺序
- [x] `docs/configuration-priority.md` 更新形参顺序说明
- [x] 更新 `__init__.py` 模块文档字符串

### 6. 补充测试用例

- [x] `test_upload_config_explicit_config_name` - 双参数显式指定配置名
- [x] `test_get_config_load_to_env_none_returns_data` - load_to_env='none' 返回值
- [x] `test_get_config_temp_env_loader_exception_propagates` - 异常传播测试
- [x] `test_get_config_save_path_priority_over_save_dir` - save_path 优先级

### 7. 更新演示脚本

- [x] `case/client_api_ergonomics_case.py` - 更新为新的形参顺序

### 8. 更新审核报告

- [x] `CODE_REVIEW_2026-04-24.md` - 记录修正清单和最终结论

## 验收标准

- [x] 所有测试通过（10/10）
- [x] API 形参无歧义
- [x] 文档与代码同步
- [x] Breaking Changes 已明确说明

## 变更文件清单

```
src/tkzs_config_service_client/client.py      # 核心 API 修改
src/tkzs_config_service_client/__init__.py     # 模块文档更新
README.md                                      # Breaking Changes 说明
docs/configuration-priority.md                 # 形参顺序文档
tests/test_client_api_ergonomics_2026_04_24.py # 新增测试
case/client_api_ergonomics_case.py             # 演示脚本更新
CODE_REVIEW_2026-04-24.md                     # 审核报告
```

## 进度

（实现过程中将 `[ ]` 改为 `[x]`）
