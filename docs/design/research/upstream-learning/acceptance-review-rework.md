---
type: meta
title: 上游学习应用研究返修复审记录
status: research_rework_record
updated: 2026-11-10
topic: 验收返修过程与复核
related_sources: []
related_synthesis: []
---

# 上游学习应用研究返修复审记录

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-10。审核者：原对话主 Agent。

**结论：认可“完整采用 OpenMAIC，避免自建课堂及拼接两套学习存储”的选型方向；整份交付物仍暂不验收通过。** 还有三项影响学习结果交接正确性的 P1 问题，以及两组需要纠正的 P2 表述。它们不要求重新选型、重新研究六仓或部署产品，但应在编写导出器和冻结规则之前解决。

本次读取返修后的四份产物，独立核对固定提交与证据定位，并追踪测验评分失败、课程 revision、PBL 状态与沙箱调用链。未修改原研究文档、上一轮审核记录或业务代码；未安装、构建、启动、调用模型或执行上游模块。

## 1. 上一轮 R1–R8 的处理情况

| 项 | 本轮判断 | 说明 |
| --- | --- | --- |
| R1 部署与 SDK 边界 | 主要问题关闭 | 已明确采用完整应用与原生 PostgreSQL，不再假设两个 SDK 就拥有生成、课堂与目录交付。PBL 的部署及导出覆盖仍见 N3 |
| R2 教学交互 | 主要问题关闭 | 已定位页面 → `/api/chat/pi` → Director/工具/子代理 → SSE → chat 持久化。受辅助推断的边界仍需按 N4 收紧 |
| R3 唯一写入与恢复 | 部分关闭 | 不再移植第二套学习库是正确修订；评分失败、历史输入版本与 PBL 状态覆盖仍有源码误读，见 N1–N3 |
| R4 公平比较 | 基本关闭 | 已接受原生 PostgreSQL和完整应用，目录、SQLite 不再是决定性门槛。成本表应区分必需与可选，不能把代码行数当作只能全部重写的证明 |
| R5 暂存与显式触发 | 关闭 | 已补暂存、显式整理、查已有知识、分流、学习后外部整理职责。后续实施继续区分 ingest 与 approve |
| R6 证据定位 | 机械问题关闭 | 独立检查 850 条：806 条代码定位、26 条 search、7 条 listing、11 条 directory；代码定位的文件、行号、仓库与提交均通过，三份正文的显式证据 ID 均存在。定位正确不保证观察或推论正确 |
| R7 实际采用的检索能力 | 关闭 | 已删除未引入 DeepTutor 检索却宣称被覆盖的论证；本期不引入向量检索及逐题引用的取舍已明确 |
| R8 移植范围与依赖 | 本期决策关闭 | 明确不移植 DeepTutor，计入真实依赖与租约恢复责任。不采用部分仍有“纯策略仅标准库”的错误表述，见 N5 |

六个上游仓库的 HEAD 均与 manifest 一致、工作区干净。没有因为缺少运行测试而判定本轮不通过。

## 2. 需要修订的三项 P1

### N1 · P1：短答评分失败会保存基础分，不能按“submitted 且评估缺失”导出

**原稿位置：** [architecture-proposal.md](architecture-proposal.md) 第 271 行；同类恢复和交接结论同步检查 `report.md`、`acceptance-request.md`。

原稿写“失败时不会写 results，runtime 停在 submitted”。真实调用链相反：

1. [`quiz-view.tsx`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/components/scene-renderers/quiz-view.tsx) 第 93–139 行的 `gradeShortAnswerQuestion` 捕获评分错误，返回 `correct: null`、`status: 'incorrect'`、`earned: Math.round(pts * 0.5)` 和“评分服务暂时不可用，已给予基础分”评语。
2. 同文件第 801–824 行合并这些返回值，并调用 `persistQuizReview`，**不会因为评分服务失败而跳过保存**。
3. [`quiz/runtime.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/quiz/runtime.ts) 第 623–636 行会把 reviewed 记录与父 session 的 completed 状态一并提交。这里还需区分“模型评分失败”和“持久化失败”，后者才可能留下 submitted。

**后果：** `phase=reviewed`、存在 results、session completed，均不能证明模型评分成功。直接映射为 `assessment: ok` 会把本地兜底基础分当成实际模型 verdict，并错误地向外部 Agent 表示已经评估。

**最小修订：** 写出上游真实状态转移，按题区分“确定性评分 / 模型评分 / 本地兜底 / 无评估 / 无法判断”。在这个固定提交下，`correct: null` 可作为该兜底路径的静态识别线索；需保留原始值和判断依据，不伪装成上游显式的错误码或模型结果。交接不能只用 `ok|missing` 两档覆盖整份尝试；混合题型允许部分题成功、部分题兜底。无需先修改上游代码，也不代跑评分模型。

### N2 · P1：当前 revision 不是历史快照，也没有绑定测验尝试的输入版本

**原稿位置：** `architecture-proposal.md` 第 59、160、172、254、357、364 行，以及 A3“交接时记录 rev、变化即新版本”。

[`stages/[id]/manifest/route.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/app/api/stages/%5Bid%5D/manifest/route.ts) 第 1–11 行把 manifest 明确定义为 **freshness manifest**：触发器维护当前 revision，帮助客户端只重新读取变化场景。它不提供“读取 rev=某旧值的课程内容”的历史存储保证。

[`quiz/runtime.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/quiz/runtime.ts) 第 19–34、253–259、514–536 行显示：

- 尝试负载是 phase、answers、results，没有课程 revision、题干/rubric 的历史快照；
- 确定性尝试身份基于 stageId、sceneId、learnerKey，没有内容版本；
- `runtimeDslVersion` 是 runtime 契约版本，不能充当课程内容版本。

**后果：** 先答旧题，再在同 stage/scene 下编辑题目或答案，最后导出当前 manifest 与场景，就可能把旧回答、旧评分和新题目/目标拼在一起。导出时才记录当前 rev，不能还原当初评分输入，也不能支撑“保留实际模型 verdict 与输入版本”“随时可重算”的承诺。

**最小修订：** 在设计中明确一种方案即可：

- 开始学习前保存包含实际题干、选项/答案键、rubric、目标、来源清单的课程快照；记录固定内容身份；同一身份学习期间禁止内容变更，变更则另建新的课程身份。导出发现 revision 与基线不符应拒绝绑定或标记版本未知。
- 或承认上游尚不能绑定历史尝试的内容版本，将这些旧记录标为 `contentVersion: unknown`，不拼接为已验证的历史评估证据；新增的绑定机制如需修改上游，明确计入适配成本。

快照是学习证据的必要输入，不是要求另建第二套可独立编辑的课程真值。需说明快照采集时点、实际保存内容及变化后的处理；仅保存 rev 数字不够。导出中的多个 HTTP 读取也应有一致性检查，例如读取前后 manifest 比较并在变化时重试或标明不一致。

### N3 · P1：四类课堂不共用一个 RuntimeStore 状态面，PBL v3 的导出与沙箱被漏计

**原稿位置：** `architecture-proposal.md` 第 18、27、243–248、280、327、357–361 行及 A1/A2。文档承诺四类课堂，把所有学习状态和事务都归到 `RuntimeStore.appendRecord`，导出器主要读取通用 runtime、stage 和 generation-run。

**源码事实：**

- [`components/scene-renderers/pbl-renderer.tsx`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/components/scene-renderers/pbl-renderer.tsx) 第 39 行遇到 `projectV3` 进入 PBL v3，不是普通 QuizView。
- [`persistence/pbl-studies.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/persistence/pbl-studies.ts) 第 12–31 行建立独立的 `pbl_v3_studies`、roles、commands、events；后续 migration 还有 evidence/reports。
- [`server/pbl-v3/store.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/pbl-v3/store.ts) 第 24 行之后的 Study 及其事务维护项目状态、环境、revision 和 evaluation，不由通用 `RuntimeStore.appendRecord` 单独负责。
- [`api/pbl/v3/route.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/app/api/pbl/v3/route.ts) 第 33–63 行按 stage/scene 查 `LearningStore.findForScene`，返回 studyId 等；不是从通用 runtime 记录还原项目学习状态。
- [`SandboxService.forOwner`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/sandbox/service.ts) 第 66–74 行使用 E2B-compatible provider；[`sandbox/config.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/sandbox/config.ts) 第 27–48 行要求有效的沙箱配置，未启用会抛 `SANDBOX_DISABLED`。应用与 Postgres 两个容器不自动提供这个执行服务。可自托管兼容服务或选择供应商，但这是额外的依赖和成本。参见 [sandbox README](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/sandbox/README.md)。

**后果：** 上游应用可以是唯一业务写入方，但不等于它内部所有领域只有一张 runtime 事实流、一个事务边界。当前导出契约只有 quiz attempts，无法完整交接 PBL 项目证据。普通测验 attempt 的 completed、聊天 session 的 completed，也不能直接当作整门课程学习完成。

**最小修订：** 给 slide、quiz、interactive、PBL 各列学习事实、持久化/API、完成含义和交接覆盖。可以明确本期只交接普通课程/quiz，排除 PBL v3 并防止产出未支持课程；也可以保留 PBL，补其只读 API/证据映射、沙箱配置和预算。不要为统一模型再造一套学习库；将“唯一写入方”改成“上游应用”，分别说明其内部领域的事务与版本。课程完成可由显式用户动作定义，但不能未经定义就等同某个 session completed。

## 3. 两组 P2 修订

### N4 · P2：没有同场景聊天记录不能证明独立作答

**位置：** `architecture-proposal.md` 第 227–233 行、A5。

当前规则是一个尽力推断，作为辅助线索可行；但应写清三值的判定表，避免“未查到聊天 ⇒ assisted=false”。

[`ChatSessionStatePayload`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/utils/chat-storage-core.ts) 第 30–43 行里的 sceneId 是**可选的 session 状态字段**，不是每条教学内容都带题目身份的独立帮助日志。同文件第 16–17、232–240 行还有聊天保留/裁剪规则。场景外讲解、缺场景标记、其他地方的提示及不完整记录，都可能让负向推断失效。跨 session 的 seq 也不是全局时间序。

**最小修订：** 明确“有同场景先行对话”只表示有辅助迹象，保留 evidence refs、规则版本及推断范围；没有足够证据时用 unknown。false/独立作答需要明确受控条件或用户声明及其来源，不能由日志缺席推出。交接中区分原始事实、派生迹象和外部判断；已有的“不等同掌握度”限定继续保留。

### N5 · P2：修掉仍被标成确定事实的三处过度推论

1. **一次页面 POST 不等于一次模型调用。** `architecture-proposal.md` 第 509 行称“教学对话每回合一次模型调用 + 可能的子代理委派”。[`director-loop.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/chat/pi/director-loop.ts) 第 223–267 行运行带工具的 Agent loop，工具结果进入循环；`call_agent` 还会执行子模型，压缩也可能调用模型。改成“每回合一次 HTTP 请求，内部模型调用数由 Director 工具轮次、子代理和压缩决定”。无需实测具体次数，但不能按一次调用估价。
2. **没有 publishConfig 不能证明未发布。** `architecture-proposal.md` 第 146 行及 OM-A-081 从 editor 的 package.json 没有 publishConfig 推出“未发布”。这只能说明缺少该显式配置；是否在 registry 发布需要发布记录证据。标为未知即可，本期完整应用采用 workspace 构建，不以此作为阻断条件，不需要强行联网或安装。
3. **policy.py 不是可直接独立 import 的纯标准库模块。** `architecture-proposal.md` 第 422 行的方案 C 写“仅标准库，无 pydantic”。[`policy.py`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/policy.py) 第 24–31 行导入 learning.models 和 pending；models 依赖 Pydantic。可以说移植算法后能设计成纯函数，但应承认那是重写和数据适配，不是当前文件的原样依赖闭包。本期不采用，不构成选型阻断。

相关 evidence 的 observation、certainty/limitations、report 和 acceptance-request 一起更新，不必扩充总条数。

## 4. 返修范围与下一次验收

只需要修订四份研究交付物，不改本记录或第一轮记录，不实现产品：

1. 将 N1 的真实失败结果纳入交接 schema，给一份“选择题成功 + 短答评分服务失败”的静态示例映射。
2. 将 N2 的内容版本绑定方案写清，说明“学习后编辑再导出”如何拒绝错配或标 unknown。
3. 选择 N3 的本期课程范围，补实际存储/API/依赖/完成定义的覆盖表；不要求把所有类型都纳入本期。
4. 收紧 N4 的三值推断，修正 N5 的成本和证据表述。
5. 在 acceptance-request 中逐项引用修改位置和证据。继续保留完整 OpenMAIC 的选型，不要求为这几项回到 SDK 拼装路线。

本轮认可的是选型方向及已修好的源码边界；尚未认可的是“仅靠只读导出、当前 revision 与统一 runtime 就能完整交接四类课程学习证据”的实现前提。复审仍以源码与设计映射为准，不以部署或真实模型调用为门槛。