# 受控学习扩展补丁

历史真实验收：`release-19` 完成真实推荐、自定义深入学习、浏览器、I4／I5 与重启验收。父发行固定为 `e1-release-06`，不修改父发行、历史发行物和历史证据。

构建命令（Windows Git Bash 使用 `ROOT=$(pwd -W)`）：

```bash
ROOT=$(pwd -W)
PYTHONPATH="$ROOT" .learning-validation/deeptutor-60fb3bd/closeout/venv/Scripts/python.exe \
  -X utf8 -B patches/deeptutor/controlled-extension/prepare_release.py \
  --base-release .learning-validation/learning-system-next-delivery/e1-release-06 \
  --output .learning-validation/learning-controlled-extension/<新独立目录>
```

新增与组合回归使用 `tools.tests.run_learning_controlled_extension`，必须显式传入候选 `--release` 和新证据 `--output`。实际检查以最新证据目录为准，不能把本文状态当作独立验收结论。

## 能力与请求

能力标识为 `learning-controlled-extension/1`。第一阶段的 `append_blocks` 请求严格包含：

- `book_id`、`page_id`、`operation`、`position`；
- `expected_revision`、`request_id`、`request_digest`、`extension_id`；
- `blocks`：1～3 个新块，每块含 `id/type/title/params/payload`，可带有界 `source_anchors`；
- `extension_binding`：显式 `qualityReview=unreviewed`、操作、活动或本地 Book 绑定、准备与来源摘要。

文本／提示接受原生成器的 `role`、`variant`、`label` 等实际展示字段，适配后仍要求非空 Markdown `body`；题块保留原生 `topic`、难度等已知字段，只接受结构完整的 choice 和新 question ID。未知块、后备正文、空题、旧块／旧题身份、客户端伪造已审状态均拒绝。普通插入一次只允许一道题；补充练习的一组仍只有一个新题块和一道新题。

请求摘要是去除 `request_digest` 后的 `learning-extension-request/1` 规范 JSON 摘要。相同 ID 与摘要返回原结果，改输入冲突。前端在 POST 前持久化完整请求，刷新或失败后先查询原请求；候选已生成时沿用原 ID 提交，结果不确定时禁止重发。GET 对账明确返回 `generating/generated/uncertain/committed`。revision 冲突使用 `/books/retry-extension` 创建显式关联的新提交请求，复用原候选字节且不新增模型调用，关联写入权威响应。applied 权威提交是成功事实，候选确认只是派生状态；查询与启动恢复在身份一致后补齐确认，不能因确认中断把已成功内容误报为不确定。活动生成在恢复期间保持 `generating`；重启后失去所有者的生成请求转为 `uncertain`，不自动重发模型。

## 权威记录与锁顺序

`deeptutor/book/extension_delivery.py` 是扩展唯一提交协调器。每次提交只有一份 `learning-extension-write/1` 权威记录，包含：

- request／extension 身份、内容序号、前驱提交摘要；
- 前后受保护内容摘要和实际 Book revision 边界；
- 本次受影响 Book／spine／Pages 的恢复图像及不存在态；
- 规范化受保护内容变更、响应和显式未审绑定。

恢复图像可以后续拆成有摘要的不可变附件；附件不另生提交真值。候选生成目录不参与 pages 枚举，也不阻断日常读取。只有 prepared 短提交或未决恢复阻断受影响 Book 的内容读取和内容写入。

锁与恢复顺序固定为：**扩展协调锁 → 旧作者恢复 → 旧题目恢复 → 扩展恢复／提交**。旧提交不得持旧 journal 锁再申请扩展锁。启动经原题目 `recover_all()` 进入扩展协调器；同一 Book 出现无法解释的新旧未决写入时保持 uncertain，不按顺序强行覆盖。已 applied 的历史记录只校验，不将旧 Page 图像回写到较新笔记或提交。

原生 `user_note` 通过独立窄差异检查：只允许新增／编辑／删除个人笔记，非笔记块及 Page 其他内容保持；普通正文、旧题、移动和其他原生写入继续拒绝。Progress／submission_id 和 learning-captures 仍走各自原链，恢复不回写它们。

`remove_block` 与 `regenerate_block` 只接受服务端确认的未审 AI 扩展块。删除仅移除目标块；深挖子页、spine 和父页链接保留。重生成仅支持文本、提示和深入学习建议，保持块 ID／类型及既有子页映射，并记录替代关系。扩展测验与原正文、原题不能通过这两个入口删除或重生成。受管课程前端同时隐藏整书重建、整页重生成、移动、类型转换和原正文编辑等未开放操作，服务端保护不依赖前端隐藏。

## 内容链

`tools/learning_book/extensions.py` 是共享确定性契约。受保护投影沿用 I4 的易变字段排除规则，另排除 `learning_extension_head` 操作元数据；`user_note` 作为个人内容单独观察，不进入受保护内容摘要。不能借此忽略正文、旧题、结构或非笔记块变化。

第一条记录以首次基线的受保护摘要为锚，后续记录以前一权威提交摘要为前驱。Book revision 只作乐观并发令牌；失败、暂停、笔记或其他非内容操作造成的跳号不构成内容链断档。完整核验按内容序号重放并比较最终当前投影，目录或文件物理顺序不是链顺序。追加只新增块且 Page 非块字段不变；深挖只允许声明的父子链接、目标映射、合成章节和计数变化；删除与重生成只允许一个目标扩展块的声明差异。每道扩展题按唯一引入提交建索引，后续页面快照只验证不变，不重复登记来源。

普通 GET 只做未决提交与稳定窗口检查。I4／I5、独立验收和需要证明内容关系的恢复边界做完整核验。首轮上限为 1,024 次提交、32 MiB 链证据；超限返回容量诊断，不截断历史。缓存只能是绑定已验证链头的可重建派生数据。

## 单次动作预算

| 操作 | 内容上限 | 新增模型调用上限 |
| --- | --- | --- |
| 已定候选追加 | 3 块；普通测验 1 题 | 0 |
| 文本／提示／建议块生成 | 1 块；建议最多 4 主题 | 1 |
| 普通测验生成 | 1 块、1 题 | 1 |
| 整组补充练习 | 提示＋讲解＋1 道新题 | 3 |
| 删除未审扩展块 | 1 块；不删除其子页或学习记录 | 0 |
| 重生成未审扩展块 | 1 个文本／提示／深入学习建议块；不包括 quiz | 1 |
| 深入学习子页 | 1 页、1 个 section、最多 6 个小节；quiz 不直接随整页发布 | 最多 7 次规划与渲染，8 次硬上限不变 |

每次调用的相关页、选区和必要来源输入不超过 128 KiB，单次输出目标不超过 32 KiB；实际模型上下文和用量仍以运行守卫及账本为准。单块和整组补充使用有界来源规格、固定 choice、禁用工具及单轮生成；每次实际 provider attempt 都在传输前扣减动作预算，文本 helper 不重复扣数，超额重试或修复不得再次请求供应商。失败估算、重试禁止和累计 80 万暂停／100 万上限不变。候选与失败请求不占内容序号。

## 验证分层

1. 旧问题：保存原入口 `question_content_protected` 和笔记覆盖风险的真实行为证据；原有保护负例继续通过。
2. 新功能：接口未实现只记缺失，不冒充旧缺陷；实现后验证真实路由、存储、I5 和原按钮闭环。
3. 新事务故障：prepared、spine、子页、父页、Book、applied 各边界，混合 revision、额外编辑、链缺失／重复／分叉／前驱篡改、并发作答和笔记。
4. 保护性回归：E1／Q3／I3／I4／I5 原有检查保持通过，不要求旧实现先失败。

模型、认证与索引替身逐项标明；合成通过不等于真实教学质量、用户试学或日常部署通过。
