---
type: meta
title: 知识与学习系统端到端职责及接口核对
status: design_integrated_implementation_pending
updated: 2026-11-12
topic: 操作矩阵、身份桥接、课程版本、来源演进与实施依赖
---

# 知识与学习系统端到端职责及接口核对

出题专题的后续设计增补见[题目生产与审查方案](learning-question-constraint-plan.md)与[实施任务书](learning-question-implementation-tasks.md)。publish-quiz／规格绑定是拟新增能力，不属于下文既有探针已证明范围。它必须贯穿 Production、准备步骤审查／continuation、原生入口、实际题版本、I4/I5 与安装恢复；新课整书完成仍复用 E1，已学内容纠错仍使用替代活动，不另建写状态。本文旧探针及摘要不因本次文档增补而更新或冒充新能力验收。

## 1. 审查对象和判断边界

本轮把[修订方案](knowledge-system-revision-plan.md)、既有[总体架构](research/upstream-learning/architecture-proposal.md)的职责约束，与当前项目应用模块、固定本地上游源码及补丁进行对照。旧文档是设计意图输入，不作为已实现证据；其他 Agent 的审查结论、旧测试数量和旧 acceptance 不作为本轮通过材料。

本轮新增探针 P01–P07，重新运行 G01–G13。原始结果见本轮补证（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-system-integration/README.md）。涉及上游的静态观察仅适用于本地固定源码及补丁；P07 另记录实际 import 的安装引擎路径与 SHA，不据此证明整个部署或所有 wheel 一致，也不代表上游最新版本。

当前结论：**总体职责可以保持，但上一份修订方案仍有连接假设需要纠正。本文件将它们收敛为明确接口和实施约束，未实施新功能。** 当前普通知识准入继续使用现有能力；新增 C2、受管课件编辑、来源影响报告与容量优化按工作包验收后开放。本文不是全仓每个函数、每种上游模式的安全审计。

## 2. 总体职责保持和本轮必要调整

1. 原文／wiki、私有准备物、课程状态、交接证据各有所有者。目录状态是展示或流程位置，不作为独立的事实／学习进度真值。
2. 外部 Agent 负责获取和较复杂准备，教学端主要消费已审资源；本地共享目录降低搬运成本，不合并权限。文件可读不等于模型可以把整库外发。
3. **纯 L 不强依赖 wiki Runtime。** 没有正式知识提交的用户学习任务，可以继续只用学习适配和独立 EvidenceStore；新业务任务契约只在受控知识提交、尤其 C2 时由可信 Host 持有。可选跨链关联不是所有学习的启动前提。
4. **课件编辑分为提交前和发布后。** 事后的 I4 检查只能发现与旧基线不同，不能代替发送前对实际编辑请求的核验。需要在已有 Production 中补受管编辑，不能靠裸 HTTP client 冒充已有门禁。
5. **已认可交付版本不原地改写历史。** 当前 I4 首次绑定不可替换，同活动新 snapshot 不能变成新的首次绑定。本轮选择先用新 activity／book 表达需要重新认可的课程版本，不强行在原活动上建设多套可写进度或重新绑定机制。
6. **C2 绑定已学习的冻结交付版本，不暗示“最新课程／最新网页”。** 已知的新冲突或当前任务依赖变化进入重核验；没有再次读取的远端来源只能报告未观察，不自称最新。

## 3. 端到端操作矩阵

“静态”表示本轮直接核对代码而未重跑该动作；“拟议”表示接口尚未实现。矩阵描述受管路径，不声称原生网页和同用户 shell 都无法绕开。表内 G／P 编号仅属于本轮补证。

| 操作 | 输入与应用入口 | 数据所有者／实际副作用 | 门禁与产出 | 失败、重放和覆盖依据 |
| --- | --- | --- | --- | --- |
| O01 收集 URL／文件 | 外部 Agent／宿主；微信专用 host；私有工作区 | 采集方保存原始字节，不自动写 wiki 或成课 | 来源、抽取方法、缺失和版本；通用搜索由外部能力承担 | 失败保留缺口，不把清洗摘要当原件；源码静态 |
| O02 采集包登记 | capture → host CLI import-package／derived.build_capture | 原 Executor 写 raw 薄记录、raw/assets、队列 | complete／原类型／抽取及附件校验；原始正文不改 | partial／PDF 停止或按实际支持处理；不是语义审阅；源码静态 |
| O03 查库与背景观察 | evidence.inspect_context／verify_context | 只读本次原件、索引、递归相关页，输出私有 context | 明确覆盖、未读、歧义；资料可用不是掌握 | 字节或选择依赖变化 stale；P04 |
| O04 核验知识 | prepare_knowledge／verify_knowledge | 私有知识包、来源／主张／关系／冲突观察 | 实际摘录绑定与独立语义审阅分别检查；共同上游分组不认证真伪 | 缺证／未决冲突不升为确定事实；来源观察局部 P06 |
| O05 学习约定 | draft_learning_brief＋认可附件 | 私有约定与认可依据；不写进度 | 目标、范围、节奏、前置条件，复用已有委托 | 不明确才澄清；当前不会形成新业务任务契约；源码静态 |
| O06 课件输入投影 | build_learning_projection／PreparationGuard | prepare、映射、实际上传讲义 | 绑定知识包、约定、认可、artifact 和目标覆盖 | 新事实回 O04，扩范围回 O05；当前步骤错误不隐式放行；G01/G05 |
| O07 知识候选接收 | preview_wiki_changes → adopt_knowledge_candidate → inspect | 私有候选、HMAC pending、副本及差异 | G0–G2／K2 与范围重核；接收不是正式授权 | 原候选身份固定；普通接口源码静态，本轮不重复原事务回归 |
| O08 正式知识事务 | admit_knowledge_candidate → apply_pending | Runtime 保存准入；Executor/WAL 修改 wiki／raw 元数据 | 真实最终 G3、当前 task/run/policy/ownership/finance 和知识依赖；只到 pending_review | 新提交与已接受 WAL 恢复分开；当前 C2 明确拒绝；源码静态 |
| O09 用户归档 | 具体批次授权 → 原受管 approve 路径 | Executor 移 raw、修 raw 引用、索引与日志 | 与 ingest 分开，不能从学习放行推导归档批准 | 原知识 ingest operation 不签发 approve；不得直接调用它的 approve_pending 代替新归档操作；源码静态 |
| O10 Query／health／维护 | 只读查询／health；需要修复再由既有候选入口 | 检查只读；日志／修复通过适用受管写入 | 不因新学习路线重新开放旧直写 CLI | 不把本轮设计审查当一次正式 ingest 或维护提交；静态入口核对 |
| O11 发布学习输入 | Production.publish_learning_inputs／recover_inputs | 远端账户 KB；本地冻结输入、请求、回执 | 实际字节与 corpus 版本，受控 corpus 不可省 guard；额度另管 | 已发送未知不重传；复用可有独立本地回执；G05，恢复规则静态 |
| O12 建书与编排 | create_activity／confirm_proposal／confirm_spine | DeepTutor 书、目录、页壳；I3 保存 activity→book 映射 | 真实目标、实际 payload／revision、独立步骤审阅；auto_compile=false | 参数审过不代表生成正文已正确；G01/G02/G03 |
| O13 预审题生成 | Production.prepare_quiz | 真实 regenerate-block 请求、题块及回执 | 模板／实际参数／revision、步骤审阅和运行预算 | 输出仍须正文／答案审阅；当前只覆盖该准备题操作，不等于任意 regenerate；源码静态 |
| O14 编写／修改正文 | 当前原生 insert-block／update-block；目标为 Production 明确编辑操作 | 远端内容；当前 client 可以发送，尚无对应高层受管编辑记录 | 原生 ACL/revision 不等于 K 准备门禁；未来固定 actual payload／依据／revision | 裸 client 无本项目前置门禁，P01/P02；处理规则见 §5 |
| O15 自由生成／扩展 | 原生 compile-page／deep-dive／supplement／rebuild 等 | 内容变更，可能新模型调用与生成队列 | 当前不在准备步骤门禁全部覆盖内；运行 token guard 也不审来源／范围 | 不自动暴露给外部模型作为通用工具；不套用 O13 的通过边界；P01、上游静态 |
| O16 观察与打开课程 | /content、/learning-state 与实际网页打开不同 | 前者观察；普通 Book GET 可能恢复编译，网页交互可继续生成 | 项目只读适配限制 Book GET；打开不是整条链零模型的证明 | P03；现有服务模型监督必须另行核对部署，不在本轮启动 |
| O17 阅读／追问／作答 | 原生网页与领域 HTTP 入口 | DeepTutor 写 progress／chat／作答；上游账本记模型用量 | 不把 is_correct、score、访问率当掌握；响应失败可能已有部分事实 | 不由外部 Agent 重放答案修复；本轮仅静态核对，不宣称重新试学通过 |
| O18 交付前基线 | Baseline.capture_baseline／record_baseline_review／check_baseline | 项目不可变 snapshot、质量审阅、首次 binding | 内容／资源／来源／实际选择题与审阅；匹配前后观察窗口 | 缺原文和内容变化分别报告；首次 binding 不被新 snapshot 替换；G06/G07/G08 |
| O19 学习证据交接 | Handoff.export_learning_results／verify_handoff | 项目不可变 I5；不改课程／原答案 | 所选会话、覆盖、I4 与准备引用、本地字节校验 | 历史成功重读不重采／不证明今日有效；缺基线仍可导出 unknown；G09/G10 |
| O20 同活动准备续接 | Production.revalidate_preparation | 不可变准备续接链；不改原 create／课程正文 | 同上传物、同学习范围、当前书 revision、实际审阅 | 只修准备依赖演进，不批准新正文或新基线；当前函数静态核对 |
| O21 来源更新／撤回 | 当前有本地版本重验；目标为显式 impact_sources 操作 | 原件历史保留；影响报告私有，正式知识修订走 O08 | 区分未知、实际字节变更、声明撤回、已审失效，不依网页篇数判断 | P04/P06；当前无自动全图传播；见 §7 |
| O22 C2 任务／放行 | 拟议 TaskContract → LearningBinding → CommitRelease | 同一 wiki Runtime 的约束元数据；不复制学习状态 | preparationTaskId 关联多个 operation，绑定已学习版本及具体候选 | P05 确认当前 operation task 不能替代；纯 L 无硬依赖；见 §4/§6 |
| O23 预算、重启、备份 | Host Invocation／学习 Budget＋RuntimeGuard／显式运维 | 三方账本各管真实调用；恢复材料按边界保存 | token、次数／字节／时间与 unknown 分列；原预算身份保留 | G11/G12/G13；不换目录清空计量，不对未知调用盲目重发 |
| O24 未来 Web／MCP | 调用同一普通应用方法；本轮不新增服务 | 应用所有权不变；返回引用和状态 | 按操作显式暴露能力，不把 owner admission 或通用 HTTP／shell 全量交模型 | 网页交互层／MCP 还需单独真实宿主验收，不能从 Python 函数存在推断已部署 |
| O25 旧学习门禁兼容接口 | StandaloneHost.run_learning_operation／旧 Runtime assessment／Readiness | 原门禁控制与证据，不是 DeepTutor progress 的镜像 | 保留旧协议兼容性；普通知识走专用非教学准入，当前 Book 学习走 I3–I5 | 不用 I5 分数／completion 伪造旧 L2，不把旧 Runtime learning_task_id 直接当 Book activity；本轮源码静态 |

O18 的现有交付门禁要求至少一道受支持选择题；纯正文课程可以存在，但不能据此宣称通过当前同一基线认可条件。本轮不扩大题型或放宽门禁。

Token 专题随后补充了[固定管线与成本治理设计](knowledge-token-efficiency-plan.md)。prepare-next 只串接 O03–O06 及 O07 的私有 preview 部分，排除 adopt、正式采集登记、模型调用和所有正式副作用；M1 只补 O23 所需真实计量关联，不改变其预算所有权。25 项操作的职责不因优化出现第二套状态机，新增管线／计量／缓存功能尚未实施。

## 4. 身份、引用和跨链桥接

| 身份／记录 | 所有者、稳定性 | 允许的桥接；不得混同 |
| --- | --- | --- |
| preparationTaskId（拟议） | 可信 Host 注册的一次用户委托；不按路径或候选号派生 | 仅在需要受控知识提交时建立；多个 operation 可引用它，纯 L 可完全没有它 |
| Runtime task_id／run_id／operation_id | 当前 Coordinator 按 operation_id＋root 派生技术任务身份 | P05 两个实际 operation 得到不同任务。保留原身份，新增关联，不把同一 task 文本当同一用户委托 |
| source identity／version／byte digest | 原件与知识准备领域 | source package、K 包、I3 大小写不同字段经显式映射；原字节摘要不等于整条 JSON 结构摘要 |
| raw locator 与流程状态 | wiki 事实来源层，允许 approve 流程迁移 | raw 全文件 hash、正文 hash、managed_extracted 抽取物是不同对象；processed 不认证知识语义或学习 |
| KnowledgePackageRef | 知识准备不可变版本与内容摘要 | 声明与实际 K2 观察绑定；不把整个包复制成另一套可写知识库 |
| BriefRef／recognitionRef／preparation binding | 学习准备事实，保留实际范围／认可与审阅 | 相同范围可复用；metadata 路径变更不等于用户改方向；来源事实变化不能被续接“重签通过” |
| corpus identity 与 I3 requestId | 学习适配；远端 KB 账户作用域，本地请求不可改绑 | corpus 可被不同课程复用；新学习目标不沿用旧 header，requestId 是本地恢复身份而非通用远端幂等键 |
| activityId／bookId／backendScope | 学习适配映射与上游领域 | activity 映射定位真实 book；裸 bookId 不证明用户／部署／准备来源；不与 Runtime learning_task_id 混同 |
| I4 snapshot／首次 binding | 证据层不可变历史 | 表达具体交付版本；不同 snapshot 不自动重置首次 binding，改变课件版本见 §5 |
| I5 exportId／handoff digest | 证据层的明确范围、时间窗口与覆盖 | verify 成功证明包自洽；不证明今日原文／课程仍相同，更不证明掌握 |
| CommitRelease（拟议） | 可信 Host 的具体知识提交放行 | 绑定 task contract、learned snapshot／I5、实际候选；不替代 G3、资料外发许可或归档 approve |

C2 的 LearningBinding 由实际 I3 回执、scope、activity/book、准备映射与 I4 首次认可版本组成。I5 没有新任务 ID 时，通过已有这些引用核对；不要求修改上游 progress 才能对接。

对于纯 L，外部 Agent 可携带本次任务的私有引用供定位，但不必须登记 wiki Runtime；其课程操作仍使用现有 I3 身份和准备门禁。如果以后从纯 L 转 C2／正式知识提交，可信 Host 再登记或关联委托，核验既有学习证据，不倒填成“之前已获得提交授权”。

## 5. 课程编辑与版本交付的最小闭环

本轮 G08 重现一个重要边界：当前 `record_baseline_review` 遇到不同 snapshot／identity 的已有 binding 会给出 `baseline_already_bound`。因此“修改原书 → 再做 I4 就重新认可”不是当前可执行路径。准备续接只更新准备引用，也不能解决这个问题。

选定以下规则，避免现在建设复杂的同书多版本学习记录归属体系：

1. **首次认可前**：允许在同一新书中通过受管正文插入／修改完成课件；发送前审实际 payload、目标、依据与 revision，固定不自动编译的参数；实际输出再做 I4。正文直写不需要为了“Agent 化”再调用一次模型。
2. **首次认可后**：该交付版本作为已学证据基准保留。实质纠错需要重新认可时，创建新 activity／book，尽可能复用语料和已审资源，再建立新 I4；记录 replaces 引用解释版本关系，不把旧作答迁入新书。
3. **原生网页直接改了原书**：承认这是上游已发生的编辑；I4/I5 可以报告与首次基线不一致，旧证据仍保留。受管路径不得清空 binding、覆盖旧 snapshot 或假称原审阅继续覆盖新正文。当前没有全 UI 强制冻结保证。
4. 新版替代关系在现有学习证据／活动回执扩展中作不可变关系，不另建进度系统；书架展示或将来网页可以派生“旧版／替代版”，该 UI 尚需实施，不宣称已有。

最小编辑能力只增加 Production 的明确正文插入与正文／标题修改方法（最终命名在接口任务固定），复用 EvidenceStore 请求／响应、全局生产锁、预算及 unknown 处理；绑定 PreparationGuard 的具体编辑审阅。其后可以审查是否需要删除／移动等更多操作，不提供任意 method/path/body 的“编辑插件”。

P07 在实际安装引擎上用临时合成书观察到：compile_now=false 插入 TEXT 后修改 body，block/page 已 ready，book 仍 compiling；内部 `_maybe_finalize_book` 才将 book 设为 ready。该内部调用只证明机制，不是已存在的公开受管完成能力。E1 因此必须覆盖“内容已全部就绪 → 明确完成交付”：有当前页／块身份、全部内容就绪、revision、无活动生成和实际审阅前置，返回可核验的实际整书状态。不能直接把 book.status 改成 ready、调用 SDK 私有方法写现有服务文件，或用普通 Book GET 隐式恢复来凑交付。

实施时先在固定补丁的独立 HTTP 实例验证是否能以已有明确操作满足上述完成契约；如需扩展，仅为该确定性完成语义加最小领域接口及构建证明，不能开放通用编译。无法保证不引入未审生成时停止，不宣称“正文直写全程零模型”。接口接线同时覆盖 Production 请求／恢复、PreparationGuard、响应解析和 CLI，不能只新增两个 Python 方法。

变更正文新增事实则回 K2；仅忠实编排依然核对实际文本；新生成题目继续核对实际题干、选项、答案和解释。已绑定课程不能通过这个新编辑方法原地重新认可。未来若确有原书内多版需求，再设计 delivery identity 与作答关联迁移，不预留一套现在无人消费的多版本框架。

## 6. C2 的时间和版本语义

本方案选择“本次范围、已认可冻结版本的学习证据＋用户明确放行”作为 C2 条件，不宣称最新实时状态：

```text
委托与来源范围 → 学习约定／核验知识 → 学习输入与真实 I3 回执
                                    → I4 认可版本 → 用户学习 → I5 范围观察
委托与来源范围 → 知识候选（可提前接收） ───────────────┐
用户明确放行＋上述对应版本证据 ──────────────────────┤
                                    CommitRelease → 原准入／G3 → pending_review
```

不存在“有准入才能生成 I5、有 I5 才能准备候选”的环。放行前可以整理候选，放行后不能换候选字节；旧 release 不自动授权修订候选。

I5 当前观察必须足以关联已认可 I4 版本和本次范围。用户后来另学新版，旧版交接仍是历史事实，不自动获得新版范围。首次放行只针对已核对版本，不能凭导出 timestamp 推断“全部学习发生在知识写入之前”。

如果用户明确要求“按当前最新课程／最新外部来源入库”，这是更强的 freshness 要求：在调用前安排当前内容／来源重读，记录观察窗口及限制；远端服务与本地 Executor 无共享事务锁，最后重读到正式提交间仍有竞态。不得用本地 SQLite 接受锁承诺远端原子一致。无法满足要求则等待或请用户明确采用冻结版本；不能暗中把“最新”解释为“历史快照”。

本地任务契约更新／撤销、已知来源冲突和实际原件依赖变化在新接受前仍停止；原 WAL 恢复和终态回放继续按原事务处理。任务注册只能由可信 Host 判断委托归属，模型自造新 task 或 unconstrained 参数不能解除现有 C2。

## 7. 来源更新／撤回的最小治理

当前 P04 实测：实际来源字节变化使 context stale；同 source version 改字节拒绝；新 version 可以保留旧历史。它并不包含自动发现网页更新、撤回通知或传播到全部课程。

新增一个**显式、按任务范围执行的来源影响检查**，命名暂为 impact_sources，不常驻：

1. 输入明确的来源旧／新版本或有定位的撤回声明、操作者要求和允许扫描范围。用户要求最新时由外部 Agent／宿主获取，原件版本不可覆盖。
2. 输出观察类型：bytes_changed、withdrawal_reported、reviewed_invalid、unobserved；撤回通知本身不自动抹除旧事实，也不把未核验通知当最终事实裁决。
3. 按实际引用追踪已有 K 包／来源页／知识关系／准备映射／I3 回执／I4。只检查可获得的明确路径及 state 根，列出 inspected、affected、unresolved 和未扫描范围；没有完整注册表时不能声称已找全所有课程。
4. 影响报告作为私有只读产物；涉及当前任务的已知冲突或失效，受管新提交／新生成必须先处理。实现时把这些引用接入任务有效性检查，不能只产出一份没人消费的报告。
5. wiki 的状态或内容变更另形成候选，经正常审阅和 Executor；已归档 raw 不删除。旧课程和 I5 保留其冻结版本，可标注需要复核，并经 §5 创建替代课程。当前原生网页尚不消费此状态，不能宣传已有实时警告或自动拦截。

整体 freshness 区分：证据字节完整、当次已核验、当前已观察有效、当前未观察。这些维度不挤进一个 verified 布尔值。归档和交接的完整性校验不失效，但新内容使用资格可能需要重新审阅。

## 8. 预算和故障恢复的交叉核对

| 边界 | 应采用的预算／恢复语义 | 不应推导的保证 |
| --- | --- | --- |
| K Host／Runtime | 当前 Invocation 的次数／字节／时间及实际 transport 可见 usage；unknown 不重发 | 模块 modelCalls=0 不等于外部 Agent 零 token |
| I3 生产请求 | 持久 dispatch marker、完整原响应、reconcile 原 ID；明确失败才能按 retryOf 另试 | 本地 requestId 不证明上游有同一幂等协议；HTTP 失败不等于远端没写 |
| 原生学习／生成 | 运行监督、真实上游 token 账本；G11–G13 验证阈值、未知计量和控制库丢失 | token guard 不审核目标或来源；本轮没有重新确认现有实例加载补丁 |
| wiki Executor | 已接受 WAL、原范围、原步骤及备份恢复；用户外部编辑冲突保留 | 不与远端课程形成分布式原子事务；不能靠撤销阻止必要恢复 |
| I4/I5 | 历史包按原身份离线校验；新观察用新操作身份，缺源或基线保留 unknown | 历史成功不证明今日服务／来源有效；新 capture 不覆盖首次 binding |
| 本机备份 | 明确停服或实际支持的一致性窗口，课程数据／本地证据／Host 状态／WAL／预算与构建清单按所有权一起保存 | 复制一份 DB 或换空 state 目录不等于恢复；本轮不操作真实备份 |

K+L 目前没有共同 token 硬钱包；业务任务关联不改变这一事实。可以在界面汇总实报数，但未知项保留，不能先相加成可强制执行的“全系统 token 限额”。

成本实施与验收进一步细化为 M1、W1／W3／W5，见[Token 专题](knowledge-token-efficiency-plan.md)。当前新接口补证确认 K transport 的业务返回不携带 usage，而 L 的归因接口可落库；不能据此推断真实生产归因已完善。后续先补可观察性，再比较同任务调用、上下文、缓存和返工；既有课件／答案／审阅和 unknown 恢复仍保留。专题新验证独立封存，不能把本文件之前的 13 项重跑当新优化已实现的证据。

## 9. 本轮发现与方案处置

| 编号 | 发现 | 影响／处置 |
| --- | --- | --- |
| J01 | 新业务任务若成为所有路线的必备状态，会让纯 L 依赖 wiki Runtime | 在主方案修订为可选关联；C2／正式知识提交由可信 Host 建立约束，保留独立学习 |
| J02 | 当前受管方法缺正文编辑；裸 client 可发送原生请求 | 新增 E1 受管编辑工作包。未补齐前不声称全部资源到课程交付受准备门禁覆盖 |
| J03 | 当前首次 I4 binding 不可用新 snapshot 替换 | 选择认可后新 activity/book 的替代版本；初始编辑与发布后纠错采用不同路径，保持历史答案 |
| J04 | I5 完整性被误当当前课程／外部来源有效 | C2 明确冻结版语义；需要最新时另取带窗口的当前观察，承认跨服务竞态 |
| J05 | 来源演进只有本地 stale，缺少影响报告的消费者 | 新增 S1 显式来源影响检查和提交／生成消费点；不自建全图后台撤回系统 |
| J06 | 工作包原先未表达课程交付和来源复核的依赖 | 更新主方案依赖：需要编写正文的新课先 E1；已有关联基线的 C2 不因 E1 全部完成而被阻断；有已知来源变更则先 S1 |
| J07 | 完成正文编辑不自动完成整书，缺公开受管完成契约 | P07 复现 block/page ready、book compiling；E1 包含确定性完成状态与独立 HTTP 验收，不能靠私有方法或隐式打开恢复 |

这些是设计问题及修订选择，不是已修复业务代码。整体可以进入明确工作包实施；C2 和新课件交付不能在相应实现验收前被标成全流程可用。

## 10. 实施顺序和关键验收

W1 入口／诊断与固定私有准备优先，M1 用量／归因可分别推进；实际 token 节省结论先有对应计量。E1 复用 Production 的编辑先闭合“外部已编写正文 → 真实受管编辑 → I4”，不要求再建通用生成 Agent。W2 任务与 C2 可以使用已有有效基线课程独立验收；若需要新编课程，则依赖 E1 和新 I4。S1 在已知来源演进的任务中成为提交前置，不要求每份没有新观察的历史来源都联网刷新。

W3/W4 按实际检索、返工和容量需要推进；W5 真实试用按实际选路线依赖对应包。每包先临时库／本机替身，然后在资料与费用已有授权范围内真实试用。没有新代码、失败或未决风险时，不重复所有历史全套测试。

新增验收必须包括：纯 L 无 wiki Runtime；原生正文变更缺审／错 revision／unknown 不重发；首次绑定后不原地重签认可；新版活动与旧答案隔离且能找回旧版；I5 旧包自洽但新使用需报告 freshness；来源影响报告能阻断相关新提交而不阻断历史查看；C2 换 operation 仍保留委托约束；跨服务观察只声明实际窗口。

## 11. 本轮交付和后续读取顺序

1. 先读本文件的操作矩阵及 J01–J07，再读[已同步的修订方案](knowledge-system-revision-plan.md)；旧审查报告仅作历史问题线索。
2. 本轮新结果、脚本、摘要与未验证范围见补证目录（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-system-integration/README.md）。前轮记录原字节保留；本次改动另绑清单，不刷新旧 verification 来冒充旧结论适用于新字节。
3. 下一步先实施 W1；E1／W2／S1 的实现范围分别按上表固定。完成一个工作包再更新当前检查点，不重启 K0–K4。

本轮没有正式 raw/wiki 变更、模型 API 外发、真实服务启动或真实课程编辑；测试后端均为合成／本机替身，P07 只操作临时手工合成书。设计自查不是独立审阅，也不证明真人身份、教学质量、所有上游入口隔离或真实部署一致。
