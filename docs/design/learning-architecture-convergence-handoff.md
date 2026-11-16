---
type: meta
title: 压缩上下文交接：执行 D1–D3 设计专题
status: historical_record
updated: 2026-11-11
topic: 学习架构收敛交接
related_sources: []
related_synthesis: []
---

# 压缩上下文交接：执行 D1–D3 设计专题

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

更新：2026-11-11。工作区：`<知识库根目录>`。

**当前交付入口为 I6 最终验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/acceptance.md）。** I6-A～D 的真实生产、经审校课件、原生学习、重启、独立备份恢复和交接消费已有限通过。累计用量（见本机账本） tokens，见 token 审计（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/token-audit.md）。I6 数据、备份及账本保留，服务已停止。下方各阶段记录保留其完成时状态。

**I2 完成时入口**：I2 有限通过：真实学习闭环已验证（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-final.md）。主 Agent 已接手完成修复、一次真实页边追问及同实例重启恢复。17 项回归通过，实际 Windows venv 停止链已验证；原课程忠实性／首次答题 500 的限制保留。下方“未启动／需修复”均属历史状态，不自动进入 I3–I6。

**I5 完成时入口**：[I5 详细任务书](learning-book-i5-plan.md)、完整验收／C01–C20（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）与 [HANDOFF](../../tools/learning_book/HANDOFF.md)。I5-A～E 已完成，174 项项目测试及实际路由／存储复验通过；原值与条件复核、完整首次绑定审查链、所选公开会话／规范事件、有界统一窗口／持久限额、原字节／refMap 搬运、离线 verify、CLI／schema 均已实现。上游 events 的私有 metadata 由入包前拒绝整份响应处理，明确 partial，无新增过滤补丁。schema／正常和 partial 包可直接离线查看，真实进程退出、OS 锁、junction、移走原 state 后恢复／校验已实测。原 I4 与 A/B 报告冻结，最新使用 validated；上游 books wheel 未改／未安装，未调用真实模型。下一步 I6 核对隔离安装、真实 I3 活动／生产学习与外部 Agent 消费；不自动重开旧额度。详细接续见 [I5 Goal 交接](learning-book-i5-goal-handoff.md)。

**I3 已完成**：I3 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i3/README.md）、[模块／CLI](../../tools/learning_book/README.md)、[任务书](learning-book-i3-plan.md)与 [总任务书](learning-book-implementation-tasks.md)。36 项本地／HTTP 契约测试通过，真实 DeepTutor 写入集成仍未做。I4 实现与隔离补丁验收见当前接手入口，尚未安装到既有服务；I5-A～E 已通过，I6 未实施，旧额度不恢复。[I2 执行交接](learning-book-i2-handoff.md)仅保留历史过程。

**I4 已完成**：验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）、[任务书](learning-book-i4-plan.md)、[基线操作](../../tools/learning_book/BASELINE.md)。I4-A～E 本地／HTTP 通过，项目 29 项、上游 19 项源码／wheel 复测及 I3 36 项回归通过；补丁未安装到既有 venv/runtime。真实部署与生产闭环仍留 I6，旧额度不复用。

**I4 的新增关键事实**：旧 GET Book 在读前恢复生成；现有 list_pages 会静默跳过坏页。因此新入口须同时保证零生成、全存储页枚举和漏页诊断。既有 I2 离线响应中 4 页／17 块 READY，但 11 道题含 1 道 Generation failed／N/A，占位必须阻断未来交付；不改 I2 历史证据。采集完整性、结构检查、外部质量审查与历史绑定分开，连续读取稳定最多证明 cooperative，不能写 verified_at_submission。

**I3 实施补充**：同 state-dir 全局 OS 单写者；输入包／回执／DT runtime 分离。KB 是账户资源作用域，可跨 Book workspace 复用，活动映射不重绑。固定源码进一步确认 TopicSource.label 必填、grounding 最多 16 份／每份 4,000 字符／文件上下文 80,000 字符；首期包限 16 份、上限入回执，实际上下文覆盖仍 unknown。新适配器真实模型预算控制尚待集成，单 worker 以外的子进程树、Linux 停止分支、共享网络目录未验收。正式资产和 I2 证据未改。

**最新执行进度**：I0/I1 已通过，I2 有限通过。使用 <本机 I2 实例目录>、MiniMax minimax-m3 与本地 Ollama bge-m3。首轮增量与超额保留（数值见本机账本）；用户另批 30,000、24,000 暂停，续测计量见本机账本（实报＋估算分列）。用户澄清 Key 未轮换、明确授权使用当前配置，不将它写成已轮换。当前本次 API/Web 已停止，临时推理设置已恢复，Ollama 未动；旧预算和续测都不能自行重新启动。下方保留设计阶段历史。

**执行后状态：D1–D3 已完成，四份产物已写入 [design-convergence](research/upstream-learning/design-convergence/design-summary.md)，[总体方案](research/upstream-learning/architecture-proposal.md)已同步。推荐 DeepTutor Book，范围为阅读/页边追问/单答案选择题/恢复/结果交接；内容绑定仅协作级，不含书面题自动批改或严格学习门禁。没有安装、运行产品或实施适配器。下一步另写实施任务书，不重复执行本交接末尾的启动指令。以下各节保留为本次执行前的上下文记录，其“待执行/尚未创建”状态已被本段和产物取代。**

## 1. 当前任务与授权

用户已同意：**更新总体设计 → 完成三个有限的设计专题 → 收敛后再拆实施任务。** 用户现在准备压缩上下文，接下来应执行 D1–D3，不能只再次提出计划或重写任务手册。

本轮仍是设计工作：允许读取本地固定源码、配置、既有测试与文档，编写设计及纯文本分析。不要安装、构建、启动产品、调用模型、执行上游模块或实现适配器；不修改正式 raw/wiki/AGENTS、业务代码与阶段状态，不提交/推送。保留工作区内其他人已有的修改和未跟踪文件。

用户偏好：充分借鉴成熟工程，允许推翻旧框架；重点研究整体可行性、职责、扩展和取舍。简单错误直接修，不为了路径、措辞反复发任务返修。不要将讨论当作产品实现指令，也不要把完整流程测试或运行六套产品作为设计前提。

## 2. 压缩后最小阅读顺序

1. 项目根 [AGENTS.md](../../AGENTS.md)。
2. 本交接，以及 [D1–D3 任务手册](learning-architecture-design-tasks.md)——专题要求、权限、交付物与验收标准均已写好。
3. [总体架构方案](research/upstream-learning/architecture-proposal.md)——原则已定；具体后端与首期范围待定。
4. [上游设计动机与架构启发](research/upstream-learning/upstream-design-rationale.md)——这是最新一轮思考，解释六个产品为什么这样取舍，并更正低估 DeepTutor 的判断。

按需查 [当前设计状态](research/upstream-learning/acceptance-request.md)、[源码报告](research/upstream-learning/report.md)、证据索引（证据未公开，无法由本仓库独立复核：docs/design/research/upstream-learning/source-evidence.json）、[固定版本 manifest](upstream-sources.md)。**不要默认把 857 条证据、全部历史审核和 S0/S1 文档重新读进上下文。**

## 3. 已确定与待决定

已经确定：资料先暂存、明确要求后整理；外部 Agent 可读知识库并负责搜集/核验/整理/候选；学习应用主要消费并提供交互，可用强模型；来源、内容版本、学习事实、用户声明和模型判断分开；知识库与学习产品解耦；同机单用户优先；界面和 Agent 共用业务语义，CLI/HTTP/MCP 是入口选择。

仍待决定：以固定课堂还是围绕来源持续学习为首个主体验；实际采用的产品/模块；可读数据和交接契约；首个可用闭环的覆盖范围与必要适配。

**OpenMAIC 并未最终胜出。** 总体方案保留其部署、字段与 slide/quiz 范围作为静态研究候选，不得当作当前必装清单。DeepTutor 的 Book/typed blocks/Page Chat、CLI/SDK、可选 server/web 与模块闭包必须纳入同情境比较；不能再说它没有课程化学习产物，也不能把全部可选前端叠加成最小部署成本。

## 4. 三个专题的实际进度与交付

截至本交接：**D1、D2、D3 均待执行**，任务手册已完成；`design-convergence/` 尚未创建，没有专题完成产物。

输出目录：`docs/design/research/upstream-learning/design-convergence/`。

| 专题 | 要解决的问题 | 文件 |
| --- | --- | --- |
| D1 | 同一用户情境比较 OpenMAIC 与 DeepTutor 实际适用组合，明确主体验、推荐与代价 | `D1-learning-backend-decision.md` |
| D2 | 数据/状态拥有者、稳定身份、版本与证据、真实机器入口、失败语义与静态交接例子 | `D2-data-and-handoff-contract.md` |
| D3 | 基于前两项确定首个闭环、支持范围、复用/配置/适配/补丁/后置清单 | `D3-first-learning-scope.md` |
| 合并 | 汇总决定、组件、边界、范围、关键证据与剩余未知 | `design-summary.md` |

先做 D1 的两种学习入口对照；D2 的不变量可同时整理，但具体映射跟随推荐。D2 若发现状态/版本关键缺口，回到 D1 重评；D3 最后定稿。**不预填空文件、不先写函数级开发任务、不立即部署。** 完成后同步总体方案、设计状态与索引。

## 5. 必须保留的研究结论

- OpenMAIC：Scene/Action/播放与 live Director 适合课堂成品；生成、课堂和对话是完整应用能力，不在两个存储/DSL SDK 中。它的 API 是实际服务端，外部 Agent 调用不等于服务端职责消失。
- DeepTutor：多个学习模式经共同应用服务处理 turn、上下文和事件；独立模块与 CLI/SDK 是真实设计，Book 有章节、测验与 Page Chat。读取 `docs-for-dev/ARCHITECTURE.md`、`MODULES.md`、`RUNTIME_DESIGN.md`、`TOOLS_AND_CAPABILITIES.md` 定位所需组合。
- Lattice：最有价值的是共同状态、人/Agent 统一入口、按打断成本分工、按需上下文、结构化展示和可撤销操作。Vault 的全树 Git/index 写入不适合直接接正式 wiki，但不足以否定其全部设计。
- Open Notebook：Source/Insight/Note 分开、来源跨主题复用；Chat/Ask/Transformation 用不同成本路径；模型和解析交给专门库。VISION 与 ADR 说明为什么这样取舍，文档原则仍需与实际接线区分。
- Kotaemon：值得借鉴可替换的索引/推理流水线与证据呈现，不代表引入整个 RAG 应用。
- MCP adapter：薄传输边界有价值，但已有后端契约漂移；能力搜索不等于工具 schema 延迟暴露。可先复用现成 CLI/HTTP，不因缺 MCP 否决产品。

技术陷阱已经确认：OpenMAIC 短答评分失败会保存基础分，reviewed/completed 不代表评分成功；manifest.rev 是变更计数而非历史快照；PBL v3 有独立领域表和 E2B-compatible 沙箱；缺辅助日志不证明独立作答；一次 HTTP 教学回合可能多次模型调用。D2 按所选后端真实结构映射，不把这些案例机械外推到所有产品。

## 6. 本地资料与操作提示

六个 clone 均在 `references/upstream/`，由主仓库 ignore，已固定提交，未安装依赖。版本以 manifest 与实际 HEAD 为准，不自动 pull/checkout/reset。

检索忽略目录时使用 `rg --no-ignore`，例如：`rg --files --no-ignore 上游仓库 DeepTutor 的 `DeepTutor/docs-for-dev``。DeepTutor 文档目录是 `docs-for-dev/`，Book 源码目录是 `deeptutor/book/`；OpenMAIC 文档在 `packages/docs/content/docs/`。避免广搜生成资源、字体或 base64 长行。

`source-evidence.json` 当前 857 条，定位与重建已复核；主 Agent 修正源在 `_notes/main-agent-evidence.json`，`build_evidence_v2.py` 重建时会合并。新专题可在文档内用固定提交+路径/符号的紧凑证据，不要求为了数量继续扩表。静态设计建议与已实现能力要分开，不编造性能、费用、恢复和教学质量实测。

旧审核记录与旧讨论交接保留为历史。最新状态不等于已选定 OpenMAIC、不等于完成产品实现，也不改变已有 S0/S1 记录。只有影响目标或推荐的未知才继续展开，避免无限研究与重复文档往返。

## 7. 压缩后可直接使用的启动指令

> 请读取 `<知识库根目录>/docs/design/learning-architecture-convergence-handoff.md`，按其中阅读顺序执行 D1–D3 设计专题，直到形成三个专题产物与 design-summary，并同步总体方案和状态。现有总体原则与研究已保存，不重做全量调研，不预设 OpenMAIC 胜出。先开始 D1 的同情境比较，再用 D2 核实交接，最后由 D3 收敛首个闭环。本轮只做设计与必要源码确认，不安装、运行产品、调模型或实施；简单文档问题直接修，保持现有修改和正式资产。