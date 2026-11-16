"""核对已安装模块的预审题目路径、原默认路径和工具挂载边界，零模型调用。"""
import asyncio
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class PreparedQuiz(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = TemporaryDirectory(prefix="prepared-quiz-")
        os.environ["DEEPTUTOR_HOME"] = cls.runtime.name

    @classmethod
    def tearDownClass(cls):
        cls.runtime.cleanup()

    def context(self, prepared=True):
        from deeptutor.book.blocks.base import BlockContext
        from deeptutor.book.models import Block, Chapter, Page
        params = {"num_questions": 1, "question_type": "choice"}
        if prepared:
            params["prepared_templates"] = [{
                "question_id": "q1", "topic": "frozen source", "question_type": "choice",
                "difficulty": "easy", "reference_question": "A or B?", "reference_answer": "A",
            }]
        return BlockContext(book_id="bk_test", chapter=Chapter(title="test"),
                            page=Page(), block=Block(type="quiz", params=params),
                            knowledge_bases=["account:kb:test"])

    def test_prepared_reuses_mimic_templates_without_reexploration_kb(self):
        from deeptutor.book.blocks.quiz import QuizGenerator
        from deeptutor.agents.question import pipeline
        result = {"summary": {"results": [{"qa_pair": {"question_id": "q1", "question": "A or B?",
                  "question_type": "choice", "options": {"A": "A", "B": "B"}, "correct_answer": "A"}}]}}
        instance = SimpleNamespace(run=AsyncMock(return_value=result))
        with patch.object(pipeline, "QuestionPipeline", return_value=instance) as constructor:
            _, _, metadata = asyncio.run(QuizGenerator()._generate(self.context()))
        self.assertIsNone(constructor.call_args.kwargs["kb_name"])
        self.assertEqual(constructor.call_args.kwargs["max_quiz_iterations_per_question"], 2)
        self.assertEqual(constructor.call_args.kwargs["builtin_tool_whitelist"], set())
        templates = instance.run.await_args.kwargs["templates_override"]
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0].source, "mimic")
        self.assertEqual(templates[0].reference_answer, "A")
        self.assertEqual(instance.run.await_args.kwargs["context"].knowledge_bases, [])
        self.assertTrue(metadata["prepared_templates"])

    def test_default_preserves_attached_kb_and_normal_pipeline_options(self):
        from deeptutor.book.blocks.quiz import QuizGenerator
        from deeptutor.agents.question import pipeline
        instance = SimpleNamespace(run=AsyncMock(return_value={"summary": {"results": [
            {"qa_pair": {"question": "test"}}]}}))
        with patch.object(pipeline, "QuestionPipeline", return_value=instance) as constructor:
            asyncio.run(QuizGenerator()._generate(self.context(prepared=False)))
        self.assertEqual(constructor.call_args.kwargs, {"language": "en", "kb_name": "account:kb:test"})
        self.assertIsNone(instance.run.await_args.kwargs["templates_override"])

    def test_invalid_reference_count_or_fields_refuses_before_model_pipeline(self):
        from deeptutor.book.blocks.base import GenerationFailure
        from deeptutor.book.blocks.quiz import QuizGenerator
        from deeptutor.agents.question import pipeline
        for value in ([], "bad", [{}]):
            context = self.context()
            context.block.params["prepared_templates"] = value
            with self.subTest(value=value), patch.object(pipeline, "QuestionPipeline") as constructor:
                with self.assertRaises(GenerationFailure):
                    asyncio.run(QuizGenerator()._generate(context))
                constructor.assert_not_called()

    def test_builtin_whitelist_uses_existing_tool_composition(self):
        from deeptutor.agents.question.pipeline import QuestionPipeline
        from deeptutor.agents._shared.tool_composition import ToolMountFlags, WORKSPACE_BASELINE_TOOLS
        instance = QuestionPipeline.__new__(QuestionPipeline)
        instance.registry = SimpleNamespace(get_enabled=lambda requested: [])
        instance.enabled_tools = []
        instance._optional_tools = []
        instance._mount_flags = Mock(return_value=ToolMountFlags())
        instance._pageindex_tool_names = Mock(return_value=[])
        instance.builtin_tool_whitelist = set()
        self.assertEqual(instance._resolved_tools(None), list(WORKSPACE_BASELINE_TOOLS))
        instance.builtin_tool_whitelist = None
        self.assertIn("web_fetch", instance._resolved_tools(None))


if __name__ == "__main__":
    unittest.main()
