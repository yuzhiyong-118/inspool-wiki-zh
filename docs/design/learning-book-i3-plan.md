# I3 详细任务书：来源交付与生产回执

> 公开设计摘编：保留通用契约与方案；历史验收、用户反馈、运行记录及本地素材不随仓库发布。设计条目不代表部署或验收完成。

## 3. 输入、身份与持久对象

### 3.1 外部 Agent 提交的资料包

一个 `prepare.json` 描述一次已经明确决定用于学习的资料整理结果。I3 不根据“收到链接”推断应该成课，也不强制每份素材生成书。整理者在包内给出以下内容：

| 字段 | 必需语义 |
| --- | --- |
| `schemaVersion`、`packageId` | 本契约版本与稳定资料包身份 |
| `preparationDecision` | 本操作只接受 `learn`；参考、暂缓、直接知识候选不走成书流程 |
| `sources[]` | `sourceId`、`sourceVersionId`、原始字节 `sha256`、原文定位及来源元数据 |
| `inputArtifacts[]` | `inputArtifactId`、字节 hash、包内定位、UTF-8 文本类型、对应原文版本、提取方法／版本及覆盖或截断说明 |
| `corpusId`、`corpusVersionId` | 这一批冻结输入集合；成员清单与内容摘要确定后不原地换内容 |
| `learningGoal`、`language`、`depth` | 非空短目标；首期中文／brief 可作为明确默认值写入规范化请求 |

约束：

1. 原文 hash 与上传投影 hash 分开。即使原文正好也是 Markdown，也记录两个角色；同一字节可复用存储，但不能合并不同作者／URL 的来源身份。
2. 所有引用先解析定位，再读取字节并核对 hash。上传应使用已校验并固定的同一份字节，而不是校验文件后另开路径上传变化后的内容。包外路径、目录逃逸、符号链接越界、重复 ID 内容冲突或非 UTF-8 输入须明确拒绝。
3. 原文定位允许作为独立只读本地来源引用；上传投影必须落在明确的资料包根内。外部 URL 是来源元数据，仅有 URL 不满足原始字节留存要求，先由生产者准备本地原文。学习创建前需要核对的原文缺失或 hash 不符时暂停，不拿摘要替代原文证据。
4. 截断／部分提取不能静默标完整；已知不完整输入不进入本期自动创建路径，返回整理者缩小或补齐资料包。实际被 DT 消费的上下文长度若没有采集，另记 `unknown`，不能由上传完整推出模型读全。
5. 资料移动但 ID／字节不变时只改定位；字节或语义输入变化时新增版本。UUID 等稳定 ID 由项目或准备者生成，禁止用标题、文件绝对路径或 bookId 充当项目来源／活动 ID。
6. 实施核对 TopicSource 与 grounding 后，首期每包限 1–16 个输入提取物，每个 sourceId 选择一个版本。Book DTO 虽可接 32 个 source_refs，实际直接 grounding 仅取前 16 个。请求补齐必填 label；回执记录每文件 4,000 字符／文件上下文 80,000 字符的已知上限及投影字符数，实际模型覆盖仍为 unknown。更多资料由生产者分包，不静默丢弃第 17 份起的显式来源。

### 3.2 后端作用域

`BackendScope` 保存 `deploymentId`、`ownerId`、`workspaceId`、身份校验方式及配置摘要。`activityId → BackendScope + bookId` 是追加后保持稳定的映射，不能把原活动重绑到新书。

- 本地未启用认证的部署，`/api/auth/profile` 不可用不是登录故障。支持显式的本地单用户配置绑定，记录 `scopeVerification=configured_single_user`；不能声称上游提供了服务端部署 UUID 或认证身份验证。
- 启用认证时用实际公开身份核对 owner；身份不符不得退回匿名默认上下文。deploymentId 由受控本地配置持有，端口不代表部署身份；runtime 更换／重建须显式重新绑定，不按同名 book 猜身份。
- Book workspace 明确传递；空字符串表示明确选择 General，不把省略选择、当前界面默认值和 General 混在一起。
- **KB 是资源库管理作用域，不必与 Book workspace 一一对应。** 保留其真实 owner／资源引用和显式选定集合，不以给 KB 请求附 workspace header 就宣称实现了语料隔离。学习隔离依靠专用、协作冻结的 corpus／KB 与核验后的成员清单。

### 3.3 本地记录

| 对象 | 保存内容与不变量 |
| --- | --- |
| `CorpusReceipt` | scope、corpus 版本、全部成员、inputArtifact/hash → KB/path、上传与索引观测、覆盖；成功后不得追加无关资料 |
| `ProductionRequest` | requestId、activityId、scope、corpusReceiptId、规范化目标／生成参数、请求摘要；发送前持久化 |
| `ProductionReceipt` | receiptId、请求引用、每阶段状态、请求／响应证据、bookId、revision 观测、失败／不确定与恢复线索 |
| `ActivityMapping` | activityId、scope、bookId、生产回执引用；不含进度／得分／完成度 |
| 派生索引 | 仅供定位，可由上述记录重建；不能成为唯一事实来源 |

保存上游实际请求的规范化 JSON 字节和去掉敏感头的响应字节，附 SHA-256、HTTP 状态、采集时间与内容类型。凭据由部署配置引用，不进入请求摘要、回执或错误正文。不能伪造 `GET Book` 会返回专用 `inputs.json` 的能力。

JSON 摘要沿用 D2：UTF-8、键排序、紧凑分隔、不转义中文、拒绝 NaN。请求摘要包括操作、作用域、资料身份／内容、会影响生成的目标与参数；不包括凭据、时间戳和可移动的本地定位。源列表顺序若影响提交则保留，不能为凑相同 hash 擅自排序。确认 proposal／spine 的 payload 与 expected_revision 属于对应阶段请求摘要。


## 4. 应用操作、CLI 与上游接口

下面是本期接口名称与语义；实现采用普通函数／数据对象，未来 Web／MCP 直接复用，不新增服务协议。

| 应用操作 | CLI：`python -m tools.learning_book.cli …` | 结果 |
| --- | --- | --- |
| `validate_package` | `validate --package <prepare.json>` | 规范化清单、hash、可创建性及缺项；纯本地，不上传 |
| `publish_learning_inputs` | `publish-inputs --package … --request-id … --deployment …` | 上传／核验／索引回执；与创建书分开，可供多活动复用 |
| `create_activity` | `create --corpus-receipt … --request-id … --activity-id … --intent … --deployment …` | 保存请求，真实 POST 创建书，返回 book/proposal 与回执 |
| `confirm_proposal` | `confirm-proposal --activity … --request-id … --payload … --expected-revision …` | 单次明确确认与 spine 回执，不自动确认下一步 |
| `confirm_spine` | `confirm-spine --activity … --request-id … --payload … --expected-revision …` | 显式 `auto_compile=false`，页面壳回执，不自行编译 |
| `inspect_receipt` | `show --request-id …` | 默认只读本地回执，不触发上游生成 |
| `reconcile_request` | `reconcile --request-id … [--candidate-book-id …]` | 只核对已有证据／候选，不重发原写请求；无法确认则保留 uncertain |

CLI 统一输出 JSON：`operation`、`requestId`、`status`、`receiptRef`、`activityRef`、`errors`、`nextAction`；需要时输出语料／proposal／spine 证据引用，不把大正文或敏感信息直接刷终端。退出码区分成功、输入冲突、占用、失败和 uncertain／partial；具体数字在 CLI 文档固定，未知结果不能返回普通成功。CLI 不自动创建后台守护进程。

表中模型操作另须 `--budget-context <已授权计量上下文>`；共享计量语义见 §6。`create --intent` 是本次活动的有效目标，覆盖资料包建议时把两者与覆盖关系保留在请求中；学习目标不是 corpus 成员摘要的一部分，因此同一资料集可用于不同目标。

### 实际上游映射

| 步骤 | 固定源码入口与必须核验的事实 |
| --- | --- |
| 建专用 KB、上传 | multipart `POST /api/knowledge-bases`、`POST /api/knowledge-bases/{kb}/upload`；稳定文件名来自 inputArtifact 身份，禁止覆盖已有不同字节 |
| 上传核验 | `GET …/{kb}/files` 枚举实际成员；`GET …/{kb}/files/{filename}` 读取原始字节，直接比对上传 hash；preview-text 不是原始字节证明 |
| 索引核验 | `GET …/{kb}/indexing-run`；核对 `run.state`、对应文件 `documents[path].status/source_hash`、可用版本及任务身份。缺字段／旧任务不能当本次成功 |
| 环境预检 | `GET …/{kb}/indexing-readiness` 只证明解析／embedding 配置和前置条件，不证明文件已索引；不能全文搜 ready/completed 判成功 |
| 创建书 | `POST /api/books`，保存 `{book, proposal}`；真实 source_refs 为 `kind:file, source_id:<KB 相对文件>, metadata:{kb_name,path}`，同时指定 knowledge_bases |
| 确认提案 | `POST /api/books/confirm-proposal`，显式 book_id／proposal／expected_revision；保存 `{book, spine, book_revision}` |
| 确认大纲 | `POST /api/books/confirm-spine`，显式 `auto_compile=false`，保存 `{pages, book_revision}`；不把页面壳当 READY |
| 无生成核对 | `GET /api/books` 列表、`GET /api/books/{id}/spine`、`GET /api/books/{id}/pages/{pageId}`；具体字段按上述版本解包 |
| 有潜在生成副作用 | **`GET /api/books/{id}` 会调用 maybe_resume_on_open**；不能放进通用“GET 都免费”的重试／核对路径。确需调用时按可能生成操作处理 |

语料发布须满足：所选输入原始字节一致、实际成员与冻结集合一致、匹配本次／可核对的索引运行及文件 source_hash、存在可用索引版本。这里上游 `documents[path].source_hash` 对比的是**上传的 inputArtifact hash**，不是清洗前原文的 hash。KB 名称存在、文件大小相同、HTTP 200 或 parser ready 都不足以满足。上游失败可返回诊断性 partial 回执，但不能生成可供 `create` 消费的成功 corpusReceipt。

同一冻结 corpus 可由不同 activity 复用，不重复上传／索引；同一 input hash 不抹去其来源身份。新成员或变更创建新的 corpusVersion／KB。已冻结集合出现未知成员／替换字节时标记漂移并停止创建，不能自动清理上游资料。


## 5. 请求去重、崩溃恢复与不确定成功

### 5.1 最小本地持久性

本地采用请求目录、不可覆盖的阶段证据与原子替换的当前回执；不增加 SQLite Task／Run 平台。可重建索引晚于证据发布，损坏时重建，不回滚已确认的远端事实。

首期每个 backend scope 只允许一个项目生产操作在途，使用 OS 文件锁，崩溃自动释放；忙时明确返回，不排后台队列。不以仅保存 PID 的永久锁目录代替操作系统锁，也不增加租约续期／过期接管系统。此锁只约束本项目调用者，用户原生 UI 的并发修改仍依赖上游 revision 和后续核验。

实施采用更严格的同 state-dir 全局单写者，防止跨部署同活动同时建书；所有参与 Agent 共用该状态根。账户 KB 的复用按独立资源作用域核对，可跨 Book workspace 复用；Book 活动映射仍绑定其实际 workspace。没有引入第二种锁服务或后台队列。

一次阶段操作的顺序：取得占用 → 校验／读取已有同 ID 请求 → 原子写 prepared 请求 → 持久写 dispatching → 发 HTTP → 先保存完整响应证据 → 提交最终回执／映射 → 更新派生索引。临时文件与目标文件同卷；写入、flush/fsync 后原子替换，进程崩溃不能留下半个成功 JSON。普通进程崩溃恢复不升级为跨本地／上游的分布式事务或断电全保证。

请求状态只表达交付结果：`prepared`、`dispatching`、`succeeded`、`failed`、`uncertain`。上传／索引未完整可另有 coverage=partial；这些不是学习状态，也不是新的通用工作流引擎。

### 5.2 精确处理规则

| 情况 | 必须行为 |
| --- | --- |
| 同 requestId、同摘要，已成功 | 返回原回执和原 book／corpus，不再发写请求 |
| 同 requestId、不同摘要 | 冲突，零远端写入；不能以“重试”覆盖原请求 |
| 同活动再次 create | 已有映射则拒绝重建；已有 dispatching／uncertain 请求时也锁住该活动，不能换 requestId 绕过。corpus 的不确定发布同样先核对，不用新 ID 再建同一 KB |
| 重启发现 prepared | 没有 dispatching 证据才允许继续原阶段；需要的执行授权／预算仍须有效 |
| 重启发现 dispatching，无完整响应 | 记 uncertain；即使可能尚未真正发出，也不盲目重发 |
| 已有完整成功响应，最终回执未写 | 按响应、作用域及输入身份恢复本地回执／映射，不再次创建 |
| 超时、连接断开、5xx、响应损坏 | 写操作默认 uncertain，除非有确切“不曾发送／没有副作用”证据；不能统一按失败自动重试 |
| 明确前置校验拒绝／409 | 保留错误与 revision；不自动刷新 revision 后重放确认 payload |
| 上传结果不明 | 核对稳定文件名、实际字节和运行证据；不能按文件名存在就判成功，也不能覆盖式重传 |
| bookId 不明 | 列表仅供候选展示；标题相同、出现时间接近都不能证明属于本请求。没有可靠关联保持 uncertain |
| bookId 已知、确认结果不明 | 使用列表／spine／page 等核对，或原响应证据；不得顺带触发 GET Book 自动恢复生成 |
| 用户指定候选 bookId | 必须核对 scope、可见输入身份／阶段产物并保存认领依据；无法证明来源时不得伪造全覆盖的生产回执 |
| 远端成功，本地状态目录失败 | 仍视为 uncertain 并报告已知远端线索；不删远端书补偿、不据本地空目录重建 |
| 后端对象删除或 scope 改变 | 保留旧映射／证据，标 missing 或错配；禁止按标题自动迁移到另一对象 |

不能单凭 4xx 推断零副作用：固定版本的 confirm 路由先领取／保存 revision，再校验 edited proposal／spine，因而无效 payload 返回 400 时也可能已经推进 revision。保存该响应并安全核对，不能把它当作“完整没有发生”而无条件重试。

`failed` 的相同请求默认返回原失败，不隐式重发；确有无副作用证据且需要重试时，创建显式关联前次记录的新请求，核对该活动／corpus 没有成功、在途或不确定操作后才允许发送。结果永久无法确认时由操作者决定如何处置，不能为了继续而伪造“远端一定没有发生”。

确认步骤每次有自己的 requestId／digest／回执，并关联同一 productionReceipt 与上一步；修订 proposal／spine 是新阶段请求，不能改已成功历史。用户／外部 Agent 已明确提出创建或确认时，不再额外强制同意一次同样操作；仍不能把“上传好了”自动等同于批准所有后续模型生成。


## 6. 预算、副作用和阶段依赖

创建、confirm-proposal、索引中的实际供应商调用，以及可能恢复生成的读取均按真实副作用分类，不只按 HTTP 动词。confirm-spine 虽设 auto_compile=false，仍作为生产写操作记录，不能让未知上游行为绕开预算检查。

实现阶段对需要模型的操作必须接收有效的执行额度上下文：累计 scope／基线 call_id、输入＋输出阈值、reported／estimated／missing、独立在途监控与停止入口。不同确认步骤共享同一个已授权计量上下文，不能每条 CLI 命令清零；本地 embedding 单列。无法观察用量／控制停止时不得发起新的模型操作。关闭 HTTP 连接不等于停止后台任务。

I2 的守卫算法、错误案例与 Windows 进程身份校验可参考，但实现需参数化部署／书／账本，不能硬编码 I2 的 bookId、基线或端口，也不能从文档／探针目录 import 产品代码。不在本阶段建设通用预算服务。真实暂停／终止只针对选定且核验所属的实例，供应商计费硬封顶仍不承诺。

**任务书和本轮 I3 实施没有调用真实模型。** 本地实现、HTTP 假服务和真实响应重放不需要新增模型额度。I2 的 100 万及 3 万额度都不作为 I3 默认额度。新建真实书或重新索引如会调用供应商，应先有对应的有限执行额度；不能为验收方便重复跑整本书。

阶段交接：I3 回执证明输入和远端创建／确认的已知事实；I4 才采集实际生成内容、资源与一致性基线并落实学前核验；I5 才交接真实学习结果；I6 才证明完整交付与恢复。当前网页直接开未完成页面可能触发编译，I3 不自动把其 URL 当“已发布课程”推送给用户。


## 7. 实施拆分与完成标准

| 子任务 | 最小交付 | 完成标准 |
| --- | --- | --- |
| I3-A 契约与本地证据 | contracts／evidence_store，资料包校验、原子回执与 scope 单写者 | 路径／版本／摘要稳定；崩溃和同 ID 冲突有确定结果，无网络必要 |
| I3-B 固定 HTTP 适配 | 真实 multipart／JSON、binary 读取、响应解包、超时／错误分类及 workspace 传递 | 不创建引擎、不写 DT 业务数据；有副作用读取不误归纯观察 |
| I3-C 语料发布 | publish_inputs、原字节核验、文件清单／索引运行匹配及 corpus 复用 | parser ready／旧索引／部分上传不放行，同 corpus 不重复索引 |
| I3-D 创建与恢复 | create／confirm／reconcile 和单次预算接入 | 每步先持久请求；恢复不盲重建；书／活动映射不重绑 |
| I3-E CLI 与验收交接 | JSON CLI、使用说明、fixtures／故障验证、结果报告 | 外部 Agent 无需读实现即可调用、判断下一步；验证层次如实区分 |

按 A → B → C → D → E 推进，每项用相应测试关闭；不为了模块数量单独扩展框架。任何约定与真实上游字段冲突，先修本文／契约并保存依据，不让测试夹具迁就错误实现。


## 8. 必测场景与验证层次

| 编号 | 场景 | 必须观察到的结果 |
| --- | --- | --- |
| A01 | 文件移动、同内容不同来源、正文变化 | 移动不改身份；不同来源不合并；变更版本／hash 冲突被发现 |
| A02 | 缺原文、错 hash、越界／符号链接、非 UTF-8、部分提取 | 上传前拒绝／暂停；远端写入次数为 0 |
| A03 | 校验后替换输入 | 上传仍使用固定已核验字节，或检测变化后拒绝；不能发出未核对内容 |
| A04 | 同 ID 相同／不同 payload、同活动重建、uncertain 后改用新 ID | 相同回执复用；冲突零写入；不通过换 ID 绕过不确定活动／corpus 的占用 |
| A05 | 两进程竞争与持锁者崩溃 | 同 scope 最多一个项目写入者；崩溃后锁可重新取得，不永久卡死 |
| A06 | 分别在 prepared、dispatching、响应保存后、映射保存前中断 | 可判定前续做、未知不重发、完整响应可恢复；保留远端成功事实 |
| A07 | 假服务已保存书但断开响应／返回 500 | 客户端 uncertain；重复运行／reconcile 不再次 POST create |
| A08 | corpus 复用、额外成员、同名不同字节 | 同集合复用；漂移停止；不覆盖或自动删远端文件 |
| A09 | parser ready=true，但索引 failed／旧 source_hash／无可用版本 | 不发布成功 corpus；仅文件可见不等于索引可用 |
| A10 | 二进制读回与 preview 归一化文本不同 | 只用原始字节核对上传 hash，不误报 preview hash 等价 |
| A11 | 三种不同响应包装及缺关键字段 | 正确解包 book/proposal、book/spine、pages；HTTP 200 缺身份不成功 |
| A13 | 同名书、错误部署／owner／workspace、General 空值、KB 资源作用域 | 不按标题认领；作用域错配拒绝；不把 KB header 当隔离证明 |
| A14 | 零额度下 inspect／reconcile 与 GET Book 副作用 | 本地 show／安全核对可用；不能意外恢复生成；未授权模型请求为 0 |
| A15 | 跨确认步骤计量、缺失 usage、在途越线／停止失败 | 不清零；停止新增调用；后台监控确实运行，停止失败可见，不自称硬封顶 |
| A16 | 本地索引损坏、远端对象消失、同响应重复落盘 | 索引可重建，原证据不改；missing 不重绑；本地发布不产生重复映射 |

测试以真实语义为中心，不要求一个场景一个测试文件。使用临时目录和可控本地 HTTP 假服务验证请求次数、响应丢失和跨进程恢复；不能仅 mock 本实现函数返回它自己期待的值。

再使用 I2 中去敏的真实请求／响应建立公开小夹具，核对参数、包装和原字节 hash。夹具不得依赖私有绝对路径、运行中的 I2 服务、已安装的 DeepTutor 源码包或真实 Key；重放必须标为 replay，不冒充新适配器已完成真实生成。

必要时可对既有隔离实例做无模型读取或独立临时 KB 的字节上传／读回，但不能修改 I2 的冻结语料、书与证据；需要索引／生成的集成测试须另有有效预算。I3 可按“本地与 HTTP 契约验收通过、真实适配写入待集成”明确交付，I6 的真实闭环不得引用该离线状态冒充通过。
