---
name: "source-command-ingest-raw"
description: "处理 raw/unprocessed 中的下一个 ingest 单元，或指定文件/文件夹（无参数时默认处理下一个）"
---

# source-command-ingest-raw

规则正本是 `AGENTS.md`；先读取它，不在本入口复制维护规范。运行接入和权限要求见 `tools/wiki_runtime/host/HOST-INTEGRATION.md` 与 `NATIVE.md`，进度见 `tools/wiki_runtime/ENTRYPOINTS.md`。

默认由可信宿主的受限 dispatcher 建立独立子上下文，继承主 Agent 模型；无需独立 API 或另选模型。通用 callback、AgentSession 类或 doctor 网关探针存在，不等于当前产品已绑定或权限已验收。缺少真实 dispatcher、独立 Reviewer 或实际权限限制时，暂停需模型审查的运行，只说明缺口；不能由同一上下文自己审自己、伪造 pass、降级到直接写正式文件或调用旧写入口。

需要语义生成或修改的维护由 Worker 提候选，经 G0–G2、独立 Reviewer、有限修复/必要规则申诉后交 Executor 重验与应用。可信确定性 health、raw-index 和 capture 导入由固定脚本重算并交 Executor，不无条件调用模型；所有落盘（含日志、缓存、索引和 raw 元数据）仍走受控入口。缺少模型 dispatcher 不妨碍只读脚本或已绑定的可信零 LLM 派生流程。模型不得直接写正式库、签发批准、调用任意 maintenance Python 或 shell 绕过。只有 Executor 确认应用成功，才能报告已落盘。实际宿主接口由可信接入方提供，不能把下述路由当作已经注册的工具。

保留 `/ingest_raw`：无参数选择下一个 ingest 单元；文件或文件夹参数相对于 `raw/unprocessed/`，例如 `Agent学习.md`、`subfolder/`；`--review` 强制分析后暂停。无参数的队列选择按 AGENTS 批次规则，多候选优先最早队列，无法判断再按名称排序；空队列说明后停止，不造空候选。读取选定资料全文，Phase 1 分析包含八维：源信息与领域类型、关键实体、关键概念、现有 wiki 关联、矛盾与张力、建议新页、建议更新页、待确认问题。按 AGENTS 的安全继续条件进入候选生成与校验；--review 在分析后暂停。

将选定批次与必要旧页作为输入，向已绑定宿主请求 `operation_type="ingest"` 的候选流程（AgentSession.maintenance.run_operation 的可信宿主路由，初始 `apply=False`）。候选覆盖索引、日志、overview、raw/index、反向边与流程元数据；具体规范取自 AGENTS。

PDF/扫描件无文本层或来源包 partial 时暂停，不能改扩展名绕过；视觉提取需真实工具支持和用户决定。图像材料保留 caption-first 模式，列出图像证据、本地路径与不确定性；不得把仅凭 alt/上下文推断的图意写成已看图事实。最终说明选定单元、候选/应用状态与不足。仅应用成功才说明进入 pending_review；本命令不归档 processed。
