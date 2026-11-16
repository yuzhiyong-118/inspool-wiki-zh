---
type: meta
title: I2 真实学习探针：执行交接与完成状态
status: historical_record
updated: 2026-11-10
topic: I2 真实学习探针交接
related_sources: []
related_synthesis: []
---

# I2 真实学习探针：执行交接与完成状态

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

更新：2026-11-10。工作区：`<知识库根目录>`。状态：**主 Agent 接手修复与真实续测已完成，I2 有限通过。** 此处 I2 是实施任务书中的真实学习探针，不是旧学习证据等级 L2，也不重启旧 S2/S3。

**完成更新**：用户授权新增用量（见本机账本）、24,000 暂停，并明确授权使用未轮换的当前 Key。主 Agent 经真实网页补做一次追问及同实例重启恢复，新增 3 次调用（用量见本机账本）；17 项离线回归通过，实际停止器已验证 Windows venv 进程树。见 最终报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-final.md） 与 续测证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-continuation.json）。本次所属 API/Web 已停止，未自动进入 I3–I6。

**以下为首轮历史执行约束**。首次 验收报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-review.md） 和 离线复审（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-review-rev2.md） 保留历史失败，不再表示当前缺少页边问答。有关凭据轮换作为继续条件的旧表述已被用户最新明确授权覆盖；状态记录为未轮换，不写成已修复。本交接及旧启动提示不能用于重跑或清零预算，续测也已结束。

## 1. 分工与授权

用户同意由其他 Agent 执行 I2，本对话主 Agent 复核原始证据和结论。执行者完成后提交“待验收”报告，不替验收者签发通过，也不自动进入 I3–I6 产品适配开发。本交接不自动创建或派发新对话。

执行者可以：读取固定源码和现有配置，使用已配置的套餐模型/本地 embedding，在隔离实例运行真实探针，编写验证脚本、自有测试资料与去敏报告，做必要的小范围配置/验证脚本修正。模型预算已确定，正常执行范围内无需再次询问预算或模型选择。

保留已有修改和数据；不提交/推送，不改正式 raw/wiki/AGENTS、旧 S0/S1 状态或现有业务代码，不更新参考仓库 HEAD，不为验证新建通用框架。不要清理整个 runtime、删除旧课程或重置用户配置；遇到已有探针先读取回执判断续做，不重复运行。

## 2. 最少阅读与当前事实

按顺序阅读：

1. 根 [AGENTS.md](../../AGENTS.md)。
2. [实施任务书](learning-book-implementation-tasks.md) §2、§5 及本交接。
3. 模型配置记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-setup/README.md）、套餐/预算（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-setup/quota-budget.md）。
4. [D2](research/upstream-learning/design-convergence/D2-data-and-handoff-contract.md) 的结果/版本语义、[D3](research/upstream-learning/design-convergence/D3-first-learning-scope.md) 的支持范围；按需定位源码，不重读 857 条证据或六仓全量研究。

| 项 | 已确认事实 |
| --- | --- |
| 固定来源 | DeepTutor `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`，应用 1.7.2 |
| 已完成 | I0/I1：八个 Python wheel + 同提交源码 Web、安装检查、无模型空书库及重启读取；未完成真实学习 |
| 执行目录 | `<本机验证目录>`，已 gitignore；绝对路径均相对此工作区解析 |
| Python / Node | `venv/Scripts/python.exe`（3.12.14）；`node/node-v22.23.4-win-x64/node.exe`（22.23.4）；不要用系统默认 Python 3.15 |
| 源码 Web | `source/web/`，npm 依赖已安装；原参考 clone 在 `上游仓库 DeepTutor 的 `DeepTutor/``，保持固定 |
| 正确 runtime home | **<本机 I2 实例目录>**。旧 `runtime` 是 I1 历史实例，不复制旧配置覆盖新实例 |
| 文本模型 | MiniMax 中国站 `minimax-m3`，`https://api.minimaxi.com/v1`；私有 catalog 已保存套餐 Key，已有真实请求成功记录 |
| Embedding | Ollama `bge-m3`，`<本机服务地址>`，实测 1024 维；模型在 `<本机模型目录>`，无需重新下载 |
| 服务 | 上次检查 DT API 未运行，Ollama 已运行；接手时以实际端口/PID 为准，不盲目另开实例 |
| 默认访问 | API loopback 8127，Web loopback 3827；单后端 worker、memory coordination，无 Redis/PocketBase |

私有文件可能在默认沙箱中读写被拒；先准确定位权限边界，用宿主支持的授权方式访问，不因此新建另一个 runtime、改 ACL 或复制密钥到公开位置。只输出模型/端点/是否存在凭据等白名单信息，不原样打印 catalog、setup、环境变量或请求头。

## 3. 预算及启动前检查

- 本轮 I2 文本模型调用累计输入＋输出 **1,000,000 原始 tokens**，包含所有子调用/重试；**800,000 时停止新增调用并暂停/取消可控在途任务**。缓存/推理 token 不重复相加，使用供应商 usage 语义。
- 先保存 <本机 I2 实例目录> 下 `data/user/usage.sqlite3` 已有 call_id/时间位点；已有 doctor 请求不算本探针新消耗。按新增 call_id 去重统计，单独列 reported、estimated、missing。只读采集 usage，不改账本，不拿空 source 字段假装精确归因。
- 确认本 runtime 没有其他生成任务并行写；记录阶段边界和账本覆盖。发现后台子调用长期不入账、用量持续不可观察，或控制不了新调用时，先暂停定位，不能靠猜测继续烧额度。
- 套餐窗口百分比是账户观测，不是原始 token 计数；其他活动、重置、已购积分会影响它。不得切换普通按量 Key、购买积分或声称实现了供应商硬封顶。100 万是初始运行预算，不保证在途请求精确停止于最后一个 token。
- 核对已知书生成 pause、chat cancel 的实际入口，再启动。一次只生成一本小书，先确认小纲目；可使用上游 `auto_compile=false` 逐页推进降低失控范围，不另造任务队列。
- 不重复安装和 doctor --online；配置异常才定点检查。首次调用前核对实际 active 模型与 embedding，关闭本探针无关的媒体、搜索/额外写工具；需要改私有配置时先备份，记录改动与恢复状态。

## 4. 最小执行路径

1. **建立本轮身份和回执**：使用唯一 runId；原始日志/请求体/脚本放验证根下 `i2-probe-<runId>/`。保留源 commit、配置摘要、runtime/进程身份和启动前用量位点。探针材料是执行者撰写的自有短 MD，测试内容不写入正式 raw/wiki。
2. **制作和导入来源**：500–1500 字左右，主题可为幂等/重试；包含少量明确、可核对的约定和一个来源特有细节，供后续验证确实读到了本资料。保存原字节及 hash。通过上游 knowledge API 导入一个专用资料集 KB，等文件可读/索引完成；不要把整个 wiki 作为输入。
3. **真实生成小书**：走上游 Book proposal → spine 确认 → page 编译；一个内容章节及必要概览即可。先保存返回的 KB/file/task/book/page/block/question 身份和响应；关键调用超时先查已有状态，不按标题猜测幂等，不无限重建。
4. **检查生成内容**：至少一段课文和一道实际单答案 choice 能与输入核对；保存题干/选项/答案键/解释及来源定位精度。内容 READY 不证明检索成功，须对照原文。若需 regenerate，限定为学习前、当前块的小修复，记录原因/次数/用量；不要手写生成课文或题目再宣称模型通过。
5. **保存学习前内容证据**：采集实际 book/spine/pages 与必要资源、原始响应、时间和摘要。此处只需探针证据，不实现 I4 产品适配器。提交时 hash 缺失依然是协作级内容绑定，不升级为严格历史证明。
6. **实际网页学习**：打开已生成书，在网页选择题中提交一个明确测试答案，并在该页 BookChatPanel 发起一次针对资料内容的追问。至少一个问题应依赖输入中的特有细节，核对回复而非仅看请求成功。记录 UI、会话关联和实际 API 读回。原始模型回复/不完整答复也要保留，不能用外部 Agent 补答来冒充内部教学。
7. **读回和重启**：在同一实例通过 API 读取实际答案、Progress 和关联公开 chat；等待当前回合结束，停止本次所属 API/Web 后，用同一 <本机 I2 实例目录> 重新启动；再次通过 API 和网页确认已保存的选择、当前页/会话。不要从脚本重放提交、重新生成回答来制造“恢复”。
8. **提交待验收结果**：提供自有测试输入、生成内容、答案/对话前后读回、用量与限制的证据；停止本次新开的 API/Web，保留数据。不要停用户原已运行的 Ollama或其他实例。

测试答题者是执行 Agent，应标 `actor=external_agent_test`，不是用户学习事实或独立掌握证据。可以通过 HTTP 自动化准备/采集；若某步仅用 quiz API/WS 验证，明确标出，**直接 API 成功不能代替网页交互通过**。

执行可以按实际上游处理方式调整顺序；以上约束旨在保留可复核的关键事实，不要求增加六套部署、完整课程生产或额外业务功能。

## 5. 源码入口与已知陷阱

优先读取固定源码对应文件，按实际请求 schema 操作；不要猜 endpoint/payload：

- 配置/启动：`docs-for-dev/AGENT_SETUP.md`、`deeptutor_cli/main.py`、`services/config/runtime_settings.py`。
- 导入/索引：`deeptutor/api/routers/knowledge.py`，`services/rag/pipelines/llamaindex/`；文件引用需真实 KB 相对路径，不能用项目绝对路径代替 source_id。
- Book：`deeptutor/api/routers/book.py`、`book/engine.py`、`book/compiler.py`。BookEngine 与聊天 turn 分别调度；断开 HTTP 不代表后台取消。
- 答题/恢复：`web/app/(workspace)/learning/books/components/blocks/QuizBlock.tsx`、`BooksRoute.tsx`、`book/progress.py`。`is_correct` 是客户端值；书面题 self:correct 是自评。Progress 可能已保存而 assessment 同步返回 500，先读回、同 submission_id 恢复。
- 页边 chat/读取：`BookChatPanel.tsx`、`book/chat_sessions.py`、`api/routers/sessions.py`；Page Chat 应引用当前 book/page，不以直接请求供应商代替应用教学链。
- 用量：`services/llm/usage_ledger.py`、`metrics.py`。每调用计数与 session/message 事件序号分开；同一调用不能重复统计。

后台 Windows 进程用隐藏窗口并保存 PID/创建时间、可执行路径及 runtime。旧 `stop_services.py` 读取 `api.pid/web.pid`，不一定覆盖这次 `api-i2.pid` 或新进程；**停止前必须确认是本次所属进程树**，不能照旧 PID 停掉其他任务。重启关闭/备份须覆盖 SQLite/WAL，不只复制书文件。

若原组合失败，先最小定位。简单环境/验证脚本修正可直接做；确需上游补丁时仅改隔离副本，保留原失败、独立 diff、原因和复验，结论注明“原版失败/补丁后状态”。不能靠安装 full、换模型、换后端或修改评分口径静默通过；影响架构的缺口交回本对话主 Agent。

## 6. 交付物：足够验收即可

去敏可审阅产物保存到 `docs/design/evidence/learning-book-i2-probe/`：

| 文件 | 内容 |
| --- | --- |
| `README.md` | 实际环境/步骤、逐项结果、缺陷与限制、修改/修复、服务最终状态；结论标“待验收”，不可把未执行项写通过 |
| `input.md` | 自有测试来源原文；记录 hash 和测试约定 |
| `evidence.json` | runId、源码/模块/配置版本、KB/book/page/block/question/session/submission 身份、前后采集时间/摘要、原始证据路径/文件 hash、覆盖状态；不含密钥/账户身份 |
| `usage.json` | 启动基线/结束位点、新调用去重用量、实际/估算/缺失、重试、是否到阈值；本地 embedding 单列 |

原始大响应、DB/日志/脚本可保留在被忽略的本轮目录，通过 evidence.json 定位供验收者只读查看。HTTP 证据只保留必要请求体/响应体，剔除 Authorization/Cookie 等头及错误中的凭据；不要把整个私有 runtime 复制进文档。网页截图可去敏后附本轮报告，不用重建展示系统或 fixtures 平台。

若中断/超预算/失败，也按相同结构交付已经取得的证据和准确恢复点；不能为了“有通过结果”再开第二轮预算。预算不随换 Agent/重启清零，续做先读本轮 usage 和回执。

## 7. 本对话主 Agent 的验收方式

验收以原始内容/记录为依据，首先只读复核，必要时用现有 API 定点读回，不默认再花一轮模型预算：

1. 固定版本、实际模块与 runtime/配置正确，改动和额外依赖已披露。
2. 自有来源真实导入/索引，生成内容及至少一题能够核对；没有用合成课文替换真实链。
3. 网页选择与页边追问实际发生，测试 actor 标注正确；不是只拿供应商连通性或直接写 DB 作为证明。
4. 重启前后同一答案和会话可定位，恢复没有重新提交/生成；访问位置与掌握度不混用。
5. 用量、部分保存/失败/缺来源和协作级版本边界如实呈现；100 万预算不被误写成套餐精确额度或硬封顶。
6. 正式库未改，旧阶段未动；隔离数据和失败现场保留，服务状态清楚。

结论可为通过、有限通过或需修复，必须写明适用范围。执行者完成后只将报告入口交回原对话；I2 验收通过后再决定 I3–I6，不自动开发。

## 8. 可直接发给执行 Agent 的提示词

以下为**首轮历史启动提示**。当前已完成首轮并被判需修复，禁止直接复用它重跑；后续以本文件顶部的验收状态和验收报告关闭条件为准。

> 请读取 `<知识库根目录>/docs/design/learning-book-i2-handoff.md`，执行其中的 I2 真实学习探针。复用已安装环境和 <本机 I2 实例目录> 的 MiniMax minimax-m3、本地 Ollama bge-m3；本轮累计输入＋输出 100 万原始 tokens，80 万暂停新增调用，所有子调用与重试计入，续做不清零。用一份自有短 MD，经真实上游导入/生成，完成网页单选、页边追问、保存/重启/API 读回，并留下可供独立验收的原始证据。正常范围无需再问预算和模型；保留现有配置/修改，不能把直接写文件或 mock 当真实通过。只做 I2，不开发 I3–I6、不改正式 raw/wiki/AGENTS/旧阶段、不更新参考源码、不提交推送。完成或遇到停止条件时，把 `docs/design/evidence/learning-book-i2-probe/README.md` 的待验收报告交回原对话，由主 Agent 验收。