# Wiki 门禁运行时

2026-10-26 用户确认按协作门禁范围交付，接受宿主权限无法全面约束的限制，停止强制隔离开发。现有检查、审查、预算、批准及恢复照常执行；Codex 严格 Native 适配器保持关闭，不把未验证的真实模型闭环记为通过，也不再以此阻塞本轮收尾。

规则正本是工作区 `AGENTS.md`。公共契约见 [契约说明](contracts/README.md)，当前设计与取舍见 [设计文档入口](../../docs/design/README.md)，历史任务记录已归档。本目录的实现按阶段验收，不能因为模块存在就声称正式库已受权限隔离。

## P1 候选采集与检查

以下命令只处理候选与检查记录，不应用正式变更，不推进真实 raw 状态。`capture` 支持本地 Markdown、已保存的微信 HTML 与 PDF。PDF 依赖可选 pypdf，未做 OCR、版面和阅读顺序核验，成功抽取仍为 partial 并保留暂停要求；在线抓取仍是旧微信工具的能力，不能将离线适配器描述为任意 URL 抓取器。

```powershell
# 先检查入口帮助；可使用当前可用 Python 的绝对路径替代 python
python -B tools/wiki_runtime/cli.py --help

# 原件、抽取、附件及定位资料包保存在专用候选区
python -B tools/wiki_runtime/cli.py capture 素材.md --root . --candidate-root .wiki-runtime/packages --package demo-md
python -B tools/wiki_runtime/cli.py capture 微信网页.html --adapter wechat --origin https://mp.weixin.qq.com/s/example --root . --candidate-root .wiki-runtime/packages --package demo-wechat

# candidate.json 是模型或调用方提出的变更清单，payload-root 存放对应载荷
python -B tools/wiki_runtime/cli.py prepare --root . --candidate candidate.json --payload-root candidate-files --run-dir .wiki-runtime/operations/demo-001 --operation-type index_rebuild --allow wiki/index.md
python -B tools/wiki_runtime/cli.py check .wiki-runtime/operations/demo-001
```

`prepare` 复制候选载荷、冻结读取依赖、规则/映射摘要与精确文件范围。运行目录必须尚不存在，库内只允许在 `.wiki-runtime/`；操作 ID 只作追踪。`check` 重新核对依赖与载荷，再在叠加视图上运行 G0–G2。输入新增、删除、编辑或候选篡改会使检查失败，须重新 prepare。

CLI 退出码：0 为本命令成功，1 为质量或门禁未通过，2 为输入/环境/契约错误。结果中的 `applied: false` 表示未应用；`passed` 仅代表本阶段确定性检查，不是内容事实保证、用户批准或正式应用凭据。保存的 JSON 只能作诊断，后续执行器必须重新运行并认证所需检查。

小型 ingest 的来源页、知识页、反向关系、索引、overview、日志、raw/index 和流程字段须同批候选；候选通过后也不能靠本 CLI 移动 raw。approve 继续需要用户对具体批次确认。当前已有任意 shell 的开发环境不构成强制隔离。

## Python 运行接口与部署边界

`coordinator.Coordinator` 已串联处理、G0–G2、独立 Reviewer 与 RuleAuditor，最多三次候选，预算和状态持久保留；详见 `coordinator/README.md`。成功只返回 `ready_to_apply` bundle。

`executor.Executor` 自行重跑门禁和所需 Reviewer，不接受 bundle 内的 pass JSON 作为凭据；通过后使用 WAL 应用，失败按原始字节恢复，遇到用户后续编辑则停止。详见 `executor/README.md` 与 `executor/VALIDATION.md`。host 传入 `reserve_call=coordinator.reserve_call`、`remaining_timeout=coordinator.remaining_timeout` 可将执行阶段的额外审查计入同一任务预算；两个回调均不应成为模型工具。

approve、规则及受信工具维护默认缺可信批准回调就拒绝；capture/import 默认缺可信包认证就拒绝。原始用户批准、作用域、包身份和凭据须由 host 认证，模型不能在 JSON 中声明获得这些权限。当前没有绑定默认付费模型或自动部署批准服务；替身测试不代表真实模型语义质量。

默认让 SubAgent 继承主 Agent 模型，分别隔离上下文和权限；`host.native.InheritedTransport` 已提供固定角色、新会话校验与严格 JSON 桥接，`host.agent.AgentSession` 统一接入维护、只读 query/lint，不要求额外模型或 API 密钥。接入规范与权限矩阵见 [host/HOST-INTEGRATION.md](host/HOST-INTEGRATION.md)。真实产品仍须提供受限子会话 dispatcher；`host run --model-config` 只属于可选 API 部署，不会自动调用当前应用的原生 SubAgent。

目前桌面环境仍为协作门禁。实际宿主角色权限和旧入口的迁移清单见 `ENTRYPOINTS.md`；`.wiki-runtime/` 已被忽略，不应将含原件、模型请求和恢复备份的运行记录提交为知识页。

首个具体宿主选用 Codex，现有登录、真实父模型继承及独立只读草稿已实测，见 [host/CODEX.md](host/CODEX.md)。其 Native 通道因尚无完整工具关闭证明保持拒绝；显式 draft 只返回草稿，不应用正式变更。

旧 `health.py --save/--write-graph/--graph-only` 和 `raw_index.py --write` 已转交确定性候选与 Executor，必须显式添加 `--state-dir <库外同卷私有目录>`。缺少目录参数会拒绝写入，不会自动选择位置。Health 保存与重建成功后仍按本次检查问题返回 0/1；`--graph-only` 以及 `host health --apply` 的退出码仅表示应用结果。

heal 默认只读计划，旧 `--apply` 已拒绝；可信 `AgentSession.heal` 重新绑定计划依赖，经过独立内容审查及 Executor，不自动造桩。详见 [host/HEAL.md](host/HEAL.md)。微信 `--raw` 已转交来源包与 Executor，不完整内容停候选；`--out` 限库外普通新文件。详见 [host/WECHAT.md](host/WECHAT.md)。历史 Python 写函数只为可信调用者保留，不向模型角色开放。操作入口位于本仓库 `.agents/skills/` 与 `.claude/commands/`；宿主绑定与权限隔离需要在实际环境另行验证。
heal 默认只读计划，旧 `--apply` 已拒绝；可信 `AgentSession.heal` 重新绑定计划依赖，经过独立内容审查及 Executor，不自动造桩。详见 [host/HEAL.md](host/HEAL.md)。微信 `--raw` 已转交来源包与 Executor，不完整内容停候选；`--out` 限库外普通新文件。详见 [host/WECHAT.md](host/WECHAT.md)。历史 Python 写函数只为可信调用者保留，不向模型角色开放。父仓库 skills/命令及本地 ingest 命令共 11 个入口已按 `rollout/skills/` 清单部署，备份与日志完整，尚待真实宿主绑定和权限验收。

`python -B tools/wiki_runtime/cli.py host doctor --root <库根>` 默认检查 JSON 后端并报告宿主绑定缺口，不要求 API 配置、不调用模型、不初始化私有状态。`gateway_verified_host_binding_required` 表示网关探针通过，实际受限 dispatcher 仍需宿主实现；不能把此状态解释为生产隔离或正式写入已获批准。

`isolation/` 已提供角色绑定的受限工具网关、部署模板及只读预检，详见 `isolation/README.md`。当前预检明确为 not_verified / may_apply:false；没有实际受限 backend，不能仅修改模板里的字段就启用生产。T11 的脚本与 skills 路由已迁移，目标宿主的受限调用和权限验收仍未完成。

## 回归命令

```powershell
python -B -m tools.wiki_runtime.contracts --examples
python -B -m unittest discover -s tools/tests -v
python -B tools/health.py
git -c core.safecrlf=false diff --check
```

测试使用临时库，覆盖原件保护、路径/载荷篡改、依赖变化、索引和双通道反向边。Windows symlink 创建权限不足的测试会明确跳过；junction/hardlink 检查可独立运行。跳过不能视为该宿主强制隔离已验收。
