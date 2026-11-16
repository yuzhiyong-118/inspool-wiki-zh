---
type: meta
title: "T08 协调状态机与有限反馈循环"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T08 协调状态机与有限反馈循环

## 状态与目标

已验收；阶段 P2。实现可重放的处理、检查、修复、申诉和停止状态机；调用 Worker 接口。22 项最终联测由协调者独立重跑通过，完整接口与边界见运行时 coordinator/README.md。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T06](t06-content-review.md)、[T07](t07-rule-audit.md)，均须验收并交付接口摘要。
- 必读：T04 公共入口、review/rule_audit 接口、契约；总方案第六、七节。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/coordinator/`、`tools/tests/test_bounded_loop.py`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：可注入 Worker/Reviewer/Auditor 的协调器、预算计数、状态记录与失效检查；假调用端到端场景。

不做：不写正式库、不实现 OS 隔离、不把运行状态写入 processing_status。

## 验收条件

1. 候选最多首次加两次修复；争议默认审查一次；总调用与时间预算跨规则审查保留。
2. 环境错误单独有界重试，未配置执行上限拒绝启动；失败或超时不转通过。
3. 候选、依赖或规则版本改变后旧报告失效；模型不能通过编辑报告或自称通过推进状态。
4. 修复成功、规则有效、规则提案待批准、预算耗尽、审查不可用路径均测试；只有 Executor 可进入实际应用。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：`-B -m unittest discover -s tools/tests -p test_bounded_loop.py -v`。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
