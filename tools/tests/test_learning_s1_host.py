"""S1 T5：统一学习 Driver、静态能力、真实 Host 撤销与暂停。"""
import copy
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
import unittest

from tools.tests import test_bounded_loop as bounded
from tools.tests import test_content_review as content
from tools.tests import test_executor_recovery as fixtures
from tools.tests.fixtures.learning_s1.workflow import confirm_learning
from tools.wiki_runtime.contracts import ContractError, candidate_digest, digest
from tools.wiki_runtime.host.native import InheritedTransport, NativeResult
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.review import PROMPT, build_request
from tools.wiki_runtime.runtime import CapabilityError, CapabilityRegistry, default_registry
from tools.wiki_runtime.runtime.identity import (
    AttestationError, TrustedAttestation, invoke_with_optional_attestation,
    record_review_identity,
)
from tools.wiki_runtime.runtime.loop_protocol import capability_manifest_digest


PROJECT = Path(__file__).resolve().parents[2]
FIXTURES = PROJECT / 'tools/tests/fixtures'


class RegistryAndDriverTests(unittest.TestCase):
    def test_static_registry_rejects_missing_checks_digest_and_revocation(self):
        registry = default_registry()
        manifest = registry.require('reviewer', required_checks=['G3'])
        self.assertEqual(capability_manifest_digest(manifest), digest(manifest))
        with self.assertRaises(CapabilityError):
            registry.require('reviewer', required_checks=[])
        with self.assertRaises(CapabilityError):
            registry.require('reviewer', implementation_digest='0' * 64,
                             required_checks=['G3'])
        registry.revoke('reviewer')
        with self.assertRaises(CapabilityError):
            registry.require('reviewer', required_checks=['G3'])
        with self.assertRaises(CapabilityError):
            CapabilityRegistry([manifest, dict(manifest, usage_visibility='exact')])

    def test_changed_capability_digest_invalidates_task_after_restart(self):
        case = bounded.BoundedLoopTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        baseline = default_registry()
        coordinator = case.coordinator(registry=baseline)
        self.addCleanup(coordinator.close)
        result = coordinator.run(case.worker, reviewer=case.reviewer)
        self.assertEqual(result.status, 'ready_to_apply', result.reason)
        changed = copy.deepcopy(baseline.manifests())
        next(item for item in changed if item['capability_id'] == 'reviewer')[
            'implementation_digest'
        ] = 'f' * 64
        with self.assertRaises(ContractError):
            case.coordinator(registry=CapabilityRegistry(changed))

    def test_auditor_has_exactly_one_invocation_and_unattested_reuse_disabled(self):
        case = bounded.BoundedLoopTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        worker_calls = []

        def worker(request, *, timeout):
            worker_calls.append(1)
            if len(worker_calls) == 2:
                return case.appeal(request)
            return case.worker(request, timeout=timeout)

        reviews = []

        def reviewer(envelope, *, timeout):
            reviews.append(1)
            return case.reviewer(envelope, timeout=timeout, fail=len(reviews) == 1)

        coordinator = case.coordinator()
        self.addCleanup(coordinator.close)
        result = coordinator.run(worker, reviewer=reviewer, auditor=case.auditor())
        self.assertEqual(result.status, 'ready_to_apply', result.reason)
        self.assertEqual(result.state['calls'], 6)
        self.assertEqual(result.state['audit_attempts'], 1)
        self.assertEqual(result.state['appeals'], 1)
        self.assertEqual(result.state['credential_reuse'], 'disabled')
        records = coordinator.runtime.store.read(
            "SELECT record_json FROM invocations WHERE task_id='"
            + coordinator.runtime_ids['task_id'] + "'"
        )
        specs = [json.loads(row['record_json'])['spec'] for row in records]
        roles = [spec['role'] for spec in specs]
        kinds = [spec['kind'] for spec in specs]
        self.assertEqual(roles.count('RuleAuditor'), 1)
        self.assertEqual(kinds.count('candidate_generation'), 3)
        self.assertEqual(kinds.count('candidate_repair'), 1)
        self.assertEqual(roles.count('Reviewer'), 2)
        self.assertEqual(sum(spec['requested_budget']['model_calls'] for spec in specs), 6)
        evidence = coordinator.runtime.store.read('SELECT * FROM unattested_review_evidence')
        self.assertEqual(len(evidence), 2)
        restarted = case.coordinator()
        self.addCleanup(restarted.close)
        replay = restarted.run(worker, reviewer=reviewer, auditor=case.auditor())
        self.assertEqual(replay.state['calls'], 6)
        self.assertEqual(replay.state['appeals'], 1)

    def test_state_projection_cannot_reset_candidate_repairs_or_deadline(self):
        case = bounded.BoundedLoopTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        coordinator = case.coordinator()
        self.addCleanup(coordinator.close)
        reviewer = lambda envelope, timeout: case.reviewer(
            envelope, timeout=timeout, fail=True,
        )
        result = coordinator.run(case.worker, reviewer=reviewer)
        self.assertEqual(result.state['candidates'], 3)
        state_path = case.run_dir / 'state.json'
        state = json.loads(state_path.read_text(encoding='utf-8'))
        original_deadline = coordinator.ownership['expires_at']
        state.update(state='checking', candidates=0, calls=0, repairs=0,
                     deadline=time.time() + 10000)
        state_path.write_text(json.dumps(state), encoding='utf-8')
        restarted = case.coordinator()
        self.addCleanup(restarted.close)
        calls = []
        def worker(request, *, timeout):
            calls.append(request)
            return case.worker(request, timeout=timeout)
        replay = restarted.run(worker, reviewer=reviewer)
        self.assertEqual(replay.state['candidates'], 3)
        self.assertEqual(replay.state['calls'], 6)
        self.assertEqual(replay.state['repairs'], 3)
        self.assertEqual(replay.state['deadline'], original_deadline)
        self.assertIn('三个候选', replay.reason)
        self.assertEqual(calls, [])

    def test_native_dispatcher_can_supply_bound_attestation(self):
        request = build_request(**content.fixture())
        envelope = {'system': PROMPT, 'input': request, 'reviewer_id': 'review'}

        def dispatcher(native_request, *, timeout):
            output = content.response(dict(
                json.loads(native_request.payload_json), system=native_request.system,
            ))
            attestation = {
                'request_id': native_request.request_id,
                'session_id': 'child-' + native_request.request_id,
                'role': native_request.role,
                'independent': True,
                'context_digest': digest(envelope),
            }
            return NativeResult(
                native_request.request_id, native_request.role,
                attestation['session_id'], output, attestation,
            )

        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        result = transport.invoke_attested(envelope, timeout=2)
        self.assertEqual(result['output']['result'], 'recommend_pass')
        self.assertEqual(result['attestation']['role'], 'reviewer')
        self.assertEqual(result['attestation']['context_digest'], digest(envelope))

    def test_coordinator_saves_attested_review_credential(self):
        case = bounded.BoundedLoopTests()
        case.setUp()
        self.addCleanup(case.doCleanups)

        def dispatcher(native_request, *, timeout):
            envelope = dict(json.loads(native_request.payload_json),
                            system=native_request.system)
            attestation = {
                'request_id': native_request.request_id, 'session_id': 'native-child-1',
                'role': 'reviewer', 'independent': True,
                'context_digest': digest(envelope),
            }
            return NativeResult(
                native_request.request_id, native_request.role, 'native-child-1',
                case.reviewer(envelope, timeout=timeout), attestation,
            )

        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        coordinator = case.coordinator()
        self.addCleanup(coordinator.close)
        result = coordinator.run(case.worker, reviewer=transport)
        self.assertEqual(result.status, 'ready_to_apply', result.reason)
        self.assertEqual(result.state['credential_reuse'], 'bound_only')
        credentials = coordinator.runtime.store.read('SELECT * FROM review_credentials')
        self.assertEqual(len(credentials), 1)
        stored = json.loads(credentials[0]['record_json'])
        self.assertEqual(stored['validator_version'], 'gates-1.0')
        self.assertEqual(stored['identity'], 'native-child-1')

    def test_attestation_records_valid_credential_and_rejects_forgery(self):
        case = bounded.BoundedLoopTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        coordinator = case.coordinator()
        self.addCleanup(coordinator.close)
        envelope = {'system': PROMPT, 'input': build_request(**content.fixture()),
                    'reviewer_id': 'reviewer'}
        def dispatcher(native_request, *, timeout):
            current = dict(json.loads(native_request.payload_json),
                           system=native_request.system)
            attestation = {
                'request_id': native_request.request_id,
                'session_id': 'child-' + native_request.request_id,
                'role': 'reviewer', 'independent': True,
                'context_digest': digest(current),
            }
            return NativeResult(
                native_request.request_id, native_request.role, attestation['session_id'],
                content.response(current), attestation,
            )
        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        attestation = transport.invoke_attested(envelope, timeout=2)['attestation']
        arguments = dict(
            invocation_id='invocation-1', learning_task_id='learning-1',
            operation_id='operation-1', role='Reviewer', content_digest=digest('content'),
            evidence_digest=digest(envelope), dependencies_digest=digest('dependencies'),
            rules_digest=digest('rules'),
            review_config={'validator_version': 'synthetic-v1',
                           'review_prompt_version': 'synthetic-p1'},
            review_request=envelope, opinion={'result': 'recommend_pass'},
            package_ref={'package_id': 'synthetic', 'version': 1,
                         'digest': digest('package')},
            objective_ids=[], scope_kind='candidate_content_review',
        )
        recorded = record_review_identity(
            coordinator.runtime, attestation=attestation, **arguments,
        )
        self.assertEqual(recorded['credential_reuse'], 'bound_only')
        self.assertEqual(recorded['credential']['validator_version'], 'synthetic-v1')
        with self.assertRaises(AttestationError):
            record_review_identity(coordinator.runtime, attestation=attestation, **arguments)
        unregistered = TrustedAttestation(
            dict(attestation), transport=transport, token='unregistered-token',
        )
        with self.assertRaises(AttestationError):
            record_review_identity(coordinator.runtime, attestation=unregistered, **arguments)
        mutated = transport.invoke_attested(envelope, timeout=2)['attestation']
        mutated['context_digest'] = digest('changed-review-input')
        with self.assertRaises(AttestationError):
            record_review_identity(coordinator.runtime, attestation=mutated, **arguments)
        for update in (
            {'request_id': ''}, {'session_id': ''}, {'role': 'worker'},
            {'independent': False}, {'context_digest': '0' * 64},
        ):
            with self.subTest(update=update), self.assertRaises(AttestationError):
                record_review_identity(
                    coordinator.runtime, attestation=dict(attestation, **update), **arguments,
                )

        class NotADispatcher:
            def __call__(self, envelope, *, timeout):
                return {'result': 'recommend_pass'}

            def invoke_attested(self, envelope, *, timeout):
                raise AssertionError('自定义对象不得进入可信 Attestation 通道')

        response = invoke_with_optional_attestation(NotADispatcher(), envelope, timeout=1)
        self.assertIsNone(response['attestation'])


class HostConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.state_dir = self.fixture.base / 'host-t5'
        self.plan = {
            'changes': [
                dict(action='write', path=path,
                     text=(self.root / path).read_text(encoding='utf-8') + '\n')
                for path in (fixtures.PAGE, 'wiki/index.md', 'wiki/log.md')
            ]
        }
        self.host = StandaloneHost(self.root, self.state_dir, transport=self.transport)
        self.addCleanup(self.host.close)
        self.records = json.loads(
            (FIXTURES / 'learning_s0/protocol_records.json').read_text(encoding='utf-8')
        )['valid']

    def transport(self, envelope, *, timeout):
        if envelope['system'].startswith('你是中文知识库的处理者'):
            return copy.deepcopy(self.plan)
        return self.fixture.reviewer(envelope, timeout=timeout)

    def run_legacy(self, operation='approve'):
        allowed = [change['path'] for change in self.plan['changes']]
        allowed += [change['source'] for change in self.plan['changes'] if 'source' in change]
        return self.host.run_operation(
            'host-t5', operation, '保留原始适用条件', allowed, [fixtures.RAW],
            max_calls=12, max_seconds=120, call_timeout=20,
        )

    def mint_approval(self):
        record = self.host.load_pending('host-t5')
        context_digest = digest(record['context'])
        now = time.time()
        self.host.approvals._save(context_digest, {
            'context_digest': context_digest, 'nonce': secrets.token_hex(32),
            'issued_at': now, 'expires_at': now + 120, 'revoked': False,
        })

    def blocking_reviewer(self, entered, release):
        def review(envelope, *, timeout):
            entered.set()
            if not release.wait(20):
                raise TimeoutError('测试未释放 G3')
            return self.fixture.reviewer(envelope, timeout=timeout)
        return review

    def journal_path(self, operation_id='host-t5'):
        return self.state_dir / 'private/journals' / (digest(operation_id) + '.json')

    def test_same_host_revoke_completes_during_g3_and_prevents_wal(self):
        self.plan = {
            'changes': [
                dict(action='write', path=path,
                     text=(self.root / path).read_text(encoding='utf-8') + '\n')
                for path in (fixtures.PAGE, 'wiki/index.md', 'wiki/log.md')
            ]
        }
        self.assertEqual(self.run_legacy()['status'], 'ready_to_apply')
        self.mint_approval()
        entered, release = threading.Event(), threading.Event()
        self.host.transport = self.blocking_reviewer(entered, release)
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(self.host.apply_pending('host-t5')))
        thread.start()
        self.assertTrue(entered.wait(5))
        revoked = self.host.revoke_pending('host-t5')
        self.assertEqual(revoked['status'], 'revoked')
        self.assertTrue(thread.is_alive(), '撤销不应等待长 G3 完成')
        release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertFalse(outcome[0]['applied'])
        self.assertFalse(self.journal_path().exists())

    def test_cross_process_revoke_uses_executor_barrier_during_g3(self):
        self.assertEqual(self.run_legacy()['status'], 'ready_to_apply')
        self.mint_approval()
        entered, release = threading.Event(), threading.Event()
        self.host.transport = self.blocking_reviewer(entered, release)
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(self.host.apply_pending('host-t5')))
        thread.start()
        self.assertTrue(entered.wait(5))
        process = subprocess.run(
            [sys.executable, '-B', '-m', 'tools.tests.fixtures.learning_s1.workflow', 'revoke', str(self.root),
             str(self.state_dir), 'host-t5'],
            cwd=PROJECT, capture_output=True, timeout=15,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(thread.is_alive())
        release.set()
        thread.join(10)
        self.assertFalse(outcome[0]['applied'])
        self.assertFalse(self.journal_path().exists())

    def prepare_learning(self):
        values = self.fixture.ingest_values()
        self.plan = {
            'changes': [
                dict(action='write', path=path, text=text)
                for path, text in values.items() if path != fixtures.RAW
            ] + [dict(
                action='raw_metadata', path=fixtures.RAW,
                metadata={'processing_status': 'pending_review',
                          'processed_into': '[[sources/来源]]'},
            )]
        }
        result = self.host.run_learning_operation(
            'host-t5', '保留原始适用条件', list(values), [fixtures.RAW],
            max_calls=12, max_seconds=120, call_timeout=20,
        )
        self.assertEqual(result['status'], 'ready_to_apply', result)
        runtime_ids = result['runtime_ids']
        candidate_value = candidate_digest(result['bundle']['candidate'])
        dependencies_value = digest(result['bundle']['snapshot'])
        rules_value = result['bundle']['manifest']['rules_digest']
        credentials = copy.deepcopy(self.records['review_credentials'])
        readiness = copy.deepcopy(self.records['readiness'])
        for credential, requirement in zip(credentials, readiness['required_credentials']):
            credential['credential_id'] += '-host-t5'
            credential['invocation_id'] += '-host-t5'
            credential['learning_task_id'] = runtime_ids['learning_task_id']
            credential['dependencies_digest'] = dependencies_value
            credential['rules_digest'] = rules_value
            credential['scope']['candidate_digest'] = candidate_value
            self.host.runtime.save_review_credential(credential)
            requirement['credential_ref'] = credential['credential_id']
            from tools.wiki_runtime.runtime import review_credential_digest
            requirement['credential_digest'] = review_credential_digest(credential)
        readiness.update(
            learning_task_id=runtime_ids['learning_task_id'],
            candidate_digest=candidate_value, dependencies_digest=dependencies_value,
            rules_digest=rules_value,
        )
        self.host.runtime.save_readiness(readiness)
        confirm_learning(self.host, runtime_ids['task_id'])
        from tools.wiki_runtime.runtime import readiness_digest
        authorization = self.host.authorize_learning(
            'host-t5', readiness_digest(readiness),
        )
        return result, authorization

    def pause_during_g3(self, *, cross_process):
        self.prepare_learning()
        entered, release = threading.Event(), threading.Event()
        self.host.transport = self.blocking_reviewer(entered, release)
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(self.host.apply_pending('host-t5')))
        thread.start()
        if not entered.wait(20):
            release.set()
            thread.join(10)
            self.fail('学习 G3 未进入阻塞点: ' + repr(outcome))
        task_id = self.host.load_pending('host-t5')['learning']['task_id']
        if cross_process:
            process = subprocess.run(
                [sys.executable, '-B', '-m', 'tools.tests.fixtures.learning_s1.workflow', 'pause', str(self.root),
                 str(self.state_dir), task_id],
                cwd=PROJECT, capture_output=True, timeout=15,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
        else:
            paused = self.host.pause_learning(task_id)
            self.assertEqual(paused['state'], 'paused')
        self.assertTrue(thread.is_alive(), '暂停不应等待长 G3 完成')
        release.set()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertFalse(outcome[0]['applied'])
        self.assertFalse(self.journal_path().exists())

    def test_learning_pause_same_host_thread_prevents_wal(self):
        self.pause_during_g3(cross_process=False)

    def test_learning_pause_cross_process_prevents_wal(self):
        self.pause_during_g3(cross_process=True)

    def test_reauthorize_and_revoke_current_cannot_leave_old_admission_valid(self):
        _result, first = self.prepare_learning()
        entered, release = threading.Event(), threading.Event()
        self.host.transport = self.blocking_reviewer(entered, release)
        outcome = []
        thread = threading.Thread(target=lambda: outcome.append(self.host.apply_pending('host-t5')))
        thread.start()
        self.assertTrue(entered.wait(20))
        second = self.host.authorize_learning('host-t5', first['readiness_digest'])
        revoked = self.host.revoke_pending('host-t5')
        self.assertEqual(revoked['authorization']['authorization_ref'],
                         second['authorization_ref'])
        first_stored = json.loads(self.host.runtime.store.read(
            "SELECT record_json FROM authorizations WHERE authorization_ref='"
            + first['authorization_ref'] + "'"
        )[0]['record_json'])
        self.assertEqual(first_stored['state'], 'revoked')
        release.set()
        thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertFalse(outcome[0]['applied'])
        self.assertFalse(self.journal_path().exists())

    def test_reauthorize_pending_write_race_revokes_every_operation_authorization(self):
        _result, first = self.prepare_learning()
        original_issue = self.host.runtime.issue_ingest_authorization
        entered, release = threading.Event(), threading.Event()
        def paused_issue(**kwargs):
            authorization = original_issue(**kwargs)
            entered.set()
            if not release.wait(20):
                raise TimeoutError('重新授权回写屏障超时')
            return authorization
        self.host.runtime.issue_ingest_authorization = paused_issue
        outcome = []
        def reauthorize():
            try:
                outcome.append(self.host.authorize_learning(
                    'host-t5', first['readiness_digest']))
            except Exception as exc:
                outcome.append(exc)
        thread = threading.Thread(target=reauthorize)
        thread.start()
        self.assertTrue(entered.wait(20))
        revoked = self.host.revoke_learning_authorization('host-t5')
        self.assertEqual(revoked['status'], 'revoked')
        release.set()
        thread.join(20)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], Exception)
        applied = self.host.apply_pending('host-t5')
        self.assertFalse(applied['applied'])
        self.assertFalse(self.journal_path().exists())
        authorizations = self.host.runtime.store.read('SELECT record_json FROM authorizations')
        self.assertGreaterEqual(len(authorizations), 2)
        self.assertTrue(all(json.loads(row['record_json'])['state'] == 'revoked'
                            for row in authorizations))

    def test_learning_managed_apply_reconciles_real_wal(self):
        result, _authorization = self.prepare_learning()
        applied = self.host.apply_pending('host-t5')
        self.assertEqual(applied['status'], 'applied', applied)
        self.assertTrue(applied['applied'])
        self.assertTrue(self.journal_path().exists())
        task_id = result['runtime_ids']['task_id']
        task = json.loads(self.host.runtime.store.read(
            "SELECT record_json FROM tasks WHERE task_id='" + task_id + "'"
        )[0]['record_json'])
        self.assertEqual(task['state'], 'completed')

    def test_learning_terminal_replay_works_after_host_restart(self):
        self.prepare_learning()
        applied = self.host.apply_pending('host-t5')
        self.assertTrue(applied['applied'])
        self.host.close()
        self.host = StandaloneHost(self.root, self.state_dir, transport=self.transport)
        replay = self.host.apply_pending('host-t5')
        self.assertEqual(replay['status'], 'applied')
        self.assertTrue(replay['applied'])
        self.assertEqual(replay['execution'], applied['execution'])

    def test_learning_recovered_replay_works_after_host_restart(self):
        self.prepare_learning()
        original = self.host._executor

        def faulty(coordinator, **kwargs):
            executor = original(coordinator, **kwargs)
            def fault(event, index):
                if event == 'after_prepare':
                    raise RuntimeError('保留可恢复 WAL')
            executor.fault = fault
            return executor

        self.host._executor = faulty
        prepared = self.host.apply_pending('host-t5')
        self.assertEqual(prepared['status'], 'prepared')
        recovered = self.host.runtime.executor.recover('host-t5')
        self.assertEqual(recovered['state'], 'recovered')
        admission = json.loads(self.host.runtime.store.read(
            'SELECT record_json FROM operation_admissions'
        )[0]['record_json'])
        binding = {field: admission[field] for field in (
            'task_id', 'learning_task_id', 'raw_batch_id', 'operation_id',
            'candidate_digest', 'dependencies_digest', 'rules_digest',
        )}
        binding.update(
            state=recovered['state'], recovery_status=recovered['recovery_status'],
        )
        self.host.runtime.reconcile_execution(binding)
        self.host.close()
        self.host = StandaloneHost(self.root, self.state_dir, transport=self.transport)
        replay = self.host.apply_pending('host-t5')
        self.assertEqual(replay['status'], 'recovered')
        self.assertFalse(replay['applied'])
        self.assertEqual(replay['execution'], recovered)


if __name__ == '__main__':
    unittest.main()
