# 准备并发布课程题目

本页对应 Q2 本机、自有课程能力。旧课不会自动迁移。发布成功只表示生产操作成功；首次 I4 还需实际最终题目审查及整书就绪。

Q3发现的工具范围、KB健康读写冲突和流式状态／缺计量门禁现已修复并限定复审（未随公开仓库附带）。新安装或升级应使用[修复补丁](../../patches/deeptutor/q3-fix/README.md)，核对实际补丁／模块指纹和完整安装文件；旧Q2接口成功不证明修复已生效。本轮没有升级日常实例，下一次模型调用前仍须接续Q3隔离新增用量（见本机账本）。

## 准备附件

在独立允许根下保存规格、讲义、来源原文快照和审查 JSON。规格使用[Q1 样例](examples/questions/README.md)及 `learning-question-spec/1`；新增描述符使用 [Schema](schemas/question-preparation.schema.json)：

```json
{
  "schema": "learning-question-preparation/1",
  "root": "E:/course-work/question-preparation",
  "specPath": "spec.json",
  "specDigest": "<用 spec_digest 计算，含定稿选项显示顺序>",
  "lessonPath": "lesson.md",
  "sourceInputs": [
    {"sourceId": "source-1", "sourceVersionId": "source-1@1", "path": "source.md"}
  ],
  "reviewPath": "production-review.json"
}
```

这是路径配置示意，摘要占位符不可直接执行。成员必须是根内无重定向的相对路径，sourceId/version/hash 必须属于此活动实际冻结的语料。讲义必须等于目标页 text 块正文按规划顺序以两个换行连接的字节；更换正文会使旧绑定失败。

生产前审查使用 [review Schema](schemas/question-preparation-review.schema.json)：明确 reviewedBy、reviewId、specDigest、模式和逐题理由。定稿的 contentDigest 用 `question_spec.question_digest`；变式先用 `render_variant_template` 核对原文、渲染实际六字段，再用 `contracts.digest` 计算模板摘要。准备者实际审阅后才能写 `decision=reviewed_for_production`，不预填虚假的通过结论。

同一个规格只允许一种模式；初期 1～8 道 A–D 单选题。描述符和各 JSON 有界读取，未知字段拒绝。归档的来源／讲义是本地附件，不因此发送到模型。现有 K 接线仍须另外提供 `--knowledge-preparation` 及有效 publish-quiz／prepare-quiz 步骤审查；新附件不替代学习约定或 K 门禁。

## 执行命令

```powershell
python -m tools.learning_book.cli publish-quiz --activity <活动ID> --request-id <新请求ID> --deployment <部署JSON> --state-dir <项目state> --page-id <页ID> --block-id <quiz块ID> --expected-revision <当前revision> --question-preparation <描述符JSON> --budget-context <当前预算JSON>
```

定稿路径不调用模型，也不经过 mimic 重写。题目、选项显示顺序、答案、解释都须原样回读。request ID 仅支持字母、数字、下划线和短横线；相同 ID 改内容是冲突，不能作为重试。

变式改用 `prepare-quiz`，同样提供 `--question-preparation`；这时不同时提供旧 `--templates`。来源、目标、场景条件和允许改写范围确定性编入 reference_question，发送前再次核验。模型生成仍可能偏题，不能把模板的答案字母直接套在新选项上。

丢失响应时：

```powershell
python -m tools.learning_book.cli reconcile --request-id <原请求ID> --deployment <同部署JSON> --state-dir <同项目state>
```

不自动补发 POST。查不到精确提交或服务报告不稳定时保持 uncertain；停止重复生成，检查原回执及 journal。原始未发送的 prepared 请求可携带有效描述符和预算续发；已 dispatch 的生成请求不重新运行。

## 学习接受和交接

含题目绑定的快照为 `learning-content-snapshot/2`，包含不可缺少的 questions.json。最终 I4 审查在原 questionChecks 之外还需 questionProductionChecks：每题明确 pageId、blockId、questionId、specDigest、questionDigest、targetObjectiveId，检查来源忠实、目标命中、答案唯一、解析正确，并写具体理由。字面无错、结构通过或 block ready 都不替代这些判断。

新 I5 包为 `learning-handoff/2`，携带可离线核对的来源／讲义快照、规格、生产审查和最终题目附件。含受控扩展时使用 `learning-handoff/3`，另带有序提交、前驱、前后受保护摘要及逐题未审状态。删附件、篡改或试图降级旧协议均拒绝；旧 /1、/2 快照／包仍按旧边界读取。离线校验不证明外部来源真实性、教学效果或用户掌握程度。

本轮发布后题块不可原地修订；需要纠错就创建替代活动，保留旧课与原作答。尚未绑定的其他 quiz 可在学习和首次 I4 之前继续受管发布。完整新课从正文准备到首次 I4 仍依赖 E1；Q2 的隔离就绪夹具验收不能替代它。

### 基线后的受控扩展（候选）

`release-14` 允许在原课程上**追加**未审讲解和新题，与“原地修改旧题”不同。使用 `append-extension`，同时提供知识准备和原题附件；新块、新 question ID 和新提交序号必须独立，旧题、选项顺序、旧作答及首次基线不改写。追加新题按唯一引入提交及所属扩展内容关联，后续快照只验证不变，明确 `extension_consistent／unreviewed`，不继承首题正式审查结论。详细操作见 [本机使用手册](LOCAL_USE.md#受控学习扩展release-21-机制)和[补丁说明](../../patches/deeptutor/controlled-extension/README.md)。候选尚未部署到日常，合成验收不等于真实教学质量通过。
