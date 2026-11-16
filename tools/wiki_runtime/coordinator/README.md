# T08 有界候选协调器

公共契约版本为 `1.0`，仅使用标准库。协调器生成和检查候选，不修改正式库、不签发用户批准，不调用 Executor。

```python
from tools.wiki_runtime.coordinator import Coordinator, requires_review

coordinator = Coordinator(
    root, run_dir,
    operation_id='operation-001', operation_type='inspool',
    task='根据明确原文更新专题结论',
    allowed_paths=['wiki/synthesis/专题.md', 'wiki/index.md', 'wiki/log.md'],
    input_refs=['raw/unprocessed/原文.md'],
    max_calls=12, max_seconds=300, call_timeout=30,
    environment_retries=1,
    source_packages=[],  # 由可信采集入口提供，不能从 Worker 响应恢复。
)
result = coordinator.run(worker, reviewer=review_transport, auditor=rule_auditor)
if result.status == 'ready_to_apply':
    bundle = result.bundle
    # 交给可信 Executor 重新检查实际输入、必需门禁和授权。
    # reserve_call=coordinator.reserve_call,
    # remaining_timeout=coordinator.remaining_timeout 可延续同一预算。
```

`run_dir` 在库内时必须位于 `.wiki-runtime/`，也可放在库外专属运行目录。调用者应独占并保护该目录，不允许模型编辑状态、报告和冻结候选；这只是协作门禁，未实施操作系统隔离。未配置 Worker 或所需 Reviewer/Auditor 时停止，不提供假生产模型、默认联网或计费服务。

## Worker 接口

`worker(request, *, timeout)` 由可信调用方注入。请求包含任务、操作身份与类型、原文引用、精确写入白名单、下一候选轮次、`payload_root` 和 `feedback`；可通过可信适配器提供读取原文所需的工具。首次 feedback 为空，后续包含当前 manifest、可信失败报告映射和内容意见。

Worker 将载荷写入请求指定的 `payload_root` 或其子目录，返回：

```python
{'candidate': candidate_contract, 'payload_root': request['payload_root']}
```

拒绝任意外部目录、正式库目录和自报 `passed`、`authorization`、`reports` 等附加字段。协调器复制并核验载荷，之后只检查冻结副本。候选最多三份：首次加两次修复；环境重试不消耗候选数，但每次模型调用先持久扣除全任务调用预算。

对当前失败提出规则争议时，Worker 可单独返回 `{'appeal': submitted_appeal_contract}`。申诉必须绑定 feedback.manifest，并引用 feedback.failures 的键（例如 `reports/G3.json`），不能同时提交新候选。RuleAuditor 使用真实失败报告，不采信 Worker 自制轨迹。默认每操作只允许一次规则审查；同时持久化 T07 的实质证据去重键，较默认“每争议一次”更保守。

## Reviewer 与 Auditor

Reviewer 参数是 T06 的 `transport(envelope, *, timeout)`。协调器实际调用 `review.build_request` 和 `review.review`，提示绑定为 `review.PROMPT_VERSION`（`review-1.0:` 加提示摘要）。原文仅取可信 `input_refs`，原页面覆盖修改目标和移动源，候选覆盖全部最终目标；请求不携带 Worker 解释、历史、申诉或自报批准。

Auditor 参数是可信 `RuleAuditor` 实例，使用 `audit(manifest, appeal, failures, seen_keys=..., reserve_call=..., timeout=...)`。`rule_valid` 返回剩余修复机会；`validator_bug`、`rule_change_needed` 和 `insufficient_evidence` 均转人工。规则提案待批准，不能授予本任务豁免。未配置、超时、证据无效、去重或预算耗尽均不转通过。

## 判定与失效

每候选先完整调用 `view.iter_paths()`，然后冻结 dependency_snapshot，再用真实 `run_gates(..., review_prompt_version=PROMPT_VERSION)` 检查 G0–G2。G3 由独立 Reviewer 的受校验意见生成，替换确定性入口对 G3 的 unsupported 占位；不把模型 JSON 当可信签名。所有返回报告核对当前绑定，返回前重新检查规则字节、依赖、目录清单和冻结载荷。

`requires_review(operation_or_manifest, candidate, view)` 可供 Executor 独立复算，不信任调用方删去 required_gates。空 changes 可跳审；`index_rebuild` 仅当所有变更只写两个 index，且去除无别名双链与空白后的原文完全相同时可跳审。新增或改写说明、别名结论、其他路径和操作都需审。当前 approve 保守重做语义审查，尚未实现机械 raw 路径替换的跳审优化；批准仍须由 Executor 单独核验 G4。

明确 PDF/音视频输入、OCR 或模型抽取、质量 partial/failed 的来源包先转人工。也检查 raw frontmatter 中明确的 input_type/source_type/original_type/original_input_type 和 used_ocr/used_model，避免简单改为 MD 扩展名绕过。未带任何类型来源标记的纯 MD 无法可靠恢复其原始类型；可信采集入口仍须保留完整来源包，不能由模型选择性省略来源信息。

## 持久状态与输出

Coordinator 现在是 Runtime 驱动的 Step Driver。`state.json` 原子替换保存兼容投影，不是第二套业务真值；Task、Run、Step、StepResult、Invocation、财务、并发、授权和恢复以 Runtime SQLite 为准。配置不同拒绝覆盖，重启不退款、不刷新 deadline，也不重新应用已通过候选。Worker、Reviewer、RuleAuditor 与修复计费均先登记并领取持久 Step；Invocation 已成功但结果未归并时，重启按原 Step／Invocation 只读恢复，不重新外呼。候选已冻结而审查未归并时继续使用原 round，不增加候选机会。候选目录存在不代表完整发布；重启逐份核对 candidate、payload、dependencies 和 manifest，缺失部分可从原 Worker 结果补齐，已有内容不一致则拒绝。中断运行可保留计数继续，但不复用旧门禁；awaiting_human 为自动流程停止状态，重启不能绕过。已 ready_to_apply 的运行重启转人工，原资料包应交 Executor 重验。

Worker、Reviewer、RuleAuditor 和 Executor G3 均经统一 InvocationPort 原子预留与结算。原子预留和实际发送都核对当前 Task／Run、PolicyRevision、ExecutionOwnership、期限与财务阻断；已成功结果的只读重放豁免动态资格。Task／Run 限制和最终 G3 留额在同一事务检查，not_started、inflight、draining 都占并发资源；unknown 保守结算、不退款、不自动重发，迟到完成只释放资源。候选修复、申诉和步骤 attempt 跨 Run 与重启保留。生产适配器须自行实现取消、网络／资源超时并限制文件权限；外层无法强杀底层 transport，但未知或迟到结果不会获得正式写入能力。可信 Native Attestation 由 transport 私有登记并一次性消费，普通字典、改绑和持久化重放不能签发可复用凭据。

每轮保存 candidate.json、manifest.json、dependencies.json、payload/、reports.json、reports/Gx.json、review-call-N.json；实际审诉另保存 audit.json。成功返回 `LoopResult(status='ready_to_apply', reason=..., bundle=..., state=...)`，bundle 包含：

- `manifest`、`candidate`、`snapshot`：公共契约对象。
- `payload_root`：该轮冻结副本的绝对路径。
- `reports`：当前 G0–G2 和所需 G3 的结果。
- `review`：独立内容审查意见，跳审时为 None。

`ready_to_apply` 只是移交候选，不表示写入或获得批准；失败时 bundle 为 None。运行状态从不写进 raw 的 processing_status。本模块不实现 G4/G5 或正式事务，Executor 必须独立确定所需门禁、实际文件版本及批准，不能把保存的报告同形 JSON 当凭据。

## 验证

仅在临时库使用真实 CandidateView、G0–G2、T06 和 T07 协议，模型为明确的测试替身。未评测实际模型的内容审查与规则裁决质量。
