# T00 专属开发记录

- 日期：2026-10-26；状态：开发自检完成，待协调者集成验收。
- 修改范围：仅本 contracts 目录与 `tools/tests/test_runtime_contracts.py`。
- 依赖：Python 标准库；未新增第三方依赖。
- 未修改真实 raw、AGENTS、ADR 或共享导航；未运行真实 ingest/approve。

## 接口交付

v1.0 八类记录、封闭 JSON schema 子集、标准库校验 API、CLI、16 个有效/无效样例、操作/业务状态分离、16 条规则映射与三条设计约束。move 可带成对 payload_path/sha256，支持同一批次迁移并更新流程元数据；正文保护仍由 G1 强制检查。

`bindings_match` 统一使用 dependencies_digest（复数），同时绑定 operation_id、候选、依赖、规则、映射、验证器和审查提示版本。结构校验不认证签发者；完整性和批准均不能由模型字段自行授予。

## 验证

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_runtime_contracts.py -v
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m tools.wiki_runtime.contracts --examples
git -c core.safecrlf=false diff --check -- tools/wiki_runtime/contracts tools/tests/test_runtime_contracts.py
```

结果：18 项测试运行成功，其中 1 项 symlink 创建因当前宿主权限限制跳过；其余 17 项通过。16 个样例均符合预期。diff --check 退出 0（新增未跟踪文件由测试实际加载，Git 对未跟踪文件本身不做 diff）。

## 发布指纹

计算规则：对下列七个文件分别取原始字节 SHA-256，组成文件名→哈希对象，再调用 contracts.digest；不包含本运行记录、样例和测试。

指纹：`51d3ae4196fbd1ece4cd8d644e2bbf0982ea7243bc551de6c8b00fa31be8b48e`

```json
{
  "schemas.json": "6bc99b80b4f94257303fe73c94f19ce9ea793f4ee7261d0dec75489c26f8a507",
  "rules.json": "0619f60b81322f50502d355bba0fde6ee08fdba6274233bbcba9cbdfe166400f",
  "state-machine.json": "0900567b8014746ec6a939968bea8dce057a1e4c3f3685f1ccd073d98e88cb4a",
  "core.py": "cd2aa0a786e7a9bf8b9f0b682044eceddd4067b417162a6fd00d5a3feca2725e",
  "__init__.py": "9b6c992a08cadbb395ee99f55f04305e3fa00e40597dd831bb675d85eeb101ea",
  "__main__.py": "47cc6ebd7fdb30494901731b5bb9edc5104ef1eee5de1cff682745c240e13e44",
  "README.md": "7d8428a69a8d6948d44743edc7c6e432d107db7a3496977ce65dfa9f575ae10b"
}
```

## 剩余限制与交接

运行时的授权真实性、实际文件哈希、junction/硬链接、并发修改、语义事实、格式完整性仍由后续门禁和执行器检查。本 API 不宣称强制隔离。symlink 的词法与解析 API 已提供，但 Windows 宿主创建/攻击实测需后续具备权限的隔离任务补验。ADR-0001 的 processed_into 时机分歧已记录，未改写 ADR，按 AGENTS 当前流程执行。T01/T02/T03 按 README 和样例接入；后续契约变更由协调者统一发布。
