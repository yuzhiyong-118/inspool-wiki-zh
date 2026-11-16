# 框架与设计

本目录保留通用方案和契约；私人实施记录、课程与审查快照不公开。文中状态与验收计数对应原文写作时点的环境，历史验收不能替代当前环境验证。

## 设计文档

- [已审知识候选正式入库：接线任务书](knowledge-candidate-admission-plan.md)
- [K0：知识准备接口与可执行协议核对](knowledge-preparation-k0-contracts.md)
- [知识准备链方案与实施任务书](knowledge-preparation-plan.md)
- [知识整理与学习系统修订方案](knowledge-system-revision-plan.md)
- [知识与学习系统 Token 成本治理设计及任务](knowledge-token-efficiency-plan.md)
- [I3 详细任务书：来源交付与生产回执](learning-book-i3-plan.md)
- [I4 详细任务书：学习前内容基线与核验](learning-book-i4-plan.md)
- [I5 详细任务书：只读学习记录与外部交接](learning-book-i5-plan.md)
- [课程受控扩展与适应性学习修复方案](learning-controlled-extension-plan.md)
- [能力目标驱动的课程内容重构方案](learning-course-authoring-redesign-plan.md)
- [学习驱动的知识入库与分级证据校验方案](learning-gated-ingest-plan.md)
- [课程题目生产、约束绑定与审查方案](learning-question-constraint-plan.md)
- [LLM Wiki 门禁、反馈循环与多 Agent 维护方案](maintenance-plan.md)
- [Wiki 知识层约定：页面规范、图谱关系与入口分工](wiki-layer-conventions.md)

## 上游选型与原始研究

上游学习应用的只读源码审查记录。上游源码副本与研究过程记录不随本仓库发布，引用以[上游来源清单](upstream-sources.md)的固定提交与文件路径定位。

- [上游来源清单：仓库、固定提交与许可](upstream-sources.md)
- [研究方法、证据口径与未公开范围](research/upstream-learning/README.md)
- [源码研究关键发现报告](research/upstream-learning/report.md)
- [从上游 README 与设计原则重新理解架构取舍](research/upstream-learning/upstream-design-rationale.md)
- [学习应用与知识库整体架构方案](research/upstream-learning/architecture-proposal.md)
- [研究验收记录](research/upstream-learning/acceptance-review.md) 与 [返修复审记录](research/upstream-learning/acceptance-review-rework.md)
- [研究交付与当前设计状态](research/upstream-learning/acceptance-request.md)
- 三专题收敛：[D1 学习底座决策](research/upstream-learning/design-convergence/D1-learning-backend-decision.md)、[D2 数据与交接契约](research/upstream-learning/design-convergence/D2-data-and-handoff-contract.md)、[D3 首个闭环与工程边界](research/upstream-learning/design-convergence/D3-first-learning-scope.md)、[收敛结论](research/upstream-learning/design-convergence/design-summary.md)
- 首轮对照：[开源学习应用源码对照与架构选型建议](upstream-learning-architecture-review.md)、[源码研究与架构建议任务手册](upstream-learning-source-research-playbook.md)、[验证约定](upstream-learning-validation-playbook.md)
- Harness 审查：[DeepSeek Harness 审查交接](deepseek-harness-review-handoff.md)、[DeepSeek Harness 候选审查](research/deepseek-harness-review-2026-11-16.md)、[Lattice Agent Harness 源码审查](research/lattice-harness-review-2026-11-16.md)、[四份外部审查产出的复核与取舍](research/lattice-chatgpt-reports-review-2026-11-16.md)

## 实现入口

- [运行时](../../tools/wiki_runtime/README.md)：候选、门禁、审查、执行与恢复。
- [学习集成](../../tools/learning_book/README.md)：资料包、版本绑定、预算、发布与交接。
- [公开发布边界](../PUBLICATION.md)：文件选择、隐私和测试边界。
