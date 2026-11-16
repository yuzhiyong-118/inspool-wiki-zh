---
name: "source-command-approve-ingest"
description: "在用户确认后，将 pending_review 的 ingest 单元归档到 raw/processed，并回补 wiki 中的 raw 引用"
---

# source-command-approve-ingest

规则正本是 `AGENTS.md`；先读取它，不在本入口复制维护规范。运行接入和权限要求见 `tools/wiki_runtime/host/HOST-INTEGRATION.md` 与 `NATIVE.md`，进度见 `tools/wiki_runtime/ENTRYPOINTS.md`。

默认由可信宿主的受限 dispatcher 建立独立子上下文，继承主 Agent 模型；无需独立 API 或另选模型。通用 callback、AgentSession 类或 doctor 网关探针存在，不等于当前产品已绑定或权限已验收。缺少真实 dispatcher、独立 Reviewer 或实际权限限制时，暂停需模型审查的运行，只说明缺口；不能由同一上下文自己审自己、伪造 pass、降级到直接写正式文件或调用旧写入口。

需要语义生成或修改的维护由 Worker 提候选，经 G0–G2、独立 Reviewer、有限修复/必要规则申诉后交 Executor 重验与应用。可信确定性 health、raw-index 和 capture 导入由固定脚本重算并交 Executor，不无条件调用模型；所有落盘（含日志、缓存、索引和 raw 元数据）仍走受控入口。缺少模型 dispatcher 不妨碍只读脚本或已绑定的可信零 LLM 派生流程。模型不得直接写正式库、签发批准、调用任意 maintenance Python 或 shell 绕过。只有 Executor 确认应用成功，才能报告已落盘。实际宿主接口由可信接入方提供，不能把下述路由当作已经注册的工具。

保留 `/approve_ingest` 的确认后归档语义。先只读列出 pending_review 批次及其来源页、旧/新路径和待修引用；未指明时可展示最近批次作为待确认对象，不能自动把它当作已批准。

必须取得用户对具体完整批次的明确确认，并由可信批准通道绑定候选、依赖和规则；“继续本会话”、开发迁移授权、模型的 human_confirmed/pass 都不构成某批次批准。若批次不明确或可信批准通道未绑定，停在可审阅候选，说明所需具体确认。

由已绑定宿主以 `operation_type="approve"` 生成候选（初始 `apply=False`），仅可信接入方可取得批准并交 Executor 应用。候选覆盖整组迁移、流程元数据、所有 raw 旧引用修复、raw/index、动作日志及逐文件追加审计；审计保留用户确认依据、来源页、可靠内容标识，不将 git HEAD 冒充原件内容 hash，不凭空编造 hash。不得直接追加 audit-log 或运行移动命令。

Executor 应用与局部旧路径残留校验均通过后，才报告整组已归档；失败则明确未完成和残留。归档过程不借机大改知识正文。
