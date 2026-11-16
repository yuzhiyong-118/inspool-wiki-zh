# Inspool Wiki 中文框架

将原始资料整理为带来源证据、双向关系和人工确认流程的 Markdown 知识库。本仓库只发布框架代码、维护规则、通用设计、补丁和合成测试；私人原文、知识页、学习记录及运行状态保存在本地。

## 开始使用

需要 Python 3.11 或更新版本。核心结构检查只用标准库；PDF 抽取可选安装 `pypdf`。完整测试中涉及外部上游包或平台权限的场景会按实际依赖明确跳过。DeepTutor 集成需要另行安装匹配版本，见 [集成说明](tools/learning_book/README.md)。克隆仓库后在仓库根目录运行：

```bash
python -B tools/init_workspace.py
python -B tools/health.py
python -B -m unittest discover -s tools/tests
```

初始化只创建空的本地资料目录和索引，遇到已有文件会保留原件。`raw/`、`wiki/` 和运行状态均在 Git 忽略规则中。页面模板位于 templates/pages（未随公开仓库附带），不包含真实来源或个人知识。

## 项目结构

| 目录或文件 | 职责 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 唯一维护规则入口 |
| [.claude/commands](.claude/commands) / [.agents/skills](.agents/skills) | 随仓库提供的操作入口，不依赖父仓库 |
| docs/design（未随公开仓库附带） | 维护门禁、知识准备、学习与出题设计 |
| [tools/wiki_runtime](tools/wiki_runtime/README.md) | 候选、检查、审查接口、执行器和恢复 |
| [tools/learning_book](tools/learning_book/README.md) | 可选的学习资料与 DeepTutor 集成 |
| [patches/deeptutor](patches/deeptutor/README.md) | 适配特定上游版本的补丁；不是已部署服务 |
| [tools/tests](tools/tests) | 合成输入、临时目录与模拟服务测试 |
| `raw/` / `wiki/` | 初始化后生成的私人资料层，不提交 |

## 日常流程

1. 将资料放进 `raw/unprocessed/`，保留原文。
2. ingest 分析并生成来源页、知识页、反向关系、索引及日志，完成后进入 `pending_review`。
3. 用户确认具体批次后，approve 整组归档并修复 raw 引用。
4. Query 优先从本地 wiki 回答；Health 检查结构，Lint 审查语义和证据。

运行时采用候选、门禁、独立审查及 Executor。宿主需要另行绑定真实 dispatcher、批准和权限控制；模块与模板存在不表示隔离或语义审查已验收。学习、模型及外部服务默认不会随初始化启动。

## 提交与隐私

首次克隆后可启用随仓库提供的提交钩子：

```bash
git config core.hooksPath .githooks
python -B tools/check_public_release.py
```

公开文件由 `public-files.json` 逐项列出。新增框架文件须审查后显式登记；检查同时拒绝私人目录、真实回放夹具、运行记录和常见凭据格式。钩子可被绕过，因此每次发布前仍应检查暂存差异。详情见 [发布边界](docs/PUBLICATION.md)、[迁移说明](docs/MIGRATION.md)和[验证记录](docs/VALIDATION.md)。

## 方法来源

参考 [Karpathy 的 llm-wiki 方法论](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)和 [llm_wiki](https://github.com/nashsu/llm_wiki)。本次拆分没有授予新的开源许可证；第三方补丁及其使用须遵循对应上游许可。
