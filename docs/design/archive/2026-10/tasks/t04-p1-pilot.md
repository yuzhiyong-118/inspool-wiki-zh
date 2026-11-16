---
type: meta
title: "T04 P1 集成与无正式写入试点"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T04 P1 集成与无正式写入试点

## 状态与目标

已验收；阶段 P1。用公共入口串联候选资料包、叠加视图与门禁，验证一个索引候选和一个小型 ingest 候选。 实际产物与验收记录见任务总表；执行中任务不视为已完成。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T01](t01-capture-adapters.md)、[T02](t02-candidate-view.md)、[T03](t03-deterministic-gates.md)，均须验收并交付接口摘要。
- 必读：前三项交付摘要、契约发布记录；总方案第十节必测场景。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/cli.py`、`tools/wiki_runtime/__init__.py`、`tools/tests/test_p1_pilot.py`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：prepare/check 命令；临时库端到端夹具；P1 验收报告与接口问题清单。

不做：不实现 Executor，不自动处理真实待入库素材，不推进 pending_review。

## 验收条件

1. 正确候选通过；漏索引、改 raw、缺反向边失败，失败退出码确实阻止后续步骤。
2. 运行前后正式库字节不变，运行产物只在指定运行区；不以测试通过替代实际应用保障。
3. P1 只证明采集和候选检查串联；ingest 候选可使用固定夹具或显式传入，不假装已经接入模型。
4. 冻结可供后续模块依赖的接口版本；修复其他任务文件须先由协调者移交所有权。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：交付 prepare/check 使用示例及 `-B -m unittest discover -s tools/tests -p test_p1_pilot.py -v`。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
