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
