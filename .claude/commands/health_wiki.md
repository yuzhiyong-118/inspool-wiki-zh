# /health_wiki

运行确定性结构与流程检查，不调用 LLM，不维护第二套检查算法。规则正本为 `AGENTS.md`，实现为 `tools/health.py`。

## 调用

1. 运行 `python tools/health.py`，自动化可使用 `--json`。
2. 原样保留问题及检查边界，不能将“结构通过”解释为“事实正确”。
3. 保存报告、图谱或日志时，使用受控派生入口；不让维护模型直接追加正式文件。
4. 由可信宿主设置库根、库外同卷的私有运行目录和本次操作 ID，执行：

```text
python -B tools/wiki_runtime/cli.py host health --root <库根> --state-dir <私有运行目录> --operation-id <本次ID> --write-graph --apply
```

该操作零 LLM，固定生成报告、图谱及 health 日志，再由 Executor 重验和写入。不需要模型 API。缺少可信运行目录或权限时，只完成只读检查并报告未落盘，不能退回 shell 直写；结构问题导致门禁失败时同样保留失败报告，不自称日志已保存。

`tools/health.py` 默认只读，退出码 0 表示结构检查通过，1 表示发现问题；兼容保存/图谱入口在写入成功后也保留该检查退出码，写入失败优先报告失败。`--graph-only` 经检查写图与日志，其退出码仅表示应用结果。`host health --apply` 的退出码同样只表示应用结果，应读取报告内的问题数判断结构状态。

## 八项检查

1. **活跃双链**：扫描内容页与 meta 实际双链；忽略围栏代码、行内代码、注释中的示例。log/audit-log 作为历史记录不检查出链，但仍可被链接。支持精确路径与同一顶层类型内唯一页面的分类迁移；同名歧义不任意选取。
2. **内容页 frontmatter**：来源页必需 type/title/raw_note/updated；其他内容页必需 type/title/updated。meta 不套用知识页证据字段要求。当前是轻量字段解析，不是完整 YAML 语法验证器。
3. **Wiki 索引**：检查 index 存在、僵尸条目与遗漏页面，递归覆盖分类子目录与 meta。自动生成的 health-report 不要求收录。
4. **Raw 路径残留**：检查活跃页面（包括来源页 frontmatter）中的显式 raw/unprocessed 双链是否指向现存文件；pending_review 的有效路径不误报。裸文本路径不作全量语义分析，approve 仍需按主规则对本批旧路径做全文局部检索。
5. **空文件与桩页**：内容页去掉 frontmatter 后正文为空或少于 100 字符。
6. **日志覆盖**：来源页名称或路径是否在 log 中出现；不保证那条日志的语义正确。
7. **Raw 队列与来源映射**：递归扫描 unprocessed/processed 中的 Markdown，核对 processing_status、所在目录、索引唯一收录与计数；pending_review/processed 必须有有效 processed_into 来源页，来源页 raw_note 回指当前 raw；processed 需有 reviewed_at。
8. **同名页面**：报告有歧义的同名 wiki 页面，使用明确路径消歧，不自动改名。

当前不检查标题锚点是否存在、证据是否支持论点或反向边的语义。后两者仍由 ingest 自检和语义 lint 负责。

## 图谱与报告

- `python tools/health.py --json`：只读 JSON，含 checks/stats/graph。
- `host health`：受控生成候选报告和日志，省略 `--apply` 时不写正式库。
- `host health --write-graph --apply`：同批重验并保存图谱、报告与日志。
- 兼容 `tools/health.py --write-graph / --graph-only / --save` 已要求显式 `--state-dir` 并转交 Executor；缺参数拒绝写入。`--graph-only` 现在也会经过检查并追加日志。
- 图谱 v2 的节点 ID 为相对路径，保留关系类型；lint 阈值统计只使用内容图，见本地图谱模式说明 `wiki/meta/graph-schema.md`（属于本地知识库层，不随本仓库发布）。

## Raw 队列快照

`python tools/raw_index.py` 只读预览；正式刷新使用 `host raw-index --root <库根> --state-dir <私有运行目录> --operation-id <本次ID> --apply`，只重建 raw-queue 标记区域，保留手写说明，并经 Executor 检查。兼容 `raw_index.py --write --state-dir <私有运行目录>` 也转交相同入口。它不改变 raw 状态、不替代 ingest 或 approve。私有运行器不向模型开放任意调用权限。

## 日志示例

```markdown
## [YYYY-MM-DD] health | 结构检查完成（X 项问题）

- 活跃链接、frontmatter、wiki 索引：……
- Raw 状态、队列与来源映射：……
- 其他问题与检查边界：……
```

修复前先查看 `tools/heal.py` 的默认 dry-run；不要为了得到零问题而生成没有证据的页面或删除历史记录。
