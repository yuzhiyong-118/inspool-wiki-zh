---
type: meta
title: "T10 运行权限隔离验证"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T10 运行权限隔离验证

## 状态与目标

最新决定（2026-10-26）：用户接受宿主权限无法全面约束的限制，停止继续实现或验证强制隔离。本任务按范围收敛关闭；保留已实现网关、桥接与测试。以下未通过记录保留为历史证据，不再阻塞协作门禁交付，不改记为强制隔离已通过。

原型及通用原生桥接已实现、待实际宿主验收；阶段 P3。受限工具网关及预检由协调者独立运行 20 项测试（19 通过、1 项权限跳过）。InheritedTransport 已校验固定角色、新子会话、请求绑定、严格 JSON 与超时，AgentSession 已统一维护和只读入口；默认继承主 Agent 模型，不要求独立 API。当前开发宿主仍共享 workspace-write，预检保持 not_verified / may_apply:false；具体产品的受限 dispatcher 与绕过测试待完成，桥接测试不能替代实际隔离验收。

## 依赖与最小上下文

2026-10-26 再验收：Codex 实际只读后端拒写复测通过，六类角色经 Native 桥接均在 RPC 前拒绝；完整工具隔离证据仍不足，T10 未通过最终验收。官方 Hook 存在错误时放行及覆盖范围限制，不能替代强制边界。实测与来源见 `tools/wiki_runtime/host/ACCEPTANCE.md`；依赖本项的 [t11-entrypoint-rollout](t11-entrypoint-rollout.md) 真实模型闭环保持阻塞。

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T09](t09-executor-recovery.md)，均须验收并交付接口摘要。
- 必读：Executor 的可信边界与部署要求；总方案第八节；实际宿主与工具权限信息。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/isolation/`、`tools/tests/test_permission_isolation.py`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：Windows 原生受限进程/账户或受限工具方案比较与选型证据；临时沙箱启动器；绕过测试与部署前提。

不做：不直接变更用户账户、主库 ACL、服务或全局环境；不将独立上下文误当权限隔离。

## 验收条件

1. 从 Worker/Reviewer/Coordinator 权限尝试 shell 直写、改检查器、造凭据、路径链接逃逸均拒绝。
2. Executor 可在授权范围内写，用户手动编辑不受破坏；缺平台能力时明确阻塞，不跳过验收。
3. 只在临时测试树配置权限；修改真实目录 ACL、账户或服务配置前必须给出具体变更和回退方案，再按授权条件执行。
4. 测试若与模型实际宿主权限不一致，报告限定结论；尚未完成 T11 时不宣称全入口守护。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：交付宿主对应的隔离/绕过测试命令；不支持的平台应明确 skip 原因并保持验收未通过。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
