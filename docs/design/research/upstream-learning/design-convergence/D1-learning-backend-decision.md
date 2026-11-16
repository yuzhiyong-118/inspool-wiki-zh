---
type: meta
title: D1：学习主体验与底座选择
status: design_decision
updated: 2026-11-09
topic: 学习底座与主体验选择
related_sources: []
related_synthesis: []
---

# D1：学习主体验与底座选择

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-10。状态：静态设计专题完成；未安装、运行或实测产品。与 [D2](D2-data-and-handoff-contract.md)、[D3](D3-first-learning-scope.md) 一起构成建议，不能据本文自动部署。

## 1. 决定及其依据

**推荐 DeepTutor 的 Book 网页学习作为首个主体验，复用其后端、Web 和必要模块；OpenMAIC 保留为固定课堂需求的替代方案。** 不同时部署两套学习应用，不抽取其中的 loop 再造一个 Agent。

这里的 Book 是生成后可反复打开的交互书：章节、内容块、随堂选择题、页边追问和阅读位置；不是每次开页面重新生成。外部 Agent 提交已整理的材料、目标和来源，应用完成教学表达。知识库仍独立存在。

推荐理由是产品匹配，而非功能数量：用户首先需要自主打开内容、阅读、追问、练习、恢复并把表现交给外部 Agent，尚未要求讲台、多角色演出、连续播放或音视频课件。Book 可直接承接这条路线；同一产品的 Reading 为后续“不先成课”的入口留下真实接口。代价是必须安装 Book 的依赖闭包、维护文件与 SQLite 混合状态，并接受首个闭环不包含书面题自动批改。

OpenMAIC 在可播放课堂、场景编辑和短答评分方面更直接。它未被判为不可行；其 PG 和常驻生成服务是持久性的合理成本。若短答原文与模型批改是首期硬要求，或用户主要需要可播放课堂，应改选 OpenMAIC，而非给 Book 再造评分/播放子系统。

## 2. 同一资料、同一情境的比较

静态情境：两篇有权使用的 Markdown 技术资料，一篇讨论任务幂等，一篇讨论失败重试；外部 Agent 查询已有 wiki，整理一个短学习单元。此处没有执行样例、调用模型或声称教学质量通过。

| 环节 | 完整 OpenMAIC | DeepTutor Book / Reading |
| --- | --- | --- |
| 收集后暂存、明确要求才整理 | 项目工作区负责；材料库可容纳学习副本，不能取代独立原文 | 项目工作区负责；DeepTutor KB 是学习投影，不是正式 wiki |
| 生成结构化学习内容 | material → generation-run → outline 确认 → scenes/actions →课堂 | selected source_refs/KB → Book proposal → spine 确认 → pages/typed blocks |
| 打开、讲解和追问 | 场景播放；live Director、子角色/工具处理追问 | 阅读章节；BookChatPanel 提交当前 book/page 的普通 chat turn |
| 答题 | quizAttempt 保存答案/阶段/结果；短答走模型评分，存在已确认的失败基础分 | QuizBlock 保存选择与客户端判分；书面题默认揭示答案/自评，不是自动批改 |
| 关闭后恢复 | 课程文档、Runtime session/record 和客户端恢复逻辑 | 书/页文件、Progress、SQLite chat session；当前页和题目尝试可读 |
| 外部 Agent 读取 | 课程 API + RuntimeStore HTTP；需项目组装来源、快照和失败语义 | Book JSON + sessions API；原生 Markdown export 只是书的内容，不是学习结果包 |
| 打开原文，只问一个局部问题 | 材料与 workbench 可用于研究/生成，但课堂学习不直接等于保留原文阅读位置的完整体验 | Reading 有材料、workspace、位置/书签、相关会话路径；不要求先生成 Book，需增加 reading/notebook 模块 |
| 支线后回主线 | 课堂 Director/场景承担主线；不能把其所有状态当作阅读位置 | 页边追问保留当前页；Reading 是另一种领域活动，不能拿 Book progress 假装覆盖 |
| 保存有价值的结果 | 通过项目交接形成候选 | Book captures 可保存选段/笔记，approved 只属上游 capture，不等于正式 wiki approve |

首期只交付 Book 主流程，Reading 作为已定位的扩展而非本期第二条完整闭环。临时局部问题可继续由外部 Agent 或现有聊天处理，不强迫其生成交互书。

## 3. 真正需要运行什么

| 项 | OpenMAIC 课堂组合 | DeepTutor Book 组合（推荐） |
| --- | --- | --- |
| 应用 | 完整 Node/Next 应用及生成后台；不能只用 storage + DSL SDK | core + server + Web；Python 后端、Next Web，复用 Python 引擎默认路径 |
| 领域模块 | 生成、课堂、Director、quiz、材料/提取及持久存储 | books、knowledge、parsing、questions、visualize、mastery；依赖闭包按 manifest 计算 |
| 默认状态 | PostgreSQL + 文档/资产目录 + 用量日志等 | 本地文件 + SQLite，固定一个后端 worker、默认 memory coordination；无需外部 DB 服务 |
| 模型 | 课程生成、Director、短答评分；媒体按需 | 书提案/来源探索/大纲/块生成、问题 pipeline、页边 chat；所选检索需要 embedding |
| 本项目选用的检索 | 可按需读取材料，不额外引入另一套 RAG 产品 | 复用本地 llamaindex pipeline；配置 embedding，承担分块/索引依赖，不宣称完全无向量栈 |
| 重依赖 | 视频 render-service、PBL 沙箱按功能另算 | parsing 自带多种文档依赖，knowledge 带 llama-index/FAISS 等；额外 OCR/browser/Manim、providers、Reading、Memory 等不默认启用 |
| 可选服务/前端 | 不启用视频导出、PBL 执行服务 | 不启用 PocketBase、Redis 多 worker、Partners 或额外桌面前端；源码 Web 与打包 Web 是替代交付形态 |

DeepTutor 的确切必要模块集合是 `{core, server, web, books, knowledge, parsing, questions, visualize, mastery}`，其 `requires` 闭包没有 reading/notebook；源码开发使用 checkout 的 Web，wheel 部署使用同版本打包 Web，不能将两者算成两套前端。包存在/版本一致/安装可用仍需后续定点验证。不能只安装 core 然后宣称有 Book 网页。

本期方案采用单 worker 的源码/同版本包形态作为部署依据；**不直接照抄默认 compose**。固定源码的 compose 包含 Redis 及相关依赖，开头“两服务”的注释已不足以代表实际组成。单 worker 默认能力有配置与源码依据，未来实际部署仍需核对启动方式，不以删除一个 compose 服务冒充已验证简化。

对 DeepTutor，knowledge 中的导入文件和索引是项目来源的学习副本；只允许导入整理后的明确资料，不将整个正式 wiki 接为可写 workspace。外部 Agent 查询 wiki 不需要经过 DeepTutor RAG。

## 4. 四条决定性调用链与证据

固定提交：DeepTutor `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`（下称 DT）；OpenMAIC `cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0`（下称 OM）。所有事实限定于本地 manifest 版本，未证明运行质量。

| 点 | DT 的实际入口/状态 | OM 的实际入口/状态 |
| --- | --- | --- |
| 内容生成 | `api/routers/book.py` 的 POST `/api/books`、confirm-proposal、confirm-spine、compile-page → `BookEngine` → `BookCompiler` / QuestionPipeline → BookStorage | `app/api/generation-runs/route.ts` POST → startGenerationRun → 持久 run engine → stage/scenes |
| 教学 | `BookChatPanel.tsx:403–419` 的 `start_turn(capability=chat, book_references)` → WS/TurnApplicationService → turn engine；`book/context.py` 组装页内容 | `/api/chat/pi` → `lib/chat/pi/director-loop.ts` → call-agent/工具；播放另有 playback/action engine |
| 答案持久化 | `QuizBlock.tsx:170–197` → `BooksRoute.tsx:883–906` → `/api/books/quiz-attempt` → `progress.record_attempt` → progress.json；随后非原子的 assessment 同步可能返回 500 | `lib/quiz/runtime.ts` 的 submitted/reviewed → RuntimeStore records；`quiz-view.tsx:93–139,801–824` 包含失败兜底并持久化 |
| 机器读取 | GET `/api/books/{id}` 返回 book/spine/pages/progress；页边聊天映射后 GET `/api/sessions/{id}`，事件另有分页接口 | GET `/api/stages/{id}` + manifest，Runtime HTTP 的 sessions/records；schema/version 与内容版本分开 |

本地证据入口：

- [Book API](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/api/routers/book.py)：742–791、810–929、1102–1218、1269–1287、1373–1405。
- [BookEngine](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/book/engine.py)：1–38、471–535、1036–1169；[Compiler](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/book/compiler.py)：99–115、424 起；[QuizGenerator](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/book/blocks/quiz.py)：`_generate`。
- [BookChatPanel](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/web/app/(workspace)/learning/books/components/BookChatPanel.tsx)：`send`；[QuizBlock](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/web/app/(workspace)/learning/books/components/blocks/QuizBlock.tsx)：170–197；[Progress](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/book/progress.py)：70–107；[sessions API](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/api/routers/sessions.py)：456–526。
- [模块 manifests](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/modules/manifests)、[数据存储](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/docs-for-dev/DATA_STORAGE.md)、[模块组装](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/docs-for-dev/MODULES.md)；`runtime_settings.py` 的 backend_workers=1、turn_coordination.backend=memory。
- OM 的具体源码结论及修订见 [总体方案旧候选依据](../report.md)、REV-N1–N5/OPT（研究过程记录未随仓库发布：docs/design/research/upstream-learning/_notes/main-agent-evidence.json），包括评分兜底、版本、PBL、辅助日志及用量。

**重要限定：BookEngine 明确平行于 ChatOrchestrator，自己管理书/页队列、后台任务与恢复，不是 TurnCapability。** 通用 chat 的 durable admission/replay 不能自动担保 Book create/compile 的幂等与事务。已有页级合并、pause/resume 和重开恢复应复用，初次 create 失败则可能没有已保存的 bookId，不能盲目重发。

## 5. D2 核查后对推荐的限制

1. Book 的 Progress 保留答案，但 `is_correct` 来自请求；服务端校验主要限制 mastery linkage，不把整个 progress 改成可信判分。导出保留原值，另以固定题目做确定性复核；书面题自评另列，不称模型评分。
2. `BookInputs` 保存创建时输入，`Book.revision` 是乐观协作 token，KB fingerprints 检测来源变化；这些不是每次作答所见完整页内容的不可变版本。必须补学习前证据；未记录提交时 hash，历史绑定只能给协作级证据或 unknown，不能给严格证明。
3. Book 内容、progress、assessment、chat 之间没有一个全局事务；答题 API 返回 500 时可能 progress 已写入。先读再决定重试；使用同一个 submission_id，不创造另一个学习账本补偿。
4. QuizGenerator 返回的 anchors 为空，RAG 关闭时主要依靠章节目标/摘要；即使开启，也不能声称已具备逐题原文锚点。来源探索按 KB 检索，不能把勾选文件自动当成所有生成步骤的文件过滤；本期使用冻结的小批资料 KB，记录实际语料集合及截断。`blocks/_rag_helpers.py` 的可选检索可吞掉失败继续生成，READY 不证明来源被使用；准备者必须核对关键事实/题目。精准引用缺失就标 activity scope。
5. 原生 Book Markdown 导出不含完整学习事实；项目必须承担结果读取、只读证据与版本校验。该层为中等适配工作，不能以“薄”暗示只有几个字段。

这些缺口不阻断“辅助阅读与选择题练习”的有限闭环，不适合拿来做严格学习门禁。若要求严格提交时绑定、服务端权威评分或跨活动掌握判断，先扩展真实上游领域入口，重新核对成本与选型。

## 6. 复用成本与淘汰的组合

| 方式 | 本期决定与工作量性质 |
| --- | --- |
| 完整复用 | DT Book/Reader/chat/runtime/API/本地存储；配置和运维中等，未估算人日或性能 |
| 配置与使用约定 | 单 worker、指定学习 workspace/KB、模型/embedding、限定块、生成确认、学前冻结；小到中等 |
| 普通适配 | 资料生产回执、活动发现与基线、结果映射与证据导出；中等，是主要自有工作 |
| 上游补丁 | 本期不以改核心为前提；严格内容绑定、权威判分或更完整错误记录成为硬要求时单列 |
| 自建 UI/抽取 loop | 当前无必须自建的体验缺口；不采用。以后可替换 UI，继续复用现有应用服务 |
| OM + DT 双应用 | 重复学习入口/模型/状态映射，首期收益不足；不采用 |
| 再部署 Open Notebook/Kotaemon/Lattice | 机制已吸收，暂无独立产品职责；不采用。不是其产品不成熟 |

## 7. 会改变推荐的条件与最小验证

- 必须首期有书面答题原文及模型评分：比较 OM quiz 完整路径，不能将 DT 自评改名满足需求。
- 必须讲台播放、多人角色、可编辑幻灯成品：转 OM；无需先复刻到 DT。
- 主要任务是原文持续阅读：在同一 DT 底座启用 reading/notebook，单独映射 position/session；不默认再添一套产品。
- 固定 DT 模块组合启动不了、页边会话无法恢复或实际生成不能使用所选来源：在隔离数据目录，只验证“一份 MD→一页→一题→一回合→重开→JSON 读取”。这项后续定点验证可能改变推荐，不要求先完成项目适配器。
- 模型/embedding 费用、本机内存和生成质量目前未知。先限定小单元、关闭非必要能力并观察真实 usage；本文没有节省 token 百分比、价格或耗时承诺。

当前没有必须向用户再次确认才能完成设计的分歧。推荐是可复核的设计选择，后续实施任务书仍需单独编写。