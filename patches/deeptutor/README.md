# DeepTutor I4 最小只读补丁

固定提交 `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`、原版本 1.7.2；本地补丁 ID `inspool-i4-content-1`。仅改 Book 路由和存储两个文件，不改生成／权限模型。不是未修改的官方发行物。模块间 `==1.7.2` 依赖保持兼容，实际身份使用 **base commit＋patch SHA＋wheel SHA**，不能只看版本号／文件名。

- 增加 `GET /api/books/{book_id}/content`，沿用现有权限解析；不调用 resume／compile／progress／chat 写入。不返回 owner 的页边会话映射，也不读共享读者的 learning overlay。
- 独立增加 `list_pages_strict`：逐文件读／验证身份，记录坏 JSON、重复 ID、跨书、文件身份与前后清单变化；路由交叉核对引用和 manifest 页数。错误位置是安全序号，不带运行绝对路径或私有文件名。
- 原整书 GET 保留打开时的恢复行为；Web／生成入口不改。`working=false` 是观测，不是事务锁。

`manifest.json` 固定补丁和目标文件 hash。补丁按 LF 保存；准备脚本校验原始字节，防止父项目 Git 仓库使所有补丁路径被跳过，并检查实际应用结果。

从项目根目录执行，`python` 须为准备好的 Python 3.11–3.14 venv（包含固定模块依赖、setuptools 和 wheel）：

```powershell
python -B patches/deeptutor/prepare_i4.py --source <固定源码目录> --output <不存在的隔离源码目录>
python -B patches/deeptutor/test_readonly_content.py --source <隔离源码目录> --report <测试报告.json>
python -B patches/deeptutor/build_i4.py --source <隔离源码目录> --output <不存在的wheel输出目录>
```

构建使用原始 `scripts/build_modules.py --module books`，设置 `PIP_NO_INDEX=1`，不下载／解析依赖；输出 wheel 和 `build-provenance.json`，不安装。wheel ZIP 中的补丁文件须与构建树逐字节相同。构建工具／ZIP 时间戳可能导致不同 wheel hash，每份实际发行物单独记录。

可将 wheel 解包到独立目录，再传给同一个测试脚本。脚本只叠加解包模块的 namespace 搜索位置，断言实际加载路径，不修改 site-packages。模型和外部连接禁止，仅放行 Windows asyncio 标准库内部 socketpair。

实际构建、源码及解包 wheel 的结果见 I4 验收（未随公开仓库附带）。补丁未安装进 I2 的既有 venv/runtime，未重启既有 API/Web。I6 在隔离实例核对实际安装字节后再填写 `contentReadBuild`；该配置是操作者的构建绑定，不是服务端签名证明。
实际构建、源码及解包 wheel 的结果见 I4 验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-book-i4/README.md）。补丁未安装进 I2 的既有 venv/runtime，未重启既有 API/Web。I6 在隔离实例核对实际安装字节后再填写 `contentReadBuild`；该配置是操作者的构建绑定，不是服务端签名证明。
