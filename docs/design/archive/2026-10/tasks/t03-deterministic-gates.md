---
type: meta
title: "T03 确定性门禁与 health 适配"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T03 确定性门禁与 health 适配

## 状态与目标

已验收；阶段 P1。把现有检查包装为 G0–G2 报告，补齐原文保护、锚点和 ingest 关系检查。 实际产物与验收记录见任务总表；执行中任务不视为已完成。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T00](t00-contracts.md)，均须验收并交付接口摘要。
- 必读：契约发布记录；`tools/health.py`；`tools/raw_index.py`；`tools/tests/test_health.py`；AGENTS 反向边和 raw 规则。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/gates/`、`tools/health.py`、`tools/tests/test_deterministic_gates.py`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：接受快照读取接口的验证器；规则 ID、目标、证据、预期修复的结构化失败报告；现有 CLI 兼容层。

不做：不改 raw_index 生成算法、不重写 test_health.py 来迎合新实现、不将引用存在误称事实正确。

## 验收条件

1. 现有 18 项回归继续通过，health 默认只读，原有退出码语义保留。
2. raw 正文改一字节和非白名单字段修改被拒；允许的流程字段不误报。
3. 无效锚点、新来源缺失、缺反向边、frontmatter/正文只补一边均有失败用例；不把所有关系强行当对称关系。
4. 检查新候选与相关旧页；无关旧问题可列为基线，原文保护和路径授权不能基线豁免。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：`-B -m unittest discover -s tools/tests -p test_health.py -v` 及 `-p test_deterministic_gates.py`；提供只读门禁 CLI。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
