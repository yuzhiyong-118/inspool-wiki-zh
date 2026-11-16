# 学习资料交付、内容基线与只读学习交接（I3–I5）

题目能力Q1／Q2已按原范围交付，Q3小样本后的三项缺口已修复并通过限定复审（未随公开仓库附带）。147项不同检查通过（17新增），[新补丁](../../patches/deeptutor/q3-fix/README.md)覆盖受管工具禁用、健康只读与流式计量／重启门禁，原三份Q3课件和六份包只读回验通过。操作见[题目生产手册](QUESTION_PRODUCTION.md)。固定八模块尚未升级日常实例，旧课不自动迁移；完整新课仍需E1。下次模型调用前，须接续Q3新增用量（见本机账本），原账本未自动归并。
题目能力Q1／Q2已按原范围交付，Q3小样本后的三项缺口已修复并通过限定复审（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3-fix/README.md）。147项不同检查通过（17新增），[新补丁](../../patches/deeptutor/q3-fix/README.md)覆盖受管工具禁用、健康只读与流式计量／重启门禁，原三份Q3课件和六份包只读回验通过。操作见[题目生产手册](QUESTION_PRODUCTION.md)。固定八模块尚未升级日常实例，旧课不自动迁移；完整新课仍需E1。下次模型调用前，须接续Q3新增用量（见本机账本），原账本未自动归并。

日常运行从 [本机使用手册](LOCAL_USE.md)开始；外部 Agent 按 [课程准备工作单](PREPARATION.md)操作。正式启动／状态／停止、预算门禁、安装接入与备份恢复分别位于 runtime.py、runtime_guard.py、local_install.py、local_backup.py，运行底座需要固定 DeepTutor 发行物。收尾证据见 验收记录（未随公开仓库附带）。
日常运行从 [本机使用手册](LOCAL_USE.md)开始；外部 Agent 按 [课程准备工作单](PREPARATION.md)操作。正式启动／状态／停止、预算门禁、安装接入与备份恢复分别位于 runtime.py、runtime_guard.py、local_install.py、local_backup.py，运行底座需要固定 DeepTutor 发行物。收尾证据见 验收记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-closeout/README.md）。

把已准备好的 UTF-8 Markdown／纯文本交给 DeepTutor HTTP 服务，留下可核验的语料、请求和活动映射。只使用 Python 标准库；不 import DeepTutor，不需要其 venv、私有探针或运行目录。建议 Python 3.11–3.14；后端固定为 DeepTutor 1.7.2、提交 `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`。

上游拥有可编辑课程、答案和进度；本模块保存不可变历史内容证据和生产／审查回执，不维护可写 progress、得分或掌握度，不自动确认下一阶段、编译课程或写正式知识库。`confirm-spine` 始终提交 `auto_compile=false`，READY 概览和 pending 内容页按实际状态记录，成功回执不代表课程已发布。

## 文件与入口

| 文件 | 职责 |
| --- | --- |
| `contracts.py` | 严格 JSON、稳定身份、原文与投影 hash、资料路径验证 |
| `evidence_store.py` | 原子文件、不可变证据、OS 文件锁、回执与活动映射 |
| `deeptutor.py` | 唯一 HTTP 适配，multipart、二进制读回、固定响应包装 |
| `budget.py` | 只读累计用量账本、独立监控、受控实例停止 |
| `runtime_guard.py`／`runtime.py` | 全服务监督租约、调用前门禁、唯一 call_id 归因、受管进程生命周期 |
| `local_install.py`／`local_backup.py` | 发行字节核对、明确接入、停服备份、隔离恢复 |
| `production.py` | `Production` 的普通应用操作，CLI／未来 Web／MCP 共用 |
| `content.py` | I4 有版本的内容投影、结构检查与保守资源依赖识别 |
| `baseline.py` | I4 `Baseline` 只读采集／复核／外部审查与首次绑定 |
| `learning_state.py` | I5-A 严格学习状态响应／读者作用域验证，不重建历史记录 |
| `records.py` | I5-B 原始作答观察、作用域 key、冲突、条件复核与首次绑定时间门禁 |
| `conversations.py` | I5-C 所选公开会话、作用域／父子／分支、规范事件及落盘前隐私门禁 |
| `read_limits.py` | 全窗口共用并持久化的 HTTP／消息／事件／字节限额，只读后端 |
| `handoff.py` | I5-D/E 有界窗口、原字节搬运／不可变包、离线校验和恢复 |
| `cli.py` | 参数、UTF-8 JSON 输出及退出码 |

Python 使用方式：构造 `EvidenceStore(state_root)`、`DeepTutor(load_deployment(config_path))`、可选 `Budget`，传给 `Production`。应用方法为 `publish_learning_inputs`、`create_activity`、`confirm_proposal`、`confirm_spine`、`prepare_quiz`、`inspect_receipt`、`reconcile_request`；纯校验直接用 `contracts.validate_package`。无模型操作不需要 Budget。

I6 实际集成增加显式 `recover_inputs(request_id)`／`recover-inputs`。原语料发布为 uncertain，且建库和上传完整响应均已保存时，可在确认旧索引终止后重建该 KB 索引。先核对成员及原字节，保存独立 kb-reindex 请求／响应，使用新索引任务验证，保留原 uploadTaskId。该操作需要有效累计预算，完成重放和只读 reconcile 复用既有事实。原索引仍在运行、原文变化或上传响应缺失时拒绝恢复。未知重建结果按原 dispatching 记录处理。

I5-A 的 `DeepTutor.read_learning_state(book_id)` 仅访问严格 GET，返回经能力／读者作用域验证的原始 HTTP Response，不补 Progress 默认值。须有独立 `learningStateReadBuild`，见 [部署样例](examples/deployment-i5.json) 与 [补丁说明](../../patches/deeptutor/i5/README.md)；构建标识不改变 I3 scope digest。authenticated 同时核对 profile 与实际 actor，匿名 owner 是配置标签。缺能力／404／身份冲突拒绝关联，零旧 Book GET 回退。

`LearningRecords.observe_records(...)` 仍只作进度观察，详见 [RECORDS](RECORDS.md)。完整交接使用 [HANDOFF](HANDOFF.md) 中的 `Handoff.export_learning_results(...)`／`verify_handoff(...)` 及 export-results／verify-handoff 两 CLI；A～E 已完成，174 项项目测试及实际路由／存储验收（未随公开仓库附带）通过。原记录不覆盖，缺时间／基线／来源依据保持 unknown；真实安装和生产学习集成留 I6。
`LearningRecords.observe_records(...)` 仍只作进度观察，详见 [RECORDS](RECORDS.md)。完整交接使用 [HANDOFF](HANDOFF.md) 中的 `Handoff.export_learning_results(...)`／`verify_handoff(...)` 及 export-results／verify-handoff 两 CLI；A～E 已完成，174 项项目测试及实际路由／存储验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）通过。原记录不覆盖，缺时间／基线／来源依据保持 unknown；真实安装和生产学习集成留 I6。

## 资料包

完整例子见 [prepare.json](examples/package/prepare.json) 和 [lesson.md](examples/package/lesson.md)。原文和输入投影可以指向同一份字节，角色和身份仍分别保存。

- `sources[]`：`sourceId/sourceVersionId/sha256/path/metadata`；metadata 可含 `title/author/externalUrl/license/capturedAt`。原文允许本地只读的包外定位；URL 单独存在不满足原文留存。
- `inputArtifacts[]`：`inputArtifactId/sourceId/sourceVersionId/sha256/path/mediaType/extraction/coverage`；只接受包内相对路径，含符号链接／junction 的解析结果也不能越界。每包 1–16 个投影，首期每个 sourceId 选择一个原文版本。上游 Book DTO 虽接受 32 个 source_refs，直接文件 grounding 只取前 16 个，因此本期在上传前限为 16 个，更多资料由生产者分包。
- `extraction` 为 `method/version`；`coverage` 为 `status/truncated`，可加短 `note`。只接受 `complete` 和 `truncated=false`；UTF-8 校验不对原文二进制做强制转换。
- `corpusId/corpusVersionId` 冻结集合；`learningGoal/language/depth` 为建议教学目标与生成参数，默认值明确规范化为 zh/brief。目标不是语料成员摘要。

校验后在内存固定实际上传字节。路径移动不改变身份／摘要；新正文须使用新来源版本、提取物 ID 和语料版本。不同作者／来源即使内容相同，也保留独立身份。跨请求核对版本冲突，不允许把旧 ID 原地换内容。

回执记录上游已知限制：每份直接文件摘要最多 4,000 字符、所选文件上下文最多 80,000 字符，记录投影字符数及超限提示。这些是源码上限，不能证明模型实际读到了完整来源；实际上下文覆盖仍记 unknown。KB 留存及索引完整，与模型使用完整是不同事实。

```powershell
python -B -m tools.learning_book.cli validate --package tools/learning_book/examples/package/prepare.json
```

校验、上传不改包内文件。原文在 create 和确认步骤发送前重新核对；移动资料后，可用同语料包重新运行 `publish-inputs` 更新独立 locator 观测，原语义请求不改写。

## 部署与预算

[deployment.json](examples/deployment.json) 是配置样例，需绑定实际部署／owner／workspace。仅接 loopback HTTP。General 明确写 `workspaceId:""`。匿名实例使用 `configured_single_user`，是受控配置绑定，不是服务端认证证明；认证部署使用 `authenticated`、`tokenEnv`，以 profile 的 `id` 核对 owner，失败不退回匿名。

首期新建当前账户资源库下的专用 KB，记录实际 `account:kb:…` 引用，不向 KB 请求附 Book workspace。相同账户语料可跨 Book workspace 复用，书的活动映射仍绑定指定 workspace。部署 URL／身份配置变化需明确处理，不能按标题迁移旧映射；配置无法自动辨认同端口后端被重装，重建 runtime 应使用新 deploymentId。

模型／索引写操作需操作者提供有效 `--budget-context`。额度配置由可信操作者提供，不能由资料包或模型自行放宽。本次实现没有使用任何真实模型额度，I2 的旧额度已结案。预算文件示意如下，数值是格式例子，不是新的执行授权：

```json
{
  "contextId": "本次已授权额度的稳定ID",
  "scope": {"此处替换为完整 BackendScope 对象": "从 load_deployment(...)[scope] 获取"},
  "ledger": "实际绝对路径/usage.sqlite3",
  "baselineCallIds": ["本次授权前已有的call_id"],
  "pauseAt": 800,
  "limit": 1000,
  "pollSeconds": 1,
  "maxSilentSeconds": 120,
  "localEmbedding": {"provider": "ollama", "metering": "not_available"},
  "stopProcess": {
    "processId": 12345,
    "executable": "实际server进程的完整可执行文件路径",
    "startedToken": "实际创建时间标识",
    "ownership": "dedicated_single_worker"
  }
}
```

可用只读 `process-identity --pid <实际serverPID>` 获取身份；选择实际服务进程，不能直接拿 venv launcher 的 PID。启动生产操作前会再次核验可执行文件、创建时间、子进程及目标端口的 OS 监听归属。首期只支持独占单 worker，Windows 只放行其刚启动的系统 conhost，其他子进程树拒绝执行；Linux 停止用 pidfd，其他平台未实现停止控制时拒绝真实模型操作。不启动、接管或终止用户的 Ollama／Web／其他服务。

账本通过只读 SQLite `llm_calls(call_id,usage_json)` 读取。输入＋输出计量、reported/estimated 分开，缺失／无效用量、账本回退或丢失、在途超过暂停线／静默期限均禁止新增调用。不同确认步骤必须使用创建时同一个额度 context，基线和额度不可在 CLI 间清零，已计量行持久核对。重启后可更新经核验的 server PID，其余额度语义不变。本地 embedding 单列配置及“计量不可用”，不编造零消耗。

监控在独立线程运行，停止关闭连接以外的实际服务进程；停止失败会明确留下 `stop_failed`。门禁触发后本地持久锁住该 context；需要操作者核对停止及授权后处理，不提供自动解锁／补额度命令。账本有延迟，供应商的在途调用仍可能计费，不能当成硬封顶。

## 完整调用顺序

以下是需要逐步明确触发的操作，非自动执行脚本；先复制／填写实际部署与已授权 budget 文件。服务由操作者另行启动，I3 不启动 DeepTutor。所有参与 Agent 共用一个私有 state-dir，资料包、回执、DT runtime-home 三者分开；示例 `.learning-book-state/` 已加入 Git ignore。

```powershell
python -B -m tools.learning_book.cli publish-inputs --package tools/learning_book/examples/package/prepare.json --request-id inputs-001 --deployment deployment.local.json --state-dir .learning-book-state --budget-context budget.local.json
python -B -m tools.learning_book.cli create --corpus-receipt inputs-001 --request-id create-001 --activity-id activity-001 --intent "理解示例中的重试约定" --deployment deployment.local.json --state-dir .learning-book-state --budget-context budget.local.json
python -B -m tools.learning_book.cli confirm-proposal --activity activity-001 --request-id proposal-001 --payload proposal-confirm.json --expected-revision 1 --deployment deployment.local.json --state-dir .learning-book-state --budget-context budget.local.json
python -B -m tools.learning_book.cli confirm-spine --activity activity-001 --request-id spine-001 --payload spine-confirm.json --expected-revision 2 --deployment deployment.local.json --state-dir .learning-book-state --budget-context budget.local.json
python -B -m tools.learning_book.cli show --request-id create-001 --deployment deployment.local.json --state-dir .learning-book-state
python -B -m tools.learning_book.cli reconcile --request-id create-001 --deployment deployment.local.json --state-dir .learning-book-state
```

示例中的 1、2 是常见 revision，必须使用上一回执的实际值。`--payload` 文件只存 edited proposal／spine 对象；存 JSON `null` 表示明确确认上游当前产物。`artifactRef` 指向原始阶段响应，其中的 proposal/spine 可供编辑，不要求把整份 HTTP 包装当 payload。

`--corpus-receipt` 接收成功发布返回的 `corpusReceiptRef`（请求 ID，不是 JSON 文件路径）；复用语料时可能返回已有 ID。`create --intent` 是实际目标，回执同时保存包的建议目标及覆盖关系。`--retry-of <失败请求ID>` 仅用于明确无副作用失败后的新请求；不能越过不确定结果或已有活动映射。

正常输出包含 `operation/requestId/status/receiptRef/activityRef/errors/nextAction`，按需带 `bookId/revision/corpusReceiptRef/artifactRef`。不把模型大正文打印在终端。退出码：

| 码 | 意义 |
| --- | --- |
| 0 | 已知成功／校验通过 |
| 2 | 输入／配置不合法 |
| 3 | 身份、版本、请求或映射冲突 |
| 4 | 单写者占用 |
| 5 | 明确失败，不能隐式重发 |
| 6 | prepared/dispatching/uncertain，需按 nextAction 继续或核对 |
| 7 | 已知事实仍保留，但远端缺失或核对不完整 |

## 回执与恢复

```text
state-dir/
  locks/production.lock           # OS 锁，全项目单写者，崩溃自动释放
  requests/<hash(requestId)>/
    request.json                  # 不可变语义请求／digest／审计
    locators.json                 # 发布输入的当前位置观测，可移动
    inputs/<稳定文件名>           # 发布时冻结的投影字节
    stages/<stage>/
      request.json / request.bin
      dispatching.json
      response.bin / response.json
    receipts/<receiptId>.json     # 不可覆盖的历史
    receipt.json                  # 当前原子发布指针／内容
    observations/                 # 只读核验与预算诊断
  activities/<hash(activityId)>.json
  budgets/                        # 额度绑定、累计位置和停止锁存
  index.json                      # 派生视图，可重建
```

首期主动采用比“每个 scope 一个写者”更严格的**同 state-dir 一个写者**，避免同活动跨部署竞争时各建一本书。不同 state-dir 不能提供相互排他，不应给同一项目另开一套状态根来规避冲突。OS 文件锁和本地原子替换面向本机文件系统，网络共享目录不在验证范围。

相同请求 ID＋相同有效输入返回原回执，不重复写上游；不同输入冲突。活动成功、prepared 或 uncertain 时都不能换 ID 重建。来源／语料版本也检查跨请求冲突。临时文件同卷写入并 fsync，不可变文件用完整文件原子发布，映射不可重绑；不承诺跨远端事务或断电全保证。

- prepared 且没有 dispatching：补齐有效执行上下文后可重跑原操作。
- dispatching 且缺完整响应：uncertain，不重发，即使实际可能尚未送达。
- 成功响应已落盘：reconcile 可恢复本地回执／映射，不重新 POST；再用安全读取核对远端存在性。
- 超时、断线、5xx、损坏响应：uncertain。确认 payload 的 400 可能已推进 revision，不把它当零副作用。
- 明确失败返回原失败；确需重试使用显式关联的新请求。上游 revision 409 不自动刷新并重放。
- 未知 bookId：`--candidate-book-id` 只存候选核对记录；公开 API 不能证明精确输入归属时保持 uncertain，不按同名或时间近认领。
- 已绑定书被删：保留映射和证据，报告 missing，不补建书，也不删除远端补偿。

`show` 默认零 HTTP；`show --rebuild-index` 从记录重建索引。`reconcile` 可以调用 profile、书列表、spine/page 或 KB 文件／indexing-run 等安全读取，绝不 GET `/api/books/{id}`，因为该接口可能恢复生成。成功语料还须精确匹配成员、原始下载字节、上传任务 ID、document source_hash 和 usable_version；preview／parser ready／HTTP 200 都不足以放行。

凭据只从环境引用进入 HTTP 头，不保存认证头；已知 token 若被服务端回显会去敏，另保留原 wire hash 并标明 redacted，不能把去敏字节当原始文件核验成功。receipt/status 仅描述交付事实，不写教学掌握度。

## 验证

I4 内容基线的调用、投影和限制见 [I4 使用说明](BASELINE.md)；补丁构建见 [DeepTutor 补丁](../../patches/deeptutor/README.md)。I3 的生产回执和下面的历史验收保持独立。

```powershell
python -B -m unittest tools.tests.test_learning_book_i3 -v
python -B -m tools.tests.run_learning_book_i3 --output docs/design/evidence/learning-book-i3
```

测试使用独立临时资料、真实 loopback HTTP 假服务、实际子进程退出／锁竞争、实际指定实例停止，以及去敏 I2 响应回放。产品不 import 测试／文档／私有验证目录。验收范围与未覆盖项见 I3 验收（未随公开仓库附带），阶段要求见 [任务书](../../docs/design/learning-book-i3-plan.md)。
测试使用独立临时资料、真实 loopback HTTP 假服务、实际子进程退出／锁竞争、实际指定实例停止，以及去敏 I2 响应回放。产品不 import 测试／文档／私有验证目录。验收范围与未覆盖项见 I3 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i3/README.md），阶段要求见 [任务书](../../docs/design/learning-book-i3-plan.md)。
