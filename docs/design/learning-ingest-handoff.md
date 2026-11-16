---
type: meta
title: 学习型知识库改造交接
status: historical_record
updated: 2026-11-09
topic: 学习型入库改造交接
related_sources: []
related_synthesis: []
---

# 学习型知识库改造交接

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

更新日期：2026-11-09。这是工作进度快照，不替代 AGENTS，也不是阶段通过凭据。后续每阶段结束或换对话时更新本文件。

> **压缩后当前入口（2026-11-12）**：[知识准备链交接：K4 本地集成交付](knowledge-preparation-handoff.md)。先读该文；以下为各轮历史摘要，不能根据旧“下一步 S2／K0／K1／K2／K3／K4”重复启动已完成阶段。

> **2026-11-11 接手入口**：已完成 DeepTutor 学习消费链的限定集成与工程收尾，当前课程和待试学项见收尾记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-closeout/README.md）。针对来源策略、可信依据和新旧知识交叉印证尚未完整落地的缺口，新增[知识准备链方案与任务书](knowledge-preparation-plan.md)。用户明确选择先完成方案与任务书、再实施；本轮未开发业务代码、调用新模型或修改正式 raw／wiki。下一步先复核 K0 接口与旧 S2 差异，不照旧 S3 激活独立理解门禁，不重跑历史阶段。

> **学习规划补充**：用户已同意课程生成前结合知识库制定学习约定。任务书 §3.1.1–3.1.2 固定背景／学习证据分离、差距分析、用户认可及范围变更；K0／K1／K3 与 A19–A27 已同步。库中有内容不能当作独立掌握，原生确认接口不能替代真实认可；现有明确意图不重复询问。当前仅设计及准备工作单更新，自动门禁未实现。

> **整体拉通补充**：已完成[端到端设计自查与修订](knowledge-preparation-integration-review.md)，任务书 §2.1 和 §3.6 明确并行知识／学习路线、交付绑定、显式回顾及纠错；验收新增 A28–A33。总体方案已同步自有知识准备职责。下一步仍是 K0 接口细化，不重做 DeepTutor，不启动旧 L2，不将设计自查当成独立复审或实施验收。

> **K0 最新进度**：[接口契约](knowledge-preparation-k0-contracts.md)、29 项合成协议核对（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k0/README.md）及独立只读复审问题关闭（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k0/review.md）完成，可以实施 K1。已修订子集来源投影、外部编写讲义、实际上传投影审校、旧页变化失效及认可／审校作用域。脚本 tools/tests/verify_knowledge_preparation_k0.py 不调用模型，不认证用户／审查者，不提供生产门禁；33 项业务验收未执行，已有课程和正式 raw／wiki 未改。

> **K1 当前接手入口**：[使用说明](../../tools/wiki_runtime/evidence/README.md)及真实临时库／CLI／独立审查证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k1/README.md）。preparation.py 和 evidence/cli.py 已实现 inspect-context／check-context／draft-brief；29 项测试通过，历史版本与畸形 JSON 两个 P2 关闭。K1 仅有界读取本地原件和 wiki，material_available／unknown 不代表掌握，草案不代表认可；历史版本覆盖显式 previous 链而非全局注册库。下一步 K2 主张／证据／冲突核验，K2–K4 未实现。无新 API 调用，未操作已有课程或账本，宿主对话用量未知。

> **本轮讨论续接入口**：后续关于资料工作台、课件消费者与知识库解耦、Lattice 复用及 OpenMAIC／DeepTutor 选型的内容见[课件消费架构讨论交接](course-consumer-architecture-handoff.md)。该文不代表新架构已实施；另保存了一项晚于下述验收记录、需核实的同 Task 调度 P2 线索。压缩上下文后讨论新架构，先读该文。**上游源码研究已于 2026-11-09 执行完毕**，四份产物见[上游学习应用源码研究](research/upstream-learning/report.md)（待主 Agent 验收）。

> **最新状态**：S1「统一任务运行时与文件事务基础」最终修复版已验收通过。§34 的 5 项 P1、3 项 P2 与复审追加 P2，以及 §35 的 pending 队列和候选半写两项 P2 全部关闭，独立复审开放 P0／P1／P2 为零。最新完整历史共 38 个测试文件、612 项完成：三路分片 583 项全部退出码为 0，Executor 独立恢复 28 项通过、1 项 Windows symlink 权限跳过。下一步是 S2 最小知识证据链与 Wiki 候选的详细设计，尚未开始；真实宿主、真实 L3、教学质量、真实 scoped 状态及 S2–S5 均不在通过范围。

## 接手顺序

1. 读取 [AGENTS.md](../../AGENTS.md)，作为现行维护规则的唯一入口。
2. 读取 [阶段路线图](learning-ingest-stages.md) 的「跨阶段执行约定」、当前阶段及阶段总览。
3. 读取[总体方案](learning-gated-ingest-plan.md)的 §3、§10–13、§15，再读[持久循环协议](learning-ingest-runtime-loop.md)、[S1 任务书](learning-ingest-s1-plan.md)的 Global Constraints 与 Task 7，以及[审查记录](learning-ingest-review.md) §35。§29–34 和 S0 任务书只保留历史基线。
4. 先运行 `git status --short`，核对实际产物并保留所有已有修改和未跟踪文件；不回滚、清理、提交或推送，不处理父仓库无关配置。
5. 全程中文，路径使用完整绝对路径。cwd 为 `<知识库根目录>`。

## 用户目标与授权

- 新资料先提取与核验知识，再出课，之后练习、追问、补讲、独立理解验收；用户确认后才应用正式 Wiki 候选。不能先考用户未学的内容。
- 用户已同意按 S0–S5 分阶段推进，并明确要求多 SubAgent、Skill、渐进式披露、脚本沉淀及阶段门禁。范围内工作持续推进；不得跳过前置、擅改现行规则或自行接入需新权限的服务。
- 尽量并行处理独立任务，子 Agent 默认继承主模型且使用独立最小上下文。按需读 Skill，不自动安装技能；重复机械工作脚本化。
- 当前改造没有提交／推送授权。历史提交与推送不自动延伸至本轮。

## 当前架构与不可回退约束

- **统一运行时**：Task Runtime 统一 Event、Task、Run、Step、Invocation、Wait、WorkItem、预算、授权和恢复；Host 提供可信输入与身份，Coordinator 是 Step Driver，Executor 独立管理文件事务与恢复。
- **单账本**：一条 Invocation 原子检查 Task、Run、并发和最终留额；unknown 不退款、不自动重发，迟到完成只释放资源。`state.json` 仅为兼容投影，不能重置 calls、deadline、repairs、appeals 或候选轮次。
- **能力绑定**：静态 manifest 只包含能力 ID、实现摘要、契约版本、必需检查、用量可见性和取消能力；全部 manifest 纳入 Workflow 实现摘要，不做插件平台、热更新或市场。
- **审查身份**：只有 `InheritedTransport` 可提供绑定当前 request／session／role／独立上下文／冻结输入的 Attestation。无 Attestation 时仅保存 UnattestedReviewEvidence，`credential_reuse=disabled`，真实 L3 不自动通过。
- **最终接受**：顺序保持 `executor.lock → SQLite BEGIN IMMEDIATE`，完整 WAL 保存前不得释放 SQLite 写事务。WAL 保存 admission_digest，Admission 绑定完整 manifest_digest；applied 归并必须核验真实 applied WAL。
- **维护绑定**：非学习 derived／Host 使用 MaintenanceBinding，绑定 Task、Run、policy、submission_epoch、created_generation 和完整候选摘要；不得与学习 Admission 混用。普通维护无 LearningState，非学习 ingest 在模型前拒绝。
- **授权边界**：学习 ingest 使用 Runtime Authorization；approve 继续 ApprovalStore／ApprovalHandle／G4。重新授权在 Executor 屏障和同一 SQLite 事务内作废旧授权，已有 WAL 不得再签新授权；Host 不得回写旧 pending 引用。
- **暂停恢复**：pause 后 pre-WAL 旧 operation supersede，恢复使用同 Task 的新 operation／Admission／Authorization；已有 WAL 按原 operation 恢复，recovered 永久封闭。
- **恢复独立**：现有 `state_dir/private/journals` 和 active 路径不变；recover 不依赖 Runtime、Admission、MaintenanceBinding 或旧租约。终态先按原绑定查询，不得被当前 policy／provenance 阻断。

## T0–T6 已交付产物

- `runtime/protocol.py`、`runtime/loop_protocol.py`：封闭纯协议、版本绑定、摘要与重放校验；`tools/tests/fixtures/learning_s0/` 保存负向样例和真实入口清单。
- `runtime/storage.py`、`runtime/invocation.py`：SQLite v1、统一 Task／Run 财务与并发账本、条件发送、unknown／draining、接管、备份及关闭后禁止迟到连接。
- `runtime/loop.py`、`runtime/service.py`：持久 Event／Step／Wait／WorkItem、Readiness／Credential 投影、ingest Authorization、operation→Admission 与执行归并。
- `runtime/registry.py`、`runtime/identity.py`：静态能力校验、Workflow 能力摘要绑定、可选 Attestation 与不可复用审查证据。
- `coordinator/loop.py`：有界 Step Driver；Worker ID 绑定 operation、轮次、完整请求摘要和 attempt；RuleAuditor managed_call 无双预留／双超时。
- `host/supervisor.py`、`host/native.py`、`host/agent.py`：学习委托、锁外 G3、真实撤销、可选 Native Attestation。
- `executor/core.py`：公共 `lookup_terminal`、跨进程 `acceptance_barrier`、锁外受管 G3、最终原子接受与独立恢复；`verify_applied` 核验真实 WAL。
- `runtime/migration.py`：freeze、pending／WAL／active inventory、唯一白名单 drain、locator-only 幂等恢复与旧写入拒绝。
- `tools/tests/test_learning_s1_host.py` 与 `tools/tests/fixtures/learning_s1/workflow.py`：真实双线程／子进程撤销、暂停、授权竞争、能力与身份负例。
- `runtime/migration.py`：三类旧 pending 分类、pending HMAC、completed／accepted WAL 存在性核验、幂等 supersede 和全局切变报告；running receipt 仅显式 drain runner 可用。
- `runtime/service.py`、`host/derived.py`、`executor/core.py`：MaintenanceBinding、created_generation fencing、维护接受上下文、终态优先和封闭 WAL 结果归并。
- `host/cli.py`、`host/supervisor.py`、`host/wechat.py`：derived／普通维护统一 Runtime 委托，创建前切变检查，非学习 ingest 拒绝，Host 连接关闭。
- `tools/raw_index.py`、`tools/heal.py`、`tools/wechat_article.py`：公开与私有直写均永久拒绝，预览保留；微信 helper 封闭并纳入入口清单。
- `tools/tests/test_learning_s1_cutover.py`、`test_learning_s1_entrypoints.py`：WAL 失踪、runner 绕过、创建副作用、fencing、冲突伪造、直写旁路、接受及归并故障回归。

真实 scoped 目录最后一次只读复核仍是在 T3 开始前：`<本机运行状态目录>/inspool-design-docs-20261026` 中 `design-docs-graph-20261026` 为 applied 终态，active 已检查且为空，无 pre-WAL pending、孤立 WAL 或 drain 需求。未读取 pending.key、未验证 HMAC，未执行真实 freeze／recover／drain。**不要把历史快照当作新的实时检查，后续不得操作该真实状态。**

## T7 接手顺序

X1–X12、L1–L9、C1–C5 已完成，勿重做。`tools/tests/test_learning_s1_scenarios.py` 与 `fixtures/learning_s1/scenarios.json` 已建立完整 X／L／C 清单，三组原审查者均复审 passed。必须保留：Host 学习终态先按原 Admission 查 WAL；产品 Host 不暴露合成 Readiness／Credential 保存入口；通用规划不得自报 applied；unknown 接管前持久阻断；Readiness 重验知识版本；可信 Attestation 只能由 InheritedTransport 私有登记并一次性消费；cutover intent 与 freeze 摘要绑定，locator-only 与 intent-only 均不得放行旧写者或清单外 pending。

以下为 §33 的历史验收记录，已由 §34–35 的修复版验收取代：

1. T1–T6 合并 Ran 124、X／L／C 合并 Ran 26，全部通过；Executor 独立恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过。
2. 完整历史单进程在 X11 达到 1800 秒，无断言失败但不计为通过；随后以排序 round-robin 三路并行分片覆盖其余 37 个测试文件，全部退出码为 0，共 569 项。加独立恢复共 38 个文件、598 项。
3. 最终独立审查为 S1 overall passed、开放 P0／P1／P2 为零；S1 状态、运行文档、审查记录、路线图与本交接已更新。下一阶段为 S2 详细设计，不将 S1 通过外推到真实业务或 S2–S5。

## 压缩后执行与成本控制

- 本轮立即压缩上下文。接手只读本交接、S1 Task 7 和运行时 §8；不重读完整审查史、全部源码或全部设计文档，缺少哪个具体接口再定点读取。
- T7 按 X、L、C 三组场景推进，复用同一组合成夹具与临时库构造器。每组先写判定和原始负例，再实现并运行该组定点测试；不得为减少调用而跳过任何矩阵项。
- 代码和文档只做局部读取与清晰补丁，机械重复工作脚本化。独立审查绑定具体场景和原始探针，不把主执行者自审写成独立审查。
- 场景实现完成前不反复跑全量合并；每组跑定点回归，最终统一跑一次 T1–T7 合并和一次完整历史套件。若中途失败，修复后先复跑原失败路径，再按最终交付要求完成全量验证，失败运行不计为通过证据。
- 长测试后台执行并继续其他不冲突工作，不轮询、不重复等待；Executor 恢复仍单独运行。不得为了省 token 取消 T7 完整历史回归、真实子进程故障或独立审查。
- T6 会话日志估算总处理量约 1.158 亿 token，其中 cache read 约 1.143 亿、输出约 20.3 万，main 调用 335 次；主要浪费来自长上下文反复重发和重复回归。该数值不是套餐扣费或 5 小时占比，实际账单以 `/usage` 为准。开始 T7 时可记录 `/usage`，结束时用差值评估成本。

## 复验命令

Python：`<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`，全部使用 `-B`，cwd 为项目根目录。

```bash
python -B -m unittest tools.tests.test_learning_s1_executor_compat tools.tests.test_learning_s1_cutover tools.tests.test_learning_s1_runtime tools.tests.test_learning_s1_executor tools.tests.test_learning_s1_host tools.tests.test_bounded_loop tools.tests.test_learning_s1_entrypoints -v
python -B -m unittest discover -s tools/tests -p "test_learning_s1_scenarios.py" -v
python -B -m unittest discover -s tools/tests -p "test_learning_s0_*.py" -v
python -B -m unittest tools.tests.test_health tools.tests.test_legacy_entrypoints tools.tests.test_runtime_contracts -v
python -B -m unittest tools.tests.test_native_transport tools.tests.test_rule_audit tools.tests.test_host_cli tools.tests.test_wechat_rollout -v
python -B -m unittest discover -s tools/tests -p "test_executor_recovery.py" -v
python -B -m unittest discover -s tools/tests -p "test_*.py" -v
python -B tools/health.py --json
node <用户家目录>/.agents/skills/wf-plan/scripts/plan_lint.js docs/design/learning-ingest-s1-plan.md --root .
git diff --check
```

T7 场景文件创建后再运行对应命令。完整恢复回归单独运行，避免此前并行中断；完整历史套件上限 1800 秒，其他命令按实际基线设置超时，超时即失败。

## 当前验证与范围限制

- 修复版 T1–T6 合并 Ran 135、全部通过；最新完整历史中的 X／L／C 为 Ran 26、全部通过。新增覆盖跨 Host applied／recovered、Invocation 资格、Step 崩溃归并、后续定义改绑、当前策略、pending／blocked 队列隔离、候选半写恢复与浮点释放。
- S0 76 项通过；公共契约 Ran 47，46 项通过、1 项 Windows symlink 权限跳过；完整 StandaloneHost 19 项通过；Native／RuleAuditor／Host CLI／微信 Ran 44，43 项通过、1 项同类跳过。
- Executor 独立恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过，525.298 秒。
- 最新完整历史共 38 个测试文件、612 项完成：三路分片 37 个文件、583 项全部退出码为 0，加独立恢复 29 项。早期失败与超时仅作定位记录，不计为通过证据。
- Health 八项零问题；S1 plan_lint 为 0 ERROR／0 WARN（16 项跨任务顺序 INFO）；`git diff --check` 通过，仅既有换行提示。
- §34–35 独立审查及追加问题复核均 passed，开放 P0／P1／P2 为零。
- 未执行真实 scoped 状态的 freeze／recover／drain；未修改真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。会话日志 token 估算不等于套餐扣费，5 小时占比和实际账单未核实。
- S1 通过不外推为真实外部宿主 Attestation、真实 L3、教学质量、真实业务批次或 S2–S5 通过。

## 必须保留的边界

- 采用协作门禁，不重新开展完整 OS／工具隔离。严格 Codex Native 自动维护适配器仍关闭，完整真实模型自动闭环未验证。
- 默认学习期间 raw 保持 unprocessed；正式 Wiki／索引不应用候选。通过学习且用户确认后拟进入 pending_review；归档 processed 仍需具体批次 approve。
- raw 正文只读；开发只用临时库与合成／明确允许样本。历史 pending_review／processed 不回退、不补造理解记录。
- 现有 MISSION／NOTES／RESOURCES、lessons、reference 是独立 teach 学习资产，不覆盖或静默迁移。
- 保留全部已有修改和未跟踪文件；父仓库 `../.claude/settings.local.json` 是无关未跟踪文件，不处理、不暂存。
- 失败只做有界修复，生成者不得放宽门禁；每阶段先取得真实测试与独立审查证据，再更新本交接文件。