# Q1 离线题目规格示例

这里的 source.md 与 lesson.md 是虚构测试材料，不是正式知识库或真实课件。authored.json 为定稿模式，variant.json 为参考变式模式；invalid/ 中的三个文件应被拒绝。

规格结构见 ../../schemas/question-spec.schema.json。标准库模块 tools.learning_book.question_spec 当前独立于生产入口，不提供发布命令，也不会发送请求或调用模型。

Python 调用示例（从仓库根目录运行）：

```python
from pathlib import Path
from tools.learning_book.question_spec import read_spec, render_variant_template

root = Path("tools/learning_book/examples/questions")
spec = read_spec(root / "variant.json")
template = render_variant_template(
    spec, "baiyu-choice-1",
    source_inputs={"baiyu": {"sourceVersionId": "1", "content": (root / "source.md").read_bytes()}},
    lesson_ref=spec["lessonRef"], lesson_bytes=(root / "lesson.md").read_bytes(),
)
# template 是现有六字段模板；此例到此停止，没有生产副作用。
```

read_spec 有 256 KiB 文件／规范 JSON 上限，拒绝重复键、未知字段、超限及读取中变化。verify_inputs 另核对实际来源、讲义字节和摘录；文件读取本身不等于来源已经验证。

extract_authored 返回定稿题副本并保留选项顺序；spec_digest 和 question_digest 都将定稿的选项顺序显式计入。修改题干、选项、答案或解释需要新审查绑定。

check_question 只查题目结构及指定字面值；没有阻断项时返回 pending_review，semanticStatus 始终是 not_evaluated。不能凭它判断场景成立、答案正确或用户掌握。

运行离线检查使用 unittest tools.tests.test_learning_question_spec。运行时模块只用标准库；Schema 对照测试使用本地已有 jsonschema，不能以跳过该测试的结果宣称 Schema 对照通过。
