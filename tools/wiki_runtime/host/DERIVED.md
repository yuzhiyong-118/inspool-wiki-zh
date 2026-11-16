# 固定机器派生入口

`derived.py` 的 `build_raw_index(root, run_dir, operation_id)`、`build_health(root, run_dir, operation_id, *, save_report=True, write_graph=False)`、`build_capture(root, run_dir, operation_id, package, package_root, *, raw_path)` 返回标准 manifest、candidate、snapshot、payload_root bundle。仅写全新候选目录；库内目录仅允许 `.wiki-runtime`，拒绝覆盖。所有文件通过 CandidateView 枚举绑定，审查提示版本绑定到当前 `review.PROMPT_VERSION`。正式库仍须由 Executor 检查与事务写入。

可信 host 向 Executor 配置 `deterministic_check=check_derivation`。此回调不是模型工具或模型 JSON 字段。回调仅在复算后，所有实际目标路径及字节完全相符时返回 True；伪造 derived 标志、改变计数、替换正文、删除手写前后区或添加任意文件均不能认证。未认证的候选继续按原审查要求处理。`wiki/index.md` 中的语义说明不属于此入口的免审范围。

derived 写操作通过 Task Runtime 的 MaintenanceBinding 绑定 Task、Run、policy、submission_epoch、ownership generation 和完整候选，不使用学习 Admission，也不创建 LearningState。终态按原绑定归并真实 WAL；五个旧 Python 直写 API 已封闭，只读预览保留。离线切变先登记 intent 与 freeze，旧 pending 只能由清单内 drain 恢复或显式 supersede，迟到 pending 不得借续办进入白名单。

Raw 队列复用 `tools/raw_index.py` 唯一算法，只替换唯一有序标记内区域，保留标记外原始字节和换行风格。Capture 队列通过临时副本复算，无正式写入。

Health 复用现有 `health.py`，不调用 LLM。报告、可选图谱、固定格式追加日志均作为同批候选。日志符合 AGENTS 的 health 记录要求，保留旧日志完整字节，问题数与图统计来自同次检查。当前 graph 无时间字段，全部图结构精确比对；报告内部临时 timestamp 不输出。日志只允许合法 ISO 日期，重算不依赖秒级时钟。Health 输出本身仍受 G0–G2 约束，发现结构问题时不得绕过闸门。

Capture 仅接受 validate_package 通过的 complete Markdown / 微信包，拒绝 partial、PDF、OCR、模型抽取、缺外部图片和未知适配器。原件、抽取和附件原字节保存于 `raw/assets/<source_id>/<source_revision>/`；canonical `source-package.json` 保留定位与哈希。新增 raw 为 `unprocessed` 薄记录，正文精确嵌入同目录布局中的抽取资产，保证原抽取的 `../attachments/` 路径可用。没有摘要、原文重写或正式旧正文变更。验收会重新验证包并重建全部期望字节和路径，任何漏附件、夹带文件、wrapper 一字节变更均失败。已有修订目录或 raw 路径拒绝重复导入；同 URL 的新 source_revision 使用新目录。

旧开发 CLI 仍有原来的能力，尚未作为模型工具暴露。这些 builder 仅供独立 host 固定入口调用，不意味着当前桌面会话、旧 CLI 或开发 shell 已被限制。无外部 API key 的测试只使用临时库，不访问真实个人资料。

验证命令：`python -B -m unittest tools.tests.test_derived_entries -v`。9 项临时库测试通过，包含实际 Executor 无 Reviewer / 无模型的 capture、raw index、health 正例，以及手写区修改、wrapper 正文修改、伪造自证文字、图字段修改、漏附件、未知适配器、partial、重复修订与候选目录覆盖拒绝。Markdown 和微信原件均覆盖，包内原件与附件逐字节保存；source-package.json 是规范化元数据，不宣称保留输入清单的排版字节。
