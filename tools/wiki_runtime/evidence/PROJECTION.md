# K3 私有学习投影与知识候选预览

K3 在普通应用模块中消费 K1 context／brief 和 K2 prepared，不新增 Agent、数据库或模型调用。外部准备者物化讲义／原件副本、prepare.json 与候选 payload；应用校验实际内容后输出可保存的 JSON。后续 Web／MCP 可调用同一操作，不依赖外部 Agent 常驻。

## 两条独立操作

```powershell
python -X utf8 -B -m tools.wiki_runtime.evidence.projection_cli build-learning-projection --wiki-root <项目根> --source-root <原件目录> --context <context.json> --knowledge <prepared.json> --brief <brief.json> --request <projection-request.json> --projection-root <私有课程包> --recognition-root <认可依据目录> [--prepare prepare.json] [--recognition <recognition.json>] [--review <projection-review.json>] [--previous <旧投影结果.json>]
python -X utf8 -B -m tools.wiki_runtime.evidence.projection_cli preview-wiki-changes --wiki-root <完整有界基线根> --source-root <原件目录> --context <context.json> --knowledge <prepared.json> --request <preview-request.json> --candidate <candidate.json> --payload-root <候选正文根>
```

JSON 仅输出 stdout；调用者将结果保存到明确的私有工作区。Python 对应 build_learning_projection、preview_wiki_changes。两者不发布课程或改正式文件；会使用自动清理的独立临时目录固定 I3 校验副本或物化候选。退出码 0 分别是限定范围投影已审、候选确定性预览通过；缺认可／缺审／缺证／失效／语义拒绝为 2，非法／不可读输入为 3。**零退出不授予正式接受或课程发布权限。**

K2 必须通过实际依赖重检且 knowledgeState=reviewed_for_scope，才消费其全包；争议包的正常部分先在 K2 显式分包再审，不由投影悄悄丢掉争议。纯知识候选不需要 brief／认可／学习记录，不调用旧 L2 或 validate_final_coverage。

## 学习约定和认可

brief 使用 learning-brief/1，封闭字段遵循 K0，复用 K1 目标、时间、范围及前置约束。背景引用只能指向本 context 的实际观察，可取子集或为空；资料存在不证明掌握。当前 K1 没有 I5／用户实践适配，前置仍只支持计划补讲／待澄清，不用 material_available 签发“已知可用”。目标、范围或时间未明确／关键前置待澄清，保持 needs_clarification。已委托默认时间可先按明确默认形成完整 brief，不自行填空冒充用户认可。

认可附件封闭字段为 id、briefRef、submittedBy、attributedAuthor、recordedAt、statement、defaults、assurance、evidenceRef、scope、acceptedIntent。其字段语义沿用 K0：

- briefRef 精确绑定正文 ID／版本／digest；attributedAuthor 与 brief.learnerId 一致。
- evidenceRef={locator,byteDigest} 指 recognition-root 内实际 UTF-8 文件；statement 必须等于该文件全文（最多 65,536 字符），不凭包内 confirmed 或原生 API 200 放行。
- scope 精确绑定 goalIds／included／excluded／pacing，acceptedIntent 等于本次实际准备的 intent。已有明确意图和范围内委托可记录其原始依据，无需为等价措辞逐次询问；实质扩展先更新约定及依据。
- assurance 仅 operator_supplied。字节、归属字符串和范围相等只验证记录一致，不能认证真人或语义同意。实际投影审阅者必须核对原始要求是否支持该目标、范围和默认值；伪造宿主认证声明拒绝。

缺附件返回 needs_clarification，并且不导出投影；约定引用或实际依据字节变化返回 stale。非法路径、链接／硬链接、声明与实际全文不符则拒绝。

## 原生 prepare 与映射

learning-projection-request/1 的封闭字段为 schema、mapId、version、intent、sourceBindings、coverage、excludedClaims。mapId 非空、version 正整数；sourceBindings／coverage／excludedClaims 的形状见 K0，运行时分别检查：

1. sourceBindings 精确覆盖实际 prepare 来源，不能要求覆盖知识包全部来源。direct_source 绑定实际知识原件版本／原字节；同一知识来源不能重复映射。authored_projection 将外部讲义作为 I3 自身原件，底层依据仍来自 coverage，不把讲义当知识自证，也不允许它覆盖同 sourceId／version 的不同知识原件。
2. 每个目标和实际上传 artifact 都有覆盖；每行有非空 Claim／Evidence，所选 Evidence 是该行已审 Claim 的有效完整支持；direct 模式还要求 Evidence 确来自对应知识原件。未选 Claim 明确列 excludedClaims={claimId,reason}，不得从包中删除。
3. 深度对应 brief.pacing.depth。intent 独立于 prepare.learningGoal 绑定：原生允许实际 create.intent 覆盖建议目标，不能只看建议文字。实际课件生成是否偏题仍需 I4。

外部准备者提供 projection-root 中已有 prepare.json 和实际来源／artifact 文件；操作重新输出已验证的 prepare 及 preparation-map/1。prepare 顶层及成员字段封闭，禁止塞入会被旧原生忽略的认可字段。所有定位先按包内相对路径、安全链、有界 UTF-8 读取校验，拒绝原件包外定位，随后将固定字节写到独立 knowledge-projection-* 临时副本，复用原生 validate_package 取得归一化 manifest／上传字节。原生校验不再无界打开外部可变原件；返回前再次核对实际文件。

当前最多 3 个上传来源、16 个 artifact；使用 K1 单文件 1 MiB、每次固定／重读流程 4 MiB、10 秒限额，预读及重读计入，原生只读这些固定字节。整个操作有数次各自限额的 K1／K2／prepare 重检，不把“单次 Reader 4 MiB”误称整个调用总读取 4 MiB。请求上限 1 MiB，应用输出规范 JSON 上限 1.5 MiB，CLI 输入文件上限 2 MiB。

投影审阅前输出 projectionState=needs_review、draftMapping 和 reviewRequest；正式 mapping=null。draftMapping 只是供人核对的草案，没有 projectionReviewRef，不可当发布包。learning-projection-review-request/1 绑定映射核心、brief／recognition／package／prepare、知识审校依据及**每个实际上传 artifact 的原字节**。

learning-projection-review/1 的封闭字段是 schema、id、requestDigest、reviewedBy、recordedAt、decision、reason、basisRefs、artifactRefs、assurance。basisRefs 等于实际知识审校引用；artifactRefs 精确覆盖实际上传物；assurance 仅 operator_supplied。审阅者读实际全文，检查用户认可范围、目标适切性、条件、遗漏、新事实和判分依据；decision=reviewed_for_scope／needs_evidence／needs_clarification／rejected。新事实回 K2，偏题或扩范围回约定；只审原件不审 artifact 不通过。

通过后 mapping 才增加 projectionReviewRef，并导出 projectionDigest。显式 previous 可继承最多各 256 条 mapVersions／sourceVersions，检查上一份当前身份确实在历史中；同 mapId／version 或上传 sourceId／sourceVersionId 不得换摘要。需要变更就新版本，无 previous 看不到其他链，不声称全局不可变存储。历史和 JSON hash 是协作绑定，不是身份签名。

check_release_request_binding 仅比较调用者提供的实际 intent／归一化 manifest digest 是否对应已审导出，始终 coursePublishAuthorized=false、actualCourseI4StillRequired=true。它没有自动接管现有 I3 CLI，也不重读整条准备链；实际调用前须重新运行 build_learning_projection，并由真实 I3 请求／回执取得这些值。K4 集成前不能宣称现有课程发布入口已被这条新链统一阻断。

## 知识候选预览

wiki-preview-request/1 的字段为 schema、intent、coverageSpec（旧 CoverageSpec）、rawBindings。candidate 使用旧 Candidate 原格式，最多 64 个 write 变更，仅 wiki／raw，暂不接受移动／删除或维护规则代码。内容页以一个已审 Claim 作为旧覆盖协议的主绑定；配套索引／日志／概览／raw 流程更新是 mechanical，不能据此证明这些正文无新增语义，真实候选内容仍需独立维护审查。

每条 teaching_disposition=non_teaching、objective_ref=null；这里只表示本次知识整理不要求教学，不是“机械操作可正式放行”。复用 compile_candidate 生成 state=preview，以及 validate_candidate_coverage 对应路径／动作。不会调用 validate_final_coverage，不产 Assessment、Readiness 或 G3／G4。

rawBindings 每项封闭为 sourceId、rawLocator、byteDigest、bindingMode（whole／body）。要求原件已在完整基线的 raw/unprocessed 登记：byteDigest 核对实际 raw 全字节，whole 模式原件等于 raw 全字节，body 模式通过旧 raw_parts 提取正文并与知识 Source 原字节匹配。每个候选内容 Claim 至少有一个所用支持原件映射；raw 状态变更与声明精确覆盖。私有 source-root 尚未登记 raw 时返回 raw_capture_required／needs_evidence，不能把新建 raw 偷混进 ingest 或改用其他 operationType 绕过。

G0–G2 保留真实 ingest operation_type，复用 CandidateView 的原件／payload／依赖校验以及旧门禁的双通道反向边、索引、日志、overview、raw/index、pending_review 和整组检查。结果保留完整门禁报告，失败不删候选、不改规则、不自动应用；通过只成为 ready_for_semantic_review。previewOnly=true、formalWriteAuthorized=false、readinessIssued=false。

旧视图会扫描完整 root，K3 的有界子类先检查最多 512 个目录／文件项、完整基线 4 MiB、单文件 1 MiB；只跳过视图既有控制目录，不能静默裁掉 references 或只取局部假装全库。每次实际读取保留原始 bytes（含未修改二进制附件），累计重读 64 MiB／20 秒，并沿用路径、别名、链接、目录变化校验。payload-root 必须与基线根互不包含。G2 会临时物化完整有界视图，返回前重新核对目录与知识依赖，属于协作快照。

上述读取限额约束视图预检及视图读取；旧 G2 的 Health 自身还会读取前后基线，不能把视图计数当全部系统读取统计。当前依靠有界完整基线与返回前重检，不承诺恶意并发替换下的硬资源隔离或跨文件原子性。

实际大仓库超过限额会拒绝，须由既有维护入口／后续 K4 处理正式内容基线，不把测试镜像的预览当真实库的 Executor 准入。输出附完整 snapshot／baseline_ref／candidateDigest，但不生成可信 manifest 或授权。业务纯预览的这些确定性报告不能作为正式 G3／用户 approve。

实现与验收见 K3 证据（未随公开仓库附带）。K0–K2 的历史绑定文件不改；新增业务模型 API／网络请求为 0，宿主对话 token 未知，不操作原课程或账本。
