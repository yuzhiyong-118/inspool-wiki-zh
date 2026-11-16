---
type: meta
title: 上游学习应用研究验收记录
status: research_accepted
updated: 2026-11-09
topic: 研究验收过程与逐项核对
related_sources: []
related_synthesis: []
---

# 上游学习应用研究验收记录

> 本文为上游选型与原始研究记录。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](../../upstream-sources.md)的固定提交与文件路径，结论与分析随正文发布。文中状态与结论对应原文写作时点，不代表当前部署或验收完成。

日期：2026-11-09。审核者：原对话主 Agent。范围：四份研究交付物、任务手册、固定版本源码，以及两个 npm 包的官方发布元数据。

**结论：本轮整体暂不验收通过，不建议按当前组合方案开始实现。** 已有研究可继续使用，无需重做六个项目的全量调研；修订下面的指定部分即可。阻断原因是源码能力与推荐架构之间存在断点、用户目标遗漏和证据定位问题，**不是缺少安装、模型调用或运行测试**。

未修改研究原稿、正式业务代码、raw、wiki、AGENTS 或阶段状态；未安装依赖、启动服务、导入上游模块或调用模型。

## 1. 已核对与可以保留的内容

- 六个克隆仓库的 HEAD 均与 [上游来源清单](../../upstream-sources.md) 一致，工作区均干净。
- `source-evidence.json` 有 575 条、无重复 ID，研究对六个项目的覆盖有价值；**数量和字段非空不代表位置、归属或推论已经正确**。
- OpenMAIC 主应用的课堂、课程生成、过程记录，以及 DeepTutor 的教学策略、学习领域事务，均有真实源码实现。把教学判断与事实记录分开、把学习完成与掌握及入库分开，是合理方向。
- 不把 MCP Client 当作产品 MCP Server，不把工具能力搜索当作 schema 延迟加载，不虚构 token 节省比例，这些判断应保留。
- Open Notebook MCP 适配器与后端之间确有静态契约差异；直接评估后端 HTTP 是合理备选，但须修正证据归属和引用。
- 不要求消费端继承现有维护 Runtime 的全部治理机制，是合理候选方向；这不自动证明拼接两套学习存储更简单。

## 2. 需要修订的问题

### R1 · P1：存储 SDK 被当成完整课程生产和消费底座，部署边界不成立

**原稿位置**：[architecture-proposal.md](architecture-proposal.md) 第 90 行、第 147–181 行、第 215 行、第 293 行。第 90 行声称依赖包、实现两个接口即可；流程又要求调用课程生成 HTTP，并假设生成结果会落到本地课程目录。

**源码核对：**

- [`@openmaic/storage` 的 handler](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/src/server/index.ts) 第 729、779 行提供的是 runtime、document 和可选 asset 存储协议，**不提供** `/api/materials`、`/api/generate-classroom` 或课堂 UI。
- [`/api/generate-classroom`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/app/api/generate-classroom/route.ts) 第 49 行调用应用内 `startGenerationRun`；[`start.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/generation/run/start.ts) 第 24–31 行依赖 runner 和 run store；[`runner.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/generation/run/runner.ts) 第 1–10 行明确有应用进程内的生成 worker；[`store.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/generation/run/store.ts) 第 1–28 行依赖 PostgreSQL、生成运行 schema 和材料持久化。外部 Agent 发 HTTP 请求，并不会把这些服务端职责转移到外部 Agent。
- [`renderer/src/index.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/renderer/src/index.ts) 导出 slide 画布、元素和效果；完整四类分派位于应用内的 [`scene-renderer.tsx`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/components/stage/scene-renderer.tsx)。Quiz 页面还有应用内 runtime、恢复、国际化和评分接线；PBL 还依赖应用内工作区与服务。
- 存储接口的声明也不会自动赋予一个新 SQLite 后端正确性。例如 [`RuntimeStore`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/src/runtime/types.ts) 第 120–238 行要求版本迁移、原子追加、CAS、状态转换和整体归并语义，这些仍由新后端实现。

**影响：** 目前不存在图中那个“仅靠两个 npm 包就同时拥有官方生成 HTTP、四类课堂和目录交付”的部署单元。生成服务、资产、课程包导出/导入和播放器接线的成本被漏计。

**最小修订：** 明确选一种成立的部署方式：

1. 完整 OpenMAIC 提供生成与课堂，使用其实际数据库和 API；只补确有必要的交接、状态或界面能力。
2. 完整 OpenMAIC 只作独立生产方，明确其部署、模型调用、资产与导出职责；本地消费端是另外一个需要开发的应用。
3. 外部 Agent 直接生产约定课件，消费端只复用选定 SDK/源码；删除实际上没有部署的生成 HTTP 和相关“现成能力”承诺。

为选定方式列出“实际部署/依赖/复制代码/自建”四类清单，补齐生成结果到冻结课程包的路径，再估工作量。不要同时领取三种方式的优点。

### R2 · P1：删除课堂对话后，内部 Agent 只剩判定，用户追问与讲解缺位

**原稿位置**：`architecture-proposal.md` 第 28–36 行承诺自己的学习与问答界面；第 171–196 行的流程只有播放、答题与评估；第 215 行明确不引入 Director，并把唯一内部 loop 用于定性判定。

[`semantic_assessment.py`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/semantic_assessment.py) 第 172–210 行是按题目、答案、rubric 和来源给出 verdict 的受限判定请求。它不能代替教学对话，也没有覆盖会话历史、课程定位、追问、举例、提示和工具上下文。一次结构化判定本身也不必包装完整 AgentLoop。

**影响：** 用户可以播放和被评分，却没有方案承接“这里不懂，请换个例子”“根据我的回答继续讲”等关键需求。之前想复用成熟 harness 的主要动机没有落实。

**最小修订：** 单独写清教学对话链：页面输入 → 当前课程/场景/相关材料与学习状态 → 历史与预算 → 模型/工具 → 流式讲解 → 对话保存。明确复用哪个已接线的上游路径，或者如实列为自建。不必引入通用工具平台，但不能把判分当教学。提示使用与答案展示应进入学习证据，避免随后把受辅助回答计为独立掌握。

### R3 · P1：两套学习状态机制的组合缺少唯一写入者、映射与恢复语义

**原稿位置**：`architecture-proposal.md` 第 204、258–285、293–294 行。一处规定独立 SQLite 是真值，一处引入 OpenMAIC RuntimeStore 作 L1，同时又移植 DeepTutor 的 storage/models 等并维护 L2 判定表。

**源码核对：**

- [`DeepTutor LearningTransaction`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/storage.py) 第 111–150 行的保证来自同一个 SQLite 事务，联合提交 progress、interaction 与事件；第 803–829 行持久化完整 `LearningProgress` 及其 evidence 投影。
- [`LearningProgress`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/models.py) 第 736 行之后含自己的尝试、证据和进度；第 771 行有 `quiz_attempts`。直接移植它并不是天然“只存从 OpenMAIC 派生的结果”。
- [`OpenMAIC RuntimeStore`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/src/runtime/types.ts) 第 183–198 行的原子性覆盖自身 record 和 sessionTransition，不能自动覆盖另一个 Python 领域库。
- 原稿没有确定 Python 代码是保留进程、进程内嵌入还是转写 TypeScript，也没有映射 Stage/Scene/Question/Attempt 与目标、rubric、课程版本的身份。

**影响：** 答案已存、判定未存时如何恢复；评估重试会不会重复推进；题目升级会不会继承旧分；两个页面并发答题时由谁仲裁，都还没有确定。两边各自有 CAS，不意味着组合后天然一致。

**最小修订：** 选一个学习写入服务和一个事务所有者。可保留上游 runtime 事实记录、仅移植纯策略；也可选 DeepTutor LearningService 为唯一学习写入入口，再适配 UI。若 L2 是异步投影，写清消费位点、幂等身份、重建与失败补算；保留实际模型 verdict、输入版本和提示使用，不能假设重跑模型会产生相同事实。给出最小身份映射与三个失败场景的恢复说明即可，无需新建分布式 Runtime。

### R4 · P2：旧设计候选被重新当作硬约束，路线比较失去公平性

**原稿位置**：`architecture-proposal.md` 第 26–36、74–83、114–121、339–350 行。

任务手册 §1 明确：三方部署、课件目录生命周期、自建 Agent、现有 Runtime 都不是必须保留的条件。原稿却用“只给课程根目录”的判据直接否决完整 DeepTutor，又把本地优先推成必须 SQLite，因此给“完整 OpenMAIC”计入更换 storage 的高适配成本。

本地部署不等于不能使用本机 PostgreSQL；完整产品也不必原生扫描我们的旧目录才能满足“资料延后整理、可视化学习、状态持久化”的用户目标。无 HTTP 服务也不是共享目录/桌面路线的自动淘汰条件。Lattice 的全树 Git 操作是直接接正式 wiki 的风险，但是否可用隔离工作区避开，应作为复用方式的取舍，不能只据此否决所有形态。

另有一处库能力与应用配置混淆：原稿说 storage 包只有 HTTP/PG 后端，实际 [`src/index.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/src/index.ts) 第 119、169 行导出 `BrowserDocumentStore` 与 `BrowserRuntimeStore`，对应 IndexedDB 实现真实存在。主应用 [`bootstrap.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/persistence/bootstrap.ts) 第 60–75 行统一接服务端、没有浏览器回退，**不能外推成 SDK 没有浏览器后端**。这不代表浏览器存储必然适合本项目，但应给出正确选项。

**最小修订：** 将用户目标与候选机制分列。重新比较完整 OpenMAIC + 原生 PostgreSQL、完整 DeepTutor + 外部整理工作流、模块组合三条路线，分别列真实缺口和维护面。保留现有维护 Runtime 可以是结论，但不能仅以旧文档“不可回退”代替取舍论证；本轮不修改旧实现与规则。

### R5 · P2：资料暂存与显式整理触发没有落入主流程，外部 Agent 的后半程职责丢失

**原稿位置**：`architecture-proposal.md` 第 173–179、186–196 行。

主流程从交链接直接进入抓取、上传、生成，缺少“先收集，用户明确要求后才整理”的触发，以及资料入库/引用/暂缓/生成课程的分流。第 194 行又说外部 Agent 在拿到课件后不再参与，与后续由外部 Agent 使用学习结果整理知识的需求不一致。

**最小修订：** 加入收集暂存、用户显式触发、查已有知识后分类三个动作；说明未生成课程的资料去向。学习结束后明确谁读交接、谁形成知识候选、谁执行现有审批归档。可以继续用文件而非新应用，不必增加工作台服务。课程源包交付与学习结果交接应分别命名，避免 A8/A11 的输入输出方向混淆。

### R6 · P2：证据索引不能按其项目与路径独立复核，部分正文引用了无关 ID

**原稿位置**：`source-evidence.json`；`acceptance-request.md` 第 43–49 行关于字段和覆盖的声明。

以 `manifest[project].local_path + file` 定位，575 条中有 **93 条 file 不是可直接打开的文件路径**，包含“同上”“全仓 grep”、目录或多个文件拼成的字符串。不是所有这类条目都意味着观察错误，但当前字段不能完成独立定位。对其余可定位条目的行号检查，另有 **7 条越界**：OM-MAIN-011、LA-MAIN-010、OM-052、LA-015、DT-LOOP-008、DT-LOOP-016、DT-API-005。

更实质的问题是 **9 条 ONMCP 证据把 Open Notebook 后端文件归到 open-notebook-mcp 仓库与提交**：ONMCP-006/008/010/012/013/015/016/019/020。该 adapter 仓库并没有这些 `api/` 文件。ONMCP-012 的实际观察是 chat context 返回结构，原稿却把它用作 source Form 端点的依据。

生成器 `build_evidence.py`（研究过程记录未随仓库发布：docs/design/research/upstream-learning/_notes/build_evidence.py） 的 `project_by_id` 根据 ID 前缀覆盖仓库归属，是需要修正的来源之一。全仓“零命中”应记录实际命令、范围、排除项及限制，不能虚构成某个文件定位，也不应由有限 grep 推成“任何接口都不存在”。

**最小修订：** 单文件条目写真实仓库/提交/路径与有效位置；多文件观察使用明确的 `locations` 数组或拆条；检索型证据用单独结构记录搜索范围；展开“同上”。修正正文 ID，补一次路径、提交、行号和交叉引用自检。无需增加证据数量。

### R7 · P2：用未采用的 DeepTutor 检索与 research 路径宣称首选组合已覆盖能力

**原稿位置**：`architecture-proposal.md` 第 123–133 行、第 304–306 行；`report.md` 第 336 行之后的 Kotaemon 否决理由。

方案实际只移植 learning 域，并要求切断 knowledge 依赖；§4.1 却依赖 DeepTutor 完整产品的 llamaindex 检索、cross encoder 和 research 引用，声称推荐组合已全部覆盖。A12 又承认消费端材料检索仍需另建且可后置。源码里存在这些能力，与选定部署拥有这些能力是两件事。

**最小修订：** 分开“上游可供借鉴”“本方案实际引入”“本期暂不需要”。可以因为当前不需要而不引入 Kotaemon，也可以选定一个检索/引用路径并计入其接线与依赖成本；不要用未引入模块证明零重复开发。来源定位和证据引用即使不做向量检索，也应说明如何从课程/答案回到冻结材料。

### R8 · P2：learning 移植范围和依赖被明显低估，部分稳定性来自域外接线

**原稿位置**：`architecture-proposal.md` 第 91–94、238–240、294、351–355 行的“约 2000 行”“无第三方依赖”“切断一个 import 即可”等说法。

静态按行计数：`storage.py` 2284 行；A2 列出的 storage/policy/mastery/grading/models/semantic_assessment 六文件合计 **4252 行**；加上实际领域服务 `service.py` 为 **7640 行**。完整 learning 顶层 26 个 Python 文件共 13826 行。这些数字只描述移植范围，不能单独证明好坏或等价性。

[`models.py`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/models.py) 第 8 行、`storage.py` 第 29 行依赖 Pydantic；storage 还依赖 path service/file I/O；[`semantic_assessment._request`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/learning/semantic_assessment.py) 第 117–136 行重新进入 lesson evidence、LLM 配置、image replay 和 workspace knowledge。不是只去掉 `lesson_evidence.py:23` 就得到了独立包。

租约也不是 store 自带超时即自动恢复：`storage.py` 第 2113–2157 行只比较 turn 所有者；[`mastery_path.py`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/api/routers/mastery_path.py) 第 108–129 行依赖 turn service 取消并释放重启孤儿；[`learning_adapter.py`](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/services/session/turns/learning_adapter.py) 第 435–449 行承担旧租约处理。抽走 storage 后，这些保证不会自动跟随。

**最小修订：** 明确采用“少量纯函数/数据结构借鉴”“抽取领域服务”还是“移植整域”；给所选范围的直接依赖、生产调用入口和需要重写的 I/O seam。说明 Python/TypeScript 组合方式并重新估价。若自建轻量服务不需要原租约机制，可以不搬它；若要搬，补上释放与恢复责任。不要为降低估计而只统计 storage 一个文件。

## 3. 进一步确认结果

### 3.1 两个 npm 包确已发布，仍未验证构建和运行

2026-11-09 15:54 UTC，只读查询 npm 官方 registry：

- [`@openmaic/storage@0.39.3`](https://registry.npmjs.org/@openmaic%2fstorage/0.39.3) 存在，当时 latest 为 0.39.3，发布依赖为 `@openmaic/dsl: ^0.13.0`。
- [`@openmaic/dsl@0.13.0`](https://registry.npmjs.org/@openmaic%2fdsl/0.13.0) 存在，当时 latest 为 0.13.0。

因此“这些版本是否已发布”这个未知项已解。未下载或执行包，未证明发布构建与固定源码逐字一致、所有 exports 可 import 或适配通过；也不能从版本存在推导 R1 的整套能力可用。即使包未发布，本地构建指定 workspace 包也不必然要求 fork 全部应用，原稿的二选一表述过强。

### 3.2 课程包和离线播放器值得纳入路线比较，但不能当完整教学应用

研究索引已有 OM-045/046 的独立播放器线索，架构主结论未充分利用。进一步定位到：

- [`classroom-zip-types.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/export/classroom-zip-types.ts) 第 11–24 行已有 `.maic.zip` 和 manifest，包含课程、agents、scenes、mediaIndex。
- [`use-export-classroom.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/export/use-export-classroom.ts) 第 56 行之后定义课程导出 snapshot，第 356 行之后构建 ZIP；[`use-import-classroom.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/import/use-import-classroom.ts) 有对应导入逻辑。资产收集和 app 依赖仍需评估。
- [`standalone-player/App.tsx`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/standalone-player/App.tsx) 第 28–32 行已有四类场景分派；其 [`PblScene.tsx`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/standalone-player/scenes/PblScene.tsx) 第 73–100 行展示静态简介并提示返回线上，不是完整 PBL；QuizScene 主要用 React 本地状态，不自动满足我们的持久学习与导出要求。

这是“可复用课程包/播放器”和“为什么仍需教学/状态接线”的具体边界。应先评价现有包与导出模块，再决定是否自建完整课程格式。**课程内容包不等于学习结果交接包**；后者需要补齐的判断可以保留。

### 3.3 merge 与租约的未知可以继续读源码解决

OpenMAIC [`runtime/pg.ts`](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/storage/src/runtime/pg.ts) 第 618–657 行实现 learner 归并：事务内读取并锁定来源 session，验证版本，改 learnerKey，返回迁移数；同 key 返回 0，record 仍引用原 session ID，不是导出或去重课程。契约明确全体失败回滚、重复同 kind session 的合并策略属于应用层。源码同时提示大量 session 时的锁范围和往返开销。

DeepTutor 租约恢复责任见 R8，不能继续笼统列成“以后开工才知道”。这两项无需安装环境即可细化。

## 4. 最小返修与复审要求

1. 保留现有项目研究，先修 R6 的证据定位与正文引用；不要再用增加条数代替定位质量。
2. 修 R4/R5 的需求与候选机制混用：保留显式整理、外部利用知识及学习后整理这条用户链，允许成熟产品改变目录和部署方式。
3. 重新比较完整应用与组合方式，选定一个可实际部署的推荐。R1/R2 的生产、课堂和教学对话职责必须完整计入。
4. 写清 R3 的单一学习写入者、最小身份映射、模型评估持久化和失败恢复；不要求开发存储后端。
5. 根据实际采用范围修 R7/R8 的能力覆盖、依赖和维护成本；将本轮已解未知从“待确认”更新为静态结论。
6. 同步四份交付物，提交修订摘要和验收入口。无需重跑全部研究，不要求装环境或做完整流程；主 Agent 对修订结论与决定推荐的源码边界复审。

**开工判断：** 本轮仍在研究与选型阶段。R1–R3 未解决前，不宜以“薄适配已确认”为前提开始 SQLite 后端、整域移植或新消费端实现。解决这些问题所需的是明确架构和源码边界，而不是先做一轮产品开发来验证模糊方案。