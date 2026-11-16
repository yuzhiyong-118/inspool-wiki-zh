"""旧确定性 CLI 的真实子进程与 Executor 回归；只操作临时库。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from tools import health, raw_index
from tools.wiki_runtime.contracts import bytes_digest, candidate_digest
from tools.wiki_runtime.executor import Executor, ExecutionError
from tools.wiki_runtime.host.derived import build_health, build_raw_index, check_derivation


TOOLS = Path(__file__).resolve().parents[1]


class LegacyEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.state = self.base / 'vault', self.base / 'state'
        # Scripts must locate their own temporary vault, as direct python tools/* does.
        (self.root / 'tools').mkdir(parents=True)
        for name in ('health.py', 'raw_index.py'):
            shutil.copyfile(TOOLS / name, self.root / 'tools' / name)
        self.put('tools/wiki_runtime/contracts/rules.json',
                 (TOOLS / 'wiki_runtime/contracts/rules.json').read_bytes())
        self.put('AGENTS.md', '# 临时库规则\n')
        self.put('wiki/index.md', '# 索引\n')
        self.put('wiki/log.md', '# 手写日志\n')
        self.put('raw/index.md', '# 手写说明\n' + raw_index.render_queue(self.root / 'raw') + '\n尾注\n')

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def cli(self, script, *args):
        # Share the installed runtime implementation, without copying its source
        # into every vault dependency snapshot. No host or Executor is mocked.
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(TOOLS.parent))
        # An unrelated cwd catches accidental reliance on module-mode imports.
        return subprocess.run([sys.executable, '-B', str(self.root / 'tools' / script), *args],
                              cwd=self.base, env=env, input='', capture_output=True,
                              encoding='utf-8', timeout=90)

    def applied(self, result):
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        data = json.loads(result.stdout)
        self.assertTrue(data['applied'])
        self.assertEqual(data['status'], 'applied')
        return data

    def test_default_commands_remain_read_only(self):
        before = self.snapshot()
        for script, args in [('health.py', ('--json',)), ('raw_index.py', ())]:
            with self.subTest(script=script):
                result = self.cli(script, *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(before, self.snapshot())
        self.assertFalse(self.state.exists())

    def test_every_write_flag_requires_explicit_state_without_mutation(self):
        before = self.snapshot()
        for script, flag in [('health.py', '--save'), ('health.py', '--write-graph'),
                             ('health.py', '--graph-only'), ('raw_index.py', '--write')]:
            with self.subTest(flag=flag):
                result = self.cli(script, flag)
                self.assertEqual(result.returncode, 2)
                self.assertIn('--state-dir', result.stderr)
                self.assertIn('host Executor', result.stderr)
                self.assertEqual(before, self.snapshot())
        self.assertFalse(self.state.exists())

    def test_state_inside_vault_is_rejected(self):
        before = self.snapshot()
        for script, flag in [('health.py', '--save'), ('raw_index.py', '--write')]:
            result = self.cli(script, flag, '--state-dir', str(self.root / 'state'))
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn('state_dir', result.stderr)
            self.assertEqual(before, self.snapshot())

    def test_health_save_and_graph_apply_and_log(self):
        result = self.cli('health.py', '--save', '--write-graph', '--state-dir', str(self.state),
                          '--operation-id', 'legacy-health')
        self.applied(result)
        self.assertIn('Health', (self.root / 'wiki/health-report.md').read_text(encoding='utf-8'))
        self.assertEqual(json.loads((self.root / 'wiki/meta/graph.json').read_bytes())['schema_version'], 2)
        self.assertIn('health |', (self.root / 'wiki/log.md').read_text(encoding='utf-8'))
        journals = list((self.state / 'private/journals').rglob('*.json'))
        self.assertTrue(journals)
        # Executor must persist the actual gate reports, not only claim success.
        self.assertTrue(any('"G5"' in p.read_text(encoding='utf-8') for p in journals))

    def test_graph_only_logs_without_creating_report(self):
        for flag in ('--graph-only', '--write-graph'):
            with self.subTest(flag=flag):
                self.applied(self.cli('health.py', flag, '--state-dir', str(self.state)))
                self.assertTrue((self.root / 'wiki/meta/graph.json').exists())
                self.assertFalse((self.root / 'wiki/health-report.md').exists())
        self.assertEqual((self.root / 'wiki/log.md').read_text(encoding='utf-8').count('health |'), 2)

    def test_existing_health_problems_are_saved_but_keep_failure_exit_code(self):
        self.put('wiki/concepts/缺字段.md', '# 缺字段\n' + '保留完整说明。' * 30)
        self.put('wiki/index.md', '# 索引\n[[concepts/缺字段]]\n')
        preview = self.cli('health.py', '--json')
        self.assertEqual(preview.returncode, 1, preview.stderr)
        problems = health.count_problems(json.loads(preview.stdout))
        self.assertGreater(problems, 0)
        for flag in ('--save', '--write-graph'):
            with self.subTest(flag=flag):
                result = self.cli('health.py', flag, '--state-dir', str(self.state))
                self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
                self.assertTrue(json.loads(result.stdout)['applied'])
        self.assertIn(f'总计：{problems} 项问题',
                      (self.root / 'wiki/health-report.md').read_text(encoding='utf-8'))
        log = (self.root / 'wiki/log.md').read_text(encoding='utf-8')
        self.assertEqual(log.count(f'检查结果：{problems} 项问题'), 2)
        # Graph-only historically reports generation success even with baseline warnings.
        self.applied(self.cli('health.py', '--graph-only', '--state-dir', str(self.state)))

    def test_raw_write_uses_executor_and_preserves_handwritten_regions(self):
        self.put('raw/unprocessed/资料.md', '---\nprocessing_status: unprocessed\n---\n原文\n')
        self.applied(self.cli('raw_index.py', '--write', '--state-dir', str(self.state),
                               '--operation-id', 'legacy-raw'))
        text = (self.root / 'raw/index.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# 手写说明\n'))
        self.assertTrue(text.endswith('\n尾注\n'))
        self.assertIn('未处理：1', text)
        self.assertIn('[[raw/unprocessed/资料]]', text)
        self.assertTrue(list((self.state / 'private/journals').rglob('*.json')))

    def test_missing_rules_fail_closed_without_formal_write(self):
        (self.root / 'AGENTS.md').unlink()
        before = self.snapshot()
        for script, flag in [('health.py', '--save'), ('raw_index.py', '--write')]:
            result = self.cli(script, flag, '--state-dir', str(self.state))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, self.snapshot())

    def test_real_executor_rejects_tampered_derived_outputs(self):
        for kind in ('health', 'raw-index'):
            with self.subTest(kind=kind):
                run = self.base / ('candidate-' + kind)
                bundle = (build_health(self.root, run, kind) if kind == 'health' else
                          build_raw_index(self.root, run, kind))
                path = 'wiki/health-report.md' if kind == 'health' else 'raw/index.md'
                change = next(c for c in bundle['candidate']['changes'] if c['path'] == path)
                payload = Path(bundle['payload_root']) / change['payload_path']
                data = payload.read_bytes() + b'\nunauthorized content\n'
                payload.write_bytes(data)
                change['sha256'] = bytes_digest(data)
                bundle['manifest']['candidate_digest'] = candidate_digest(bundle['candidate'])
                before = self.snapshot()
                executor = Executor(self.root, self.base / ('journals-' + kind),
                                    deterministic_check=check_derivation)
                with self.assertRaises(ExecutionError):
                    executor.apply(bundle)
                # Executor may create its vault coordination lock before rejecting;
                # all business files and every other path must remain untouched.
                after = self.snapshot()
                before.pop('.wiki-runtime/executor.lock', None)
                after.pop('.wiki-runtime/executor.lock', None)
                self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
