---
type: meta
title: 学习型知识库 v0.6 外部审查交接
track: decision
status: superseded
date: 2026-11-02
updated: 2026-11-02
topic: 架构复审交接
superseded_by: learning-ingest-v07-review-handoff.md
---

# 学习型知识库 v0.6 外部审查交接

> 本文件保留历史审查快照。当前设计已演进为 [v0.7 外部审查交接](learning-ingest-v07-review-handoff.md)，后续审查以新版为准。

## 1. 审查目的

本文件用于把本轮设计迭代交接给未参与修订的 Agent 做独立审查。审查目标不是继续增加机制，而是判断 v0.6 是否满足原始业务需求、是否与真实代码兼容、是否形成可执行和可验收的完整闭环。

本轮只审查设计。不要把尚未实现本身报告为缺陷，不要修改 AGENTS、公共契约 v1、运行时代码或真实 raw，不要运行正式知识入库，不要以删减已明确要求的能力作为修正方案。

## 2. 必读材料与顺序

项目根目录：`<知识库根目录>`。

1. [AGENTS.md](../../AGENTS.md)：现行维护规则，业务规则正本。
2. [总体方案 v0.6](learning-gated-ingest-plan.md)：当前设计主文档。
3. [S0–S5 路线图](learning-ingest-stages.md)：阶段责任、验收和停止条件。
4. [S0 详细任务书](learning-ingest-s0-plan.md)：当前阶段的实体、接口、任务依赖、锁协议和验证矩阵。
5. [审查记录](learning-ingest-review.md)：历史问题、修订及复审证据，最新内容见第 9–13 节。
6. [项目交接快照](learning-ingest-handoff.md)：当前实施状态与授权边界。
7. 实际代码：`tools/wiki_runtime/host/`、`coordinator/`、`executor/`、`candidate/`、`review/`、`contracts/`。

重点代码：

- `tools/wiki_runtime/host/supervisor.py`
- `tools/wiki_runtime/host/approval.py`
- `tools/wiki_runtime/coordinator/loop.py`
- `tools/wiki_runtime/executor/core.py`
- `tools/wiki_runtime/candidate/view.py`
- `tools/wiki_runtime/review/content.py`

需要沿实际调用链继续阅读，不能只凭组件名称推断能力。

## 3. 版本演变摘要

| 版本 | 主要变化 | 当前意义 |
| --- | --- | --- |
| v0.2 | 先教后验、来源路由、T／S／I／P／C 分类、冲突处理、学习与入库分离 | 原始业务设计基础 |
| v0.3 | 增加最终 diff 全覆盖 B1；补证提升、长期预算、两类失效、角色认证和输入能力 I1–I5 | B1 已在设计层关闭，仍待实现验证 |
| v0.4 | 知识版本与最终事务分离；三个贯穿样例；四模块；判分校准；用户成本观察 | 优化目标保留 |
| v0.5 | 外部草案曾尝试收敛运行器、状态、证据和授权；多轮审查发现 Coordinator 能力误判、授权循环、Evidence 输入及状态混用等问题 | 不作为项目内独立权威版本；有效修订已并入 v0.6 |
| v0.6 | 重新明确 Durable Task Runtime、统一授权语义、Executor 独立事务和 Knowledge Evidence 子系统 | 外部审查 `passed_with_residual`；允许开始 S0，残余项待实际验收 |

## 4. 不可削弱的业务与安全不变量

1. 新资料默认经过证据核验、课程、练习、讨论／补讲和独立理解验收，用户确认后才应用正式 Wiki。
2. 知识可信与用户理解是不同属性，但数据模型解耦不能成为免学习入库路径。
3. ingest 与 approve 是不同业务操作，各自拥有独立 operation、candidate、manifest、snapshot 和 Executor Transaction。
4. 最终 diff 的每项语义变更必须有证据处置和教学处置；未映射项拒绝。
5. 必过及复用目标需要有效独立理解证据；可选拓展和非教学处置不伪造 Assessment。
6. 来源演进和判分校准属于完整能力目标。
7. 学习记录可以按依赖局部失效；正式事务按 CandidateView／Executor 的严格依赖规则整体重建。
8. 混合冲突批次不能通过局部拆分绕过整组 raw 应用边界。
9. 应用前撤销、应用后补偿性撤回和归档后修正必须区分。
10. raw 正文只读；历史 pending_review／processed 不回退、不补造学习记录。
11. 公共契约 v1 当前保持冻结；不因新设计临时向 manifest、G3 或 ApprovalStore context 塞字段。
12. 采用已接受的协作门禁，不重新开展完整 OS／工具隔离。

## 5. v0.6 总体架构

```text
Host
├── Durable Task Runtime
│   └── Learning Task / Run 关联 / 共享预算 / 租约与 fencing / 状态事件
├── Authorization
│   ├── ingest：Host 业务授权
│   └── approve：ApprovalStore / ApprovalHandle / G4
└── Execution Integration
    ├── 最终候选 / Coverage / Readiness / 授权关联
    ├── Coordinator：单次 Run、局部预算、deadline、候选检查
    └── Executor：最终复验 / 正式事务 / WAL / 独立恢复

Knowledge Evidence
└── Source / 持久原文 / Evidence / Evidence–Claim Relation / Claim
    └── 核验 / 冲突 / 版本 / 依赖传播

Knowledge Output
└── Lesson / Article / VideoScript / 其他输出适配器

Learning & Assessment
└── Objective / Tutor / Rubric / Assessment / Calibration
```

这些都是逻辑职责和数据所有权边界，不是要求新增服务或数据库。代码目录按子系统划分，阶段任务书和合成夹具按阶段命名；不按 S0／S1 等阶段复制共享状态、协议或运行时。

### 5.1 Durable Task Runtime

由 Host 扩展长期持久化能力。现有 Coordinator 只管理单 Run 的 `max_calls`、`max_seconds`、deadline 和 Run 状态，不能被描述为已经具备跨会话总账本。

Durable Task Runtime 不负责教学语义、证据裁决或 Wiki 写入；Executor 不负责长期学习状态。

### 5.2 Knowledge Evidence

Source、Evidence、Claim 是不同实体。Evidence 与 Claim 多对多，`supports／contradicts／qualifies` 位于 Evidence–Claim 关系记录，而不是 Evidence 自身。

Evidence metadata 不能代替 G3 实际读取原文。当前 `input_refs` 是库根相对、严格 UTF-8、进入依赖快照并绑定内容哈希的原文路径，不是 Evidence ID 或 URL。

### 5.3 Knowledge Output

Knowledge Output 消费版本化知识和证据快照，通过适配器生成 Lesson、Article、VideoScript 等输出。课程是学习流程中的一种输出；文章和视频不强制经过学习门禁。输出新增事实或改变结论时必须返回 Knowledge Evidence，公开发布另有独立授权。

### 5.4 Learning & Assessment

Objective 声明目标类型、所需证据、rubric 和通过条件。概念、机制、程序性、迁移和综合推理目标不能互相替代验收证据。

Assessment 绑定实际 rubric_template、本课 rubric 与 evaluator 版本；模板校准绑定 suite、rubric_template、evaluator 和适用 objective_type，本课 rubric 的正确性另经独立证据审查。旧 Assessment 不能与修复后的新校准凭据拼接放行。

## 6. 关键协议

### 6.1 双层预算

Host 提供组合预算入口，覆盖 Worker、Reviewer、RuleAuditor、工具调用及 Coordinator／Executor 两侧 G3。

当前设计顺序：

1. 验证任务租约与 invocation 唯一性。
2. Coordinator 在外部调用前持久扣减 Run 额度并保存 invocation 回执。
3. Host 以条件写入预留任务级额度并保存回执。
4. 两层均成功才发起外部调用。

Host 拒绝时，已扣 Run 额度按失败尝试保守计入；不得在外部调用后才更新 Coordinator。相同 invocation_id 的重放读取原回执，不重复调用或扣减，不同实际尝试使用不同 ID。S0 必须覆盖“Run 已扣、Host 尚未预留便崩溃”的对账。

### 6.2 Readiness 与授权

```text
最终 Candidate / Manifest / Snapshot
    ↓
L3 生成不可变 Readiness 与 readiness_digest，不包含用户授权
    ↓
用户授权绑定 action、operation_id、candidate_digest、
             readiness_digest、dependencies_digest 和规则版本
    ↓
Host 读取并认证 pending 完整性／身份，不在此时检查 deadline 或 provenance 新鲜度
    ↓
Executor 短锁 lookup_terminal；身份一致的终态直接返回，不新增审查或扣费
    ↓
仅非终态执行 Host 授权、deadline、provenance 预检，随后释放 Host 线程锁
    ↓
锁外执行 Executor G3
    ↓
最终锁内复验依赖、版本、Readiness、授权和 fencing
    ↓
首个完整 WAL：事务接受
```

统一授权字段属于 Host 私有审计语义，不直接进入封闭 ApprovalStore context。approve 通过 `approval context_digest ↔ learning_task_id／raw_batch_id／ingest execution_result` 的私有映射关联；`consumed` 由 Executor 已应用结果派生。

一条组合指令只记录处理意图，不提前签发未来 approve 的真实凭据。实际 ingest 应用报告和 approve context 生成后，owner 仍独立确认。

### 6.3 fencing、原子接受与 Executor 恢复

- 租约包含 lease_owner、单调递增 lease_generation 和到期时间。
- 领取、续租、释放均原子完成；续租和释放匹配 task、owner、generation。
- 业务结果采用条件原子提交，不能先检查、后写入而留下竞态。
- Host 私有 pending 操作绑定 learning_task_id 和创建时 generation，不修改公共 v1 manifest。
- Host 预检不是最终准入。Executor 在 G3 后、首个 WAL 前重验 Readiness、授权撤销、版本和 fencing。
- 撤销、失效和换代须与最终准入处于同一跨进程串行化边界，或由持久层条件接受阻止旧状态写入。
- 首个完整 WAL 是唯一接受标志；接受前拦截，接受后由 Executor 独立完成或恢复。
- Executor 回滚后的 recovered 不归并为 applied；保留有效学习证据，重新应用使用新 operation 并重新核验当前候选与授权。

### 6.4 判分校准与 L2

- 固定案例和 holdout 在调试前确定。
- holdout 一旦用于修改 rubric、提示词、规则或 evaluator，即失去 holdout 资格。
- 重复判分次数、输入和配置预先固定；不得选择性重跑或靠多数票消除不一致。
- 核心目标误放行、提示复述冒充独立掌握、证据类型错误替代、关键条件缺失仍通过、不一致未裁决，以及版本变化后沿用旧 Assessment，均阻断 L2。
- 区分可复用 rubric_template 与本课内容 rubric；校准绑定模板、evaluator 和 objective_type，本课答案仍须独立证据审查。
- 小样本只证明固定测试集表现，不声称总体准确率。

## 7. 本轮审查与修订结果

内部独立审查发现的三项组合授权、ApprovalStore 映射和历史凭据表述问题已修复并定点复核通过，见[审查记录](learning-ingest-review.md) 第 9 节。

后续另一名外部 Agent 与只读 SubAgent 的结论为 **`passed_with_residual`**：总体可行，可以开始 S0，无需推翻整体架构。原子接受点是 S0 必须关闭的重要协议缺口；预算回执、回滚归并和校准模板复用同时纳入 S0。详见审查记录第 10 节。

S0 至少验证：G3 期间撤销或换代不产生新 WAL；接受点附近崩溃能唯一判断接受状态；同一 invocation 重放不重复扣费；Executor 回滚不误标 applied；不同课程复用校准具有适用依据和失效条件。

该结论不代表 S0 已实施、真实宿主闭环已运行或教学效果已验证。

## 8. 已执行的确定性检查

- 只读 `python -B tools/health.py --json`：退出码 0，八项检查零问题。
- 五份设计文档的 59 处本地文件链接及标题锚点：缺失 0。
- `git diff --check`：通过。
- 未运行新业务流程或历史全套测试。
- 未修改 AGENTS、公共契约、运行时代码、raw 或正式 Wiki；未提交／推送。

## 9. 请独立审查的重点问题

1. 四项架构决策是否足以消除职责重叠，还是引入了新的总控或状态分裂？
2. Host／Coordinator 双层预算的顺序、崩溃结算和幂等协议是否完整？
3. Readiness 不含授权、授权绑定 readiness_digest 是否彻底消除循环绑定？
4. ingest Host 授权与 approve ApprovalStore／G4 的分工是否保留各自安全边界？
5. Evidence、持久原文和 G3 input_refs 的映射是否符合当前实现？
6. fencing 的条件提交、pending 代次绑定、Executor 锁内准入及 WAL 恢复是否形成闭环？
7. 学习记录局部失效与 Executor 事务整体失效是否仍有冲突？
8. 判分校准的适用范围、版本绑定和 L2 阻断是否可被绕过？
9. 最终 diff 全覆盖是否仍允许合法的可选拓展和非教学处置？
10. 三个贯穿样例是否足以覆盖正常、外部纠错和跨会话并发恢复？

请区分事实、推断和设计建议。每项发现给出原文位置、实际代码证据、影响、合理替代解释、最小修正和验收方式。

## 10. 期望审查输出

- 总体结论：`passed／failed／blocked／passed_with_residual`。
- 阻断问题、重要改进和可选优化分别列出。
- 明确哪些旧问题已关闭，哪些仍未闭合。
- 标明未运行、未实现和无法确认的范围。
- 不修改文件；将审查意见返回给主 Agent 汇总。


## Related

- [v0.7 外部审查交接](learning-ingest-v07-review-handoff.md)：本文件的后续版本。
