---
type: meta
title: 框架与设计
status: active
updated: 2026-11-17
topic: 设计导航入口
related_sources: []
related_synthesis: []
---

# 框架与设计

本目录是本仓库的设计正本：维护规则、通用方案、契约与设计推导都在这里维护一份。私人原文、知识页、课程正文、个人学习记录与运行状态不随本仓库发布。

文中状态与验收计数对应原文写作时点的环境，历史验收不能替代当前环境验证。

## 按问题找文档

| 你的问题 | 从这里开始 |
| --- | --- |
| 门禁怎么拦、角色怎么分、失败怎么恢复 | [维护方案](maintenance-plan.md) |
| 候选、检查、审查、执行与恢复的运行时接口 | [运行时说明](../../tools/wiki_runtime/README.md)、[入口矩阵](../../tools/wiki_runtime/ENTRYPOINTS.md) |
| 知识怎么准备、审校、准入与入库 | [知识准备链方案](knowledge-preparation-plan.md)、[K0 接口契约](knowledge-preparation-k0-contracts.md) |
| 已审知识如何正式入库 | [知识候选准入接线任务书](knowledge-candidate-admission-plan.md) |
| 学习底座选型、数据与交接契约、首个闭环 | [上游研究入口](research/upstream-learning/README.md)、[三专题收敛结论](research/upstream-learning/design-convergence/design-summary.md) |
| 学习底座各阶段的任务书与验收 | [学习实施任务书](learning-book-implementation-tasks.md)、[I3](learning-book-i3-plan.md)、[I4](learning-book-i4-plan.md)、[I5](learning-book-i5-plan.md) |
| 课程怎么按能力目标重构与验收 | [课程内容重构方案](learning-course-authoring-redesign-plan.md)、[候选蓝图](learning-course-authoring-blueprint.md) |
| 题目怎么生成、约束绑定与审查 | [出题约束方案](learning-question-constraint-plan.md)、[实施任务书](learning-question-implementation-tasks.md) |
| 课程受控扩展与块生命周期 | [受控扩展方案](learning-controlled-extension-plan.md)、[评审记录](learning-controlled-extension-review.md) |
| 学习型入库怎么分阶段推进 | [入库改造总方案](learning-gated-ingest-plan.md)、[分期路线图](learning-ingest-stages.md)、[整体审查](learning-ingest-review.md) |
| token 成本怎么归因与治理 | [Token 成本治理设计](knowledge-token-efficiency-plan.md) |
| 知识层页面、关系与图谱怎么写 | [Wiki 知识层约定](wiki-layer-conventions.md) |
| 上游项目选型的依据是什么 | [上游来源清单](upstream-sources.md)、[关键发现报告](research/upstream-learning/report.md) |
| 本次迁移做了什么、哪些没公开 | [迁移摘要](migration-summary.md)、[迁移方案](public-repo-content-backfill-plan.md) |
| 历轮审查发现了什么问题、怎么修的 | [审查发现与修复机制汇总](evidence-findings.md) |
| 十二个迁移批次各做了什么、怎么复核 | [批次交接说明](migration-batches.md) |

## 当前设计

当前仍在生效的方案与契约。历史版本与被替代路线见下方「历史演进」。

### 维护门禁与框架层

- [维护方案：门禁、反馈循环与多 Agent 维护](maintenance-plan.md) — 角色权限、候选与正式库分离、失败处理与恢复、证据链。
- [Wiki 知识层约定](wiki-layer-conventions.md) — 页面规范、关系字段、工作流与状态机、入口职责分层，以及三条历史 ADR 决策。
- [审查发现与修复机制汇总](evidence-findings.md) — 历轮审查中只存在于验收证据目录的问题、原因、修复机制与保留的失败教训。
- [Token 成本治理设计与任务](knowledge-token-efficiency-plan.md) — 固定管线、用量归因、上下文与缓存、对照验收。

### 知识准备、准入与入库

- [知识准备链方案与实施任务书](knowledge-preparation-plan.md) — K0–K4 的接口、任务拆分与验收边界。
- [K0：知识准备接口与可执行协议](knowledge-preparation-k0-contracts.md) — 局部来源投影、失效与并发语义。
- [知识候选正式入库接线任务书](knowledge-candidate-admission-plan.md) — 专用非教学准入如何复用 Runtime 与 Executor。
- [知识整理与学习系统修订方案](knowledge-system-revision-plan.md) — 跨操作任务身份、可信放行、依赖复用与容量修订。
- [知识库重设计审查方案](knowledge-base-redesign-review-plan.md) 与 [审查记录](knowledge-base-redesign-review.md) — 知识库重设计的完整评估与结论。

### 学习底座与数据交接

- [学习实施任务书](learning-book-implementation-tasks.md) — I0–I6 各阶段范围与完成标准。
- [I3 详细任务书：来源交付与生产回执](learning-book-i3-plan.md)
- [I4 详细任务书：学习前内容基线与核验](learning-book-i4-plan.md)
- [I5 详细任务书：只读学习记录与外部交接](learning-book-i5-plan.md)
- [I6 部署与生产学习集成](learning-book-i6-plan.md)
- [学习架构三专题任务手册](learning-architecture-design-tasks.md) — D1 学习底座、D2 数据与交接、D3 首个闭环。

### 课程、出题与受控扩展

- [课程内容重构方案](learning-course-authoring-redesign-plan.md) — 能力目标驱动、多角色分责、G0–G4 门禁与共享预算。
- [课程体验重设计方案](learning-course-experience-redesign-plan.md)
- [课程覆盖审计与候选蓝图](learning-course-authoring-blueprint.md)
- [出题约束方案](learning-question-constraint-plan.md) 与 [实施任务书](learning-question-implementation-tasks.md)
- [课程受控扩展方案](learning-controlled-extension-plan.md) 与 [评审记录](learning-controlled-extension-review.md)

### 学习型入库改造

- [学习驱动的知识入库与分级证据校验方案](learning-gated-ingest-plan.md) — 统一任务运行时、单账本预算、可信审查凭据与知识沉淀。
- [S0 任务书](learning-ingest-s0-plan.md)、[S1 任务书](learning-ingest-s1-plan.md)、[分期路线图](learning-ingest-stages.md)
- [持久循环与受控扩展设计](learning-ingest-runtime-loop.md) — Task Runtime、事件、等待、预算与恢复。

## 研究依据

研究的结论、依据与复核记录。结论可读，但原始证据附件不随本仓库发布。

### 上游学习应用选型

- [研究方法、证据口径与未公开范围](research/upstream-learning/README.md) — 证据定位的三种形态、关键修订与校验方式。
- [上游来源清单](upstream-sources.md) — 各仓库的固定提交、许可与审查限制。
- [源码研究关键发现报告](research/upstream-learning/report.md) — 五条处理链、机制对照、token 成本与选型结论。
- [上游源码级机制结论提取](research/upstream-learning/source-mechanism-findings.md) — 支撑选型结论的源码事实、复用边界的硬约束、接口偏斜与更正记录。
- [从上游 README 与设计原则重新理解架构取舍](research/upstream-learning/upstream-design-rationale.md) — 六项目各自在优化什么、最值得吸收的八项取舍。
- [学习应用与知识库整体架构方案](research/upstream-learning/architecture-proposal.md)
- [研究验收记录](research/upstream-learning/acceptance-review.md) 与 [返修复审记录](research/upstream-learning/acceptance-review-rework.md)
- [研究交付与当前设计状态](research/upstream-learning/acceptance-request.md)
- 三专题：[D1 学习底座决策](research/upstream-learning/design-convergence/D1-learning-backend-decision.md)、[D2 数据与交接契约](research/upstream-learning/design-convergence/D2-data-and-handoff-contract.md)、[D3 首个闭环与工程边界](research/upstream-learning/design-convergence/D3-first-learning-scope.md)、[收敛结论](research/upstream-learning/design-convergence/design-summary.md)

### 上游 Harness 审查

- [DeepSeek Harness 候选审查](research/deepseek-harness-review-2026-11-16.md)
- [Lattice Agent Harness 源码审查](research/lattice-harness-review-2026-11-16.md)
- [四份外部审查产出的复核与取舍](research/lattice-chatgpt-reports-review-2026-11-16.md)
- [DeepSeek Harness 审查交接](deepseek-harness-review-handoff.md)

### 出题与约束参考

- [学习应用出题研究复核](research/learning-agent-question-generation-review.md)
- [出题约束参考复核](research/question-constraint-reference-review.md)

## 历史演进

以下是被替代或已被收敛的路线，保留是为了追溯推理过程。**不要据此重启已停止的工作。**

| 文档 | 现状与后续关系 |
| --- | --- |
| [开源学习应用源码对照与架构选型建议](upstream-learning-architecture-review.md) | 首轮对照；已由[关键发现报告](research/upstream-learning/report.md)取代，保留作线索而非结论 |
| [源码研究与架构建议任务手册](upstream-learning-source-research-playbook.md)、[验证约定](upstream-learning-validation-playbook.md) | 该轮研究的执行约定，已执行完毕 |
| [知识准备链交接](knowledge-preparation-handoff.md) | 当时的续接入口；当前状态以[知识准备链方案](knowledge-preparation-plan.md)为准 |
| [K4 后端到端整合审查](knowledge-preparation-post-k4-review.md) | 修复前的问题与依据，已由后续接线关闭 |
| [知识准备与学习系统端到端复核](knowledge-preparation-integration-review.md) | 设计自查与修订记录，非验收凭据 |
| [知识与学习系统端到端复核](knowledge-system-integration-review.md) | 职责与接口核对，操作矩阵与修订 |
| [知识候选准入交接](knowledge-candidate-admission-handoff.md) | 接线交付的交接记录 |
| [学习底座 I2 探针交接](learning-book-i2-handoff.md)、[I5 目标交接](learning-book-i5-goal-handoff.md) | 阶段交接记录 |
| [学习系统本地收尾方案](learning-book-local-use-closeout-plan.md) | 本地收尾范围与边界 |
| [学习架构收敛交接](learning-architecture-convergence-handoff.md) | D1–D3 专题的交接记录 |
| [后续批次执行与审查交接](learning-system-next-execution-handoff.md) | 当时的分批范围与交回材料约定 |
| [学习型入库改造交接](learning-ingest-handoff.md) | 改造交接；当前以[总方案](learning-gated-ingest-plan.md)为准 |
| [入库改造 v0.6 审查交接](learning-ingest-v06-review-handoff.md)、[v0.7 审查交接](learning-ingest-v07-review-handoff.md) | 历史版本审查记录 |
| [课件消费架构早期讨论交接](course-consumer-architecture-handoff.md) | 早期讨论；不再作为选型入口 |
| [2026-10 设计评估](archive/2026-10/design-review.md) 与 [任务总表](archive/2026-10/development-tasks.md) | 当时的提案、任务与未通过记录；其中 T00–T11 拆分已被后来的 S0–S5 分期取代 |

## 操作说明

- [运行时](../../tools/wiki_runtime/README.md)：候选、检查、审查、执行与恢复。
- [学习集成](../../tools/learning_book/README.md)：资料包、版本绑定、预算、发布与交接。
- [上游补丁](../../patches/deeptutor/README.md)：适配特定上游版本的补丁，不是已部署服务。
- [公开发布边界](../PUBLICATION.md)、[迁移说明](../MIGRATION.md)、[验证记录](../VALIDATION.md)。
- [迁移摘要](migration-summary.md)：本次迁移的主题、处理类别与未公开范围。
- [批次交接说明](migration-batches.md)：十二个批次各做了什么、合并规则、复核路径与需要重点看的地方。
- [迁移方案](public-repo-content-backfill-plan.md)：单一设计正本的执行方案与阶段划分。
