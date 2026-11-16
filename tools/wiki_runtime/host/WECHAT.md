# 微信来源入口

`tools/wechat_article.py` 是零模型调用的可信 owner CLI。默认预览、`--full` 与 `--json` 继续只读解析；`--raw` 的旧直接写入行为已经取消。

## 登记新资料

在 PowerShell 中先建立库外候选父目录，然后运行：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B tools/wechat_article.py 'https://mp.weixin.qq.com/s/ARTICLE_ID' --raw --state-dir 'E:/wiki-owner-state' --candidate-dir 'E:/wechat-candidates/article-001'
```

- `--state-dir` 必须显式指定，为正式库外、同卷的专属私有状态目录。
- `--candidate-dir` 是可信宿主选择的库外全新目录，父目录必须已存在；不得与正式库或状态目录交叠。
- 抓取只允许 HTTPS `mp.weixin.qq.com/s/<文章ID>`。每跳重定向及最终响应地址都必须满足同一限制；不接受账号密码、显式端口、片段、路径转义或控制字符。
- 抓取保留原始响应 HTML 字节，单篇上限 8 MiB；离线 capture 产生 `source-package.json`、原件、抽取正文和质量证据。
- 只有质量为 `complete` 的包才进入已有 `import-package` 固定派生流程，经过真实门禁、精确重算与 Executor 后登记 `raw/unprocessed`，同步 `raw/index.md`；原件和来源清单整体保存在 `raw/assets`。
- 不完整、验证页、截断、无效 UTF-8 或缺附件时仅保留候选包和 JSON 报告，`status=candidate_only`，退出码 1。不会初始化私有状态或写正式 raw。
- 当前 URL 入口不自动下载图片、音频、视频等外部附件。包含这些资源的文章通常停为 `partial`；应由可信采集者补全离线文件并使用既有 capture/import-package 流程重新制包，不能手改质量字段宣称完整。

成功登记退出码为 0；路径拒绝、抓取失败或执行异常为 2。门禁返回未应用时为 1，JSON 中保留实际执行状态。此入口不执行 ingest，不标记 `pending_review`，不归档 `processed`。

## 普通导出与只读兼容

```powershell
python tools/wechat_article.py 'https://mp.weixin.qq.com/s/ARTICLE_ID'
python tools/wechat_article.py 'https://mp.weixin.qq.com/s/ARTICLE_ID' --full
python tools/wechat_article.py 'https://mp.weixin.qq.com/s/ARTICLE_ID' --json
python tools/wechat_article.py 'https://mp.weixin.qq.com/s/ARTICLE_ID' --out '<库外输出目录>/new-article.md'
```

`--out` 是解析文本导出，不是来源包，不代表抓取完整。只允许库外普通新 `.md` 文件，父目录须存在；拒绝已有目标、symlink/junction/hardlink、规则入口、代码库和私有状态路径，文件上限 8 MiB。显式 `--state-dir` 时同时排除该状态树。`--raw` 不能与 `--out/--full/--json` 混用。

## 可信 Python 接口

```python
from tools.wiki_runtime.host.wechat import capture_url

report = capture_url(root, state_dir, candidate_dir, url)
```

这是可信 owner API，不能注册为模型工具；宿主选择 root、state、candidate 及网络实现。内部复用 `cli._prepare_derived`，以免建立另一套派生执行策略。可传 `apply=False` 生成并登记待应用的固定派生计划，随后通过既有 host inspect/apply 处理；完整包和候选目录须保留供重验。

旧 `write_to_raw_unprocessed` 已永久拒绝直接写入；微信资料统一通过上述受管 capture/import 路径，raw 保持 unprocessed。库外普通 Markdown 导出仍使用 `export_markdown`，不属于正式知识入库。当前桌面仍能直接运行可信 Python 的权限事实不因此改变，OS 隔离验收仍属 T11 剩余工作。

## 离线验证

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest tools.tests.test_wechat_rollout -v
```

测试仅在临时库运行，网络替换为固定字节；正式 capture、门禁、固定重算、Executor 和 WAL 不替换，不访问真实微信或真实 raw。
