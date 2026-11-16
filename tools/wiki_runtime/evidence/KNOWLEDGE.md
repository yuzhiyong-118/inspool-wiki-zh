# 知识包与范围审校操作（K2）

knowledge.py 提供 prepare_knowledge、verify_knowledge、partition_knowledge；knowledge_cli.py 提供前两项的只读命令。复用现有 package_protocol.py 和 K1 实际已读 context，不改它们的协议，不初始化执行器、数据库或常驻 Agent。程序不调用模型、采集网络、发布课程或写正式 raw／wiki。

## 使用与结果

```powershell
python -X utf8 -B -m tools.wiki_runtime.evidence.knowledge_cli prepare-knowledge --wiki-root <含wiki的项目根> --source-root <原件目录> --context <context.json> --request <knowledge-request.json> [--review <review-observation.json>] [--previous <prepared.json>]
python -X utf8 -B -m tools.wiki_runtime.evidence.knowledge_cli check-knowledge --wiki-root <含wiki的项目根> --source-root <原件目录> --context <context.json> --prepared <prepared.json>
```

JSON 仅输出 stdout，由调用者保存到明确的私有目录。退出码 0 仅表示 operator_supplied 的 reviewed_for_scope；缺审、缺证、语义拒绝、失效为 2；非法／不可读输入为 3。两种零都不能授权正式写库。Python 调用抛 PreparationError 或旧协议 ContractError；CLI 将输入错误转换为通用 JSON，不回显原件／配置或 traceback。

result 复用 K0 约定；knowledgeState 进一步区分 needs_review、needs_evidence、rejected、reviewed_for_scope、stale。缺审时 result=ready_for_review 只是“可供审阅”，**必须读取 knowledgeState**。claimChecks 保留各主张的 blockers、pending、实际支持 Evidence 和 answerUse；scoped_candidate_only 仍须经过后续投影及实际课件审校，不是最终答案认证。缺少完整支持的确定性缺口先记 needs_evidence；完整候选仅缺审查时保留 needs_review。范围、语义支持与来源有效性由指定审阅者负责，不从 verified 字符串推导真实通过。

每个 prepared 同时绑定 contextDigest、原包、comparison、reviewRequest、实际 reviewObservation、来源依赖声明和 reportDigest。verify_knowledge 会重读 K1 实际依赖，再重新组装和比较所有结果；重算外层 hash 不能直接将 claimChecks 改为通过。它不是签名，操作者仍可提出新的语义观察；assurance 始终保留 operator_supplied，formalWriteAuthorized=false。

## 提案字段

knowledge-preparation-request/1 的封闭字段：

| 字段 | 约束 |
| --- | --- |
| schema、packageId、version、intent | schema 固定；稳定包 ID、正整数版本、明确整理意图；不要求有课程或学习约定 |
| evidence | 最多 40 条旧 Evidence 完整记录；source_digest 为原始字节 SHA-256 |
| claims | 1～10 条旧 Claim；保留归属、条件与自报 evidence_status |
| relations | 最多 80 条旧 EvidenceClaimRelation；evidence_digest 是 Evidence 整条记录的 JSON 摘要 |
| conflicts | 最多 10 条旧 Conflict；主张及证据非空且相互有关联，空范围不被当成“不影响任何主张” |
| existingKnowledge | 最多 30 条旧 ExistingKnowledgeRelation；target 必须解析到 K1 实际已读的当前 locator 或唯一 pageId；歧义不猜测 |
| sourceObservations | 精确覆盖本次 K1 来源；字段见下表，不改变 Source 旧协议 |

Source 从本次实际 context 构造：source_id、version、原字节摘要和完整可读行范围；locator=source:<sourceId> 是逻辑定位，磁盘路径仍在 context。不同包可共用同一原件。请求 JSON 上限 1 MiB，prepared 上限 2 MiB，CLI 各文件输入上限 2 MiB；保留 K1 单次文件／目录／重读限额。准备前和返回前各重验一次 K1 依赖，属于协作读取，不是跨文件原子快照。

sourceObservations 每项封闭字段为 sourceId、canonicalLocator、sourceType（first_party／report／repost／unknown）、topics 字符串数组、publishedAt（文本或 null）、acquiredBy、originId（文本或 null）、upstreamSourceIds、basisEvidenceIds、reason。未知上游用 null，外部共同上游可用逻辑 originId，本批上游可用 sourceId 引用；循环／自引拒绝。已知 originId 必须引用本批真实匹配的 Evidence 作为声明依据。日期、规范定位和采集方式仍是操作者记录，不认证原始 PDF／OCR、现实身份或完整采集过程。

共同 originId、批内上游关系及完全相同原字节会合并声明分组，关系传递合并；不把转载数当独立佐证。independentCorroborationCount 始终为 null；没有独立性认证，不给网站打永久信用分，不据此常规启用网站。工具 T、来源 S、主张 I 的完整治理仍待后续实际接入。

包的 ID／版本／摘要历史沿显式 previous 链继承，最多 256 项，禁止同包同版本改内容；没有 previous 不知道别的调用历史，不称全局注册或强制不可变存储。原件身份与历史由 K1 负责。修改旧页、索引、目录选择、来源字节会 stale；重新阅读产生新观察，不能无声地给旧审校换绑定。

## 行号与摘录

原字节摘要永远由 read_bytes 得到，不做 Unicode 或换行归一化。行视图仅将 CRLF 视为 LF，按 LF 分行，行号从 1 开始，end_line 包含在内。文件末尾的一个终止换行不增加虚构空行；连续末尾空行仍计算实际空行。裸 CR、BOM、组合字符、空白与 Unicode 行分隔字符不特殊处理。

Evidence.excerpt 必须恰好等于所选完整行以 LF 连接的文本；不得修剪空白、增删省略号、拼接不连续行、改写或搜索后移动行号。部分引用请分别建立 Evidence 或选择能完整引用的行。extraction_state=partial／failed 与 source.complete=false 均不能提供完整支持。真实摘录只证明文字存在，仍可能不支持 Claim。

## 语义审校观察

程序先返回 knowledge-review-request/1，绑定旧 packageRef、contextDigest、comparisonRef、sourceObservationsDigest、intent 和实际范围，外部审阅者读取对应 context 全文、原包与旧页后提供观察。它不自动调用真实 Reviewer，不把任意 callback 当已接入的宿主能力。

knowledge-review-observation/1 的封闭字段：schema、id、requestDigest、reviewer、recordedAt、assurance（仅 operator_supplied）、非空 basisEvidenceIds，以及下列六个数组。允许逐步补审；遗漏项保持 needs_review，不能用空数组跳过实际已读页。

| 数组 | 每项字段及语义 |
| --- | --- |
| claims | ref=claim_id、decision=reviewed_for_scope／needs_evidence／rejected、reason、conditions（精确绑定 Claim 条件） |
| relations | ref=旧关系整条 JSON digest、decision=accepted／out_of_scope／needs_evidence／rejected、reason；审阅摘录实际是否支持／反驳／限定主张及版本范围 |
| conflicts | ref=conflict_id、decision=resolved_for_scope／unresolved／needs_evidence、reason、safeClaimIds、basisEvidenceIds；后两者必须位于该冲突实际范围；旧记录 resolved 文本不等于已审解决 |
| comparisons | ref=旧知识关系整条 digest、decision=exact_duplicate／related／new／condition_difference／version_change／corrects_old／unresolved／insufficient、reason、basisEvidenceIds、oldEvidence（locator、start_line、end_line、excerpt）；旧页摘录也核对实际文字 |
| sources | ref=source_id、decision=reviewed_for_scope／unknown、reason；只对当前原文与用途负责，不能签发网站认证 |
| documents | ref=实际已读旧页 locator、decision=relations_complete／irrelevant／needs_evidence、reason；说明已检查本页与全包主张的关系或排除理由。relations_complete 必有实际旧知识关系，irrelevant 不得同时带有关联关系 |

comparison 固定实际查询、已读页面身份／字节／定位、覆盖与未知边界；comparisonChecks 单独展示逐页语义覆盖。没有命中或读过的页被判 irrelevant，都不能推出整库不存在。新证据可以按真实依据纠正旧摘要；不能凭旧页地位或多个转载投票。条件／版本差异要记录理由并修订相应 Claim／关系范围；未决旧知识冲突保持阻断。针对同版本的 corrects_old 是审阅者明确判断，不会自动改旧页，也不证明旧页背后全部原始来源已被复核。

接受的支持必须有完整匹配原文、范围相符的关系以及 Claim／关系／所用来源的审校；接受的限定若未落实到 Claim 条件会阻断。接受的反证在没有已审解决记录时阻断。未决冲突影响的 Claim 不能作为确定答案；不删除反证来让包“通过”。某项关系 out_of_scope 或 rejected 的语义正确性仍由审阅者负责，程序只保留有绑定的判断。

实际审校范围和决定不能从 JSON 格式推导为独立可信 Reviewer 身份。当前应用接受操作者提供的审阅记录；任意声称 host_authenticated、G3 或 pass 的 assurance 均拒绝。缺少可用真实审阅时保留 needs_review，不调用付费模型凑通过。

## 显式分包与边界

partition_knowledge(prepared, claim_ids, package_id=..., version=..., reason=...) 产生新的请求草案及 parentReportDigest、parentPackageRef、excludedClaimIds、reason。调用者保存该分包附件和原报告。要求新包 ID，选取严格子集，不能选择任何仍列于冲突中的主张；全部原件、Evidence 和来源观察保留，避免丢弃反证／上游。该函数只做草案，必须重新 prepare 并审校新 reviewRequest，不继承旧通过状态。需要调整有争议主张时直接提出有完整依据的新版本，而非借此助手隐藏冲突。

K2 不实施学习认可／投影、prepare.json 导出、候选 preview、网站采集、正式接受或学习反馈适配；这些按 K3／K4 及既有维护入口推进。新语义内容由外部 Agent 负责；当前宿主主／子 Agent token 用量不可见记 unknown，应用模型 API／网络调用为 0，不改已有 DeepTutor 账本。已有课程授权不自动覆盖新资料外发。

完整样例、实际 CLI 输出和独立审查见 K2 验收（未随公开仓库附带）。K1 入口仍见 [README](README.md)，其历史绑定文件未改。
