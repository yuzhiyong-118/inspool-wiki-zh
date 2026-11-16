"""S1 T7：X／L／C 组合故障矩阵的真实临时库场景。"""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import unittest

from tools.tests import test_executor_recovery as recovery_fixtures
from tools.tests import test_learning_s1_cutover as cutover_case_module
from tools.tests import test_learning_s1_entrypoints as entrypoint_case_module
from tools.tests import test_learning_s1_executor as executor_case_module
from tools.tests import test_learning_s1_executor_compat as compat_case_module
from tools.tests import test_learning_s1_host as host_case_module
from tools.tests import test_learning_s1_runtime as runtime_case_module
from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.executor import Executor, ExecutionError
from tools.wiki_runtime.host.supervisor import HostError
from tools.wiki_runtime.runtime import (
    AuthorizationError, ExecutionReconcileError, InvocationConflictError, empty_proposal,
    readiness_digest, review_credential_digest,
)
from tools.wiki_runtime.runtime.identity import AttestationError, record_review_identity


PROJECT = Path(__file__).resolve().parents[2]
SCENARIOS = PROJECT / 'tools/tests/fixtures/learning_s1/scenarios.json'


def ExecutorAcceptanceTests():
    return executor_case_module.ExecutorAcceptanceTests()


def HostConcurrencyTests():
    return host_case_module.HostConcurrencyTests()


def RegistryAndDriverTests():
    return host_case_module.RegistryAndDriverTests()


def RuntimeLoopTests():
    return runtime_case_module.RuntimeLoopTests()


def RuntimeTests():
    return runtime_case_module.RuntimeTests()


def ExecutorCompatibilityTests():
    return compat_case_module.ExecutorCompatibilityTests()


def CutoverTests():
    return cutover_case_module.CutoverTests()


def EntrypointTests():
    return entrypoint_case_module.EntrypointTests()


@contextmanager
def fixture(case):
    """复用既有真实故障构造器，同时保证组合子场景及时释放进程与 SQLite。"""
    case.setUpClass()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()
        case.doCleanups()


class ExecutionScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(SCENARIOS.read_text(encoding='utf-8'))['groups']['X']['scenarios']
        cls.by_id = {scenario['id']: scenario for scenario in cls.matrix}
        if set(cls.by_id) != {f'X{index}' for index in range(1, 13)}:
            raise AssertionError('X 组场景清单必须完整且唯一')
        for scenario in cls.matrix:
            if not callable(getattr(cls, scenario['test'], None)):
                raise AssertionError('场景未绑定真实测试: ' + scenario['id'])

    def test_x01_g3_interference_never_accepts(self):
        actions = {
            'revoke': lambda case, admission: case.service.revoke_ingest_authorization(
                admission['authorization_ref']),
            'pause': lambda case, _admission: case.service.pause(case.task['task_id']),
            'readiness_invalidation': lambda case, admission: case.service.invalidate_readiness(
                admission['readiness_digest'], reason='X1 组合失效'),
            'ownership_generation': self._change_ownership,
        }
        for name, action in actions.items():
            with self.subTest(scenario='X1', fault=name), fixture(ExecutorAcceptanceTests()) as case:
                admission = case.interfere_during_review(
                    lambda current, action=action, case=case: action(case, current))
                self.assertFalse(case.journal_path(admission['operation_id']).exists())
        with self.subTest(scenario='X1', fault='actual_g3_overage'), fixture(
                ExecutorAcceptanceTests()) as case:
            case.test_actual_g3_overage_blocks_acceptance_without_wal()
            self.assertEqual(len(case.store.read('SELECT * FROM execution_results')), 0)

    @staticmethod
    def _change_ownership(case, _admission):
        changed = copy.deepcopy(case.ownership)
        changed['generation'] += 1
        changed['owner'] = 'x1-new-owner'
        case.store.mutate(lambda connection: connection.execute(
            'UPDATE execution_ownerships SET owner=?, generation=?, record_json=? WHERE task_id=?',
            (changed['owner'], changed['generation'], json.dumps(changed), case.task['task_id']),
        ))

    def test_x02_acceptance_crash_has_one_outcome(self):
        with self.subTest(scenario='X2', fault='before_wal'), fixture(
                ExecutorAcceptanceTests()) as case:
            config, _bundle, admission = case.process_config('x2-before-wal', review_timeout=600)
            case.run_managed(config, 'after_acceptance_before_prepare', expected=87)
            self.assertFalse(case.journal_path(admission['operation_id']).exists())
            result = case.run_managed(config)
            self.assertEqual(result['state'], 'applied')
            self.assertEqual(len(case.store.read('SELECT * FROM invocations')), 1)
        for fault, expected, applied in (
            ('after_prepare', 'recovered', False),
            ('after_commit', 'applied', True),
        ):
            with self.subTest(scenario='X2', fault=fault), fixture(
                    ExecutorAcceptanceTests()) as case:
                config, bundle, admission = case.process_config('x2-' + fault)
                case.run_managed(config, fault, expected=87)
                journal = case.journal_path(admission['operation_id'])
                self.assertTrue(journal.exists())
                wal_before = journal.read_bytes()
                recovered = Executor(case.root, case.journal).recover(admission['operation_id'])
                self.assertEqual(recovered['state'], expected)
                projected = case.service.reconcile_execution(
                    case.result_binding(admission, recovered))
                self.assertEqual(projected['applied'], applied)
                replay = case.make_executor(
                    reviewer=self._forbidden_dynamic,
                    invocation_port=self._forbidden_dynamic,
                    acceptance_context=self._forbidden_dynamic,
                )
                self.assertEqual(replay.apply(bundle, admission=admission), recovered)
                if applied:
                    self.assertEqual(journal.read_bytes(), wal_before)
                else:
                    self.assertEqual(json.loads(journal.read_bytes())['state'], 'recovered')

    def test_x03_invocation_reentry_crash_and_replay(self):
        import subprocess
        import sys
        import time
        from tools.tests.test_learning_s1_runtime import PROCESS_FIXTURE, wait_for

        for name, method in (
            ('same_process_active_reentry', 'test_same_process_active_reentry_is_busy_and_never_takes_over'),
            ('not_started_send_race', 'test_not_started_send_race_has_exactly_one_transport_winner'),
        ):
            with self.subTest(scenario='X3', fault=name), fixture(RuntimeTests()) as case:
                getattr(case, method)()
                for table in ('task_finance', 'run_finance'):
                    account = json.loads(case.store.read(
                        f'SELECT actual_json FROM {table}')[0]['actual_json'])
                    self.assertEqual(account['model_calls'], 1)
        with fixture(RuntimeTests()) as case:
            root = Path(case.temporary.name) / 'x3-process-recovery'
            store, port, spec = case.make_runtime(root, concurrency=2)
            prefix = Path(case.temporary.name) / 'x3-recovery'
            started = prefix.with_suffix('.started')
            release = prefix.with_suffix('.release')
            original_config = prefix.with_suffix('.json')
            original_config.write_text(json.dumps({
                'root': str(root), 'spec': spec, 'started': str(started),
                'release': str(release), 'timeout': 30.0,
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
                before_execution = port.get_execution(spec['invocation_id'])
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
                recovered = port.recover_invocation(spec['invocation_id'], {
                    'execution_token': before_execution['execution_token'],
                    'recovery_epoch': before_execution['recovery_epoch'],
                    'executor_stopped': True,
                })
                self.assertEqual(recovered['resource_state'], 'draining')
                self.assertEqual(recovered['recovery_epoch'], before_execution['recovery_epoch'] + 1)
                port.confirm_resource_released(spec['invocation_id'], {
                    'execution_token': recovered['execution_token'],
                    'recovery_epoch': recovered['recovery_epoch'],
                    'executor_stopped': True,
                })
                self.assertEqual(
                    port.get_execution(spec['invocation_id'])['resource_state'], 'released')
                self.assertEqual(port.replay(spec)['state'], 'unknown')
                self.assertEqual(started.read_text(encoding='utf-8').splitlines(),
                                 [spec['invocation_id']])
                before = {
                    table: store.read(f'SELECT actual_json FROM {table}')
                    for table in ('task_finance', 'run_finance')
                }
                for rows in before.values():
                    self.assertEqual(json.loads(rows[0]['actual_json'])['model_calls'], 1)
                changed = copy.deepcopy(spec)
                changed['input_digest'] = '0' * 64
                with self.assertRaises(InvocationConflictError):
                    port.replay(changed)
                for table, expected in before.items():
                    self.assertEqual(store.read(f'SELECT actual_json FROM {table}'), expected)
                self.assertEqual(len(store.read('SELECT * FROM invocations')), 1)
            finally:
                if original.poll() is None:
                    original.kill()
                    original.communicate(timeout=10)

    def test_x04_nonterminal_states_recover_without_success(self):
        for fault, expected in (
            ('after_prepare', 'prepared'),
            ('after_applying', 'applying'),
            ('after_write', 'recovery_required'),
        ):
            with self.subTest(scenario='X4', fault=fault), fixture(
                    ExecutorAcceptanceTests()) as case:
                config, bundle, admission = case.process_config('x4-' + fault)
                case.run_managed(config, fault, expected=87)
                journal_path = case.journal_path(admission['operation_id'])
                journal = json.loads(journal_path.read_bytes())
                executor = Executor(case.root, case.journal)
                if fault == 'after_write':
                    def stop_recovery(event, index):
                        if event == 'recover_before_intent' and index == 0:
                            raise RuntimeError('X4 恢复中断')
                    current = Executor(
                        case.root, case.journal, fault=stop_recovery,
                    ).recover(admission['operation_id'])
                else:
                    current = executor._result(journal)
                self.assertEqual(current['state'], expected, current)
                projected = case.service.reconcile_execution(
                    case.result_binding(admission, current))
                self.assertFalse(projected['applied'])
                self.assertFalse(projected['authorization_consumed'])
                recovered = executor.recover(admission['operation_id'])
                self.assertEqual(recovered['state'], 'recovered', recovered)
                projected = case.service.reconcile_execution(
                    case.result_binding(admission, recovered))
                self.assertFalse(projected['applied'])
                self.assertEqual(executor.apply(bundle, admission=admission), recovered)
                with self.assertRaises(AuthorizationError):
                    case.service.issue_ingest_authorization(
                        task_id=case.task['task_id'], operation_id=admission['operation_id'],
                        readiness_digest=admission['readiness_digest'],
                    )

    def test_x05_terminal_replay_ignores_dynamic_state(self):
        for terminal in ('applied', 'recovered'):
            with self.subTest(scenario='X5', terminal=terminal), fixture(
                    ExecutorAcceptanceTests()) as case:
                config, bundle, admission = case.process_config('x5-' + terminal)
                if terminal == 'applied':
                    result = case.run_managed(config)
                else:
                    case.run_managed(config, 'after_prepare', expected=87)
                    result = Executor(case.root, case.journal).recover(admission['operation_id'])
                self.assertEqual(result['state'], terminal)
                case.service.reconcile_execution(case.result_binding(admission, result))
                if terminal == 'recovered':
                    case.service.pause(case.task['task_id'])
                case.store.mutate(lambda connection: (
                    connection.execute('UPDATE task_finance SET blocked=1'),
                    connection.execute(
                        "UPDATE execution_ownerships SET expires_at=0, "
                        "record_json=json_set(record_json, '$.expires_at', 0)"),
                ))
                for payload in Path(bundle['payload_root']).iterdir():
                    payload.unlink()
                case.write('wiki/unrelated.md', '库内无关变化\n')
                before = case.snapshot()
                wal_before = case.journal_path(admission['operation_id']).read_bytes()
                finance_before = case.store.read('SELECT * FROM task_finance')
                invocations_before = case.store.read('SELECT * FROM invocations')
                replay = case.make_executor(
                    reviewer=self._forbidden_dynamic,
                    invocation_port=self._forbidden_dynamic,
                    acceptance_context=self._forbidden_dynamic,
                )
                self.assertEqual(replay.apply(bundle, admission=admission), result)
                self.assertEqual(case.snapshot(), before)
                self.assertEqual(case.journal_path(admission['operation_id']).read_bytes(), wal_before)
                self.assertEqual(case.store.read('SELECT * FROM task_finance'), finance_before)
                self.assertEqual(case.store.read('SELECT * FROM invocations'), invocations_before)
                changed = dict(admission, authorization_ref='x5-other-admission')
                with self.assertRaisesRegex(ExecutionError, '不同 Admission'):
                    replay.apply(bundle, admission=changed)
        with self.subTest(scenario='X5', terminal='host_applied'), fixture(
                HostConcurrencyTests()) as case:
            case.prepare_learning()
            first = case.host.apply_pending('host-t5')
            self.assertTrue(first['applied'], first)
            case.host.runtime.store.mutate(lambda connection: (
                connection.execute('UPDATE task_finance SET blocked=1'),
                connection.execute(
                    "UPDATE execution_ownerships SET expires_at=0, "
                    "record_json=json_set(record_json, '$.expires_at', 0)"),
            ))
            wal_before = case.journal_path().read_bytes()
            replay = case.host.apply_pending('host-t5')
            self.assertTrue(replay['applied'], replay)
            self.assertEqual(replay['execution'], first['execution'])
            self.assertEqual(case.journal_path().read_bytes(), wal_before)
        with self.subTest(scenario='X5', terminal='host_recovered'), fixture(
                HostConcurrencyTests()) as case:
            prepared, _authorization = case.prepare_learning()
            record = case.host.load_pending('host-t5')
            learning = record['learning']
            admission = case.host.runtime.build_admission(
                run_id=learning['run_id'], operation_id='host-t5',
                manifest_digest=digest(record['bundle']['manifest']),
                readiness_digest=learning['readiness_digest'],
                authorization_ref=learning['authorization_ref'],
            )
            coordinator = case.host._coordinator(record['config'], learning=True)
            executor = case.host._executor(coordinator, managed=True)
            def stop_after_prepare(event, _index):
                if event == 'after_prepare':
                    raise RuntimeError('X5 Host 接受后崩溃')
            executor.fault = stop_after_prepare
            interrupted = executor.apply(prepared['bundle'], admission=admission)
            self.assertEqual(interrupted['state'], 'prepared')
            case.host.pause_learning(learning['task_id'])
            recovered = case.host.recover('host-t5')
            self.assertEqual(recovered['execution']['state'], 'recovered')
            self.assertFalse(recovered['applied'])
            case.host.runtime.store.mutate(lambda connection: (
                connection.execute('UPDATE task_finance SET blocked=1'),
                connection.execute(
                    "UPDATE execution_ownerships SET expires_at=0, "
                    "record_json=json_set(record_json, '$.expires_at', 0)"),
            ))
            wal_before = case.journal_path().read_bytes()
            replay = case.host.apply_pending('host-t5')
            self.assertEqual(replay['execution'], recovered['execution'])
            self.assertFalse(replay['applied'])
            self.assertEqual(case.journal_path().read_bytes(), wal_before)

    def test_x06_host_revoke_and_pause_stay_responsive(self):
        scenarios = (
            ('same_host_revoke', 'test_same_host_revoke_completes_during_g3_and_prevents_wal'),
            ('cross_process_revoke', 'test_cross_process_revoke_uses_executor_barrier_during_g3'),
            ('same_host_pause', 'test_learning_pause_same_host_thread_prevents_wal'),
            ('cross_process_pause', 'test_learning_pause_cross_process_prevents_wal'),
        )
        for name, method in scenarios:
            with self.subTest(scenario='X6', fault=name), fixture(HostConcurrencyTests()) as case:
                getattr(case, method)()
                self.assertFalse(case.journal_path().exists())

    def test_x07_identity_and_scope_negative_matrix(self):
        from tools.wiki_runtime.runtime.identity import invoke_with_optional_attestation

        with self.subTest(scenario='X7', fault='trusted_transport_positive'), fixture(
                RegistryAndDriverTests()) as case:
            case.test_native_dispatcher_can_supply_bound_attestation()
        with self.subTest(scenario='X7', fault='self_signed_transport'):
            class SelfSignedTransport:
                def __call__(self, _envelope, *, timeout):
                    return {'result': 'recommend_pass'}

                def invoke_attested(self, _envelope, *, timeout):
                    raise AssertionError('自定义 transport 不得进入可信 Attestation 通道')

            response = invoke_with_optional_attestation(
                SelfSignedTransport(), {'system': 'synthetic', 'input': {}}, timeout=1,
            )
            self.assertIsNone(response['attestation'])
        with fixture(RuntimeLoopTests()) as case:
            envelope = {'system': 'synthetic', 'input': {'candidate': 'A'}, 'reviewer_id': 'reviewer'}
            arguments = dict(
                invocation_id='x7-invocation', learning_task_id=case.task['learning_task_id'],
                operation_id='x7-operation', role='Reviewer', content_digest=digest('content'),
                evidence_digest=digest(envelope), dependencies_digest=digest('dependencies'),
                rules_digest=digest('rules'),
                review_config={'validator_version': 'synthetic-v1',
                               'review_prompt_version': 'synthetic-p1'},
                review_request=envelope, opinion={'result': 'recommend_pass'},
                package_ref={'package_id': 'synthetic', 'version': 1, 'digest': digest('package')},
                objective_ids=[], scope_kind='candidate_content_review',
            )
            unattested = record_review_identity(case.service, attestation=None, **arguments)
            self.assertEqual(unattested, {'credential_reuse': 'disabled', 'credential': None})
            readiness = copy.deepcopy(case.records['readiness'])
            case.service.save_readiness(readiness)
            with self.assertRaises(AuthorizationError):
                case.service.issue_ingest_authorization(
                    task_id=case.task['task_id'], operation_id='x7-unattested',
                    readiness_digest=readiness_digest(readiness),
                )
            valid = {
                'request_id': 'x7-request', 'session_id': 'x7-child', 'role': 'reviewer',
                'independent': True, 'context_digest': digest(envelope),
            }
            for name, update in (
                ('missing_request_identity', {'request_id': ''}),
                ('wrong_role', {'role': 'worker'}),
                ('cross_scope', {'context_digest': '0' * 64}),
            ):
                with self.subTest(scenario='X7', fault=name), self.assertRaises(AttestationError):
                    record_review_identity(
                        case.service, attestation=dict(valid, **update),
                        **dict(arguments, invocation_id='x7-' + name),
                    )
            for credential in case.records['review_credentials']:
                case.service.save_review_credential(credential)
            valid_authorization = case.service.issue_ingest_authorization(
                task_id=case.task['task_id'], operation_id='x7-valid-candidate',
                readiness_digest=readiness_digest(readiness),
            )
            self.assertEqual(valid_authorization['state'], 'issued')
            wrong = copy.deepcopy(case.records['review_credentials'][0])
            wrong['credential_id'] = 'x7-wrong-candidate'
            wrong['scope']['candidate_digest'] = '0' * 64
            case.service.save_review_credential(wrong)
            readiness['required_credentials'][0].update(
                credential_ref=wrong['credential_id'],
                credential_digest=review_credential_digest(wrong),
            )
            case.service.save_readiness(readiness)
            with self.assertRaises(AuthorizationError):
                case.service.issue_ingest_authorization(
                    task_id=case.task['task_id'], operation_id='x7-wrong-candidate',
                    readiness_digest=readiness_digest(readiness),
                )
        with self.subTest(scenario='X7', fault='unattested_host_executor_g3'), fixture(
                HostConcurrencyTests()) as case:
            case.prepare_learning()
            reviews_before = len(case.fixture.calls)
            applied = case.host.apply_pending('host-t5')
            self.assertTrue(applied['applied'], applied)
            self.assertEqual(applied['state']['credential_reuse'], 'disabled')
            self.assertEqual(len(case.fixture.calls), reviews_before + 1)
            self.assertTrue(case.host.runtime.store.read(
                'SELECT * FROM unattested_review_evidence'))
            credentials = case.host.runtime.store.read('SELECT * FROM review_credentials')
            self.assertEqual(len(credentials), 2)
            self.assertTrue(all(
                json.loads(row['record_json'])['credential_id'].endswith('-host-t5')
                for row in credentials
            ))

    def test_x08_budget_slots_and_draining_are_atomic(self):
        scenarios = (
            ('last_thread_budget', 'test_two_threads_competing_for_last_budget_have_one_winner'),
            ('last_process_budget', 'test_two_processes_competing_for_last_budget_have_one_winner'),
            ('last_process_slot', 'test_two_processes_competing_for_last_concurrency_slot_have_one_winner'),
            ('not_started_slot', 'test_not_started_reservation_holds_slot_and_proven_unsent_can_release'),
            ('late_completion', 'test_timeout_is_unknown_conservative_and_late_completion_only_releases'),
            ('repeated_timeout', 'test_repeated_timeouts_cannot_exceed_concurrency_or_fabricate_tokens'),
        )
        for name, method in scenarios:
            with self.subTest(scenario='X8', fault=name), fixture(RuntimeTests()) as case:
                getattr(case, method)()

    def test_x09_recovery_conflict_preserves_user_edits(self):
        with fixture(ExecutorAcceptanceTests()) as case:
            config, _bundle, admission = case.process_config('x9-conflict')
            case.run_managed(config, 'after_write', expected=87)
            case.write('wiki/synthesis/结论.md', '用户后续编辑\n')
            before = case.snapshot()
            conflict = Executor(case.root, case.journal).recover(admission['operation_id'])
            self.assertEqual(conflict['state'], 'recovery_required')
            self.assertEqual(conflict['recovery_status'], 'conflict')
            projected = case.service.reconcile_execution(case.result_binding(admission, conflict))
            self.assertFalse(projected['applied'])
            self.assertFalse(projected['authorization_consumed'])
            self.assertEqual(case.snapshot(), before)
            forged = case.result_binding(admission, {
                'state': 'applied', 'recovery_status': 'not_needed',
            })
            with self.assertRaises(ExecutionReconcileError):
                case.service.reconcile_execution(forged)
            self.assertEqual(case.snapshot(), before)

    def test_x10_ingest_and_approve_authorization_boundaries(self):
        with self.subTest(scenario='X10', fault='ingest_as_g4'), fixture(
                ExecutorAcceptanceTests()) as case:
            case.test_admission_requires_matching_operation_and_ingest_cannot_replace_g4()
        with self.subTest(scenario='X10', fault='learning_approve'), fixture(
                HostConcurrencyTests()) as case:
            case.prepare_learning()
            with self.assertRaises(HostError):
                case.host.approve_pending('host-t5')
            self.assertFalse(case.journal_path().exists())
        with self.subTest(scenario='X10', fault='executor_approve_revocation_barrier'), fixture(
                ExecutorAcceptanceTests()) as case:
            case.test_approve_revocation_uses_barrier_and_final_g4_precedes_no_wal()

    def test_x11_history_requires_compensating_operation(self):
        with self.subTest(scenario='X11', fault='accepted_ingest'), fixture(
                ExecutorAcceptanceTests()) as case:
            bundle, authorization, admission = case.prepare('x11-original')
            result = case.executor.apply(bundle, admission=admission)
            original_projection = case.service.reconcile_execution(
                case.result_binding(admission, result))
            journal = case.journal_path(admission['operation_id'])
            original_wal = journal.read_bytes()
            original_result = case.store.read(
                "SELECT * FROM execution_results WHERE operation_id='x11-original'")
            with self.assertRaises(AuthorizationError):
                case.service.revoke_ingest_authorization(authorization['authorization_ref'])
            with self.assertRaises(AuthorizationError):
                case.service.issue_ingest_authorization(
                    task_id=case.task['task_id'], operation_id=admission['operation_id'],
                    readiness_digest=admission['readiness_digest'],
                )
            task = copy.deepcopy(case.task)
            run = copy.deepcopy(case.run)
            ownership = copy.deepcopy(case.ownership)
            learning = copy.deepcopy(case.learning)
            task.update(task_id='x11-compensation-task', state='running')
            run.update(run_id='x11-compensation-run', task_id=task['task_id'],
                       state='running', execution_history=[])
            ownership.update(task_id=task['task_id'], owner='x11-compensation-owner')
            learning.update(task_id=task['task_id'], state='awaiting_confirmation')
            case.service.create_task(
                policy=case.policy, task=task, run=run, ownership=ownership,
                learning_state=learning,
            )
            case.task, case.run, case.ownership, case.learning = task, run, ownership, learning
            correction_raw = 'raw/unprocessed/修正.md'
            correction_source = 'wiki/sources/修正来源.md'
            case.write(correction_raw,
                       '---\nprocessing_status: unprocessed\n---\n新证据限定原结论仅适用于样本 A。\n')
            values = {
                correction_raw: '---\nprocessing_status: pending_review\n'
                                'processed_into: "[[sources/修正来源]]"\n---\n'
                                '新证据限定原结论仅适用于样本 A。\n',
                correction_source: '---\ntype: source\nstatus: active\ntopic: 测试\n'
                                   'updated: 2026-10-27\nraw_note: "[[raw/unprocessed/修正]]"\n'
                                   'related_synthesis: ["[[synthesis/结论]]"]\n---\n# 修正来源\n'
                                   + '新证据及其适用条件。' * 30 + '\n参见 [[synthesis/结论]]\n',
                'wiki/synthesis/结论.md': (case.root / 'wiki/synthesis/结论.md').read_text(
                    encoding='utf-8').replace(
                        'related_sources: ["[[sources/来源]]"]',
                        'related_sources: ["[[sources/来源]]", "[[sources/修正来源]]"]',
                    ) + '\n补偿修正：原结论仅适用于样本 A，见 [[sources/修正来源]]。\n',
                'wiki/index.md': (case.root / 'wiki/index.md').read_text(
                    encoding='utf-8') + '[[sources/修正来源]]\n',
                'wiki/log.md': (case.root / 'wiki/log.md').read_text(
                    encoding='utf-8') + '## [2026-10-27] ingest | 补偿修正\n[[sources/修正来源]]\n',
                'wiki/meta/overview.md': (case.root / 'wiki/meta/overview.md').read_text(
                    encoding='utf-8') + '[[sources/修正来源]]\n',
                'raw/index.md': '# 素材\n- 未处理：0\n- 待确认：2\n- 已处理：0\n'
                                '| 素材 | 状态 |\n'
                                '| [[raw/unprocessed/原文]] | pending_review | [[sources/来源]] |\n'
                                '| [[raw/unprocessed/修正]] | pending_review | [[sources/修正来源]] |\n',
            }
            before_compensation = case.snapshot()
            new_bundle, new_authorization, new_admission = case.prepare(
                'x11-compensation', values=values, input_refs=[correction_raw],
            )
            self.assertNotEqual(new_admission['operation_id'], admission['operation_id'])
            self.assertNotEqual(new_authorization['authorization_ref'], authorization['authorization_ref'])
            self.assertEqual(journal.read_bytes(), original_wal)
            self.assertEqual(case.snapshot(), before_compensation)
            compensated = case.executor.apply(new_bundle, admission=new_admission)
            self.assertEqual(compensated['state'], 'applied')
            new_projection = case.service.reconcile_execution(
                case.result_binding(new_admission, compensated))
            self.assertTrue(new_projection['applied'])
            self.assertTrue(original_projection['applied'])
            self.assertIn('补偿修正', (case.root / 'wiki/synthesis/结论.md').read_text(
                encoding='utf-8'))
            self.assertEqual(journal.read_bytes(), original_wal)
            self.assertEqual(case.store.read(
                "SELECT * FROM execution_results WHERE operation_id='x11-original'"), original_result)
            self.assertEqual(json.loads(case.journal_path('x11-compensation').read_bytes())[
                'manifest']['operation_id'], 'x11-compensation')
        with self.subTest(scenario='X11', fault='archive_correction'), fixture(
                recovery_fixtures.ExecutorTests()) as case:
            approved = []
            original_secret, correction_secret = object(), object()
            def check_approval(context, approval):
                operation_id = context['manifest']['operation_id']
                approved.append((operation_id, approval))
                expected = (original_secret if operation_id == 'x11-archive' else
                            correction_secret if operation_id == 'x11-archive-correction' else None)
                return approval is expected
            executor = case.executor(approval_check=check_approval)
            archive_bundle = case.approve_bundle('x11-archive')
            original = executor.apply(archive_bundle, approval=original_secret)
            self.assertEqual(original['state'], 'applied')
            journal = case.journal / (digest('x11-archive') + '.json')
            original_wal = journal.read_bytes()
            archived_files = case.snapshot()
            original_approval_checks = len(approved)
            self.assertGreater(original_approval_checks, 0)
            self.assertEqual(executor.apply(archive_bundle, approval=object()), original)
            self.assertEqual(case.snapshot(), archived_files)
            self.assertEqual(len(approved), original_approval_checks)
            correction = case.bundle(
                {'AGENTS.md': (case.root / 'AGENTS.md').read_bytes() + b'# compensation\n'},
                operation='rule_maintenance', operation_id='x11-archive-correction',
            )
            correction['manifest']['input_refs'] = ['raw/processed/原文.md']
            with self.assertRaisesRegex(ExecutionError, 'G4'):
                executor.apply(correction, approval=original_secret)
            self.assertEqual(case.snapshot(), archived_files)
            self.assertFalse((case.journal / (digest('x11-archive-correction') + '.json')).exists())
            corrected = executor.apply(correction, approval=correction_secret)
            self.assertEqual(corrected['state'], 'applied')
            self.assertGreater(len(approved), original_approval_checks)
            self.assertEqual(journal.read_bytes(), original_wal)

    def test_x12_host_driver_cannot_self_grant(self):
        with self.subTest(scenario='X12', fault='legacy_counter_reset'), fixture(
                RegistryAndDriverTests()) as case:
            case.test_state_projection_cannot_reset_candidate_repairs_or_deadline()
        with self.subTest(scenario='X12', fault='self_reported_approval'), fixture(
                RuntimeTests()) as case:
            output = case.port.invoke(case.spec, lambda: {
                'approved': True, 'review_state': 'pass', 'model_calls': 0,
            }, 1.0)
            self.assertTrue(output['approved'])
            from tools.wiki_runtime.runtime import RuntimeService
            RuntimeService(case.store)
            self.assertEqual(case.store.read('SELECT * FROM authorizations'), [])
            self.assertEqual(case.store.read('SELECT * FROM review_credentials'), [])
            account = json.loads(case.store.read('SELECT actual_json FROM task_finance')[0]['actual_json'])
            self.assertEqual(account['model_calls'], 1)
        with self.subTest(scenario='X12', fault='host_credential_injection'), fixture(
                HostConcurrencyTests()) as case:
            case.prepare_learning()
            tables = ('authorizations', 'review_credentials', 'readiness_records', 'task_finance')
            before = {
                table: case.host.runtime.store.read(f'SELECT * FROM {table}')
                for table in tables
            }
            for method in ('save_learning_readiness', 'save_learning_review_credential'):
                with self.assertRaises(AttributeError):
                    getattr(case.host, method)({})
            for table, expected in before.items():
                self.assertEqual(case.host.runtime.store.read(f'SELECT * FROM {table}'), expected)

    @staticmethod
    def _forbidden_dynamic(*_args, **_kwargs):
        raise AssertionError('终态重放不得触发审查、预算或动态准入')


class LoopScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(SCENARIOS.read_text(encoding='utf-8'))['groups']['L']['scenarios']
        cls.by_id = {scenario['id']: scenario for scenario in cls.matrix}
        if set(cls.by_id) != {f'L{index}' for index in range(1, 10)}:
            raise AssertionError('L 组场景清单必须完整且唯一')
        for scenario in cls.matrix:
            if not callable(getattr(cls, scenario['test'], None)):
                raise AssertionError('场景未绑定真实测试: ' + scenario['id'])

    class ResponseLost(RuntimeError):
        pass

    class NotCommitted(RuntimeError):
        pass

    @staticmethod
    def _restart(case):
        from tools.wiki_runtime.runtime import RuntimeService, RuntimeStore
        case.store.close()
        case.store = RuntimeStore(case.root, busy_timeout=0.15)
        case.service = RuntimeService(case.store, executor=case.executor, clock=lambda: 100.0)
        return case.service

    @contextmanager
    def _after_commit(self, store):
        original = store.mutate
        def committed_then_lost(fn):
            original(fn)
            raise self.ResponseLost('事务已提交，仅响应丢失')
        store.mutate = committed_then_lost
        try:
            yield
        finally:
            store.mutate = original

    @contextmanager
    def _before_commit(self, store):
        original = store.mutate
        def not_committed(_fn):
            raise self.NotCommitted('外部规划已返回，提交前中断')
        store.mutate = not_committed
        try:
            yield
        finally:
            store.mutate = original

    @staticmethod
    def _records(case, table):
        return [json.loads(row['record_json']) for row in case.store.read(
            f'SELECT record_json FROM {table}')]

    @staticmethod
    def _finance(case):
        return {
            table: case.store.read(f'SELECT * FROM {table}')
            for table in ('task_finance', 'run_finance')
        }

    @staticmethod
    def _answer(wait, answer_id='answer-1', revision=1, knowledge_version=1):
        return {
            'answer_id': answer_id, 'wait_id': wait['wait_id'],
            'answer_revision': revision, 'answer_digest': digest(answer_id),
            'answer_ref': None, 'knowledge_version': knowledge_version,
            'question_version': wait['question_version'],
            'rubric_version': wait['rubric_version'],
        }

    def _make_wait(self, case):
        case.plan_one()
        claim = case.service.claim_step('owner', now=100.0)
        wait = copy.deepcopy(case.loop_records['wait'])
        case.service.submit_step_result(
            case.make_result(claim, waits=[wait]),
            work_item_id=claim['work_item']['work_item_id'], claimed_by='owner',
            proposal=__import__('tools.wiki_runtime.runtime', fromlist=['empty_proposal']).empty_proposal(
                case.task['revision'], waits=[wait],
            ), now=100.5,
        )
        return wait

    def test_l01_event_commit_replay_and_conflict(self):
        from tools.wiki_runtime.runtime import LoopConflictError
        with fixture(RuntimeLoopTests()) as case:
            event = copy.deepcopy(case.loop_records['event'])
            with self._after_commit(case.store):
                with self.assertRaises(self.ResponseLost):
                    case.service.accept_event(event)
            service = self._restart(case)
            replayed = dict(event, receipt_sequence=99)
            self.assertEqual(service.accept_event(replayed)['receipt_sequence'], 1)
            step, item = case.step_and_work()
            service.plan_pending(lambda frozen: __import__(
                'tools.wiki_runtime.runtime', fromlist=['empty_proposal']
            ).empty_proposal(frozen['task']['revision'], steps=[step], work_items=[item]))
            confirmed = service.accept_event(replayed)
            self.assertEqual(confirmed['processing_state'], 'processed')
            self.assertEqual(confirmed['receipt_sequence'], 1)
            changed = dict(event, type='authorization_submitted')
            with self.assertRaises(LoopConflictError):
                service.accept_event(changed)
            self.assertEqual(len(case.store.read('SELECT * FROM events')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM steps')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 1)

    def test_l02_crash_windows_resume_durable_work(self):
        from tools.wiki_runtime.runtime import empty_proposal
        with fixture(RuntimeLoopTests()) as case:
            event = copy.deepcopy(case.loop_records['event'])
            case.service.accept_event(event)
            service = self._restart(case)
            step, item = case.step_and_work()
            planner_calls = []
            def planner(frozen):
                planner_calls.append(frozen['event']['event_id'])
                return empty_proposal(frozen['task']['revision'], steps=[step], work_items=[item])
            with self._before_commit(case.store):
                with self.assertRaises(self.NotCommitted):
                    service.plan_pending(planner)
            self.assertEqual(planner_calls, ['event-1'])
            self.assertEqual(case.store.read('SELECT * FROM work_items'), [])
            service = self._restart(case)
            with self._after_commit(case.store):
                with self.assertRaises(self.ResponseLost):
                    service.plan_pending(planner)
            service = self._restart(case)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 1)
            self.assertEqual(self._records(case, 'events')[0]['processing_state'], 'processed')
            claim = service.claim_step('owner', now=100.0)
            next_step, next_work = case.step_and_work('step-after-crash')
            result = case.make_result(claim, follow_ups=[next_work], follow_up_steps=[next_step])
            with self._after_commit(case.store):
                with self.assertRaises(self.ResponseLost):
                    service.submit_step_result(
                        result, work_item_id=claim['work_item']['work_item_id'],
                        claimed_by='owner', proposal=empty_proposal(
                            case.task['revision'], steps=[next_step], work_items=[next_work],
                        ), now=100.5,
                    )
            service = self._restart(case)
            self.assertEqual(service.submit_step_result(
                result, work_item_id=claim['work_item']['work_item_id'],
                claimed_by='owner', now=100.5,
            ), result)
            self.assertEqual(len(case.store.read('SELECT * FROM step_results')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 2)
            self.assertEqual(self._records(case, 'steps')[0]['state'], 'completed')
        with self.subTest(scenario='L2', fault='stale_frozen_snapshot'), fixture(
                RuntimeLoopTests()) as case:
            from tools.wiki_runtime.runtime import LoopConflictError
            for event_id in ('l2-event-v2', 'l2-event-stale'):
                event = copy.deepcopy(case.loop_records['event'])
                event['event_id'] = event_id
                case.service.accept_event(event)
            def planner(frozen):
                version = 2 if frozen['event']['event_id'] == 'l2-event-v2' else 1
                return empty_proposal(
                    frozen['task']['revision'],
                    learning_state=dict(frozen['learning_state'], knowledge_version=version),
                )
            with self.assertRaises(LoopConflictError):
                case.service.plan_pending(planner)
            self.assertEqual(self._records(case, 'learning_states')[0]['knowledge_version'], 2)
            events = {record['event_id']: record for record in self._records(case, 'events')}
            self.assertEqual(events['l2-event-v2']['processing_state'], 'processed')
            self.assertEqual(events['l2-event-stale']['processing_state'], 'pending')
            service = self._restart(case)
            service.plan_pending(lambda frozen: empty_proposal(
                frozen['task']['revision'], learning_state=frozen['learning_state'],
            ))
            self.assertEqual(self._records(case, 'learning_states')[0]['knowledge_version'], 2)
            self.assertTrue(all(record['processing_state'] == 'processed'
                                for record in self._records(case, 'events')))

    def test_l03_claim_takeover_and_original_invocation(self):
        import subprocess
        import sys
        from tools.wiki_runtime.runtime import LoopConflictError
        from tools.tests.test_learning_s1_runtime import PROCESS_FIXTURE
        with fixture(RuntimeLoopTests()) as case:
            _event, step, _item = case.plan_one()
            spec = copy.deepcopy(case.records['invocation_spec'])
            spec['invocation_id'] = 'l3-original-invocation'
            spec['input_digest'] = step['input_digest']
            gate = Path(case.temporary.name) / 'l3-claim-gate'
            processes = []
            for index in range(2):
                config = Path(case.temporary.name) / f'l3-claim-{index}.json'
                config.write_text(json.dumps({
                    'root': str(case.root), 'gate': str(gate), 'owner': f'l3-process-{index}',
                    'now': 100.0, 'lease_seconds': 1.0,
                    'invocation_id': spec['invocation_id'],
                }), encoding='utf-8')
                processes.append(subprocess.Popen([
                    sys.executable, '-B', str(PROCESS_FIXTURE), 'claim', str(config),
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            gate.write_text('go', encoding='utf-8')
            outputs = [process.communicate(timeout=20) for process in processes]
            self.assertCountEqual([process.returncode for process in processes], [0, 36], outputs)
            original = json.loads(next(
                stdout for process, (stdout, _stderr) in zip(processes, outputs)
                if process.returncode == 0
            ))
            original_result = case.make_result(original)
            transport_result = {
                'output': 'original-success', 'step_result_digest': original_result['result_digest'],
            }
            calls = []
            case.service.port.invoke(
                spec, lambda: calls.append('transport') or transport_result, 1.0,
            )
            taken = case.service.claim_step('new-owner', now=102.0, lease_seconds=10.0)
            self.assertTrue(taken['takeover'])
            with self.assertRaises(LoopConflictError):
                case.service.submit_step_result(
                    original_result, work_item_id=original['work_item']['work_item_id'],
                    claimed_by=original['work_item']['claimed_by'], now=102.5,
                    invocation_id=spec['invocation_id'],
                )
            self.assertEqual(case.service.port.replay(spec), transport_result)
            current = case.make_result(taken)
            case.service.submit_step_result(
                current, work_item_id=taken['work_item']['work_item_id'],
                claimed_by='new-owner', now=103.0, invocation_id=spec['invocation_id'],
            )
            self.assertEqual(calls, ['transport'])
            self.assertEqual(len(case.store.read('SELECT * FROM invocations')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM step_invocations')), 2)
            account = json.loads(case.store.read(
                'SELECT actual_json FROM task_finance')[0]['actual_json'])
            self.assertEqual(account['model_calls'], 1)
        with self.subTest(scenario='L3', fault='unknown_never_resends'), fixture(
                RuntimeLoopTests()) as case:
            import time
            _event, step, _item = case.plan_one()
            spec = copy.deepcopy(case.records['invocation_spec'])
            spec['invocation_id'] = 'l3-unknown-invocation'
            spec['input_digest'] = step['input_digest']
            case.service.claim_step(
                'old-owner', now=100.0, lease_seconds=1.0,
                invocation_id=spec['invocation_id'],
            )
            calls = []
            unknown = case.service.port.invoke(
                spec, lambda: calls.append('only-call') or time.sleep(0.05) or {'output': 'late'},
                0.001,
            )
            self.assertEqual(unknown['state'], 'unknown')
            with self.assertRaises(LoopConflictError):
                case.service.claim_step('new-owner', now=102.0, lease_seconds=10.0)
            blocked = self._records(case, 'steps')[0]
            self.assertEqual(blocked['generation'], 1)
            self.assertEqual(blocked['state'], 'blocked')
            self.assertIsNone(case.service.claim_step('third-owner', now=104.0))
            self.assertEqual(case.service.port.replay(spec)['state'], 'unknown')
            self.assertEqual(calls, ['only-call'])
            self.assertEqual(case.store.read('SELECT * FROM step_results'), [])
            self.assertEqual(len(case.store.read('SELECT * FROM invocations')), 1)

    def test_l04_answer_race_revision_and_readiness(self):
        import threading
        from tools.wiki_runtime.runtime import LoopConflictError, empty_proposal
        with fixture(RuntimeLoopTests()) as case:
            for credential in case.records['review_credentials']:
                case.service.save_review_credential(credential)
            case.service.save_readiness(copy.deepcopy(case.records['readiness']))
            readiness_before = case.store.read('SELECT * FROM readiness_records')
            wait = self._make_wait(case)
            first_step, first_work = case.step_and_work('step-assessment')
            answer = self._answer(wait)
            barrier = threading.Barrier(2)
            outcomes, errors = [], []
            def respond():
                try:
                    barrier.wait(3)
                    outcomes.append(case.service.answer_wait(answer, proposal=empty_proposal(
                        case.task['revision'], steps=[first_step], work_items=[first_work],
                    )))
                except Exception as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=respond) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(len([item for item in outcomes if item['replayed']]), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM wait_answers')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 2)

            version_event = copy.deepcopy(case.loop_records['event'])
            version_event['event_id'] = 'l4-knowledge-invalidated'
            case.service.accept_event(version_event)
            changed_learning = dict(case.learning, knowledge_version=2)
            race_answer = self._answer(wait, 'answer-race', 2)
            race_step, race_work = case.step_and_work('step-race-assessment')
            barrier = threading.Barrier(2)
            def invalidate():
                try:
                    barrier.wait(3)
                    case.service.plan_pending(lambda frozen: empty_proposal(
                        frozen['task']['revision'], learning_state=changed_learning,
                    ))
                except Exception as exc:
                    errors.append(exc)
            def old_answer():
                try:
                    barrier.wait(3)
                    revision = self._records(case, 'tasks')[0]['revision']
                    outcomes.append(case.service.answer_wait(race_answer, proposal=empty_proposal(
                        revision, steps=[race_step], work_items=[race_work],
                    )))
                except LoopConflictError:
                    outcomes.append({'answer': {'answer_id': 'answer-race'}, 'state': 'conflict'})
                except Exception as exc:
                    errors.append(exc)
            threads = [threading.Thread(target=invalidate), threading.Thread(target=old_answer)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            accepted_race = [item for item in outcomes if item.get('answer', {}).get(
                'answer_id') == 'answer-race']
            self.assertEqual(len(accepted_race), 1)
            expected_work = 3 if accepted_race[0]['state'] == 'accepted' else 2
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), expected_work)
            stale = self._answer(wait, 'answer-after-invalidation', 3)
            self.assertEqual(case.service.answer_wait(stale)['state'], 'superseded')
            self.assertEqual(case.store.read('SELECT * FROM readiness_records'), readiness_before)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), expected_work)
        with self.subTest(scenario='L4', fault='ordered_revision'), fixture(
                RuntimeLoopTests()) as case:
            wait = self._make_wait(case)
            for revision in (1, 2):
                step, work = case.step_and_work(f'step-assessment-{revision}')
                answer = self._answer(wait, f'answer-revision-{revision}', revision)
                self.assertEqual(case.service.answer_wait(answer, proposal=empty_proposal(
                    case.task['revision'], steps=[step], work_items=[work],
                ))['state'], 'accepted')
            revised = self._answer(wait, 'answer-revision-2', 2)
            self.assertTrue(case.service.answer_wait(revised)['replayed'])
            self.assertEqual(len(case.store.read('SELECT * FROM wait_answers')), 2)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 3)

    def test_l05_result_domain_and_followups_are_atomic(self):
        from tools.wiki_runtime.runtime import LoopConflictError, empty_proposal
        with fixture(RuntimeLoopTests()) as case:
            _event, step, _item = case.plan_one()
            spec = copy.deepcopy(case.records['invocation_spec'])
            spec['input_digest'] = step['input_digest']
            case.service.port.invoke(spec, lambda: {'output': 'artifact-producer'}, 1.0)
            artifact = case.store.artifact_root / 'l5-result.json'
            artifact.write_bytes(b'{"synthetic":true}')
            artifact_digest = case.store.publish_artifact(spec['invocation_id'], 'l5-result.json')
            claim = case.service.claim_step('owner', now=100.0)
            changed_learning = dict(case.learning, knowledge_version=2)
            next_step, next_work = case.step_and_work('step-l5-follow-up')
            result = case.make_result(
                claim, learning_state=changed_learning, follow_ups=[next_work], follow_up_steps=[next_step],
            )
            result['artifact_digests'] = [artifact_digest]
            result['result_digest'] = digest({field: result[field] for field in (
                'artifact_digests', 'domain_change_digest', 'wait_request_digest',
                'follow_up_digests', 'failure',
            )})
            with self._after_commit(case.store):
                with self.assertRaises(self.ResponseLost):
                    case.service.submit_step_result(
                        result, work_item_id=claim['work_item']['work_item_id'],
                        claimed_by='owner', proposal=empty_proposal(
                            case.task['revision'], learning_state=changed_learning,
                            steps=[next_step], work_items=[next_work],
                        ), now=100.5,
                    )
            service = self._restart(case)
            self.assertEqual(service.submit_step_result(
                result, work_item_id=claim['work_item']['work_item_id'],
                claimed_by='owner', now=100.5,
            ), result)
            self.assertEqual(self._records(case, 'learning_states')[0]['knowledge_version'], 2)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 2)
            self.assertEqual(len(case.store.read('SELECT * FROM step_results')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM artifacts')), 1)
            changed = copy.deepcopy(result)
            changed['artifact_digests'] = []
            changed['result_digest'] = digest({field: changed[field] for field in (
                'artifact_digests', 'domain_change_digest', 'wait_request_digest',
                'follow_up_digests', 'failure',
            )})
            with self.assertRaises(LoopConflictError):
                service.submit_step_result(
                    changed, work_item_id=claim['work_item']['work_item_id'],
                    claimed_by='owner', now=100.5,
                )
            self.assertEqual(len(case.store.read('SELECT * FROM step_results')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 2)

    def test_l06_capability_and_knowledge_version_invalidation(self):
        from tools.wiki_runtime.runtime import AuthorizationError, LoopConflictError
        from tools.wiki_runtime.runtime.registry import CapabilityRegistry, CapabilityError
        with fixture(RuntimeLoopTests()) as case:
            event = copy.deepcopy(case.loop_records['event'])
            case.service.accept_event(event)
            step, item = case.step_and_work()
            dependency = __import__(
                'tools.wiki_runtime.runtime.loop_protocol', fromlist=['learning_state_digest']
            ).learning_state_digest(case.learning)
            step['dependency_digests'] = [dependency]
            case.service.plan_pending(lambda frozen: __import__(
                'tools.wiki_runtime.runtime', fromlist=['empty_proposal']
            ).empty_proposal(frozen['task']['revision'], steps=[step], work_items=[item]))
            claim = case.service.claim_step('owner', now=100.0)
            case.service.loop.invalidate_dependency(dependency, reason='L6 依赖失效')
            with self.assertRaises(LoopConflictError):
                case.service.submit_step_result(
                    case.make_result(claim), work_item_id=claim['work_item']['work_item_id'],
                    claimed_by='owner', now=100.5,
                )
            manifest = copy.deepcopy(case.loop_records['capability_manifest'])
            registry = CapabilityRegistry([manifest])
            workflow = copy.deepcopy(case.task['workflow_ref'])
            workflow['required_checks'].append('independent_review')
            valid_step, _work = case.step_and_work('capability-step')
            self.assertEqual(registry.validate_step(valid_step, workflow)['capability_id'],
                             'synthetic.review')
            with self.assertRaises(CapabilityError):
                CapabilityRegistry().validate_step(valid_step, workflow)
            missing_checks = copy.deepcopy(workflow)
            missing_checks['required_checks'].remove('independent_review')
            with self.assertRaises(CapabilityError):
                CapabilityRegistry([manifest]).validate_step(valid_step, missing_checks)
            registry.revoke('synthetic.review')
            with self.assertRaises(CapabilityError):
                registry.validate_step(valid_step, workflow)
            changed_step = dict(valid_step, implementation_digest='0' * 64)
            with self.assertRaises(CapabilityError):
                CapabilityRegistry([manifest]).validate_step(changed_step, workflow)

            for credential in case.records['review_credentials']:
                case.service.save_review_credential(credential)
            case.service.save_readiness(copy.deepcopy(case.records['readiness']))
            migrated = copy.deepcopy(case.records['readiness'])
            migrated['dependencies_digest'] = digest('l6-knowledge-version-2')
            case.service.save_readiness(migrated)
            pre_change_auth = case.service.issue_ingest_authorization(
                task_id=case.task['task_id'], operation_id='l6-pre-change-admission',
                readiness_digest=readiness_digest(case.records['readiness']),
            )
            version_event = copy.deepcopy(case.loop_records['event'])
            version_event['event_id'] = 'l6-knowledge-version-event'
            case.service.accept_event(version_event)
            case.service.plan_pending(lambda frozen: empty_proposal(
                frozen['task']['revision'],
                learning_state=dict(frozen['learning_state'], knowledge_version=2),
            ))
            with self.assertRaises(AuthorizationError):
                case.service.issue_ingest_authorization(
                    task_id=case.task['task_id'], operation_id='l6-old-credential',
                    readiness_digest=readiness_digest(migrated),
                )
            from tools.wiki_runtime.runtime import AdmissionError
            with self.assertRaises(AdmissionError):
                case.service.build_admission(
                    run_id=case.run['run_id'], operation_id='l6-pre-change-admission',
                    manifest_digest=case.records['admission']['manifest_digest'],
                    readiness_digest=readiness_digest(case.records['readiness']),
                    authorization_ref=pre_change_auth['authorization_ref'],
                )
            replacements = {}
            for credential in case.records['review_credentials']:
                replacement = copy.deepcopy(credential)
                replacement['credential_id'] += '-l6-v2'
                replacement['invocation_id'] += '-l6-v2'
                replacement['dependencies_digest'] = migrated['dependencies_digest']
                replacement['scope']['package_ref']['version'] = 2
                case.service.save_review_credential(replacement)
                replacements[credential['role']] = replacement
            for requirement in migrated['required_credentials']:
                replacement = replacements[requirement['role']]
                requirement['credential_ref'] = replacement['credential_id']
                requirement['credential_digest'] = review_credential_digest(replacement)
            case.service.save_readiness(migrated)
            authorized = case.service.issue_ingest_authorization(
                task_id=case.task['task_id'], operation_id='l6-new-credential',
                readiness_digest=readiness_digest(migrated),
            )
            self.assertEqual(authorized['state'], 'issued')
            self.assertNotEqual(readiness_digest(migrated),
                                readiness_digest(case.records['readiness']))

    def test_l07_restart_retry_and_wait_preserve_bounds(self):
        from tools.wiki_runtime.runtime import LoopConflictError, empty_proposal
        with fixture(RuntimeLoopTests()) as case:
            _event, planned_step, _item = case.plan_one()
            spec = copy.deepcopy(case.records['invocation_spec'])
            spec['input_digest'] = planned_step['input_digest']
            case.service.port.invoke(spec, lambda: {'output': 'completed-business'}, 1.0)
            completed = case.service.claim_step('owner', now=100.0)
            case.service.submit_step_result(
                case.make_result(completed), work_item_id=completed['work_item']['work_item_id'],
                claimed_by='owner', now=100.5,
            )
            finance = self._finance(case)
            self.assertEqual(json.loads(finance['task_finance'][0]['actual_json'])['model_calls'], 1)
            service = self._restart(case)
            self.assertIsNone(service.claim_step('owner', now=101.0))
            self.assertEqual(self._finance(case), finance)
            event = copy.deepcopy(case.loop_records['event'])
            event['event_id'] = 'l7-repair-event'
            service.accept_event(event)
            step, item = case.step_and_work('step-format-repair')
            service.plan_pending(lambda frozen: empty_proposal(
                frozen['task']['revision'], steps=[step], work_items=[item],
            ))
            failure = {
                'category': 'content', 'fingerprint': digest('same-format-failure'),
                'reason': '格式修复没有改变失败指纹',
            }
            first = service.claim_step('owner', now=101.0)
            service.submit_step_result(
                case.make_result(first, failure=failure),
                work_item_id=first['work_item']['work_item_id'], claimed_by='owner', now=101.5,
            )
            service.loop.retry_step(first['step']['step_id'], failure['fingerprint'])
            service = self._restart(case)
            second = service.claim_step('owner', now=102.0)
            self.assertEqual(second['step']['attempt'], 2)
            service.submit_step_result(
                case.make_result(second, failure=failure),
                work_item_id=second['work_item']['work_item_id'], claimed_by='owner', now=102.5,
            )
            with self.assertRaises(LoopConflictError):
                service.loop.retry_step(second['step']['step_id'], failure['fingerprint'])
            service = self._restart(case)
            self.assertEqual(self._records(case, 'tasks')[0]['state'], 'blocked')
            self.assertEqual(len(case.store.read('SELECT * FROM step_results')), 3)
            self.assertEqual(len(case.store.read('SELECT * FROM invocations')), 1)
            self.assertEqual(self._finance(case), finance)
        with self.subTest(scenario='L7', fault='waiting_user'), fixture(
                RuntimeLoopTests()) as case:
            wait = self._make_wait(case)
            finance = self._finance(case)
            service = self._restart(case)
            self.assertIsNone(service.claim_step('owner', now=101.0))
            self.assertEqual(self._records(case, 'tasks')[0]['state'], 'waiting')
            self.assertEqual(self._finance(case), finance)
            step, work = case.step_and_work('step-after-wait')
            service.answer_wait(self._answer(wait), proposal=empty_proposal(
                case.task['revision'], steps=[step], work_items=[work],
            ))
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 2)
            self.assertEqual(self._finance(case), finance)

    def test_l08_storage_failures_preserve_authoritative_state(self):
        import sqlite3
        import threading
        import time
        from tools.wiki_runtime.runtime import (
            LoopConflictError, RuntimeStore, RuntimeStoreError, SchemaVersionError,
        )
        with self.subTest(scenario='L8', fault='db_busy_backup_schema'), fixture(
                RuntimeTests()) as case:
            entered, release = threading.Event(), threading.Event()
            def holder():
                def hold(_connection):
                    entered.set()
                    if not release.wait(5):
                        raise TimeoutError('L8 锁屏障超时')
                case.store.mutate(hold)
            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(entered.wait(2))
            before = self._finance(case)
            started = time.monotonic()
            with self.assertRaises(RuntimeStoreError):
                case.port.invoke(case.spec, lambda: {'output': 'must-not-run'}, 1.0)
            self.assertLess(time.monotonic() - started, 2.0)
            release.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(self._finance(case), before)
            self.assertEqual(case.store.read('SELECT * FROM invocations'), [])
            case.port.invoke(case.spec, lambda: {'output': 'after-busy'}, 1.0)
            tracked = case.store.artifact_root / 'tracked.json'
            tracked.write_bytes(b'{"tracked":true}')
            case.store.publish_artifact(case.spec['invocation_id'], 'tracked.json')
            (case.store.artifact_root / 'orphan.json').write_bytes(b'{"orphan":true}')
            backup = case.store.backup(Path(case.temporary.name) / 'l8-backup')
            self.assertEqual(backup['artifacts'], ['tracked.json'])
            self.assertFalse((Path(backup['database']).parent / 'artifacts/orphan.json').exists())
            import shutil
            from tools.wiki_runtime.runtime import RuntimeInvocationPort
            restored_root = Path(case.temporary.name) / 'l8-restored'
            restored_learning = restored_root / '.wiki-runtime' / 'learning'
            restored_learning.mkdir(parents=True)
            shutil.copy2(backup['database'], restored_learning / 'runtime.db')
            shutil.copytree(Path(backup['database']).parent / 'artifacts',
                            restored_learning / 'artifacts')
            restored = RuntimeStore(restored_root)
            try:
                self.assertEqual(RuntimeInvocationPort(restored).replay(case.spec),
                                 {'output': 'after-busy'})
                self.assertEqual((restored.artifact_root / 'tracked.json').read_bytes(),
                                 b'{"tracked":true}')
                actual = json.loads(restored.read(
                    'SELECT actual_json FROM task_finance')[0]['actual_json'])
                self.assertEqual(actual['model_calls'], 1)
            finally:
                restored.close()
            connection = sqlite3.connect(case.store.db_path)
            try:
                connection.execute('PRAGMA user_version=88')
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(SchemaVersionError):
                RuntimeStore(case.root)
            connection = sqlite3.connect(case.store.db_path)
            try:
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 88)
                actual = connection.execute('SELECT actual_json FROM task_finance').fetchone()[0]
                self.assertEqual(json.loads(actual)['model_calls'], 1)
            finally:
                connection.close()
        with self.subTest(scenario='L8', fault='atomic_rollback'), fixture(
                RuntimeLoopTests()) as case:
            _event, step, _item = case.plan_one()
            spec = copy.deepcopy(case.records['invocation_spec'])
            spec['input_digest'] = step['input_digest']
            case.service.port.invoke(spec, lambda: {'output': 'rollback-producer'}, 1.0)
            (case.store.artifact_root / 'rollback.json').write_bytes(b'{}')
            artifact_digest = case.store.publish_artifact(spec['invocation_id'], 'rollback.json')
            claim = case.service.claim_step('owner', now=100.0)
            changed_learning = dict(case.learning, knowledge_version=2)
            unbound_step, unbound_work = case.step_and_work('step-must-rollback')
            result = case.make_result(
                claim, learning_state=changed_learning, follow_ups=[unbound_work],
                follow_up_steps=[unbound_step],
            )
            result['artifact_digests'] = [artifact_digest]
            result['result_digest'] = digest({field: result[field] for field in (
                'artifact_digests', 'domain_change_digest', 'wait_request_digest',
                'follow_up_digests', 'failure',
            )})
            from tools.wiki_runtime.contracts import ContractError
            with self.assertRaises(ContractError):
                case.service.submit_step_result(
                    result, work_item_id=claim['work_item']['work_item_id'],
                    claimed_by='owner', proposal=empty_proposal(
                        case.task['revision'], learning_state=changed_learning,
                        task_state='invalid-terminal', steps=[unbound_step],
                        work_items=[unbound_work],
                    ), now=100.5,
                )
            self.assertEqual(case.store.read('SELECT * FROM step_results'), [])
            self.assertEqual(self._records(case, 'learning_states')[0]['knowledge_version'], 1)
            self.assertEqual(self._records(case, 'work_items')[0]['state'], 'claimed')
            self.assertEqual(len(case.store.read('SELECT * FROM steps')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM work_items')), 1)
            self.assertEqual(len(case.store.read('SELECT * FROM artifacts')), 1)

    def test_l09_controlled_invocation_cannot_self_grant(self):
        from tools.wiki_runtime.runtime import LoopConflictError, RuntimeService
        from tools.wiki_runtime.runtime.identity import (
            AttestationError, invoke_with_optional_attestation, record_review_identity,
        )
        from tools.wiki_runtime.runtime.registry import (
            CapabilityError, RegisteredInvocationPort, default_registry,
        )
        with self.subTest(scenario='L9', fault='capability_and_driver'), fixture(
                RuntimeTests()) as case:
            registry = default_registry()
            workflow = {
                'workflow_id': 'l9-controlled', 'implementation_digest': digest('l9-controlled'),
                'contract_version': 'candidate-1', 'required_checks': ['G3'],
                'allowed_capabilities': ['worker', 'reviewer'],
            }
            port = RegisteredInvocationPort(case.port, registry, workflow)
            def implementation():
                return {'approved': True, 'review_state': 'pass'}
            result = port.invoke(case.spec, implementation, 1.0)
            self.assertTrue(result['approved'])
            invocation = case.port.get_invocation(case.spec['invocation_id'])
            self.assertIsNone(invocation['settlement']['actual_usage']['tokens'])
            self.assertTrue(all(manifest['usage_visibility'] == 'partial'
                                for manifest in registry.manifests()))
            self.assertTrue(all(manifest['cancellation'] == 'best_effort'
                                for manifest in registry.manifests()))
            service = RuntimeService(case.store)
            self.assertEqual(case.store.read('SELECT * FROM authorizations'), [])
            self.assertEqual(case.store.read('SELECT * FROM review_credentials'), [])
            response = invoke_with_optional_attestation(
                lambda _envelope, timeout: {'result': 'recommend_pass'},
                {'system': 'l9', 'input': {}}, timeout=1.0,
            )
            self.assertIsNone(response['attestation'])
            arguments = dict(
                learning_task_id=case.spec['learning_task_id'], operation_id='l9-operation',
                role='Reviewer', content_digest=digest('l9-content'),
                evidence_digest=digest('l9-evidence'), dependencies_digest=digest('l9-dependencies'),
                rules_digest=digest('l9-rules'),
                review_config={'validator_version': 'l9-v1', 'review_prompt_version': 'l9-p1'},
                review_request={'system': 'l9', 'input': {}},
                opinion={'result': 'recommend_pass'},
                package_ref={'package_id': 'l9', 'version': 1, 'digest': digest('l9-package')},
                objective_ids=[], scope_kind='candidate_content_review',
            )
            identity = record_review_identity(
                service, attestation=None, invocation_id='l9-self-report', **arguments,
            )
            self.assertEqual(identity, {'credential_reuse': 'disabled', 'credential': None})
            forged = {
                'request_id': 'forged', 'session_id': 'forged-child', 'role': 'reviewer',
                'independent': True, 'context_digest': digest(arguments['review_request']),
            }
            with self.assertRaises(AttestationError):
                record_review_identity(
                    service, attestation=forged, invocation_id='l9-forged', **arguments,
                )
            self.assertEqual(len(case.store.read('SELECT * FROM unattested_review_evidence')), 1)
            registry.revoke('worker')
            other = case.another_spec('l9-after-revoke')
            with self.assertRaises(CapabilityError):
                port.invoke(other, lambda: {'approved': True}, 1.0)
            self.assertEqual(len(case.store.read('SELECT * FROM invocations')), 1)
            self.assertEqual(case.store.read('SELECT * FROM authorizations'), [])
            self.assertEqual(case.store.read('SELECT * FROM review_credentials'), [])
        with self.subTest(scenario='L9', fault='self_applied_without_wal'), fixture(
                RuntimeLoopTests()) as case:
            event = copy.deepcopy(case.loop_records['event'])
            case.service.accept_event(event)
            applied = dict(case.learning, state='applied')
            with self.assertRaises(LoopConflictError):
                case.service.plan_pending(lambda frozen: empty_proposal(
                    frozen['task']['revision'], learning_state=applied, task_state='completed',
                ))
            self.assertEqual(self._records(case, 'events')[0]['processing_state'], 'pending')
            step, item = case.step_and_work()
            case.service.plan_pending(lambda frozen: empty_proposal(
                frozen['task']['revision'], steps=[step], work_items=[item],
            ))
            claim = case.service.claim_step('owner', now=100.0)
            with self.assertRaises(LoopConflictError):
                case.service.submit_step_result(
                    case.make_result(claim, learning_state=applied),
                    work_item_id=claim['work_item']['work_item_id'], claimed_by='owner',
                    proposal=empty_proposal(
                        case.task['revision'], learning_state=applied, task_state='completed',
                    ), now=100.5,
                )
            self.assertEqual(self._records(case, 'learning_states')[0]['state'],
                             'awaiting_confirmation')
            self.assertEqual(self._records(case, 'tasks')[0]['state'], 'running')
            self.assertEqual(case.store.read('SELECT * FROM step_results'), [])
            self.assertEqual(case.store.read('SELECT * FROM execution_results'), [])
        with self.subTest(scenario='L9', fault='host_controlled_surface'), fixture(
                HostConcurrencyTests()) as case:
            tables = ('authorizations', 'review_credentials', 'readiness_records', 'task_finance')
            before = {table: case.host.runtime.store.read(f'SELECT * FROM {table}')
                      for table in tables}
            for method in ('save_learning_readiness', 'save_learning_review_credential'):
                with self.assertRaises(AttributeError):
                    getattr(case.host, method)({'state': 'current', 'approved': True})
            for table, expected in before.items():
                self.assertEqual(case.host.runtime.store.read(f'SELECT * FROM {table}'), expected)


class CutoverScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(SCENARIOS.read_text(encoding='utf-8'))['groups']['C']['scenarios']
        cls.by_id = {scenario['id']: scenario for scenario in cls.matrix}
        if set(cls.by_id) != {f'C{index}' for index in range(1, 6)}:
            raise AssertionError('C 组场景清单必须完整且唯一')
        for scenario in cls.matrix:
            if not callable(getattr(cls, scenario['test'], None)):
                raise AssertionError('场景未绑定真实测试: ' + scenario['id'])

    def test_c01_legacy_wal_original_root_and_terminal_closure(self):
        for state_name in ('prepared', 'applying', 'applied', 'recovered'):
            with self.subTest(scenario='C1', wal_state=state_name), fixture(
                    ExecutorCompatibilityTests()) as case:
                root, state, bundle = case.operation('c1-' + state_name)
                operation = 'c1-' + state_name
                if state_name == 'prepared':
                    case.process('apply', root, state, operation, 'after_prepare', expected=87)
                elif state_name in ('applying', 'recovered'):
                    case.process('apply', root, state, operation, 'after_applying', expected=87)
                else:
                    case.process('apply', root, state, operation)
                journal = state / 'private/journals' / (digest(operation) + '.json')
                self.assertTrue(journal.exists())
                executor = Executor(root, state / 'private/journals')
                if state_name in ('prepared', 'applying'):
                    with self.assertRaisesRegex(ExecutionError, '必须先 recover'):
                        executor.lookup_terminal(bundle)
                if state_name != 'applied':
                    recovered = case.process('recover', root, state, operation)
                    self.assertEqual(recovered['state'], 'recovered')
                terminal = executor.lookup_terminal(bundle)
                expected = 'applied' if state_name == 'applied' else 'recovered'
                self.assertEqual(terminal['state'], expected)
                wal_before = journal.read_bytes()
                for payload in Path(bundle['payload_root']).iterdir():
                    payload.unlink()
                def forbidden(*_args, **_kwargs):
                    raise AssertionError('旧终态不得触发预算、审查或动态检查')
                replay = Executor(
                    root, state / 'private/journals', reviewer=forbidden,
                    reserve_call=forbidden, remaining_timeout=forbidden,
                    deterministic_check=forbidden,
                )
                self.assertEqual(replay.apply(bundle), terminal)
                self.assertEqual(replay.recover(operation), terminal)
                self.assertEqual(journal.read_bytes(), wal_before)
                self.assertFalse((root / '.wiki-runtime/executor-active.json').exists())

    def test_c02_pending_dispositions_without_history_or_budget_fabrication(self):
        from tools.wiki_runtime.host.derived import check_derivation
        from tools.wiki_runtime.host.supervisor import StandaloneHost
        from tools.wiki_runtime.runtime.migration import (
            freeze_legacy_entries, inspect_cutover, supersede_pending,
        )
        with fixture(CutoverTests()) as case:
            for operation in ('c2-terminal', 'c2-recovery', 'c2-superseded'):
                case.process('make-pending', operation)
            pending_root = case.state / 'private/pending'
            pending_before = {path: path.read_bytes() for path in pending_root.glob('*.json')}
            history_before = {
                path.relative_to(case.state): path.read_bytes()
                for path in (case.state / 'operations').rglob('*') if path.is_file()
            }
            host = StandaloneHost(case.root, case.state, offline=True)
            self.addCleanup(host.close)
            executor = Executor(
                case.root, case.state / 'private/journals', deterministic_check=check_derivation,
            )
            self.assertEqual(executor.apply(
                host.load_pending('c2-terminal')['bundle'])['state'], 'applied')
            def stop_after_prepare(event, _index):
                if event == 'after_prepare':
                    raise RuntimeError('C2 保留 accepted WAL')
            recovery_bundle = host.load_pending('c2-recovery')['bundle']
            self.assertEqual(Executor(
                case.root, case.state / 'private/journals', deterministic_check=check_derivation,
                fault=stop_after_prepare,
            ).apply(recovery_bundle)['state'], 'prepared')
            freeze_legacy_entries(case.root, case.state)
            initial = inspect_cutover(case.state)
            classifications = {item['operation_id']: item['classification']
                               for item in initial['inventory']['operations']}
            self.assertEqual(classifications, {
                'c2-terminal': 'terminal', 'c2-recovery': 'accepted_pending_recovery',
                'c2-superseded': 'pre_wal_pending',
            })
            self.assertFalse(initial['report']['ready_for_runtime'])
            receipt = supersede_pending(
                'c2-superseded', 'C2 不继承旧预算语义', root=case.root, state_dir=case.state,
            )
            self.assertEqual(receipt, supersede_pending(
                'c2-superseded', 'C2 不继承旧预算语义', root=case.root, state_dir=case.state,
            ))
            recovered = executor.recover('c2-recovery')
            self.assertEqual(recovered['state'], 'recovered')
            self.assertEqual(executor.apply(recovery_bundle), recovered)
            report = inspect_cutover(case.state)['report']
            self.assertTrue(report['ready_for_runtime'])
            self.assertEqual({path: path.read_bytes() for path in pending_root.glob('*.json')},
                             pending_before)
            history_after = {
                path.relative_to(case.state): path.read_bytes()
                for path in (case.state / 'operations').rglob('*') if path.is_file()
            }
            self.assertEqual(history_after, history_before)
            self.assertFalse((case.state / '.wiki-runtime/learning/runtime.db').exists())

    def test_c03_pause_resume_requires_new_operation_and_admission(self):
        from tools.wiki_runtime.runtime import AdmissionError
        with fixture(ExecutorAcceptanceTests()) as case:
            old_admission = case.interfere_during_review(
                lambda _admission: case.service.pause(case.task['task_id']))
            old_binding = case.store.read('SELECT * FROM operation_admissions')[0]
            self.assertEqual(old_binding['binding_state'], 'superseded_by_pause')
            new_run = copy.deepcopy(case.run)
            new_run['run_id'] = 'c3-run-after-pause'
            new_ownership = copy.deepcopy(case.ownership)
            new_ownership['generation'] += 1
            new_ownership['owner'] = 'c3-owner-after-pause'
            case.service.resume(case.task['task_id'], run=new_run, ownership=new_ownership)
            case.run = new_run
            replacement = case.service.issue_ingest_authorization(
                task_id=case.task['task_id'], operation_id=old_admission['operation_id'],
                readiness_digest=old_admission['readiness_digest'],
            )
            with self.assertRaises(AdmissionError):
                case.service.build_admission(
                    run_id=new_run['run_id'], operation_id=old_admission['operation_id'],
                    manifest_digest=old_admission['manifest_digest'],
                    readiness_digest=old_admission['readiness_digest'],
                    authorization_ref=replacement['authorization_ref'],
                )
            old_bundle = case.bundle(old_admission['operation_id'])
            with self.assertRaises(AdmissionError):
                case.executor.apply(old_bundle, admission=old_admission)
            self.assertFalse(case.journal_path(old_admission['operation_id']).exists())
            new_bundle, _authorization, new_admission = case.prepare('c3-new-operation')
            self.assertNotEqual(new_admission['submission_epoch'], old_admission['submission_epoch'])
            result = case.executor.apply(new_bundle, admission=new_admission)
            self.assertEqual(result['state'], 'applied')
            self.assertTrue(case.service.reconcile_execution(
                case.result_binding(new_admission, result))['applied'])
            self.assertFalse(case.journal_path(old_admission['operation_id']).exists())

    def test_c04_derived_and_python_apis_have_no_direct_write_bypass(self):
        from unittest.mock import patch
        from tools import health, heal, raw_index
        from tools.wiki_runtime.runtime.migration import MigrationError
        with fixture(EntrypointTests()) as case:
            (case.root / 'raw/unprocessed/note.md').write_text(
                '---\nprocessing_status: unprocessed\n---\nC4 合成原文\n', encoding='utf-8',
            )
            code, derived = case.host_cli('raw-index', '--operation-id', 'c4-derived', '--apply')
            self.assertEqual(code, 0, derived)
            self.assertTrue(derived['applied'])
            self.assertEqual(case.rows('SELECT * FROM operation_admissions'), [])
            self.assertEqual(case.rows('SELECT * FROM learning_states'), [])
            self.assertEqual(len(case.rows('SELECT * FROM maintenance_results')), 1)
            patches = patch.multiple(
                health, WIKI_ROOT=case.root / 'wiki', RAW_ROOT=case.root / 'raw',
                META_DIR=case.root / 'wiki/meta', GRAPH_JSON=case.root / 'wiki/meta/graph.json',
                HEALTH_REPORT=case.root / 'wiki/health-report.md',
            )
            patches.start()
            self.addCleanup(patches.stop)
            heal_patch = patch.object(heal, 'WIKI_ROOT', case.root / 'wiki')
            heal_patch.start()
            self.addCleanup(heal_patch.stop)
            before = {path.relative_to(case.root): path.read_bytes()
                      for path in case.root.rglob('*') if path.is_file()}
            writes = (
                lambda: raw_index.refresh_index(apply=True),
                lambda: heal.run_heal(dry_run=False),
                lambda: heal.heal_missing_pages([], dry_run=False),
                lambda: heal.heal_broken_links([], dry_run=False),
                lambda: heal.heal_index_sync([], dry_run=False),
            )
            for write in writes:
                with self.subTest(scenario='C4', direct_write=write), self.assertRaisesRegex(
                        MigrationError, '已封闭'):
                    write()
            self.assertIsInstance(raw_index.refresh_index(apply=False), str)
            self.assertTrue(heal.run_heal(dry_run=True)['dry_run'])
            self.assertEqual(heal.heal_missing_pages([], dry_run=True), [])
            self.assertEqual(heal.heal_broken_links([], dry_run=True), [])
            self.assertIsInstance(heal.heal_index_sync([], dry_run=True), list)
            after = {path.relative_to(case.root): path.read_bytes()
                     for path in case.root.rglob('*') if path.is_file()}
            self.assertEqual(after, before)

    def test_c05_cutover_crashes_and_writer_races_resume_idempotently(self):
        from tools.wiki_runtime.runtime.migration import (
            MigrationError, assert_runtime_creation_allowed, freeze_legacy_entries,
            inspect_cutover, drain_registered_pending, supersede_pending,
        )
        for point in ('after-running', 'after-prepare', 'after-active',
                      'after-applied', 'after-recovered', 'after-completed'):
            with self.subTest(scenario='C5', crash=point), fixture(CutoverTests()) as case:
                case.crash_resume(point, 'c5-' + point)
                self.assertTrue(inspect_cutover(case.state)['report']['ready_for_runtime'])
                assert_runtime_creation_allowed(case.root, case.state, 'c5-new-' + point)
        with self.subTest(scenario='C5', crash='supersede_and_locator'), fixture(
                CutoverTests()) as case:
            case.process('make-pending', 'c5-supersede-crash')
            freeze_legacy_entries(case.root, case.state)
            case.process('supersede-crash', 'c5-supersede-crash', 'C5 分类后崩溃', expected=87)
            self.assertFalse(inspect_cutover(case.state)['report']['ready_for_runtime'])
            first = supersede_pending(
                'c5-supersede-crash', 'C5 分类后崩溃', root=case.root, state_dir=case.state,
            )
            self.assertEqual(first, supersede_pending(
                'c5-supersede-crash', 'C5 分类后崩溃', root=case.root, state_dir=case.state,
            ))
            self.assertTrue(inspect_cutover(case.state)['report']['ready_for_runtime'])
        with self.subTest(scenario='C5', crash='intent_only_resume_and_tamper'), fixture(
                CutoverTests()) as case:
            case.process('make-pending', 'c5-intent-resume')
            case.process('freeze-after-intent', 'c5-intent-resume', expected=85)
            intent_path = case.root / '.wiki-runtime/legacy-cutover.intent.json'
            original_intent = intent_path.read_bytes()
            tampered = json.loads(original_intent)
            tampered['freeze_digest'] = '0' * 64
            intent_path.write_text(json.dumps(tampered), encoding='utf-8')
            with self.assertRaisesRegex(MigrationError, 'intent'):
                freeze_legacy_entries(case.root, case.state)
            intent_path.write_bytes(original_intent)
            freeze_legacy_entries(case.root, case.state)
            self.assertEqual(intent_path.read_bytes(), original_intent)
            self.assertEqual(drain_registered_pending(
                'c5-intent-resume', root=case.root, state_dir=case.state,
            )['status'], 'applied')
        with self.subTest(scenario='C5', crash='intent_only_late_pending'), fixture(
                CutoverTests()) as case:
            case.process('make-pending', 'c5-intent-original')
            case.process('freeze-after-intent', 'c5-intent-original', expected=85)
            intent_path = case.root / '.wiki-runtime/legacy-cutover.intent.json'
            original_intent = intent_path.read_bytes()
            case.process('make-pending', 'c5-intent-late')
            with self.assertRaisesRegex(MigrationError, '重算冻结候选不一致'):
                freeze_legacy_entries(case.root, case.state)
            self.assertEqual(intent_path.read_bytes(), original_intent)
            with self.assertRaisesRegex(MigrationError, '尚未 freeze'):
                drain_registered_pending(
                    'c5-intent-late', root=case.root, state_dir=case.state,
                )
            self.assertFalse((case.state / 'private/journals').exists())
        with self.subTest(scenario='C5', crash='locator_only'), fixture(CutoverTests()) as case:
            case.process('make-pending', 'c5-locator')
            case.process('freeze-after-locator', 'c5-locator', expected=85)
            rejected = case.process('guard', 'c5-locator', expected=1)
            self.assertIn('正在切变', rejected.stderr)
            blocked_target = case.base / 'c5-locator-blocked-write'
            (case.base / 'c5-locator-release').write_text('go', encoding='utf-8')
            case.process(
                'writer', '', case.base / 'c5-locator-ready', case.base / 'c5-locator-release',
                blocked_target, expected=1,
            )
            self.assertFalse(blocked_target.exists())
            self.assertFalse((case.state / 'private/journals').exists())
            freeze = freeze_legacy_entries(case.root, case.state)
            self.assertTrue(inspect_cutover(case.state)['frozen'])
            case.process('drain-crash', 'c5-locator', 'after-completed', expected=86)
            result = drain_registered_pending('c5-locator', root=case.root, state_dir=case.state)
            self.assertEqual(result['status'], 'applied')
            self.assertEqual(freeze['freeze_digest'], json.loads(
                (case.root / '.wiki-runtime/legacy-cutover.json').read_bytes())['freeze_digest'])
        with self.subTest(scenario='C5', crash='checked_and_late_writers'), fixture(
                CutoverTests()) as case:
            import os
            import subprocess
            import sys
            import threading
            import time
            case.process('make-pending', 'c5-writer-race')
            ready, release = case.base / 'c5-ready', case.base / 'c5-release'
            target = case.base / 'c5-first-write'
            writer = subprocess.Popen([
                sys.executable, '-B', str(cutover_case_module.FIXTURE), 'writer',
                str(case.root), str(case.state), '', str(ready), str(release), str(target),
            ], cwd=PROJECT, env=dict(os.environ, PYTHONPATH=str(PROJECT)),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            frozen, errors = [], []
            def freeze():
                try:
                    frozen.append(freeze_legacy_entries(case.root, case.state))
                except Exception as exc:
                    errors.append(exc)
            try:
                deadline = time.monotonic() + 15
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists())
                thread = threading.Thread(target=freeze)
                thread.start()
                time.sleep(0.15)
                self.assertTrue(thread.is_alive())
                release.write_text('continue', encoding='utf-8')
                thread.join(30)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(target.read_text(encoding='utf-8'), 'writer-finished')
            finally:
                if not release.exists():
                    release.write_text('cleanup', encoding='utf-8')
                _stdout, writer_stderr = writer.communicate(timeout=30)
            self.assertEqual(writer.returncode, 0, writer_stderr)
            late_target = case.base / 'c5-late-write'
            late = case.process(
                'writer', '', case.base / 'c5-late-ready', case.base / 'c5-late-release',
                late_target, expected=1,
            )
            self.assertIn('旧写入口已冻结', late.stderr)
            self.assertFalse(late_target.exists())
            drained = drain_registered_pending(
                'c5-writer-race', root=case.root, state_dir=case.state,
            )
            self.assertEqual(drained['status'], 'applied')
            assert_runtime_creation_allowed(case.root, case.state, 'c5-managed-after-race')
            self.assertFalse(late_target.exists())


if __name__ == '__main__':
    unittest.main()
