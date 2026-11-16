# T06 交付记录（待集成验收）

日期：2026-10-26。公共契约 v1.0 沿用已冻结版本；协调者发布摘要为
`6bc99b80b4f94257303fe73c94f19ce9ea793f4ee7261d0dec75489c26f8a507`。
本任务未修改公共契约、CLI、wiki 或 raw。

## 接口与绑定

```python
from tools.wiki_runtime.review import build_request, review, PROMPT_VERSION, PROMPT_DIGEST

# manifest.review_prompt_version 必须采用 PROMPT_VERSION。
request = build_request(
    manifest, candidate, dependency_snapshot,
    rules=agents_bytes, mapping=rules_json_bytes,
    originals={raw_path: raw_bytes},
    original_pages={old_page_path: old_page_bytes},
    candidate_files={final_path: final_bytes},
)
report = review(request, transport=transport, timeout=30.0)
```

`transport(envelope, *, timeout)` 返回 dict、严格 JSON 字符串或 UTF-8 JSON bytes。
envelope 只有 `system`、`input`、`reviewer_id`；无会话历史、Worker 辩护、工具或写入授权。
每次 review 发起独立调用。上游须提供完整原文与原页范围；本模块不自动读取正式库，
也不能证明调用者没有遗漏来源。输入只支持 UTF-8 文本文档；PDF 应先通过对应资料包质量流程，
不能将此审查代替多模态完整性门禁。

`build_request` 校验公共契约及所有绑定，核对原文/原页的依赖哈希、候选最终字节与旧页前提。
返回纯 JSON 请求，`review` 再次校验并复制，不信任传输回调修改请求。
不接收完整 manifest、authorization_refs、Worker 自述或附加工具。

提示正文在 `content.py` 的 `PROMPT`；摘要为原始 UTF-8 SHA-256：
`d31343e8e933ee77c55efd83b617962964bdd53a55bcbdf17dc6749d133054f2`。
导出 `PROMPT_VERSION = 'review-1.0:' + PROMPT_DIGEST`，报告的版本字段也绑定提示内容，
提示改变会使旧请求及报告失效。提示是执行协议，规则仍以请求内 AGENTS 原文为准。

输出只使用公共 `review_report`，不产生可信通过凭据。运行器仍须认证报告来源与当前前提。
报告逐项核对 operation_id、candidate/dependency/rules/mapping 摘要、验证器版本、提示版本及 reviewer_id。

## 引证协议

格式为 `original:路径#L1-L2`、`before:路径#L1-L2`、`candidate:路径#L1-L2`。
行号按 Python `str.splitlines()` 从 1 开始，范围必须存在且含非空内容。
finding.target 定位 candidate 或 before；finding.evidence 是 JSON 字符串：

```json
{"refs":["original:raw/unprocessed/协议夹具.md#L1-L2","candidate:wiki/sources/协议夹具.md#L1-L2"],"reason":"原文仅说小样本中可能有效，候选扩大为所有场景。"}
```

refs 必须包含 target 和原文/原页依据，并全部收录于 evidence_refs。
建议通过必须引用至少一段原文，并覆盖每个候选最终文件及删除前页面。
推荐规则不能变成 blocking。行号真实只代表引证可定位，不能证明说明或模型结论正确。

## 失败边界

- 无效请求抛 `ReviewError`，不启动模型；协调者须停止当前审查。
- 缺少 transport 默认返回 `error`，不会私自选择服务或调用付费 API。
- transport 异常、超时、畸形输出、未知字段、旧绑定、缺失/无效引证返回 `error`。
- 模型报告 `insufficient_evidence` 保留该状态，不按置信度放行；不管理重试或规则申诉。
- 超时使用 daemon 线程和有界队列等待强制返回 error；迟到结果丢弃。无法强杀正在运行的
  Python 回调或撤销其外部请求，因此 transport 必须由可信运行器配置并限制能力。
  本模块未传入写工具，但不构成操作系统权限隔离，不能限制恶意 Python 回调的环境权限。

## 协议测试

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_content_review.py -v
git -c core.safecrlf=false diff --check -- tools/wiki_runtime/review tools/tests/test_content_review.py
```

17 项测试通过；包括完整通过、条件扩大、无出处数字、抹平冲突的具体发现样例，
逐项绑定失效、非法引证、推荐项误升阻塞、缺证据、畸形 JSON、超时不遵守 timeout、
传输回调篡改请求，以及 create/move/delete 的覆盖检查。
测试用原文、候选及模型响应均为内存专属夹具，未访问正式原始资料。

这是**协议测试**，未接入真实模型，未进行真实模型质量评测；样本规模、模型版本、
成本、错判率和不同模型错误相关性均未测。任务状态为待协调者集成验收，非最终已验收。
token 使用量：宿主未提供，未知。
