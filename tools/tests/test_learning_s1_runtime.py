"""S1 Task 2／3 的真实 SQLite、持久循环、双线程与子进程故障语义。"""
import copy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.executor import Executor
from tools.wiki_runtime.runtime import (
    AdmissionError, ArtifactReferenceError, AuthorizationError, BackupError,
    ExecutionReconcileError, InvocationBusyError, InvocationConflictError, InvocationLimitError,
    LoopConflictError,
    RecoveryEvidenceError, RuntimeInvocationPort, RuntimeService, RuntimeStore,
    RuntimeStoreError, SchemaVersionError, admission_digest, empty_proposal,
)
from tools.wiki_runtime.runtime.loop_protocol import (
    follow_up_digest, learning_state_digest, wait_digest,
)


FIXTURES = Path(__file__).resolve().parent / 'fixtures'
PROCESS_FIXTURE = FIXTURES / 'learning_s1' / 'runtime_process.py'


def wait_for(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'等待文件屏障超时: {path}')
        time.sleep(0.01)


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads(
            (FIXTURES / 'learning_s0' / 'protocol_records.json').read_text(encoding='utf-8')
        )['valid']

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.stores = []
        self.root = Path(self.temporary.name) / 'root'
        self.store, self.port, self.spec = self.make_runtime(self.root)

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.temporary.cleanup()

    def make_runtime(self, root, *, model_calls=20, concurrency=4, final_reserve=0,
                     busy_timeout=0.2):
        policy = copy.deepcopy(self.records['executor_context']['policy_revision'])
        policy['budget']['model_calls'] = model_calls
        policy['policy_digest'] = digest({
            field: policy[field] for field in (
                'revision', 'budget', 'stop_policy', 'creation_reason'
            )
        })
        task = copy.deepcopy(self.records['task'])
        task['current_policy_digest'] = policy['policy_digest']
        run = copy.deepcopy(self.records['run'])
        run['execution_history'] = []
        reserve = {field: 0 for field in policy['budget']}
        reserve['active_seconds'] = 0.0
        reserve['model_calls'] = final_reserve
        store = RuntimeStore(root, busy_timeout=busy_timeout)
        self.stores.append(store)
        port = RuntimeInvocationPort(store, clock=lambda: 100.0)
        port.register_policy_revision(policy)
        port.register_task(task, concurrency_limit=concurrency, final_review_reserve=reserve)
        port.register_run(run, concurrency_limit=concurrency, final_review_reserve=reserve)
        port.register_execution_ownership(copy.deepcopy(self.records['ownership']))
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['policy_digest'] = policy['policy_digest']
        return store, port, spec

    def another_spec(self, invocation_id, *, role='Worker'):
        spec = copy.deepcopy(self.spec)
        spec['invocation_id'] = invocation_id
        spec['role'] = role
        return spec

    def test_path_pragmas_and_connections_are_real_and_thread_local(self):
        self.assertEqual(
            self.store.db_path,
            self.root / '.wiki-runtime' / 'learning' / 'runtime.db',
        )
        main_values = self.store.mutate(lambda connection: (
            connection.execute('PRAGMA journal_mode').fetchone()[0],
            connection.execute('PRAGMA synchronous').fetchone()[0],
            connection.execute('PRAGMA foreign_keys').fetchone()[0],
            connection.execute('PRAGMA busy_timeout').fetchone()[0],
            threading.get_ident(),
        ))
        thread_values = []

        def worker():
            thread_values.append(self.store.mutate(lambda connection: (
                connection.execute('PRAGMA journal_mode').fetchone()[0],
                connection.execute('PRAGMA synchronous').fetchone()[0],
                connection.execute('PRAGMA foreign_keys').fetchone()[0],
                threading.get_ident(),
            )))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(main_values[:3], ('wal', 2, 1))
        self.assertGreater(main_values[3], 0)
        self.assertLessEqual(main_values[3], 200)
        self.assertEqual(thread_values[0][:3], ('wal', 2, 1))
        self.assertNotEqual(main_values[4], thread_values[0][3])

    def test_success_replay_and_same_id_invoke_do_not_call_or_charge_twice(self):
        calls = []

        def transport():
            calls.append('called')
            return {'output': 'ok'}

        first = self.port.invoke(self.spec, transport, 1.0)
        self.assertEqual(first, {'output': 'ok'})
        self.assertEqual(self.port.replay(self.spec), first)
        self.assertEqual(self.port.invoke(self.spec, lambda: self.fail('不得重发'), 1.0), first)
        self.assertEqual(calls, ['called'])
        record = self.port.get_invocation(self.spec['invocation_id'])
        self.assertEqual(record['result_state'], 'succeeded')
        self.assertEqual(record['settlement']['actual_usage']['tokens'], None)
        self.assertEqual(self.port.get_execution(self.spec['invocation_id'])['resource_state'],
                         'released')
        for table, key in (('task_finance', 'task_id'), ('run_finance', 'run_id')):
            account = self.store.read(f'SELECT * FROM {table}')[0]
            actual = json.loads(account['actual_json'])
            reserved = json.loads(account['reserved_json'])
            self.assertEqual(actual['model_calls'], 1)
            self.assertEqual(reserved['model_calls'], 0)
        self.assertEqual(self.port.remaining_run_time(self.spec['run_id']), 890.0)

    def test_same_id_different_spec_is_rejected(self):
        self.port.invoke(self.spec, lambda: {'output': 'ok'}, 1.0)
        changed = copy.deepcopy(self.spec)
        changed['input_digest'] = '3' * 64
        for operation in (
            lambda: self.port.invoke(changed, lambda: {'output': 'bad'}, 1.0),
            lambda: self.port.replay(changed),
        ):
            with self.assertRaises(InvocationConflictError):
                operation()
        self.assertEqual(self.port.replay(self.spec), {'output': 'ok'})

    def test_same_process_active_reentry_is_busy_and_never_takes_over(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []
        outcomes = []

        def transport():
            calls.append(threading.get_ident())
            entered.set()
            self.assertTrue(release.wait(5))
            return {'output': 'first-only'}

        def first():
            outcomes.append(('first', self.port.invoke(self.spec, transport, 2.0)))

        def second():
            entered.wait(2)
            try:
                self.port.invoke(self.spec, lambda: {'output': 'takeover'}, 1.0)
            except InvocationBusyError:
                outcomes.append(('second', 'busy'))

        one = threading.Thread(target=first)
        two = threading.Thread(target=second)
        one.start()
        self.assertTrue(entered.wait(2))
        two.start()
        two.join(3)
        release.set()
        one.join(3)
        self.assertFalse(one.is_alive() or two.is_alive())
        self.assertCountEqual(outcomes, [('first', {'output': 'first-only'}), ('second', 'busy')])
        self.assertEqual(len(calls), 1)

    def test_not_started_send_race_has_exactly_one_transport_winner(self):
        self.port._reserve(self.spec)
        barrier = threading.Barrier(2)
        entered = threading.Event()
        loser_done = threading.Event()
        release = threading.Event()
        calls = []
        outcomes = []

        def transport():
            calls.append(threading.get_ident())
            entered.set()
            self.assertTrue(release.wait(5))
            return {'output': 'single-send-winner'}

        def worker():
            barrier.wait(3)
            try:
                outcomes.append(('ok', self.port.invoke(self.spec, transport, 2.0)))
            except InvocationBusyError:
                outcomes.append(('busy', None))
                loser_done.set()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(2))
        self.assertTrue(loser_done.wait(2))
        release.set()
        for thread in threads:
            thread.join(3)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len([item for item in outcomes if item[0] == 'ok']), 1)
        self.assertEqual(len([item for item in outcomes if item[0] == 'busy']), 1)
        self.assertEqual(self.port.replay(self.spec), {'output': 'single-send-winner'})

    def test_recovered_not_started_old_invoke_cannot_adopt_new_epoch(self):
        reserved = threading.Event()
        resume_old = threading.Event()
        old_calls = []
        outcomes = []
        port = self.port

        class PausingPort(RuntimeInvocationPort):
            def _claim_send(self, invocation_id, execution):
                reserved.set()
                if not resume_old.wait(5):
                    raise TimeoutError('旧调用恢复屏障超时')
                return super()._claim_send(invocation_id, execution)

        pausing_port = PausingPort(self.store, clock=port.clock)

        def old_invoke():
            try:
                result = pausing_port.invoke(self.spec, lambda: old_calls.append('old') or {
                    'output': 'stale-executor'
                }, 1.0)
                outcomes.append(('unexpected-success', result))
            except InvocationBusyError:
                outcomes.append(('busy', None))

        thread = threading.Thread(target=old_invoke)
        thread.start()
        try:
            self.assertTrue(reserved.wait(2))
            before = port.get_execution(self.spec['invocation_id'])
            recovered = port.recover_invocation(self.spec['invocation_id'], {
                'execution_token': before['execution_token'],
                'recovery_epoch': before['recovery_epoch'],
                'executor_stopped': True,
            })
            self.assertEqual(recovered['recovery_epoch'], before['recovery_epoch'] + 1)
        finally:
            resume_old.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [('busy', None)])
        self.assertEqual(old_calls, [])
        current = port.get_execution(self.spec['invocation_id'])
        self.assertEqual(current['recovery_epoch'], recovered['recovery_epoch'])
        self.assertEqual(current['send_state'], 'not_sent')
        self.assertEqual(current['resource_state'], 'not_started')
        new_calls = []
        result = port.invoke(self.spec, lambda: new_calls.append('new') or {
            'output': 'recovered-executor-only'
        }, 1.0)
        self.assertEqual(result, {'output': 'recovered-executor-only'})
        self.assertEqual(new_calls, ['new'])
        self.assertEqual(old_calls, [])
        self.assertEqual(port.get_execution(self.spec['invocation_id'])['recovery_epoch'],
                         recovered['recovery_epoch'])

    def test_not_started_reservation_holds_slot_and_proven_unsent_can_release(self):
        store, port, spec = self.make_runtime(Path(self.temporary.name) / 'unsent', concurrency=1)
        _record, execution, created = port._reserve(spec)
        self.assertTrue(created)
        self.assertEqual(port.get_execution(spec['invocation_id'])['resource_state'], 'not_started')
        with self.assertRaises(InvocationLimitError):
            port.invoke(self.another_spec('other'), lambda: {'output': 'bad'}, 1.0)
        port.confirm_resource_released(spec['invocation_id'], {
            'execution_token': execution['execution_token'],
            'recovery_epoch': execution['recovery_epoch'],
            'proof_not_sent': True,
        })
        other = copy.deepcopy(spec)
        other['invocation_id'] = 'other'
        self.assertEqual(port.invoke(other, lambda: {'output': 'after-release'}, 1.0),
                         {'output': 'after-release'})

    def test_invocation_requires_current_ownership_and_running_state_at_send(self):
        for scenario in ('generation', 'expired', 'paused'):
            with self.subTest(scenario=scenario):
                root = Path(self.temporary.name) / ('eligibility-' + scenario)
                store, port, spec = self.make_runtime(root)
                calls = []
                if scenario == 'paused':
                    port._reserve(spec)
                    service = RuntimeService(store, executor=Executor(
                        root, Path(self.temporary.name) / 'paused-journals',
                    ))
                    service.pause(spec['task_id'])
                else:
                    def invalidate(connection):
                        row = connection.execute(
                            'SELECT record_json FROM execution_ownerships'
                        ).fetchone()
                        ownership = json.loads(row['record_json'])
                        if scenario == 'generation':
                            ownership['generation'] += 1
                        else:
                            ownership['expires_at'] = 0.0
                        connection.execute(
                            'UPDATE execution_ownerships SET generation=?, expires_at=?, '
                            'record_json=?',
                            (ownership['generation'], ownership['expires_at'],
                             json.dumps(ownership)),
                        )
                    store.mutate(invalidate)
                with self.assertRaises(InvocationConflictError):
                    port.invoke(spec, lambda: calls.append('called') or {'output': 'bad'}, 1.0)
                self.assertEqual(calls, [])
                if scenario == 'paused':
                    self.assertEqual(port.get_execution(spec['invocation_id'])['send_state'],
                                     'not_sent')
                else:
                    self.assertEqual(store.read('SELECT * FROM invocations'), [])

    def test_successful_invocation_replay_does_not_require_current_eligibility(self):
        root = Path(self.temporary.name) / 'success-replay-after-pause'
        store, port, spec = self.make_runtime(root)
        result = port.invoke(spec, lambda: {'output': 'persisted'}, 1.0)
        service = RuntimeService(store, executor=Executor(
            root, Path(self.temporary.name) / 'success-replay-journals',
        ))
        service.pause(spec['task_id'])
        self.assertEqual(port.replay(spec), result)
        self.assertEqual(port.invoke(spec, lambda: self.fail('成功结果不得重发'), 1.0), result)

    def test_unsent_release_clamps_floating_point_residual(self):
        store, port, spec = self.make_runtime(Path(self.temporary.name) / 'float-release')
        first = copy.deepcopy(spec)
        first['requested_budget']['active_seconds'] = 0.1
        second = copy.deepcopy(spec)
        second['invocation_id'] = 'floating-second'
        second['requested_budget']['active_seconds'] = 0.7
        _record, first_execution, _created = port._reserve(first)
        _record, second_execution, _created = port._reserve(second)
        port.confirm_resource_released(second['invocation_id'], {
            'execution_token': second_execution['execution_token'],
            'recovery_epoch': second_execution['recovery_epoch'], 'proof_not_sent': True,
        })
        port.confirm_resource_released(first['invocation_id'], {
            'execution_token': first_execution['execution_token'],
            'recovery_epoch': first_execution['recovery_epoch'], 'proof_not_sent': True,
        })
        self.assertEqual(port.get_execution(first['invocation_id'])['resource_state'], 'released')

    def test_timeout_is_unknown_conservative_and_late_completion_only_releases(self):
        store, port, spec = self.make_runtime(Path(self.temporary.name) / 'timeout', concurrency=1)
        calls = []

        def slow():
            calls.append('slow')
            time.sleep(0.15)
            return {'output': 'late-success-must-not-overwrite'}

        result = port.invoke(spec, slow, 0.01)
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['resource_state'], 'draining')
        record = port.get_invocation(spec['invocation_id'])
        self.assertEqual(record['result_state'], 'unknown')
        self.assertEqual(record['settlement']['actual_usage'],
                         {**spec['requested_budget'], 'tokens': None})
        self.assertEqual(port.replay(spec)['state'], 'unknown')
        self.assertEqual(port.invoke(spec, lambda: self.fail('unknown 不得重发'), 0.01)['state'],
                         'unknown')
        other = copy.deepcopy(spec)
        other['invocation_id'] = 'blocked-by-draining'
        with self.assertRaises(InvocationLimitError):
            port.invoke(other, lambda: {'output': 'must-not-run'}, 1.0)
        deadline = time.monotonic() + 3
        while port.get_execution(spec['invocation_id'])['resource_state'] != 'released':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertEqual(port.get_invocation(spec['invocation_id']), record)
        self.assertEqual(calls, ['slow'])
        self.assertEqual(port.invoke(other, lambda: {'output': 'new-after-evidence'}, 1.0),
                         {'output': 'new-after-evidence'})

    def test_repeated_timeouts_cannot_exceed_concurrency_or_fabricate_tokens(self):
        store, port, spec = self.make_runtime(Path(self.temporary.name) / 'repeat', concurrency=1)
        calls = []
        for index in range(2):
            current = copy.deepcopy(spec)
            current['invocation_id'] = f'timeout-{index}'
            result = port.invoke(current, lambda: time.sleep(0.1) or {'output': 'late'}, 0.005)
            self.assertEqual(result['state'], 'unknown')
            calls.append(port.get_invocation(current['invocation_id']))
            self.assertEqual(port.replay(current)['state'], 'unknown')
            following = copy.deepcopy(current)
            following['invocation_id'] = f'not-allowed-{index}'
            with self.assertRaises(InvocationLimitError):
                port.invoke(following, lambda: {'output': 'over-limit'}, 0.01)
            execution = port.get_execution(current['invocation_id'])
            port.confirm_resource_released(current['invocation_id'], {
                'execution_token': execution['execution_token'],
                'recovery_epoch': execution['recovery_epoch'],
                'executor_stopped': True,
            })
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(item['settlement']['actual_usage']['tokens'] is None
                            for item in calls))
        account = json.loads(store.read('SELECT actual_json FROM task_finance')[0]['actual_json'])
        self.assertEqual(account['model_calls'], 2)

    def test_actual_overage_blocks_both_scopes_and_policy_is_immutable(self):
        store, port, spec = self.make_runtime(Path(self.temporary.name) / 'overage', model_calls=1)
        usage = {**spec['requested_budget'], 'model_calls': 2,
                 'active_seconds': 2.0, 'tokens': None}
        result = port.invoke(spec, lambda: {
            'result': {'output': 'accepted-but-over-budget'}, 'actual_usage': usage,
        }, 1.0)
        self.assertEqual(result, {'output': 'accepted-but-over-budget'})
        for table in ('task_finance', 'run_finance'):
            row = store.read(f'SELECT * FROM {table}')[0]
            self.assertEqual(row['blocked'], 1)
            self.assertIn('model_calls', row['block_reason'])
        after_overage = copy.deepcopy(spec)
        after_overage['invocation_id'] = 'after-overage'
        with self.assertRaises(InvocationLimitError):
            port.invoke(after_overage, lambda: {'output': 'bad'}, 1.0)
        original = store.read('SELECT * FROM policy_revisions')[0]
        with self.assertRaises(RuntimeStoreError):
            store.mutate(lambda connection: connection.execute(
                'UPDATE policy_revisions SET revision=2 WHERE policy_digest=?',
                (original['policy_digest'],),
            ))
        self.assertEqual(store.read('SELECT * FROM policy_revisions')[0], original)

    def test_final_review_reserve_is_part_of_the_same_atomic_budget(self):
        store, port, spec = self.make_runtime(
            Path(self.temporary.name) / 'reserve', model_calls=2, final_reserve=1,
        )
        self.assertEqual(port.invoke(spec, lambda: {'output': 'worker'}, 1.0), {'output': 'worker'})
        worker = copy.deepcopy(spec)
        worker['invocation_id'] = 'worker-2'
        with self.assertRaises(InvocationLimitError):
            port.invoke(worker, lambda: {'output': 'bad'}, 1.0)
        final = copy.deepcopy(spec)
        final['invocation_id'] = 'final-review'
        final['role'] = 'ExecutorG3'
        self.assertEqual(port.invoke(final, lambda: {'output': 'final'}, 1.0), {'output': 'final'})

    def test_two_threads_competing_for_last_budget_have_one_winner(self):
        store, port, spec = self.make_runtime(Path(self.temporary.name) / 'thread-race',
                                               model_calls=1, concurrency=2)
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(invocation_id):
            current = copy.deepcopy(spec)
            current['invocation_id'] = invocation_id
            barrier.wait(3)
            try:
                outcomes.append(('ok', port.invoke(current, lambda: {'output': invocation_id}, 1.0)))
            except InvocationLimitError:
                outcomes.append(('limited', invocation_id))

        threads = [threading.Thread(target=worker, args=(f'thread-{index}',))
                   for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(len([item for item in outcomes if item[0] == 'ok']), 1)
        self.assertEqual(len([item for item in outcomes if item[0] == 'limited']), 1)
        self.assertEqual(len(store.read('SELECT * FROM invocations')), 1)

    def run_processes(self, root, specs, *, concurrency=4, model_calls=20, hold=False):
        store, port, _spec = self.make_runtime(root, model_calls=model_calls,
                                               concurrency=concurrency)
        gate = Path(self.temporary.name) / f'gate-{len(list(Path(self.temporary.name).iterdir()))}'
        started = Path(self.temporary.name) / f'started-{time.time_ns()}.txt'
        release = Path(self.temporary.name) / f'release-{time.time_ns()}'
        processes = []
        for spec in specs:
            spec = copy.deepcopy(spec)
            spec['policy_digest'] = _spec['policy_digest']
            config = Path(self.temporary.name) / f'config-{time.time_ns()}.json'
            payload = {
                'root': str(root), 'spec': spec, 'gate': str(gate), 'started': str(started),
            }
            if hold:
                payload['release'] = str(release)
            config.write_text(json.dumps(payload), encoding='utf-8')
            processes.append(subprocess.Popen([
                sys.executable, '-B', str(PROCESS_FIXTURE), 'invoke', str(config),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        gate.write_text('go', encoding='utf-8')
        if hold:
            wait_for(started)
            time.sleep(0.2)
            release.write_text('finish', encoding='utf-8')
        results = [process.communicate(timeout=25) for process in processes]
        return [process.returncode for process in processes], results, started

    def test_two_processes_competing_for_last_budget_have_one_winner(self):
        root = Path(self.temporary.name) / 'process-budget'
        specs = [self.another_spec('process-budget-1'), self.another_spec('process-budget-2')]
        codes, results, started = self.run_processes(root, specs, model_calls=1, concurrency=2)
        self.assertCountEqual(codes, [0, 33], results)
        self.assertEqual(len(started.read_text(encoding='utf-8').splitlines()), 1)
        store = RuntimeStore(root)
        self.stores.append(store)
        self.assertEqual(len(store.read('SELECT * FROM invocations')), 1)

    def test_two_processes_competing_for_last_concurrency_slot_have_one_winner(self):
        root = Path(self.temporary.name) / 'process-concurrency'
        specs = [self.another_spec('process-slot-1'), self.another_spec('process-slot-2')]
        codes, results, started = self.run_processes(root, specs, concurrency=1, hold=True)
        self.assertCountEqual(codes, [0, 33], results)
        self.assertEqual(len(started.read_text(encoding='utf-8').splitlines()), 1)

    def test_cross_process_reentry_kill_and_recovery_never_resends(self):
        root = Path(self.temporary.name) / 'process-recovery'
        store, port, spec = self.make_runtime(root, concurrency=2)
        prefix = Path(self.temporary.name) / 'recovery'
        started = prefix.with_suffix('.started')
        release = prefix.with_suffix('.release')
        original_config = prefix.with_suffix('.json')
        original_config.write_text(json.dumps({
            'root': str(root), 'spec': spec, 'started': str(started), 'release': str(release),
            'timeout': 30.0,
        }), encoding='utf-8')
        original = subprocess.Popen([
            sys.executable, '-B', str(PROCESS_FIXTURE), 'invoke', str(original_config),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            wait_for(started)
            deadline = time.monotonic() + 5
            while port.get_execution(spec['invocation_id'])['resource_state'] != 'inflight':
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            before = port.get_execution(spec['invocation_id'])
            reentrant_config = prefix.with_name(prefix.name + '-reentrant.json')
            reentrant_config.write_text(json.dumps({
                'root': str(root), 'spec': spec, 'started': str(started),
            }), encoding='utf-8')
            reentrant = subprocess.run([
                sys.executable, '-B', str(PROCESS_FIXTURE), 'invoke', str(reentrant_config),
            ], capture_output=True, text=True, timeout=20)
            self.assertEqual(reentrant.returncode, 32, reentrant.stderr + reentrant.stdout)
            original.kill()
            original.communicate(timeout=10)
            recovery_config = prefix.with_name(prefix.name + '-takeover.json')
            recovery_config.write_text(json.dumps({
                'root': str(root), 'spec': spec, 'evidence': {
                    'execution_token': before['execution_token'],
                    'recovery_epoch': before['recovery_epoch'],
                    'executor_stopped': True,
                },
            }), encoding='utf-8')
            recovered = subprocess.run([
                sys.executable, '-B', str(PROCESS_FIXTURE), 'recover', str(recovery_config),
            ], capture_output=True, text=True, timeout=20)
            self.assertEqual(recovered.returncode, 0, recovered.stderr + recovered.stdout)
            payload = json.loads(recovered.stdout)
            self.assertEqual(payload['recovered']['recovery_epoch'], before['recovery_epoch'] + 1)
            self.assertNotEqual(payload['recovered']['execution_token'], before['execution_token'])
            self.assertEqual(payload['replayed']['state'], 'unknown')
            self.assertEqual(payload['execution']['resource_state'], 'released')
            with self.assertRaises(RecoveryEvidenceError):
                port.confirm_resource_released(spec['invocation_id'], {
                    'execution_token': before['execution_token'],
                    'recovery_epoch': before['recovery_epoch'],
                    'completed': True,
                })
            self.assertEqual(started.read_text(encoding='utf-8').splitlines(),
                             [spec['invocation_id']])
            account = json.loads(store.read('SELECT actual_json FROM task_finance')[0]['actual_json'])
            self.assertEqual(account['model_calls'], 1)
        finally:
            if original.poll() is None:
                original.kill()
                original.communicate(timeout=10)

    def test_db_busy_is_bounded_and_does_not_create_or_reset_state(self):
        entered = threading.Event()
        release = threading.Event()

        def holder():
            def hold(connection):
                entered.set()
                if not release.wait(5):
                    raise TimeoutError('测试锁屏障超时')
            self.store.mutate(hold)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(entered.wait(2))
        started = time.monotonic()
        with self.assertRaises(RuntimeStoreError):
            self.port.invoke(self.spec, lambda: {'output': 'must-not-run'}, 1.0)
        elapsed = time.monotonic() - started
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertLess(elapsed, 2.0)
        self.assertEqual(self.store.read('SELECT * FROM invocations'), [])
        self.assertEqual(self.port.invoke(self.spec, lambda: {'output': 'after-busy'}, 1.0),
                         {'output': 'after-busy'})

    def test_backup_uses_snapshot_and_copies_only_referenced_verified_artifacts(self):
        result = self.port.invoke(self.spec, lambda: {'output': 'backup'}, 1.0)
        self.assertEqual(result, {'output': 'backup'})
        artifact = self.store.artifact_root / 'nested' / 'result.json'
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'{"ok":true}')
        artifact_digest = self.store.publish_artifact(self.spec['invocation_id'],
                                                      'nested/result.json')
        destination = Path(self.temporary.name) / 'backup'
        backed_up = self.store.backup(destination)
        self.assertEqual(backed_up['artifacts'], ['nested/result.json'])
        self.assertEqual((destination / 'artifacts' / 'nested' / 'result.json').read_bytes(),
                         b'{"ok":true}')
        snapshot = sqlite3.connect(destination / 'runtime.db')
        try:
            self.assertEqual(snapshot.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(snapshot.execute(
                'SELECT artifact_digest FROM artifacts WHERE relative_path=?',
                ('nested/result.json',),
            ).fetchone()[0], artifact_digest)
            self.assertEqual(snapshot.execute('SELECT count(*) FROM invocations').fetchone()[0], 1)
        finally:
            snapshot.close()
        second = self.store.artifact_root / 'missing.json'
        second.write_bytes(b'must-exist')
        self.store.publish_artifact(self.spec['invocation_id'], 'missing.json')
        second.unlink()
        with self.assertRaises(BackupError):
            self.store.backup(Path(self.temporary.name) / 'failed-backup')
        self.assertFalse((Path(self.temporary.name) / 'failed-backup').exists())
        with self.assertRaises(ArtifactReferenceError):
            self.store.publish_artifact(self.spec['invocation_id'], 'absent.json')

    def test_unknown_schema_is_rejected_without_reinitialization(self):
        connection = sqlite3.connect(self.store.db_path)
        try:
            connection.execute('PRAGMA user_version=77')
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(SchemaVersionError):
            self.store.mutate(lambda connection: connection.execute('SELECT 1'))
        with self.assertRaises(SchemaVersionError):
            RuntimeStore(self.root)
        connection = sqlite3.connect(self.store.db_path)
        try:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 77)
            self.assertGreater(connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0], 5)
        finally:
            connection.close()


class RuntimeLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads(
            (FIXTURES / 'learning_s0' / 'protocol_records.json').read_text(encoding='utf-8')
        )['valid']
        cls.loop_records = json.loads(
            (FIXTURES / 'learning_s0' / 'loop_protocol_records.json').read_text(encoding='utf-8')
        )['valid']

    def setUp(self):
        from tools.wiki_runtime.executor import Executor

        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'root'
        self.store = RuntimeStore(self.root, busy_timeout=0.15)
        self.executor = Executor(
            self.root, Path(self.temporary.name) / 'executor-state/private/journals',
        )
        self.service = RuntimeService(
            self.store, executor=self.executor, clock=lambda: 100.0,
        )
        self.policy = copy.deepcopy(self.records['executor_context']['policy_revision'])
        self.task = copy.deepcopy(self.records['task'])
        self.run = copy.deepcopy(self.records['run'])
        self.run['execution_history'] = []
        self.ownership = copy.deepcopy(self.records['ownership'])
        self.learning = copy.deepcopy(self.records['executor_context']['learning_state'])
        self.service.create_task(
            policy=self.policy, task=self.task, run=self.run, ownership=self.ownership,
            learning_state=self.learning,
        )

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def step_and_work(self, step_id='step-1', *, generation=1):
        step = copy.deepcopy(self.loop_records['step'])
        step.update(step_id=step_id, generation=generation, state='pending', result_digest=None)
        item = copy.deepcopy(self.loop_records['work_item'])
        item.update(
            work_item_id='work-' + step_id, step_id=step_id, generation=generation,
            ready_at=0.0, schedule_key=f'{step_id}:attempt-1:generation-{generation}',
            claimed_by=None, lease_expires_at=None, state='pending',
        )
        return step, item

    def plan_one(self):
        event = copy.deepcopy(self.loop_records['event'])
        self.service.accept_event(event)
        step, item = self.step_and_work()
        calls = []

        def planner(frozen):
            calls.append(frozen)
            return empty_proposal(
                frozen['task']['revision'], steps=[step], work_items=[item],
            )

        planned = self.service.plan_pending(planner)
        self.assertEqual(planned[0]['processing_state'], 'processed')
        self.assertEqual(len(calls), 1)
        return event, step, item

    def make_result(self, claim, *, waits=None, follow_ups=None, follow_up_steps=None,
                    learning_state=None, failure=None):
        waits = [] if waits is None else waits
        follow_ups = [] if follow_ups is None else follow_ups
        follow_up_steps = [] if follow_up_steps is None else follow_up_steps
        if len(follow_ups) != len(follow_up_steps):
            raise ValueError('后续 WorkItem 与 Step 必须成对提供')
        result = {
            'step_id': claim['step']['step_id'],
            'attempt': claim['step']['attempt'],
            'generation': claim['step']['generation'],
            'input_digest': claim['step']['input_digest'],
            'artifact_digests': [],
            'domain_change_digest': (
                learning_state_digest(learning_state) if learning_state is not None else None
            ),
            'wait_request_digest': wait_digest(waits[0]) if waits else None,
            'follow_up_digests': [
                follow_up_digest(step, item)
                for step, item in zip(follow_up_steps, follow_ups)
            ],
            'failure': failure,
        }
        result['result_digest'] = digest({field: result[field] for field in (
            'artifact_digests', 'domain_change_digest', 'wait_request_digest',
            'follow_up_digests', 'failure',
        )})
        return result

    def test_takeover_result_binds_follow_up_step_definitions(self):
        self.plan_one()
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['input_digest'] = self.loop_records['step']['input_digest']
        old = self.service.claim_step(
            'old-owner', now=100.0, lease_seconds=1.0,
            invocation_id=spec['invocation_id'],
        )
        next_step, next_item = self.step_and_work('step-2')
        original = self.make_result(
            old, follow_ups=[next_item], follow_up_steps=[next_step],
        )
        self.service.port.invoke(spec, lambda: {
            'output': 'original', 'step_result_digest': original['result_digest'],
        }, 1.0)
        taken = self.service.claim_step('new-owner', now=102.0, lease_seconds=10.0)
        changed_step = copy.deepcopy(next_step)
        changed_step['input_digest'] = 'f' * 64
        result = self.make_result(
            taken, follow_ups=[next_item], follow_up_steps=[next_step],
        )
        with self.assertRaisesRegex(LoopConflictError, 'follow_up_digests'):
            self.service.submit_step_result(
                result, work_item_id=taken['work_item']['work_item_id'],
                claimed_by='new-owner', now=103.0, invocation_id=spec['invocation_id'],
                proposal=empty_proposal(
                    self.task['revision'], steps=[changed_step], work_items=[next_item],
                ),
            )
        self.service.submit_step_result(
            result, work_item_id=taken['work_item']['work_item_id'],
            claimed_by='new-owner', now=103.0, invocation_id=spec['invocation_id'],
            proposal=empty_proposal(
                self.task['revision'], steps=[next_step], work_items=[next_item],
            ),
        )
        following = self.service.claim_step('next-owner', now=104.0)
        self.assertEqual(following['step']['input_digest'], next_step['input_digest'])

    def test_retry_uses_current_policy_revision(self):
        self.plan_one()
        failure = {
            'category': 'environment', 'fingerprint': '6' * 64, 'reason': 'probe',
        }
        claim = self.service.claim_step('owner', now=100.0)
        self.service.submit_step_result(
            self.make_result(claim, failure=failure),
            work_item_id=claim['work_item']['work_item_id'], claimed_by='owner', now=100.5,
        )
        changed = copy.deepcopy(self.policy)
        changed['revision'] = 2
        changed['stop_policy']['max_step_attempts'] = 1
        changed['policy_digest'] = digest({field: changed[field] for field in (
            'revision', 'budget', 'stop_policy', 'creation_reason',
        )})
        self.service.switch_policy(self.task['task_id'], changed)
        with self.assertRaises(LoopConflictError):
            self.service.loop.retry_step('step-1', failure['fingerprint'])
        current = json.loads(self.store.read('SELECT record_json FROM steps')[0]['record_json'])
        self.assertEqual(current['attempt'], 1)

    def test_existing_work_item_obeys_stricter_current_attempt_limit(self):
        self.plan_one()
        failure = {
            'category': 'environment', 'fingerprint': '6' * 64, 'reason': 'probe',
        }
        claim = self.service.claim_step('owner', now=100.0)
        self.service.submit_step_result(
            self.make_result(claim, failure=failure),
            work_item_id=claim['work_item']['work_item_id'], claimed_by='owner', now=100.5,
        )
        retried = self.service.loop.retry_step('step-1', failure['fingerprint'])
        self.assertEqual(retried['step']['attempt'], 2)
        changed = copy.deepcopy(self.policy)
        changed['revision'] = 2
        changed['stop_policy']['max_step_attempts'] = 1
        changed['policy_digest'] = digest({field: changed[field] for field in (
            'revision', 'budget', 'stop_policy', 'creation_reason',
        )})
        self.service.switch_policy(self.task['task_id'], changed)
        self.assertIsNone(self.service.claim_step('owner', now=101.0))
        current = json.loads(self.store.read('SELECT record_json FROM steps')[0]['record_json'])
        self.assertEqual(current['state'], 'blocked')
        task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
        self.assertEqual(task['state'], 'blocked')

    def test_stale_dependency_blocks_only_affected_task_and_scan_continues(self):
        self.plan_one()
        dependency = self.loop_records['step']['dependency_digests'][0]
        self.service.loop.invalidate_dependency(dependency, reason='probe stale dependency')
        task2 = copy.deepcopy(self.task)
        task2.update(task_id='task-2', learning_task_id='task-learning-2')
        run2 = copy.deepcopy(self.run)
        run2.update(task_id='task-2', learning_task_id='task-learning-2', run_id='run-2')
        ownership2 = copy.deepcopy(self.ownership)
        ownership2.update(task_id='task-2', learning_task_id='task-learning-2')
        learning2 = copy.deepcopy(self.learning)
        learning2.update(task_id='task-2', learning_task_id='task-learning-2')
        self.service.create_task(
            policy=self.policy, task=task2, run=run2, ownership=ownership2,
            learning_state=learning2,
        )
        event2 = copy.deepcopy(self.loop_records['event'])
        event2.update(event_id='event-2', task_id='task-2')
        self.service.accept_event(event2)
        step2, item2 = self.step_and_work('step-good')
        step2['task_id'] = item2['task_id'] = 'task-2'
        step2['dependency_digests'] = []
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], steps=[step2], work_items=[item2],
        ))
        claimed = self.service.claim_step('owner-good', now=100.0)
        self.assertEqual(claimed['task']['task_id'], 'task-2')
        blocked = json.loads(self.store.read(
            "SELECT record_json FROM tasks WHERE task_id='task-1'"
        )[0]['record_json'])
        self.assertEqual(blocked['state'], 'blocked')
        self.assertEqual(self.service.claim_step('owner-good-2', now=100.0), None)

    def test_blocked_task_cannot_claim_another_item_in_same_scan(self):
        self.plan_one()
        event2 = copy.deepcopy(self.loop_records['event'])
        event2['event_id'] = 'event-same-task'
        self.service.accept_event(event2)
        step2, item2 = self.step_and_work('step-good-same-task')
        step2['dependency_digests'] = []
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], steps=[step2], work_items=[item2],
        ))
        dependency = self.loop_records['step']['dependency_digests'][0]
        self.service.loop.invalidate_dependency(dependency, reason='probe stale dependency')
        self.assertIsNone(self.service.claim_step('owner', now=100.0))
        task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
        self.assertEqual(task['state'], 'blocked')
        good = json.loads(self.store.read(
            "SELECT record_json FROM work_items WHERE work_item_id='work-step-good-same-task'"
        )[0]['record_json'])
        self.assertEqual(good['state'], 'pending')
        self.assertIsNone(good['claimed_by'])

    def test_pending_expired_step_skips_task_without_blocking_global_scan(self):
        self.plan_one()
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['input_digest'] = self.loop_records['step']['input_digest']
        old = self.service.claim_step(
            'old-owner', now=100.0, lease_seconds=1.0,
            invocation_id=spec['invocation_id'],
        )
        self.service.port._reserve(spec)
        task2 = copy.deepcopy(self.task)
        task2.update(task_id='task-2', learning_task_id='task-learning-2')
        run2 = copy.deepcopy(self.run)
        run2.update(task_id='task-2', learning_task_id='task-learning-2', run_id='run-2')
        ownership2 = copy.deepcopy(self.ownership)
        ownership2.update(task_id='task-2', learning_task_id='task-learning-2')
        learning2 = copy.deepcopy(self.learning)
        learning2.update(task_id='task-2', learning_task_id='task-learning-2')
        self.service.create_task(
            policy=self.policy, task=task2, run=run2, ownership=ownership2,
            learning_state=learning2,
        )
        event2 = copy.deepcopy(self.loop_records['event'])
        event2.update(event_id='event-pending-other', task_id='task-2')
        self.service.accept_event(event2)
        step2, item2 = self.step_and_work('step-pending-other')
        step2['task_id'] = item2['task_id'] = 'task-2'
        step2['dependency_digests'] = []
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], steps=[step2], work_items=[item2],
        ))
        claimed = self.service.claim_step('healthy-owner', now=102.0)
        self.assertEqual(claimed['step']['step_id'], 'step-pending-other')
        invocation = self.service.port.get_invocation(spec['invocation_id'])
        self.assertEqual(invocation['result_state'], 'pending')
        old_step = json.loads(self.store.read(
            "SELECT record_json FROM steps WHERE step_id='step-1'"
        )[0]['record_json'])
        self.assertEqual(old_step['generation'], old['step']['generation'])
        self.assertEqual(self.service.claim_step('healthy-owner-2', now=102.0), None)

    def prepare_authorization(self, operation_id='operation-1'):
        for credential in self.records['review_credentials']:
            self.service.save_review_credential(credential)
        readiness = copy.deepcopy(self.records['readiness'])
        self.service.save_readiness(readiness)
        authorization = self.service.issue_ingest_authorization(
            task_id=self.task['task_id'], operation_id=operation_id,
            readiness_digest=self.records['authorization']['readiness_digest'],
            authorization_ref='authorization-' + operation_id,
        )
        admission = self.service.build_admission(
            run_id=self.run['run_id'], operation_id=operation_id,
            manifest_digest=self.records['admission']['manifest_digest'],
            readiness_digest=self.records['authorization']['readiness_digest'],
            authorization_ref=authorization['authorization_ref'],
        )
        return authorization, admission

    def test_event_replay_conflict_and_revision_condition_leave_durable_work(self):
        event, step, item = self.plan_one()
        replay = copy.deepcopy(event)
        replay['receipt_sequence'] = 99
        self.assertEqual(self.service.accept_event(replay)['receipt_sequence'], 1)
        changed = copy.deepcopy(event)
        changed['type'] = 'authorization_submitted'
        with self.assertRaises(LoopConflictError):
            self.service.accept_event(changed)
        self.assertEqual(len(self.store.read('SELECT * FROM events')), 1)
        self.assertEqual(len(self.store.read('SELECT * FROM work_items')), 1)

        second = copy.deepcopy(event)
        second['event_id'] = 'event-revision-conflict'
        self.service.accept_event(second)
        with self.assertRaises(LoopConflictError):
            self.service.plan_pending(lambda frozen: empty_proposal(
                frozen['task']['revision'] + 1,
            ))
        pending = self.store.read(
            "SELECT record_json FROM events WHERE json_extract(record_json, '$.processing_state')='pending'"
        )
        self.assertEqual(len(pending), 1)
        restarted = RuntimeService(self.store, executor=self.executor, clock=lambda: 100.0)
        self.assertEqual(len(restarted.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'],
        ))), 1)

    def test_two_processes_claim_exactly_one_work_item(self):
        self.plan_one()
        gate = Path(self.temporary.name) / 'claim-gate'
        configs = []
        processes = []
        for index in range(2):
            config = Path(self.temporary.name) / f'claim-{index}.json'
            config.write_text(json.dumps({
                'root': str(self.root), 'gate': str(gate), 'owner': f'process-{index}',
                'now': 100.0,
            }), encoding='utf-8')
            configs.append(config)
            processes.append(subprocess.Popen([
                sys.executable, '-B', str(PROCESS_FIXTURE), 'claim', str(config),
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        gate.write_text('go', encoding='utf-8')
        results = [process.communicate(timeout=20) for process in processes]
        self.assertCountEqual([process.returncode for process in processes], [0, 36], results)
        claimed = self.store.read('SELECT * FROM work_items')
        self.assertEqual(len(claimed), 1)
        self.assertIn('"state":"claimed"', claimed[0]['record_json'])

    def test_result_replay_conflict_and_stale_generation_are_rejected(self):
        self.plan_one()
        first = self.service.claim_step('owner-a', now=100.0)
        result = self.make_result(first)
        self.service.submit_step_result(
            result, work_item_id=first['work_item']['work_item_id'], claimed_by='owner-a',
            now=100.5,
        )
        self.assertEqual(self.service.submit_step_result(
            result, work_item_id=first['work_item']['work_item_id'], claimed_by='owner-a',
            now=100.5,
        ), result)
        changed = copy.deepcopy(result)
        changed['artifact_digests'] = ['7' * 64]
        changed['result_digest'] = digest({field: changed[field] for field in (
            'artifact_digests', 'domain_change_digest', 'wait_request_digest',
            'follow_up_digests', 'failure',
        )})
        with self.assertRaises(LoopConflictError):
            self.service.submit_step_result(
                changed, work_item_id=first['work_item']['work_item_id'], claimed_by='owner-a',
                now=100.5,
            )

        second_event = copy.deepcopy(self.loop_records['event'])
        second_event['event_id'] = 'event-takeover'
        second_event['receipt_sequence'] = 2
        self.service.accept_event(second_event)
        old_step, old_item = self.step_and_work('step-takeover')
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], steps=[old_step], work_items=[old_item],
        ))
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['invocation_id'] = 'invocation-takeover'
        spec['input_digest'] = old_step['input_digest']
        old = self.service.claim_step(
            'old-owner', now=200.0, lease_seconds=1.0, invocation_id=spec['invocation_id'],
        )
        original_result = self.make_result(old)
        self.service.port.invoke(spec, lambda: {
            'output': 'original', 'step_result_digest': original_result['result_digest'],
        }, 1.0)
        taken = self.service.claim_step('new-owner', now=202.0, lease_seconds=10.0)
        self.assertTrue(taken['takeover'])
        self.assertEqual(taken['step']['attempt'], old['step']['attempt'])
        self.assertEqual(taken['step']['generation'], old['step']['generation'] + 1)
        self.assertEqual(taken['work_item']['schedule_key'],
                         'step-takeover:attempt-1:generation-2')
        with self.assertRaises(LoopConflictError):
            self.service.submit_step_result(
                self.make_result(old), work_item_id=old['work_item']['work_item_id'],
                claimed_by='old-owner', now=202.5,
            )
        self.assertEqual(len(self.store.read('SELECT * FROM invocations')), 1)
        current = self.make_result(taken)
        self.service.submit_step_result(
            current, work_item_id=taken['work_item']['work_item_id'], claimed_by='new-owner',
            now=203.0, invocation_id=spec['invocation_id'],
        )

    def test_wait_answers_are_versioned_and_never_duplicate_assessment_work(self):
        self.plan_one()
        claim = self.service.claim_step('owner', now=100.0)
        wait = copy.deepcopy(self.loop_records['wait'])
        result = self.make_result(claim, waits=[wait])
        self.service.submit_step_result(
            result, work_item_id=claim['work_item']['work_item_id'], claimed_by='owner',
            proposal=empty_proposal(self.task['revision'], waits=[wait]), now=100.5,
        )
        answer = {
            'answer_id': 'answer-1', 'wait_id': wait['wait_id'], 'answer_revision': 1,
            'answer_digest': '8' * 64, 'answer_ref': None, 'knowledge_version': 1,
            'question_version': 1, 'rubric_version': 1,
        }
        next_step, next_work = self.step_and_work('step-assessment')
        accepted = self.service.answer_wait(answer, proposal=empty_proposal(
            self.task['revision'], steps=[next_step], work_items=[next_work],
        ))
        self.assertEqual(accepted['state'], 'accepted')
        self.assertTrue(self.service.answer_wait(answer)['replayed'])
        self.assertEqual(len(self.store.read('SELECT * FROM work_items')), 2)
        stale = dict(answer, answer_id='answer-stale', answer_revision=2, knowledge_version=2)
        self.assertEqual(self.service.answer_wait(stale)['state'], 'superseded')
        self.assertEqual(len(self.store.read('SELECT * FROM work_items')), 2)
        revised = dict(answer, answer_id='answer-revised', answer_revision=3)
        third_step, third_work = self.step_and_work('step-reassessment')
        self.assertEqual(self.service.answer_wait(revised, proposal=empty_proposal(
            self.task['revision'], steps=[third_step], work_items=[third_work],
        ))['state'], 'accepted')
        self.assertEqual(len(self.store.read('SELECT * FROM work_items')), 3)
        self.assertEqual(len(self.store.read('SELECT * FROM wait_answers')), 3)
        superseded_wait = dict(wait, consumption_state='superseded')
        self.store.mutate(lambda connection: connection.execute(
            'UPDATE waits SET record_json=? WHERE wait_id=?',
            (json.dumps(superseded_wait, sort_keys=True, separators=(',', ':')), wait['wait_id']),
        ))
        expired = dict(answer, answer_id='answer-expired', answer_revision=4)
        self.assertEqual(self.service.answer_wait(expired)['state'], 'superseded')
        self.assertEqual(len(self.store.read('SELECT * FROM work_items')), 3)

    def test_authorization_requires_current_attested_credentials_and_immutable_records(self):
        readiness = copy.deepcopy(self.records['readiness'])
        self.service.save_readiness(readiness)
        self.service.save_unattested_review_evidence({
            'evidence_id': 'unattested-1', 'learning_task_id': self.task['learning_task_id'],
            'operation_id': 'operation-unattested', 'content_digest': '9' * 64,
            'review_digest': 'a' * 64, 'validator_version': 'synthetic-v1',
        })
        with self.assertRaises(AuthorizationError):
            self.service.issue_ingest_authorization(
                task_id=self.task['task_id'], operation_id='operation-unattested',
                readiness_digest=self.records['authorization']['readiness_digest'],
            )
        for credential in self.records['review_credentials']:
            self.service.save_review_credential(credential)
        authorization, admission = self.prepare_authorization()
        with self.service.acceptance_context(admission) as context:
            self.assertEqual(context['authorization']['state'], 'issued')
            self.assertEqual(context['readiness']['state'], 'current')
        original = self.store.read('SELECT * FROM readiness_records')[0]
        with self.assertRaises(RuntimeStoreError):
            self.store.mutate(lambda connection: connection.execute(
                'UPDATE readiness_records SET record_json=? WHERE readiness_digest=?',
                ('{}', original['readiness_digest']),
            ))
        self.service.invalidate_credential('assessor-opinion-1', reason='测试失效')
        with self.assertRaises(AdmissionError):
            with self.service.acceptance_context(admission):
                pass
        self.assertEqual(authorization['state'], 'issued')

    def test_acceptance_context_holds_write_serialization_until_exit(self):
        _authorization, admission = self.prepare_authorization()
        second = RuntimeStore(self.root, busy_timeout=0.1)
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def holder():
            try:
                with self.service.acceptance_context(admission):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError('acceptance_context 测试屏障超时')
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(entered.wait(2))
        with self.assertRaises(RuntimeStoreError):
            second.mutate(lambda connection: connection.execute(
                'UPDATE task_finance SET block_reason=block_reason WHERE task_id=?',
                (self.task['task_id'],),
            ))
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        second.close()
        with self.service.acceptance_context(admission):
            pass

    def test_pause_resume_supersedes_pre_wal_binding_and_forbids_rebind(self):
        authorization, admission = self.prepare_authorization()
        paused = self.service.pause(self.task['task_id'])
        self.assertEqual(paused['submission_epoch'], 2)
        binding = self.store.read('SELECT * FROM operation_admissions')[0]
        self.assertEqual(binding['binding_state'], 'superseded_by_pause')
        with self.assertRaises(AdmissionError):
            with self.service.acceptance_context(admission):
                pass
        new_run = copy.deepcopy(self.run)
        new_run['run_id'] = 'run-after-pause'
        new_ownership = copy.deepcopy(self.ownership)
        new_ownership['generation'] += 1
        new_ownership['owner'] = 'owner-after-pause'
        resumed = self.service.resume(
            self.task['task_id'], run=new_run, ownership=new_ownership,
        )
        self.assertEqual(resumed['task']['task_id'], self.task['task_id'])
        old_auth = self.store.read('SELECT record_json FROM authorizations')[0]
        self.assertIn('"state":"expired"', old_auth['record_json'])
        replacement_auth = self.service.issue_ingest_authorization(
            task_id=self.task['task_id'], operation_id=admission['operation_id'],
            readiness_digest=admission['readiness_digest'],
        )
        with self.assertRaises(AdmissionError):
            self.service.build_admission(
                run_id=new_run['run_id'], operation_id=admission['operation_id'],
                manifest_digest=admission['manifest_digest'],
                readiness_digest=admission['readiness_digest'],
                authorization_ref=replacement_auth['authorization_ref'],
            )
        new_operation = 'operation-after-pause'
        new_auth = self.service.issue_ingest_authorization(
            task_id=self.task['task_id'], operation_id=new_operation,
            readiness_digest=admission['readiness_digest'],
        )
        new_admission = self.service.build_admission(
            run_id=new_run['run_id'], operation_id=new_operation,
            manifest_digest=admission['manifest_digest'],
            readiness_digest=admission['readiness_digest'],
            authorization_ref=new_auth['authorization_ref'],
        )
        self.assertNotEqual(new_admission['submission_epoch'], admission['submission_epoch'])
        with self.service.acceptance_context(new_admission):
            pass

    def test_takeover_without_original_invocation_binding_is_rejected(self):
        self.plan_one()
        self.service.claim_step('old-owner', now=100.0, lease_seconds=1.0)
        with self.assertRaises(LoopConflictError):
            self.service.claim_step('new-owner', now=102.0)
        self.assertEqual(len(self.store.read('SELECT * FROM step_results')), 0)

    def test_takeover_with_unknown_invocation_cannot_fabricate_success(self):
        self.plan_one()
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['input_digest'] = self.loop_records['step']['input_digest']
        self.service.claim_step(
            'old-owner', now=100.0, lease_seconds=1.0, invocation_id=spec['invocation_id'],
        )
        unknown = self.service.port.invoke(spec, lambda: time.sleep(0.05) or {'output': 'late'}, 0.001)
        self.assertEqual(unknown['state'], 'unknown')
        with self.assertRaises(LoopConflictError):
            self.service.claim_step('new-owner', now=102.0, lease_seconds=10.0)
        step = json.loads(self.store.read('SELECT record_json FROM steps')[0]['record_json'])
        self.assertEqual(step['generation'], 1)
        self.assertEqual(step['state'], 'blocked')
        self.assertIsNone(self.service.claim_step('third-owner', now=104.0))
        self.assertEqual(self.service.port.replay(spec)['state'], 'unknown')
        self.assertEqual(len(self.store.read('SELECT * FROM step_results')), 0)
        self.assertEqual(len(self.store.read('SELECT * FROM invocations')), 1)

    def test_dependency_change_rejects_old_claimed_result(self):
        event = copy.deepcopy(self.loop_records['event'])
        self.service.accept_event(event)
        step, item = self.step_and_work()
        step['dependency_digests'] = [learning_state_digest(self.learning)]
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], steps=[step], work_items=[item],
        ))
        claim = self.service.claim_step('owner', now=100.0)
        second = copy.deepcopy(event)
        second['event_id'] = 'event-dependency-change'
        self.service.accept_event(second)
        changed_learning = dict(self.learning, knowledge_version=2)
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], learning_state=changed_learning,
        ))
        with self.assertRaises(LoopConflictError):
            self.service.submit_step_result(
                self.make_result(claim), work_item_id=claim['work_item']['work_item_id'],
                claimed_by='owner', now=100.5,
            )
        current = json.loads(self.store.read('SELECT record_json FROM steps')[0]['record_json'])
        self.assertEqual(current['state'], 'running')
        self.assertIsNone(current['result_digest'])

    def test_policy_switch_updates_finance_without_resetting_consumption(self):
        changed = copy.deepcopy(self.policy)
        changed['revision'] = 2
        changed['budget']['model_calls'] = 0
        changed['policy_digest'] = digest({field: changed[field] for field in (
            'revision', 'budget', 'stop_policy', 'creation_reason',
        )})
        self.service.switch_policy(self.task['task_id'], changed)
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['policy_digest'] = changed['policy_digest']
        with self.assertRaises(InvocationLimitError):
            self.service.port.invoke(spec, lambda: {'output': 'must-not-run'}, 1.0)
        for table in ('task_finance', 'run_finance'):
            account = self.store.read(f'SELECT * FROM {table}')[0]
            self.assertEqual(json.loads(account['budget_json'])['model_calls'], 0)
            self.assertEqual(json.loads(account['actual_json'])['model_calls'], 0)
            self.assertEqual(account['blocked'], 0)
        self.assertEqual(self.store.read('SELECT * FROM invocations'), [])

    def test_policy_switch_invalidates_old_admission_without_mutating_policy(self):
        _authorization, admission = self.prepare_authorization()
        changed = copy.deepcopy(self.policy)
        changed['revision'] = 2
        changed['budget']['model_calls'] += 1
        changed['policy_digest'] = digest({field: changed[field] for field in (
            'revision', 'budget', 'stop_policy', 'creation_reason',
        )})
        self.service.switch_policy(self.task['task_id'], changed)
        with self.assertRaises(AdmissionError):
            with self.service.acceptance_context(admission):
                pass
        self.assertEqual(self.store.read('SELECT * FROM policy_revisions')[0]['record_json'],
                         json.dumps(self.policy, sort_keys=True, separators=(',', ':')))
        replacement = self.service.issue_ingest_authorization(
            task_id=self.task['task_id'], operation_id=admission['operation_id'],
            readiness_digest=admission['readiness_digest'],
        )
        with self.assertRaises(AdmissionError):
            self.service.build_admission(
                run_id=self.run['run_id'], operation_id=admission['operation_id'],
                manifest_digest=admission['manifest_digest'],
                readiness_digest=admission['readiness_digest'],
                authorization_ref=replacement['authorization_ref'],
            )

    def test_takeover_replays_original_invocation_without_new_call_or_charge(self):
        self.plan_one()
        spec = copy.deepcopy(self.records['invocation_spec'])
        spec['input_digest'] = self.loop_records['step']['input_digest']
        old = self.service.claim_step(
            'old-owner', now=100.0, lease_seconds=1.0, invocation_id=spec['invocation_id'],
        )
        calls = []
        original_result = self.make_result(old)
        transport_result = {
            'output': 'original', 'step_result_digest': original_result['result_digest'],
        }
        self.service.port.invoke(
            spec, lambda: calls.append('called') or transport_result, 1.0,
        )
        taken = self.service.claim_step('new-owner', now=102.0, lease_seconds=10.0)
        self.assertEqual(self.service.port.replay(spec), transport_result)
        self.assertEqual(calls, ['called'])
        self.assertEqual(len(self.store.read('SELECT * FROM invocations')), 1)
        account = json.loads(self.store.read('SELECT actual_json FROM task_finance')[0]['actual_json'])
        self.assertEqual(account['model_calls'], 1)
        forged_learning = dict(self.learning, state='applied')
        forged = self.make_result(taken, learning_state=forged_learning)
        with self.assertRaises(LoopConflictError):
            self.service.submit_step_result(
                forged, work_item_id=taken['work_item']['work_item_id'],
                claimed_by='new-owner', now=103.0, invocation_id=spec['invocation_id'],
                proposal=empty_proposal(self.task['revision'], learning_state=forged_learning),
            )
        stored_learning = json.loads(
            self.store.read('SELECT record_json FROM learning_states')[0]['record_json']
        )
        self.assertEqual(stored_learning['state'], 'awaiting_confirmation')
        self.service.submit_step_result(
            self.make_result(taken), work_item_id=taken['work_item']['work_item_id'],
            claimed_by='new-owner', now=103.0, invocation_id=spec['invocation_id'],
        )

    def test_retry_policy_preserves_attempts_and_stops_identical_failures(self):
        self.plan_one()
        failure = {
            'category': 'environment', 'fingerprint': '6' * 64,
            'reason': 'synthetic transport stopped',
        }
        first = self.service.claim_step('owner', now=100.0)
        self.service.submit_step_result(
            self.make_result(first, failure=failure),
            work_item_id=first['work_item']['work_item_id'], claimed_by='owner', now=100.5,
        )
        retried = self.service.loop.retry_step('step-1', failure['fingerprint'])
        self.assertEqual(retried['step']['attempt'], 2)
        second = self.service.claim_step('owner', now=101.0)
        self.assertEqual(second['step']['attempt'], 2)
        self.service.submit_step_result(
            self.make_result(second, failure=failure),
            work_item_id=second['work_item']['work_item_id'], claimed_by='owner', now=101.5,
        )
        with self.assertRaises(LoopConflictError):
            self.service.loop.retry_step('step-1', failure['fingerprint'])
        task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
        self.assertEqual(task['state'], 'blocked')
        self.assertEqual(len(self.store.read('SELECT * FROM step_results')), 2)

    def test_pause_with_wal_before_reconcile_preserves_original_execution_binding(self):
        _authorization, admission = self.prepare_authorization('wal-before-reconcile')
        journal = self.executor._journal(admission['operation_id'])
        journal.parent.mkdir(parents=True, exist_ok=True)
        result = copy.deepcopy(self.records['execution_results']['prepared'])
        result['operation_id'] = admission['operation_id']
        manifest = {field: result[field] for field in (
            'operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
        )}
        manifest.update(
            mapping_digest='0' * 64, validator_version='synthetic-v1',
            review_prompt_version='synthetic-review-v1',
        )
        journal.write_text(json.dumps({
            'manifest': manifest, 'state': 'prepared', 'steps': [],
            'admission_digest': admission_digest(admission),
        }), encoding='utf-8')
        self.service.pause(self.task['task_id'])
        binding = self.store.read('SELECT * FROM operation_admissions')[0]
        self.assertEqual(binding['binding_state'], 'active')
        projected = self.service.reconcile_execution(result)
        self.assertTrue(projected['accepted'])
        self.assertFalse(projected['applied'])

    def test_reconcile_is_idempotent_and_recovered_or_conflict_is_not_applied(self):
        cases = (
            ('recovered', 'recovered'), ('conflict', 'conflict'), ('applied', 'applied'),
        )
        for key, operation_id in cases:
            with self.subTest(key=key):
                authorization, admission = self.prepare_authorization(operation_id)
                binding = copy.deepcopy(self.records['execution_results'][key])
                binding['operation_id'] = operation_id
                manifest = {field: binding[field] for field in (
                    'operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
                )}
                manifest.update(
                    mapping_digest='0' * 64, validator_version='synthetic-v1',
                    review_prompt_version='synthetic-review-v1',
                )
                journal = self.executor._journal(operation_id)
                journal.parent.mkdir(parents=True, exist_ok=True)
                journal.write_text(json.dumps({
                    'manifest': manifest,
                    'state': 'recovery_required' if key == 'conflict' else key,
                    'recovery_status': binding['recovery_status'],
                    'steps': [], 'admission_digest': admission_digest(admission),
                }), encoding='utf-8')
                projected = self.service.reconcile_execution(binding)
                self.assertEqual(projected['applied'], key == 'applied')
                self.assertEqual(projected['authorization_consumed'], key == 'applied')
                self.assertEqual(self.service.reconcile_execution(binding), projected)
                auth = self.store.read(
                    "SELECT record_json FROM authorizations WHERE authorization_ref='"
                    + authorization['authorization_ref'].replace("'", "''") + "'"
                )
                self.assertEqual(
                    json.loads(auth[0]['record_json'])['state'],
                    'consumed' if key == 'applied' else 'issued',
                )
                if key != 'applied':
                    with self.service.acceptance_context(admission):
                        pass
                if key == 'conflict':
                    forged = copy.deepcopy(self.records['execution_results']['applied'])
                    forged['operation_id'] = operation_id
                    with self.assertRaises(ExecutionReconcileError):
                        self.service.reconcile_execution(forged)
                    task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
                    self.assertEqual(task['state'], 'running')
        applied = self.store.read(
            "SELECT record_json FROM operation_admissions WHERE operation_id='applied'"
        )[0]
        self.assertIsNotNone(applied)

    def test_reconcile_rejects_caller_forged_conflict_without_wal_evidence(self):
        _authorization, admission = self.prepare_authorization('forged-conflict')
        forged = copy.deepcopy(self.records['execution_results']['conflict'])
        forged['operation_id'] = admission['operation_id']
        manifest = {field: forged[field] for field in (
            'operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
        )}
        manifest.update(
            mapping_digest='0' * 64, validator_version='synthetic-v1',
            review_prompt_version='synthetic-review-v1',
        )
        journal = self.executor._journal(admission['operation_id'])
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(json.dumps({
            'manifest': manifest, 'state': 'recovery_required', 'steps': [],
            'admission_digest': admission_digest(admission),
        }), encoding='utf-8')
        with self.assertRaisesRegex(ExecutionReconcileError, 'recovery_status'):
            self.service.reconcile_execution(forged)
        self.assertEqual(self.store.read('SELECT * FROM execution_results'), [])

    def test_generic_proposals_cannot_pause_task_or_preserve_old_execution_binding(self):
        _authorization, admission = self.prepare_authorization()
        event = copy.deepcopy(self.loop_records['event'])
        self.service.accept_event(event)
        before_run = self.store.read('SELECT record_json FROM runs')
        before_binding = self.store.read('SELECT * FROM operation_admissions')
        before_auth = self.store.read('SELECT record_json FROM authorizations')
        with self.assertRaises(LoopConflictError):
            self.service.plan_pending(lambda frozen: empty_proposal(
                frozen['task']['revision'], task_state='paused',
            ))
        task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
        self.assertEqual(task['state'], 'running')
        self.assertEqual(self.store.read('SELECT record_json FROM runs'), before_run)
        self.assertEqual(self.store.read('SELECT * FROM operation_admissions'), before_binding)
        self.assertEqual(self.store.read('SELECT record_json FROM authorizations'), before_auth)
        step, item = self.step_and_work()
        self.service.plan_pending(lambda frozen: empty_proposal(
            frozen['task']['revision'], steps=[step], work_items=[item],
        ))
        claim = self.service.claim_step('owner', now=100.0)
        with self.assertRaises(LoopConflictError):
            self.service.submit_step_result(
                self.make_result(claim), work_item_id=claim['work_item']['work_item_id'],
                claimed_by='owner', proposal=empty_proposal(
                    self.task['revision'], task_state='paused',
                ), now=100.5,
            )
        task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
        self.assertEqual(task['state'], 'running')
        self.assertEqual(task['submission_epoch'], admission['submission_epoch'])
        self.assertEqual(self.store.read('SELECT record_json FROM runs'), before_run)
        self.assertEqual(self.store.read('SELECT * FROM operation_admissions'), before_binding)
        self.assertEqual(self.store.read('SELECT record_json FROM authorizations'), before_auth)
        self.assertEqual(self.store.read('SELECT * FROM step_results'), [])


if __name__ == '__main__':
    unittest.main()
