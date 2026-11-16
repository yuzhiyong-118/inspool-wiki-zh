# 学习交接包与外部 Agent 消费（I5）

I6 已完成真实部署、原生学习、独立恢复及交接消费的限定范围验收，见 最终报告（未随公开仓库附带）和 真实包（未随公开仓库附带）。本地消费示例见 候选（未随公开仓库附带），实际运行补丁见 [I6 清单](../../patches/deeptutor/i6/README.md)。
I6 已完成真实部署、原生学习、独立恢复及交接消费的限定范围验收，见 最终报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/acceptance.md）和 真实包（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/handoff/handoff.json）。本地消费示例见 候选（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/consumer-candidate.md），实际运行补丁见 [I6 清单](../../patches/deeptutor/i6/README.md)。

`Handoff.export_learning_results(...)` 只读取上游课程／学习记录／所选公开教学会话，输出不可变 `learning-handoff/1` 包。`verify_handoff(...)` 只做本地校验，不连接服务、不访问原 state 或原文定位。上游是唯一可写学习状态；本模块不回放答案、不生成课程、不修改正式 raw/wiki，不自动 ingest/approve。

I5 本地／HTTP 验收已完成，见 最终证据（未随公开仓库附带）。真实部署还需 I6 核对安装的补丁／发行物和实际 I3 活动／语料回执，不能把裸 bookId、合成样例或 I2 旧用量额度当生产授权。
I5 本地／HTTP 验收已完成，见 最终证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）。真实部署还需 I6 核对安装的补丁／发行物和实际 I3 活动／语料回执，不能把裸 bookId、合成样例或 I2 旧用量额度当生产授权。

## 命令与普通应用方法

立即离线查看合成正常包与 partial 包，无需部署配置：

```powershell
python -B -m tools.learning_book.cli verify-handoff --package docs/design/evidence/learning-book-i5/validated/handoff/examples/normal
python -B -m tools.learning_book.cli verify-handoff --package docs/design/evidence/learning-book-i5/validated/handoff/examples/partial
```

实际使用时由操作者提供已核验部署和有效 I3 activity：

```powershell
python -B -m tools.learning_book.cli export-results --activity <activityId> --export-id <本次新ID> --deployment deployment.local.json --state-dir .learning-book-state
python -B -m tools.learning_book.cli export-results --activity <activityId> --export-id <另一次新ID> --deployment deployment.local.json --state-dir .learning-book-state --sessions-file selected-sessions.json --clock-assumption clock.json --completion-declaration completion.json
```

可选 `--snapshot-id`、`--collection-declaration`、`--limits`；无模型操作不需要 budget-context。`--limits` 仅允许可信操作者收紧默认限额。`--snapshot-id` 是比较候选，不替换首次绑定；省略时采用实际 accepted binding，没有基线也可取回原记录。时钟假设格式见 [RECORDS](RECORDS.md)，没有声明默认历史关联 unknown。

Python 使用 `Handoff(EvidenceStore(state_dir), DeepTutor(load_deployment(config))).export_learning_results(activity_id, export_id, ...)`；纯本地 `verify_handoff(package_dir)` 与 CLI 共用同一函数，不 import 上游包或旁读其 runtime/SQLite。

export-results 的 status=succeeded／退出码 0 表示本次声明范围的记录交付，**不表示课程通过或学习完成**。partial／退出码 7 可能有有效部分覆盖包，也可能仅有 diagnosticRef、artifactRef=null：后一种不能伪装成可消费的空学习包。verify-handoff 对有效 partial 包退出 0，因为验证结果和数据覆盖是两个维度；JSON 中 resultStatus 保留 partial。

相同 exportId／相同语义输入返回已验证的历史包，零 HTTP；新观察须用新 ID。输入冲突拒绝，不覆盖历史；包丢失或损坏不能靠旧成功回执通过。读取不额外弹批准窗口，也不会触发正式知识归档。

## 包与字节关系

| 文件／目录 | 用途 |
| --- | --- |
| `handoff.json` | 作用域、构建、覆盖、完成声明、限额、来源与基线映射、当前检查引用 |
| `records.json` | 原始作答、稳定 key／legacy、全部 raw occurrences、原判分与条件复核、保守绑定 |
| `conversations.json` | 明确选择的公开会话、父子／分支、预览与规范事件、附件引用、边界复核 |
| `request.json` | 本次语义输入与摘要；不绑定当前机器绝对路径 |
| `wN/` | 各轮内容／资源、原始进度与公共会话响应、当次检查；最多三轮，不跨轮拼完整状态 |
| `prior-rounds.json` | 若有失败前轮，单列其实际观察；同 submission key 的前轮冲突仍阻止末轮历史关联 |
| `baseline/fN.bin` | I4 快照／资源／capture request／binding／review request 的**原字节**，由新 refMap 解释 |
| `manifest.json`／`complete.json` | 全文件清单与 hash，最后写完成标记后整目录原子发布 |

原记录中恰好名为 rawRef 的字段仍是来源内容，不改写。仅新的交接包装引用指向包内位置；旧 I4 JSON 的路径字段保留原字节，不改路径后冒称 hash 未变。离线 verifier 核对完整目录、SHA、原始 JSON pointer、作用域、搬运快照／绑定／审查链和保证级别；schema 见 [契约](schemas/learning-handoff.schema.json)。Schema 结构通过不能取代字节和引用校验。

来源原文默认不复制，`sourceRetention=external`、`sourceOriginalsVerified=false`。缺原文不能声称核验了事实或已有源材料备份。附件也只保留公开引用，不沿 URI 下载；完整交接包自包含的是**内部学习证据**，不是全部源材料。

### 受控扩展与 `learning-handoff/3`（候选）

首次基线后存在合法扩展时，包升级为 `learning-handoff/3`。`extensionEvidence` 指向当次原始扩展证据，包含连续内容序号、前驱提交摘要、前后受保护内容摘要和实际 revision 边界；revision 跳号本身不等于内容链断档。离线 verifier 从首次快照有界重放至当前内容，检查链完整、逐题关联及 `unreviewed` 状态，缺文件、缺中间提交、分叉、篡改和降级均拒绝。

旧题继续使用 `baseline_consistent`；新题使用 `extension_consistent` 并携带所属 commitDigest 和 `qualityReview=unreviewed`。这表示扩展内容可关联，不表示正式审查通过、提交时版本证明或用户已掌握。个人笔记不作为受保护正文重放，但也不得借笔记类型掩护正文变化。普通 GET 使用轻量稳定屏障，I4／I5 才执行完整重放；当前上限 1,024 次提交、32 MiB 链证据，超限明确诊断而不截断。旧 `/1`、`/2` 包按原规则读取，不原地改写。候选验证范围见扩展证据（未随公开仓库附带）。
旧题继续使用 `baseline_consistent`；新题使用 `extension_consistent` 并携带所属 commitDigest 和 `qualityReview=unreviewed`。这表示扩展内容可关联，不表示正式审查通过、提交时版本证明或用户已掌握。个人笔记不作为受保护正文重放，但也不得借笔记类型掩护正文变化。普通 GET 使用轻量稳定屏障，I4／I5 才执行完整重放；当前上限 1,024 次提交、32 MiB 链证据，超限明确诊断而不截断。旧 `/1`、`/2` 包按原规则读取，不原地改写。候选验证范围见扩展证据（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-controlled-extension/README.md）。

## 选择、稳定性与限额

显式会话文件：

```json
{"schema":"learning-session-selection/1","sessions":[{"sessionId":"实际ID","bookId":"实际书ID","pageId":"实际页ID"}]}
```

只取当前读者映射和明确选中会话，双向校验 book/page/workspace；不扫描全部 sessions，不调用 threads/backfill、hint 或 migration。所选会话读完也不等于全部历史，historyCoverage 始终 partial、allHistoricalSessions unknown。旧消息只能导出公开预览时明确 partial；不能用空 events＋complete=true 覆盖旧历史。

每轮在整个窗口两端取内容／资源，中间读取进度、公开会话和分页事件，再核对进度／会话全文／所有事件页和基线证据。固定数量／更新时间不遮掉内容变化；最多三轮，共用预算，网络错误没有隐式重试。全局 OS 锁只协调本项目，不把协作声明当上游事务锁；ABA、另一个客户端实际显示和独立作答仍未证明。

默认上限：32 次会话选择读取、10,000 条消息、50,000 条公开事件、100 次事件分页、512 次 HTTP；单响应最高 64 MiB，总响应及最终包分别最高 256 MiB。重读和重试共享计量；已完成请求计量持久化，进程中断在未知传输点时 pendingRequest 阻止同 export 继续假称预算准确。最终包在发布前对全部文件精确计量；中断后已计入的完整包构建也不清零。私有尝试目录不是已发布包，不承诺其大小等同最终包限额。

实际发现上游公共 events 可能带私有模型 metadata。项目在落盘前拒绝整份含私有结构／已知凭据回显的响应，只保留安全错误和 wire hash，明确未捕获；不把去敏字节冒充原文。普通公开记录保持原字节。构建标识是操作者的配置绑定，不是服务器签名证明。

## 完成声明与外部 Agent 提示词

collection/completion 声明可选，分别使用 `learning-collection-declaration/1`、`learning-completion-declaration/1`，字段须含 attributedAuthor、submittedBy、实际 scope、declaredAt、statement、provenance。user 角色文字不等于认证；Agent 转交保留两方身份，保证级别固定 operator_supplied。结束声明后仍看到更晚的记录，保留声明和 laterActivityObserved，currentCompletion 仍 unknown；不从 READY／score 推断结束。

可交给消费者的提示词：

> 先用 verify-handoff 离线校验此学习包，再读取 handoff.json、records.json 和 conversations.json。区分原始观察、条件复核、用户声明和覆盖限制；保留冲突、null、unknown 和 prior-rounds，不把 score／自评当掌握证明。仅使用包内真实 rawRef／JSON pointer，并经 refMap 解释旧 I4 证据。来源原文若 external／缺失，明确未核验事实。不要回放答案、补写进度、调用生成或直接归档 wiki；可以据已有本地知识与可核对原文提出回顾／知识候选，正式 ingest/approve 仍按知识库规则由用户触发和确认。

实际验收平台为 Windows／Python 3.12、固定 DeepTutor SQLite／单 worker 形态；PocketBase、多 worker、共享网络目录及真实学习生产集成均未因此通过。I2 的课程忠实性和原生首答 500 等已知限制保留，I5 不修复它们。
