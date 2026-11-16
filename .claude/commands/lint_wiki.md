# /lint_wiki

对 `wiki/` 做**语义层**健康检查。在运行 lint 之前，建议先跑 `/health_wiki` 清掉确定性错误。

本命令与 `/health_wiki` 的分工：
- `/health_wiki`：零 LLM，纯确定性结构检查
- `/lint_wiki`：需要 LLM 判断的语义分析

---

## Phase 0：前置检查

1. 调用 `/health_wiki`（或 `python tools/health.py --json`）获取当前基础健康数据及 `stats`
2. 优先直接使用 health JSON 的当前图谱；需要落盘时按 `/health_wiki` 的受控 `host health --write-graph --apply` 入口执行，再读取 `wiki/meta/graph.json`；不要复用可能陈旧的图谱或由模型直写
3. 读取 `wiki/index.md`、`wiki/log.md`、`wiki/meta/purpose.md`
4. 读取 health 当前 `stats` 中的内容页统计（排除 meta 节点及其导航边，不重复计算）：
   - 内容页总数 = `wiki/{sources,entities,concepts,synthesis}/**/*.md` 数量（排除 `.gitkeep`、`index.md`、`log.md`、`meta/`）
   - 平均出链数
   - 节点数、边数、高度数节点比例

---

## Phase 1：语义检查

### 1. 孤立页面

- 在 `wiki/index.md` 中无链接、且被其他页面引用次数 = 0 的内容页
- 排除明确作为“入口”的 overview 类页面

### 2. 缺少来源支撑的强结论

- 识别正文中使用确定性语气（“必须”、“必然”、“已经证明”等）的 claim
- 检查该 claim 附近是否有 `[[sources/...]]` 或 `[[sources/...#某节]]` 支撑
- 知识页（`entities/`、`concepts/`、`synthesis/`）的 `supports` 字段至少应链接到页级来源节点

### 3. 陈旧结论

- 对比新 ingest 的来源页与已有 `synthesis/` 页面的结论
- 若发现冲突，标注并提示更新
- 对于 Obsidian 自动同步产生的 `vault backup` commit，默认不排除，但如果用户已配置过滤，可应用过滤

### 4. 高频提及但尚未独立建页的概念或实体

- 统计正文中被 `[[...]]` 引用次数 >= 3 次但缺少独立 `.md` 文件的目标
- 排除已存在于 `wiki/index.md` 但作为普通文本（非链接）的术语

### 5. 链接密度检查

**仅当同时满足以下条件时启用：**
- 内容页总数 >= 20
- 平均出链数 >= 1.5

**检查内容：**
- 找出出链 < 2 的页面（死胡同页面，会加剧 wiki 碎片化）
- 排除 `wiki/meta/overview.md`

**未激活时输出：**
```
链接密度检查：当前内容页不足 20 或平均出链 < 1.5，已跳过，避免空库误报。
（统计：内容页 N，平均出链 M）
```

### 6. 图拓扑感知检查

**仅当同时满足以下条件时启用：**
- `wiki/meta/graph.json` 存在且解析成功
- 内容页总数 >= 20
- 边数 >= 1.5 × 节点数
- 度数 >= 2 的节点比例 >= 40%

**检查内容：**
- **Hub Stubs**：高度数节点（被大量引用）但正文内容过薄（< 200 字符去 frontmatter）
- **Fragile Bridges**：两个知识群之间只有 1 条边连接
- **Isolated Communities**：与外部零连接的知识群

**未激活时输出：**
```
图拓扑检查：图谱密度不足（节点 N，边 E，高度数节点比例 P%），已跳过。
```

### 7. 重复页面或命名不一致

- 检查标题相近但文件名不同的页面
- 检查同一实体/概念被拆成多个页面

### 8. 外部 URL 直接依赖

- 检查知识页正文是否直接依赖外部 URL 作为主要证据
- 优先建议改为本地 `wiki/sources/` 页面链接

### 9. 关系字段缺失

- 核心知识页（`entities/`、`concepts/`、`synthesis/`）应至少有一个 `supports` 或 `contradicts`
- 排除 `wiki/meta/purpose.md`（元文件，不接受 `supports` / `contradicts` 语义）

### 10. 正文与 frontmatter 不一致

- frontmatter 中声明的 `related_*` 应在正文中有对应 `[[...]]` 双链
- 正文中出现的重要双链应考虑同步到 frontmatter

### 11. 分类迁移残留

- 检查是否仍有 `wiki/concepts/...`、`wiki/entities/...`、`wiki/synthesis/...` 的完整旧路径字符串
- 检查用户手动迁移分类后是否残留失效目录假设

### 12. raw 流程状态

- 是否存在长时间停留在 `pending_review` 的 raw 素材
- 是否应当成组处理却被拆散的相关 raw 素材
- 是否存在批次过大（> 5 篇）导致上下文噪声过高的 ingest 组

---

## Phase 2：输出与日志

1. 整理所有发现，按严重程度分组：
   - 🔴 必须修复
   - 🟡 建议优化
   - 🟢 信息提示

2. 输出格式：

```markdown
【Lint 报告】

## 必须修复
- ……

## 建议优化
- ……

## 信息提示
- ……

## 跳过的检查
- ……（说明原因）
```

3. 将以下日志作为候选，随相应维护操作交给门禁与 Executor；只读检查器本身不写日志。缺少宿主桥接时报告“日志未落盘”，不能直接追加正式文件：

```markdown
## [YYYY-MM-DD] lint | 语义检查完成（X 项必须修复，Y 项建议优化）

- 必须修复：……
- 建议优化：……
```

---

## 约束

- 只做语义分析，不重复 `/health_wiki` 的确定性检查
- 不直接修改文件，只输出修复建议
- 原生 SubAgent 默认继承主 Agent 模型，生成者和审查者使用独立上下文；不要求额外 API。通用接入见 `tools/wiki_runtime/host/HOST-INTEGRATION.md`
- 修复与日志落盘进入候选 → 门禁 → 独立审查 → Executor；approve 等敏感操作仍需绑定具体变更的用户确认。`tools/heal.py` 仅用 dry-run 辅助提出计划，不向模型暴露旧 `--apply` 写入口
- 阈值参数应来自 `tools/health.py` 的 JSON 输出，不要硬编码两套逻辑
