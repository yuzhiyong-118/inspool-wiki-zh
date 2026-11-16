---
type: meta
title: 研究交付与当前设计状态
status: research_delivered
updated: 2026-11-09
topic: 研究交付物与设计状态
related_sources: []
related_synthesis: []
---

# 研究交付与当前设计状态

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

更新：2026-11-10。主 Agent 根据用户“简单问题直接修订、重点看整体架构”的指示，已直接完成本轮文档校正与整体方案收敛。

**后续执行进度**：[实施任务书](../../learning-book-implementation-tasks.md)已编写；I0/I1 已完成固定源码的隔离安装、无模型 API/Web/浏览器空书库和重启读取，见 前置验证（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-preflight/README.md）。I2 待模型/embedding/预算配置，未开发 I3–I6 适配器，服务已停止。下文“本次未安装/启动”描述设计收敛当时，不覆盖后续执行。

**当前状态：D1–D3 已完成静态设计和关键源码复核，推荐 DeepTutor Book，数据交接与首个闭环范围已收敛。** 见 [收敛结论](design-convergence/design-summary.md)。推荐覆盖阅读、页边追问、单答案选择题、恢复和结果交接；历史内容绑定仅协作级，书面题自评不当模型批改。运行质量、部署及教学效果尚未验证；本次没有实施产品、安装依赖、启动服务、调用模型或推进旧阶段。下一步另写有限实施任务书，不把静态设计完成当产品验收通过。

## 当前入口

- [整体架构方案](architecture-proposal.md)：当前唯一的总体建议入口，已重写职责、证据、预算及扩展边界。
- [三专题收敛结论](design-convergence/design-summary.md)：当前完成产物入口，链接 D1 选择、D2 契约与三例、D3 范围/成本/未来验收观察。
- [设计收敛任务手册](../../learning-architecture-design-tasks.md)：已完成专题的原要求与完成标准，不再是待执行清单。
- [上游设计动机与架构启发](upstream-design-rationale.md)：重读六仓 README、设计原则与 ADR 后的补充；产品目标、作者取舍、我们能吸收的八项原则分开说明。OpenMAIC 的推荐限定于当前固定课件路线，DeepTutor 的交互书与模块化入口不再被错误排除。
- [源码报告](report.md)：六仓机制与研究发现，当前结论见其 §3.3、§8。
- 源码证据（证据未公开，无法由本仓库独立复核：docs/design/research/upstream-learning/source-evidence.json）：857 条；主 Agent 补充与校正源（研究过程记录未随仓库发布：docs/design/research/upstream-learning/_notes/main-agent-evidence.json）。
- [首次审核](acceptance-review.md)、[返修复审](acceptance-review-rework.md)：保留历史发现，不把其中已关闭事项重复当作当前阻断。

## R1–R8 与 N1–N5 的关闭方式

下表记录先前 OpenMAIC 候选中的问题如何修正；表中的组件与“本期”均属当时候选范围，不是当前 DeepTutor 选型。当前数据责任、接口和覆盖已按 D1–D3 合并。

| 项 | 当前处理 |
| --- | --- |
| R1 部署/SDK | 完整采用应用与原生 PG；自己的适配工作按职责计价，不再声称两个 SDK 提供全部产品 |
| R2 教学对话 | 复用上游已接线的 Director；评分与教学分开 |
| R3 状态真值 | 唯一业务写入方为上游应用，内部区分 quiz/chat RuntimeStore 与 PBL 领域事务，不增第二套学习库 |
| R4 选型 | 本地部署不限制数据库；目录不是硬约束；完整产品先用，未来按实际接口替换 UI/服务 |
| R5 用户链 | 暂存→显式整理→查知识→分流→学习→外部整理候选→既有 ingest/approve |
| R6 证据 | 使用真实 locations/搜索结构；主 Agent 校正以独立 JSON 覆盖源保留，重建不丢失 |
| R7 检索 | 不宣称未引入能力已覆盖；当前先维护来源、内容身份及精确度限制，检索按使用问题后加 |
| R8 移植成本 | 不移植 DeepTutor 整域；纯算法借鉴也计入数据适配，不能把 policy 文件说成零依赖 |
| N1 评分异常 | 按题标 deterministic/model/fallback/missing/unknown；混合题型允许 partial，不把基础分当模型 verdict |
| N2 内容版本 | 学习前固定实际内容和来源；当前 rev 只用于变化检测；历史内容绑定缺失或变化则 unknown |
| N3 PBL/范围 | 本期保证 slide+quiz+对话；interactive 为 partial；PBL 默认不生产且交接 unsupported；未来单独扩展 |
| N4 辅助 | 有关联对话只代表迹象；缺记录默认 unknown；独立作答需明确证据或声明 |
| N5 表述 | HTTP 回合不等于一次模型调用；缺 publishConfig 不推出未发布；policy 的数据依赖说明已修正 |

## 整体优化已落入设计

1. 原始资料在本地独立保存，sourceId/hash 不依赖应用的 materialId，知识库能脱离学习产品演进。
2. 生产回执、学习前快照、原始学习事实和派生判断分开，避免后期靠模型总结补历史。
3. 用契约、所选 DT 后端适配、应用操作、校验组装四个普通模块隔离变化，不建通用插件平台。
4. 按类型声明覆盖和错误语义，保留 partial/unknown；以后 PBL/检索/掌握度都是明确扩展，不挤进当前最小闭环。
5. 复用已有持久 run、局部重试、按需取证与用量日志；补固定版本、备份范围、升级兼容与导出一致性。

## 证据与复核方式

当前项目分布：DeepTutor 285, OpenMAIC 272, kotaemon 80, lattice 94, open-notebook 87, open-notebook-mcp 39。

重建：`python -I docs/design/research/upstream-learning/_notes/build_evidence_v2.py`。生成器会应用 `main-agent-evidence.json` 的校正，历史笔记保留。

本轮复核限定为文件定位/行号/提交/引用、关键调用链及设计与源码对应，不把静态推断当运行证明。新职责、快照、交接 schema、覆盖规则属于待实现的项目设计，上游没有被宣称已具备它们。

## 后续边界

三个专题已保存到 `design-convergence/`，总体方案/索引/交接已同步。新增发现包括 BookEngine 独立生成、Book 客户端判分/自评、Progress 与 assessment 非原子、原生 export 只有书内容、默认 compose 与最小单 worker 配置的差异。没有增加重复学习库来掩盖这些边界。下一步另写首个闭环的实施任务书，先在隔离环境验证会改变推荐的模块/Web/模型/恢复未知，不要求运行全部参考产品，不自动沿用旧 S2/S3 实施单。