# T10 运行权限隔离原型

公共数据契约仍为 `1.0`；网关 API `1.0`。本目录只依赖标准库及既有路径/JSON 契约，不修改 Executor、规则、正式库、ACL、账户、服务或全局配置。

**当前交付是工具网关原型，实际宿主强制隔离未通过验收。** Codex app 的协作子代理共享 workspace-write；模型仍能通过宿主 shell/文件工具越过网关。网关、模板、角色说明与独立上下文不能撤销这些权限。T11 必须继续阻止将当前部署描述为全入口守护。

## 选型与已知条件

| 方案 | 真实边界 | 当前条件与决定 |
|---|---|---|
| Codex app 子代理/候选子目录 | 共享当前身份和宿主工具 | 不构成强制隔离；不能选为已完成方案 |
| Windows 独立用户、ACL、受限进程 | OS 身份及资源访问控制 | 可研究，但未配置或验证；不自动创建账户、ACL 或网络规则 |
| 当前 codex sandbox | 依赖实际版本和宿主能力 | 协调者只读 `--help` 预检未确认可用 backend；禁止推断有 Windows 子命令或盲目安装 |
| 受限工具 transport | 模型只收 JSON 数据，无本地代码、通用文件、shell 或可替换的可信回调 | 已提供默认继承宿主模型的 InheritedTransport；实际产品的 dispatcher 与权限须部署验收，外部模型 API 可选 |

所选边界不是“在有 shell 的 Python 进程里隐藏对象”。模型必须在外部服务或真正受限的客户端中运行，只通过可信 transport 调用绑定工具。可信 host、Python 代码、角色映射、读取范围、Executor 与 journal 均不能由模型写入或重新注册。模型不得通过 Python 反射、pickle、eval、动态插件或脚本工具执行本地代码。

## API 与临时启动示例

以下仅创建临时夹具和受限工具通道，**不是 OS 沙箱启动器**。host 建立认证后的会话，调用 `bind` 并只将返回函数注册给该会话。模型工具参数只有 `(tool, arguments)`，没有 session、role、root、权限和回调参数。host 不得再将 `bind`、Gateway 对象或配置文件注册为模型工具。

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from tools.wiki_runtime.isolation import Gateway

with TemporaryDirectory() as temporary:
    root = Path(temporary)
    for name in ('formal', 'trusted', 'worker1'):
        (root / name).mkdir()
    gateway = Gateway(root / 'formal', protected_roots=[root / 'trusted'])
    worker_channel = gateway.bind('worker', candidate_root=root / 'worker1',
                                  read_scopes={'wiki': root / 'formal'})
    reviewer_channel = gateway.bind('reviewer', read_scopes={'wiki': root / 'formal'})
    # trusted transport 固定调用 worker_channel；模型不能选择 reviewer_channel。
    worker_channel('candidate_write', {'path': 'draft.md', 'text': '候选'})
```

| 身份 | 工具 | 含义 |
|---|---|---|
| Worker | `read(scope,path)`、`candidate_write(path,text)` | host 显式授予的目录只读；只写自身候选根 |
| Reviewer / Auditor | `read(scope,path)` | host 显式授予的目录只读 |
| Coordinator | `request_task(target,task)` | 返回调度请求数据及 `executed:false`；原型不执行任务文本 |
| Executor | 无模型工具 | 可信 host 在工具网关外持有并调用 T09 Executor |

所有参数字段封闭校验；未知工具、额外 role/session/批准字段、任意读取根、绝对路径、`..`、Windows 路径别名、重解析点、硬链接和运行时配置路径均拒绝。父目录由 host 预建；写入受限 UTF-8 文本。候选目录不能与正式库、受保护根或其他 Worker 根相交。host 必须只授予确有需要的读取范围，**不能把包含密钥/凭据的父目录授予 read**；候选文件的内容不能作为凭据或可执行脚本。

`request_task` 中的字符串始终是数据。未来调度器可以创建受限模型任务，但不能把内容当 shell/Python 执行，也不能把请求转换成用户批准。可信 Executor 的 reviewer、approval_check、package_check、预算及恢复回调均只由受保护 host 提供；注册回调不等于具备模型执行器或用户认证机制。本模块没有实现这些可信服务，也不替代 T09 的门禁。

## 只读部署预检

退出码固定为 `2`，输出 `status:not_verified`、`enforced:false`、`may_apply:false`。模板仅表示部署意图；不能用于签发隔离完成。profile 中加入 `verified`、`probe_result` 等额外字段会记录拒绝；即便给出合法模板及完美工具目录也不会通过。实际工具目录必须由可信 host 从 transport 注册表获取，静态 JSON 文件不证明真实宿主只暴露这些工具。`os.access` 只是当前进程可写风险线索，在 Windows 上不能作为 ACL 验收证据。

本版不提供“上传探针报告即签发通过”的 API，也没有自动启用生产部署的开关。未来 backend 接入需提交真实实现、认证证据来源和独立验收测试；不得只改 profile 或模型报告使状态变为 verified。

## 真实 backend 后续验收与回退

当前无可执行的 OS 变更方案，因此不请求或修改真实权限。工具部署前应提交具体 reviewable host 配置：关闭模型的 shell/通用文件/代码执行和自定义工具注册；四角色使用固定认证通道；模型仅能访问网关；Executor 独立出站可信路径；代码、规则、配置、凭据及 journal 由用户/host 管理。回退为停止模型 transport 并恢复用户原工作流；不开放旁路 shell 作为自动降级。

在专属临时树中，由**实际模型受限身份/进程**执行下列探针，并由受保护 host 在树外保存结果和前后字节哈希：

1. Worker 成功写自己候选；Reviewer/Auditor 可读授权夹具；Coordinator 可发送调度数据。
2. 每个角色实际尝试 shell、正式库写、规则/检查器/运行器修改、journal/批准/报告伪造及注册身份替换；要求系统或真实 transport 拒绝，正式字节不变。
3. 从候选路径、读取路径和 scope 执行绝对路径、路径穿越、junction/symlink/hardlink 逃逸；要求拒绝，受保护字节不变。
4. 从所有可用入口（文件、代码、缓存、日志、模型插件、子代理）验证没有同权限旁路；枚举实际工具注册表及 backend 版本/配置。
5. 由独立可信 Executor 在临时正式库通过已有 T09 正向/恢复回归，模型不能持有其凭据；用户直接编辑仍可用且冲突会被保留。

探针必须真的在受限 backend 中运行；模型自报“拒绝”、测试替身抛 PermissionError 或静态清单都不能认证实际隔离。当前代码仅作路径逐次检查，不能对抗恶意本地进程并发切换路径；生产还须保证候选树及授权目录的祖先路径不受模型/非可信进程修改，或使用经过验证的 handle-based backend。缺少这些能力继续保持 not_verified。

## 可复现测试

测试仅使用临时夹具。硬链接和 Windows junction 使用真实文件系统验证；symlink 如无系统权限则明确 skip。另有“当前进程仍可直接写临时正式库”的反证用例，确保不会以网关拒绝替代宿主验收。测试不安装 sandbox，不配置用户/ACL/服务，不读写真实 raw 或业务状态。
