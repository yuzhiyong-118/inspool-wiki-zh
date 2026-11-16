---
type: meta
title: 上游学习应用源码研究 · 关键发现报告
status: research_report
updated: 2026-11-10
topic: 上游学习应用源码研究关键发现
related_sources: []
related_synthesis: []
---

# 上游学习应用源码研究 · 关键发现报告

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

> 本报告是 `docs/design/upstream-learning-source-research-playbook.md` 的执行产出之一。
> 结论均引用 `source-evidence.json` 中的证据 ID；所有 ID 都可回溯到固定提交下的具体文件与行号。
> 2026-11-10 主 Agent 已直接修正评分失败、内容版本、PBL 与来源交接边界；当前结论以 §3.3、§8 和架构方案为准，§5 保留研究过程的更正历史。
> 后续 README/设计原则重读见 [上游设计动机与架构启发](upstream-design-rationale.md)：更正此前低估 DeepTutor 交互书与模块化形态的表述，比较各项目为不同学习体验付出的成本。
> [三个设计专题已完成](design-convergence/design-summary.md)，当前推荐为 DeepTutor Book，具体依据、交接与有限闭环见 D1–D3。本文 OpenMAIC 推荐保留为候选路径研究；新增事实直接定位在专题中，未改写本报告的 857 条历史证据计数。静态设计完成不代表产品运行通过。
> 完整方案见 [`architecture-proposal.md`](architecture-proposal.md)，提交验收说明见 [`acceptance-request.md`](acceptance-request.md)。

---

## 1. 研究基线

六个上游仓库均为本地固定提交克隆，本轮只做静态源码阅读。

| 项目 | 仓库 | 固定提交 | 许可证 | 证据条数 |
| --- | --- | --- | --- | --- |
| OpenMAIC | THU-MAIC/OpenMAIC | `cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0` | MIT | 272 |
| DeepTutor | HKUDS/DeepTutor | `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db` | Apache-2.0 | 285 |
| open-notebook | lfnovo/open-notebook | `a6b572eb9849785dfb7c747190a01b0bb99fedf2` | MIT | 87 |
| open-notebook-mcp | Epochal-dev/open-notebook-mcp | `a2cddbf65cba8c4c8de7be16566781b7612a9545` | MIT | 39 |
| Lattice | vimalinx/lattice | `762b00cb028ad1a86ee505db4ca5ed14103657ac` | MIT | 94 |
| Kotaemon | Cinnamon/kotaemon | `9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9` | Apache-2.0 | 80 |

- 全部 HEAD 与 [上游来源清单](../../upstream-sources.md) 记录一致，工作区干净，未做 checkout / pull / rollback。
- 本轮**未安装依赖、未构建、未启动服务、未调用任何模型 API、未 import 上游模块、未执行测试**。
- 证据总量 **857** 条，确定性分布：`source_confirmed` 846、`conditional` 5、`inference` 5、`unknown` 1。
- 其中 **26 条来自"复查轮"**（主执行者二次核对，针对初稿自身的过度概括与手册未逐条落到证据的条目），逐条列在 `_notes/main-executor-openmaic.md`、`main-executor-deeptutor.md`、`open_notebook.md` 的"追加"小节。
- 其中 **21 条来自"返修轮"**（2026-11-10，按验收记录 R1–R8 定点补证），逐条列在 `_notes/rework-r1-r8.md`（研究过程记录未随仓库发布：docs/design/research/upstream-learning/_notes/rework-r1-r8.md）；检索型证据的命令与范围记在 `_notes/search-evidence.json`（45 条）。
- 原始证据笔记在 `_notes/`（研究过程记录未随仓库发布：docs/design/research/upstream-learning/_notes）：`main-executor-*.md` 是主执行者第一手阅读记录，`openmaic.md` / `lattice.md` / `open_notebook.md` / `open_notebook_mcp.md` / `kotaemon.md` / `deeptutor.md` 是分派子代理的独立阅读记录，两组交叉验证。
- **证据索引完整性（R6）**：当前 857 条；主 Agent 独立复核文件、行号、提交、ID/引用并验证重建保留校正。历史 850 条的机械审计见 `_notes/audit_evidence_v2.py`；新增与修正源为 `_notes/main-agent-evidence.json`。这些检查不代替观察与推理的定点源码核实。

---

## 2. 证据方法与边界

本轮沿三条线索把"有声明 / 有实现 / 主应用已使用"分开：

1. **谁在用**：从生产入口（HTTP 路由、WebSocket、CLI、前端组件）反向 grep 调用方，而不是从库能力正向推断。例：`LearningService` 在 `deeptutor/learning/mastery.py` 之外的调用方有 HTTP 路由、WS 路由、14 个能力工具、turn 适配器、教学循环 augment、启动期 reconcile 六处（DT-LEARN-002~009、DT-MAIN-033、DT-MAIN-034）。
2. **哪条路径**：同一项目常有两条以上实现路径（DeepTutor 的 Python/TypeScript 双引擎、OpenMAIC 的课堂聊天/课程构建双路径）。凡涉及默认行为的结论，只采用**默认路径**的证据，非默认路径的结论单独标注。
3. **是否只是库**：`package.json` 声明了依赖 ≠ 源码 import 了。例：OpenMAIC 的 `package.json:76` 声明 `@modelcontextprotocol/sdk`，但全仓源码零 import（OM-MAIN-012）。

**"未找到"的口径**：所有否定结论都基于全仓静态检索（列出检索模式与排除目录），是"在该提交的该检索范围内未发现"，不等于全项目绝对不存在。相关条目在证据 `limitations` 中标注。

**复查轮（2026-11-09）**：初稿完成后做了一轮针对性复查，查两类问题——① 结论是否**过粗**（把"没有 X"错误推广成"只有 Y"）；② 手册点名但初稿未逐条落到证据的要求是否漏答。复查新增 **26 条证据**，产生 **4 处对初稿自身的更正**（见 §5.1），并补齐手册 §7 T3 与 §8 点名的三组问题（当前以 `architecture-proposal.md` 的责任、来源、能力与成本章节为准）。

**返修轮（2026-11-10）**：按主 Agent 的验收记录 R1–R8 做定点返修，新增 **21 条证据**、产生 **8 处对本文与结论的更正**（其中 3 处推翻初稿结论，见 §5.2），并对 850 条证据做了**机械审计**（历史审计，当前状态见 `acceptance-request.md`）。

---

## 3. 五条处理链的关键发现

### 3.1 资料与课件

**OpenMAIC 的“资料 → 场景化课堂”生产链很完整。** DeepTutor 也有来源到交互书、章节与 typed blocks 的生成路径，不能将“不同于 OpenMAIC Scene DSL”写成“没有课程化学习产物”；相关 README、模块与源码入口见 [补充设计研究](upstream-design-rationale.md#1-需要先更正的判断)。

- 对外 Agent 的官方 SOP 写在仓库内的 `skills/openmaic/references/generate-flow.md`：`POST /api/materials`（原始字节 + `X-Material-Filename`）→ `POST /api/generate-classroom {requirement, materialIds[]}` → 轮询 `pollUrl` → `result.classroomId`（OM-MAIN-013）。
- **服务端故意不接受调用方传入的 URL**（OM-MAIN-014），必须由外部 Agent 自己下载字节再上传。这决定了"外部 Agent 收链接"的工作流边界。
- `materialIds` 上限 5；web search / 图像 / 视频 / TTS 由服务端 `openmaic.yml` 槽位决定，请求不能逐次开关（OM-MAIN-017）。
- 生成是**多阶段服务端流水线**：researching → generating_outlines → generating_scenes → generating_media；失败可停在某一步并用 `POST /api/generation-runs/{runId}/retry` 只重跑该步（OM-MAIN-016）。阶段数 ≠ 模型调用次数。
- 应用内 Agent 的抓取工具体现了很好的"落地 + 短回显"模式：抓取后 `saveWebMaterial` 落库，只回 `page.markdown.slice(0, 2000)` 的预览并给出 `nextOffset`/`totalChars`（OM-MAIN-025）；材料正文按 8000 字符分页定点读取（OM-MAIN-026）。

**但 OpenMAIC 对材料不做 RAG——这一条必须写清楚，否则会高估它的"资料能力"。** 三条独立证据指向同一结论：

- 仓库里**确实存在**一套 RAG 实现（`lib/rag/`：`chunking/`、`ingest/`、`providers/in-memory-lexical-index.ts`、`types.ts`），但**全仓生产源码零 import**——在 `lib/ app/ components/ packages/` 中检索 `lib/rag` 命中 0（排除 `lib/rag/` 自身与 `tests/`）。**有实现、有类型，主应用未接线**（OM-MAIN-039）。
- 即便接线，它唯一的 provider 自述 `capabilities = { lexical: true, vector: false, metadataFilter: true }`——**纯词法、内存、无向量**（OM-MAIN-039）。
- storage 包的 material 后端只有 `types.ts` 与 `pg.ts`，**没有切块、没有向量索引**（OM-MAIN-047）；材料抽取是 `lib/server/agent-runtime/extraction-watcher.ts` 的**异步结算**（`readSettledSources`），与索引无关（OM-MAIN-047）。

**结论**：OpenMAIC 的材料链是"**抽取成文本 → 按字符分页喂给 Agent**"，不是"切块 → 向量检索 → 召回"。它强在**课件生产**，不在**材料检索**。

**DeepTutor 同时有资料导师和来源到交互书的路径**：knowledge/parsing 为资料解析与检索提供能力，Book 从来源生成章节、typed blocks、quiz 与 Page Chat；详见 README 第 448–472 行和 book/models.py。它与 OpenMAIC 的场景课堂契约不同，不能据此说没有课程化生产。实际模块依赖见 DT-MOD-006/020，补充取舍见 upstream-design-rationale.md。

**Open Notebook 的资料入口有两种形状且语义不同**：`POST /api/sources` 入参全部声明为 `Form(...)`（ONMCP-012），`POST /api/sources/json` 才是 JSON 模型入口（ONMCP-013）。二者返回同一个 handler。

**Open Notebook 的抽取/切分/嵌入/上下文四层全是自建的**，边界很清楚：

- **抽取**委托给外部包 content-core 2.x，引擎由 `ContentSettings` 单例决定：URL 取 `"auto"/"simple"/"firecrawl"/"jina"/"crawl4ai"`，文档取 `"auto"/"docling"/"simple"`，未设置回落 `"auto"`（ON-077）。`content-core` 的源码不在本 clone 内，各引擎真实抽取逻辑本轮无法验证（ON-001）。
- **切块**自建：`open_notebook/utils/chunking.py` 做内容类型判定（扩展名 + 启发式双路）并按类型选切分器（HTML/Markdown 头部感知 + 递归字符切分），chunk 尺寸/重叠/最小尺寸都可配置推导（ON-074）。
- **嵌入**自建：`open_notebook/utils/embedding.py` 提供批量与单条两种生成，外加均值池化（ON-075）。
- **上下文组装**自建：`open_notebook/utils/context_builder.py` 有 `build_notebook_context` / `build_source_context` 两个入口，内含按 token 预算的截断 `_truncate_source_to_token_budget`（ON-076）。

这四层是**六个项目里最完整的一套自建 RAG 数据面**，与 OpenMAIC 的"无 RAG"形成鲜明对照。

**Lattice 没有资料生产链**，它是桌面端的个人学习库。

**Kotaemon 是资料问答栈**：以"用户勾选的文件"为检索前提，未选中文件时直接返回空列表（KT-MAIN-010）。

### 3.2 教学交互

**OpenMAIC：场景图 + 四类专用渲染器 + 确定性判分 + 已接线的教学对话。**

- 主应用课堂按 `switch (scene.type)` 分派 `slide` / `quiz` / `interactive` / `pbl` 四类场景，各有专用渲染器（OM-MAIN-029）。`packages/@openmaic/renderer` 只导出画布/元素/效果层/`slideToPng`，**不含场景类型、判分、agent、持久化**（OM-MAIN-028）——即渲染包与教学域是分离的。
- 判分是**纯确定性**的：`lib/quiz/grading.ts` 全文只有 `import type`，类型擦除后物理上无法触达模型客户端（OM-MAIN-031）；`gradeChoiceQuestions` 同步、无 await/fetch；`isShortAnswer(q) => q.type === 'short_answer'`（OM-MAIN-030 定义题型）。
- 开放题不在此文件；有开放题时才会发出 HTTP 请求，无开放题时 `Promise.all([])` 不发请求（OM-MAIN-032）。

**返修轮补出的教学对话链（R2）——初稿只说"复用 Pi Director"，没把链写出来。** 真实链路是（全部有源码锚点）：

1. 页面输入 → 客户端**每回合 POST 一次** `POST /api/chat/pi`，请求体必须同时带 `messages`（客户端维护的历史）、`storeState`（stage / scenes / outlines / currentSceneId）、`config.agentIds`（OM-B-29、OM-B-37、OM-B-38）。
2. 服务端走 stage 槽位 + **强制 tool-calling 能力**校验，再进 Director 主循环 `runPiDirectorLoop`，**每请求重建** 4 个工具 + 压缩运行时（OM-B-01、OM-B-30/31/34~36、OM-B-46）。
3. 四个工具：`read_scene`（按需取场景证据，场景正文**不预载**，单次上限 24 000 字符，OM-B-03/18/19）、`call_agent`（委派教师/助教/学生子代理执行真实教学发言；legacy 子代理默认仅 12 条历史，OM-B-13/20/21）、`cue_user`（话轮交回用户，prompt ≤240 字符、选项 2–4 个，OM-B-22）、`close_session`（结束会话，结束原因四类，OM-B-23）。
4. 返回 **SSE**（15s 心跳）（OM-B-32）；对话落库为 `kind:'chat'` 的 runtime session + `chat_message` / `chat_session_state` 记录，**不入文档库**（OM-B-40、OM-A-087）。
5. 上下文与预算：压缩运行时 `contextWindow` 默认 128 000，压缩**保留** sceneId/revision、read_scene 事实、URL、时间戳与已委派的 agent 结果；压缩会话是**每请求内存态**（OM-B-08/09/10）。

**定性判分不是教学对话（R2 的关键区分）**：`POST /api/quiz-grade` 的真实形态是入参 `{question, userAnswer, points, commentPrompt?, language?}`、出参 `{score, comment}`、模型槽位 `quiz-grade`、强制输出 `{"score": <整数>, "comment": "<一两句评语>"}`，缺字段 400；**无会话历史、无场景上下文、无工具、非流式**（OM-A-086）。它回答"这道题得几分"，不回答"这里不懂，换个例子"。

**教学对话面全部在应用内，SDK 里没有**：`lib/chat/pi/` 20 文件 7209 行、`lib/chat/` 26 文件 7828 行、`lib/agent/runtime/` 1591 行，外部依赖 `pi-agent-core` / `pi-ai` 0.80.3（OM-A-084、OM-MAIN-022）。

**上游没有任何 quiz 提示计数**：全仓 386 处 `hint` 命中全部无关，quiz 侧没有"用了提示"的字段。因此"受辅助"只能**派生**——用同一 `sceneId` 在该次提交之前是否已有教学对话记录（OM-A-087 的 `sceneId` + OM-A-092 的阶段时序），且只能作为**证据标记**，不是掌握度判定。

**DeepTutor：单一"exploring loop"，教学能力复用同一个 AgentLoop。**

- 完整生产链：WS `/ws` → `TurnApplicationService.start_turn` → `ChatCapability.run` → `AgenticLoopPipeline.run` → `AgentLoop.run` → `python_scheduler.run_loop` → `host.invoke("call_round")` → `AgentLoop._call_llm` → `client.chat.completions.create(**kwargs)`（DT-LOOP-001~022）。
- 工具结果以 `role=tool` 回灌同一会话；无工具的轮次即终局（DT-LOOP-007~009）。
- 掌握度教学能力**复用同一个 AgentLoop**，只换提示词基底（DT-LOOP-001~022；`capabilities/mastery/capability.py` 自述 "An agent loop IS the tutor"）。
- `/ws` 统一 turn 协议 v2.0：11 种入站命令、16 种出站事件（DT-API-005、DT-API-006）。
- 另有 9 个 WS 端点，其中 `/ws/mastery-paths` 用于学习目标修订重放（DT-API-006 之后的 5.3 节）。

**Lattice 是纯桌面应用**：PySide6 + QtWebEngine，Python 侧通过自定义 URL scheme 与 bridge 通信，**没有任何对外服务接口**（LA-MAIN-006、LA-MAIN-009）。它的 `web.py` 是"给 Agent 用的两个网页接口"（搜索网页、读一页为文本），用 `httpx` 作客户端（LA-MAIN-007）。

**Open Notebook 的一次 `/api/search/ask` 不是"一次模型调用"，而是 1 + N + 1 次。** Ask 是 LangGraph 多阶段图：`START → agent → (conditional) provide_answer → write_final_answer → END`（ON-070）。

- `agent`（`call_model_with_messages`）是**规划器**，本身一次模型调用（同 `max_tokens=ASK_MAX_TOKENS=8192`），产出若干条 search term（ON-073）。
- `trigger_queries` 对每条 term 产出一个 `Send("provide_answer", {...})`，**按 term 扇出并行分支**（ON-070）。每个分支 = 一次 `vector_search(term, 10, True, True)` + **一次模型调用**（`max_tokens=8192`）；召回为空时该分支直接返回空答案、**不调模型**（ON-071）。
- `write_final_answer` 是**独立的合成调用**（同样 `max_tokens=8192`），`add_edge("provide_answer", "write_final_answer")` 使其在**全部扇出分支收敛之后**才执行（ON-072）。

所以一次问答的模型调用次数是 **1（规划）+ N（每个 term 一次）+ 1（合成）**，N 由规划模型决定，源码不设上限。这是"用一个问答入口换来多次检索+多次生成"的典型形态，成本必须按 N 计，不能按"一次问答一次调用"估。

### 3.3 学习状态（主 Agent 校正版）

DeepTutor 的 SQLite LearningTransaction 将进度、interaction 和事件一起提交，使用 revision CAS、幂等身份及明确的租约释放责任；事实、模型定性判断与策略计算分离，值得借鉴。它不是可直接抽走的零依赖学习包，整域规模、Pydantic/知识域依赖及调用方恢复接线见 DT-LEARN-022~027；`policy.py` 还导入 models/pending。当前不移植该域。

OpenMAIC 普通测验/聊天使用 RuntimeStore，按 learnerKey 分区、session 内 seq 排序、CAS 和单次追加的原子 sessionTransition 已有实现（OM-MAIN-034~038、OM-A-092）。**唯一业务写入方是上游应用，不是全应用所有领域只有一个 RuntimeStore 事务。** PBL v3 有独立 study/event/evidence 表及沙箱配置（OM-MAIN-044/045、REV-N3）。

复审确认的关键边界：

- **评分失败**：短答 API 失败会返回 `correct:null`、基础分及失败评语，仍可形成 reviewed/completed；与持久化失败留下 submitted 不同。导出逐题标 deterministic/model/fallback/missing/unknown，不能用 phase 判断评分成功（REV-N1）。
- **内容版本**：manifest.rev 是 freshness 计数；runtimeDslVersion 是记录契约版本。quiz attempts 没有完整题干/rubric 历史快照，也没有内容 revision 身份。当前文档和 rev 不能代替旧题版本；本方案在学习前固定内容证据，并在导出时检查基线，缺失或变化写 unknown（REV-N2）。
- **辅助证据**：聊天 session 的 sceneId 可选，记录有保留边界；同场景先行聊天仅表示有辅助迹象，缺记录不能推出独立作答（REV-N4）。
- **完成范围**：quiz/chat 的 completed 是对应会话/尝试的状态，不是整门课完成或独立掌握；课程结束按用户声明或另行定义的课程级规则表达。
- **来源范围**：上游没有逐题来源锚点，producerRef 不总是 runId（OM-A-088/089）。生产时保存 sourceId/hash 与 materialId/runId/stageId 回执；旧数据缺来源则保留 unknown。

本期交接保证 slide/quiz 及对应教学对话；interactive 声明 partial，PBL 暂不纳入默认生产及结果交接。课程内容快照、原始学习事实、派生标签和知识候选分别保存。完整契约与例子见架构方案 §4–§9。

Lattice 学习内容与 Git、Vault/index 写入绑定；适合隔离环境下借鉴交互，不直接接正式 wiki。Kotaemon/Open Notebook 的事实来源、引用和检索边界仍有参考价值，但不引入其整套依赖。

### 3.4 上下文与 token 控制

这是本轮最需要按路径区分的一节。不能把某个输入片段的裁剪外推为完整请求的硬预算。以下按路径说明。

**DeepTutor 的默认（Python）路径有两层，互相独立，且都是软的：**

- (A) 请求前的历史规划 + 滚动摘要：历史预算 `min(max(256, window*0.35), 131072)`，摘要预算 `min(max(96, budget*0.40), 16384, model.max_tokens)`，逐字尾巴 `max(128, budget*0.60)`（DT-MAIN-008）。模块自述 **"The budget is a planning target, not destructive truncation"**——最新的非空消息即使超预算也保留（DT-MAIN-009）。摘要由独立 agent 生成并作为 system 消息注入，**每次压缩额外一次模型调用**（DT-MAIN-010）。
- (B) 请求时的 context-window 守卫：预算 = `window * 0.9`；**只裁剪 `role == "tool"` 的消息内容**（替换为 snip marker）；裁剪完仍超预算 → 只 `logger.warning("... no tool results are left to trim; sending it as-is")` → **原样发送**（DT-MAIN-032）。这是"超预算仍发送"的确定路径。
- 计量单位是 token（tiktoken `cl100k_base`，不可用时退化为 `len(text)//4`）；**图片按 4096 token/张规划计**（DT-MAIN-012）——这是静态规划估算，不是供应商 usage。
- `context_budget.py` 只是事后计量与分解，**不是预算执行点**；真正的执行点是 `pipeline._guard_context_window`（DT-MAIN-032、DT-CTX-001~018）。

**OpenMAIC 也有两条路径，且默认值不同：**

- 课程构建 Agent 的压缩**默认关闭**，只有 `OPENMAIC_AGENT_COMPACTION_ENABLED=true` 才启用（OM-MAIN-007）。
- 课堂 Director 对话的压缩由 `settings.enabled` 控制，默认值来自外部包 `pi-agent-core` 的 `DEFAULT_COMPACTION_SETTINGS.enabled`；该包在本机未安装，**默认值未核实**（OM-MAIN-008，确定性 `unknown`）。
- token 数是 `estimateDirectorContextTokens(...)` 的**静态估算**，不是供应商 usage（OM-MAIN-009）。
- Agent 运行时是**有租约的持久会话扫描器**：scanInterval 1000ms、heartbeat 2000ms、leaseTtl 10000ms、maxConcurrent 2、maxAttempts 5（OM-MAIN-011）。

**Open Notebook** 的 `_truncate_source_to_token_budget` 用二分法在原文前缀上找能装进预算的最长切点（ON- 系列）；`ASK_MAX_TOKENS = 8192`。

**Kotaemon** 的证据上下文上界是 `max_context_length = 32000` token，证据串带 `file_name` 与 `(Page N)`（KT-MAIN-019）；引用抽取用 function calling 强制逐字引文且 ≤15 词（KT-MAIN-017），且**默认关闭**（`use_citation: bool = False`，KT-MAIN-018）。

### 3.5 MCP / API / 模块边界

| 项目 | MCP 方向 | 对外 HTTP | 进程内 API |
| --- | --- | --- | --- |
| OpenMAIC | **既不是 server 也不是 client**——全仓零 MCP 实现（OM-MAIN-012） | 110 个 `app/api/**/route.ts` 路由处理器（OM-056）+ 官方 Agent SOP | 无 |
| DeepTutor | **纯客户端**：只 import `mcp.client.*`，无任何 server 注册（DT-MAIN-035、DT-API-007~010） | 约 700+ HTTP 端点（静态统计 715）+ **9 个 WS**，**由 manifest 驱动**（DT-MAIN-039、DT-MAIN-045） | `DeepTutorApp` / `TurnApplicationService` / `ApplicationContainer`（DT-MAIN-041） |
| open-notebook | 适配器是 **MCP server**（FastMCP，33 个工具，ONMCP-001/002） | 后端自身 REST | 无 |
| open-notebook-mcp | 同上 | 通过 `OPEN_NOTEBOOK_URL` 调后端（默认 `http://localhost:5055`，ONMCP-004） | 无 |
| Lattice | **完全不存在**任何 MCP/HTTP 接口（LA-MAIN-006） | 无 | 无（GUI 内部 scheme/bridge） |
| Kotaemon | **纯客户端**（KT-MAIN-001~003） | 有 Web UI | 有 |

**DeepTutor 的模块机制值得单独点出**：`deeptutor/modules/manifests/*.json`（25 份）是**声明式目录**，不是插件加载器——`catalog.py` 读取并校验依赖无环等 8 类规则，docstring 明说 "Reading the catalog never imports a feature or creates its services"（DT-MOD-001/002）。HTTP 路由按 manifest 挂载，鉴权策略有四种（public / authenticated / learning / admin）（DT-MAIN-039）。

**DeepTutor 的依赖成本必须算清**：`mastery` 模块自身 `requirements: []`，持久化只用 **stdlib `sqlite3`**（DT-MOD-005、DT-MOD-008）；但 manifest 声明 `requires: ["knowledge"]`，闭包是 `mastery → knowledge → parsing` → 传递引入 **numpy、llama-index 栈、faiss-cpu、pageindex、bm25s** 加 parsing 的 10 项解析包（DT-MOD-006、DT-MOD-020）。好消息是**代码层耦合极小**：AST 扫描显示 mastery 拥有的代码对 knowledge 拥有的代码的**唯一模块级 import** 是 `lesson_evidence.py:23 → services.rag.source_pages`，其余全是函数内 lazy import（DT-MOD-007）。

### 3.6 部署形态与 SDK 边界（返修轮补，R1）

**初稿最大的结构性错误是把"完整应用 / 独立 SDK / 可抽取源码"三种形态的优点同时领走。** 源码事实把它们分得很清：

| 形态 | 提供什么 | 不提供什么 | 证据 |
| --- | --- | --- | --- |
| **完整应用**（Next.js + Postgres） | 课程生成 HTTP、四类场景课堂、Director 教学对话、判分、运行时学习记录、课程库、材料库、`.maic.zip` 导出/导入、独立播放器 | — | OM-MAIN-013/016/024/034~038、OM-A-001~048 |
| **独立 SDK** | 场景 DSL、存储契约与实现（http / pg / browser / s3）、场景级生成函数、渲染原语、导入、几何 | **没有** `/api/materials`、`/api/generate-classroom`、课堂 UI、教学对话、生成编排、导出/导入接线 | OM-A-012/014/021~023、OM-A-067、OM-A-081/082 |
| **可抽取源码** | 零运行时依赖的纯函数可抄：`lib/quiz/grading.ts`、`packages/@openmaic/renderer` | 抄过来只有零件，没有产品 | OM-MAIN-028/031、OM-A-021~023 |

- **课程生成 HTTP 需要真正的服务端**：`POST /api/generate-classroom` 调应用内 `startGenerationRun`，依赖 runner 与 run store；run store 只有 Postgres 一条路；worker 是**应用进程内的定时器**，不是独立队列或独立进程（OM-A-001/002/003/006）。外部 Agent 发 HTTP **不会**把服务端职责转移出去。
- **生成编排共 10123 行，全在应用内**：`lib/server/generation/` = `run/` 17 文件 6998 行 + `steps/` 10 文件 2772 行（OM-A-083）；SDK 侧 `@openmaic/generation` 只提供场景级生成函数，**模型调用由宿主注入**（OM-A-014/015/016）。
- **存储 SDK 不包含生成服务，也不包含完整课堂**：SDK 自带的 HTTP handler 只提供 runtime / document / 可选 asset 三个存储协议（OM-A-067）；课堂的四路 dispatch 在应用内 `components/stage/scene-renderer.tsx`（OM-A-025）。
- **可部署形态就是 compose**：`openmaic` 服务从仓库构建、发布到 `127.0.0.1:3000`、`depends_on: postgres (service_healthy)`、挂 `openmaic-data` 卷到 `/app/data`；`postgres` 服务为 `postgres:16`（库/用户 `openmaic`，默认密码 `openmaic-dev`，**发布到非回环前必须改**）；`render-service` 带 `profiles: [video-export]`，**默认不启动**（OM-A-095、OM-MAIN-020）。根包 `openmaic@1.4.2`，`engines.node >=22.19.0`，`packageManager pnpm@10.28.0`，`postinstall` 构建 8 个 workspace 子包（OM-A-094）。
- **部署前置是硬开关**：`isAgentRuntimeEnabled()` 读 `OPENMAIC_AGENT_RUNTIME_ENABLED`；`isAgentRuntimeConfigured()` = enabled **且** 有 `DATABASE_URL`；`isServerPersistenceConfigured()` 只看 `DATABASE_URL`。这些入口分别检查 persistence 或 agent runtime，不能把所有材料入口都归为一个开关；配置缺失可能返回 404（OM-A-085、OM-MAIN-019）。
- **发布状态不一致**：六个 SDK 包全是 `0.x`（必须锁精确版本）；`generation@0.3.31`、`importer@0.3.1`、`renderer@0.2.1`、`geometry@0.1.0` 有 public `publishConfig`，而 **`@openmaic/editor@0.0.12` 没有显式 publishConfig，registry 发布状态不能由此推出**（OM-A-081、OM-A-082）。
- **生成结果落到数据库，不是文件**：`producer: 'server-job'` + `producerRef: runId` 写入 Postgres 文档行，字节落服务端资产池；**没有任何服务端把课程写成目录或 zip 的路径**（服务端压缩包导出的唯一命中是 **skill**，不是课程包）（OM-A-009/017/018/019/020）。`.maic.zip` 导出是**浏览器触发**（JSZip），导入落到应用文档 store + 服务端资产池 + 设备本地 Dexie 镜像——**不是目录**（OM-A-042/043/044）；独立播放器是构建产物、完全离线，其 quiz 只是 React 本地状态（无持久化、简答不判分），PBL 退化为静态 briefing（OM-A-033~036、OM-A-039）。
- **课程当前变更计数是 manifest 的 rev，不能代替历史快照**：`GET /api/stages/{id}/manifest` 返回 `{rev, scenes:[{id, order, rev}]}`，由数据库触发器产生；上游**没有"冻结"标志位**（OM-A-097）。

---

## 4. 机制对照（八个维度）

| 维度 | OpenMAIC | DeepTutor | open-notebook (+mcp) | Lattice | Kotaemon |
| --- | --- | --- | --- | --- | --- |
| 资料与课件 | **最强**：完整生产链 + 官方 Agent SOP + 阶段化重试；**但材料不做 RAG**（`lib/rag` 有实现未接线，唯一 provider 无向量，OM-MAIN-039/047）；**产物落 Postgres 文档行 + 服务端资产池，无服务端课包导出路由**（OM-A-009/017~020） | 资料导师 + 交互书/章节/typed blocks；**默认检索是 llamaindex 向量 + BM25 融合**（DT-MAIN-046） | source 管理 + **自建切块/嵌入/上下文四层**（ON-074~076） | 无生产链 | 文件问答 |
| 教学交互 | 场景图 4 类 + 专用渲染器 + 确定性判分 + **已接线的流式教学对话**（Director，7209 + 1591 行，OM-A-084、OM-B-01~46） | 单 AgentLoop 复用 + turn 协议 v2.0 + WS | 问答流（SSE）；**一次 ask = 1+N+1 次模型调用**（ON-070~073） | 桌面 GUI + scheme/bridge | RAG 问答 |
| 学习状态 | 中：runtime 象限有状态梯 + CAS + 原子状态迁移 + 确定性测验尝试（OM-MAIN-034~038、OM-A-092）；**无掌握度、无目标推进、无通用导出** | **最强**：SQLite + CAS + 租约 + 幂等 + 事件排序；**但租约无 TTL，释放靠调用方**（DT-LEARN-022~024） | 无 | Git commit 序列 | 无 |
| 上下文/token | 两条路径，默认不同；静态估算 | 两层软预算 + tool 结果裁剪 + 额外摘要调用 | 前缀二分截断 | 未核实 | 32k 上限 + 每文档 LLM 打分 |
| MCP | 无 | 纯客户端 | **server**（适配器有契约缺陷） | 无 | 纯客户端 |
| HTTP | 110 个路由处理器（OM-056） | 715 个 HTTP + 9 个 WS，manifest 驱动（DT-MAIN-045） | REST + SSE | 无 | 有 |
| 模块边界 | pnpm workspace；**`@openmaic/dsl` 与 `@openmaic/storage` 是 npm public 可发布包**，storage 的唯一 runtime 依赖只有 dsl（OM-MAIN-040/041）；storage 后端 = 服务端 `http`/`pg` + 浏览器端 `browser`（KV=Web Storage，runtime/document/asset=IndexedDB），**无 filesystem 后端**（OM-MAIN-021、OM-A-051~054）；**但生成编排（10123 行）、课堂、教学对话全在应用内，不在 SDK 里**（OM-A-083/084） | manifest 声明式目录 + importlinter 契约 | Python 包 | PySide6 强绑定（传递依赖 Qt） | llama_index 栈 |
| 维护成本 | 中：Next.js + Postgres 硬要求 + 外部 `pi-agent-core` | 按所选 CLI/SDK/Web 与模块闭包估计，不叠加所有可选形态 | 中 | 高且不可拆（Vault Git 副作用） | 高（llama_index） |

---

## 5. 对首轮评审的更正（重要）

首轮 `docs/design/upstream-learning-architecture-review.md` 的结论本轮逐条复核，**有 6 处必须更正**：

1. **OpenMAIC 的"课堂 Director 压缩默认启用"依据错误**。首轮引用的 `enabled: true` 是 trace 结构体的硬编码字段，不是开关；真开关的默认值来自未安装的外部包，无法从源码确认。已降级为 `unknown`（OM-MAIN-008）。课程构建 Agent 压缩默认**关闭**这一条仍成立（OM-MAIN-007）。
2. **DeepTutor 的引擎分叉是三档不是两档**。`typescript` 单独就切调度器到 Node（模型调用与工具执行仍在 Python）；`typescript-native` 才把 provider 调用也搬进 Node。首轮"只有 `typescript-native` 才切 TS"不准确（DT-MAIN-003 更正）。
3. **首轮用 TS 路径的历史规划来描述 DeepTutor 行为，是把非默认路径的保证外推**。默认是 Python 调度器（DT-MAIN-001/002）。修正后的表述是：**两套引擎各有自己的上下文实现，不能互相引用对方的保证**；但默认路径同样有滚动摘要，所以"默认路径没有历史压缩"也是错的（DT-MAIN-007~010）。
4. **首轮"DeepTutor 的 `context_budget.py` 是执行点"不准确**。它是事后计量；执行点是 `pipeline._guard_context_window`（DT-MAIN-032）。
5. **Kotaemon 的"重排 / hybrid / 引用"三项在出厂状态下并非都真正生效**。重排默认标记为 True，但缺 `COHERE_API_KEY` 时**静默 no-op**（KT-MAIN-011/012）；"hybrid" 实现是朴素拼接而非融合算法，去重逻辑疑似失效（KT-MAIN-013/014，`inference`）；引用抽取是可选开关且需另开一轮 LLM 调用（KT-MAIN-017/018）。首轮按"能力存在"计收益是高估了。
6. **open-notebook-mcp 的问题不止"缺参数"**。SubAgent 曾判定"source 根本挂不上任何 notebook"，这不成立——后端 `SourceCreate.validate_notebook_fields` 会把 `notebook_id` 自动转成 `notebooks=[notebook_id]`（ONMCP-015）。真实失败点是**请求体格式错 + 端点选错**：适配器用 JSON body 打 `POST /api/sources`，而该端点入参经 `Depends(parse_source_form_data)` 全部声明为 `Form(...)`；正确的 JSON 入口是 `POST /api/sources/json`，适配器没有用它（ONMCP-012/013/014）。结论不变且更强：适配器**不能**当作现成接口层。

另有 3 处首轮未覆盖、本轮新增的关键事实：

- **OpenMAIC 官方提供云版 Live Demo（`https://open.maic.chat`），每天 10 次生成配额**（OM-MAIN-018）——这是"完整采用"路线里一个此前未被计入的选项与约束。
- **DeepTutor 的 `LearningService` 确实在生产链路**，有六个入口（DT-MAIN-033、DT-MAIN-034、DT-LEARN-002~009）。此前是"待确认"。
- **Lattice 的 Vault 有更强的 Git 副作用**：首次使用 `git init` + commit、`commit()` 内部是**无路径限定的 `git add -A`**（LA-MAIN-012）、`Model.__init__` **无条件**执行一次全树 commit（LA-MAIN-013）、`Vault.__init__` **改写用户 `.gitignore`**（LA-MAIN-014）。

### 5.1 复查轮对本文初稿自身的更正（4 处）

初稿完成后做了一轮复查（针对"结论是否过粗"与"手册要求是否都有证据落地"），发现并更正了 4 处：

1. **"OpenMAIC 的学习状态只有记录流"是过度概括。** 它有真实的**学习者运行时层**：状态梯 `active|completed|archived`、记录种类 `chat|quizAttempt|playback`、`learnerKey` 分区、CAS 追加、409/404 错误语义、确定性 `quizAttemptId`、完整 runtime HTTP 面（含 `/runtime/learners/merge`）（OM-MAIN-034~038）。初稿把"没有掌握度"错误地推广成了"只有记录流"。**更正后的定位**：它给的是**学习过程的事实记录与并发安全**，缺的是**掌握度判定与目标推进**（OM-MAIN-039~047 相关）。
2. **初稿漏了 OpenMAIC 的 SDK 边界，这会低估"复用现成接口"的可行性。** `@openmaic/dsl`（v0.13.0）与 `@openmaic/storage`（v0.39.3）**都是 npm public 可发布包**（`publishConfig` 指向 registry.npmjs.org、`access: public`、无 `private: true`）；`@openmaic/storage` 的**唯一 runtime 依赖只有 `@openmaic/dsl`**，peer 只有可选的 aws-sdk；`exports` 映射共 **19 个子路径**（OM-MAIN-040、OM-MAIN-041）。storage 包还**自带独立 HTTP 服务端**（`createRuntimeHttpHandler` / `createStorageHttpHandler`）与**版本化 schema 迁移**（校验和 + advisory lock）（OM-MAIN-042、OM-MAIN-043）。**更正后的含义**：我们可以**依赖这个包**而不是 fork 整个应用，适配面从"改造 Next.js 应用"缩到"实现 `RuntimeStore`/`DocumentStore` 接口"。
3. **初稿漏了 OpenMAIC 材料链的一个关键事实。** `lib/rag/` 有一套完整的切块/ingest/索引实现，但**全仓生产源码零 import**（未接线），且唯一 provider 是 `vector: false` 的纯词法内存索引；material 后端无切块无向量（OM-MAIN-039、OM-MAIN-047）。**OpenMAIC 对材料不做 RAG**——这直接改变"用不用引入检索栈"的判断（§4 对照表已改）。
4. **初稿把 Open Notebook 的问答当成"一次问答一次调用"。** 实际是 LangGraph 多阶段图 **1（规划）+ N（每 term 一次检索+生成）+ 1（合成）** 次模型调用（ON-070~073）。成本口径必须按 N 计。

另有 2 处"初稿未给证据、复查补齐"：Open Notebook 的抽取/切块/嵌入/上下文四层边界（ON-074~077），以及 DeepTutor 的默认检索 provider 与重排/引用的接线位置（DT-MAIN-046~048），后者用于回答手册 §7 T3 的"检索、重排、引用能否被首选产品覆盖"。

### 5.2 返修轮（2026-11-10）对本文与结论的更正（8 处）

按主 Agent 的验收记录 R1–R8 定点返修后，**有 8 处必须更正，其中 3 处推翻了初稿结论**：

1. **推荐组合错了：初稿说"以 OpenMAIC 应用形态 + 移植 DeepTutor learning 域"，这等于把两套学习存储拼在一起。** 初稿自己写"两者组合后，每一块都是引用一个已知实现或抄一个独立小模块"——但 `deeptutor/learning` 域的真实规模是**顶层 26 个 .py 合计 13826 行**（`service.py` 3388、`storage.py` 2284、`lesson_evidence.py` 1179、`models.py` 835…），其中 `models.py` 与 `storage.py` **依赖 pydantic**，`semantic_assessment.py` 还在函数内 lazy import 回 `lesson_evidence` / LLM 配置 / image replay / workspace knowledge（DT-LEARN-025/026）。初稿"约 2000 行、无第三方依赖"的概括**低估了整域**。**更正**：本轮推荐改为"完整采用 OpenMAIC 应用 + 不移植 learning 域"，详见 [`architecture-proposal.md`](architecture-proposal.md) §1/§7/§10。
2. **"用未采用的 DeepTutor knowledge/research 路径证明推荐组合已覆盖检索、重排、引用"是无效论证**（验收记录 R7 指出）。初稿 §8 用 DT-MAIN-046/047/048 说明 Kotaemon 的三项能力"已被首选产品覆盖"——而那些路径属于**我们决定不采用的 DeepTutor**。**更正**：本轮如实写明**本期不引入任何向量检索/重排/引用栈**，并给出无向量时的来源回溯链与它的边界（`architecture-proposal.md` §9.2/§9.3）。
3. **"storage 包只有 http/pg、浏览器端没有回退"把两件事混成了一句**（见 §3.3 第 5 条）。浏览器后端**真实存在**且实现了 CAS 与原子追加（OM-A-051~054、OM-A-068~070）；准确表述是"主应用统一接服务端、浏览器侧没有回退"。**更正**：按"实际引入"重新核算能力与成本（`architecture-proposal.md` §9）。
4. **初稿漏了教学对话链。** 初稿 §5 只说"课堂 Director 复用上游的 Pi Director"，但没有把这条链写出来（页面输入 → `POST /api/chat/pi` → `runPiDirectorLoop` → `read_scene`/`call_agent`/`cue_user`/`close_session` → SSE → 落 `kind:'chat'` 的 runtime session），也没有说明**定性判分（`POST /api/quiz-grade`：单次、无历史、无场景、无工具、非流式）不能代替教学对话**（OM-A-086、OM-B-01~46）。**更正**：补出完整对话链与上下文/预算控制（`architecture-proposal.md` §5）。
5. **初稿没有确定"唯一学习状态写入者"。** 初稿同时保留 OpenMAIC runtime（L1）与移植的 DeepTutor 判定层（L2），是**两套真值**。**最终校正**：业务写入方是 OpenMAIC 应用；普通 quiz/chat 由 RuntimeStore 管理，PBL 有独立领域表和事务（CAS + 原子 `sessionTransition`）；本期不做掌握度层，将来若做只能是**纯函数派生投影**（`architecture-proposal.md` §6）。
6. **初稿"约 2000 行、无第三方依赖"低估了 learning 域**（同第 1 条）。真实规模 13826 行，纯策略子集（`mastery.py` 40 + `grading.py` 64 + `policy.py` 581）约 **685 行**；policy 原文件仍有 models/pending 依赖。
7. **初稿漏了租约的恢复责任。** `mastery_path_leases` 表**没有 TTL 列、没有后台回收**，`acquire_path_lease` 只比较 turn 归属；释放是**调用方的责任**，上游有两处明确落点：`mastery_path.py:_cancel_active_learning_turn`（L108-L130，为"重启孤儿"显式释放）与 `learning_adapter.py:_release_superseded_lease`（L41-L72）（DT-LEARN-022/023/024）。**抽走 storage 不会让这些责任自动跟随**。**更正**：写进采用形式与依赖闭包一节（`architecture-proposal.md` §10.3）。
8. **初稿没有可实际部署的形态。** 初稿把"完整应用 / 独立 SDK / 可抽取源码"三种形态的优点同时领走。源码事实：生成编排 10123 行全在应用内（OM-A-083），教学对话 7209 + 1591 行全在应用内（OM-A-084），SDK 侧 `@openmaic/generation` 只提供场景级生成函数且模型调用由宿主注入（OM-A-014/015/016）。可部署形态就是 compose（应用 + `postgres:16` + 卷，OM-A-095）。**更正**：选定一种形态并给出"实际部署 / 依赖 / 复制代码 / 自建"四类清单（`architecture-proposal.md` §4）。

此外**上一轮 §3.3 第 5 条**已在 §5.2 第 3 条更正；**§7.3 的"引用不需要靠 Kotaemon，因为 DeepTutor research 路径默认开启"**这句论证同样依赖未采用的路径，按第 2 条一并更正：本期不引入检索栈，所以既不用 Kotaemon，也不用 DeepTutor research。

---

## 6. token 成本：能省的、可能多的、以及不能算的

本轮**没有任何实测数字**。以下只分析输入构成、静态调用路径与额外成本。

### 6.1 机制上确实能省输入的

| 机制 | 证据 | 省的到底是什么 | 边界 |
| --- | --- | --- | --- |
| 抓取后只回短预览 + 定点分页读取 | OM-MAIN-025、OM-MAIN-026 | 抓取结果不进上下文，只回 2000 字符；正文按 8000 字符页读 | 这是 **Agent 工具路径**；对外 HTTP 走 `/api/materials` |
| 工具 schema 延迟加载 | DT-MAIN-015~019、DT-TOOL-001~009 | 未加载的工具 schema 不进请求 | 默认只作用于 **MCP 工具与插件工具**，内置工具默认不延迟；**加载后会持久化累积**（`loaded_tools.json`），长会话仍会变大 |
| 前缀二分截断 | ON-系列（`_truncate_source_to_token_budget`） | 把单份来源裁到预算内 | 裁的是**前缀**，可能截掉后半段 |
| 证据上下文硬上界 | KT-MAIN-019 | 证据串 ≤32000 token | 是上界不是目标值 |
| 教学策略不调模型 | DT-MAIN-043 | 判定推进是纯本地计算 | 前提是**定性判定另走一次模型调用** |

### 6.2 机制上会**增加**成本或额外调用的

| 机制 | 证据 | 额外成本 |
| --- | --- | --- |
| 滚动摘要 | DT-MAIN-010、DT-CTX-002 | **每次压缩一次额外模型调用**，且摘要 agent 复用全局模型档位 |
| LLM 相关性打分 | KT-MAIN-007/008、KT-MAIN-016 | **每个被评分文档一次 LLM 调用**（并发），默认开启；可用 `USE_LOW_LLM_REQUESTS` 关闭 |
| 引用抽取 | KT-MAIN-017/018 | **独立于答案生成的额外一轮**，用 function calling 强制逐字引文；默认关闭 |
| 定性掌握判定 | DT-MAIN-037 | `semantic_assessment` 一次 `max_tokens=2200` 的模型调用 |
| 课程生成多阶段 | OM-MAIN-016 | 四个阶段；**源码只暴露阶段名，未暴露调用计数** |
| Ask 多阶段扇出 | ON-070~073 | 一次问答 = **1 + N + 1** 次模型调用（规划器 + 每条 term 一次"检索+生成" + 一次合成），每次 `max_tokens=8192`；N 由规划模型给出，源码不设上限 |
| 引用抽取（research 路径） | DT-MAIN-048 | research agent 的 `enable_citation_list` / `enable_inline_citations` **默认 True**，即引用是这条路径的**默认能力**（与 Kotaemon 的默认关闭相反） |

### 6.3 不能当作计费 token 的静态估算

- DeepTutor 的图片 4096 token/张（DT-MAIN-012）、历史预算比例（DT-MAIN-008）是**规划值**。
- OpenMAIC 的 `estimateDirectorContextTokens` 是**静态估算**（OM-MAIN-009）。
- Open Notebook 的 `token_count` 与 Kotaemon 的 32000 上界同属估算/上界。

### 6.4 本轮明确不能回答的

- 生成一次课程实际消耗多少模型调用与 token（源码未暴露调用计数接口；`app/api/usage` 路由存在但语义未核实，OM-MAIN-024）。
- 任何"节省 X%"的说法——本轮无 usage、无账单、无延迟数据。

---

## 7. 可复用入口（源码级）

### 7.1 OpenMAIC

| 入口 | 位置 | 说明 |
| --- | --- | --- |
| `POST /api/materials` | OM-MAIN-013 | 原始字节 + `X-Material-Filename` |
| `POST /api/generate-classroom` | OM-MAIN-013/017 | `{requirement, materialIds[] ≤5}`；**不接受 URL** |
| `POST /api/generation-runs/{runId}/retry` | OM-MAIN-016 | 只重跑失败的那一步 |
| `pollUrl` → `{classroomId, url}` | OM-MAIN-013 | 轮询契约 |
| `lib/quiz/grading.ts` | OM-MAIN-031 | 零运行时依赖的确定性判分，**可直接抄** |
| `packages/@openmaic/dsl/src/stage.ts` | OM-MAIN-030 | 场景/题型 DSL 类型 |
| `components/stage/scene-renderer.tsx` | OM-MAIN-029 | 四类场景分派结构 |
| `packages/@openmaic/storage/src/runtime/types.ts` | OM-MAIN-003 | `expectedLastSeq` CAS 契约 |
| `packages/@openmaic/dsl/src/runtime.ts` | OM-MAIN-034 | 学习运行时类型契约：状态梯 / kind 分类 / `learnerKey` 分区 |
| **`@openmaic/storage`（npm 包）** | OM-MAIN-040、OM-MAIN-041 | **可直接依赖，不必 fork 应用**：唯一 runtime 依赖只有 `@openmaic/dsl`，peer 只有可选 aws-sdk；`exports` 19 个子路径 |
| `packages/@openmaic/storage/src/server/index.ts` | OM-MAIN-042 | `createRuntimeHttpHandler` / `createStorageHttpHandler`——**持久化服务可脱离 Next.js 单跑**，并带鉴权/授权/merge 策略注入点 |
| `packages/@openmaic/storage/src/runtime/http.ts` | OM-MAIN-038 | runtime 的完整 HTTP 面（含 `POST /runtime/learners/merge`） |
| `packages/@openmaic/storage/src/pg-migrations.ts` | OM-MAIN-043 | 版本化 schema 迁移 + 校验和 + advisory lock（Postgres） |
| **`docker-compose.yml`** | OM-A-095 | **实际部署形态**：应用容器 + `postgres:16` + 卷；`render-service` 默认不启 |
| `package.json`（根） | OM-A-094 | `openmaic@1.4.2`、`engines.node >=22.19.0`、`pnpm@10.28.0`、postinstall 构建 8 个子包 |
| `lib/config/feature-flags.ts` | OM-A-085 | 部署硬开关：`OPENMAIC_AGENT_RUNTIME_ENABLED` + `DATABASE_URL`；缺任一 → 相关路由 404 |
| `app/api/chat/pi/route.ts` + `lib/chat/pi/*` | OM-B-01~46、OM-A-084 | **教学对话链**：每回合一次 POST、SSE、4 个工具、场景取证 24k 上限、压缩运行时 128k |
| `app/api/quiz-grade/route.ts` | OM-A-086 | 定性判分（单次、无历史、无场景、无工具、非流式）——**不能代替教学对话** |
| `app/api/materials/move` `/library` `/folders` | OM-A-096 | 资料暂存与分流的现成原语（move 全有或全无、`unfiled`、keyset 分页） |
| `app/api/stages/[id]/manifest` | OM-A-097 | 课程版本快照 `{rev, scenes:[{id,order,rev}]}`（DB 触发器产生） |
| `GET /api/generation-runs/{id}` | OM-A-088 | 课程 → 生成材料的可追链（`input.materialIds`） |

### 7.2 DeepTutor

| 入口 | 位置 | 说明 |
| --- | --- | --- |
| `deeptutor/learning/policy.py` | DT-MAIN-043 | "No LLM calls, no I/O" 的教学策略 |
| `deeptutor/learning/mastery.py` | DT-MAIN-042 | 掌握度公式 + 显式可替换点 |
| `deeptutor/learning/storage.py` | DT-MAIN-020~025 | SQLite / CAS / 租约 / 幂等 / 事件排序 |
| `deeptutor/learning/grading.py` | DT-MAIN-036 | 确定性判分，fail-closed |
| `deeptutor/learning/models.py` | DT-LEARN-016 | `LearningEvidence` 字段设计 |
| `deeptutor/runtime/registry/deferred_tools.py` | DT-MAIN-015~019 | 延迟工具加载 + 加载时再校验 + 会话持久化 |
| `deeptutor/app/facade.py` | DT-MAIN-041 | 进程内 API 形态参考 |

### 7.3 Kotaemon（只抄一层）

`libs/kotaemon/kotaemon/indices/qa/citation.py`（KT-MAIN-017）及其**字符级引文回锚到 PDF 页级高亮**的思路，是它唯一值得单独抄的部分。整套检索栈不建议引入。

**返修更正（R7）**：初稿在此处写"'引用'这件事不需要靠 Kotaemon，因为 DeepTutor 的 research 路径默认开启 `enable_citation_list` 与 `enable_inline_citations`（DT-MAIN-048）"——这个论证**依赖一条我们决定不采用的路径**，因此无效。本轮的真实结论是：**本期不引入任何检索/重排/引用栈**（理由见 `architecture-proposal.md` §9.2），所以 Kotaemon 与 DeepTutor research **都不引入**；来源回溯改走**非向量**的链（课程 → run → materialIds、图片 → sourceDocumentId、导出清单 → mediaIndex.sourceRef），并如实标注"逐题来源锚点在上游不存在"（OM-A-088/089）。

### 7.4 Lattice（只抄思想）

`lattice/web.py` 的 SSRF 防护（解析域名后拒绝回环/链路本地/组播/私有网段，含 fake-IP 段例外处理，LA-MAIN-008）是值得抄的设计。**Vault 不抄**。

### 7.5 open-notebook（材料侧四层，OpenMAIC 缺的那块）

OpenMAIC 对材料不做 RAG（OM-MAIN-039、OM-MAIN-047），所以"切块/嵌入/上下文组装"这三层如果我们要，就有两个来源：

| 层 | 位置 | 说明 |
| --- | --- | --- |
| 切块 | `open_notebook/utils/chunking.py`（ON-074） | 内容类型判定 + 按类型选切分器 + 可配置尺寸/重叠；**纯 stdlib/llama-index 切分器，无外部服务** |
| 嵌入 | `open_notebook/utils/embedding.py`（ON-075） | 批量 + 单条 + 均值池化；供应商由配置决定 |
| 上下文组装 | `open_notebook/utils/context_builder.py`（ON-076） | 两个入口 + 按 token 预算截断 |
| 抽取 | `open_notebook/graphs/source.py`（ON-077） | **委托 content-core 2.x**，引擎 `auto/simple/firecrawl/jina/crawl4ai`（URL）与 `auto/docling/simple`（文档）；`content-core` 源码不在本 clone 内 |

结论：**可借鉴切块/嵌入/上下文分层**；context_builder 还依赖领域数据库对象，不是可直接独立复制的纯函数；**抽取层要额外评估**——它依赖外部包 `content-core`，本轮无法核实其内部行为（ON-001）。

---

## 8. 选型结论（2026-11-10 主 Agent 修订）

**固定课堂候选是完整 OpenMAIC，项目适配集中在来源身份与回执、学习前输入证据、实际接口映射和学习结果组装。** 当前总体设计保留此候选；最终底座与范围由 D1–D3 与 DeepTutor 适用组合比较后决定。 学习事实由上游应用各领域维护，本项目不引入第二套可编辑学习库，不自建通用 Agent harness。完整方案见 [architecture-proposal.md](architecture-proposal.md)。

若选择 OpenMAIC 路径，已有范围建议是 slide+quiz+教学对话，interactive 交接范围为 partial，PBL 不纳入默认生产及结果交接；这是供 D3 采用或调整的建议。评分失败按真实兜底结果保留；内容版本不明不拼接旧题证据；没有聊天记录不等于独立作答。新增设计是项目决策，不能当作上游现成功能。

整体继续吸收的机制是：文档/资产/状态分离，持久生成 run 与阶段恢复，场景与材料按需取证，事实/模型判断/策略分层，窄适配器隔离上游，稳定来源引用与证据快照。当前不建插件平台、消息总线、第二套任务队列或完整向量栈；新增需求出现后再沿模块边界扩展。

预算优先复用上游并发/重试限制和 usage。一次 HTTP 教学回合可能有多轮模型、子代理及压缩调用；`/api/usage` 是部署级用量，不是价格账单或任务级硬预算，缺 usage 也会漏记（REV-N5、REV-OPT-01）。单用户 owner 模式与 shared owner 配置不能同时照抄（REV-OPT-02）。

源码误读已由主 Agent 校正；总体原则已更新，底座、真实契约与首期范围待 D1–D3 收敛，再形成实施任务书。本轮不部署、不实现，也不改现有阶段状态。

## 9. 未解决项（具体、有限、与决策相关）

| # | 未知项 | 为什么没回答 | 对决策的影响 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 生成一次课程的实际模型调用次数与 token | 源码只暴露阶段名，未暴露调用计数；本轮不跑 | 影响成本估算，不影响路线选择 | OM-MAIN-016/024 |
| 2 | OpenMAIC 云版与本地提交的能力差异 | 官方文档已声明可能不同 | 影响"用云版还是自建" | OM-MAIN-018 |
| 3 | 课堂 Director 压缩的默认值 | 默认值在未安装的外部包 `pi-agent-core` 里 | 不影响选择（课程构建路径默认关闭已确定） | OM-MAIN-008 |
| 4 | Kotaemon 去重逻辑是否恒真 | `llama_index` 未安装，无法运行确认 | 只影响是否抄 hybrid 实现；**本轮不引入 Kotaemon**，故不影响决策 | KT-MAIN-014 |
| 5 | OpenMAIC 补一个 SQLite storage 后端的实际工作量 | 本轮只做研究，不实现 | **本轮不再需要**：选定完整应用形态，直接用上游自带的 Postgres 后端，不写新的存储后端 | OM-MAIN-021/040/041、OM-A-079 |
| 6 | DeepTutor 套件依赖 `knowledge` 闭包的 numpy/faiss 是否真会随 mastery 启用 | manifest 声明与代码级耦合已核实，但实际安装集未实测 | **本轮不移植 learning 域**，故不影响决策；若将来按语义重写少量算法，可不带入知识检索闭包，但 policy 的数据模型和 pending 依赖仍需适配 | DT-MOD-005~007、DT-MOD-020、DT-LEARN-025/026 |
| 7 | Lattice 文档描述的 ACP 能力 | `docs/TEST_REPORT.md` 提到的测试脚本与 ACP 源码在快照中不存在 | 不影响当前课件选择；不因此否定其工作台设计 | LA-MAIN-016 |
| 8 | `content-core` 2.x 各抽取引擎的真实行为（`firecrawl`/`jina`/`crawl4ai`/`docling`） | 包源码不在本 clone 内 | 只影响"是否用 open-notebook 的抽取层"，不影响推荐路线 | ON-001/ON-077 |
| 9 | 交接包在真实长会话下的体积与读取成本 | 未实测 | 影响导出器实现（分页/流式），不影响路线 | OM-MAIN-038 |
| 10 | 上游升级时 `manifest` / runtime 契约的破坏性变更节奏 | 需跟随上游 release notes | 影响我们的读侧适配；接口集中在适配器中，仍需对真实路由族、schema 与迁移核对兼容 | OM-A-097 |

**已由返修轮解决、从未知项移出的（保留确认时间与边界）**：

| 原未知 | 解决时间 | 结论 | 边界 | 证据 |
| --- | --- | --- | --- | --- |
| npm 上 `@openmaic/dsl` / `@openmaic/storage` 的实际发布版本 | 2026-11-09（主 Agent 查询）+ 2026-11-10（源码侧） | 两个包在 npm 上存在；源码侧另核实其余四个包有 public `publishConfig`，editor 的实际发布状态仍未知 | 未联网核对 registry 上实际存在的版本 | OM-MAIN-040、OM-A-081 |
| `POST /runtime/learners/merge` 的合并语义 | 2026-11-10 | 事务 + `FOR UPDATE` 锁来源会话 + 迁移 + 校验；同 key 返回 0；**是 learnerKey 迁移，不是导出或去重** | 未实测；重复同 kind session 的合并策略属应用层 | OM-A-091 |
| DeepTutor 路径租约的超时回收策略 | 2026-11-10 | **没有 TTL，也没有后台回收**；释放是调用方责任，有两处明确落点 | 只读源码，未运行 | DT-LEARN-022/023/024 |
| 学习域移植的真实规模 | 2026-11-10 | 26 文件 13826 行；耦合部分 `storage.py` 2284 + `service.py` 3388；纯策略子集约 685 行；policy 原文件仍有 models/pending 依赖 | 静态行数统计 | DT-LEARN-025/026 |
| storage 包有没有浏览器后端 | 2026-11-10 | **有**，四个；浏览器 runtime 后端内含版本迁移/CAS/原子追加 | 只覆盖已实现的 backend 文件 | OM-A-051~054、OM-A-068~070 |
| SDK 能不能脱离应用单独用 | 2026-11-10 | 能，但只有零件——没有生成编排、没有课堂、没有对话 | SDK 消费规则见 extend-sdk.md（版本表已过期，以 package.json 为准） | OM-A-012/014/083/084、OM-A-082 |

**本轮完成不等于部署通过。** 研究通过只表示架构依据充分，不表示部署、教学效果或生产稳定性已验证。