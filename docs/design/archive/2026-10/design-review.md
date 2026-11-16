---
type: meta
title: LLM Wiki 设计对照与维护改进
status: archived
updated: 2026-10-26
related_sources: []
related_synthesis: []
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../README.md)。


# LLM Wiki 设计对照与维护改进

## 范围与依据

这是一次维护设计评估，不是新资料 ingest，也不批准已有 pending_review。用户在本轮会话中同意有限横向对照后推进优化。对照以 2026-10-26 可访问的官方说明和契约为依据，未安装或运行外部项目；链接指向可变化的分支，不代表完整代码审计或性能验证。

本地现状见 overview（未随本仓库发布：wiki/meta/overview.md），主题边界见 purpose（未随本仓库发布：wiki/meta/purpose.md），证据图约定见 graph-schema（未随本仓库发布：wiki/meta/graph-schema.md）。保留 Markdown、Obsidian 双链、raw 正文只读、用户确认 approve 的基本架构。

## 三个项目的互补价值

| 项目 | 官方设计事实 | 本库取舍 |
|---|---|---|
| claude-obsidian | 修改计划绑定读取时的哈希；统一 apply，保存恢复日志；冲突时停止覆盖 | 借鉴计划、冲突检测与恢复机制。官方事务契约依赖 POSIX 目录描述符和 flock，要求 Windows 使用 WSL；不直接移植到当前 PowerShell 环境 |
| llm-wiki-compiler | 编译、查询与发布分层；发布时重新验证引用；执行状态独立存放 | 借鉴确定性验证与执行状态分离。其官方架构明确“链接有效不等于事实得到支持”，批量批准也不承诺整个批次原子写入 |
| karpathy-llm-wiki | 将 ingest/query/lint 包成轻量 skill，并列出刻意不构建的功能 | 借鉴按实际失败模式增加功能的原则；暂缓向量检索、复杂本体和数值置信度，不照搬其全部取舍 |

官方依据：[claude-obsidian 事务契约](https://github.com/AgriciDaniel/claude-obsidian/blob/main/skills/wiki/references/operation-transactions.md)、[llm-wiki-compiler 架构](https://github.com/atomicstrata/llm-wiki-compiler/blob/main/ARCHITECTURE.md)、[karpathy-llm-wiki 设计边界](https://github.com/Astro-Han/karpathy-llm-wiki#design-boundaries)。

## 本轮已实现

1. **修正当前状态**：README 不再声称等待首次 ingest；purpose 保留主题方向，把当前找不到的旧“已回答”页面标为待核实。历史描述与当前文件不一致，不据此断言丢失原因。
2. **默认只读检查**：health 不再隐式重写 graph.json；发现问题退出 1，显式参数才保存图谱或报告。日志仍由维护代理追加。
3. **扩展确定性覆盖**：检查活跃 meta 出链，排除代码示例；raw 目录、状态、队列、来源映射和来源页 raw_note 必须对齐。append-only 的 log 与 audit-log 不作为当前死链的出发页，但仍可作为链接目标。
4. **统一链接解析**：优先精确路径；唯一同名页面可在同一顶层类型下移动，重名时报告歧义，不任意选择。显式 raw 路径不通过文件名猜测迁移。当前不校验标题锚点是否存在，也不承诺完整实现 Obsidian 的所有链接语法。
5. **修正图统计**：内容图只统计 sources/entities/concepts/synthesis；meta 节点另外计数。图谱 v2 使用相对路径标识节点并保留关系种类，作为随文件树重建的派生数据，不作为知识页永久语义 ID。
6. **队列快照工具**：raw_index 默认预览，显式 write 只更新标记区域。标记外说明保留，缺少标记时拒绝覆写；单文件替换并检测索引是否变化，不宣称具备跨文件事务能力。
7. **记录真实入口**：本地只有 ingest/health/lint 三个命令模板；approve/query/inspool 另由共享 skills 提供，或按 AGENTS.md 执行。修复 heal 补入新 meta 页时的 Path 类型判断错误，并共享链接解析目标集。

两篇未登记 raw 仅增加 processing_status，原正文逐字节不变；没有执行 ingest 或 approve。

## 暂缓与保留分歧

- **不新增检索基础设施**：先用少量真实问答测召回与引用支撑，再决定是否需要向量索引。
- **不把每次更新都变成大规模重写**：来源摘要、关键概念与跨来源综合按实际内容创建，不为增加节点数而建页。
- **哈希区分用途**：原始正文去重、写入冲突检测、外部网页版本变化是不同问题；流程 frontmatter 变化不能等同于来源正文变化。
- **保留现有关系字段**：轻量参考项目不采用复杂关系本体，但本库已有 supports/contradicts 与 Dataview 使用目标，本轮不删除。
- **ADR 冲突尚未定案**：0001-state-storage（未随本仓库发布：wiki/meta/adr/0001-state-storage.md） 写 processed 后才填 processed_into，当前 AGENTS.md 和已有 raw 则在 pending_review 已填；按现行主规则检查，旧 ADR 保留并标记此处待处理。ADR 的“提议”状态与索引的“评审通过”描述也需后续统一，不能从文案猜测实际批准历史。
- **范围冲突尚未定案**：purpose（未随本仓库发布：wiki/meta/purpose.md） 保留通用工程排除规则与既有 Nginx 案例的分歧，不擅自扩大或删除主题。

## 可恢复写入方案（待实现）

本节是下一阶段的方案，当前所有写入入口尚未统一接入事务引擎，不提供全库回滚保证。

1. **计划阶段**：一个 ingest 单元生成一个操作清单，记录操作 ID、输入 raw 的正文哈希、每个目标的原始文件哈希和拟写入内容。raw frontmatter 继续是业务状态真相源；执行日志仅记录工作进度。
2. **验证阶段**：在候选目录验证页面、索引、双向关系和来源映射；检查目标路径、目标重名及内容是否由用户改动。未通过则不推进 pending_review。
3. **应用阶段**：协作写入者使用同一把 Windows 可用的进程锁；应用前备份目标并持久化日志，逐个临时文件替换，最后写入 raw 状态。外部编辑器不共享锁，因此仍需读取时哈希核验并诚实说明检查与替换之间的竞争窗口。
4. **恢复阶段**：依据操作日志识别未完成步骤；只有当前字节仍与本操作已写内容相符时才回滚，避免覆盖用户后续修改。进程退出、磁盘失败和同步软件冲突要分开测试。
5. **批准阶段独立**：操作清单与“写入计划已验证”都不等于用户同意 approve；原有三组 pending_review 不因本次维护而归档。原文正文保持只读。

最低验收：修改一篇目标后 apply 必须拒绝覆盖；在每个写入阶段故障注入后可识别并恢复；重复 apply 不重复创建页或日志；恢复时遇到用户新编辑必须停止；Windows 原生路径和 Unicode 文件名通过验证。完成这些条件并统一接入入口后，才称为“可恢复写入已实现”。

## 检索与回答验收建议

选 8–12 个真实问题，覆盖精确名称、中文/英文别名、跨来源综合、冲突与“库里没有答案”。每题手工指定应命中的证据页，记录是否找回、回答是否由原文支持、是否混入未确认判断；固定题集用于之后的回归。

优先评估“能否从现有页面得到可核实答案”，不把链接多、字数多或星数高直接当作知识质量。

## 本轮验证

- `python -B -m unittest discover -s tools/tests -v`：18 项通过，临时库覆盖分类移动、同名歧义、旧 raw 路径、来源映射、默认只读、队列保留手写说明与幂等更新等行为。
- 扩展后的 health：0 项结构问题；12 篇内容页、43 条内容图有向边。它不证明内容事实正确，也未验证实际 Obsidian 界面或 Hermes 运行状态。
- raw 队列：unprocessed 2、pending_review 3、processed 1。新增流程 frontmatter 时，两篇原正文均逐字节比对保持一致。
- 图谱已显式重建为 v2；后续默认 health 不再隐式重写。

## 维护入口

- 后续执行架构提案：[agent-maintenance-plan](../../maintenance-plan.md)，展开门禁、SubAgent 分工、修复循环与规则申诉；不表示这些能力已落地。
- 当前状态：overview（未随本仓库发布：wiki/meta/overview.md）
- 内容索引：index（未随本仓库发布：wiki/index.md）
- 图谱与证据约定：graph-schema（未随本仓库发布：wiki/meta/graph-schema.md）
- raw 状态决策：0001-state-storage（未随本仓库发布：wiki/meta/adr/0001-state-storage.md）
