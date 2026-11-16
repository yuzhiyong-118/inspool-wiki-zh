# T10 运行记录

- 日期：2026-10-26。
- 依赖：协调者确认 T09 接口冻结及独立回归通过后解锁实现；公共数据契约 `1.0`，本地工具网关 API `1.0`。
- 状态：原型待集成；**实际宿主强制隔离未验收，not_verified**。开发测试完成不能将 T10 标为强制隔离已验收。
- 文件所有权：只新增本目录及 `tools/tests/test_permission_isolation.py`；未改 Executor、公共契约/CLI、wiki、raw、规则或系统配置。

## 实现与限制

`Gateway.bind` 由可信 host 绑定身份，返回 `call(tool, arguments)`。Worker 可读显式 scope、只写专属候选；Reviewer/Auditor 只读；Coordinator 只返回调度请求数据，不执行代码。没有 shell、正式写、Executor、批准、凭据签发或动态回调注册的模型端点。

路径检查拒绝穿越、绝对/Windows 别名、运行时目录、symlink/junction/reparse、hardlink、大小写别名与授权根重叠。检查只覆盖该网关调用；不能对抗同权限本地攻击进程并发切换路径。部署需独占受保护路径或引入已验证的 handle-based backend。

`inspect_deployment` 与只读 CLI 固定输出 `status:not_verified`、`enforced:false`、`may_apply:false`；CLI 实际进程退出码 `2`。profile 只能表示意图，额外 verified/探针字段被拒；任何工具清单都不能让隔离状态升级。尚未实现或认证真实外部受限 backend。

## 验证

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_permission_isolation.py -v
```

最终结果：20 项，19 通过、1 跳过（当前 Windows 身份缺少创建 symlink 权限）；0 失败，运行时间约 0.7 秒。真实 hardlink、Windows junction 攻击测试通过，均只操作临时树。CLI 子进程测试确认退出码为 `2`、输出保持拒绝、测试树字节不变。首次开发运行发现 Windows stdout 编码与 UTF-8 读取冲突，改为 ASCII JSON 后最终全量通过；首次失败不计验收通过。

覆盖：四角色未知/危险工具拒绝、role/session/批准字段伪造、未授权读范围、路径穿越及 Windows 别名、跨 Worker 写、保护根/其他候选根重叠、硬链接、junction、普通 symlink 能力检查、候选更新/大小限制、实际同权限进程直写反证、假 profile/探针不能升级状态、额外工具目录拒绝及只读 CLI。

对真实工作区执行只读 preflight：即使传入合法模板目录仍为 not_verified；`os.access` 报告 AGENTS.md、wiki、raw、tools/wiki_runtime 的当前进程可写线索。未实际写这些路径，未改变系统权限；该线索不能代替真实 ACL 验证。PowerShell 工具包装器可能把原生非零退出概括成 1，单元测试通过 subprocess 直接断言实际 CLI 退出为 2。

git 路径范围检查无既有文件改动；本任务新增文件未进入 git index。未安装 sandbox、变更账户、ACL、服务、环境或网络规则。

## 移交与停止条件

供协调者/T11 使用的 API：`Gateway`、`PermissionDenied`、`inspect_deployment`。模板和 README 为具体部署意图及后续真实探针清单，不能替代实际工具 transport 或用户认证 host。没有生产安装/启用动作。

下一步必须由实际宿主提供只允许绑定工具的受限模型入口、受保护的 Executor/规则/journal，以及在该真实身份中运行的旁路探针证据；独立集成验收前保持阻塞生产强制隔离。T11 可继续独立开发，但不得将当前部署写成正式库已受强制门禁守护。
