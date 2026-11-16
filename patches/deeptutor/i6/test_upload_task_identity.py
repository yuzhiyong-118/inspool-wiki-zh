"""已安装 DocumentAdder 的单文件／批量入口均传递真实进度任务 ID，无模型。"""
import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class UploadTaskIdentity(unittest.TestCase):
    def test_single_and_batch_paths_preserve_upload_task_identity(self):
        with TemporaryDirectory(prefix="i6-upload-task-") as temp:
            os.environ["DEEPTUTOR_HOME"] = temp
            from deeptutor.knowledge import add_documents as module
            root = Path(temp)
            for name in ("a.md", "b.md"):
                (root / name).write_text("source", encoding="utf-8")
            adder = module.DocumentAdder.__new__(module.DocumentAdder)
            adder.base_dir = root
            adder.kb_name = "fixture"
            adder.rag_provider = "llamaindex"
            adder.progress_tracker = SimpleNamespace(task_id="kb_upload_fixture", update=Mock())
            adder._record_successful_hash = Mock()
            service = SimpleNamespace(add_documents=AsyncMock(return_value=True))
            with patch.object(module, "RAGService", return_value=service):
                for files in ([root / "a.md"], [root / "a.md", root / "b.md"]):
                    with self.subTest(count=len(files)):
                        service.add_documents.reset_mock()
                        result = asyncio.run(adder.process_new_documents(files))
                        self.assertEqual(result.processed_count, len(files))
                        self.assertFalse(result.has_failures)
                        self.assertEqual(service.add_documents.await_args.kwargs["task_id"], "kb_upload_fixture")


if __name__ == "__main__":
    unittest.main()
