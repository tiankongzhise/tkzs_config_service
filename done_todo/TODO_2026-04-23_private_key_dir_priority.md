# TODO (2026-04-23): login/private_key_dir 优先级支持

## 需求背景
- 目前 `private_key_path` 需要传完整文件路径，用户希望只传父目录。
- 新增 `private_key_dir` 后，文件名应按用户名 + 私钥后缀自动生成。
- 需要定义同层和跨层的明确优先级规则。

## 需求拆解
- [x] `login` 新增参数 `private_key_dir`
- [x] `configure_client` 新增参数 `private_key_dir`
- [x] 同一优先级中，若同时有 `private_key_path` 和 `private_key_dir`，以 `private_key_path` 为准
- [x] 不同优先级中，以高优先级为准：`login` > `configure_client` > 默认逻辑
- [x] `private_key_dir` 拼接规则：`{dir}/{normalized_username}{private_key_suffix}`
- [x] 更新测试用例覆盖所有组合优先级
- [x] 更新 README 与 docs 文档说明和示例

## 验收标准
- [x] `login(private_key_dir=...)` 能正确按用户名推导私钥文件
- [x] `configure_client(private_key_dir=...)` 对新实例生效
- [x] 同层 `private_key_path` 覆盖 `private_key_dir`
- [x] 不同层优先级正确：`login` 参数覆盖全局配置
- [x] 测试通过，文档与实现一致
