# Codex 接入与当前验收边界

最近一次剩余两项验收的实测结果与阻塞依赖，见 [验收记录](ACCEPTANCE.md)。

2026-10-26 用户决定不再投入完整工具隔离，以协作门禁交付。下述严格 Native 适配器保留关闭状态，独立草稿可供试用；其未完成隔离与真实自动闭环不再阻塞本轮收尾。没有将工具隔离标记改为 true，也没有自动启用写库。

2026-10-26 在本机 Codex CLI `0.164.0-alpha.11.1` 验证。使用现有 ChatGPT 登录，不新增密钥、不覆盖用户配置，不修改账户、ACL 或服务。规则仍以 AGENTS.md 为准。

## 已实现的接口

`codex.CodexDispatcher` 通过 App Server stdio 连接本机 Codex。它从 `thread/read(includeTurns=false)` 读取父线程真实 model/modelProvider，不读取父历史、不回退猜测默认模型。显式草稿使用新的 ephemeral 根线程，核对返回模型和只读 sandbox，禁用请求中列出的工具类别与 MCP。

`inspect()` 只读诊断，不创建模型任务。`draft()` 是独立实验通道，返回 `CodexDraft`，固定 `tool_isolation_verified=false`、`applied=false`。它不是 NativeResult，也不能直接作为维护报告或候选批准使用。

`__call__()` 默认原生接入在任何 RPC 前拒绝运行，因为尚不能证明 NativeRequest 的 `tools=()`。不要把它传入 AgentSession 或包装成已经通过权限验收的 transport；也不能从 draft 中抽取 output，绕过这些检查直接交维护执行器。

RPC 使用无 shell 子进程，校验消息身份、JSON 字段、单行/总量/队列上限、写入及锁等待超时。全部服务端批准、动态工具和未知请求被拒绝并停止；出现工具 item 也停止。事件可能在工具执行后才收到，因此这些检测不等于事前的完整工具隔离。

## 可信维护者 CLI

在已有 Codex 会话的终端执行；父线程默认取 `CODEX_THREAD_ID`，也可显式传 `--parent-thread-id`。可执行文件默认从 PATH 查找，也可指定绝对路径。

`<CODEX_RUNTIME_PYTHON>` 表示本机 Codex 运行时自带的 Python 解释器路径；该路径属于本机配置，不随仓库发布，使用时替换为实际路径。

```powershell
& '<CODEX_RUNTIME_PYTHON>' -B -m tools.wiki_runtime.host.codex_cli inspect --timeout 30
```

显式草稿需 `--role` 与 UTF-8 JSON `--payload` 文件，固定系统提示由角色映射取得，载荷不能设置 model/tools/system。最小合成 Worker 载荷是：

```json
{"input":{"task":"这是连通性测试，仅返回 changes 为空数组的 JSON，不使用工具或读写文件。"},"documents":[]}
```

将合成载荷保存到专用运行目录后，可运行：

```powershell
& '<CODEX_RUNTIME_PYTHON>' -B -m tools.wiki_runtime.host.codex_cli draft --role worker --payload .wiki-runtime/codex-smoke-payload.json --timeout 60
```

此命令会使用当前账号额度调用继承的模型；只打印草稿，无 apply 选项，不写正式知识库。退出码 0 表示诊断或草稿调用成功，不表示权限隔离或维护门禁已通过。失败只输出固定诊断，不回显可能包含私有数据的服务端错误。

## 实际验证结果

- 真实 inspect 继承父模型和 provider 成功；本机值为 `gpt-6.1-sol` / `openai`，实现没有硬编码它们。
- Windows sandbox readiness 为 ready。App Server 的真实 `command/exec` 临时目录探针先读取原件成功，随后写入触发系统 PermissionError，原字节不变。探针只覆盖这一只读后端路径，不能外推为所有角色/工具已验收。
- 一次真实独立 Worker 合成草稿返回 `{"changes":[]}`，没有发送真实知识库内容，没有执行 ingest/approve 或应用变更。
- 17 项 Codex 定向用例通过，覆盖父模型缺失、角色/会话篡改、严格 JSON、批准/动态工具拒绝、工具事件、超时、进程清理及流量边界；独立审查复跑通过。脱敏现场证据位于 `.wiki-runtime/codex-live-probe.json`，属于本机运行目录，不随仓库发布，也不作为知识页提交。

## 未完成的强制隔离

官方说明 Codex 自定义子代理继承父权限，角色文件不能创建独立只读沙箱，见 [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)。本实现因此使用独立根线程，而不是假定桌面子代理已经受限。

本机公开协议与配置可逐类关闭工具，但尚未取得完整的有效工具白名单或总工具关闭证明。`dynamicTools=[]` 只是没有增加客户端工具；`environments=[]` 只关闭环境访问；`disabledPluginIds` 的 schema 明确注明尚不筛除插件能力。参考 [App Server](https://learn.chatgpt.com/docs/app-server) 和 [配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)。不能将这些设置或模型自报当作完整隔离证据。

在取得完整受限工具能力证据，并用实际模型身份完成所有旁路与批准通道验证前，T10/T11 保持未最终验收，自动原生维护通道不启用。当前桌面主会话仍有 workspace-write；新增适配器不会收回它已有的工具权限。不得仅改 verified 字段、放宽 tools=() 或添加另一个提示模板来标记完成。
