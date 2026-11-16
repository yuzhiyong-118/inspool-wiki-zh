# K0：知识准备接口与可执行协议核对

> 公开设计摘编：保留通用契约与方案；历史验收、用户反馈、运行记录及本地素材不随仓库发布。设计条目不代表部署或验收完成。

## 2. 最小文件与数据所有权

每次准备工作区只增加两个业务记录及可引用的观察附件：

| 记录 | 保存内容 | 何时形成 |
| --- | --- | --- |
| learning-brief.json | 学习约定正文和对背景观察的引用 | 有成课意图时；不需要先有知识包 |
| preparation-map.json | 约定、知识包、核验报告、prepare 归一化内容、实际意图与覆盖的关联 | 知识审校和约定就绪后；无成课时不强制存在 |
| observations/ 下的明确附件 | 背景观察、用户认可依据、知识审校及其作用范围 | 按实际证据形成，不虚构统一认证机制 |

KnowledgePackage、原文、prepare.json、I3 回执、I4 基线和 I5 结果包继续使用各自现有格式。新记录引用这些产物，不复制原始作答、课程正文或 Claim 成为新正本。操作回执由现有宿主／应用能力保存，工作区不添加第二套调度器。

新记录使用 camelCase，引用旧 KnowledgePackageRef 时原样保留 package_id/version/digest。工作区文件路径只是定位信息；稳定 source locator 使用逻辑标识，通过本次 locator 清单解析到文件。不能把可移动文件路径混入来源身份；同逻辑标识的新字节必须新版本。


## 3. 学习约定正文与认可附件

约定正文的版本化类型为 learning-brief/1，包含下列字段。实现时字段封闭，非法或未知值拒绝，不能静默降级。

| 字段 | 约束 |
| --- | --- |
| schema、briefId、version、learnerId | schema 固定；稳定 ID 和本次学习者标识非空；version 为正整数。learnerId 是作用域标识，不是认证凭据 |
| goals | 非空数组；每项 goalId、outcome、checkMethod，ID 唯一，目标写成可完成行为 |
| backgroundRefs | 相关观察引用数组；允许为空，空时按 unknown 规划 |
| prerequisites | 每项 topic、observationRef 或 null、handling；handling 为已知可用、计划补讲或待澄清，不自带掌握度分数 |
| included、excluded | 本轮范围及排除项，字符串数组；included 非空 |
| pacing | sessionMinutes、totalMinutes 为正整数或 null，depth 为 brief／standard／deep；未知时间须在认可依据中说明采用的明确默认或进一步澄清 |

BriefRef 为 briefId/version/digest，digest 仅计算正文。正文不内嵌认可或 confirmed=true，避免认可引用正文又成为正文摘要一部分的循环。draft／needs_clarification／confirmed／superseded 是应用根据当前正文、认可与替代关系得出的状态，不由任意包字段自行授权。

认可附件至少记录 BriefRef、原始用户要求或委托的定位与字节摘要 evidenceRef、提交者、用户归属 attributedAuthor、时间、具体覆盖范围 scope、被认可的实际成课目标 acceptedIntent、明确默认值及 assurance。attributedAuthor 与本次 brief.learnerId 一致，背景观察的 subject 也须对应同一学习者；字符串相同只证明记录作用域一致。当前可提供的人工／操作者记录使用 operator_supplied，不能称宿主已认证。K3 必须由实际调用环境解析认可依据；没有实际依据、范围越界或关键项未明确时留 needs_clarification。合成 fixture 中的 user 字符串只表示测试内容，不证明真人已认可。

用户要求与课件传输授权分别核对。mapping.intent 必须等于认可附件的 acceptedIntent；实际 create.intent 或提案变更如改变目标、范围或量级，更新约定。等价措辞由已有认可范围与转换说明导出新的 acceptedIntent 记录，无须重复询问；不能只重算摘要就自行扩大认可范围。发布检查读取实际 I3 请求中的 intent 与确认 payload，不能只检查建议 learningGoal 或本地计划值。原生 API 200 仅证明操作事实。

背景观察最少记录 observationId、subject（当前用户／任务明确的学习者）、topic、basisType、evidenceRefs、observedAt、applicableVersion、planningUse 和 limitation。basisType 限 material_available、user_report、practice_record、learning_record、unknown。planningUse 限 connect_background、propose_brief_review、use_within_evidence_scope、plan_supplement、clarify。material_available 只能用于连接背景；不得依据它签发 mastered 或自动跳过关键前置。主题／主体／时间／版本不匹配时维持 unknown 或补讲。


## 4. 知识与课程的交付映射

preparation-map/1 的必需内容如下，K3 对实际输入重新核对：

| 字段 | 含义与检查 |
| --- | --- |
| mapId、version、schema | 不可覆盖的本次映射身份及版本 |
| briefRef、recognitionRef | 指定约定版本与认可附件摘要；学习投影必有，纯知识任务没有此记录也可推进 |
| packageRef、reviewRef | 旧 KnowledgePackageRef 与指定范围审校附件引用；审查自报不替代独立维护 G3 |
| prepareRef | 原生 packageId 加 normalizedManifestDigest；摘要来自 validate_package(...).manifest，包含语料身份、建议目标、来源与输入元数据，排除定位路径 |
| projectionReviewRef | 对实际上传投影的审校附件引用，绑定本次 packageRef、prepareRef、被审 artifact 身份／字节摘要、判断者／依据／范围；不能只审原件或知识包 |
| intent | 即将实际提交 create 的目标文本；映射摘要绑定它，不以 learningGoal 代替；业务核对其与约定是否一致 |
| sourceBindings | 按实际 prepare 的 sourceId/sourceVersionId 唯一且精确覆盖上传来源，不能要求覆盖知识包的全部来源；共用 mode、sourceId、sourceVersionId、byteDigest。direct_source 另含 knowledgeSourceRef（source_id/version/content_digest）并要求对应原文字节相等；authored_projection 将讲义自身作为 I3 原件，底层依据通过 coverage 引用，不要求全部上传 |
| coverage | 每项绑定 goalId、非空 claimIds、evidenceIds、artifactId、教学处置与范围理由；引用必须属于本次固定输入 |
| excludedClaims | 未进入课程的 Claim 及理由，不因排除而改写知识包状态 |

映射整体使用既有 JSON 摘要规则。coverage 中的 goalId 集合应完整覆盖约定 goals，选读项另列理由；goal 与 claim 的语义匹配仍需准备者审校，程序检查引用存在不等于意义吻合。每行 artifact 对应的 Claim／Evidence 须存在有效支持关系并处于知识审校范围；直接来源模式下 Evidence 的原文来源必须对应该 artifact 的 sourceBinding。编写讲义模式通过 coverage 关联一个或多个底层来源，不把讲义自身当作支持自身事实的证据。

sourceBindings 不允许重复或将同一知识来源重复映射冒充独立来源。未选 Claim／Evidence／来源仍保留在同一知识包；仅使用局部内容不应强迫上传无关原文或复制知识包。每个实际上传 artifact 均须被投影审校覆盖，包括 direct_source 模式下可能已清洗／改写的 artifact；审校核对实际上传字节而非只核对 source 字节。讲义编排、忠实改写不额外生成知识包；新事实、条件扩大或新判分依据必须返回知识准备。

知识 Source.content_digest 与 Evidence.source_digest 都绑定原文字节；EvidenceClaimRelation.evidence_digest 则绑定 Evidence 整条记录。不要将 source_digest(source_record) 的结构摘要填进 Evidence.source_digest。

审校附件绑定 packageRef、实际审阅的 Claim/Evidence 范围、判断者、decision、理由、依据 basisRefs、comparisonRef（未比较旧知识时为 null）与 assurance。旧包 ExistingKnowledgeRelation.target 只含目标文本，不能单独证明旧页未变化。comparison 附件保存实际查询／覆盖、已读页面的稳定标识与字节摘要、当前定位、读时间及未读项；审校通过 comparisonRef 绑定它，发布前重验实际已读依赖。旧页改变或不可读使相关比较／审校 stale；新发现页面可能触发补查，原查询不能声称全库不存在。

原协议的 evidence_status=supported 或 verification_status=verified 是数据声明，不是认证。选作确定答案的 Claim 须有相应范围的有效审校、完整原文证据与支持关系，且无未决冲突；引用／摘录检查与语义审查分别记录。投影审校独立绑定实际 inputArtifacts 的摘要，不复用既有课程的 I4 质量报告冒充新投影已审。

发布前核对当前原文字节、包摘要、约定认可、投影与映射。I3 活动映射随后记录实际 bookId 和请求；I4 绑定实际课件，不预先塞入 preparation-map 造成反向依赖。新增章节和题目若引入新事实或改约定，退回对应准备环节。


## 5. 应用操作与执行入口

以下接口名是 K1–K4 的实现目标，当前没有创建空实现或注册能力。先用普通 Python 应用模块及 CLI，未来 MCP／网页共用，不要求常驻服务。

| 操作 | 输入 → 输出 | 失败／副作用边界 |
| --- | --- | --- |
| inspect_context | 材料定位、wiki 索引、有限检索参数、可用学习证据 → 背景观察、覆盖及缺口 | 只读；不可读保留 unknown；不访问未选会话或整库外发 |
| draft_learning_brief | 用户意图、背景观察 → 约定正文、需澄清项 | 私有草案；不自行生成真实认可 |
| prepare_knowledge | 明确整理意图、原件、局部既有知识 → KnowledgePackage、核验观察 | K1／K2；真实采集／语义调用按宿主能力处理；不自动改正式库 |
| build_learning_projection | 正文及认可、已审知识与实际 intent → prepare.json、preparation-map、检查结果 | K3；仅私有产物；缺证、缺认可或 stale 不发布 |
| inspect_release | 实际 I3 回执、课件与审校、I4 基线、准备映射 → 发布检查 | 分别报告结构、语义与内容一致性；本操作不生成课程 |
| review_learning | 指定活动、公开会话选择、导出声明 → 既有交接包引用、表现／纠错观察 | 显式调用 export-results、verify-handoff；不改变原作答／进度 |
| preview_wiki_changes | 知识包与覆盖说明 → 既有 CandidatePreview | 私有预览；正式应用交现有审查、授权和 Executor，不伪造 L2 |

inspect_context 与 draft_learning_brief 可形成约定而不先调用 prepare_knowledge；prepare_knowledge 也可没有约定独立整理知识。只有 build_learning_projection 同时消费两者。候选预览不是创建正式 sources 页，持久原文采集亦是独立副作用。


## 6. 检查结果与恢复语义

K1–K4 操作统一返回 result、findings、artifactRefs、nextAction，具体封闭字段在首个实现时按本文件固定。result 限 ready_for_review、needs_clarification、needs_evidence、stale、rejected、uncertain；ready_for_review 表示机器检查可供审阅，不是内容已正确或拥有写权限。

| 条件 | 必须保留的结果 |
| --- | --- |
| 用户意图不足／认可范围不符 | needs_clarification，不深入成课 |
| 原文缺失／partial／无支持语义 | needs_evidence，不能生成确定答案 |
| 已引用原件或约定／包／投影变化 | stale，报告具体变化和受影响引用 |
| 同 ID／版本不同内容、非法路径或引用 | rejected，不覆盖旧记录 |
| 外部调用已发送而结果未知 | uncertain，保存原调用身份；不换 ID 重发 |
| 私有分析可用但正式入口不可用 | 私有产物如实保留；正式应用未验收，不伪造整体成功 |

解析与确定性重检不消费模型预算。真实调用走既有调用管理，不重复扣费；宿主用量不可见记 unknown。文件发布复用现有原子写工具及不可变版本习惯，但本次接口设计不承诺跨服务原子事务。


## 7. 离线核对与放行边界

使用合成样例（未随公开仓库附带）和可执行核对脚本（未随公开仓库附带）检验：旧包与新映射可对接、真实字节／定位／目标覆盖能对应、现有校验器的拒绝项与未覆盖项被如实记录。脚本不实现生产认可或语义门禁；任何传入的 user／reviewer 字符串都不能授权。

运行：

```powershell
python -X utf8 -B tools/tests/verify_knowledge_preparation_k0.py
```

离线脚本通过只证明固定样例和旧协议边界，不证明新流程已接宿主、已完成目标适切性评测、原文支持语义已机器认证或用户实际掌握。K0 独立复审与修订关闭已完成，可以开始 K1；不能据此将 K1–K4 或 A01–A33 业务验收标为通过。
