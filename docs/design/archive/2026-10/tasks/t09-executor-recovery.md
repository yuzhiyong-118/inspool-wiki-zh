---
type: meta
title: "T09 统一执行器、授权与恢复"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T09 统一执行器、授权与恢复

## 状态与目标

已验收；阶段 P3。提供 apply/recover、可信回调、哈希前提与 WAL；完整接口和限制见 executor/README.md。协调者全库 199 项回归通过（3 项权限跳过）。没有对真实资料运行 apply/approve，尚未部署强制隔离。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T08](t08-bounded-loop.md)，均须验收并交付接口摘要。
- 必读：全部已冻结契约、总方案第七、八节、AGENTS ingest/approve 顺序；现有 raw_index 接口。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/executor/`、`tools/tests/test_executor_recovery.py`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：应用/恢复接口、可信批准接入协议、操作互斥、journal 和幂等机制；逐步故障注入样本。

不做：不修改真实用户 ACL、不归档真实 pending 批次、不承诺目录树原子事务，不把批准秘密交给模型。

## 验收条件

1. 全部必要报告绑定同一候选、规则、验证器、依赖；模型自造 human_confirmed 和通过 JSON 无效。
2. ingest 配套页面就绪后才 pending_review；approve 必须绑定用户确认批次，迁移后全文检查旧 raw 路径。
3. 每个写入步骤故障可识别和恢复；重复 apply/recover 无重复日志或迁移；用户后续编辑不得覆盖。
4. 本机可信批准接收端与模型进程的边界必须具体说明；若边界未部署则只标协作模式，不声称抵御任意同权限 shell。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：`-B -m unittest discover -s tools/tests -p test_executor_recovery.py -v`；在临时库逐步故障注入。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
