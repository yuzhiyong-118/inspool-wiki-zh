# I4 详细任务书：学习前内容基线与核验

> 公开设计摘编：保留通用契约与方案；历史验收、用户反馈、运行记录及本地素材不随仓库发布。设计条目不代表部署或验收完成。
日期：2026-11-10。状态：**I4-A～E 已实现，本地／HTTP 契约通过，真实部署集成待 I6**，见 I4 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）及 [使用说明](../../tools/learning_book/BASELINE.md)。上游最小补丁已在隔离副本应用、重新构建并测试，未安装到既有 I2 服务；模型／embedding 调用为 0，I2/I3 历史证据未覆盖。上一阶段为 I3 本地／HTTP 契约通过（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i3/README.md），真实适配写入仍待集成。

总体边界沿用 [总任务书](learning-book-implementation-tasks.md)、[D2](research/upstream-learning/design-convergence/D2-data-and-handoff-contract.md) 和 [D3](research/upstream-learning/design-convergence/D3-first-learning-scope.md)。开工依据保留在 设计核对记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4-design/README.md）及源码 hash；下文为阶段验收标准，实际通过范围及资源限制以 I4 报告为准。不重跑 I2，不把旧预算恢复为可用。

## 1. 目标与阶段边界

在上游完成课程生成后，项目保存一份**不可编辑的历史内容证据**：用了哪个活动／语料、实际页面／题目／资源是什么、读取是否稳定、支持哪些题型、质量由谁检查过、未来记录最多能绑定到什么程度。

| I4 实现 | 继续后置 |
| --- | --- |
| 无生成副作用的完整内容读取，以及必要的最小上游补丁 | 自动编译、补题、模型重试、第二个 BookEngine |
| 有版本的内容投影、完整页面枚举、依赖资源清单及字节 hash | 通用网页抓取器、任意 HTML／脚本依赖打包器、离线课件播放器 |
| 有限复读、一致性边界、不可变候选快照及核验记录 | 严格事务快照、提交时内容 hash、独立掌握证明 |
| 选择题结构检查、失败占位识别、外部质量审查回执与基线绑定 | 自动判定所有教学结论正确、模型书面批改 |
| CLI 与普通应用操作，给 I5/I6 明确的输入／门禁 | 学习结果导出、门户、MCP Server、正式知识归档 |

I3 的 lazy 页面壳不能直接成为 I4 基线。I4 不负责把它编译完成；可在离线／HTTP 假服务和既有真实响应上实现与验收，真实编译由后续有效额度下的 I6 编排承担。

## 2. 开工前必须关闭的读取缺口

### 2.1 已确认事实

1. 固定版本 `GET /api/books/{id}` 在返回 book/spine/pages/progress 前调用 `maybe_resume_on_open`。`include_blocks=false` 也不取消该调用。不能将其当无额度读取，不能依赖“上次看到 READY”消除并发状态变化的可能性。
2. `GET /api/books` 返回 manifest 与生成概况，没有完整页列表；spine/page GET 不恢复生成，但只凭 spine 及已知 pageId，不能证明枚举了全部存储页面。manifest.page_count 只能交叉核对，不能代替实际枚举。
3. `BookStorage.list_pages` 对无法读取／验证的 JSON **跳过后继续返回**。仅移除 GET Book 的 resume 调用，仍不能据 HTTP 200 宣称全部页面完整。
4. Book/Page/Block 的 READY 和 `source_quality.status=ready` 不等于题目生成成功或来源忠实。既有 I2 响应中，4 页／17 块均 READY，但 11 道题包含 1 道 `[Generation failed]`、答案 `N/A` 的占位题；另有非 choice 题。不得改旧响应来让 I4 通过。

### 2.2 选定的最小调整

**先补上游只读 `GET /api/books/{book_id}/content`，再接 I4 采集。** 保留现有整书 GET 的打开／恢复行为。新入口沿用同一 owner/workspace/书权限解析，不使用新引擎，不启动／恢复／取消任何生成，不写 progress/chat，也不调用生成服务。

拟返回契约：

```json
{
  "schema": "book-content-read/1",
  "book": {"实际上游 manifest 字段": "不捏造进度或来源"},
  "spine": {"实际上游 spine 字段": "完整返回"},
  "pages": ["全部实际页面，包含完整 blocks"],
  "generation": {"status": "ready", "working": false},
  "pageEnumeration": {
    "mode": "strict",
    "fileCount": 4,
    "returnedCount": 4,
    "errors": []
  }
}
```

该示意中的对象说明不是接口夹具；实际字段按固定模型返回。实现要求：

- 在存储层增加专用于此入口的严格枚举能力，保留旧 `list_pages` 行为。实际目录中应识别的每个 page JSON 都要成功解析、核对文件身份与 page.id/book_id，或报告不完整；不得继续静默丢页。异常仅返回安全标识／错误码，不泄露 runtime 绝对路径。
- 页面 ID 重复、引用页缺失、跨书混入、坏 JSON、读中删除等不能返回“完整”枚举。前后目录清单变化需明确报变化；具体诊断包装可实现时简化，但完整语义不可省略。
- `generation` 仅为观测。`working=false` 不证明没有其他客户端编辑或独立生成任务，仍需协作冻结与项目端复读。
- 不要求返回 progress、会话、答案记录；I5 另行采集。不为 I4 新增学习状态表。
- 适配器只把这个**确实存在且按契约验收的**新入口列入安全读取；404／旧响应／缺 schema／缺枚举诊断时停止。不能回退到旧 GET Book，也不能向旧接口随便附 `resume=false` 就认为有效——旧版本可能忽略未知 query 参数。

采用此入口是为了同时解决生成副作用、全页枚举和漏页诊断三个问题，不再并行保留“普通 GET＋预算守卫”或“直接读 DT runtime 目录”两条产品路径。

### 2.3 补丁与版本管理

- 原始提交仍固定 `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`。最小 diff、补丁 hash、测试和构建说明已保存到项目的 [patches/deeptutor](../../patches/deeptutor/README.md)，实际 wheel hash 见验收证据。
- 实施在隔离副本应用补丁，重新构建对应发行物。记录 base commit＋patch hash＋实际 wheel hash；不得直接手改已安装 wheel，或把补丁版本写成未修改的官方版本。
- Web 继续使用原固定提交；只读新增入口不得改变旧 Web 的行为。若原实现必须改 auth/存储模型或多个生成流程，先缩小补丁并回审，不扩成上游重构。
- 兼容的只读能力升级不重建活动、不改变部署数据身份；补丁／读取契约版本作为采集 provenance 保存，不能为了加版本字段让已有 I3 activity 映射失效。runtime 重建或身份变更仍按 I3 另行绑定。

**I4-A 的路由／存储测试未通过前，不推进完整基线采集，也不借临时通路把它标成完成。** 可以先做纯投影规则和夹具分析。

## 3. 应用操作与工程组织

沿用 `tools/learning_book/` 和同一个私有 state-dir，复用 I3 的 scope 核对、规范化 JSON、原子文件与 OS 单写者；不修改已确认的活动映射。

| 操作 | 拟 CLI | 结果 |
| --- | --- | --- |
| `capture_baseline` | `capture-baseline --activity … --capture-id … --snapshot-id … --purpose pre_learning/retrospective` | 不可变候选快照或明确的失败／不完整采集记录 |
| `check_baseline` | `check-baseline --activity … --snapshot-id … --check-id …` | 核对本地完整性及当前远端内容，生成独立检查记录，不改旧快照 |
| `record_baseline_review` | `review-baseline --activity … --snapshot-id … --review-id … --review-file …` | 记录外部审查；通过全部门禁且当前复核一致时绑定首次正式基线 |

各命令沿用 `--state-dir/--deployment` 和 UTF-8 JSON 输出／退出码。没有 HTTP 写／生成操作，不要求模型额度。没有自动生成、修复或额外用户确认弹窗；`review-file` 是准备者完成实际审查后提交的具体结果，可由用户或外部 Agent 提供。

建议最小文件边界：`baseline.py` 放采集／复核／审查应用操作，`content.py` 放投影／题目与资源描述；必要时在文件内合并小函数。HTTP 只读入口和 CLI 接入现有文件，不建设新的后端抽象或注册框架。

采集记录放独立 `captures/` 命名空间，快照放 `snapshots/`，审查／检查放对应证据目录，首次基线绑定为独立不可变记录。**不要把读操作塞进 I3 生产请求状态机**：读取失败没有“远端写入结果不明”的语义，也不能让一次失败采集永久占用活动、阻止生产方处理课程。

## 4. 内容投影与身份

规则版本拟为 `dt-book-content/1`；`content.json` 按 I3 canonical JSON 固定实际 UTF-8 字节，`contentDigest=sha256(该文件字节)`。不可只保存 digest，不以 revision、title 或页面数量代替内容。

| 内容 | 投影要求 |
| --- | --- |
| Book | id、标题、描述、proposal、语言／深度、来源／KB 指纹及内容有关的扩展字段 |
| Spine | 全部章节、顺序、目标、摘要、依赖、page_ids、source_anchors、概念图及有语义的扩展 |
| Page | 真实 id/book_id/chapter_id、标题／目标、内容类型、顺序、全部 blocks、links、parent_page_id |
| Block | id/type、标题、params、完整 payload、source_anchors、内容／导航有关的 metadata／扩展；不能只摘正文 |
| Quiz | 原始题干、类型、选项键和值、答案键、解释、难度等完整保留；诊断另列，不改写原题 |
| 来源映射 | 关联 I3 已有 production/corpus/sourceVersion/inputArtifact 与 hash，不凭书名或块的引用文本推断精确来源 |

剔除规则必须精确到已核对的模型位置，例如 Book/Page/Block 的 created_at/updated_at、顶层 progress/reading、已知 chat 映射及编译运行时间字段。不能递归删除所有名叫 `updated_at` 的 payload 值，也不能整块丢掉 metadata 或只给 payload 建白名单后遗漏新内容。

状态、生成／错误、观测 revision 和读时间单独保存用于门禁与一致性核对，不能当内容版本。未知扩展字段优先保留；若会影响渲染／导航而规则尚未处理，则将投影覆盖标 partial，不能静默删掉再报一致。实现须附精确字段表和回归例子。

章节／页／块的可见顺序保留。题目身份使用 `(pageId, blockId, questionId)`，同一 q_1 在不同块出现合法；同一块重复题 ID、无 ID 或无法唯一定位的题目不得进入 supported 复核。不要按题干或答案 hash 折叠题目。

## 5. 资源范围与包完整性

内容快照是证据包，不承诺脱离 DT Web 独立运行。记录实际 renderer/Web 版本，不复制整个 node_modules。

1. text/section/callout/quiz 与上游概览 concept_graph 为首期核对对象，完整保存其实际 payload。内联 JSON／图代码属于内容字节，**只存不执行**。
2. 按固定渲染器识别实际渲染依赖：Markdown 图片／引用式图片、已支持的资源字段等。普通来源链接、导航页链接不是自动下载依赖，不抓取所有正文 URL。
3. 只通过已核对的同部署、同作用域静态下载入口读取资源，例如上游 `/files/outputs/...`。不能任意 GET payload 给出的地址，不能把课程 URL 指向 GET Book 也作为资源下载。
4. 外部图片、未知 URI、认证缺失、404、重定向、越界、超限、无法固定的动态依赖分别记 missing/unsupported/partial；不能悄悄联网补齐。active HTML／脚本、音视频及通用 figure 依赖闭包不在本期完整覆盖范围。
5. 同一 URI 的字节也可能变化。每个采集轮次读取实际字节、保留 URI／引用位置／MIME／长度／hash／包内路径，比较轮次间资源 manifest；不能只核对 URI。
6. 资源存储使用 hash 或受控 ID 的包内路径，拒绝 URI 目录逃逸和符号链接越界。所有 manifest 引用都必须存在且匹配 hash。需要去敏的响应／URI 不能当完整原始字节证据。

`resourceManifestDigest` 单列。快照身份同时固定投影版本、contentDigest、来源映射和资源 manifest；`check-baseline` 必须比较资源，不能因题干文字没变忽略图片／图表变化。I5 使用的绑定证据也必须引用这些摘要。

## 6. 采集与稳定性协议

1. 校验 I3 activity 映射、成功 production/corpus 回执、当前 backend scope、资料留存与来源版本；不确定生产结果、错 scope、原文缺失或语料漂移不得进入可交付基线。
2. 明确 `purpose`。pre_learning 保存准备者的协作冻结声明；retrospective 是事后内容证据。声明不是服务器锁，也不证明历史上没人作答。既有学习记录早于捕获时点的绑定留给 I5，不能补造“作答前基线”。
3. 经新只读入口读取**全部实际页面和块**、严格枚举诊断与生成状态，采集资源字节。完整基线要求 Book/page/block 均处于可接受 READY 状态、没有已知错误、生成未报告在工作；paused/partial/hidden/未知状态保留诊断，不把它们归为全部成功。
4. 连续完成两轮独立读取，比较投影、资源、页面／块 ID 集合、revision 与必要生成状态。原始响应不含 progress 并不让它变成原子事务；逐项保存时间与摘要。
5. 不同则最多重试两次，即最多三组独立的成对读取；不得无限等待或恢复生成。持续变化记 `captureStatus=inconsistent`，缺页／资源等记 partial，采集错误记 failed；这些诊断均不发布为可用基线。
6. 稳定完整候选先在同卷临时目录写内容、原始响应、资源、manifest 并重验，再一次发布最终目录和完成标记。完成标记最后写；索引／指针不是唯一证据，也不能先指向未完整包。

一个 captureId 固定其语义输入（活动、scope、snapshotId、purpose、声明、规则版本等），不绑定可移动绝对路径。相同 ID 完成后返回原结果；不同输入冲突。中途进程崩溃的未完成目录不能被发现为成功；因为没有远端写副作用，可以保留旧尝试，用新尝试目录重新完整读取，不能把跨重启的两次单读拼成一对。

snapshotId 成功发布后不可换字节。首次基线绑定前允许生成多个候选，以便准备阶段修复上游内容后重新审查；首次正式绑定后，不能通过再采集当前版来遮盖漂移，修订按 D2 使用新 activity/book。

## 7. 结构检查、质量审查和交付门禁

三者分开保存，不使用一个模糊 passed 字段：

| 层次 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| captureStatus | stable_complete／partial／inconsistent／failed 的采集事实 | 来源忠实、教学质量或掌握度 |
| structuralCheck | 实际状态、身份、页／块引用、题目结构和已知失败标记 | 题目答案在语义上正确、解释没有臆造 |
| qualityReview | 具体准备者对固定快照与原文作出的审查判断及发现 | 模型绝对可靠、来源已经正式入库 |

单答案 choice 的 supported 条件：明确为 choice；题干非空；至少两个非空选项、键唯一；correct_answer 精确命中唯一选项键；题目身份可定位。答案文本、A/C、多答案集合、不存在的键和未知格式不得强行规范化成一个字母。选项显示顺序按实际数据保存，未来复核不按数组位置猜键。

short_answer／fill_in_blank／written 及未知类型原样保留，评估支持为 unsupported，不因 payload 带 correct_answer 就视为可自动批改。课程可在明确“阅读＋已支持 choice”的范围下处理这些题；未覆盖清单必须可见，不能宣称全套题型已支持。

`[Generation failed]`、已知错误占位组合、空题干／空内容、无效选项／答案键、错误状态即使外层 READY，也必须形成具体定位的阻断发现。`N/A` 本身可能是正常文本，不作全局字符串封杀；结合题干标记／失败信息识别，疑似项交实际审查。

quality review 文件至少引用：reviewId、actorId／角色（用户或外部准备 Agent）、activity/snapshot、content/resource/source 摘要、逐项发现、来源证据引用、题目语义检查、unsupported 范围及 decision。关键事实／数字／白名单／算法／题目答案应能与原文核对，不能用 `source_quality=ready` 或聊天后来的纠正代替检查。review 中的 pass 是作者判断，不伪造为确定性证明。

同一个 `review-baseline` 操作可记录审查并在满足全部条件后绑定首次基线，不额外要求用户再批准同一个动作。必须先重新核对当前内容与资源：

- stable_complete，资源和来源证据完整，结构检查无阻断；首个 D3 闭环至少有一道 supported choice。
- 实际审查通过、无未关闭的来源／题目质量阻断，unsupported 范围被明确说明。
- 当前核对仍与被审快照一致；不能将旧 review 复用于改过的当前内容。
- scope 和 activity 映射一致，无另一正式基线绑定冲突。

不满足时，保存审查的原判断／发现与门禁失败原因，不改正文、不补题、不生成模型答案。通过后保存不可变基线绑定；质量审查和绑定不是正式 wiki 的 approve，也不表示学习完成。I6 仍须做交付及真实闭环验收。

## 8. 后续绑定与失败恢复

`check-baseline` 产生新的不可变检查记录，保留 content/resources/current revision、读取边界和错误；不覆盖旧 snapshot 或原质量判断。

当前内容、资源及必要来源状态一致时，最多输出：

```json
{
  "binding": "baseline_consistent",
  "assurance": "cooperative",
  "submissionContent": "unknown"
}
```

只要缺基线、scope 错、内容／资源变更、读取不完整，binding 为 unknown。来源原文缺失与课程内容是否相同是两个事实，分别表达；不能在来源缺失时仍给“全部可交付”结论。历史作答时点及 page/block/question 对齐由 I5 对每条记录检查，**首期永不输出 verified_at_submission**。

重复 review/check 不写上游。读中丢失资源不删旧证据；坏 manifest／内容 hash／资源 hash 拒绝使用。新目录不得覆盖旧 snapshot；派生索引可重建。断电、跨文件原子性、ABA 改后改回、另一客户端所见版本均不在本阶段保证内。

## 9. 子任务与依赖

| 子任务 | 交付和关闭标准 |
| --- | --- |
| I4-A 读取补丁 | 只读 content 路由＋严格枚举；保持旧 GET 行为；路由／存储测试证明零生成／零业务写，损坏页不静默跳过；保存可复现 diff／构建标识 |
| I4-B 投影与诊断 | 精确字段表、版本化投影、身份／顺序／题型／失败占位检查，真实去敏夹具正反例 |
| I4-C 资源和快照 | 受控依赖读取、字节 manifest、两轮比较、最多两次重试、原子发布／崩溃恢复 |
| I4-D 复核与基线 | check、质量 review 回执、首次基线绑定及不可重绑；保守历史绑定输出 |
| I4-E CLI 与交接 | JSON CLI、输入／包样例、测试命令及证据，更新任务／设计入口的准确状态 |

A → B/C → D → E；B 的纯函数可以先做，但 A 未通过不能把只读完整采集标为已实现。复用 I3 基础，不改其生产语义，不覆盖 I3 历史报告；新增兼容改动须运行 I3 的 36 项回归，最新证据另存 I4 目录。

## 10. 必测场景

| 编号 | 场景与必须观察到的事实 |
| --- | --- |
| B01 | 旧整书 GET 仍保留恢复；新 content 在 ready/compiling/paused 等状态均不调用 resume/compile/LLM，不写业务数据；非 ready 仅返回真实状态或诊断 |
| B02 | 新入口 404／旧包装／schema 缺失：明确不支持，零回退 GET Book；不得靠未知 query 参数伪造只读能力 |
| B03 | 孤立存储页、坏页 JSON、跨书页、重复 ID、缺引用页、枚举时删除：严格覆盖诊断，不能静默发布完整基线 |
| B04 | 相同 revision 下改 payload／答案／章节顺序／未知语义字段：digest 变化；仅 progress/chat/已列明观测时间变化不改内容摘要 |
| B05 | 多页多块全部读取；同名 q_1 跨块合法，同块重复或无 ID 不进入 supported；不能只取第一页或第一道题 |
| B06 | READY 内的 Generation failed 占位、无效答案键、空内容、未知题型：分开标阻断或 unsupported；原字节保留，不强制改题 |
| B07 | I2 历史 4 页／17 块夹具：可保留候选证据，但失败占位与来源忠实性限制阻止直接通过交付门禁；人工构造内容不冒充 I2 真实修复 |
| B08 | 资源 URI 相同但字节变化、资源丢失／重定向／越界／外部地址：比较字节并标完整性；没有任意 URL 请求或脚本执行 |
| B09 | 第一次读后变更再稳定、持续变化、读中删页：只有独立稳定对可用；三组耗尽后 inconsistent，无无限循环／模型重试 |
| B10 | scope／owner／workspace／活动／语料 hash 错配及原文缺失：失败或明确 partial，不能按同名聚合来源 |
| B11 | 写 raw/content/assets/manifest/完成标记各阶段崩溃：未完成不可见；重启重新成对读取；成功 snapshotId 不换内容，索引可重建 |
| B12 | 同 captureId 同输入／不同输入、两进程争用、同 snapshotId 不同字节：复用／冲突／busy 可判定，无远端写请求 |
| B13 | review 没看原文／缺摘要／有未关闭阻断／审后内容变化：保留判断但不绑定；仅改 decision=pass 不能越过结构及当前核对 |
| B14 | 首次审查后正常绑定；另一个 snapshot 不能遮盖已绑定内容漂移；不额外弹出重复确认，不影响正式 approve |
| B15 | retrospective、记录早于捕获、缺提交时 hash、改后改回：不得输出 verified_at_submission／掌握度；相等最多 cooperative |
| B16 | 未配置模型／零额度：采集／复核测试仍可执行，供应商请求为 0；I3 36 项回归通过，产品不 import 私有探针／测试夹具 |

测试使用真实 loopback HTTP 假服务和实际临时目录／子进程，断言请求路径及次数。上游路由用实际框架测试并观测生成／存储入口，不能只测项目自己期待的 JSON。去敏真实响应明确标 replay，必要时对隔离的补丁服务做无模型只读集成；禁止打开旧 GET Book 验证读取安全。
## 11. 交付、停止条件和预算

实施后才创建 `docs/design/evidence/learning-book-i4/README.md`，提交代码／补丁、版本与构建 hash、CLI 示例、候选／正式基线／review／check 样例、B01–B16 对照、故障文件与请求计数、I3 回归结果及未覆盖项。不提前放“已通过”占位报告。

本轮 I4 实现、隔离补丁构建／ASGI 路由与 HTTP 假服务验证，真实模型／embedding 调用均为 0；未改既有服务安装，不沿用 I2 额度，也未重新生成课程。需要编译／补题时，另走 I6 的新授权额度与受控生成路径。

向 I5 交接时注意：新 content 入口不返回 progress，I5 须另核对无生成副作用的学习记录／会话读取入口，不能因为已有内容快照就回退旧 GET Book 来拿进度。

如果新入口无法保证无生成副作用、完整页枚举无法证明、需改业务权限模型或必须引入第二个引擎／状态库，停止相应实现并记录最小差距。来源忠实性问题不靠提高 hash 校验强度解决；证据完整性问题也不靠一句人工“看过了”放行。
