"""S1 T4：锁外 G3、最终原子接受、Admission 绑定与独立恢复。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from tools.wiki_runtime.candidate import CandidateView
from tools.wiki_runtime.contracts import bytes_digest, candidate_digest, digest
from tools.wiki_runtime.executor import Executor, ExecutionError
from tools.wiki_runtime.review import PROMPT_VERSION
from tools.wiki_runtime.runtime import (
    AdmissionError, ExecutionReconcileError, RuntimeInvocationPort, RuntimeService, RuntimeStore,
    readiness_digest, review_credential_digest,
)


FIXTURES = Path(__file__).resolve().parent / 'fixtures'
PROCESS_FIXTURE = FIXTURES / 'learning_s1' / 'executor_process.py'
PROJECT = Path(__file__).resolve().parents[2]
RULES = PROJECT / 'tools/wiki_runtime/contracts/rules.json'
RAW = 'raw/unprocessed/原文.md'
PAGE = 'wiki/synthesis/结论.md'
SOURCE = 'wiki/sources/来源.md'


class ExecutorAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'vault'
        self.payload = self.base / 'payload'
        self.journal = self.base / 'private/journals'
        self.root.mkdir()
        self.payload.mkdir()
        self.write('AGENTS.md', '# 规则\n原始资料正文只读。\n')
        self.write('tools/wiki_runtime/contracts/rules.json', RULES.read_bytes())
        self.write(RAW, '---\nprocessing_status: unprocessed\n---\n仅在小样本中可能有效。\n')
        self.text = ('---\ntype: synthesis\nstatus: active\ntopic: 测试\nupdated: 2026-10-26\n---\n# 结论\n'
                     + '保留适用条件与不确定性，原文仅在小样本中可能有效。' * 25 + '\n')
        self.write(PAGE, self.text)
        self.write('wiki/index.md', '# 索引\n[[synthesis/结论]]\n')
        self.write('wiki/log.md', '# 日志\n## [2026-10-26] init | 测试\n[[synthesis/结论]]\n')
        self.write('raw/index.md', '# 素材\n- 未处理：1\n- 待确认：0\n- 已处理：0\n'
                   '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | unprocessed |\n')
        self.records = json.loads(
            (FIXTURES / 'learning_s0/protocol_records.json').read_text(encoding='utf-8')
        )['valid']
        self.store = RuntimeStore(self.root, busy_timeout=0.2)
        self.addCleanup(self.store.close)
        self.port = RuntimeInvocationPort(self.store, clock=lambda: 100.0)
        self.calls = []
        self.executor = self.make_executor()
        self.service = RuntimeService(self.store, executor=self.executor, clock=lambda: 100.0)
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

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode() if isinstance(data, str) else data)

    def snapshot(self):
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob('*')
            if path.is_file() and '.wiki-runtime' not in path.parts
        }

    def reviewer(self, envelope, *, timeout):
        self.calls.append(timeout)
        request = envelope['input']
        evidence = ['original:' + path + '#L1-L1' for path in request['originals']]
        evidence += ['candidate:' + path + '#L1-L1' for path in request['candidate_files']]
        evidence += [
            'before:' + change['path'] + '#L1-L1'
            for change in request['candidate']['changes'] if change['action'] == 'delete'
        ]
        return dict(
            contract_version='1.0', **request['bindings'], reviewer_id=envelope['reviewer_id'],
            result='recommend_pass', findings=[], evidence_refs=evidence,
        )

    def make_executor(self, **kwargs):
        options = dict(
            reviewer=self.reviewer, invocation_port=self.port,
            acceptance_context=lambda admission: self.service.acceptance_context(admission),
        )
        options.update(kwargs)
        return Executor(self.root, self.journal, **options)

    def ingest_values(self):
        return {
            RAW: '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/来源]]"\n---\n仅在小样本中可能有效。\n',
            SOURCE: '---\ntype: source\nstatus: active\ntopic: 测试\nupdated: 2026-10-26\nraw_note: "[[raw/unprocessed/原文]]"\nrelated_synthesis: ["[[synthesis/结论]]"]\n---\n# 来源\n'
                    + '保留原始限定与来源证据。' * 30 + '\n参见 [[synthesis/结论]]\n',
            PAGE: self.text.replace('---\n#', 'related_sources: ["[[sources/来源]]"]\n---\n#')
                    + '\n证据来自 [[sources/来源]]\n',
            'wiki/index.md': '# 索引\n[[synthesis/结论]]\n[[sources/来源]]\n[[meta/overview]]\n',
            'wiki/log.md': '# 日志\n## [2026-10-26] ingest | 来源\n[[sources/来源]]\n',
            'wiki/meta/overview.md': '# 总览\n[[sources/来源]]\n',
            'raw/index.md': '# 素材\n- 未处理：0\n- 待确认：1\n- 已处理：0\n'
                            '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | pending_review | [[sources/来源]] |\n',
        }

    def bundle(self, operation_id='operation-1', *, operation='ingest', values=None, input_refs=None):
        values = self.ingest_values() if values is None else values
        changes = []
        for index, (path, data) in enumerate(values.items()):
            data = data.encode() if isinstance(data, str) else data
            name = f'{operation_id}-{index}.md'
            (self.payload / name).write_bytes(data)
            target = self.root / path
            precondition = (dict(kind='hash', sha256=bytes_digest(target.read_bytes()))
                            if target.exists() else dict(kind='absent'))
            changes.append(dict(
                action='write', path=path, payload_path=name, sha256=bytes_digest(data),
                precondition=precondition,
            ))
        candidate = dict(contract_version='1.0', operation_id=operation_id, changes=changes)
        view = CandidateView(self.root, candidate, self.payload)
        list(view.iter_paths())
        snapshot = view.dependency_snapshot()
        manifest = dict(
            contract_version='1.0', operation_id=operation_id, operation_type=operation,
            task='保留原文条件', input_refs=[RAW] if input_refs is None else input_refs,
            allowed_paths=list(values),
            rules_path='AGENTS.md', rules_digest=bytes_digest((self.root / 'AGENTS.md').read_bytes()),
            mapping_digest=bytes_digest(RULES.read_bytes()), validator_version='gates-1.0',
            review_prompt_version=PROMPT_VERSION, candidate_digest=candidate_digest(candidate),
            dependencies_digest=digest(snapshot), round=1,
            required_gates=['G0', 'G1', 'G2'], authorization_refs=[],
        )
        return dict(
            manifest=manifest, candidate=candidate, snapshot=snapshot,
            payload_root=str(self.payload), reports=[{'result': 'pass'}],
            review={'result': 'recommend_pass'},
        )

    def prepare(self, operation_id='operation-1', *, values=None, input_refs=None):
        bundle = self.bundle(operation_id, values=values, input_refs=input_refs)
        candidate_value = candidate_digest(bundle['candidate'])
        dependencies_value = digest(bundle['snapshot'])
        rules_value = bundle['manifest']['rules_digest']
        credentials = copy.deepcopy(self.records['review_credentials'])
        readiness = copy.deepcopy(self.records['readiness'])
        for credential, requirement in zip(credentials, readiness['required_credentials']):
            old_id = credential['credential_id']
            credential['credential_id'] = old_id + '-' + operation_id
            credential['invocation_id'] += '-' + operation_id
            credential['dependencies_digest'] = dependencies_value
            credential['rules_digest'] = rules_value
            credential['scope']['candidate_digest'] = candidate_value
            self.service.save_review_credential(credential)
            requirement['credential_ref'] = credential['credential_id']
            requirement['credential_digest'] = review_credential_digest(credential)
        readiness.update(
            candidate_digest=candidate_value, dependencies_digest=dependencies_value,
            rules_digest=rules_value,
        )
        self.service.save_readiness(readiness)
        readiness_value = readiness_digest(readiness)
        authorization = self.service.issue_ingest_authorization(
            task_id=self.task['task_id'], operation_id=operation_id,
            readiness_digest=readiness_value, authorization_ref='authorization-' + operation_id,
        )
        admission = self.service.build_admission(
            run_id=self.run['run_id'], operation_id=operation_id,
            manifest_digest=digest(bundle['manifest']), readiness_digest=readiness_value,
            authorization_ref=authorization['authorization_ref'],
        )
        return bundle, authorization, admission

    def result_binding(self, admission, result):
        return {
            field: admission[field] for field in (
                'task_id', 'learning_task_id', 'raw_batch_id', 'operation_id',
                'candidate_digest', 'dependencies_digest', 'rules_digest',
            )
        } | {'state': result['state'], 'recovery_status': result['recovery_status']}

    def journal_path(self, operation_id):
        return self.journal / (digest(operation_id) + '.json')

    def assert_no_wal_or_write(self, operation_id, before):
        self.assertFalse(self.journal_path(operation_id).exists())
        self.assertFalse((self.root / '.wiki-runtime/executor-active.json').exists())
        self.assertEqual(self.snapshot(), before)

    def test_managed_apply_reconcile_and_terminal_replay_have_one_review(self):
        bundle, authorization, admission = self.prepare()
        result = self.executor.apply(bundle, admission=admission)
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual(len(self.calls), 1)
        journal = json.loads(self.journal_path(admission['operation_id']).read_bytes())
        self.assertIn('admission_digest', journal)
        self.assertEqual([report['gate'] for report in journal['reports']],
                         ['G0', 'G1', 'G2', 'G3', 'G4', 'G5'])
        projected = self.service.reconcile_execution(self.result_binding(admission, result))
        self.assertTrue(projected['applied'])
        stored_auth = json.loads(self.store.read(
            'SELECT record_json FROM authorizations'
        )[0]['record_json'])
        self.assertEqual(stored_auth['state'], 'consumed')

        def forbidden(*args, **kwargs):
            raise AssertionError('终态重放不得触发审查、预算或动态准入')

        replay = self.make_executor(
            reviewer=forbidden, invocation_port=forbidden, acceptance_context=forbidden,
        )
        self.assertEqual(replay.apply(bundle, admission=admission), result)
        self.assertEqual(replay.lookup_terminal(bundle, admission), result)
        changed = dict(admission, authorization_ref='different-authorization')
        with self.assertRaisesRegex(ExecutionError, '不同 Admission'):
            replay.apply(bundle, admission=changed)
        with self.assertRaisesRegex(ExecutionError, '不同 Admission'):
            replay.lookup_terminal(bundle, changed)
        with self.assertRaisesRegex(ExecutionError, '不同 Admission'):
            replay.lookup_terminal(bundle)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(authorization['state'], 'issued')

    def interfere_during_review(self, action):
        bundle, _authorization, admission = self.prepare()
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def blocking_reviewer(envelope, *, timeout):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('G3 测试屏障超时')
            return self.reviewer(envelope, timeout=timeout)

        executor = self.make_executor(reviewer=blocking_reviewer)
        before = self.snapshot()

        def apply():
            try:
                executor.apply(bundle, admission=admission)
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=apply)
        thread.start()
        self.assertTrue(entered.wait(10), errors)
        action(admission)
        release.set()
        thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1, errors)
        self.assertIsInstance(errors[0], AdmissionError)
        self.assert_no_wal_or_write(admission['operation_id'], before)
        return admission

    def test_revoke_during_unlocked_g3_prevents_wal(self):
        self.interfere_during_review(
            lambda admission: self.service.revoke_ingest_authorization(
                admission['authorization_ref'],
            ),
        )

    def test_pause_during_unlocked_g3_prevents_old_operation_and_resume_uses_new_one(self):
        admission = self.interfere_during_review(
            lambda _admission: self.service.pause(self.task['task_id']),
        )
        binding = self.store.read('SELECT * FROM operation_admissions')[0]
        self.assertEqual(binding['binding_state'], 'superseded_by_pause')
        new_run = copy.deepcopy(self.run)
        new_run['run_id'] = 'run-after-pause'
        new_ownership = copy.deepcopy(self.ownership)
        new_ownership['generation'] += 1
        new_ownership['owner'] = 'owner-after-pause'
        self.service.resume(self.task['task_id'], run=new_run, ownership=new_ownership)
        self.run = new_run
        new_bundle, _authorization, new_admission = self.prepare('operation-after-pause')
        with self.assertRaisesRegex(ExecutionError, 'operation_id'):
            self.executor.apply(new_bundle, admission=admission)
        result = self.executor.apply(new_bundle, admission=new_admission)
        self.assertEqual(result['state'], 'applied', result)

    def test_readiness_invalidation_during_unlocked_g3_prevents_wal(self):
        self.interfere_during_review(
            lambda admission: self.service.invalidate_readiness(
                admission['readiness_digest'], reason='测试失效',
            ),
        )

    @staticmethod
    def capture_error(errors, call):
        try:
            call()
        except Exception as exc:
            errors.append(exc)

    def test_ownership_generation_change_during_unlocked_g3_prevents_wal(self):
        def supersede(_admission):
            changed = copy.deepcopy(self.ownership)
            changed['generation'] += 1
            changed['owner'] = 'new-owner'
            self.store.mutate(lambda connection: connection.execute(
                'UPDATE execution_ownerships SET owner=?, generation=?, record_json=? WHERE task_id=?',
                (changed['owner'], changed['generation'], json.dumps(changed), self.task['task_id']),
            ))

        self.interfere_during_review(supersede)

    def test_actual_g3_overage_blocks_acceptance_without_wal(self):
        bundle, _authorization, admission = self.prepare()
        port = self.port

        class OveragePort:
            def remaining_run_time(self, run_id):
                return port.remaining_run_time(run_id)

            def invoke(self, spec, call, timeout):
                def measured():
                    usage = {**spec['requested_budget'], 'model_calls': 11, 'tokens': None}
                    return {'result': call(), 'actual_usage': usage}

                return port.invoke(spec, measured, timeout)

        before = self.snapshot()
        with self.assertRaisesRegex(AdmissionError, '预算已阻断'):
            self.make_executor(invocation_port=OveragePort()).apply(bundle, admission=admission)
        self.assert_no_wal_or_write(admission['operation_id'], before)
        for table in ('task_finance', 'run_finance'):
            self.assertEqual(self.store.read(f'SELECT blocked FROM {table}')[0]['blocked'], 1)

    def test_admission_requires_matching_operation_and_ingest_cannot_replace_g4(self):
        bundle, _authorization, admission = self.prepare()
        other = self.bundle('other-operation')
        with self.assertRaisesRegex(ExecutionError, 'operation_id'):
            self.executor.apply(other, admission=admission)
        values = {'AGENTS.md': '# 新规则\n仍须独立批准。\n'}
        maintenance = self.bundle('rule-operation', operation='rule_maintenance', values=values)
        with self.assertRaisesRegex(ExecutionError, '不能替代'):
            self.executor.apply(maintenance, admission=admission, approval=object())
        self.assertFalse(self.journal_path('rule-operation').exists())

    def test_manifest_rebinding_is_rejected_before_g3_or_wal(self):
        bundle, _authorization, admission = self.prepare()
        before = self.snapshot()
        mutations = (
            ('task', '更换审查任务'),
            ('input_refs', [PAGE]),
            ('allowed_paths', list(bundle['manifest']['allowed_paths']) + ['wiki/uncovered.md']),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                changed = copy.deepcopy(bundle)
                changed['manifest'][field] = value
                with self.assertRaisesRegex(ExecutionError, 'manifest_digest'):
                    self.executor.apply(changed, admission=admission)
                self.assert_no_wal_or_write(admission['operation_id'], before)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.store.read('SELECT * FROM invocations'), [])

    def test_applied_reconcile_without_real_wal_is_rejected_without_side_effects(self):
        _bundle, _authorization, admission = self.prepare('forged-applied')
        forged = self.result_binding(admission, {
            'state': 'applied', 'recovery_status': 'not_needed',
        })
        with self.assertRaisesRegex(ExecutionReconcileError, '真实 WAL'):
            self.service.reconcile_execution(forged)
        self.assertEqual(self.store.read('SELECT * FROM execution_results'), [])
        authorization = json.loads(self.store.read(
            'SELECT record_json FROM authorizations'
        )[0]['record_json'])
        task = json.loads(self.store.read('SELECT record_json FROM tasks')[0]['record_json'])
        self.assertEqual(authorization['state'], 'issued')
        self.assertEqual(task['state'], 'running')

    def test_approve_revocation_uses_barrier_and_final_g4_precedes_no_wal(self):
        values = {'AGENTS.md': '# 新规则\n仍须独立批准。\n'}
        bundle = self.bundle('approve-interface', operation='rule_maintenance', values=values)
        valid = [True]
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def blocking_reviewer(envelope, *, timeout):
            entered.set()
            self.assertTrue(release.wait(5))
            return self.reviewer(envelope, timeout=timeout)

        executor = self.make_executor(
            reviewer=blocking_reviewer, reserve_call=lambda: True, invocation_port=None,
            acceptance_context=None, approval_check=lambda context, approval: valid[0],
        )
        before = self.snapshot()
        thread = threading.Thread(target=lambda: self.capture_error(
            errors, lambda: executor.apply(bundle, approval=object()),
        ))
        thread.start()
        self.assertTrue(entered.wait(10), errors)
        with executor.acceptance_barrier():
            valid[0] = False
        release.set()
        thread.join(15)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(errors[0], ExecutionError)
        self.assertIn('批准已失效', str(errors[0]))
        self.assert_no_wal_or_write('approve-interface', before)

    def process_config(self, operation_id='operation-1', *, review_timeout=30):
        bundle, _authorization, admission = self.prepare(operation_id)
        config = self.base / f'{operation_id}-config.json'
        config.write_text(json.dumps({
            'root': str(self.root), 'journal': str(self.journal), 'bundle': bundle,
            'admission': admission, 'policy': self.policy, 'task': self.task, 'run': self.run,
            'ownership': self.ownership, 'learning': self.learning,
            'review_timeout': review_timeout,
            'readiness': json.loads(self.store.read(
                'SELECT record_json FROM readiness_records'
            )[0]['record_json']),
            'credentials': [json.loads(row['record_json']) for row in self.store.read(
                'SELECT record_json FROM review_credentials'
            )],
        }, ensure_ascii=False), encoding='utf-8')
        return config, bundle, admission

    def run_managed(self, config, exit_at=None, *, expected=0):
        args = [sys.executable, '-B', str(PROCESS_FIXTURE), 'managed-apply', str(config)]
        if exit_at:
            args.append(exit_at)
        result = subprocess.run(
            args, cwd=PROJECT, env=dict(os.environ, PYTHONPATH=str(PROJECT)),
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def test_crash_at_acceptance_has_no_wal_and_retry_replays_original_g3(self):
        config, bundle, admission = self.process_config(review_timeout=600)
        self.run_managed(config, 'after_acceptance_before_prepare', expected=87)
        self.assertEqual(self.port.remaining_run_time(self.run['run_id']), 300.0)
        self.assertFalse(self.journal_path(admission['operation_id']).exists())
        self.assertEqual(len(self.store.read('SELECT * FROM invocations')), 1)
        result = self.run_managed(config)
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual(len(self.store.read('SELECT * FROM invocations')), 1)
        record = self.store.read('SELECT record_json FROM invocations')[0]
        self.assertIn('"result_state":"succeeded"', record['record_json'])

    def test_real_wal_recovery_and_reconcile_never_mark_recovered_as_applied(self):
        config, bundle, admission = self.process_config('real-recovery')
        self.run_managed(config, 'after_prepare', expected=87)
        self.assertTrue(self.journal_path(admission['operation_id']).exists())
        self.service.pause(self.task['task_id'])
        binding = self.store.read('SELECT * FROM operation_admissions')[0]
        self.assertEqual(binding['binding_state'], 'active')
        recovered = Executor(self.root, self.journal).recover(admission['operation_id'])
        self.assertEqual(recovered['state'], 'recovered', recovered)
        projected = self.service.reconcile_execution(self.result_binding(admission, recovered))
        self.assertFalse(projected['applied'])
        self.assertFalse(projected['authorization_consumed'])
        replay = Executor(self.root, self.journal)
        self.assertEqual(replay.apply(bundle, admission=admission), recovered)

    def test_crash_after_applied_wal_recovers_and_reconciles_original_binding(self):
        config, bundle, admission = self.process_config('accepted-before-reconcile')
        self.run_managed(config, 'after_commit', expected=87)
        recovered = Executor(self.root, self.journal).recover(admission['operation_id'])
        self.assertEqual(recovered['state'], 'applied', recovered)
        projected = self.service.reconcile_execution(self.result_binding(admission, recovered))
        self.assertTrue(projected['applied'])
        self.assertEqual(self.service.reconcile_execution(
            self.result_binding(admission, recovered)
        ), projected)


    def test_execution_reconcile_requires_real_wal_for_every_state(self):
        for operation, state, recovery in (
            ('forged-recovered', 'recovered', 'recovered'),
            ('forged-prepared', 'prepared', 'required'),
            ('forged-applying', 'applying', 'required'),
            ('forged-conflict', 'recovery_required', 'conflict'),
        ):
            with self.subTest(state=state, recovery=recovery):
                _bundle, _authorization, admission = self.prepare(operation)
                forged = self.result_binding(admission, {
                    'state': state, 'recovery_status': recovery,
                })
                with self.assertRaises(ExecutionReconcileError):
                    self.service.reconcile_execution(forged)
                self.assertEqual(self.store.read(
                    "SELECT * FROM execution_results WHERE operation_id='" + operation + "'"
                ), [])
        bundle, _authorization, admission = self.prepare('verified-state-transition')
        def stop_after_prepare(event, _index):
            if event == 'after_prepare':
                raise RuntimeError('保留 prepared WAL')
        prepared = self.make_executor(
            fault=stop_after_prepare,
        ).apply(bundle, admission=admission)
        self.assertEqual(prepared['state'], 'prepared')
        projected = self.service.reconcile_execution(self.result_binding(admission, prepared))
        self.assertFalse(projected['applied'])
        recovered = Executor(self.root, self.journal).recover(admission['operation_id'])
        projected = self.service.reconcile_execution(self.result_binding(admission, recovered))
        self.assertFalse(projected['applied'])
        self.assertTrue(projected['terminal'])
        self.assertEqual(Executor(self.root, self.journal).apply(
            bundle, admission=admission,
        ), recovered)


if __name__ == '__main__':
    unittest.main()
