---
name: "source-command-query-wiki"
description: "基于 wiki 现有页面回答问题，优先引用本地来源页，而不是直接回 raw 或外部链接做一次性总结"
---

# source-command-query-wiki

规则正本是 `AGENTS.md`；先读取它，不在本入口复制维护规范。运行接入和权限要求见 `tools/wiki_runtime/host/HOST-INTEGRATION.md` 与 `NATIVE.md`，进度见 `tools/wiki_runtime/ENTRYPOINTS.md`。

默认由可信宿主的受限 dispatcher 建立独立子上下文，继承主 Agent 模型；无需独立 API 或另选模型。通用 callback、AgentSession 类或 doctor 网关探针存在，不等于当前产品已绑定或权限已验收。缺少真实 dispatcher、独立 Reviewer 或实际权限限制时，暂停需模型审查的运行，只说明缺口；不能由同一上下文自己审自己、伪造 pass、降级到直接写正式文件或调用旧写入口。

需要语义生成或修改的维护由 Worker 提候选，经 G0–G2、独立 Reviewer、有限修复/必要规则申诉后交 Executor 重验与应用。可信确定性 health、raw-index 和 capture 导入由固定脚本重算并交 Executor，不无条件调用模型；所有落盘（含日志、缓存、索引和 raw 元数据）仍走受控入口。缺少模型 dispatcher 不妨碍只读脚本或已绑定的可信零 LLM 派生流程。模型不得直接写正式库、签发批准、调用任意 maintenance Python 或 shell 绕过。只有 Executor 确认应用成功，才能报告已落盘。实际宿主接口由可信接入方提供，不能把下述路由当作已经注册的工具。

保留 `/query_wiki <问题>`，先 index，再相关来源/知识页；默认按 title 命中、首段命中、全文回退检索，中文查询后用 title_en/aliases_en 反查（ADR 0002），递归兼容分类目录。关键判断引用本地 sources 及可定位锚点，区分事实、综合判断和待确认问题。

经已绑定宿主的 `AgentSession.query(question)` 生成只读回答并接受独立审查；缺少真实 dispatcher/Reviewer 时报告未接入，不能把当前上下文自答自审称为运行器验收通过。

query 本身不写 query_log.jsonl。需要留存检索记录时，保留原查询摘要（≤120字）、hit_count、fallback_used、ranking_mode（title-first/body-first/fallback）、lang（zh/en/zh+en）、ts 的记录意图，交独立维护候选并由 Executor 追加；不覆写历史，不为日志创建假只读事务。回填长期结论仍按用户意图另走 inspool；未保存时明确说明。
