# 确定性门禁 v1

接口：`run_gates(manifest, candidate, dependency_snapshot, view, *, validator_version='gates-1.0', review_prompt_version='none') -> list[gate_report]`。

采用公共契约 1.0。三个输入先严格校验；畸形契约抛 `ContractError`，不合成缺少可靠绑定的报告。结构合法而绑定、实际文件或读取失败时输出 `fail/error`。报告的生产者字符串不证明可信签发者身份。

调用者应先枚举并读取完整候选视图，再冻结 `dependency_snapshot` 与 manifest。检查结束再次核对实际读取集；检查中新增读取依赖会使旧绑定失效。视图采用 T02 的 `root/read_bytes/materialize/verify_dependencies/dependency_snapshot` 接口，物化使用临时目录，health 使用独立模块实例，避免修改全局根目录。正式库保持只读。

G0 核对契约、操作 ID、规则与映射原始字节摘要、候选及依赖摘要、版本、每个文件前提、移动源/候选哈希、精确路径白名单与操作类型对应路径。普通业务只进入 wiki/raw，规则维护可进入 AGENTS/wiki，工具维护仅进入 tools；白名单仍由可信运行器创建，输入字符串自身不证明授权。

G1 按原始字节边界保护正文，只允许五个流程字段变化。非白名单字段按完整原始字段块比较，注释与空行独立保护；不通过宽容 YAML 解析结果判断相等。只支持保守的标量、字符串列表语法；多行标量、锚点、别名、复杂映射、重复键、未知语法拒绝，需要调用者提交最小明确元数据更新。新二进制附件仅在 capture/import 登记于 raw/assets，既有附件只读。

G2 包装现有 health，补候选页标题/块锚点、索引收录、ingest 新页的内容页入边及指向旧页的双通道反向边、状态/来源映射/配套文件、整组处理、approve 旧路径扫描。原有问题仅对无关未触及目标列基线 warning；raw 字节和 G0 不允许基线豁免。AGENTS 推荐字段缺失保持 warning。反向边仅要求 ingest 新页所关联的旧内容页，不把任意关系强行对称化。正文关系说明的语义质量、事实真实性与冲突判断留给独立审查。`updated` 检查存在且旧页纳入候选；不猜测实际执行日，不伪称验证日期语义。

G0/G1/G2 总是返回。required_gates 中的 G3/G4/G5 输出 unsupported，不能由本工具认证模型审查、用户批准或执行恢复。

只读独立 CLI（输出 JSON，全部通过退出 0、门禁拒绝退出 1、输入错误退出 2）：

路径解析和快照核验不等于操作系统权限隔离；本模块没有 apply，不申请业务批准，不替代未来的写入前重验与事务恢复。
