---
type: meta
title: I5 Goal 完成与 I6 接续
status: historical_record
updated: 2026-11-11
topic: I5 目标与范围交接
related_sources: []
related_synthesis: []
---

# I5 Goal 完成与 I6 接续

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

I6 后续已完成限定范围闭环，见 I6 最终验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/acceptance.md）与 token 审计（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i6/token-audit.md）。下方是 I5 Goal 完成时交接，原 Goal 结果保持已完成。

更新：2026-11-11。用户授权以 Goal 模式完成 I5。I5-A～E 的产品实现、C01–C20、必要修复及当前字节回归均已完成；最新入口为 统一验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/validated/README.md）、[HANDOFF](../../tools/learning_book/HANDOFF.md)与 [任务书](learning-book-i5-plan.md)。不要继续执行本文件旧稿中已经完成的 C/D/E 待办，也不要重跑 D1–D3 或 S0/S1。

## 当前交付

- 174 项项目测试通过：I3 36、I4 29、A HTTP 14、B 43、C 28、D/E 24；上游 learning-state 25 项源码／wheel 复测、content 19 项、真实 session/SQLite 9 项通过。正常／partial 包、schema、进程实际退出、两进程竞争、Windows junction、移动目录后离线验证、CLI JSON／退出码均已实测。
- 消费者入口是 `Handoff.export_learning_results(...)`／`verify_handoff(...)` 和 export-results／verify-handoff，不是重写通用 Agent。上游继续拥有可写课程／progress，项目只保存不可变证据；raw/wiki/AGENTS 未改。
- 报告和当前源码／样例 hash 以 validated/verification.json 为准。原 A/B/I3/I4 报告冻结，不为后续代码重写旧 hash；final/ 和 acceptance/ 是初期统一试跑，不作为最新交付。
- books wheel 未变化、未安装。固定源在 `<本机验证目录>`；最终 wheel 在 `i5-a-final-v2-wheels`，实际 SHA 为 `7b42c8be75058074e1a4b38daf7046ac7e303f9164733b8fc9b184c19867c21d`，I5-A patch SHA 为 `09992fc36bd05f6d2599bb06f274e1688496b090424558771d5297457908e917`。C 不再加上游过滤补丁。
- 项目真实模型／embedding 调用为 0；未启动既有 API/Web／runtime，未调用任何 generation/compile/quiz-attempt。不使用或重开 I2 已结案额度，不提交／推送。

## 保留的关键取舍

整个导出窗口两端核对内容／资源，中间取进度／所选会话和全部规范事件页，并复核所有边界与实际首次绑定证据。最多三轮，共享并持久化读取限额；未知传输点计量不完整时 fail closed。同 ID 完成后只返回旧事实；新观察使用新 exportId。临时 export-attempts 不是交付，消费者只读完成的 handoffs。

已有 I4 文件逐字节复制，新 refMap 解释旧引用；不改旧 JSON 再声称 hash 相同。原值中的 rawRef/detail/events 等仍为来源内容，不被改写。前轮记录单列，不能混成完整末轮；跨轮已见的同 submission key 冲突仍保留。来源原文 external，附件仅引用，离线验证不回原机器补取。

公开 events 实测可能泄露私有模型 metadata，项目在保存前拒绝整份响应，仅安全错误和 wire hash，明确 partial。legacy events API 的空 complete 不作为全文证据；所选会话完成也不代表全历史。任何历史关联至多 cooperative／submissionContent unknown，缺时间／实际绑定／来源／关键读取依据时 unknown；无掌握或独立作答证明。

完成声明是实际输入归属而非认证，保留 attributedAuthor/submittedBy 和更晚观察，currentCompletion unknown。score、READY、自评或声明不自动 approve 知识。

## 下一步仅为 I6，未授权自动执行

1. 先核对隔离实例的实际安装字节、固定版本／build，以及真实 I3 语料／活动映射；不得拿合成样例或 I2 裸 bookId 代替。
2. 在新的明确范围内串真实资料 → 生产／外部审查／首次基线 → 网页学习／恢复 → I5 导出／搬移／备份 → 外部 Agent 消费。不要把 I5 本地契约通过写成完整生产通过。
3. 真实编译／追问／补题需另定有限模型额度，旧 I2 原 100 万及续测 3 万都已结案，当前额度为不可用。原生首答 500、I2 忠实性问题仍保留，不能重发答案掩盖失败。
4. 固定首期为 Windows/Python 3.12、SQLite／单 worker；PocketBase、多 worker、共享网络目录和其他平台没有因本次通过。

Goal 最终状态以主 Agent 的工具返回为准；剩余 I6 不属于本 Goal。没有新增审批需求或待补用户资料。