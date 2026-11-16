# I5 详细任务书：只读学习记录与外部交接

> 公开设计摘编：保留通用契约与方案；历史验收、用户反馈、运行记录及本地素材不随仓库发布。设计条目不代表部署或验收完成。
更新：2026-11-11。状态：**I5-A～E 已实现并通过本地／HTTP 契约验收**，见 完整验收与 C01–C20（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）、[使用说明](../../tools/learning_book/HANDOFF.md)。项目 174 项测试通过；上游 learning-state 25 项源码／wheel 复测、content 19 项及实际 session/SQLite 9 项通过。真实安装／生产学习集成留 I6，累计补丁未安装到既有服务，项目真实模型／embedding 调用为 0。原任务书编写日期 2026-11-10，设计核对（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5-design/README.md）、A 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/README.md）、B 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/i5-b/README.md）与 I4（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）保留历史依据。

边界沿用 [总任务书](learning-book-implementation-tasks.md)、[D2](research/upstream-learning/design-convergence/D2-data-and-handoff-contract.md)、[D3](research/upstream-learning/design-convergence/D3-first-learning-scope.md)。I3/I4 是本地／HTTP 契约通过，真实部署和完整生产闭环仍留 I6；不能将此任务书当作已实现的 exporter。

## 1. 目标和不扩大的职责

让外部 Agent 拿到**真实可见的作答／阅读位置／公开教学会话、固定内容证据、来源映射与明确的未知项**，用于学习回顾与知识候选整理。上游仍是唯一可写学习状态；项目只保存不可变证据与保守派生结果。

| I5 交付 | 继续后置 |
| --- | --- |
| 无生成副作用的进度／页边映射读取，区分缺失、损坏与有效空记录 | 回放答案、补写 progress、修复上游题目或同步 question bank |
| 所选公开会话和规范 turn events 的有限分页读取 | 搜索全账户／跨 workspace 聊天、恢复已删历史、导出私有模型 replay |
| 原始记录、作用域 key、来源／内容绑定、选择题条件性复核 | 模型书面批改、受控测验、独立掌握证明、自动知识归档 |
| 可搬运 `learning-handoff/1` 包和 JSON CLI／应用方法 | 新门户、MCP Server、第二个可写学习库或通用后端框架 |

用户可以在尚未结束、没有基线、存在失败记录时导出事实；这些情况不靠伪造“完成／全部正确”放行，也不应一律阻止其取回仍存在的数据。

## 2. 开工前读取门禁：I5-A

### 2.1 已核对的缺口

1. 旧 `GET /api/books/{id}` 仍会 `maybe_resume_on_open`；I4 新 content 接口有意不含 progress 和聊天映射。不能为拿进度回退旧 GET，也不能用 POST visit/bookmark/quiz-attempt 当读取。
2. 两种 learning store 的 `load_progress` 都将缺失／读错／JSON 或模型验证失败折叠为 None；`ResolvedBook.load_progress` 随后生成空 Progress。模型还会补当前 timestamp／默认空字段，不能将它当已保存事实。`save_progress` 不负责统一刷新 `updated_at`，只比更新时间也会漏变更。
3. own 的页边会话映射在 canonical manifest metadata；shared 则在**当前读者** overlay。overlay 旧 loader 也会吞错误、过滤／转成字符串。不能读取作者的 progress 或用规范化后的空映射证明“从未聊天”。
4. 会话详情 GET 是当前公开视图：有 messages、active_turns、失败回合附注；规范 events 可能仅为预览，特定超长字段还会被裁剪。它不等于事件全文／全局原子快照。
5. 规范事件 GET 有 after_seq／limit／total／last_seq／next_seq／complete；没有关联规范 turn 的旧消息会返回空 events、total=0、complete=true。该返回不能覆盖详情中的旧 events 预览或证明旧历史完整。

### 2.2 选定最小补丁

在固定源码＋I4 补丁的**新隔离构建树**中，增加：

`GET /api/books/{book_id}/learning-state`

沿用 `_resolve_book_or_404`、请求 user/workspace 与 `resolved.learning`，不更改权限模型，不调用 resume/compile/生成、迁移／会话 adoption、save／score 重算。只输出当前读者的学习状态和诊断，不重复传全书内容。

核心契约如下；I5-A 实施版额外返回逐项 `valueAcquired/coverage/diagnostics`、文件摘要／字节数及 `consistency=per_item_observation`，实际字节和构建身份见 验收（未随公开仓库附带）。下例只解释字段，不是实际用户记录：
核心契约如下；I5-A 实施版额外返回逐项 `valueAcquired/coverage/diagnostics`、文件摘要／字节数及 `consistency=per_item_observation`，实际字节和构建身份见 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/README.md）。下例只解释字段，不是实际用户记录：

```json
{
  "schema": "book-learning-state-read/1",
  "bookId": "实际上游书ID",
  "readerScope": {"workspaceId": "实际请求workspace", "actorId": "实际请求主体", "identityKind": "authenticated或local_single_user"},
  "contentAccess": {"source": "own或shared", "permission": "现有权限"},
  "progress": {"status": "valid", "value": {"实际已存JSON字段": "不补默认值"}},
  "pageChatSessions": {"status": "valid", "value": {"实际pageId": "实际sessionId"}},
  "diagnostics": []
}
```

- 单个存储项状态固定为 `valid/missing/invalid/unreadable/changed`；有效空 attempts／空映射为 valid，缺文件为 missing，JSON／字段／book_id 错误为 invalid，权限／I/O 失败为 unreadable，检测到读取替换为 changed。不能将任一错误改成 valid 空对象。
- 严格读取只在上游内部使用本来就拥有的路径；项目适配器仍只走 HTTP，不直接读 DT runtime／SQLite。新增小型严格读取 helper，保留旧 loader 行为；own/shared 必须走各自实际存储路径。
- 拒绝解析后越出所选存储根的路径／符号链接，不以“当前进程有权限”代替读者作用域校验。
- valid 的原始 JSON 原样返回、保留未知字段，另列结构诊断；不通过 `Progress.model_dump` 重新构造历史记录，不补 missing timestamp、question_id、submission_id、is_correct 或分数。可利用现有模型做验证，但不能把其补出的字段当原数据返回。
- strict JSON 拒绝重复键、NaN；身份、类型、字符串映射及数组成员逐项诊断，不能静默丢掉坏 attempt。legacy 字段缺失可以保留并标该项 partial，不能新造身份／时间；同一文件中的其他有效项仍可保留。
- 对文件读取保存摘要／安全诊断，检测可见的前后替换／删除；不声称跨 manifest、overlay、SQLite 的事务。坏 JSON 不必作为任意文本公开返回，但必须明确 raw value 未取得，不能声称记录全保留。错误不暴露运行绝对路径。
- own 映射从本书原始 manifest JSON 严格取值，不从补过默认值的 model_dump 取；metadata 不存在与有效空映射分别观测。canonical manifest 本身不存在／损坏时报告 book 不可用，不能仍称只有“无进度”。shared 映射只来自当前读者 overlay，绝不返回 owner 的会话 ID。
- authenticated 配置核对实际 actorId；匿名配置的 owner 是 I3 受控配置标签，不假设等于服务端 local-admin ID。保存两者及身份强度，workspace 必须明确吻合；deploymentId 仍是操作者绑定，不能伪造成服务端认证。
- 新入口 404／旧形状／缺 scope／缺 schema 时停止相关采集，零旧 GET 回退；可保留明确的诊断包。缺失与失败不创建 Progress 或 overlay 文件。

### 2.3 补丁工程约束

I4 的发行物和验收证据冻结。新补丁记录 base commit、I4 基础 patch/wheel、I5 增量 patch 和最终 wheel hash；按上游模块归属实际构建需要的 wheel，不默认“任何改动都只需 books”。不直接编辑 site-packages，不覆盖 I4 的 manifest、补丁或旧报告。

构建标识不参与既有 I3 scope digest，兼容只读升级不能使 activity 映射失效。I5-A 已增加独立 `learningStateReadBuild`（baseCommit/i4PatchSha256/patchSha256/wheelSha256），保持 I4 旧配置可用；不因为增添 provenance 重置数据身份。新路径已在真实路由＋实际临时存储测试通过后加入安全读取清单。

**I5-A 未通过，不推进“完整进度采集已实现”的结论。** 可先写纯记录投影／历史反例分析。若必须修改生成、评估或权限核心流程，停止扩补丁并回报最小缺口。

## 3. 会话的选择、校验和覆盖

### 3.1 首期选择范围

采用 **当前 reader 的 pageChatSessions＋操作者明确提供的 sessionId**。显式选择文件包含 sessionId 和预期 book/page；重复选择去重，但保留选择来源。只对所选会话读取公开详情和 events，不默认扫描全部会话或账户历史。

当前映射可能被新会话替换，旧会话可能归档／删除；因此 `allHistoricalSessions=unknown`，Book 级 `historyCoverage=partial`，即使所有所选会话都读完也不提升为“该书全部历史已导出”。空映射／未选择额外 ID 只能说本次未发现所选会话，不能推断没有求助。

不使用 `GET /sessions/{id}/threads` 作只读发现：其实现会尝试 backfill 归属。也不使用 ask-hint、migration/adoption、消息重放／改写入口。未来完整发现另立任务；不能在 I5 顺手增加全库搜索或无界 offset 扫描。

### 3.2 身份与记录

复用已核对的 `GET /api/sessions/{id}`、必要的 organization 元信息、`GET /api/sessions/{sid}/messages/{mid}/events`；开工测试须确认当前 SQLite/单 worker 形态的这些调用无生成／业务更新。新建 store 的初始化／schema migration 是实例准备动作，不能计成采集的零写证明；测试先初始化并停止迁移，再观察业务表和文件。

- 双向核对 book.page→session 与 session.preferences.book_id/book_page_id，以及实际当前 workspace。shared 的 learnerScope 与 canonical content owner 分开，禁止串作者聊天。
- 显式旧 session 可以已不在当前映射中，但必须有匹配 book/page 的反向关联，标 `explicit_historical`；不因标题或时间相近认领。缺反向关联、冲突 book/page/workspace、查不到会话：隔离诊断，不把它当有效空历史聚合。
- Message.id 在其 session／部署／owner/workspace 范围内使用；父子／分支关系、preferences 中的 branch selection 原样保留。不把所有分支线性拼成用户实际读过的一条对话；断父链／循环／未知角色单列 partial。
- 会话摘要 compressed_summary、失败回合附注、active_turns 均为各自类型的公开观测，不升级为原始回答或权威判分。active_turns 非空时记 unfinished，保留已存消息，不自动等待／取消／恢复回合。
- API 限制、缺 ID／时间等必须记覆盖；不调用另一个模型“补全聊天”。附件只保存公开描述与引用，内容未固定则 `attachmentCoverage=references_only/partial`；不沿附件 URI 任意下载。它与 I4 内容资源范围是两件事。

### 3.3 事件分页

仅对有明确规范 turn 关联的消息分页。以请求 after_seq 和上游返回的 seq 继续，核对 session/message/turn 身份、严格递增、无冲突重号、游标有前进、total/last_seq/complete 一致，并在末尾重新核对位点／内容摘要。不把 seq 连号作为唯一真值，不假设事件有全局顺序。

保存分页响应原字节及每页边界，不直接用最后一页覆盖详情预览。规范事件已经完整补取时，详情中的 `_truncated` 与已恢复的规范正文分开表达；未恢复／legacy／缺事件 turn／游标卡住／404／达到限额均 partial。`complete=true` 不能单独推翻旧预览的 truncated/total 或 legacy 事实。

只导出公开用户／导师消息和公共事件，不读 provider replay、model_turn、provider_response_state 等内部状态。现有详情会去掉两个私有 metadata 键，但 events 分页路由没有同样显式调用；实施必须用注入反例验证边界。若 HTTP 响应出现私有字段／凭据回显，拒绝将其原字节落入交接包，保存安全错误及 wire hash，标该项未捕获／partial；不得先保存“原始证据”再声称已经去敏。若必须补上游公共过滤，限定为既有公开序列化边界的小补丁并单独验收，不开放内部历史读取。

## 4. 作答记录与派生判断

### 4.1 原始事实和稳定 key

每个 attempt 保留原始对象、响应 artifact／JSON pointer／数组位置；字段缺失与显式 null 不等价。坏成员也保留其安全原值和诊断，不静默剔除后报全通过。进度的 score、weak_chapters、导航／书签是上游观测，不能用 score／访问页数宣布理解率或完成。

- 非空合法 submission_id：key 是**结构化元组** `(deploymentId,ownerId,workspaceId,bookId,submission_id)` 的版本化 canonical 摘要，同时保存组成字段，不能简单以冒号拼接而产生歧义。
- 同一 key 多次且原始答案、page/block/question、is_correct、timestamp 不同：记录 identity_conflict，保留各观察，不选最后一份覆盖；相同 key／完全相同 payload 可去重呈现，但保留全部原始位置。
- 缺／空 submission_id 的旧记录：`identityQuality=legacy`，用 export 内 rawRef＋数组位置定位，不跨 export 合并；相同时间／答案／hash 的两次尝试仍可能都是事实。
- 保存所有尝试，不只取 latest。旧上游 latest 的 key 不含 page，不能将其聚合分数当项目完整记录身份规则。

### 4.2 分类与选择题复核

| 可见事实 | 保守分类 |
| --- | --- |
| 可定位 choice，is_correct 为 bool | `method=client_reported`，原值不改；这不是服务端权威评分 |
| 已知非 choice，user_answer 为 self:correct/self:incorrect | `method=user_self_report`，保留原值和不一致诊断；不伪造书面答案原文 |
| 有实际 attempt，is_correct 显式 null | `method=ungraded`；不能改成 false |
| is_correct 缺失／类型错误、题型不明／身份歧义 | `method=unknown` 或具体 unsupported，保留原值；不推断已揭示或自评 |
| 基线题没有 observed attempt | 独立 `missing_attempt` 观察；不生成假 submission 或“答错”记录 |

非 choice 的任意非空文本不自动视为 self-report；题型缺失或已漂移时也不按字符串猜定真实题型。原 API 不足以证明揭示按钮的完整过程，故“空答案＋null”只证明一条 ungraded 记录。同步 assessment 的 HTTP 500 不一定表示 progress 未保存；未观测到原错误就记 `assessmentSync=unknown`。不为验收重发 quiz-attempt／补同步。

attempt 本身不保存题型，任何题型分类须注明所依据的 snapshot。历史绑定 unknown 时，不把基线题型说成用户当时题型；原 is_correct 及其客户端报告来源仍可独立保存，语义分类保持 unknown／条件性。

`choice-key/1` 只针对 I4 已支持、唯一 `(pageId,blockId,questionId)` 的单答案 choice；检查 user_answer 是否**精确**等于某选项键，再比较 correct_answer。未知／多答案／文本答案／UI 大小写转换不做模糊归一化：不支持或不唯一时 derivedCheck=unknown，不把解析失败判为答错。原客户端判分与复核不同，保留两者并标 disagreement。

## 5. 内容绑定和时间门禁

复用 I4 的完整快照验证和**本次新检查**，不读取某个旧 checkId 的历史成功就当当前结论。包中引用 rule、contentDigest、resourceManifestDigest、sourceMappingDigest、实际 accepted binding、reviewDigest 和本次检查；只比 revision／当前题干不足。

每条记录最多 `binding=baseline_consistent, assurance=cooperative, submissionContent=unknown`。须同时满足：

1. I3 activity/backendScope 真实匹配；引用有效且完整的 I4 accepted binding，而非任意候选快照或仅 decision=pass 的文件。
2. 完整包、正式绑定及所指审查证据校验通过；本次检查仍一致且来源可用，原文缺失和内容相同是分别表达的事实。
3. purpose=pre_learning；时间存在、有限、合理，记录时间在**capturedAt 与首次 boundAt 均之后**。不能只比较捕获时间，让学习后才通过的审查变成学习前交付。边界精度不明／同一不确定时段／时钟异常均 unknown；跨端时钟没有证明时，只是明确的本机协作时间假设。
4. page/block/question 可在固定基线唯一定位；不存在未解释内容／资源变更、采集中的记录冲突或未完成关键读取。

retrospective、早于绑定、无时间、缺基线、未获正式绑定、内容／资源变更、身份错配的记录为 unknown。仍可附 `comparisonToBaseline` 条件性复核，必须标 `historicalBinding=unknown`，不称其为用户当时题目的评分。现有 I4 包只给 capture 微秒时间，不证明服务器时钟精度；I5 不补造缺失历史。

ABA、另一客户端显示内容、提示影响和独立作答均未证明，**首期永不输出 verified_at_submission 或 mastery_passed**。有关联公开教学消息可以标 assistance.observed 并附证据及范围，缺记录一律 unknown，不能推出 unassisted。

## 6. 一致性、有限读取和发布

### 6.1 一次完整采集轮次

协作暂停新答题／编辑／追问是操作者声明，不是服务端锁。一次轮次按以下顺序取事实：

1. 核对 I3 映射／生产未决项、配置 scope、来源／语料；来源缺失保留单独诊断，身份错误则拒绝关联。
2. 在整个窗口**两端**各取一次 I4 内容／资源观测；窗口内依次读取 learning-state 开始位点、所选会话详情／events，再重新读 learning-state 和所选会话关键边界。不能只在窗口中间检查一次内容就称整个导出期间一致。
3. 比较进度**完整语义 payload**、attempt 身份／位置／原值、页边映射、会话消息身份／正文／分支、事件和 active-turn 状态、内容／资源摘要。数量／updated_at／末尾 ID 相同也不能忽略同 ID 原内容变化。
4. 有变化则完整重开轮次，最多再试两次，总计三轮。跨轮次不拼一个“完整”结果；原轮次响应留在尝试证据，最终仍变记 inconsistent/partial。一个轮次的 events 分页有自己的起止位点，不能因页数耗尽就报完整。

I5-B 已从 I4 提取共享的 **learning_context／read_content_once／evaluate_content_observations／load_learning_evidence**，D/E 进一步共享 quality_review_reasons 供搬运包离线校验。I4 原命令行为保留；D 已组织含会话的完整窗口和三轮上限，不套 B 操作叠重试。所有轮次共用持久化请求／字节／分页限额；不依赖私有 `_check` 作为跨模块契约。

### 6.2 默认资源限额

首期建议使用可信操作者配置的保守上限，实施时固定进 `exporterVersion`／回执并写测试：最多 32 个所选会话、10,000 条消息、50,000 条公共事件、100 次事件分页；单响应沿用现有 64 MiB 上限、最终包 256 MiB、一次 export 总 HTTP 请求不超过 512。限额**覆盖所有重读轮次**，不是失败后清零；不受资料包或模型输出自行放宽。

会话详情无消息分页 API，不能发明 offset 参数或截前 N 条仍报全。达到任一上限时保留已完整取得的记录与准确截断位置／未访问清单，coverage=partial；整份响应传输失败不宣称已经捕获其中任何完整记录。不启动生成，无模型预算；这些是采集资源限额，不是 I2 旧 tokens 额度。

### 6.3 不可变交接包

`exportId` 固定 activity、scope、选择集合、snapshot 选择、声明、规则／能力版本、限额等语义输入，不绑定可移动机器路径。相同 ID 已完成则返回历史结果，检查包 hash；不同输入冲突。需要新观察用新 exportId。中途崩溃的新尝试重新完整读取；若已完整发布则恢复原回执，不重新关联当前已改的学习状态。

复用 I3 OS 单写者、严格 JSON 和原子发布；独立 `exports/`／导出操作 namespace，不使用生产 POST reservation。staging 写入原响应、records、判断、基线证据、manifest，逐文件核验，完成标记最后写并发布整目录；不允许先更新索引或读到半包。Windows 长路径、路径逃逸、符号链接及跨进程竞争沿用 I4 的实际故障测试。

包自包含：复制被引用的 I4 snapshot、资源、基线绑定／审查及本次复核证据，改用包内 ID／相对引用，并验证同一 digest；不能只放原机器 state-dir 路径。来源 metadata 和 hash／定位原样保留；原文没复制到包里时明确 `sourceRetention=external`，该包不是源材料全备份，接收方缺原文不能宣称核验事实。默认不自动嵌入全部原文或下载聊天附件。

已存在的 I4 文件须复制**原字节**。由新增交接层建立“旧 ref → 包内 artifact”的映射，不改旧 JSON 路径后还宣称原 digest；旧 locator 仅为历史定位，离线验证不能依赖其所在机器仍可访问。必要的不可变 review request／绑定证据同包附带，不能只复制一个脱离审查来源的 baselineBound=true。

`collectionStatus`、各维度 coverage、binding、completion 分开：稳定得到一个部分覆盖包可以成功发布，但 CLI 返回 partial。损坏／越界／scope 错误绝不能当可消费学习包；可发布独立诊断，不混入有效 record 集合。rawRef／JSON pointer 必须指向实际保存的公开字节；去敏／拒绝响应另标，不用 hash 冒充已保存原文。

## 7. 应用操作、CLI 和字段

最小新增建议为 `handoff.py`：普通 `export_learning_results(...)` 操作及 `verify_handoff(...)` 本地包验证，按需一个小记录投影文件；复用已有 scope/HTTP/证据模块，不建新的任务运行框架。

已实现 CLI：

```text
export-results --activity … --export-id … [--snapshot-id …] [--sessions-file …]
               [--collection-declaration …] [--completion-declaration …]
               --deployment … --state-dir …
verify-handoff --package <交接包目录>
```

未指定 snapshot 时只使用已有 accepted binding；没有基线也允许导出原记录，binding unknown。指定候选快照仅作明确比较，不能借此绕过首次绑定。完成声明可选，必须具有实际作者／来源、scope、时间和原始声明文本；外部 Agent 转交时保存 submittedBy 与 attributedAuthor，不能仅凭一个 role=user 字段宣称已认证。无声明时 completion=unknown，不从 READY／访问／正确率推结束；声明不代表课程质量通过或知识已 approve。I5 不增加独立“结束审批”流程。

结束声明只是其时点的用户陈述；若后续仍有可见学习记录，保留原声明并标 laterActivityObserved，不删除声明，也不把它当当前仍已结束的状态证明。

输出沿用 UTF-8 JSON／现有退出码，提供相对 state-dir 的 receiptRef／artifactRef。包验证零 HTTP／模型，可离线核对所有内部引用；外部来源未附带属于明确覆盖限制，不靠重查远端补齐包。读取／导出不额外弹用户批准窗口，也不修改正式 raw/wiki。

交接字段沿用 D2 `learning-handoff/1`，已固化 [schema](../../tools/learning_book/schemas/learning-handoff.schema.json)：backendScope/build、activity、sources、content/binding、原始 records 与稳定 key、assessments.raw／comparisonToBaseline、navigation、conversation selection／消息／events／分支、assistance、completion 声明、逐项 coverage、collection boundaries／限额、errors/limitations 和 manifest。正常／partial／diagnostic 结构校验及离线字节校验均已实测。

## 8. 子任务和依赖

| 子任务 | 交付和关闭标准 |
| --- | --- |
| I5-A 严格学习状态读取 | 新 GET、own/shared 严格读取、实际路由／存储与旧入口兼容测试；独立增量补丁／发行物身份 |
| I5-B 记录与绑定（已通过） | 43 项本地／HTTP 测试；attempt key／legacy／冲突／null、条件复核、实际审查链／本次窗口和 capturedAt＋首次 boundAt，详见 B 验收 |
| I5-C 所选会话与事件（已通过） | 28 项契约与 9 项实际公开路由／SQLite 验证；双向作用域、有限分页、legacy／私有字段／附件限制 |
| I5-D 一致性与包（已通过） | 单轮原语＋最多三轮、持久限额、原字节／refMap 搬运、原子发布、实际进程退出／恢复与 OS 锁 |
| I5-E CLI 与交接（已通过） | 两 CLI、完整 schema／正常与 partial 包、D/E 合计 24 项实测、C01–C20 对照和 I6 交接 |

A → B/C → D → E 均已按依赖完成，最新统一复验在 validated，保留原 A/B/I3/I4 报告，不将合成 HTTP 替代实际路由证明。下一步 I6 核对实际安装、真实活动映射／生产学习／备份恢复；本次不自动启动。

## 9. C01–C20 必测场景

| 编号 | 必须观察到的事实 |
| --- | --- |
| C01 | 新 learning-state 在各 Book 状态零 resume/生成／业务写；缺失项不新建文件；实际 owner/workspace/shared reader 隔离；旧入口不变 |
| C02 | 缺文件、有效空、坏 JSON、重复键、非有限数、错误 book_id、非法成员、读中删除／替换分别诊断；不补 timestamp／默认答案，不静默丢记录 |
| C03 | 新能力缺失／旧包装／认证身份或 workspace 错配，拒绝关联；零旧 Book GET、零 POST、零 runtime／SQLite 产品旁读 |
| C04 | 多页多块多次尝试完整保留；scoped submissionId、相同 payload 多位置、冲突 payload、无 ID 的重复 legacy，均不按答案 hash 错去重 |
| C05 | false／null／缺失／错误类型、自评／未知题型／无作答分开；不伪造 written 原文、模型评分或 HTTP 500 原因 |
| C06 | valid choice 精确键复核、选项顺序、不合法／多答案／大小写不匹配、重复题身份；原判分与复核不同均保留，不回灌 |
| C07 | 无／坏／未正式绑定基线、retrospective、时间缺失／异常／早于 capturedAt 或 boundAt、近精度边界、缺原文，绑定保守 unknown |
| C08 | 当前内容或同 URI 资源变更、scope 错、ABA，至多 cooperative；不出现 verified_at_submission／mastery 或独立作答承诺 |
| C09 | shared 不读 owner 会话；显式历史 session 合法反向关联／映射替换／错误 book/page/workspace／404／缺关联分别处理，不按标题收编 |
| C10 | 当前映射为空仍 historyCoverage partial／assistance unknown；所选会话均读完不称全部历史；无全库扫描、threads backfill、hint／migration |
| C11 | 多页规范事件核对身份、游标和边界；重复／冲突 seq、无前进、变化 total/last_seq、404、限额，均终止并 partial |
| C12 | 详情预览／大字段裁剪、legacy turn=None 的空 complete=true、缺规范 turn、失败／运行中回合，保留原可见记录与覆盖，不能伪装全文 |
| C13 | 私有 provider state／model_turn／凭据回显注入反例不写入包／stdout；普通公开事件可读；附件外链零任意请求 |
| C14 | 消息分支与父子、同 messageId 改内容、断链／循环、同 count/updated_at 改答案均可见，不线性伪造对话或只比数量 |
| C15 | 学习状态／会话／内容在读取间变化：最多三轮、不跨轮拼完整；所有重读共用 HTTP／字节／分页预算，超限保留明确 partial |
| C16 | raw/records/baseline/assets/manifest/complete/publish 各边界故障及实际进程退出；未完成不可见，重启新轮次，发布后恢复原事实 |
| C17 | 相同 exportId 复用／不同输入冲突、OS 两进程争用、snapshotId 不可替换；导出 namespace 不占生产 reservation |
| C18 | 把包复制到另一目录、移走原 state-dir 后仍能验证内部引用；篡改／缺文件／路径或 symlink 越界拒绝；外部原文缺失不伪装源材料备份 |
| C19 | 无完成声明／有效用户归属声明／Agent 转交／作用域错／过早声明分开；不从分数或 READY 推完成，不触发正式 approve |
| C20 | 零模型配置／零生成预算可执行；JSON CLI／退出码／离线 verify；I3 36＋I4 29 兼容回归，产品不 import 测试／文档／私有探针 |

测试采用真实 loopback HTTP 假服务、临时文件与独立进程；A 使用实际 FastAPI＋own/shared 存储。会话路由使用实际 SQLite 临时库、规范 turn 和 legacy 消息，验证公共视图／分页真实行为，而非只测 exporter 自造包装。既有 I2 原始安全响应可作为注明 provenance 的反例／回放；不新增假真实用户、不删失败项来通过。
## 10. 交付、预算和接续

完整交付位于 `docs/design/evidence/learning-book-i5/validated/`：代码／补丁／发行物身份、174 项项目测试与实际路由复验、正常／partial 可搬运样例、schema、C01–C20 对照和 I6 交接。原 A/B 样例和早期 final/acceptance 试跑保留历史，不当作最新字节闭合；B 的进度样例不是完整包。`learning-book-i5-design` 仍仅为原源码核对。

本轮／I5 的无模型实现与测试不使用生成额度。I2 的原 100 万和后来 3 万均已结案；需要真实编译／追问／补题时，另获 I6 的有限额度。不能通过再生成整本书来获取漂亮导出夹具。

接续入口：**I5 已通过，阅读 validated 验收后再决定 I6 的真实部署集成与额度**。公开 API 无法取回的历史保持 partial／unsupported；不引入第二套学习库补真值，不恢复缺失历史，不扩大成新 Agent harness。
