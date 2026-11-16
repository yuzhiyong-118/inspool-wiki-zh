---
name: "source-command-inspool"
description: "将一次高价值回答或阶段性结论回填为 wiki 页面，通常优先沉淀到 wiki/synthesis"
---

# source-command-inspool

规则正本是 `AGENTS.md`；先读取它，不在本入口复制维护规范。运行接入和权限要求见 `tools/wiki_runtime/host/HOST-INTEGRATION.md` 与 `NATIVE.md`，进度见 `tools/wiki_runtime/ENTRYPOINTS.md`。

默认由可信宿主的受限 dispatcher 建立独立子上下文，继承主 Agent 模型；无需独立 API 或另选模型。通用 callback、AgentSession 类或 doctor 网关探针存在，不等于当前产品已绑定或权限已验收。缺少真实 dispatcher、独立 Reviewer 或实际权限限制时，暂停需模型审查的运行，只说明缺口；不能由同一上下文自己审自己、伪造 pass、降级到直接写正式文件或调用旧写入口。

需要语义生成或修改的维护由 Worker 提候选，经 G0–G2、独立 Reviewer、有限修复/必要规则申诉后交 Executor 重验与应用。可信确定性 health、raw-index 和 capture 导入由固定脚本重算并交 Executor，不无条件调用模型；所有落盘（含日志、缓存、索引和 raw 元数据）仍走受控入口。缺少模型 dispatcher 不妨碍只读脚本或已绑定的可信零 LLM 派生流程。模型不得直接写正式库、签发批准、调用任意 maintenance Python 或 shell 绕过。只有 Executor 确认应用成功，才能报告已落盘。实际宿主接口由可信接入方提供，不能把下述路由当作已经注册的工具。

保留 `/inspool`：将高价值回答、跨来源比较或阶段结论沉淀为 wiki 页面，通常优先 synthesis。先只读查 index 和相关证据，区分事实、判断和开放问题。

交已绑定宿主的 `operation_type="inspool"` 候选流程（初始 `apply=False`）；候选包含页面、必要关系/反向边、索引和 query/refactor 动作日志。按 AGENTS 维护证据链，不复制聊天记录。缺少宿主接入时可以给可审阅内容与计划，但不能声称已沉淀或直接保存。
