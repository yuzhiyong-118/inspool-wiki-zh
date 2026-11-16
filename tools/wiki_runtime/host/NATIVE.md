# 原生 SubAgent transport

`InheritedTransport` 是现有 `transport(envelope, *, timeout) -> dict` 的桥接实现。它只接受可信宿主注入的 Python callback；不执行 shell、不联网、不读取 API 密钥，也没有独立模型配置。具体 Agent 产品仍需实现 dispatcher，当前代码不能证明任何产品已经连接。

```python
from tools.wiki_runtime.host.native import InheritedTransport, NativeResult
from tools.wiki_runtime.host.supervisor import StandaloneHost

def dispatcher(request, *, timeout):
    # 此处必须由宿主 SDK 真正建立新的受限子会话。
    # 沿用当前宿主模型；不得传独立模型名，不得复用父会话或先前子会话。
    # system=request.system；任务数据=json.loads(request.payload_json)
    # tools=()，history=()；不能继承父 Agent 的 shell/文件/批准工具。
    child = host_create_fresh_restricted_session(request, timeout=timeout)
    output = child.run_json()
    # ID、role、session_id 必须来自可信宿主记录，绝不能从 output 中读取。
    return NativeResult(request.request_id, request.role, child.session_id, output)

transport = InheritedTransport(dispatcher, parent_session_id=trusted_parent_session_id)
host = StandaloneHost(vault_root, private_state_dir, transport=transport)
```

示例中的 `host_create_fresh_restricted_session` 是宿主需要实现的映射，并非本库提供的函数。宿主应从自己的会话管理器取得父会话 ID，且在整个生命周期内复用同一个 transport 实例，使已用 session 记录持续有效；宿主本身也必须保证全局会话不复用。

`NativeRequest` 是冻结数据记录，包含唯一 `request_id`、固定 `role`、`system`、任务数据 `payload_json`，并明确 `model_policy="inherit"`、`fresh_context=True`、`tools=()`、`history=()`。Worker 也只产生 JSON 候选计划；正式读写由原有 RoleBackend、Coordinator 和 Executor 执行。

角色只按运行器既有的完整 system 常量精确匹配：`WORKER_SYSTEM` → worker，内容审查 `PROMPT` → reviewer，规则审查 `SYSTEM_PROMPT` → auditor，`QUERY_SYSTEM` → query，`LINT_SYSTEM` → lint，`REVIEW_SYSTEM` → readonly-review。问题、原文、候选、payload 内的 role 或工具声明均是数据，不能改变路由。未知 system、额外 envelope 字段、模式不匹配在派发前拒绝；调用方本身须为可信运行器，不能向不可信用户暴露任意 system 注入接口。

dispatcher 只能返回精确 `NativeResult` 实例。桥接校验请求 ID、角色与新 session ID，拒绝父会话和已见 session；模型输出与元数据分开，模型不能自报身份。输出可为 dict、JSON str 或 bytes，限 2 MiB，拒绝重复键、非有限数字、过深结构、非对象和未知顶层字段；各角色的完整业务 schema、绑定、证据、权限仍由现有运行器重新验证。JSON 对象被复制解析，不能携带可调用对象或代码执行能力。

可选 `NativeResult.attestation` 经桥接绑定请求、会话、角色和冻结输入后，由当前 transport 私有登记为一次性句柄。消费时核对 transport 归属、未消费 token、完整快照和公开字段，普通字典、未登记句柄、字段改绑、持久化重放及重复消费均不能生成可复用 ReviewCredential。登记不跨进程恢复；消费后保存失败需要重新审查。无 Attestation 时只保存本次 UnattestedReviewEvidence，真实 L3 不自动通过。

超时使用 daemon 线程限制等待并丢弃迟到结果，不能强杀已经运行的 callback；callback 必须自行落实 SDK 超时、取消和子会话回收。异常只返回固定错误，不回显模型文本或宿主异常。冻结 dataclass、空 tools 声明和 session ID 校验都不是 OS 隔离证明：受限权限、真实的新上下文和继承模型必须由可信宿主实际实施并通过其绕过测试。可信 dispatcher 若撒谎或拥有任意写能力，本模块无法撤销它的 Python 权限。

测试：`py -B -m unittest tools.tests.test_native_transport -v`。可信假 dispatcher 验证 T06/T07 的实际 envelope 与现有运行器校验，并在临时库运行 Worker → T06 → Executor 再审查和只读 query/lint → 独立审查；测试清空环境变量且禁止创建 ResponsesTransport。这证明桥接与运行器可以无 API 密钥组合运行，不证明模型语义质量或产品 SDK 已接通。
