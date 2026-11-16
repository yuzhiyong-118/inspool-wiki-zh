---
type: meta
title: 从上游 README 与设计原则重新理解架构取舍
status: research_analysis
updated: 2026-11-11
topic: 上游设计动机与架构取舍
related_sources: []
related_synthesis: []
---

# 从上游 README 与设计原则重新理解架构取舍

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-10。主 Agent 补充研究。读取本地 manifest 固定提交下六个项目的 README、设计原则与相关架构文档，针对关键更正定点看源码；没有安装、执行产品或调用模型。

后续 D1–D3 已按本文启发完成同情境比较，当前推荐改为 DeepTutor Book，见 [收敛结论](design-convergence/design-summary.md)。下文“OpenMAIC 用于固定课堂”的判断保留为情境分析，不代表当前选型；Book 生成独立于 chat turn 的接线和首期真实覆盖以专题为准。

**这次的重点是为什么划出这些边界，而不是再列一遍功能。** 下文明确区分作者的设计主张、源码可见结构和本项目的架构推断。设计文档不是运行通过证明；Lattice 自己列出了原则未完全实现的地方，Open Notebook 也有原则与实际存储边界不同的情况。

## 1. 需要先更正的判断

1. **DeepTutor 不能简单归为“没有课程，只能文档问答”。** [README](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/README.md) 第 448–472 行介绍 Book、Mastery Path、沉浸阅读与练习。Book 从来源生成章节与有类型内容块，含 quiz、卡片、图、交互内容和 Page Chat。[book/models.py](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/book/models.py) 有 BookInputs、SourceAnchor、Chapter 和 BlockType，[book 路由](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/api/routers/book.py) 有 proposal、spine 和生成入口。这足以推翻“没有结构化学习产物”的排除理由；并不证明它与 OpenMAIC Scene DSL、导出协议完全兼容。
2. **DeepTutor 的最小使用形态不必包含所有前端和模块。** README 第 693–731、814–844 行以及 [模块文档](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/docs-for-dev/MODULES.md) 描述 CLI/SDK core、可选 server/web 和独立功能分发。[CLI](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor_cli/main.py) 第 103–119 行进入 DeepTutorApp，与 [架构文档](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/docs-for-dev/ARCHITECTURE.md) 的共同应用服务路径一致。仍需计算具体模块闭包、版本与资源，不能反过来声称最小安装已实测很轻。
3. **Lattice 缺对外 HTTP、Vault 有 Git 副作用，不足以否定其整个设计。** 它把本地文件所有权和共同工作台作为目标；共享目录或桌面形态下，没有独立服务并非自动缺陷。直接把 Vault 指向正式 wiki 仍不合适，产品原则与 UI/上下文机制却很值得借鉴。

因此：完整 OpenMAIC 是**固定课件与课堂路线的合理首选**，不是已经证明在所有个人学习形态下都优于其他方案。不能把“课程包必须长成某种样子”当作未经讨论的用户目标。

## 2. 六个项目各自在优化什么

| 项目 | 文档明确的中心 | 架构优势与为何如此划分 | 代价与适用范围 |
| --- | --- | --- | --- |
| OpenMAIC | 将主题/资料变为可视课堂 | 先生成 outline/scene，再由 playback 与 action engine 播放，需要追问时进入 live Director；课程可检查、编辑、复用和导出。持续生成任务需要跨请求存活，因此选择常驻 Node + PG | 课堂形态强，状态和资源较多；预先生成适合成体系内容，临时小问题不必都走完整成课 |
| DeepTutor | 一个连续、可扩展的学习工作区 | 多种学习 capability 共用 turn 应用服务、上下文、授权与事件；CLI/WS/SDK 是同一服务的入口。独立模块减少各学习模式重复造会话、工具和恢复机制 | 共享 runtime 的协议与依赖治理复杂；模块化不等于无依赖，每个模式闭包要单算 |
| Open Notebook | 自有研究资料的理解与加工 | Sources/Insights/Notes 分开，来源跨 notebook 关联；Chat、Ask、Transformation 用不同输入与持久化语义。模型、提取等重集成交给专门库，研究应用聚焦知识层 | 外部库升级与排障跨仓；Async worker 和数据库要维护。研究系统不自动变成教学系统 |
| Lattice | 学习者和 AI 共用的本地工作台 | 状态在中间，双方走同一入口；按注意力与打断成本分工，结构化展示块由客户端渲染；文件与可撤销操作保护用户掌控 | 文件冲突、Git 操作和多面板编排有自身成本；“自评理解”与自动掌握门禁是不同产品选择 |
| Kotaemon | 可用、可定制的文档问答/RAG 工作台 | 将基础组件与应用/UI、索引与 reasoning pipeline 分开，使开发者能比较和替换方法；证据与文档预览是答复的一部分 | Gradio/索引栈有约束；提供扩展入口不保证默认重排和引用配置都已生效，也不说明必须引整栈 |
| open-notebook-mcp | 让外部 Agent 使用既有研究系统 | 业务仍在 HTTP 后端，MCP 负责工具发现、输入输出和传输；默认短输出、限量和 request identity 有助于外部消费 | 两套契约会漂移；README 的 progressive disclosure 不等于静态注册工具的 schema 真被延迟暴露，已有适配缺陷仍需核对 |

依据：[OpenMAIC README](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/README.md) 第 318–364、538–598、707–717、1002–1010 行；[DeepTutor README](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/README.md) 第 239–248、346–375、448–472、693–731 行；[Open Notebook README](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/README.md) 第 57–97、206–225 行及 [VISION](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/VISION.md)；[Lattice README](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/README.md) 第 20–120 行及 [PHILOSOPHY](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/docs/PHILOSOPHY.md)；[Kotaemon README](https://github.com/Cinnamon/kotaemon/blob/9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9/README.md) 第 34–85、252–286、367–376 行；[MCP adapter README](https://github.com/Epochal-dev/open-notebook-mcp/blob/a2cddbf65cba8c4c8de7be16566781b7612a9545/README.md) 第 123–135、282–290 行。

## 3. 最值得我们吸收的八项取舍

### 3.1 先写清产品边界，再讨论采用哪个框架

Open Notebook 的 [VISION](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/VISION.md) 明确研究助手的职责，也明确不承担文件存储、通用聊天或用户全部工作流。它还区分长期原则与当前阶段，避免把“当前先简单”变成永久禁令。[PDR-001](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/7-DEVELOPMENT/decisions/PDR-001-single-user-first.md) 的单用户优先只要求不白白封死将来的 owner/scope，不要求现在实现多租户。

**对我们：** 稳定核心是知识与学习证据的积累；课件、阅读、问答是消费方式。资料收集后可以进入研究、来源摘要、直接阅读、课程或知识候选，不能把“先生成一门课”变成所有学习的前置条件。先完整支持固定课件是阶段选择，不是让知识库从属于课程系统。

保留稳定 ID、来源关系、清晰的 scope 就能减少后续障碍；不据此预建账号平台、分布式服务或完整插件市场。重要取舍保留短记录：背景、决定、未选方案、代价及什么条件会促使重评，减少上下文压缩后反复讨论。

### 3.2 将人和 Agent 当作同一业务状态的客户端

Lattice 的 [PHILOSOPHY](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/docs/PHILOSOPHY.md) 第 7–18 行把共同状态与统一操作入口作为根原则。[Open Notebook ADR-003](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/7-DEVELOPMENT/decisions/ADR-003-streamlit-to-nextjs.md) 将前端改成 API 客户端，明确付出前后端两套构建的代价来获得集成能力。DeepTutor 则让 CLI、WS、SDK 汇入共同 turn service。

**对我们：** 用户页面、内部教学、外部整理不能各自维护业务真值。知识查询、候选提交、课程发现、证据导出等应用操作应有稳定入口；GUI/CLI/MCP 只是适配。原审批与正式 wiki 写入权限照旧，统一入口不等于所有客户端有相同权限。

同机优先时，结构化 CLI/文件回执可能就够用；外部 Agent 接入不必从 MCP Server 开始。反过来，也不应因上游没有 MCP 就排除其复用价值。

### 3.3 把可复用的资料加工结果独立于课程

Open Notebook 的 [Sources/Insights/Notes 模型](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/2-CORE-CONCEPTS/notebooks-sources-notes.md) 将原文、按来源保存的转换产物、用户/AI 笔记分开；一个来源可以关联多个 notebook。[Chat/Ask/Transformation 的比较](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/2-CORE-CONCEPTS/chat-vs-transformations.md) 解释了为何一次提取、持续对话和跨库搜索不应该都是同一个 loop。

**对我们：** 在明确整理时产生可复用的提取文本、来源摘要、关键段落及出处；以后多门课程共用这些材料，不反复让模型读相同正文。接受后的来源摘要沿用 `wiki/sources`，待整理加工物留在工作区，不另建一份平行知识图谱。

复用应关联原文 hash、处理方法/版本和生成时间；原文更新或处理规则变化才重新评估。摘要用于导航与背景，关键事实仍回原文核实。这里的价值是减少重复解析与模型输入，不是宣称摘要永远足够或现在就实现复杂缓存平台。

### 3.4 Agent 分工围绕节奏与状态所有权

Lattice 的设计哲学第 157–172 行直接说明：分工依据是打断成本。主讲维护路线，快答处理小障碍，练习教练按步骤推进，整理与应用制作在后台；支线结果通过轨迹回流，主线决定权不分散。OpenMAIC 则把不同课堂角色交给 Director 调度，优化的是课堂中的发言和动作配合。

**对我们：** 外部 Agent 做资料整理与重研究，内部教学维持当前学习节奏，这个分工有产品依据。但内部未必永远只能一个聊天线程：可以有不打断主线的支线问答，先作为同一服务的模式/会话，不为每种角色新建一个持久 Agent。

支线回主线只返回问题、来源定位、答题/解释结果、可能缺的前置知识和未解决点，不合并全部聊天历史。主讲决定是否调整路线；后台整理不得让当前解释等它完成。多角色的 token 成本也需显式计入，不因名称不同就默认并行调用多个模型。

### 3.5 上下文应由界面事实与按需内容组成

Lattice 第 75–94 行区分“路标、screen、tab、目录事实”；屏幕只说明正在显示什么，不证明知识库里有哪些内容。OpenMAIC 有课程大纲导航与按需 read_scene；DeepTutor 的 [RUNTIME_DESIGN](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/docs-for-dev/RUNTIME_DESIGN.md) 区分公开对话与 provider-ready 私有模型历史，要求工具调用和结果一起保留。

**对我们：** 每回合提供活动/课程 ID、场景或来源定位、用户明确提交的选段引用、待答题身份和近期结果摘要；正文、长历史和其他来源按需读取。公开对话、模型续接上下文和长期学习证据应分层，不能全靠一份压缩聊天摘要承担。

推理上下文可裁剪，历史答案/评分/来源证据应留存；显示层不用暴露模型私有 replay 字段。上下文结构稳定也利于前缀复用，但实际缓存命中与计费仍须看供应商 usage，不能仅根据提示相同就声称节省。

### 3.6 交互默认使用结构化声明，复杂生成按需要升级

Lattice 第 96–112 行让模型输出结构化展示意图，客户端用已有组件绘制题目、图表和卡片，复杂小应用才交给独立构建流程。它因此避免每次显示一个小题都先生成一个应用。DeepTutor typed blocks、OpenMAIC Scene/Action 也体现了内容协议与展示实现分离。

**对我们：** 即时解释不需要每次新生成整套 HTML 课件。先用文字、公式、图和已有交互组件；固定课程可预生成，针对回答的解释动态生成，答题结果持续保存。声明式组件输出与修改学习状态的命令分开，展示成功不能被当作领域写入成功。

这有利于以后自己维护界面：先增加一类显示组件与契约，而非改整个 harness。需要新交互时先问能否由现有块组合，复杂应用和 PBL 再承担执行环境与验证成本。当前完整 OpenMAIC 不因此立刻 fork，先判断上游现成组件覆盖多少。

### 3.7 个人化状态应有作用域与证据，而非一个“掌握分”

Lattice 把跨主题成立的信息与主题档案分开，并规定 AI 估计不覆盖用户自评（README 第 58 行，PHILOSOPHY 第 174–181 行）。DeepTutor 在 README 第 597–603 行描述轨迹、可审阅事实、跨面综合三级记忆；它的 mastery 又提供基于表现的另一种判断。这是不同语义，不是谁更正确。

**对我们：** 分清用户声明的目标/偏好、活动内发生的表现、导师的阶段估计、独立评估结果。跨课程画像、专题上下文、当前活动状态有不同寿命；“我懂了”“模型认为懂了”“独立做对了”不要写进同一个权威字段。

先在交接与来源记录里保留作者、时间、作用域和 evidence refs，便于外部 Agent 形成可审阅的专题总结。是否建设自动记忆图或复习算法，根据实际使用决定，不现在移植 DeepTutor 整域；但不能为了只做消费者而丢掉个体学习的连续性。

### 3.8 低部署成本来自边界与可选依赖，不只来自少写代码

Open Notebook 的 [ADR-002](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/7-DEVELOPMENT/decisions/ADR-002-external-libraries.md) 把 provider/提取集成委托专门库；[ADR-004](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/7-DEVELOPMENT/decisions/ADR-004-background-workers.md) 将长任务与请求解耦，但复用现有 DB 排队，避免一开始增加 Redis/Celery。其 [ADR-001](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/7-DEVELOPMENT/decisions/ADR-001-surrealdb.md) 选择 SurrealDB 是运维集中化的产品取舍，不能把作者的比较推成其他数据库技术上无法实现相同职责。

[ADR-007](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/7-DEVELOPMENT/decisions/ADR-007-optin-runtimes.md) 将 Chromium/OCR 等重依赖设为可选。DeepTutor 的模块与 lazy activation 同样避免没用到的 parser/provider 全部激活；短命解析子进程还解决本地库内存长期滞留，线程并不能自动解决这个问题。

**对我们：** 通常网页/文本用便宜的确定性提取，确有需要再启用浏览器渲染或 OCR；先复用所选应用的任务与状态服务。不为借鉴机制而部署多个完整产品，也不为省服务数强行把重解析塞进前台请求。能力描述与实现加载分开，缺依赖应明说；实际扩展点在需要时做普通接口，不预建通用插件系统。

## 4. 对当前方案的实际影响

| 决定 | 当前处理 | 重新评估的触发 |
| --- | --- | --- |
| 完整 OpenMAIC 用于固定课件学习 | 继续保留，有明确产品匹配；不升格为全知识系统唯一底座 | 用户主要转为资料阅读、长期导师、自适应路径时，重新比较 DeepTutor 的实际最小模块组合 |
| 课程前的资料/来源层 | 补充稳定 source、可复用提取物与来源摘要关系，课程只是其派生产物 | 重复解析/摘要成为成本瓶颈后，再建设实际缓存与索引 |
| 内外 Agent 接口 | 应用操作统一，GUI/CLI/HTTP/MCP 适配按实际消费者选 | 外部 Agent 需要稳定机器接口时，先看现有 CLI/API，不直接扩展几十个工具 |
| 教学交互 | 保留固定课件 + 动态解释；支线问答/后台整理是节奏原则，不立即增设服务 | 真实学习中主线经常被小问题或后台任务打断 |
| 用户学习连续性 | 保留用户声明、表现与推断的作用域/证据，不要求本期自动画像 | 多课程持续使用后需要回顾偏好、先修不足或复习建议 |
| 工程治理 | 记录决定与代价，成熟能力完整复用，自己的边界小而清晰 | 既有边界不再能表达真实需要，而非仅因看见新项目 |

更完整的设计需要说明每个项目为哪种体验付出哪些成本，再有选择地吸收。当前优先借鉴的权重也应调整：OpenMAIC 负责课堂成品，Lattice/DeepTutor 提供学习交互与连续性的参照，Open Notebook 提供知识工作流与边界治理，Kotaemon 提供可替换检索和证据呈现，MCP adapter 提供外部消费接口的经验与反例。