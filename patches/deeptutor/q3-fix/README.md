# Q3 受管出题与计量修复补丁

固定上游仍为 60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db。此目录在已验 Q2 发行物之上修复三个缺口，不改 Q2 或 Q3 试验的历史产物。持久化协议不变；本地补丁身份为 learning-question-q3-fix/1。

## 修复内容

- QuizGenerator 在提供预审模板时设置 allow_tools=False。QuestionPipeline 的实际工具组合、PageIndex 准备和 dispatch 同时遵守该标记；一般探索／聊天默认行为保持。空 builtin 白名单不再被当作“无工具”的保证。
- 受控书的 BookEngine.kb_drift_report 只观察，不补写 fingerprint、漂移标记或日志。缺基线／旧算法／读取失败明确 unknown；已有可比较基线时返回 drift 或 unchanged。普通旧书继续原维护行为，通用 save_book 和 journal 保护不放宽。
- MeasuredStream 记录终止原因，正常 stop／tool_calls 后关闭不再误记 interrupted；length 记 truncated，提供方错误记 failed，提前取消记 interrupted。终止后缺 trailer 时最多读取16帧、等待1秒；不新增模型请求。
- 活跃 RuntimeGuard 下，流创建失败或结束时缺供应商用量，将估算留账但记录 metering_unknown，拒绝继续调用及用估算解除暂停。非流式历史估算记录不被重新解释或改写。

## 从固定输入构建

```powershell
$fixPython = '<本机验证目录>'
& $fixPython -X utf8 -B patches/deeptutor/q3-fix/prepare_release.py --base-release <本机验证目录> --output <尚不存在的独立输出目录>
```

脚本核对 Q2 的完整发行回执、1,111 个业务文件及八个输入 wheel，应用本目录固定补丁，核对结果字节，重新生成 wheel RECORD，再物化独立 site。只在新的输出目录写入，不安装到已有解释器／日常实例，不调用网络或模型。Windows git 的换行转换在新输出中规范化并按清单重验。

build_patch.py 是维护者从固定 Q2 输入重建补丁的工具；日常安装只运行 prepare_release.py。ZIP 容器摘要以每次实际构建回执为准，不把成员相同宣称为整个 ZIP 位级相同。

## 安装与恢复接线

新部署沿用 questionProductionBuild 的四个封闭字段，patchSha256 使用本目录 manifest 的摘要，moduleSha256 使用实际新 site 的 question_publication.py 原字节摘要。该模块加入 SAFETY_REVISION，使旧 Q2 的能力指纹无法冒充本次修复；完整安全能力由安装／启动的所有文件检查共同保证，不靠常量自我声明。

local_install 仅接受显式 Q2／本修复两条固定清单链，父补丁身份必须吻合；最终文件核对覆盖 pipeline、quiz、engine、metrics、publication 及继承文件。项目接线还钉住 runtime_guard.py。混入任意旧修复文件，即便自行更新安装摘要，也会被固定补丁清单拒绝。

接入、停服备份、独立恢复继续使用已有 local_install／runtime／local_backup，不直接替换已有控制目录中的文件或运行旧备份配置。本轮只构建和隔离验收，**没有升级日常实例**。Q3 隔离新增用量（见本机账本）仍须在下一次模型调用前按call_id接续，不能重置或遗漏。

实际发行物、测试和复核结论见本轮修复验收（未随公开仓库附带）。
实际发行物、测试和复核结论见本轮修复验收（证据未公开，无法由本仓库独立复核：docs/design/evidence/learning-question-q3-fix/README.md）。
