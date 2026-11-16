# 独立 owner 批准通道

`ApprovalStore(private_root)` 只由可信 host 持有。模型 JSON/JSONL 工具注册表不包含批准方法、密钥读取或凭据文件读取。正式 host 应把 `private_root` 放在受限工具所有读写 scope 之外，并传给后端的 `protected_roots`。不得放入正式 raw 或把此目录当模型候选目录。

可信 owner CLI 从 Executor 重建完整 context，先展示实际 diff，再调用：

```python
store = ApprovalStore(private_root)
handle = store.approve_interactive(context)
executor = Executor(..., approval_check=store.verify)
executor.apply(bundle, approval=handle)
# 重启后从受保护存储恢复，而不是接受模型提交的引用：
handle = store.lookup(context)
store.revoke(context)
```

API 为 `approve_interactive(context, *, input_stream=None, output_stream=None, ttl_seconds=86400)`、`lookup(context)`、`verify(context, handle)`、`revoke(context)`。`ApprovalHandle` 是可信 Python 内部对象，拒绝普通构造及 JSON/pickle 序列化。模型字符串、字典、authorization_refs 或 confirmed 字段不能成为批准。普通内容和机械索引更新无需新人工确认；本存储只签发 approve、rule_maintenance、tool_maintenance。

输入与输出都必须持有 OS 确认的 TTY 文件描述符；管道、StringIO、只伪造 `isatty()` 的对象不能确认。输出用 ASCII JSON 转义完整 manifest/candidate/snapshot/source_paths/bindings，包含 scope、批次、任务、候选和版本。owner 必须输入完整 64 位 context SHA256；yes/true 或摘要前缀不批准。完整 context 绑定与 Executor 使用相同 canonical JSON 算法，版本和全部依赖改变都会使原凭据失效。该终端方法不能注册到模型工具，也不能接受模型 JSONL stdin 作为 owner 输入。

目录中首次独占创建 32 字节 HMAC 密钥，后续保留。非空目录丢失 key、损坏 key、被改写的记录、symlink/junction/reparse 路径或文件硬链接均拒绝；不会自动修复损坏凭据。每次校验重新读盘，TTL 到期和持久撤销即时失效；再次人工批准会更换 nonce，使旧 handle 失效。`lookup` 对缺失/过期/撤销返回 None，对损坏或不可信存储抛出异常；`verify` 对上述情况返回 False。调用方不得把异常降级为批准。

本实现没有修改 Windows ACL，也没有建立独立 OS 用户。它限制的是正式模型工具通道，并不把同用户持有任意 shell/Python 的桌面开发会话变成强隔离环境。同权限进程能够修改 host 代码、读取 key、回放私有记录或控制终端；这类行为需 OS 账户/权限和可信启动器另行防护。逐次路径检查也不是对抗恶意并发重解析切换的 OS 原子隔离承诺。测试里显式 patch 内部终端检查仅用于可信单元测试，不能作为真人认证证据；真实 subprocess pipe 拒绝另有覆盖。
