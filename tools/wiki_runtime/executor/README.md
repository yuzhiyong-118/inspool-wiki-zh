# T09 统一执行与恢复

公共契约 `1.0`；本模块只依赖标准库。它在临时库测试，未修改真实 raw、业务状态、规则或系统 ACL。

```python
from tools.wiki_runtime.executor import Executor, ExecutionError

executor = Executor(
    root, journal_root,
    reviewer=trusted_review_transport,   # T06 transport(envelope, *, timeout)
    reserve_call=reserve_call,           # 零参数；先持久扣全任务预算，成功返回 True
    review_timeout=30,
    remaining_timeout=remaining_timeout, # 可选：零参数，返回 host 剩余秒数
    approval_check=approval_check,       # 可选：可信 host 验证 opaque 用户批准
    package_check=package_check,         # 可选：可信采集来源认证
)
result = executor.apply(loop_result.bundle, approval=opaque_approval,
                        source_packages=())
result = executor.recover(operation_id)  # 未提交批次逆序回滚；已提交不撤销
```

`apply` 接收 T08 的 manifest/candidate/snapshot/payload_root；忽略其中的 reports/review。前置检查失败抛 `ExecutionError` 或底层 `ContractError/ValueError`；准备 WAL 后的可捕获故障返回公共 `execution_result`，状态通常为 `recovery_required`。已完整备份但尚未激活的初始化故障返回 `prepared`、recovery_status=required。真实进程中断直接重启后 recover。相同 operation_id 绑定整份 manifest/candidate/snapshot；已 applied/recovered 的重复操作返回历史结果，无重复写入。恢复后重新应用需新 operation_id 和新检查，不能复活旧事务。

Runtime 受管 ingest 使用 `admission=`，维护操作使用 MaintenanceBinding。锁外 G3 期间不持 Host 线程锁；最终接受按 `executor.lock → SQLite BEGIN IMMEDIATE` 串行，并在完整 WAL 保存前重验 Task／Run、预算、授权、Readiness、知识版本和 fencing。接受前撤销或暂停必须阻止首个 WAL；接受后由 Executor 独立完成或恢复。applied／recovered 先按原绑定查询真实 WAL，不因过期、暂停、预算阻断或库变化重新审查。恢复不依赖 Runtime 或旧租约，旧 journal_root 不变。WAL 持久化 recovery_status；归并核验从 WAL 派生该状态，不使用调用方参数构造预期 conflict。无此字段的旧 WAL 只能按可从 state 唯一派生的状态归并，不能补信自称的 conflict。prepared、applying、recovery_required／conflict、applied、recovered 归并前均核对真实 WAL、原 Admission 和 recovery_status，伪造中间态或终态不能形成第二套接受事实。

Executor 每次重建真实 CandidateView、完整枚举并重跑 G0–G2；根据 requires_review 自行复算 G3，调用者删除 required_gates 无法跳过。即便 T08 已审查，当前也重新调用一次真实 T06 协议；尚未优化为可信签发凭据。缺 reviewer、reserve_call、预算、有效时间或有效意见即拒绝。调用有界、迟到结果丢弃；底层 transport 自己负责取消和网络超时。G4/G5 由本模块计算，可信报告写入私有 journal，不接受文件里的 pass/user_confirmed 作为凭据。

独立入口可注入固定 `deterministic_check(context, view, source_packages)` 重算器，仅在 index_rebuild/health/capture/import 四类机械产物完全匹配时跳过模型审查。ingest、知识回填、规则与工具维护不接受此豁免；不注册为模型工具，也不读取模型的 derived=true 字段。capture 薄来源记录仅在同一重算器验证全部原件、抽取、附件、定位和记录嵌入映射后可替代直接复制正文；其余情况继续严格匹配抽取字节。

普通内容/机械索引更新不增加人工批准；approve、rule_maintenance、tool_maintenance 必须通过 `approval_check(context, opaque_approval) is True`。回调在审查前、审查后和最终 WAL 准备前核验。context 含完整 manifest、manifest_digest、candidate、snapshot、operation_type、从 move 真实源路径推导的 source_paths，以及全部版本/摘要 bindings。host 必须把凭据绑定这个完整 context，拒绝候选、批次、任务、scope、规则、版本变化；凭据撤销必须立即生效。operation_id、authorization_refs 和模型 JSON 均不是认证。回调由未来 trusted host 提供，不允许模型注册自己的检查器；没有入口时默认拒绝。当前开发尚未部署该可信交互进程。

capture/import 缺可信 package_check 时拒绝。source_packages 是 `(source_package, package_root)` 序列；host 回调签认来源身份和与操作的对应关系，Executor 另严格校验契约、包内字节哈希、非空抽取和质量策略，并要求新 raw 正文逐字节来自其中的抽取正文。明确 PDF/音视频、OCR/模型抽取或非 complete 质量转人工。未保留来源类型的既有裸 Markdown 不能可靠恢复原始类型，生产采集 host 必须保留包的来源信息。

当前已用真实 capture + validate_package + 可信 package_check 联测无附件 Markdown，并在 raw/assets 保留原件字节。正文逐字节比较暂不支持附件相对路径重定位；完整附件 capture 布局及 raw/assets 映射须由 T11 集成后验收。二进制附件也尚无 T06 文本审查表示，不能宣称所有已采集输入都可直接正式入库；不得用模型重写正文绕过限制。

写入采用完整 WAL：初始 journal 保存每个原语的新旧字节/base64、SHA-256、备份位置及意图状态，先落盘再动业务文件。write 使用同目录临时文件并 fsync；新文件独占安装。move 为目标写入与源移除两个可恢复步骤，可带 frontmatter payload。ingest 最后才更新 raw pending_review；其他配套页、索引、overview、日志先成功。approve 完成后扫描整个 wiki 的所有文件字节，检查旧 raw 路径残留。每步与 G5 复核未修改的读取依赖、所有目标版本和目录清单。

journal_root 必须在正式库外且不包含正式库，或位于 `.wiki-runtime/executor/` 子目录；不得与 payload 重叠，且须与库同卷。host 必须保护 journal 及运行器代码，向模型只读。跨 journal_root 共用根级 OS advisory 非阻塞互斥锁和 active 指针，未恢复批次阻止新事务。路径逐次拒绝大小写别名、symlink、junction、hardlink，保存前重新检查 journal 根。

恢复先核整批目标，再逐步核对，用户后续编辑会返回 conflict，不自动覆盖其他待恢复页。恢复过程每步也先记录意图，重复恢复可以接续。无关的非目标编辑和新增页不会在回滚时被删除。Windows 现有文件替换使用 ReplaceFileW，同时将**实际被替换**的版本原子保留到私有 journal；删除使用同卷重命名保留实际字节。新文件使用独占 hardlink 安装，随后移除临时链接。若最终哈希检查到替换之间发生编辑，会保存该用户版本并返回 conflict；自动恢复停止，需 host 人工对账。保留备份不自动清理。

这仍是**协作门禁**：没有部署 ACL、独立用户或受限写入工具，同权限 shell 可以绕过或修改脚本/回调/journal。不是目录原子事务，也没有整个文件系统的 compare-and-swap：窄窗口中的编辑可能先被替换，但实际字节被保留并明确报告，不能宣称用户文件在所有时刻都不被替换。非 Windows 的保守替换是先重命名备份再独占安装，存在目标短暂缺失窗口，未作为生产支持承诺。恶意并发重解析路径切换、磁盘断电持久性与同步软件干预尚无 OS 隔离保障。无法认证或备份不完整时必须停止，不能自动降级放行。

故障测试接口 `fault(event, index)` 只供可信测试注入；index 是执行原语编号，初始化/提交为 -1。事件包括 before_prepare/after_prepare/before_active/after_active/after_applying/after_commit、每步 before_intent/after_intent/before_replace/after_replace/after_write/after_done，以及恢复 recover_before_intent/recover_after_intent/recover_after_write/recover_after_done。回调不得由模型控制生产写入过程。测试额外用真实子进程 `os._exit` 验证新文件 hardlink 安装后、临时链接清除前退出：恢复只对 journal 记载且 inode/完整哈希一致的两个链接清理自己的临时链接；陌生或更多硬链接拒绝。部分写入或被修改的临时文件保留为 conflict，需人工对账。

```powershell
& '<用户家目录>/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -B -m unittest discover -s tools/tests -p test_executor_recovery.py -v
```
