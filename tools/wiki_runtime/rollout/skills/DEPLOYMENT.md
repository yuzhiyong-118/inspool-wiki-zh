# 父仓库 skills 与命令入口替换清单

本目录是 T11 的入口部署材料；2026-10-26 已部署全部十一个目标，并通过 deployed 模式核验。`manifest.json` 固定目标的绝对路径、原文件 SHA256、候选 SHA256；`candidates/` 保留同名布局。五个 skill 的发现名称和 description 原样保留，五个父 Claude 命令保留各自 frontmatter，仅作为对应 skill 的短路由；另包含本工作区既有 ingest_raw 命令的同类短路由。本工作区 approve_ingest/inspool/query_wiki 命令不存在，不创建新入口；lint/health 由根任务另行维护。没有改 AGENTS、ADR 或真实 raw。

在仓库根目录执行只读检查：

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B tools/wiki_runtime/rollout/skills/check_bundle.py --mode deployed
```

检查只接受清单固定十一个目标及其对应候选；拒绝路径链接、junction、reparse point、多个硬链接、重复目标、重复 JSON 字段和 hash 漂移。检查器不提供 apply 参数或写能力，也不会自动创建备份。候选/hash 检查证明可部署前提，不能代替内容审查或真实宿主权限验收。

部署由获得父仓库写授权的可信维护者单独执行：先审阅候选和 diff，确认十一个目标精确白名单。显式 owner 工具 `deploy_bundle.py --apply --backup-dir <专用新目录>` 重新运行 pending 检查；按原始字节保留每个目标的独立备份并验证备份 hash；写入前再次检查所有祖先、目标及候选均非链接、hash 未变；只替换列出的十一个文件。备份只允许 `inspool-wiki-zh/.wiki-runtime/rollout-backups/` 下的新命名目录，父目录须预建，不能覆盖已有备份。逐文件状态记录在备份中的 `deployment.json`，失败停止并保留已改和未改状态，不自动回滚覆盖用户编辑。工具不注册给模型，不能以通配符复制整棵 .agents 或 .claude。

这是可信维护者的一次部署工具，要求部署期间不并发编辑这些入口。文件 hash 检查与原子替换之间仍有竞争窗口，不是全局 CAS 或跨文件原子事务，不承诺对恶意并发路径切换安全。替换中断后依据备份和实际目标 hash 对账；不得刷新原始 hash 继续覆盖。独立测试覆盖日志落盘期间编辑、备份期间编辑、部分替换后编辑和 raw/.git 备份路径拒绝。

恢复使用相同参数追加 `--resume`，必须保持原清单与全部原始备份。恢复前全量核验原件、候选、清单身份和逐文件日志；只接受日志允许的原件/候选精确字节，未知修改一律停止。已经应用的文件只核验，不重复覆盖；旧状态日志按内容哈希另存为 `resume-<sha256>.json`。Windows 日志替换仅对短暂共享冲突重试四次，正式目标替换失败则停止对账。恢复既不是刷新前提，也不构成新的 raw 批次批准。

部署后使用同一检查器 `--mode deployed` 验证目标字节等于候选；部署前才使用默认 pending 模式。清单的 prepared_not_deployed 是制包时状态，检查器不更新它，不以修改清单掩盖漂移。本次父目标写入通过显式沙箱升级执行；后续修改仍需对应写权限。

本次原件及逐文件部署记录位于 `.wiki-runtime/rollout-backups/entrypoints-20261026-01/`，清单 SHA256 为 `86d43220aa178844136cea234dbf9896480adf9d907511967f458b7480d36de5`。首次因 Windows 状态日志替换被拒而停止；同一清单、原备份恢复成功，十一项均为 deployed，原失败日志另存哈希历史。最终 deployment.json SHA256 为 `3765db5962e1c53b247987655a4e2ff93899aed7992906a2bd109da826fd59d7`。这些是入口部署证据，不是宿主权限隔离证明。

候选路由保留 ingest 文件/目录参数与 --review、图像/PDF 暂停、query 检索模式及日志字段意图、approve 批次/路径核对与审计意图；去掉模型直接写正式文件、追加日志及迁移的执行方式。ingest 八维分析模式摘要保留在 skill 内，避免引用旧命令形成复制循环；库内 lint 语义说明可按需读取，AGENTS 始终是唯一规则正本，旧命令的直写指令不能越过候选门禁。

实际接入接口为可信宿主的 AgentSession.query/lint 及 maintenance.run_operation（初始 apply=False）；maintenance 和批准接口不注册给模型。语义维护走 Worker 候选、G0–G2、独立 Reviewer、有限修复/申诉、Executor；可信确定性 health、raw-index、capture 导入走固定脚本重算和 Executor，不无条件调用模型。批准必须绑定用户已确认的具体批次、候选、依赖和规则。当前会话的继续或本次入口部署授权不等于批准任何 raw 批次。

默认模型继承，无需额外 API。通用 Python callback 或网关探针不是具体产品的 dispatcher，桌面普通 SubAgent 共享写权限也不是强制隔离。宿主未绑定真实受限 dispatcher 或不能独立审查时，入口停止需审查流程并报告缺口；不得假装已经受控落盘。因此即使部署这十一个入口，T11 的真实宿主/绕过测试仍未验收，不能宣称全入口完成。
