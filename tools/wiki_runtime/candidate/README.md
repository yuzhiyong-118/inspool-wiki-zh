# T02 只读候选视图

依赖公共契约 v1.0，`schemas.json` SHA-256 为
`6bc99b80b4f94257303fe73c94f19ce9ea793f4ee7261d0dec75489c26f8a507`。

```python
from tools.wiki_runtime.candidate import CandidateView, CandidateError

view = CandidateView(root, candidate, payload_root)
text = view.read_text('wiki/index.md')  # 默认严格 UTF-8
paths = list(view.iter_paths('wiki'))  # 根相对 POSIX 字符串，递归且排序
with view.materialize() as validation_root:
    # 在此运行只读 health；validation_root 是新建的独立临时目录。
    pass
snapshot = view.dependency_snapshot()
view.verify_dependencies(snapshot)  # True 或异常；绝不刷新旧前提
```

- `read_bytes` 保留原始字节；`exists` / `is_file` 只查询文件。
- `root` / `payload_root` 是规范化 Path；`candidate` 返回防御复制；
  `candidate_digest` 绑定构造时的候选清单。
- 写入、替换、迁移及可选迁移 payload 均只存在于内存和验证临时副本。
  `source_sha256` 始终核对正式源原件。视图不判断 raw 元数据修改是否合法，
  应交给 G1；真实 raw 从未被本模块写入。
- 删除默认拒绝。`allow_deletes=True` 仅启用视图表达能力，不代表删除授权。
- 正式目标旧哈希、必须不存在前提、读取依赖、payload 哈希均会核验；
  payload 篡改、目录新增、大小写别名、文件父子冲突、硬链接与 reparse
  路径（含 junction）导致拒绝。
- `materialize(*, parent=None)` 仅新建随机临时目录，拒绝在正式根或候选根
  下物化，没有覆盖指定目标的 API；退出时自动清理。消费者应只读临时树。
- 内容视图排除 `.git`、`.wiki-runtime`、`__pycache__` 目录，以及库内的
  payload 根；候选不得以这些目录为目标。空目录不作为文件枚举结果。

构造时记录文件基线哈希，实际读取时再次核对，保证未修改页不会悄悄切换到
新版本。实际读取/枚举会增加依赖，因此运行器应先完成所需读取，再冻结
manifest 的 `dependencies_digest`，报告前再核对摘要与前提。v1 snapshot 只
能表达文件哈希和不存在前提；目录新增检测是同一实例的内部状态，不能经由
snapshot 序列化移交。跨进程恢复应重新构造视图并重新运行检查。

这里的检查只提供路径约束和失效证据，不是 OS 权限隔离，也不宣称消除了
外部进程竞态；后续执行器仍须在受控写入前重新解析与核验。
