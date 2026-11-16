---
type: meta
title: K4 后端到端拉通审查与最小整合建议
status: historical_record
updated: 2026-11-12
topic: K4 后端到端整合审查
related_sources: []
related_synthesis: []
---

# K4 后端到端拉通审查与最小整合建议

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

日期：2026-11-12。结论：**需要整合，先修连接处，再用真实资料做全流程验收；现有证据不要求推翻整体架构。** 本次为只读实现审查、纯内存边界重放和文档记录，没有修业务实现、发布课程、调用真实模型或正式写库。

K4 的 168 项检查确实通过，但主要是 K1–K4、I3 和选定 I5 能力分别验证，未覆盖所有新组合。尤其“受控复用 → I4 → I5”以及“发布后库正常演进 → 继续教学”缺少组合验收。因此不能把此前“本地集成交付”理解成整理、正式接纳和学习回流已经连成完整可用链。历史通过记录原样保留；本次新增问题未修，不重算历史摘要来掩盖缺口。

主 Agent 与只读独立审阅者 `/root/k2_readonly_review` 分别核对代码。独立审阅者没有修改文件、运行物化测试或调用 API。纯内存重放见 probes.json（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-post-k4-review/probes.json），远端与原件检查使用明确的内存替身，不能冒充真实端到端验收。

## 1. 待修问题

### R1 · P1：受控复用回执在 I4 缺少冻结输入

触发：相同 corpus 经受控 `publish-inputs` 复用，返回新本地回执；用该回执 create，再采集内容基线。

实际实现：[production.py](../../tools/learning_book/production.py):585–605 的 `_reuse_guarded_corpus` 只保存请求、定位和成功回执，没有普通发布路径保存的 `inputs/<remotePath>`。而 [baseline.py](../../tools/learning_book/baseline.py):91–100 的 `_sources` 按**本次 corpus request ID**读取这些输入，不沿 reusedFrom 查找。

结果：上传／create 可以成功，I4 却报 `input_evidence_missing`、sources.status=partial，I5 的 resultStatus 也要求来源完整。纯内存重放实际调用 `_reuse_guarded_corpus` 和 `_sources`，复现该错误；它只验证接口组合，未发送 HTTP。

最小修订：复用时把已校验输入字节冻结到新本地回执；或沿可信原回执解析输入并核对复用链。前者改动较小，后者要额外处理链上损坏、循环及可搬运性。两者都保持零远端重传。补一条新复用回执 → create → I4 来源完整 → I5 引用有效的组合验收，并覆盖重启／原回执缺失；不要用忽略 input_evidence_missing 修复。

### R2 · P1：知识候选缺少进入正式维护的明确交接接口

触发：K2 已审知识包和 K3/K4 candidate preview 完成后，准备按工作单走现有维护入口。

实际实现：[WORKSHEET.md](../../tools/wiki_runtime/evidence/WORKSHEET.md) §3 只指向“已有维护入口”。现有 [host/cli.py](../../tools/wiki_runtime/host/cli.py) 的 run 路线从 task 重新驱动 Worker；低层 [cli.py](../../tools/wiki_runtime/cli.py):38–61 虽可接 candidate，但重建 manifest、input_refs=[]，不消费知识包／知识审阅／candidatePreview；[coordinator/loop.py](../../tools/wiki_runtime/coordinator/loop.py):593–608 记录 Reviewer 身份时使用 candidate 的包身份，不自然带入 K2 的知识引用。

此外，K4 的 knowledge_content 是显式范围，[executor/core.py](../../tools/wiki_runtime/executor/core.py):315–320 仍构造完整根 CandidateView。内容预览通过不能被直接当成该正式运行器已接受相同依赖范围。

结果：目前是人工交接，不能把已审候选当现成可直接提交的受管包；重新生成还可能丢失知识引用、产生新正文或多花一次整理成本。这是缺接线，不是要求绕过正式审查。

最小修订：增加薄的候选接收／转交适配，冻结原 candidate/payload 摘要、KnowledgePackageRef、知识观察、原始输入和明确内容范围，转换为当前维护 operation 的输入；正式门禁仍由已有 Reviewer/Executor 重检。若转换必须重新生成，应显式产生新候选并重审差异，不能暗中换 payload。接入前只提供可读交接清单，明确不可直接应用。**不以启用严格 Native 或伪造 G3 作为修复。**

### R3 · P1：资料／wiki 合法变化后，已创建课程缺少受控续接路径

触发：用当前已审准备创建活动，尚未确认目录或稍后需新增题目；此时自己完成入库、相关页移动，或其他合法维护改变了 K1 依赖。

实际实现：[preparation.py](../../tools/wiki_runtime/evidence/preparation.py):347–362 对索引、旧页和目录变化判 stale；[knowledge_preparation.py](../../tools/learning_book/knowledge_preparation.py):36–50 每次重新构建完整投影。完成必要的重新核验后，mappingDigest 会变化；但 [production.py](../../tools/learning_book/production.py):43–46 对后续步骤要求 expected 等于初始 create 的 inherited binding，[knowledge_preparation.py](../../tools/learning_book/knowledge_preparation.py):75–80 又精确比较。活动仍固定指向原 create，reconcile 和 recover-inputs 都不是重新绑定准备的入口。

结果：旧准备正确地停止，新准备即便已重新审过也会 `preparation_binding` 拒绝；同一活动缺少正常恢复通道。纯内存探针确认 intent 和 manifest 不变、仅新 mappingDigest 改变时仍被拒绝；正常依赖变化与无续接入口由主／独立审阅静态核对，未修改正式 wiki 来制造场景。

最小修订：增加不可变的重新核验／续接记录，连接 oldBinding → newBinding，绑定同一 activity/book、当前 revision、变化原因、新审阅及仍有效的意图。后续操作引用被接受的续接记录，保留原 create 和旧审阅。实质扩范围仍需新认可。补“课程创建 → 正常知识入库／分类迁移 → 重新核验 → 同活动继续”的组合验收。不要删除 guard、改旧请求或切到过时库快照假装恢复。

### R4 · P2：准备证据和学习约定没有沿 I3/I4/I5 保留下来

触发：外部 Agent 用已审知识编写讲义，课程学习结束后，将 I5 包交给另一个 Agent 回顾／纠错。

实际实现：[knowledge_preparation.py](../../tools/learning_book/knowledge_preparation.py):47–52 把完整映射缩成 mappingDigest、intent 和 normalizedManifestDigest；I3 保存原生 manifest，但没有冻结完整 preparation-map、brief／知识审阅及其可解析引用。[baseline.py](../../tools/learning_book/baseline.py):108–113 的来源映射只有 corpus；[handoff.py](../../tools/learning_book/handoff.py):370–372 继续携带该映射。

结果：现有 I5 自身的作答和内容证据可以有效，但 authored 讲义只追到讲义本身；下一 Agent 不能仅凭交接包解析到底层 Claim／原文 Evidence 与学习约定。仅有 hash 不等于能找回被 hash 的内容；用户手动保留私有文件可缓解，却不是已接好的可搬运链。

最小修订：I3 冻结一份有界 preparation provenance 附件，保存已存在的约定／映射／知识观察及引用；I4/I5 只读携带可验证引用或必要附件。底层原件可以继续 external，缺件明确标注，不需要上传整库，不新增可写进度或把 I5 变成事实认证。补“仅带交接包及明确保留的知识证据，让另一个 Agent 找回依据”的消费验收。

## 2. 整合范围与顺序

先修 R1，恢复已承诺的 corpus 复用链；R4 把引用保留下来，为 R3 的新旧绑定续接提供实际可核验依据；随后补 R3，最后接 R2 的正式候选交接。实现顺序可在不改变上述依赖的前提下微调，四项在同一整合批次收口，不另造 K5 或新通用 harness。

继续复用普通模块、既有回执、不可变附件及原维护 Runtime；不加总线、第二套知识状态库或全局可写掌握画像。给外部 Agent 一个明确的交接清单与下一动作即可，不需要自动运行一个全局“全流程”。确定性验证零模型，原件／知识／课程／学习状态仍分别归原权威所有。

本轮不要求扩展完整网站注册、爬虫平台、全库语义搜索或自动掌握评估。这些已有未覆盖项与四个连接缺陷分开，不能靠“长期能力暂缺”解释当前复用回归。

## 3. 修订后应实际拉通的三条路线

| 路线 | 最少组合验收 | 失败出口 |
| --- | --- | --- |
| 仅整理知识 | 私有原件/已登记 raw → 查库/已审知识 → preview → 既有受管候选接收/独立审查 → 正式维护前的具体差异 | 缺角色或具体授权保持待处理；不伪造学习，不用 preview 自行批准 |
| 仅学习 | 已审包/有效约定 → 两个不同 brief 复用同 corpus → 提案/目录/正文 → I4 → 显式 I5 → 另一 Agent 追溯依据 | 缺输入/审阅/版本即停止；未知发送先对账，不换 ID 重发 |
| 资料与学习并行 | 创建课程 → 正常入库/分类迁移 → 局部失效 → 重新核验续接 → 同活动继续 → 错题/新事实回 K2 | 保留旧学习证据和新旧准备版本；实质扩范围另认可 |

先在临时库及本机 HTTP 替身完成上述组合；再选一批已授权的真实资料做有限真实使用。真实外发、实际课件 I4、正式写库及 approve 仍分别记录，不为了完成表格强行外发或改用户状态。168 项阶段检查不能替代这些路线的实际证据。

本次无业务代码修改；四项尚未修复。下一步应以本报告作为整合依据，修复后按真实变化更新验收与工作单，不重做选型，也不覆盖 K4 历史验收。