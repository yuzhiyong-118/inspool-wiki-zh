# E1 作者正文与整书交付补丁

固定上游仍为 `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`。本目录在已验 Q3 `release-04` 上增加作者交付能力，不改写 Q2／Q3 历史发行物。补丁身份为 `learning-authored-delivery/1`，能力标识为 `learning-authored-delivery/1`。

## 范围

- `deeptutor/book/author_delivery.py`：只允许 `text` 正文插入／修改和整书完成。请求携带稳定 ID、语义摘要、作者绑定、revision 和整书页块计划。
- 正文不调用模型。每次写入保存 before／after Book、Page、响应及摘要的同步 journal；重复请求读取原结果，未知结果按原 ID 查询，不换 ID 重发。
- 整书完成逐项核对实际页块、payload 摘要、ready 状态、整书 worker／in_flight／页面 generation、学习进度和 revision。目录计划与提交端都使用严格页面枚举，并核对 spine、manifest 页数、唯一 ID、章节归属及页面引用；每个交付章节必须至少有一个页面。
- `confirm_spine` 的 manifest 章数与页数都包含自动概览章，首次注入、重复确认和目录编辑保持同一语义。
- 教学内容按块类型逐块检查实际字段，不能由同页其他有效块掩盖缺内容块。`text` 按前端 `body ?? content` 的空值选择规则读取实际渲染字段；`format`、URL 和元数据不能代替正文。仅明确的导航／结构块可豁免内容字段，且每页仍须有实际教学内容，未知类型明确拒绝。
- 作者 journal 接入现有 `question_publication.storage_barrier`。不稳定事务在显式恢复前阻止普通存储读取和原生写入；恢复只按原 requestId 与 before／after 摘要进行，疑似额外编辑拒绝。
- `deeptutor/book/engine.py` 在单页任务和整书 worker 登记点与作者提交共用协调锁，防止状态检查到提交之间穿插启动生成；完成接口不停止 worker，也不启动生成。
- `POST /api/books/author-block`、`POST /api/books/complete-authored-book`、`GET /api/books/author-deliveries/{request_id}?book_id=...` 及能力 GET 是仅有的新增路由。没有开放通用 HTTP 方法、任意 block payload 或文件编辑。
- 项目 `Production` 继续负责知识准备、实际步骤审阅、来源冻结、预算、请求证据、I4／I5 和替代 activity/book。首次基线后的修改使用 `replacementOf`，不重绑旧答案。

## 构建

```powershell
$python = '.learning-validation/deeptutor-60fb3bd/closeout/venv/Scripts/python.exe'
$env:PYTHONPATH = $PWD
& $python -X utf8 -B patches/deeptutor/e1-authored-delivery/prepare_release.py `
  --base-release .learning-validation/learning-question-q3-fix/release-04 `
  --output <尚不存在的独立输出目录>
```

脚本核验父发行回执和 1,111 个业务文件，替换四个固定文件，重新生成八个 wheel 的 RECORD 和独立 site。最终发行包含 1,112 个业务文件。不会安装到既有解释器、访问网络或调用模型。

`manifest.json` 固定四个变更文件、目标 wheel 和父链；`patchSha256` 是父发行 ID 与文件前后的确定性摘要。`local_install.verify_question_install` 只在整个固定 E1 文件集符合当前字节时接受此后代，混装、缺模块或旧继承文件仍拒绝。

## 验证边界

真实 Production／CLI／loopback HTTP／BookEngine／BookStorage 覆盖正文写入、整书完成、I4、I5、重复／并发、旧 revision、缺审、运行中、缺内容、来源变化、已认可替代和 journal 恢复。R1–R5 修订增加严格目录与正常多页、空正文、整书 worker、四边界真实进程退出、普通 GET／原生写入屏障、额外编辑和生成登记协调检查。F1–F3 续接真实 confirm_spine 首次／重复／编辑、多章及删除章节、渲染字段冲突、逐块内容门禁、空章和重复归属。模型提案／目录和 KB 索引只使用合成固定设置，未验证真实供应商、认证、索引生成、教学质量或用户试学。E1 不自动切入日常实例。

原始交付证据见 `docs/design/evidence/learning-system-next-delivery/batch-3/`；R1–R5 修订证据见 `remediation-1/`，F1–F3 续接证据见 `remediation-2/`（均位于 `docs/design/evidence/learning-system-next-delivery/`）。
