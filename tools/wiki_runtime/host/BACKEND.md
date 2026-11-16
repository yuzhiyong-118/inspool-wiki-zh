# 单角色 JSONL 后端

`RoleBackend(formal_root, *, role, read_scopes=None, candidate_root=None, protected_roots=())` 在可信启动时绑定 Gateway 闭包。`invoke(tool, arguments)` 返回 `{ok:true,result:...}` 或 `{ok:false,error:{code:...}}`；错误不回显请求、异常或本地路径。`catalog()` 返回当前角色实际工具的 `{name,parameters}` 列表；`descriptor()` 记录后端版本、源码 SHA-256、角色及注册表。

独立入口为 `python -B -m tools.wiki_runtime.host.backend --bootstrap OWNER_JSON`。OWNER_JSON 由可信 host 的 argv 提供，仅允许构造参数字段。模型标准输入每行只能是 `{"tool":"read","arguments":{"scope":"wiki","path":"page.md"}}`。角色、session、权限、回调、shell、批准和 Executor 均不是模型工具。`--describe` 是可信启动参数，只输出描述并退出；模型 JSON 不能切换该参数。

Worker 只能读 host 授予的 scope 并写自身候选；Reviewer/Auditor 只读；Coordinator 的 `request_task` 只返回数据，`executed:false`。候选父目录须由可信 host 预建。模型字符串不会作为代码执行。每行上限 2 MiB、JSON 嵌套深度 24、节点数 20000；拒绝重复键、非有限数、未知字段、非法 UTF-8 和畸形 JSON。超长行终止通道，避免尾部被当成新命令。

`probe_backend()` 由可信父进程在临时树运行真实 `-m` 子进程，四角色分别执行正向和拒绝探针，使用真实 hardlink 及 symlink（Windows 无 symlink 权限时用 junction），并由父进程比较 formal/private 文件名与字节。报告包含逐项结果、由真实子进程取得的注册表与源码摘要。探针不访问生产库、不调整 ACL/用户/全局配置，不接受外部报告或静态 verified 字段签发通过。

此证据只覆盖固定角色 JSON 数据入口。远端模型必须只有文本传输，无本地代码或通用工具旁路；本地 host、代码、启动参数、祖先目录及候选树须受可信方控制。当前 Gateway 逐路径检查不防恶意本地进程并发替换路径。当前桌面开发会话仍可使用 shell；同 Windows 用户客户端直接操作文件的能力没有被撤销。本实现不声明 OS 隔离，也不改变 legacy isolation preflight 的 `not_verified`。

验证：`python -B -m unittest discover -s tools/tests -p test_host_backend.py -v`。
