# PDF 回归样本

公共契约 v1.0。`test_pdf_adapter.py` 的 `make_pdf()` 使用可选 pypdf，直接在临时目录生成小型解析样本，仓库不保存二进制 PDF，也不读取真实 raw：

- `text`：带标题、作者元数据的单页或多页文字；创建日期不冒充发布日期。
- `blank`：空白页，以及文字与空白混合页。
- `image`：单像素图像 XObject 的扫描件替身，无可抽取文字。
- `vector`：文字加矢量矩形，覆盖图表未处理提示。
- 损坏、截断、零页、密码加密和空密码加密文件。

这些是解析器行为测试数据，不是交付出版文档；不测试视觉排版质量。OCR、表格重建、阅读顺序和人工校验不在本版能力内，成功抽取依然为 `partial`，必须继续既有 PDF/多模态暂停策略。视觉运算符检测仅为保守提示。

依赖：在运行测试的 Python 环境中安装 `pypdf`（`python -m pip install pypdf`）。未安装时仅跳过解析测试，仍执行真实子进程缺依赖测试与模拟缺依赖测试；不自动安装、不联网。

验证命令（仓库根）：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_pdf_adapter.py -v
```

缺依赖环境可用 `-S` 禁用 site-packages 重复执行：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -S -B -m unittest discover -s tools/tests -p test_pdf_adapter.py -v
```

2026-10-26 开发自检：正常环境 18 项全部通过；`-S` 环境 2 项通过、16 项因缺可选依赖跳过。正常环境还包含通过子进程阻断导入和模拟 ImportError 的缺依赖分支。最终集成验收由协调者执行。

接口：`capture_pdf(..., vault_root=...) -> (dict, Path)`、`validate_pdf_package(package, root)`、`capabilities('pdf')`，位于 `tools.wiki_runtime.capture.pdf`。签名与现有 capture 一致；外部附件映射暂不支持。缺依赖抛 `UnsupportedPdfError`（`status='unsupported'`），不写候选包。注册与 CLI 由集成者维护。
