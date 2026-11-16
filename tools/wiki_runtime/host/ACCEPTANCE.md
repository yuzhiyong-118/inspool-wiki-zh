# Codex 剩余两项验收记录

> 公开版本：保留通用契约与结论；历史验收、运行记录及本地素材不随仓库发布。文中结论与计数对应 2026-10-26 当时的环境，不代表当前部署或验收完成；脱敏现场证据保存在本机忽略目录，无法由本仓库独立复核。

日期：2026-10-26。最新决定：用户接受协作门禁的宿主权限限制，不再继续投入强制隔离。当前按已实现脚本与入口范围交付；完整强制隔离和真实 Codex 自动闭环没有通过验收，也不再作为本轮收尾前置条件。严格 Native 适配器仍关闭，真实模型闭环留作可选后续。

以下是范围收敛前的实测记录，保留其结论，不改写历史结果。范围调整不豁免确定性门禁、独立审查、有限重试或具体批次批准。

## 第一项：宿主权限隔离

本轮实际复跑现有 Codex app-server，使用原 ChatGPT 登录和父会话模型元数据，不设置独立模型或 API 密钥。

| 检查 | 结果 | 能证明的范围 |
| --- | --- | --- |
| 父模型元数据读取 | 通过 | 继承 gpt-6.1-sol / openai，不读取父历史 |
| 当前 MCP 枚举 | 通过 | 本次为 node_repl、rea；能力集合会变化，不能硬编码旧枚举 |
| Windows 只读后端探针 | 通过 | 临时文件读取成功，写入触发 PermissionError，原字节未变 |
| 六类角色经真实 Native 桥接拒绝 | 通过 | Worker、Reviewer、Auditor、Query、Lint、只读复核全部在任何 RPC 前拒绝 |
| 完整工具限制及所有旁路的事前阻断 | 未证实 | 不能将上述结果外推为完整隔离 |

真实负向探针返回 RPC -32603（sandbox denied exec error），属于预期的系统拒写证据。脱敏现场结果保存在忽略目录 `.wiki-runtime/codex-live-probe.json`，不随本仓库发布；本轮探针未调用模型。

当前配置禁用已知工具类别、动态枚举并禁用 MCP，仍缺少有效工具全集或总关闭证明。`inspect` 实测返回 `native_compatible=false`、`tool_isolation_verified=false`。这些检查没有收回当前桌面会话已有的 workspace-write 权限。

本轮额外核对了 [OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)：PreToolUse 错误、超时或格式错误可能不阻止工具；托管工具不走本地 Hook，部分特殊工具也可能绕开。由此不能用 deny-all Hook 代替完整、失败时关闭的强制边界。没有安装这种 Hook，也没有改账户、ACL、全局配置或启用服务。

## 第二项：真实 Codex 自动维护闭环

状态：依赖第一项，未执行完整真实模型闭环，不能验收通过。现有合成 Worker 草稿仅是连通性证据；本轮没有新模型调用。

本轮另复跑临时库的拒绝后修复、三次候选耗尽、规则审查四种处理结果与持久预算、逐写入边界恢复、独立批准、防止离线绕过 G3 六项场景。门禁、协调器和执行器使用真实实现，模型使用测试替身；这属于回归证据，不替代真实 Codex 的模型角色和权限验收。

后续必须先获得运行时工具限制的事前强制证据（包括异常时关闭、工具发现、网络/插件/MCP、文件写入及权限提升路径），才可连接维护执行器；随后在临时库用真实独立角色执行生成→拒绝→修复→审查→应用→中断恢复，并验证实际批准通道。不得把 draft.output 包装为 NativeResult、强改 verified 标志或跳过 G3 来完成测试。

## 本轮可复现检查

使用当前可用 Python 解释器，统一加 `-B`：

```powershell
python -B -m tools.wiki_runtime.host.codex_cli inspect --timeout 30
python -B -m unittest tools.tests.test_codex_host tools.tests.test_native_transport
```

第二条实际运行 28 项，全部通过，13.916 秒，包含新增六角色关闭边界用例。实际 Codex 诊断需要宿主正常访问现有登录目录；本次通过已授权的提升执行完成，没有改 HOME/CODEX_HOME。

临时库回归选自 `test_bounded_loop`、`test_executor_recovery`、`test_standalone_host`，六项全部通过，135.175 秒。加前述 28 项，本轮定向回归共 34 项通过；不是全套重跑。只读 Health 八项检查 0 问题，git diff --check 通过。完整结果同步到 `wiki/log.md`，该日志不随本仓库发布。本记录不是上线批准，T10/T11 保持未最终验收。
