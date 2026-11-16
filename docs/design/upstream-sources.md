---
type: meta
title: 上游学习应用来源清单
status: active
updated: 2026-11-16
topic: 上游选型的来源、固定版本与再分发边界
related_sources: []
related_synthesis: []
---

# 上游学习应用来源清单

> 本清单是上游选型与原始研究的来源基准。所有引用上游源码的结论都绑定到下表的固定提交；本仓库不搬运上游源码副本，只保留来源、版本、许可与定位路径。

## 一、研究范围与取用约定

- 研究性质：**只读源码审查**。没有部署、没有选定、也没有在运行时验证任何上游项目。
- 取用方式：浅克隆（`depth=1`，`filter=blob:none`，无 tag），按默认分支检出；克隆完成后核对 HEAD 与本清单记录的提交一致，工作区保持干净。
- 源码副本存放于本地研究工作区的 `references/upstream/<name>`，该目录被忽略，**不随本仓库发布**。公开版以本清单为准。
- 证据索引（路径→符号→行号的检索产物）体积约 1.09 MB，同样不随本仓库发布；正文中的定位以「仓库 + 固定提交 + 文件路径 + 行号」表达。

## 二、来源、固定版本与许可

| 项目 | 仓库 | 固定提交 | 提交日期 | 分支 | 根许可 | 跟踪文件数 |
| --- | --- | --- | --- | --- | --- | --- |
| OpenMAIC | [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) | `cee7b7ff3b7f3ef16acc5b1c8f3b4c6ada8ab4a0` | 2026-11-09 | main | MIT | 4248 |
| DeepTutor | [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor) | `60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db` | 2026-11-06 | main | Apache-2.0 | 4530 |
| open-notebook | [lfnovo/open-notebook](https://github.com/lfnovo/open-notebook) | `a6b572eb9849785dfb7c747190a01b0bb99fedf2` | 2026-11-08 | main | MIT | 657 |
| kotaemon | [Cinnamon/kotaemon](https://github.com/Cinnamon/kotaemon) | `9ad3e4e49aa35b8acddd235918a5d9753c1cfdf9` | 2026-05-30 | main | Apache-2.0 | 414 |
| lattice | [vimalinx/lattice](https://github.com/vimalinx/lattice) | `762b00cb028ad1a86ee505db4ca5ed14103657ac` | 2026-11-09 | main | MIT | 636 |
| open-notebook-mcp | [Epochal-dev/open-notebook-mcp](https://github.com/Epochal-dev/open-notebook-mcp) | `a2cddbf65cba8c4c8de7be16566781b7612a9545` | 2025-12-22 | main | MIT | 19 |
| deepseek-harness | [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | `39163dd30f703a79079e2d2446545cff3c453738` | 2026-11-13 | master | MIT | 21632 |
| rederive | [EricJujianZou/rederive](https://github.com/EricJujianZou/rederive) | `7f43edc0ee0e098e98f77b01187027238aba77c8` | 2026-10-26 | master | MIT | 15 |
| admit-only-what-rederives | [veriker/admit-only-what-rederives](https://github.com/veriker/admit-only-what-rederives) | `2641c748f9556cb955da26bdf64a0ce148539fd8` | 2026-06-17 | main | Apache-2.0 | 258 |
| audit-and-rederive | [jxzhang97/audit-and-rederive](https://github.com/jxzhang97/audit-and-rederive) | `414d78f1d0abb46738adf0706c98c9a55031d40c` | 2026-08-05 | main | 待确认 | 5 |

`audit-and-rederive` 的根许可字段在原始记录中即为非 ASCII 字符、无法可靠还原，且仓库根目录未观察到许可文件；引用其代码前需单独确认许可，本文不据此推断任何授权。

## 三、引用方式

正文与评审记录中引用上游源码时，采用固定提交永久链接，形式为：

```
https://github.com/<owner>/<repo>/blob/<commit>/<path-in-repo>
```

这样做同时满足三件事：读者可自行核对原文；结论不被上游后续提交漂移；本仓库无需搬运任何上游源码副本。少数链接带行号或区间（如「第 729、779 行」），行号对应上表的固定提交。

## 四、审查覆盖与限制

| 项目 | 审查方式 | 运行验证 |
| --- | --- | --- |
| OpenMAIC / DeepTutor / open-notebook / kotaemon / lattice / open-notebook-mcp / rederive / admit-only-what-rederives / audit-and-rederive | 定向静态源码审查，**非穷尽** | 未运行：未安装依赖、未启动应用、未执行其测试 |
| deepseek-harness | 定向静态审查 + 12 项离线源码算法探针（路由与存储替身） | 未运行上游测试套件、完整运行时、模型 API 与原生沙箱 |

因此：这些仓库的结论是**源码口径**，不是运行口径。涉及运行行为、真实模型表现、原生沙箱与权限隔离的判断，本文只能给出「源码如此」，不能给出「实测如此」。下游方案中凡引用本清单结论处，都应保留这一限制。

## 五、相关入口

- [上游源码对照与架构选型建议](upstream-learning-architecture-review.md)：首轮六项目对照。
- [源码研究与架构建议任务手册](upstream-learning-source-research-playbook.md)：研究方法与交付约定。
- [研究目录](research/upstream-learning/README.md)：证据方法、产物与未公开范围。
