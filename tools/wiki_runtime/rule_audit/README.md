# T07 规则申诉协议

使用冻结契约 v1.0；不修改契约、规则正本、ADR、候选或正式库。申诉与返回均为 `appeal_report`；结构合法只是意见，不是批准凭据。

```python
auditor = RuleAuditor(
    rules_bytes, mapping_bytes,
    validator_version=manifest['validator_version'],
    review_prompt_version=manifest['review_prompt_version'],
    transport=transport,
)
result = auditor.audit(
    manifest, submitted_appeal, trusted_failure_reports,
    seen_keys=persisted_seen_keys,
    reserve_call=reserve_global_call,
    evidence_documents={'ADR0001': original_text},
    timeout=30.0,
)
```

`transport(request, *, timeout)` 返回完整 `appeal_report` dict。请求含固定中文 system、`rule-audit-1.0` 提示版本、规则原文及映射、申诉、可信失败轨迹和可选原文文档。不存在默认网络服务，不联网或付费。

`trusted_failure_reports` 是可信运行器持有的 `failure_ref -> gate_report`。运行器须认证报告来源；模型自己提供同形 JSON 不能变成可信轨迹。每个争议规则必须存在于映射，并实际出现在同操作同版本失败报告的 blocking findings 中。缺失、空白或过期证据会抛 `ContractError`/`AuditError`。

`AuditResult.status` 为 `reviewed / duplicate / unavailable / budget_exhausted / error`。只有 reviewed 含 report，裁决位于 `report['disposition']`：

- `rule_valid`：返回候选修复流程，剩余机会由协调者保留。
- `validator_bug`：先补失败用例再修验证器，要求重验。
- `rule_change_needed`：返回独立修订提案草稿，要求用户明确批准及重验。
- `insufficient_evidence`：停止自动循环并转人工。

任何结果均不允许内容应用或自动豁免。规则变更模板包含 diff、反例测试、既有页面影响与迁移计划；具体 diff 的充分性仍需独立审查，模板本身不能证明提案已完整或已获批准。

协调者按操作串行调用，持久化 `seen_keys`，并在 `reserve_call()` 原子扣除全任务调用/时间预算；返回 False 拒绝唤醒。相同实质证据不会重复审查，换候选摘要、版本或建议措辞不会重置此限制。新反例、失败证据或原文材料可形成新键，但仍须外部预算允许。模型错误和超时保留已消耗的机会；默认每争议一次以及全局预算由 T08 强制实施。

daemon 线程为等待提供超时边界；Python 无法强杀任意 transport，迟到结果被丢弃。生产 transport 还须自身实现可取消请求、资源与网络超时。去重集和预算回调是可信接口，不能从模型响应恢复，模块不提供重置接口。
