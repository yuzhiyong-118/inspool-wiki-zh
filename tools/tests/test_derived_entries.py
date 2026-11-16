"""固定派生入口只在临时库验证；不读取真实个人资料。"""
import copy
from pathlib import Path
import tempfile
import unittest

from tools.wiki_runtime.candidate import CandidateView
from tools.wiki_runtime.capture import capture
from tools.wiki_runtime.contracts import bytes_digest
from tools.wiki_runtime.host.derived import (build_capture, build_health,
    build_raw_index, check_derivation)


class DerivedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'vault'
        self.root.mkdir()
        self.put('AGENTS.md', '# 规则\n')
        mapping = Path(__file__).parents[1] / 'wiki_runtime/contracts/rules.json'
        self.put('tools/wiki_runtime/contracts/rules.json', mapping.read_bytes())
        self.put('wiki/index.md', '# 索引\n')
        self.put('wiki/log.md', '# 手写日志\n')
        self.put('raw/index.md', '# 手写前缀\n<!-- raw-queue:start -->\n旧计数\n<!-- raw-queue:end -->\n手写后缀\n')
        self.put('raw/unprocessed/旧记录.md', '---\nprocessing_status: unprocessed\n---\n原文\n')
        self.serial = 0

    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode('utf-8') if isinstance(data, str) else data)

    def run_path(self):
        self.serial += 1
        return self.root / '.wiki-runtime' / ('r' + str(self.serial))

    def accepts(self, bundle, packages=()):
        view = CandidateView(self.root, bundle['candidate'], bundle['payload_root'])
        return check_derivation(dict(manifest=bundle['manifest'], candidate=bundle['candidate'],
                                     operation_type=bundle['manifest']['operation_type']), view, packages)

    def alter(self, bundle, path, transform):
        result = copy.deepcopy(bundle)
        record = next(c for c in result['candidate']['changes'] if c['path'] == path)
        payload = Path(result['payload_root']) / record['payload_path']
        data = transform(payload.read_bytes())
        payload.write_bytes(data)
        record['sha256'] = bytes_digest(data)
        return result

    def package(self, body='# 原件\n全文不可摘要\n'):
        source = Path(self.temp.name) / 'input.md'
        source.write_text(body, encoding='utf-8')
        return capture(source, Path(self.temp.name) / ('packages' + str(self.serial)),
                       'p', vault_root=self.root)

    def test_queue_preserves_handwritten_regions_and_rejects_tamper(self):
        bundle = build_raw_index(self.root, self.run_path(), 'queue')
        self.assertTrue(self.accepts(bundle))
        entry = next(c for c in bundle['candidate']['changes'] if c['path'] == 'raw/index.md')
        self.assertIn('未处理：1', (Path(bundle['payload_root']) / entry['payload_path']).read_text(encoding='utf-8'))
        bad = self.alter(bundle, 'raw/index.md', lambda x: x.replace('手写前缀'.encode(), b'changed'))
        self.assertFalse(self.accepts(bad))
        # 候选自称纯派生不参与认证。
        bad['manifest']['task'] = 'derived=true deterministic=true'
        self.assertFalse(self.accepts(bad))

    def test_health_exact_outputs_and_graph_tamper(self):
        bundle = build_health(self.root, self.run_path(), 'health', write_graph=True)
        self.assertTrue(self.accepts(bundle))
        bad = self.alter(bundle, 'wiki/meta/graph.json', lambda x: x.replace(b'"schema_version": 2', b'"schema_version": 3'))
        self.assertFalse(self.accepts(bad))

    def test_health_log_cannot_replace_old_prefix(self):
        bundle = build_health(self.root, self.run_path(), 'health', save_report=False)
        self.assertTrue(self.accepts(bundle))
        bad = self.alter(bundle, 'wiki/log.md', lambda x: x.replace('手写'.encode(), b'bad'))
        self.assertFalse(self.accepts(bad))

    def test_capture_complete_and_body_tamper(self):
        package, package_root = self.package()
        bundle = build_capture(self.root, self.run_path(), 'capture', package, package_root,
                               raw_path='raw/unprocessed/新资料.md')
        self.assertTrue(self.accepts(bundle, [(package, package_root)]))
        bad = self.alter(bundle, 'raw/unprocessed/新资料.md', lambda x: x + b'changed')
        self.assertFalse(self.accepts(bad, [(package, package_root)]))

    def test_wechat_capture_preserves_html_and_extracted(self):
        source = Path(self.temp.name) / 'article.html'
        source.write_text('<h1 id="activity-name">示例文章</h1><div id="js_content"><p>完整原文</p></div>', encoding='utf-8')
        package, package_root = capture(source, Path(self.temp.name) / 'wechat-package', 'p', vault_root=self.root)
        bundle = build_capture(self.root, self.run_path(), 'wechat', package, package_root,
                               raw_path='raw/unprocessed/微信记录.md')
        self.assertTrue(self.accepts(bundle, [(package, package_root)]))
        original = next(c for c in bundle['candidate']['changes'] if c['path'].endswith('originals/source.html'))
        self.assertEqual((Path(bundle['payload_root']) / original['payload_path']).read_bytes(), source.read_bytes())

    def test_capture_attachment_omission_and_revision_repeat(self):
        source = Path(self.temp.name) / 'input.md'
        source.write_text('# 附件\n![图](pic.png)\n', encoding='utf-8')
        source.with_name('pic.png').write_bytes(b'fixture-png')
        package, package_root = capture(source, Path(self.temp.name) / 'package', 'p', vault_root=self.root)
        bundle = build_capture(self.root, self.run_path(), 'capture', package, package_root,
                               raw_path='raw/unprocessed/新资料.md')
        self.assertTrue(self.accepts(bundle, [(package, package_root)]))
        bad = copy.deepcopy(bundle)
        bad['candidate']['changes'] = [c for c in bad['candidate']['changes'] if '/attachments/' not in c['path']]
        self.assertFalse(self.accepts(bad, [(package, package_root)]))
        base = self.root / 'raw/assets' / package['source_id'] / package['source_revision']
        base.mkdir(parents=True)
        with self.assertRaises(ValueError):
            build_capture(self.root, self.run_path(), 'again', package, package_root, raw_path='raw/unprocessed/另一个.md')

    def test_partial_unknown_and_run_overwrite_rejected(self):
        package, package_root = self.package('# 部分\n![图](missing.png)\n')
        self.assertEqual(package['quality']['status'], 'partial')
        with self.assertRaises(ValueError):
            build_capture(self.root, self.run_path(), 'partial', package, package_root, raw_path='raw/unprocessed/x.md')
        bad = copy.deepcopy(package)
        bad['parser']['adapter_id'] = 'untrusted'
        with self.assertRaises(ValueError):
            build_capture(self.root, self.run_path(), 'bad', bad, package_root, raw_path='raw/unprocessed/x.md')
        run = self.run_path()
        build_raw_index(self.root, run, 'one')
        with self.assertRaises(ValueError):
            build_raw_index(self.root, run, 'two')
        with self.assertRaises(ValueError):
            build_raw_index(self.root, self.root / 'wiki/run', 'bad')

    def test_executor_capture_and_index_need_no_model(self):
        from tools.wiki_runtime.executor import Executor
        package, package_root = self.package()
        bundle = build_capture(self.root, self.run_path(), 'execute-capture', package, package_root,
                               raw_path='raw/unprocessed/新资料.md')
        executor = Executor(self.root, self.root / '.wiki-runtime/executor/journal',
                            deterministic_check=check_derivation, package_check=lambda context, packages: True)
        result = executor.apply(bundle, source_packages=[(package, package_root)])
        self.assertEqual(result['state'], 'applied')
        bundle = build_raw_index(self.root, self.run_path(), 'execute-index')
        self.assertEqual(executor.apply(bundle)['state'], 'applied')

    def test_executor_health_needs_no_model(self):
        from tools.wiki_runtime.executor import Executor
        bundle = build_health(self.root, self.run_path(), 'execute-health', write_graph=True)
        executor = Executor(self.root, self.root / '.wiki-runtime/executor/journal',
                            deterministic_check=check_derivation)
        self.assertEqual(executor.apply(bundle)['state'], 'applied')


if __name__ == '__main__':
    unittest.main()
