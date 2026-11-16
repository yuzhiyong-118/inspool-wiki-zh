# 只读 Query 与语义 Lint

`answer_query(root, question, transport, *, input_refs=(), max_calls=4, max_seconds=120, call_timeout=30, mode='query')` 是独立的无状态入口。`transport` 由可信宿主注入；默认可经 `InheritedTransport` 继承主 Agent 模型，也可使用可选 `ResponsesTransport`。`AgentSession.query/lint` 已封装前者，不需要 API 密钥或私有状态目录。未绑定真实宿主 dispatcher 时不能把测试假传输当作实际完成。

该入口不创建 Coordinator、Executor、候选载荷、待审记录或批准事务，也不写 wiki、日志、缓存或运行密钥。所有正文及依赖复核均通过固定 `auditor` / `reviewer` 的 `RoleBackend` 只读通道；文件枚举仅访问目录与元数据。此边界属于应用数据能力约束，不是操作系统沙箱。

首先读取 `wiki/index.md`。显式 `input_refs` 优先，仅接受 `wiki/index.md` 与 `wiki/{sources,entities,concepts,synthesis,meta}/` 中的 Markdown 页面。没有显式输入时依次选择索引链接；20 页以内的小库补全内容页，较大库最多选择 20 页。总正文上限 1 MiB；不读取 raw、private、运行密钥、隐藏目录，不联网补充外部事实。模型调用本身可由宿主配置为远端传输。分类子目录递归兼容；唯一同名页可在原类型下解析迁移后的索引链接。歧义不猜测。

Query 模型必须精确返回：

```json
{"status":"answered","answer":"中文回答","citations":["wiki/sources/来源.md#关键观点"],"judgment":"fact"}
```

`status` 只允许 `answered` / `insufficient_evidence`，`judgment` 只允许 `fact` / `inference` / `conflict`。引用必须属于本次实际读取的文档，可以为页级、存在的标题锚点、有效 `#L1-L2` 行范围。未知工具、角色、批准与其他字段一律拒绝。未提供证据不能返回 `answered`。

所有有证据的回答（包括单来源事实）均进入独立 Reviewer JSON 请求；避免回答器通过自标 `fact` 隐藏强断言或跨来源推论。Reviewer 只接收固定系统提示、问题、原文和候选 JSON，不接收回答器解释、历史或修复反馈。审查精确返回 `{"verdict":"pass|fail","reason":"中文依据"}`；失败或不可用均不能默认通过。最多一次修复，所有生成与审查共享调用次数和总时间预算。宿主额外限制不遵守超时的可信传输等待时长。传输线程是可信宿主代码；超时不会撤销注入 Python 函数本身的能力。

`mode='lint'` 只做有界页面集的语义检查，模型精确返回：

```json
{"status":"completed","findings":[{"path":"wiki/concepts/概念.md","reason":"问题说明","evidence_refs":["wiki/concepts/概念.md#L1-L2"]}]}
```

检查失败返回 `incomplete` 与空 findings；不做修复、不推断未读取 raw 的状态。空 findings 同样独立审查，不能等同全库通过。确定性 Health 与日志维护是其他显式操作；本入口不会为了符合写入流程而伪造事务或改写日志。

宿主在模型调用前后及返回前比较已读取文档摘要与内容目录清单，变化即停止。这是依赖变化检测，不声称阻止恶意本地并发者或操作系统级 TOCTOU。结果在业务 JSON 外增加 `applied:false`、`calls`、`scope`、`partial_scope`；失败另外返回固定宿主 `reason`，不回显传输错误或模型原文。`partial_scope:false` 表示当前允许内容类型的页面均已读入，不意味着外部来源或 raw 已审查。

验证：`python -B -m unittest tools.tests.test_readonly_host`。测试只使用临时库和可信假传输，覆盖只读前后哈希、引用与 scope、分类迁移、修复和独立审查、预算/超时、依赖变化、未知权限字段以及 lint 仅报告。
