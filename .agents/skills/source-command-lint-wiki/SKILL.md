---
name: "source-command-lint-wiki"
description: "对 wiki 做结构、证据链、关系字段和 raw 状态一致性检查，并修复低风险问题"
---

# source-command-lint-wiki

规则正本是 `AGENTS.md`；先读取它，不在本入口复制维护规范。运行接入和权限要求见 `tools/wiki_runtime/host/HOST-INTEGRATION.md` 与 `NATIVE.md`，进度见 `tools/wiki_runtime/ENTRYPOINTS.md`。

默认由可信宿主的受限 dispatcher 建立独立子上下文，继承主 Agent 模型；无需独立 API 或另选模型。通用 callback、AgentSession 类或 doctor 网关探针存在，不等于当前产品已绑定或权限已验收。缺少真实 dispatcher、独立 Reviewer 或实际权限限制时，暂停需模型审查的运行，只说明缺口；不能由同一上下文自己审自己、伪造 pass、降级到直接写正式文件或调用旧写入口。

需要语义生成或修改的维护由 Worker 提候选，经 G0–G2、独立 Reviewer、有限修复/必要规则申诉后交 Executor 重验与应用。可信确定性 health、raw-index 和 capture 导入由固定脚本重算并交 Executor，不无条件调用模型；所有落盘（含日志、缓存、索引和 raw 元数据）仍走受控入口。缺少模型 dispatcher 不妨碍只读脚本或已绑定的可信零 LLM 派生流程。模型不得直接写正式库、签发批准、调用任意 maintenance Python 或 shell 绕过。只有 Executor 确认应用成功，才能报告已落盘。实际宿主接口由可信接入方提供，不能把下述路由当作已经注册的工具。

保留 `/lint_wiki`：检查结构、证据、关系与 raw 状态，并经受控流程修复低风险问题。先使用库内 `tools/health.py --json` 做零模型只读结构检查；语义检查与阈值分工读取库内 `.claude/commands/lint_wiki.md`，不要沿用旧版一级目录限定或 meta 死链豁免。

已绑定宿主的 `AgentSession.lint()` 是只读语义审查入口，独立 Reviewer 验证后返回报告。维持可比较的输出：死链清单、frontmatter 合规问题、其他语义问题、已修复与下一步；结构结果来自 health，尚未执行的修复标为建议。

如需修复或保存日志，另走 `operation_type="lint"` 的候选流程（初始 `apply=False`），经独立审查和 Executor 后再报告已修复。只读 lint 不直接追加日志；缺少维护接入时明确日志未落盘。不要用旧 heal --apply 或任意文件写入绕过。
