---
type: meta
title: 学习型知识库的持久循环与受控扩展设计
status: proposed
updated: 2026-11-08
topic: 持久事件、可恢复步骤、事务存储与受控能力
---

# 学习型知识库的持久循环与受控扩展设计

## 1. 决策、范围与当前状态

本文件把 agent-autoloop 调研及后续架构审查结论落实为设计，配套[主方案](learning-gated-ingest-plan.md)、[路线图](learning-ingest-stages.md)和[S1 任务书](learning-ingest-s1-plan.md)。它是运行时协议依据，不另设实施阶段或第二套运行时。S1 的 T0–T6 已完成各自验收，T7 组合验收尚未实施；未处理真实 raw／Wiki，未改变 AGENTS 或公共契约。

采用持久事件、可恢复业务步骤、SQLite 单一权威账本、静态可信能力注册和统一提交端口。学习入库与全部业务维护入口均已委托 Runtime；不建设第三方插件市场、自动安装、热替换、工作流 DSL、分布式调度、通用事件图或完整事件溯源框架。

单一权威账本是架构约束，单份 JSON 不是。S0 历史 59 项目标测试与历史回归只证明当时的纯协议；T0–T6 已分别取得协议、SQLite、持久循环、最终接受、学习 Driver、真实 Host 撤销、旧 pending 切变和全局入口的新证据，不能外推为 T7 完整故障矩阵通过。最新状态见审查记录 §23–28。

## 2. 架构与唯一职责

```text
Host / CLI：可信用户输入、身份、宿主模型／工具／参数适配
  ↓ 认证事件与能力元数据
Task Runtime
  ├─ Event 接收、去重、直接因果关系与待处理状态
  ├─ Task / Run / Step / Invocation / Wait / WorkItem
  ├─ 调度、预算、执行所有权、停止策略与审计
  ├─ 可信策略、凭据绑定、授权及提交资格
  └─ SQLite：状态、事件、工作项与预算的统一事务存储
  ↓ 明确的步骤请求                  ↑ 校验后的步骤结果
Driver + 静态注册的工作流／能力实现
  ├─ Evidence / Output / Learning / Persistence 领域模块
  ├─ Agent、检索、解析与通知适配器
  └─ 提交端口 → Wiki Executor：最终接受、完整 WAL、写入与独立恢复
```

内核不理解某课答案或某主张真假。领域模块提供语义判断；内核统一核验身份、版本、范围、必需检查集合及状态绑定。能力实现能提出下一步，不能自行修改预算、授予权限、取消必需门禁或写正式 Wiki。一个模块可以提供多个能力，不按角色数或函数数拆包。

### 2.1 三种循环

| 循环 | 所有者 | 边界 |
| --- | --- | --- |
| 任务循环 | Runtime | 事件、状态、步骤、等待、领取、恢复和总预算 |
| Agent 内部推理与工具循环 | 可信宿主／Agent 适配器 | 在本次 Invocation 的工具范围与时间上限内运行，返回可信用量和结束证据 |
| 生成—审查—修复循环 | 工作流定义、Runtime 调度 | 持久化缺口与产物，每次尝试统一记账，不能另设重试账本 |

能力实现、宿主和 Driver 不得同时管理相同调用的超时／退款／重发。宿主内部不可观测的工具调用不能宣称已逐项预留；能力描述必须标记 `usage_visibility` 和可执行的限制层级。不可执行的精确限制记 unknown 或阻断依赖该限制的动作，不能按零计费；语义重试与回执修复也计入统一额度。

## 3. 实体、身份与最小契约

下表是协议增量的必需语义，封闭字段及解析器由 Task 0 固定，不把示意名称当作已存在代码。

| 实体 | 必需绑定与状态 |
| --- | --- |
| RuntimeTask | 稳定 task_id、workflow_ref、current_policy_digest、submission_epoch、revision；执行状态 ready／running／waiting／paused／blocked／completed／canceled |
| LearningState | 同一 Task 下的 preparing／studying／assessing 等领域阶段及知识版本；由学习工作流维护，不硬编码进通用 Task 枚举 |
| Event | event_id、可信 producer、type、task_id、payload_digest／引用、可选直接 causation_id、目标版本、接收序号及处理状态 |
| Step | step_id、task_id、能力及实现版本、input_digest、依赖产物、attempt、执行代次、状态及结果摘要 |
| WorkItem | 所属 Task／Step、ready_at、唯一调度键、claimed_by／generation／lease、待执行／已领取／完成／阻断状态 |
| Wait | wait_id、问题或条件类型、目标 Step、知识／问题／rubric 版本、回答策略、消费状态及继续条件 |
| StepResult | step_id、attempt、generation、input_digest、result_digest、产物摘要、业务变更提案、等待／后续请求或结构化失败 |
| PolicyRevision | revision、policy_digest、不可变预算／停止策略和创建原因；Task 只切换当前 revision |
| WorkflowRef | 可信工作流 ID、实现摘要、契约版本、必需检查与允许能力集合；由创建任务时的可信策略固定 |

Run 是一次有界活动执行，可执行多个步骤；Step 是业务进度，Invocation 是一次实际外部调用。新 Run 不生成新的长期预算；新 Step attempt 不复用旧外部调用 ID。已完成 Step 只有在全部依赖仍有效且本步骤允许复用时才能复用产物。Invocation、Admission 和 Authorization 记录 policy_digest，防止预算策略被原地替换。

S0 原 Task.state 中的教学阶段改为 LearningState；现有 `learning_task_id` 作为业务关联保留，不能通过模型自报串接另一 Task。S0 解析器、夹具、摘要和消费者统一切换，不长期维护两套权威 Task。历史 S0 测试记录保留原范围，新增协议独立取得通过证据。

### 3.1 事件与回答

1. 去重键为可信 producer＋event_id。另以 task_id、type、目标版本和 payload_digest 计算不可变业务信封摘要，排除接收序号与处理状态；同键同信封返回原确认，同键不同信封报冲突。即使 payload 相同，改投另一 Task、type 或目标版本也不得返回旧确认。
2. 输入事件只能携带资料或经认证的用户意图，不能指定能力路径、shell 命令、身份、预算或放行策略。时间、随机材料、身份元数据由外层传入。
3. 接收事件、记录接收序号及持久待处理标记在同一数据库事务完成；接受不等于业务处理已完成。驱动器按序读待处理事件，基于 revision 在短事务中完成处理标记、状态迁移及工作项登记。任一事务崩溃均可从持久状态继续，不依靠内存队列。
4. 工作流规划在事务外读取冻结快照，只产生有界提案；提交时重验 Task revision、Step generation、依赖和策略。冲突则重新规划，不重复已确认副作用。不得在数据库事务内执行任意能力实现、模型、网络或用户交互。
5. Wait 接受答案时原子检查身份、问题版本及未消费状态，并登记回答和后续工作。重复回答不重复判分。修改答案需要新回答修订；已经判分的原证据保留，不能覆盖。
6. 过期或错误知识版本的回答可保留为审计资料，但不能推进当前版本。证据变化与旧答案同时到达时，后续 Step 提交及 Readiness 签发必须重验依赖版本，不能只依赖事件到达顺序。
7. 本期只合并同对象、同内容的重复通知；用户答案、授权和不同版本证据不能静默合并。通用事件合并和 correlation／causation 图不在 S1 建设。

### 3.2 步骤、领取与结果

步骤按有价值的恢复边界划分，如提取主张、生成课程、独立审查、等待作答、理解验收、编译候选；不把每个函数或模型 token 当步骤。

工作项领取、Step attempt／generation 分配、运行资格及调度并发检查原子完成；执行发生在事务外。所有外部调用仍经 InvocationPort 原子检查财务与资源额度；领取工作不代表已取得模型并发槽。S1 串行执行同 Task 的领域变更，跨 Task 的并发受统一限制；不建设并行图调度。

结果以 `(step_id, attempt, generation)` 作为原确认键，并原子绑定 input_digest 和 result_digest。同键同摘要重放返回原确认，同键不同摘要拒绝；旧执行者或失效依赖不能覆盖当前 Step。后续工作的每项摘要同时绑定 Step 不可变定义与 WorkItem，接管者不能保持原结果摘要却改绑后续输入。保存产物引用、领域状态、审计和后续工作项是同一事务。调用已经完成而结果尚未归并时，先按原 Invocation 查询／重放，不能仅因 WorkItem 租约到期重新发送。

WorkItem 接管只增加 generation，不自动增加业务 Step attempt。旧 attempt 已发出的 Invocation 保留调用 ID、原绑定和财务记录；新 generation 取得受控的只读恢复绑定，经 InvocationPort 核验原请求／结果并重验当前依赖后，生成当前 generation 的 StepResult，不直接接纳旧执行者的自报结果。Task 业务所有权换代不改变原 Invocation 的身份归属。成功结果可以归并；原 Invocation 仍为 pending 时只在本次扫描中跳过该 Task，继续其他 Task，不得抛错阻断全局队列或重新发送；unknown 保持阻断，不伪造结果。若依赖失效则保留旧产物并由工作流决定新尝试。只有策略许可的新业务尝试才增加 attempt，并为新的实际外部调用分配新 ID 和额度。

Step 完成只表示该步骤结果已接受，不表示知识正确、用户掌握、授权通过或文件已应用。只有可信身份与完整版本绑定的领域凭据，才能满足工作流规定的检查。回执格式修复只修改表达，不重做业务；每次修复调用独立记账、有固定次数上限，修复失败保留原业务状态和待处理原文。

## 4. SQLite、现有 WAL 与切变

单个受控运行目录使用 `.wiki-runtime/learning/runtime.db`，同目录保留 runtime.key 及有界不可变 artifacts；不新增数据库服务。SQLite 使用明确事务控制、WAL、synchronous=FULL、foreign_keys=ON、有限 busy_timeout；关键预留、领取、提交使用短写事务与条件更新。每进程／线程持有自己的连接；不在外部调用期间占用写事务。

权威状态是当前状态表；events／audit 是同事务追加的审计与持久输入，WorkItem 是同库待执行工作。它们不构成多套可独立写入的任务真值。不承诺只靠有界审计重建全部状态，不引入另一条 JSONL 权威日志。任务和调用数据增长通过索引与按需查询处理，不每次读取扫描、解析全部历史。

唯一约束保护事件键、步骤结果键、工作项调度键、Invocation ID 和 operation→admission_digest。业务记录按接口进行 schema／身份／摘要校验；授权、Admission、凭据等跨边界记录保留规范摘要及必要 HMAC，不能把旧的整份 JSON HMAC 直接视为数据库认证。协作边界下不承诺防同权限恶意进程改库。

不可变产物先完整写入、校验摘要，再在事务中发布引用；崩溃留下的未引用文件只作为孤儿清理，不能推导业务成功。外部消息或其他副作用通过持久工作项／投递记录派发，使用提供方幂等键；提供方不支持时保留未知结果并核实，不能宣称恰好一次。

schema v1 使用明确版本并在每次写入前核对，未知版本拒绝；出现 v2 需求时才另行评审事务性迁移，不在 S1 预建通用升级框架。备份使用 SQLite backup API 或停写检查点后的完整备份，不直接复制正在写入的主 db 文件。先固定数据库快照，再复制该快照引用的 artifacts 与配套密钥，期间禁止删除被引用产物。数据库／密钥损坏、版本不兼容或产物缺失时阻断，不自动重置。事件明细的保留／压缩不能删除在途任务的去重键、结果摘要、授权与恢复绑定。

### 4.1 现有 WAL 定位与旧 pending

当前 Host 的 Executor journal_root 是 `state_dir/private/journals`，active 是 `.wiki-runtime/executor-active.json`，锁是 `.wiki-runtime/executor.lock`。这些路径不得因新增 runtime.db 而静默改变。本版继续复用已配置的单一 journal_root，不建立多 root 注册表；Executor.lookup_terminal、apply 和 recover 必须从同一 root 定位完整 WAL。

旧 pending 采用 offline cutover：Task 3 在 Task 4 改造 G3 前停止全部旧 Host 进程，冻结新操作创建及未登记 apply，唯一离线 drain runner 用原预算回调与 Executor 处理 inventory 中可继续的 pre-WAL pending。runner 只能为清单内 operation 创建身份一致的 WAL，其他旧入口写入全部拒绝。无法取得原预算语义的记录留给 Task 6 标记 `superseded_by_runtime_cutover`，随后以新 Task、operation、Readiness 和 Authorization 重新确认。已接受 WAL 从原 root 恢复或查询。旧 calls 等聚合历史不能反造 Invocation；预算必须继承时只允许 owner 批准的保守调整事件。`inspect_cutover` 与 supersede 幂等，重启先检查再继续；任何旧记录下落不明，或获准 drain 之外的旧进程创建 WAL，都阻断新写入路径。

五个 Python API 写分支使用 `legacy_write_guard(root, operation_id=None)`，在同一 executor.lock 内完成资格检查并覆盖全部实际文件写入；不能先 assert 后释放锁再写。freeze 在同一锁内等待已登记写者退出后发布描述，之后新写者不得进入。`run_heal` 外层与辅助函数共享同一 guard，禁止嵌套获取非重入锁。T6 的受管委托只在切换点使用该 guard，不包裹 Runtime／Executor 调用。

## 5. 必须保留的接受屏障

数据库 WAL 与 Wiki Executor 完整 WAL 的职责不同。数据库事务不能原子提交任意 Wiki 文件；Executor 完整 WAL 仍是唯一正式接受事实。

锁顺序固定为 `executor.lock → SQLite transaction`。普通 Runtime 事务不得反向等待 Executor 锁。最终接受、Runtime 授权撤销、ApprovalStore 撤销、Task 暂停、Readiness 失效和所有权强制换代共用 executor.lock；任一入口等待锁或数据库 busy 均有界且不能先报告成功。

最终接受在 executor.lock 下开启 Runtime 的 BEGIN IMMEDIATE 短事务，复验 Task／Run、deadline、预算、版本、授权与 fencing；在同一屏障内保存完整 Executor WAL，再释放事务与锁。该事务取得写串行化边界但不另写 accepted 状态，也不对“数据库提交＋文件 WAL”做两阶段伪提交。支持修改这些最终条件的入口必须遵守该屏障；可增加预算阻断的结算等普通写入与本短事务串行化，外部调用始终在锁外。

Task 暂停时在同一屏障内递增 submission_epoch，并将已有 execution binding 的 pre-WAL 操作标记 `superseded_by_pause`。Admission 与 Authorization 绑定创建时 epoch；pause→resume 后旧 epoch 仍失效，同 operation 也不得换 Admission 重绑。恢复后在同一 Task 下使用新 operation_id、新 Admission 和新 Authorization；有效 Readiness 按依赖复核复用。已有 WAL 始终按原 operation 恢复，终态重放豁免动态检查。

WAL 前崩溃是未接受；完整 WAL 后崩溃是已接受。operation→admission_digest 在进入 Executor 前持久化，Admission 同时绑定完整 manifest_digest，WAL 保存该 Admission 摘要；WAL 后 Runtime 结果尚未归并时按原绑定查询恢复。applied 归并必须由 Executor 核对真实 applied WAL、Admission 摘要与公共绑定，不能凭提交记录消费授权。恢复不依赖旧 Run、预算或 Task 租约；applied／recovered 终态重放优先于动态预检。recovered／conflict 不冒充应用成功。ingest 与 approve 保留不同授权、operation 和真实 G4；S1 不激活 capture/import 授权。

## 6. 受控扩展接口与策略

| 接口类型 | 作用 | 不能做 |
| --- | --- | --- |
| 工作流 | 定义领域步骤、依赖、等待条件与领域状态解析 | 动态删除固定必需门禁，另建调度与预算 |
| 能力 | 检索、抽取、课程、验收、候选编译等有界执行 | 自签身份或批准、直接改库、访问其他能力私有状态 |
| 适配器 | Agent、模型、工具、来源、渠道接入 | 从外部文本加载命令或自动授予新权限 |
| 提交后端 | 在授权范围内执行持久副作用与恢复 | 把普通 StepResult 当作已接受文件事务 |

S1 的静态 manifest 只声明能力 ID、实现摘要、契约版本、必需检查、可观测用量和取消／结束确认能力。可信本地 registry 显式注册并检查缺失／冲突能力。权限由可信代码、角色端口和允许产物目录固定，不另建通用插件权限矩阵或输入输出类型系统。能力实现只取得本次所需端口与冻结输入，不取得任意数据库连接；这是可信代码的协作约束，不是同进程安全隔离。

创建 Task 时固定工作流及能力实现版本、必需检查集合、角色分离规则、允许工具、预算和停止策略，形成不可变 PolicyRevision。策略来自可信配置，不能只信能力实现的自报 manifest。缺少必需实现、实现摘要变化或版本撤销时阻断新执行。预算或策略变化创建新 revision，Task 显式切换 current_policy_digest；Invocation 保留使用时的 policy_digest。既有实现迁移需要显式事件、兼容性校验、受影响产物／凭据失效和必要的新确认，不能自动热替换。

S1 仅实现合成工作流及最小注册协议来验证运行时，真实证据与教学仍在 S2／S3。现有领域目录作为内置能力提供实现，无须统一搬入 plugins/。学习工作流要求理解验收；文章输出工作流不要求学习但仍有证据与发布约束。选择工作流不能成为把新资料免学习写入正式 Wiki 的旁路，既有非学习维护只按现行授权范围接入。

## 7. 预算、进展与停止

保留单 Invocation 原子预留：Task／Run 财务、并发及最终 G3 留额同事务检查；not_started 在预留成功时即占位，inflight／draining 也占资源，unknown 保守结算且不退款／重发；旧调用资源未释放时新尝试仍受限制。Task 所有权和 Invocation execution_token／recovery_epoch 分离。

RetryPolicy 只包含错误类别、失败指纹、attempt 上限、not_before 和停止原因。环境失败有限退避；内容失败只修具体缺口；证据不足转补证／等待；无用户回答保持等待。相同输入与失败指纹达到固定阈值即阻断，不另建通用“工作流进展声明”机制。改写措辞、轮换工具或开新 Run 不刷新总预算和重试次数。

派生事件深度只是辅助保险，不能替代 Task 总调用、活动时间、修复、申诉与步骤 attempt 上限。等待不占活动时间，也不保持 Agent 阻塞进程；预算耗尽不自动缩减必需检查。审计贯通 Task→Event→Step→Invocation→artifact／Credential→operation→Executor 结果，不要求模型暴露内部思维链。

## 8. 单路径与阶段验收

所有业务写入入口最终统一委托 Runtime，包括 `host/cli.py` 的 derived 流程、`refresh_index(apply=True)`、`run_heal(dry_run=False)`，以及 `heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 的 dry_run=False 分支；只读查询及 `apply=False`／`dry_run=True` 预览不强制建模为写入工作流，且保持原行为。旧 CLI／Host 如保留只做参数适配。Coordinator 重构为 Driver，不保留独立 calls／deadline／repair 权威。是否保留旧函数签名取决于真实调用方，不为旧测试创建第二运行时。纯验证器、CandidateView、Executor 和 ApprovalStore 的职责继续保留。

S1 按 T0–T7 执行：协议与完整入口基线；Executor 恢复兼容、最小 freeze／inventory／runner／重启检查及五个 Python API 写分支的 freeze 拒绝；SQLite／Invocation；持久循环与真实 drain；最终接受；学习入口与真实 Host 撤销；旧 pending、Python API 与全局切变；组合验收。Executor 兼容与 SQLite 可并行，其他任务按依赖推进。全局单路径只有在全部清单入口和旧 pending 均切变后才能声明，不以学习入口统一代替。详细文件、接口和门禁见[S1 任务书](learning-ingest-s1-plan.md)。

S1 必须用真实临时数据库、双进程和故障屏障覆盖以下 X1–X12、L1–L9、C1–C5：

| 编号 | 场景 | 必须观察到的结果 |
| --- | --- | --- |
| X1 | 锁外 G3 中撤销／暂停／Readiness 失效／换代／预算超额 | 状态变化真实完成，首个 WAL 不存在，正式文件不变 |
| X2 | 接受点附近崩溃 | 无完整 WAL 为未接受；有完整 WAL 独立恢复；WAL 后、归并前崩溃按原 Admission 续办 |
| X3 | Invocation 崩溃、活跃重入与重放 | 双线程／跨进程同 ID 不重复执行；杀死执行者后按证据接管；不重复扣减 |
| X4 | prepared／applying／recovery_required／recovered | Runtime 不误标 applied；原 operation 可恢复 |
| X5 | applied／recovered 终态重放 | 过期、暂停、预算阻断、库变化下仍无审查、无预算、无新写入；同 bundle 不同 Admission 拒绝 |
| X6 | 同 Host 双线程与跨进程撤销／暂停 | 两条路径均不被长 G3 阻挡，并与接受有唯一顺序；由 Task 5 验收 |
| X7 | 身份与凭据负向样例 | 自签、缺角色、跨作用域、错候选均拒绝；无探针则独立重审且真实 L3 不自动通过 |
| X8 | 并发资源与最终留额 | 最后财务额度或并发槽仅一个预留成功；not_started 占位；超时与崩溃接管强制 draining，迟到完成只释放资源 |
| X9 | 恢复冲突 | recovery_required＋conflict 投影人工对账，不覆盖后续编辑 |
| X10 | ingest／approve 授权与撤销边界 | ingest 授权不能通过 G4；approve 不自动签发；Task 4 验 Executor 接口顺序，Task 5 验真实 Host revoke_pending 与跨进程撤销 |
| X11 | 接受后撤销与归档后修正 | 历史不变，只能新建补偿操作与授权 |
| X12 | Host／Coordinator 权限边界 | 不能改权威余额或审查状态；旧计数不影响 Runtime 余额 |
| L1 | 事件重复／同键异内容、提交后响应丢失 | 一条输入事实；冲突拒绝；原确认可重放 |
| L2 | 接收后未规划、规划后未提交、状态与工作项提交后崩溃 | 无已完成状态但漏工作；重启继续，不依赖内存队列 |
| L3 | 双进程领取、执行者失联、旧 generation 结果 | 单赢家；旧结果拒绝；换代后经原 Invocation 成功归并，不新增调用或预留；unknown 不重发 |
| L4 | 重复回答、回答与失效竞争、答案修订 | 不重复判分；旧版本不能推动当前 Readiness |
| L5 | 结果保存后未派下一步、相同结果重放／异结果重放 | 产物／领域状态／后续工作一致；异结果冲突 |
| L6 | 依赖变化、能力缺失／撤销／摘要变化、版本迁移 | 必需检查不被跳过；原凭据不得跨版本复用 |
| L7 | 重启、无进展修复、格式修复失败、等待用户 | 不刷新预算／attempt；不重做已完成业务；有界停止 |
| L8 | db busy、事务回滚、产物孤儿、备份与未知 schema | 有界失败、不假报成功、不重置账本；恢复原绑定 |
| L9 | Host／Driver／能力实现尝试绕过统一调用或自报批准 | 受控接口拒绝；不可观测宿主限制如实标记 |
| C1 | 旧 prepared／applying／applied／recovered WAL | 原 journal_root 可查询／恢复，recovered 永久封闭 |
| C2 | 旧 pending 切变 | 每类记录有去向，不伪造 Invocation 或刷新授权／预算；drain 先于 Task 4 G3 改造及 Task 5 Coordinator 重构 |
| C3 | G3 中暂停后恢复 | 旧 operation／epoch 拒绝；同 operation 换 Admission 拒绝；新 operation 完成当前授权后可接受 |
| C4 | derived 与 Python API 入口 | derived、`refresh_index`、`run_heal`、`heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 均不直接写正式文件；只读预览保持原行为 |
| C5 | 离线 cutover 中断、写者与旧进程竞争 | 分类、supersede、drain、启用前崩溃均幂等续办；写者检查后暂停时 freeze 等待且无迟到写入，freeze 后新写者拒绝；除获准 drain 外无新 WAL |

这些场景证明运行机制，不证明真实知识正确或教学有效。S3 必需校准、独立作答及 S5 的成本／用户负担评估不后移、不取消。未完成协议、设计复审和真实故障矩阵时，不得沿用历史 passed 放行。

## 9. 参考与取舍依据

- [agent-autoloop 协议](https://github.com/KKKKhazix/agent-autoloop/blob/main/docs/protocol.md)、[调度](https://github.com/KKKKhazix/agent-autoloop/blob/main/kernel/decide.ts)、[事务实现](https://github.com/KKKKhazix/agent-autoloop/blob/main/kernel/store.ts)：参考事件唤醒、回执、领取及事务边界。未引入依赖、未运行上游，也未固定上游 commit；实施若直接取用代码需另核对具体提交与契约。
- [OpenAI 编排](https://developers.openai.com/api/docs/guides/agents/orchestration)、[门禁与人工审查](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)、[工作流评估](https://developers.openai.com/api/docs/guides/agent-evals)：参考有界专家能力、贴近副作用的检查及执行轨迹，不要求采用 SDK。
- [Anthropic：Building effective agents](https://www.anthropic.com/research/building-effective-agents)：参考确定性工作流与局部自主循环、简单可组合设计；这是工程原则，不作为当前工具版本说明。
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)：参考本地嵌入式事务存储。SQLite 不代替 Executor 文件 WAL，也不自动提供任意外部副作用的恰好一次保证。

以上为本会话 2026-11-04 的只读调研依据，2026-11-06 落盘；动态网页不是本项目的合规认证或已完成实测。通用插件平台、完整事件溯源、通用事件图、过早 schema 迁移框架和双权威运行路径均因当前缺少决定性收益而不采用。
