# Q2 本地题目发行能力

固定 DeepTutor 提交仍为 `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`，继承 I4、I5、I6 和 closeout。新增能力为 `learning-question-publication/1`；协议 `/1`、`/2` 表示持久化协议版本。

## 构建与接入

1. `prepare.py --source <已核对的 closeout site-packages> --output <全新目录>`：核对 manifest 中前置及继承文件，复制模块并应用增量补丁。输出目录必须不存在；不修改源模块或运行数据。
2. `build_wheels.py --source <上述目录> --output <另一个全新目录> --wheel <固定 wheel> ...`：八个不重叠输入，派生本机 wheel、重算 RECORD，并独立解包到 site。`release.json` 留存输入／输出摘要及所有业务文件。books 输入固定摘要见 manifest；其他输入也在发行回执中逐个记录。
3. 部署配置显式增加 `questionProductionBuild`，字段为 `capability`、`baseCommit`、`patchSha256`、`moduleSha256`。后两项来自本目录 patch 和实际安装的 `deeptutor/book/question_publication.py`，不从名称推测。
4. 复用 `tools.learning_book.local_install` 接入完整八模块；它核对新补丁、继承的计量／生成／只读模块及项目接线代码。Runtime 启动再次核对。服务仍为本机单 worker；共享书不开放此新增写能力。
5. 复用既有停服备份／恢复，将 runtime、state、control 一起搬运。新安装须重新绑定路径与进程，保留原账本与预算 floor，不直接运行旧配置。项目代码不在数据备份中，恢复时须使用摘要一致的项目 checkout；不一致会拒绝启动。

`build_patch.py` 是维护者从已核对输入重新生成增量补丁的工具，日常安装不用执行。上一次 closeout wheel 与已安装源码存在三个文件差异：生成状态 overview、generation 的 previousOperationId／retryOf 区分、router 的换行与暂停动作名。manifest 明列 wheel 基线摘要；本轮保留 closeout manifest 验证过的生命周期修订，并同时接受 pause/resume 及 pause_book/resume_book。历史 closeout manifest 不重写。

## 发布与变式

- `POST /api/books/publish-quiz`：严格窄请求，经原书编辑权限解析；定稿直接写入，模型调用为零。
- `POST /api/books/regenerate-block` 携带有效 `question_binding`、`request_id`、`request_digest`：进入受管变式分支；仅接受原六字段确定性模板，不走旧的原地生成分支。QuizGenerator、QuestionPipeline、提示构造、格式修复仍是上游实际路径。
- `GET /api/books/{book_id}/question-capability`：原编辑授权下核对实现文件摘要和支持协议。缺能力在项目发送 POST 前失败。
- `GET /api/books/quiz-publications/{request_id}?book_id=...`：同作用域、同编辑权限下只读核对精确提交，不凭书列表认领成功。

每个题块只允许首次受管绑定。多个未绑定题块可在学习和 I4 前逐个发布；已绑定题目改题需替代活动。该保守限制避免为草稿再建一套可变题目历史。原生内容编辑／删除保持关闭；原生答题、progress、learning captures 及仅更新聊天会话映射／时间戳仍可运行。旧无规格课程保留原行为；其既有 I4 绑定由项目 state 门禁保护，不臆造远端历史标记。

规格讲义必须对应目标页 text 块，按规划顺序取 body（缺 body 时 content），以两个换行连接后核对 UTF-8 字节摘要。新范围不含共享书、短答题、任意新增块或整书 finalize。

## journal 与不确定状态

定稿同步执行：验证 → prepared journal → page → book → 核验 → applied。journal 留存前后摘要、after-image 和响应。进程退出后，只有精确符合协议前后状态才补齐；额外修改进入 uncertain，不覆盖。不将单文件原子写夸大为数据库事务或任意断电保证。

变式在内存中的页／块副本生成，持久 `generating` reservation 阻止竞争内容写入和稳定采集。结构成功才经同一 journal 发布；格式失败不改持久页。中断的 generating 不重放模型，重启后保持不确定，只阻断相关书；其他书可以启动。返回 503／丢失响应不能改成明确无副作用失败。提交后发 block_ready 通知；通知可重复或丢失，成功事实以 journal 回读为准。

项目请求已 dispatch 而无完整响应时只 reconcile。GET 回读另存 book-reconcile 阶段，明确不是原 POST 响应；核对原 requestDigest 后才能恢复成功，随后重放本地请求不会再次 POST。

变式用量归入 `book:prepare_question_variant`，session 为 book ID，turn 为生产 request ID；沿用 RuntimeGuard 和原累计账本。两轮 quiz loop 不是“两次调用”：还有 forced finish、格式修复、推理空输出重试及提供方行为，须按实际底层调用计量。测试中假 SDK 的用量（见本机账本） 是合成计量，不是真实业务用量。

限定验收和命令见Q2 验收（未随公开仓库附带）。
限定验收和命令见Q2 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q2/README.md）。
