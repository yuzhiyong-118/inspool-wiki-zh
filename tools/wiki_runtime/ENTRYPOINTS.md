# 入口迁移清单

脚本与 11 个规则入口已按协作门禁范围交付。下表说明已接管路径与保留的可信兼容接口；完整宿主强制隔离不在当前交付范围。当前设计与限制以 [设计入口](../../docs/design/README.md) 为准，历史任务记录（`docs/design/archive/2026-10/development-tasks.md`，随设计迁移批次发布）供追溯。可信运行器、规则、授权、报告及 journal 不应由模型角色写入。
脚本与 11 个规则入口已按协作门禁范围交付。下表说明已接管路径与保留的可信兼容接口；完整宿主强制隔离不在当前交付范围。当前设计与限制以 [设计入口](../../docs/design/README.md) 为准，[历史任务记录](../../docs/design/archive/2026-10/development-tasks.md) 供追溯。可信运行器、规则、授权、报告及 journal 不应由模型角色写入。

| 入口 | 当前行为 | 接入目标 |
|---|---|---|
| runtime capture / host import-package | capture 生成 MD/微信 HTML/PDF 候选包；complete MD/微信可由受信 import-package 经 Executor 登记 unprocessed 并保存原件/附件/清单 | PDF/partial 仍暂停，不得改扩展名绕过抽取审阅 |
| runtime prepare/check | 冻结候选、完整依赖与 G0–G2 检查；结果不是批准 | 保留只读检查路径；应用只交 Executor |
| evidence operations-cli | `inspect-task` 只读导航，`describe-input` 生成同一工作单契约，`prepare-next` 仅串接固定私有机械步骤 | 原文登记、模型、课程 POST、admit/apply/approve 和预算变更仍走各自独立授权入口；纯学习路线不登记 wiki Runtime 任务 |
| Coordinator API | 处理、独立审查、申诉、有限重试；只返回 bundle | 由可信 host 绑定角色、工具与预算，不让模型编辑运行状态 |
| Executor API | 重新检查、受信回调认证、可恢复应用 | 只提供给可信 host，不作为模型可自行调用的任意写工具 |
| health 默认 / --json | 只读检查 | 继续零 LLM；无需假写入事务 |
| health --save / --write-graph / --graph-only | 已接管：显式 --state-dir 后委托 host 确定性候选与 Executor；缺少参数拒绝 | 保存/重建成功后保留健康检查退出码；graph-only 也检查并追加日志，但退出码只表示应用结果 |
| raw_index 默认 | 只读预览 | 保留预览 |
| raw_index --write | 已接管：显式 --state-dir 后委托 host raw-index 与 Executor；缺少参数拒绝 | 保留手写区域与依赖重验；不需要模型 |
| refresh_index(apply=True) Python API | 公开与私有直写均已永久拒绝；只读预览保留 | 正式更新使用 raw_index --write 的 Runtime 受管入口 |
| heal 默认 / --plan | 只读建议；显式计划导出限候选区，不造桩、不自动改链 | AgentSession.heal 重新核验计划与锁内基线，Worker、独立 Reviewer、Executor 共享预算 |
| heal --apply / run_heal(dry_run=False) | CLI 及公开／私有 Python 直写均已拒绝；只读预览保留 | 正式修复使用 host/HEAL.md 的 Runtime 受管接入 |
| 微信 --raw / --out | --raw 要求库外 state/candidate，完整来源包经 Executor；--out 仅库外普通新 MD | 缺附件等 partial 停候选；原始字节和来源清单保留，详见 host/WECHAT.md |
| ingest / inspool / lint 修复 / 改名合并 | skills/命令已迁移为受控路由；缺真实 dispatcher 时停止需模型审查的应用 | Worker 候选 → 门禁/审查 → Executor；不能由命令名称决定跳审 |
| approve | skill/命令已要求可信批准绑定，用户继续开发不构成批准 | 可信确认绑定完整批次/候选/依赖/规则，执行器迁移及全文回链自检 |
| query / lint 检查 | 已有只读 answer_query 与 AgentSession.query/lint，独立审查，无自动写入 | 日志、缓存、回填另走受控候选，不创建假事务 |
| Codex inspect / 显式 draft | 现有登录及父模型继承已实测；独立只读草稿成功；没有 apply 入口 | host/CODEX.md；Native 默认因无完整工具关闭证明而停止，不接 Executor |
| 父仓库 source-command skills（历史迁移记录） | 迁移前由旧父仓库通过 `tools/wiki_runtime/rollout/skills` 的部署工具下发 5 个 skills 与命令；该部署器、清单与恢复工具不随本仓库发布 | 当前入口已本地化到本仓库 `.agents/skills/`（未随本仓库发布：agents/skills） 与 `.claude/commands/`（未随本仓库发布：claude/commands），直接按仓库内文件使用，不依赖父仓库部署工具；真实宿主仍需另行绑定 |
| 父仓库 source-command skills | 5 skills、5 父命令及 1 本地 ingest 命令已部署，全部目标等于候选哈希 | rollout/skills 保存清单、显式 owner 部署/恢复工具和部署说明；真实宿主尚需接入 |

## 接入验收缺口

- 默认采用宿主原生 SubAgent，继承主 Agent 模型并隔离上下文、工具权限；InheritedTransport 和 AgentSession 已实现，具体产品的受限子会话 dispatcher 与权限验收仍待完成，API 模型不是前置条件。详见 host/HOST-INTEGRATION.md。
- 已有可选 API transport、本地批准、JSONL 后端及派生操作模块；模块存在不代表目标宿主已部署。模型提供的 pass JSON、profile.verified 或 human_confirmed 不能替代可信授权和实际隔离证据。
- 当前 Codex app 子代理共享 workspace-write。仅新增脚本与 SubAgent 不能阻止 shell 绕过，实际强制隔离必须从宿主工具能力或进程权限落实。开发环境权限不能被当作生产角色权限。
- PDF 首版 partial，不能从扩展名变为 MD 就自动进入知识生成。需要可信保留原类型及多模态审阅条件。
- host import-package 已整体处理 raw/assets 原件、抽取、附件与来源清单，raw 薄记录和队列同批应用；微信 URL 已接入该流程，但不自动下载外部附件，PDF 与其他格式也不能据此宣称无缝支持。
- 旧 CLI 写入口还存在时不能宣称全入口守护；若某入口尚未接入，生产模型不能获得该入口或泛化 shell 的调用能力。

上线前须用实际后端从各角色尝试正式写入、改规则/检查器、伪造批准、日志/缓存旁路和路径链接逃逸。网关单元测试仅验证网关本身；没有实际宿主证据时，强制隔离验收仍未通过。
