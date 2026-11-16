"""独立 owner 命令的真实子进程集成；不访问真实资料或外部模型。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import raw_index
from tools.wiki_runtime.capture import capture
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.contracts import digest

REPO = Path(__file__).resolve().parents[2]


class HostCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root, self.state = self.base / 'vault', self.base / 'state'
        self.root.mkdir()
        self.put('AGENTS.md', (REPO / 'AGENTS.md').read_bytes())
        self.put('tools/wiki_runtime/contracts/rules.json',
                 (REPO / 'tools/wiki_runtime/contracts/rules.json').read_bytes())
        self.put('wiki/concepts/测试.md', '---\ntype: concept\ntitle: 测试\nupdated: 2026-10-26\n---\n# 测试\n' + '保留完整说明。' * 30)
        self.put('wiki/index.md', '# 索引\n[[concepts/测试]]\n')
        self.put('wiki/log.md', '# 日志\n')
        self.put('raw/unprocessed/a.md', '---\nprocessing_status: unprocessed\n---\n仅在小样本中可能有效。\n')
        self.put('raw/index.md', '# 素材\n' + raw_index.START + '\n' + raw_index.END + '\n')
        self.put('raw/index.md', '# 素材\n' + raw_index.render_queue(self.root / 'raw') + '\n')

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def cli(self, command, *options):
        args = [sys.executable, '-B', '-m', 'tools.wiki_runtime.host', command,
                '--root', str(self.root)]
        if command != 'doctor':
            args += ['--state-dir', str(self.state)]
        return subprocess.run([*args, *options], cwd=REPO, input='',
                              capture_output=True, encoding='utf-8', timeout=90)

    def result(self, process, code=0):
        self.assertEqual(process.returncode, code, process.stderr + process.stdout)
        return json.loads(process.stdout)

    def test_doctor_probes_actual_backend_without_network_or_initialization(self):
        before = self.snapshot()
        result = self.result(self.cli('doctor'))
        self.assertEqual(result['status'], 'gateway_verified_host_binding_required')
        self.assertEqual(result['model_policy'], 'inherit')
        self.assertEqual(result['model_integration'], 'native_inherited')
        self.assertEqual(result['missing_configuration'], ['trusted_host_dispatcher'])
        self.assertFalse(result['may_run_model'])
        self.assertTrue(result['backend_probe']['passed'])
        self.assertFalse(result['model_configured'])
        self.assertFalse(result['live_model_verified'])
        self.assertFalse(result['may_apply'])
        self.assertFalse(result['desktop_session_restricted'])
        self.assertFalse(self.state.exists())
        self.assertEqual(before, self.snapshot())

    def test_prepare_inspect_apply_index_without_model_and_without_duplicate_write(self):
        self.put('raw/index.md', '# 手写说明\n' + raw_index.START + '\n旧队列\n' + raw_index.END + '\n保留尾注\n')
        before = self.snapshot()
        prepared = self.result(self.cli('raw-index', '--operation-id', 'index-op'))
        self.assertEqual(prepared['status'], 'ready_to_apply')
        self.assertEqual(before, self.snapshot())
        reviewed = self.result(self.cli('inspect', '--operation-id', 'index-op'))
        self.assertEqual(reviewed['diffs'][0]['path'], 'raw/index.md')
        applied = self.result(self.cli('apply', '--operation-id', 'index-op'))
        self.assertTrue(applied['applied'])
        text = (self.root / 'raw/index.md').read_text(encoding='utf-8')
        self.assertIn('未处理：1', text)
        self.assertTrue(text.startswith('# 手写说明\n'))
        self.assertTrue(text.endswith('保留尾注\n'))
        after = self.snapshot()
        self.result(self.cli('apply', '--operation-id', 'index-op'))
        self.assertEqual(after, self.snapshot())

    def test_health_report_graph_and_log_use_executor_without_model(self):
        result = self.result(self.cli('health', '--operation-id', 'health-op', '--write-graph', '--apply'))
        self.assertTrue(result['applied'])
        self.assertTrue((self.root / 'wiki/health-report.md').is_file())
        self.assertTrue((self.root / 'wiki/meta/graph.json').is_file())
        log = (self.root / 'wiki/log.md').read_bytes()
        self.assertIn('health | 确定性结构检查'.encode(), log)
        self.result(self.cli('apply', '--operation-id', 'health-op'))
        self.assertEqual(log, (self.root / 'wiki/log.md').read_bytes())

    def test_import_keeps_assets_and_managed_source_expands_for_reviewer(self):
        source = self.base / 'new.md'
        source.write_bytes('# 新资料\n\n这一段才是真正的来源正文。\n'.encode())
        package, package_root = capture(source, self.base / 'packages', 'p1', vault_root=self.root)
        original = (self.root / 'raw/unprocessed/a.md').read_bytes()
        result = self.result(self.cli('import-package', '--operation-id', 'capture-op',
                                      '--package-root', str(package_root), '--raw-path',
                                      'raw/unprocessed/new.md', '--apply'))
        self.assertTrue(result['applied'])
        base = 'raw/assets/' + package['source_id'] + '/' + package['source_revision']
        self.assertEqual((self.root / base / package['originals'][0]['path']).read_bytes(), source.read_bytes())
        self.assertEqual((self.root / 'raw/unprocessed/a.md').read_bytes(), original)
        host = StandaloneHost(self.root, self.state, None, offline=True)
        refs, packages = host._expand_inputs(['raw/unprocessed/new.md'])
        self.assertIn(base + '/extracted/content.md', refs)
        self.assertEqual(packages[0]['input_type'], 'markdown')
        self.assertIn('未处理：2', (self.root / 'raw/index.md').read_text(encoding='utf-8'))

    def test_pipe_cannot_approve_even_if_it_supplies_exact_digest(self):
        def transport(envelope, *, timeout):
            if 'reviewer_id' in envelope:
                request = envelope['input']
                refs = ['original:' + p + '#L1-L1' for p in request['originals']]
                refs += ['candidate:' + p + '#L1-L1' for p in request['candidate_files']]
                return dict(contract_version='1.0', **request['bindings'], reviewer_id=envelope['reviewer_id'],
                            result='recommend_pass', findings=[], evidence_refs=refs)
            return {'changes': [{'action': 'write', 'path': 'tools/proposed.py', 'text': '# 候选工具\n'}]}
        host = StandaloneHost(self.root, self.state, None, transport=transport)
        result = host.run_operation('sensitive-op', 'tool_maintenance', '提出候选工具',
                                    ['tools/proposed.py'], ['raw/unprocessed/a.md'],
                                    max_calls=6, max_seconds=120, call_timeout=30)
        self.assertEqual(result['status'], 'ready_to_apply', result)
        self.assertIsNone(host.approvals.lookup(result['context']))
        process = subprocess.run([sys.executable, '-B', '-m', 'tools.wiki_runtime.host', 'approve',
                                  '--root', str(self.root), '--state-dir', str(self.state),
                                  '--operation-id', 'sensitive-op'], cwd=REPO,
                                 input=digest(result['context']) + '\n', capture_output=True,
                                 encoding='utf-8', timeout=90)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertIn('ApprovalError', process.stderr)
        self.assertIsNone(host.approvals.lookup(result['context']))
        self.assertFalse((self.root / 'tools/proposed.py').exists())


if __name__ == '__main__':
    unittest.main()
