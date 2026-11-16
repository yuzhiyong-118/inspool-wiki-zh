---
type: meta
title: 知识库重设计多维审查报告
status: review_complete
updated: 2026-11-12
topic: K／L／C1–C3 五条路线的实际闭环判定与分级 findings
---

# 知识库重设计多维审查报告

本报告依据[审查方案](knowledge-base-redesign-review-plan.md)执行。审查对象是 `inspool-wiki-zh` 当前工作树中的知识准备链（K0–K4）与学习消费链（I3–I6），目标是判断这套重设计能否以可接受的用户负担、Agent 操作成本和长期维护成本，支撑 **K／仅整理知识**、**L／仅学习**、**C1 学习后回顾纠错**、**C2 明确先学后入库**、**C3 整理与学习并行** 五条路线。

**原审查以只读方式执行并新增本报告；后续收尾仅校正本报告及记录设计决策。未修改任何业务实现、raw／wiki 内容、根规则或公开入口，未启动真实服务、未调用业务模型 API、未生成课程、未提交或推送。**

---

## 0. 结论摘要

**总体结论：保持总体方向并局部修复。** 不需要重构子系统，不需要重新选型。

| 项 | 结论 |
| --- | --- |
| 架构方向 | K／L 两条路线在代码层**已真实解耦**，无第二套可写状态库，无第二份事实真值；数据所有权与保证级别（`operator_supplied`／`cooperative`／`formalWriteAuthorized: false`）设计是本项目最强资产，**建议保留** |
| R1–R4 | **R1／R3／R4 的代码修复成立**，且本轮实际跑通的组合验收覆盖了 post-k4-review 要求的 3 条主路径；**R2 只修到"可读交接清单"，"进入正式维护"半边仍缺** |
| 严重度分布 | **P0 = 0**；**P1 = 3**；P2 = 23；P3 = 13 |
| 真正未闭合的三件事 | ① K 路线终点「受控正式维护」被显式关闭且工作单仍指向已知有损的旧入口；② C2「先学后入库」**没有任何可记录载体**，代码与文档都不区分 C2 与普通 L→K；③ 公开入口层断链——新 Agent 按 `AGENTS.md`／`ENTRYPOINTS.md`／已部署 skills 走不到 K／L。收尾复核时工作单已补接收／续接命令，见 §12，但根规则与入口矩阵缺口仍在 |
| 选型 | **无决定性反证，不重新选型 DeepTutor**（I6 有限真实闭环已实证 Book 路线成立） |
| 网络研究 | 项目内**没有**搜索发现与通用抓取，这是**刻意的安全边界**；缺口在文档未声明该边界，不在缺少爬虫 |
| Token | 宿主主／子 Agent 用量**记 `unknown`**（仓库无采集点）；L 侧账本可引用且自洽；K 侧零计量，任何"K 路线省了多少"当前不可证伪 |

三项 P1 全部**不需要重构**，最小修正方向见 §4.2 与 §8。收尾阶段已确认三项设计决策，但仍处设计阶段，未据此实施代码或入口改动，见 §11–§12。

---

## 1. 审查基线

### 1.1 工作树身份

| 项 | 值 |
| --- | --- |
| 工作区 | `<知识库根目录>` |
| Git 仓库根 | `<本机工作父目录>/<本机父工作区>`（`inspool-wiki-zh/` 为子目录） |
| Git HEAD | `ab572e7aa312254f30b539ccb2d17a804afab27f` |
| HEAD 说明 | `vault backup: 2026-11-02 01:24:54` |
| 工作树状态 | 审查开始时 **117 项变更**（31 项 ` M` + 86 项 `??`），全部为**审查前既有状态** |
| 本轮改动 | **仅新增本文件**（`docs/design/knowledge-base-redesign-review.md`） |

审查以**实际工作树**为准，不把 HEAD 当作当前实现。

### 1.2 首批必审文件清单与逐文件字节摘要

SHA256 前 16 位；字节数为审查开始时实际值。

| 文件 | SHA256（前 16） | 字节 |
| --- | --- | ---: |
| `AGENTS.md` | `C21D41278630F57D` | 17,963 |
| `docs/design/knowledge-base-redesign-review-plan.md` | `30D6545F0A6971F4` | 25,586 |
| `docs/design/knowledge-preparation-handoff.md` | `9B1873C815203577` | 27,538 |
| `docs/design/knowledge-preparation-post-k4-review.md` | `9A7834CF16BFF2FB` | 9,613 |
| `docs/design/knowledge-preparation-plan.md` | `85398901D91F169D` | 34,277 |
| `docs/design/knowledge-preparation-k0-contracts.md` | `1E0822BBE250C554` | 14,508 |
| `docs/design/knowledge-preparation-integration-review.md` | `C24AD258E8ED65A9` | 8,907 |
| `docs/design/README.md` | `0BDDFB2550C6A01A` | 16,734 |
| `docs/design/evidence/knowledge-preparation-k4/business-matrix.md` | `807289A4AA9DD3AF` | 4,233 |
| `docs/design/research/upstream-learning/architecture-proposal.md` | `72B11CA60456BB31` | 16,537 |
| `docs/design/research/upstream-learning/report.md` | `8E9D4D0EFC1632C9` | 55,980 |
| `docs/design/upstream-learning-architecture-review.md` | `B19AD027DA28CDA1` | 21,740 |
| `docs/learning/system-architecture/README.md` | `5F2AAFB0633FF21A` | 3,897 |
| `tools/wiki_runtime/ENTRYPOINTS.md` | `DB3D1C8B9AB3AB4E` | 5,172 |
| `tools/wiki_runtime/evidence/WORKSHEET.md` | `8D63B56C7174B6BD` | 9,863 |
| `tools/wiki_runtime/evidence/README.md` | `5ABEA14140AA7044` | 6,043 |
| `tools/wiki_runtime/evidence/KNOWLEDGE.md` | `E828708629FB83F9` | 10,323 |
| `tools/wiki_runtime/evidence/PROJECTION.md` | `3BB2C4DF1DC841F0` | 10,986 |
| `tools/wiki_runtime/evidence/preparation.py` | `BAF1F75FA9470993` | 22,102 |
| `tools/wiki_runtime/evidence/projection.py` | `9100D8369CB63937` | 20,627 |
| `tools/wiki_runtime/evidence/preview.py` | `DB164EF63AC43EFD` | 10,635 |
| `tools/wiki_runtime/evidence/knowledge.py` | `A6AA8C271FBE882F` | 24,140 |
| `tools/wiki_runtime/evidence/managed_raw.py` | `AED458E361C76A9E` | 2,119 |
| `tools/wiki_runtime/evidence/package_protocol.py` | `FFCDF16C087C47BF` | 11,526 |
| `tools/wiki_runtime/evidence/integration_cli.py` | `A4AD4EDACC669EF9` | 2,220 |
| `tools/wiki_runtime/evidence/content_view.py` | `D810664B5F1A13E4` | 3,542 |
| `tools/wiki_runtime/host/cli.py` | `30407DFAF52A8971` | 13,815 |
| `tools/wiki_runtime/host/supervisor.py` | `BE08D1194B425D8A` | 38,402 |
| `tools/wiki_runtime/host/knowledge_candidate.py` | `79A0CB3F3C945CE4` | 11,726 |
| `tools/wiki_runtime/host/model.py` | `4AABEFA56BB6C090` | 9,150 |
| `tools/wiki_runtime/host/wechat.py` | `8E24B61433DB21B7` | 6,965 |
| `tools/wiki_runtime/host/codex.py` | `F7B5BE3DD77DA8A9` | 21,949 |
| `tools/wiki_runtime/capture/adapters.py` | `AB631C3F5FF792D0` | 15,607 |
| `tools/wiki_runtime/capture/pdf.py` | `EED9642AE1848666` | 11,477 |
| `tools/wiki_runtime/contracts/core.py` | `CD2AA0A786E7A9BF` | 9,044 |
| `tools/wiki_runtime/contracts/schemas.json` | `6BC99B80B4F94257` | 28,371 |
| `tools/wiki_runtime/runtime/storage.py` | `0B7BFCC5DE7964DC` | 15,090 |
| `tools/wiki_runtime/runtime/protocol.py` | `D4A1CF8C25343822` | 38,777 |
| `tools/wiki_runtime/runtime/migration.py` | `EF754B2BAB280CE3` | 30,055 |
| `tools/learning_book/LOCAL_USE.md` | `FBDF471E676B8D40` | 7,605 |
| `tools/learning_book/README.md` | `8DF5C50DADFD1AB4` | 16,837 |
| `tools/learning_book/HANDOFF.md` | `376E7DAA28B0535D` | 8,520 |
| `tools/learning_book/PREPARATION.md` | `2727D7AE919663AD` | 5,878 |
| `tools/learning_book/cli.py` | `0635B3E2061B4527` | 11,162 |
| `tools/learning_book/contracts.py` | `40AD20BA4CCCB4AC` | 13,724 |
| `tools/learning_book/production.py` | `90A08997F89F0140` | 57,071 |
| `tools/learning_book/baseline.py` | `E6FF32166BBCDAFD` | 41,730 |
| `tools/learning_book/knowledge_preparation.py` | `843113E030DE982F` | 7,072 |
| `tools/learning_book/preparation_provenance.py` | `0C21E8E4B422A678` | 7,759 |
| `tools/learning_book/preparation_handoff.py` | `E82A451C4DAA7D97` | 4,134 |
| `tools/learning_book/preparation_continuation.py` | `9C29F201DC177858` | 5,744 |
| `tools/learning_book/budget.py` | `E02909621CB43007` | 17,707 |
| `tools/learning_book/read_limits.py` | `C5C085350F234C23` | 3,651 |
| `tools/learning_book/runtime.py` | `6BC1CA09357C8380` | 14,561 |
| `tools/learning_book/evidence_store.py` | `6F84D80B0D0927F3` | 11,273 |
| `tools/learning_book/local_install.py` | `1C22E792250A2049` | 6,620 |
| `tools/learning_book/schemas/learning-handoff.schema.json` | `D2103BB5930AEEF7` | 13,206 |
| `tools/tests/test_knowledge_preparation_integration.py` | `D3DF21500E2C33FA` | 18,938 |

后续新增的引用文件同样按此规则补记摘要，见各 finding 条目。

### 1.3 审查方法与预算执行

| 角色 | 交付 | 深读主文件 | 外部一手来源 | 运行探针 | 补证轮次 |
| --- | --- | ---: | ---: | ---: | ---: |
| 用户旅程审查者 | 完成 | 8 | 0 | 2 | 1 |
| Agent 开发体验审查者 | 完成 | 8 | 0 | 2 | 1（定向 grep） |
| 架构与契约审查者 | 完成 | 8 | 0 | 2（1 次中止） | 1 |
| Token 与网络研究审查者 | 完成 | 8 | 0（1 次被 Cloudflare 拦截，未绕过） | 2 | 1 |
| 上游与简化审查者 | 完成 | 8 | 0（用本地固定克隆 `references/upstream/`） | 3 | 1 |
| 实现与故障审查者 | **未在预算内完成**，见 §10 | — | — | — | — |
| **主 Agent** | 完成 | 见 §1.2 | 0 | 1（§3.1） | 1（对抗复核 §5） |

- 外部一手来源上限 3／角色，本轮**全部角色实际外部抓取为 0**；上游对照改用仓库内 `references/upstream/` 六个固定克隆（含 commit 与许可记录于 `references/upstream/manifest.json`），满足"优先复用本地固定源码"。
- 探针一律使用**临时库、本机 HTTP 替身与测试替身**，与真实业务证据分列记录。

### 1.4 上游一手来源清单

本轮**未执行任何外部 HTTP 抓取**，全部上游结论来自仓库内 `references/upstream/` 的固定克隆。克隆记录时间 `recorded_at = 2026-11-09T12:03:59.009501+00:00`，克隆模式 `depth=1, filter=blob:none, no-tags`（**无 tag、无历史**，故不得据其做基于历史的论证，也不得把固定提交下的行为写成上游最新状态）。

| 上游项目 | 仓库 URL | 固定 commit | commit 日期 |
| --- | --- | --- | --- |
| DeepTutor | `https://github.com/HKUDS/DeepTutor` | `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db` | 2026-11-06T16:41:21+08:00 |
| OpenMAIC | `https://github.com/THU-MAIC/OpenMAIC` | `cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0` | 2026-11-09T19:29:50+08:00 |
| open-notebook | `https://github.com/lfnovo/open-notebook` | `a6b572eb9849785dfb7c747190a01b0bb99fedf2` | 2026-11-08T10:51:23-03:00 |
| Kotaemon | `https://github.com/Cinnamon/kotaemon` | `9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9` | 2026-05-30T21:02:58+07:00 |
| Lattice | `https://github.com/vimalinx/lattice` | `762b00cb028ad1a86ee505db4ca5ed14103657ac` | 2026-11-09T17:39:43+08:00 |
| open-notebook-mcp | `https://github.com/Epochal-dev/open-notebook-mcp` | `a2cddbf65cba8c4c8de7be16566781b7612a9545` | 2025-12-22T12:31:07+01:00 |

DeepTutor 的 commit subject 为 `release: v1.7.2`，与 `patches/deeptutor/README.md:3` 记录的 `baseVersion: "1.7.2"` 互相印证；但**克隆无 tag**，"1.7.2" 与该 commit 的绑定只靠 subject 文本（P3-08）。本轮**未**执行外部查询去确认上游是否存在指向同一 commit 的 `v1.7.2` tag——见 §10 第 5 项。

---

## 2. §1 路线验收矩阵（逐行实际结果）

| 路线 | 最少操作序列能否走通 | 断点位置 | 闭环判据逐条结果 | 失败出口是否可执行 |
| --- | --- | --- | --- | --- |
| **K／仅整理知识** | **部分走通**（到"可交接候选＋独立审阅＋具体差异"为止） | `tools/wiki_runtime/host/supervisor.py:525-526`、`:639-641` 对 `knowledge_candidate` 一律拒绝 approve／apply；`tools/wiki_runtime/evidence/WORKSHEET.md:33` 仍指向**已被判定不消费知识包**的旧维护入口 | 无学习产物即可得可交接候选 ✓；知识引用／内容范围／原始输入未丢失 ✓（`knowledge_candidate.py:109-138` 冻结 `preparedDigest`／`knowledge_package_ref`／`knowledge_review_ref`／`allowed_paths`）；**"受控正式维护" ✗** | **可执行**（`non_teaching_admission_unavailable` 显式可见、`applied:false`），但**不能作为终点**——§1.1 把"受控正式维护"列入 K 的定义 |
| **L／仅学习** | **走通**（到 I5 显式交接） | 无功能性断点；原审查基线的公开入口缺口见 P1-3，收尾时当前工作单 §7 已补接收／续接命令，根规则与入口矩阵仍缺指针 | 课程／学习记录／内容基线／准备依据可按各自边界解析 ✓（`handoff.py:381-384` → `preparationEvidence`，`preparation_handoff.verify_mapping` 从归档重算整链）；**不推出权威掌握 ✓**（`submissionContent: unknown`／`not_mastery_proof`／`sourceOriginalsVerified: false` 常驻） | **可执行**（I3 侧 `cli.py:169-176` 保留 `code`＋`message`＋`nextAction`；K 侧 `check-preparation` 把失败压成一个码，见 P2-01） |
| **C1／学习后回顾纠错** | **部分走通** | 纠错回流终点仍落在 P1-1 关闭的正式准入上；`tools/learning_book/HANDOFF.md:35-44` 包文件表与 `:72` 消费者提示词都未提 `preparationEvidence`（P2-08） | 原答案／旧基线／历史学习证据保留 ✓；**新事实不会从聊天直接入库 ✓**（`WORKSHEET.md:94` 明禁，回流须经 K2）；**修正分别回知识或课件流程 ✓**（候选／I4 两分支） | **部分可执行**：`business-matrix.md:36` A30 仍标 `partially_verified`（"未新增真实错题纠正发布／正式知识应用"），真实错题闭环未验收 |
| **C2／明确先学后入库** | **断在第一步（记录约束）** | `tools/wiki_runtime/evidence/preparation.py:376-378` 与 `:417-422`：`learning-brief/1` 正文**无任何顺序约束字段**；`preparation_continuation.py:37-41` 的 `_compatible` 只比对 brief 的 6 个范围字段，**不比对** recognition 的 `statement`／`evidenceRef` | 顺序约束只约束本次任务 ✗（无载体可约束）；不形成所有知识维护的循环依赖 ✓（**因为根本没有门禁**，属偶然成立而非设计成立）；用户改变顺序或范围时形成新认可 ✗（范围变化会**静默复用旧约束**） | **不可执行**：当前只是散文约定，代码不区分 C2 与普通 L→K |
| **C3／整理与学习并行** | **部分走通**（续接链在代码层成立；失效粒度与入口有缺口） | `tools/wiki_runtime/evidence/preparation.py:361-362`：wiki **清单摘要**变化即判 stale → 实际是**全量重建**而非方案要求的"局部失效"（P2-22）；原审查基线缺公开入口；收尾时当前工作单 §7 已补 `revalidate-preparation`，剩余根规则与入口矩阵缺口见 P1-3 | 新旧准备版本及学习证据均可追溯 ✓（`preparation_continuation.py:17-23,96-101` 不可变续接记录；`production.py:79-89` dispatch 期阻断不对应的续接）；实质扩范围另取认可 ✓（同活动扩范围抛 `DeliveryError`，须另起流程） | **可执行**：无合法续接入口时 `preparation_continuation_stale` 显式阻断，不删除 guard、不沿用 stale 准备 |

**矩阵小结**：五条路线中 **L 走通、C3 基本走通、K 与 C1 部分走通、C2 在第一步断开**。所有断点都是**接线层或契约层**，没有一条需要架构重构。

---

## 3. R1–R4 状态核实

`docs/design/knowledge-preparation-post-k4-review.md` 记录的四项待修连接问题，本轮逐项核对代码并实际运行组合验收。

### 3.1 本轮实际运行探针（主 Agent）

```powershell
& '.\.learning-validation\deeptutor-60fb3bd\closeout\venv\Scripts\python.exe' -X utf8 -B `
  -m unittest tools.tests.test_knowledge_preparation_integration -v
```

结果：**`Ran 14 tests in 552.552s` / `OK`**（0 失败、0 错误、0 跳过）。全部 14 项通过，逐项如下：

| 测试用例 | 覆盖的 R 项 | 结果 |
| --- | --- | --- |
| `test_reuse_create_I4_sources_complete_and_no_reupload` | **R1** 复用回执 → create → I4 来源完整 → 零重传 | ok |
| `test_missing_or_tampered_provenance_remains_partial` | R1／R4 缺件不得静默降级 | ok |
| `test_wiki_change_revalidation_same_activity_continues_without_recreate` | **R3** 合法 wiki 变化 → 重新核验 → 同活动继续 | ok |
| `test_bad_review_or_wrong_revision_cannot_accept_continuation` | R3 错误审阅／错 revision 拒绝 | ok |
| `test_scope_or_uploaded_header_change_requires_other_workflow` | R3 扩范围须另起流程 | ok |
| `test_I4_I5_portable_package_can_resolve_brief_claims_and_evidence_offline` | **R4** 仅带交接包让另一 Agent 离线找回依据 | ok |
| `test_rehashed_archive_with_wrong_knowledge_package_is_rejected` | R4 归档篡改拒绝 | ok |
| `test_rehashed_archive_with_wrong_projection_artifact_is_rejected` | R4 投影产物篡改拒绝 | ok |
| `test_adopt_inspect_review_consume_same_candidate_without_worker_or_apply` | **R2** 候选接收＋审阅（**不含正式应用**） | ok |
| `test_adopt_copy_is_immutable_to_original_payload_changes_and_detects_vault_stale` | R2 接收物不可变＋失效检测 | ok |
| `test_missing_knowledge_review_or_changed_candidate_cannot_adopt` | R2 缺审／换候选拒绝 | ok |
| `test_standard_capture_thin_raw_preview_adopt_and_review` | R2 采集→薄 raw→预览→接收→审阅 | ok |
| `test_managed_extraction_changed_cannot_be_used_as_verified_original` | R2 抽取物改动不得当已核验原件 | ok |
| `test_after_cutover_adopt_review_and_new_operation_are_not_legacy` | R2 新世代操作不被当 legacy | ok |

> **口径声明**：这是**本地临时库＋本机 HTTP 替身**上的组合验收，**不是**真实远端端到端验收，不含真实模型调用、真实课程发布或正式库写入。测试替身的结果不外推为真实环境结论。

### 3.2 逐项状态判定

| 项 | 原级 | 代码状态 | 本轮验收 | 判定 |
| --- | --- | --- | --- | --- |
| **R1** 受控复用回执在 I4 缺冻结输入 | P1 | **已修**：`tools/learning_book/production.py:643-645` 在 `_reuse_guarded_corpus` 内 `atomic(request_dir/'inputs'/name, data, immutable=True)`，注释明写"复用远端语料也须拥有自己的冻结输入，I4/I5 按当前回执读取"；`baseline.py` 按 sha256 校验并以 `input_evidence_missing` 报 issue（**未忽略**） | **主路径组合验收通过** | **已修复待验 → 主路径已验**。收尾复核确认原回执的输入文件缺失已覆盖；复用后**重启实例／完整原回执缺失**仍未被单独覆盖（P2-23） |
| **R2** 知识候选缺进入正式维护的交接接口 | P1 | **部分修复**：`host/knowledge_candidate.py:73-174` 提供 `adopt`（冻结 `preparedDigest`／candidate／payload／`knowledge_review_ref`／内容范围）＋`review_adopted`（走真实 Reviewer 与 coordinator）＋`inspect_adopted`（出 diffs）；`host/cli.py:169-170` 注册 `adopt-knowledge`／`review-knowledge` | 接收／审阅／不可变／失效组合**全部通过** | **已知待修（P1-1）**。post-k4-review 允许的"接入前只提供可读交接清单"这档**已达成**；"转换为当前维护 operation 的输入、由既有 Reviewer/Executor 重检"这档**未实现**：`supervisor.py:525-526` 拒绝 approve、`:639-641` 拒绝 apply |
| **R3** 合法知识变化后课程缺受控续接路径 | P1 | **已修**：`preparation_continuation.py:17-23,96-101` 生成不可变续接记录（绑定同 activity/book/scope、revision、原因、新审阅、仍有效 intent）；`production.py:437-450` 提供 `revalidate_preparation`；`:79-89` 在 dispatch 期以 `preparation_continuation_stale` 阻断不对应的续接 | **主路径组合验收通过**（扩范围、错审阅、错 revision 三条负向同时通过） | **已修复待验 → 主路径已验**。收尾复核确认后续独立复核已覆盖"分类迁移"变体，见 P2-23；本报告不重复实施该验证 |
| **R4** 准备证据与学习约定未沿 I3/I4/I5 保留 | P2 | **已修**：I3 `production.py:61-65` 冻结归档；I4 `baseline.py` 写入映射摘要；I5 `handoff.py:381-384` 搬运、`preparation_handoff.verify_preparation` 复验 | **"仅带交接包找回依据"组合验收通过** | **已修复待验 → 主路径已验**。附带标注缺口见 P2-12（归档未声明快照属性） |

> **纪律**：四项**均未被本审查标为"已关闭"**。本轮跑通的是本地组合验收主路径；真实远端端到端、真实课程内容基线、正式库写入三项**未验证**。

---

## 4. 分级 findings

### 4.1 P0

**无。** 本轮未发现不可逆数据损失、严重越权或核心事实被静默篡改的路径。审阅的每个边界都保持 fail-closed：`formalWriteAuthorized: false`、`non_teaching_admission_unavailable`、`sourceOriginalsVerified: false`、`operator_supplied`、`submissionContent: unknown`、`not_mastery_proof`。

### 4.2 P1（3 条）

---

#### **P1-1｜K 路线终点「受控正式维护」被显式关闭，且工作单仍指向已知有损的旧入口**

- **严重度** P1（核心路线无法闭环：K 路线的终点步骤在代码层被拒绝）
- **生命周期** 已知待修（R2 部分修复）
- **处置** 修正候选（用户已确认开放薄适配；设计阶段未实施）

**原文**

`tools/wiki_runtime/host/supervisor.py:525-526`（`BE08D1194B425D8A`）：
> `if record.get('kind') == 'knowledge_candidate':`
> `    raise HostError('知识接收候选不签发批准；非教学正式准入尚未提供')`

`tools/wiki_runtime/host/supervisor.py:639-641`：
> `if record.get('kind') == 'knowledge_candidate':`
> `    return {'status':'non_teaching_admission_unavailable','applied':False,`
> `            'reason':'已接收/审阅知识候选；正式非教学 ingest 准入保持关闭'}`

`tools/wiki_runtime/evidence/WORKSHEET.md:33`（`8D63B56C7174B6BD`）——**唯一面向外部 Agent 的工作单**：
> "检查实际 payload：内容页证据、frontmatter／正文双通道反向边、index／log／overview／raw index 和整组 pending_review 都应在候选里。之后走**已有维护入口**的实际 Reviewer／Executor 门禁。"

而该"已有维护入口"已被 [post-k4-review](knowledge-preparation-post-k4-review.md):25 判定为有损：
> "现有 `host/cli.py` 的 run 路线从 task 重新驱动 Worker；低层 `cli.py`:38–61 虽可接 candidate，但重建 manifest、**`input_refs=[]`**，不消费知识包／知识审阅／candidatePreview"

本轮独立核对 `tools/wiki_runtime/cli.py:55`：`"input_refs": []` —— 确认属实。

`tools/wiki_runtime/host/knowledge_candidate.py:132-142`（`79A0CB3F3C945CE4`）：
> `'formal_application':'non_teaching_admission_unavailable'}, 'knowledge':k}`
> `return {'status':'pending_review', 'operation_id':operation_id, 'applied':False,`
> `        'nextAction':'inspect_or_review_knowledge','formalWriteAuthorized':False}`

**影响**：路线 **K**（终点步骤）、**C1**（纠错回流终点）、**C2**（L→K 衔接）。涉及模块 `wiki_runtime/host/{knowledge_candidate,supervisor,cli}.py`、`wiki_runtime/cli.py`、`evidence/WORKSHEET.md`。破坏的信任承诺：**"已审知识不丢失地进入受管维护"**。

**合理替代解释与已有缓解**
1. R2 的最小修订原文允许"接入前只提供可读交接清单，明确不可直接应用"（post-k4-review:31）——**当前状态完全满足这一档**，且 `formalWriteAuthorized: false` 与 `non_teaching_admission_unavailable` 在产物里**显式可见**，属 fail-closed 而非静默降级。
2. 保持关闭可能是刻意的安全边界：`architecture-proposal.md:130` 要求"正式库写入及 approve 权限不因共用接口而合并"。
3. `adopt()` 已把候选物化为标准 operation manifest（`input_refs`／`allowed_paths`／`required_gates: ['G0','G1','G2']`／各 digest），**转换这一半已经做完**，缺的只是消费这一半。

**最小修正方向**
增加一条**薄的转换适配**：把 `knowledge_candidate` 的冻结 manifest 转换为当前维护 operation 的输入，正式门禁仍由既有 Reviewer／Executor 重检；若转换必须重新生成，显式产出新候选并重审差异，不得暗中换 payload。

**需要新增的组合验证**
"K2 已审包 → preview → adopt → 转换 → 既有维护入口接收 → 正式页生成"全链，并覆盖 payload 摘要不一致时拒绝、`allowed_paths` 越界时拒绝。

**用户取舍结果**：已选择开放薄适配，不调整 K 路线终点。适配只把已审候选交给现有维护流程，Reviewer／Executor／既有门禁和用户 approve 不变；当前仅记录设计决定，未实施。

**Token 成本／用户负担／证据质量**：转换适配不新增模型调用，成本影响接近 0（宿主用量记 `unknown`）；用户负担可减少一次人工搬运候选；证据质量提升点是"已转成正式 operation 输入"这段目前无可验证证据。

---

#### **P1-2｜C2「先学后入库」没有任何可记录载体，顺序变化会静默复用旧约束**

- **严重度** P1（核心路线无法闭环：C2 验收矩阵的第一步"记录本次先学后入库约束"在代码层不存在）
- **生命周期** 新增
- **处置** 修正候选（用户已确认硬门禁；设计阶段未实施）

**原文**

`tools/wiki_runtime/evidence/preparation.py:376-378`（`BAF1F75FA9470993`）——brief 请求的封闭字段集：
> `_need(type(request) is dict and not set(request) - {`
> `    'briefId', 'version', 'goals', 'included', 'excluded', 'pacing',`
> `    'prerequisites', 'userIntent'}, 'brief_request_fields')`

`tools/wiki_runtime/evidence/preparation.py:417-422`——`learning-brief/1` 正文：
> `brief = {'schema': 'learning-brief/1', 'briefId': request['briefId'],`
> `    'version': request['version'], 'learnerId': body['learnerId'], 'goals': goals,`
> `    'backgroundRefs': [...], 'prerequisites': prerequisites, 'included': included,`
> `    'excluded': excluded, 'pacing': pacing}`

`tools/learning_book/preparation_continuation.py:37-41`（`9C29F201DC177858`）——续接兼容性判定：
> `def _compatible(old, new):`
> `    # 本操作续接依赖更新，不偷换已上传内容或学习方向。`
> `    _need(old['manifest'] == new['manifest'] and old['binding']['intent'] == new['binding']['intent'])`
> `    _need(all(old['brief'][k] == new['brief'][k] for k in`
> `        ('learnerId','goals','included','excluded','pacing','prerequisites')))`

**实测（静态确定性追踪）**：`learning-brief/1` 正文**不含 `userIntent`**，也不含任何顺序字段。`userIntent` 只是 `draft_learning_brief` 的**输入**，被折算为 `goals`／`included` 后即丢弃。因此"先学完再入库"这句话**不进入 brief 正文 → 不进入 briefRef 摘要 → 不进入 mapping → 不进入 binding → 不进入 provenance 归档**。同时 brief 请求字段是封闭集，新增顺序字段会被现有校验**直接拒绝**。`_compatible` 只比对 brief 的 6 个范围字段，**不比对** recognition 的 `statement`／`evidenceRef`／`id` → 用户把顺序要求从"先学后入库"改成"先入库后学"，只要 goals／included／excluded／pacing 与 intent 不变，续接链**接受**新 provenance 并**静默丢弃旧约束**。

**影响**：路线 **C2**（全部），并波及 C3（续接链共用 `_compatible`）。涉及模块 `evidence/preparation.py`、`learning_book/preparation_continuation.py`、`host/knowledge_candidate.py`。破坏的信任承诺："用户明确要求的顺序约束只约束本次任务；用户改变顺序或范围时形成新认可，**不暗中复用旧约束**"。

**合理替代解释与已有缓解**
1. 这可能是刻意的"工作约定"取舍：`knowledge-preparation-plan.md:176` 已有同类原则（"当前若只有人工工作单能提醒，就明确为工作约定，不能声称原生评分已被技术阻断"）；`WORKSHEET.md:7` 要求 Agent 先确认本次是"暂存／整理／学习／**明确要求先学后入库**"。
2. 用户原话确实以 `statement` 字节形式被 sha256 绑定并归档（`preparation_provenance.py:72-73`），只是**不可被程序判定**。
3. 项目自身已诚实记为 `partially_verified`：`business-matrix.md:34` A28"先学后入库仅工作单上的本次明确顺序，**正式执行未验收**"。

**最小修正方向**
在 `learning-brief/1` 与认可附件中加入封闭枚举 `taskOrdering: 'learn_before_commit' | null` 和稳定 `taskId`，使其进入 briefRef 摘要；候选交接携带同一 `taskId` 与 `learningHandoffRef`。`_compatible` 增加对 `taskOrdering` 及 recognition `statement`／`evidenceRef` 的比对；`adopt()` 在 `learn_before_commit` 任务缺少同任务、可核验的有效 I5 交接包时拒绝接收。门禁只证明规定顺序已有证据，不判断课程完成、学习掌握或教学质量。

**需要新增的组合验证**
① C2 任务：同任务有效 I5 交接 → adopt 候选 → 约束仍生效；② 顺序改变 → 要求新认可，旧约束不被静默复用；③ 非 C2 任务 → adopt 不被阻塞；④ 其他 taskId 或无效 handoff → 拒绝。

**用户取舍结果**：已选择硬门禁，不采用仅提示方案；当前只完成设计决策，未实施字段或门禁。

**Token 成本／用户负担／证据质量**：结构化后每次准备多 1 个字段与 1 次比对，Token 影响可忽略（总量 `unknown`）；用户需在约定确认时多确认一个枚举项；证据质量**实质提升**——C2 相关结论当前只有"Agent 声称已遵守"，结构化后可产出第三方可解析的机器可读证据。

---

#### **P1-3｜公开入口层断链：根规则与入口矩阵仍缺，工作单缺口已后续修复**

- **严重度** P1（核心路线无可用公开入口契约）
- **生命周期** 部分已修复待验
- **处置** 修正候选；根 `AGENTS.md` 纯指针已获用户设计许可，但设计阶段不实施

**原文**

原审查基线中，`AGENTS.md`（`C21D41278630F57D`）不含知识准备／学习入口，只定义 Health／Ingest／Approve／Query／Lint 五类操作；`tools/wiki_runtime/ENTRYPOINTS.md`（`DB3D1C8B9AB3AB4E`）不含 evidence CLI、learning_book CLI 或新增接收／续接命令；5 个 rollout SKILL.md 与对应 commands 也未指向工作单。

原基线中 `adopt-knowledge`／`review-knowledge`／`revalidate-preparation` 未进入工作单。**收尾复核**：当前 `WORKSHEET.md`（`F523F9A99A43564D`）§7 已补这些命令、参数、前置条件与正式准入边界；因此“未被任何工作单收录”仅是历史状态，不是当前事实。当前 `docs/design/README.md` 也已指向连接修复验收。

**影响**：全部五条路线的公开可发现性。工作单内部导航已缓解，剩余断点是新 Agent 从根 `AGENTS.md`／`ENTRYPOINTS.md`／已部署 skills 出发仍无法发现该工作单。不得再把工作单本身列为缺失。

**合理替代解释与已有缓解**
1. 工作单作为主 Agent 派单交付物成立，不必自主发现；但本次审查采用“零历史上下文新 Agent”前提，且 `ENTRYPOINTS.md` 已被当作权威矩阵。
2. 命令可由 `--help` 和当前工作单定位；根规则与入口矩阵仍缺统一指针。

**最小修正方向**
后续实施时，`ENTRYPOINTS.md` 增 1 行指向知识准备／学习工作单；根 `AGENTS.md` 只增 1 行纯指针，不复制规则；rollout skills 按实际部署需要复用同一指针。`WORKSHEET.md` 的接收／续接内容已完成，不重复新增。

**需要新增的组合验证**
文档内命令清单与 `argparse` 实际子命令／必填参数的一致性测试，覆盖当前 `WORKSHEET.md` §7，而非只检查命令名是否存在。

**是否需要用户作价值取舍**：不再需要。用户已确认允许根 `AGENTS.md` 增加一行纯指针；本轮仅记录该设计决定，未修改文件。

**Token 成本／用户负担／证据质量**：剩余改动以少量指针为主；收益是让无历史上下文 Agent 能到达当前工作单。

---

### 4.3 P2（23 条）

以下每条按 §6 要求给出：原文＋行号＋摘要、影响、替代解释／缓解、最小修正＋组合验证＋是否需用户取舍。

| # | 标题 | 生命周期／处置 | 关键依据（文件:行，SHA256 前 16） | 影响与替代解释 | 最小修正 ＋ 组合验证 ＋ 取舍 |
| --- | --- | --- | --- | --- | --- |
| **P2-01** | K4 `check-preparation` 把全部失败压成单一错误码 | 新增／修正候选 | `evidence/integration_cli.py:37-39`（`A4AD4EDACC669EF9`）：`except (DeliveryError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError): result, code = {'result':'rejected','code':'integration_input_or_dependency_invalid',...}, 2`。探针实测三种畸形接线（多字段／缺 `review`／文件不存在）输出**完全相同**。被丢弃的精确码本就存在：`learning_book/knowledge_preparation.py:19-22`（`preparation_descriptor_fields`／`_schema`）、`:96`（`production_review_missing`） | K／L／C1／C2／C3 凡经 `check-preparation` 者。**替代解释**：折叠是防泄漏设计，但被丢弃的是**非敏感错误码**而非内容，隐私收益≈0 | 透出 `exc.code` 并按码映射 `nextAction`，不保留路径。验证：三种畸形接线 → 三个互不相同的 code。无取舍 |
| **P2-02** | 退出码 2 跨 5 个 CLI 语义冲突；argparse 用法错误绕过"stdout 必有 JSON" | 新增／修正候选 | 文档基线 `evidence/README.md:62`（K1：0／2／3）、`KNOWLEDGE.md:12`（K2）、`PROJECTION.md:12`（K3）同构；但 `learning_book/cli.py:18-19`（`0635B3E2061B4527`）的 `EXIT_CODES` 里 `invalid:2`、`conflict:3`，与文档**不一致**。探针：K2 `check-knowledge` 少传 `--context` → exit 2 且 **stdout 为空**（usage 落 stderr）；`learning_book/cli.py:22-25` 把 argparse 错误转成 JSON，两侧契约不同 | 只做 `exit != 0` 判断的 Agent 无法区分"参数写错"与"知识未审完"。**替代解释**：0/2/3 分层本身正确（"零退出不授权"），缺陷仅在 argparse 复用 2 | 4 个 evidence CLI 把 argparse 错误统一为 `findings:[{code:'invalid_arguments'}]`＋exit 3；补 K4 退出码契约。验证：缺必填参数 → exit 3 且 stdout 有 JSON。无取舍 |
| **P2-03** | `previous` 在三处是三种互不兼容形状 | 新增／修正候选 | `evidence/preparation.py:274-276`（K1，`previous_learner_scope`）／`evidence/knowledge.py:185-198`（K2，`package_history_binding`）／`evidence/projection.py:34-42`（K3，`previous_projection_shape`）；而连接文件**只有一个** `previous` 字段（`WORKSHEET.md:56`），`knowledge_preparation.py:32-33` 把它**只喂给** `build_learning_projection` | 新 Agent 复用一个 `previous.json` 跨阶段会硬失败，或更坏——语义错配。**替代解释**：各阶段文档分别定义了自己的 `previous`，代码与阶段文档一致，缺的是工作单层的一句消歧 | `WORKSHEET.md` §4 明确"本文件 `previous` 仅指 K3 投影历史"；补负向测试。验证：同名字段跨阶段误用 → 得到 `previous_projection_shape`。无取舍 |
| **P2-04** | 契约只存在于散文：无机器可校验 schema，Agent 需手写 8 份封闭 JSON | 新增／修正候选 | `tools/wiki_runtime/evidence/` 17 个文件**零个 `.json`**；封闭字段只在代码 `_fields`（`preparation.py:39-40` 的 `set(value) == set(fields)`）。需手写：`knowledge-context-request/1`（`preparation.py:259-261`）、`knowledge-preparation-request/1`（`knowledge.py:213-214`）、`learning-projection-request/1`、`wiki-preview-request/1`（`preview.py:69-70`）、`knowledge-preparation-connection/1`（14 字段）、2 份审阅观察、1 份步骤请求 | **视角分歧**：Agent DX 角色主张补 schema；上游角色经探针实测认定 `_fields` 是**封闭等值检查，强度不低于 JSON Schema**，且 `wiki_runtime/contracts/schemas.json` 由 `core.py:85` 的 `load_schema()` 实际加载并用封闭 JSON Schema 子集校验，**补 schema 净增一份需同步的真值** | **主 Agent 裁决**：采纳上游角色，**不补 schema**；改为在 `evidence/README.md` 显式记录"本目录契约以代码 `_fields` 封闭集合为准，不提供 JSON Schema"，并补一张"各 CLI 读哪个状态字段"的统一枚举表。验证：文档断言与 `_fields` 实参集合逐项相等（从代码反射比对）。无取舍 |
| **P2-05** | 回执与上下文体量：单路线约 21 个中间 JSON；无"下一步该跑什么"的可执行导航 | 新增／修正候选 | 必读文档实测 99,972 B（AGENTS 17,963＋WORKSHEET 9,863＋evidence 三份 27,352＋learning_book 五份 44,794）；冻结 8 文件合计 48,041 B，**其中不含定义 request schema 的 27,352 B** → 只读 8 文件必然在 `request_fields` 上失败 | **替代解释**：`AGENTS.md` 是常驻上下文、其余按需读，线性相加**高估**真实成本；故这是量级结论而非精确账单 | 给 `check-preparation` 增加"下一步该跑什么＋该读什么"的机器可读导航（命令名＋必需参数＋期望状态）。验证：对每条路线状态迁移断言 next-step 与 `WORKSHEET.md` 步骤表一致。无取舍 |
| **P2-06** | wiki 侧宿主用量不可观测；模块级 `modelCalls: 0` 易被误读 | 新增／修正候选 | `evidence/integration_cli.py:30`、`content_view.py:88`、`projection.py:306` 均输出 `modelCalls: 0`；`host/model.py:176-192`（`4AABEFA56BB6C090`）只解析 `output` 消息，**全 `host/` 目录 grep `usage\|input_tokens\|output_tokens\|cache_read\|total_tokens` 零命中**。L 侧对照：`learning_book/budget.py:242,253-276`（`E02909621CB43007`）读 provider 的 `llm_calls` ledger | 任何"K 路线省了多少"的断言当前**不可证伪**。**替代解释**：`modelCalls: 0` 的真实含义是"这个确定性模块自己没调模型"，是准确的模块级事实；把它当 K 路线 Token 结论才会形成错误信任。`acceptance.json:19` 已诚实写 `hostConversationTokens: "unknown"` | 保留 `modelCalls: 0`，增加 `modelCallsScope: 'deterministic_module'`、`hostUsage: null`、`usageObservable: false` 与确定性代理指标；`host/model.py` 的 usage 采集只对应 K 侧宿主调用，不与 P2-21 的 L 侧归因合并。验证：模块级 0 保留，宿主用量仍明确 unknown。无取舍 |
| **P2-07** | C1／C3 的新命令在工作单缺席，外部 Agent 无从得知续接入口存在 | 已修复待验／修正候选 | 原审查基线中 `revalidate-preparation` 与 `adopt-knowledge` 在工作单零命中。**收尾复核**：当前 `WORKSHEET.md`（`F523F9A99A43564D`）§7 已补接收、独立审阅、续接命令及前置条件 | 原缺口已由后续连接修复覆盖；C1／C3 仍属既定交付范围，无需再作产品选择 | 剩余验证为文档命令与实际 CLI 的确定性一致性测试，以及续接组合测试的 sequence／digest 单调性断言；本轮只做设计复核，不新增实施 |
| **P2-08** | 交接包已带 `preparationEvidence`，但 `HANDOFF.md` 的包表与消费者提示词都不提 | 新增／修正候选 | `learning_book/schemas/learning-handoff.schema.json:25`（`D2103BB5930AEEF7`）已定义 `learning-preparation-evidence/1`（refMap ≤33、`sourceOriginalsVerified` 恒 false）；但 `tools/learning_book/HANDOFF.md:35-44` 的包文件表与 `:72` 的消费者提示词**均未提及**。代码侧确实搬运：`handoff.py:381-384`（`486BE5C5AD9B985F`） | C1 最重：下一个 Agent 拿包**按文档**读，找不到 Claim／原文依据。**替代解释**：`preparationEvidence` 设计为可选（仅当该活动确有绑定时才有），`HANDOFF.md` 未列属"未随实现更新文档" | `HANDOFF.md` 包表增 `preparation/` 一行；消费者提示词补"若存在 preparation 证据，按其 refMap 找回约定／映射／知识观察并区分事实证据与学习者证据"。验证：`post-k4-review.md:51` 要求的消费验收（本轮已由 `test_I4_I5_portable_package_can_resolve_brief_claims_and_evidence_offline` 通过，需在 `HANDOFF.md` 引用该用例名）。无取舍 |
| **P2-09** | 原件必须先正式写入 `raw/` 才能预览，"登记 raw"无命令映射 | 新增／修正候选 | `WORKSHEET.md:22`"先经适用的采集入口登记原件"；`evidence/PROJECTION.md:55`"要求原件已在完整基线的 `raw/unprocessed` 登记…否则返回 `raw_capture_required`"；真正落地 raw 的是 `host/cli.py:193-198,202-203` 的 `import-package`（"确定性候选，经统一执行器应用"）——**没有任何文档把"登记原件"翻译成这条命令** | K 路线真实最小序列比工作单呈现的多两步，且顺序与"先审后写"直觉相反。**替代解释**：这是三层结构的**必然正确顺序**（`AGENTS.md:20-26` 规定 raw 是事实来源层、主张必须落在已有原件上），缺陷只在文档未写清 | `WORKSHEET.md` §3 补"登记原件＝`host/cli.py import-package --package-root … --raw-path …`（经统一 Executor）"。验证：从空 `raw/` 跑通 capture→import-package→inspect-context→prepare-knowledge→preview 的最小链。无取舍 |
| **P2-10** | `PREPARATION.md` 对门禁状态的断言已过时（方向相反） | 新增／修正候选 | `tools/learning_book/PREPARATION.md:9`（`2727D7AE919663AD`）"**目前这是准备者需要执行的工作约定，自动门禁与知识背景比对尚未实现**"；但 K4 已实现：`learning_book/cli.py:77` 为 `publish-inputs/recover-inputs/create/confirm-*` 加 `--knowledge-preparation`，help 写"显式知识准备接线 JSON；**受控请求不可省略**" | L／C2／C3。用户按文档判断"要不要准备接线文件"会判断错误，且**错误发生在所有准备工作做完之后**，返工成本最高。**替代解释**：PREPARATION.md 描述原生 `prepare.json` 工作约定，K4 接线是可选增量，两者可共存——但"尚未实现"与"不可省略"不能同时为真 | 改写 `PREPARATION.md:9` 并指向 `WORKSHEET.md` §4。验证：文档一致性检查（断言不再含"尚未实现"）。无取舍 |
| **P2-11** | 项目内无搜索发现与通用抓取；资料卡 11 项要求字段中 4 项无载体 | 新增／待裁决 | `tools/` 下 grep `search_engine\|bing\|google\|duckduckgo\|serp\|search_api\|def_search\|web_search` → 零命中；唯一命中是 `host/codex.py:379`（`F7B5BE3DD77DA8A9`）把 `web_search` 设为 `'disabled'`。真实出网只有 `host/wechat.py:36-58`（微信白名单）与 `host/model.py:150`。`capture/adapters.py:16-20,30-32` 只注册 markdown／wechat／pdf 且 `capabilities()` 返回 `offline:True, used_ocr:False, used_model:False`。资料卡对照：`contracts/schemas.json:104-172` 的 `source_package` **无** `canonical_url`／`summary`／`claim_ids`／`reviewRequired`；`capture/adapters.py:251-252` 的 `locators` 只有 `{block_id, artifact_path, location}`，**不含摘录正文** | 全部路线（原料入口共用）。**替代解释（主 Agent 采纳）**：这是**刻意的安全边界**——`codex.py` 关 `web_search`、`wechat.py` 严格白名单、`plan.md:86` 明确"网络获取由宿主现有能力提供"。真正的缺陷是**工作单没有声明该边界**，以及宿主 `defuddle` 技能存在但 CLI 未安装（`Get-Command defuddle` → ABSENT），**能力声明 ≠ 当前可执行** | ① 在 `WORKSHEET.md` 明确"用户自己完成『找到 URL → 抓到本地 → 选对格式』三步，项目从第 4 步开始；wechat 路径可省第 2 步但仅限微信文章"；② 把"资料卡字段是否属本仓契约"作为**显式待决项**交回用户；③ 若要补资料卡，做成 `source_package` 的**兄弟层**（独立 schema）而非加字段，使摘要的候选性质在类型层面被隔离。验证：`reviewRequired` 常开 ＋ 摘录逐字绑定 ＋ locator 可回读 三项断言。**需用户取舍**（是否要为一个真实抓取／校验步骤付费） |
| **P2-12** | 准备依据归档内嵌完整 KnowledgePackage 副本，但未标注快照属性 | 新增／修正候选 | `learning_book/knowledge_preparation.py:54-58`（`843113E030DE982F`）归档含 `'knowledge': args[1]`；`preparation_provenance.py:31-37`（`0C21E8E4B422A678`）的自洽性只由**归档内部重建**保证（用归档里的 request 重建 package 再与归档里的 package 比对），**不回读工作区的 `knowledge.json` 或原文字节** | L／C1。与 `knowledge-preparation-k0-contracts.md:27`"新记录引用这些产物，**不复制原始作答、课程正文或 Claim 成为新正本**"存在张力。**替代解释**：归档内容寻址、不可变、≤4 MiB 有界，且显式标注 `sourceRetention:'external'`／`sourceOriginalsVerified:False`；R4 修订原文要求"保存…**及引用**"，现有实现是超集。这是**快照语义未显式化**，不是"第二套可写状态库" | 在归档 schema 与 handoff 清单中显式标注 `snapshotOf`／`observedAt`／`currency: 'snapshot_not_current'`，并在 `verify_preparation` 中断言该字段存在。验证："归档后修改工作区 `knowledge.json` → 交接包仍验证通过但明确标注非当前"。无取舍 |
| **P2-13** | 同名字段 `mappingDigest` 在两个 schema 中语义不同 | 新增／修正候选 | `knowledge_preparation.py:48-51` 的 `binding.mappingDigest = digest(mapping)`（**含** `projectionReviewRef`）；`evidence/projection.py:269-270,293` 与 `preparation_provenance.py:82-83` 的 `mappingDigest = digest(core)`（**不含** `projectionReviewRef`）。实测证据：`docs/design/evidence/knowledge-preparation-k4/cli-smoke.json:14`（`16afb83…`）与 `:108`（`069f644…`）——同一份产物，两个值 | 跨模块消费与人工判读。**当前无功能性缺陷**（代码从未把两者互相比较）。**替代解释**：这是为打破"映射摘要←审阅引用←审阅摘要←映射摘要"循环而做的必要拆分，属刻意设计 | 核心摘要改名 `coreMappingDigest`（或 binding 改 `fullMappingDigest`），两个 schema 说明二者关系。验证：同一份产物的两个摘要分别等于其定义所指集合的摘要。无取舍 |
| **P2-14** | 文档正本状态陈述不一致 | 部分已修复待验／修正候选 | 原基线中 `knowledge-preparation-plan.md` 与 handoff 的四项修复状态冲突。**收尾复核**：当前 handoff（`E0D6D477916ABB55`）顶部已指向连接修复验收与 185 项最终依据；`research/upstream-learning/report.md:370` 的固定课堂候选表述仍与 D1 的 DeepTutor Book 推荐存在时间层级差异 | 当前 handoff 已消除主要状态冲突；旧 `report.md` 属研究过程，保留原文但需明确历史层级 | `plan.md` 与旧研究文档只补当前入口／历史取代注记，不重写历史正文。验证：文档状态链接和 D1 选型注记的确定性检查。无取舍 |
| **P2-15** | `docs/design/` 顶层 31 份文档并存，旧 ingest 链未归档 | 已知待修／修正候选 | 实测顶层 31 份：plan 10／handoff 8／review 5／other 8；其中旧 ingest 链至少 9 份。归档先例：`docs/design/archive/2026-10/` 已有 13 份 | 全部路线（检索面）。这些文档承载审阅链与历史结论，删除会破坏可追溯性；首轮上游评审又是 `report.md` 更正的对照物，应与旧 ingest 链区别处理 | 设计定论为**归档不删除**：只把旧 ingest 链 9 份移入 `docs/design/archive/2026-11/`；首轮上游评审保留在当前区并加历史注记，`docs/design/README.md` 补当前入口。实际移动属后续实施，验证链接与健康检查。无需用户重新选择 |
| **P2-16** | 课程交付的 16 份源快照中 6 份与现行原文不同，缺少差异说明 | 新增／修正候选 | 收尾复核直接读取 `docs/learning/system-architecture/evidence-index.json`：已有 `asOf: 2026-11-11`，因此原“无版本标记”表述不成立。逐对比对现行原文与索引 hash：10 份 SAME，`01-architecture-proposal.md`／`04-production.py`／`09-local_install.py`／`11-LOCAL_USE.md`／`12-PREPARATION.md`／`14-README.md` **DIFF** | L／C2。漂移本身可见且可核对；快照保存当时字节，与后续实现不同是正常行为，不是数据损坏 | 不改快照、不重新冻结历史证据。后续仅在 `source-snapshots/` 增加说明，引用已有冻结日期与 hash 清单，并列出上述 6 份当前差异。验证同时核对快照字节与索引 hash、现行原文与索引差异。无需用户选择 |
| **P2-17** | state-dir 与 runtime 库无 schema 版本迁移阶梯 | 新增／修正候选 | `tools/wiki_runtime/runtime/storage.py:17,201-204`（`0B7BFCC5DE7964DC`）：`SCHEMA_VERSION = 1`，版本不符直接 `SchemaVersionError`；`tools/learning_book/evidence_store.py:103`（`6F84D80B0D0927F3`）写 `"schemaVersion": 1` 但**无对应迁移**。上游对照：`report.md:321` 记 OpenMAIC 有"版本化 schema 迁移 ＋ 校验和 ＋ advisory lock" | L。**替代解释**：本项目 state-dir 尚在单一部署形态，I3–I5 均以**独立 state-dir** 跑，实际未发生原地版本升级，迁移需求**尚未真实发生**；`local_install.py` 的 `enrollment.json` 已用"same cumulative call IDs"显式记录了**路径**迁移语义 | **不建迁移框架**（那是上游已有、当前不需要的重轮子）。改为：`evidence_store.py` 读到 `schemaVersion != 1` 时**显式拒绝并给出"需要新 state-dir"的明确消息**（把隐式 KeyError 变成确定失败）；`enrollment.json` 增 `schemaVersion` 留位。验证：旧版 state-dir fixture 触发拒绝路径，断言消息与退出码确定。**若要真正支持原地升级则需用户确认是否值得** |
| **P2-18** | `bytesRead` 是"工作字节"而非"上下文字节"，存在 2× 重读放大 | 新增／修正候选 | `evidence/preparation.py:343` 的 `context['coverage']['bytesRead'] = reader.used`；`:338-342` 返回前**重读**全部已用文件并重算清单 → `reader.used` 含重读量。`evidence/README.md` 与 `PROJECTION.md:59` 都已声明"不能把视图计数当全部系统读取统计" | Token 口径：**这是本地 IO 工作量，不是 Token，也不是上下文大小**——四类口径里属"不产生节省"。**替代解释**：重读是刻意的正确性保证（返回前验证依赖未变），不是浪费 | 新增 `uniqueBytesRead` 字段与 `bytesRead` 并列；在 §7.1 口径表注明"本地 IO 工作量 ≠ Token ≠ 上下文大小"。验证：断言 `uniqueBytesRead <= bytesRead`。无取舍 |
| **P2-19** | 上下文对象内嵌全量原文（上限 1.5 MiB），与"短回执"目标相反 | 新增／修正候选 | `evidence/preparation.py` 的 `context` 内嵌 `documents[]` 全文；`:52` 附近限额为 context JSON ≤1.5 MiB；`evidence/README.md:38`"只支持 .md／.txt" | **节省类型**：属"减少原始输入/输出"的**反面**——送模型的上下文偏大。**替代解释**：内嵌全文是"摘录必须逐字等于原文行拼接"（`evidence/knowledge.py:23-30`）与"可回读定位"的前提，不能简单改成只存摘要 | 保留摘录逐字绑定与可回读定位，但把**未用于主张支撑的文档正文**改为落盘＋引用（按需回读），使进模型的上下文只含实际被引用部分。验证：主张数不变时上下文字节显著下降且逐字一致性仍 100%。**需用户取舍**（是否愿意增加一次回读往返） |
| **P2-20** | K1 正文内容检索缺失（`bodySearch: False`） | 新增／修正候选 | `evidence/preparation.py:335`：`'bodySearch': False, 'wholeWikiExhausted': False`；召回只靠文件名、索引行与双链选择候选页 | "查库"实际是**元数据候选选择**，不是全文／语义搜索。**替代解释**：这是 K1 的明确设计（handoff.md:97"**它是元数据候选选择，不是全文／语义搜索**"），且真实根仅 43 文件，量级不需要向量检索 | 任何"检索已覆盖"类结论必须带 `bodySearch`／`wholeWikiExhausted` 限定语；若要补，先做**关键词**子串检索（复用 `capture/adapters.py` 既有分块定位），**不引入向量栈**。验证：精确关键词命中、大小写／空白变体及未命中用例；不把同义词理解作为子串检索承诺。**需用户取舍**（是否值得为召回率补一层） |
| **P2-21** | L 路线归因管道存在但产出为空 | 新增／修正候选 | `learning_book/budget.py:238-278` 与 `learning_book/runtime_guard.py:46-47,131-139` 的 `calls` 表已含 session_id／turn_id／source 三列，但 I6 实测**三列全空**；`docs/design/evidence/learning-book-i6/token-audit.md:15` 自述无法可靠细分且未用日志标签猜算 | 归因缺失会把"生成循环贵"误判为"资料搬运贵"。现有空值是诚实边界，不应猜补；`runtime_guard.begin()` 已有三个可选参数，但项目 Python 源码未显示生产调用点，需继续追踪实际补丁调用方 | 独立追踪 L 侧 `runtime_guard.begin()` 的生产调用者并传入真实 session／turn／source；不得用 P2-06 的 `host/model.py` 采集冒充 L 侧归因。在此之前，按 Agent 归因仍注明 per-call 为空。验证：合成 L 调用落库后可读出三列。无取舍 |
| **P2-22** | C3 的失效粒度是"全量重建"而非方案要求的"局部失效" | 新增／修正候选 | `evidence/preparation.py:361-362`：`_need(_inventory(roots[0], reader) == paths, 'inventory_changed_during_inspection')` → wiki **清单摘要**任一变化即判 stale；`:347-366` 的 `verify_context` 之后**必须**重跑 inspect→knowledge→brief(version+1)→request(version+1)→recognition→review 全链（组合测试 `refresh_after_wiki_change` 正是如此） | C3 的成本与用户负担：并行维护一次 wiki 就要**重建整条准备链**，不是只重做受影响主张。**替代解释**：清单变化确实可能改变候选页集合，全量失效是**保守正确**的选择；方案写的"局部失效"是更细的粒度目标而非已交付能力 | 把失效判定从"清单摘要相等"细化为"**已读页字节 ＋ 被选候选集合**"两级：清单变但已读页未变时不使已读页失效，只重做候选选择。验证：新增一页无关文件后，仅重跑候选选择而非全链。**需用户取舍**（保守失效 vs 增量失效的返工成本） |
| **P2-23** | R1 重启／完整原回执缺失仍待补证；R3 分类迁移已有后续复核 | 部分已修复待验／修正候选 | 原基线只覆盖 wiki/index 追加。**收尾复核**：当前组合用例已删除原上传回执的输入文件后验证复用副本仍 complete；后续独立复核记录明确关闭迁移分类问题。现有记录仍未单独证明“复用后重启实例”及“完整原回执缺失”两个 R1 分支 | 不能继续写成两个分支完全未覆盖，也不能把原输入文件缺失外推为整个原回执缺失或重启验收 | 后续只需补 R1 两个明确分支；R3 分类迁移引用现有独立复核，不重复实施。所有真实应用仍不在设计阶段执行。无取舍 |

---

### 4.4 P3（13 条，观察项／局部简化）

| # | 标题 | 生命周期／处置 | 关键依据 | 说明与替代解释 |
| --- | --- | --- | --- | --- |
| P3-01 | `canonical`／`digest` 两套等价实现 | 新增／修正候选 | `tools/wiki_runtime/contracts/core.py:19-21`（`CD2AA0A786E7A9BF`）与 `tools/learning_book/contracts.py:18-20`（`40AD20BA4CCCB4AC`）；探针实测三组用例字节与 digest 完全一致。`evidence/projection.py:8` 已从 `learning_book.contracts` 导入 → 边界早已穿透 | 合并为薄转发。**替代解释**：可能曾是有意的部署隔离，但两侧都是纯标准库，隔离理由不成立。**验证**：重跑全部 digest 绑定不变性测试，确认已落盘 receipt 的 digest 未变 |
| P3-02 | `preparation_handoff` 的 `oldRef` 实际存放 path 字符串 | 新增／仅观察 | `preparation_handoff.py:11-16,48-53,74`（`E82A451C4DAA7D97`） | 命名与内容不符，非逻辑错误。改名 `oldRefPath`。无取舍 |
| P3-03 | `sourceOriginalsVerified` 是常量 `False`，无法区分"确认未验证"与"尚未验证" | 观察项／仅观察 | `preparation_provenance.py:23`、`preparation_handoff.py:62-64` | 降级是**显式标注**的，不是静默降级。改三态枚举（`not_verified`／`verified_external`／`unavailable`）。无取舍 |
| P3-04 | `previous` 历史链只留摘要，正文未随包归档 | 观察项／仅观察 | `evidence/projection.py:31-42,294`（`9100D8369CB63937`） | 设计意图即为显式、非全局的短链，摘要级足以判定失效。归档附 `mapVersions` 明细为后续项。无取舍 |
| P3-05 | 宿主 `defuddle` 技能存在但 CLI 未安装 | 观察项／仅观察 | `Get-Command defuddle` → ABSENT；技能自身写明 "If not installed: `npm install -g defuddle`" | **能力声明 ≠ 当前可执行**。本轮**未安装**（需授权）。最小补证：`npm ls -g --depth=0`（只读） |
| P3-06 | 47 次调用（用量见本机账本） 对应 361 字符源材料 | 观察项／仅观察 | `docs/design/evidence/learning-book-i6/token-audit.md:11-13,19` | 固定开销×调用数主导，与资料长度弱相关。**不得据此计算节省百分比**（两次运行用量见本机账本，不是同一任务集） |
| P3-07 | markdown 适配器的 locator 为逐行粒度，长文包体积膨胀 | 观察项／仅观察 | `capture/adapters.py:139,148-149,251-252`（`AB631C3F5FF792D0`） | 合并相邻行为块级 locator。无取舍 |
| P3-08 | 上游克隆无 tag，"1.7.2" 与 commit 的绑定只靠 subject 文本 | 观察项／仅观察 | `references/upstream/manifest.json:3` 声明 `no-tags`；DeepTutor commit `60fb3bd…` 的 subject 为 `release: v1.7.2` | 已知且声明过的克隆策略。在 manifest 增 `version_source: "commit-subject"`。无取舍 |
| P3-09 | 上游升级会外溢到本项目的具体改动面为三处 | 观察项／仅观察 | 补丁面 7 个上游文件（I4 改 2／I5 改 1／I6 改 4）；安装面 `learning_book/local_install.py:58` 硬编码"必须 8 个 wheel"；依赖面 `patches/deeptutor/closeout/dependencies.lock` 固定 84 个包 | 设计意图的**正确执行**。建立"上游版本 → 补丁重建清单"短文档。无取舍 |
| P3-10 | 上游六个项目均未提供"人与 Agent 调用同一套业务操作"的现成外部门面 | 观察项／仅观察 | `references/upstream/lattice.md:17`"没有 MCP、没有 HTTP API、没有对外 CLI"；`open_notebook_mcp.md:322` 记 4 处静默失败 | 本项目 `Production` 是"普通应用操作，CLI／未来 Web／MCP 共用"，**已做到上游都没做到的事**。建议把该来源写进设计文档 |
| P3-11 | 六道确认无语义重复，但有可省的机械税 | 观察项／仅观察 | ①约定认可 ②K2 语义审阅 ③K3 上传物审阅 ④I3 步骤审阅 ⑤I4 课件审阅 ⑥用户 approve。④ 的载体是接线 schema 里**唯一**的 `operationReview` 槽，而受控路径需审 `confirm-proposal`／`confirm-spine`／`prepare-quiz` **三个**操作 | ②③④绑定**不同对象**，无重复；单用户下角色坍缩是部署形态而非设计缺陷。把 `operationReview` 从单槽改为按操作列表。**需用户取舍**（单用户 6 次往返是否作长期形态） |
| P3-12 | `assurance` 字面量两写法并存 | 新增／修正候选 | `operator_supplied`（`projection.py:283`、`knowledge.py:119`）vs `operator_supplied_no_host_authentication`（`knowledge_preparation.py:51,58`） | 跨侧组合时**主动降级**为更保守写法，是有意加强。只需统一字面量或加交叉说明。**验证**：`preparation_provenance.py:52,71,75` 断言同步后重跑 `test_learning_book_preparation.py` |
| P3-13 | `learning-book` 侧 6 道确认与 `evidence` 侧 5 道确认的术语表未统一 | 观察项／仅观察 | `KNOWLEDGE.md:14`（`E828708629FB83F9`）与 `knowledge_preparation.py:41-51` | 状态机**层次不同**（K 侧审阅 vs L 侧投影），不应合并；只需共享术语表。归入 P2-04 的统一枚举表一并处理 |

---

## 5. 视角间一致与分歧

### 5.1 四个角色独立确认的结论（一致）

| 结论 | 用户旅程 | Agent DX | 架构 | Token | 上游 | 主 Agent |
| --- | :-: | :-: | :-: | :-: | :-: | :-: |
| K 路线终点"正式维护"被显式关闭 | ✓ | ✓ | ✓ | | | ✓ |
| C2「先学后入库」无载体 | ✓ | ✓ | ✓ | | | ✓ |
| 原审查基线中，新命令（`adopt-knowledge`／`revalidate-preparation`）不在用户文档；收尾时工作单已补 | ✓ | ✓ | ✓ | ✓ | | ✓ |
| `AGENTS.md`／`ENTRYPOINTS.md` 不含 K／L 路线 | ✓ | ✓ | | | | ✓ |
| K／L 数据真值唯一，无第二套可写状态库 | | | ✓ | | ✓ | ✓ |
| 项目内无搜索发现与通用抓取 | ✓ | | | ✓ | | ✓ |
| 无决定性反证，不重新选型 DeepTutor | | | | | ✓ | ✓ |
| 宿主用量不可见须记 `unknown`，不得写成 0 | | ✓ | ✓ | ✓ | | ✓ |

### 5.2 实质分歧与主 Agent 裁决

| # | 分歧 | 各方立场 | 主 Agent 裁决与理由 |
| --- | --- | --- | --- |
| 1 | `evidence/` 侧是否应补 JSON Schema | **Agent DX**：应补，8 份手写 JSON 是高负担且无机器可校验契约。**上游**：**不应补**——`_fields` 是封闭等值检查（强度不低于 JSON Schema 且拒绝未知字段更严格），补 schema 净增一份需同步的真值；且 `wiki_runtime/contracts/schemas.json` 由 `core.py:85` **实际加载**，并非"wiki_runtime 侧无 schema" | **采纳上游，不补 schema**，改为在 `evidence/README.md` 显式记录设计决定 ＋ 补统一状态枚举表。理由：契约强度已达标，schema 的边际收益低于其同步成本。P2-04 已按此改写 |
| 2 | 「无搜索发现与通用抓取」的严重度 | **Token 角色**：P1（若 C3 作为项目能力交付）；**用户旅程**：P2（明确取舍，减少负担但换来不可验证的信任）；**上游**：不构成接入理由 | **定为 P2**。理由：`knowledge-preparation-plan.md:86` 明确"网络获取由宿主现有能力提供"，该边界**已写在设计层**；审查方案 §7.3 是**候选评估清单**，不是项目承诺。真实缺陷是"工作单没对用户声明这条边界"＋"宿主 defuddle 技能在但 CLI 未装"。P2-11 已按此改写 |
| 3 | `report.md` §8 的选型结论是否需要重写 | **上游**：**加标注，不重写正文**（保留研究过程真实性） | **采纳**。P2-14 按标注处理 |
| 4 | `docs/design/` 旧文档是删除还是归档 | **上游**：**归档不删除**（删会破坏更正的可追溯性）；但首轮评审文档与旧 ingest 链应分别处理 | **采纳为设计定论**：旧 ingest 链 9 份归档，首轮评审文档保留并降级标注；不再把删除列为等价选项。实际移动属后续实施 |
| 5 | R1–R4 的最终状态 | **架构／用户旅程／Agent DX**：均为"已修复待验"；**主 Agent**：已实际跑通组合验收 | 以实际组合验收和后续独立复核为准：R1／R3／R4 主路径已验，R2 仍缺正式维护适配；R3 分类迁移已有后续复核，R1 重启／完整原回执缺失仍待补证（P2-23）。本报告不新增关闭声明 |
| 6 | 实现与故障审查者未在预算内完成 | 该角色未交付；其职责由主 Agent 直读代码、实际运行验收及其他角色交叉覆盖 | 记为 **`evidence_insufficient`**，不是审查者自行“接受限制”。崩溃重启、并发写、恶意输入的独立复核缺口保留在 §10 |

### 5.3 对抗复核（1 轮，仅高严重度）

按方案 §4，对 P1 三条做证据冲突与既有缓解复核：

| 高严重度 finding | 证据是否不足 | 是否已有保护 | 是否只是用户已接受限制 | 复核结论 |
| --- | --- | --- | --- | --- |
| P1-1（K 终点关闭） | 否——`supervisor.py` 原文直接证明 | **有**：错误显式、无静默降级；R2 修订案允许只读交接这档 | **部分是**——保持关闭曾是刻意的安全边界 | **维持 P1**。收尾时用户已选择薄适配，K 定义不变；既有正式门禁不放宽，当前未实施 |
| P1-2（C2 无载体） | 否——三处原文构成完整静态追踪 | **有**：用户原话被 sha256 绑定归档；业务矩阵已诚实标 `partially_verified` | **部分是**——原设计允许先做工作约定 | **维持 P1**。收尾时用户已选择硬门禁；还需 taskId／learningHandoffRef 绑定，不能只加枚举便宣称闭环 |
| P1-3（入口断链） | 否——根规则与入口矩阵的零命中可复现 | **有**：当前工作单已补命令；`--help` 和设计交接可定位 | **部分是**——工作单本就是派单交付物 | **维持 P1**，但工作单缺失部分已后续修复；剩余为公开入口指针，用户已允许根 AGENTS 纯指针，当前未实施 |

**复核未发现需要下调或撤销的 P1**；未发现"以静态设计覆盖实际闭环"的误判。

---

## 6. Token 消耗画像

### 6.1 口径分离（按方案 §7.1）

| 类型 | 本项目的实例 | 不能误写为 |
| --- | --- | --- |
| 减少原始输入／输出 | 有界读取＋`read_limits` 限额、摘录逐字绑定、短回执（只返回引用／摘要／状态／下一动作） | 缓存命中就等于原始 Token 消失 |
| 减少模型调用 | `prepared_templates` 直接进入题目生成、每题工具轮次收紧、确定性步骤零模型 | 多 Agent 并行一定节省 |
| 降低计费或延迟 | Prompt Cache（I6 实测 cache_read 占输入 54.72%）、低价模型 | 实际发送内容必然减少 |
| 转移为本地计算 | 本地 embedding（Ollama bge-m3，1024 维） | 本地 Token 与硬件成本为零 |

### 6.2 实际消耗环节

| # | 环节 | 发起者 | 输入规模 | 确定性预处理 | 计量可见性 | 依据 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | K 路线语义裁决（改写／查询／lint） | 受信宿主 `StandaloneHost.run_operation` → `ResponsesTransport` 或 Codex 原生 transport | 每次 operation ≤8 次模型调用；输入为已封封的 context（≤1.5 MiB）＋选定页 | **有**：有界读取、`byteDigest` 绑定、摘录逐字校验 | **无**：`host/model.py:176-192` 只解析 `output` 消息，全 `host/` 目录无 `usage` 采集点 | `host/supervisor.py:392-393`；`host/model.py`（`4AABEFA56BB6C090`） |
| 2 | L 路线课件／题目生成（业务 API） | DeepTutor runtime（minimax-m3，`reasoning_effort=none`） | 语料＋模板＋循环；I6 实测 compile_core 47 次调用 | 部分（I3 归一化、投影、预审题目模板） | **可见**：只读上游 `usage.sqlite3` 的 `llm_calls`，实报／估算／缺失分列 | `learning_book/budget.py:242,253-276`（`E02909621CB43007`） |
| 3 | L 路线本地 embedding | DeepTutor 索引层（Ollama bge-m3） | 文本切块 → 1024 维 | 有（本地向量） | **unknown**：`budget.py:276` 默认返回 `{"metering":"unknown"}` | `learning_book/budget.py:276` |
| 4 | 宿主主／子 Agent／Skill／MCP | 宿主 | 不可见 | 部分（脚本化环节不调模型） | **unknown**（仓库无采集点；验收文件自身写 `unknown`） | `docs/design/evidence/knowledge-preparation-k4/acceptance.json:19` |

> **关键口径**：`modelCalls: 0` 出现在 `content_view.py:88`、`projection.py:306`、`integration_cli.py:30`，含义是"**这个确定性模块自己没调模型**"，**不是**对模型 transport 的计量。把它当成 K 路线的 Token 结论即为错误信任。

### 6.3 可引用的账本数据（自洽性已复核）

| 口径 | 数值 |
| --- | --- |
| I6 阶段基线 | 62 次调用／tokens 用量见本机账本（输入／输出／cache_read／reasoning 分项同账本） |
| 四阶段自洽 | 四阶段分项之和 = 阶段基线总数；1＋5＋47＋9 = 62 ✔ |
| I6 终值 | 67 次调用／tokens 用量见本机账本 = 实报 ＋ 估算 ＋ 0 缺失；与基线增量精确对账 ✔ |
| 架构课程增量 | tokens 用量见本机账本（正文直写 0、首题 1 次调用） |
| 业务累计 | tokens 累计见本机账本；总额 100 万／暂停线 80 万 |
| cache_read 占比 | I6 阶段：**54.72%**（分子分母见本机账本）（属"降低计费或延迟"，**不是**原始 Token 消失） |

**必须写 `unknown` 的项**：宿主主 Agent／SubAgent／Skill／MCP 的 Token；cache **write** tokens；重试次数与每工具归因（per-call 的 session_id／turn_id／source 在 I6 实测**全空**）；本地 embedding 的 token／耗时／硬件成本；货币成本与跨会话累计。

**不得据此声称的节省比例**：优化对照运行（2 次（用量见本机账本））与基线中断运行（9 次（用量见本机账本））**不是同一任务集**，任何百分比都不成立。

### 6.4 宿主计量不可见时的确定性代理指标

| 代理指标 | 取数位置 |
| --- | --- |
| 已读页数／字节数 | `evidence/preparation.py:332-336` 的 `readPages`／`bytesRead`（**注意是工作字节，含重读**，见 P2-18） |
| 上下文摘要与清单摘要 | `preparation.py` 的 `contextDigest`／`coverage.inventoryDigest` |
| 主张／证据／关系／冲突条数 | `evidence/knowledge.py:213-217` 的 `COUNTS` 限额 |
| 投影复用与覆盖 | `evidence/projection.py:294-307` 的 `mapVersions`／`sourceVersions`／coverage 行数 |
| 候选变更条数 | `evidence/preview.py:80` 的 `1 <= len(candidate['changes']) <= 64` |
| 上传字节与语料摘要 | `learning_book/production.py` 的 `package.inputs`／`corpusDigest` |
| 归档字节上限 | `preparation_provenance.py:12` `MAX_BYTES = 4 * 1024 * 1024` |

### 6.5 §7.2 十二项候选裁决

| # | 候选 | 裁决 | 一句话依据 |
| --- | --- | --- | --- |
| 1 | 用量归因 | **适用，优先验证** | K 侧为空白，L 侧管道存在但 I6 产出为空；没有归因则后续所有节省结论不可证伪 |
| 2 | 确定性脚本 | **已有且应复用** | 摘录逐字绑定、hash／diff／判分／状态检查已成体系 |
| 3 | 固定管线 | **适用，优先验证** | K1→K2→K3→候选→adopt 的每步都已确定性化，可加断点恢复与中间产物落盘 |
| 4 | 渐进式披露 | **适用，优先验证** | 常驻规则最小化已是设计意图（`AGENTS.md` 只写规则），但执行层入口未按需暴露（P1-3） |
| 5 | 大结果落盘与短回执 | **已有且应复用**（但当前 context 内嵌全量原文） | 见 P2-19 |
| 6 | 会话生命周期与历史裁剪 | **条件适用** | 本机单用户、任务边界清晰；宿主压缩时机由用户自选 |
| 7 | SubAgent 隔离 | **已有且应复用** | 本次审查本身即验证：6 个隔离上下文、总用量仍 `unknown` |
| 8 | 缓存友好布局 | **适用，优先验证** | 已有命中率实测（54.72%）；需按真实命中率判断，不盲目增加缓存内容 |
| 9 | 有界检索 | **已有且应复用** | `read_limits`＋`LIMITS` 硬上限已实现；**但正文检索缺失**（P2-20） |
| 10 | 产物复用 | **已有且应复用** | 语料复用、投影复用、归档内容寻址均已实现（R1 即复用链修复） |
| 11 | 模型／推理／输出路由 | **条件适用** | K 侧已固定单 provider＋JSON schema＋`max_output_tokens: 8192`；语义裁决下沉小模型会**高风险**伤害证据链 |
| 12 | 条件性方案（语义缓存／LLMLingua／自动摘要／Batch／多 Agent 编排） | **不适用或后置** | 当前无对照实验证明净收益；方案 §7.2 第 12 项本身要求"只有在对照实验证明净收益时采用" |

**本轮未获授权也未实际执行的 A/B，结果一律为 `not_executed`。**

### 6.6 本次审查自身的用量（按 §7.1 记录）

| 类型 | 数值 |
| --- | --- |
| 宿主主 Agent cacheRead／未缓存输入／输出 | **`unknown`**（宿主不暴露计量，不记 0） |
| 业务 API 账本 | **本轮未调用任何业务模型 API**（0 次外发，非"零用量"而是"未使用"） |
| 本地模型 | 未使用（本机 Ollama 仅被动观测到 11434 在监听，未调用 API） |
| 可审计代理指标 | 主 Agent ＋ **6 个 SubAgent 角色**（5 个完成、1 个未在预算内完成）；主 Agent 深读 22＋ 个文件、运行 **1** 个探针（14 项组合验收，552.552 s）；上游对照使用仓库内 `references/upstream/` 6 个固定克隆；外部一手来源 **0**（1 次被 Cloudflare 拦截，未绕过） |
| 重试 | 无重试；1 个探针被并发资源争用拖慢，未重启 |

---

## 7. 网络研究与本地模型适用性矩阵

### 7.1 当前「用户整理一份网页资料」的真实路径

1. **搜索发现这一步根本不存在**：`tools/` 下 grep `search_engine|bing|google|duckduckgo|serp|search_result|search_api|def_search|web_search` → 零命中；唯一命中是 `host/codex.py:379` 把 `web_search` 设为 `'disabled'`。项目自带后端路径不但没有搜索，还**关闭**了搜索。
2. **没有通用网页抓取**：全仓真实出网只有 `host/wechat.py:36-58`（微信文章专用，逐跳校验 URL，白名单 `https://mp.weixin.qq.com/s/<id>`，保留原始字节）与 `host/model.py:150`（模型 API）。
3. **capture adapters 是纯离线**：`capture/adapters.py:16-20` 只注册 markdown／wechat／pdf；`capabilities()` 显式返回 `offline:True, used_ocr:False, used_model:False`。它处理的是**已经在本地的文件**。
4. **因此真实路径是：用户自己完成「找到 URL → 抓到本地 → 选对格式」三步，项目只从第 4 步（本地文件→资料包）开始。** wechat 路径可替用户省掉第 2 步，但仅限微信文章。
5. **宿主层能力 ≠ 当前可执行**：宿主 `web_search` 工具可用；`defuddle` **技能文件存在但 CLI 未安装**（`Get-Command defuddle` → ABSENT，技能自身写明需 `npm install -g defuddle`）；`ollama.exe` 已装且 11434 在监听（本轮只查 PATH 与端口，未调用 API，未深查已装模型清单）。

### 7.2 适用性裁决

| 候选 | 裁决 | 节省类型 | 关键判断 |
| --- | --- | --- | --- |
| 现有宿主网页提取 ＋ Defuddle | **适用，优先验证**（宿主层；项目内不复用） | 减少原始输入／输出 | 最短路径。**但** Defuddle **不保留原始字节**，与 `capture/adapters.py:239-240`"原件 sha256 ＋ 保留原始字节"的强绑定不同 → 必须包一层保存 raw HTML，否则违反"原始快照"要求；且**绝不可**改用云端版（URL 外发第三方） |
| Trafilatura | **不适用或后置** | — | 与 Defuddle 重复同类能力；且其一手文档本轮被 Cloudflare JS 挑战拦截，**能力细节未获一手证实**（不得绕过挑战） |
| Crawl4AI | **条件适用** | 减少原始输入／输出 | 浏览器栈运维成本高；`fit_markdown` 裁剪会破坏现有逐字复现契约；先用"用户手工保存"验证真实需求强度再评估 |
| Scrapy | **不适用或后置** | — | 项目内**不存在**批量、周期性站内任务，不为临时读几篇文章引入 |
| SearXNG | **适用，优先验证**（唯一能补"搜索发现"缺口的候选，但**应先用宿主搜索**） | 减少模型调用（少一次搜索轮） | 仍依赖上游搜索引擎，需评估质量、限流、**查询外发**与部署成本；查询外发是隐私决策项，交用户 |
| BGE Embedding／Reranker | **条件适用** | 减少原始输入／输出 | 先证明关键词、索引与结构化关系不足再增加向量检索。**当前真实根仅 43 文件，`bodySearch: False`，向量栈无消费者** |
| Ollama 本地生成模型 | **条件适用**（生成模型可用性未确认） | 转移为本地计算 | 本机 Ollama 已装且 11434 在监听，但本轮未执行 `ollama list`，不能声称只装了 embedding 模型；可用时承担整理分类、标签、候选去重、检索词、分段摘要、**带来源定位的资料卡**；**不裁决**证据支持、冲突、正式入库或授权；本地摘要**不得**进 `wiki/` 正文 |

### 7.3 资料卡字段对照（§7.3 要求的 11 项）

| 字段 | 现有载体 | 缺口 | 依据 |
| --- | :-: | :-: | --- |
| `sourceId` | ✅ `source_package.source_id` | 无 | `contracts/schemas.json:113-116`；`capture/adapters.py:245`（`AB631C3F5FF792D0`） |
| 规范 URL | ❌ 仅 `source.origin`（**原始** URL，未规范化／未去重） | **缺** | `schemas.json:137-140`；`host/wechat.py:19-27`（`8E24B61433DB21B7`） |
| 原始快照 | ✅ `originals[].path/sha256` ＋ 原始字节文件 | 无 | `capture/adapters.py:208-209,239-240` |
| 正文摘要 | ❌ 来源包层**无**摘要字段 | **缺**，且是"第二份真值"高危字段 | `schemas.json:104-172`（无 summary 键） |
| 抽取器及版本 | ✅ `parser.adapter_id/adapter_version/parser_version/config_digest` | 无 | `capture/adapters.py:253-254`；`capture/pdf.py:63-66`（`EED9642AE1848666`） |
| 完整／截断状态 | ✅ `quality.status`＋`quality.missing` | 无 | `capture/adapters.py:152-153,166-167,255-258` |
| 候选主张归属 | ❌ 来源包层**无**；claim↔evidence 绑定只存在于**知识包层** | **缺**（层级错位） | `evidence/knowledge.py:225-227,243`（`A6AA8C271FBE882F`） |
| 连续原文摘录 | ⚠️ **知识包层有**（`_excerpt` 强制逐字＝原文行拼接）；**来源包层无** | 来源包 `locators` 不含摘录正文 | `evidence/knowledge.py:23-30`；`capture/adapters.py:251-252` |
| 定位 | ✅ `locators[]{block_id, artifact_path, location}` | 粒度：markdown 逐行一 block | `capture/adapters.py:139,148-149` |
| 缺失信息 | ✅ `quality.missing[]`＋`source.unavailable_fields[]` | 无 | `capture/adapters.py:243,255-257`；`schemas.json:154-161` |
| `reviewRequired` | ❌ 来源包 schema **无**（`knowledge.py:404` 的 `reviewRequired:True` 属主张选择层） | **缺** | `evidence/knowledge.py:402-404` |

**统计：11 项中 5 项完整具备、1 项部分具备、1 项跨层具备但不在来源卡层、4 项无载体。**

**"本地摘要是否会变成第二份事实真值"**：**当前不会，因为根本没有摘要载体**；风险是**即将产生**。若新增资料卡，必须同时具备 ①`reviewRequired` 常开、②摘录逐字绑定、③locator 可回读、④摘要与原文分文件存放且摘要永不进 `wiki/` 正文 —— 否则会立刻产生第二份真值，且**在结构上无法被现有契约发现**（`source_package` 是 `additionalProperties: false`，新增摘要必须先改 schema，**这其实是好事：它强制显式决策**）。可直接复用的正面范式不必新发明：`evidence/knowledge.py:23-30` 的 `_excerpt`、`capture/adapters.py:305-318` 的 `validate_package`（抽取结果必须能由原件重算复现）、`evidence/preparation.py:315-317` 的 `semanticStatus: 'unreviewed'` ＋ `proposedRelation`（现成的"候选未审"标记）。

---

## 8. 推荐最小闭环、后续再做与明确不建议

### 8.1 后续可先做的小闭环（纯接线／口径／文档，不改架构，不新增依赖）

> 以下均为**后续实施建议**，不是本轮已执行动作。当前保持设计阶段，不修改代码、入口或规则文件。

| 序 | 设计动作 | 对应 finding | 预估成本 |
| --- | --- | --- | --- |
| 1 | `ENTRYPOINTS.md` 增 K／L 一行；根 `AGENTS.md` 按已确认设计增一行**纯指针**。当前 `WORKSHEET.md` 已有接收／续接命令，不重复补写 | P1-3 | 少量文档 |
| 2 | `HANDOFF.md` 包文件表增 `preparation/`；消费者提示词补按 refMap 找回依据并区分事实证据与学习者证据 | P2-08 | 1 段 |
| 3 | `integration_cli.py` 透出 `exc.code` ＋ 按码映射 `nextAction`（不保留路径） | P2-01 | 小 |
| 4 | 4 个 evidence CLI 把 argparse 错误统一为 JSON ＋ exit 3；补 K4 退出码契约 | P2-02 | 小 |
| 5 | K 侧保留模块级 `modelCalls: 0`，增加 `modelCallsScope`／`hostUsage`／`usageObservable` 和代理计数；`host/model.py` 采集仅解决 K 侧宿主用量 | P2-06 | 小 |
| 6 | 独立追踪 L 侧 `runtime_guard.begin()` 的生产调用方，填入真实 session／turn／source，不与 K 侧采集合并 | P2-21 | 待定位 |
| 7 | 补 `bytesRead` 的 `uniqueBytesRead`；把"本地 IO 工作量 ≠ Token ≠ 上下文大小"写入口径表 | P2-18 | 小 |
| 8 | `evidence/README.md` 记录 `_fields` 契约决定＋统一状态枚举表；`WORKSHEET.md` §4 消歧 `previous` | P2-04、P2-03、P3-13 | 1 段 |
| 9 | `PREPARATION.md:9` 改写；工作单补 `import-package` 命令映射与网络获取边界 | P2-10、P2-09、P2-11 | 3 段 |
| 10 | 相关状态文档与旧研究文档加当前入口／历史取代注记，不重写历史正文 | P2-14 | 少量文档 |
| 11 | 归档 schema 与 handoff 清单加快照属性；区分核心映射摘要与完整映射摘要 | P2-12、P2-13 | 小 |
| 12 | `evidence_store.py` 对未知 schemaVersion 显式拒绝并给明确消息；`enrollment.json` 留版本字段 | P2-17 | 小 |
| 13 | 只补 R1 的复用后重启／完整原回执缺失两条用例；R3 分类迁移引用现有独立复核 | P2-23 | 小 |

### 8.2 后续再做（方向已确认或仍需基线；当前均不实施）

1. **P1-1（正式准入薄适配）**：用户已选择开放“候选 → 当前维护 operation 输入”的薄适配，保留 Reviewer／Executor／既有门禁和用户 approve，不开放直接写库。
2. **P1-2（C2 硬门禁）**：用户已选择硬门禁。仅显式 `learn_before_commit` 任务要求同任务有效 I5 交接包；需设计 `taskId` 与 `learningHandoffRef` 绑定，不判断“学完”或“掌握”，普通任务不受影响。
3. **P1-3（公开入口）**：用户已允许根 `AGENTS.md` 增加一行纯指针；实际修改留待实施阶段。
4. **增量失效**（P2-22）：把失效判定细化为"已读页字节 ＋ 被选候选集合"两级。
5. **上下文瘦身**（P2-19）：未用于主张支撑的文档正文改为落盘＋引用。
6. **候选内正文检索**（P2-20）：先做关键词子串检索，**不引入向量栈**；并把 `bodySearch`／`wholeWikiExhausted` 写进任何"检索已覆盖"结论的必填限定语。
7. **资料卡**（P2-11）：做成 `source_package` 的**兄弟层**（独立 schema）；是否进入本仓契约及真实外发范围仍留待对应任务确认。
8. **文档归档与快照说明**（P2-15／P2-16）：设计定论为旧 ingest 链归档不删除、首轮评审保留标注；历史快照只补差异说明，不重新冻结。无需再次产品裁决。
9. **A/B 实验**（按 §7.4 固定任务集）：第一轮只做 B（确定性抓取＋抽取＋去重＋短回执），质量判据＝`_excerpt` 逐字一致率 ＋ locator 可回读率；计量来源＝P2-06 的 K 侧 usage ＋ P2-21 的 L 侧归因，分别验收。
10. **上游升级重建清单**（P3-09）：7 个上游文件 ＋ 8 个 wheel ＋ 84 包依赖锁。
11. **确定性脚本抽取器**：把纯搬运环节脚本化；保留独立语义审阅、来源取舍和实质扩范围认可。

### 8.3 明确不建议做

| # | 不建议 | 理由 |
| --- | --- | --- |
| 1 | **不重新选型 DeepTutor**，也不引入 OpenMAIC 作为第二后端 | **无决定性反证**。I6 失败项发生在**生成内容侧**而非 Book 路径本身；D1 预设的四条"会改变推荐的条件"已被真实启动、真实网页答题、真实重启恢复否定；"必须首期有书面答题原文及模型评分"是项目**主动不要求**的能力 |
| 2 | **不在项目内自建搜索引擎或爬虫框架** | 无消费者、与宿主能力重复、放大未审内容入库风险 |
| 3 | **不引入 Trafilatura** | 与 Defuddle 重复同类能力；一手文档本轮未获证实 |
| 4 | **不引入 Crawl4AI 自托管** | 浏览器栈运维成本高；`fit_markdown` 裁剪会破坏现有逐字复现契约 |
| 5 | **不引入 Kotaemon 检索栈或任何向量检索栈** | 出厂状态下重排**静默 no-op**，hybrid 实现是朴素拼接且去重疑似失效；本期明确不引入检索／重排／引用栈 |
| 6 | **不引入 open-notebook-mcp** | 它是"MCP 包装引入契约漂移"的反面教材（4 处静默失败），恰是本项目坚持自包 `Production` 的理由 |
| 7 | **不移植 DeepTutor `learning` 域** | 13,826 行 ＋ pydantic ＋ knowledge 闭包（numpy／faiss／llama-index）；本项目只需只读观察 ＋ unknown 保持 |
| 8 | **不删除 `tools/wiki_runtime/runtime/`** | 上游无对应物；删则正式 raw／wiki 写入失去可恢复凭据 |
| 9 | **不为 `evidence/` 补 JSON Schema** | `_fields` 封闭集合强度已不低于 JSON Schema；补 schema 净增一份需同步的真值 |
| 10 | **不把"独立审阅语义核对"自动化** | `WORKSHEET.md:17` 已明令：程序或准备者自己填 `accepted` 只能测试控制流，不能当独立语义验收 |
| 11 | **不为让 C2／C3"看起来闭环"而放宽 `formalWriteAuthorized` 或开启正式准入** | 保持 fail-closed 是本项目最可信的部分 |
| 12 | **不把 K4 错误输出改成回显原文／绝对路径** | 隐私边界保留；只应补**错误码**与 `nextAction` |
| 13 | **不把 `operator_supplied` 升格为人工认证语义** | 全部文档一致声明它不是真人同意、不是 G3 |
| 14 | **不使用"测试通过数"充当 R1–R4 的关闭凭据** | `knowledge-preparation-handoff.md:196` 自己已警告不得相加外推 |
| 15 | **不基于 I6 的两次运行计算任何节省百分比** | 非同一任务集，不构成 A/B |
| 16 | **不把缓存命中写成原始 Token 消失** | 现有实测 54.72% 属"降低计费或延迟"口径 |

---

## 9. 后续验证顺序

> 本表是后续实施阶段的验证设计，本轮不执行。

| 序 | 验证项 | 目的 | 前置 |
| --- | --- | --- | --- |
| 1 | 补 R1 的复用后重启／完整原回执缺失两条用例 | 闭合 P2-23 的剩余分支；R3 分类迁移引用现有独立复核 | 进入实施阶段 |
| 2 | 文档一致性测试（当前工作单命令清单 ↔ `argparse`；`ENTRYPOINTS.md`／`AGENTS.md` 指针 ↔ 实际入口） | 防止 P1-3 类断链复发 | §8.1 第 1–2 项落地 |
| 3 | K4 退出码与错误码矩阵测试（4 个 evidence CLI ＋ `learning_book` CLI） | 闭合 P2-01、P2-02 | §8.1 第 3–4 项 |
| 4 | 分别执行 K 侧 usage 采集与 L 侧归因落库的合成调用测试 | 分别闭合 P2-06、P2-21，为节省论证提供前提 | §8.1 第 5–6 项 |
| 5 | C2 的 `taskOrdering`、`taskId`、`learningHandoffRef` 三条组合用例 | 验证硬门禁、顺序变化新认可及非 C2 不受影响 | 已确认硬门禁；先完成字段与任务绑定设计 |
| 6 | 候选 → 维护 operation 输入的全链组合验收 | 闭合 P1-1 | 已确认开放薄适配；既有 Reviewer／Executor／approve 不变 |
| 7 | 真实资料的小规模受控全流程 | 验证本地组合验收之外的真实环境 | 另需具体资料的外发范围与费用授权 |
| 8 | 增量失效改造后的回归（新增无关文件 → 仅重做候选选择） | 闭合 P2-22 | 先确认保守失效与返工成本的实测基线 |
| 9 | A/B 第一轮（B 方案：确定性抓取＋抽取＋去重＋短回执） | 为 §7.4 提供首个有依据的净收益结论 | 第 4 项分别完成，另需安装／外发授权 |

---

## 10. 未验证项（不得当作已通过）

| # | 未验证内容 | 原因 | 最小补证方法 |
| --- | --- | --- | --- |
| 1 | **真实远端端到端**：真实 DeepTutor 后端、真实模型调用、真实课程发布、正式 raw／wiki 写入 | 方案禁止本轮启动真实服务与调用业务 API；组合验收使用替身 | 在已授权沙箱 deployment 执行受控流程，核对真实 POST 前重验 |
| 2 | **真实教学效果、真实宿主认证、真实用户试学** | 超出本次范围 | 需真实用户行为记录，不可用测试数量填补 |
| 3 | **真实网页抽取质量**（非微信站点） | 项目内无通用抓取路径；Defuddle CLI 未安装 | 另获安装与外发授权后对 1 个真实 URL 做 A/B，不绕过 Cloudflare |
| 4 | **Trafilatura 一手能力** | 文档访问被 Cloudflare 挑战拦截，本轮未绕过 | 读取官方仓库文档；本地安装验证另需授权 |
| 5 | **上游 v1.7.2 是否有指向 `60fb3bd…` 的 git tag** | 本地克隆为 `--no-tags` | 只读查询官方 GitHub tag ref 并记录 URL 与访问日期 |
| 6 | **宿主 Ollama 已装模型清单** | 本轮只查 PATH 与端口，未查询清单 | `ollama list`（只读）；在此之前生成模型可用性保持 unknown |
| 7 | **快照索引的逐文件实现版本** | 收尾已确认索引存在 `asOf: 2026-11-11`，原“是否记录冻结日期”已补证；但各条目没有独立 commit 字段 | 保留历史索引，另加当前差异说明；是否需要逐文件版本在实施前评估 |
| 8 | **`learning_book` 侧 `CHOICE_RULE` 与上游 `grading.py` 的语义差异** | 未深读相关实现 | 读对应代码及实际 handoff，确认 historicalBinding 与 unknown 边界 |
| 9 | **`docs/design/` 其他选型矛盾** | 本轮只核对主要文档关系 | 对当前文档检索推荐／选型／结论后人工判读 |
| 10 | **`state-dir` 是否已有实际升级路径** | 未完整检索第二处版本写入 | 全仓检索 `user_version`／`SCHEMA_VERSION` 后判断 |
| 11 | **实现与故障审查者角色未在预算内完成** | 该角色未交付 | 记 `evidence_insufficient`；后续连接修复另有 185 个不同检查的最终依据，但崩溃重启、并发写、恶意输入仍未由该独立角色复核 |
| 12 | **本次审查自身的主／子 Agent Token 用量** | 宿主不暴露计量 | 记 `unknown`；代理指标不冒充 Token 硬上限 |

---

## 11. 本轮交付、设计决策与边界

**交付物**

1. 本文件 `docs/design/knowledge-base-redesign-review.md`（新增并完成收尾校正）。
2. [审查方案](knowledge-base-redesign-review-plan.md)（既有，本轮收尾未修改）。

**本轮明确未做**：未修改任何业务实现、根 `AGENTS.md`、公开入口、`raw/`、`wiki/` 或运行配置；未启动真实服务；未调用业务模型 API；未生成课程；未提交或推送；未把任何 finding 自行标为“已关闭”；未自行接受限制。当前仍是**设计阶段**，§8–§9 均为后续建议，不是施工回执。

**用户已确认的三项设计决策**（仅记录，未实施）

| # | 已确认方向 | 实施边界 |
| --- | --- | --- |
| 1 | P1-1 开放正式维护的**薄转换适配** | 只把已审候选转换为现有维护 operation 输入；Reviewer、Executor、既有门禁和用户 approve 不变，不开放直接写库 |
| 2 | P1-2 的 C2 采用**硬门禁** | 仅显式 `learn_before_commit` 任务要求同任务有效 I5 交接包；需 `taskId`／`learningHandoffRef` 绑定，不判断“学完”或“掌握”，普通任务不受影响 |
| 3 | 允许根 `AGENTS.md` 增加一行知识准备工作单的**纯指针** | 不复制规则正文；实际修改留待实施阶段 |

**仍需按具体任务另行确认的事项**：真实资料与查询的外发范围、费用、Defuddle 或其他工具的安装、资料卡是否进入本仓契约，以及任何真实正式写入。旧文档归档不删除、历史快照只补差异说明不再列为产品待决项。

**后续文档登记建议**：实施入口修复时，在 `docs/design/README.md` 当前结论中增加本报告链接；K／L 行应加入实际的 `tools/wiki_runtime/ENTRYPOINTS.md`，不是误写成本 README 的表格。当前设计阶段未执行这些登记或入口修改。

---

## 12. 收尾复核与校正记录

1. **数量与原始证据**：P2 实际为 23 条；16 份课程源快照中有 6 份现行原文与索引 hash 不同，遗漏的 `01-architecture-proposal.md` 已补入 P2-16。索引本身已有 `asOf`，故删除“无版本标记”的错误表述。
2. **后续证据状态**：当前 `WORKSHEET.md`（`F523F9A99A43564D`）§7 已补接收／续接命令；当前 handoff（`E0D6D477916ABB55`）已指向连接修复验收及 185 个不同检查的最终依据。P1-3、P2-07、P2-14、P2-23 已按这些新证据改为部分修复或缩小剩余范围，原始发现保留作历史对照。
3. **口径修正**：模块级 `modelCalls: 0` 是真实值，不再建议改为 null；K 侧宿主用量与 L 侧 session／turn／source 归因拆开处理。Ollama 生成模型可用性改为 unknown，不再声称只安装 embedding。
4. **验证建议修正**：关键词子串检索不再承诺同义词命中；R1 的原输入文件缺失不再外推为重启或完整原回执缺失；实现审查缺口记 `evidence_insufficient`，不由审查者自行接受。
5. **设计阶段边界**：本次收尾只修改本审查报告，未实施 P1-1／P1-2／P1-3，未修改归档、快照、规则或入口文档，未运行新的应用测试。报告中的“已修复待验”均引用后续已有证据，不表示本次收尾进行了实现或验收。
