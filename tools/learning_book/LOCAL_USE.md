# 本地学习系统使用手册

当前本机配置为 `.learning-book-runtime/local/runtime.json`；学习底座为固定补丁版 DeepTutor 1.7.2，Windows／Python 3.12／Node 22／SQLite 单 worker。本机 loopback 使用默认 API 与网页端口（见安装参数）。课程、作答和教学会话仍由 DeepTutor 保存，项目回执和交接包独立保存。

## 启动与停止

在仓库根目录运行：

```powershell
$learnPython = '<学习运行时 Python 解释器路径>'
$learnConfig = '.learning-book-runtime/local/runtime.json'
& $learnPython -X utf8 -B -m tools.learning_book.runtime start --config $learnConfig
& $learnPython -X utf8 -B -m tools.learning_book.runtime status --config $learnConfig
& $learnPython -X utf8 -B -m tools.learning_book.runtime stop --config $learnConfig
```

重复启动会返回已有监督器状态；端口被其他实例占用时拒绝启动。启动失败先查 `status` 和控制目录中的私有日志。不要同时启动旧 `run_i6.py` 或另一个原生服务指向同一 runtime。正常入口会核对安装文件和生产网页摘要，升级后应重新核对发行清单。

## 用量及中断

`status` 返回累计实报／估算 tokens、总额、暂停线、受管进程、调用身份及停止原因。现有累计授权为 **100 万，80 万暂停**；迁移时完整继承 I6 的 67 个 call_id／用量见本机账本，没有把旧调用放入免计基线。本地 embedding 的 token 计量不可用。

获授权的收尾预审题验证新增用量（见本机账本），累计用量（见本机账本）；后续以实际 status 为准。该题运行成功但内容审查未通过，失败题已移除。课程材料见课程讲义（未随公开仓库附带）。

架构课程现已发布，准备新增用量（见本机账本），其中正文直写 0、首题 1 次调用；累计用量（见本机账本）。学习前基线通过，实际试学尚待完成。因无模型的依赖索引故障更换过恢复控制身份（实例标识属本机运行记录，不随本仓库发布）；仍是同一账本、全部历史、原总额与暂停线，旧锁和停止回执保留。

2026-11-13 已按 call_id 归并 Q3 的五条隔离调用（用量见本机账本），并升级到 Q3 `release-04`。当前控制身份为 Q3 修复实例（标识属本机运行记录，不随本仓库发布），累计用量（见本机账本），其中实报与估算见本机账本；免计基线、80 万暂停线和 100 万上限不变。原课程、作答、聊天和项目证据已核对，独立恢复通过。首次基线后的第八页使当前检查为 `binding=unknown`，不将首次基线改写为一致。部署与恢复证据见 后续交付第一批（未随公开仓库附带）。

监督器持续检查账本；模型公共计量入口在每次实际调用前检查同一门禁。预算到线只阻止新的模型调用，阅读、个人笔记和已有作答继续，不再把整项学习服务停止。API 另有失联检查线程，监督器丢失时停止自身及身份匹配的网页进程。没有 armed 开关。纯阅读不因账本长期不变而超时；单次实际模型调用当前有 600 秒上限。并发在途调用和供应商晚到计量仍可能越过本地暂停线，不能承诺供应商硬封顶。

`budget_pause`／`budget_exceeded` 先核对用量并取得新的额度决定；`usage_unknown`／`call_usage_missing`／`unsettled_calls` 先补齐实际计量证据。不得删除控制库、账本或预算回执来恢复调用。普通操作者停止或监督器失联，在没有未结算调用且累计预算有效时，可以重新启动。

编译或重生成中断后，页面标注本次状态和操作 ID，保留上次完整内容。打开页面和重复查询不会重发。需要重试时点击“重新生成”，产生新的操作并关联前次 ID。HTTP 结果未知时先读回课程／页面和持久回执。既有答案与首次基线不会被恢复操作改写；内容改变仍按 I4／I5 报告漂移或未知关联。

## 准备课程与交接结果

外部 Agent 先按 [课程准备工作单](PREPARATION.md)整理来源、学习目标和参考题，经审校后交付。资料到达工作区不会自动成课，也不会自动归档知识库。

### E1 作者整书交付

已审正文使用 `author-block` 原样写入，再用 `author-plan` 从实际页块生成计划，最后调用 `complete-authored-book`。这些步骤不代替 I4，也不能把普通块 ready 当作整书完成。部署必须显式配置匹配 E1 发行物的 `authoredDeliveryBuild`；接入工具会核对固定补丁和实际作者模块字节。


```powershell
& $learnPython -X utf8 -B -m tools.learning_book.cli author-block --activity <activityId> --request-id <新的请求ID> --deployment <隔离deployment.json> --state-dir <隔离state> --page-id <pageId> --operation insert --body-file <已审正文.md> --budget-context <隔离预算.json> --knowledge-preparation <已审connection.json> --expected-revision <当前revision>
& $learnPython -X utf8 -B -m tools.learning_book.cli author-plan --activity <activityId> --deployment <隔离deployment.json> --state-dir <隔离state>
& $learnPython -X utf8 -B -m tools.learning_book.cli complete-authored-book --activity <activityId> --request-id <新的请求ID> --deployment <隔离deployment.json> --state-dir <隔离state> --plan <上一步plan.json> --budget-context <隔离预算.json> --knowledge-preparation <已审connection.json> --expected-revision <当前revision>
```

丢失响应时使用原 `requestId` 执行 `reconcile`，不得换 ID 重发。首次 I4 后纠错使用 `create --replacement-of <旧activityId>` 创建替代 activity/book，保留旧题、作答、基线和 I5，不原地重绑。补丁与隔离证据见 [E1 说明](../../patches/deeptutor/e1-authored-delivery/README.md)。

### 受控学习扩展（release-21 机制）

未审 AI 文本／提示／深入学习建议块可删除和重生成，删除建议块时保留已生成子页；个人笔记可删除。原正文、原题和扩展 quiz 不开放该入口，整书重建与整页重生成继续保护。操作使用原请求重放、关联重试和目标摘要保护。冻结完整组合回归在 release-21 定版时实际通过（226 次执行／223 项不同检查），真实 HTTP 只读核对通过；该计数对应当时环境，不表示当前部署状态。生命周期修复与部署报告属本机验收证据，不随本仓库发布。新增内容仍为 `unreviewed`，I5 历史 `history=partial` 限制不变，不声称新的独立复审、正式内容审查或用户掌握。

`release-19` 的真实推荐、自定义深入学习和 I4／I5 历史结果见真实验收报告（未随公开仓库附带），不覆盖本版修改。

受管课程使用独立扩展路由和权威 journal，不删除 `question_content_protected`；普通原生正文／旧题修改仍拒绝。新增内容使用新块、新 question ID 和显式 `unreviewed` 状态，成功提交即保存，可以阅读和练习，但不冒充正式内容审查通过。

部署候选必须配置与实际扩展模块匹配的 `extensionBuild`。`append-extension` 同时需要知识准备和原题附件，服务端会核对同一来源投影：

```powershell
& $learnPython -X utf8 -B -m tools.learning_book.cli append-extension --activity <activityId> --request-id <新请求ID> --deployment <隔离deployment.json> --state-dir <隔离state> --page-id <pageId> --extension-id <新扩展ID> --blocks <严格块数组.json> --budget-context <隔离预算.json> --knowledge-preparation <已审connection.json> --question-preparation <原题附件.json> --expected-revision <当前revision>
```

候选生成在正式 pages 枚举之外完成，随后短提交。生成失败或响应不完整保持 uncertain，按原 requestId 检查，不换 ID 重发。revision 冲突则通过 `/books/retry-extension` 显式关联原候选，以新提交请求复用候选字节，不重新生成。个人笔记走独立窄写入规则；深入学习子页、spine、父链接、主题映射和 Book 计数由同一提交恢复。扩展后的检查与 `/3` 交接见 [I4 基线](BASELINE.md)和[补丁说明](../../patches/deeptutor/controlled-extension/README.md)。当前证据与阻塞见本轮交接（未随公开仓库附带）。

学习前完成内容审查和 I4 基线；网页负责阅读、选择题、追问及位置恢复。聊天保留原文，并显示按 Unicode 字符实计、排除空白的原文字符数；这不是 token 数，也不把模型自称的字数当实测值。

学习后按 [交接手册](HANDOFF.md)导出所选会话，再离线核验：

```powershell
& $learnPython -X utf8 -B -m tools.learning_book.cli export-results --activity <activityId> --export-id <新的导出ID> --deployment .learning-book-runtime/local/deployment.json --state-dir .learning-book-state/local --sessions-file selected-sessions.json
& $learnPython -X utf8 -B -m tools.learning_book.cli verify-handoff --package <返回的包目录>
```

导出成功表示声明范围的数据交付，学习完成与掌握程度仍按实际证据表达。来源原文默认 external，资料包应独立保留；正式知识沉淀继续遵循 ingest／approve。

## 备份及恢复

先停服，再备份到一个尚不存在的目录：

```powershell
& $learnPython -X utf8 -B -m tools.learning_book.local_backup backup --config $learnConfig --target .learning-book-backups/<新的备份名>
& $learnPython -X utf8 -B -m tools.learning_book.local_backup verify --package .learning-book-backups/<备份名>
& $learnPython -X utf8 -B -m tools.learning_book.local_backup restore --package .learning-book-backups/<备份名> --target .learning-book-data/<新的恢复目录>
```

备份覆盖 runtime、项目 state、控制库及实际文件摘要。控制器锁不复制；原文若在这些目录之外，需要另行备份。备份含本机设置和教学记录，保存在本机私有目录。

恢复只复制和核验，不立即启动。恢复副本中的旧配置仍指向原路径，必须用 `local_install` 显式重新绑定，传 `--control-from <恢复目录>/control` 以继承原控制库的累计 floor 和未结算调用。runtime 为 `<恢复目录>/runtime`，project-state 为 `<恢复目录>/state`，新 control 可为 `<恢复目录>/controller`。原实例先停服，复用同一部署端口、身份与语料作用域；观察副本可先禁用模型。不要直接运行备份内的旧 runtime.json。

## 安装、升级与回退

发行依据见 [收尾补丁清单](../../patches/deeptutor/closeout/README.md)。重新安装分为源码核对、构建、依赖安装、模块安装、数据接入五步。普通启动使用已构建的生产资产，不现场运行 npm build。

新本机安装先创建 Python 3.12 venv，按 `dependencies.lock` 安装固定依赖，再安装清单中的八个同版本 wheel；执行 `pip check`。Node 使用已验证的 22.23.4。新数据目录可用原生 `deeptutor init --non-interactive` 初始化；已有数据先停服并精确备份。

使用 uv 缓存安装 Python 依赖时必须加 `--link-mode copy`。缓存硬链接虽字节相同，仍可能被上游 pathsec 拒绝，已实际导致新课程的 NLTK stopwords 索引读取失败；安装接入会提前检查依赖实体化。已有环境先停服，把链接文件按原字节复制为独立文件后再恢复索引，不放宽安全检查。

接入命令的完整参数由 `python -m tools.learning_book.local_install --help` 列出：runtime、project-state、全新 control、Python 基础解释器、site-packages、Node、standalone Web、部署、原预算、context-id 和八个 `--wheel`。接入时核对全部安装字节及网页资产，迁移沿用全部历史调用，另记新的控制身份。由实际运行账号初始化和执行，不能混用 sandbox 账号创建的私有设置。

本次原 I6 runtime／state／venv 均保留，用于回退核对。回退运行必须先停止新实例；后续若已发生学习或模型调用，先备份最新数据并核对旧版本兼容性及累计用量，不能直接把旧备份当最新数据运行。
