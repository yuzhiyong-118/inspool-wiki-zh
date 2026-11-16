---
type: meta
title: 学习型知识库 S1 详细任务书
status: proposed
updated: 2026-11-09
topic: 持久循环、恢复兼容、统一入口与文件事务
---

# 学习型知识库 S1 详细任务书

## Goal

把 S0 及循环协议增量转换为真实基础设施：Task Runtime 使用 SQLite 统一 Event、Task、Run、Step、Invocation、Wait、WorkItem、预算、授权和结果登记；Coordinator 重构为有界 Step Driver；Executor 继续独占最终接受、完整 WAL、文件应用与独立恢复。

本任务书按 T0–T7 重排实施顺序：先固定协议和旧 WAL 兼容，再建设账本与持久循环，随后接 Executor、学习入口和全局切变，最后整体验收。目标仍包括所有业务入口的统一 Runtime 路径，不以“学习入口已统一”冒充全局完成。

> 2026-11-09 实施状态：T0–T7 全部完成，S1 验收通过。设计复审见审查记录 §22，实施与最终验收证据见 §23–33。完整运行时语义见[持久循环与受控扩展设计](learning-ingest-runtime-loop.md)。通过范围不含真实宿主、真实 L3、教学质量、真实 scoped 状态或 S2–S5。

Spec: [学习驱动的知识入库与分级证据校验方案](learning-gated-ingest-plan.md)

前置：[S0 详细任务书](learning-ingest-s0-plan.md)的历史验收，以及本任务书 Task 0 的新协议验收。阶段要求：[S0–S5 路线图](learning-ingest-stages.md)的 S1。

## Architecture

```text
Host / CLI
└── 用户、owner、工具与参数适配，不持有业务总控状态
    ↓
Task Runtime / SQLite
├── Event / Task / Run / Step / Invocation / Wait / WorkItem
├── 不可变 PolicyRevision / submission_epoch / generation
├── 统一财务与执行资源 / ExecutionOwnership
├── Readiness / Authorization / ReviewCredential 状态投影
├── 静态可信 CapabilityRegistry
└── 结果归并与旧状态 cutover
    ↓ 受控 Step 请求                         ↑ StepResult
Driver（重构 Coordinator）
    ↓
Executor
├── 现有 journal_root / active / 终态查询 / acceptance_barrier
├── 锁外 G3 → 锁内 G0–G2、依赖、G4 与动态准入复验
└── 完整 WAL → 文件应用 / 回滚 / 独立恢复
```

SQLite 的事务与 Wiki Executor 的文件 WAL 是不同边界。数据库不能替代文件接受事实，Executor 也不接管长期任务状态。

## Tech Stack

- 现有 Python、标准库、`unittest`、临时目录、真实双线程与子进程。
- 现有 contracts、CandidateView、G0–G5、ApprovalStore、Executor WAL 与恢复。
- Python 标准库 sqlite3：本地单库、短事务、WAL、synchronous=FULL、foreign_keys=ON、有限 busy_timeout；无数据库服务或新包依赖。
- S0 纯协议与合成记录；真实知识、课程和 raw 批次仍属 S2–S5。
- 静态可信 registry，不引入插件框架、工作流 DSL、事件溯源平台或通用 schema 迁移框架。

## Global Constraints

1. Task Runtime 是任务、调用、预算、授权和结果归并的唯一权威；Host／CLI／Coordinator 不保留第二套业务真值。
2. 现有 Executor `journal_root` 和 active 路径不得静默改变。完整 WAL 是唯一接受事实，恢复不得依赖新 Runtime 或旧租约。
3. 旧 pre-WAL pending 必须 drain 或明确 supersede 后重新确认；不得从聚合 calls 伪造 Invocation 历史，不得借 cutover 重置预算或授权。
4. 所有业务写入入口最终统一委托 Runtime，包括 `host/cli.py` 的 derived 流程；只读查询不强制建成写入工作流。
5. 一条 Invocation 在同一 SQLite 写事务完成身份、policy、Task／Run 财务、并发资源及最终留额检查，同时取得 not_started 并发槽。
6. not_started／inflight／draining 都占资源；unknown 保守结算但不退款／重发／提前释放资源，迟到完成只释放资源。
7. Task ownership、Step generation 和 Invocation execution_token／recovery_epoch 分别管理，不互相代替。
8. 事件接收、状态与工作项提交分别原子完成；外部规划、插件、模型、工具和 TTY 不在 SQLite 事务内执行。
9. 最终接受锁顺序为 `executor.lock → SQLite BEGIN IMMEDIATE`，并保持至完整 Executor WAL 保存；普通 Runtime 事务不得反向等待 Executor 锁。
10. Task 暂停增加 submission_epoch，并将已有 execution binding 的 pre-WAL 操作标记 superseded_by_pause；恢复后在同一 Task 下使用新 operation_id、新 Admission 和新 Authorization。已有 WAL 始终按原 operation 恢复，终态重放豁免动态状态检查。
11. PolicyRevision 不可变，Task 只切换当前 revision；Invocation、Admission 和 Authorization 记录 policy_digest，不原地修改预算策略。
12. ingest 使用 Runtime 授权；approve 继续 ApprovalStore／ApprovalHandle／G4；两类撤销都经过同一 Executor 屏障。
13. Readiness／ReviewCredential 内容不可变，失效存状态投影。无可信 Attestation 时只保留本次 G3 的 UnattestedReviewEvidence，不自动满足真实 L3。
14. 公共契约 v1、AGENTS、真实 raw 与正式 Wiki 不因设计或开发测试改变；测试只用合成资料和临时库。
15. 全局单路径不得成为新资料免学习入库旁路；既有非学习维护仍按现行授权与门禁执行。

## Plan-stage Decisions

- **D1：先兼容，再切变。** 先证明现有 journal_root 下的事务可恢复，再建设 SQLite；旧 pending 在新入口启用前一次性处置。
- **D2：SQLite 直接服务原子协议。** 不先实现 JSON 再迁移，不保留双权威账本；当前状态表为权威，事件和审计不是另一套可独立覆盖的状态。
- **D3：最小持久循环。** Event、Step、Wait、WorkItem 只覆盖真实恢复边界；同 Task 串行，跨 Task 受统一并发限制，不建设并行图调度。
- **D4：静态能力注册。** registry 只记录能力 ID、实现摘要、契约版本、必需检查、用量可见性和取消能力；权限由可信代码与角色端口固定，不建设通用类型系统或插件权限矩阵。
- **D5：schema v1 先拒绝未知版本。** 保留事务性备份和版本检查；出现 v2 需求时才设计迁移，不在 S1 预建通用升级框架。
- **D6：暂停即提交代次失效。** submission_epoch 与 Task generation 分开；pause→resume 不允许旧 Admission 继续。已有 execution binding 的 pre-WAL 操作必须 supersede，恢复后用同一 Task 的新 operation_id 继续，不能换 Admission 重绑原 operation。
- **D7：全局目标与验收一致。** `host/cli.py`、derived 流程及旧 pending 切变是必需交付，不能只重构 Coordinator 就宣称全局单路径。
- **D8：验收随任务前置。** 每个任务先取得自己的真实失败／通过证据，T7 做组合回归；不把所有兼容风险留到阶段末尾。

## Review Focus

1. WAL 是否始终能在现有 journal_root 定位，旧 recovered 是否永久封闭，旧 pending 是否有确定去向。
2. 任务图是否先提供 acceptance_barrier 再消费，Executor 文件是否按顺序修改，是否仍有循环依赖。
3. submission_epoch、policy_digest、StepResult result_digest 是否进入封闭协议和跨记录校验，而非只在文字中出现。
4. SQLite 与 Executor WAL 的锁顺序、崩溃点和终态豁免是否保持唯一语义。
5. 全局单路径是否覆盖真实 `host/cli.py` derived 入口，是否误把只读查询强制纳入写入事务。
6. 静态 registry、简单 RetryPolicy 和 schema v1 是否被重新扩张成通用平台。
7. S1 是否仍只用合成知识／学习记录，是否把基础设施通过误写成真实教学或真实入库通过。

## 1. 固定恢复与切变边界

### 1.1 现有路径不得改换

当前 Host 使用 `state_dir/private/journals` 作为 Executor journal_root，active 位于 `.wiki-runtime/executor-active.json`，共享锁位于 `.wiki-runtime/executor.lock`。新 Runtime 数据位于 `.wiki-runtime/learning/runtime.db`，不得据此推断或迁移 Executor WAL。

本版继续复用 Host 已配置的 journal_root，不建立多 journal_root 注册表。Executor.lookup_terminal、apply 和 recover 都从同一已配置 root 读取 journal；active 中的 journal_root 只用于一致性核对，不能替代首次定位。

### 1.2 一次性 cutover

1. 采用 offline cutover：Task 3 在 Task 4 改造 G3 前停止全部旧 Host 进程，冻结新操作创建及未登记 apply，只保留读取、恢复、owner 对账和唯一离线 drain runner；全局切变完成前不得重启其他旧写入进程。
2. 已接受 WAL 按原 journal_root 恢复或查询，不迁移字节，不改变 operation 终态。
3. 可继续的 pre-WAL pending 必须在 Task 3 开头、Task 4 G3 改造与 Task 5 Coordinator 重构前，由原 Coordinator 预算回调与 Executor drain；runner 只能处理 inventory 登记的 operation_id，且 WAL 身份必须与清单完全一致。无法取得原预算语义或不能继续的记录留给 Task 6 标记 `superseded_by_runtime_cutover`，随后以新 Task、operation、Readiness 和 Authorization 重新确认，不强行 drain 或伪造调用。
4. 旧 calls／candidates／audit_attempts 只作历史，不反造 Invocation。若必须继承预算，采用 owner 批准的保守上限，记为 cutover 调整事件，不能声称恢复了原逐次消耗。
5. 只有旧 WAL 可定位、pre-WAL pending 已处置、全局入口已适配后，才启用新写入路径。`inspect_cutover` 与 supersede 幂等，重启先检查再继续；除清单内获准 drain operation 外，任何旧入口／旧进程都不得创建新 WAL。

## 2. 协议增量与最小化范围

### 2.1 Task 0 必须封闭的字段

- StepResult 增加 `result_digest`，并以 `(step_id, attempt, generation)` 作为原确认键；同键同 input_digest／result_digest 返回原确认，同键不同摘要拒绝。
- PolicyRevision 包含 revision、policy_digest、不可变预算／停止策略和创建原因；Task 保存 current_policy_digest，Invocation／Admission／Authorization 保存使用时的 policy_digest。
- Admission 与 Authorization 增加 `submission_epoch`，Admission 另绑定完整 `manifest_digest`。Task 暂停时原子递增，resume 不恢复旧 epoch；最终接受必须匹配当前 epoch、manifest、Candidate、依赖与规则。
- Event 只保留可信 producer、event_id、task_id、type、payload_digest、目标版本、接收序号、处理状态及可选直接 causation_id；以 task_id、type、目标版本、payload_digest 计算业务信封摘要，不建设通用事件图。
- RetryPolicy 只保留错误类别、失败指纹、attempt 上限、not_before 和停止原因；相同输入与失败指纹达到阈值即停止，不引入通用“工作流进展声明”框架。
- RuntimeTask 与 LearningState 分离；S0 原 Task 解析器、摘要、夹具和消费者统一切换，不并存两套 Task 真值。

### 2.2 保留的核心协议

- 原子预留财务与 not_started 槽，同时核对当前 Task／Run、PolicyRevision、ExecutionOwnership 和期限；not_sent→sent 以 token＋recovery_epoch 条件迁移并继承同一槽，发送前在同一事务重验动态资格与预算阻断。成功结果的只读重放豁免动态资格。
- sent＋pending 且无结束证据时归并 unknown 并 inflight→draining；宿主确认结束可 inflight／draining→released。未发送预留释放沿用浮点容差归零，不得因残差永久占用资源。
- WorkItem 接管只增加 generation，不自动增加业务 attempt；原 Invocation 成功结果经当前依赖重验后可归并，pending 仅在本轮跳过所属 Task 并继续扫描，unknown 保持阻断。后续工作摘要同时绑定 Step 不可变定义与 WorkItem；重试和领取均核对当前停止策略，单 Task 的失效依赖局部阻断并继续扫描其他 Task。
- 最终锁内重跑 G0–G2、质量、依赖、目录、payload、规则与 G4，检查 RuntimeTask／LearningState／Run、deadline、预算阻断、submission_epoch、policy_digest、Readiness、Authorization、Credential 和 fencing。
- applied 才派生授权 consumed；recovered 不是 applied；Executor 在 WAL 中持久化 recovery_status，归并不得使用调用方参数构造预期 conflict。无该字段的旧 WAL 只接受可由 state 唯一派生的状态。Host 终态查询与归并复用同一 Executor。

完整字段语义、事件／步骤状态机和 X／L 场景以[运行时设计](learning-ingest-runtime-loop.md)为准，本任务书不另复制一套定义。

## 3. 任务依赖与文件顺序

```text
Task 0 协议与现状基线
 ├──────────────────┐
Task 1 Executor 兼容  Task 2 SQLite / Invocation
 └────────┬─────────┘
          Task 3 持久循环
             ↓
          Task 4 最终接受
             ↓
          Task 5 学习入口
             ↓
          Task 6 全局切变
             ↓
          Task 7 综合验收
```

Task 1 与 Task 2 可并行。Task 1 先提供 acceptance_barrier，Task 3 才能暂停／撤销；Task 4 再修改同一 Executor 文件完成最终接受。Task 5 只接学习入口，Task 6 才声明全局切变完成。

### Task 0: 固定循环协议与真实现状基线

**Files**

- Modify: `tools/wiki_runtime/runtime/protocol.py`
- Create: `tools/wiki_runtime/runtime/loop_protocol.py`
- Modify: `tools/wiki_runtime/runtime/__init__.py`
- Create: `tools/tests/test_learning_s0_loop_protocol.py`
- Create: `tools/tests/fixtures/learning_s0/loop_protocol_records.json`
- Create: `tools/tests/fixtures/learning_s0/legacy_inventory.json`

**Interfaces**

- Consumes: 既有 S0 协议；真实 `host/supervisor.py`、`host/cli.py`、`coordinator/loop.py`、`executor/core.py`、`tools/raw_index.py`、`tools/heal.py` 的路径与状态。
- Produces: RuntimeTask／LearningState、Event／Step／Wait／WorkItem／StepResult／WorkflowRef、PolicyRevision、submission_epoch、result_digest、静态 CapabilityManifest 的封闭解析与摘要；真实入口／WAL／pending 基线清单。

**依赖**：无。只定义协议与合成样例，不实现 SQLite 或调度。

**实施步骤**

1. 将 RuntimeTask 与 LearningState 分离并统一更新现有 S0 消费者，保留历史测试范围说明。
2. 封闭 Event／Step／Wait／WorkItem／StepResult／WorkflowRef 和最小 CapabilityManifest，补 result_digest 与原确认键。Event 明确包含 type，以 task_id、type、目标版本、payload_digest 计算不可变业务信封摘要，排除接收序号与处理状态。
3. 为 Invocation／Admission／Authorization 增加 policy_digest 与必要的 submission_epoch 绑定及负向样例。
4. 固化现有 journal_root、active、Host pending、Coordinator 状态及全部写入入口清单，包括 `host/cli.py` derived、`refresh_index(apply=True)`、`run_heal(dry_run=False)`，以及 `heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 的 dry_run=False 分支；只读预览单列。
5. 限定 registry／RetryPolicy／schema v1 的范围，不创建通用插件或迁移框架。

**验收**

- 同 StepResult 键同摘要可重放、异摘要拒绝；缺 result_digest 拒绝。
- 同 producer＋event_id 且同业务信封返回原确认；同 payload 改投不同 Task／type／目标版本均报冲突，不得返回旧确认。
- 暂停后旧 submission_epoch、错误 policy_digest、跨 Task／revision 绑定均拒绝。
- 通用 Task 枚举不含教学阶段；原 S0 消费者没有第二套 Task 真值。
- 基线清单准确指出现有 journal_root、active、pending、derived、一个 raw_index 写分支及四个 heal 写分支，只读预览不误列为写入口。
- 新协议独立审查通过，历史 59 项不作为增量凭据。

**失败出口**：字段仍只存在于说明文字、入口清单遗漏真实写调用，或协议增量依赖后续实现才能验收时停止。

### Task 1: 建立 Executor 恢复兼容与最小切变设施

**Files**

- Modify: `tools/wiki_runtime/executor/core.py`
- Modify: `tools/wiki_runtime/executor/__init__.py`
- Create: `tools/wiki_runtime/runtime/migration.py`
- Modify: `tools/raw_index.py`
- Modify: `tools/heal.py`
- Modify: `tools/tests/test_health.py`
- Create: `tools/tests/test_learning_s1_executor_compat.py`
- Create: `tools/tests/test_learning_s1_cutover.py`
- Create: `tools/tests/fixtures/learning_s1/executor_process.py`
- Create: `tools/tests/fixtures/learning_s1/legacy_cutover.py`

**Interfaces**

- Consumes: Task 0 基线；现有 Executor._lock、_journal、_active、_result、recover、旧 pending 存储及五个 Python API 写分支。
- Produces: `Executor.lookup_terminal(bundle) -> dict | None`；`Executor.acceptance_barrier()`；`inspect_cutover(state_dir)`；`freeze_legacy_entries(root, state_dir)`；`inventory_pending(state_dir)`；`legacy_write_guard(root, operation_id=None)` 上下文管理器；清单约束的 `drain_registered_pending(operation_id)` 与可重入检查点。

**依赖**：Task 0；与 Task 2 可并行。此任务只提取锁、公共 bundle 终态查询和最小切变设施，不提前实现 Task 4 的锁外 G3 或 Admission 绑定校验。

**实施步骤**

1. 固定现有 journal_root／active 路径和身份校验，不迁移 WAL。
2. 在短锁内实现 journal／active／terminal 初查；同 operation 不同公共 manifest／candidate／snapshot 拒绝，非终态要求原 operation 恢复。私有 Admission 校验留到 Task 3 建立 execution binding 后的 Task 4。
3. 将同一 Executor 锁暴露为 acceptance_barrier，供 Runtime 暂停／撤销、ApprovalStore 撤销及 legacy_write_guard 复用。
4. 实现最小 freeze、inventory、唯一 runner、operation 白名单、清单外写入拒绝和幂等重启检查；在库内受控位置保存与 state_dir 及 inventory digest 绑定的 freeze 描述，供旧 API 核验。
5. 为 `refresh_index`、`run_heal`、`heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 的生产写分支统一接入 `legacy_write_guard`。guard 在同一 executor.lock 内完成资格检查并覆盖全部实际文件写入，freeze 也用同一锁等待已登记写者退出后原子发布；只读预览不检查也不改变。`run_heal` 外层持有一次 guard 后调用私有未包装实现，或对辅助函数传递同一 guard，禁止嵌套获取非重入锁。
6. 用真实旧路径合成 prepared／applying／applied／recovered WAL 验证定位、恢复和终态封闭；inventory 为空时显式记录无需 drain。调整 `test_health.py` 增加“检查后暂停写者→freeze 等待→drain 期间无迟到写入”的故障点，冻结前旧行为不在本任务强行改写。

**验收**

- 四种旧 WAL 状态都能从原 root 正确查询或恢复；recovered 不得重新 apply。
- 终态查询不调用 G3、不消耗预算，并先于新 deadline／provenance 检查；本任务不宣称已验证 Admission 异绑拒绝。
- acceptance_barrier 与 Executor 使用同一把跨进程锁，没有第二把撤销锁。
- T3 开始前即可获得冻结、白名单 runner、清单外拒绝及重启检查；runner 中断后幂等续办，清单外 operation 不得创建 WAL。
- 五个 Python API 写分支从资格检查到实际写入均由同一 guard 保护；freeze 等待已登记写者退出，drain 期间无迟到写入，freeze 后新写者拒绝；只读预览保持原行为。
- 空 inventory 可跳过 drain 但仍通过冻结与恢复检查；现有 Executor 恢复测试保持通过。

**失败出口**：需要迁移 WAL、另建 root 注册表、旧接受状态不可定位，或资格检查与实际写入之间仍存在未串行化窗口时停止后续任务。

### Task 2: 实现 SQLite v1 与统一 Invocation

**Files**

- Create: `tools/wiki_runtime/runtime/storage.py`
- Create: `tools/wiki_runtime/runtime/invocation.py`
- Modify: `tools/wiki_runtime/runtime/__init__.py`
- Create: `tools/tests/test_learning_s1_runtime.py`
- Create: `tools/tests/fixtures/learning_s1/runtime_process.py`

**Interfaces**

- Consumes: Task 0 协议与 PolicyRevision；既有 Invocation 纯协议。
- Produces: `RuntimeStore(root)`；按需 `read(query)`；可信内部 `mutate(fn)`；`backup(destination)`；`RuntimeInvocationPort.invoke(spec, call, timeout)`；`replay(spec)`；`remaining_run_time(run_id)`；`confirm_resource_released(invocation_id, evidence)`。

**依赖**：Task 0；与 Task 1 可并行。

**实施步骤**

1. 实现 SQLite 路径、WAL／FULL／外键、有限 busy_timeout、独立连接、schema v1 与未知版本拒绝。
2. 建立不可变 PolicyRevision、Invocation、InvocationExecution、ownership 等表及唯一／引用约束。
3. 在同一写事务完成 policy、Task／Run 财务、并发资源、最终留额、身份检查与 not_started 占位。
4. 实现条件发送、结果、unknown、财务结算、资源释放、重放和崩溃接管。
5. 实现 SQLite backup API 备份；备份先固定数据库快照，再复制该快照引用的不可变 artifacts，期间禁止删除被引用产物。

**验收**

- 双进程竞争最后财务额度／并发槽只有一个成功；not_started 在发送前后都占位。
- 同 ID 活跃重入不重复执行；杀死执行者后按证据接管，不自动重发。
- unknown 不退款，inflight→draining→released 路径唯一，反复超时不能突破并发上限。
- 实际超额在同一事务形成预算阻断；policy revision 不原地变化。
- db busy、备份失败、产物缺失和未知 schema 均有界拒绝，不自动重置。

**失败出口**：出现第二账本、通用迁移框架，或执行／资源状态无法从 SQLite 唯一恢复时停止。

### Task 3: 实现持久事件、Step、Wait 与动态授权

**Files**

- Create: `tools/wiki_runtime/runtime/loop.py`
- Create: `tools/wiki_runtime/runtime/service.py`
- Modify: `tools/wiki_runtime/runtime/protocol.py`
- Modify: `tools/wiki_runtime/runtime/__init__.py`
- Test: `tools/tests/test_learning_s1_runtime.py`

**Interfaces**

- Consumes: Task 1 acceptance_barrier、最小 freeze／inventory／runner／重启检查及五个 Python API 写分支的 freeze 约束、Task 2 RuntimeStore／InvocationPort、Task 0 协议。
- Produces: `create_task`；`accept_event`；`plan_pending`；`claim_step`；`submit_step_result`；`answer_wait`；`pause/resume`；`acceptance_context(admission)`；`issue_ingest_authorization`；`build_admission`；`reconcile_execution`。

**依赖**：Task 1–2。Task 0 已导出基础协议；本任务顺序追加 loop／service，不并行改写共享导出段。

**实施步骤**

1. 在 Task 4 改造 G3 前，使用 Task 1 已验收的冻结、inventory、唯一 runner 和重启检查停止旧 Host 进程，再由原 Coordinator 预算回调处理 inventory 中可继续的 pre-WAL pending；runner 只能为清单内 operation 创建身份一致的 WAL，其他旧入口写入全部拒绝。inventory 为空记录无需 drain，无法 drain 的记录留给 Task 6。
2. 实现事件接收去重、事务外冻结规划、revision 条件提交和持久 WorkItem。
3. 实现 Step 原子领取、generation 结果归并、版本化 Wait 与重复／过期回答处理。
4. 实现不可变 PolicyRevision 切换与简单 RetryPolicy；不建立通用进展声明或事件图。
5. 暂停经 acceptance_barrier 并增加 submission_epoch；已有 execution binding 的 pre-WAL 操作同时标记 superseded_by_pause。resume 创建新活动资格，在同一 Task 下以新 operation_id、新 Admission 和新 Authorization 继续；有效 Readiness 仅按既有依赖复核复用，已有 WAL 仍走原 operation。
6. acceptance_context 持有同一 SQLite 短写事务，供 Task 4 最终检查至 WAL 保存；不在其中调用模型／插件／TTY。
7. 保存 Readiness／Credential 状态投影、ingest 授权及 operation→admission_digest；approve 只关联现有 ApprovalStore context_digest。

**验收**

- C2 前置：可继续旧 pending 已在 Task 4 G3 改造和 Task 5 Coordinator 重构前 drain；drain WAL 与 inventory 完全一致，此外无其他旧入口新 WAL。
- L1–L5：事件不丢工作、重复回答不重复判分、Step 接管不重发、结果与后续工作原子提交。
- pause→resume 后旧 operation／Admission 拒绝；同 operation 换新 epoch／Admission 也因重绑拒绝；新 operation 完成当前授权后才可继续。
- 旧 generation、错 input_digest／result_digest、错 policy_digest、跨版本回答均拒绝。
- acceptance_context 不提前释放数据库写串行化边界。
- recovered／conflict 不误归并 applied，WAL 后归并前崩溃按原 binding 续办。

**失败出口**：暂停恢复可绕过旧 epoch 或重绑原 operation、事件与后续工作分事务丢失，或 Runtime 出现第二套接受事实时停止。

### Task 4: 完成 Executor 最终接受与独立恢复

**Files**

- Modify: `tools/wiki_runtime/executor/core.py`
- Modify: `tools/wiki_runtime/executor/__init__.py`
- Create: `tools/tests/test_learning_s1_executor.py`
- Test: `tools/tests/fixtures/learning_s1/executor_process.py`

**Interfaces**

- Consumes: Task 1 的 barrier／公共 bundle lookup_terminal、Task 3 的 acceptance_context 与动态绑定。
- Produces: 扩展 `Executor.lookup_terminal(bundle, admission=None)` 的私有 Admission 校验；`Executor.apply(bundle, *, admission=None, approval=None, source_packages=())`；故障点 `after_acceptance_before_prepare`；完整恢复与结果归并。

**依赖**：Task 1–3。严格在 Task 1 后修改同一 Executor 文件；只有本任务才验收异 Admission 拒绝。

**实施步骤**

1. 在初始终态查询后，锁外完成 CandidateView、G0–G2、质量和 G3；所有 G3 调用走同一 InvocationPort。
2. 最终 executor.lock 内再查 journal／active，重建 CandidateView 并重跑 G0–G2、质量、依赖、目录、payload、规则和 G4。
3. 进入 acceptance_context，重验 operation→admission_digest、Task／Run、LearningState、deadline、预算、submission_epoch、policy、Readiness、授权、凭据和 fencing。
4. 在完整 WAL 前触发 after_acceptance_before_prepare；WAL 保存前不释放 SQLite 写串行化边界。
5. 保留现有文件应用、G5 和 recover；恢复不要求旧租约或当前可提交状态。

**验收**

- X1–X5：撤销／暂停／失效／换代／预算超额无 WAL，接受点崩溃可唯一判断，终态重放零新消耗；同公共 bundle 不同 Admission 拒绝。
- pause→resume 的旧 epoch 操作无 WAL；新 operation 未完成当前授权也不得接受。
- 仅在 Executor 接口级验证 approve 撤销与最终 G4／WAL 的唯一顺序，以及 ingest 授权不能代替 G4；真实 Host revoke_pending 的端到端撤销留到 Task 5，不在本任务提前宣称通过。
- recovered／conflict 保留现有语义，恢复不依赖 Runtime 租约。
- 现有公共契约和 Executor 回归通过。

**失败出口**：最终检查提前释放事务、锁内调用模型，或恢复受当前 Task／Run 动态状态阻断时停止。

### Task 5: 接入学习 Driver、Host 与静态 registry

**Files**

- Modify: `tools/wiki_runtime/coordinator/loop.py`
- Create: `tools/wiki_runtime/runtime/registry.py`
- Create: `tools/wiki_runtime/runtime/identity.py`
- Modify: `tools/wiki_runtime/rule_audit/core.py`
- Modify: `tools/wiki_runtime/host/supervisor.py`
- Modify: `tools/wiki_runtime/host/native.py`
- Modify: `tools/wiki_runtime/host/agent.py`
- Create: `tools/tests/fixtures/learning_s1/workflow.py`
- Create: `tools/tests/test_learning_s1_host.py`

**Interfaces**

- Consumes: Task 2 InvocationPort、Task 3 循环与授权、Task 4 Executor 接口。
- Produces: Step Driver；静态 CapabilityRegistry；合成学习工作流；RuleAuditor managed_call；Host 学习创建／事件／回答／暂停／恢复／授权／应用委托；可选 Attestation。

**依赖**：Task 1–4。

**实施步骤**

1. 仅核对 Task 3 已完成的 drain 结果与剩余 supersede 清单，不再首次 drain；Coordinator 重构为 Step Driver，不保留独立 calls／deadline／repair 权威，旧签名只作参数适配。
2. 所有 Worker／Reviewer／Auditor 调用统一 InvocationPort，并登记、领取和归并持久 Step；Invocation 成功而 StepResult 未归并时按原 Invocation 只读恢复。候选已冻结时按 round 找到唯一原 Worker Invocation，不重建本地请求或新增候选。候选目录存在不代表完整发布，candidate、payload、dependencies、manifest 逐份校验或从原结果补齐，已有不一致拒绝。Auditor managed_call 与旧 reserve_call 互斥，不嵌套双预留或双超时。
3. 实现最小静态 registry，不实现通用类型系统、插件权限矩阵、热更新或市场。
4. Host 学习入口只委托 Runtime，长 G3 与锁等待期间不持 Host 线程锁。
5. InheritedTransport 可选返回可信 Attestation；不可用时只形成 UnattestedReviewEvidence，Executor 独立重审。
6. approve 继续 ApprovalStore／G4，revoke_pending 先进入 Executor.acceptance_barrier。

**验收**

- 旧 pending 在 Task 3 已 drain 或明确留给 Task 6 supersede，不使用无条件预算回调，也不在 Task 4 后补走旧 G3。
- X6：同 Host 双线程与跨进程暂停／撤销不被长 G3 阻挡，Task 7 再做组合复验。
- X10 的 Host 端到端部分：真实 revoke_pending 与最终 G4／WAL 使用同一跨进程屏障，同 Host 双线程和跨进程撤销均有唯一顺序；不得只复用 Task 4 的接口测试结论。
- 学习链只有一套预算和调用记录；一次 Auditor 恰好一条 Invocation，新 Run 不刷新 repairs／appeals。
- 缺／错／撤销能力不会省略必需检查；静态注册表未扩张为插件平台。
- 无 Attestation 时 credential_reuse=disabled，真实 L3 不自动通过。
- 学习入口之外尚未迁移的旧流程明确标记给 Task 6，不提前宣称全局统一。

**失败出口**：Host 成为业务总控、测试替身冒充真实身份，或学习入口仍绕开 InvocationPort 时停止。

### Task 6: 完成旧 pending 与全局业务入口切变

**Files**

- Modify: `tools/wiki_runtime/runtime/migration.py`
- Modify: `tools/wiki_runtime/runtime/service.py`
- Modify: `tools/wiki_runtime/coordinator/loop.py`
- Modify: `tools/wiki_runtime/executor/core.py`
- Modify: `tools/wiki_runtime/host/cli.py`
- Modify: `tools/wiki_runtime/host/supervisor.py`
- Modify: `tools/wiki_runtime/host/derived.py`
- Modify: `tools/wiki_runtime/host/wechat.py`
- Modify: `tools/raw_index.py`
- Modify: `tools/heal.py`
- Modify: `tools/wechat_article.py`
- Modify: `tools/tests/test_health.py`
- Modify: `tools/tests/test_learning_s0_loop_protocol.py`
- Modify: `tools/tests/test_standalone_host.py`
- Modify: `tools/tests/test_learning_s1_cutover.py`
- Modify: `tools/tests/fixtures/learning_s0/legacy_inventory.json`
- Modify: `tools/tests/fixtures/learning_s1/legacy_cutover.py`
- Create: `tools/tests/test_learning_s1_entrypoints.py`

**Interfaces**

- Consumes: Task 1 旧 WAL 恢复、最小切变设施与五个写分支 freeze 约束、Task 5 新 Runtime 入口、Task 0 完整入口清单；真实旧 pending／Coordinator 记录。
- Produces: 扩展 `inspect_cutover(state_dir)`；`supersede_pending(operation_id, reason)`；带 created_generation 的 MaintenanceBinding、维护接受上下文与 WAL 归并；derived 与 Python API 内置工作流适配；一次性 cutover 报告。

**依赖**：Task 1–5。`host/supervisor.py` 在 Task 5 后顺序修改；`migration.py`、raw_index、heal、`test_health.py`、cutover 测试与夹具在 Task 1 基础上扩展。`executor/core.py` 只在 Task 4 的接受上下文上增加非学习维护绑定，`coordinator/loop.py` 只在 Task 5 后补充非学习投影，`runtime/service.py` 复用 Task 3 的短事务；均不另建第二套切变设施或保留第二写路径。

**实施步骤**

1. 保持旧 Host 进程停止和旧入口冻结，先运行 inspect_cutover 并枚举旧 pending／WAL；按 terminal、accepted_pending_recovery、pre_wal_pending 分类。
2. 已接受事务从原 journal_root 恢复或查询。Task 3 已 drain 的记录只核对；无法 drain 的 pre-WAL pending 标记 superseded_by_runtime_cutover，不以新 Runtime 伪造旧预算语义。
3. 不反造 Invocation；需要预算继承时记录 owner 批准的保守调整事件，不声称恢复精确历史。
4. 将 `host/cli.py` 的 raw-index／health／import-package 等 derived 写入流程接入内置 Runtime 工作流；纯只读查询保持只读。
5. 在 Task 1 的 freeze 约束上，将 `refresh_index`、`run_heal`、`heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 的生产写分支接入 Runtime，或保持直接写拒绝并要求受管入口；`apply=False` 与 `dry_run=True` 预览保持不变。legacy_write_guard 只用于旧写路径与切换点，不得包裹 Runtime／Executor 调用或长审查。补充五个 API 的写／只读回归。
6. inspect_cutover、supersede 与报告生成幂等，重启先检查再继续；分类后、supersede 后、drain 后和启用新路径前崩溃均可恢复。除 Task 3 清单内获准 drain operation 外，冻结后其他旧进程／旧入口不能创建 WAL。
7. 启用统一入口前逐项核对 Task 0 清单；旧签名仅作参数适配，不保留第二套可写循环。`test_health.py` 的旧写测试改为受管正例或直接写拒绝负例，只读断言保留，不以双运行时维持旧测试。

**验收**

- 真实旧 pending fixture 的每类记录都有确定去向，授权不被静默沿用，预算不被刷新或伪造。
- 旧 recovered 永久封闭，accepted_pending_recovery 可从原 root 恢复。
- C5：cutover 各崩溃点均可幂等续办；除获准 drain operation 外无新 WAL，且 drain WAL 的身份与 inventory 完全一致。
- C4：derived、`refresh_index` 及四个 heal 写分支均不再直接写正式文件；五个 API 的只读预览保持原行为，`test_health.py` 与新写语义一致。
- 新资料不能借非学习工作流免学习入库；入口清单没有遗漏，cutover 期间不存在两个可同时写入的权威运行时。
- 全局单路径声明有真实代码与 Python API 回归支撑。

**失败出口**：任何旧记录下落不明、任一清单内入口仍直接写入，或以删除旧状态完成切变时停止。

### Task 7: 执行组合故障矩阵、独立审查与交接

**Files**

- Create: `tools/tests/test_learning_s1_scenarios.py`
- Create: `tools/tests/fixtures/learning_s1/scenarios.json`
- Modify: `docs/design/learning-ingest-review.md`
- Modify: `docs/design/learning-ingest-stages.md`
- Modify: `docs/design/learning-ingest-handoff.md`
- Modify: `docs/design/README.md`
- Modify: `tools/wiki_runtime/coordinator/README.md`
- Modify: `tools/wiki_runtime/executor/README.md`
- Modify: `tools/wiki_runtime/host/HOST-INTEGRATION.md`

**Interfaces**

- Consumes: Task 0–6 的实现、真实故障证据、旧 WAL／pending 回归和宿主探针。
- Produces: S1 通过／失败结论、缺陷修复记录、S2 最小接口和未验证范围。

**依赖**：Task 0–6。

**实施步骤**

1. 汇总执行 X1–X12、L1–L9 以及 C1 旧 WAL、C2 旧 pending、C3 pause→resume、C4 derived 无旁路、C5 离线 cutover 崩溃重入场景。
2. 运行 S0／S1 目标测试、公共契约、相关 Host／Coordinator／Executor 测试和完整历史套件。
3. 由未参与实现的独立审查者核对真实代码、锁、SQLite、迁移和测试证据；先复现缺陷再有界修复。
4. 只有全部必需证据通过才更新 S1 状态；宿主能力缺失与合成记录单独标记。
5. 更新运行文档、审查记录、路线图与交接，不修改 AGENTS 或真实知识库。

**验收**

- X／L／C 全部通过，完整历史回归无相关失败，公共 v1 保持兼容。
- Health 八项零问题，`git diff --check` 通过。
- 独立审查覆盖旧 WAL、cutover、全局入口、公共契约和任务依赖，不仅检查新数据库路径。
- 交接列出实际命令、测试数量、跳过项、宿主限制和 S2 输入。

**失败出口**：以文档或合成工作流代替真实故障证据、独立阻断未关闭、文档状态超过实现时，S1 保持未完成。

## 4. 验证命令

程序使用 `<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，cwd 为项目根目录，所有 Python 命令使用 `-B`。S1 目标测试每命令 300 秒；完整历史套件 1800 秒。超时即失败，不重跑取最好结果。

```bash
python -B -m unittest discover -s tools/tests -p "test_learning_s0_loop_protocol.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_runtime.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_executor_compat.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_executor.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_host.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_cutover.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_entrypoints.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_scenarios.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s0_*.py" -v
python -B -m unittest discover -s tools/tests -p "test_runtime_contracts.py" -v
python -B -m unittest discover -s tools/tests -p "test_executor_recovery.py" -v
python -B -m unittest discover -s tools/tests -p "test_standalone_host.py" -v
python -B -m unittest discover -s tools/tests -p "test_bounded_loop.py" -v
python -B tools/health.py --json
```

完整回归：

```bash
python -B -m unittest discover -s tools/tests -p "test_*.py" -v
```

设计机械检查：

```bash
node <用户家目录>/.agents/skills/wf-plan/scripts/plan_lint.js docs/design/learning-ingest-s1-plan.md --root .
git diff --check
```

plan_lint 只检查任务书结构，不证明协议、锁、恢复或覆盖完整。

## 5. 需求—任务—门禁映射

| 需求 | 任务 | 主要验证 |
| --- | --- | --- |
| 循环协议与真实入口基线 | 0、7 | 协议负例、入口清单与独立审查 |
| 旧 WAL 定位与独立恢复 | 1、4、6、7 | C1、X2／X4／X5，旧 recovered 永久封闭 |
| SQLite 与单 Invocation | 2、3、5 | X3／X8，预算、并发、崩溃和重放 |
| 持久 Event／Step／Wait | 0、3、5、7 | L1–L5，接管不重复调用，回答版本有效 |
| 静态 registry 与有界重试 | 0、3、5、7 | L6／L7／L9，缺能力不跳门禁，无平台扩张 |
| 暂停恢复与 policy revision | 0、2、3、4 | C3、X1／X5，旧 epoch／policy 不得接受 |
| Executor 原子接受 | 1、3、4、5、7 | X1–X6，锁顺序与完整 WAL；X6 由 Task 5 验收 |
| 学习入口与身份降级 | 5、7 | X7／X12，单预算、无身份不放行真实 L3 |
| 旧 pending 与全局单路径 | 3、5、6、7 | C2／C4／C5，drain 先于 Task 4 G3 改造、derived 无旁路、cutover 可重入 |
| 公共契约与阶段边界 | 0、4、6、7 | 契约回归、合成标记、S2–S5 未验收记录 |

## 6. 材料需求与默认假设

现有代码和协议足以实施，不需要新增外部资料。工程假设如下：

1. 采用 SQLite 是对旧“不使用数据库”实现约束的明确替换，理由是跨进程、多记录原子更新；它不是外部数据库服务，也不改变 Executor 文件 WAL。
2. 单 Host 的现有 journal_root 是本期唯一 WAL 位置，不为假设中的多 root 需求建设注册表。
3. schema v1 只实现版本检查、未知拒绝与备份；真正出现 v2 时再单独评审迁移。
4. 无 Attestation 时 S1 可验证基础设施降级，但不代表真实 L3 或真实宿主身份链通过。
5. 现有 transport 可能无法强杀迟到调用；draining 能阻止超发，不能被描述为强制取消。
6. 合成 Readiness／Assessment 只驱动事务测试，S2 证据、S3 学习、S4 扩展和 S5 真实批次仍需各自验收。

## 7. S1 完成条件与停止条件

完成条件：Task 0–7 全部完成；X1–X12、L1–L9 与 C1–C5 真实证据通过；旧 WAL／pending 和全部业务入口完成切变；公共契约、完整回归和独立审查通过；运行文档、审查记录、路线图和交接更新。

以下任一情况阻断 S1：

- 旧 WAL 不可定位、旧 pending 下落不明，或 recovered 可重新接受。
- 仍有直接 Executor 业务入口，或宣称全局单路径但只覆盖学习入口。
- 事件已处理却丢后续工作、Step 接管重发旧调用、重复回答重复判分。
- 同 ID 活跃调用被接管、not_started 未占槽、unknown 退款／重发／提前释放资源。
- pause→resume 复用旧 submission_epoch，或 Invocation 使用失效 policy_digest。
- SQLite 被当作正式接受事实，最终检查提前释放串行化边界，或锁内调用模型。
- Executor 恢复依赖旧租约，recovered／conflict 被归并 applied。
- 静态 registry 扩张为插件平台，或 schema v1 被迫预建通用迁移框架。
- 无真实身份仍复用凭据，测试替身被当作产品宿主证据。
- 以合成记录宣称真实知识、学习或入库业务通过。
