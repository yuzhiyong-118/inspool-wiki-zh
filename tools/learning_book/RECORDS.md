# 作答记录与基线关联（I5-B）

`records.py` 提供纯函数 `project_records(...)` 和只读应用方法 `LearningRecords.observe_records(...)`。上游仍独占 progress 的写入；本模块不回放答案、不补同步、不生成题目，不计算掌握度。当前输出是进度观察证据，**不是完整 `learning-handoff/1` 包**。

## 调用与职责

```python
from tools.learning_book.contracts import load_deployment
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.evidence_store import EvidenceStore
from tools.learning_book.records import LearningRecords

backend = DeepTutor(load_deployment("deployment.local.json"))
reader = LearningRecords(EvidenceStore(".learning-book-state"), backend)
result = reader.observe_records("实际activityId")
```

配置需有 I4 content 与 I5-A learning-state 的独立构建身份，见 [部署样例](examples/deployment-i5.json)。无 Budget／模型配置也可读取；服务需由操作者另行提供。`snapshot_id` 省略时只采用实际首次绑定，没有绑定仍保留原记录；显式候选只作条件比较，不替换既有基线。

每次调用创建新的 `record-observations/<随机目录>`。保存两份原始 learning-state 响应、窗口两端的内容／资源读取证据、当次检查与 `records.json`；返回 state 相对 `artifactRef`。不占生产请求／reservation，不提供历史成功 ID 复用来代替本次读取。中断目录只是内部读取尝试；当前没有 I5-D 的不可变交接包发布／恢复协议。

一次调用只读一轮，无重试：I3 context／实际绑定审查链 → 内容与资源开始边界 → 两次进度／页边映射 → 内容与资源结束边界 → 再核绑定证据。比较完整 JSON（含 bool 与 int 的区别）、当前内容／资源／来源摘要及绑定证据字节。数量和 updated_at 相同不能遮掉原值变化。无法读完整内容仍可保留实际取得的作答，绑定 unknown，报告 partial。

I5-D 应复用以下小接口，把会话读取放入统一窗口并统一计数，不能套本操作再叠加三层重试：

- `Baseline.learning_context(activity_id)`：既有 I3 映射／未决生产／语料证据门禁。
- `Baseline.read_content_once(directory, number, context)`：一次观察，无隐含重试。
- `Baseline.evaluate_content_observations(...)`：I4 一致性判定，无 HTTP。
- `Baseline.load_learning_evidence(...)`：校验实际 binding、完整 snapshot、capture request、review request／摘要／质量门禁及已存在的回执。I4 绑定已提交而回执因崩溃缺失时保留绑定事实；坏审查不因一个 pass 字段通过。
- `project_records(...)`：输入已保存的公开字节及已核验基线／本次检查，纯投影，不代替应用层 scope 和证据校验。

## 原值、身份和判分

非空合法 submission_id 的 key 是版本化结构化数组 `(deploymentId, ownerId, workspaceId, bookId, submission_id)` 的 canonical SHA，同时保留各组成字段。完全相同 payload 可以合并展示，但每个 rawRef／SHA／JSON pointer／数组位置仍保留；相同 key 对应不同原值则保留各变体，标 identity_conflict，不选最后一条覆盖。

缺／空 submission_id 使用本次观察内的原始位置定位。两份响应里的相同旧记录仍可能是同一事实或多个事实，所以不跨响应／导出去重、不声称 logicalAttemptCount。坏成员不删除；字段缺失与 null 分开。score、weak_chapters、访问位置原样作为 upstreamSummaries，不推导完成或理解率。

choice 复核复用 I4 `supports_choice` 和支持题目清单，且 page/block/question 唯一。`choice-key/1` 精确比较实际选项键；不转换大小写、文本、多答案或补空答案。派生判断放在 comparisonToBaseline，原 is_correct 不改；不同则保留 disagreement。

明确 null 是 ungraded。历史题型可关联时，choice 的 bool 是 client_reported；已知 written／short_answer／fill_blank 的 self:correct／self:incorrect 是 user_self_report，不能伪造书面答案或模型评分。缺 verdict／题型未知或历史关联不明时 method unknown，仍保留原客户端报告来源。没有观测到原 HTTP 同步错误，assessmentSync 始终 unknown。

## 时间假设与承诺范围

默认没有足够的服务器时钟精度／偏差证据，历史绑定保持 unknown。操作者可传明确的协作假设，不额外弹批准窗口：

```python
clock = {
    "schema": "learning-clock-assumption/1", "kind": "same_local_clock",
    "actorId": "实际声明人", "statement": "实际的同机时钟、偏差和精度依据",
    "maxSkewSeconds": 1, "timestampResolutionSeconds": 0.001,
}
result = reader.observe_records("实际activityId", clock_assumption=clock)
```

这是一项操作者声明，不是服务端认证。偏差和分辨率必须有限；整数时间至少留一秒不确定性，浮点时间至少保留其表示精度。记录最早可能时间须严格晚于 capturedAt 和首次 boundAt 的精度区间；最晚可能时间不能晚于实际采集观察。缺时间、异常／未来时间、边界不确定、回顾性基线、当前漂移、来源不可用或冲突均 unknown。

即使全部门禁通过，也最多 `baseline_consistent/cooperative`，`submissionContent=unknown`；条件复核不证明当时实际显示的版本，ABA、提示影响、独立作答和掌握度仍未证明。当前未读取教学会话，assistance 始终 unknown。

这里的 B 方法仍只观察进度，原阶段验收见 I5-B（未随公开仓库附带）。完整公开会话、全窗口限额／重试、可搬运包及 CLI 已在 I5-C～E 完成，入口为 [HANDOFF](HANDOFF.md)和 最终验收（未随公开仓库附带）；下一步 I6 做已安装服务的真实集成。
这里的 B 方法仍只观察进度，原阶段验收见 I5-B（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/i5-b/README.md）。完整公开会话、全窗口限额／重试、可搬运包及 CLI 已在 I5-C～E 完成，入口为 [HANDOFF](HANDOFF.md)和 最终验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）；下一步 I6 做已安装服务的真实集成。
