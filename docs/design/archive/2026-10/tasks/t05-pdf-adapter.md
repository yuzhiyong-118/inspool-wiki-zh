---
type: meta
title: "T05 PDF 适配与抽取质量"
status: archived
updated: 2026-10-26
topic: 门禁执行层开发任务
---

> 历史归档：保留 2026-10 的设计评估、实施与验收过程，不作为当前待执行清单。当前结论和阅读入口见 [设计文档 README](../../../README.md)。


# T05 PDF 适配与抽取质量

## 状态与目标

已验收；阶段 P1 扩展。保留 PDF 原件并生成逐页可追溯的派生文本，显式报告无法抽取和多模态限制。 实际产物与验收记录见任务总表；执行中任务不视为已完成。

## 依赖与最小上下文

- 先读工作区 `AGENTS.md` 与 [agent-development-tasks](../development-tasks.md#%E7%8B%AC%E7%AB%8B%E4%B8%8A%E4%B8%8B%E6%96%87%E4%B8%8E%E4%BA%A4%E4%BB%98%E8%A7%84%E5%88%99)，规则以 AGENTS 为准。
- 前置任务：[T04](t04-p1-pilot.md)，均须验收并交付接口摘要。
- 必读：契约及 capture 能力接口；总方案第十二节；`.claude/commands/ingest_raw.md` 的暂停条件；实施时读取 PDF 技能。
- 只加载本任务必要章节、发布的契约及依赖交付摘要，无需继承全部聊天。接口缺口提交协调者，不自行修改公共契约。

## 修改范围与产物

允许修改：`tools/wiki_runtime/capture/pdf.py`、`tools/tests/test_pdf_adapter.py`、`tools/tests/fixtures/pdf/`。这些是拟定路径，当前可能尚不存在。共享初始化、注册及导航由协调者处理；任何范围移交必须先记录。

交付：PDF 能力声明、页码定位、提取质量报告；文本/空白/损坏/加密与图表样本；依赖和安装说明。

不做：首版不承诺全格式表格、OCR、版面理解；不直接改 raw 或注册表共享文件，接入由集成者完成。

## 验收条件

1. 原件字节与页数可核对，文本对应页码，损坏或加密不能输出虚假的 complete。
2. 扫描件或关键图表未处理时报告 partial 和原因；不把普通文本抽取成功等同于阅读顺序完全正确。
3. 原始类型和 OCR 标志继续传给策略，转 MD 不能绕过现有暂停约定。
4. 缺解析依赖时明确 unsupported/环境错误；离线回归不要求付费 OCR 或在线模型。
5. 测试只使用临时库或专属夹具，不改真实 raw 正文、业务状态、AGENTS 或 ADR，不覆盖已有未提交改动。

验收命令：`-B -m unittest discover -s tools/tests -p test_pdf_adapter.py -v`；记录可用与缺依赖两种环境的结果。 使用 [agent-development-tasks](../development-tasks.md#%E9%AA%8C%E6%94%B6%E4%B8%8E%E7%8A%B6%E6%80%81) 中的可用 Python 解释器；新增命令必须在交付时给出完整可复现形式。

## 交付与停止条件

返回任务 ID、契约版本和摘要、修改文件、验证命令与结果、剩余风险和接口建议；完整日志留在专属运行记录。依赖缺失、跨文件所有权冲突、契约变更或需要真实环境授权时，停止相应步骤并报告；可继续不依赖它的本任务工作。开发者不得自行将任务标为最终已验收。

任务总表与批次见 [agent-development-tasks](../development-tasks.md)；设计依据见 [agent-maintenance-plan](../../../maintenance-plan.md)。
