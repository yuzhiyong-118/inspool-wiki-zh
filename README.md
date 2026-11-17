# Inspool Wiki 中文框架

将原始资料整理为带来源证据、双向关系和人工确认流程的 Markdown 知识库。本仓库只发布框架代码、维护规则、通用设计、补丁和合成测试；私人原文、知识页、学习记录及运行状态保存在本地。

> 维护边界：当前采用协作门禁——脚本检查、独立审查、有限重试与执行器已交付。2026-10-26 决定接受宿主仍可能直接写文件的限制，不再投入完整强制隔离；严格自动维护适配器仍关闭，真实模型自动闭环留作可选后续。

## 开始使用

需要 Python 3.11 或更新版本。核心结构检查只用标准库；PDF 抽取可选安装 `pypdf`。完整测试中涉及外部上游包或平台权限的场景会按实际依赖明确跳过。DeepTutor 集成需要另行安装匹配版本，见 [集成说明](tools/learning_book/README.md)。克隆仓库后在仓库根目录运行：

```bash
python -B tools/init_workspace.py
python -B tools/health.py
python -B -m unittest discover -s tools/tests
```

初始化只创建空的本地资料目录和索引，遇到已有文件会保留原件。`raw/`、`wiki/` 和运行状态均在 Git 忽略规则中。页面模板位于 templates/pages，不包含真实来源或个人知识。

## 这是什么

- **目的**：把在「AI 编码助手 / AI Agent 工程实践」方向上收集的资料，逐步沉淀为结构化、可交叉引用、可回看的知识库；规则由 LLM 维护，数据由 LLM 沉淀，**人**决定 ingestion 单元与 approve 时机。
- **来源**：基于 Andrej Karpathy 的 [llm-wiki.md](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) + nashsu/llm_wiki 公开文档的子集（应用层特性未采纳）。
- **边界**：本仓库是框架与规则，不是某一个人的知识库。知识页、课程正文与个人学习记录留在本地。

## 30 秒定位

| 你想问 | 去看哪里 |
| --- | --- |
| 规则怎么定，Agent 能做什么、不能做什么 | [AGENTS.md](AGENTS.md)，Claude Code 通过 `CLAUDE.md` 指针读取 |
| 门禁、SubAgent 与反馈循环怎么建设 | [维护方案](docs/design/maintenance-plan.md) |
| 知识层页面怎么写、关系怎么连 | [Wiki 知识层约定](docs/design/wiki-layer-conventions.md) |
| 候选、审查、执行与恢复的运行时接口 | [运行时说明](tools/wiki_runtime/README.md) |
| 门禁与权限边界、宿主接入、实际 Codex 边界 | [入口矩阵](tools/wiki_runtime/ENTRYPOINTS.md)、[宿主接入](tools/wiki_runtime/host/HOST-INTEGRATION.md)、[Codex 说明](tools/wiki_runtime/host/CODEX.md) |
| 学习资料与出题生产怎么用 | [学习集成](tools/learning_book/README.md)、[题目生产手册](tools/learning_book/QUESTION_PRODUCTION.md) |
| 全部设计文档怎么找 | [设计入口](docs/design/README.md) |
| 这次迁移现在什么状态、要决定什么 | [交接说明](docs/design/migration-batches.md) |
| 这次迁移做了什么、哪些没公开 | [设计迁移摘要](docs/design/migration-summary.md) |
| 公开了什么、哪些内容留在本地 | [发布边界](docs/PUBLICATION.md) |
| 这个仓库怎么从个人工作区迁出来的 | [迁移说明](docs/MIGRATION.md) |

## 项目结构

| 目录或文件 | 职责 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 唯一维护规则入口 |
| [.claude/commands](.claude/commands) / [.agents/skills](.agents/skills) | 随仓库提供的操作入口，不依赖父仓库 |
| [docs/design](docs/design/README.md) | 维护门禁、知识准备、学习与出题设计 |
| [tools/wiki_runtime](tools/wiki_runtime/README.md) | 候选、检查、审查接口、执行器和恢复 |
| [tools/learning_book](tools/learning_book/README.md) | 可选的学习资料与 DeepTutor 集成 |
| [patches/deeptutor](patches/deeptutor/README.md) | 适配特定上游版本的补丁；不是已部署服务 |
| [tools/tests](tools/tests) | 合成输入、临时目录与模拟服务测试 |
| `raw/` / `wiki/` | 初始化后生成的私人资料层，不提交 |

本地资料层分两层：`raw/` 是原始资料（保留外部 URL 与原文），`wiki/` 是结构化知识（来源页、实体页、概念页、综合页）。两层都不进入公开仓库，初始化脚本只创建空的目录与索引。

## 维护边界与已确定的设计取舍

以下取舍在原始工作区已经确定并经过实际验证，公开版本保留结论与依据：

1. **协作门禁**：确定性脚本检查结构、引用、索引、原文保护与流程状态；Worker 生成候选，独立 Reviewer 审查内容，失败后在预算内修复，规则争议交 Rule Auditor 提建议，不自动放宽规则；Executor 复验并应用变更，保留日志、冲突检测与恢复，approve 仍须用户确认具体批次。
2. **SubAgent 边界**：默认继承宿主模型并使用独立上下文，不要求额外模型或 API 密钥。
3. **统一资料包接口**：Markdown、离线微信与 PDF 走同一入口；不完整提取保守停留候选；PDF 与真实模型语义质量仍有评测范围限制。
4. **强制隔离停止投入**：接受宿主仍可能直接写文件的限制，没有「任何 Agent 都无法绕过」的保证。实际宿主角色权限仍需单独验收，部署模板不等于宿主已受限。
5. **外部 Agent 自动化**：曾以「常驻 Agent + 定时任务 + 消息网关」为方向并分阶段设计，approve 永不自动执行、必须见到人工确认标记；各阶段需独立可验证、可回滚。该方向的完整决策留痕见 [Wiki 知识层约定](docs/design/wiki-layer-conventions.md) 第六节。
6. **入口清单**：模板、命令与 skill 的部署清单、原件备份与逐文件日志留在本地，入口归属与迁移历史见 [入口矩阵](tools/wiki_runtime/ENTRYPOINTS.md)。

## 日常流程

1. 将资料放进 `raw/unprocessed/`，保留原文。
2. ingest 分析并生成来源页、知识页、反向关系、索引及日志，完成后进入 `pending_review`。
3. 用户确认具体批次后，approve 整组归档并修复 raw 引用。
4. Query 优先从本地 wiki 回答；Health 检查结构，Lint 审查语义和证据。

更细的语义：

- **ingest 单元**不是固定“一篇”，而是一篇素材或一组明确相关的素材；判定优先级为同一子文件夹、相同 `ingest_group`、用户明确要求，否则按单篇处理。建议单批次 2 到 5 篇。
- **状态机**：`unprocessed → pending_review → processed`。ingest 只推进到 `pending_review`，approve 才推进到 `processed`，未经确认不得直接跨段。
- **回填**：一次值得保留的问答通过 inspool 沉淀回 wiki，默认优先综合页。
- **Lint**：检查孤立页面、弱证据、重复页、旧路径残留、关系字段缺失、`pending_review` 积压与图谱关系。

运行时采用候选、门禁、独立审查及 Executor。宿主需要另行绑定真实 dispatcher、批准和权限控制；模块与模板存在不表示隔离或语义审查已验收。学习、模型及外部服务默认不会随初始化启动。

## 操作与入口速查

| 操作 | 作用 | 当前入口 |
| --- | --- | --- |
| ingest_raw | 分析素材、生成页面、自检，使用 LLM | [.claude/commands](.claude/commands) 模板；[.agents/skills](.agents/skills) 中的 `source-command-ingest-raw` |
| approve_ingest | 用户确认后执行状态与路径迁移 | `.agents/skills` 中的 `source-command-approve-ingest`；无本地命令模板 |
| query_wiki | 基于已有 wiki 回答问题，使用 LLM | `.agents/skills` 中的 `source-command-query-wiki`；无本地命令模板 |
| inspool | 回填高价值问答，使用 LLM | `.agents/skills` 中的 `source-command-inspool`；无本地命令模板 |
| health_wiki | 确定性结构及流程一致性检查，无 LLM | `.claude/commands` 模板；`python tools/health.py` |
| lint_wiki | 语义、证据与知识关系检查，使用 LLM | `.claude/commands` 模板；`.agents/skills` 中的 `source-command-lint-wiki` |

命令与 skill 随仓库提供，不依赖外部父仓库。未安装对应 skill 的 Agent 仍可按 [AGENTS.md](AGENTS.md) 执行，不应假定同名命令一定存在。

## 本地脚本速查

```bash
# 零 LLM 结构检查（默认只读；0=通过，1=发现问题）
python tools/health.py

# 输出 JSON（供自动化消费）
python tools/health.py --json

# 显式生成图谱；写标志必须提供库外同卷私有状态目录，经 Executor 门禁
python tools/health.py --write-graph --state-dir <私有运行目录>

# 保存报告并追加 health 日志；--graph-only 同样经门禁并记录日志
python tools/health.py --save --state-dir <私有运行目录>

# 预览 raw 队列，确认后仅更新 raw/index.md 的标记区域
python tools/raw_index.py
python tools/raw_index.py --write --state-dir <私有运行目录>

# 运行维护工具回归测试
python -B -m unittest discover -s tools/tests -v

# 预览结构自愈
python tools/heal.py

# 模型只使用 dry-run 形成修复计划；候选经审查及 Executor 后应用
# 旧 heal --apply 已拒绝；可信宿主使用 AgentSession.heal
```

heal 计划绑定原始依赖，模糊改链不跳过独立审查，且不自动建立桩页，详见 [heal 说明](tools/wiki_runtime/host/HEAL.md)。微信 URL 的 `--raw` 已改为保留原始 HTML、生成来源包，再经 Executor 登记；缺附件等不完整内容停留候选，`--out` 只允许库外新文件，详见 [微信来源说明](tools/wiki_runtime/host/WECHAT.md)。两者均无需单独配置模型。

## 提交与隐私

首次克隆后可启用随仓库提供的提交钩子：

```bash
git config core.hooksPath .githooks
python -B tools/check_public_release.py
```

公开文件由 `public-files.json` 逐项列出。新增框架文件须审查后显式登记；检查同时拒绝私人目录、真实回放夹具、运行记录和常见凭据格式。钩子可被绕过，因此每次发布前仍应检查暂存差异。详情见 [发布边界](docs/PUBLICATION.md)、[迁移说明](docs/MIGRATION.md)和[验证记录](docs/VALIDATION.md)。

## 方法来源

参考 [Karpathy 的 llm-wiki 方法论](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)和 [llm_wiki](https://github.com/nashsu/llm_wiki)。本次拆分没有授予新的开源许可证；第三方补丁及其使用须遵循对应上游许可。
