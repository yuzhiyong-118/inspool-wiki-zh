---
type: meta
title: 学习型入库整体方案独立审查
status: historical_record
updated: 2026-11-02
topic: 学习型入库整体审查
related_sources: []
related_synthesis: []
---

# 学习型入库整体方案独立审查

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

审查日期：2026-11-02。审查对象为 [总体方案 v0.2](learning-gated-ingest-plan.md)、[阶段路线图](learning-ingest-stages.md) 与 [交接](learning-ingest-handoff.md)，以现行 [AGENTS](../../AGENTS.md) 和实际运行时代码交叉核对。

**最新审查结论：S0 纯协议实现与合成验收已通过；S1 的 T0–T6 已完成各自实施、真实临时库测试和独立复审，见第 23–28 节。** 各阶段与任务记录分别保存；T7、S1 整体及 S2–S5 尚未验收。第 1–22 节保留各版设计与审查历史，旧版通过凭据不自动覆盖新增设计或实现。

## 1. 审查方法与边界

- 主审完整阅读总体方案与路线图，核对 Coordinator、CandidateView、G1/G2、内容审查输入、Executor、批准通道，以及现有 MISSION／NOTES／RESOURCES。现有学习资产尚无作答证据，不迁移、不补造掌握记录。
- 首轮分派架构、教学、治理三个只读 SubAgent；未收取完整最终报告，其中教学代理明确因服务额度中止。过程消息仅作线索，由主审重新核对，不计为独立通过。
- 继续后由新的只读审查员复核预算、权责与阶段依赖，并对主审的两项候选阻断发现进行反证核对。它未参与方案编写，也不修改文件。本轮是方案初审，不是修订后的复审。反证核对认可 B1 为阻断；补证提升原拟列阻断，经复核发现仍有合法实现路径，主审采纳将其降为重要改进 I1。预算同样列为 S0 必决而非当前架构阻断。
- 仅使用本地证据。没有重新认证方案中的外部服务能力、Star、安装量或教学效果；这些历史调研不作为本轮放行依据。
- 不把“L0–L3 尚未实现”“当前 ingest 不要求学习确认”“严格 Native 适配器未启用”本身报成缺陷：方案已经承认它们，实施和验收属于后续阶段。

以下行号对应本次读取的未修订方案和代码。基线 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| learning-gated-ingest-plan.md | C7CE56E9309AEAC058763B69E02011E60EFD7658BE45E8E3CB0F45430E2C3A35 |
| learning-ingest-stages.md | 533D82BD72D5B249F930C6E147E2667FDC23E6CA0945680C7C499755B6ECB91E |

## 2. 阻断问题

### B1：最终候选缺少逐项覆盖约束，教学子集可能被当作整份候选的就绪证明

**证据。** [总体方案](learning-gated-ingest-plan.md) L232 只建立“关键主张—目标—课程—题目—证据”映射，L242、L244 允许可选目标和每节 3–5 个重点；L313 的 L0 检查课程核心主张及判分依据，L315 的 L2 检查必要目标，L316 再绑定整个最终候选。L250 的摘要绑定能防止候选换版，却不能证明最初那一版的全部语义变更已被覆盖。[现有 G3](../../tools/wiki_runtime/review/content.py) L30–34 要求引证覆盖候选文档，不负责学习目标覆盖。

**失败场景。** 候选含 A、B 两项新知识或一项新的跨页关联；课程只讲 A，用户通过 A，B 未进入目标表但始终留在同一候选。候选摘要完全匹配，现有文字仍不能判定 B 应允许、阻断还是移出。另一种情况是把难以解释的核心结论标成可选，随后声称整份候选已理解。

**最小修订。** 在 §9 和 L0/L3 增加一条覆盖不变量：最终 diff 的每项新增／改写语义，都必须有主张、证据处置及教学处置；教学处置只能是必过目标、经独立审查认可的可选拓展、已验证且仍有效的既有目标，或有理由的非教学变更。未映射项阻断；“可选”不免除证据核验，核心判分依据不能由生成者自行降为可选。无需逐句出题，也无需所有可选项考试。

**验收。** 增加一个“同一候选夹带未映射新结论”的反例，L3 必须拒绝；可选背景有证据和明确理由时可以不考试；核心结论改标可选必须触发独立复核。脚本检查 ID、覆盖和绑定，语义审查检查分类是否合理。方案层先写清规则，S0 固定样例，S3/S4 建映射和判据，S5 验证最终 diff 覆盖。

## 3. 重要改进

### I1：外部补证到正式本地证据节点的交付链未闭合（S0 必决）

**证据。** [总体方案](learning-gated-ingest-plan.md) L248 允许讨论引入外部主张，L279 要求保存外部原文，L293 将证据快照放入 `.wiki-runtime/learning/`，L299 记录 URL、定位和摘要，但没有说明正式应用后哪些证据转为持久本地来源、如何进入最终 G3、如何处理补证采集与原 ingest 批次的关系。[AGENTS](../../AGENTS.md) L92–100、L134–137 要求知识结论优先连接本地 sources。[CandidateView](../../tools/wiki_runtime/candidate/view.py) L38–44 排除 `.wiki-runtime`；[Coordinator](../../tools/wiki_runtime/coordinator/loop.py) L245–261 和 [Executor](../../tools/wiki_runtime/executor/core.py) L260–263 的 G3 原文来自明确的 input_refs。[G1](../../tools/wiki_runtime/gates/core.py) L197–204 只允许 capture/import 新增 raw 或 raw/assets，不能在普通 ingest 中顺手补入。

**失败场景。** 原始笔记中的结论被一份新获取的外部材料纠正，课程和最终候选采用纠正后的结论。若仅把证据放在私有学习目录，正式知识留下的本地证据链和最终 G3 输入可能缺失；若到 ingest 时才新增 raw，现有 G1 拒绝；若先运行 capture，则可能提前改变 raw/index，必须解释它与“学习未完成时索引不变”的边界。单纯增加一个来源 URL 不能回答这些问题。

**最小修订。** 增加一段“补证提升协议”：明确临时快照、持久证据、本地来源页、G3 原文输入之间的映射，以及保存时点、原 ingest 单元与补证批次的关系、失败后允许保留什么。可以复用已有 raw/来源页；不要求每个网页都新建 raw。如果选择登记新 raw，必须使用已有 capture/import，并明确学习期间是否允许独立采集、何时重建依赖与重新确认；不能把这项副作用藏在 ingest 中。暂不决定存储目录细节，但必须在 S0 选定可与现行门禁组合的路径。现有方案未排除独立 capture/import 或持久来源记录等合法方案，因此这是必须补齐的接口，不是已证明无法实现的架构矛盾。

**验收。** 用“原 raw A + 新外部证据 B，B 推翻 A”的例子完整追踪：课程与候选引用 B 的真实可读范围；最终 G3 能收到受摘要绑定的 B；正式知识能通过本地来源追溯 B；移走临时学习目录后已承诺保留的证据仍可追溯；采集或应用中断不错误推进原批次状态。S0 定边界，S1 提供持久来源映射，S2 消费该映射，S5 联测。

### I2：区分长期学习任务与短时执行预算（S0 必决）

**证据与影响。** [方案](learning-gated-ingest-plan.md) L74 允许跨会话学习且暂停不退款，L283 同时限制墙钟时间；[Coordinator](../../tools/wiki_runtime/coordinator/loop.py) L130–136、L156–168 持久化绝对 deadline。晚上暂停、隔日返回会超时；直接另建操作又可能重置额度。其 awaiting_human/ready_to_apply 也不是通用学习暂停状态（L270–275）。这是既有机制的适配问题，不要求在整体初审时实现新账本。

**最小修订。** S0 明确 learning task 与执行 run 的映射：检索、模型调用、修复和申诉计入长期共享账本；每次自动工作有有限运行时间，等待用户不消耗活动执行时间；证据新鲜度与批准有效期照常流逝。新 run 不创造新额度。C1→C2→C3 明确是累计上限还是追加额度，首版建议采用累计上限；模型 token 无可信统计继续记 unknown。并发任务先预留额度，Executor 最终 G3 也计入，不把全部预算在教学前耗完。

**验收。** 等待一天可恢复且余额不增加；活动超时仍停；两个子任务竞争最后一份额度只有一个获准；重启、工具替换、补讲循环均不退款；最终复验不足预算时暂停，不写入。

### I3：区分学习记录局部失效与写入事务整体失效（S0 定边界，S2/S4/S5 验证）

**证据与影响。** [方案](learning-gated-ingest-plan.md) L220 先沿 supports/contradicts 追踪，L250、[路线图](learning-ingest-stages.md) L143 承诺只重验相关目标。但 [Coordinator](../../tools/wiki_runtime/coordinator/loop.py) L230–232 完整枚举视图；[CandidateView](../../tools/wiki_runtime/candidate/view.py) L220–235 绑定枚举到的文件，L243–259 拒绝依赖／目录变化。无关日志或页面变更也可能使旧事务不可应用，不等于用户所有知识都失效。反之，前置概念变化可能沿教学依赖影响多个目标，不能只看 wiki 的直接证据边。

**最小修订。** 保留现有严格事务检查；另用最小的主张—目标—前置目标依赖表判断学习记录可复用范围。旧事务失效后重新生成候选和审查，不能替换旧快照冒充原通过；不确定影响范围时保守标记待复核。用户确认仍绑定当前最终候选，不能把可复用的理解证据误作可复用批准。

**验收。** 无关页面改动：旧事务拒绝，相关学习记录经检查可保留；前置概念变化：所有受影响目标被标记；候选仅格式变化与核心语义变化走不同的教学重验路径，均重验事务和确认绑定。

### I4：把角色产物的认证责任与宿主可行性检查提前写入依赖表

**证据与影响。** [方案](learning-gated-ingest-plan.md) L254–307 已写明独立上下文和可信运行器，方向正确；但 [路线图](learning-ingest-stages.md) L155 将真实宿主调度／身份验证放到 S5。S1–S4 可以开发纯组件，却不能因此宣称已经具备端到端可信学习记录。现有 [ApprovalStore](../../tools/wiki_runtime/host/approval.py) L24 只支持 approve、rule_maintenance、tool_maintenance，不直接解决学习 ingest 的确认。

**最小修订。** S0 交付一张短表：谁提出、谁独立判断、谁认证并保存、谁可撤销，各角色可读写哪些产物。Researcher/Tutor 不签发自己的通过记录；Reviewer/Assessor 返回意见，运行器核验身份和绑定；Rule Auditor 不解除知识冲突；Executor 复验应用。明确缺独立审查或身份通道时停止。S0 记录目标宿主可行性证据和未知项；在依赖该能力的阶段前增加最小合成探针，完整闭环仍留 S5。不要因当前能调用 SubAgent 就宣布运行器认证已完成，也不重开 OS 隔离或要求另配 API。

**验收。** 生成者自填 passed 被拒；审查者缺失时不回退自审；跨任务/候选重放意见被拒；宿主探针与测试替身证据分列。Reviewer 与 Assessor 可复用实现，但需要独立任务上下文与分别绑定的职责，避免为七个角色建设七套服务。

### I5：为首版输入能力设置明确的阶段验收范围

**证据与影响。** [方案](learning-gated-ingest-plan.md) L90、L93、L138 和 [路线图](learning-ingest-stages.md) S1/S3 涵盖论文、PDF/OCR、partial 教学；[Coordinator](../../tools/wiki_runtime/coordinator/loop.py) L283–297 对明确 PDF/OCR 等先暂停，[Executor](../../tools/wiki_runtime/executor/core.py) L205–211 同样拒绝相关 raw 自动应用。方案已承认能力限制，但“来源获取成功”容易被误用为“学习到写入已经可用”的阶段凭据。

**最小修订。** S0/S1 用小矩阵列出可获取、可教学、可自动应用三个独立状态。首版自动闭环优先使用现有可完整处理的文本来源；PDF/OCR 保留人工补充或受限研究路径，不纳入自动写入通过声明。partial 材料只支持可见范围内的主张，不能用改扩展名、去掉来源类型绕过暂停。扩大支持范围需单独样例验证，不要求为 S1 一次装齐服务。

**验收。** 同样 MD 输出但来源为 PDF/OCR 时仍保持类型信息和暂停；仅摘要可读时不能证明实验细节；完整文本闭环与受限材料测试分别汇报。

## 4. 保留、收敛与可后置项

| 处理 | 设计与理由 |
| --- | --- |
| 保留 | 先教后验、提示与独立作答分开、允许用户纠正判分；不以总分掩盖核心误解。 |
| 保留 | T/S/I/P/C 各管不同维度；来源按具体主张评价，热度、官方身份和用户偏好不替代证据。 |
| 保留 | 候选与正式库分离、两步 ingest/approve、历史批次不回退、raw 正文只读、冲突不靠多数表决。 |
| 保留 | 原 Coordinator/Executor 与 G0–G5；L 门禁作为前置业务条件；公共 v1 在迁移批准前保持不变。 |
| 收敛 | 用少量本地记录和适配函数补足上述不变量；不建第二套事务、通用多 Agent 框架或课程平台。 |
| 收敛 | 首个垂直样例用现有搜索和完整文本；来源扩展主要改数据，新增协议按需做适配。S1 不以服务数量验收。 |
| 后置 | Tavily/Exa 二选一、DeepWiki/Context7、复杂路由评分、向量库、FSRS、掌握概率、全站抓取及完整课程网站。它们都不是本轮放行前置。 |
| 后置 | 长期课程导出目录、完整对话保留策略；在用户选择前保留私有状态，不自动发布。正式证据的持久性不能一并后置（见 I1）。 |

`evidence_status` 当前混合“原文陈述”和“证据支持”等维度（方案 L195），后续应允许“作者确实这样说，但结论存在争议”同时成立。可用一个归属字段加一个核验结果表达，不必新增复杂本体；交 S2 样例校准。

## 5. 最小修订与复审顺序

1. 修订方案 §9/§13 的候选覆盖不变量，明确 S0/S3/S4/S5 的检查责任。不要先写运行时代码来替代设计决定。
2. 把 I1–I5 写入相应阶段的明确验收项，尤其是 S0 的补证提升、任务/run、时间、依赖与角色认证责任；不要求本轮提前选定所有存储细节或实现这些组件。
3. 由未参与修订的只读审查者复核 B1 的反例是否被覆盖，并确认 I1–I5 已有阶段责任与停止条件，检查新文字是否与“学习期不写正式候选”、整组 raw、现行 capture/ingest/approve 约束一致。语义复审和链接/结构检查分别记录。
4. B1 关闭、无新增关键矛盾且复审记录落盘后，才放行 S0。S0 完成另需自己的验收，不能把本次整体审查当作 S0 已通过。

**初审时状态（历史）：B1 未修订、未复审，S0–S5 暂停。** 当时没有要求用户重新授权已同意的阶段工作。上述工程边界可先形成具体提案；只有改变既定要求、修改 AGENTS，或涉及新服务权限时，才按实际范围取得授权。最新状态见第 7 节。

仍需用户决定的实际产品取舍是：是否另行允许“未决争议本身”作为成果入库、长期保存或公开哪些学习回答、是否接入需要新权限的服务。沿用方案的保守默认即可继续设计：不自动启用争议例外、不公开完整问答、不接新服务；这些取舍不必在 S0 前逐一追问。需求覆盖以交接和路线图已记录的要求为准，不把不可见历史对话推断为额外授权。

## 6. 实际检查与未验证项

- 执行只读 `python -B tools/health.py --json`（使用交接所列 Python 路径）：退出码 0，八项检查均无问题，内容页 12、内容图边 43。Health 不覆盖本文架构和教学语义问题。
- 初审前及文档产出后执行 `git diff --check`：退出码 0。用 Python 标准库对本记录、交接和设计 README 的 45 处本地文件链接检查，缺失 0；未将此检查称为语义或新流程验收。
- 本轮仅审查和维护设计记录；未运行新业务闭环、真实模型教学评测或历史全套测试。未改 AGENTS、公共契约、运行时代码、raw 或现有学习资产，未提交/推送。
- Health 为只读结果，未调用受控正式落盘入口，不声称已追加 wiki/log 或写图；检查结果保存在本记录。未重置或改写原有 wiki/log 等变更。继续审查时观察到 Git HEAD 已为 `ab572e7`（vault backup），本代理未执行该提交；方案与路线图哈希复核仍与上述基线一致。
- 本轮模型 token 消耗及历史剩余额度无可信统计，记 unknown；首次三个子任务未完成的调用不视为免费或完成，未据此宣称预算充足。
- 尚未验证：实际目标宿主到学习记录认证的闭环、真实教学与评分质量、拟议外部适配器的当前可用性。它们应由对应阶段取证，不能用结构全绿或公开项目自述代替。

## 7. v0.3 修订与独立复审（2026-11-02）

用户在初审后明确授权“可以，修订吧”。本次修订总体方案和路线图，保留现行规则、代码和六阶段结构；没有把待交付接口或样例清单冒充 S0 产物。

| 审查项 | 修订落点 | 复审结论与剩余工作 |
| --- | --- | --- |
| B1 | 方案 §9.4、§12 coverage、§13 L0/L3；路线图 S0/S3/S4/S5 | **设计层关闭**。覆盖全部语义差异，含删除造成的范围变化及跨页关系；独立审查直接对照完整 diff；首次冻结已有 A/B 的反例明确拒绝。可选／非教学／复用目标均有条件，不豁免核心要求。实现和实测仍留相应阶段。 |
| I1 | 方案 §4.3；路线图 S0 必决、S1 来源包、S5 联测 | 阶段要求已落实。S0 仍须选择与现有门禁兼容的具体提升协议，确认采集副作用、重建确认、分组及失败保留项；未定不能通过 S0。 |
| I2 | 方案 §3、§11、§12；路线图 S0/S4/S5 | 阶段要求已落实。长期累计账本、短 run、活动时间／等待、原子预留、最终 G3 留额明确；有限参数及实际接口衔接待 S0。 |
| I3 | 方案 §8、§12；路线图 S0/S2/S3/S4/S5 | 阶段要求已落实。教学前置依赖传播与事务全量失效分开，允许理解证据复核复用，不继承旧候选确认。 |
| I4 | 方案 §10；路线图责任表及阶段停止条件 | 阶段要求已落实。角色意见与运行器认证分开；宿主探针须在首次依赖能力前完成，缺能力仅能组件试验，不能通过相关阶段。 |
| I5 | 方案 §4.3；路线图 S0/S1/S5 | 阶段要求已落实。完整文本作为首条闭环，PDF/OCR/partial 的获取、教学和应用范围分开；未放宽现有暂停。 |

独立复审者：只读 SubAgent `/root/re_review_v03`，新上下文，未参与修订。它读取初审问题、v0.3、路线图和必要的实际代码，返回：**B1 在设计层已关闭，未发现新阻断，I1–I5 足以作为 S0 输入**。这不是对具体预算参数、接口实现或真实宿主闭环的通过意见。

复审提出一项非阻断措辞问题：方案 §15 与路线图 S5 的“未确认时索引不变”需区分独立获准的 capture/import。主审已补明其副作用按 S0 协议单独核验，不构成学习 ingest 应用确认，原批次不因此推进；同一独立审查者定点复核通过，与 §4.3 一致，保留原通过结论。未通过新增例外放松门禁。

确定性检查单独记录：只读 Health 八项零问题（12 个内容页、43 条内容边）；五份设计文档的 60 处本地链接（含 2 处标题锚点）检查通过；`git diff --check` 通过。链接检查首轮把合法目录链接误当文件缺失，修正检查口径为允许存在的目录后通过，没有为迁就检查改动目录链接。没有运行新业务流程或历史全套测试。

复审和交接收尾后的文件 SHA-256（用于区分后续修改，不是运行时凭据）：

| 文件 | SHA-256 |
| --- | --- |
| learning-gated-ingest-plan.md | 8ccfcecd6511e9cbefccf4352fe985d43468a783df4254bbcd4f4ced485ef157 |
| learning-ingest-stages.md | 493c85b8bc8950159764adfaf64a4d6e54565f5b1cdb4d961d171ae8f0b162e2 |

**放行范围：仅整体审查前置门禁。** B1 实现效果、I1–I5 接口细节和固定样例仍须在 S0–S5 实际交付并逐阶段验收。本次只完成用户要求的设计修订与复审，S0 尚未续做；后续可按已有授权进入 S0，不重复申请阶段许可。AGENTS、公共 v1 契约、raw、正式索引和现有学习资产未改动；未提交或推送，Health 未走正式落盘入口。模型 token 消耗和历史预算余量仍记 unknown。

## 8. v0.4 可行性思考保存（2026-11-02）

用户进一步询问整体可行性、架构优化和资料缺口，并明确要求先写入方案，避免上下文耗尽丢失。已将五项建议保存为 v0.4：知识版本与最终事务分离、贯穿样例、四模块实现、判分器校准、用户时间与学习收益观测；同步路线图 O1–O5 与交接摘要。四类定向参考 R16–R19 及已读范围、用途和证据限制保存在方案 §17。

本次是经授权的思考落盘，没有独立语义复审或 S0 实施。v0.3 的历史结论和哈希保留；接手应先对新增边界做定点核对，尤其最终候选编译仍须满足 B1、阶段试联不绕过前置、精简注册表不免来源核验。后续仍按现有授权推进，不需要为单纯换阶段重新申请许可。

收尾检查：五份设计文档 60 处本地链接（含 1 处标题锚点）有效，`git diff --check` 通过。仅保存文档，未改规则、代码、raw 或正式索引，未提交／推送；未重复运行此前已通过且本轮未影响的 Wiki Health。


## 9. v0.6 架构修订与独立复审（2026-11-02）

用户确认并授权落盘四项架构决策：Host 内 Durable Task Runtime 统一长期 Learning Task、Run 关联、共享账本和 fencing；统一操作授权语义但保留 ingest Host 业务授权与 approve ApprovalStore／G4 的不同凭据边界；现有 Executor 继续独占正式事务、WAL 和独立恢复；Knowledge Evidence 子系统统一 Source、Evidence、Claim、关系记录、版本和依赖传播。四项均为逻辑职责与数据所有权划分，不新增四套服务。

本轮同步修订总体方案、S0–S5 路线图、设计 README 和交接。重点协议包括：双层预算在外部调用前完成预留与失败结算；Readiness 不包含用户授权并输出 readiness_digest；G3 input_refs 指向受依赖快照绑定的持久原文路径而非 Evidence ID；学习记录局部失效与 Executor 事务整体重建分开；fencing 采用条件原子提交并只约束新事务准入；判分校准绑定 rubric、evaluator 和 objective_type 并实际阻断 L2。

独立审查者未参与本次修订，读取 v0.6、路线图、交接及真实 Host／Coordinator／Executor／CandidateView／G3 代码。主体架构未发现新的阻断；初审为 **failed**，剩余三项如下：

| 初审问题 | 修订 | 定点复审 |
| --- | --- | --- |
| 组合指令可能提前签发未来 approve 凭据 | 组合指令只记录流程意图；实际 ingest 应用报告和 approve context 生成后，owner 仍独立确认 | 通过，与 ApprovalStore 的完整 context 和 TTY 确认一致 |
| 统一授权字段可能直接进入封闭 ApprovalStore context | 统一字段仅属 Host 私有审计语义；以 context_digest 映射任务、批次及 ingest execution_result，consumed 由 Executor 结果派生 | 通过，不改变 ApprovalHandle 或公共 v1 |
| 交接的历史“复审通过”可能被误读为 v0.6 凭据 | 明确限定为 v0.3 历史结果，v0.6 以本节实际复审为准 | 通过 |

同一独立审查者对三项修订定点复审结论为 **passed**，未发现修订引入的新矛盾。该结论仅表示 v0.6 本轮设计审查通过，不代表 S0 已实施、真实宿主闭环已运行或教学效果已验证。

确定性检查单独记录：只读 `python -B tools/health.py --json` 退出码 0，八项检查零问题，内容页 12、内容图边 43；五份设计文档 59 处本地文件链接及标题锚点检查缺失 0；`git diff --check` 退出码 0。未运行新业务流程或历史全套测试，未修改 AGENTS、公共契约、运行时代码、raw 或正式 Wiki，未提交／推送。模型 token 消耗仍记 unknown。


## 10. v0.6 外部审查与 S0 残余项（2026-11-02）

另一名未参与 v0.6 修订的 Agent 与一名只读 SubAgent 分别核对方案和实际调用链，结论为 **passed_with_residual**：总体可行，可以开始 S0，无需推翻 Host／Coordinator／Executor、Knowledge Evidence 或教学评估的职责划分。

### 10.1 重要残余：原子接受点

方案原先只明确 Host 在 Executor apply 前检查 ingest 授权，以及 Executor 在锁内、首个 WAL 前准入，没有完整规定 G3 期间发生授权撤销、Readiness 失效或租约换代时的最终接受协议。现有 Executor 最终 `_authorize` 只覆盖 approve 等敏感操作，Host 锁又是实例内线程锁，不能阻止另一个 Host 进程修改私有状态。

已将最小修订写入总体方案 §12.4、§13.1 和路线图 S0：Host 检查仅为预检；Executor 在 G3 后、首个 WAL 前重验 Candidate、依赖、Readiness、授权撤销、版本与 fencing；撤销、失效和换代须与最终准入处于同一跨进程串行化边界，或由持久层条件接受阻止旧状态写入。首个完整 WAL 是唯一接受标志；接受前拦截，接受后由 Executor 独立完成或恢复。该项仍是 **S0 必须实际设计并验证关闭的残余项**，文档修订不等于运行验收通过。

### 10.2 其他 S0 接口与成本项

| 项目 | 审查判断 | 已落盘的 S0 要求 |
| --- | --- | --- |
| 双层预算崩溃幂等 | 现有 Coordinator 只有聚合计数，没有 invocation 身份 | 两层按 invocation_id 持久化回执；重放不重复调用或扣减；覆盖 Run 已扣、Host 未预留便崩溃的对账样例 |
| 恢复结果归并 | Executor 对未提交事务回滚时，recovered 不能解释为应用成功 | 回滚后保留有效学习证据，应用未完成；重新应用使用新 operation 并重新核验 Candidate、Readiness 与授权 |
| 校准粒度与成本 | 每课独有 rubric 若都要求独立校准，会重复建设标签与 holdout | 区分可复用 rubric_template 与本课内容 rubric；校准绑定模板、evaluator 和 objective_type，本课答案仍须独立证据审查 |

### 10.3 S0 至少新增的五个验证场景

1. G3 期间撤销授权、使 Readiness 失效或换代，不能产生新 WAL。
2. 接受点附近崩溃，能够依据完整 WAL 唯一判断事务是否已接受。
3. 同一 invocation 重放，不重复调用或扣减。
4. Executor 回滚后，学习任务不误标为 applied。
5. 不同课程复用校准时，有明确适用依据和失效条件。

实现范围继续保持单机持久存储、一个权威任务账本、共享 Agent 调用组件和现有 Executor WAL／锁／恢复机制；不把逻辑模块拆成服务，不重复保存彼此状态。现有资料足以开展 S0，不需要扩大调研。

本次为审查结论与文档修订落盘，未运行新业务流程，未修改 AGENTS、公共契约、代码或真实 raw，未提交／推送。


## 11. S0 详细任务书与独立复审（2026-11-02）

用户授权先展开 S0。已形成 [S0 详细任务书](learning-ingest-s0-plan.md)，将阶段拆成六项有序任务：私有协议与合成夹具、Durable Task Runtime、逐 invocation 双层预算、Executor 原子接受与 Host 授权、校准／覆盖协议、S0 场景验收。每项明确文件、接口、依赖、实施步骤、验收和失败出口，并附需求—任务—门禁映射及实际命令。

两路只读核对提供真实代码入口和样例矩阵；未参与任务书编写的另一名独立审查者随后复审。初审为 **failed**，发现六项可执行性缺口：

| 初审问题 | 修订结果 |
| --- | --- |
| Executor 在 G3 期间持锁，撤销无法完成，X1 与锁设计冲突 | 改为锁外 G3；锁内重建 CandidateView、重跑 G0–G2、复验依赖与版本，再执行 acceptance_check 和首个完整 WAL |
| 缺少真实 ingest 签发／撤销、Readiness 失效和 admission 加载入口 | 增加 Host 私有 owner API；apply_pending 必须加载私有 admission，X1／B2 不得直接操纵存储代替 |
| 缺少 acceptance_check 成功后、WAL 前的故障点 | 新增 after_acceptance_before_prepare，崩溃为未接受且正式库不变 |
| 预算遗漏结果保存与结算等崩溃边界 | 固定 Host 预留后／dispatch 前、dispatch 后／调用前、结果保存后／结算前、结算后／响应前四类验收 |
| replay 只带 ID，缺少跨任务请求绑定 | 改为 replay(spec)，invoke／replay 均校验 spec_digest 和任务／Run 作用域 |
| 恢复投影缺少中间态与结果身份验收 | 覆盖 applied／prepared／applying／recovery_required／recovered／conflict，并拒绝 operation、Candidate 或依赖摘要不匹配 |

同一独立审查者定点复审六项修订，结论为 **passed**；锁外 G3→锁内最终复验→首个完整 WAL 与现有 Executor 可兼容，不需要修改公共契约或另建事务系统。通过范围仅为 S0 任务书设计；实现、真实宿主探针和场景测试均未运行。

确定性检查：`plan_lint.js` 为 0 ERROR／0 WARN；任务书 3 处本地设计链接均存在；`git diff --check` 通过。plan_lint 的 docs/specs 专用互指规则不适用于本仓 docs/design，Spec 链接与内容一致性已由独立语义审查覆盖。未修改 AGENTS、公共契约、运行时代码或真实 raw，未提交／推送。


## 12. 知识输出与工程目录边界复审（2026-11-02）

用户确认两项补充原则：课程、公众号文章和视频脚本等属于可扩展的知识输出类型，不应影响整体门禁与知识核验；工程目录按长期子系统职责区分，任务和验收按阶段区分，不按阶段复制共享状态或运行时。

已将 Knowledge Output 与 Learning & Assessment 拆为独立逻辑子系统。Knowledge Output 消费版本化知识和证据快照，通过适配器生成 Lesson、Article、VideoScript 等输出；新增事实、改变结论或扩大适用范围必须返回 Knowledge Evidence。学习验收只约束学习流程，公开发布仍需独立授权。S5 统一命名为“知识沉淀与正式入库”。

总体方案 §3.4 明确现有 host／coordinator／executor／candidate／contracts／review 与拟新增 evidence／learning／output 的目录职责；阶段任务书和合成夹具可按阶段命名，共享协议、实体和存储不得按阶段复制。S3 的课程输出与题目依据分别落在 output／learning，S5 只负责正式知识沉淀、事务、恢复和归档。

本次同步还修正了总体方案 §12.4 遗留的“锁内完成 G3”旧表述，使其与 S0 任务书一致：锁外 G3，锁内重建 CandidateView、重跑 G0–G2、复验依赖和版本，首个完整 WAL 前最终准入。

未参与编辑的独立审查者定点复审结论为 **passed**：未发现旧 Teaching & Assessment 混合边界、阶段运行时复制、锁协议矛盾或需求回退；输出层没有形成免证据、免授权发布或免学习正式入库的旁路。本结论仍只属于设计审查，未运行实现或新业务测试。

机械检查：S0 `plan_lint.js` 为 0 ERROR／0 WARN；相关旧命名与旧锁表述检索无残留；`git diff --check` 通过。未修改代码、AGENTS、公共契约或真实 raw，未提交／推送。


## 13. S0 重放、阶段边界与锁分段复审（2026-11-02）

另一 Agent 对 S0 任务书提出四项问题。主 Agent 对照真实 Executor、Host 和历史测试记录确认均有依据，并按授权修正：

1. **终态事务重放顺序**：锁外 G3 前增加 Executor 初始短锁 journal／active 检查；身份一致的 applied／recovered 直接返回历史结果。最终准入前再次检查，新增 X6 验证不重复审查或扣费。
2. **S0 与后续阶段倒挂**：S0 完成条件只包含 X1–X6 与 P1–P4 的协议、基础设施和合成记录验收；真实课程、冲突、补证、依赖传播和最终编译等 B 场景明确归属 S1–S5，不参与或反向阻塞 S0。
3. **同 Host 撤销受线程锁阻挡**：Host `_lock` 只保护 pending 读取、完整性／身份认证和不可变 admission 快照，在 Executor G3／apply 前释放；新增同 Host 双线程暂停／撤销测试。
4. **完整测试超时不足**：完整套件总时限由 300 秒改为 1800 秒，依据 `wiki/log.md` 2026-10-26 的 877.929 秒历史回归，保留增长空间，仍不允许重跑取最好结果。

独立定点复审进一步发现：仅在 Executor 内增加初始检查仍不足，现有 Host 会先做 `remaining_timeout` 和 provenance 新鲜度核验，导致终态重放在到达 Executor 前被拦截。随后补充 `Executor.lookup_terminal(bundle)`：Host 先认证 pending 完整性／HMAC／身份，再通过短锁查询身份一致的终态；只有非终态才执行 deadline、provenance、授权预检和锁外 G3。Executor apply 内继续保留初始与最终 journal／active 检查。X6 增加真实 Host 下 deadline 过期及应用后库／provenance 变化的重放用例。

最终独立复核结论为 **passed**。Host 前置阻断已移除，四项问题及追加的 Host 调用链缺口均在设计层关闭；锁顺序、阶段验收归属和现有 Executor 终态语义相容。通过仍只限设计，`lookup_terminal`、Host 新顺序及所有 S0 实现和场景测试尚未执行。

机械检查：S0 `plan_lint.js` 为 0 ERROR／0 WARN；`git diff --check` 通过。未修改代码、AGENTS、公共契约或真实 raw，未提交／推送。


## 14. v0.7 统一运行时架构与独立复审（2026-11-02）

用户确认采纳另一 Agent 的架构收敛建议：统一 Task Runtime、取消双层权威预算、定义稳定 KnowledgePackage、在严格信任条件下复用 ReviewCredential、将授权／原子接受／完整写入意图组成一个协议，保留学习验收独立性并重排实施路线。

v0.7 明确：Task Runtime 统一流程、调用、预算、授权、等待、暂停恢复和结果登记；Host 只负责交互、工具与身份接入；Coordinator 复用 Run 内候选工作循环但不再拥有权威账本；Executor 继续独立负责文件事务、WAL 和恢复。一条 Invocation 在同一原子操作中检查 Task、Run、并发和最终留额。KnowledgePackage 统一主张、证据、冲突、版本、可读范围和既有知识关系，供课程、文章、视频与 Wiki 候选共同引用。

S0–S5 重排为：实体／接口／场景；统一运行时与事务基础；最小知识链与 Wiki 候选；学习与独立验收；来源与输出扩展；真实小批次知识沉淀验证。S0 任务书同步重写为四项协议任务，不再要求 S0 提前实现后续业务。必需判分校准在 S3 接入 L2，S4 只扩展适用领域。

未参与修订的独立审查者初审为 **failed**，发现八项接口／阶段缺口：

1. Host／Coordinator 残留已取消的权威职责。
2. 缺少 Runtime 注入 Coordinator／Executor 的同一 InvocationPort。
3. 缺少私有 Admission 与 Executor acceptance_check 最终准入契约。
4. S2 compile_candidate 依赖尚未存在的学习产物。
5. 把 conflict 当作公共 Executor state，与 v1 不兼容。
6. 主文档残留旧阶段归属。
7. 必需判分校准仍推迟到 S4。
8. S1 缺少首次消费前的真实身份与重放负向门禁。

已逐项修订：统一 Runtime 认证与失效；定义 InvocationPort；补全 Admission、G3 后／WAL 前接受及 after_acceptance_before_prepare；S2 改用 coverage_spec 且只能产出 CandidatePreview／Coverage；conflict 由 recovery_required＋recovery_status=conflict 投影；同步阶段归属；必需校准移至 S3；S1 增加身份、自签、缺角色、跨任务／候选重放拒绝及不可用时独立重审。

同一独立审查者定点复审结论为 **passed**，八项均关闭，未发现对应问题残留。该结论仅表示 v0.7 设计及 S0 任务书通过本轮审查，不代表任何阶段已实现或运行验收。

机械检查：S0 `plan_lint.js` 为 0 ERROR／0 WARN；`git diff --check` 通过。未修改代码、AGENTS、公共契约或真实 raw，未提交／推送。

## 15. S0 协议实现与独立验收（2026-11-03）

已按 Task 1–3 新增私有协议、合成记录和场景测试：`runtime/protocol.py` 固定 Task／Run／Invocation、单账本限制检查、执行所有权、ReviewCredential、Readiness、Authorization、CollectionAuthorization、Admission 和 Executor 结果归并；`evidence/`、`learning/`、`persistence/` 分别定义知识包、学习与输出、候选覆盖协议。三个贯穿场景只把 S0 负向协议标为通过，S1–S5 业务步骤全部保持 `not_passed`。

实现后的首次独立审查为 **failed**，发现必要理解凭据可省略、Assessment 未绑定独立 Assessor、rubric 角色与目标错配、最小字段缺失、采集授权与场景归属不闭合，以及公共契约测试命令空跑。逐项修复后，第二次审查发现两项残余：误以 CandidatePreview 摘要充当公共 Candidate 摘要，以及本课 rubric 审查可跨 Task 复用。

最终协议明确：`certify_readiness(candidate, candidate_preview, understanding_records, final_review_credential, ...)` 使用公共 v1 `candidate_digest` 绑定 Candidate，另以 `coverage_digest` 绑定预览与覆盖；从最终 Coverage 重推导全部必过／复用目标，绑定 Assessment、独立 Assessor 和最终 Reviewer；L2 与最终准入分别检查当前 Task、证据、依赖和规则。完整重算相关摘要后，跨 Task、缺角色、错内容、漏目标及空凭据仍被拒绝。

最终独立复核结论为 **passed**：两项残余均关闭，定点范围内未发现新增阻断。S0 协议、模块和场景测试共 **55 项通过**；公共契约 **18 项通过、1 项因宿主不允许 symlink 按原逻辑跳过**；最终完整历史回归 **447 项通过、6 项按既有平台条件跳过**，用时 818.769 秒；Health 八项零问题，S0 `plan_lint.js` 为 0 ERROR／0 WARN，`git diff --check` 通过。S0 四项任务及阶段验收完成，可进入 S1 的真实运行时与事务基础实现。

通过范围仅为 S0 纯协议、合成记录和负向样例。真实锁、持久化账本、跨进程身份与撤销、Executor 原子接受和恢复，以及 S2–S5 业务均未实现或未验证。未修改公共契约 v1、现有 Executor、AGENTS 或真实 raw／Wiki，未提交／推送。

## 16. S0 外部缺陷复审与协议补强（2026-11-03）

S0 初次完成后，外部只读审查复现了四项缺陷：实际 Candidate 的路径未与 Coverage 绑定；Candidate 的 operation_id 未纳入准入一致性；Evidence 定位可超出 Source 可读范围；计数预算接受小数。主 Agent 独立复现确认四项均存在，并先在原实现上取得对应失败测试，再实施修复。

修复后，`CandidateChange` 显式绑定 action 和可空 source，`validate_candidate_coverage` 对公共 Candidate 与 CandidatePreview 的路径集合、动作及移动源逐项核对；最终准入同时要求 Candidate、执行上下文、Admission 和 Authorization 的 operation_id 一致。组包时 Evidence 定位不得越过 Source 可读上下界。请求数、页面数、输入字节、模型调用、修复和申诉次数均要求非负整数，只有活动时间允许小数；tokens 继续为可空整数。

外部审查者随后独立复核，结论为 **passed**：完整重算相关摘要后，路径、动作和移动源错配均拒绝，合法 move 正例仍可接受；操作身份错配、证据上下界越界及计数类型错误均拒绝。S0 目标测试增至 **59 项并全部通过**，公共契约 **18 项通过、1 项平台跳过**。最终完整历史回归 **451 项通过、6 项按既有平台条件跳过**，用时 836.615 秒；Health 八项零问题。上述结果作为当前 S0 交接凭据。

本节仍只覆盖纯协议与合成样例，不把结构校验当作真实文件内容、证据语义、教学判断或 S1 真实事务能力的证明。

## 17. S1 详细任务书与独立设计复审（2026-11-03）

已形成 [S1 详细任务书](learning-ingest-s1-plan.md)，将统一运行时与事务基础拆成六项有序任务：单一持久账本与 Invocation、生命周期与授权、Executor 终态与原子接受、Coordinator／Host 适配、真实故障矩阵、独立审查与交接。设计选择单文件权威账本、`executor.lock → runtime.lock` 短临界区、不可变记录与状态投影分离；完整 WAL 仍是唯一接受事实，不新增数据库或第二套事务。

未参与编写的独立审查者初审为 **failed**，发现五项需要修订的问题：

1. ApprovalStore 的 approve 撤销未纳入最终 G4／WAL 的跨进程串行化，可能撤销完成后仍接受旧事务。
2. capture/import 只有签发计划，没有对应 Executor 最终准入，形成半条授权链。
3. Coordinator／RuleAuditor 的 managed_call 不够具体，可能双预留或保留第二套 repairs／appeals 限制。
4. 最终审查留额未明确同时约束 Task 与 Run。
5. 终态重放缺少相同公共 bundle、不同 Admission 的负向用例。

已逐项修订：Runtime 授权与 ApprovalStore 撤销都使用 Executor 接受屏障；S1 不签发或激活受管 capture/import 授权，留待 S2 补证链；Auditor managed_call 与旧 reserve_call 互斥且只产生一条 Invocation；Task／Run 都保留最终 G3 额度；execution_bindings 保存 admission_digest 并加入终态负例。另将 Host 文案明确为 Runtime 业务撤销与 approve 撤销两条路径。

同一独立审查者定点复审结论为 **passed**，五项均关闭，未发现新增 P0／P1 协议缺陷。随后一处 Host 撤销措辞歧义已修正。该结论只表示 S1 详细设计可实施，不代表 S1 已实现、真实锁与恢复已运行或 S2–S5 已验收。

机械检查：S1 `plan_lint.js` 为 0 ERROR／0 WARN；`runtime/__init__.py` 跨 Task 1／2 的导出顺序已在任务依赖中说明。未修改代码、AGENTS、公共契约或真实 raw／Wiki，未提交／推送。当前不需要新增外部资料；实施阶段须用真实子进程和临时库取得故障证据，不能以本设计复审替代。

## 18. S1 执行与资源生命周期补强（2026-11-03）

外部审查提出三项 P1：最终准入未明确检查 Task／Run 暂停、deadline 与预算阻断；同 ID 活跃调用与崩溃遗留未区分；财务结算可能过早释放仍在运行的底层调用。另要求进入 Executor 前持久化 operation → admission_digest，并明确无 Attestation 时本次意见、Readiness 和复用资格的边界。

主 Agent 核对后接受全部意见并修订：

1. Task 暂停纳入 Executor 接受屏障；最终锁内重验 Task／Run 可提交状态、deadline 和预算阻断。G3 中暂停或实际超额均无 WAL，终态与已接受恢复豁免动态条件。
2. 新增私有 InvocationExecution，以 execution_token、recovery_epoch、心跳和条件迁移约束同 ID 执行。活跃重入只能等待／查询／busy；租约到期不证明外部资源死亡。
3. 财务结算与 resource_state 分离。unknown 保守结算但不释放并发；迟到完成只释放资源，不改写结果或退款。
4. operation → admission_digest 在进入 Executor 前保存且不可重绑，覆盖 WAL 后、结果归并前崩溃。
5. 无 Attestation 只形成 UnattestedReviewEvidence，可用于本次实际 G3，不签发可复用凭据，也不自动满足真实 L3 required_credentials。

独立 SubAgent 复审认为第 1、2、4、5 组关闭，但发现一项残余 P1：直接超时或崩溃接管后的 `inflight → draining` 入口不唯一，可能导致迟到完成无法释放资源。现已明确：直接超时在同一账本事务中保存 unknown、完成财务结算并执行 inflight→draining；崩溃接管且无结束证据时执行同一迁移；迟到完成只允许 draining→released；宿主证明全部资源终止时允许 inflight／draining→released。X3／X8 分别覆盖直接超时与崩溃接管后迟到完成。

最后一次独立定点复核调用因宿主 5 小时额度限制返回 429，没有取得复核文本。因此当前状态是**修订完成，最终定点复核未完成**，不能沿用第 17 节的 passed 覆盖本次新增修订。未修改代码、AGENTS、公共契约或真实 raw／Wiki，未提交／推送。

## 19. S1 预留与并发槽原子化补强（2026-11-03）

外部定点审查确认一项真实缺口：原设计只把 inflight／draining 计入并发，导致两个不同 Invocation 可在并发上限为 1 时都完成财务预留并停在 not_started，随后同时发送。

已按用户确认采用“预留时同时取得并发槽”方案：财务预留与 `resource_state=not_started` 占位在同一持久化临界区完成；not_started、inflight、draining 都占用并发槽，只有 released 释放。not_sent→sent 只用 token＋epoch 做条件迁移并继续持有原槽，不再分配第二个槽。证明未发送时允许同时释放财务预留和 not_started 槽；未知结果仍保持 draining。

Task 1 和 X8 已补充两个进程竞争最后财务额度／并发槽、预留后尚未发送的占位，以及发送前后另一进程均无法取得槽位的真实测试要求。该修订不需要改变整体架构或增加第二套状态。

本轮未再次调用 SubAgent；第 18 节最后一次复核已因宿主额度 429 中止，本节新增修订同样尚未取得独立复核通过。未修改代码、AGENTS、公共契约或真实 raw／Wiki，未提交／推送。

## 20. 持久循环、事务存储与受控扩展落盘（2026-11-06）

用户在调研 agent-autoloop、讨论可扩展性与过度设计后要求“先落地方案”。本轮仅更新设计，不实施协议增量或 S1，不修改 AGENTS、公共契约、运行时代码及真实 raw／Wiki，不提交／推送。

新增[运行时设计](learning-ingest-runtime-loop.md)，同步主方案、S1 任务书、路线图、README 和交接。采用持久 Event、业务 Step／Wait／WorkItem、SQLite 单一事务存储、固定可信策略与显式能力注册；Coordinator 重构为 Driver，旧入口只作参数适配。取消目标设计中的 JSON 账本及双执行模式；不建设插件市场、热替换、DSL、分布式调度或完整事件溯源。任务循环、宿主 Agent 内循环和业务修复循环分别归属，统一预算和限制可观测边界。

保留原有最终门禁：财务与资源分离、预留即占 not_started 槽、unknown 不退款／重发、双留额、可信凭据、两类授权、终态优先、完整 Executor WAL 唯一接受及独立恢复。最终接受锁顺序改为 executor.lock→SQLite BEGIN IMMEDIATE 短事务，保持数据库写串行化边界至文件 WAL 保存，不另写数据库 accepted 状态，不伪装跨存储原子提交。

S0 历史通过范围保留；新增 Task／学习阶段分离和 Event／Step／Wait 等封闭契约必须新验收，作为 S1 前置。S1 增加 L1–L9 故障矩阵，不以模型意见、结构检查或合成工作流代替真实宿主、证据和教学验收。

独立只读协议初审发现一项 P1：Step generation 换代后，原 Invocation 的可信结果缺少重新归并规则。已明确接管只换 generation、不自动增加业务 attempt；新执行者经原 Invocation 恢复绑定核验并重验依赖，形成当前 generation 的 StepResult，不新增调用或预留，unknown 保持阻断。L3 相应增加成功归并验证。该审查者定点复核结论为 **passed**，原 P1 关闭、同段无新增阻断。

第二名独立只读审查者核对新协议、S1 和主方案／路线图／交接，发现三项 P1：最终接受仍混用 Task=applying／applied；Task 2 暂停依赖到 Task 3 才产生的屏障且缺 acceptance_check 产出；主方案工具表残留“状态文件、不新增数据库”。已分别修正为 RuntimeTask 与 LearningState 分离、Task 2 先提取现有 Executor 锁并产出持有同一数据库事务的 acceptance_context／check、SQLite 领域状态与不可变产物分离。第二次定点复核为 **passed**，三项关闭且未发现新增 P0／P1。屏障及数据库事务保持至完整 WAL 保存，不以单次布尔查询替代。

机械检查：S1 plan_lint 为 **0 ERROR／0 WARN**；10 份相关文档的 **121 个本地链接／锚点有效**，围栏与尾空白检查通过；git diff --check 通过；只读 Health 八项零问题，未向正式 Wiki 写 health 日志。未运行实现测试或完整回归，因为本轮仅改设计；历史测试数字仍仅对应当时实现。

本节最终结论是**本次持久循环设计及跨文档一致性复审通过**，不是 S0 增量或 S1 实施验收通过。下一步先按 S1 §6 实现并验收新增纯协议，再进入六项基础设施任务。真实 SQLite／锁／崩溃／宿主身份及业务效果仍需逐项取得证据；本轮没有启动这些实现工作。

## 21. S1 恢复兼容、全局切变与 T0–T7 重排复审（2026-11-06）

主 Agent 与一名未参与原框架编写的独立只读审查者交叉核对 §20 新架构及真实 Host／Coordinator／Executor，发现 §20 未覆盖的阻断问题。用户随后授权重排任务，未修改运行时代码、AGENTS、公共契约或真实 raw／Wiki。

### 21.1 初审发现与架构取舍

初审发现一项 P0、两项 P1 及协议／范围缺口：文档所写 `.wiki-runtime/executor` 与真实 `state_dir/private/journals` 不一致，operation→Admission 不能定位 WAL；旧 pending 无 cutover；全局单路径未覆盖 `host/cli.py` 的 derived 直接 Executor 入口。另有 StepResult 缺 result_digest、pause→resume 语义和不可变策略修订未闭合。

架构判断：SQLite、Event 去重、Step／Wait／WorkItem 与统一执行路径有直接故障恢复依据，不属于过度设计；通用插件权限矩阵、输入输出类型系统、通用事件图、通用工作流进展声明和过早 schema 迁移框架收敛。采用静态 registry、简单 RetryPolicy、schema v1 未知版本拒绝与备份，不减少最终全局单路径目标。

### 21.2 T0–T7 任务图及复审迭代

已重写 [S1 任务书](learning-ingest-s1-plan.md) 并同步 [运行时设计](learning-ingest-runtime-loop.md)：T0 协议与入口基线；T1 旧 WAL 兼容；T2 SQLite／Invocation；T3 持久循环；T4 最终接受；T5 学习入口；T6 旧 pending 与全局切变；T7 综合验收。T1／T2 可并行，验收为 X1–X12、L1–L9 与 C1–C5。

后续独立复审先后发现并已修订：

1. Task 1 在 execution binding 存在前验收异 Admission。改为 Task 1 只查公共 bundle，Task 4 才校验私有 Admission。
2. 暂停后新 epoch 与原 operation→Admission 封闭冲突。改为 pre-WAL 旧 operation 标 `superseded_by_pause`，同 Task 以新 operation_id／Admission／Authorization 继续；已有 WAL 始终原 operation 恢复。
3. X1–X12 判定表缺失且 X6 早于 Host 改造。已在运行时文档恢复完整判定表，X6 归 Task 5。
4. 旧 pending drain 晚于 Coordinator／Executor 改造且冻结口径与 drain WAL 冲突。改为 Task 3 开头、Task 4 G3 改造前，由唯一离线 runner 仅处理 inventory 中 operation；Task 5 只核对，其他旧入口不得创建新 WAL。
5. cutover 崩溃重入未定义。采用 offline cutover，inspect／supersede 幂等并新增 C5；除清单内获准 drain operation 外无新 WAL，drain 身份必须完全一致。

同一独立审查者最终定点复核结论为 **passed**：上述 P0／P1／P2 均已关闭，未发现新的同级问题。在“全部旧 Host 停止、唯一 runner、有限 inventory”的 offline 前提下，drain 是一次性兼容步骤，不构成可持续的第二运行时。

### 21.3 当前放行范围与机械检查

当前仅表示**重排后的 S1 详细设计可实施**。Task 0 新协议、真实 SQLite、锁、崩溃、旧 WAL／pending、全局入口和宿主身份仍须逐项实现与验收，不能将本节写成 S0 增量或 S1 已通过。

S1 `plan_lint.js` 为 0 ERROR／0 WARN；跨任务同文件 INFO 均已写明 Task 1／4、Task 5／6 及 Task 0／2／3 的修改顺序。本轮仅修改设计文档，未运行实现测试或完整回归，未提交／推送。

## 22. S1 全写入口、Event 幂等与切变前置复审（2026-11-07）

外部审查在 T0–T7 设计通过后继续核对真实写面。主 Agent 与同一独立只读审查者逐项复核并修订，本轮仍只修改设计文档。

### 22.1 入口与协议修订

1. 补全 `refresh_index(apply=True)`、`run_heal(dry_run=False)`，以及 `heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 的生产写分支；T0 清单、T6 适配、C4 与 Python API 回归均覆盖五个入口，只读预览保留。
2. T1 提前创建 migration.py、cutover 测试与最小 freeze／inventory／runner／重启检查，T3 直接消费；T6 在同一文件和测试上扩展，不再后置 drain 所需设施。
3. T4 只验 Executor 接口级 approve 撤销顺序，T5 才验真实 Host revoke_pending、双线程与跨进程端到端撤销。
4. Event 增加 type，并以 task_id、type、目标版本、payload_digest 计算不可变业务信封摘要；接收序号与处理状态不参与。补同 payload 改投不同 Task／type／版本的负例。
5. S0 顶部失效锚点改为 S1 Task 0，`test_health.py` 同时纳入冻结负例与最终写语义迁移。

### 22.2 追加发现的写面与竞态问题

独立复审进一步确认：三个 heal 辅助函数可绕过 run_heal 外壳直接写；T3 drain 前这些写分支不能等到 T6 才受控。已在 T1 为五个写分支统一增加 freeze 检查，T6 再转换为受管委托或永久拒绝。

随后审查发现一次性 `assert_legacy_write_allowed` 仍有“检查后、写入前”竞态：写者通过检查后，freeze 与 drain 可能开始，旧写者继续落盘。已改为 `legacy_write_guard` 上下文管理器，在同一 executor.lock 内完成资格检查并覆盖全部实际文件写入；freeze 同锁等待已登记写者退出后发布。run_heal 外层与辅助函数共享 guard，禁止嵌套获取非重入锁；T6 不把 guard 包裹 Runtime／Executor。C5 增加检查后暂停写者、freeze 等待、drain 无迟到写入和 freeze 后拒绝。

独立审查者最终定点复核结论为 **passed**：五个写入口、切变前置、Event 幂等、approve 验收分层和写 guard 竞态均关闭，未发现新的 P0／P1／P2。

### 22.3 放行范围与机械检查

当前结论仅表示**修订后的 S1 详细设计可实施**，不是 Task 0 协议实现、S1 运行时或真实业务验收通过。

S1 `plan_lint.js` 为 0 ERROR／0 WARN；跨任务同文件 INFO 均写明修改顺序。10 份相关文档的 121 个本地链接及锚点有效；Health 八项零问题；`git diff --check` 通过。未运行实现测试或完整回归，未修改代码、AGENTS、公共契约或真实 raw／Wiki，未提交／推送。

## 23. S1 Task 0 协议实现与现状基线审查（2026-11-07）

### 23.1 实施范围

已修改 `runtime/protocol.py`、`runtime/__init__.py` 和原 S0 协议夹具／测试，新增 `runtime/loop_protocol.py`、`test_learning_s0_loop_protocol.py`、`loop_protocol_records.json` 与 `legacy_inventory.json`。实现仅限封闭纯协议、摘要、重放和真实入口清单，不实现 SQLite、调度、锁或 Executor 改造。

RuntimeTask 与 LearningState 已分离；Invocation／Admission／Authorization 绑定稳定 task_id、学习业务 ID 和 policy_digest，Admission／Authorization 另绑定 submission_epoch。Event 业务信封覆盖 task_id、type、目标版本和 payload_digest；StepResult 以 step_id、attempt、generation 为原确认键并绑定 input_digest／result_digest。静态 CapabilityManifest 不含权限矩阵、热更新或插件框架。

### 23.2 独立发现与修复

协议审查初审发现：通用绑定漏核对 learning_task_id（P1）、user_answer Wait 可缺知识／问题／rubric 版本（P2）、原跨 Task 夹具未直接改变稳定 task_id（P3）。入口审查初审发现：`raw_index.py --write` 外层委托入口未写入清单（P1）、入口测试偏源码字符串而缺行为验证（P2）、host_apply_pending 对 CLI derived 分支描述过宽（P3）。

修复后，三类运行时记录均校验学习业务 ID；用户回答 Wait 强制三个版本，其他条件类型仍可空；新增稳定 task_id 重放负例。清单补齐 raw_index 外层委托链，五个 Python API 在临时库验证预览不写和写分支实际生效，并修正 derived 描述。两名未参与实现的只读 SubAgent 分别复跑原始探针和必要测试，最终均为 **passed**，未发现新的 P0／P1／P2。

### 23.3 实测、真实基线与限制

- Task 0 目标测试 17 项通过；全部 S0 76 项通过；公共契约 Ran 18，其中 17 项通过、1 项 Windows symlink 平台跳过。
- `LegacyEntrypointTests.test_raw_write_uses_executor_and_preserves_handwritten_regions` 真实临时库子进程回归 1 项通过。
- `git diff --check` 通过，仅有既有 LF→CRLF 提示；测试后未出现额外工作树产物。
- 真实 scoped 状态中，`design-docs-graph-20261026` 的 pending 与 WAL 均为同一操作，WAL 为 applied 且 steps 全部 done；manifest、candidate、snapshot、payload_root 一致，重算 candidate digest 为 `8d22f354b791d88651c9c7be022fde8f52fe17398e2520b7b516aeb83c5698fe`，dependencies digest 为 `01ba68aa1271dbf4f8868d9ee8c0f104f3f857084e7b64eba47f9f7dba2b5d45`，均匹配。
- 当前清单范围无 pre-WAL pending、孤立 WAL、active 或 Coordinator state，无需 drain；未读取 pending.key、未验证 HMAC、未执行 recover，未修改真实 raw／Wiki。

本次通过只覆盖 Task 0 协议与现状基线，不覆盖完整 Admission 的终态绑定（T4）、SQLite／Invocation、真实锁、暂停恢复、全局切变或 X／L／C 故障矩阵。T1／T2 尚未开始，S1–S5 未因此通过；未提交／推送。

## 24. S1 Task 1／2 真实基础设施实施与独立复审（2026-11-07）

### 24.1 实施范围

T1 修改 `executor/core.py`、`raw_index.py`、`heal.py`、`test_health.py`，新增 `runtime/migration.py`、Executor 兼容与 cutover 测试及两个真实子进程夹具。`Executor.lookup_terminal` 在原 journal_root 的短锁内优先返回 applied／recovered，不调用 G3 或预算；`acceptance_barrier` 复用原 executor.lock。freeze、inventory、active 核对、白名单 drain、legacy 写保护及幂等重启均在临时库执行，未迁移或修改真实 WAL。

T2 新增 `runtime/storage.py`、`runtime/invocation.py`、运行时测试与子进程夹具，并更新 `runtime/__init__.py`。SQLite v1 使用 WAL、synchronous=FULL、外键、有限 busy_timeout 和线程局部连接；一条 Invocation 在同一事务完成 Task／Run 财务、并发、最终留额与 not_started 占位。实现成功重放、保守 unknown、draining 资源保留、可信结束释放、证据接管和 SQLite 快照备份；未实现 T3 的 Event／Step／Wait／调度。

### 24.2 独立发现、修复与终审

T1 初审由未参与实现的只读 SubAgent 复现：freeze 后真实旧 Host 可绕过 runner 创建 WAL（P0）；裸 operation_id 可绕过唯一 runner（P1）；active 未纳入 inventory／restart（P1）；locator 与 freeze 描述之间存在崩溃窗口且 drain 故障点不足（P2）。修复后，Executor 在终态初查之后、新 G3／WAL 之前于同锁核验 freeze、完整公共身份和 runner running receipt；recover 与终态重放保持豁免。裸 ID 不再授权，active 异常组合 fail closed，locator 先发布，并补齐六个 drain 崩溃边界。

T1 定点复审确认上述问题关闭，但又复现 locator-only 状态无法公开续办（P1）。最终修复在同一 Executor 锁内重算 inventory 与候选 freeze，仅当 locator root 和 freeze_digest 完全匹配时补写原描述；新增真实崩溃→拒绝→同绑定重试→drain，以及 root／digest 篡改拒绝。最终 T1 复审 **passed**，全部原发现关闭。

T2 初审复现旧 not_started 调用在恢复后可采用新 epoch 发送（P1）。修复将预留时取得的 execution_token＋recovery_epoch 传入条件发送的查询和更新，旧上下文失配即 busy 且不调用 transport；新执行者仍可显式取得唯一发送权。最终 T2 复审 **passed**，未发现新增同类问题。

### 24.3 最终实测与边界

- T1／T2 最终合并目标测试：38 项通过，其中 Executor compat 4、cutover 16、SQLite／Invocation 18。
- 全部 S0：76 项通过；Health＋旧入口＋公共契约合并 Ran 47，其中 46 项通过、1 项 Windows symlink 平台跳过。
- Executor 恢复：Ran 29，其中 28 项通过、1 项 Windows symlink 权限跳过；真实 prepared／applying／applied／recovered 与原 root 恢复回归通过。
- 两路最终独立审查均为 passed；原始攻击／故障探针在修复后重跑，不只依赖新增测试。
- 最终 Health 八项零问题；S1 `plan_lint.js` 为 0 ERROR／0 WARN（12 项既有跨任务文件 INFO 均有顺序约束）；`git diff --check` 通过，仅有既有 LF→CRLF 提示。
- 本轮没有运行完整历史套件，没有执行真实 scoped 状态的 freeze、recover 或 drain，没有修改真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。模型 token 统计为 unknown。

本次通过只作为 T3 的前置，不代表 T3–T7、X1–X12、L1–L9、C1–C5、真实 L3 或 S1 整体已通过。T4 的私有 Admission 校验、锁外 G3 与原子接受仍未实现；旧 Host／CLI 和五个 Python API 的全局 Runtime 委托仍属 T5／T6。

## 25. S1 Task 3 持久循环实施与独立复审（2026-11-07）

### 25.1 实施与真实状态边界

T3 新增 `runtime/loop.py`、`runtime/service.py`，扩展运行时导出、`test_learning_s1_runtime.py` 和真实子进程夹具。现有 SQLite 当前状态表继续作为唯一权威；新增 Event、Step、WorkItem、StepResult、Wait、回答修订、RetryPolicy、Step–Invocation 绑定、依赖失效投影、Readiness／Credential 投影、ingest Authorization、operation→Admission 与执行结果归并。规划在事务外执行，事件处理、结果和后续工作分别在短事务内原子提交。

`acceptance_context` 持有 SQLite `BEGIN IMMEDIATE` 至调用方退出，不写第二套接受事实。pause／撤销／失效复用 Executor barrier；pause 增加 submission_epoch，只 supersede 无 WAL 的 pre-WAL binding，WAL 后未归并仍保留原 operation。resume 使用同 Task 的新 Run 与 ownership，后续必须新建 operation／Admission／Authorization。approve 未接入 ingest 授权。

开始前使用修复后的 `inventory_pending` 对真实 scoped 目录重新只读盘点：`design-docs-graph-20261026` 仍为 applied 终态，身份匹配，active 已检查且为空，无 pre-WAL pending、孤立 WAL 或 drain 需求。未读取 pending.key、未验证 HMAC，未执行真实 freeze／recover／drain。

### 25.2 独立发现、修复与最终结论

未参与实现的只读 SubAgent 初审复现四项 P1 与一项 P2：接管可绕过原 Invocation；依赖变化后旧结果仍可提交；PolicyRevision 切换未更新财务预算；conflict 可被 applied 覆盖；接管返回值残留旧 schedule_key。修复增加领取时 Step–Invocation 绑定、依赖失效投影、当前 Task／Run 预算投影更新及合法执行结果迁移，conflict 必须人工对账且修复使用新 operation。

定点复审确认其中四项关闭，但又复现“同输入成功 Invocation 可搭配伪造 StepResult 领域变更”（P1）。最终修复要求 Invocation 实际返回的 `step_result_digest` 等于提交结果摘要；该摘要覆盖产物、领域变化、Wait、后续工作与失败，generation 可独立递增。原始伪造 applied 探针已拒绝且领域状态不变。最终独立复审 **passed**，无未关闭 P0／P1／P2。

### 25.3 最终实测与限制

- T1–T3 合并目标测试最终 54 项通过，其中 runtime 34 项；覆盖真实双进程领取、Invocation 成功／unknown 接管、依赖失效、预算降额、重复／过期回答、pause→resume、WAL 后归并与 conflict 防覆盖。
- 全部 S0 76 项通过；Health＋旧入口＋公共契约 Ran 47，46 项通过、1 项 Windows symlink 跳过；Executor 恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过。
- Health 八项零问题；S1 `plan_lint.js` 为 0 ERROR／0 WARN（12 项既有跨任务文件 INFO 均有顺序约束）；`git diff --check` 通过，仅有既有 LF→CRLF 提示。
- 未运行完整历史套件；未执行真实 scoped 状态的 freeze／recover／drain；未修改真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。模型 token 统计为 unknown。

本次通过只覆盖 T3 的持久循环与动态绑定，不代表真实 Attestation／真实 L3 已建立，也不代表 T4 原子接受、T5 真实 Host 撤销、T6 全局切变、T7 的 X／L／C 组合矩阵或 S1 整体已通过。

## 26. S1 Task 4 最终接受实施与独立复审（2026-11-07）

### 26.1 实施与真实故障证据

T4 扩展 `executor/core.py`、`runtime/service.py` 与 Admission 协议，新增 `test_learning_s1_executor.py` 并扩展真实 Executor 子进程夹具。受管 ingest 在初始终态查询后于锁外执行 G3，调用统一 `RuntimeInvocationPort`；最终在 `executor.lock → SQLite BEGIN IMMEDIATE` 内重跑确定性检查与动态准入，完整 WAL 保存前不释放数据库写事务。WAL 保存 admission_digest，Admission 绑定完整 manifest_digest；终态重放不依赖当前 Task／Run、预算或审查回调。

G3 的 InvocationSpec 使用稳定配置超时预留，实际调用仍受剩余时间限制；接受点前崩溃后按原 Invocation 重放，不重发模型。`verify_applied` 要求真实 applied WAL、Admission 摘要及公共绑定一致，Runtime 不得凭调用方记录消费授权。recover 继续独立读取原 journal_root，不要求 Admission、旧租约或当前可提交状态。

### 26.2 独立发现、修复与最终结论

未参与实现的只读 SubAgent 初审复现一项 P0 与两项 P1：无 WAL 的 applied 记录可消费授权；窄预算下接受点崩溃后的 G3 spec 随剩余时间变化而无法重放；Admission 未绑定完整 manifest，可替换 task、allowed_paths 和 input_refs，使 G3 改读 Wiki 而非原 raw。修复后新增无 WAL applied 无副作用、600 秒 review_timeout／900 秒总预算崩溃重试及 manifest 异绑负例。

原审查者复跑三条原始攻击路径，确认无 WAL applied 被拒绝且 Task／LearningState／授权不变；崩溃重试仅一个 Invocation、模型未重发；manifest 异绑在 G3／WAL 前拒绝。最终独立复审 **passed**，未发现新增锁顺序反转、终态动态依赖或 Admission 协议遗漏。

### 26.3 最终实测与限制

- T4 目标测试 13 项通过；T1–T4 合并最终 67 项通过，其中 compat 4、cutover 16、runtime 34、Executor 13。
- 全部 S0 76 项通过；Health＋旧入口＋公共契约 Ran 47，46 项通过、1 项 Windows symlink 权限跳过。
- Executor 恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过，单独完整复跑耗时约 546 秒。首次并行运行曾在无 traceback 下以宿主码 3840 中断；对应用例定点通过，随后无并行完整复跑通过，不将中断计为通过证据。
- Health 八项零问题；S1 `plan_lint.js` 为 0 ERROR／0 WARN（12 项既有顺序 INFO）；`git diff --check` 通过，仅有既有 LF→CRLF 提示。
- 未运行完整历史套件；未执行真实 scoped 状态的 freeze／recover／drain；未修改真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。模型 token 统计为 unknown。

本次通过只覆盖 T4 的 Executor 最终接受、接口级 approve 撤销顺序与独立恢复，不代表真实 Attestation／真实 L3、T5 真实 Host revoke_pending、T6 全局入口切变、T7 的 X／L／C 组合矩阵或 S1 整体已通过。


## 27. S1 Task 5 学习 Driver、Host 与真实撤销实施及独立复审（2026-11-08）

### 27.1 实施与真实故障证据

T5 将 Coordinator 重构为 Runtime 驱动的有界 Step Driver。Worker、Reviewer、RuleAuditor 与学习 ExecutorG3 均使用统一 InvocationPort；`state.json` 只保留兼容投影，calls、deadline、repairs、appeals 从 SQLite 重算，候选轮次从持久 manifest 派生。Worker Invocation 同时绑定 operation、轮次、完整请求摘要和 attempt；unknown、Reviewer error 及存储／执行异常直接停止，不自动重发。

新增静态 `CapabilityRegistry`，全部能力 manifest 纳入 Workflow 实现摘要，缺失、撤销或实现摘要变化会阻断旧 Task 新执行。RuleAuditor 的 `managed_call` 与旧 `reserve_call` 互斥，一次申诉恰好一条 Invocation，不嵌套双预留或双超时。

Host 学习创建、事件、回答、暂停、恢复、授权和应用均委托 Runtime；长 G3 与 Executor 屏障等待期间不持 Host 线程锁。学习 ingest 继续使用 manifest_digest、Admission、acceptance_context 和真实 WAL 归并；approve 继续使用 ApprovalStore／G4。真实 `revoke_pending` 先经过 Executor.acceptance_barrier。重新签发授权会在同一 Executor 屏障和 SQLite 事务内作废旧授权，已有 WAL 的 operation 不再签发新授权，Host 防止并发回写旧 pending 引用。

Native dispatcher 可选返回绑定 request、session、role、独立上下文和冻结输入的 Attestation。只有 `InheritedTransport` 能开启该通道；保存前重新校验完整字段并写入必需的 validator_version。无 Attestation 时仅保存 UnattestedReviewEvidence，`credential_reuse=disabled`，真实 L3 不自动通过。

真实临时库与子进程测试覆盖：同 Host 双线程和跨进程 approve 撤销；同 Host 和跨进程学习暂停；A／B 授权竞争中撤销当前引用后旧 Admission 无 WAL；受管学习应用经真实 WAL 归并；能力摘要跨重启变化拒绝；投影篡改不能重置候选或预算；合法 Attestation 保存及伪造身份拒绝。

### 27.2 独立发现、修复与最终结论

未参与实现的只读 SubAgent 在审查过程中复现能力实现摘要跨重启重绑、旧授权 A 绕过当前引用撤销，以及三项最终 P1：unknown 换新 Invocation 自动重发、合法 Attestation 缺少 validator_version 而无法保存、任意 duck-typed transport 可伪造可信身份。主执行者另修复 `state.json` 候选轮次投影可影响修复上限的问题。

逐项修复后，原审查者复跑原始探针：第一条 Worker 仍阻塞时没有第二 Worker；合法 Attestation 成功写入 SQLite；自定义对象、空 request、伪造 session、错角色和非独立上下文均不能生成凭据；旧授权为 expired，撤销后无 WAL；能力摘要变化重启拒绝。最终独立复审 **passed**。

合并回归随后发现同轮申诉与修复生成共用 Worker ID 的冲突，Worker ID 改为绑定完整请求摘要。原审查者再次补核：申诉链三次 Worker 调用具有不同 ID，同输入重放不增加 Worker 或 Invocation 数，unknown 仍直接停止；该增量复审 **passed**。没有开放的 P0／P1／P2。

### 27.3 验证范围与限制

- 独立复审：三条环境测试＋两条 Attestation 测试 Ran 5 OK；A／B 撤销＋managed apply Ran 2 OK；Worker ID 增量复审包含完整 bounded-loop 22 项与 T5 Auditor 单账本测试。
- 主执行者定点复验：三条 P1 测试、A／B 授权、能力摘要、投影篡改及 Worker ID 失败路径均通过；Native＋RuleAuditor 兼容 23 项通过。
- Executor 恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过，单独完整复跑约 534 秒。
- 全部 S0 76 项通过；Health＋旧入口＋公共契约 Ran 47，46 项通过、1 项 Windows symlink 权限跳过；Health 八项零问题；S1 plan_lint 为 0 ERROR／0 WARN；`git diff --check` 仅有既有 LF→CRLF 提示。
- 未运行完整历史套件；未执行真实 scoped 状态的 freeze／recover／drain；未修改真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。模型 token 统计为 unknown。

本节通过只覆盖 T5 学习 Driver、Host 委托、静态能力、可选 Attestation 和真实撤销／暂停，不证明真实宿主 Attestation、真实 L3、教学质量、T6 全局入口切变、T7 的 X／L／C 组合矩阵或 S1 整体已通过。


### 27.4 最终合并实测

- 最终合并 Ran 103，103 项通过：T1–T5 共 80 项（compat 4、cutover 16、runtime 34、Executor 13、Host 13），bounded-loop 22 项及旧期限权威注入 1 项。
- 此前一次 103 项合并运行有 3 个同源 Worker ID 冲突；绑定完整请求摘要后，三条原失败路径与预算重启定点通过，随后完整复跑全绿，不将失败运行计为通过证据。


## 28. S1 Task 6 旧 pending 与全局入口切变实施及独立复审（2026-11-08）

### 28.1 实施范围与协议边界

T6 将旧 pending 按 terminal、accepted_pending_recovery、pre_wal_pending 分类。无法 drain 的 pre-WAL 记录通过 `supersede_pending` 在现有 freeze 描述中封闭，报告幂等；不反造 Invocation、预算或授权。completed drain 必须保留身份一致的原终态 WAL，accepted WAL 失踪、记录失踪、异绑及未认证 pending 均阻断切变。

derived 和非学习 Host 维护统一使用 Runtime MaintenanceBinding。绑定覆盖 Task、Run、Workflow、policy、submission_epoch、created_generation 和完整候选摘要；最终接受继续使用 `executor.lock → SQLite BEGIN IMMEDIATE`，原 journal_root 和 Executor WAL 不变。学习 ingest 仍只使用 Admission／Authorization，普通 run_operation 的非学习 ingest 在模型调用前拒绝。普通维护不创建 LearningState，import-package 只登记 unprocessed raw，不形成学习入库旁路。

`refresh_index`、`run_heal`、`heal_missing_pages`、`heal_broken_links`、`heal_index_sync` 的公开和私有写模式均永久拒绝，只读预览不变；微信旧 raw helper 同样封闭并补入入口清单。Host／derived 在动态检查前加载原维护绑定并查询或恢复 WAL，applied／recovered 重放不受当前 policy、provenance 或 ownership 变化影响。维护归并要求完整 execution_result schema、状态关系以及原 WAL 规范结果一致。

### 28.2 独立初审发现与有界修复

两名未参与实现的只读 SubAgent 分别审查切变和维护入口，初审共发现 8 项 P1、3 项 P2；主执行者逐项修复并新增真实临时库负例：

1. completed drain 的 WAL 失踪后仍可能返回缓存 applied，并错误 supersede；现要求匹配终态 WAL，completed 不得覆盖。
2. running receipt 可被普通 managed Host 复用且未核身份；现仅显式 drain runner 的同一 operation 可放行，所有分支先核身份。
3. 冻结期间可先创建 pending／Task／binding，再到 Executor 才拒绝；现将检查前移到 pending、学习 Task 和维护绑定创建之前，拒绝时无这些副作用。
4. inventory 信任未认证 pending 的 runtime_managed；现逐条验证现有 pending.key HMAC 和封闭 envelope。
5. 私有 raw-index／heal helper 与微信 helper 仍可直写；现全部封闭，微信入口补登记并加行为负例。
6. MaintenanceBinding 未固定 ownership 代次；现绑定 created_generation，换代后 pre-WAL 拒绝，终态重放豁免。
7. Host 前置 policy／provenance／deadline 阻断终态重放；现先按原绑定查询或恢复 WAL，再处理非终态。
8. 普通 ingest 旧测试仍绕过学习，普通维护仍创建 LearningState；现分别在模型前拒绝和取消该投影。
9. recovered 已落盘、active 未清的合法崩溃残留被误判；现接受 terminal_stale 并可幂等清理。
10. applied＋conflict 可伪造成功；现做封闭 schema、状态关系和 WAL 规范结果核验。复审追加发现 prepared／applying＋conflict 也可伪造不可能状态，已进一步限定 conflict 只能属于 recovery_required。

中间合并运行曾分别出现 derived Task 误带 run_id、旧期限测试读取旧 Runtime 路径等失败；均修复后重跑，不将失败运行计为通过证据。独立审查指出的测试顺序和 Host 资源释放问题也已修正。

### 28.3 独立复审结论

原切变审查者复跑 WAL 失踪、runner-only、HMAC 篡改、terminal stale active、学习 Task 创建和非 derived running receipt 探针，最终 **passed**，其此前 4 项 P1 和 1 项 P2 全部关闭。

原维护入口审查者复跑私有 helper、ownership fencing、即时及 policy switch 后重放、非学习 ingest、普通维护无 LearningState、applied／prepared／applying＋conflict 等探针，最终 **passed**，其此前 4 项 P1 和 2 项 P2 全部关闭。追加的创建边界与冲突状态残余也经原审查者复核关闭；最终无开放 P0／P1／P2。

本节通过只覆盖 T6 的旧 pending、离线切变、维护绑定和全局入口，不证明真实 Attestation／真实 L3、教学质量、T7 的 X1–X12／L1–L9／C1–C5 组合矩阵或 S1 整体已通过。未执行真实 scoped 状态的 freeze／recover／drain，未修改真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。

### 28.4 最终验证记录

- 最终 T1–T6 合并 Ran 124，124 项通过，用时约 595 秒：3 项普通 Host 边界、compat 4、cutover 22、runtime 34、Executor 13、Host 13、bounded-loop 22、entrypoints 13。
- 全部 S0 76 项通过；Native＋RuleAuditor＋Host CLI＋微信 Ran 44，43 项通过、1 项 Windows symlink 权限跳过。
- Health＋旧入口＋公共契约 Ran 47，46 项通过、1 项 Windows symlink 权限跳过；Health 八项零问题。
- S1 plan_lint 为 0 ERROR／0 WARN／16 个跨任务顺序 INFO；`git diff --check` 通过，仅既有 LF→CRLF 提示。
- 完整 StandaloneHost 19 项通过；Executor 恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过，单独运行约 535 秒。此前旧 `_executor` 测试替身签名导致 1 项失败，透传新增维护参数后完整复跑通过，失败运行不计为通过证据。
- 未运行完整历史套件；模型 token 统计为 unknown。

## 29. S1 Task 7 X 组组合故障矩阵与独立复审（2026-11-08）

### 29.1 实施与初审发现

新增 `tools/tests/test_learning_s1_scenarios.py` 和 `tools/tests/fixtures/learning_s1/scenarios.json`，以真实临时 SQLite、Executor WAL、Host 双线程及子进程故障覆盖 X1–X12。初版 12 项定点运行通过后，未参与实现的独立审查者发现 1 项 P0、5 项 P1 和 1 项 P2，初版结果不作为最终通过凭据。

P0 是真实 Host 的学习 applied 重放在进入 Executor 前被动态 `build_admission` 拒绝。新增原始探针复现首次 applied、第二次 `awaiting_human/AdmissionError` 后，`host/supervisor.py` 改为先按原 operation→Admission 查询真实 WAL，命中终态则直接按原绑定归并；只有未命中才重建 Coordinator 和动态 Admission。X5 现覆盖真实 Host applied／recovered 在过期、预算阻断及合法暂停后的重放。

其他修复包括：X3 补双线程与 `not_started` 竞争、Task／Run 单次扣减及 `draining→released`；X5 去除伪造的 completed→paused 并补 WAL／财务／Invocation 快照；X7 补可信 transport 正例、自签降级、有效候选对照和真实 Driver→Host→Executor G3；X8 删除默认账本无效断言；X11 实际应用带新证据的语义补偿，并证明归档修正拒绝旧批准、接受新批准；X12 删除只被合成测试使用的 Host Readiness／Credential 直接保存入口，测试改用显式 Runtime 合成注入。场景清单已同步实际故障项。

### 29.2 最终验证与独立复审

- 既有 `test_learning_s1_host`：Ran 13，13 项通过，126.745 秒。
- X1–X6 分片：对 `ExecutionScenarioTests.test_x01_g3_interference_never_accepts` 至 `test_x06_host_revoke_and_pause_stay_responsive` 逐项执行 `python -B -m unittest ... -v`，Ran 6，6 项通过，268.641 秒。
- X7–X12 分片：对 `ExecutionScenarioTests.test_x07_identity_and_scope_negative_matrix` 至 `test_x12_host_driver_cannot_self_grant` 逐项执行同一 unittest 入口，Ran 6，6 项通过，126.486 秒。分片只用于满足单命令 300 秒限制，场景未减少。
- 原独立审查者复跑原始 Host 两次应用探针，结果首次和第二次均为 applied 且 execution 相同；另独立复跑 X3、X5、X7、X11、X12，全部通过。复审结论 **passed**，原 P0／P1／P2 全部 closed，无开放阻断。

本节只证明 X1–X12 组合故障矩阵及其修复。L1–L9、C1–C5、T1–T7 最终合并、完整历史套件和 S1 整体尚未验收；真实宿主 Attestation、真实 L3 与教学质量仍未验证。未操作真实 scoped 状态、真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。

## 30. S1 Task 7 L 组组合故障矩阵与独立复审（2026-11-08）

### 30.1 初审发现与产品修复

L 组使用真实临时 SQLite、双进程领取、提交后响应丢失及重启续办覆盖 L1–L9。初版 9 项通过后，独立审查发现 5 项 P1 和 4 组 P2 断言缺口。主执行者以原始临时库探针复现后完成有界修复：

- 通用 LoopProposal 不得自报 `learning_state=applied` 或直接封闭 Task；正式 applied 仍只能由真实 Executor WAL 归并。
- Event 规划提交原子比较当前与冻结 LearningState 摘要，旧快照保持 pending 并可在新快照下重规划，不覆盖已提交知识版本。
- Readiness 的凭据包版本必须与当前知识版本一致，签发授权、构造 Admission 和最终接受均重验。
- unknown Invocation 在增加 generation 前持久阻断 Task／Step／WorkItem；后续无工作、不无限换代、不重发。
- Attestation 最终由 `InheritedTransport` 私有登记和一次性消费；普通字典、未登记 token、字段改绑、持久化重放及重复消费均拒绝。初审后复审又发现公开铸造与句柄改绑两条路径，均已复现并关闭。

P2 断言同步补强：必需检查删除、真实非零预算跨重启、写入后晚期失败全量回滚、备份恢复重放原 Invocation、partial 用量与 unknown token。`runtime_process.py` 只增加测试所需的领取租约和 Invocation 绑定参数。

### 30.2 最终验证与复审结论

- L 组与 `test_learning_s1_runtime` 合并：Ran 43，43 项通过，4.844 秒。
- 真实 Native／Coordinator／Attestation 定点：Ran 3，3 项通过，3.447 秒。
- Host＋X7／X12 合并：Ran 15，15 项通过，166.661 秒；最终全量回归仍需在最新句柄实现下复跑。
- 原独立审查者先确认其余 4 项 P1 和全部 P2 关闭，再复跑公开工厂与真实句柄改绑探针，确认工厂不存在、改绑为 `AttestationError`、克隆与持久化重放不能重复消费；最终复审 **passed**。

可信登记是 transport 进程内状态；未消费句柄跨进程不可继续消费，保存凭据失败后需重新审查，均为 fail-closed。按既定协作边界，不防同进程可信代码直接改私有登记或 monkeypatch。C1–C5、T1–T7 最终合并、完整历史套件和 S1 整体尚未验收；真实外部宿主 Attestation、真实 L3 和教学质量仍未验证。未操作真实 scoped 状态、真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。

## 31. S1 Task 7 C 组切变矩阵与独立复审（2026-11-08）

### 31.1 场景与缺陷修复

C1–C5 使用真实旧 WAL、认证 pending、Executor、Host、Python API 与子进程崩溃覆盖切变组合。初审确认 C1、C3、C4 有效，发现 locator-only 旧 guard 写入 P1 与报告自声明 P2。主执行者复现 guard entered 和真实目标写入后，在 locator 前增加 root 级 cutover intent，旧 guard、Executor 新 WAL 与 Runtime 创建均在 intent／freeze 未完成时 fail closed；C5 新增 guard／writer 拒绝后续办。

报告删除 `global_single_path`、`invocation_history_fabricated`、`budget_reset` 三个常量字段。C2 改为直接比较 pending 与 `state/operations` 历史字节，并确认 Runtime／Invocation 数据库未创建；全局入口证据由 C4 的真实 derived 与五个 Python API 组合提供。

复审又发现 intent-only 续办可重绑清单并吸收迟到 pending。原始探针复现 digest 改变且迟到操作 applied 后，新增封闭 `_read_intent`，已有 freeze 和无 freeze 续办均强制核对 root、state_dir 与 freeze_digest。C5 新增 intent-only 正常续办、摘要篡改、迟到 pending 拒绝及无 WAL；原探针最终为 `INTENT_REBIND_CLOSED`、`INTENT_UNCHANGED=True`。

### 31.2 最终验证与复审

- 完整 C 组：Ran 5，5 项通过，122.044 秒。
- C5＋完整 cutover 曾 Ran 23，仅旧“描述缺失”文案断言与新 `cutover intent` 拒绝不一致；更新文案后原 locator 测试复跑通过，其他 22 项通过。完整合并将在最终回归重跑。
- intent 修复后的 C5：Ran 1，1 项通过，57.828 秒。
- 原独立审查者复跑 C5、迟到 pending、已有 freeze 篡改和旧 freeze 无 intent 兼容探针，确认迟到记录不能 drain、无 WAL、旧 freeze 可补写同绑定 intent；最终复审 **passed**，无开放 P0／P1。

T1–T7 最终合并、完整历史套件和 S1 整体尚未验收；真实外部宿主 Attestation、真实 L3 与教学质量仍未验证。未操作真实 scoped 状态、真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。

## 32. S1 整体组合审查与三项协议修复（2026-11-09）

### 32.1 首轮合并与整体审查发现

首轮 T1–T6 合并 Ran 121、全部通过（584.860 秒），X／L／C 合并 Ran 26、全部通过（522.038 秒）；S0 76 项通过，公共契约 47 项中 46 项通过、1 项 Windows symlink 权限跳过，Host 相关 63 项中 62 项通过、1 项同类跳过。整体独立审查仍以组合探针发现 1 项 P0 与 2 项 P1，因此上述全绿不作为 S1 放行凭据。

- **P0 授权竞争**：重新授权 B 已生效、pending 尚未回写时，撤销只处理旧 A，随后真实 applied。现按 operation 在同一屏障与事务中撤销全部未消费授权，Host 回写前重验新授权仍 issued；原始交错现为 A/B 全 revoked、回写拒绝、无 WAL。consumed 历史拒绝撤销且字节不变。
- **P1 通用暂停**：LoopProposal 可直接 paused 而不增加 epoch、不停 Run、不作废 Admission。现 completed/canceled/paused 均只能走受信协议，planner 与 StepResult 负例均保持原状态。
- **P1 全状态归并**：无 WAL recovered 曾被接受并阻止真实 applied 收敛。现 Executor 对 prepared/applying/recovery_required/conflict/applied/recovered 全状态核验真实 WAL、Admission、公共摘要与 recovery_status，Runtime 归并统一调用；伪造结果不再落库，真实 applied 可完成 converged。

### 32.2 修复复审

新增 Host 授权交错 1 项、通用 paused 1 项、Executor 全状态 1 项，并更新 Runtime 的匹配 WAL 夹具；相关原始失败路径全部复跑通过。原整体审查者独立复跑三个原始探针及补充状态矩阵，确认：授权竞争后 `apply=False、WAL=False`；paused 两条入口不变；伪造 recovered 拒绝，真实 prepared／applying／recovery_required／conflict／applied／recovered 均可按原语义归并。复审结论 **passed（限三项修复及补充探针）**，不是 S1 整体通过声明。

修复后的首次合并 Ran 124，仅 `test_pause_with_wal_before_reconcile...` 仍写空 `{}` 假 WAL 而失败；将其改为合法 prepared WAL 后原测试通过，并扫描确认无同类空夹具。最终 T1–T6 合并 Ran 124、全部通过（580.494 秒），X／L／C 合并 Ran 26、全部通过（512.151 秒）。

Executor 独立恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过（531.897 秒）。完整历史套件正在执行；真实外部宿主 Attestation、真实 L3 与教学质量仍未验证。未操作真实 scoped 状态、真实 raw／Wiki、AGENTS 或公共契约 v1，未提交／推送。

## 33. S1 最终验收通过（2026-11-09）

完整历史单进程运行到 X11 时达到 1800 秒上限，日志无断言失败，但未计为通过。随后使用三路并行分片覆盖除独立 Executor 恢复外的全部 37 个测试文件，全部退出码 0，共 569 项，`FULL_HISTORY_SHARD_FAILURES=[]`；加上独立恢复的 29 项，共 38 个测试文件、598 项测试完成。独立恢复为 28 项通过、1 项 Windows symlink 权限跳过；其他既有权限跳过按各套件实际结果保留，不宣称无跳过。

其余最终证据：T1–T6 合并 124 项通过，X／L／C 26 项通过；S0 76 项通过；公共契约 47 项中 46 项通过、1 项权限跳过；Host 相关 63 项中 62 项通过、1 项权限跳过。Health 八项零问题，S1 plan_lint 为 0 ERROR／0 WARN，`git diff --check` 通过，10 份设计与运行文档的 77 处本地链接无缺失。

原整体独立审查者机械核对 38 个文件与 598 项计数，复查三组缺陷关闭和全部日志后给出 **S1 overall passed，开放 P0／P1／P2 为零**。据此，S1「统一任务运行时与文件事务基础」验收通过，T0–T7 全部完成。

通过范围不包括：真实外部宿主 Attestation 与 dispatcher 权限、真实 L3、真实课程／判分校准／教学效果与用户负担、真实 scoped 状态的 freeze／recover／drain、真实 raw／Wiki 业务批次，以及 S2–S5。Windows symlink 权限跳过与协作门禁边界继续保留，不宣称 OS 强制隔离。未修改 AGENTS 或公共契约 v1，未提交／推送。

## 34. S1 恢复、执行资格与结果完整性修复复审（2026-11-09）

### 34.1 新审查与采纳范围

后续外部审查以 5 项 P1、3 项 P2 推翻当前实现可继续作为 S2 前置的结论。主执行者逐项对照源码，并用临时库独立复现其中 7 项；Coordinator 持久 Step 缺口由实际调用链确认。八项全部采纳，§33 仅保留为此前版本的历时记录，不作为本次修复版本的通过凭据。

修复内容：

1. Host 终态查询与 Runtime 归并复用同一 Executor，覆盖跨 Host applied／recovered 重放。
2. Coordinator 的 Worker、Reviewer、RuleAuditor 和修复计费接入持久 Step；成功 Invocation 未归并时按原 Step 只读恢复。已冻结候选按 round 找到唯一原 Worker Invocation，不重建本地请求、不新增候选。
3. Invocation 在原子预留和实际发送两个边界核对 Task／Run、当前 policy、ownership、期限与财务阻断；成功结果只读重放豁免动态资格。
4. `follow_up_digests` 同时绑定 Step 不可变定义与 WorkItem，接管者不能改绑后续输入。
5. Executor 在 WAL 持久化 recovery_status，学习和维护归并均从 WAL 派生；无该字段的旧 WAL 不接受调用方自称的 conflict。
6. 重试和已有 WorkItem 领取均受当前 PolicyRevision 的停止策略约束。
7. 失效依赖局部阻断受影响 Task，继续扫描其他 Task。
8. 未发送资源释放使用既有浮点容差归零语义。

### 34.2 独立复审与追加修复

未参与实现的只读审查者实际运行 16 项定点测试并补做活跃执行者竞争、同 Task 阻断探针。初审确认 7 项关闭，但发现同 Task 阻断后仍可能从预取快照领取另一 WorkItem，形成 Task=blocked、WorkItem=claimed 的 P2 不一致。修复在单次扫描中记录 blocked_tasks 并跳过其剩余候选，新增同 Task 负例。原审查者复跑原始探针与 3 项相关测试后给出 **overall passed，开放 P0／P1／P2 为零**。

### 34.3 已执行验证与当前边界

- 8 项原始缺陷及追加 P2 的新增定点回归均通过；两类 Coordinator 崩溃点均保持 Worker／Reviewer 各一次外呼、一个候选、两个完整 StepResult。
- 状态投影篡改场景保持 6 次调用、3 个候选且无新增 Worker 外呼；跨 Host applied／recovered 重放通过。
- T1–T6 合并 Ran 135、全部通过，700.681 秒；StandaloneHost 19 项通过；S0 76 项通过。
- 公共契约 Ran 47，46 项通过、1 项 Windows symlink 权限跳过；Native／RuleAuditor／Host CLI／微信 Ran 44，43 项通过、1 项同类跳过。
- X／L／C 首轮有 3 项测试辅助调用未提供成对 Step；修正 L2／L5／L8 后定点 3 项通过。最新代码的三路完整历史分片通过：37 个文件、581 项测试全部退出码为 0；分片 0／1／2 分别为 198／224／159 项。
- Executor 独立恢复 Ran 29，28 项通过、1 项 Windows symlink 权限跳过，525.298 秒。合计 38 个测试文件、610 项测试完成。
- Health 八项零问题；S1 plan_lint 为 0 ERROR／0 WARN；`git diff --check` 通过，仅既有换行提示。

**本修复批次最终结论：passed。** 八项原缺陷及追加 P2 均关闭，独立复审和最新完整回归通过，S1 可重新作为 S2 的前置。本轮仍未操作真实 scoped 状态、真实 raw／Wiki，未修改 AGENTS 或公共契约 v1，未提交／推送。该结论不等于真实宿主 Attestation、真实 L3、教学质量、真实业务批次或 S2–S5 已通过。

## 35. S1 队列与候选发布边界追加复审（2026-11-09）

后续审查发现 §34 仍漏掉两项 P2：过期 WorkItem 的原 Invocation 为 pending 时，领取异常中止全局扫描；round 目录只写入 candidate 和 payload 后，重启把目录存在误判为完整发布并停在 FileNotFoundError。两项均采纳，§34 的通过结论仅属于其对应版本。

修复后，pending 原调用仅使所属 Task 在本轮扫描中暂时跳过，不改写 Step、WorkItem、Invocation 或 generation，其他 Task 可继续领取。候选发布不再以目录存在作为完成凭据；candidate、逐份 payload、dependencies 和 manifest 均执行“存在则比对，缺失则从原 Worker 结果补齐”，已有内容不一致或截断异绑均拒绝。

新增原始场景回归通过：pending 队列、同 Task 阻断与跨 Task 扫描 3 项；半写 round、原崩溃恢复与候选修复闭环 3 项。独立审查者另运行 6 项定点测试及 candidate、payload、dependencies、截断 manifest 四类篡改探针，确认篡改均 awaiting_human，Worker 不重复外呼、Reviewer 不接收异绑内容。复审结论 **overall passed，开放 P0／P1／P2 为零**。

最新代码的三路完整历史分片全部通过：分片 0／1／2 分别为 199／225／159 项，共 37 个文件、583 项，所有退出码为 0。Executor 本轮未改，§34 的独立恢复 28 项通过、1 项权限跳过仍适用；合计 38 个文件、612 项测试完成。

**本节最终结论：passed。** 两项追加 P2 均关闭，独立复审与最新完整回归通过，S1 修复版可继续作为 S2 前置。未操作真实 scoped 状态、真实 raw／Wiki，未修改 AGENTS 或公共契约 v1，未提交／推送。真实宿主、真实 L3、教学质量与 S2–S5 不在通过范围。