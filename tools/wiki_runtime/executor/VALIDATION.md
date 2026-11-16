# T09 开发验证记录

日期：2026-10-26。仅临时库；不修改正式 wiki/raw、AGENTS、ACL 或真实用户。公共契约 1.0，验证器 gates-1.0，Reviewer 使用当前 T06 PROMPT_VERSION。模型为明确测试 transport，不代表真实模型语义质量。

完整开发回归：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_executor_recovery.py -v
```

运行期间该文件含 25 个测试，输出 `Ran 25 tests in 392.907s`、`OK (skipped=1)`。唯一跳过项是 Windows symlink 创建缺少权限 WinError 1314。随后新增的两个测试分别独立运行并通过，当前文件共 27 项；最终整文件 27 项由协调者独立复核。

补充真实采集正向：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest tools.tests.test_executor_recovery.ExecutorTests.test_real_capture_validate_package_and_apply_preserves_original -v
```

输出 `Ran 1 test in 6.778s`、`OK`。实际调用 T01 capture、validate_package、可信 package_check 和 T09 apply，raw/assets 原件字节保持一致。

补充 Windows junction：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest tools.tests.test_executor_recovery.ExecutorTests.test_windows_junction_is_rejected_without_touching_target -v
```

输出 `Ran 1 test in 0.130s`、`OK`。真实建立临时 junction，候选拒绝，外部 sentinel 保持不变；使用 Path.rmdir 仅移除 junction。

最终 payload 根路径核验调整后的针对性回归：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest tools.tests.test_executor_recovery.ExecutorTests.test_private_journal_overlap_and_root_lock tools.tests.test_executor_recovery.ExecutorTests.test_real_process_exit_after_new_file_link_is_recoverable -v
```

输出 `Ran 2 tests in 7.023s`、`OK`。真实子进程在新文件 hardlink 安装后 `os._exit(87)`，观察 nlink=2 后成功恢复。

覆盖：全部写入原语 before_intent/after_intent/after_replace/after_write/after_done，全部恢复步骤四边界，初始 journal/active/提交边界；approve 的目标写入、源移除和 frontmatter payload；幂等；用户写后编辑、恢复期间编辑、非目标读取依赖修改、新目录/新文件；窄窗口实际替换版本备份；可信批准撤销与 scope 绑定；伪造批准/pass、缺审查/预算、超时与迟到结果；质量 partial、包哈希篡改、未知包；ingest 配套成功后才 pending；机械索引无额外人工批准；hardlink/junction 拒绝。

尚未验收：真实模型质量、生产 trusted host/ACL 隔离、附件重定位及二进制审查、跨卷 journal、断电持久性、非 Windows 生产支持。ReplaceFileW 保存实际被替换字节并报告冲突，不等于整个文件系统 compare-and-swap。部分临时写入及不明外部编辑保留为 conflict，需人工对账。详细边界见同目录 README。
