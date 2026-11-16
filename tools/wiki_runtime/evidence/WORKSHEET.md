# 外部 Agent 知识准备与课程交付工作单（K4）

本工作单串接现有普通应用操作；不要求外部 Agent 常驻，不新建 loop 或第二套学习状态。先读根 [AGENTS.md](../../../AGENTS.md)，再读本工作单。包、观察、投影及回执是不同对象；退出 0 和 `operator_supplied` 不构成人类认证或正式写入授权。

## 1. 选路线与冻结限额

先从用户已给的要求确认本次是暂存、整理知识、学习，还是明确要求“先学后入库”。已有明确方向与委托直接复用；缺目标、时间／深度或实质扩范围才询问。不把链接自动成课，不要求纯知识整理先学。

在私有工作区记录原始要求、来源载体、最多 3 份初始文本、10 个核心主张、每缺口最多 2 次补查、最多 2 轮修订；实际调整须在执行前冻结。业务模型额度沿用实际授权，宿主对话 tokens 无可信计量就记 unknown。确定性操作不调模型。

工作目录建议分别放 `inbox/`、上下文／知识包 JSON、`projection/`、认可依据、独立审阅观察和 `payload/`。原件不可覆盖版本；旧报告及失败证据保留。候选 payload 根必须在知识根之外，且二者互不包含。

## 2. 原文与知识核对（两条路线共用）

1. 调用 [K1](README.md) 的 `inspect-context`，显式给出原件范围和查询词；完整读取实际返回页。元数据无命中只说明本次未读到，不说明库内没有或用户不会。资料存在只作背景连接。
2. 用 [K2](KNOWLEDGE.md) `prepare-knowledge` 组包。摘录必须是原文完整连续行；保留适用条件、版本、共同上游和旧页不同意见。原件不完整、不支持主张或未决冲突，不得成为确定事实或标准答案。
3. 将实际原文、旧页全文、Claim／关系／冲突／来源观察和 reviewRequest 交真实审阅者。保存实际返回的 `knowledge-review-observation/1`；程序或准备者自己填 accepted 只能测试控制流，不能当独立语义验收。
4. 重跑得到 `knowledgeState=reviewed_for_scope` 后才消费。争议包可显式分包再审，不悄悄删主张。变化只重做受影响部分；旧版本和旧学习记录不改写。

## 3. 纯知识候选

先经适用的采集入口登记原件，不能在 ingest 候选中偷建 raw。保留原始字节；采用 body 绑定时，原件对应 raw 的正文，而 raw 全文件摘要另核。

调用 [K3](PROJECTION.md) 的 `preview-wiki-changes`；大仓库可显式加 `--baseline-scope knowledge_content`。该范围固定为**完整 wiki/、raw/、AGENTS.md 和 rules.json**，包含任意层级子目录、隐藏文件、同批 raw 和二进制附件，不扫描 docs/references/运行环境。默认 `whole_root` 仍保留。

```powershell
python -X utf8 -B -m tools.wiki_runtime.evidence.integration_cli inspect-baseline --wiki-root <实际项目根>
python -X utf8 -B -m tools.wiki_runtime.evidence.projection_cli preview-wiki-changes --wiki-root <实际项目根> --source-root <原件根> --context <context.json> --knowledge <knowledge.json> --request <preview-request.json> --candidate <candidate.json> --payload-root <库外payload根> --baseline-scope knowledge_content
```

这里 G0–G2 绑定真实根中声明范围，物化只复制该范围，返回前重检实际文件与目录。不是全仓库文件基线，也不是正式 Executor 准入。每次最多 512 项、基线 4 MiB、单文件 1 MiB；超限停止，不裁剪库。实际 Health 还会读前后知识基线，不把视图读取计数当整个系统 IO。

检查实际 payload：内容页证据、frontmatter／正文双通道反向边、index／log／overview／raw index 和整组 pending_review 都应在候选里。之后走已有维护入口的实际 Reviewer／Executor 门禁。`non_teaching` 表示不需学习，不能当正式放行。严格 Native 缺认证时继续关闭；用户 approve 才能迁移 processed。

## 4. 学习约定、上传物与显式接线

K1 形成 brief，复用已有用户要求及范围内委托。认可附件绑定实际要求全文、主体、目标／排除项和节奏。`operator_supplied` 只证明操作者提供了一份记录，不认证真人同意；真实审阅者仍须核对其语义。知识包不反向依赖 brief，一个知识包可给不同课程复用。

外部 Agent 编写讲义或选原文副本，物化原生 prepare.json；用 K3 `build-learning-projection` 输出待审映射，实际完整审阅每份上传 artifact 及目标覆盖。新事实回 K2，超范围回约定。最终须 `projectionState=reviewed_for_scope`，不能只看 result 或 READY。

新增接线文件 `knowledge-preparation-connection/1` **封闭字段**：

```json
{
  "schema": "knowledge-preparation-connection/1",
  "wikiRoot": "实际库根",
  "sourceRoot": "原件根",
  "projectionRoot": "私有课件包根",
  "recognitionRoot": "原始要求依据根",
  "context": "context.json",
  "knowledge": "knowledge.json",
  "brief": "brief.json",
  "request": "projection-request.json",
  "recognition": "recognition.json",
  "review": "projection-review.json",
  "previous": null,
  "prepare": "prepare.json",
  "operationReview": null
}
```

除 `prepare` 相对 projectionRoot，其他相对定位均相对接线文件目录，也可使用显式绝对定位。没有认可／审阅时相应字段可 null，检查会阻断；`previous` 沿显式历史链继承，不是全局注册。接线是操作者配置，不是密钥或身份签名。

```powershell
python -X utf8 -B -m tools.wiki_runtime.evidence.integration_cli check-preparation --knowledge-preparation <connection.json>
```

准备好具体实际发送数据、目的地与费用范围，再按用户已授权范围使用原 I3 CLI：`publish-inputs`、`create` 增加 `--knowledge-preparation <connection.json>`，原部署／state／budget 参数照用。guard 在真正 POST 前重读 K1／K2、认可、投影观察、实际 prepare／原文／artifact，比较实际 manifest、corpus、上传 bytes 和 create.intent。初始 guard 不替用户授权新资料外发，也不认证宿主角色。

受控绑定进入请求 semantic 摘要。已受控 corpus／activity 换请求 ID 或省略接线不能降级；历史未接入入口仍兼容，结果标 `legacy_not_integrated`。复用旧语料时受控操作创建新的**本地复用回执**并引用原 KB，零上传，不改旧请求。新 brief 可以复用同一 corpus，并使用本次已审 manifest 的语言／深度及实际 intent，不能继承旧 header 冒充新约定。

## 5. 后续提案／目录／题目和实际内容

受控 activity 的 confirm-proposal、confirm-spine、prepare-quiz 必须另外审**本次实际 payload、scope、activity、book 和 expected_revision**。传 null 确认上游当前对象无法固定被审文本，受控路径拒绝；先读取并核对真实提案／目录，再使用显式对象。

把待发送参数按下列封闭形状保存，scope 来自真实 I3 部署／回执，payload 必须等于对应原生请求的完整 body：

```json
{"operation":"confirm-proposal","activityId":"实际activity","scope":{},"payload":{"book_id":"实际book","expected_revision":1,"proposal":{"实际字段":"实际审阅内容"}}}
```

```powershell
python -X utf8 -B -m tools.wiki_runtime.evidence.integration_cli check-preparation --knowledge-preparation <connection.json> --production-request <actual-step.json>
```

向真实审阅者提供输出 `productionReviewRequest` 及实际内容，保存 `learning-production-review/1`：schema、id、requestDigest、reviewedBy、recordedAt、decision、reason、assurance；decision 为 reviewed_for_scope、assurance 为 operator_supplied。将接线 `operationReview` 指向此观察，再用原 CLI 加接线调用。请求 semantic 冻结 reviewRef，完整 request／观察存现有 audit；实际 POST 前重检，不能换一份 accepted 观察冒充原审阅。

初始映射审的是输入，步骤审阅审的是提案／目录／题目请求，实际生成课件另走 I4。已审正文可参考原 [课程准备](../../../tools/learning_book/PREPARATION.md) 的原生 insert-block/update-block 方式，避免重复整章生成；**这些原生编辑接口不在本次 I3 guard 内**，须逐次保存真实请求／响应并审正文、版本、基线，不能声称新链已统一保护全部写入。没有现成高层受管编辑操作时，不自行调用未审原生接口凑验收。

## 6. 回顾、纠错与恢复

用户请求后显式运行现有 [I5](../../../tools/learning_book/HANDOFF.md) `export-results`，不需模型预算；先 `verify-handoff` 再读原作答、所选公开会话、基线和覆盖。没有常驻外部 Agent 也可执行；结束声明、分数和 READY 都不证明掌握。当前 K1 尚未自动读 I5 形成背景，人工规划须保留原引用及 unknown，不自造可写用户画像。

错题或聊天新结论先作为待核验输入，取实际题／原答案／基线及用户原话，查原文后再进入 K2。不得直接从聊天写正式事实，也不覆盖原答案或旧基线；修正课程走新版本／I4，修正知识走候选及原维护规则。当前新 guard 不提供全套来源撤回传播或权威掌握评估。

外部写入超时或中断，先 `show`／`reconcile` 原 ID。已保存完整响应可恢复，dispatching／uncertain 不盲目重发或换 ID。`recover-inputs` 的 reindex 也是新增 POST，受控请求须重新提供有效接线。只读查看历史事实不要求今日依赖仍有效，也不重置预算。确定失败再按原 retryOf 关联；原采集、失败候选及修订次数均保留。

历史验收见 K4 记录（未随公开仓库附带）；随后连接修订的当前操作见下节及整合修复记录（未随公开仓库附带）。
历史验收见 K4 记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k4/README.md）；随后连接修订的当前操作见下节及整合修复记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-integration-fix/README.md）。

## 7. K4 后连接修订：接收、续接与依据搬运

标准 `host import-package` 产生的是引用抽取文件的 raw 薄记录。对应 preview-request 的 rawBindings 使用 `bindingMode=managed_extracted`：核对薄记录、source-package、完整原件／附件／抽取字节及 complete 质量，K2 Source 对应实际抽取正文。whole／body 仍用于原文直接在 raw 的情况。PDF／OCR／模型抽取及 partial 不因换成此模式自动放行。

知识候选通过 preview 后，可由 owner 入口直接接收同一 candidate，无需重新运行 Worker：

```powershell
python -B tools/wiki_runtime/cli.py host adopt-knowledge --root <知识根> --state-dir <库外同卷状态根> --operation-id <原candidate.operation_id> --context <context.json> --knowledge <knowledge.json> --candidate <candidate.json> --request <preview-request.json> --source-root <原件根> --payload-root <原payload根> --baseline-scope knowledge_content
python -B tools/wiki_runtime/cli.py host inspect --root <知识根> --state-dir <同一状态根> --operation-id <同一ID>
```

接收重新验证当前 K2、raw 和候选，冻结 payload、原页差异及知识依据，用既有 HMAC pending 保存。inspect 返回已保存状态、独立意见及 K2 内容；`currentValidation` 单列当前是否失效，不能把可查历史当成当前通过。原 payload 后续修改不改变接收副本。操作属于 Runtime 新世代，不会被 cutover 误判为旧遗留操作；这不等于已获得正式准入。

需要咨询性内容审阅时，可信 Python 宿主可用 `StandaloneHost.review_knowledge_candidate(id)` 复用其 transport；可选 API CLI 为 `host review-knowledge`，同样提供 root/state-dir/operation-id 及 model-config。真实外发须已覆盖本次原文和候选；离线接收与 inspect 不需要模型。Reviewer 复用现有 Invocation、持久预算及未知调用不重发；不调用 Worker 再造正文。结果只到 `reviewed_for_transfer`／`needs_changes`，**不是 G3 凭据或 ready_to_apply**。未建立专用准入时 apply／recover 返回 knowledge_admission_required，approve 仍拒绝；新增非教学知识事务操作见下节，不走 derived 或教学 Admission。

资料索引或相关页面合法变化后，重新完成受影响的 K1/K2／约定附件／投影审阅，保持原上传 manifest、学习目标、范围、节奏和前置条件，再为已创建活动申请准备续接：

```powershell
python -B -m tools.learning_book.cli revalidate-preparation --deployment <部署配置> --state-dir <原I3状态根> --activity <原activity> --continuation-id <新ID> --knowledge-preparation <重新审过的connection.json> --expected-revision <当前书revision> --reason <依赖变化原因>
```

此操作只读远端确认同一书的 revision，不调用模型或课程 POST；先返回 `needs_review` 与 `reviewRequest`。真实审阅者核对新旧准备后提供 `learning-preparation-continuation-review/1`，字段为 schema、id、requestDigest、reviewedBy、recordedAt、decision、reason、assurance；decision=reviewed_for_scope、assurance=operator_supplied。再次用相同参数加 `--review-file <观察>` 接受，追加不可变记录。原 create、原书及旧审阅保持原字节，不删除 guard，不重建课程。未决生产请求须先对账；后续 confirm/quiz 仍分别审实际 payload，并匹配当前续接链。

续接最多 32 条；同 ID 只在相同当前前提下重读，不承诺书 revision 已变化后重跑旧命令仍成功。范围、原上传材料或 header 改变另走课程版本／新活动与 I4，不能靠续接偷换；本操作仅修复依赖演进后的继续能力。历史链通过 I4/I5 的准备引用读取。

受控复用现在为新回执保存独立冻结 inputs，仍不向远端重复上传。新接线请求另存至多 4 MiB 的不可变准备附件：完整映射、brief、认可原话、已审知识／Evidence 摘录、审校记录和最多 5 篇实际已读旧页的原字节文本快照；旧页按实际 byteDigest／bytes 核对，不用虚构正文补定位。底层完整原件继续 external，不复制整库。I4 绑定 origin/active 及续接链；I5 搬运必要附件并核对引用、字节与实际对象。另一个 Agent 可从交接找回学习目标、Claim/Evidence 与旧页对照，不必依赖原准备目录；`sourceOriginalsVerified=false` 保留，不从离线完整性推导真实语义或掌握。

新 verifier 仍接受没有该扩展的历史交接包；消费带准备附件的新包应使用更新后的 verifier/schema。历史已接线请求若从未留存附件，不回填伪造通过，I4 明确 partial；原未接线 legacy 课程按原保证级别保留。以上均不改写原答案、学习进度或既有基线。

## 8. 专用知识准入与正式事务

代码已接线，临时库验收状态以当前执行交接（未随公开仓库附带）为准；不得把实现存在当作已授权对当前真实资料写库。
代码已接线，临时库验收状态以[当前执行交接](../../../docs/design/knowledge-candidate-admission-handoff.md)为准；不得把实现存在当作已授权对当前真实资料写库。

纯知识整理推荐 `preview → adopt-knowledge → admit-knowledge → apply`。不需要先调用咨询 review-knowledge，最后由 Executor 做一次正式 G3。若另做咨询审阅，两次分别计费、共享 adopt 时固定的总预算；咨询意见不直接升格正式凭据，已有修改要求会阻止同候选的新提交。

```powershell
python -X utf8 -B tools/wiki_runtime/cli.py host admit-knowledge --root <知识根> --state-dir <同一状态根> --operation-id <同一ID> --authorization-reason <宿主实际收到的本次整理授权说明> --sequence knowledge_only
python -X utf8 -B tools/wiki_runtime/cli.py host apply --root <知识根> --state-dir <同一状态根> --operation-id <同一ID> --model-config <已授权的模型配置>
```

admit 是可信 owner／已授权应用宿主入口，不是对外模型工具。authorization-reason 只记录授权依据，任意文字、candidate.intent、confirmed=true 或 operator_supplied 不是身份凭据；可信调用者必须先有本次用户任务授权。新协议维持当前本地可信宿主保证，不宣称对抗同权限恶意进程。`sequence` 必填；当前知识入口只接受 knowledge_only，learn_first 明确停止，不能把未知学习状态当已完成。

可信 Python 宿主使用 `StandaloneHost.admit_knowledge_candidate(id, authorization_reason=..., sequence='knowledge_only')`，再 `apply_pending(id)`，复用已有 transport。admit 本身无需模型。只读／接收／admit 不代表获得新的真实 API 外发许可；调用前仍须覆盖实际原文及候选和费用。

默认使用完整 knowledge_content，必须在 adopt 时选定；旧 whole_root 接收记录不在正式知识准入支持范围，不能改原 operation 的范围来续接。范围内递归 wiki/raw、AGENTS 与规则映射，原件质量、K2、旧知识及 G0–G3 都重检；范围外 references／环境不参与此轮知识基线，也不允许候选写入。512 项／4 MiB 等既有边界仍保留，超限停止而非裁剪库。

准入绑定原 operation／候选／manifest／准备依据／授权／内容范围，以及 Runtime Task／Run、policy、epoch、ownership。现有字段 learning_task_id 仅作为 Runtime 关联 ID；此路径不创建 learning_states、Readiness 或教学 Admission。新提交前、最终接受锁内检查有效性；模型期间来源变化、撤销或当前负面意见均阻止 prepare。咨询回包在短 OS 接受锁内重读合并，保留其他 Host 的授权，不用旧记录覆盖。

apply 仍由原 Executor WAL 批量写入，raw 状态最后成为 pending_review，不能签发 reviewed_at 或移动到 processed。独立 approve 及用户对批次的明确确认不由本操作代办。inspect 的 knowledgeAdmission 分列准入／真实执行与是否还需动态校验；已有实际终态时 status 显示 applied／recovered，内容咨询状态保存在 contentReviewState。formalWriteAuthorized=false 不是执行历史被否认，而是 inspect 不签发新的写权限。

真实调用超时记 unknown，迟到结果不能覆盖，不换 ID 自动重发；可确定的 Reviewer error 意见也持久保留，不因重新 apply 重发。成功同 ID 返回原 WAL 事实。发生 recovery_required 则 `host recover` 原 ID；恢复与终态重放可以不提供模型配置，沿原 WAL 的范围与备份执行，不重新审阅或重新授权，外部编辑冲突会保留并报告。撤销停止新提交，不阻止已经接受批次的恢复。

这里沿用 Runtime 的调用次数、字节、时间等预算与 transport 用量可见性，未知 tokens 不记零；不重设或自动代扣 DeepTutor 的既有费用账本。RuntimeStore 备份保留新增准入领域表，但该数据库 package 单独不包含 Host pending、Executor WAL 与备份文件；整套 Host 恢复仍须保留原状态目录。此次故障检查使用原状态目录重启，未宣称仅凭数据库 package 恢复全部事务文件。
