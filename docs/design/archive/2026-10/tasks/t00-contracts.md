---
type: meta
title: "T00 公共契约与规则映射"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T00 公共契约与规则映射

## 状态与目标

已验收；阶段 P0。v1.0 契约、规则映射、状态表与 16 个正反样例已交付；18 项测试中 17 通过，1 项因 symlink 创建权限跳过。发布记录见 `tools/wiki_runtime/contracts/RUN-T00.md`。文件与凭据真实性仍由后续门禁和执行器保证。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：无；这是其他任务的接口前提。
- 必读：`AGENTS.md`；总方案第二、五、七、九、十二节；`tools/health.py` 的检查入口；既有 ADR-0001。
- 契约交付需包含字段定义、失败行为和有效/无效样例，再由协调者发布冻结版本。

## 修改范围与产物

允许修改：`tools/wiki_runtime/contracts/`、`tools/tests/test_runtime_contracts.py`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：资料包、operation manifest、候选清单、依赖快照、门禁报告、审查报告、申诉报告、执行结果的字段与有效/无效样例；状态转换表；规则 ID 到 AGENTS 条目及检查器的映射。

不做：不实现适配器、模型调用、正式写入或修改 AGENTS。

## 验收条件

1. 契约可机器校验；未知主版本、未知操作、缺少必需字段均拒绝，提供可运行验证命令。
2. 明确 UTF-8/原始字节哈希、路径规范、必须不存在前提、候选摘要计算和版本失效规则；摘要不能依赖 JSON 键顺序。
3. 区分强制规则与推荐项；processed_into 争议保留记录，以 AGENTS 为当前正本，不擅改 ADR。
4. 分清模型输出与可信凭据：模型 JSON 只能表达请求或意见，不能自行授予权限或通过。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：新增契约验证命令及 `-B -m unittest discover -s tools/tests -p test_runtime_contracts.py -v`。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
