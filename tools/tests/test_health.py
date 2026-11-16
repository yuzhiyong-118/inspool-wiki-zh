"""维护工具的行为回归：使用临时库，避免修改真实知识库。"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import health
import heal
import raw_index


class WikiFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "vault"
        self.state = Path(self.tmp.name) / "private-state"
        self.wiki = self.root / "wiki"
        self.raw = self.root / "raw"
        for folder in ("sources", "concepts", "entities", "synthesis", "meta"):
            (self.wiki / folder).mkdir(parents=True)
        for folder in ("unprocessed", "processed"):
            (self.raw / folder).mkdir(parents=True)
        self.patches = patch.multiple(health, WIKI_ROOT=self.wiki, RAW_ROOT=self.raw,
                                     META_DIR=self.wiki / "meta", GRAPH_JSON=self.wiki / "meta/graph.json",
                                     HEALTH_REPORT=self.wiki / "health-report.md")
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.heal_patch = patch.object(heal, "WIKI_ROOT", self.wiki)
        self.heal_patch.start()
        self.addCleanup(self.heal_patch.stop)
        self.heal_health_patch = patch.multiple(heal.health, WIKI_ROOT=self.wiki, RAW_ROOT=self.raw,
            META_DIR=self.wiki / "meta", GRAPH_JSON=self.wiki / "meta/graph.json",
            HEALTH_REPORT=self.wiki / "health-report.md")
        self.heal_health_patch.start()
        self.addCleanup(self.heal_health_patch.stop)
        self.write("wiki/index.md", "# 索引\n\n## 总览\n")
        self.write("wiki/log.md", "# 日志\n")
        self.write("AGENTS.md", "# 临时测试库规则\n")
        mapping = Path(__file__).resolve().parents[1] / "wiki_runtime/contracts/rules.json"
        self.write("tools/wiki_runtime/contracts/rules.json", mapping.read_text(encoding="utf-8"))
        self.write("raw/index.md", "说明保留\n" + raw_index.START + "\n" + raw_index.END + "\n尾注保留\n")
        self.sync_raw_fixture()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def sync_raw_fixture(self):
        index = self.raw / "index.md"
        original = index.read_text(encoding="utf-8")
        generated = raw_index.render_queue(self.raw)
        updated = (original[:original.index(raw_index.START)] + generated
                   + original[original.index(raw_index.END) + len(raw_index.END):])
        self.write("raw/index.md", updated)

    def note(self, path, body="", extra=""):
        kind = "source" if path.startswith("sources/") else "concept"
        return self.write("wiki/" + path, f"---\ntype: {kind}\ntitle: 页面\nupdated: 2026-10-26\n{extra}---\n\n# 页面\n" + body + "\n" + "说明。" * 50)

    def maps(self):
        return health.page_maps(list(self.wiki.rglob("*.md")) + list(self.raw.rglob("*.md")))

    def test_frontmatter_indented_list_and_body_not_parsed(self):
        fm = health.parse_frontmatter('---\nrelated_sources:\n  - "[[sources/a]]"\n---\nstatus: bogus')
        self.assertIn("[[sources/a]]", str(fm["related_sources"]))
        self.assertNotIn("status", fm)

    def test_meta_dead_link_detected_code_examples_ignored(self):
        self.write("wiki/meta/overview.md", '[[不存在]]\n`[[例子]]`\n```yaml\na: "[[模板]]"\n```\n[[#本节]]')
        self.assertEqual(health.run_health()["checks"]["broken_links"], {"meta/overview.md": ["不存在"]})

    def test_log_target_resolves_and_audit_history_is_exempt(self):
        self.write("wiki/meta/overview.md", "[[log]]")
        self.write("wiki/meta/audit-log.md", "[[已删除历史页]]")
        self.assertFalse(health.run_health()["checks"]["broken_links"])

    def test_unique_note_survives_category_move(self):
        target = self.note("concepts/子分类/循环.md")
        names, paths = self.maps()
        self.assertEqual(health.resolve_page("concepts/循环#定义", names, paths), target)
        self.assertEqual(health.resolve_page("wiki/concepts/子分类/循环.md", names, paths), target)
        self.assertIsNone(health.resolve_page("entities/循环", names, paths))

    def test_same_stem_is_not_silently_merged(self):
        a = self.note("concepts/a/循环.md")
        b = self.note("concepts/b/循环.md")
        names, paths = self.maps()
        self.assertIsNone(health.resolve_page("循环", names, paths))
        self.assertEqual(health.resolve_page("concepts/a/循环", names, paths), a)
        graph = health.build_graph([a, b])
        self.assertEqual(len({n["id"] for n in graph["nodes"]}), 2)

    def test_valid_pending_raw_and_reciprocal_source(self):
        self.write("raw/unprocessed/a.md", '---\nprocessing_status: pending_review\nprocessed_into: "[[wiki/sources/a]]"\n---\n原文')
        self.note("sources/a.md", extra='raw_note: "[[raw/unprocessed/a]]"\n')
        self.sync_raw_fixture()
        self.assertFalse(health.check_raw_queue(*self.maps()))
        self.assertFalse(health.check_path_residue([self.wiki / "sources/a.md"]))

    def test_raw_without_state_or_index_is_visible(self):
        self.write("raw/unprocessed/a.md", "原始笔记")
        issues = health.check_raw_queue(*self.maps())
        self.assertTrue(any("processing_status" in i for i in issues))
        self.assertTrue(any("收录次数" in i for i in issues))

    def test_approve_stale_path_and_wrong_state_detected(self):
        self.write("raw/processed/a.md", '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/a]]"\n---\n原文')
        source = self.note("sources/a.md", extra='raw_note: "[[raw/unprocessed/a]]"\n')
        self.sync_raw_fixture()
        issues = health.check_raw_queue(*self.maps())
        self.assertTrue(any("目录不一致" in i for i in issues))
        self.assertTrue(any("未回指" in i for i in issues))
        self.assertTrue(health.check_path_residue([source]))

    def test_source_mapping_and_index_state_mismatch(self):
        self.write("raw/processed/a.md", '---\nprocessing_status: processed\nprocessed_into: "[[sources/a]]"\n---\n原文')
        self.sync_raw_fixture()
        index = self.raw / "index.md"
        index.write_text(index.read_text(encoding="utf-8").replace("| processed |", "| unprocessed |"), encoding="utf-8")
        issues = health.check_raw_queue(*self.maps())
        self.assertTrue(any("reviewed_at" in i for i in issues))
        self.assertTrue(any("来源页不存在" in i for i in issues))
        self.assertTrue(any("状态不一致" in i for i in issues))

    def test_graph_keeps_relation_types_content_stats_exclude_meta(self):
        a = self.note("concepts/a.md", '[[concepts/b]]', 'supports:\n  - "[[concepts/b]]"\n')
        b = self.note("concepts/b.md")
        meta = self.write("wiki/meta/a.md", "[[concepts/a]] [[concepts/b]]")
        graph = health.build_graph([a, b, meta])
        edge = next(e for e in graph["edges"] if e["source"] == "concepts/a")
        self.assertEqual(edge["relations"], ["body", "supports"])
        stats = health.compute_graph_stats(graph, [a, b])
        self.assertEqual((stats["node_count"], stats["edge_count"], stats["avg_outgoing_links"]), (2, 1, 0.5))

    def test_missing_index_counts_as_failure(self):
        (self.wiki / "index.md").unlink()
        self.assertGreater(health.count_problems(health.run_health()), 0)

    def test_default_cli_is_read_only_and_returns_failure(self):
        self.write("wiki/meta/a.md", "[[缺失]]")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(sys, "argv", ["health.py", "--json"]), contextlib.redirect_stdout(io.StringIO()):
            result = health.main()
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(result, 1)
        self.assertEqual(before, after)

    def test_raw_snapshot_preserves_notes_and_is_idempotent(self):
        self.write("raw/unprocessed/分类/笔记.md", "---\nprocessing_status: unprocessed\n---\n原文")
        self.sync_raw_fixture()
        first = (self.raw / "index.md").read_bytes()
        self.assertIn("未处理：1", first.decode("utf-8"))
        normalized = (self.raw / "index.md").read_text(encoding="utf-8")
        self.assertTrue(normalized.startswith("说明保留\n"))
        self.assertTrue(normalized.endswith("尾注保留\n"))
        self.sync_raw_fixture()
        self.assertEqual(first, (self.raw / "index.md").read_bytes())
        self.assertFalse(health.check_raw_queue(*self.maps()))

    def test_raw_snapshot_refuses_missing_markers(self):
        self.write("raw/index.md", "手写队列")
        with self.assertRaises(ValueError):
            self.sync_raw_fixture()
        self.assertEqual((self.raw / "index.md").read_text(encoding="utf-8"), "手写队列")

    def test_heal_can_add_new_meta_page_without_path_type_error(self):
        self.write("wiki/meta/新报告.md", "# 报告")
        result = heal.heal_index_sync(health.all_wiki_pages(), dry_run=True)
        self.assertTrue(any(a["type"] == "add_missing" for a in result))

    def test_pending_raw_link_with_spaces_and_dots_is_not_residue(self):
        self.write("raw/unprocessed/笔记 v1.2.md", "原文")
        source = self.note("sources/a.md", extra='raw_note: "[[raw/unprocessed/笔记 v1.2]]"\n')
        self.assertFalse(health.check_path_residue([source]))

    def test_saved_report_is_not_checked_as_content(self):
        with patch.object(sys, "argv", ["health.py", "--save", "--state-dir", str(self.state)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(health.main(), 0)
        self.assertTrue((self.wiki / "health-report.md").exists())
        self.assertEqual(health.count_problems(health.run_health()), 0)

    def test_graph_only_writes_stable_derived_graph(self):
        with patch.object(sys, "argv", ["health.py", "--graph-only", "--state-dir", str(self.state)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(health.main(), 0)
            original = (self.wiki / "meta/graph.json").read_bytes()
            self.assertEqual(health.main(), 0)
            self.assertEqual(original, (self.wiki / "meta/graph.json").read_bytes())
        self.assertEqual((self.wiki / "log.md").read_text(encoding="utf-8").count("health |"), 2)
        self.assertFalse((self.wiki / "health-report.md").exists())

    def test_all_five_python_write_branches_reject_direct_writes_but_not_previews(self):
        from tools.wiki_runtime.runtime.migration import MigrationError
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        writes = [
            lambda: raw_index.refresh_index(apply=True),
            lambda: heal.run_heal(dry_run=False),
            lambda: heal.heal_missing_pages([], dry_run=False),
            lambda: heal.heal_broken_links([], dry_run=False),
            lambda: heal.heal_index_sync([], dry_run=False),
        ]
        for write in writes:
            with self.subTest(write=write), self.assertRaisesRegex(MigrationError, "已封闭"):
                write()
        self.assertIsInstance(raw_index.refresh_index(apply=False), str)
        self.assertTrue(heal.run_heal(dry_run=True)["dry_run"])
        self.assertEqual(heal.heal_missing_pages([], dry_run=True), [])
        self.assertEqual(heal.heal_broken_links([], dry_run=True), [])
        self.assertIsInstance(heal.heal_index_sync([], dry_run=True), list)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_freeze_still_rejects_legacy_guard_without_blocking_previews(self):
        from tools.wiki_runtime.runtime.migration import (
            MigrationError, freeze_legacy_entries, legacy_write_guard,
        )
        freeze_legacy_entries(self.root, self.state)
        with self.assertRaisesRegex(MigrationError, "已冻结"):
            with legacy_write_guard(self.root):
                pass
        self.assertIsInstance(raw_index.refresh_index(apply=False), str)
        self.assertTrue(heal.run_heal(dry_run=True)["dry_run"])


if __name__ == "__main__":
    unittest.main()
