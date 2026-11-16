---
type: meta
title: DeepSeek Harness 审查交接
status: historical_handoff
updated: 2026-11-16
topic: 上游 Harness 审查的任务边界与交接
related_sources: []
related_synthesis: []
---

# DeepSeek Harness 审查交接

> 本文为历史交接记录，描述当时的工作状态、已完成的核对与当时的下一步，不作为当前执行指令。上游源码副本与研究过程记录未随本仓库发布；引用上游源码时绑定[上游来源清单](upstream-sources.md)的固定提交与文件路径。

## 2026-11-16 恢复后的最新状态（优先于下方旧交接）

- 已读取旧交接并下载官方 DSH；固定 `39163dd30f703a79079e2d2446545cff3c453738`，登记[上游来源清单](upstream-sources.md)。未安装依赖、未启动完整运行时。
- 完成 [DSH 候选审查](research/deepseek-harness-review-2026-11-16.md) 与 12 项离线源码算法探针（证据未公开，无法由本仓库独立复核：docs/design/evidence/deepseek-harness-review-20261116/probe-results.json）。测试是替身路由/存储下的真实算法，不是原生 SDK/Qt/沙箱集成。
- 用户新增四份 ChatGPT 审查产出，位于本机材料目录（路径未随本仓库发布）；要求逐段理解本质、核验后再当证据。已读完并形成 [四份材料复核](research/lattice-chatgpt-reports-review-2026-11-16.md)，原件未改，SHA256 与段落定位保存在证据目录（证据未公开，无法由本仓库独立复核：docs/design/evidence/deepseek-harness-review-20261116/external-documents.json）。
- 核心结论：DSH 执行机制值得验证，但 SDK 默认协议缺直接单会话 cancel 与实时 assistant chunk；需要受支持插件/通道适配。不能因此说 DSH 核心没有这些能力。四文中的“先自建补强必更划算”没有成本证据。
- 课程语义可采纳定义/尝试/评价/自评分离，不意味着先建设完整课程平台。run-04 因果叙事反馈仍未修改；没有迁移课程、修改 Learning 或调用模型。
- 当前审查交付完成；下一项候选工作是隔离 Tutor 接口可行性验证或课程试学切片，不应声称已经授权/完成替换部署。
- 无后台下载/测试进程需要恢复。只读 health 为 0 问题，未写正式 health 日志。

---

更新时间：2026-11-16（Asia/Shanghai）。用户准备压缩上下文，要求先写交接。本轮先暂停研究推进，等用户继续。

## 1. 当前任务与用户意图

用户对现有自建学习系统反复改造后的体验不满意，已开始试用 Lattice，并考虑直接采用其完整产品作为学习系统底座，把我们已有的课程设计思考融入其中。

用户明确纠正过：不是从 Lattice 中挑几项能力复用、继续从头做界面，而是评估用它作为框架。随后要求先审查 Lattice 的 harness，已完成本轮审查。

最新问题是：是否应让 DeepSeek Harness 这样的开源运行时管理 Lattice 的 Agent 执行层。助手建议先将 DeepSeek Harness 审查到与 Lattice 相同的深度，用户回答“可以”。**当前获授权的下一步是源码审查与隔离测试，不是直接改造或部署替换。**

助手已说明：重点核验取消、失败恢复、上下文和工具执行，再判断是否值得接管执行层。本轮不改正在使用的应用，不访问真实模型或密钥，不修改实际 Learning。

## 2. 不要丢失的产品背景

- Lattice 已部署官方 Windows 便携版 v0.3.3：`<本机安装目录>\Lattice.exe`。
- 独立学习库：`<本机安装目录>\Learning`。
- 桌面快捷方式：`<本机桌面>\Lattice.lnk`。
- 本机模型设置：`%APPDATA%\lattice\providers.json`；用户明确授权复用 DeepTutor 的 MiniMax 连接，模型 `minimax-m3`。**不要打印其中的密钥。**
- 部署时已验证应用进程／窗口创建、学习库初始化、MiniMax 模型列表认证成功；桌面截图两次超时，未完成真实 GUI 视觉核验。不可把这些说成真实教学效果验收。
- Lattice 用量独立，不接入 DeepTutor 的原本地用量账本。正式 wiki、DeepTutor 和 Learning 当前没有建立自动同步。
- 用户希望学习的 目标课程项目 仓库实际在 Gitee 的私有仓库（地址与固定提交未随本仓库发布）。

## 3. 现有课程最新状态

入口：run-04 README（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-course-authoring/run-04/README.md）。已读完整 HTML、两份复审报告、重构方案与候选蓝图。

- 模块 4 样课（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-course-authoring/run-04/agent-advice-full-lesson.html）：Agent 建议怎样成为合法执行。
- 完整课程仍是重构蓝图；run-04 是独立 HTML 样课，不是已部署的新 DeepTutor Book。
- 已有真实 JSON／离线输出／源码引用、建议—实例化—校验—创建—确认—执行链、五问练习、评价标准和独立短变式。
- 记录显示事实／工程、教学／评价复审与六组渲染检查通过。本会话只是读取，没有重跑这些历史验收。
- 最新用户反馈：分标题之间缺少关联，同一案例的因果推进不足。README 已记录诊断，但固定候选正文尚未修改。
- 我们的课程目标是独立设计 Flow／Agent，强调完整案例、先备、迁移练习和证据。不要继续用旧版“只有摘要、只有治理工程”的判断描述最新课程工作。

## 4. Lattice 审查已完成的工作

正式报告：[Lattice harness 审查](research/lattice-harness-review-2026-11-16.md)。

证据：

- 探针脚本（证据未公开，无法由本仓库独立复核：docs/design/evidence/lattice-harness-review-20261116/probe_harness.py）
- 最终结果（证据未公开，无法由本仓库独立复核：docs/design/evidence/lattice-harness-review-20261116/probe-results.json）
- 15 项观察断言已通过，包含正向检查与缺陷复现。**不是产品 15 项检查全绿，也不是完整集成验收。**
- 使用真实 model/vault/providers/sandbox 业务代码；Qt 外壳用替身、网络用 httpx MockTransport，部分方法从 AST 原样提取。没有真实模型调用、GUI 调度测试或断电恢复测试。
- 临时测试库：`.tmp/lattice-harness-review/probe-*`。上游源码和实际 Learning 未改。

### 固定版本

- 本地浅克隆（不随本仓库发布）：`lattice`，commit `762b00cb028ad1a86ee505db4ca5ed14103657ac`。
- 本次查询 main：`d8e6481f4620fe005d700fbfa6a20509be1ab0ff`，比本地多 1 提交，仅 README 改动；本次 harness 源码与查询时 main 一致。
- 官方 v0.3.3 tag：`b5c127a8169da1a8a2062b33fa99be5bb7d26678`，本地比发行 tag 多 27 提交。版本字符串同为 0.3.3 不能当成源码相同。

### 主要结论

Lattice 核心 harness 自写，使用 httpx、asyncio、Qt 线程、SQLite、Git、Jupyter 等通用库，没有采用 LangChain／LangGraph 一类 Agent 编排框架。

有价值的部分：模型—工具闭环、流式解析和重试；界面状态读取；学习者记忆、主题路线与档案；五种角色协作；普通文件事实层、索引重建与撤销；可编辑 Agent 政策与渐进加载技能。

重要事实修正：Lattice **有**轻量 `lessons` 课程对象、objective/state/body、`save_knowledge` 入口和 `tutorial-production` 技能。只是未提供我们那套正式课程验收状态机。不能继续笼统说“没有课程”。

已发现的限制／缺陷：

1. **H1 / P1：后置所有权检查可绕过。** `police()`只看未提交修改、以 HEAD 为基线；shell 自行 Git 提交后可逃过恢复。技能目录 `skills/` 在直接编辑工具里被禁改，但 shell 后置保护漏掉它。两种情况均在临时库复现。
2. **H2 / P2：批量保存不原子。** 第一节合法、第二节标题为空时，报错前已保存第一节；重试留下重复课文，成功动作记录为 0。
3. **H3 / P2：取消回答未贯通后台 shell。** 原样 rpc_cancel 只停模型 worker，后台工具继续。源码追踪＋方法级探针，不是真实 GUI 停止测试。
4. **H4 / P2：历史裁剪不等待摘要。** tutor 默认 history=24，以半窗口步进；100 条消息无摘要时只保留 73～100。摘要通常在离开或空闲 15 分钟后产生。没有整体输入 token 预算。
5. **H5 / P2：计量与预算不完整。** 已发出但无正文的失败可能 usage=null；40 限制是工具轮数，一轮 41 次调用全部执行。没有通用整任务费用／时间上限。
6. **H6：内容可恢复不等于执行可恢复。** 工具运行与后台队列主要在内存，未找到通用持久化执行状态与幂等恢复协议。此项静态判断，未做杀进程实验。
7. Windows shell 直接使用用户权限且继承宿主环境，没有 Linux bubblewrap 隔离。Git 撤销不覆盖库外副作用。

总判断：值得作为交互式教学底座候选，执行可靠性仍需补强。不要因为自写就判定不好，也不要把框架替换当成解决一切缺陷。

## 5. DeepSeek Harness 已核对的信息

官方项目明确是 **deepseek-ai/deepseek-harness**，不是同名第三方小项目。

- [官方仓库](https://github.com/deepseek-ai/deepseek-harness)
- [官方架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)
- [官方安全说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md)

上述内容已通过 web 工具读取。以下目前只是官方文档描述，**尚未用源码与测试证明**：

- 基于 Cordis，“everything is a plugin”；模型适配、工具注册、会话日志和 Agent 循环均为可替换组件。
- profile 有 web/headless/sdk/sdk-minimal/acp。Python SDK 通过正常 dsh SDK profile 启动运行时，并非可直接替换 Lattice Python ApiWorker 的同进程库。
- 工具有 pre-execute/execute/post-execute 管线；会话保存 turn/step/tool 等持久化事件；存在取消与错误恢复机制。
- 会话模型历史由事件日志派生；文档也承认硬进程中断、尚未 settlement 时，不存在该次完整持久化 attempt stream。
- 当前官方仍标注 developer preview，会有兼容性破坏；安全说明称未经安全审计，不可仅凭沙箱或权限提示认定可靠隔离。

上一次答复的建议只是**评估分工**：Lattice 保留教学产品／领域状态，候选 harness 管理通用模型与工具运行；课程设计属于教学层。避免外套一层后仍保留两套重试、上下文与任务状态。

## 6. 最新执行进度：刚开始准备，尚未获取 DeepSeek 源码

用户同意后只执行了一次只读工具调用：

- 读取本地研究工作区的 `references/upstream/README.md` 与 `manifest.json` 尾部和 Lattice 审查报告开头。
- 定位工具：Node `<本机工具目录>\node.exe`；npm 同目录；pnpm 在 Codex runtime 的 fallback bin；Git `<本机工具目录>\git.exe`。
- 搜索本地 DeepSeek 文件，没有返回匹配项；**未克隆 DeepSeek Harness、未确定审查 commit、未安装依赖、未运行它的测试**。
- 没有需要恢复的后台下载／构建进程；该次命令已经结束。当前只新增本交接文档。

上游参考约定：源码放在本地研究工作区的 `references/upstream/<name>`，通常浅克隆，登记 `manifest.json` 与 `README.md`；该目录源码副本被忽略，不提交到主仓库，也不随本仓库发布，公开版以[上游来源清单](upstream-sources.md)为准。下载不是采用决定。研究结论放 `docs/design/research/`，证据放 `docs/design/evidence/`。

## 7. 恢复后的执行顺序

1. 固定 DeepSeek Harness 当前审查版本，获取官方源码（先核对本地目标是否已存在）。记录 commit、许可、下载状态；不要直接追随会变的 master 给出结论。
2. 读实际 package/profile/SDK 与测试入口，定位 agent-loop、tools、session persistence、context management、cancel/subprocess、sandbox、usage 与预算的实现。
3. 按 Lattice 的问题逐项核对：
   - 取消是否真正传播到工具和进程，而不仅是 AbortSignal 存在；
   - 重启／异常后的未完成调用如何记录，能否恢复，哪些副作用仍结果未知；
   - 上下文裁剪／摘要／token 预算如何落实；
   - 失败请求用量、总调用量与时间限制；
   - Windows 的真实隔离边界；
   - SDK 外部工具接入后能否保留 Lattice 当前 UI 事件和领域操作语义。
4. 选择小范围的既有测试或自写离线探针，隔离工作目录和配置，使用假模型／假工具。用户已授权隔离测试；不需因普通依赖准备反复请示，但先读脚本、避免无关安装和真实密钥／网络副作用。
5. 区分框架提供的机制、默认配置真正启用的能力、仍须 Lattice 业务工具自行保证的事务／幂等。特别是批量保存原子性不会因换框架自动获得。
6. 交付固定源码审查、可复现证据与逐项对照，结论应回答是否值得进入一条教学会话的最小接入验证。**当前不直接做替换部署。**

## 8. 工作约束与沟通

- 默认中文；遵循库根 AGENTS.md。正式 raw/wiki 写入另有受管流程，此次审查不要为记录报告去绕过正式写库入口。
- 不修改用户现有课程、正式知识库事实、Lattice 配置或学习数据。
- 研究源码不需要逆向技能；读取上游技能作为研究对象，不等于执行其工作流。
- 不自动派生子代理；当前用户只授权审查，没有明确要求多 Agent。
- 联网 shell 受限时可用 `require_escalated` 按任务授权取得访问；此前正常通过，无需把沙箱失败直接当成用户拒绝。
- 用户讨厌反复确认和无休止加机制；把发现与实际学习影响相连，避免把“加一套更复杂系统”当默认答案。
- 最终结论注明测试范围：源码、方法级替身、真实运行、真实模型分别有哪些证据，不能互相冒充。

用户继续后从第 7 节开始即可，不重做 Lattice 审查、不重跑已经通过的 15 项探针。