---
type: meta
title: DeepSeek Harness：Lattice 执行层候选审查
status: historical_review
updated: 2026-11-16
topic: 上游 Agent Harness 源码审查
related_sources: []
related_synthesis: []
---

# DeepSeek Harness：Lattice 执行层候选审查

> 本文为上游 Harness 审查记录。审查证据（探针结果、原始材料、证据索引）未随本仓库发布；引用上游源码时绑定[上游来源清单](../upstream-sources.md)的固定提交与文件路径。文中结论为源码与离线探针口径，不含上游测试套件、完整运行时、模型 API 与原生沙箱的验证。

日期：2026-11-16。固定提交：`39163dd30f703a79079e2d2446545cff3c453738`，根包版本 `0.2.2-rc.3`，MIT。源码在本地研究工作区的浅克隆目录（不随本仓库发布）；下载和身份已登记[上游来源清单](../upstream-sources.md)。

## 判断

**DSH 核心 harness 能力值得进入隔离适配验证；当前 Python SDK 不能直接无损接替 Lattice 的流式 ApiWorker。** 首要障碍是公开 SDK 通道没有直接单会话取消方法和实时 assistant chunk 通知，不是 Python 启动 Node 的困难。

不支持现在整体替换部署；也不支持直接决定把 DSH 所有机制重新写进 Lattice。先验证一个 Tutor 的必要接口能否通过受支持插件/通道实现，再比较适配与自建的总维护成本。课程领域事务、用户字段保护和教学质量，两个方案都要自己负责。

用户后来提供了四份 ChatGPT 分析；已全文阅读并核验关键主张，详见[独立复核报告](lattice-chatgpt-reports-review-2026-11-16.md)。它们不能相互充当独立证据，也不能由架构图直接推导成本优势。

## 证据范围

- 静态阅读：实际 agent-loop、工具管线与调度、Session 修复、写前检查点、压缩配置及替换事务、Token Meter、SDK 协议/服务/Python Session、默认 profile、Windows 进程与沙箱相关实现/说明。
- 实际执行：probe.mjs（证据未公开，无法由本仓库独立复核：docs/design/evidence/deepseek-harness-review-20261116/probe.mjs），12 项结果（证据未公开，无法由本仓库独立复核：docs/design/evidence/deepseek-harness-review-20261116/probe-results.json）。Node v24.22.1，Node TypeScript transform 运行未改动的上游源文件；导入 façade 只选择用到的真实 llm error/message 辅助；scope routing、注册表、事件投递、存储是替身。载入文件 SHA256 已记录。
- 没有安装 DSH 依赖，没有修改上游，没有调用模型/读取凭据，没有运行完整 SDK、Qt 或原生沙箱，没有真实杀进程恢复实验。12 项通过包含边界/缺陷行为复现，不是产品全绿。
- Wiki 只读 health 为 0 项问题；未通过受控入口写 health 日志，本轮未直接改正式 wiki。

复现：在本知识库根目录执行 `node docs/design/evidence/deepseek-harness-review-20261116/probe.mjs`；需要对应固定源码及 Node >=24.9。探针只把结果写入本证据目录。

## 与 Lattice 问题对照

| 关注点 | DSH 固定源码/探针结果 | 仍不保证 |
|---|---|---|
| 取消链 | agent 当前 phase 持有 AbortController；工具管线融合原始 caller signal 与 wrapper signal；已启动工作先结束，未启动调用返回 ABORTED_BEFORE_DISPATCH | 同进程工具忽略 signal 时无法硬杀；已发生效果不能回滚 |
| 并发 | 仅显式 isConcurrencySafe=true 可并行；独占工具形成屏障；有界池、按模型顺序结算 | 并发声明错误的业务工具仍会竞争；不是跨工具事务 |
| 超时 | timeout-policy 给声明 timeoutMs 的工具传播 deadline；探针中超时 5ms，忽略取消的工具仍运行到结束并写入，然后报告 TOOL_TIMEOUT | 不是硬返回截止时间；未声明 timeout 的工具不自动获得此预算 |
| 恢复 | interruptedTurnClosers 为开口日志补工具结果、step/end、turn/end；区分未开始和结果未知；重复修复闭合日志不再追加 | 不恢复外部进程，不自动重放工具，不提供 exactly-once |
| 写前持久化 | session-checkpoint-policy 在顶层工具 dispatch 前 flush；flush 失败时不执行工具；请求流也有前置检查点 | 只验证了工具侧替身存储顺序；没有测试真实磁盘断电耐久性 |
| 上下文容量 | 模型容量、输出预留、headroom 共同定阈值；默认自动压缩；小窗口须调整策略 | 启发式估算不是硬上限；压力压缩失败可警告后继续请求 |
| 历史摘要 | 压缩选择保留工具配对；先取得更短摘要再替换模型可见面；原始事件仍保留 | 摘要语义准确与教学证据完整需要另验；默认指令面向 coding assistant |
| 计量 | Provider 用量与启发式基线分离；请求 envelope 对齐后使用 usage anchor；可区分缓存读/写 | 缺 usage 无法凭空恢复实际账单；未证明中文估算精度和缓存节费 |
| 整任务预算 | 已定位工具超时、模型输出上限及目标轮次机制 | 没找到可据此声称“所有 SDK 普通会话默认都有整任务金额/调用总数/墙钟上限”的证据；未全仓证明不存在扩展能力 |
| Lattice 批量保存 H2 | 模拟业务工具前一条写入、后一条失败，重试留下两条重复数据 | 换 harness 不自动增加领域原子提交和逻辑操作幂等 |
| Lattice 所有权 H1 | DSH 能承载前置策略，但必须限制全部 fs/shell 能力和资源范围 | workspace-write 仍允许写工作区内部；并不自动保护 Card 字段、skills 或 .git |

## 影响接入的四个具体问题

### 1. SDK 通道与核心能力不同

`packages/sdk/protocol/src/types.ts` 的 RequestMap 与 `packages/sdk/server/src/server.ts:500` 分派包含 initialize、prompt/query、resume、wait、working-directory、shutdown，没有 session/cancel。通知是 session.event/status、query completed、subagent 和用户提问取消，未暴露实时 assistant chunk。服务订阅 durable session/event；核心则在本地发 `agent/assistant-stream`，结算后才写完整 assistant/message/attempt。

因此 Python 的 on_notification 不等于逐 token 流式 UI。已有历史事件中的 stream 也不等于用户当时就收到 chunk。需要自定义插件/通道或更改 SDK 才能满足 Lattice 体验；此处是当前默认 SDK 接口结论，不是声称整个 DSH 无法流式或取消。

Python runtime wheel 文档称封装可执行运行时、不需系统 Node；本轮没有安装 wheel验证分发。不能把“Python 调 Node”本身作为拒绝 DSH 的充分理由。

### 2. 默认 profile 不等价

`bundle/base/cordis.patch.yml` 默认 sandbox-policy 为 workspace-write（环境可覆盖），挂载 token-meter、compaction-basic、timeout-policy、checkpoint-policy 等。

`bundle/sdk-minimal/cordis.patch.yml` 是独立完整树，**默认 danger-full-access**，也有平台 shell、压缩、持久化，不等于“只剩模型循环”或“天然最小权限”。开始原型前必须列清实际启用工具，避免 Lattice 领域入口旁边还有可绕过的任意文件写入。

### 3. Windows 有专门实现，但不能夸大隔离

已定位 subprocess-local 的 Windows Job 管理，以及 sandbox-windows-acl 的受限令牌/ACL实现。文档明确其主要限制写和删，不是等价的读取/联网隔离；还有硬链接等限制，工作区授权会留存部分 ACL 配置。此次仅静态审查，没有对用户目录应用 ACL 或执行原生探针。

结论限于“比 Lattice 直接用户权限执行具有更完整的实现机制”；不声称已证明本机安全隔离。第三方/自定义工具如果绕过该执行路径也不自动受保护。

### 4. 通用压缩须补教学语义

默认 thresholdRatio=0.8、retainRatio=0.16、headroomTokens=65536，按模型及输出容量求有效阈值。小窗口示例探针确认默认配置可因无剩余压力预算而拒绝，需要路由级配置。

`compaction-basic/src/region.ts` 在摘要生成、边界稳定和确实更短检查后写替换事件；`summarizer.ts` 重用历史前缀与工具 schema，可能改善服务端缓存，但不是已测命中率。默认摘要要求英文工程检查点，不是教学档案。需要保留学习目标、首次作答、提示暴露、误解及待验证前提，不能让“完成了代码任务”替代“学习者能迁移”。

## 下一次最小接入实验的门槛

先做接口可行性验证，保持真实 Learning、MiniMax 配置和现有安装不动：

1. 一个 Tutor，会话输入含当前主题及必要课程版本；保留 Lattice 领域工具和 UI。
2. 通过支持的插件边界输出实时 chunk、工具事件、单会话取消与停止确认；不把关闭整个 runtime 当取消。
3. 用同一题目与真实用户提交事件衔接：显示成功不等于回答；answered 由 UI/应用写，AI 只评估。
4. 模拟输出中断、工具取消、持久化失败；确认未知副作用不盲重放，其他会话不受影响。
5. 一个执行历史权威，用户可见 Thread 为产品投影；明确补齐与去重，不重新维护两套完整模型历史。

若必须复制修改大量 DSH 私有内部代码才能完成上述最小路径，适配成本是负面证据；若薄插件即可完成，不能因 Lattice 原先自写就排除采用 DSH。最终比较还需真实教学体验和模型行为，当前没有这部分验收。

本轮交付到候选审查与离线算法验证，没有进行运行时替换或课程迁移。