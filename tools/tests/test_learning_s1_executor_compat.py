"""S1 T1：真实旧 Executor 路径、终态重放与跨进程接受屏障。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import raw_index
from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.executor import Executor, ExecutionError
from tools.wiki_runtime.host.derived import build_raw_index, check_derivation


FIXTURE = Path(__file__).resolve().parent / 'fixtures/learning_s1/executor_process.py'
PROJECT = Path(__file__).resolve().parents[2]
RULES = PROJECT / 'tools/wiki_runtime/contracts/rules.json'


class ExecutorCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def operation(self, name):
        root, state = self.base / name / 'vault', self.base / name / 'state'
        for folder in ('raw/unprocessed', 'raw/processed', 'wiki'):
            (root / folder).mkdir(parents=True, exist_ok=True)
        (root / 'AGENTS.md').write_text('# 临时规则\n', encoding='utf-8')
        target = root / 'tools/wiki_runtime/contracts/rules.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(RULES.read_bytes())
        (root / 'raw/index.md').write_text(raw_index.render_queue(root / 'raw'), encoding='utf-8')
        bundle = build_raw_index(root, state / 'operations' / name, name)
        (state / 'operations' / name / 'bundle.json').write_text(
            json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
        return root, state, bundle

    def process(self, command, root, state, operation, exit_at=None, *, expected=0):
        args = [sys.executable, '-B', str(FIXTURE), command, str(root), str(state), operation]
        if exit_at:
            args.append(exit_at)
        result = subprocess.run(args, cwd=PROJECT, env=dict(os.environ, PYTHONPATH=str(PROJECT)),
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_prepared_applying_applied_and_recovered_use_original_journal_root(self):
        for state_name in ('prepared', 'applying', 'applied', 'recovered'):
            with self.subTest(state=state_name):
                root, state, bundle = self.operation(state_name)
                if state_name == 'prepared':
                    self.process('apply', root, state, state_name, 'after_prepare', expected=87)
                elif state_name in ('applying', 'recovered'):
                    self.process('apply', root, state, state_name, 'after_applying', expected=87)
                else:
                    self.process('apply', root, state, state_name)
                journal = state / 'private/journals' / (digest(state_name) + '.json')
                self.assertTrue(journal.exists())
                self.assertEqual(json.loads(journal.read_bytes())['state'],
                                 'applying' if state_name == 'recovered' else state_name)
                executor = Executor(root, state / 'private/journals')
                if state_name in ('prepared', 'applying'):
                    with self.assertRaisesRegex(ExecutionError, '必须先 recover'):
                        executor.lookup_terminal(bundle)
                if state_name != 'applied':
                    recovered = self.process('recover', root, state, state_name)
                    self.assertEqual(recovered['state'], 'recovered')
                result = executor.lookup_terminal(bundle)
                expected_state = 'applied' if state_name == 'applied' else 'recovered'
                self.assertEqual(result['state'], expected_state)
                self.assertEqual(executor.apply(bundle), result)
                self.assertEqual(json.loads(journal.read_bytes())['state'], expected_state)
                self.assertFalse((root / '.wiki-runtime/executor-active.json').exists())

    def test_terminal_replay_precedes_payload_dynamic_checks_and_budget(self):
        root, state, bundle = self.operation('terminal')
        self.process('apply', root, state, 'terminal')
        for path in Path(bundle['payload_root']).iterdir():
            path.unlink()
        calls = []

        def forbidden(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError('终态不得调用审查、预算或 provenance')

        executor = Executor(root, state / 'private/journals', reviewer=forbidden,
                            reserve_call=forbidden, remaining_timeout=forbidden,
                            deterministic_check=forbidden)
        expected = executor.lookup_terminal(bundle)
        self.assertEqual(expected['state'], 'applied')
        self.assertEqual(executor.apply(bundle), expected)
        self.assertEqual(calls, [])

    def test_terminal_rejects_manifest_candidate_and_snapshot_rebinding(self):
        root, state, bundle = self.operation('identity')
        self.process('apply', root, state, 'identity')
        executor = Executor(root, state / 'private/journals')
        for key in ('manifest', 'candidate', 'snapshot'):
            with self.subTest(key=key):
                changed = copy.deepcopy(bundle)
                if key == 'manifest':
                    changed[key]['task'] = '异绑任务'
                elif key == 'candidate':
                    changed[key]['changes'][0]['sha256'] = '0' * 64
                else:
                    changed[key]['files'] = []
                with self.assertRaisesRegex(ExecutionError, '不同候选'):
                    executor.lookup_terminal(changed)
                with self.assertRaisesRegex(ExecutionError, '不同候选'):
                    executor.apply(changed)

    def test_acceptance_barrier_is_the_existing_cross_process_lock(self):
        root, state, _ = self.operation('barrier')
        process = subprocess.Popen(
            [sys.executable, '-B', str(FIXTURE), 'hold', str(root), str(state), 'barrier'],
            cwd=PROJECT, env=dict(os.environ, PYTHONPATH=str(PROJECT)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), 'locked')
            executor = Executor(root, state / 'private/journals')
            with self.assertRaisesRegex(ExecutionError, '另一执行器占用'):
                with executor.acceptance_barrier():
                    pass
            self.assertTrue((root / '.wiki-runtime/executor.lock').exists())
        finally:
            _stdout, process_stderr = process.communicate('\n', timeout=30)
        self.assertEqual(process.returncode, 0, process_stderr)


if __name__ == '__main__':
    unittest.main()
