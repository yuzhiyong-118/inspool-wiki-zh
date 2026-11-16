# I5-A 严格学习状态只读补丁

固定 DeepTutor `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`／1.7.2，累计 I4 content 补丁，增加 `GET /api/books/{book_id}/learning-state`。I4 的文件和历史证据保持冻结；本目录的 manifest 记录 I4 基础 patch/wheel、I5 增量 patch 和所属模块。

新增 helper 位于 `deeptutor/book/learning_state_read.py`，路由仍由已有 Book 权限解析选择 canonical content 与当前 reader learning store。两处增量均属于上游 `books.json` 的 paths，因此本次仅构建 books wheel；未改 core/server 模块、权限模型或生成流程。

接口逐项返回 `valid/missing/invalid/unreadable/changed`、`valueAcquired`、`coverage` 和安全诊断。有效 JSON 原值不经过 Progress 序列化；损坏成员不删除，不补分数／答案／timestamp；legacy 缺字段使 coverage partial。有效空对象和缺失分开。own 映射严格读取原 manifest；shared 只读取当前读者 overlay，不回退作者状态。canonical manifest 不可用时返回 409；无权限／未知书沿用 404。

严格 JSON 拒绝重复键、非有限数和非法 UTF-8；每项上限 16 MiB。拒绝所选存储根以外的路径和符号链接／junction／reparse 重定向。比较路径和打开句柄的文件身份、大小、mtime，检测可见替换／删除；Windows 的 ctime API 差异不参与跨句柄比较。它是逐项观测，不是跨文件事务或 ABA 防护。

从项目根执行，使用已准备依赖的 Python 3.12 venv；本次实际只验收 Windows/Python 3.12，不扩大为各平台通过：

```powershell
python -B patches/deeptutor/i5/prepare.py --source <原始固定源码> --output <尚不存在的隔离树>
python -B patches/deeptutor/i5/test_learning_state.py --source <隔离树> --report <源码测试报告.json>
python -B patches/deeptutor/i5/build.py --source <隔离树> --output <尚不存在的wheel目录>
# 将 wheel 解包到另一个新目录，再运行同一测试脚本：
python -B patches/deeptutor/i5/test_learning_state.py --source <wheel解包目录> --report <wheel测试报告.json>
python -B patches/deeptutor/test_readonly_content.py --source <wheel解包目录> --report <I4兼容报告.json>
python -B patches/deeptutor/i5/verify_delivery.py --source <最终隔离树> --original-source <原始固定源码> --wheel <本次实际wheel文件>
```

准备脚本逐项校验 I4 前置与应用后字节；构建使用上游模块脚本、`PIP_NO_INDEX=1`、无依赖安装，检查 wheel 内三份累计目标文件的实际字节。不安装、不编辑 site-packages、不启动既有实例。不同构建的 ZIP 时间戳可能使 wheel hash 改变，须记录各自实际值。

实际身份、报告及后续入口见 I5-A 验收（未随公开仓库附带）。项目使用独立 `learningStateReadBuild`，兼容旧 `contentReadBuild`；二者都不进入 I3 scope digest。构建配置是操作者绑定，不是服务端安装证明。真实安装／认证中间件与生产闭环留 I6。
实际身份、报告及后续入口见 I5-A 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i5/README.md）。项目使用独立 `learningStateReadBuild`，兼容旧 `contentReadBuild`；二者都不进入 I3 scope digest。构建配置是操作者绑定，不是服务端安装证明。真实安装／认证中间件与生产闭环留 I6。
