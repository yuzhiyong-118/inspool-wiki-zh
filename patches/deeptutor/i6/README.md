# I6 固定上游补丁

固定提交 60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db，版本 1.7.2。安装核对见 [最终清单](manifest.json)，实际运行见 I6 验收（未随公开仓库附带）。这些是本机补丁发行物。

## 补丁顺序

先用 [I5 准备脚本](../i5/prepare.py)从固定原始源码创建独立、尚不存在的构建目录，该步骤会继承 I4 和 I5 的两个只读接口。随后按 manifest.json 的顺序应用本目录四份补丁。

| 补丁 | 所属模块 | 实际作用 |
| --- | --- | --- |
| quiz-legacy-session.patch | books | 缺少旧 chat_session_id 时使用已有无会话路径，修复原生首次答题保存后返回 500。 |
| upload-task-identity.patch | knowledge | 单文件及批量上传把进度任务 ID 传入既有 RAGService，避免上传回执与持久索引分离。 |
| prepared-quiz.patch | books、questions | 为已审校题目复用 QuestionPipeline 的 templates_override／mimic 流程，限定工具和循环，保存原生题型与结果。普通调用保持原默认选项。 |
| editorial-bridge.patch | books | 手动编辑正文时清理失效的模型过渡句，标题单独编辑保留过渡句。 |

为独立构建目录设置 GIT_CEILING_DIRECTORIES 为其父目录，先 git apply --check --ignore-space-change，再应用。用清单中的 finalSourceLfSha256 核对实际修改文件。构建时设置 PIP_NO_INDEX=1，用上游 scripts/build_modules.py 构建 books、questions、knowledge，其他五个模块使用原固定 wheel。

实际安装的八个 wheel 业务文件共 1,109 个，逐文件核对已通过。新安装应以实际 wheel SHA256 更新部署配置及记录，保留本次历史清单。前端为同提交生产 standalone，构建标识见 I6 部署记录。

## 预审题目输入

通过原生 regenerate-block 的 params_override 提供 num_questions、question_type 和 prepared_templates。当前预审路径支持 choice，列表数量须与实际 num_questions 一致，question_id 唯一。每行明确包含 question_id、topic、question_type、difficulty、reference_question、reference_answer，值为非空字符串，单字段最高 32,768 字符。

topic 放本次准备者已核对的有限来源正文。reference_question 和 reference_answer 是参考题与答案，上游 mimic 模式会据其生成同类新题。生成后仍须核对题干、选项与解释，实际输出不保证逐字复制模板。元数据 prepared_templates=true 标识使用该路径。

该路径不重复执行 Explore 和 Plan，不附 KB 做全库探索，通过既有 builtin_whitelist 收紧自动工具并保留工作区基础工具，每题最多两轮。实际单题及过渡文为 2 次调用（用量见本机账本），详见 token 审计（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/token-audit.md）。

## 回归入口

使用实际安装这组三个补丁 wheel 的隔离 Python 执行，无需模型。

```powershell
python -B patches/deeptutor/i6/test_prepared_quiz.py -q
python -B patches/deeptutor/i6/test_editorial_bridge.py -q
python -B patches/deeptutor/i6/test_upload_task_identity.py -q
python -B patches/deeptutor/i6/test_quiz_legacy_session.py --scratch <独立临时目录> --expected-first-status 200
```

前三个脚本共六项测试，最后一个启动独立临时 HTTP 服务并验证原生首次作答。I3 的 recover-inputs 属于本项目显式恢复操作，其两项回归在 test_learning_book_i3.py，保留原上传并记录独立索引重建响应。
