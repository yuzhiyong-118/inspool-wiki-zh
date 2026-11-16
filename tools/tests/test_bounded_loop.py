"""临时库与真实门禁/T06/T07协议；假模型不代表实际语义质量。"""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.wiki_runtime.coordinator import Coordinator
from tools.wiki_runtime.contracts import bytes_digest, ContractError, validate
from tools.wiki_runtime.review import PROMPT_VERSION
from tools.wiki_runtime.rule_audit import RuleAuditor

BASE = Path(__file__).resolve().parents[1] / 'wiki_runtime/contracts'
RAW = 'raw/unprocessed/原文.md'
PAGE = 'wiki/synthesis/结论.md'


class BoundedLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'vault'
        self.root.mkdir()
        self.write('AGENTS.md', '# 规则\n正文只读，判断需来源。\n')
        self.write('tools/wiki_runtime/contracts/rules.json', (BASE / 'rules.json').read_bytes())
        self.write(RAW, '---\nprocessing_status: unprocessed\n---\n仅在小样本中可能有效。\n')
        self.text = ('---\ntype: synthesis\nstatus: active\ntopic: 测试\nupdated: 2026-10-26\n---\n'
            '# 结论\n\n仅在小样本中可能有效。' + '这是完整的临时夹具说明，保留来源的适用条件与不确定性。' * 12 + '\n')
        self.write(PAGE, self.text)
        self.write('wiki/index.md', '# 索引\n[[synthesis/结论]]\n')
        self.write('wiki/log.md', '# 日志\n## [2026-10-26] init | 测试\n已登记 [[synthesis/结论]]。\n')
        self.write('raw/index.md', '# 素材\n- 未处理：1\n- 待确认：0\n- 已处理：0\n'
                   '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | unprocessed |\n')
        self.params = dict(operation_id='bounded-test', operation_type='inspool', task='保留条件生成结论',
            allowed_paths=[PAGE, 'wiki/index.md', 'wiki/log.md'], input_refs=[RAW],
            max_calls=15, max_seconds=120, call_timeout=30, environment_retries=1)
        self.run_dir = Path(self.tmp.name) / 'run'

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode() if isinstance(content, str) else content)

    def coordinator(self, **overrides):
        return Coordinator(self.root, self.run_dir, **dict(self.params, **overrides))

    def worker(self, request, *, timeout):
        payload_root = Path(request['payload_root'])
        changes = []
        for n, path in enumerate((PAGE, 'wiki/index.md', 'wiki/log.md')):
            data = (self.root / path).read_bytes() + b'\n'
            name = str(n) + '.md'
            (payload_root / name).write_bytes(data)
            changes.append(dict(action='write', path=path, payload_path=name, sha256=bytes_digest(data),
                precondition=dict(kind='hash', sha256=bytes_digest((self.root / path).read_bytes()))))
        return dict(candidate=dict(contract_version='1.0', operation_id='bounded-test', changes=changes),
                    payload_root=str(payload_root))

    def reviewer(self, envelope, *, timeout, fail=False):
        args = envelope['input']
        self.assertNotIn('feedback', args)
        self.assertNotIn('explanation', args)
        self.assertEqual(args['prompt_version'], PROMPT_VERSION)
        self.assertEqual(set(args['originals']), {RAW})
        self.assertEqual(set(args['original_pages']), {PAGE, 'wiki/index.md', 'wiki/log.md'})
        source = 'original:' + RAW + '#L4-L4'
        target = 'candidate:' + PAGE + '#L9-L9'
        evidence = [source] + ['candidate:' + p + '#L1-L1' for p in args['candidate_files']]
        findings = []
        if fail:
            evidence.append(target)
            findings = [dict(rule_id='FACT-001', severity='blocking', category='condition_expansion',
                target=target, evidence=json.dumps(dict(refs=[source, target], reason='须保留原文限定')),
                expected='保留限定', repairable=True)]
        return dict(contract_version='1.0', **args['bindings'], reviewer_id=envelope['reviewer_id'],
                    result='request_changes' if fail else 'recommend_pass', findings=findings,
                    evidence_refs=evidence)

    def appeal(self, request):
        feedback = request['feedback']
        manifest = feedback['manifest']
        binding = {k: manifest[k] for k in ('operation_id', 'candidate_digest', 'dependencies_digest',
            'rules_digest', 'mapping_digest', 'validator_version', 'review_prompt_version')}
        return dict(appeal=dict(contract_version='1.0', **binding, rule_ids=['FACT-001'],
            failure_refs=['reports/G3.json'], evidence='具体原文有小样本限定', goal_conflict='需核对规则适用性',
            minimal_counterexample='保留条件的两行文本', proposal='核对失败定位', impact='仅测试结论页',
            disposition='submitted'))

    def auditor(self, disposition='rule_valid', transport=None):
        def fake(request, *, timeout):
            return dict(request['appeal'], disposition=disposition, proposal='规则裁决及后续验证', impact='独立修订与重验')
        return RuleAuditor((self.root / 'AGENTS.md').read_bytes(), (BASE / 'rules.json').read_bytes(),
            validator_version='gates-1.0', review_prompt_version=PROMPT_VERSION,
            transport=fake if transport is None else transport)

    def test_repair_success_uses_real_gates_and_review(self):
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        calls = []
        def reviewer(envelope, *, timeout):
            calls.append(envelope)
            return self.reviewer(envelope, timeout=timeout, fail=len(calls) == 1)
        result = self.coordinator().run(self.worker, reviewer=reviewer)
        self.assertEqual(result.status, 'ready_to_apply', result.reason)
        self.assertEqual(result.state['candidates'], 2)
        self.assertEqual(result.state['calls'], 4)
        self.assertEqual({r['gate'] for r in result.bundle['reports']}, {'G0', 'G1', 'G2', 'G3'})
        self.assertTrue(all(r['result'] == 'pass' for r in result.bundle['reports']))
        self.assertEqual(before, {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(result.bundle['manifest']['authorization_refs'], [])
        for report in result.bundle['reports']:
            validate('gate_report', report)

    def test_three_candidates_exhausted(self):
        result = self.coordinator().run(self.worker,
            reviewer=lambda e, timeout: self.reviewer(e, timeout=timeout, fail=True))
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertEqual(result.state['candidates'], 3)
        self.assertEqual(result.state['calls'], 6)
        self.assertIn('三个候选', result.reason)
        self.assertIsNone(result.bundle)

    def test_four_audit_dispositions_and_persisted_budget(self):
        for disposition in ('rule_valid', 'validator_bug', 'rule_change_needed', 'insufficient_evidence'):
            with self.subTest(disposition=disposition):
                self.run_dir = Path(self.tmp.name) / disposition
                worker_calls, reviewer_calls = [], []
                def worker(request, *, timeout):
                    worker_calls.append(request)
                    return self.appeal(request) if len(worker_calls) == 2 else self.worker(request, timeout=timeout)
                def reviewer(envelope, *, timeout):
                    reviewer_calls.append(envelope)
                    return self.reviewer(envelope, timeout=timeout, fail=len(reviewer_calls) == 1)
                result = self.coordinator().run(worker, reviewer=reviewer, auditor=self.auditor(disposition))
                self.assertEqual(result.status, 'ready_to_apply' if disposition == 'rule_valid' else 'awaiting_human', result.reason)
                self.assertEqual(result.state['audit_attempts'], 1)
                self.assertEqual(len(result.state['seen_keys']), 1)
                self.assertEqual(result.state['calls'], 6 if disposition == 'rule_valid' else 4)
                persisted = json.loads((self.run_dir / 'state.json').read_text(encoding='utf-8'))
                self.assertEqual(persisted['calls'], result.state['calls'])
                self.assertEqual(persisted['seen_keys'], result.state['seen_keys'])

    def test_dispute_not_repeated_after_rule_valid(self):
        worker_count = []
        def worker(request, *, timeout):
            worker_count.append(request)
            if len(worker_count) in (2, 4):
                return self.appeal(request)
            return self.worker(request, timeout=timeout)
        result = self.coordinator().run(worker,
            reviewer=lambda e, timeout: self.reviewer(e, timeout=timeout, fail=True), auditor=self.auditor())
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertIn('一次规则争议', result.reason)
        self.assertEqual(result.state['audit_attempts'], 1)
        self.assertEqual(result.state['candidates'], 2)
        self.assertEqual(len(result.state['seen_keys']), 1)

    def test_environment_timeout_is_independently_bounded(self):
        entries = []
        def worker(request, *, timeout):
            entries.append('started')
            time.sleep(.15)
            entries.append('finished')
            return self.worker(request, timeout=timeout)
        started = time.monotonic()
        result = self.coordinator(call_timeout=.01).run(worker)
        self.assertLess(time.monotonic() - started, .14)
        self.assertEqual(entries, ['started'])
        self.assertEqual(result.state['calls'], 1)
        self.assertEqual(result.state['candidates'], 0)
        self.assertEqual(result.state['environment_errors'], 0)
        self.assertEqual(result.status, 'awaiting_human')
        time.sleep(.17)
        self.assertEqual(entries, ['started', 'finished'])
        self.assertIsNone(result.bundle)

    def test_environment_unknown_does_not_retry_or_spend_candidate(self):
        calls = []
        def worker(request, *, timeout):
            calls.append(1)
            raise OSError('临时不可用')
        result = self.coordinator().run(worker, reviewer=self.reviewer)
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.state['candidates'], 0)
        self.assertEqual(result.state['calls'], 1)
        self.assertEqual(result.state['environment_errors'], 0)

    def test_reviewer_environment_failure_has_global_bound(self):
        def reviewer(envelope, *, timeout):
            raise OSError('服务不可用')
        result = self.coordinator().run(self.worker, reviewer=reviewer)
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertEqual(result.state['calls'], 2)
        self.assertEqual(result.state['environment_errors'], 0)
        self.assertEqual(result.state['candidates'], 1)

    def test_call_budget_preserved_across_restart_and_audit(self):
        calls = []
        def worker(request, *, timeout):
            calls.append(1)
            return self.appeal(request) if len(calls) == 2 else self.worker(request, timeout=timeout)
        result = self.coordinator(max_calls=3).run(worker,
            reviewer=lambda e, timeout: self.reviewer(e, timeout=timeout, fail=True), auditor=self.auditor())
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertIn('budget_exhausted', result.reason)
        self.assertEqual(result.state['calls'], 3)
        restarted = self.coordinator(max_calls=3).run(self.worker, reviewer=self.reviewer)
        self.assertEqual(restarted.state['calls'], 3)
        self.assertEqual(restarted.state['deadline'], result.state['deadline'])
        with self.assertRaises(ContractError):
            self.coordinator(max_calls=30)

    def test_time_budget_and_restart_not_reset(self):
        coordinator = self.coordinator(max_seconds=.02)
        deadline = coordinator.state['deadline']
        time.sleep(.03)
        result = self.coordinator(max_seconds=.02).run(self.worker, reviewer=self.reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertEqual(result.state['calls'], 0)
        self.assertEqual(result.state['deadline'], deadline)

    def test_reserved_call_survives_interrupted_restart(self):
        coordinator = self.coordinator(max_calls=1)
        self.assertTrue(coordinator._reserve())  # 模拟扣费后进程退出，没有模型结果。
        result = self.coordinator(max_calls=1).run(self.worker, reviewer=self.reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertEqual(result.state['calls'], 1)
        self.assertEqual(result.state['deadline'], coordinator.state['deadline'])
        self.assertEqual(result.state['candidates'], 0)

    def test_successful_invocations_reconcile_original_steps_after_crash(self):
        class SimulatedCrash(BaseException):
            pass

        for kind in ('worker-round', 'review-round'):
            with self.subTest(kind=kind):
                self.run_dir = Path(self.tmp.name) / ('crash-' + kind)
                worker_calls, reviewer_calls = [], []

                def worker(request, *, timeout):
                    worker_calls.append(request)
                    return self.worker(request, timeout=timeout)

                def reviewer(envelope, *, timeout):
                    reviewer_calls.append(envelope)
                    return self.reviewer(envelope, timeout=timeout)

                coordinator = self.coordinator()
                original = coordinator.runtime.submit_step_result

                def interrupt(result, **kwargs):
                    if kind in kwargs['invocation_id']:
                        raise SimulatedCrash(kind)
                    return original(result, **kwargs)

                coordinator.runtime.submit_step_result = interrupt
                with self.assertRaises(SimulatedCrash):
                    coordinator.run(worker, reviewer=reviewer)
                coordinator.close()
                restarted = self.coordinator()
                self.addCleanup(restarted.close)
                result = restarted.run(worker, reviewer=reviewer)
                self.assertEqual(result.status, 'ready_to_apply', result.reason)
                self.assertEqual(result.state['candidates'], 1)
                self.assertEqual(result.state['calls'], 2)
                self.assertEqual(len(worker_calls), 1)
                self.assertEqual(len(reviewer_calls), 1)
                self.assertEqual(len(restarted.runtime.store.read('SELECT * FROM invocations')), 2)
                self.assertEqual(len(restarted.runtime.store.read('SELECT * FROM step_results')), 2)
                restarted.close()

    def test_partially_published_round_resumes_from_original_worker_result(self):
        class SimulatedCrash(BaseException):
            pass

        self.run_dir = Path(self.tmp.name) / 'partial-round'
        worker_calls, reviewer_calls = [], []

        def worker(request, *, timeout):
            worker_calls.append(request)
            return self.worker(request, timeout=timeout)

        def reviewer(envelope, *, timeout):
            reviewer_calls.append(envelope)
            return self.reviewer(envelope, timeout=timeout)

        coordinator = self.coordinator()
        original_write = Path.write_bytes
        manifest = self.run_dir / 'round-1/manifest.json'

        def interrupt(path, data):
            if path == manifest:
                raise SimulatedCrash('manifest not published')
            return original_write(path, data)

        with patch.object(Path, 'write_bytes', new=interrupt):
            with self.assertRaises(SimulatedCrash):
                coordinator.run(worker, reviewer=reviewer)
        coordinator.close()
        self.assertTrue((self.run_dir / 'round-1/candidate.json').exists())
        self.assertTrue((self.run_dir / 'round-1/payload/0.md').exists())
        self.assertFalse(manifest.exists())
        restarted = self.coordinator()
        self.addCleanup(restarted.close)
        result = restarted.run(worker, reviewer=reviewer)
        self.assertEqual(result.status, 'ready_to_apply', result.reason)
        self.assertEqual(result.state['candidates'], 1)
        self.assertEqual(result.state['calls'], 2)
        self.assertEqual(len(worker_calls), 1)
        self.assertEqual(len(reviewer_calls), 1)
        self.assertTrue(manifest.exists())
        self.assertTrue((self.run_dir / 'round-1/dependencies.json').exists())

    def test_unavailable_rule_auditor_stops_without_fake_model(self):
        calls = []
        def worker(request, *, timeout):
            calls.append(1)
            return self.appeal(request) if len(calls) == 2 else self.worker(request, timeout=timeout)
        auditor = RuleAuditor((self.root / 'AGENTS.md').read_bytes(), (BASE / 'rules.json').read_bytes(),
            validator_version='gates-1.0', review_prompt_version=PROMPT_VERSION)
        result = self.coordinator().run(worker,
            reviewer=lambda e, timeout: self.reviewer(e, timeout=timeout, fail=True), auditor=auditor)
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertIn('unavailable', result.reason)
        self.assertEqual(result.state['calls'], 3)

    def test_rule_version_change_during_review_invalidates_pass(self):
        def reviewer(envelope, *, timeout):
            opinion = self.reviewer(envelope, timeout=timeout)
            self.write('AGENTS.md', '# 已改变规则')
            return opinion
        result = self.coordinator().run(self.worker, reviewer=reviewer)
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertIn('规则版本变化', result.reason)
        self.assertIsNone(result.bundle)

    def test_dependency_change_during_review_invalidates_pass(self):
        def reviewer(envelope, *, timeout):
            opinion = self.reviewer(envelope, timeout=timeout)
            self.write(RAW, '原文已改变。')
            return opinion
        result = self.coordinator().run(self.worker, reviewer=reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertIsNone(result.bundle)

    def test_payload_change_during_review_invalidates_pass(self):
        def reviewer(envelope, *, timeout):
            opinion = self.reviewer(envelope, timeout=timeout)
            (self.run_dir / 'round-1/payload/0.md').write_bytes(b'changed')
            return opinion
        result = self.coordinator().run(self.worker, reviewer=reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertIsNone(result.bundle)

    def test_stale_review_report_is_not_a_credential(self):
        def reviewer(envelope, *, timeout):
            report = self.reviewer(envelope, timeout=timeout)
            report['candidate_digest'] = '0' * 64
            return report
        result = self.coordinator().run(self.worker, reviewer=reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertIn('无效', result.reason)

    def test_models_must_be_configured(self):
        self.assertIn('Worker', self.coordinator().run(None).reason)
        self.run_dir = Path(self.tmp.name) / 'no-review'
        result = self.coordinator().run(self.worker)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertIn('独立内容', result.reason)

    def test_semantic_write_cannot_skip_by_operation_flag(self):
        result = self.coordinator(operation_type='index_rebuild').run(self.worker)
        self.assertEqual(result.status, 'awaiting_human', result.reason)
        self.assertIn('独立内容', result.reason)

    def test_index_new_claim_and_link_alias_require_reviewer(self):
        for extra in ('所有场景都有效。', '[[synthesis/结论|所有场景都有效]]'):
            with self.subTest(extra=extra):
                self.run_dir = Path(self.tmp.name) / ('claim' if '|' not in extra else 'alias')
                def worker(request, *, timeout):
                    response = self.worker(request, timeout=timeout)
                    response['candidate']['changes'] = [c for c in response['candidate']['changes'] if c['path'] == 'wiki/index.md']
                    change = response['candidate']['changes'][0]
                    target = Path(response['payload_root']) / change['payload_path']
                    target.write_bytes(target.read_bytes() + extra.encode())
                    change['sha256'] = bytes_digest(target.read_bytes())
                    return response
                result = self.coordinator(operation_type='index_rebuild').run(worker)
                self.assertEqual(result.status, 'awaiting_human', result.reason)
                self.assertIn('独立内容', result.reason)

    def test_readonly_and_pure_index_need_no_reviewer(self):
        def readonly(request, *, timeout):
            return dict(candidate=dict(contract_version='1.0', operation_id='bounded-test', changes=[]),
                        payload_root=request['payload_root'])
        result = self.coordinator(operation_type='query').run(readonly)
        self.assertEqual(result.status, 'ready_to_apply', result.reason)
        self.assertIsNone(result.bundle['review'])
        self.run_dir = Path(self.tmp.name) / 'index'
        def index(request, *, timeout):
            response = self.worker(request, timeout=timeout)
            response['candidate']['changes'] = [c for c in response['candidate']['changes'] if c['path'] == 'wiki/index.md']
            return response
        result = self.coordinator(operation_type='index_rebuild').run(index)
        self.assertEqual(result.status, 'ready_to_apply', result.reason)

    def test_untrusted_payload_root_and_self_approval_rejected(self):
        def external(request, *, timeout):
            response = self.worker(request, timeout=timeout)
            response['payload_root'] = str(self.root)
            return response
        result = self.coordinator().run(external, reviewer=self.reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertEqual(result.state['candidates'], 0)
        self.run_dir = Path(self.tmp.name) / 'self-pass'
        def self_pass(request, *, timeout):
            return dict(self.worker(request, timeout=timeout), passed=True)
        result = self.coordinator().run(self_pass, reviewer=self.reviewer)
        self.assertEqual(result.status, 'awaiting_human')

    def test_pdf_partial_and_ocr_pause_before_worker(self):
        example = json.loads((BASE / 'examples/source_package.valid.json').read_text(encoding='utf-8'))
        for mode in ('pdf', 'partial', 'ocr'):
            with self.subTest(mode=mode):
                self.run_dir = Path(self.tmp.name) / mode
                package = copy.deepcopy(example)
                if mode == 'pdf':
                    package['input_type'] = 'pdf'
                elif mode == 'partial':
                    package['quality']['status'] = 'partial'
                else:
                    package['parser']['used_ocr'] = True
                result = self.coordinator(source_packages=[package]).run(self.worker, reviewer=self.reviewer)
                self.assertEqual(result.status, 'awaiting_human')
                self.assertEqual(result.state['calls'], 0)
        self.run_dir = Path(self.tmp.name) / 'pdf-as-md'
        self.write(RAW, '---\ninput_type: pdf\n---\n转换后的文字。\n')
        result = self.coordinator().run(self.worker, reviewer=self.reviewer)
        self.assertEqual(result.status, 'awaiting_human')
        self.assertEqual(result.state['calls'], 0)

    def test_explicit_execution_limits_required(self):
        for kwargs in (dict(max_calls=0), dict(call_timeout=float('inf')), dict(max_seconds=0), dict(environment_retries=-1)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.coordinator(**kwargs)


if __name__ == '__main__':
    unittest.main()
