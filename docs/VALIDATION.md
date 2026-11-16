# 独立仓库迁移验证

验证日期：2026-11-16。

- 空白工作区初始化及八项结构检查通过；重复初始化保留已有文件。
- 公开 Python 文件语法检查通过，测试发现无导入错误。
- 迁移专项验收共 59 项：58 项通过，1 项因 Windows 无符号链接权限跳过。
- 契约的 16 个有效／无效样例符合预期。
- 公开暂存树白名单检查通过；在隔离索引中强制加入 raw 文件时被成功拦截。
- 公开文件未匹配原私人 raw/wiki 中超过 100 字符的整行正文。该检查是辅助手段，不替代内容审阅。
- 上游补丁、清单和实现文件的暂存字节与提取前一致，避免换行转换破坏 SHA 校验。
- Markdown 本地导航目标检查通过。

## 可复核的专项命令

```bash
python -B -m unittest tools.tests.test_public_workspace tools.tests.test_health tools.tests.test_learning_s0_loop_protocol tools.tests.test_runtime_contracts tools.tests.test_host_cli.HostCLITests.test_import_keeps_assets_and_managed_source_expands_for_reviewer -v
python -B -m tools.wiki_runtime.contracts --examples
python -B tools/check_public_release.py
```

## 验证边界

全量回归曾在 Windows 沙箱的子进程管道回收处停滞并中止；相同资料导入用例在本机环境单独复测和最终专项中均通过。未将全量回归记为通过，未重新验收外部 DeepTutor 部署、真实模型调用、学习效果或前端构建。依赖私人样本的测试未公开，见 [发布边界](PUBLICATION.md)。

## 设计内容迁移的核验

设计迁移按批次独立提交并打标签，每批的核验范围与结果如下（截至 2026-11-17，未推送远端）。

| 批次 | 标签 | 范围 | 暂存树门禁 |
| --- | --- | --- | --- |
| A | `s2-batch-a` | 单一正本口径、公开门禁增强、wiki 层通用规则提取 | 383 个公开文件，0 项问题 |
| B | `s2-batch-b` | 上游选型与原始研究 | 426 个公开文件，0 项问题 |
| C | `s2-batch-c` | 学习底座与数据交接的逐小节合并 | 426 个公开文件，0 项问题 |
| D | `s2-batch-d` | 知识准备、准入与入库的逐小节合并 | 428 个公开文件，0 项问题 |
| E | `s2-batch-e` | 课程、出题、受控扩展与入库改造的逐小节合并 | 432 个公开文件，0 项问题 |
| F | `s2-batch-f` | 2026-10 历史演进档案发布 | 446 个公开文件，0 项问题 |
| G | `s2-batch-g` | 框架运行时、补丁说明与阶段验收记录 | 455 个公开文件，0 项问题 |
| H | `s2-batch-h` | 设计导航重写与迁移摘要 | 见本批提交时的门禁结果 |

每批另做两项人工核对：

- **私人标记逐行扫描**：盘符路径、Unix 家目录、父工作区名、个人身份、凭据形态、私有验证目录、私人层链接、私有仓库，在全部公开 Markdown 中均为 0 命中（代码块内的上游 i18n 示例与合成测试夹具按设计保留）。
- **重复内容检查**：合并后的文件不出现重复长行或重复标题。

结构检查 `python -B tools/health.py` 零 LLM 只读运行，无死链与孤立页。门禁与公开工作区相关测试 33 项通过。

**这些结果只说明公开树自洽与无私人标记命中，不等于设计内容已被证明完整。** 完整性以逐小节映射、差异块解释与导航可达性为准，见[设计迁移摘要](design/migration-summary.md)与[迁移方案的完成标准](design/public-repo-content-backfill-plan.md)。
