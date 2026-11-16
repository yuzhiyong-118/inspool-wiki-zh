---
type: meta
title: 开源学习应用源码对照与架构选型建议
status: historical_selection_review
updated: 2026-11-09
topic: 开源学习应用源码对照与选型
related_sources: []
related_synthesis: []
---

# 开源学习应用源码对照与架构选型建议

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-09。状态：首轮定点源码研究完成，尚未安装依赖、运行上游应用、执行上游测试或选定实施方案。

后续执行依据：[开源学习应用源码研究与架构建议任务手册](upstream-learning-source-research-playbook.md)。用户指定其他 Agent 深入源码研究、本对话主 Agent 验收；本轮根据实际处理方式提出架构建议，不要求部署与完整流程测试。

## 1. 选型前提：原架构可以推翻

用户最新明确要求：只要上游设计更合适，整体框架可以重选；上游已有 MCP、API 或完整应用时，可以直接使用，不必保留之前的目录流转、三方部署或自建 Agent Runtime。

因此，[前轮交接](course-consumer-architecture-handoff.md)中的三方分工是理解业务职责的参考，课件根目录独立运行是一个候选验证条件，均不是限制选型的硬要求。已有 S0／S1 投入也不是保留该架构的理由。

仍需满足的用户目标：资料先收集，按明确指令整理；外部 Agent 能利用已有知识完成较重的工作；用户有自己的学习界面，内部可调用优秀模型；答案与学习状态可恢复，并能被后续知识整理利用；优先单机部署，控制开发、运行和维护成本。当前正式知识库的维护规则仍以 AGENTS 为准；改变这些规则应另写具体提案。

研究顺序调整为：先看完整产品能否覆盖主要流程，再看现成 API／MCP 能否补足边界，最后才考虑 SDK 抽取或自行实现。

## 2. 本地研究基线

源码保存在本地研究工作区的 `references/upstream/`（不随本仓库发布），每个子目录是独立的浅克隆；由该目录 `.gitignore` 排除主仓库跟踪。完整来源、日期和状态见[版本清单](upstream-sources.md)。不要默认更新 main，后续结论先绑定下表提交。

| 项目 | 固定提交前缀 | 根许可证 | 本轮用途 |
| --- | --- | --- | --- |
| OpenMAIC | `cee7b7ff3b7f` | MIT | 完整网页课堂、课程生成接口、DSL／存储／渲染 SDK |
| DeepTutor | `60fb3bdfddb3` | Apache-2.0 | 完整教学 Agent、掌握度、学习证据与上下文管理 |
| Open Notebook | `a6b572eb9849` | MIT | 资料工作台、检索、内容提取与 HTTP 服务 |
| Kotaemon | `9ad3e4e49aa3` | Apache-2.0 | 检索、重排、引用与证据上下文组织 |
| Lattice | `762b00cb028a` | MIT | 本地桌面教学、文件式内容和轻量交互 |
| Open Notebook MCP | `a2cddbf65cba` | MIT | Open Notebook 官方文档推荐的独立社区适配器，接口方向与兼容性核实 |

根许可证已经读取；字体、素材、第三方内嵌代码及依赖的许可不由根许可证自动覆盖，实际抽取模块时再按所需范围核对。Star 不作为功能或稳定性验收凭据。

## 3. 第一轮选型结论

**优先评估直接采用 DeepTutor 或 OpenMAIC 作为学习端；没有必要先建设自己的完整课程 Agent。** 二者的重点不同，尚不能只凭源码阅读宣布其中一个整体更成熟或最终胜出。

| 路线 | 与我们目标最相关的能力 | 仍需验证的缺口 | 当前判断 |
| --- | --- | --- | --- |
| 完整采用 DeepTutor，外部 Agent 通过 HTTP／适配器协作 | 网页教学、目标与掌握度、练习／评估／复习、持久学习状态、上下文控制已有实现 | 外部资料与课程导入需要哪些接口；学习结果如何导出给知识库；Windows 单机依赖和真实体验 | 以理解、追问、练习为核心时优先验证 |
| 完整采用 OpenMAIC，外部 Agent 调用现有生成与存储接口 | 资料到课程、网页课堂、测验、交互场景，外部 Agent 已有 HTTP 工作流 | 目标级掌握证据、已有课件导入、学习结果交接；完整应用部署成本 | 以固定课件、可视化与课堂体验为核心时优先验证 |
| Open Notebook 加既有 MCP 适配器 | 资料工作台与外部 Agent 协作入口已经存在 | 适配器与当前后端兼容性；课程教学并非其完整核心；作为第二套产品是否增加负担 | 若首选学习产品已有资料管理，不立即叠加 |
| Lattice 为底座做定制 | 桌面交互、Markdown 内容与轻量模型循环可读性较好 | Qt 产品形态、Vault 写入／Git 副作用、对外交接与现有规则差异 | 保留候选，不默认重写为浏览器后端 |
| 自建应用并抽取各项目模块 | 可以精准控制交付形式 | 要自己接通 Agent、前端、状态和升级，容易把多个项目复杂度一起带进来 | 完整产品验证不适配后再选择 |

Kotaemon 主要是知识检索参考，暂不作为课程应用底座。不要为了“多借鉴”同时部署所有项目。

## 4. 源码中值得直接吸收的机制

### 4.1 课件数据、学习事实和媒体资产分别管理

OpenMAIC 把课程文档、学习运行记录、媒体资产和偏好设置放在不同存储接口里。`DocumentStore` 管课程；`RuntimeStore` 管学习者会话及按顺序追加的事实；`AssetStore` 管资源。学习记录的顺序由存储端 `seq` 决定，不依赖多个窗口的本地时钟；追加可带 `expectedLastSeq`，防止旧页面覆盖新记录。

**对我们的调整：**不必先自建一套课程目录规范。若整体验证通过，可采用其文档和学习记录接口；待学习／学习中／完成可以只是 UI 查询视图。若最终保留共享目录，也只用目录做交付，不再强迫每次细粒度答题都搬动文件夹。

证据：[运行记录契约](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/dsl/src/runtime.ts)、[RuntimeStore 接口](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/src/runtime/types.ts)、[存储职责说明](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/README.md)。

### 4.2 固定内容由渲染器展示，确定性评分不调用模型

OpenMAIC 用 Stage／Scene 表达课程与场景，普通幻灯片和测验有结构化类型。选择题走 `gradeChoiceQuestions` 本地比对，简答题按显式题型走另一条处理路径。Quiz 的 draft／submitted／reviewed、答案和结果进入运行记录，不只存在聊天文本中。

**对我们的调整：**常规课件展示、答题保存、选择题判分与进度计算由程序承担；模型用于讲解、追问、开放题评价和补讲。课件生成一次后重复学习不需要每次重新生成页面，但 AI 辅导仍按实际调用计费。

证据：[Stage／Quiz 契约](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/dsl/src/stage.ts)、[本地判分](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/quiz/grading.ts)、[作答持久化](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/quiz/runtime.ts)。这能减少部分模型调用；尚无本项目 token 节约百分比的实测数据。

### 4.3 学习目标和评估状态由领域服务维护

DeepTutor 的 `LearningService` 汇集作答、掌握度、复习调度与保存；`policy.py` 按知识类型判定掌握状态。其代码区分有提示练习和独立表现，记录目标、题目、会话、turn、反馈及提示使用等信息。`assessment.py` 将不同学习界面的评估归一，使用明确的提交身份。

**对我们的调整：**如果采用 DeepTutor，应先复用这些领域接口，再评估怎样导出知识整理所需的最少事实。无需另写一套相同用途的进度状态机。它的默认阈值和最近作答加权是具体教学策略，不是普遍成立的教育标准，不能直接成为正式知识入库凭据。

证据：[学习服务](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/service.py)、[教学策略](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/policy.py)、[评估归一](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/assessment.py)、[简单掌握度算法](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/mastery.py)。

### 4.4 持久状态比“模型记得”可靠，文件也不是天然更简单

DeepTutor 的学习存储实现使用工作区 SQLite、版本比较和事务；其说明明确指出旧的逐课 JSON 替换虽然单次写入原子，两个会话仍可能读到同版并相互覆盖。现在还持久化交互生命周期和幂等记录。

**对我们的调整：**单机部署可以共用文件，但不必坚持“所有状态都放一个课程文件夹”。若选中上游，优先以它的存储作为学习事实真值，导出文件给外部 Agent；避免外部 Agent 和学习应用同时改写同一份进度文件。目录、数据库、回执三者不可分别维护互相矛盾的权威状态。

证据：[LearningStore](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/storage.py)。这里是静态阅读确认存在的机制，尚未运行其并发与恢复测试。

### 4.5 工具 schema 按需加载，而非每次发送全部接口

DeepTutor 的扩展工具先提供简短清单，模型需要时调用 `load_tools` 加入完整 schema；加载权限会再校验，不仅靠清单隐藏。完整 schema 的加载结果会延续到后续会话轮次，因此长会话中仍可能逐渐变大。

**对我们的调整：**优先用选中产品现成的工具加载机制；学习时只启用必要的课程／检索能力。若宿主已经支持延迟加载，无需再自建另一套工具注册平台。按需加载能减少初始 schema 开销，但首次加载可能增加一轮调用，必须算总成本。

证据：[延迟加载实现](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/runtime/registry/deferred_tools.py)、[MCP 客户端适配](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/services/mcp/manager.py)。

### 4.6 分开展示历史、模型上下文与真实学习事实

DeepTutor 的 TypeScript chat-engine 以完整轮次分组规划历史，摘要须正常完成且没有工具调用才替换旧摘要；失败不推进归档位置。OpenMAIC 的 Director 压缩会记录压缩前后 token 估算、保留边界和失败，并提示摘要保留未决目标、场景版本及来源信息。

**对我们的调整：**聊天记录可以完整保存，模型每轮只读有预算的近期轮次与摘要；答案、评分、目标状态仍从持久存储读取，不能只留在摘要里。不要因做了摘要就删除证据或推断“全部学过”。

证据：[DeepTutor 历史规划](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/packages/chat-engine/src/context/history.ts)、[模型上下文投影](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/packages/chat-engine/src/context/conversation.ts)、[OpenMAIC Director 压缩](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/chat/pi/director-compaction.ts)。注意这些是不同引擎和路径，不能把一个路径的保证外推到整个项目。

### 4.7 抓取和提取内容落地，返回短预览，再按需检索

OpenMAIC 的网页提取使用 Readability 与 Turndown；工作台抓取成功后保存为 material，只先返回约 2,000 字符预览、材料 ID、长度与后续读取位置。Open Notebook 把内容提取交给 `content-core`。这些都说明基础解析应由现成库和程序承担，而不让模型反复从完整 HTML 中寻找正文。

**对我们的调整：**优先复用选中应用的资料处理链，外部 Agent 获得稳定资料标识并定点读取。提取结果、来源信息和失败／截断状态需保留；预览没有包含某段不等于源文件没有该段。动态网页、登录内容与复杂 PDF 的质量仍需样本验证。

证据：[正文提取](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/web-fetch/builtin-extraction.ts)、[存储材料并返回预览](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/agent-runtime/fetch-url.ts)、[Open Notebook 提取入口](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/open_notebook/graphs/source.py)。

### 4.8 显式选择资料范围，检索后限制证据上下文

Open Notebook 可逐份选择不加入、摘要或全文；单来源上下文构建还会按预算截断并标记。Kotaemon 的检索有 text／vector／hybrid 模式、top-k 与可选重排，之后单独组织带文件与页码的证据上下文。

**对我们的调整：**教学轮次优先围绕当前目标、当前课件和必要证据，而非每次附上整个知识库。使用上游的限定资料范围和检索接口，比先增加跨库多 Agent 调研更直接。RAG 限制的是每轮送入的资料量，不自动保证检索命中或引用正确。

证据：[上下文构建](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/open_notebook/utils/context_builder.py)、[检索与重排](https://github.com/Cinnamon/kotaemon/blob/9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9/libs/ktem/ktem/index/file/pipelines.py)、[证据格式化](https://github.com/Cinnamon/kotaemon/blob/9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9/libs/kotaemon/kotaemon/indices/qa/format_context.py)。

## 5. MCP／API 到底能否直接调用

| 项目 | 本轮查到的接口方向 | 能否据此直接作为我们的后端 |
| --- | --- | --- |
| OpenMAIC | HTTP 生成、材料、课程和持久化路由；外部 Agent Skill 描述完整 HTTP 调用流程 | 有直接集成路径，不必先包 MCP。尚未找到可据以确认其自身完整能力已作为 MCP Server 暴露的实现 |
| DeepTutor | 自己作为 MCP Client 连接工具；学习路径有 HTTP API、WebSocket 和模块初始化接口 | 可以评估 HTTP 协作。MCP 设置页面不是对外教学 MCP Server 的证明 |
| Open Notebook | 本体有 HTTP API；官方文档推荐 Epochal-dev 的独立 MCP Server | 可优先验证适配器，但它是单独维护的项目，不能当成本体版本一致的完整接口 |
| Kotaemon | 已看到 MCP 配置管理和客户端工具适配 | 尚未确认它将自身知识库能力对外暴露为 MCP Server |
| Lattice | 当前阅读到的主要入口为 Qt Bridge／本地工具 | 暂未确认现成对外 MCP 服务；不能据此假设外部 Agent 可直接驱动所有功能 |

直接证据：[OpenMAIC 外部生成流程](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/skills/openmaic/references/generate-flow.md)、[DeepTutor 学习 API](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/api/routers/mastery_path.py)、[Open Notebook 的 MCP 文档](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/docs/5-CONFIGURATION/mcp-integration.md)、[适配器源码](https://github.com/Epochal-dev/open-notebook-mcp/blob/a2cddbf65cba8c4c8de7be16566781b7612a9545/src/open_notebook_mcp/server.py)、[Kotaemon MCP 工具](https://github.com/Cinnamon/kotaemon/blob/9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9/libs/kotaemon/kotaemon/agents/tools/mcp.py)。

**适配器的静态缺口：**Open Notebook MCP 的 `create_source` 声称支持链接、文本和上传，但其参数没有文本正文或文件；`execute_chat` 和 `get_chat_context` 的部分参数在适配器可省略，在当前后端请求模型中为必填。先验证最小调用组合，不能照 README 宣称所有工作流开箱即用。服务是否启动成功、错误码和具体兼容影响尚未实测。

## 6. token 成本：哪些真能省，哪些可能增加

| 机制 | 可减少的成本 | 代价或边界 |
| --- | --- | --- |
| 本地源码＋定点检索＋持久研究笔记 | 研究时重复抓网页、发送导航和重复读整篇源码 | 克隆本身不减少模型上下文；后续仍要控制读取量 |
| 课件生成后固定渲染、确定性评分 | 重复生成页面与简单题判分调用 | 开放题、追问与补讲仍需模型 |
| 资料提取一次落地、检索再读 | 重复解析及每轮全文输入 | OCR、转写、embedding 和检索服务可能有额外成本 |
| 按需加载工具 schema | 常驻工具说明和参数的上下文 | 初次发现可能多一轮；已加载 schema 会累积 |
| 完整原始记录＋滚动摘要 | 长会话重复发送历史 | 摘要也需调用，且不能取代学习证据 |
| MCP／HTTP 返回有限结果 | 跨应用搬运和自建适配代码 | 协议本身不省 token，也不承担整个流程的预算控制 |

两个实际反例需要记住：

1. Open Notebook MCP 有 `search_capabilities`，但 AST 静态检查到 **33 个函数均以 `@mcp.tool()` 注册**。这不是服务器默认只暴露一个搜索工具的实现；schema 是否按需进入模型取决于客户端／宿主。不能把 README 的 progressive disclosure 直接当作传输层 schema 缩减证明。
2. Open Notebook 的 Ask 是规划 → 对搜索结果分别生成回答 → 汇总的流程。若外部 Agent 已能综合，直接调用有范围和数量限制的 `search` 可能比再嵌套一次 Ask 更省模型调用；Ask 是否更划算需比较回答质量与总用量。

此外，DeepTutor Python 路径的一处 context guard 在删减工具结果后仍超预算时会告警并继续发送；OpenMAIC Director 压缩失败会回到未压缩消息。上下文控制不是所有路径上的硬预算保证，更不能代替任务级费用、时间与重试上限。

证据：[MCP 静态注册与搜索](https://github.com/Epochal-dev/open-notebook-mcp/blob/a2cddbf65cba8c4c8de7be16566781b7612a9545/src/open_notebook_mcp/server.py)、[Ask 图](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/open_notebook/graphs/ask.py)、[DeepTutor guard](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/loop/pipeline.py)、[实际请求计量](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/loop/context_budget.py)。不提供未经测量的节省百分比。

## 7. 工程成本与不应照搬的部分

- **SDK 不等于整套课堂。**OpenMAIC `@openmaic/renderer` 的导出以 `SlideCanvas` 等幻灯片组件为主；测验、教学 Agent、学习状态仍在其他包或应用代码。直接取 renderer 并不能省掉全部课程应用工作。
- **库能力不等于主应用配置。**OpenMAIC storage 包保留浏览器后端，但本次提交的主应用 `bootstrap.ts` 明确将文档、学习记录和资产接到服务端 HTTP，且没有浏览器持久化回退。不能按包 README 的描述把完整应用认作纯前端单机版。
- **运行依赖要分别计算。**OpenMAIC 根包要求 Node >=22.19，完整默认部署有 PostgreSQL；Open Notebook 有 SurrealDB、LangGraph 和内容处理组件；DeepTutor 可选模块也有依赖关系。单机并不等于只需一个可执行文件。
- **Lattice 不是必须去 Qt。**若其桌面体验合适，可以保留 Qt／QThread。需要处理的是它自身 Vault、索引接纳和自动 Git 操作与我们的正式知识库规则是否兼容；不应先花成本改写宿主形态。
- **不复制所有模块。**多角色课堂、音视频生成、图谱、插件市场、远程多用户等可选功能不应成为最小学习闭环的必经依赖。能力存在不等于要启用。
- **不扩散两套真值。**若采用产品数据库，就通过它的 API 读写并按需导出；避免同一份答案同时由产品、课件目录和现有 Runtime 独立维护。

证据：[OpenMAIC 包配置](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/package.json)、[renderer 导出](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/renderer/src/index.ts)、[主应用持久化](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/persistence/bootstrap.ts)、[Open Notebook 依赖](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/pyproject.toml)、[DeepTutor mastery 模块依赖](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/modules/manifests/mastery.json)、[Lattice Vault](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/vault.py)。

## 8. 下一步验证与选型门槛

本节保留未来运行验证的备选思路。用户已将当前任务调整为先完成源码研究与架构建议；以下完整旅程不作为本轮必做事项或验收门槛，只在出现影响选型且无法由源码解决的具体未知时再确定验证范围。

先对 DeepTutor 与 OpenMAIC 各验证同一条完整用户旅程，再确定采用完整产品还是抽取模块。此处列出验证方案，不代表本轮已安装或授权运行。

1. 外部 Agent 存入两份资料，其中一份与现有知识重复；用户未要求整理时，不自动生成课程。
2. 用户明确要求整理和学习后，利用资料创建一个小课程／学习主题；记录外部输入、上游内部又做了哪些模型调用。
3. 用户学习一个目标、完成一道确定性题和一道开放题，再追问一次；确认页面反馈和真实持久记录一致。
4. 刷新页面、重启进程后恢复；重复提交答案时不产生重复事实或丢掉原反馈。
5. 通过现有 API 或导出功能，外部 Agent 读取实际答案、反馈、目标状态、未决问题与对应来源，而不是从整段聊天猜测。
6. 准备知识候选，按当前知识库流程处理；不让学习产品直接初始化或改写正式 wiki。
7. 统一记录实际模型调用次数、输入／输出／缓存 token、延迟、失败重试、依赖组件和需要维护的补丁。分别统计外部 Agent、产品模型、摘要／embedding 等，不能只看单个聊天框的用量。

若完整产品只缺薄接口，优先使用或补充该接口；若必须大改其核心数据和 Agent 才能跑通，再评估 SDK／模块复用。若本地目录需求能由导出／导入完成，就不强制替换产品已有存储。任何候选尚未验证的能力都保持“待验证”，不因 Star 高而免审。

## 9. 本轮完成范围与续接

已完成六个公开仓库的本地固定版本下载、根许可证查看、关键接口与上下文路径的定点静态阅读，补充了可复用机制、真实限制及下一步验证方案。未实施新业务架构、未运行第三方代码、未改 AGENTS／正式 raw／wiki，也未重跑或关闭 S1 历史 P2。

续接先读本文与 [上游来源清单](upstream-sources.md)；按上文代码入口定点检索，不再重复整篇 README。正式总体方案尚未重写，待选型证据足够后围绕最终采用方式一次性修订。