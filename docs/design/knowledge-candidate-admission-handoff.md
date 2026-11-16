---
type: meta
title: 知识正式入库接线：执行交接
status: historical_record
updated: 2026-11-12
topic: 知识候选正式入库交接
related_sources: []
related_synthesis: []
---

# 知识正式入库接线：执行交接

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

更新：2026-11-12。用户已选择“补齐正式入库接线，先在临时库验收”。这是 K4 后连接工作的后续，不创建 K5；任务范围见[任务书](knowledge-candidate-admission-plan.md)。

## 当前检查点

**实现和临时库验收已完成，独立复核无新实质阻断。** 101 个不同检查有最终通过依据，含 18 个新增检查；按源代码修订与夹具修正分次补验，不声称一次全部通过。先读验收摘要（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission/README.md）、清单（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission/acceptance.json）和问题关闭（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission/review.md）。当前无活动 Goal、后台测试、真实 API 或正式知识应用；没有提交／推送，不再等待旧工具 session。

普通原文与标准采集薄 raw 均通过专用准入和真实临时库事务；关键 WAL 点实际进程退出、撤销后离线恢复、终态重放、用户冲突保留，以及 owner CLI 在咨询期间 admit 的真实跨进程交错已验证。咨询回包覆盖授权的并发 P2 已修复关闭。原正式内容 43 文件未变；真实语义／用户身份认证不由合成审阅测试证明。

新增 `runtime/knowledge_ingest.py`、`host/knowledge_ingest.py` 与 `test_knowledge_ingest_admission.py`。改动 Executor 的准入类型分支、显式 knowledge_content 视图和 WAL 范围、步骤版本校验；Runtime 抽出共用 _submission_context，新增领域表仍在同一 RuntimeStore；Host 增加 admit 方法和 owner CLI，原 apply／revoke／recover 分派到专用路径，inspect 分列内容意见和实际执行状态。

- `knowledge-ingest-admission/1` 独立于学习 Admission 和维护绑定，不创建 learning_states／Readiness。Runtime 历史字段 learning_task_id 仅沿用为关联 ID，不表示已创建教学状态或已学习。
- 可信宿主显式 admit，保存 HMAC 授权说明和精确范围；模型 JSON 的 intent／confirmed／operator_supplied 不签发权限。sequence 必填，当前仅 knowledge_only；learn_first 明确拒绝，不能推断已完成。
- 推荐 adopt → admit → apply，只做一次最终 G3。咨询 review-knowledge 可选；保存的 opinion 不直接升格 G3，若此前要求修改，同候选不再换次审阅争取通过。
- 新提交在模型调用前及接受锁内重检任务／policy／epoch／所有权／预算／撤销，最后重验 K2、原件和知识依赖。准入使用同一 OS 接受锁，避免并发覆盖宿主授权。
- 知识范围贯穿 G0–G3、目录清单、WAL、步骤校验和恢复；不扫描 references／环境。旧默认全根行为保留，正式 apply 不能用任意自传 scope。
- raw 只到 pending_review，最后写；reviewed_at 不得由新 ingest 签发，processed 仍需另一次明确 approve。
- 实际 WAL 的终态／恢复优先，不因自己已写后的旧基线 stale 或授权撤销被卡；用户编辑冲突保留。结果归并必须核对真实 WAL，不凭 pending 自报。

## 分次验证结果

证据目录：knowledge-candidate-admission（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission）。`run_checks.py` 保存实际输出，禁止覆盖原记录；tests-summary.json 逐个绑定最终依据。所有运行已结束。

- admission-tests.json：14 项、13 通过；unknown 夹具预期错误原样保留，启动后修改的路径另补验。
- regression-tests.json：82 项、81 通过；一个旧子进程编码问题由 legacy-crash-followup.json 单独通过关闭（42.593 秒）。
- targeted-tests.json：7 项、6 通过；同一个 unknown 夹具错误保留，reviewed_at 拒绝等已通过。
- final-boundary-tests.json：7 项通过（479.406 秒），含真实超时／迟到结果与实际重启不重发。
- final-transaction-tests.json：5 项通过（708.438 秒），含 owner CLI 跨进程交错、范围／payload 变化、关键 WAL 点真实进程退出及离线恢复。
- final-continuity-tests.json：4 项通过（611.469 秒），含原接收边界、managed raw／cutover、G3 期间撤销、恢复冲突。
- final-guard-tests.json：6 项通过（152.172 秒），含最终代码下 5 个 Runtime／最新负面意见检查及端到端事务；记录启动源摘要，运行期间未改源代码。
- 独立只读审阅者 `/root/k2_readonly_review` 核查代码和实际函数的纯内存探针，发现并关闭 1 个并发 P2，未发现新实质阻断；未独立运行物化或完整回归。

## 后续使用与保留边界

按[工作单 §8](../../tools/wiki_runtime/evidence/WORKSHEET.md#8-专用知识准入与正式事务)使用明确授权资料：preview → adopt → admit → apply → pending_review。当前只支持 knowledge_only；先学后入库的未知条件仍停止，processed 迁移仍需独立用户 approve。

任务书、WORKSHEET、知识准备交接及设计入口已更新；最终清单另绑当前字节和历史差异，不改旧 acceptance。只读 health、正式内容哈希、AST、链接及 diff 检查见 verification.json。Runtime 次数／字节／时间预算没有重设 DeepTutor 账本，宿主 tokens 仍 unknown；新增真实业务 API 0。

本次未操作正式 raw／wiki／AGENTS、真实课程／服务配置／API／业务账本，不把临时库事务通过升级为真实资料业务通过；后续选择真实资料时核对对应使用授权。本任务已完成，不重放旧进程或重做原阶段。