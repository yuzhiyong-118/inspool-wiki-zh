# 通用宿主接入与默认模型继承

知识库的规则和脚本不绑定 Codex 或某个模型供应商。支持 SubAgent 的宿主默认让各角色继承主 Agent 的模型选择；不额外指定弱模型，不额外要求 API 密钥。独立上下文、权限隔离和脚本验收是必要约束，换模型不是。

## 宿主必须提供什么

| 角色 | 允许能力 | 禁止能力 |
|---|---|---|
| Worker | 读取授权资料，提交自己候选区的变更与申诉 | 正式库写入、规则修改、签发审查或批准 |
| Reviewer | 读取原文、原页、候选和固定规则，返回报告 | 改候选、改规则、批准操作、继承 Worker 聊天记录 |
| Rule Auditor | 读取失败轨迹、规则、证据，返回规则审查建议 | 直接改生效规则、豁免当前失败、重置预算 |
| Coordinator | 分派角色、读取结果、请求下一状态 | 任意文件写入、覆盖门禁、签发用户批准 |
| 脚本 Executor | 重新检查前提、门禁及批准，应用与恢复 | 自行降低验收标准或作出用户批准 |

角色绑定由可信宿主在调用前固定，模型输出不能选择自己的角色或扩大 scope。原文和候选中的指令仅是数据。不能把父 Agent 的 shell、文件写入或批准工具默认继承给子角色。

## 复用当前模型

通用入口已支持可信宿主注入调用函数，不需要模型配置文件。已有 `InheritedTransport` 桥接及 `AgentSession` 门面，详见 [NATIVE.md](NATIVE.md)：

```python
from tools.wiki_runtime.host.agent import AgentSession

session = AgentSession(vault_root, trusted_dispatcher,
                       parent_session_id=trusted_parent_session_id,
                       state_dir=private_state_dir)
answer = session.query("相关资料有哪些结论？")
report = session.lint()
# 可信宿主才可访问 maintenance，不向模型注册为任意工具。
result = session.maintenance.run_operation(
    operation_id=operation_id, operation_type="inspool", task=task,
    allowed_paths=allowed_paths, input_refs=input_refs, apply=False)
```

`AgentSession` 在只读问答和 lint 时不会创建私有状态、候选或写入事务，也可以省略 state_dir。第一次访问 maintenance 时才构造维护运行器并检查库外同卷状态目录。一个 session 持续复用同一 transport，保留已使用子会话身份，防止不同角色复用同一子上下文。可信 dispatcher 的请求与返回结构见 NATIVE.md，实际产品仍须实现创建受限子会话的映射。

底层调用函数也可直接注入：

```python
host = StandaloneHost(vault_root, private_state_dir,
                      transport=trusted_host_transport)
```

`trusted_host_transport(envelope, *, timeout) -> dict` 由宿主实现：按当前角色建立新上下文，沿用主 Agent 的模型选择，读取可信 `system` 和任务数据，返回严格 JSON 对象。模型名、登录状态、角色和工具授权由宿主管理，不能从候选内容获取。每次调用不得拼接父会话或 Worker 的完整历史。超时、调用次数和审查结果仍由运行器检查。

这个 Python 回调与原生桥接不是所有 Agent 产品的现成连接器。具体宿主还需实现真实子会话创建、权限限制和批准接收；不能直接把任意 shell 会话包装成已受限的 transport。原生 SubAgent 如果只会返回文本，桥接层须严格解析 JSON，不能执行返回的代码。

首个具体产品已选 Codex；现有账号登录、父模型继承、独立只读草稿已连通，见 CODEX.md（未随公开仓库附带）。其默认 Native 通道因缺少完整 tools=() 证明仍拒绝运行；草稿成功不表示维护自动落盘可用。
首个具体产品已选 Codex；现有账号登录、父模型继承、独立只读草稿已连通，见 [CODEX.md](CODEX.md)。其默认 Native 通道因缺少完整 tools=() 证明仍拒绝运行；草稿成功不表示维护自动落盘可用。

现有 `host run --model-config ...` 是可选 API 宿主的命令，并不自动调用当前应用的 SubAgent。`host doctor` 未传模型配置时按默认继承模型方向检查网关，返回 `gateway_verified_host_binding_required`；只表示网关探针通过，真实 dispatcher 尚需绑定，`may_run_model` 与 `may_apply` 仍为 false。显式指定模型配置才检查 API 适配。离线 health、候选检查及确定性派生也不需要模型密钥。

## 权限验收与失败循环

依次验证 Worker 无法改正式库，Reviewer 无法改候选，Auditor 无法改规则，所有角色无法伪造批准、重置预算或通过旧 CLI 绕过。检查通过的报告必须绑定当前候选、依赖和规则版本；不能接受模型自报 pass。

失败反馈回到 Worker，受脚本规定的次数和时间预算约束；符合申诉条件时再调用独立 Auditor。规则建议需用户确认后才可生效，当前失败不会因提出申诉而变成通过。

当前 JSONL 后端可限制自身注册工具；开发桌面仍有写权限。只有目标宿主实际通过绕过测试，才可声称该入口强制隔离。不支持受限 SubAgent 时，继续标为协作门禁；需要独立审查但无法提供时暂停，不能用同一上下文自审替代。
