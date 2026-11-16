---
type: meta
title: I6 隔离部署与学习闭环
status: historical_record
updated: 2026-11-16
topic: I6 部署与生产学习集成方案
related_sources: []
related_synthesis: []
---

# I6 隔离部署与学习闭环

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

I6 完成后的工程收尾已推进，获授权的六章架构课程已发布、内容审查及新学习前基线通过，见 [本地学习系统收尾计划](learning-book-local-use-closeout-plan.md)及 本轮验收／继续入口（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-closeout/README.md）。用户亲自试学及原生追问待完成；I6 原验收证据保持原字节。

依据 [总任务书](learning-book-implementation-tasks.md)、I5 完整验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）与 I2 最终验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i2-probe/acceptance-final.md）。

当前 I6-A～D 已完成，结论为限定范围有限通过，见 最终验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/acceptance.md）。首次生成质量问题保留，经外部审校的课程已通过基线、原生学习、重启、独立恢复及交接验证。

用户首轮授权 300,000 原始 tokens，200,000 暂停，实际在暂停线以下的实际位点停服（用量见本机账本）。随后用户将累计总额提高到 1,000,000，并要求审计和优化 token；执行者设置 800,000 暂停线。最终共 67 次调用／tokens 见本机账本，账本与基线均沿用，详见 审计（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/token-audit.md）。文本模型为 MiniMax 中国站 minimax-m3，reasoning_effort=none，embedding 为本机 bge-m3。独立 runtime-live 和 .learning-book-state/i6-live 持久保留，API/Web 已停止。

## 验收任务

| 阶段 | 操作与证据 | 进入下一步的条件 |
| --- | --- | --- |
| I6-A 隔离安装 | Windows／Python 3.12／Node 22，固定 DeepTutor 源码、七个原 wheel 和累计补丁 books wheel。新虚拟环境、新运行目录、SQLite 单 worker、独立 loopback 端口。以锁文件安装 Web 依赖并构建生产包，记录实际依赖、wheel 和渲染产物标识。 | 实际安装字节核对，后端及生产 Web 启动，健康／列表／代理与只读接口核对通过。 |
| I6-B 生产与基线 | 选一份自有短资料，先写来源、教学目标及独立核对项。真实 CLI 发布语料和创建活动，显式审查 proposal/spine，保留实际语料和活动映射。显式触发生成，按来源核对正文、题目及资源，通过 I4 外部审查和首次绑定。 | 确定新额度且能观测账本与停止专用进程。课堂内容应达到预先设定的最低质量；失败保留原响应，按实际错误继续诊断。 |
| I6-C 学习与恢复 | 生产 Web 在已绑定课程实际阅读、提交一次有效选择题并发起一次页边追问。记录第一次提交响应、原生 progress、公开会话与内容摘要；停止并重启，核对原值与次数。 | 会话、作答和原始来源可追踪；重启读取不增加模型用量。历史首答 500 或会话不完整如复现，单列缺陷与影响。 |
| I6-D 交接与恢复 | 用实际活动和所选会话执行 I5 导出。复制包到隔离目录并离线校验。实例停机后备份，恢复到独立副本并检查实际 Book／progress／会话；副本使用独立运行路径，禁止模型生成。按 HANDOFF 由外部消费者读取并给出可追溯的知识候选。 | 保留校验、恢复与候选证据。候选可追溯到来源与原始记录，正式知识库保留现行 ingest/approve。 |

## 固定边界

- I6-A 使用空库。安装和接口检查与真实语料、教学质量分别验收。匿名单用户依赖 loopback 与本机访问边界，用户认证、多 worker、PocketBase 和网络共享目录另行验证。
- I2 的生成与续测额度均已结案。开始 I6-B 前需要本轮额度。上游 compile／网页追问也须在独立监控内，使用同一账本和额度。协作计量有延迟，在途调用可能超过暂停线。
- 质量检查至少包括短资料中的关键事实、来源外扩展的标示、正确答案与解释的一致性。实际核对项随选定资料先行落盘。来源丢失、生成占位或题目错误保留原始证据。
- 安装与部署阶段的路径、运行日志、凭据及可能含学习私密信息的运行目录保存在 Git 忽略区。提交范围内只保留去敏记录、校验值和可复验步骤。