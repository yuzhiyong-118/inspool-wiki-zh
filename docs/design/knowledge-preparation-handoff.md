---
type: meta
title: 知识准备链交接：K4 本地集成交付与使用边界
status: historical_record
updated: 2026-11-12
topic: 知识准备链交接与使用边界
related_sources: []
related_synthesis: []
---

# 知识准备链交接：K4 本地集成交付与使用边界

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

更新：2026-11-12。工作区：`<知识库根目录>`。本文件是当前续接入口；根 AGENTS.md 仍是维护规则正本，验收记录负责证明实际通过范围。

> **最新独立复审（2026-11-14）：W1／E1 固定候选的限定隔离验收通过。** 先读release-06 复审与下一步（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-review/remediation-review-02/README.md）。F1–F3 已关闭，原 R1–R5 已测范围保留；独立 162＋13＋3＝178 项不同检查全过。原生目录首次／重复／编辑、受管写入新增正文页、整书完成、I4／I5 及负例均有依据。候选 `<本机验证目录>` 八 wheel／1,112 业务文件；日常仍为 Q3，已记账量见本机账本；80 万暂停／100 万上限及原学习记录保留。E1 未日常部署，本轮零模型调用；下一步受控部署准备及用户试学，部署按用户后续实际指派。W2/C2、S1、完整 M1、W3–W5 等仍按主方案安排。下方未通过／未完成的描述保留为历史检查点。

> **最新修复候选复审（2026-11-13）：E1 release-05 暂不通过。** 先读第二轮独立复审与 F1–F3（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-review/remediation-review-01/README.md）。R3 worker／R4 屏障与公开恢复／R5 首次 inspect 在所测范围关闭；R1／R2 部分修复，但实际 confirm_spine 自动概览章引起章数不符阻断，空正文仍可被后备字段或同页 quiz 掩盖，计划空章仍能完成。下一步只修三项并派生新候选，保留已关闭项；日常 Q3 身份与账本只读核对一致，E1 未部署，无新增模型调用。下方是历次审查与交付历史。

> **最新独立复审（2026-11-13）：后续三批整体暂不通过。** 先读独立复审与五项修订（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-review/README.md）。执行交付的源码／发行摘要、五条 Q3 用量、累计用量（见本机账本）、floor 及日常宿主运行身份已核对；独立重跑 153＋12 项既有检查通过。但新增反例确认 E1 的目录缺页、空正文、存活整书 worker、半提交 journal 可读四项 P1，以及 W1 首次 inspect 摘要循环依赖一项 P2。下一步只修 R1–R5、派生新的固定发行物和新证据，再回原对话复审；E1 不部署日常，不追加真实模型样本，日常 Q3 继续运行。下方“未归并／未升级”属于历史检查点，已由本条及执行交付记录覆盖；本轮仅审查，没有改产品或停启服务。

> **交给其他Agent执行（2026-11-13）：** 使用[后续执行与审查交接](learning-system-next-execution-handoff.md)作为任务入口，分批处理用量／部署、W1和E1，交付新证据后由原对话审查。本文提供既有状态与历史，不代表所有剩余方案已实现；整体工作包按需查[主方案](knowledge-system-revision-plan.md#11-实施任务与依赖)。本次仅编写执行交接，没有实际升级或新增模型调用。

> **最新Q3修复检查点（2026-11-13）：三项缺口已修复并通过限定复审。** 先读修复验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3-fix/README.md）、复核（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3-fix/review.md）及[接入说明](../../patches/deeptutor/q3-fix/README.md)。新补丁learning-question-q3-fix/1从固定Q2发行物派生，实际release-04八模块／1,111业务文件，147项不同检查通过（17新增），原Q3三份课件／六份包只读回验通过。受管出题真实组合和dispatch禁用工具，健康读不写canonical，流式终止／尾帧／缺计量及重启门禁已修；旧通用工具及写保护保持原边界。测试不再用工具组合器替身制造通过；新项目文件pin包括runtime_guard.py。本轮新增模型0，日常实例／旧课程／wiki/raw／原预算账本未改，旧验收未重写。原Q3新增用量仍未归并，合并视角见本机账本；下一次模型调用先按call_id接续，原80万暂停／100万上限不变。不重跑Q1/Q2/Q3或追加样本；后续可进入停服备份／显式接入的部署准备，E1／真实认证与RAG／用户试学仍按原任务处理。无活动Goal、后台测试或试验服务。

> **上一轮Q3试验检查点（历史）：受控试验完成，默认部署待三个问题修复复审。** 先读 报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3/README.md）、问题与最小修订（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3/review.md）、实际命令（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3/commands.md）。普通／增强各两题，增强固定场景通过2/2、普通0/2；实报与发送前失败估算分列，合计新增用量见本机账本。增强成本多23.3%，不声称直接省token、普遍质量或教学效果。定稿CLI无模型发布，三个I4 /2接受、网页原生作答一条、API/Web停止重启、三份内容／学习状态摘要一致及I5搬运均有依据；未学习的两份导出保持partial。身份／就绪书／索引为实验夹具，未验E1或真实认证/RAG。工具白名单绕过、KB健康GET触发受保护写入、成功流误记interrupted尚未修复，不能升级日常实例。原日常账本未改；隔离新增未归并，合并视角见本机账本；下次模型工作前按call_id归并或联查，原80万暂停/100万上限不变。不重跑Q1/Q2/Q3或追加样本，下一步确定性修复并复审。Q3服务已停止，本机端口已关闭，无活动Goal、原课程/wiki/raw/原预算变更。

> **上一轮 Q2 检查点（历史）：受管题目接线通过限定离线验收。** 先读 Q2 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q2/README.md）、问题关闭（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q2/review.md）、[操作手册](../../tools/learning_book/QUESTION_PRODUCTION.md)及[任务书检查点](learning-question-implementation-tasks.md#5-阶段交接与当前检查点)。最终 run-04 共 163 项不同检查通过，含 22 项新增集成。独立八模块 wheel／1,111 个业务文件在 `<本机验证目录>` 物化验证，未升级日常实例。定稿无模型发布，变式先生成副本再提交；来源／讲义／生产审查、冻结 request、实际 publication response、最终题目及 I4/I5 /2 附件闭合。journal 只按精确前后状态恢复；原生内容写不能降级绑定，原生作答／聊天映射保持。发布后纠错用替代活动，不支持共享书和草稿原地换题。Q3 未开始，完整新课首次 I4 仍需 E1；下一步先核对 E1，或为已有就绪课件准备 Q3 小批次计划并重新核对授权／预算。没有活动 Goal、后台测试／本专题服务、真实业务模型调用、正式课程／wiki/raw／原预算账本变更。旧验收保持原字节，不重做 Q1/Q2。

> **上一轮 Q1 检查点（历史）：Goal 范围为 Q1，离线交付已通过。** 先读验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q1/README.md）、接口选择（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q1/interface-check.md）与[任务书当前检查点](learning-question-implementation-tasks.md#5-阶段交接与当前检查点)。已新增 question_spec.py、Schema、两种合法与三种非法样例及虚构材料，23 项新检查＋5 项既有定向回归通过。规格核对讲义／来源字节，最终题摘要显式含选项顺序；字面无错仍是 pending_review。选定参考题字段的确定性渲染；Q2 才做 publish-quiz 窄 API、journal、guard／continuation、I4/I5 /2、安装与恢复。Q2／Q3 未开始，默认生产路径、现有课程／账本、真实模型均未改动；无后台测试或服务。旧原始失败产物与验收保持原字节，不重跑 Q1；若继续实施，下一步 Q2，完整新课到首次 I4 仍受 E1 约束。

> **上一轮出题设计检查点（历史）：已整理，可开始 Q1 离线任务，当时尚未实施。** 先读[重整方案](learning-question-constraint-plan.md)与[详细任务书 §5](learning-question-implementation-tasks.md#5-阶段交接与当前检查点)。两轮本地研究覆盖三个约束项目及此前六个学习应用；现分定稿原样发布、变式有界生成，随堂追问仅保留教学策略。旧 R1–R6 与旧 Q1–Q3 阶段含义已被取代，不能照旧跑“先模型后接线”。下一步 Q1.1 接口核对，随后 Schema／纯函数／反例；Q2 接生产、准备审阅、原生入口、I4/I5 与安装恢复；Q3 在授权及当前账本允许时做真实验证。整体 W1 路线不重排，Q1 可独立开展；完整新课到首次 I4 仍需 E1。设计文档核对见本轮记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-design/README.md）。没有本专题代码、活动 Goal、后台测试、模型调用或课程／账本变更。

> **最新 Token 设计检查点：方案已细化，实现未启动。** 先读[Token 成本治理专题](knowledge-token-efficiency-plan.md)与[主方案 §11](knowledge-system-revision-plan.md#11-实施任务与依赖)。原审查的固定机械管线、用量归因、短回执、会话／缓存、局部复用和 F01–F06 同任务对照已明确采纳；不使用旧报告的消耗数据作为新证明。本轮 3 组接口探针及 5 项重跑（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-token-design/README.md）只验证当前落点，不代表 prepare-next／M1／W3 已完成或有确定节省率。下一步 W1 先导航／模板再私有机械串接，M1 可分别推进；遇到语义审阅、权限或正式副作用停止。没有真实模型调用、账本变更、正式内容变更、活动 Goal 或后台测试。此前证据保持原字节，当前方案另绑新清单。

> **最新设计检查点：整体接口已拉通，新增设计未实施。** 先读[25 项操作矩阵与 J01–J07](knowledge-system-integration-review.md)、[同步后的修订方案](knowledge-system-revision-plan.md)及本轮新补证（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-system-integration/README.md）。纯 L 不依赖新增 wiki Runtime 任务；受管正文编辑还需整书完成契约，首次 I4 认可后纠错先走新 activity/book，C2 默认关联已学冻结版。7 组新探针与 13 项重新执行测试不代替真实部署／教学验收。当前下一步是 W1 入口与诊断，E1／W2／S1 等仍待实施；下方既有准入实现的停止点不因此重做，旧验收保持原字节。没有活动 Goal、后台测试、真实 API 或正式内容操作。

> **当前最新停止点：专用非教学知识入库接线及临时库验收完成。** 见[执行交接](knowledge-candidate-admission-handoff.md)、本次验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission/README.md）和[任务书](knowledge-candidate-admission-plan.md)。101 个不同检查有通过依据，含 18 个新增检查；并发覆盖授权问题已修复并独立复核关闭。可信宿主可显式 admit 后交给 Executor，未建立专用准入的候选仍不能应用；旧普通 run(ingest) 继续关闭。当前只支持 knowledge_only，raw 只到 pending_review，processed 仍需独立 approve。本次未应用真实库、未新增真实 API、未操作既有课程或账本，无活动 Goal／后台测试。

> **上一轮历史停止点：K4 后四项连接修订已按限定范围完成，独立复核无新阻断。** 先读修复记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-integration-fix/README.md）及问题关闭（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-integration-fix/review.md），原问题见[修复前拉通审查](knowledge-preparation-post-k4-review.md)。当时复用输入、同活动续接、I4/I5 依据、候选接收／咨询已接线，但正式非教学准入仍关闭；本次专用准入见顶部。历史 185 个不同检查的通过依据不升级成当前字节或 33 项生产业务全通过。

修复收尾检查点：首轮组合 14 项通过；既有路径回归 170 项中 169 通过，末轮定向补验 33 项中 32 通过，二者同一新增负例夹具漏算包 content_digest；纠正夹具后单项通过。tests-summary.json 合并每个检查的最终依据，185 个不同检查无未解决项，不篡改原错误输出。独立只读复核已关闭迁移分类、离线对象引用闭合、历史候选查看、合法旧页全文缺失与冲突分支／可交接状态问题；没有替主 Agent运行物化测试。必要旧页快照随归档冻结并核对实际字节，完整原件 external；不虚构 text。没有活动 Goal、真实 API、正式库写入或后台测试进程。压缩后先读修复记录及当前 acceptance，不因旧工具 session 不可读就重做阶段。

## 1. 接手结论与本次停止点

用户先完成方案和任务书，再授权实施。**当前 K0–K3 原限定范围完成，K4 已交付本地集成、真实文本独立审阅、业务映射与交接；不代表 33 项生产业务全部通过。** 先读 K4 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k4/README.md）及[外部 Agent 工作单](../../tools/wiki_runtime/evidence/WORKSHEET.md)。I3 可显式接入新门禁，已受控请求不能降级；历史入口与原生编辑没有因此全部受控，正式维护门禁保持原边界。

| 项目 | 当前实际状态 |
| --- | --- |
| DeepTutor 学习消费链 I3–I6 及工程收尾 | 限定范围通过，六章架构课已发布；不能当作完整知识治理或权威掌握评估 |
| K0 接口及协议样例 | 独立复审通过，修订后 29 项离线核对通过 |
| K1 本地只读准备 | 实现及独立代码复审通过，29 项临时库测试、3 条实际 CLI 合成流程通过 |
| K2 主张／证据／冲突 | 本地只读及 operator_supplied 范围观察通过：37 项测试、29 项 K1 回归、7 次 CLI、独立代码与两包实际内容审阅 |
| K3 学习投影、认可与发布门禁、候选预览 | 原私有范围通过：38 项测试＋K2／K1 回归、实际全文审阅；当前显式生产接线另见 K4 |
| K4 集成与交接 | 历史 162＋6 项及后续四项修复范围保留；现又补齐专用知识准入并通过临时库事务验收，未应用真实库 |
| 来源网站的完整注册、路由、生命周期及自动交叉印证 | 原设计保留，尚未完整落地；不默认所有服务已安装或接入 |

用户已明确再次授权直接开始 K4，并自行处理上下文压缩；当前没有活动 Goal，按普通任务推进，不重做 K0–K3。没有提交／推送。正式 raw／wiki／AGENTS、已有课程与运行配置在 K0–K3 工作中未改。大量旧脏文件和未跟踪文件属于前序工作，不能清理或覆盖。

### Goal 执行与上下文恢复约定

- 当前 Goal 已由用户清除，后续用户另行授权 K4；普通模式推进。用户自行选择压缩时机。交接仅是恢复线索；自动压缩若发生在任务中途，恢复时必须结合最新会话摘要、实际文件差异及运行进程核对，不能只按上一个完成点重放。
- K 系列范围仍为 K0–K4，各自已验收限定范围见本交接；K4 本地工程交付完成，未执行业务边界保留，不另造 K5 等阶段。
- 当前检查点（2026-11-12）：K4 162 项核心／回归全通过（227.889 秒），新增 CLI＋5 项 I5 补充 6 项全通过（23.830 秒），共 168 个不同检查。初次状态分类失败及两次 CLI 夹具失败保留记录，未放宽门禁。三个独立复审 P2 已关闭：scope 可变别名、第二约定 header 恢复、后续步骤审阅留存；未发现新阻断。
- 上述“未发现新阻断”是 K4 当时的限定复审结论。修复前拉通审查确认四个新连接缺口，纯内存探针复现复用后的 input_evidence_missing 和新旧 binding 拒绝；该次审查没有改业务代码。随后已完成顶部所述修复，当前结论以连接修复验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-integration-fix/acceptance.json）为准。旧 acceptance 原字节保留，当前代码与历史绑定的差异另行记录，不能改旧 hash 掩盖。
- K4 actual-content-baseline.json 在真实根只读盘点 43 个文件，非整个仓库或 Executor 准入；health-readonly.json 结构检查退出 0。real-text/ 是实际 AGENTS.md 全字节案例，真实独立知识／正向投影通过、负向拒绝、纠错新版本 needs_review；认可仅离线模拟，不能用来发布真实新课。未运行真实模型 API／课程生产调用，未写正式知识库。
- 真实 API 外发和正式知识应用按原授权与入口要求处理；缺条件的项目明确记未验收，不用私有通过替代。不设置新模型额度，不改原预算账本；宿主 tokens 未有可信总计时仍记 unknown。

## 2. 压缩后最小阅读顺序

1. 根 [AGENTS.md](../../AGENTS.md)及本交接。
2. [知识准备任务书](knowledge-preparation-plan.md)：先读 §2.1、§3.1.1–3.1.2、§3.4–3.6、K2 行和验收矩阵；不要重新展开全部旧阶段历史。
3. [K0 接口](knowledge-preparation-k0-contracts.md)：来源／主张协议与学习约定／投影映射的边界。
4. [K1 使用说明](../../tools/wiki_runtime/evidence/README.md)和验收摘要（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k1/README.md）。
5. [K2 操作与字段](../../tools/wiki_runtime/evidence/KNOWLEDGE.md)、独立审查（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k2/review.md）及 knowledge.py／knowledge_cli.py。K3 再读 learning_book/contracts.py、production.py 与 persistence/protocol.py 的真实接口，不先引入新平台。
6. [K3 操作与字段](../../tools/wiki_runtime/evidence/PROJECTION.md)、验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k3/README.md）与独立复审（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k3/review.md）；K4 再按真实接线需求读 production.py／CLI，不先访问旧课程或运行配置。
7. 当前使用先读 [K4 工作单](../../tools/wiki_runtime/evidence/WORKSHEET.md)、验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k4/README.md）与业务边界矩阵（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k4/business-matrix.md）。K3 文档的未接线说明是历史状态，当前实现以 K4 为准。
8. 连接修复后又完成专用非教学知识准入，先读[最新执行交接](knowledge-candidate-admission-handoff.md)及本次验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission/README.md）。前轮修复验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-integration-fix/README.md）和[修复前跨阶段审查](knowledge-preparation-post-k4-review.md)用于理解历史问题，不再按其中顺序重做。准入和咨询分开，真实资料应用仍须对应任务授权。

整体设计取舍按需查[端到端复核](knowledge-preparation-integration-review.md)及[总体方案](research/upstream-learning/architecture-proposal.md)。旧文档存在“尚未实施／服务已停止”等历史记录；优先本交接与当前 acceptance，不照旧 S2／S3 启动完整流程。

## 3. 已确定的产品与架构方向

外部成熟 Agent 负责开放式采集、查库、核验和整理；DeepTutor 负责课程呈现、教学生成、追问及原始学习状态；我们维护知识准备应用操作、稳定来源／版本、生产回执、内容基线、只读学习交接、运行与预算控制。原始资料和长期 wiki 独立，DeepTutor Knowledge 是学习资料副本／索引，不能代替正式知识库。

流程分两条，避免循环依赖：

```text
资料暂存 → 明确整理 → 原文／既有知识核对 → 已审知识包 → 知识候选／现有维护流程
                     用户意图＋知识背景／学习证据 → 学习约定
                                  已审知识＋有效约定
                                           ↓
                                学习投影 → DeepTutor
                                           ↓
                            实际课件审校 → 基线 → 用户学习
                                           ↓
                             显式导出回顾 → 下次规划／纠错
```

- 不把每个链接自动成课；用户可只暂存、只整理、参考或暂缓。
- 学习约定结合知识库分析差距，但“库中有内容”不等于已掌握。事实证据与学习者证据分别引用。
- 学习目标、范围／排除项、时间深度和检验方式明确后才深入成课。已有明确意图／委托直接复用；关键缺口才询问，实质扩大范围才重新认可。
- DeepTutor confirm-proposal／confirm-spine 的 API 成功不是用户认可，也不是 approve。准备者后台检查不要求用户逐项确认。
- 学习表现影响下次规划；新事实和错题回知识核验。导出回顾当前是外部 Agent 显式执行，不是自动后台触发，不需常驻外部 Agent。
- 学习不是所有知识入库的前置；用户明确要求“先学后入库”时只约束本次。旧独立理解 L2 门禁未启用，不造 Assessment／Readiness 来凑通过。
- 不重写教学 harness，不建新通用 loop、动态插件平台、全局用户画像库或第二套可写进度。先普通模块／CLI，未来网页／MCP 共用应用操作。

## 4. K0 的关键接口与已修问题

K0 acceptance：`docs/design/evidence/knowledge-preparation-k0/acceptance.json`。当前结果 result.json 是 29 项；result-initial.json 是初次 17 项，仅历史追溯。

- 既有 KnowledgePackage 使用封闭旧协议，保留 Source／Evidence／Claim／relations／conflicts／existing_knowledge。Source.content_digest 与 Evidence.source_digest 绑定原文字节；EvidenceClaimRelation.evidence_digest 绑定 Evidence 记录，不能混用。
- 旧 prepare 校验会忽略部分未知顶层字段。学习约定、知识审校与投影映射单独封装，不能往旧 prepare 塞字段就当已校验。
- sourceBindings 精确覆盖实际 prepare 来源且唯一。direct_source 对应知识原文字节；authored_projection 把外部编写讲义作为 I3 原件，底层证据通过 coverage 引用，不要求全部上传。
- 知识审校和实际上传 artifact 的 projectionReview 分别绑定。实际 create.intent 要匹配认可范围，不只看建议 learningGoal。
- 旧知识比较需记录已读页、字节摘要和查询覆盖，旧 ExistingKnowledgeRelation.target 单独不足以判断失效。
- learning-brief 的 learnerId、认可附件的 attributedAuthor、背景 subject 要一致；operator_supplied／author_judgment 都不是宿主认证。
- K0 修复了局部来源投影、附件依据缺失和重启目标覆盖缺口，并独立确认外部编写讲义路径是必要兼容。

旧协议的已知能力缺口已通过实际例子确认：supported 主张即便没有支持关系也能解析；编造摘录且重算摘要也能解析；合法结构不证明语义。K2 要补真实原文与主张核验，不修改历史记录将这些缺口抹掉。

## 5. K1 已交付代码、限制与验证

| 文件 | 职责 |
| --- | --- |
| tools/wiki_runtime/evidence/preparation.py | inspect_context、verify_context、draft_learning_brief；标准库、零模型／网络、零文件写入 |
| tools/wiki_runtime/evidence/cli.py | inspect-context、check-context、draft-brief；JSON 仅输出 stdout |
| tools/wiki_runtime/evidence/README.md | 请求格式、限额和当前未实现边界 |
| tools/tests/test_knowledge_preparation_k1.py | 29 项真实临时文件／子进程测试 |
| docs/design/evidence/knowledge-preparation-k1/ | acceptance、独立 review、合成 sample 和实际 CLI 输出 |

K1 先读索引，从文件名、索引行和双链选择有限页面，递归兼容用户分类目录。**它是元数据候选选择，不是全文／语义搜索，也不自动判断矛盾。** 返回完整实际已读文本、字节、目录选择条件及 semanticStatus=unreviewed。没有命中保留 unknown，不说库中不存在或用户不会。

背景只生成 material_available／unknown；I5 作答和聊天状态明确 not_read。草案是 draft、recognitionRequired=true，userIntent 的归属保证仅 operator_supplied。前置只支持计划补讲／待澄清，不从资料存在签发“已知可用”；不必把已明确无需补讲的基础都列为待补前置。

返回前重读实际依赖；draft_learning_brief 必须传 wiki_root／source_root，先 verify_context。原文、旧页、索引或目录选择条件改变会 stale；移动目录是合法操作，重新观察可以保留原文字节身份。无不可变页 ID 时不虚构永久身份，歧义保留 pageId=null。

默认硬上限：3 来源、5 已读页面、10,000 目录项、单文件 1 MiB、总读取 4 MiB（含重读）、10 秒；可收紧。context JSON 限 1.5 MiB，CLI JSON 输入限 2 MiB。源 complete 只是准备者声明，不能认证原始载体；PDF／OCR 等出处必须保留并在后续核验。

sourceVersions 继承明确传入的 previous 链，最多 256 个 ID／版本／字节绑定。没有 previous 看不到其他链历史，不能称全局来源注册。独立审查发现的两个 P2 已修复：

1. v1→v2→改写 v1，以及来源暂时移出再加入，必须保留历史并拒绝换字节。
2. 畸形嵌套 context 必须结构化拒绝；错误 text 类型和错误记录类型在两个真实 CLI 操作中均无 traceback。

实际测试命令（无需无故重复整个历史测试集）：

```powershell
& <本机验证目录> -X utf8 -B -m unittest tools.tests.test_knowledge_preparation_k1
```

结果 29 项、0 失败／跳过，5.244 秒。三条 CLI 合成流程 exit 0，实际读 2 页，见 cli-smoke.json。独立审查只读复核并关闭两个 P2，未独立重跑会写临时目录的完整测试；不能把两种证据混写。

## 6. K2 已交付与下一步 K3

新增文件：tools/wiki_runtime/evidence/knowledge.py、knowledge_cli.py、KNOWLEDGE.md，tools/tests/test_knowledge_preparation_k2.py，以及 docs/design/evidence/knowledge-preparation-k2/。没有修改 K0／K1 已绑定代码、README、测试或验收摘要。

K2 核心状态与边界：

- prepare_knowledge(context, request, wiki_root=..., source_root=..., review=None, previous=None) 组装旧 KnowledgePackage；不要求学习约定。Source 从 K1 原字节与逻辑身份构造，外部提案的 Evidence／关系需符合旧协议。
- 行号从 1 起、终点包含；CRLF 只在行视图转 LF，末尾一个终止换行不增空行，裸 CR／BOM／Unicode／空白不归一；摘录必须等于整段连续完整行。原始 bytes 摘要始终不变。
- reviewRequest 绑定实际包、上下文、旧页 comparison、来源观察与范围。真实审阅者提供 knowledge-review-observation/1，assurance 仅 operator_supplied；程序不自动调模型，不认证 Reviewer／G3 或授写权限。
- knowledgeState 分 needs_review／needs_evidence／rejected／reviewed_for_scope／stale；缺审时 result=ready_for_review 仅表示可供审阅，下游必须检查 knowledgeState 和具体 Claim。支持、限定、反证、未决冲突、条件差异及旧页纠错按实际记录处理。
- documents 数组对所有实际已读页给全包关联或排除理由；缺审不因没有 existingKnowledge 条目就被忽略。comparisonChecks 显示逐页语义覆盖；仍不声称全库搜索或旧页原始证据都已核清。
- 来源共同上游、相同声明 originId 和原字节合并分组；未知不当独立，independentCorroborationCount=null。没有启用网站注册／常规信任。
- packageVersions 继承显式 previous 链，最多 256 项；同 ID／版本不同包字节拒绝，不是全局注册库。verify_knowledge 重读实际依赖并重算结果，重算报告 hash 不能直接篡改通过。
- partition_knowledge 仅出显式草案：新包 ID、严格主张子集、父报告引用／排除清单／理由，保留全部 Evidence／来源，不能选择仍列于冲突的主张；新包必须另审，调用者保留分包附件及原报告。

最终测试：37 项 K2＋29 项 K1 回归，66 项通过，0 失败／错误／跳过，16.071 秒，见 tests.json。七条真实 CLI 中缺审／拒绝预期 exit 2；两份冻结虚构包由只读独立 Agent 实际审阅：正向原文纠正旧摘要，负向真实摘录不支持“所有故障可恢复”而被拒绝。两个代码 P2 已独立复核关闭：缺证／缺审混淆、空／无关联冲突被忽略。审查者未独立重跑完整测试，不将合成测试决定当实际语义效果。

K3 原定工作（以下已完成私有实现，生产接线留 K4）：

1. 按 K0 独立约定／认可附件和 preparation-map 契约，核对当前 K1 brief 与 K2 包／观察的实际字段；复用用户已有明确意图，缺依据／范围变化才澄清。不得从 API 200 或包内 confirmed 得出真人同意。
2. 实现 build_learning_projection 的私有导出：选取 reviewed_for_scope 的 Claim／有效 Evidence，覆盖约定目标；分别核对 direct_source 与 authored_projection，精确覆盖实际 prepare 来源，不强迫上传全部原件。
3. 绑定实际 prepare 归一化摘要、实际 intent、上传 artifact 字节和投影审校；新事实／扩大条件回 K2。不要往旧 prepare 塞会被忽略的约定字段。
4. 接现有候选 preview，明确 frontmatter／正文双向边及索引／日志覆盖；不伪造旧 required_objective／L2／Readiness，不直接写正式库。先确认既有 compile 接口能提供真实 preview，再做最小适配。
5. 临时库完成缺审、缺认可、目标遗漏、局部来源、编写讲义、旧页／原文／投影变化、无学习的知识预览等场景，独立审查后记录实际通过边界。K4 再做完整业务与故障／成本验收。

新资料外发或真实采集若超出已有明确授权，先准备具体数据范围、目的地和费用再处理许可；不能套用架构课专属授权。无需为离线阶段新增付费模型。来源平台扩展按实际缺口推进；T／S／I 三维仍保留，不合成网站永久信用分。

### K3 实际交付与 K4 起点

新增 evidence/projection.py、preview.py、projection_cli.py、PROJECTION.md 和 test_knowledge_preparation_k3.py；K0–K2 原代码／测试／验收字节均未改。

- build_learning_projection 消费已有 brief／K2 prepared／外部物化 prepare.json 和上传文件，返回已核对 prepare／preparation-map，不替外部 Agent 新编课文。缺认可留 needs_clarification；缺实际 artifact 审阅留 needs_review，只出 draftMapping，正式 mapping=null。
- 认可附件读取实际依据文件并绑定全文、brief、学习者、范围和实际 intent；assurance=operator_supplied，不能证明真人许可。实际投影 Reviewer 还须核对该原始要求的语义。测试／样例用户要求均明确虚构，不是对真实新课程的授权。
- 包内有界路径／字节先校验，再用知识投影临时副本复用原生 I3 归一化；实际上传来源精确覆盖、允许仅用知识包局部来源；外部讲义自身是新输入，底层事实通过 coverage 引用。目标／上传物全面覆盖，变化分别使认可、知识或投影审阅失效。
- final mapping 绑定投影观察；显式 previous 继承 mapVersions／sourceVersions（各最多 256），上一份当前身份必须在历史中，同版本不得换摘要。不设全局注册库。
- preview_wiki_changes 复用旧 compile_candidate／CandidateView／G0–G2，固定 ingest、write-only、non_teaching、无 L2。原件须已在完整私有基线 raw/unprocessed 登记，缺失留 raw_capture_required；真实双通道回链／索引／日志／overview／raw index／pending_review 都检查。
- 候选基线至多 512 项／4 MiB、单文件 1 MiB，视图累计重读 64 MiB／20 秒；保留未改二进制。真实大仓库超限拒绝，不裁剪 references 冒充全基线。快照是协作读取，不是正式 Executor 准入或对抗恶意本地并发的安全隔离。
- check_release_request_binding 只比较调用者提供的实际 intent／manifest 摘要；没有自动接管现有 I3 CLI，不替代实际请求回执、全链重检或生成课件 I4，coursePublishAuthorized 始终 false。

最终 104 项（K3 38＋K2 37＋K1 29）通过，0 失败／错误／跳过，105.275 秒。六次实际 CLI：私有候选通过、负向缺审、direct 通过、direct 重检一致、authored 通过、夹带新事实拒绝。只读独立审查关闭三个 P2（二进制兼容、raw 路径前置校验、历史成员绑定），另修 I3 固定副本和待审映射提醒。三份上传文本均实际审阅，候选七份 payload 亦实际读过；独立审查者未重跑完整测试或物化构建。

以下为 K4 原定工作（现已交付本地集成，实际完成范围及未覆盖项见后文）：

1. 整理外部 Agent 端到端工作单，将 K1 查询／brief、K2 审查、K3 投影／候选按知识与学习两条路线串联；分别记录已有能力和缺口，不以调用者自报证明认证。
2. 核对真实仓库内容基线的可用入口。当前有界完整根预览不能直接扫描含 references／运行环境的大仓库；须明确正式依赖范围与重检方式，不能把测试副本的 G0–G2 当正式准入。
3. 对现有 I3 生产入口做最小接线，使真实待发送请求读取已审映射、实际 intent／normalized manifest，并在实际调用前重验依据；保留历史独立入口的真实兼容／受控范围，不宣称当前已上线门禁。实际生成课件另走 I4。
4. 在临时库／私有工作区逐条映射 A01–A33 的 actual／expected／未执行，补缺认可、旧页／原文／投影／意图单侧变化、非学习候选、失败恢复及显式回顾／纠错。真实 API 与正式应用另列，不能为了填满矩阵强行外发或绕过身份／approve。
5. 最后独立审查、成本记录与交接。离线准备优先，业务模型 API 维持零；宿主 tokens 不可见记 unknown。新真实资料发送若不在既有明确许可内，先准备具体数据、目的地和费用再处理授权。

### K4 实际交付及后续使用

- 新增 content_view.py／integration_cli.py／learning_book/knowledge_preparation.py／WORKSHEET.md／K4 测试；修改 preview.py／projection_cli.py、I3 production.py／cli.py。K0–K2 绑定文件和 K0–K3 acceptance 原字节不改；K3 两份实现变更由 K4 回归和新验收覆盖，不修改旧摘要“续期”。
- 显式 `--baseline-scope knowledge_content` 在真实根只扫描完整 wiki/raw、AGENTS 和规则映射，包含隐藏文件／二进制／任意分类层级；保持原 G0–G2、目录重检和协作快照。whole_root 默认仍在。正式 Executor 不因私有预览通过就接纳。
- I3 可用 `--knowledge-preparation connection.json`。接线与字段见工作单，操作前和真正 POST 前重验实际 K1/K2、认可、投影、来源／artifact、manifest/corpus/bytes/intent。绑定进入 semantic。受控语料／activity 不能通过省略参数或换 ID 降级；legacy 保留且输出 legacy_not_integrated。复用语料有新本地回执、无第二次上传，允许不同 brief 使用各自真实 header。
- confirm-proposal／confirm-spine／prepare-quiz 需额外审实际 payload/scope/book/revision；null 确认在受控路径拒绝。独立步骤观察及其摘要冻结进请求；旧已保存响应和只读对账不依赖今日材料仍有效。recover-inputs 的 reindex 也是 POST，需要有效接线。
- 实际文本正负与纠错例子保存于 K4 real-text/；只读独立审阅确实读全文，未将测试 accepted 字符串冒充语义能力。实际 I6 既有交接包重验 valid，1 条作答、完成 unknown、有辅助；不当作新导出、独立掌握或自动学习画像。
- A01–A33 为 22 项指定本地验证、10 项部分验证、1 项文档路线本轮未执行；真实新增模型外发与正式知识应用都未验收。I5 自动背景适配、完整网站降级／撤回传播、严格 Native 认证及权威掌握仍缺；原生编辑/Web/编译等未接线写操作不受新 guard 自动保护，实际课件仍需 I4。
- 后续按工作单使用具体资料做受控准备；若要真实外发，先核对该资料的具体发送与费用授权，不能套架构课授权或此处模拟认可。正式入库仍按原维护入口与用户 approve。无需重做 K0–K4 或自行追加新阶段；用户真实试学按原独立收尾记录处理。

## 7. 现有课程、运行与用量提示

已发布真实课：《学习系统架构：从理解到独立搭建》，六章正文＋概览＋第一道选择题。

- book：<对象标识>，activity：<课程活动标识>。
- 入口：第一章（试学入口未随本仓库发布）。
- 课程交付（未随本仓库发布：docs/learning/system-architecture/delivery.json）与收尾状态（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-closeout/README.md）保存既有发布、基线和备份证据。
- 最近工程观察为正常 runtime 运行，API <本机端口>／Web <本机端口>；K0–K3 未重新查询服务或学习状态，压缩后不要把旧观察当当前实时状态。
- 最近记录的业务累计用量（见本机账本）、100 万总额／80 万暂停线；K0–K3 没有读取最新账本，不声称当前仍为该数字。主／子 Agent 宿主对话用量无可信统计，另记 unknown，不计成零。
- 架构课已明确获准使用 MiniMax 中国 API／minimax-m3，不需重复请求相同范围许可；底层 16 份依据快照及密钥不因课程授权就默认外发。
- K0–K3 新业务模型 API 调用 0。不要为新知识准备自动重启／停止服务、改预算 context 或重新生成已有课。
- 用户真实试学、当前收尾的原生教学对话验证仍需看实际记录；用户打开页面不能被代理推断为完成或掌握。

如确需运行服务，读 tools/learning_book/LOCAL_USE.md，使用正式 runtime start／status／stop 和 `.learning-book-runtime/local/runtime.json`；不要复用旧 I6 armed 探针。凭据不输出，账本不清零。

## 8. 工作方式与最容易误用的边界

保持中文、渐进读取、合理只读独立审查；主 Agent 负责实现和修复。遵循当前会话实际多 Agent／技能规则，不把历史审查意见当认证。需要 Skill 才读，不自动安装新服务或插件。

不得把 K0 29 项协议核对、K1 29 项、K2 37 项、K3 38 项测试和 A01–A33 业务验收相加当成一个完整通过数字；不得据此宣布知识准备全链、S2–S5、真实宿主认证或权威掌握评估完成。

K0–K3 acceptance.json 绑定了其代码、样例和证据字节。后续修改受影响代码后按实际变化重验并写新记录；不要改旧 acceptance 摘要让旧通过“继续成立”。既有 raw 正文、正式维护规则、历史课程和学习证据保持原有边界，任何新实现先用临时库。


## 9. 2026-11-13 后续执行检查点

本次按 `learning-system-next-execution-handoff.md` 的三批范围执行，不重做 K／I／Q 历史阶段，不提交或推送。

- Q3 五条隔离调用已按 call_id 归并，新增用量（见本机账本）；日常账本用量（见本机账本），实报与估算见本机账本。原免计基线、80 万暂停线、100 万上限和历史 interrupted／估算标签不变。归并冲突拒绝及零增量重放见第一批证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-delivery/batch-1/README.md）。
- 日常已升级到 Q3 `release-04`，独立备份恢复通过。随后为保持 E1 项目源码演进后的重启兼容，使用原 Q3 site 同步项目接线，当前控制身份为 <本机控制实例>，`authoredDeliveryBuild=null`。最终服务运行中，E1 未部署到日常。
- 原课程、作答、聊天和项目证据已对照。首次 I4 为 7 页，当前课程 8 页，当前检查保留 `binding=unknown`；没有用旧基线覆盖当前事实。I5 partial 仍按实际覆盖表达。
- W1 已交付统一 `inspect-task`／`describe-input`／`prepare-next`，五阶段与既有单步语义一致，缺审、stale、越界、未知操作和中断续接均有检查。真实 CLI 冒烟及 132 项相关检查通过，见第二批证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-delivery/batch-2/README.md）。宿主回合和 provider tokens 不可见，仍为 unknown，不发布节省比例。
- E1 已交付作者正文写入、明确整书完成、请求级 journal 和替代 activity/book。六组真实 CLI／Production／loopback HTTP 检查通过，覆盖 I4／I5、丢失响应、并发、旧 revision、缺审、运行中、缺内容、来源变化、已认可替换和恢复，见第三批证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-delivery/batch-3/README.md）。真实模型、认证、索引生成和用户试学未验证。

E1 原组合 `batch-3/run-31` 的 153 项不同检查全部通过，失败／错误／跳过均为 0，耗时 354.797 秒；其中六组为 E1，其余 147 项为相关回归，重跑不累加为不同测试数。独立复审随后用新反例确认 R1–R5 五项遗漏，因此原通过记录不是当前验收结论。

R1–R5 修复候选为 `e1-release-05`，实际修订、旧版反例和失败原件见修复证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-delivery/remediation-1/README.md）。最终 158 项组合及 W1／用量 13 项全部通过，合计 171 项不同检查，失败／错误／跳过均为 0。第二轮独立复审另确认 F1–F3 三项相邻缺口。

F1–F3 续接候选为 `e1-release-06`，见第二轮修复证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-next-delivery/remediation-2/README.md）。最终 162 项组合及 W1／用量 13 项全部通过，合计 175 项不同检查，失败／错误／跳过均为 0。

随后经用户明确指派，`e1-release-06` 已受控部署到日常，控制身份为 <本机控制实例>；原课程和证据文件保持，重启及 41 项相关回归通过。目标课程项目 五章、概览和定稿首题已发布，I4 为 `baseline_consistent`，等待用户亲自试学和完成独立设计实验。累计用量（见本机账本），本窗口新增用量（见本机账本）。见部署与试学报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-system-e1-trial/README.md）。没有提交或推送；其他方案工作包不因此扩大完成范围。