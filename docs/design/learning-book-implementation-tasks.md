---
type: meta
title: Book 学习闭环实施任务书
status: historical_playbook
updated: 2026-11-09
topic: 学习底座各阶段的任务拆分
related_sources: []
related_synthesis: []
---

# Book 学习闭环实施任务书

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

后续执行入口为 [本地学习系统收尾计划](learning-book-local-use-closeout-plan.md)。运行监督、中断恢复、安装备份及课程准备入口已交付；获授权的 六章架构课程（未随本仓库发布：docs/learning/system-architecture/README.md）已发布，内容审查与学习前基线通过，见 本轮验收与继续入口（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-closeout/README.md）。T5 用户亲自试学及原生追问待完成，无需重复请求既有课程发送授权。I6 的有限通过记录继续保留。

更新：2026-11-11。状态：I0/I1 已通过，I2 **有限通过**，I3～I5 本地与 HTTP 契约通过，I6-A～D 的真实生产、经审校课件、原生学习、恢复和交接闭环 **有限通过**。见 I6 最终验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/acceptance.md）、token 审计（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/token-audit.md）与 [任务书](learning-book-i6-plan.md)。原始准备依据保留在 前置验证（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-preflight/README.md）、模型配置（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-setup/README.md） 与 套餐/预算核对（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-setup/quota-budget.md）。总体设计见 [D1–D3 收敛结论](research/upstream-learning/design-convergence/design-summary.md)、[总体方案](research/upstream-learning/architecture-proposal.md)。旧阶段记录保留。

当前分工：首轮由外部 Agent 执行，主 Agent 已接手完成剩余修复与复验。见 最终报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-final.md）；[I2 交接](learning-book-i2-handoff.md)保留原要求，不作为可直接重跑的启动指令。

**I5 完成时入口**：[I5 详细任务书](learning-book-i5-plan.md)与 完整验收／C01–C20（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）。I5-A～E 已完成，174 项项目测试及上游 learning-state 25 项源码／wheel 复测、content 19 项、session/SQLite 9 项通过；普通应用方法、两 CLI、schema、正常／partial 包、实际进程恢复／锁和搬移验证均已交付。使用见 [HANDOFF](../../tools/learning_book/HANDOFF.md)。下一步 I6 真实部署和生产学习集成；未安装或启动既有实例，真实模型／embedding 调用为 0。A/B 与设计核对保留，不覆盖历史。

**I3/I4 完成时记录**：[I3 模块／CLI](../../tools/learning_book/README.md)、[I3 任务书](learning-book-i3-plan.md)及 验收证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i3/README.md）。36 项测试覆盖 A01–A16，包括实际子进程崩溃／竞争／停止及去敏回放；真实适配写入待后续新额度及 I6 集成，不自动生成课程。I4 的只读接口、内容快照、资源核对和审查绑定已实现，见 I4 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）（项目 29 项、上游 19 项源码／wheel 复测通过），未安装到既有服务；I5-A～E 已通过，I6 尚未实施。

**I2 历史验收状态**：真实页边教学问答及会话重启恢复已补齐，续测新增 3 次调用（用量见本机账本），低于获准的 30,000。预算守卫及 Windows venv 停止链已修复，17 项回归通过。首轮超额（数值见本机账本）、生成忠实性缺陷、原生首答 500 等历史／产品限制保留；Key 未轮换，用户明确授权当次继续使用。旧额度不恢复；本轮仅推进另获授权的 I3 本地实现。

## 1. 目标和本次执行边界

先确认所选 DeepTutor 组合实际能运行，再实现资料交付、基线与学习结果交接。首个用户流程为：明确整理资料 → 小型交互书 → 网页阅读/页边追问/单答案选择题 → 重开恢复 → 外部 Agent 消费真实记录。上游负责学习真值，项目不维护第二套可写 progress。

I0/I1 已完成；I2 首轮曾验收需修复，现已完成修复和限定续测、有限通过。可依据已验证的主链细化 I3–I6，保留已知缺陷作为范围和质量门禁，不直接开发完整适配器或启用所有上游产品／模式。

可提交的产物：任务书、去敏验证记录与必要的项目代码/测试。当前验证使用 `<本机验证目录>`，已在本仓忽略；其中的虚拟环境、工具、缓存、runtime、配置和原始日志不提交。不得修改正式 raw/wiki/AGENTS 或把它们设为应用可写 workspace。保留现有脏文件，不更新上游提交，不修改全局 Python/Node 或已有模型设置。

## 2. 基线、组件和组织

- 上游：DeepTutor `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`，源码版本 `1.7.2`；研究文档中的 1.7.0 是模块布局说明，不是当前版本 pin。
- 功能闭包：core、server、Web、books、knowledge、parsing、questions、visualize、mastery。优先本地固定源码构建独立 wheels，避免源码全仓暴露模块却只安装部分依赖。
- 工具链：上游支持 Python 3.11–3.14，指导使用 Node 22 LTS；本机默认 Python 3.15 不符合要求，不强行安装。验证工具链放隔离目录。
- Python 模块与源码 Web 是允许的组合，但必须记录 Web 来自相同提交。若采用打包 Web，必须先实际构建资产，不能将只有 `__init__.py` 的 Web wheel 当作可用网页。
- 单后端 worker、Python 引擎、SQLite/文件、memory coordination；不加 Redis/PocketBase。绑定 loopback，启动的进程/PID/日志必须可定位，验证结束可停止；后台 Windows 进程隐藏窗口。
- 验证记录保存到 `docs/design/evidence/learning-book-preflight/`；记录已执行、失败、未执行和阻断条件，不把静态/模拟通过写成真实模型链通过。

后续项目模块暂定 `tools/learning_book/`，与 `tools/wiki_runtime/` 分离；具体实现文件在对应任务开工时确定，不提前创建接口桩。`tools/learning_book` 仅承担契约、后端访问、应用操作和证据组装，正式维护仍调用现有入口。

## 3. 任务与依赖

| 任务 | 交付 | 依赖和停止条件 |
| --- | --- | --- |
| I0 环境/版本与隔离 | 工具版本、HEAD/模块闭包、运行目录、无敏感值的环境记录 | 不满足 Python/Node 时先补本地工具链，不污染全局 |
| I1 无模型安装与启动 | 固定源码模块安装、pip check、模块状态、API/Web 启动和 HTTP 读取证据 | 安装或必要模块启动失败需定点定位；不可用加装 full 掩盖闭包缺陷 |
| I2 有限真实学习探针 | 一份自有 MD → 小书/有效 choice → 当前页追问 → 保存/重开/JSON 读回；实际用量及缺失项 | I1；指定 LLM/embedding/费用边界。失败可回 D1，不要求先做项目适配 |
| I3 来源与生产回执 | source/version/artifact/corpus/活动映射、请求摘要、输入上传和创建回执 | I2 证明主链可用；不确定成功先读取/核对，不盲目重建 |
| I4 学习前基线 | 内容投影规则、只读快照、资源清单、一致性/绑定状态 | I3；真实 pages 全部读取，不以 revision 充当历史版本 |
| I5 只读学习结果交接 | HTTP 读取 progress/chat、原始记录、作用域 key、失败/覆盖和不可变包 | I4；身份不符拒绝聚合，缺内容保留 unknown/partial |
| I6 闭环与交付 | 同一小资料完整闭环、重启/备份恢复、使用说明和外部 Agent 操作提示 | I3–I5；不越过正式 ingest/approve |

本轮前置验证不提前创建 I3–I6 产品代码。I1 不通不自动切 OM，也不靠构造假输出通过；将阻断归类为本机条件、发行/依赖、上游缺陷或设计假设错误，再决定局部修订或回 D1。

## 4. I0/I1 的具体验收

1. 记录实际上游 HEAD、源码版本、依赖闭包、Python/Node 路径与版本；不打印凭据、完整环境或敏感配置。
2. 安装固定来源构建的选定模块，使用专用 venv/cache/runtime，保留实际 dependency freeze 和 wheel 摘要；检查包文件所有权不重叠。源码 Web 单独使用固定 lockfile，不能将最小 Python 集合说成最小前端依赖集。
3. `init --non-interactive`、模块状态/必要路由加载、pip check 无模型执行；有能力未 ready 应说明原因。未配置 LLM 不是服务不能启动的证明，服务启动也不是模型可用证明。
4. API 仅 loopback，读取健康、书库列表等非模型入口；Web 实际响应并可访问书库。仅构建成功、仅 CLI `--help` 或静态 mock 不算网页链路通过。
5. 重启隔离实例后可读同一 runtime；记录进程停止/保留状态。启动时若自动做网络检查，区分健康探测与模型生成，避免测试过程中误用继承凭据。
6. 供应商配置空白或移除子进程凭据继承；Node telemetry 关闭。供应商真实调用仅 I2 使用指定配置，不借助本聊天宿主/已有登录绕过明确边界。

## 5. I2 的最小真实探针

本节保留 I2 历史执行条件：文本模型请求的输入＋输出累计 100 万原始 tokens 初始预算，包含子调用／重试；80 万暂停新增调用，给在途任务留余量。本地 embedding 独立记录，套餐百分比与原始 tokens 不假设一比一，见 套餐／预算核对（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-setup/quota-budget.md）。首轮超额及后来获准的 3 万续测已分别结案；用户明确授权使用当前未轮换 Key，最新状态以最终验收为准。这些额度不作为未来 I3 默认可用额度。

仅用自有短 MD（例如幂等与重试），一个冻结语料 KB、一个内容章节及必要概览；使用实际上游生成与教学路径，人工/结构检查至少一道有效单答案 choice。不得把手写 pages/answers 或模拟模型响应算作真实探针。

保存：输入 hash/版本与 KB/file、创建请求/响应、bookId、实际题目、用户测试答案、page chat session、重启后的 API 响应、供应商实际 usage/estimated/missing。日志去敏后只摘录所需字段，不提交 API key/请求头。

失败与重试以现有 book/page/submission_id 为范围。预算接近上限时暂停书/取消当前回合；已经发出的调用可能继续计费，不能承诺精确本地硬限额。无支持的供应商硬限额时，记录软控制与实际消耗，不将轮次等同货币上限。

若无模型/embedding 配置，只能结论“I1 通过，I2 待配置”，不得报告首个学习闭环通过。若真实探针暴露无法引用来源、无法保存/恢复或必要模块组合不可运行，带最小失败证据重评 D1。

## 6. I3–I6 的实现标准

契约以 [D2](research/upstream-learning/design-convergence/D2-data-and-handoff-contract.md) 为准：

- 原文、清洗提取物、sourceVersion 和上传 inputArtifact 各自有 hash；同一冻结 corpus 可跨活动复用，变化创建新版本，不把全库检索误当文件过滤。
- stable activityId 与 backend deployment/owner/workspace/bookId 映射；同请求不同 payload 拒绝，未知成功不按标题猜测匹配。
- 基线实际保存内容字节/题目与资源，连续读取比较并有限重试。冻结是协作约定，attempt 无提交时 hash 时绝不声称 verified_at_submission。
- 选择题的客户端判分保留原样，确定性复核另列；书面题自评、ungraded、missing、同步失败分别表达。不重新问模型补历史 verdict。
- 跨 export 的原记录 key 带真实作用域；无 ID 的旧尝试不能按相同答案 hash 合并。聊天分页/裁剪/删除、读取期间变化明示 partial。
- export 完成 manifest/资源校验后发布；临时目录不当完整结果。索引可重建，原始事实和唯一历史证据不可凭理论可重建删除。
- 人和 Agent 共用应用操作；第一入口为 CLI，已有上游 Web 保留。MCP/自有门户不是本期前置；CLI 不从旁启动第二个 BookEngine 并行改上游存储。
- 错误条件的测试覆盖真实语义：部分保存、身份错配、内容改版、重复请求、缺原文/历史；不写仅镜像代码的测试。备份与恢复用隔离副本，不碰正式数据。

## 7. 工程管理与后续状态

每项完成须给出产物/命令/结果及未覆盖项；记录使用的源码/配置版本。失败先最小复现，局部补丁与配置变更单列，不能静默升级上游或把额外模块加入“已验证最小组合”。安装 resolver 得到的外部依赖版本需保存，不能只锁顶层 DeepTutor。

I2 后再落实 I3–I6 的函数级任务与验收文件；只在必要时修改本任务书。没有用户指令不提交/推送；不修改正式 raw/wiki/AGENTS 或旧阶段通过状态。真实模型、运行可用性和教学质量分别报告，禁止以一类通过替代另一类。