---
type: meta
title: 学习型知识库 v0.7 外部审查交接
track: decision
status: proposed
date: 2026-11-02
updated: 2026-11-02
topic: 架构复审交接
---

# 学习型知识库 v0.7 外部审查交接

> 2026-11-06 更新指针：本文以下内容保留当时的审查基线；当前运行时已在[持久循环与受控扩展设计](learning-ingest-runtime-loop.md)及[S1 任务书](learning-ingest-s1-plan.md)调整为 SQLite、持久事件／Step／Wait 和统一执行路径。请先读[最新交接](learning-ingest-handoff.md)及审查记录最新一节，不依据本历史说明实施旧 JSON／双模式方案。S0 新增协议尚未实施，历史通过不覆盖本次变化。

## 1. 审查目的

本文件用于让未参与修订的 Agent 审查 v0.7。重点不是继续增加机制，而是判断统一 Task Runtime、单账本预算、KnowledgePackage、可信审查复用和新阶段路线是否减少状态协调，同时不削弱学习、证据、授权和正式事务边界。

本轮只审查设计，不修改 AGENTS、公共契约 v1、运行时代码或真实 raw，不运行正式知识入库，不以删减完整能力作为修正方案。

## 2. 必读材料

项目根目录：`<知识库根目录>`。

1. [AGENTS.md](../../AGENTS.md)：现行规则正本。
2. [总体方案 v0.7](learning-gated-ingest-plan.md)：当前设计主文档。
3. [S0–S5 路线图](learning-ingest-stages.md)：新阶段责任和验收。
4. [S0 详细任务书](learning-ingest-s0-plan.md)：实体、接口、协议与场景。
5. [审查记录](learning-ingest-review.md)：历史问题和复审证据；v0.6 及更早结论不自动覆盖 v0.7。
6. [项目交接](learning-ingest-handoff.md)：当前状态与授权边界。

实际代码重点：

- `tools/wiki_runtime/host/supervisor.py`
- `tools/wiki_runtime/host/approval.py`
- `tools/wiki_runtime/coordinator/loop.py`
- `tools/wiki_runtime/executor/core.py`
- `tools/wiki_runtime/candidate/view.py`
- `tools/wiki_runtime/review/content.py`
- `tools/wiki_runtime/contracts/`

沿真实调用链核对，不按组件名称推断能力。

## 3. v0.7 相对旧版的主要变化

1. Task Runtime 统一 Task、Run、Invocation、预算、授权、等待、暂停恢复和结果登记。
2. Host 只承担交互、工具和身份接入，不再逐渐成为业务总控。
3. Coordinator 的候选生成、修复和检查工作循环可复用为 Run Execution Driver，但不再拥有独立权威预算。
4. 一条 Invocation 在一次原子操作中检查 Task、Run、并发和最终留额，取消双层权威账本。
5. KnowledgePackage 成为证据、输出、学习和 Wiki 候选共享的稳定版本化产物。
6. ReviewCredential 只有在独立身份、完整绑定和适用范围有效时才允许复用；否则保留 Executor 独立重审。
7. 首个完整 WAL 同时记录事务接受和完整写入意图，不另建接受记录。
8. S0–S5 重排为实体与场景、统一运行时、最小知识链、学习验收、来源与输出扩展、真实小批次验证。

## 4. 不可削弱的业务不变量

1. 新资料默认经过证据核验、课程、练习、讨论／补讲和独立理解验收，用户确认后才正式入库。
2. 知识与学习状态解耦不能形成免学习正式入库旁路。
3. ingest 与 approve 使用不同 operation、Candidate、Snapshot 和 Executor Transaction。
4. 最终 diff 每项语义变更都有证据处置和教学处置；未映射项拒绝。
5. 必过及复用目标需要有效独立理解证据；可选拓展和非教学处置不伪造 Assessment。
6. 来源演进、判分校准和其他输出类型属于完整能力目标。
7. 学习记录局部失效；正式事务按完整依赖严格重建。
8. 混合冲突不得拆组绕过整组 raw 应用边界。
9. 应用前撤销、应用后补偿和归档后修正必须区分。
10. raw 正文只读；历史 pending_review／processed 不回退、不补造学习记录。
11. 公共契约 v1 当前保持冻结。
12. 采用协作门禁，不重新开展完整 OS／工具隔离。

## 5. 模块与目录边界

```text
Task Runtime
└── Task / Run / Invocation / 预算 / 授权 / 等待恢复 / 结果登记

Host
└── 交互 / 工具 / 身份与权限入口

Knowledge Evidence
└── Source / Evidence / Claim / Conflict / KnowledgePackage

Knowledge Output
└── Lesson / Article / VideoScript / OutputArtifact

Learning & Assessment
└── Objective / Tutor / Rubric / Assessment / Calibration

Knowledge Persistence
└── Wiki Candidate / Coverage / 图谱关系 / Readiness 输入

Run Execution Driver（复用现有 Coordinator 工作循环）
└── 候选生成 / 修复 / 检查，不拥有独立权威预算

Executor
└── 最终复验 / 原子接受 / 完整 WAL / 文件应用 / 回滚与独立恢复
```

代码目录对应为 `runtime/`、`host/`、`coordinator/`、`executor/`、`candidate/`、`contracts/`、`evidence/`、`learning/`、`output/`、`persistence/`、`review/`。任务书和合成夹具按阶段命名，不按阶段复制协议、实体或存储。

## 6. 核心协议

### 6.1 单账本 Invocation

一条记录包含 invocation_id、task／run／operation、spec_digest、限制检查、预留、发送、结果和结算。Task 总额度、Run 上限、并发额度和最终验证留额在同一次原子操作中检查并预留。

相同 ID 不同输入或跨任务调用拒绝；重放读取原记录，不重复调用或扣费；unknown 不重发、不退款；新实际尝试使用新 ID。崩溃后从同一记录恢复，不需要双层账本对账。

### 6.2 KnowledgePackage

至少包含主张及适用条件、支持／反驳／限定证据、原文定位、版本与可读范围、已解决和未解决冲突、与已有知识的关系，以及知识包版本和摘要。

课程、文章、视频和 Wiki 候选引用同一知识包版本。输出新增事实、改变结论或扩大范围时提交新的知识修订请求，不直接修改原包。

### 6.3 ReviewCredential

审查记录绑定冻结输入、产物、证据、规则、提示词、验证器、审查配置、角色和适用范围。Task Runtime 认证独立调用和绑定，独立角色负责语义判断。

只有所有绑定仍有效且适用范围相同才复用；任何相关变化使相关记录失效。可信身份或绑定未实现时，不能凭 Coordinator 自带报告或摘要匹配取消 Executor 独立审查。

### 6.4 Readiness、授权、接受与恢复

```text
冻结 Candidate / Manifest / Snapshot
    ↓
必要审查与学习验收
    ↓
不可变 Readiness / readiness_digest，不包含授权
    ↓
用户授权当前 action / operation / Candidate / Readiness / 依赖 / 规则
    ↓
Executor 检查授权、Readiness、依赖和执行所有权
    ↓
原子保存首个完整 WAL，包含接受与完整写入意图
    ↓
文件应用或独立恢复
    ↓
Task Runtime 按实际结果归并
```

Executor 在新审查或预算消耗前提供 `lookup_terminal`，身份一致的 applied／recovered 直接返回历史结果。只有非终态才继续预检。

接受前完成撤销、Readiness 失效或换代必须阻止旧操作；接受后由 Executor 独立完成或恢复。recovered 不归并为 applied；重新应用使用新 operation、新 Readiness 和新授权。

## 7. 新阶段验收边界

| 阶段 | 当前阶段实际验收 |
| --- | --- |
| S0 | 可解析协议、合成记录、模块接口、场景及阶段归属 |
| S1 | 统一运行时、单账本、真实锁、授权、原子接受、重放和文件恢复 |
| S2 | 最小证据链、KnowledgePackage、外部纠错和 Wiki 候选 |
| S3 | 课程、学习反馈、独立理解验收及必需的判分校准 |
| S4 | 来源演进、扩展校准和其他输出类型 |
| S5 | 真实小批次的正确性、用户负担、成本、正式入库和恢复 |

每阶段只验收本阶段已实现能力；完整业务要求持续保留，到依赖齐备时验收。独立验收用于 L2 放行前，必需判分校准必须在 S3 完成，不能推迟到 S4。

## 8. 请重点审查的问题

1. Task Runtime 统一后，Host、Coordinator、Executor 是否还存在重复权威状态？
2. 单条 Invocation 是否足以表达所有预算限制、发送状态、崩溃、重放和结算？
3. KnowledgePackage 是否足以支撑证据、输出、学习和 Wiki 候选，而不形成新的巨型对象？
4. ReviewCredential 的信任条件是否足以防止生成者自签或不当复用？
5. Readiness、授权、完整 WAL 和结果归并是否仍有循环或第二份事实？
6. 现有 Coordinator 工作循环和 Executor 哪些可直接复用，哪些需要适配或重构？
7. 新阶段是否消除了 S0 与后续业务的验收倒挂，同时保留全部原始要求？
8. 输出扩展是否不会绕开证据核验、学习门禁、发布授权或正式入库？
9. 三个贯穿场景是否仍使用同一套运行时、预算、知识包和授权协议？
10. 是否出现为了统一而合并本应独立的证据审查、学习验收或文件事务职责？

请区分事实、推断和设计建议。每项发现给出文档与代码位置、影响、合理替代解释、最小修正和验收方式。

## 9. 期望输出

- 总体结论：`passed／failed／blocked／passed_with_residual`。
- 分别列出阻断问题、重要改进和可选优化。
- 明确旧问题哪些已关闭、哪些仍未闭合。
- 标明未实现、未运行和无法确认的范围。
- 不修改文件，将审查意见返回主 Agent 汇总。


## 10. 本轮独立审查结果

未参与修订的独立审查者初审发现八项接口／阶段缺口：旧 Host／Coordinator 权威残留、缺少统一 InvocationPort、缺少 Admission／acceptance_check、S2 依赖未来学习产物、conflict 公共状态不兼容、旧阶段归属、必需校准推迟、S1 缺少真实身份负向门禁。

八项均已修订，并由同一独立审查者定点复核为 **passed**。完整证据见[审查记录](learning-ingest-review.md) 第 14 节。

该结论仅表示 v0.7 及 S0 任务书通过本轮设计审查，不代表任何阶段已实现或运行验收。后续继续审查时以当前文档和实际代码为准。
