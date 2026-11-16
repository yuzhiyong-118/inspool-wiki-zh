# 本地使用收尾补丁

固定上游 `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db`／1.7.2，先继承 I4、I5 和 I6，再应用本目录 closeout.patch；Web 单独应用 web-closeout.patch。`manifest.json` 固定补丁、前后源字节和依赖锁。历史清单不改写。

- 公共 CallMeasurement 接入项目 RuntimeGuard：每个真实模型调用／重试使用原 call_id，账本提交后才结算；原生 SDK 和 services 两条计量路径共用，嵌套计量继续去重。
- Book 编译／重生成在原生 Page JSON 保存 generation、操作 ID、输入摘要、开始／终止及有限旧内容。完成与新 payload 同次原子保存；旧数据兼容，重启识别失去执行者的任务。
- 当前单 worker 内，活跃生成期间拒绝新的课程编辑。页面保留上次完整内容并提供显式重生成；聊天显示确定性原文字符数。
- RuntimeGuard 控制库只保存进程／租约／调用生命周期和账本 floor，没有第二份可编辑课程、答案、进度或 token 账本。

重新准备：

```powershell
python -X utf8 -B patches/deeptutor/closeout/prepare.py --source <固定原始源码> --output <全新构建目录> --with-web
```

构建 Python 时设置 PYTHONUTF8=1、PIP_NO_INDEX=1，用上游 scripts/build_modules.py 构建 core、books、server；knowledge／questions 沿用 I6，parsing／visualize／mastery 沿用固定原 wheel。八模块业务文件不能相互覆盖。完整 Python 依赖固定于 dependencies.lock；当前本机新 venv 已通过离线缓存安装和 pip check。

uv 安装使用 `--link-mode copy`，避免缓存硬链接。真实架构课程导入发现 NLTK 数据文件硬链接会触发上游 pathsec 拒绝；依赖已按相同字节实体化，并在 local_install 增加接入预检。pip check 和业务 wheel 字节核对不能替代这项文件拓扑检查。

Web 在独立源码中的 web 下安装 package-lock 依赖，以 Node 22 执行 scripts/build.mjs。构建使用 Google Geist／Lora 字体，需要已有构建缓存或联网获取；运行只使用 standalone 资产。**构建 node_modules 使用真实目录**：本次发现 junction 会被 Next standalone 带入，发行物核验因此拒绝；实体化后重建为独立资产。不要将外部链接放进交付包。

最终实际 wheel 和逐文件 Web 摘要由本机 `.learning-book-runtime/local/release.json` 记录，公开摘要在收尾验收报告。安装核对 1,110 个模块文件；本次 Web 产物为 3,639 个文件。源码准备另用全新目录重复应用并核对通过。

范围为本机 SQLite／单 worker。新门禁在 LEARNING_BOOK_GUARD 显式配置时启用；正式 runtime 入口始终设置它并运行持续监督，直接绕过入口启动原生程序不属于受管运行。上游原始生成入口仍可使用；本次生成恢复覆盖整页编译和单块重生成，不宣称其他能力也具备相同持久生成协议。
