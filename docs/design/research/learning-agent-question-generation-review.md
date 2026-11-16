---
type: meta
title: 学习应用出题与反馈机制复核
status: historical_record
updated: 2026-11-12
topic: 学习应用出题研究复核
related_sources: []
related_synthesis: []
---

# 学习应用出题与反馈机制复核

> 本文为历史设计记录，随设计迁移整理发布。文中状态与验收计数对应原文写作时点的环境，不代表当前部署或验收完成。私人证据未随本仓库发布，引用处以「证据未公开，无法由本仓库独立复核」标注；本机路径已抽象为占位符，执行时替换为实际路径。

日期：2026-11-12。配套阅读：[三个约束参考项目复核](question-constraint-reference-review.md)、[当前出题约束方案](../learning-question-constraint-plan.md)。

本轮直接读取本地固定版本源码，覆盖出题输入、生成、结构检查、展示、作答与反馈的重要路径。未安装、启动或执行这些项目，未调用模型，未复现教学效果或 token 收益。以下结论限定于所列源码路径，不将旧研究报告的验收结论作为本轮证据。

## 1. 总体判断

值得吸收，尤其是 **OpenMAIC 的结构化题目及局部编辑、Lattice 的形成性小题和分级提示、DeepTutor 的有界参考题生成**。它们与 rederive 的问题地图可以互补，没有必要因此换掉当前 DeepTutor 底座。

应当把“教学方法”与“题目生产方式”区分开。递进约束、例题渐退、反例辨析可以用于不同题目；定稿导入、生成变式、对话小题则有不同的发布、校验和证据要求。无需为每一种组合另建引擎或插件平台。

## 2. 本地版本与角色

本轮核对 HEAD 及所读文件内容，见源码清单（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-agent-question-generation-review/source-manifest.json）。

| 项目 | 固定 HEAD | 本轮所见角色与借鉴点 |
| --- | --- | --- |
| DeepTutor | `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db` | 章节上下文／参考模板驱动的生成、结构检查、有限修复；当前底座 |
| OpenMAIC | `cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0` | 考点与题型配置、结构化题目、局部修改、选择题本地评分与短答模型评分分离 |
| Lattice | `762b00cb028ad1a86ee505db4ca5ed14103657ac` | 对话题块、先答后评、支线反馈回主线、提示渐进与例题渐退 |
| open-notebook | `a6b572eb9849785dfb7c747190a01b0bb99fedf2` | 来源转化为持久 insight，可作准备材料生成机制；不是现成测验判分链 |
| kotaemon | `9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9` | 有限近期上下文生成后续问题建议；不是考核题 |
| open-notebook-mcp | `a2cddbf65cba8c4c8de7be16566781b7612a9545` | 检索／问答连接层；所读公开问答入口并非课程出题接口 |

后面三个项目的负面结论只针对本轮所读入口，未声称其全部扩展中都不存在测验功能。

## 3. DeepTutor：保留生成能力，明确模板不是定稿

依据：[Book QuizGenerator](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/book/blocks/quiz.py)、[QuestionPipeline](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/pipeline.py)、[中文出题提示](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/deeptutor/agents/question/prompts/zh/pipeline.yaml)、[QuizBlock](https://github.com/HKUDS/DeepTutor/blob/60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db/web/app/(workspace)/learning/books/components/blocks/QuizBlock.tsx)。

- `QuizGenerator._generate` 将章节标题、摘要、学习目标并入 topic，调用 QuestionPipeline，提取题目、选项、答案与解释。它返回的来源锚点列表在该路径中为空；配置了知识库不等于每一道题已绑定来源证据。
- `pipeline.py:547–553` 的 mimic 模式跳过 Explore 与 Plan，以参考模板作为计划；`_render_reference_block` 将参考题与答案注入提示，然后仍进入模型生成循环。
- `_collect_quiz_issues` 检查必要字段、题型结构、A–D 选项键和答案键等；失败后可调用一次修复并再次检查。不能据此证明题目命中了目标、场景成立或答案受来源支持。
- 模板的 `question_id` 被沿用，但题干、选项、答案仍可能变化。稳定 ID 不代表内容版本相同。
- Book 的 QuizBlock 对选择题按答案键本地比较；非选择题支持揭示答案与自评。自评不能当作模型批改或独立掌握证据。

**我们已吸收的部分：**[I6 补丁](../../../patches/deeptutor/i6/prepared-quiz.patch)与[prepare_quiz](../../../tools/learning_book/production.py)已接入六字段预审参考模板，限制选择题和数量，并收紧生成循环／工具。跳过探索规划不是这次才提出的新优化。

**进一步建议：**变式题继续走有界生成，补明确目标／来源条件及最终内容审查；外部 Agent 已经交付完整审校题时，考虑受管的定稿发布路径，减少再次改写。当前 `engine.py` 的 `_EDITABLE_BLOCK_TYPES` 仅含 TEXT、USER_NOTE、CALLOUT，不能宣称现有通用编辑接口已经能安全导入任意 quiz。需要明确适配入口、题目版本与作答绑定，不能直接写底层课程文件。

## 4. OpenMAIC：结构化题目与生成分离最有价值

依据：[生成器](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/generation/src/scene-generator.ts)、[系统提示](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/generation/templates/quiz-content/system.md)、[用户提示](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/generation/templates/quiz-content/user.md)、[题目类型](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/packages/@openmaic/dsl/src/stage.ts)、[编辑工具](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/agent-runtime/dsl-tools.ts)、[工具使用约定](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/server/agent-runtime/course-tools.ts)。

`generateQuizContent` 接收 outline 的标题、描述、keyPoints、题数、难度与题型配置，调用模型后解析 JSON 并检查选项契约。默认是三道中等单选。提示要求清晰题干、合理干扰项和解释，短答另带 rubric，但提示中的要求不是已执行的语义校验。

其 QuizQuestion 明确区分展示文本 `label`、选项键 `value`、答案 `answer`、解析 `analysis` 和短答评分提示 `commentPrompt`。`patch_stage` 可以对结构化场景局部修改，先验证结果结构再写入；工具约定强调先读目标、最小修改、再读取核对。

**值得吸收：**把题目当作可审阅、可定稿、可局部修订的内容资产，生成只是生产这种资产的一种方式。修改一个选项不应默认重生成整组题或整本课。每次内容修改后是否需要重新审查、旧作答对应哪个版本，由我们的业务契约明确。

评分依据：[grading.ts](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/lib/quiz/grading.ts)、[quiz-view.tsx](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/components/scene-renderers/quiz-view.tsx)、[短答评分路由](https://github.com/THU-MAIC/OpenMAIC/blob/cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0/app/api/quiz-grade/route.ts)。

- 选择题在本地按答案键集合比较；缺失答案不会自动把选择题转成 AI 短答。
- UI 先提交并持久化答案，再评分并保存结果，attemptId 将记录关联起来。
- 短答单独调用模型，可携带评分标准。
- UI 评分异常以及服务端解析异常存在给半分的兜底。此行为不适合我们的证据链：故障应保留未评分／错误状态，不能自动形成得分或掌握证据。

**不需要照搬：**整套课堂系统、全部题型或数据库；也没有从所读路径发现自动证明题目受原始来源支持的完整机制。它解决了内容工程的一部分，没有替我们解决来源忠实性。

## 5. Lattice：小题服务于教学，不必每道都升级为正式考核

依据：[展示块协议](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/agents/blocks.md)、[tutor](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/agents/tutor.md)、[flash](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/agents/flash.md)、[coach](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/agents/coach.md)、[题块展示](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/ui/blocks.js)、[提交处理](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/ui/app.js)、[对话桥接](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/bridge/turns.py)。

`lattice:quiz` 是 question 加可选 options；没有 options 时是自由作答。该展示契约没有预先绑定的答案键。提示要求先让学习者作答，再给答案和讲评。主会话小题可交给 flash 简短判断，answered 与 judged 记录关联原会话，主会话随后读取短反馈继续讲解。

这适合形成性诊断，例如“如果这个条件改变，会怎样”。它不同于带冻结答案键的已审测验；LLM 讲评也不能不经审查就作为知识准入或掌握结论。

**另一个有价值的机制：**[例题渐退](https://github.com/vimalinx/lattice/blob/762b00cb028ad1a86ee505db4ca5ed14103657ac/lattice/skills/worked-examples/SKILL.md)按完整例题、相似题、部分填空、独立完成、条件变式递进；coach 用分级提示，并允许用户明确请求答案时解释。它能补充 rederive，避免把所有课程都做成不断追问却不讲解的模式。这里是原项目的教学设计，未在本轮证明其教学效果。

**适配方式：**先借鉴题块、反馈摘要和提示策略，不必先新增一个独立 Agent。内部教学消费者也可完成这些职责；只有支线延迟、上下文与成本测量显示有益时，才拆出专门讲评角色。保留一套学习状态，不引入另一个可写进度库或复制 Lattice 的 Qt／工具执行框架。

## 6. 其他项目：准备与引导机制

- **open-notebook**：[run_transformation](https://github.com/lfnovo/open-notebook/blob/a6b572eb9849785dfb7c747190a01b0bb99fedf2/open_notebook/graphs/transformation.py)把来源全文或指定文本转成 insight，拒绝空输入、空输出以及被长度限制截断的响应，成功后保存衍生产物。可借鉴“完整生成后才保存准备材料”，但它输出文本，没有在该入口提供正式题目 schema、答案键或题目来源证明；全文输入也不自动等于省 token。
- **kotaemon**：[SuggestFollowupQuesPipeline](https://github.com/Cinnamon/kotaemon/blob/9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9/libs/ktem/ktem/reasoning/prompt_optimization/suggest_followup_chat.py)取最近三轮对话生成 3–5 个简短后续问题。可借鉴有界上下文和探索方向提示；这些是建议用户问什么，不能当成检验学习者的测验题。
- **open-notebook-mcp**：[公开问答入口](https://github.com/Epochal-dev/open-notebook-mcp/blob/a2cddbf65cba8c4c8de7be16566781b7612a9545/src/open_notebook_mcp/server.py)的 ask_question／ask_simple 是向资料问答后端提问，所读接口不是测验生成和作答回传协议。无需为了出题新增这层依赖。

## 7. 结合三个约束项目后的建议

| 场景 | 生产与消费方式 | 审查与状态 |
| --- | --- | --- |
| 外部 Agent 已提供完整定稿题 | 受管发布并原样消费，避免重复改写 | 固定来源、目标及题目版本；保留作答与版本关联；当前需补入口 |
| 希望生成新场景或变式 | DeepTutor 有界参考题生成 | 结构自动检查，目标／来源／答案语义审查；失败明确退回，修复计入预算 |
| 讲解中的预测、辨析或追问 | Lattice 式轻量题块，可选 rederive 约束递进或例题渐退 | 先答后评，作为教学观察；不自动产生正式掌握或知识准入结论 |

外部 Agent 准备“目标、来源、适用条件、误解、参考题、可选提示”；内部消费者负责展示、收集作答、按已审标准判分和反馈、维护状态。结构化内容、生成流程和教学策略各有明确边界，当前不需要通用插件平台。

对[当前约束方案](../learning-question-constraint-plan.md)的影响：保留约束作为可选教学材料与审查依据，取消“关键词命中即可证明场景正确”和“错误项必须各违反不同约束”的强结论；补最终题目版本绑定；允许维护小范围上游补丁，不为完全不改上游而制造旁路状态。前一份[三项目复核](question-constraint-reference-review.md)的其他修订建议继续适用。

## 8. token 收益与后续验证

有明确机制依据的优化方向包括：已审定稿题不再改写、选择题本地判分、已准备材料跳过重复探索、局部修改代替整组重生成、有界支线上下文与反馈摘要。前两项中的选择题本地比较、参考路径跳过探索规划，在当前底座／补丁中已有基础，不应全部作为新增收益记账。

支线 Agent 可能增加模型往返，来源审查和误拒修复也有成本。只读源码不能给出净节省比例。后续比较应固定来源、目标、题量和审查标准，同时统计最终通过率、总 token、失败与修复成本、用户等待时间。对定稿路径还要核对发布前后内容一致、编辑使旧审查失效、重启与导出保持题目版本。

本轮产物仅为研究报告与源码核对清单；未修改原方案、运行时、配置、课件、raw 或 wiki，也未启动新的实施任务。