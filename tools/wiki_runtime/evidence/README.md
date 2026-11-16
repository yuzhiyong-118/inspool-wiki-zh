# 知识证据与本地准备操作

package_protocol.py 保留 S0 的 Source／Evidence／Claim／KnowledgePackage 纯协议。K1 新增 preparation.py 的 inspect_context、verify_context、draft_learning_brief，以及独立 CLI；不改旧协议，不调用模型、网络、DeepTutor 或正式维护执行器。

## K1 能做什么

- 核对 1～3 份明确指定的完整／partial UTF-8 文本及原始字节摘要。
- 先读 wiki/index.md，再从文件名、索引行和双链选择最多 5 篇内容页；递归兼容 sources／entities／concepts／synthesis 的分类子目录。
- 保存完整实际已读文本、字节摘要、查询条件、目录清单摘要、候选与未读数量；未读取页面正文不算全文搜索。
- 将命中记录为未做语义审查的关联候选；相同字节只标 exact_duplicate，不能合并来源身份或推断转载独立性。
- 生成 material_available／unknown 背景观察，及带目标、范围、时间、前置安排的学习约定草案。
- 在草案前重新核对原文、已读页、索引和目录选择条件；变更则返回 stale。

不会据此判断事实正确、知识冲突或用户已掌握。当前不读取 I5 作答／聊天，也不把用户基础全设为不会；外部准备者仍根据实际用户意图提出目标和前置安排。真正的学习记录证据接入、知识语义审校及发布门禁属于后续任务。

## 输入与边界

inspect-context 使用 knowledge-context-request/1：

```json
{
  "schema": "knowledge-context-request/1",
  "learnerId": "本次学习者",
  "queryTerms": ["备份"],
  "sources": [{
    "sourceId": "来源稳定标识",
    "sourceVersionId": "v1",
    "path": "source.md",
    "sha256": "填写原始字节的64位小写SHA256",
    "complete": true,
    "mediaType": "text/markdown"
  }],
  "wikiRefs": [],
  "limits": {"maxPages": 5}
}
```

source.path 是明确 source-root 下的相对路径；只支持 .md／.txt。未知请求字段、重复来源身份、错误摘要、空原件、NUL、非法相对路径、链接／重解析点／硬链接均拒绝。complete=false 的可读文本保留 needs_evidence，不冒充完整核验。

complete 是准备者对所给原件可读范围的声明，K1 只验证实际给出的 UTF-8 字节；不能从扩展名和声明反推出原始 PDF／OCR 身份或缺失内容。采集出处与原始类型需保留在来源资料中，由后续知识准备核对，不能把本地读取通过当作原始来源完整性认证。

初始硬上限：3 个来源、5 篇已读内容页、10,000 个目录项、单文件 1 MiB、总读取 4 MiB、10 秒。limits 可收紧；总读取包括返回前重读，超限不静默截断或跳过。context 序列化内容限 1.5 MiB，防止输出超出后续 CLI 的 2 MiB JSON 输入上限。目录读取不跟随链接，读取前后检查文件身份与字节；保证级别为协作读取，不宣称跨文件原子快照或对抗恶意本机并发替换。

previous 可传上一份完整 context。sourceVersions 继承该链的 ID／版本／字节绑定，最多 256 项，达到上限拒绝继续扩展；同 ID／版本的新内容拒绝，同内容换定位可重新观察。未提供 previous 时无法得知其他调用链历史；没有新增权威注册库、数据库或强制全局幂等保证。

上下文包含 observation 的日期、定位与摘要，因此一次新读取可以产生新观察摘要；sourceId／sourceVersionId／原文字节身份不因此改变。页面没有不可变 ID 时，唯一同名页给出 wiki 链接，歧义页保留当前定位与 pageId=null；不会给分类路径赋予永久语义。目录新增／移动需要重新选择，不能解释为旧知识结论错误。

## 三个 CLI

以下输出仅到 stdout。将其保存到明确的私有工作区；不要重定向到正式 raw／wiki。CLI 本身不创建报告、日志、控制库或批准记录。

```powershell
python -X utf8 -B -m tools.wiki_runtime.evidence.cli inspect-context --wiki-root <包含wiki的根> --source-root <原件目录> --request <inspect-request.json> > <私有工作区/context.json>
python -X utf8 -B -m tools.wiki_runtime.evidence.cli check-context --wiki-root <包含wiki的根> --source-root <原件目录> --context <私有工作区/context.json>
python -X utf8 -B -m tools.wiki_runtime.evidence.cli draft-brief --wiki-root <包含wiki的根> --source-root <原件目录> --context <私有工作区/context.json> --request <brief-request.json>
```

brief-request 的闭合字段为 briefId、version、userIntent、goals、included、excluded、pacing、prerequisites。goals 使用 goalId／outcome／checkMethod；pacing 使用 sessionMinutes／totalMinutes／depth。缺目标、范围、时间或关键前置未明确时返回 needs_clarification，缺目标或范围时 brief=null，不编造课程。有效输出仍是 draft、recognitionRequired=true；userIntent 的归属保证仅为 operator_supplied，不能把草案当作真人已认可。

K1 前置处理只支持计划补讲／待澄清，observationRef 为 null；不会从资料存在推出“已知可用”。已明确无需补讲的知识不必列入待补前置，这不要求用户重学所有基础；以后消费真实用户声明／学习证据时再扩展对应的已知可用判断。

退出码：0 表示 ready_for_review；2 表示 stale／needs_evidence／needs_clarification，保留实际 JSON；3 表示非法或不可读输入。ready_for_review 只表示可供外部准备者审阅，不代表事实或用户认可已通过。

普通 Python 调用使用同名函数；draft_learning_brief 必须传 wiki_root、source_root，先重验实际依赖再构造草案。模块不负责原子持久化或正式写入，调用者后续复用既有应用／Runtime 的保存与调用管理。

可运行合成样例及验收见记录（未随公开仓库附带）；接口依据见[K0](../../../docs/design/knowledge-preparation-k0-contracts.md)。
可运行合成样例及验收见记录（证据未公开，无法由本仓库独立复核：docs/design/evidence/knowledge-preparation-k1/README.md）；接口依据见[K0](../../../docs/design/knowledge-preparation-k0-contracts.md)。
