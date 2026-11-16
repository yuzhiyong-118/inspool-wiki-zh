# 外部 Agent 课程准备工作单

目标是把经核对的资料交给课件消费者，并交付可复核的学习证据。普通函数／CLI 与原生 HTTP 已足够，执行者不需要读取私有验证脚本。

## 准备与边界

课程规划约定（2026-11-11）：先有限预览资料并查相关 wiki／可用学习记录，提出与用户背景相符的学习方向、目标、范围／排除项、时间深度及检验方式。库中有页面只证明资料可用，不能直接视为用户已掌握；用户说明、实际作答和实践证据分别引用。已有明确意图和有效委托直接复用，关键缺口才澄清，不重复确认相同内容。范围明确且有真实认可依据后再深入整理课件；纯资料整理不必先成课。

将这份学习约定与实际提案、目录及练习对应，审校偏题、遗漏与内容过量。DeepTutor 的确认接口若由 Agent 调用，不自动证明用户认可。范围内补讲沿用约定，新增专题或明显扩大课时须更新认可；已发布内容改动仍遵循原有基线与改版约束。详细设计、待实现字段和验收见[知识准备链任务书 §3.1.1–3.1.2](../../docs/design/knowledge-preparation-plan.md#311-结合知识库制定学习约定)。**目前这是准备者需要执行的工作约定，自动门禁与知识背景比对尚未实现**；不向严格 prepare.json 私加字段，不把整个知识库默认发送给模型。

1. 先暂存用户给出的资料与整理意图。用户明确要求整理、准备入库或生成课程后，再选择需要学习的内容；并非每个链接都自动成课。
2. 记录 sourceId、sourceVersionId、原文 hash、作者／标题／定位和抽取方法。原文只读，学习投影与原文分开；明确缺失、截断和冲突。
3. 按 [I3 契约与示例](README.md)生成 prepare.json、原文及 UTF-8 投影。先运行 `validate`，再 `publish-inputs`，成功后引用实际 corpusReceiptRef `create`。沿用部署和累计预算。
4. 学习目标写成“学完后能判断……、解释……”。题数、题型、不得外扩、字数等属于生成约束，放在明确的准备参数或参考题中；不要把它们塞进学习目标或章节正文。
5. 首次真实试用限定一份短资料、一章、一个选择题。参考题给出题干、选项、唯一答案、逐项依据和原文定位。数值、编号、否定条件和例外优先逐项核对。

## 成课与预审题

`confirm-proposal` 和 `confirm-spine` 使用审查后的提案／目录及实际 revision；后者固定 auto_compile=false。尚未完成内容审校时，先使用纯观察 `/content`，避免提前进入阅读动作触发普通生成。

普通整章编译保留，实际费用随章节、工具和重试变化。若外部准备者已经写好短课正文，可以使用原生 `POST /api/books/insert-block` 的 `compile_now=false` 创建 text／quiz 块，使用原生 `POST /api/books/update-block` 的 body 字段写入已审正文，再只生成参考题。每次写入使用最新 expected_revision、保存完整请求和响应；响应未知先读回，不能盲目重试。准备完成前不要把 pending 章节当可学习成品。这个方式复用现有编辑接口，课程仍由 DeepTutor 保存。

已有题块的预审题使用普通 CLI：

```powershell
& $learnPython -X utf8 -B -m tools.learning_book.cli prepare-quiz --activity <已映射活动ID> --request-id <新的请求ID> --page-id <页面ID> --block-id <quiz块ID> --templates templates.json --expected-revision <当前revision> --deployment .learning-book-runtime/local/deployment.json --state-dir .learning-book-state/local --budget-context .learning-book-runtime/local/budget.json
```

templates.json 为数组，每项严格包含六个非空字符串，1～8 项、ID 唯一、目前仅 choice：

```json
[{"question_id":"lesson-choice-1","topic":"资料主题","question_type":"choice","difficulty":"easy","reference_question":"已核对的题干与 A/B/C/D 选项，并附有限原文依据","reference_answer":"唯一答案与逐项解释、来源定位"}]
```

此入口在请求前校验模板与实际 quiz 目标，传原生 num_questions 和 prepared_templates，复用累计监督、原生生成状态和 I3 不重发语义。相同 ID／相同输入返回已保存响应；输入改变拒绝；未知写入保留待核对。生成仍可能改写例子或解释，参考题不等于输出质量保证。

## 审校、学习和消费

按原文分别核对正文、目标、题干、唯一答案、解释和例外；发现来源外规则、条件颠倒或编号错误时先修正，再采集 I4 基线并记录审查。普通生成与预审题路径分别记录实际调用、输入／输出、缓存和实报／估算 tokens；不要从一次短题测量推算所有课程成本。

课件聊天只引用所选页并使用已有知识库。现有用户显式工具选择继续生效；短资料可由用户在原生设置中选择所需工具，避免无关研究工具。预审题路径已省去重复 Explore／Plan，并使用既有 builtin whitelist；聊天上下文和工具开销应根据实际 call_id 数据再收紧，不删来源来制造低用量。

用户亲自阅读、答题、追问和重开页面后，选择实际公开会话，按 [HANDOFF](HANDOFF.md)导出并 verify-handoff。消费者保留 unknown／partial、原始作答、消息及 JSON pointer；分清原判分、条件复核与掌握判断，不把模拟作答或 Agent 自测写成用户学习事实。

给下一位执行者：先读本工作单、LOCAL_USE 和当前验收报告，核对实际 runtime 状态与剩余额度；只在用户明确学习意图范围内准备课程。交付资料包、各次回执、审查、用量与交接候选；知识库入库和 approve 继续按 AGENTS.md 执行。
