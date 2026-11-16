# 已审知识候选正式入库：接线任务书

> 公开设计摘编：保留通用契约与方案；历史验收、用户反馈、运行记录及本地素材不随仓库发布。设计条目不代表部署或验收完成。
日期：2026-11-12。状态：用户已授权实施，专用知识准入及临时库验收完成，见本次验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-candidate-admission/README.md）。前置的 K4 后连接修复验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-integration-fix/README.md）当时仅完成候选接收和咨询审阅、正式非教学 ingest 仍关闭；本次补上独立准入，不修改历史结论，不另设 K5。

## 1. 目标与约束

让外部 Agent 已经准备好的、经过 K2 核验及候选审阅的**同一份知识候选**，能由可信宿主交给现有 Executor，以事务方式写入 wiki，并把本批 raw 标为 `pending_review`。无需创建课程、完成学习或伪造 L2／Readiness；用户另行要求“先学后入库”时，必须保留该次顺序约束。

成功写入只表示本次 ingest 完成。raw 从 `unprocessed` 迁移到 `processed` 仍属于另一次 approve，必须有用户对该批次的明确确认，不能由本次入库授权顺带执行。

初始实施、故障注入和验收全部使用临时库、合成来源及合成审阅 transport；不操作正式 raw／wiki、当前课程、真实 API 和既有预算账本。验收通过也不自动申请或签发当前真实库的授权。

## 2. 为什么不能直接解除关闭状态

| 已核对的实际接口 | 当前限制 | 必须处理的结果 |
| --- | --- | --- |
| [knowledge_candidate.py](../../tools/wiki_runtime/host/knowledge_candidate.py) 的 adopt／review_adopted；[supervisor.py](../../tools/wiki_runtime/host/supervisor.py) 的 apply_pending | `reviewed_for_transfer` 只是可交接审阅，apply 分支主动关闭 | 不能把保存的 opinion 或 operator_supplied K2 观察直接当正式权限 |
| [RuntimeService](../../tools/wiki_runtime/runtime/service.py) 的 build_admission／_maintenance_binding | 学习 Admission 需要学习授权／Readiness；维护绑定明确拒绝 ingest | 增加有明确类型的非教学准入；不改 operation_type 套用 derived 或维护入口 |
| [Executor](../../tools/wiki_runtime/executor/core.py) 的 _check／_listing／_assert_all | 默认 CandidateView 扫整个非控制目录，WAL 的目录与恢复也使用该范围 | `knowledge_content` 的正式检查、提交、WAL 和恢复必须使用同一个已绑定范围；只改预览或构造函数不够 |
| [ContentView](../../tools/wiki_runtime/evidence/content_view.py) 的 content_scope／_scan_content | 完整读取 wiki/raw、AGENTS 及规则映射，有界且不提供 Executor 准入 | 把内容范围作为显式可信配置复用，不能把 preview 的 `executorAdmission=false` 改成 true 来签发权限 |
| [迁移规则](../../tools/wiki_runtime/runtime/migration.py) 的 _check_executor_apply／assert_runtime_creation_allowed | freeze 后只允许登记的旧操作恢复或新的受管操作 | 新入口须通过实际切变检查；不能仅设置 runtime_managed 即认为准入通过 |
| [Executor](../../tools/wiki_runtime/executor/core.py) 的 _review、现有 InvocationPort | 学习受管 G3 有持久 Invocation；普通旧分支不是同一种准入协议 | 新路径须保留明确预算、调用身份、重放／unknown 规则和最终 G3；不沿用一个“通过”布尔值 |

这些限制是代码中的实际约束，不是新增业务要求。目标是补上“知识路线进入现有正式事务”的连接，不重写知识核验、课程系统或任务循环。

## 3. 最小实现方向

```text
已接收的候选＋K2／原件／旧知识依据
                    ↓
可信宿主确认本次整理意图及精确写入范围
                    ↓
Runtime 非教学准入绑定＋现有任务／预算／所有权
                    ↓
Executor 同范围 G0–G2＋实际候选 G3＋最终动态重检
                    ↓
现有 WAL 批量写入／回滚
                    ↓
wiki 配套页面成功 → raw 最后标 pending_review
                    ↓
另一次用户确认 → 现有 approve（本任务不自动执行）
```

### 3.1 非教学准入是独立业务类型

复用当前 RuntimeStore、Task／Run、PolicyRevision、ExecutionOwnership、InvocationPort 和 Executor；不新增常驻 Agent、通用工作流引擎、第二套预算或数据库服务。

准入至少绑定：

- operation、Task／Run、policy、submission epoch、ownership generation。
- 原始候选、manifest、依赖快照、规则／映射／验证器／审阅版本摘要。
- K2 知识包及观察、preview request、候选覆盖和实际 raw／来源版本。
- 精确 allowed_paths、明确的内容范围标识，以及可信宿主本次允许执行 ingest 的依据。
- 本次是否存在“先学后入库”顺序限制及其真实解除依据；缺失时不能默认为已学习。

采用封闭协议，禁止同 operation 改绑候选、准备包、写入范围或授权上下文。不能只从 intent 文本、外部 JSON 的 `confirmed=true`、K2 的 `reviewedBy` 或模型输出推导用户授权。宿主可信配置／已授权入口才可接纳本次任务；其安全保证仍是现有本地可信宿主模型，不宣称抵御同权限恶意进程。

实现应先确定协议落点，再改接线：学习 Admission、知识准入和维护绑定必须可区分，旧维护入口仍不能接收任意 ingest。新记录可与既有 Runtime 数据共存，旧记录读取、备份和恢复必须测试；不得为了复用而伪造课程或学习状态。

### 3.2 正式视图、事务与恢复共用一个范围

默认沿用完整 `knowledge_content`：递归 wiki/raw、AGENTS、规则映射。它包含任意分类子目录及来源附件；references、运行环境等在范围外，不作为本次知识依赖，也不得被候选写入。

允许范围来自可信实现，不接受候选自传任意 glob／视图类。检查和实际写入使用同一范围；WAL 必须记录可验证的范围身份。重启恢复使用 WAL 原范围，不能因新进程参数改成全库或缩成 touched paths。范围内新增、删除、内容变化、大小写碰撞及链接／重解析点按当前规则停止；范围外无关文件变化不应导致一轮知识操作扫描大型运行环境。

复用现有 WAL／锁／原子替换／冲突保留／逆序回滚。raw 状态最后写入，配套来源页、反向边、索引、日志和 overview 任一失败都不能留下已完成状态。恢复只处理已接受的原 WAL；不依赖仍有效的模型配置、未过期的新提交授权或重新生成候选。

### 3.3 最终审阅与费用

接收后的内容审阅仍可用于人工 inspect；正式提交必须获得与实际最终 request 绑定的 G3。由可信代码核验 Invocation 及完整 request，不能只采信 pending 中一份 recommend_pass。预算、角色、原文、原页和候选必须实际可追溯。

优先只做一次必要的正式 G3；若复用已有调用，须证明其完整 request、版本、scope 和成功 Invocation 完全相同，并在提交前重验依赖。不能仅凭文本 opinion 升格、扩大历史调用范围，或将 unknown 当成可重试失败。若无法合法复用，应明确计入新增调用，不为了省 token 放宽检查。

本任务无真实模型调用授权要求：验收 transport 明确为合成。实际使用时再按具体资料、供应商和既有费用授权核对，不沿用架构课外发许可。

### 3.4 入口与状态

Host 增加明确知识入库操作，复用已接收的同一 operation／payload；不调用 Worker 重生成，不借旧普通 `run_operation(ingest)` 进入。可信宿主方法与 owner CLI 可以接入；不能自动把准入签发注册成外部模型工具。

inspect 继续区分冻结历史、当前有效性、独立意见、是否有本次有效准入、真实 Executor 结果。`reviewed_for_transfer` 不直接改成 `applied`。Runtime 的“已应用”必须从真实 WAL 核对归并，禁止仅依靠 pending 字段。终态重放只返回原执行事实，不能因库已变化而刷新原前提或重复写入。

暂停／撤销／policy 或 ownership 变化在 prepare 接受前必须生效。已接受 WAL 的恢复按现有事务责任执行，不能用撤销卡住回滚。重复同 ID 不重复 Worker／G3／写入；冲突不静默覆盖或换 ID 重发。

## 4. 实施顺序与验收

1. **固定准入协议和信任入口。** 写出正向样例及缺授权／错类型／错包／错范围负例；明确学习、非教学知识和维护路径的分支。先证明不会重新开放旧普通 ingest。
2. **接通 Executor 范围。** 将内容范围贯穿检查、目录枚举、WAL、终态查找与恢复，保留旧默认行为；用范围外大型文件、范围内变化及重启参数变化验证。
3. **接通 Runtime／Host。** 绑定原接收记录、当前 K2／raw／旧知识依赖、真实 G3 Invocation 及动态准入；提交时再核对，失败不得刷新绑定。真实执行结果归并必须核 WAL。
4. **临时库跑完整链。** 标准 capture 薄 raw 和普通原文各走 K2 → preview → adopt → inspect／review → admit／apply → pending_review；课程与 L2 全程不存在。保留来源页／知识页双通道反向边及索引等实际字节。
5. **故障及兼容性验收。** 覆盖下表；仅因新代码、新失败或尚未覆盖的风险增加测试，不无条件重跑所有历史流程。

| 必须验证的情形 | 期望结果 |
| --- | --- |
| 无课程、无学习完成声明的有效知识任务 | 临时库成功 pending_review，不创建学习状态来凑准入 |
| 未核验／冲突未处理／缺 G3／伪造 opinion／非宿主准入 | 正式字节不变；明确缺失条件 |
| 同 operation 换候选、K2 包、raw、规则、scope 或 Task／Run | 拒绝改绑；不能刷新旧通过 |
| 实际范围被扩大，payload 篡改，索引／日志／回边缺失 | G0–G3 或准入拒绝，无正式变更 |
| 内容范围内新文件／分类移动／原文变化 | 原候选失效；合法分类移动不当作知识语义变化或要求用户移回 |
| 范围外 references／运行文件新增或变化 | 不扫描为知识基线，不因此刷新范围；不允许写入这些路径 |
| G3 超时／unknown／预算耗尽及重启 | 不重置费用、不换 ID 自动重发、不接受未知结果 |
| G3 后或 acceptance 前 policy／ownership／依赖失效 | prepare 前停止；正式字节不变 |
| 首次提交成功、同 ID 再次 apply | 原终态，无重复模型调用、日志或 raw 元数据写入 |
| 关键 WAL 点进程退出、重启及重复 recover | 原批次完整恢复；不重跑模型或重新签发准入 |
| 恢复中用户改了目标页或事务备份 | 保留外部字节、报告 conflict；不静默覆盖 |
| freeze 前后／旧 pending 未清／已完成 cutover | 不吸收旧身份，新受管操作只在允许条件下推进 |
| 成功 ingest 后自动移动 raw 到 processed 或伪造 reviewed_at | 拒绝；本任务不代替用户 approve |
| 现有学习 ingest、derived、维护、approve 与旧 WAL | 原协议边界及行为保留；新入口不能成为旧路径绕过通道 |

最终交付包含代码、命令工作单、实际分次测试输出、费用口径、故障恢复证据和新的验收清单。精确区分临时库正式事务通过与真实库业务使用；不自动升级旧 A01–A33 状态。记录历史 acceptance 仍保留原字节，并列出因本次改动而变化的已绑定文件。
## 5. 本文件当前完成点

专用知识准入、同范围 Executor／WAL／恢复、Host／owner CLI 接线已实现；101 个不同检查有最终通过依据，其中 18 个新增检查，分次原始错误与修正复跑保留。独立复核发现的咨询回包并发覆盖授权问题已修复关闭。当前没有后台测试或活动 Goal，未提交／推送；压缩后先读[执行交接](knowledge-candidate-admission-handoff.md)及本次 acceptance，不重做 K0–K4。

临时库使用真实事务实现验收，不是对当前正式库的执行许可或真实语义认证。当前专用入口只支持明确 knowledge_only；learn_first 继续拒绝未知解除条件，processed 仍须独立 approve。真实资料应用、API 外发与费用须按对应任务授权，不能套用本次临时库范围。
