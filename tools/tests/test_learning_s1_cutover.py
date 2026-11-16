"""S1 T1：真实 pending、freeze 锁竞争、白名单 drain 与中断续办。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tools import raw_index
from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.executor import Executor
from tools.wiki_runtime.host.derived import check_derivation
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.runtime.migration import (
    MigrationError, drain_registered_pending, freeze_legacy_entries,
    inspect_cutover, inventory_pending, legacy_write_guard, supersede_pending,
)


FIXTURE = Path(__file__).resolve().parent / 'fixtures/learning_s1/legacy_cutover.py'
PROJECT = Path(__file__).resolve().parents[2]
RULES = PROJECT / 'tools/wiki_runtime/contracts/rules.json'


class CutoverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.state = self.base / 'vault', self.base / 'state'
        for folder in ('raw/unprocessed', 'raw/processed', 'wiki'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / 'AGENTS.md').write_text('# 临时规则\n', encoding='utf-8')
        target = self.root / 'tools/wiki_runtime/contracts/rules.json'
        target.parent.mkdir(parents=True)
        target.write_bytes(RULES.read_bytes())
        (self.root / 'raw/index.md').write_text(raw_index.render_queue(self.root / 'raw'), encoding='utf-8')

    def process(self, command, operation, *extra, expected=0):
        result = subprocess.run(
            [sys.executable, '-B', str(FIXTURE), command, str(self.root), str(self.state), operation, *map(str, extra)],
            cwd=PROJECT, env=dict(os.environ, PYTHONPATH=str(PROJECT)),
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return result

    def test_empty_inventory_explicitly_needs_no_drain_and_restart_is_idempotent(self):
        empty = inventory_pending(self.state)
        self.assertEqual(empty['operations'], [])
        self.assertFalse(empty['drain_required'])
        self.assertEqual(empty['disposition'], 'no_drain_required')
        first = freeze_legacy_entries(self.root, self.state)
        second = freeze_legacy_entries(self.root, self.state)
        self.assertEqual(first, second)
        inspected = inspect_cutover(self.state)
        self.assertTrue(inspected['frozen'])
        self.assertEqual(inspected['disposition'], 'no_drain_required')
        self.assertEqual(inspected['inventory']['inventory_digest'], first['inventory_digest'])

    def test_only_registered_pending_can_drain_and_repeat_returns_original_result(self):
        self.process('make-pending', 'allowed')
        freeze = freeze_legacy_entries(self.root, self.state)
        self.assertEqual(freeze['inventory']['operations'][0]['classification'], 'pre_wal_pending')
        before = set((self.state / 'private/journals').glob('*.json')) if (self.state / 'private/journals').exists() else set()
        with self.assertRaisesRegex(MigrationError, '不在获准 drain 清单'):
            drain_registered_pending('not-registered', root=self.root, state_dir=self.state)
        self.assertEqual(set((self.state / 'private/journals').glob('*.json')), before)
        with self.assertRaisesRegex(MigrationError, '已冻结'):
            with legacy_write_guard(self.root):
                pass
        first = json.loads(self.process('drain', 'allowed').stdout)
        self.assertEqual(first['status'], 'applied', first)
        self.assertEqual(first, drain_registered_pending('allowed', root=self.root, state_dir=self.state))
        journals = list((self.state / 'private/journals').glob('*.json'))
        self.assertEqual([path.name for path in journals], [digest('allowed') + '.json'])
        self.assertEqual(inspect_cutover(self.state)['inventory']['operations'][0]['journal_state'], 'applied')

    def test_interrupted_drain_recovers_original_wal_and_closes_recovered(self):
        self.process('make-pending', 'interrupted')
        freeze_legacy_entries(self.root, self.state)
        self.process('interrupted-drain', 'interrupted', expected=86)
        journal = self.state / 'private/journals' / (digest('interrupted') + '.json')
        self.assertEqual(json.loads(journal.read_bytes())['state'], 'applying')
        first = drain_registered_pending('interrupted', root=self.root, state_dir=self.state)
        self.assertEqual(first['status'], 'recovered', first)
        journal_bytes = journal.read_bytes()
        second = drain_registered_pending('interrupted', root=self.root, state_dir=self.state)
        self.assertEqual(first, second)
        self.assertEqual(journal.read_bytes(), journal_bytes)
        self.assertEqual(json.loads(journal.read_bytes())['state'], 'recovered')

    def test_freeze_waits_for_checked_writer_and_rejects_late_writer_during_drain(self):
        self.process('make-pending', 'drain-during-race')
        ready, release = self.base / 'ready', self.base / 'release'
        first_target = self.base / 'first-write'
        writer = subprocess.Popen(
            [sys.executable, '-B', str(FIXTURE), 'writer', str(self.root), str(self.state), '',
             str(ready), str(release), str(first_target)],
            cwd=PROJECT, env=dict(os.environ, PYTHONPATH=str(PROJECT)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        frozen, errors = [], []

        def freeze():
            try:
                frozen.append(freeze_legacy_entries(self.root, self.state))
            except Exception as exc:
                errors.append(exc)

        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists(), writer.stderr.read() if writer.poll() else 'writer not ready')
            thread = threading.Thread(target=freeze)
            thread.start()
            time.sleep(0.15)
            self.assertTrue(thread.is_alive(), 'freeze 必须等待检查后暂停的已登记写者')
            self.assertFalse((self.root / '.wiki-runtime/legacy-cutover.json').exists())
            release.write_text('continue', encoding='utf-8')
            thread.join(30)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(first_target.read_text(encoding='utf-8'), 'writer-finished')
            self.assertTrue(frozen)
        finally:
            if not release.exists():
                release.write_text('cleanup', encoding='utf-8')
            _stdout, writer_stderr = writer.communicate(timeout=30)
        self.assertEqual(writer.returncode, 0, writer_stderr)

        late_target = self.base / 'late-write'
        late = self.process('writer', '', self.base / 'late-ready', self.base / 'late-release',
                            late_target, expected=1)
        self.assertIn('旧写入口已冻结', late.stderr)
        self.assertFalse(late_target.exists())
        drained = json.loads(self.process('drain', 'drain-during-race').stdout)
        self.assertEqual(drained['status'], 'applied')
        self.assertFalse(late_target.exists())

    def test_freeze_blocks_real_host_apply_and_bare_guard_operation_id(self):
        self.process('make-pending', 'host-bypass')
        freeze_legacy_entries(self.root, self.state)
        before = (self.root / 'raw/index.md').read_bytes()
        direct = self.process('host-apply', 'host-bypass', expected=1)
        self.assertIn('尚未完成切变', direct.stderr)
        guarded = self.process('guard', 'host-bypass', expected=1)
        self.assertIn('裸 operation_id', guarded.stderr)
        self.assertFalse((self.state / 'private/journals').exists())
        self.assertEqual((self.root / 'raw/index.md').read_bytes(), before)
        applied = json.loads(self.process('drain', 'host-bypass').stdout)
        self.assertEqual(applied['status'], 'applied')
        replay = json.loads(self.process('host-apply', 'host-bypass').stdout)
        self.assertEqual(replay['status'], 'applied')
        self.assertEqual(replay, applied)

    def test_inventory_rejects_orphan_bad_mismatched_active(self):
        active = self.root / '.wiki-runtime/executor-active.json'
        active.parent.mkdir()
        cases = [b'{', dict(journal_root=str(self.state / 'private/journals'), operation_id='orphan')]
        for value in cases:
            with self.subTest(value=value):
                active.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
                with self.assertRaises(MigrationError):
                    inventory_pending(self.state, self.root)
                active.unlink()
        self.process('make-pending', 'pending-only')
        active.write_text(json.dumps(dict(journal_root=str(self.state / 'private/journals'),
                                          operation_id='pending-only')), encoding='utf-8')
        with self.assertRaisesRegex(MigrationError, '没有匹配'):
            inspect_cutover(self.state)
        active.unlink()

        host = StandaloneHost(self.root, self.state, offline=True)
        self.process('make-pending', 'wal')
        bundle = host.load_pending('wal')['bundle']
        def fault(event, index):
            if event == 'after_prepare':
                raise RuntimeError('保留 prepared')
        result = Executor(self.root, self.state / 'private/journals',
                          deterministic_check=check_derivation, fault=fault).apply(bundle)
        self.assertEqual(result['state'], 'prepared')
        for operation_id, journal_root in [('wal', str(self.base / 'wrong-journals')),
                                           ('pending-only', str(self.state / 'private/journals'))]:
            with self.subTest(operation_id=operation_id, journal_root=journal_root):
                active.write_text(json.dumps(dict(journal_root=journal_root, operation_id=operation_id)),
                                  encoding='utf-8')
                with self.assertRaises(MigrationError):
                    inventory_pending(self.state, self.root)
                active.unlink()

    def test_matching_recoverable_active_can_freeze_and_recover(self):
        self.process('make-pending', 'active-recovery')
        host = StandaloneHost(self.root, self.state, offline=True)
        bundle = host.load_pending('active-recovery')['bundle']
        def fault(event, index):
            if event == 'after_active':
                raise RuntimeError('保留 active')
        result = Executor(self.root, self.state / 'private/journals',
                          deterministic_check=check_derivation, fault=fault).apply(bundle)
        self.assertEqual(result['state'], 'recovery_required')
        inventory = inventory_pending(self.state, self.root)
        self.assertEqual(inventory['active']['status'], 'recoverable')
        freeze_legacy_entries(self.root, self.state)
        self.assertEqual(inspect_cutover(self.state)['inventory']['active']['status'], 'recoverable')
        recovered = Executor(self.root, self.state / 'private/journals').recover('active-recovery')
        self.assertEqual(recovered['state'], 'recovered')
        self.assertIsNone(inspect_cutover(self.state)['inventory']['active'])

    def test_terminal_active_is_safe_to_clear_and_replay_bypasses_freeze(self):
        self.process('make-pending', 'active-terminal')
        host = StandaloneHost(self.root, self.state, offline=True)
        bundle = host.load_pending('active-terminal')['bundle']
        def fault(event, index):
            if event == 'after_commit':
                raise RuntimeError('WAL 后、active 清理前')
        result = Executor(self.root, self.state / 'private/journals',
                          deterministic_check=check_derivation, fault=fault).apply(bundle)
        self.assertEqual(result['state'], 'applied')
        self.assertEqual(inventory_pending(self.state, self.root)['active']['status'], 'terminal_stale')
        freeze_legacy_entries(self.root, self.state)
        replay = Executor(self.root, self.state / 'private/journals').apply(bundle)
        self.assertEqual(replay['state'], 'applied')
        self.assertFalse((self.root / '.wiki-runtime/executor-active.json').exists())
        self.assertEqual(inspect_cutover(self.state)['freeze']['drains'], {})

    def test_locator_only_crash_is_resumed_by_identical_freeze_and_drain(self):
        self.process('make-pending', 'locator-window')
        self.process('freeze-after-locator', 'locator-window', expected=85)
        locator = self.state / 'private/legacy-cutover.pointer.json'
        locator_bytes = locator.read_bytes()
        self.assertFalse((self.root / '.wiki-runtime/legacy-cutover.json').exists())
        with self.assertRaisesRegex(MigrationError, '定位指针与库内描述不一致'):
            inspect_cutover(self.state)
        direct = self.process('host-apply', 'locator-window', expected=1)
        self.assertIn('cutover intent', direct.stderr)
        self.assertFalse((self.state / 'private/journals').exists())
        freeze = freeze_legacy_entries(self.root, self.state)
        self.assertEqual(freeze['drains'], {})
        self.assertEqual(locator.read_bytes(), locator_bytes)
        self.assertTrue(inspect_cutover(self.state)['frozen'])
        result = json.loads(self.process('drain', 'locator-window').stdout)
        self.assertEqual(result['status'], 'applied')
        self.assertTrue(inspect_cutover(self.state)['frozen'])

    def test_locator_only_resume_rejects_tampered_digest_and_root(self):
        self.process('make-pending', 'locator-tamper')
        self.process('freeze-after-locator', 'locator-tamper', expected=85)
        locator_path = self.state / 'private/legacy-cutover.pointer.json'
        original = locator_path.read_bytes()
        locator = json.loads(original)
        for field, value in [('freeze_digest', '0' * 64), ('root', str(self.base / 'other-root'))]:
            with self.subTest(field=field):
                changed = dict(locator, **{field: value})
                locator_path.write_text(json.dumps(changed), encoding='utf-8')
                with self.assertRaisesRegex(MigrationError, '重算候选不一致'):
                    freeze_legacy_entries(self.root, self.state)
                self.assertFalse((self.root / '.wiki-runtime/legacy-cutover.json').exists())
                locator_path.write_bytes(original)

    def crash_resume(self, point, operation):
        note = self.root / 'raw/unprocessed/note.md'
        note.write_text('---\nprocessing_status: unprocessed\n---\n合成原文\n', encoding='utf-8')
        before = (self.root / 'raw/index.md').read_bytes()
        self.process('make-pending', operation)
        freeze_legacy_entries(self.root, self.state)
        if point == 'after-recovered':
            self.process('drain-crash', operation, 'after-active', expected=86)
        self.process('drain-crash', operation, point, expected=86)
        freeze_path = self.root / '.wiki-runtime/legacy-cutover.json'
        receipt = json.loads(freeze_path.read_bytes())['drains'][operation]
        self.assertEqual(receipt['status'], 'completed' if point == 'after-completed' else 'running')
        journal = self.state / 'private/journals' / (digest(operation) + '.json')
        expected_wal = {'after-running': None, 'after-prepare': 'prepared', 'after-active': 'prepared',
                        'after-applied': 'applied', 'after-recovered': 'recovered',
                        'after-completed': 'applied'}[point]
        self.assertEqual(json.loads(journal.read_bytes())['state'] if journal.exists() else None, expected_wal)
        active = self.root / '.wiki-runtime/executor-active.json'
        self.assertEqual(active.exists(), point == 'after-active')
        inspect_cutover(self.state)
        if point == 'after-running':
            host = StandaloneHost(self.root, self.state, offline=True)
            bundle = host.load_pending(operation)['bundle']
            with self.assertRaisesRegex(MigrationError, 'journal_root'):
                Executor(self.root, self.base / 'wrong/private/journals',
                         deterministic_check=check_derivation).apply(bundle)
            changed = copy.deepcopy(bundle)
            changed['manifest']['task'] = '异绑'
            with self.assertRaisesRegex(MigrationError, '身份与 freeze'):
                Executor(self.root, self.state / 'private/journals',
                         deterministic_check=check_derivation).apply(changed)
            self.assertFalse(journal.exists())
        result = drain_registered_pending(operation, root=self.root, state_dir=self.state)
        expected = 'recovered' if point in ('after-prepare', 'after-active', 'after-recovered') else 'applied'
        self.assertEqual(result['status'], expected, result)
        self.assertFalse(active.exists())
        formal = self.root / 'raw/index.md'
        self.assertEqual(formal.read_bytes() == before, expected == 'recovered')
        receipt = json.loads(freeze_path.read_bytes())['drains'][operation]
        self.assertEqual(receipt['status'], 'completed')
        inspect_cutover(self.state)
        stable = (journal.read_bytes(), freeze_path.read_bytes(), formal.read_bytes())
        self.assertEqual(drain_registered_pending(operation, root=self.root, state_dir=self.state), result)
        self.assertEqual(stable, (journal.read_bytes(), freeze_path.read_bytes(), formal.read_bytes()))

    def test_drain_crash_after_running_before_host(self):
        self.crash_resume('after-running', 'crash-running')

    def test_drain_crash_after_prepared(self):
        self.crash_resume('after-prepare', 'crash-prepared')

    def test_drain_crash_after_active(self):
        self.crash_resume('after-active', 'crash-active')

    def test_drain_crash_after_applied_before_completed(self):
        self.crash_resume('after-applied', 'crash-applied')

    def test_drain_crash_after_recovered_before_completed(self):
        self.crash_resume('after-recovered', 'crash-recovered')

    def test_drain_crash_after_completed_before_return(self):
        self.crash_resume('after-completed', 'crash-completed')

    def test_terminal_recovery_and_pre_wal_records_have_deterministic_cutover_dispositions(self):
        for operation in ('old-terminal', 'old-recovery', 'old-superseded'):
            self.process('make-pending', operation)
        host = StandaloneHost(self.root, self.state, offline=True)
        self.addCleanup(host.close)
        executor = Executor(self.root, self.state / 'private/journals',
                            deterministic_check=check_derivation)
        applied = executor.apply(host.load_pending('old-terminal')['bundle'])
        self.assertEqual(applied['state'], 'applied')

        def stop_after_prepare(event, index):
            if event == 'after_prepare':
                raise RuntimeError('保留旧 accepted WAL')

        recovery_bundle = host.load_pending('old-recovery')['bundle']
        recovery = Executor(self.root, self.state / 'private/journals',
                            deterministic_check=check_derivation,
                            fault=stop_after_prepare).apply(recovery_bundle)
        self.assertEqual(recovery['state'], 'prepared')
        freeze_legacy_entries(self.root, self.state)
        initial = inspect_cutover(self.state)
        classifications = {item['operation_id']: item['classification']
                           for item in initial['inventory']['operations']}
        self.assertEqual(classifications, {
            'old-terminal': 'terminal', 'old-recovery': 'accepted_pending_recovery',
            'old-superseded': 'pre_wal_pending',
        })
        self.assertFalse(initial['report']['ready_for_runtime'])

        receipt = supersede_pending(
            'old-superseded', '无法恢复旧预算语义', root=self.root, state_dir=self.state,
        )
        self.assertEqual(receipt['status'], 'superseded_by_runtime_cutover')
        self.assertEqual(receipt, supersede_pending(
            'old-superseded', '无法恢复旧预算语义', root=self.root, state_dir=self.state,
        ))
        with self.assertRaisesRegex(MigrationError, '原因不得重绑'):
            supersede_pending('old-superseded', '另一原因', root=self.root, state_dir=self.state)
        with self.assertRaisesRegex(MigrationError, '不得继续旧 drain'):
            drain_registered_pending('old-superseded', root=self.root, state_dir=self.state)
        recovered = executor.recover('old-recovery')
        self.assertEqual(recovered['state'], 'recovered')
        replay = executor.apply(recovery_bundle)
        self.assertEqual(replay['state'], 'recovered')
        report = inspect_cutover(self.state)['report']
        self.assertTrue(report['ready_for_runtime'])
        self.assertEqual(report['counts'], {
            'terminal': 2, 'accepted_pending_recovery': 0, 'pre_wal_pending': 0,
            'superseded_by_runtime_cutover': 1,
        })
        self.assertFalse((self.state / '.wiki-runtime/learning/runtime.db').exists())

    def test_supersede_crash_is_idempotent_and_never_creates_invocation_or_wal(self):
        self.process('make-pending', 'supersede-crash')
        freeze_legacy_entries(self.root, self.state)
        self.process('supersede-crash', 'supersede-crash', '分类后崩溃', expected=87)
        pending = inspect_cutover(self.state)
        self.assertFalse(pending['report']['ready_for_runtime'])
        self.assertEqual(pending['freeze']['drains'], {})
        journal = self.state / 'private/journals' / (digest('supersede-crash') + '.json')
        self.assertFalse(journal.exists())
        first = supersede_pending(
            'supersede-crash', '分类后崩溃', root=self.root, state_dir=self.state,
        )
        second = supersede_pending(
            'supersede-crash', '分类后崩溃', root=self.root, state_dir=self.state,
        )
        self.assertEqual(first, second)
        self.assertTrue(inspect_cutover(self.state)['report']['ready_for_runtime'])
        self.assertFalse(journal.exists())
        self.assertFalse((self.state / '.wiki-runtime/learning/runtime.db').exists())

    def test_completed_drain_and_accepted_wal_cannot_disappear_without_blocking(self):
        self.process('make-pending', 'missing-completed-wal')
        self.process('make-pending', 'missing-accepted-wal')
        host = StandaloneHost(self.root, self.state, offline=True)
        self.addCleanup(host.close)

        def stop_after_prepare(event, index):
            if event == 'after_prepare':
                raise RuntimeError('保留 accepted WAL')

        Executor(self.root, self.state / 'private/journals',
                 deterministic_check=check_derivation,
                 fault=stop_after_prepare).apply(host.load_pending('missing-accepted-wal')['bundle'])
        accepted = self.state / 'private/journals' / (digest('missing-accepted-wal') + '.json')
        freeze_legacy_entries(self.root, self.state)
        self.process('drain', 'missing-completed-wal')
        journal = self.state / 'private/journals' / (digest('missing-completed-wal') + '.json')
        journal.unlink()
        with self.assertRaisesRegex(MigrationError, 'completed drain'):
            drain_registered_pending('missing-completed-wal', root=self.root, state_dir=self.state)
        with self.assertRaisesRegex(MigrationError, 'completed drain'):
            supersede_pending('missing-completed-wal', '不得覆盖', root=self.root, state_dir=self.state)

        accepted.unlink()
        with self.assertRaisesRegex(MigrationError, '已接受 WAL 下落不明'):
            inspect_cutover(self.state)

    def test_running_receipt_is_runner_only_and_managed_identity_is_checked(self):
        self.process('make-pending', 'runner-only')
        freeze_legacy_entries(self.root, self.state)
        self.process('drain-crash', 'runner-only', 'after-running', expected=86)
        rejected = self.process('host-apply', 'runner-only', expected=1)
        self.assertIn('尚未完成切变', rejected.stderr)
        journal = self.state / 'private/journals' / (digest('runner-only') + '.json')
        self.assertFalse(journal.exists())

        host = StandaloneHost(self.root, self.state, offline=True)
        self.addCleanup(host.close)
        changed = copy.deepcopy(host.load_pending('runner-only')['bundle'])
        changed['manifest']['task'] = '异绑 managed bundle'
        from tools.wiki_runtime.runtime.migration import _check_executor_apply
        with self.assertRaisesRegex(MigrationError, '身份与 freeze'):
            _check_executor_apply(
                self.root, self.state / 'private/journals', changed, managed=True,
                drain_operation_id='runner-only',
            )
        self.assertFalse(journal.exists())
        drained = json.loads(self.process('drain', 'runner-only').stdout)
        self.assertEqual(drained['status'], 'applied')

    def test_inventory_rejects_unauthenticated_managed_marker(self):
        self.process('make-pending', 'tampered-managed')
        path = self.state / 'private/pending' / (digest('tampered-managed') + '.json')
        envelope = json.loads(path.read_bytes())
        envelope['record']['runtime_managed'] = True
        path.write_bytes(json.dumps(envelope).encode('utf-8'))
        with self.assertRaisesRegex(MigrationError, 'HMAC'):
            inventory_pending(self.state, self.root)

    def test_terminal_stale_active_after_recovery_is_idempotently_cleared(self):
        self.process('make-pending', 'terminal-active-recovery')
        host = StandaloneHost(self.root, self.state, offline=True)
        self.addCleanup(host.close)

        def stop_after_active(event, index):
            if event == 'after_active':
                raise RuntimeError('保留 active')

        Executor(self.root, self.state / 'private/journals',
                 deterministic_check=check_derivation,
                 fault=stop_after_active).apply(host.load_pending('terminal-active-recovery')['bundle'])
        freeze_legacy_entries(self.root, self.state)
        executor = Executor(self.root, self.state / 'private/journals')
        self.assertEqual(executor.recover('terminal-active-recovery')['state'], 'recovered')
        active = self.root / '.wiki-runtime/executor-active.json'
        active.write_text(json.dumps({
            'journal_root': str(self.state / 'private/journals'),
            'operation_id': 'terminal-active-recovery',
        }), encoding='utf-8')
        inspected = inspect_cutover(self.state)
        self.assertEqual(inspected['inventory']['active']['status'], 'terminal_stale')
        self.assertEqual(executor.recover('terminal-active-recovery')['state'], 'recovered')
        self.assertIsNone(inspect_cutover(self.state)['inventory']['active'])


if __name__ == '__main__':
    unittest.main()
