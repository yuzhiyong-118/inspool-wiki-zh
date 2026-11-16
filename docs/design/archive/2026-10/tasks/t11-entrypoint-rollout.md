---
type: meta
title: "T11 全部入口接入与最终验收"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T11 全部入口接入与最终验收

## 状态与目标

最新决定（2026-10-26）：用户接受协作门禁的宿主权限限制；本任务按脚本和 11 个入口已部署的范围交付，不再以 T10 强制隔离作为收尾前置。真实 Codex 模型自动闭环未执行，留作可选后续；严格 Native 适配器仍关闭，不因本次取舍强改 verified 或自动启用写库。

入口代码和模板已迁移，未完成真实宿主全量验收；阶段 P4。已提供通用原生桥接、可选 API host、派生操作与只读模块；health 保存/图谱和 raw_index --write 已经 Executor。heal CLI 只读计划、旧 --apply 拒绝，可信 AgentSession.heal 绑定计划与基线并独立审查；微信 --raw 保留原始字节，经完整来源包与 Executor 登记，partial 停候选，--out 限库外新文件。5 个父 skills、5 个父命令及本地 ingest 命令共 11 项已实际部署并核验，原件及部署/恢复日志完整。真实产品 dispatcher 和权限绕过验收仍未完成，不以独立模型 API 替代宿主权限验证。

## 依赖与最小上下文

2026-10-26 再验收：本轮 34 项定向回归通过，其中六项临时库覆盖修复、预算、规则审查、批准与恢复。模型使用测试替身；不能记为真实 Codex 自动维护验收。实际模型完整闭环因 [t10-permission-isolation](t10-permission-isolation.md) 尚未通过而未执行，详细结论见 `tools/wiki_runtime/host/ACCEPTANCE.md`。

首个实际宿主已选 Codex。父模型继承、独立只读草稿和只读后端写拒绝已实测；完整工具能力与旁路验收尚未通过，严格 Native 自动维护未启用，详见 `tools/wiki_runtime/host/CODEX.md`。

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T05](t05-pdf-adapter.md)、[T10](t10-permission-isolation.md)，均须验收并交付接口摘要。
- 必读：全部任务交付摘要；现有 tools、README、命令模板、父仓库 source-command 技能入口；总方案操作矩阵。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wechat_article.py`、`tools/raw_index.py`、`tools/heal.py`、`tools/wiki_runtime/cli.py`（T04 移交后）、`tools/tests/test_runtime_end_to_end.py`；共享文档由协调者合并。。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：capture/ingest/approve/inspool/lint 修复/移动/索引/日志缓存入口矩阵；兼容与迁移说明；质量和调用开销报告。

不做：不顺便修改 AGENTS/ADR，不自动启用 Hermes、计划任务或网络服务，不处理真实 raw 队列来充当测试。

## 验收条件

1. 旧微信 --raw/--out、heal --apply、raw_index --write、health 保存报告/图谱等路径都有明确门禁归属，不能留下旁路。
2. 只读问答和纯确定性索引不无条件唤醒所有模型；新格式通过注册接入，不改知识循环核心。
3. 总方案十二类故障/正向场景、既有回归和输入异常覆盖；报告实际已验证环境与尚存局限。
4. 父仓库只读/越出当前写范围的技能文件不得直接改，准备补丁及部署要求；未接入入口保持禁用或明确阻塞全量验收。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：完整 `-B -m unittest discover -s tools/tests -v`、只读 `tools/health.py`、端到端故障套件；命令与环境写入交付摘要。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
