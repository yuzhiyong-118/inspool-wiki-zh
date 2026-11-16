# 独立入口接口约定 v1

这是选定独立受限工具入口后的接入约定，不修改公共资料/操作契约 v1.0，也不把当前桌面会话改为受限角色。正式入口的模型只有 JSON 数据通道，没有本机代码、文件、shell、批准或 Executor 的任意调用能力。

## 模型传输

通用接入优先由宿主提供 `transport(envelope, *, timeout) -> dict`，SubAgent 默认继承主 Agent 的模型选择，分别建立上下文并限制工具权限；无需额外 API 配置。详见 [HOST-INTEGRATION.md](HOST-INTEGRATION.md)。下面的 ResponsesTransport 是可选 API 适配器，其密钥要求不适用于其他宿主。

`ResponsesTransport(config, *, environ=None).__call__(envelope, *, timeout) -> dict`。
envelope 为可信调用方生成的 JSON 对象，包含 `system` 字符串，其余内容整体作为用户输入数据，不从模型输出读取模型名、URL、工具、密钥或配置。请求不注册 provider 工具，不执行远端 function/tool calls。输出必须是单个 JSON 对象，重复键、非有限数、拒绝、截断、过大或非消息输出都拒绝。

配置字段固定为 provider、base_url、model、api_key_env、timeout_seconds、max_output_tokens；provider 首版仅 openai_responses。默认无模型/密钥时不可调用，不能写死模型、自动改用其他供应商或读取整个用户配置。环境密钥只进 Authorization，不进入日志、错误或模型正文。

## 本地用户批准

`ApprovalStore(private_root)`；`approve_interactive(context, *, input_stream=None, output_stream=None, ttl_seconds=86400) -> ApprovalHandle`；`lookup(context) -> ApprovalHandle | None`；`verify(context, handle) -> bool`；`revoke(context)`。
context 是 Executor 的完整批准上下文：manifest、manifest_digest、candidate、snapshot、operation_type、source_paths、bindings。签名绑定规范化 context 摘要；凭据只能由用户独立终端确认产生，模型协议中没有批准工具。非 TTY 输入不能确认；不提供 confirmed=true 的签发接口。模型看不到私有密钥、批准目录或可重置预算的接口。

## 角色后端

`RoleBackend(formal_root, *, role, read_scopes=None, candidate_root=None, protected_roots=())`：只封装已绑定 Gateway；`invoke(tool, arguments)` 执行固定工具；`catalog()` 返回实际注册表；`descriptor()` 只描述当前受限 JSON 通道，不宣称整个桌面会话已隔离。

`python -B -m tools.wiki_runtime.host.backend --bootstrap OWNER_JSON` 提供单角色 JSONL 入口，bootstrap 仅从可信启动参数读取，必须在首个模型消息前固定。每行仅包含 tool、arguments；role/session、配置、批准、shell、Executor 请求均拒绝。没有 eval/exec/任意模块导入/模型指定子进程，不把 JSON 中字符串当代码。

模型在远端作为文本生成器运行，没有本机文件系统权限；本地 JSON 网关是唯一工具能力。真实子进程探针验证这一通道，但不能据此宣称仍有任意 shell 的桌面开发会话已受限。当前开发、原有 CLI 和未来正式入口的能力边界分别记录。
