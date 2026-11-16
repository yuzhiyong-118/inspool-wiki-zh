# /ingest_raw

读取 `AGENTS.md` 作为唯一规则正本，然后按 `../../../.agents/skills/source-command-ingest-raw/SKILL.md` 路由；相对路径从本命令文件目录解析。保留本命令原参数与用户意图。

`/ingest_raw [文件或文件夹] [--review]`；无参数处理下一单元。

需要语义生成或修改的维护由 Worker 提候选，经门禁、独立 Reviewer 与 Executor；可信确定性 health、raw-index 和 capture 导入由固定脚本重算并交 Executor，不无条件调用模型，所有落盘仍受控。模型不得直接写正式文件、日志或迁移 raw。原生子上下文继承主模型，无需独立 API。实际受限 dispatcher/独立审查未绑定时暂停需模型审查的流程；只读脚本和已绑定的可信零 LLM 派生可继续。不能用当前上下文自审或把通用 callback 当作产品已连接。接入详情见 `tools/wiki_runtime/host/HOST-INTEGRATION.md`。
