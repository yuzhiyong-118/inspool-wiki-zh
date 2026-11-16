"""P1 真实模块串联：临时库验证候选，不应用正式内容。"""
import json
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wiki_runtime.cli import prepare, check
from wiki_runtime.contracts import bytes_digest, ContractError


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root, self.payload, self.run = base / "vault", base / "payloads", base / "operation"
        self.root.mkdir()
        self.payload.mkdir()
        authority = Path(__file__).resolve().parents[2] / "AGENTS.md"
        self.put("AGENTS.md", authority.read_bytes())
        mapping = Path(__file__).resolve().parents[1] / "wiki_runtime/contracts/rules.json"
        self.put("tools/wiki_runtime/contracts/rules.json", mapping.read_bytes())
        self.put("wiki/index.md", "# 索引\n\n[[concepts/已有概念]]\n")
        self.put("wiki/log.md", "# 日志\n")
        self.put("wiki/meta/overview.md", self.note("meta", "总览", "现有总览。" * 30))
        self.put("wiki/concepts/已有概念.md", self.note("concept", "已有概念", "已有说明。" * 30))
        # meta 也必须在索引；它不会计入内容页。
        self.put("wiki/index.md", "# 索引\n\n[[concepts/已有概念]]\n[[meta/overview]]\n")
        self.put("raw/unprocessed/a.md", "---\nprocessing_status: unprocessed\n---\n原始证据。\n")
        self.put("raw/index.md", self.queue("unprocessed"))

    def put(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)

    def note(self, kind, title, body, extra=""):
        return f"---\ntype: {kind}\ntitle: {title}\nupdated: 2026-10-26\n{extra}---\n\n# {title}\n\n{body}\n"

    def queue(self, state):
        refs = "[[sources/a]]" if state == "pending_review" else "待 ingest"
        return (f"# 队列\n\n- 未处理：{int(state == 'unprocessed')}\n"
                f"- 待确认：{int(state == 'pending_review')}\n- 已处理：0\n\n"
                f"| 文件 | 来源页 | 状态 |\n|---|---|---|\n"
                f"| [[raw/unprocessed/a]] | {refs} | {state} |\n")

    def baseline(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def stage(self, updates, operation="index_rebuild"):
        changes = []
        for index, (rel, text) in enumerate(updates.items()):
            data = text.encode("utf-8") if isinstance(text, str) else text
            payload_name = f"file-{index}.md"
            (self.payload / payload_name).write_bytes(data)
            target = self.root / rel
            pre = {"kind": "hash", "sha256": bytes_digest(target.read_bytes())} if target.exists() else {"kind": "absent"}
            changes.append({"action": "write", "path": rel, "payload_path": payload_name,
                            "sha256": bytes_digest(data), "precondition": pre})
        candidate = {"contract_version": "1.0", "operation_id": "pilot-001", "changes": changes}
        prepare(self.root, candidate, self.payload, self.run, operation_type=operation,
                allowed_paths=list(updates), task="临时库 P1 集成试点")
        return candidate

    def ingest_updates(self):
        source = self.note("source", "a", "## 核心摘要\n\n原文说明。" * 20 +
                           "\n关联 [[concepts/已有概念]] 和 [[concepts/新概念]]。\n",
                           'raw_note: "[[raw/unprocessed/a]]"\nrelated_concepts:\n  - "[[concepts/已有概念]]"\n  - "[[concepts/新概念]]"\n')
        return {
            "wiki/sources/a.md": source,
            "wiki/concepts/新概念.md": self.note("concept", "新概念", "原文支持的概念。" * 20 + "\n见 [[sources/a]]。",
                                                      'supports:\n  - "[[sources/a]]"\n'),
            "wiki/concepts/已有概念.md": self.note("concept", "已有概念", "已有说明。" * 30 + "\n新证据 [[sources/a]] 补充定义。",
                                                       'related_sources:\n  - "[[sources/a]]"\n'),
            "wiki/index.md": "# 索引\n\n[[concepts/已有概念]]\n[[concepts/新概念]]\n[[sources/a]]\n[[meta/overview]]\n",
            "wiki/log.md": "# 日志\n\n## [2026-10-26] ingest | a\n\n新增 [[sources/a]] 和概念。\n",
            "wiki/meta/overview.md": self.note("meta", "总览", "现有总览。" * 30 + "\n新增 [[sources/a]]。"),
            "raw/unprocessed/a.md": '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/a]]"\n---\n原始证据。\n',
            "raw/index.md": self.queue("pending_review"),
        }

    def test_valid_index_candidate_and_frozen_payload_do_not_write_vault(self):
        before = self.baseline()
        self.stage({"wiki/index.md": "# 新索引\n\n[[concepts/已有概念]]\n[[meta/overview]]\n"})
        # 输入工作区后来被改，冻结记录仍使用之前复制的载荷。
        (self.payload / "file-0.md").write_text("被替换", encoding="utf-8")
        result = check(self.run)
        self.assertTrue(result["passed"], result)
        self.assertFalse(result["applied"])
        self.assertEqual(before, self.baseline())

    def test_missing_index_entry_is_rejected(self):
        self.stage({"wiki/index.md": "# 索引\n[[meta/overview]]\n"})
        self.assertFalse(check(self.run)["passed"])

    def test_stale_dependency_is_rejected_before_reusing_reports(self):
        self.stage({"wiki/index.md": (self.root / "wiki/index.md").read_text(encoding="utf-8")})
        self.put("wiki/concepts/用户新页.md", self.note("concept", "用户新页", "用户手动创建。" * 30))
        with self.assertRaises((ContractError, ValueError)):
            check(self.run)

    def test_tampered_frozen_payload_is_rejected(self):
        self.stage({"wiki/index.md": (self.root / "wiki/index.md").read_text(encoding="utf-8")})
        (self.run / "payload/file-0.md").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            check(self.run)

    def test_valid_ingest_candidate_only_validates_no_apply(self):
        before = self.baseline()
        self.stage(self.ingest_updates(), "ingest")
        result = check(self.run)
        self.assertTrue(result["passed"], result)
        self.assertEqual(before, self.baseline())

    def test_raw_body_mutation_is_rejected(self):
        updates = self.ingest_updates()
        updates["raw/unprocessed/a.md"] = updates["raw/unprocessed/a.md"].replace("原始证据", "被改证据")
        self.stage(updates, "ingest")
        self.assertFalse(check(self.run)["passed"])

    def test_missing_reciprocal_relation_is_rejected(self):
        updates = self.ingest_updates()
        updates["wiki/concepts/已有概念.md"] = self.note("concept", "已有概念", "未补回链。" * 30)
        self.stage(updates, "ingest")
        self.assertFalse(check(self.run)["passed"])

    def test_run_output_cannot_be_written_into_wiki(self):
        self.run = self.root / "wiki/operation"
        with self.assertRaises(ContractError):
            self.stage({"wiki/index.md": "# 索引\n"})

    def test_direct_cli_capture_from_other_working_directory(self):
        source = Path(self.tmp.name) / "文章.md"
        source.write_text("# 标题\n\n完整正文。\n", encoding="utf-8")
        cli = Path(__file__).resolve().parents[1] / "wiki_runtime/cli.py"
        result = subprocess.run([sys.executable, "-B", str(cli), "capture", str(source),
                                 "--root", str(self.root), "--candidate-root", str(self.payload),
                                 "--package", "capture-test"], cwd=self.tmp.name,
                                capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["package"]["input_type"], "markdown")
        self.assertTrue((self.payload / "capture-test/source-package.json").exists())

    def test_pdf_registry_and_cli_preserve_partial_policy(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("当前解释器没有可选 PDF 依赖")
        from tools.wiki_runtime.capture import identify, validate_package
        source = Path(self.tmp.name) / "扫描件.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        with source.open("wb") as stream:
            writer.write(stream)
        self.assertEqual(identify(source), "pdf")
        cli = Path(__file__).resolve().parents[1] / "wiki_runtime/cli.py"
        before = self.baseline()
        result = subprocess.run([sys.executable, "-B", str(cli), "capture", str(source),
                                 "--root", str(self.root), "--candidate-root", str(self.payload),
                                 "--package", "pdf-test"], cwd=self.tmp.name,
                                capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1, result.stderr)
        package = json.loads(result.stdout)["package"]
        self.assertEqual(package["input_type"], "pdf")
        self.assertEqual(package["quality"]["status"], "partial")
        validate_package(package, self.payload / "pdf-test")
        self.assertEqual(before, self.baseline())


if __name__ == "__main__":
    unittest.main()
