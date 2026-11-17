---
type: meta
title: 上游源码级机制结论提取
status: research_analysis
updated: 2026-11-17
topic: 上游项目源码核实得到的机制级结论与复用边界
related_sources: []
related_synthesis: []
---

# 上游源码级机制结论提取

本文提取自上游源码静态核实记录中**只存在于研究笔记、未随仓库发布**的机制级结论。与[关键发现报告](report.md)的关系：那份报告给的是选型结论与处理链发现；本文给的是**支撑这些结论的源码事实与复用边界**，以及研究过程中对首轮结论的更正。

> 研究是**只读静态审查**：未安装、未执行、未调用模型。全部结论为源码口径，涉及运行行为、延迟与真实模型表现的部分只能给源码推断。结论对应各上游的固定提交（见[上游来源清单](../../upstream-sources.md)），不代表当前上游版本。

**证据编号说明**：本文每条结论都标注原始记录的证据编号（如 `LA-023`、`KT-MAIN-014`、`DT-CTX-006`、`ON-037`、`OM-029`）与源码位置。编号分两类前缀——`LA-*`／`KT-*`／`DT-*`／`ON-*`／`OM-*` 是子执行者核实记录，`*-MAIN-*` 是主执行者独立复核记录；末尾带 `MAIN` 的编号来自主执行者复核对首轮结论的修正。编号在原始记录中可逐条回查，但原始记录本身未随本仓库发布。

**确定性分三级**（沿用原始记录的口径）：`source_confirmed` 表示静态阅读可确认；`inference` 表示按语言或框架语义推断、**未运行验证**；`declared` 表示上游文档声明而非代码事实。**本文不把推断写成事实。**

## 一、六个项目的形态事实

| 项目 | 形态事实 | 复用边界的硬约束 |
| --- | --- | --- |
| **Lattice** | Qt 桌面应用：PySide6 的网页视图承载 UI，Python 侧通过 WebChannel 暴露唯一 RPC 通道。模型循环是自己实现的 OpenAI 兼容工具调用循环，不是某个 agent SDK | **没有任何对外接口**——无 MCP、无 HTTP API、无对外 CLI（全仓 `lattice/` 下 .py 零命中 `mcp|FastAPI|flask|aiohttp|http.server`，LA-MAIN-006）。Vault 副作用极重：启动即对整个工作树 `git add -A` 并提交，此后每 10 秒自动提交、每 2 秒全树扫描，并改写 `.gitignore`（LA-MAIN-002～005、LA-MAIN-012～014） |
| **Kotaemon** | 文档问答应用（Gradio + LlamaIndex + LangChain）。**代码中完全没有课程、大纲、学习对象概念**（全仓 `curriculum|course|learning objective|lesson` 零命中，KT-50），是检索参考而非课程底座 | 硬依赖极重；引用/问答层硬依赖 `ktem` 包（KT-45～KT-47）；默认重排模型需额外 API key，缺失时静默不生效（KT-MAIN-011/012） |
| **DeepTutor** | Python 调度器是默认路径（`DEEPTUTOR_CHAT_ENGINE` 默认 `"python"`）；TypeScript 是可选的**实验性调度器**，不是并行实现 | TS 只替换调度器，模型调用与工具执行仍在 Python 侧；只有一条特殊模式才把模型调用本身搬进 Node（DT-LOOP-004/005/006）。**「有两个引擎」的说法容易误导** |
| **OpenMAIC** | 课件生成 + 课堂播放 + 现场导演三段式；课程可检查、编辑、复用、导出 | 课堂形态强、状态与资源多；对外接口不收 URL——服务端故意不抓调用方 URL，须外部 Agent 自己下载并上传字节（OM-010）；`@openmaic/renderer` 是幻灯片画布包，不是课堂渲染器 |
| **Open Notebook** | 「资料库 + 双入口问答」：Chat 是单次模型调用，Ask 是多阶段流水线；`search` 是独立直连工具，完整绕开 Ask | **不是一个课程或教学系统**——全仓没有课程、测验、掌握度、间隔重复等学习领域概念（ON-036）。检索在 API 层是文本与向量的严格二选一，不做混合 |
| **open-notebook-mcp** | stdio 优先的 MCP server（可选 HTTP 传输），本质是纯 HTTP 客户端 | 与后端存在多处 API 形状分歧，部分工具**在当前后端上根本不工作**（ONMCPL-004/005 等）；没有课程链 |

## 二、机制级结论：值得直接借用的做法

这些是研究中最有复用价值的部分——它们是**机制**，不是功能清单。

### 2.1 上下文预算的正确做法

- **技能清单延迟暴露**：Lattice 的技能格式兼容 Anthropic Agent Skills，且「技能目录只给名字 + 一行说明，需要时才读全文」——这是上下文预算的正确做法，值得直接采纳（`lattice/skills.py`，LA-067）。
- **滑动窗口按半窗步进对齐**：Lattice 的 `_history()` 取最后 N 条时，起点按 `step = max(1, limit//2)` 步进，使连续两轮的请求前缀完全一致，从而命中服务端 prompt cache。**缓存友好**的设计而非巧合（`lattice/bridge/turns.py` `_history()` L335-L348，LA-023）。注意其限制：**按条数不按 token 预算**。
- **逐块重排是主要成本来源**：Kotaemon 默认配置下每次提问约 12 次模型调用——1 次答案生成 + 1 次引用抽取 + **N 次逐文档相关性打分**（N 等于 top-k，实际默认 10）。`LLMTrulensScoring.run()` 对每个被评分的文档并发调一次 LLM（`libs/kotaemon/kotaemon/indices/rankings/llm_trulens.py` L113-L150，KT-MAIN-016）。查询扩展默认不走。**引入逐块重排前必须先算这笔账**，否则成本结构会被静默放大。限制：调用次数与 token 未实测。
- **上下文「预算」在不同路径上未必真截断**：Open Notebook 只有 source-chat 一条路径真正截断，`POST /api/chat/context` 只做选择与计数、不截断（ON-037、ON-038、ON-039）。**不能把一个端点的截断行为外推到全部路径**。

### 2.2 工具加载的权限与累积

- **延迟加载后仍会再校验权限，而且校验两次**：DeepTutor 的 `load()` 内做一次 `_is_allowed`，dispatch 时 `ScopedToolRegistry.execute` 再拒绝未授权 provider 工具（`deeptutor/runtime/registry/deferred_tools.py` L176-202，DT-TOOL-006/007）。只在加载时校验是不够的——加载与执行之间的状态可能已变。
- **已加载的工具 schema 会累积且持久化**：DeepTutor 的 `_persist` 把已加载工具记到 session 级 JSON 文件，后续轮次起即带上全部已加载 schema（DT-TOOL-008/009）。**这是设计使然而非缺陷**，但意味着长会话的输入成本单调增长，需要纳入预算。限制：持久化异常时只 warning 不阻断。
- **能力目录是声明式目录，不是插件加载器**：DeepTutor 的 `manifests/*.json` 是声明式目录（25 个），`manifests()` 首次调用时读取并做 8 类校验（含依赖无环），不是运行时插件加载器（`deeptutor/modules/catalog.py` L24-76，DT-MOD-001）。这个「声明 + 启动期校验」的组合比运行时动态装载更容易保持依赖可推算。

### 2.3 引用与证据回锚

- **字符级回锚是真正可用的 provenance**：Kotaemon 用 LLM 函数调用抽取逐字引文，再用 difflib 模糊回锚到字符区间，最终在 PDF 上高亮（KT-25～KT-27；引用抽取用 function calling 强制逐字引文且 ≤15 词，`libs/kotaemon/kotaemon/indices/qa/citation.py` L10-L19/L31-L42，KT-MAIN-017）。**这是可以单独抄走的一层**——不需要整套检索栈，只需要「抽取 + 回锚 + 高亮」三步。
- **证据装配的元数据要少而可读**：Kotaemon 的证据上下文上界 32000 token，证据串只带 `file_name` 与 `(Page N)`，不带内部标识（`libs/kotaemon/kotaemon/indices/qa/format_context.py` L25/L52-L54，KT-MAIN-019），既可读又不泄漏内部状态。
- **命中来源标记不等于内容遵守来源约束**：正文可能把来源的封闭白名单扩展成自己的判断。**来源锚点存在只证明来源进了上下文**，不证明整段主张都有来源支持。

### 2.4 学习状态与记录

- **两套记录要分清**：Lattice 的会话记录（`threads/`）与学习状态（`journal/` + `cards/` + `topics/` + `insights/` + `me.md`）是两套，各有自己的目录、格式与生命周期（LA-050～LA-055）。把学习状态当聊天记录读，会漏掉掌握度、复习计划与薄弱点。
- **学习状态需要真事务**：DeepTutor 用 SQLite（`mastery.sqlite3`，工作区作用域）、真事务（`BEGIN IMMEDIATE`）、revision CAS 与多重幂等键（DT-LEARN-021…033）。学习记录被重复写入或并发写入是真实风险，不是理论风险。
- **掌握度有两类判定**：DeepTutor 中一类来自模型推断、一类来自可观察表现。**两者语义不同，不能写进同一个权威字段**，也不能把阈值当作普适标准——阈值本身是产品决策。
- **学习记录用序号做乐观并发**：OpenMAIC 的记录带 `seq` 与 `expectedLastSeq`，`seq` 在同一事务内由 `SELECT COALESCE(MAX(seq), -1) ... +1` 得到，会话行锁串行化同会话的 appender（`packages/@openmaic/storage/src/runtime/types.ts` L50-L118 与 `pg.ts` L485-L592，OM-028/OM-029），读改写时校验能发现并发覆盖。

## 三、复用边界的硬约束

这些结论决定「能不能直接用」，比功能清单重要。

### 3.1 版本与仓库形态带来的论证限制

- **一次性快照的仓库不能做基于历史的论证**：Lattice 的仓库历史深度为 1（`git rev-list --count HEAD` = 1），全仓是单次快照带入的。**因此不能论证「某功能后来被删掉了」**。引用该上游的结论时，只能说当前固定提交是什么样。
- **文档残迹不能当作当前能力**：Lattice 快照内的 `docs/TEST_REPORT.md` L10/L37 描述了一个含「Codex · ACP 主讲」的版本并提到 `tests/learning_codex_smoke.py`，但**该测试脚本与全部 ACP 源码在当前快照中不存在**（LA-MAIN-016）。正确表述是「文档残迹显示上游曾有或另有该形态，**但本快照不可验证**」。
- **文档与实际不一致会骗过依赖检查**：Lattice 的 `lattice/i18n.py` L14 顶层 `from PySide6.QtCore import QLocale`，而 `lattice/vault.py` 等核心模块 `from .i18n import tr`——核心域**直接 import 无、传递依赖有**（LA-MAIN-015）。所以「核心零 GUI 依赖」的说法会被检查骗过。
- **结论要区分「域名层可行」与「整体可行」**：Lattice 上前者可行而后者不现实。可行的切分线落在**领域逻辑与传输实现之间**（`index.py` + `providers.py` 的 HTTP 客户端部分 + `agents.py` + `tools.py` 的 schema 部分），不在产品边界上。

### 3.2 依赖与部署成本

- **作为库直接复用会把整个栈拖进来**：Kotaemon 的 `kotaemon` 包虽可独立安装，但硬依赖 gradio / fastapi / llama-index / chromadb / langchain / umap-learn 等（KT-45～KT-47）。避免主框架只能靠「不装依赖再手工装子集」，这种做法很脏且易碎。
- **真正的应用级管线在另一个包里**：Kotaemon 的应用级检索管线 `DocumentRetrievalPipeline` 位于 `libs/ktem/ktem/index/file/pipelines.py`，带 reranker 装配、MMR、表格补全与 file scope 过滤——**不可从 `kotaemon` 单独拿到**；引用/问答层硬依赖 `ktem`，缺它会直接抛 ImportError（KT-45）。
- **存储位置常与直觉不符**：Kotaemon 的数据**不在 `~/.kotaemon`**，而在 `<flowsettings.py 所在目录>/ktem_app_data/`（KT-05～KT-08）。曾有「Kotaemon 把数据存在 `~/.kotaemon`」的说法，原始记录直接判为**错误**。
- **最小启动面可以很小**：DeepTutor 的 `deeptutor start` 或 `deeptutor serve` 即可本地起；会话存储默认 SQLite（零配置），Redis 仅在 integrations 显式配置时需要，向量库仅在 knowledge 模块启用时需要。**但前端构建需 Node 20+**（DT-ENTRY-001…007）。
- **重依赖需分清主依赖与可选依赖**：Open Notebook 的主依赖是 LangGraph + LangChain + SurrealDB + content-core；docling / crawl4ai 走 extras，主依赖里并没有出现文档处理与爬取库（ON-038、ON-002）。**「重」这个判断必须区分必选与可选**，否则会高估成本。

### 3.3 接口与适配器的版本偏斜

open-notebook-mcp 适配器落后于后端至少一轮 API 演进，具体表现为（均为 `src/open_notebook_mcp/server.py`）：

- **字段名差异的历史误判已纠正**：适配器发送 `notebook_id`（单数），后端推荐 `notebooks`（复数），但 `SourceCreate.validate_notebook_fields` 显式实现了兼容转换。首轮据此判断关联失效（ONMCPL-004/005），后续复核已撤回该判断（ONMCP-015）；字段名差异本身不构成接口阻断。
- **必填性反转**：`execute_chat` 的 `context` 在适配器里可选、在后端是必填；`get_chat_context` 的 `context_config` 同样反转（ONMCPL-009/010）；
- **请求体格式与端点声明不符**：`create_source` 发 JSON 体到表单端点（ONMCPL-004）；
- **响应类型假设错误**：`ask_question` 打到 `POST /api/search/ask`，该端点返回 SSE 流，而适配器的 `make_request` 无条件 `r.json()`（ONMCPL-007/008）。

结论口径：**适配器不能被当作「与本体版本一致的完整接口」**。评估外部 Agent 接入方案时，必须逐参数核对契约与后端请求模型，并把「契约与实现不一致」当作**已知阻断**而非待验证项。另有版本 skew 事实：适配器提交 `notebook_id`，后端已标 deprecated 并主推 `notebooks[]`（ONMCP-006/007）。

### 3.4 检索融合与去重的实现细节

- **「混合检索」可能只是朴素拼接**：Kotaemon 的 hybrid 实现是**朴素拼接**——FTS 结果全部在前且 `score=-1.0` 硬编码，向量结果全部在后按原 score，**无归一化、无 RRF、无加权**（`libs/kotaemon/kotaemon/indices/vectorindex.py` L226-L236，KT-MAIN-013）。按「混合检索」这个名字估性能会高估。
- **去重条件疑似恒真（静态推断，未运行验证）**：Kotaemon 的 `vs_ids: list[str]` 是 id 列表，而过滤条件写作 `for doc in ds_docs if doc not in vs_ids`——把 `Document` 对象与 `str` 列表比较。按 pydantic BaseModel 语义该条件**应为恒真**（去重失效），后果是同一块内容在结果里出现两次。**但这是 `inference` 不是 `confirmed`：llama_index 未安装，无法运行时确认 `Document.__eq__` 的实际行为**（`libs/kotaemon/kotaemon/indices/vectorindex.py` L190/L199/L228-L231，KT-MAIN-014）。因此只能说「静态阅读强烈指向恒真」，**不能说「已复现」**。这一项在[关键发现报告](report.md)第 9 节仍列为**未解决项**，本文不改变它的状态。
- **分词器影响中文效果**：Kotaemon 的 FTS 用 LanceDB Tantivy 的 `en_stem` 分词器（`libs/kotaemon/kotaemon/storages/docstores/lancedb.py`，KT-09），中文场景必须更换。

### 3.5 上下文压缩的两条路径不可混谈

OpenMAIC 存在两条上下文路径：课堂聊天路径默认启用压缩，课程构建 Agent 路径由 `OPENMAIC_AGENT_COMPACTION_ENABLED` 控制且默认关闭。**必须分开陈述**，否则会把一条路径的行为说成全系统的行为。压缩保留什么、失败时会怎样，两条路径也不相同。

另有一处更正值得保留：研究首轮曾以 DeepTutor 的某个非默认路径（TypeScript 实验路径）的证据描述全项目的默认行为。复核后结论是——默认的 Python 路径**同样有**滚动摘要机制，只是实现位置不同（`deeptutor/services/session/context_builder.py`）。正确表述是「两套实现各有自己的机制，**不能互相引用对方的保证**」。

### 3.6 会话与记录的生命周期

- **追加式记录与可回填目录并存**：Lattice 的会话记录 `threads/<年-月>/<id>.jsonl` 追加写入，长对话靠 organizer 写摘要检查点（LA-056/057/058）。追加式不等于完整——历史可能只覆盖摘要之前的部分。
- **没有对外接口的项目无法直接接入现有工作流**：Lattice 本身提供不了「外部成熟 Agent 负责搜集核验整理」的接入口，只能自己包一层（LA-MAIN-006）。
- **领域模型不兼容会贯穿全链路**：Lattice 的文档种类是 topic/card/lesson/note/insight，frontmatter 约定是 `id/kind/title/by/created/updated/links`；我们的约定是 `type/status/topic/updated` + `supports/contradicts`——需要改的不只是文件格式，还有关系字段与索引。
- **追加式存储的冲突要在写入侧处理**：OpenMAIC 的 `appendRecord` 在事务内分配 `seq` 并用行锁串行化同会话写入（OM-029），这类保证不是默认具备的。

## 四、研究过程中的更正与保留的失败

保留这一节是因为它记录了**哪些看起来可靠的说法实际上有洞**。

- **首轮结论被自己推翻**：DeepTutor「没有历史压缩」的判断被复核推翻，默认的 Python 路径确实有滚动摘要机制。**首轮用非默认路径的证据描述默认行为，是这类研究最常见也最容易漏的错误。**
- **计数口径差异被区分**：子执行者记录约 714 个 HTTP 路由处理函数，主执行者复核为 715，差 1 属计数口径差异，不影响结论。引用时应写「约 700+ HTTP 端点 + 9 个 WS」而不是给出精确数字。
- **一处推断被明确降级**：Kotaemon 的判重条件被标为 `inference` 而非 `confirmed`——llama_index 未安装，无法运行时确认 `Document.__eq__`，因此只保留「按 pydantic 语义应为恒真」的静态推断，**不写成「已复现」**。这条同时说明：**能用静态阅读判定的方向，不应被表述成运行验证过的结论。**
- **一处证据被判定为不可用**：open-notebook-mcp 复核中，SubAgent 称适配器只发 `notebook_id`（单数）而「后端只读 `notebooks`（复数）→ source 根本不会挂到任何 notebook」。主执行者核对 `SourceCreate.validate_notebook_fields`（ONMCP-015）发现**该字段名转换是显式实现的，这条不成立**——字段名不是问题。同类降级还有一处：先前称 `search_capabilities` 能「减少发送给模型的工具 schema」也被判为**不成立**，仓库内无任何传输层过滤钩子，33 个工具始终全部注册并随 `tools/list` 发出（ONMCPL-011～014）。
- **明确未覆盖的范围**：Open Notebook 的内容抽取在外部包 `content-core` 里，其内部实现不在核实范围（ON-006～009）；运行行为、延迟数据与真实模型表现全部未覆盖。**读取测试文件只表示「覆盖意图」，不表示「已通过」**（如 DeepTutor 的 30 个学习状态测试模块标为「已读未执行」，DT-LEARN-021）。

## 五、与已发布文档的分工

| 文档 | 回答什么 |
| --- | --- |
| [关键发现报告](report.md) | 五条处理链的发现、机制对照、token 成本、选型结论与未解决项 |
| [从上游 README 与设计原则重新理解架构取舍](upstream-design-rationale.md) | 为什么划出这些边界；八项对我们有用的取舍 |
| [上游学习应用研究：方法、产物与未公开范围](README.md) | 研究方法、证据定位三种形态、三层校验、研究纪律 |
| 本文 | 支撑上述结论的**源码事实**、复用边界的硬约束、接口偏斜与更正记录 |

原始证据定位：上游源码研究笔记与主执行者独立核实记录（未随本仓库发布）；源码摘录与检索索引不随本仓库发布，引用上游源码时按[上游来源清单](../../upstream-sources.md)的固定提交与文件路径核对。
