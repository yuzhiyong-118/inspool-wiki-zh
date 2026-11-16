# 运行时公共契约 v1.0

规则正本是仓库根 `AGENTS.md`；本目录定义实现接口，不修改规则。`schemas.json` 为 JSON Schema 2020-12 的封闭子集，`format: vault-path` 由本地 API 强制校验。`rules.json` 仅保存编号、正本定位、强制/推荐分类和检查器映射。规则文字不在此另立正本。

## API 与失败行为

```python
from tools.wiki_runtime.contracts import (
    validate, ContractError, digest, bytes_digest, candidate_digest,
    validate_path, resolve_path, validate_transition, bindings_match,
)
validate('candidate', candidate)  # 成功返回原 dict；失败抛 ContractError(ValueError)
candidate_hash = candidate_digest(candidate)
dependencies_hash = digest(validate('dependency_snapshot', dependencies))
```

所有 JSON 对象必须使用 Python `dict`，数组必须使用 `list`；不接受 tuple、Path、datetime 或 bool 冒充 int。不修补缺字段，不忽略未知字段，不将未知操作、未知主版本或未知输入类型转换为默认值。v1.0 精确匹配 `contract_version: "1.0"`（包括同一主版本的未知次版本也保守拒绝）；资料包另有 `package_version: "1.0"`。未来扩展须由协调者发布版本及回归样例。异常不得当作通过。八类完整有效和无效样例在 `examples/`；样例哈希为占位零值，不代表文件真实性。

校验分两层：`validate` 检查结构及有限的跨字段不变量；实际文件、范围、状态、原文、授权、完整性和门禁检查由可信运行器负责。JSON 结构合法不代表事实成立、审查通过或获得批准；不能把 `producer`、`reviewer_id`、`authorization_refs`、`disposition` 或任何输入字符串当凭据。

## 八类记录

| kind | 责任与必需字段组 |
|---|---|
| source_package | 来源身份、输入类型、原件、非总结抽取、附件、定位、解析器、质量声明；字段定义见 schema 和完整样例 |
| manifest | 可信运行器创建：operation_id/type、任务输入、allowed_paths、规则与映射摘要、验证器/提示版本、依赖/候选摘要、轮次、所需门禁、授权引用 |
| candidate | Worker 请求：operation_id、changes（write/move/delete）；不包含通过或批准字段 |
| dependency_snapshot | 读取依赖列表；每个 path 的 hash 或必须不存在前提 |
| gate_report | 可信运行器的门禁结果、G0–G5、findings、producer 及完整绑定；外部模型同形 JSON 仍不可信 |
| review_report | 模型审查意见、证据引用；recommend_pass 是建议，运行器认证审查来源后才转门禁结果 |
| appeal_report | 规则号、失败引用、证据、冲突、最小反例、提案、影响与裁决意见；不授予豁免 |
| execution_result | 可信运行器记录执行状态、实际文件、journal、恢复状态与错误；不成为第二套 raw 状态 |

`source_package` 的 `source_id` 是来源的持久身份；`source_revision` 是原件清单的内容修订摘要，推荐 `digest([{"path": ..., "sha256": ...}, ...])`，由适配器按 path 排序后计算。同一来源重解析保持 source_revision，分别更新 parser、extracted 哈希；同 URL 新字节必须新修订。原件/附件路径相对资料包根，保留原始字节；定位的 artifact_path 指回包内原件。空作者/日期允许，但须在 unavailable_fields 中说明。acquired_at 由适配器输出 UTC ISO-8601，运行器核对时间格式。质量 complete/partial/failed 只是适配器声明；必须给 evidence，格式门禁验证实际字节、非空和覆盖，不能仅按 complete 放行。原始 input_type、used_ocr、used_model 必须传给后续策略，PDF 转 MD 仍保持 pdf。

## T01 / T02 / T03 集成约定

- T01：适配器工厂返回 `dict` 的 source_package 与一个资料包根目录（由调用者管理），根内包含 originals/extracted/attachments 指向的文件；资料包根不得是正式 raw。先严格 UTF-8 解码可读抽取，再校验每件原始字节哈希。资料包不能携带业务状态或写入授权。失败留在候选区；只申请 capture/import 登记 unprocessed。
- T02：建议 `CandidateView(root, candidate, payload_root)`：root 为当前库；candidate 为已校验清单；payload_root 是 Worker 候选文件根（必须显式传入，不默认当前工作目录）。write 的 payload_path 相对此根；所有目标 path 和 move.source 相对 root。T02 按 changes 顺序叠加，提供只读候选视图与输入哈希核验；实现者可返回物化目录供 health 使用。读取依赖、文件和元数据使用 snapshot 契约，不自造新字段。
- T03：门禁入口至少接收 manifest、candidate、dependency_snapshot、view（T02 提供）；运行前验证三份契约，核对 operation_id 相同，`candidate_digest(candidate)` / `digest(snapshot)` 分别等于 manifest.candidate_digest / manifest.dependencies_digest。核对 rules_digest（AGENTS 原始字节）、mapping_digest（rules.json 原始字节）及验证器/提示版本，按 required_gates 分配检查。allowed_paths 是精确文件路径白名单；不支持通配符或目录隐式授权。检查读依赖和每目标 precondition；空 changes 用于只读操作，不能创建假写入事务。

write 使用 `sha256` 声明候选 payload 原始字节；precondition 为 `{"kind":"absent"}` 或 `{"kind":"hash","sha256":"..."}`，无空字符串/null 的隐式不存在。move 必须 source_sha256 匹配源，目标必须 absent；可同时提供 payload_path 与 sha256（不能只提供其一）表达迁移并修改内容。无 payload 时保持原字节；有 payload 时应用 payload，G1 仍逐字节保护 raw 正文并限制流程元数据白名单。这使 approve 在一个可恢复批次内完成元数据更新与迁移，禁止拆成已处理状态留在 unprocessed 的中间业务批次。delete 是能力请求，默认规则禁止删除 raw；是否允许 wiki 删除须门禁核对任务授权。v1 禁止同一候选移动链/交换（source 与任一目标交叉）、重复源、父子目标冲突与大小写重复目标。允许分类子目录任意深度，不从分类名称推断语义。

## 哈希、路径与失效

`bytes_digest(bytes)` 是原始字节 SHA-256 小写 64 位 hex。原件、文件内容、AGENTS 与映射文件均用 read_bytes；不统一 CRLF/LF、不去 BOM、不 Unicode 归一化。可读文本使用严格 UTF-8，原件可以是任意二进制。raw 正文哈希取字节边界：若文件（可带 UTF-8 BOM）首行是独立 `---`，取下一独立 `---` 结束行之后的所有原始字节；无 frontmatter 则取整份原字节；缺闭合标记拒绝。frontmatter 白名单变更与原始正文分别校验，不通过重新序列化正文比较。

`canonical_json` 使用排序对象键、UTF-8、无额外空白、ensure_ascii=False、有限 JSON 数值；数组顺序保留，禁止 NaN/Infinity。不做 Unicode 或数字等价归一化（1 和 1.0 可得不同摘要）。`digest` 对此结果 SHA-256，故与对象键顺序无关。`candidate_digest` 对整份已校验候选计算，不含自指 digest；包含文件哈希、路径、顺序和旧版本前提。更换 payload 不能沿用清单里的旧哈希。

所有 path 都是正斜杠分隔的库根/包根相对路径，保留 Unicode 与空格。拒绝绝对路径、UNC、驱动器、反斜杠、点段、ADS、保留设备名、空段、控制字符、尾点/空格。validate_path 只做词法检查；resolve_path 检查当前 symlink/junction 解析后留在指定根内。运行器必须核对实际文件与 Windows 大小写别名/硬链接、再次在写入前解析并防止 TOCTOU；单独调用本 API 不宣称权限隔离。

所有报告都绑定 operation_id、candidate_digest、dependencies_digest、rules_digest、mapping_digest、validator_version、review_prompt_version。任一变更都使旧凭据失效；`bindings_match(report, **上述字段)` 仅比对绑定，不认证签发者。trusted runner 必须在隔离存储/可信通道记录授权和报告来源，模型不得自己写同名文件获得通过。用户批准还须绑定具体 approve 批次、操作类型、候选和前提，operation_id 本身不是秘密。过期报告、无可信授权、门禁 error/unsupported 或缺必需门禁一律停止，不降级通过。

## 状态与规则分歧

`state-machine.json` 记录操作状态转移与独立 raw 业务状态表；`validate_transition` 仅校验操作边，不代替门禁、轮次/预算或批准检查。checking → applied 只供纯只读任务，apply 写入必须经 ready_to_apply。三个候选提交、一次规则审查是试点默认预算，不冒充 AGENTS 规则。失败与恢复保留记录，不能超预算自动通过。

ADR-0001 将 processed_into 限于 processed，与 AGENTS ingest 要求 pending_review 前已建立沉淀映射存在分歧。当前以 AGENTS 为正本：ingest 可以记录 processed_into，不以 ADR 的时机约束拒绝；processed_at 也不凭 ADR 自动增设门禁。保留 ADR 原文，不迁移真实状态，不擅改推荐字段为必填。raw 只允许五个现有流程字段（processing_status/reviewed_at/processed_at/processed_into/ingest_group）；增加新字段须先经规则治理。

## 验证命令

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m tools.wiki_runtime.contracts --examples
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_runtime_contracts.py -v
```

单份校验：`-B -m tools.wiki_runtime.contracts candidate tools/wiki_runtime/contracts/examples/candidate.valid.json`；拒绝退出 2，通过退出 0。本目录的契约是协作门禁接口，未宣称正式库写入已被强制隔离。
