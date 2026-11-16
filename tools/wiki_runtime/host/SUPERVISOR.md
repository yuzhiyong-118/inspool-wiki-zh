# 独立受限入口

这里的独立指角色上下文和权限。默认模型继承与通用宿主接入见 [HOST-INTEGRATION.md](HOST-INTEGRATION.md)。传入可信 `transport` 时无需 `model_config` 或额外 API 密钥；本文远端 JSON 模型的描述属于可选 API 部署方式，不是所有宿主的必要形态。

`StandaloneHost(root, state_dir, model_config=None, *, transport=None, offline=False)` 是可信宿主。`root` 是正式库，`state_dir` 必须显式指定在库外、同卷，不能包含正式库。它下设 `private/`（批准、签名待审记录、恢复 journal）与 `operations/`（协调状态、固定候选与 Worker 载荷）。不能把状态目录的内容提交到知识库。

模型是远端的 JSON 文本生成器，没有本机代码执行权限。宿主不给模型 shell、API 密钥、批准、任意文件写入、Executor 或预算管理工具。每次 Worker、T06 Reviewer、T07 RuleAuditor 都是新请求；Reviewer 不接收 Worker 的反馈或辩护。固定身份的 `RoleBackend` 负责正式资料的受限读取与候选写入；Worker 的写入根只绑定本次请求的 `worker_payload_root`，私有目录受保护。正式库仅由可信 Executor 发布。

这约束的是独立入口的模型通道，不能据此声称当前桌面会话、Windows 账户或任意本机进程已经受到操作系统隔离。可信 Python 调用方及运行文件仍须由部署者保护。

## 调用与返回

```python
host = StandaloneHost(vault, state_dir, transport=trusted_host_transport)
result = host.run_operation(
    operation_id="owner-operation-001", operation_type="inspool", task="具体任务",
    allowed_paths=["wiki/synthesis/结论.md", "wiki/index.md", "wiki/log.md"],
    input_refs=["raw/unprocessed/原文.md"],
    max_calls=8, max_seconds=300, call_timeout=60,
    apply=False, environment_retries=1,
)
```

`allowed_paths` 是精确文件清单，移动源也须列入；模型不能增加范围。预算包括处理、审查、申诉及 Executor 的额外审查。Task Runtime 统一管理 Task／Run／Step／Invocation、财务、授权和恢复，Host 不另存权威余额或审查状态。重启同一操作时恢复原始 deadline 和调用次数，不能重置。默认传入复用宿主模型的可信 `transport`；仅选择可选 API 适配时才需要 [MODEL.md](MODEL.md) 的配置和密钥。两种接入都没有提供时拒绝运行，不自动选择模型。`transport` 注入点仅供可信宿主或测试使用；不能来自模型输入。

学习 ingest 使用 Runtime Authorization，approve 继续使用 ApprovalStore／G4，二者不可互替。锁外 G3 不持 Host 线程锁，暂停和撤销可真实完成；撤销按 operation 封闭全部未消费授权，新授权回写 pending 前再次确认仍 issued，consumed 历史不能撤销。pre-WAL 旧 operation 在 pause 后 supersede，resume 使用同 Task 的新 operation、Admission 和 Authorization。已有 WAL 始终按原 operation 恢复，终态先按原绑定查询，Host 不暴露合成 Readiness／Credential 写入入口。

返回为字典：`status`、布尔 `applied`，并按阶段包含 `reason`、`state`、`bundle`、`context` 或 `execution`。`ready_to_apply` 只表示候选完成检查、已保存待审记录。`apply=True` 仍交 Executor 重新运行 G0–G2 和必要 T06；既有报告不能替代重验。普通操作不另加人工批准；`approve`、`rule_maintenance`、`tool_maintenance` 缺独立批准时返回 `awaiting_approval`。

`load_pending(operation_id)` 仅按宿主私有位置加载并认证记录，返回 `config/bundle/context/provenance`。调用方可据此展示完整 diff。`approve_pending(operation_id, **kwargs)` 调用 `ApprovalStore.approve_interactive`；只有 owner 独立真实 TTY 输入完整上下文摘要才能签发，管道、JSON 的 `approved: true`、运行命令本身都不能批准。返回摘要不含凭据。`revoke_pending(operation_id)` 撤销当前绑定上下文的批准。`apply_pending(operation_id)` 重新读取可信记录、恢复协调预算、复核生成基线、查询批准，再交 Executor。`recover(operation_id)` 仅从同一操作的私有 journal 恢复，保留执行器的并发编辑冲突保护。

owner 在密钥撤回或服务故障时可显式以 `offline=True` 构造宿主，不需要模型配置。离线模式只安装固定的拒绝模型传输，禁止 `run_operation`，允许加载、独立终端批准、撤销及恢复；语义 `apply_pending` 仍因 G3 不可用而停止，不能借离线模式跳审查。它不会重置等待期间的预算。若非空私有状态或操作目录丢失 `pending.key`，宿主拒绝自动生成新密钥，须由 owner 对账。

待审记录以私有密钥 HMAC 绑定候选、上下文、配置与生成前 provenance。生成前枚举完整文件及目录基线，模型调用后、候选发布前、应用前都复核；不会把调用期间的新内容默认为 Worker 已读的旧内容。候选 SHA256 和目标前提均由宿主生成。Executor 继续检查固定 payload、依赖、规则及实际差异。过期或基线变化须显式重新建立操作。

对于显式 `input_refs` 中由 capture 创建的 raw 薄来源记录，宿主只展开一跳同组的 `raw/assets/<source_id>/<source_revision>/extracted/content.md`。`source_package` 字段必须指向该目录的 `source-package.json`，包身份、原件、抽取和附件须通过可信 `validate_package`；单包最多 128 个文件、总计 32 MiB。真实抽取原文加入 Worker 和 Reviewer 的绑定 `input_refs`，原类型和完整度作为可信 `source_packages` 传入 Coordinator。PDF、多模态、partial、OCR 或模型抽取仍触发暂停。普通手工 Markdown 保持原状，不任意跟随链接、外部路径或私有状态。展开之前已固定操作基线，扩展后的引用清单才进入 manifest、待审上下文和签名。

## Worker 数据协议

仅返回一个 `{"changes": [...]}`，最多 128 个动作，整个响应最多 2 MiB，每个候选文件最多 1 MiB：

- `{"action":"write","path":"wiki/...md","text":"完整文本"}`
- `{"action":"delete","path":"wiki/...md"}`，是否允许仍由下游门禁决定。
- `{"action":"move","source":"raw/unprocessed/...md","path":"raw/processed/...md","metadata":{...}}`；普通非 raw 移动也可带 `text`，`text` 与 `metadata` 互斥；无两者则保留源文件字节。
- `{"action":"raw_metadata","path":"raw/unprocessed/...md","metadata":{...}}`

`metadata` 只允许 `processing_status/reviewed_at/processed_at/processed_into/ingest_group`，值仅字符串或字符串数组。raw 原件不能使用 `write` 或 `move+text`；宿主只替换指定流程字段块，逐字节保护其他字段、注释及正文。新 raw 采集须走可信 capture/import 资料包流程，本入口不从 Worker 文本授予资料包认证。

收到具体失败后，可单独返回 `{"appeal":{...}}`，字段精确为 `rule_ids/failure_refs/evidence/goal_conflict/minimal_counterexample/proposal/impact`。宿主补齐当前失败 manifest 的全部绑定及 `disposition=submitted`，T07 独立裁决。未知字段、工具、角色、批准声明和自行填写裁决均拒绝。

## 验证范围

`python -B -m unittest tools.tests.test_standalone_host -v` 使用临时库和可信假模型传输，实际运行 RoleBackend、Coordinator、G0–G2、T06 和 Executor，验证候选发布、独立审查、并发变化、raw 字节保护、预算恢复及批准拒绝。替身验证不证明真实模型的内容理解质量；未配置并调用真实模型时，必须明确报告 live 模型尚未验证。
