# heal 修复计划接入

`heal` 的模糊改链、索引删项与缺页分类包含语义判断。计划生成可确定性运行，但建议不能成为免审的确定性派生产物。新入口固定使用 `lint` 操作类型，沿用 Worker → G0–G2 → 独立 Reviewer → Executor 重验；所有模型调用共享同一操作预算，默认继承宿主模型。

## 只读扫描与导出

```powershell
python -B tools/heal.py --root E:/临时库 --json
python -B tools/heal.py --root E:/临时库 --operation-id heal-001 --plan .wiki-runtime/candidates/heal-001.json
```

默认扫描不创建目录、不写日志或正文。`--plan` 是显式的候选区写入，限定在所选库的 `.wiki-runtime/candidates/`，拒绝覆盖已有文件、正式正文路径与重解析路径。导出的计划是数据，不是批准记录。`--apply` 在未连接可信宿主 dispatcher 的旧 CLI 中直接拒绝，不配置独立 API 作为替代。

计划含 `operation_id`、固定 `operation_type: lint`、建议 `actions`、中文 `task`、精确 `allowed_paths`、`input_refs`、完整文件哈希与目录清单 `baseline`，以及用于识别内容的 `plan_digest`。哈希不是宿主授权凭证。

`allowed_paths` 只列受影响的既有内容页、索引与日志；原始资料、规则、工具和新桩页面均不在范围内。内容目录递归扫描，用户分类子目录原样保留；能够按同类型唯一页面解析的迁移链接不会被误报。模糊匹配列出候选而不选择目标，高频缺页只列待核查项。需要新建有来源支撑的页面时，应另由可信宿主建立明确范围的维护任务。

## 可信宿主

```python
from tools.wiki_runtime.host.agent import AgentSession
from tools.wiki_runtime.host.heal import build_heal_plan, run_heal_plan

plan = build_heal_plan(root, operation_id="heal-001", min_refs=3)
session = AgentSession(root, dispatcher, parent_session_id=parent_id,
                       state_dir=external_same_volume_private_state)
result = session.heal("heal-001", plan=plan, max_calls=8,
                      max_seconds=300, call_timeout=60, apply=False)
# 等价低层接口：run_heal_plan(session.maintenance, plan, ...)
# apply=True 仍走同一 Reviewer / Executor 与预算。
```

`run_heal_plan` 重新只读复算计划，任何任务、允许范围、文件内容或目录变化都会停止，不能自动刷新旧快照。它同时将 `baseline` 交给 `StandaloneHost.run_operation(expected_baseline=...)`，宿主在锁内建立处理基线时再次精确比对，避免验证与处理之间换入新依赖。后续候选与落地继续使用既有依赖验证和恢复机制。计划没有建议时返回 `no_changes`，不请求模型。

这些 API 只供可信宿主使用，不能作为模型可任意调用的工具；产品部署仍须真实限制文件系统权限与工具 dispatcher。测试中的假 transport 只验证流程及边界，不证明模型判断质量。

## 历史函数兼容

`tools/heal.py` 中的历史 Python 修复函数保留，供已有可信维护代码迁移使用。它们包含可直接改写文件的旧模式，不是模型工具，不应由 dispatcher 暴露；新 CLI 不再调用该写入通路。接入方应使用上述只读计划与宿主入口。
