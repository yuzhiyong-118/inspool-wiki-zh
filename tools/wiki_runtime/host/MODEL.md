# 模型传输边界

本页仅描述可选 Responses API 适配器。默认接入方向是复用宿主的模型与登录，让 SubAgent 继承模型、隔离上下文和权限；通用回调接口见 [HOST-INTEGRATION.md](HOST-INTEGRATION.md)。不使用本适配器时，不要求设置这里的 API 密钥。

`ResponsesTransport(config, environ=...)` 只接受 CONTRACT 中的六个字段。`base_url` 是 Responses API 前缀（例如 `https://api.openai.com/v1`），传输追加 `/responses`；`model` 必须由用户明确配置。`api_key_env` 指定环境变量名，密钥只加入 Authorization 头。无有效模型或密钥时失败，不尝试其他供应商或默认模型。

每次 `transport(envelope, timeout=...)` 单独发送 system 和 JSON user 数据，不附带历史。请求使用 `store: false`、空 `tools` 和 JSON object 格式。输出限定为一条完整助手文本消息，随后严格解析成单个 JSON 对象；允许并忽略供应商的 `reasoning` 元数据，不将其作为业务结果。工具调用、其他未知输出项、拒绝、截断、重复键、非有限数字、非 JSON 和超过 2 MiB 的响应均失败。报告的业务字段仍由 Reviewer、Rule Auditor 或调用方契约检查。

生产连接要求 HTTPS；HTTP 仅允许显式回环地址或 localhost，供本地服务和测试使用。禁用环境代理及所有重定向，避免 Authorization 跟随地址变化。错误只返回通用描述，不记录正文或密钥。

有效预算取调用方与配置超时的较小值，包括输入编码和等待时间。调用方超时后不接纳迟到结果。标准库阻塞网络运行在 daemon 线程中，读取分块检查截止时间；正在阻塞的 DNS、连接或读取不能保证在该瞬间被强制取消。此限制不会延长调用方等待预算，也不会产生本机工具调用或写入。

验证命令：`python -B -m unittest tools.tests.test_host_model -v`。测试使用真实回环 HTTP 服务验证协议、认证、重定向、恶意输出及超时，不消耗外部模型额度。尚未进行真实外部模型调用；需要部署者在独立终端设置其选定模型及密钥。
