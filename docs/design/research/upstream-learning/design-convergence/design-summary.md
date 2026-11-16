---
type: meta
title: 三专题设计收敛结论
status: design_converged
updated: 2026-11-09
topic: 三专题设计收敛结论
related_sources: []
related_synthesis: []
---

# 三专题设计收敛结论

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-10。D1–D3 已完成静态设计与关键源码复核，后续按 [实施任务书](../../../learning-book-implementation-tasks.md)推进。I0/I1 无模型验证通过；使用 MiniMax minimax-m3 和本地 Ollama bge-m3 的 I2 首轮已执行，完整验收尚未通过。未开发产品适配器。原始准备见 前置验证（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-preflight/README.md） 和 100 万原始 token 预算/80 万暂停约定（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-setup/quota-budget.md）。

当前执行结论：I2 验收需修复（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-review.md）；页边教学未执行、预算暂停失效，原始交付另有凭据暴露。当前不重跑整轮、不自动进入适配开发，先按验收报告关闭问题。

**推荐：使用 DeepTutor Book 交互书作为首个学习入口，完整复用其 Web、生成与页边 chat；本项目只承担资料交付、证据固定与结果交接。** OpenMAIC 仍是课堂播放、角色演出和短答模型批改成为核心需求时的替代方案。本轮未再次要求用户选择产品细节，也未将推荐冒充运行验收通过。

| 已收敛决定 | 内容 |
| --- | --- |
| 用户体验 | 明确整理后生成小型交互书，网页阅读/追问/单答案选择题练习，恢复后导出；原文局部阅读无需被永久绑定为先成课 |
| 实际组件 | DT core/server/Web + books/knowledge/parsing/questions/visualize/mastery；单 worker、Python 引擎、本地文件/SQLite；既有 llamaindex 检索需 embedding |
| 资料/知识 | 原始来源和 accepted wiki/sources 独立；DT KB 为学习投影，外部 Agent 可直接查现有 wiki，正式审批不变 |
| 自有工程 | 稳定 ID/生产回执、学习前只读快照、DT HTTP 读侧与语义映射、不可变结果包；中等适配工作，无第二套可写学习库 |
| 结果语义 | 保留实际答案、原客户端判分、自评/未评分及错误；确定性复核另列，学习结束由用户声明，不推出独立掌握 |
| 版本边界 | 协作冻结 + 内容摘要检测；attempt 无提交时内容 hash，严格历史绑定不成立，不拿当前内容补历史 |
| 工程取舍 | 不造 Agent harness、通用插件平台、新队列/预算平台；不部署六套产品，不先做门户/MCP/长期画像/PBL |

决定性源码更正：BookEngine 自己管理生成队列，平行于聊天 turn；Book 默认书面题是揭示/自评；progress 已写后 assessment 同步失败可返回 500；原生 Markdown export 不是结果导出；revision/fingerprints 不是逐次作答快照；默认 compose 包含额外服务，不能拿注释当最小部署依据。

剩余未知集中为：精确包/Web 组合的运行可用性、所选模型/embedding 兼容、本机资源和生成/教学质量、usage 覆盖。后续先做“一份 MD→一页/一题→追问→重开→JSON 读取”的隔离定点验证；失败可能改变选型，不需要先开发整个适配器。严格自动评估和强历史绑定是已明确后置的能力，不称为已解决。

详细决定、证据与未来验收：

- [D1 学习体验与底座](D1-learning-backend-decision.md)：同情境比较、真实依赖闭包、选型代价及重评条件。
- [D2 数据与交接](D2-data-and-handoff-contract.md)：所有权/接口/版本/失败，一份契约和三个静态例子。
- [D3 首个闭环](D3-first-learning-scope.md)：实际组件、范围、工作量、预算/恢复/备份与后续验收观察。

下一步按 I2 验收报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-review.md）先做离线修订和凭据处置；只补真实页边问答/恢复所需的模型额度须另定，不重置旧预算或重跑整轮。复审前不推进 I3–I6 或旧 S2/S3。