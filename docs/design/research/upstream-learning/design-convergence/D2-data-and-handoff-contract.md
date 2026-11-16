---
type: meta
title: D2：数据、操作与学习结果交接契约
status: design_decision
updated: 2026-11-09
topic: 数据、操作与学习结果交接契约
related_sources: []
related_synthesis: []
---

# D2：数据、操作与学习结果交接契约

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-10。状态：设计完成；I3 的来源／生产回执已实现并通过本地 HTTP 契约验收，真实写入待集成，见 I3 报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i3/README.md）。I4 内容基线已实现并通过本地／HTTP 验收，见 I4 报告（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）；[I5 详细任务书](../../../learning-book-i5-plan.md)已完成，结果交接和 I6 真实部署集成尚未实现，不能将下表整体视为已交付。底座采用 [D1](D1-learning-backend-decision.md) 推荐的 DeepTutor Book；本期范围见 [D3](D3-first-learning-scope.md)。

## 1. 真值和身份

项目稳定 ID 由项目生成，不依赖文件位置、标题、bookId 或 KB 路径。各 backendRef 必须带 deploymentId、owner/workspace，防止同名 ID 或重装后串数据。相同字节可以去重存储，但不能因 hash 一样就合并来源作者/URL/授权身份。

| 对象 | 稳定身份、拥有者与写入者 | 实际保存/读取 | 修改、寿命和缺失 |
| --- | --- | --- | --- |
| 原始来源 | sourceId + sourceVersionId + SHA-256；收集工作区/外部 Agent | 原始字节 + 来源元数据，项目目录 manifest 定位 | 正文变化新增版本；移动只改定位。删除后历史引用保留 tombstone/missing，不能改指向新正文 |
| 提取物 | artifactId + 原文版本/hash + 方法/版本；资料生产方 | 工作区文件、解析覆盖/截断说明 | 派生物可重建；人工修订另存版本，不冒充原文；唯一历史提取证据不能无条件清理 |
| 来源摘要 | draftId 或 accepted 来源页关联；外部 Agent/现有维护流程 | 待处理工作区；接受后沿用 wiki/sources | 摘要不是关键事实的替代证据，不另建正式来源图谱 |
| 学习投影 | sourceVersionId + inputArtifactId/hash → DT deployment/KB/file；DT API 写入 | DT KB raw/索引；knowledge API、生产回执 | 是可替换输入副本，索引可重建。清洗文本 hash 与原文 hash 分开；不能在副本改完后静默覆盖源资料 |
| 活动与工作内容 | activityId → DT bookId；DT BookEngine/编辑入口 | manifest/spine/page 文件，GET `/api/books/{id}` | 上游是唯一可编辑学习内容；修订版使用新活动/新 book，旧映射不重绑；删除不删已保存证据 |
| 创建输入 | productionReceiptId；项目保存请求，DT 保存 BookInputs | 项目请求/响应回执；DT `inputs.json` | Book API 未提供专用 inputs JSON 读取，不能声称 GET Book 就返回完整输入。项目保存自己提交的内容，实际解析截断见下文 |
| 学前内容证据 | snapshotId + rule/content/resource/source 摘要；项目只写一次 | 只读 content.json、依赖资源及清单 | 快照是历史输入证据，不开放编辑/进度写入。变更产生新快照/活动，不原地覆盖 |
| 学习尝试与实际记录 | backendScope + submission_id；无 ID 时用原始记录定位 | DT Progress.quiz_attempts；`progress.json` / Book JSON | DT 业务入口写；项目只读。原答案原样保留。无 ID 旧记录不假装全局唯一 |
| 评分/判断 | 原始值与作者分别记录；上游、用户或独立评估者 | progress 原值、可能的 assessment 记录、公开 chat | 原判断不覆盖；新判断另记。Book 默认无模型书面评分，不能填补一个不存在的 verdict |
| 用户声明 | declarationId + author + scope + time；用户明确提交 | 项目附属声明回执或可定位的上游记录 | 目标/偏好可以跨活动；“本次结束”仅 activity；“我懂了”是自评。过期/撤回不删原证据 |
| 导师估计/独立评估 | judgmentId + 作者/方法 + evidenceRefs + scope | 可定位的公开记录或独立评估产物 | 教学口吻不自动解析成权威掌握。独立评估须另有条件与证据，首期不生成 |
| 交接包 | exportId + schema/exporterVersion；项目 | 不可变 JSON + 原始响应/快照引用 | 重新导出产生新版本；可重建派生标签，不改历史事实；删除会丢唯一证据时须显式处理 |
| 活动索引/最近导出指针 | 项目辅助视图 | receipts/snapshots/exports 的可重建索引 | 不保存可独立改写的答案/掌握度；丢失可重建 |
| 知识候选/正式知识 | 候选由外部 Agent；接受写入走现有维护入口 | 工作区候选 → raw/wiki | capture approved、book ready、用户结束均不触发正式 approve；现有授权不变 |

本期单用户不取消 owner/workspace 校验。无需新增账号系统；project owner 绑定选定部署身份即可。学习目录不承担待处理→处理中→已完成三套物理迁移状态机；用户界面/上游是学习状态入口，目录只保存资料和交接证据。

## 2. 应用操作与真实入口

下面是业务语义，不是要求再造一组 HTTP 服务。首个项目入口为本地 CLI + JSON 文件回执，I3 的生产操作已有实现；需页面按钮时再接同一个应用操作。其他新增能力仍按阶段后置，状态以对应任务／验收为准。

| 操作 | 提供方/入口 | 权限与限制 |
| --- | --- | --- |
| collect、prepare | 外部 Agent 的共享工作区、manifest 与生产回执约定 | 明确整理后才 prepare；不自动 ingest，不强制模型调用 |
| queryKnowledge | 外部 Agent 读取现有 wiki/index 和来源页，按现有规则检索 | 不需再导入整个 wiki，也不让内部模型自由写正式库 |
| publishLearningInputs | 项目适配调用 DT POST `/api/knowledge-bases` 或 `/{kb}/upload` | 使用专用学习 KB、稳定版本文件名；保存 task/文件回执，等导入可读再成书 |
| createActivity | DT POST `/api/books` → confirm-proposal → confirm-spine | 项目先保存请求与返回 bookId；确认是生成批准，不是正式知识审批 |
| discover/open | DT GET `/api/books`、GET `/api/books/{id}`；上游网页书库/reader | 外部 Agent 可直接 HTTP；Book GET 可能恢复未完成生成，不是无副作用的纯读取 |
| captureBaseline | I4 已实现，通过补丁 GET `/api/books/{id}/content` 及受控资源读取 | 最小补丁／严格枚举已隔离构建测试，尚未安装进既有服务；两轮读取与外部审查／首次绑定分开，覆盖限制见 I4 报告；不回退旧 GET Book |
| learn/ask/answer | 上游 Book 网页；chat 使用统一 WS turn；quiz-attempt / progress API | 保持同一用户/活动；适配器不代填答案、不维护镜像 progress |
| read/exportResults | [I5 任务书](../../../learning-book-i5-plan.md)已完成、实现未开始；先补严格 learning-state GET，复用所选公开 session／events | 区分缺失／损坏／有效空；不回退旧 GET Book，不把所选会话当全部历史；原值、条件复核及覆盖分别保存 |
| declareEnd | 用户明确声明，项目附属回执 | course/activity 结束不等于 page 访问、Book READY 或 attempt 完成 |
| submitKnowledgeCandidate | 外部 Agent 读取导出与原文，放工作区候选 | 回现有 ingest/approve；未来 MCP 只适配操作，不能升级审批权限 |

API 以 DT HTTP 服务为基准，Web 的代理负责转发。CLI/SDK 可用于已有操作，但本期不从旁启动第二个 BookEngine 同时写同一目录：文件 read-modify-write 的单进程假设需要保留。外部 Agent 与用户页面通过同一个运行中的服务写业务状态。

输入映射使用真实 `TopicSource`：`kind:file, source_id:<KB 内相对文件>, metadata:{kb_name,path}`，配合选定 `knowledge_bases`；项目 sourceId 放生产回执/metadata 映射，不能将项目绝对路径直接塞进 source_id 后声称服务端能读取。文件 grounding 有长度上限，`BookInputs.source_context` 也会裁剪；项目回执必须记录原文/提取物是否完整、已知上限，实际输入字节未采集时记 unknown。source_refs 代表“请求选择了哪些来源”，不证明每个段落或题目实际使用了所有资料。

本期将每个小批资料集导入独立、协作冻结的学习 KB（示例名 learning-inputs 代表这一批），生成/学习期间不向其中追加无关文件。同一冻结资料集可以供两本书复用；资料集变化创建新版本/KB，不要求每门书重新索引完全相同的集合。回执记录 corpusId、文件清单、inputArtifact/hash 映射、选定 KB 和已知额外输入；未知文件/跨库来源使 coverage 降为 partial。这样避免把全库检索误当所选文件过滤，也明确了按资料集隔离可能重复索引的成本；它是上游输入投影，不是第二个正式知识库。

I3 任务细化时补核的入口语义：KB 走资源库管理作用域，不能以 Book workspace header 宣称 KB 已按 workspace 隔离；回执须保留真实 KB owner／资源引用与 Book scope。`indexing-readiness.ready` 仅是配置／前置条件，不是索引完成；发布输入还需比对实际原始文件字节、`indexing-run` 的文件状态及上传投影 source_hash／可用版本。具体实现与恢复约束见 [I3 详细任务书](../../../learning-book-i3-plan.md)。

## 3. 上游字段 → 项目字段

| 上游事实 | 交接字段 | 语义/新增责任 |
| --- | --- | --- |
| 请求 source_refs、KB/file；BookInputs | sources / productionReceipt | 稳定项目来源与上传请求由项目新增；实际来源使用与精确锚点允许 partial |
| Book.id/revision、spine、pages/blocks/payload | activity.backendRef / snapshot | revision 只是协作 token；保存完整所选内容的项目证据，不假装有上游历史版本 API |
| Progress.current_page_id、visited/bookmarked_page_ids | observations.navigation | 实际页位置/访问，不是阅读时长或理解率；恢复到页，不保证精确滚动位置 |
| quiz_attempts 的 submission_id、timestamp、page/block/question、user_answer、is_correct | records / assessments.raw | 原值原样；submission_id 为空时用导出响应位置+摘要定位，identityQuality=legacy，不折叠相同答案的多次尝试 |
| 同期快照中的题干/选项/答案键 | assessments.derivedCheck | 仅对唯一可识别、单一答案键的 choice 题作确定性比较，ruleVersion 独立；不替换原客户端判分 |
| `self:correct` / `self:incorrect` 或空答揭示 | userReport / revealed_ungraded | 自评，不是学生书面解题原文；不能伪造缺失的书面答案 |
| metadata.page_chat_sessions、session preferences.book_id/book_page_id | conversationRefs | 双向关联校验；关系不一致时隔离，不把别页会话拼进当前活动 |
| sessions messages + 分页 events | records.rawPayload、readBoundary | 公开历史与 trace 可读范围；主接口可能裁剪大事件，需分页或标缺失；不导出模型私有 replay 当学习证据 |
| attempt 保存后 assessment 同步失败 | captureErrors / assessmentSync | 原记录可存在但请求报错；缺日志时只能说同步状态 unknown，不能从 progress 缺失反推网络失败原因 |
| Book/Page/Block 状态 | generationCoverage | 生成 READY 与 learner completion 无关；PARTIAL 不是“所有块已成功” |
| 没有上游对应字段 | assistance、completion、contentBinding、export schema | 项目保守派生/用户声明，明确证据强度；没有帮助日志不推 false |

首期 assessments.method 使用 `client_reported`、`user_self_report`、`ungraded`、`missing`、`unknown`；对 choice 可附 `derivedCheck.method=deterministic`。未来真有模型 verdict 才新增 `model` 并附真实记录；有明确兜底记录才标 `fallback`。不把 OM 的失败基础分规则套在 DT 上。

同一原记录跨 export 的去重使用 `recordKey=(deployment,owner,workspace,bookId,submission_id)`，不是某份包里的数组序号；公开消息使用其 session/message 身份。该 key 是带作用域的上游事实引用，不代替项目 activityId。I5 按完整结构化元组的版本化 canonical 摘要编码，示例里的冒号字符串仅作说明，不能直接拼接以免产生歧义。无 submission_id 的旧尝试只提供包内定位和 identityQuality=legacy，不能仅凭时间/答案 hash 去重，因为完全相同的多次练习也可能真实发生。

## 4. 版本和一致性：明确能证明到哪一步

I4 已补只读 content 入口和严格枚举，隔离源码／新构建 wheel 及项目契约测试通过，见 I4 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）。补丁未安装到既有部署，使用前核对实际构建。旧 GET Book 仍会恢复生成，旧 `list_pages` 仍为 best-effort；不能把只读新入口的保证推广到旧接口。

1. **生产回执**保存 project source 版本/hash、上传/创建请求 hash、请求时间、deployment/owner/workspace、上游 commit、book/KB/file 映射与不确定操作。创建请求不能仅靠标题去重。
2. **学前快照**在页面/块完成、无编译和编辑进行时建立。连续两次读取 book/spine/pages，比较完整内容投影的 digest 与 revision；失败有限重试两次，仍变化则 `captureStatus=inconsistent`，不发布为基线。单看 revision 不够，后台页写入未必等价于一次编辑 token。
3. 快照保存有顺序的章节/页/块、题目/选项/答案键/解释、目标、真实来源映射和依赖资源；分开保存原始响应。内容投影排除 progress、聊天映射、更新时间等非内容字段，投影规则带版本。不把界面未来可编辑的正文保存在项目内作为第二份工作内容。
4. `contentDigest=sha256(content.json 的实际 UTF-8 字节)`；写入者固定 JSON 编码规则（键排序、紧凑分隔、无 NaN、不转义中文），保存原字节供校验。hash 表示此快照，不宣称跨 exporter 版本的语义等价。source hash 始终按原始字节计算。资源只保存 URI 而未固定字节时，该部分 evidenceCoverage=partial。
5. 首期采用**协作冻结**：学习期间不 regenerate/rebuild/supplement/编辑题目，更新另建 book/activity。外部生产方只在准备时写；用户通过上游直接改书不会被项目物理阻断，导出需再次检查。
6. **不得把协作冻结写成严格历史绑定。** 现有 attempt 不带提交时内容 hash。导出时当前内容等于基线，只能得到 `binding=baseline_consistent, assurance=cooperative, submissionContent=unknown`；不证明期间从未改过又改回，也不证明别的客户端所见版本。严格 `verified_at_submission` 首期不可用。
7. 当前内容不同、缺正式基线、回答早于 capturedAt／首次 boundAt 或时间边界不明、页/题不匹配：该记录 `binding=unknown`，保留原答案和旧快照分开引用，禁止将当前答案键当历史评分键。可展示“对基线题目的条件性复核”，不得称为原题评分。
8. 导出不是跨文件/SQLite 的原子事务。停下新答题、等待当前回合结束后采集；记录每个响应摘要、时间、message/attempt 位点，再复读关键内容/记录摘要。发现新增则有限重读或 partial。记录读边界，不声称这是全局时刻。严格一致快照需未来领域事务支持。

上述边界让外部 Agent 能做保守的学习回顾和资料整理；不能据其发“独立掌握通关证”。若将来通关是目标，应在真实提交入口绑定题目版本并保存原输入/评估，而不是继续强化导出侧猜测。

## 5. 最小交接契约

以下是拟新增的 JSON 契约，`learning-handoff/1` 是文档内 schema 标识，与产品版本/课程版本无关。示例中的短 hash/ID 是说明值，实际使用完整 digest 与不透明唯一 ID。

```json
{
  "schema": "learning-handoff/1",
  "exportId": "exp-01",
  "exporterVersion": "project-book-map/1",
  "capturedAt": "2026-11-10T12:00:00Z",
  "backend": {"kind": "deeptutor-book", "deploymentId": "local-a", "revision": "60fb3bd", "owner": "local-owner", "workspace": "study"},
  "activity": {"activityId": "act-01", "backendId": "bk-01", "productionReceiptId": "prod-01", "corpusId": "corpus-01"},
  "sources": [{"sourceId": "src-01", "sourceVersionId": "sv-01", "sha256": "sha256:…", "inputArtifactId": "artifact-01", "inputSha256": "sha256:…", "backendRef": {"kb": "learning-inputs", "path": "sv-01.md"}, "scope": "activity", "locator": null, "coverage": "partial"}],
  "content": {"snapshotId": "snap-01", "digest": "sha256:…", "binding": "baseline_consistent", "assurance": "cooperative", "submissionContent": "unknown"},
  "records": [{"recordKey": "dt:local-a:local-owner:study:bk-01:sub-01", "recordRef": "raw-01#/progress/quiz_attempts/0", "submissionId": "sub-01", "pageId": "pg-01", "blockId": "bl-01", "questionId": "q-01", "rawPayload": {"user_answer": "B", "is_correct": true}}],
  "assessments": [{"recordRef": "raw-01#/progress/quiz_attempts/0", "method": "client_reported", "rawCorrect": true, "derivedCheck": {"method": "deterministic", "ruleVersion": "choice-key/1", "against": "snap-01", "correct": true, "historicalBinding": "cooperative"}}],
  "assistance": {"value": "unknown", "evidenceRefs": [], "scope": "activity"},
  "completion": {"scope": "activity", "value": "declared_end", "declaredBy": "user", "evidenceRef": "declaration-01"},
  "coverage": {"navigation": "supported", "choiceAttempts": "supported", "writtenAnswerText": "unsupported", "modelGrading": "unsupported", "history": "partial", "missingFields": ["submissionContentHash"]},
  "collection": {"consistency": "observed_stable", "rawRefs": ["raw-01"], "boundaries": [{"resource": "book:bk-01", "attemptCount": 1, "responseDigest": "sha256:…", "readAt": "2026-11-10T12:00:00Z"}]},
  "limitations": ["来源仅活动级；提交时内容未被上游绑定；不证明独立作答"]
}
```

原始响应、对应 recordRef、快照资源及 manifest 放同一个可搬运的导出目录，使用项目 ID/包内引用，不把原机器绝对路径当永久证据。完成文件与 manifest 校验后再发布包，未完整写出的临时目录不当可用 export。包内路径必须受 manifest 边界约束；hash 是完整性校验，不是作者签名。摘要和 derivedCheck 都能重建；已丢失的原 verdict、被删除的聊天、未提交答案不能重建。

## 6. 三个静态例子

### A. 正常结果，同一来源用于两次学习

外部 Agent 整理 `src-01/sv-01/hash-H1`，上传学习 KB 的 `sv-01.md`。活动 act-01/book-A 讲幂等；act-02/book-B 讲重试，均引用同一 sourceVersion，不复制两份正式摘要。两活动分别有 productionReceipt、snapshot 和 progress，不共享 learner completion。

act-01 的选择题 q-01 用户选择 B；原 progress `is_correct=true`，基线选项键 B，导出为 client_reported，并附对 snap-A 的确定性复核。页边会话 sid-A 的公开记录通过 Book metadata 与 session preferences 对齐；关闭/重开从同一 API 读到保存状态。act-02 无作答，不能继承 act-01 的完成或正确性。

外部 Agent 实际收到原始答案 B、基线问题、复核规则、关联来源集合及公开会话；能知道一次练习发生过、当前与基线相符，不能由此证明独立掌握或 q-01 精确来自原文第几段。

### B. 混合结果与保存服务失败

同一次活动含三题：

| 题 | 实际可见记录 | 导出 |
| --- | --- | --- |
| q1 choice | 答案 A、客户端 false，原 Progress 已保存；快照答案键 B | client_reported(false) + deterministic(false)，保留原值 |
| q2 written | `user_answer="self:correct"`, `is_correct=true` | user_self_report；书面答案原文 unsupported；不称模型批改 |
| q3 written | 揭示后空答案、`is_correct=null`，或没有 attempt | 前者 ungraded，后者 missing；不标答错、不补造输入 |

另一次 q1 提交已保存 progress，但 assessment/question-bank 同步失败，API 返回 500（`book.py:1135–1217`）。若项目实际采集到该错误，附 operation/error；未采集到则 assessmentSync=unknown。重读 progress 确认相同 submission_id 已存在后，使用同一个 ID 恢复/重试，不追加“补偿答案”。进度与第二存储不假装全有或全无。

整个包 assessmentCoverage=partial；默认 Book 没有模型批改服务，不能凭 HTTP 500 创造 `model_failed` 或套用 OM 的半分 fallback。未来后端真的返回模型评分/兜底时，必须保存该原始 verdict 和失败来源再扩展分类。本例没有模型再调用。

### C. 学后改内容或读取时发生变化

snap-A 保存 q-01 答案键 B；学习后用户直接编辑成 C。导出检测 digest 不同：原答案和客户端 true 仍保留，binding=unknown，snap-A 与当前快照分开；不把 C 拼进历史记录宣称“用户当时答错”。应另建 act-03/book-C 承接新内容。

即使导出开始/结束都为同一 book revision，只要 pages 内容摘要变化仍判不一致；没有变化只能报 observed_stable，不能证明原子性或排除改后回退。聊天同时追加时按各 message 的读取位点标 partial，可稍后生成另一份 export；原 export 不原地覆盖。历史活动首次补基线时，既有 attempt 的版本仍 unknown。

## 7. 失败、重试、删除和恢复

- **项目请求幂等**：生产方先保存 requestId/requestDigest 与单写者占用，再调用上游并追加回执。重复相同请求返回已有回执；相同 ID 不同 payload 拒绝。本地登记不是上游 create 的 exactly-once 保证。
- **上游不确定成功**：create 没有已定位的幂等键且提案生成在保存 Book 之前；超时记 uncertain，列书/人工核对回执，不仅按标题自动匹配，也不盲目重建。上传按 sourceVersion 命名，文件存在但无法核对字节时同样 uncertain。准备未确定完成则不发布活动。
- **答案幂等**：复用上游 submission_id；同 ID 不同答案返回 409。页面刷新丢失 pending ID、无 ID 历史尝试及并发请求不具有跨重启 exactly-once；不要声称 exporter 能弥补。已经保存的事实可在服务重启后重读。
- **身份不一致**：deployment/owner/workspace/book 或 chat 反向关联不符时拒绝聚合，保留 diagnostic，不降级成“空历史”继续出完整包。
- **来源/资源缺失**：标 missing，并保留版本/hash/旧快照；无原文时外部 Agent 不能做已核验事实沉淀。精确定位不足允许活动级，但不能编页码。
- **聊天边界**：Book 每页映射不一定枚举全部历史会话；用户可删消息、切换会话，主接口有大事件裁剪。分页达到边界/资源删除须在 coverage 明示。session/message 事件序号仅在其本地作用域有意义，不能合并成全局因果顺序。
- **辅助判断**：有关联教学/提示只能 `observed`，附记录和时间不确定性；缺记录一律 unknown。用户声明“独立完成”仍保存为声明，不自动变成受控测验事实。
- **完成与回收**：用户可随时导出未完成活动；结束声明不删除内容/状态。备份与删除覆盖源文件、DT 隐藏状态和项目证据；删除源原文不自动级联删除历史引用。重建索引不能重建丢失的唯一原始记录。

## 8. 源码依据与结论

均为 D1 的 DT 固定提交：`book/models.py:176–192,218–226,450–547`；`book/storage.py:98–111,172–180`；`book/learning_overlay.py`；`book/progress.py:70–107`；`book/chat_sessions.py:20–39`；`api/routers/book.py:742–791,1102–1218,1269–1287`；`api/routers/sessions.py:456–526`；`book/inputs.py:345–388`；`learning/topic_generation.py:148–194`；`api/routers/knowledge.py:3411–3453,3527–3539`。文件入口链接见 [D1 证据表](D1-learning-backend-decision.md#4-四条决定性调用链与证据)。

**D2 没发现必须增加第二套可写学习库的缺口。** 新增的是回执、只读证据和导出，不是第二个进度系统。代价是内容绑定与学习评估保持明确的协作级/部分覆盖；严格学习门禁不在此契约已经保证的范围。