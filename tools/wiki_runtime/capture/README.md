# T01 离线候选采集

公共契约 v1.0；未修改冻结 schemas。MD/微信离线解析无需第三方依赖或网络；PDF 使用可选 pypdf。

```python
from tools.wiki_runtime.capture import capture, validate_package, identify, capabilities

package, package_root = capture(
    input_path, candidate_root, "capture-001",
    vault_root=vault_root,
    origin="https://mp.weixin.qq.com/s/example",  # 可省略，默认文件 URI
    # source_id="持久身份",  # 默认由 origin 决定
    # attachments={"https://example.org/image.png": local_image_path},
)
validate_package(package, package_root)
```

`candidate_root`、`vault_root` 必须显式指定；第三个位置参数必须是包根相对路径，不得绝对或穿越。候选根可不存在；包根必须不存在，拒绝覆盖。候选根及包根经解析后仅允许位于库外或库内 `.wiki-runtime/`；拒绝库根、`raw/`、`wiki/`、`tools/`、`.git/` 等控制区。调用者应使用独立运行目录，避免同时修改同一路径；这里的路径核验不是 OS 权限隔离，也不宣称抵御恶意并发替换。

返回 `(dict, pathlib.Path)`，包内保存 `source-package.json`、`originals/source.md|html`、`extracted/content.md` 和 `attachments/`。原件保留输入字节；抽取只进行非总结的格式转换与附件路径重绑。附件原始引用与包路径对应关系保存在质量 evidence。没有业务状态或授权字段，不登记正式 raw。

固定 `ADAPTERS` 已由协调者注册 `markdown`、`wechat` 与 `pdf`。`identify(path)` 按扩展名识别，未知类型抛 ValueError，不从扩展名猜测 PDF 转写为 MD 的原始类型；已转换资料必须由保持原始类型的适配器接入。`capabilities(id)` 返回离线能力声明；PDF 缺依赖时声明 unsupported，实际调用明确拒绝。注册不读取输入里的执行指令。PDF 包使用 `pdf.validate_pdf_package` 复算验证，成功抽取保守 partial，保持多模态暂停。

HTML 使用标准库解析器限制正文边界，复用旧微信脚本的 Markdown 转换与元数据提取。HTML 仅支持离线微信正文，缺正文或验证页为 failed；未闭合子树、截断标记、缺标题或缺附件为 partial。MD 严格 UTF-8，拒绝空正文和未闭合 frontmatter。作者/日期未知时保留空值并声明 unavailable_fields。附件可显式映射，或从输入同目录安全解析相对引用；不联网获取远程附件。读取不到或越界资源标记缺失；初始文件 IO 错误直接抛出，不伪装成规则失败。资源文件扩展名仅影响包名和 media_type，不执行文件。

`validate_package` 检查 schema、路径、真实字节哈希、抽取 UTF-8、原件修订摘要和定位引用；对于本模块的 complete 包还复算原件解析并验证附件覆盖。它不签发门禁批准。HTML 检测保守且有限，无法证明上游服务器从未省略内容；新增站点结构应补夹具。中断留下的半包不含最终 source-package.json；调用者另选新包路径重试，不能把残留当成功。

## 本任务验证记录

运行目录为仓库根，所有测试写入临时目录：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_capture_adapters.py -v
```

离线微信样本验证（同样只使用临时目录）：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_capture_adapters.py -k test_wechat -v
```
