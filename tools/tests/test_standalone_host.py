"""独立入口联测：真实网关、协调器、门禁和执行器，模型为可信测试替身。"""
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tools.tests import test_executor_recovery as fixtures
from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.host.approval import ApprovalError
from tools.wiki_runtime.host.supervisor import StandaloneHost, HostError, update_raw_metadata
from tools.wiki_runtime.gates import raw_parts
from tools.wiki_runtime.capture import capture
from tools.wiki_runtime.runtime import RuntimeStore


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.state_dir = self.fixture.base / 'host'
        self.envelopes = []
        self.plan = {'changes': [dict(action='write', path=p, text=(self.root / p).read_text(encoding='utf-8') + '\n')
                                 for p in (fixtures.PAGE, 'wiki/index.md', 'wiki/log.md')]}
        self.host = StandaloneHost(self.root, self.state_dir, transport=self.transport)

    def transport(self, envelope, *, timeout):
        self.envelopes.append(copy.deepcopy(envelope))
        if envelope['system'].startswith('你是中文知识库的处理者'):
            return copy.deepcopy(self.plan)
        return self.fixture.reviewer(envelope, timeout=timeout)

    def run_host(self, name='host-test', operation='inspool', apply=False, max_calls=8):
        allowed = [c['path'] for c in self.plan.get('changes', [])]
        allowed += [c['source'] for c in self.plan.get('changes', []) if 'source' in c]
        return self.host.run_operation(name, operation, '保留原始适用条件', allowed,
                                       [fixtures.RAW], max_calls=max_calls, max_seconds=120,
                                       call_timeout=20, apply=apply)

    def test_real_gates_reviewer_and_executor_apply(self):
        result = self.run_host(apply=True)
        self.assertEqual(result['status'], 'applied', result)
        self.assertTrue(result['applied'])
        self.assertEqual(result['state']['calls'], 3)  # Worker + T06 + Executor T06。
        self.assertEqual(len(self.fixture.calls), 2)
        for envelope in self.envelopes[1:]:
            self.assertNotIn('documents', envelope)
            self.assertNotIn('feedback', envelope['input'])
            self.assertNotIn('payload_root', envelope['input'])
            self.assertNotIn('tools', envelope)
        self.assertTrue((self.state_dir / 'private/journals').is_dir())
        replay = self.host.apply_pending('host-test')
        self.assertEqual(replay['status'], 'applied', replay)
        self.assertEqual(len(self.fixture.calls), 2)
        self.assertEqual(self.host.runtime.store.read('SELECT * FROM learning_states'), [])

    def test_pending_does_not_write_and_apply_revalidates(self):
        before = self.fixture.snapshot()
        result = self.run_host()
        self.assertEqual(result['status'], 'ready_to_apply', result)
        self.assertEqual(before, self.fixture.snapshot())
        self.assertEqual(self.host.load_pending('host-test')['context'], result['context'])
        self.fixture.write(fixtures.RAW, '用户并发更新原文\n')
        result = self.host.apply_pending('host-test')
        self.assertFalse(result['applied'])
        self.assertEqual(len(self.fixture.calls), 1)

    def test_directory_provenance_before_apply(self):
        self.assertEqual(self.run_host()['status'], 'ready_to_apply')
        (self.root / 'new-empty-directory').mkdir()
        result = self.host.apply_pending('host-test')
        self.assertFalse(result['applied'])
        self.assertEqual(len(self.fixture.calls), 1)

    def test_worker_input_mutation_cannot_refresh_preconditions(self):
        def mutate(envelope, *, timeout):
            if envelope['system'].startswith('你是中文知识库的处理者'):
                self.fixture.write(fixtures.RAW, '用户刚更新的内容\n')
            return self.transport(envelope, timeout=timeout)
        self.host.transport = mutate
        result = self.run_host(apply=True)
        self.assertFalse(result['applied'])
        self.assertEqual(self.fixture.calls, [])
        self.assertIn('用户刚更新', (self.root / fixtures.RAW).read_text(encoding='utf-8'))

    def test_strict_plan_unknown_action_scope_and_claims(self):
        plans = [{'changes': [], 'approved': True}, {'changes': [], 'role': 'executor'},
                 {'changes': [], 'tools': ['shell']}, {'changes': [dict(action='shell', path=fixtures.PAGE)]},
                 {'changes': [dict(action='write', path=fixtures.PAGE, text='x', approved=True)]}]
        for index, plan in enumerate(plans):
            with self.subTest(plan=plan):
                self.plan = plan
                result = self.run_host('invalid-' + str(index), apply=True)
                self.assertFalse(result['applied'])
        self.plan = {'changes': [dict(action='write', path='wiki/escape.md', text='x')]}
        result = self.host.run_operation('scope', 'inspool', '严格范围', [fixtures.PAGE], [fixtures.RAW],
                                         max_calls=3, max_seconds=60, call_timeout=10, apply=True)
        self.assertFalse(result['applied'])
        self.assertFalse((self.root / 'wiki/escape.md').exists())

    def test_raw_metadata_exact_bytes(self):
        before = ('\ufeff---\r\nsource: "原始来源"\r\n# 保留注释\r\nprocessing_status: unprocessed\r\n'
                  'processed_into:\r\n  - "[[sources/旧页]]"\r\n\r\n---\r\n正文\r\n\n末尾无换行').encode()
        result = update_raw_metadata(before, {'processing_status': 'pending_review',
                                             'processed_into': ['[[sources/新页]]']})
        original_fields, original_body = raw_parts(before)
        fields, body = raw_parts(result)
        self.assertEqual(original_body, body)
        self.assertEqual(original_fields['source'], fields['source'])
        self.assertEqual(original_fields['@layout'], fields['@layout'])
        with self.assertRaises(HostError):
            update_raw_metadata(before, {'source': '篡改'})

    def test_non_learning_ingest_is_rejected_before_model_or_formal_write(self):
        before = (self.root / fixtures.RAW).read_bytes()
        with self.assertRaisesRegex(HostError, '必须使用学习入口'):
            self.run_host(operation='ingest', apply=True)
        self.assertEqual((self.root / fixtures.RAW).read_bytes(), before)
        self.assertEqual(self.envelopes, [])
        self.assertFalse((self.state_dir / 'private/journals').exists())

    def test_approve_requires_independent_tty_not_command_or_json(self):
        bundle = self.fixture.approve_bundle()
        self.plan = {'changes': [dict(action='write', path=c['path'],
                                      text=(self.fixture.payload / c['payload_path']).read_text(encoding='utf-8'))
                                 for c in bundle['candidate']['changes'] if c['action'] != 'move'] +
                     [dict(action='move', source=fixtures.RAW, path='raw/processed/原文.md',
                           metadata={'processing_status': 'processed', 'reviewed_at': '2026-10-26'})]}
        before = self.fixture.snapshot()
        result = self.run_host(operation='approve', apply=True)
        self.assertEqual(result['status'], 'awaiting_approval', result)
        self.assertEqual(before, self.fixture.snapshot())
        with self.assertRaises(ApprovalError):
            self.host.approve_pending('host-test', input_stream=io.StringIO(digest(result['context']) + '\n'),
                                      output_stream=io.StringIO())
        code = '''import json,sys
from tools.wiki_runtime.host.approval import ApprovalStore,ApprovalError
context=json.loads(sys.stdin.readline())
try:
    ApprovalStore(sys.argv[1]).approve_interactive(context)
except ApprovalError:
    print("pipe-denied")
    sys.exit(3)
sys.exit(7)
'''
        process = subprocess.run([sys.executable, '-B', '-c', code, str(self.state_dir / 'private/approvals')],
                                 input=json.dumps(result['context']).encode() + b'\n', capture_output=True,
                                 cwd=Path(__file__).resolve().parents[2], timeout=15)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stdout.strip(), b'pipe-denied')
        self.assertEqual(self.host.apply_pending('host-test')['status'], 'awaiting_approval')
        self.assertIsNone(self.host.approvals.lookup(result['context']))
        offline = StandaloneHost(self.root, self.state_dir, None, offline=True)
        self.assertEqual(offline.load_pending('host-test')['context'], result['context'])
        with self.assertRaises(ApprovalError):
            offline.approve_pending('host-test', input_stream=io.StringIO(), output_stream=io.StringIO())
        self.assertEqual(offline.revoke_pending('host-test')['status'], 'revoked')

    def test_budget_survives_restart_and_executor_cannot_refill(self):
        result = self.run_host(max_calls=2)
        self.assertEqual(result['status'], 'ready_to_apply', result)
        restarted = StandaloneHost(self.root, self.state_dir, None, transport=self.transport)
        result = restarted.apply_pending('host-test')
        self.assertFalse(result['applied'])
        self.assertEqual(result['state']['calls'], 2)
        self.assertEqual(len(self.fixture.calls), 1)
        result = restarted.apply_pending('host-test')
        self.assertEqual(result['state']['calls'], 2)

    def test_expired_budget_not_reset(self):
        self.assertEqual(self.run_host()['status'], 'ready_to_apply')
        store = RuntimeStore(self.state_dir)
        ownership = json.loads(store.read('SELECT record_json FROM execution_ownerships')[0]['record_json'])
        ownership['expires_at'] = time.time() - 1  # 修改权威期限，而非 state.json 投影。
        store.mutate(lambda connection: connection.execute(
            'UPDATE execution_ownerships SET expires_at=?, record_json=? WHERE task_id=?',
            (ownership['expires_at'], json.dumps(ownership), ownership['task_id']),
        ))
        store.close()
        restarted = StandaloneHost(self.root, self.state_dir, None, transport=self.transport)
        result = restarted.apply_pending('host-test')
        self.assertFalse(result['applied'])
        self.assertEqual(result['state']['deadline'], ownership['expires_at'])

    def test_pending_tampering_is_not_trusted(self):
        self.assertEqual(self.run_host()['status'], 'ready_to_apply')
        path = self.state_dir / 'private/pending' / (digest('host-test') + '.json')
        record = json.loads(path.read_bytes())
        record['record']['bundle']['candidate']['changes'][0]['sha256'] = '0' * 64
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaises(HostError):
            self.host.apply_pending('host-test')

    def test_requires_host_transport_or_optional_api_configuration(self):
        with self.assertRaisesRegex(HostError, '可信宿主 transport'):
            StandaloneHost(self.root, self.fixture.base / 'unconfigured', None)
        for state in (self.root, self.root / 'state', self.root.parent):
            with self.subTest(state=state), self.assertRaises(HostError):
                StandaloneHost(self.root, state, None, transport=self.transport)

    def test_host_transport_does_not_construct_api_adapter(self):
        with patch('tools.wiki_runtime.host.supervisor.ResponsesTransport',
                   side_effect=AssertionError('native transport must not create API client')):
            host = StandaloneHost(self.root, self.fixture.base / 'native-host',
                                  transport=self.transport)
        self.assertEqual(host.transport, self.transport)

    def test_expected_plan_baseline_cannot_be_refreshed_before_dispatch(self):
        _, baseline = self.host._baseline('bound-plan', self.host.private)
        self.fixture.write(fixtures.RAW, '用户刚修改了来源正文\n')
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(HostError, '基线已变化'):
            self.host.run_operation('bound-plan', 'lint', '修复引用', [fixtures.PAGE],
                                    [fixtures.RAW], expected_baseline=baseline)
        self.assertEqual(self.envelopes, [])
        self.assertEqual(self.fixture.snapshot(), before)

    def test_managed_capture_inputs_expand_and_package_quality_survives(self):
        original = self.fixture.base / 'capture.md'
        original.write_text('# 原件\n限定在小样本中可能有效。\n', encoding='utf-8')
        candidate_root = self.fixture.base / 'packages'
        package, package_root = capture(original, candidate_root, 'one', vault_root=self.root, source_id='test-source')
        asset = 'raw/assets/' + package['source_id'] + '/' + package['source_revision']
        target = self.root / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(package_root, target)
        self.fixture.write(fixtures.RAW, '---\nsource_package: "[[' + asset + '/source-package.json]]"\n'
                           'processing_status: unprocessed\n---\n![[' + asset + '/extracted/content.md]]\n')
        result = self.run_host()
        self.assertEqual(result['status'], 'ready_to_apply', result)
        record = self.host.load_pending('host-test')
        self.assertEqual(record['config']['source_packages'], [package])
        self.assertIn(asset + '/extracted/content.md', record['config']['input_refs'])
        review = self.envelopes[-1]['input']
        self.assertIn('限定在小样本', review['originals'][asset + '/extracted/content.md'])
        package['quality'].update(status='partial', missing=['定位未完成'])
        (target / 'source-package.json').write_text(json.dumps(package), encoding='utf-8')
        calls = len(self.envelopes)
        paused = self.run_host('partial-source')
        self.assertEqual(paused['status'], 'awaiting_human', paused)
        self.assertEqual(len(self.envelopes), calls)

    def test_independent_rule_auditor_uses_t07_and_same_budget(self):
        worker_count, review_count, audits = [0], [0], []
        def model(envelope, *, timeout):
            if envelope['system'].startswith('你是中文知识库的处理者'):
                worker_count[0] += 1
                if worker_count[0] == 2:
                    return {'appeal': dict(rule_ids=['FACT-001'], failure_refs=['reports/G3.json'],
                        evidence='原文仅限定小样本', goal_conflict='核查规则适用', minimal_counterexample='带限定的结论',
                        proposal='核查实际失败', impact='仅测试页')}
                return copy.deepcopy(self.plan)
            if 'appeal' in envelope:
                audits.append(copy.deepcopy(envelope))
                return dict(envelope['appeal'], disposition='rule_valid', proposal='规则有效，保留限定', impact='修复结论页')
            review_count[0] += 1
            result = self.fixture.reviewer(envelope, timeout=timeout)
            if review_count[0] == 1:
                source, target = 'original:' + fixtures.RAW + '#L4-L4', 'candidate:' + fixtures.PAGE + '#L1-L1'
                result.update(result='request_changes', findings=[dict(rule_id='FACT-001', severity='blocking',
                    category='condition_expansion', target=target,
                    evidence=json.dumps({'refs': [source, target], 'reason': '保留限定'}),
                    expected='保留小样本条件', repairable=True)])
                result['evidence_refs'] += [source, target]
            return result
        self.host.transport = model
        result = self.run_host(apply=True)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(len(audits), 1)
        self.assertEqual(result['state']['audit_attempts'], 1)
        self.assertEqual(result['state']['calls'], 7)
        self.assertEqual(audits[0]['appeal']['disposition'], 'submitted')

    def test_offline_load_and_recovery_do_not_require_model_key(self):
        before = self.fixture.snapshot()
        self.assertEqual(self.run_host()['status'], 'ready_to_apply')
        make_executor = self.host._executor
        def failing(coordinator, **kwargs):
            executor = make_executor(coordinator, **kwargs)
            executor.fault = self.fixture.fault('after_write', 0)
            return executor
        self.host._executor = failing
        result = self.host.apply_pending('host-test')
        self.assertEqual(result['status'], 'recovery_required', result)
        offline = StandaloneHost(self.root, self.state_dir, None, offline=True)
        self.assertEqual(offline.load_pending('host-test')['config']['operation_id'], 'host-test')
        result = offline.recover('host-test')
        self.assertEqual(result['status'], 'recovered', result)
        self.assertEqual(before, self.fixture.snapshot())
        with self.assertRaises(HostError):
            offline.run_operation('forbidden', 'query', '离线不能运行模型', [], [], max_calls=1,
                                  max_seconds=10, call_timeout=1)

    def test_offline_semantic_apply_never_skips_g3(self):
        self.assertEqual(self.run_host()['status'], 'ready_to_apply')
        before = self.fixture.snapshot()
        offline = StandaloneHost(self.root, self.state_dir, None, offline=True)
        result = offline.apply_pending('host-test')
        self.assertFalse(result['applied'])
        self.assertEqual(result['state']['calls'], 3)
        self.assertEqual(before, self.fixture.snapshot())

    def test_missing_pending_key_is_not_regenerated(self):
        key = self.state_dir / 'private/pending.key'
        key.unlink()
        with self.assertRaises(HostError):
            StandaloneHost(self.root, self.state_dir, None, offline=True)
        self.assertFalse(key.exists())


if __name__ == '__main__':
    unittest.main()
