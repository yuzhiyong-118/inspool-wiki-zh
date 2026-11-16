---
type: meta
title: "T01 MD 与微信候选资料包"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T01 MD 与微信候选资料包

## 状态与目标

已验收；阶段 P1。让 MD 与微信抽取输出标准候选资料包，不直接登记或修改正式 raw。 实际产物与验收记录见任务总表；执行中任务不视为已完成。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T00](t00-contracts.md)，均须验收并交付接口摘要。
- 必读：契约发布记录；`tools/wechat_article.py`；`tools/raw_index.py`；总方案第十二节。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/capture/`（不含 `pdf.py`）、`tools/tests/test_capture_adapters.py`、`tools/tests/fixtures/capture/`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：适配器识别、能力声明、提取和校验入口；保留来源快照、正文、附件、定位与质量报告；离线微信 HTML 夹具。

不做：不在线批量抓取，不改现有微信脚本、raw 队列或现有正文，不负责知识生成。

## 验收条件

1. 原始载荷与派生文本分别哈希，保留原始类型；重复内容和来源修订可区分。
2. 验证页、空正文、截断、附件缺失返回 partial/failed，不当作完整文章；网络失败不算规则失败。
3. 输出限制在指定候选区；路径穿越、绝对输出逃逸拒绝；模块无导入时写入副作用。
4. 适配器发现采用固定注册机制，便于后续 PDF 接入；现有微信脚本暂保留，由 T11 收束旧入口。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：`-B -m unittest discover -s tools/tests -p test_capture_adapters.py -v`；离线样本验证命令由任务交付。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
