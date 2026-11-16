---
type: meta
title: 学习型知识库 S0 详细任务书
status: proposed
updated: 2026-11-02
topic: 实体、模块接口、状态所有权与贯穿场景
---

# 学习型知识库 S0 详细任务书

> 2026-11-07 状态说明：本文保留已完成 S0 的历史基线及验收范围，不以新架构覆盖旧记录。Event／Step／Wait／WorkItem／StepResult／WorkflowRef 和 RuntimeTask／LearningState 分离的协议增量已作为 S1 Task 0 独立验收，见[审查记录](learning-ingest-review.md) §23；真实持久循环与运行时仍属 S1 后续任务，历史 59 项测试不证明这些增量通过。

## Goal

将 v0.7 转换为一套可解析、可审查、可用合成样例验证的协议：统一 Task Runtime、单账本 Invocation、KnowledgePackage、ReviewCredential、Readiness、Authorization、Executor Transaction，以及各业务模块的稳定接口。

S0 只完成实体、接口、状态所有权、协议校验和场景定义。真实运行时、Executor 改造、来源业务、课程学习和真实入库分别属于 S1–S5，不得提前冒充完成。

Spec: [学习驱动的知识入库与分级证据校验方案 v0.7](learning-gated-ingest-plan.md)

路线：[S0–S5 路线图](learning-ingest-stages.md)。审查依据：[审查记录](learning-ingest-review.md) 最新一节。

## Architecture

```text
Task Runtime
├── Task / Run / Invocation
├── 单一权威预算账本
├── 执行所有权 / 等待 / 暂停恢复
├── Authorization / Readiness / ReviewCredential
└── 结果登记与恢复协调

Host
└── 用户交互 / 工具接入 / 身份与权限入口

Knowledge Evidence
└── Source / Evidence / Claim / Conflict / KnowledgePackage

Knowledge Output
└── Lesson / Article / VideoScript / OutputArtifact

Learning & Assessment
└── Objective / Tutor / Rubric / Assessment / Calibration

Knowledge Persistence
└── Wiki Candidate / Coverage / 图谱关系 / Readiness 输入

Run Execution Driver（复用现有 Coordinator 工作循环）
└── Run 内候选生成 / 修复 / 检查，不拥有独立权威预算

Executor（现有）
└── 最终复验 / 原子接受 / 完整 WAL / 文件应用 / 回滚与独立恢复
```

这些是逻辑模块与数据所有权边界，不要求拆成独立服务。代码按子系统分目录，任务和合成夹具按阶段命名；不按阶段复制协议或状态。

## Tech Stack

- Python 现有运行时和标准库。
- 项目现有 `contracts` 摘要与路径校验、`unittest`、临时目录和合成 JSON。
- 不新增数据库、服务、包依赖或模型 API。
- S0 不需要真实模型、真实 raw 或正式 Wiki；真实宿主和 Executor 行为留到 S1 及以后验证。

## Global Constraints

1. 新资料默认经过核验、教学、练习和独立理解验收，用户确认后才正式入库。
2. 知识与学习状态解耦不能形成免学习的正式入库旁路。
3. ingest 与 approve 是不同 operation 和事务；组合指令不提前签发未来 approve 凭据。
4. 公共契约 v1 的 manifest、Candidate、Snapshot、G3 request 和 ApprovalStore context 保持封闭。
5. Task Runtime 是 Task／Run／Invocation、预算、授权和结果登记的唯一协调权威；Host 不另建业务总控。
6. 一条 Invocation 在一次原子操作中检查 Task、Run、并发和最终验证留额，不使用两个权威账本。
7. KnowledgePackage 是证据、输出、学习和 Wiki 候选共享的稳定版本化产物。
8. ReviewCredential 只有在独立身份、完整绑定和适用范围有效时才可复用；摘要匹配不证明语义正确。
9. Readiness 不包含授权；授权绑定 readiness_digest。
10. 首个完整 WAL 同时记录接受与完整写入意图；已接受事务由 Executor 独立完成或恢复。
11. 学习记录局部失效，正式事务按完整依赖严格重建。
12. 可选拓展和非教学处置不伪造 Assessment；混合冲突不得拆组绕过。
13. 不处理真实 raw，不修改 AGENTS，不运行正式知识入库，不恢复完整 OS／工具隔离。

## Plan-stage Decisions

- **D1：统一运行时。** Task Runtime 统一流程推进、Agent 调用、预算、授权、等待、暂停恢复和结果登记。
- **D2：Run 是执行记录。** Run 保留局部限制和执行历史，但不拥有独立权威账本；现有 Coordinator 工作循环作为 Run Execution Driver 复用。
- **D3：一条调用记录。** Invocation 同时保存任务／Run／operation、spec_digest、预留、发送、结果和结算状态。
- **D4：知识包跨模块复用。** 输出或 Wiki 映射新增事实、改变结论或扩大范围时，提交新的知识修订请求。
- **D5：审查复用有信任前置。** 可信身份和完整绑定不具备时，保留 Executor 独立重审。
- **D6：接受与写入意图同一事实。** 不另建 accepted=true 或第二份需要协调的接受记录。
- **D7：S0 只验证协议。** 后续业务场景保留要求和归属，不参与 S0 完成判定。

## Review Focus

1. Task Runtime、Host、Run Execution Driver 和 Executor 是否仍有重复权威状态。
2. 单条 Invocation 是否能表达所有预算限制、崩溃状态、重放和结算，而不需双层对账。
3. KnowledgePackage 是否覆盖主张、证据、冲突、版本、可读范围和既有知识关系。
4. ReviewCredential 复用是否会绕过独立语义审查或 Executor 最终复验。
5. Readiness、授权、原子接受和结果归并是否存在循环或第二份事实。
6. S0 的协议测试是否被误写成需要 S1–S5 已完成的业务验收。

## 核心实体与所有权

| 实体 | 最小内容 | 唯一权威写入方 |
| --- | --- | --- |
| Task／Run | 长期任务、Run 关联、阶段、等待、暂停、阻断和恢复点 | Task Runtime |
| Invocation | invocation_id、task／run／operation、spec_digest、限制检查、预留、发送、结果和结算 | Task Runtime |
| Lease／ExecutionOwnership | owner、单调递增 generation、有效期和条件提交 | Task Runtime |
| Source／Evidence | 持久原文、定位、摘录、版本、摘要、可读范围和提取状态 | Knowledge Evidence |
| Evidence–Claim Relation | evidence_id、claim_id、supports／contradicts／qualifies、条件和核验状态 | Knowledge Evidence |
| Claim／Conflict | 命题、归属、条件、证据状态、核验和冲突处置 | Knowledge Evidence |
| KnowledgePackage | 主张、证据关系、定位、版本、可读范围、冲突、既有知识关系、包版本与摘要 | Knowledge Evidence |
| Objective／Rubric／Assessment | 目标类型、前置依赖、本课判据、作答证据和 evaluator 版本 | Learning & Assessment |
| OutputArtifact | 知识包版本、输出类型、表达内容、证据映射和输出质量记录 | Knowledge Output |
| Candidate／Manifest／Snapshot | 最终 Wiki 变更、公共事务字段和依赖快照 | Run Execution Driver／CandidateView |
| Coverage | 最终 diff、证据处置、教学处置、分类理由和审查绑定 | Knowledge Persistence |
| ReviewCredential | 冻结输入、审查结论、角色、证据、规则、配置和适用范围 | Task Runtime 认证，独立角色提供意见 |
| Readiness | 最终候选、证据与学习凭据、依赖、规则和未决阻断 | Task Runtime 认证 |
| Authorization | 动作、范围、候选、Readiness、依赖、规则和撤销状态 | Task Runtime／ApprovalStore 分别持久化 |
| Executor Transaction／WAL | 接受、完整写入意图、应用步骤、提交、回滚和恢复 | Executor |

Evidence 不保存单值 relation；同一证据可支持一个 Claim、反驳另一个。`consumed` 从 Executor applied 结果派生，不回写 ApprovalStore 历史。

## 核心协议

### 单账本 Invocation

```python
InvocationSpec = {
    "invocation_id": str,
    "learning_task_id": str,
    "run_id": str,
    "operation_id": str | None,
    "lease_generation": int,
    "role": str,
    "kind": str,
    "input_digest": str,
    "requested_budget": dict,
}

runtime.invoke(spec, call, *, timeout) -> InvocationResult
runtime.replay(spec) -> InvocationResult
runtime.settle(invocation_id, outcome, actual_usage) -> InvocationRecord
runtime.remaining_run_time(run_id) -> float
```

同一持久化临界区内完成：ID 与 spec 绑定、执行所有权、Task／Run／并发／最终留额检查和预留。记录随后依次保存发送状态、结果和结算；崩溃后从同一记录恢复。

相同 ID 不同输入或跨任务调用拒绝。成功重放返回保存结果；unknown 不重发、不退款；新实际尝试使用新 ID。只有可证明未发送且未发生外部调用时才允许释放预留。

Task Runtime 向 Run Execution Driver 和 Executor 注入同一个私有 InvocationPort：`invoke(spec, call, timeout)`、`replay(spec)` 和 `remaining_run_time(run_id)`。Coordinator 原调用计数只能作为非权威执行历史，Executor 不得再通过 reserve_call 回到另一套权威账本。S1 用跨 Worker、Reviewer、RuleAuditor 和 Executor G3 的重放样例证明一次调用只预留和结算一次。

### KnowledgePackage 与模块接口

```python
evidence.build_package(source_refs, claim_refs, conflict_refs) -> KnowledgePackage
output.render(package_ref, output_type, output_policy) -> OutputArtifact
learning.prepare(package_ref, objective_specs) -> LearningPlan
persistence.compile_candidate(package_ref, coverage_spec, baseline_ref) -> CandidatePreview
```

所有接口只接受明确的知识包版本。任何模块发现新增事实、结论变化或范围扩大，都返回知识修订请求，不直接修改原包。

### ReviewCredential

ReviewCredential 至少绑定：审查角色、独立 invocation、原文／原页／产物内容摘要、证据快照、依赖、规则、提示词、验证器、审查配置、适用范围和结论。

Task Runtime 负责认证角色与绑定，独立角色负责语义判断。最终执行只复用当前仍有效且适用范围相同的凭据；任何相关变化使相关记录失效。可信身份或绑定未实现时不得复用 Coordinator 自带报告代替 Executor 审查。

### Readiness、授权与原子接受

```text
冻结 Candidate / Manifest / Snapshot
    ↓
必要审查与学习验收
    ↓
生成不可变 Readiness / readiness_digest，不包含授权
    ↓
用户授权当前 action / operation / Candidate / Readiness / 依赖 / 规则
    ↓
Executor 检查授权、Readiness、依赖和执行所有权
    ↓
原子保存首个完整 WAL，包含接受与完整写入意图
    ↓
文件应用或独立恢复
    ↓
Task Runtime 按实际 Executor 结果归并
```

私有准入契约不修改公共 manifest：

```python
Admission = {
    "learning_task_id": str,
    "raw_batch_id": str,
    "run_id": str,
    "operation_id": str,
    "created_generation": int,
    "candidate_digest": str,
    "readiness_digest": str,
    "dependencies_digest": str,
    "rules_digest": str,
    "authorization_ref": str,
}

Executor(..., acceptance_check=None)
executor.apply(bundle, admission=host_private_admission, ...)
acceptance_check(executor_context, admission) -> bool
```

Executor 在新审查或预算消耗前提供 `lookup_terminal(bundle)`，身份一致的 applied／recovered 直接返回历史结果。非终态才继续预检。审查期间撤销、Readiness 失效或执行所有权换代必须能被真实完成，并在首个完整 WAL 前阻止旧操作。

acceptance_check 在 G3 后、首个完整 WAL 前执行，重新核对 Candidate、Readiness、授权撤销、依赖、规则、版本和 fencing；撤销／失效／换代与最终接受使用同一跨进程串行化边界。S1 增加 `after_acceptance_before_prepare` 故障点，验证检查成功后、WAL 前崩溃仍为未接受。

Executor 结果归并固定为：

- applied：应用成功，派生授权 consumed。
- prepared／applying／recovery_required：已接受但未完成，继续 recover，禁止换 operation 绕过。
- recovered：已回滚，应用未完成；有效学习证据保留，重新应用使用新 operation、新 Readiness 和新授权。
- `state=recovery_required` 且 `recovery_status=conflict`：Runtime 投影为人工对账阻断，不重建事务覆盖用户修改；conflict 不是新的 Executor state，不扩张公共 v1。

### 校准与理解证据

Objective、本课 rubric、可复用 rubric_template、evaluator 和 Assessment 分开。模板校准验证提示依赖、条件遗漏、表达差异等通用判分行为；本课 rubric 必须回到证据审查。

理解记录说明用户在哪些目标、条件和版本下展示过什么能力，不使用永久有效的单一“已掌握”标签。S0 只验证这些记录的绑定和失效协议，真实校准与教学在 S3 验收。

## 工程目录边界

```text
tools/wiki_runtime/
├── runtime/              # 拟新增：Task / Run / Invocation / 预算 / 授权 / 恢复协调
├── host/                 # 交互、工具、身份与权限入口
├── coordinator/          # 复用 Run 内工作循环，不再拥有权威预算
├── executor/             # 文件事务、WAL 与恢复
├── candidate/            # 最终候选与依赖快照
├── contracts/            # 公共契约
├── evidence/             # 拟新增：证据与 KnowledgePackage
├── learning/             # 学习目标、判据、作答和校准
├── output/               # 拟新增：知识输出适配器
├── persistence/          # 拟新增：Wiki 映射、覆盖和 Readiness 输入
└── review/               # 审查协议
```

本轮只定义目录职责，不创建或迁移生产目录。S0 的协议代码可以落在对应 `runtime/`、`evidence/`、`learning/` 等模块，但不得建立 `s0/` 作为另一套运行时。

## 任务依赖与文件顺序

```text
Task 1 核心实体与协议
    ↓
Task 2 模块接口与目录边界
    ↓
Task 3 三个贯穿场景和后续验收归属
    ↓
Task 4 可执行协议校验、独立审查与 S0 交接
```

共享协议只由 Task 1 创建，后续任务消费；不在多个任务中重复定义实体。

### Task 1: 定义核心实体、状态与单账本协议

**Files**

- Create: `tools/wiki_runtime/runtime/__init__.py`
- Create: `tools/wiki_runtime/runtime/protocol.py`
- Create: `tools/tests/fixtures/learning_s0/protocol_records.json`
- Create: `tools/tests/test_learning_s0_protocol.py`

**Interfaces**

- Consumes: 现有 `contracts.digest`、`bytes_digest` 和路径校验原语。
- Produces: Task、Run、Invocation、InvocationPort、ExecutionOwnership、ReviewCredential、Readiness、Admission、Authorization、ExecutionResultBinding 的解析、规范摘要与校验函数。

**实施步骤**

1. 定义私有记录和状态字段，禁止注入公共 v1。
2. 固定 Invocation 的预留、发送、结果、unknown、结算和重放规则，以及 Runtime 注入 Run Execution Driver／Executor 的同一 InvocationPort。
3. 固定 Readiness 不含授权、授权绑定 Readiness、Admission、acceptance_check、WAL 接受和结果归并。
4. 固定终态查询先于新审查／预算消耗的规则。
5. 建立包含合法记录及错误绑定、错误代次、错误状态、跨任务重放和 `recovery_required＋recovery_status=conflict` 的合成记录。

**验收**

- 相同 invocation_id 配不同 spec_digest 或任务作用域被拒绝。
- 同一条 Invocation 能同时表达 Task、Run、并发和最终留额限制，没有第二个权威账本字段；Worker、Reviewer 和 Executor G3 使用同一 InvocationPort。
- Readiness 无授权字段；Admission 与当前候选、Readiness、授权、依赖、规则和 fencing 绑定。
- recovered 不会被协议解析为 applied；applied 才派生 consumed；conflict 只从 recovery_required＋recovery_status=conflict 投影，不是新公共状态。
- 公共 v1 现有契约测试不需修改即可通过。

**失败出口**：协议仍要求 Host／Coordinator 各自保存权威预算，或无法表达终态重放、撤销和结果归并时，停止后续任务。

### Task 2: 定义知识包、业务模块接口和目录边界

**Files**

- Create: `tools/wiki_runtime/evidence/__init__.py`
- Create: `tools/wiki_runtime/evidence/package_protocol.py`
- Create: `tools/wiki_runtime/learning/artifact_protocol.py`
- Create: `tools/wiki_runtime/persistence/__init__.py`
- Create: `tools/wiki_runtime/persistence/protocol.py`
- Create: `tools/tests/test_learning_s0_modules.py`

**Interfaces**

- Consumes: Task 1 的通用身份、摘要、状态和审查绑定。
- Produces: KnowledgePackage、OutputArtifact、LearningPlan、CoverageDisposition、CandidatePreview 及本文模块接口。

**实施步骤**

1. 定义知识包的主张、证据关系、定位、版本、可读范围、冲突和既有知识关系。
2. 定义四种覆盖处置：required_objective、reuse_objective、optional_extension、non_teaching。S2 的 coverage_spec 只包含规划中的处置和目标引用，不包含真实学习凭据；S2 只产出 CandidatePreview／Coverage，S3 才绑定实际理解与审查记录，此前不得生成通过的 Readiness。
3. 定义课程、文章、视频和 Wiki 候选对同一知识包版本的引用。
4. 定义输出新增语义时返回知识修订请求，而非修改原包。
5. 固定 Objective、本课 rubric、rubric_template、evaluator、Assessment 和理解条件的绑定。
6. 核对每个实体的目录归属和唯一写入方。

**验收**

- 同一 Evidence 可对不同 Claim 具有不同关系。
- 知识包版本变化能被课程、文章、视频和 Wiki 候选共同检测。
- S2 没有真实学习产物时，coverage_spec 不能伪造通过凭据或生成有效 Readiness；S3 才能完成学习绑定。
- 可选和非教学记录不要求伪造 Assessment；核心目标缺少独立凭据则协议拒绝。
- 本课 rubric 不因模板校准通过而免独立证据审查。
- 新增输出类型只要求表达适配和质量标准接口，不要求复制运行时或证据模型。

**失败出口**：知识包缺少证据／冲突／版本信息，或新增输出类型需要改变门禁、运行时和知识沉淀接口时，返回设计审查。

### Task 3: 固定三个贯穿场景和阶段验收归属

**Files**

- Create: `tools/tests/fixtures/learning_s0/scenarios.json`
- Create: `tools/tests/test_learning_s0_scenarios.py`

**Interfaces**

- Consumes: Task 1–2 的实体、接口和合成记录。
- Produces: ScenarioRecord，包含 scenario_id、fixture_version、输入摘要、步骤、预期状态、所需证据层、允许副作用和阶段归属。

**实施步骤**

1. 固定正常文本场景：原始资料→知识包→课程→独立验收→Wiki 候选→Readiness→授权→Executor ingest／approve。
2. 固定外部纠错场景：临时材料→冲突→持久原文→Evidence–Claim→依赖传播→重新学习→G3 实际原文→知识沉淀。
3. 固定跨会话场景：Task／Run 恢复、预算继承、执行所有权换代、旧提交拒绝、学习局部失效、事务重建和 Executor 独立恢复。
4. 为每一步标注所属 S0–S5、所需脚本／语义审查／真实宿主／owner 证据及当前是否可验收。
5. 明确 S0 只执行协议层负向样例，真实业务场景由后续阶段验收。

**验收**

- 三个场景均使用同一套 Task Runtime、Invocation、KnowledgePackage、Readiness 和授权协议。
- 场景没有依赖另一套阶段运行时、预算或接受记录。
- S0 完成条件不包含需要 S1–S5 实现的真实业务结果。
- 后续场景保留完整要求，不能因当前不可验收而标记通过。

**失败出口**：阶段归属冲突、场景共用协议不一致，或 S0 必须等待后续业务实现才能通过时，停止并修正路线。

### Task 4: 执行 S0 协议验收并形成阶段交接

**Files**

- Modify: `docs/design/learning-ingest-review.md`
- Modify: `docs/design/learning-ingest-handoff.md`
- Modify: `docs/design/learning-ingest-stages.md`

**Interfaces**

- Consumes: Task 1–3 的可执行协议、合成记录、场景和检查命令。
- Produces: 实际检查结果、独立审查意见、未实现能力和 S1 允许依赖的接口清单。

**实施步骤**

1. 运行 S0 协议、模块和场景测试。
2. 运行现有公共契约及相关回归，证明没有改变既有语义。
3. 由未参与编写的审查员核对真实代码兼容性和需求覆盖。
4. 只有协议测试和独立审查均通过才更新 S0 状态；否则保留失败记录。

**S0 必需的负向协议样例**

- 跨任务／不同输入的 invocation 重放被拒绝。
- unknown 调用不会自动重发或退款。
- 旧 generation 的续租、释放和业务提交在协议上无效。
- 无当前授权、Readiness 失效或必要理解凭据缺失时不能进入接受。
- 已 applied／recovered 的重放不会生成新审查或预算记录。
- recovered 不投影为 applied，已接受事务恢复不要求旧租约。
- 知识包变化会使相关输出、学习和 Wiki 候选绑定失效。
- 本课 rubric 不能凭无关模板校准免证据审查。
- 候选含 A／B 而覆盖记录只有 A 时，协议拒绝。
- 后续真实业务场景没有当前证据时，结果保持未验收。

**失败出口**：任何必需协议样例无法执行、字段检查被当作语义证明，或独立审查发现与真实代码不兼容时，S0 不通过。

## 验证命令

程序使用 `<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，cwd 为项目根目录，所有 Python 命令使用 `-B`。S0 目标测试建议超时 120 秒；需要运行完整历史套件时总时限为 1800 秒，依据历史约 878 秒记录保留增长空间。超时即失败，不重跑取最好结果。

```bash
python -B -m unittest discover -s tools/tests -p "test_learning_s0_protocol.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s0_modules.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s0_scenarios.py" -v
python -B -m unittest discover -s tools/tests -p "test_runtime_contracts.py" -v
python -B tools/health.py --json
```

另运行：

```bash
node <用户家目录>/.agents/skills/wf-plan/scripts/plan_lint.js docs/design/learning-ingest-s0-plan.md --root .
git diff --check
```

plan_lint 只检查计划结构和占位等机械问题，不证明接口语义或场景覆盖。当前 Spec 位于项目既有的 docs/design，plan_lint 的 docs/specs 专用互指检查不适用，由独立审查核对 Spec 链接与内容一致性。

## 需求—任务—门禁映射

| 需求 | 任务 | S0 验证 | 后续实际验收 |
| --- | --- | --- | --- |
| 统一 Task Runtime 与 Host 边界 | 1、2、4 | 实体唯一所有权和协议检查 | S1 真实运行时 |
| 单账本 Invocation 与原子预算 | 1、4 | 重放、unknown、并发限制和结算记录 | S1 崩溃与并发探针 |
| KnowledgePackage 跨模块复用 | 2、3、4 | 版本、证据、冲突和输出绑定 | S2–S4 业务实现 |
| ReviewCredential 可信复用 | 1、2、4 | 角色、绑定、适用范围和失效 | S1 起真实身份与审查 |
| Readiness、授权与原子接受 | 1、3、4 | 无循环、无授权拒绝、WAL 协议 | S1 锁与恢复，S5 真实入库 |
| 学习独立性与校准分层 | 2、3、4 | 目标、模板、本课判据和理解条件绑定 | S3／S4 教学与校准 |
| 知识沉淀与正式入库 | 2、3 | Wiki 候选接口和 ingest／approve 分离 | S2 候选，S5 真实批次 |
| 三个贯穿场景 | 3、4 | 统一步骤、状态和阶段归属 | S2–S5 按依赖逐步完成 |

## S0 完成条件与停止条件

完成条件：四项任务完成；S0 协议、模块和场景测试通过；相关现有契约回归通过；独立审查确认与真实代码相容；后续场景均有明确阶段归属；审查记录、路线图和交接更新。

以下任一情况阻断 S0：

- 仍有 Host／Coordinator 第二套权威任务状态或预算。
- 单条 Invocation 无法原子表达所有限制或崩溃恢复。
- 知识包不能承载证据、冲突、版本或既有知识关系。
- 审查凭据仅凭摘要即可复用，或生成者能自签通过。
- Readiness 与授权循环绑定，或接受与写入意图分成两份可能不一致的事实。
- S0 完成条件要求 S1–S5 的真实业务已经实现。
- 真实 raw、正式 Wiki 或用户数据被用于破坏性测试。
