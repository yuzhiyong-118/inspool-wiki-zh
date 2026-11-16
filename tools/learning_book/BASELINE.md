# I4 内容基线：采集、审查、复核

状态：应用实现与本地／HTTP 契约验收通过；证据与未覆盖项（未随公开仓库附带）。没有自动编译／补题，也没有把新补丁安装到既有真实服务。产品仅用标准库，不 import DeepTutor、私有探针或测试夹具。

## 调用

复用同一个 `EvidenceStore`、`DeepTutor` 配置及 I3 成功的 activity/corpus 映射，构造 `Baseline(store, backend)`。方法为 `capture_baseline`、`check_baseline`、`record_baseline_review`；三个 CLI 共用这些方法。仅 GET，无需模型配置或预算。

给原部署配置**增加** `contentReadBuild`，保持既有 deployment/owner/workspace/URL 不变；该字段不参与 I3 scope digest。格式见 [deployment-i4.json](examples/deployment-i4.json)，构建身份取实际 [补丁发行物](../../patches/deeptutor/README.md)。配置样例中的 hash 对应本轮构建，重新构建须改为新 wheel 的真实 hash。不存在新接口／缺契约时停止，绝不回退普通 GET Book。

pre_learning 需要准备者提交 `declaration.json`，例如：

```json
{"actorId":"实际准备者ID","statement":"已协作暂停内容编辑和生成，开始学习前采集。"}
```

```powershell
python -B -m tools.learning_book.cli capture-baseline --activity activity-001 --capture-id capture-001 --snapshot-id snapshot-001 --purpose pre_learning --declaration declaration.json --deployment deployment.local.json --state-dir .learning-book-state
python -B -m tools.learning_book.cli review-baseline --activity activity-001 --snapshot-id snapshot-001 --review-id review-001 --review-file review.json --deployment deployment.local.json --state-dir .learning-book-state
python -B -m tools.learning_book.cli check-baseline --activity activity-001 --snapshot-id snapshot-001 --check-id check-001 --deployment deployment.local.json --state-dir .learning-book-state
```

retrospective 不传冻结声明。每个 ID 固定语义输入；重复已完成操作返回历史结果，**不是重新核对当前状态**。要再次检查使用新 checkId，失败采集重试使用新 captureId；进程中断、尚无 result 的相同 captureId 会重新完整读取，已发布包则原样恢复回执。不同输入复用 ID 或覆盖 snapshotId 会 conflict。

成功／诊断回执的 `receiptRef`、`artifactRef` 相对于 state-dir，外部 Agent 可直接定位结果和快照 manifest，无需自行计算目录摘要。采集时间记录到微秒，但机器时钟精度／跨端一致性仍未证明；I5 不得把时间先后自动升级为提交时内容证明。

## 投影与包

规则 `dt-book-content/1` 保存完整 book/spine/pages/blocks/payload/params/anchors/语义 metadata，不摘取成纯正文。未知模型扩展保留；未知响应扩展保留且覆盖 partial。canonical JSON 会排序对象键，所以另存每道题实际 `optionDisplayOrders`，保留选项显示顺序。

精确排除位置如下，**不递归删除同名 payload／metadata 字段**：

| 位置 | 排除字段／单独观测 |
| --- | --- |
| book | created_at、updated_at、revision、status、error、stale_detected_at、chat_session_id、source、permission、can_edit、can_delete |
| book.metadata | page_chat_sessions、compile_started_at |
| spine | updated_at、version |
| page、block | created_at、updated_at、status、error |
| response 顶层 | progress、reading 不入正文；generation、pageEnumeration 单独观测；未知字段保留且 partial |

连续两轮分别核对 scope、原文／冻结输入、远端语料成员及原始字节／索引任务与 usableVersion，再读新 content 接口与资源。比较内容、资源、来源映射、revision、实际状态；不一致最多再做两对，总计至多六次整书读取。失败／不一致保留原响应与诊断，不能用前一次单读凑新的一对。

```text
state-dir/
  captures/<ID摘要>/request.json、a/<尝试>/rN/、result.json
  snapshots/<ID摘要>/content.json、resources.json、sources.json、capture.json
                    raw/、assets/、manifest.json、complete.json
  checks/<ID摘要>/request.json、a/、result.json
  reviews/<ID摘要>/request.json、a/、result.json
  baselines/<activity摘要>.json
```

写者锁与 I3 共用；读操作不进入生产请求状态机、不保留远端写入 reservation。包在同卷 staging 中写完、逐文件重验，完成标记最后写，整个目录再发布；没有完成标记不能读为成功。无独立 I4 索引真值，定位使用操作回执／不可变 manifest。遗留 staging／尝试是故障证据，不自动清理。

`captureStatus`、`structuralCheck`、`qualityReview` 分开：稳定读完的内容也可能包含失败题。包完整不代表教学审查通过。

## 资源与审查

按固定 renderer 识别 text、section、quiz、deep_dive、user_note 的 Markdown 图片和引用式图片、概览图的已知依赖；callout 是纯文本。代码只保存，不执行。复杂／含歧义 Markdown、动态图依赖、HTML、figure、音视频及未知块保守 partial，不承诺完整 CommonMark／脚本资源闭包。普通引用链接不抓取，代码示例里的图片文本不下载。

只下载同部署 `/files/outputs/` 下的 png/jpeg/gif/webp，必须是具名 Book workspace；General 原路由可能回退 partner，资源归属未知时不下载、标 partial。拒绝外站、越界、多重编码、query/fragment、主动内容及重定向。每轮读取实际字节，核对 MIME／位图签名、长度和 hash；最多 64 个资源、每份 8 MiB／合计 32 MiB。内容包是证据，不是离线播放器；Web 基础依赖以固定 renderer commit 标识。

审查文件结构见 合成测试样例（未随公开仓库附带）。实际准备者必须核对固定快照与原文后填写，不能将样例中的 pass 当真实审查。至少包含 actor/角色、activity/snapshot/三个摘要、sourceFidelityChecked、来源身份/hash/位置/核对声明、每道 supported choice 的语义核对和来源证据、findings、unsupportedAcknowledged、decision。

选择题只接受明确 choice、非空题干、至少两个非空选项及精确答案键、可唯一定位的 `(pageId,blockId,questionId)`；不模糊转换答案。其他题型保留为 unsupported。Generation failed、无效题／空内容／错误状态阻断。审查不能越过这些确定性门禁，来源忠实性也不能由 hash 或 READY 自动证明。

审查操作重新成对读取；所有门禁通过时直接绑定首次基线，无重复确认弹窗。首个 D3 闭环至少一道有效 choice。首次绑定不可替换；新候选不能遮盖旧基线漂移。绑定后崩溃仍保留已提交绑定，即使恢复时当前内容已变，也分别报告历史 `baselineBound` 和当前 `gatePassed`。这些记录不触发正式 ingest／approve。

一致时最多输出 `baseline_consistent / cooperative / submissionContent=unknown`。ABA、另一客户端所见内容、提交时版本、掌握度均未证明；缺来源与内容是否一致分别表达。I5 仍须实现无生成副作用的 progress／会话读取、时间／身份和题目对齐，不能回退普通 GET Book。

存在受控扩展时，当前读取额外包含 `extension.bin` 原始证据，并纳入两次读取的 boundaryDigest。`check-baseline` 从首次快照按内容序号和前驱有界重放，全部合法扩展与当前受保护内容一致时输出 `extension_consistent`；旧题仍按首次基线关联，新题按所属扩展及显式未审状态关联。普通 GET 只检查未决提交和读取窗口，不冒充完整重放。缺失、分叉、篡改、未授权删除或无法解释的差异继续 `unknown`，不能靠忽略新增字段或笔记类型放行。当前全链上限为 1,024 次提交、32 MiB 证据；超出明确诊断。候选尚未部署到日常，真实教学审查仍由准备者另行完成。

```powershell
python -B -m tools.tests.run_learning_book_i4 --output <新验收目录>
python -B -m tools.tests.run_learning_book_i3 --output <新验收目录>/i3-regression
```
