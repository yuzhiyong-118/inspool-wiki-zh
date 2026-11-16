# T08 开发运行记录

- 日期：2026-10-26。
- 状态：开发完成，待协调者复核与集成；开发者不自行标记最终已验收。
- 所有权：仅 coordinator/ 与 tools/tests/test_bounded_loop.py；未修改公共契约、CLI、Reviewer、RuleAuditor、正式 raw、AGENTS、ADR 或共享 wiki 导航。
- 运行环境：Windows PowerShell；标准库，无新增依赖。token 使用量宿主未提供，记为未知。

## 契约与依赖

公共契约版本 `1.0`，读取时原始字节 SHA-256：

| 文件 | SHA-256 |
|---|---|
| schemas.json | `6bc99b80b4f94257303fe73c94f19ce9ea793f4ee7261d0dec75489c26f8a507` |
| state-machine.json | `0900567b8014746ec6a939968bea8dce057a1e4c3f3685f1ccd073d98e88cb4a` |
| rules.json | `0619f60b81322f50502d355bba0fde6ee08fdba6274233bbcba9cbdfe166400f` |

规则正本由每次运行读取实际 AGENTS 字节摘要，不在此复制规则内容。T06 `review.PROMPT_VERSION` 为 `review-1.0:` 加固定提示 SHA-256；T07 通过真实 `RuleAuditor.audit` 调用并使用其 reserve_call/seen_keys 接口。本任务没有改变依赖模块。

## 交付文件

- `coordinator/__init__.py`：导出 Coordinator、LoopResult、requires_review。
- `coordinator/loop.py`：三候选、一次申诉、独立环境重试、调用/时间预算持久化、真实门禁与独立审查、版本失效和候选移交。
- `coordinator/README.md`：精确调用协议、跳审边界、暂停策略、运行目录信任和 T09 接口。
- `coordinator/RUN-T08.md`：本记录。
- `tools/tests/test_bounded_loop.py`：仅临时夹具，真实 CandidateView/G0–G2/T06/T07，明确假模型。

## 开发验证过程

首轮测试使用 2 秒单次等待和不完整 raw/index 临时夹具。真实 CandidateView/G0–G2 在该 Windows 环境耗时数秒，导致环境重试耗尽；放大测试等待上限后，真实 G2 又拒绝了夹具缺失队列计数和表格的问题。未绕过门禁，修复了临时夹具和测试运行时限。开发中途被其他上下文加载的旧测试输出不作为最终验收。

修复后 20 项完整联测通过，耗时 87.094 秒；之后补齐已 reserve 调用的中断重启和规则审查 transport 未配置两项测试。最终运行前冻结 Python 文件，运行期间仅补文档；最终结果如下。

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_bounded_loop.py -v
```

```text
test_call_budget_preserved_across_restart_and_audit ... ok
test_dependency_change_during_review_invalidates_pass ... ok
test_dispute_not_repeated_after_rule_valid ... ok
test_environment_retry_then_success_does_not_spend_candidate ... ok
test_environment_timeout_is_independently_bounded ... ok
test_explicit_execution_limits_required ... ok
test_four_audit_dispositions_and_persisted_budget ... ok
test_index_new_claim_and_link_alias_require_reviewer ... ok
test_models_must_be_configured ... ok
test_payload_change_during_review_invalidates_pass ... ok
test_pdf_partial_and_ocr_pause_before_worker ... ok
test_readonly_and_pure_index_need_no_reviewer ... ok
test_repair_success_uses_real_gates_and_review ... ok
test_reserved_call_survives_interrupted_restart ... ok
test_reviewer_environment_failure_has_global_bound ... ok
test_rule_version_change_during_review_invalidates_pass ... ok
test_semantic_write_cannot_skip_by_operation_flag ... ok
test_stale_review_report_is_not_a_credential ... ok
test_three_candidates_exhausted ... ok
test_time_budget_and_restart_not_reset ... ok
test_unavailable_rule_auditor_stops_without_fake_model ... ok
test_untrusted_payload_root_and_self_approval_rejected ... ok

Ran 22 tests in 91.020s

OK
```

修复成功用例逐字节比较整个临时正式库，确认协调器只写运行目录；其余测试也只使用临时文件。没有触碰真实 raw，未自动 approve。测试覆盖四类裁决、申诉机会去重和持久化、全局调用预算跨申诉与重启、时间预算跨重启、原文/载荷/规则/报告绑定失效、环境超时及有限重试、未配置模型、PDF/partial/OCR 和 MD 原类型标记暂停、索引强结论/别名绕过及自报批准拒绝。

## T09 移交与剩余边界

成功 `LoopResult.bundle` 字段为 manifest、candidate、snapshot、payload_root、reports、review；仅返回 ready_to_apply。T09 应用前须重验实际前提与候选字节、独立复算 requires_review、重新取得可信 G3，并检查所需授权；保存的 pass JSON 不是签名。T08 不提供 G4/G5 或实际应用能力。

默认每操作一次规则审查比“每争议一次”更保守；approve 暂保守进行语义审查，尚未实现纯路径机械替换的跳审优化。缺少所有来源类型标记的 MD 无法恢复原始 PDF 身份，可信采集入口须保留并传入资料包。daemon 无法强杀底层调用，生产 transport 必须自行取消并约束资源和文件权限；run_dir 需要可信调用方独占保护。当前为协作门禁，未宣称操作系统隔离或全库强制守护。未评测真实模型的审查或规则裁决质量。
