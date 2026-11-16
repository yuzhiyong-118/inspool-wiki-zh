"""T07 仅使用内存夹具；ADR 分歧不改变真实规则或业务状态。"""
from copy import deepcopy
import json
from pathlib import Path
import threading
import unittest

from tools.wiki_runtime.contracts import bytes_digest, validate
from tools.wiki_runtime.rule_audit import RuleAuditor, AuditError, SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / 'tools/wiki_runtime/contracts'


class RuleAuditTests(unittest.TestCase):
    def setUp(self):
        self.rules = (ROOT / 'AGENTS.md').read_bytes()
        self.mapping = (CONTRACTS / 'rules.json').read_bytes()
        self.manifest = json.loads((CONTRACTS / 'examples/manifest.valid.json').read_text('utf-8'))
        self.manifest.update(rules_digest=bytes_digest(self.rules), mapping_digest=bytes_digest(self.mapping))
        self.appeal = json.loads((CONTRACTS / 'examples/appeal_report.valid.json').read_text('utf-8'))
        for key in ('operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
                    'mapping_digest', 'validator_version', 'review_prompt_version'):
            self.appeal[key] = self.manifest[key]
        self.appeal.update(rule_ids=['STATE-001'], failure_refs=['reports/adr-timing.json'],
                           evidence='AGENTS 允许 pending_review 前记录 processed_into；ADR0001 则限制到 processed。',
                           goal_conflict='检查器按 ADR 拒绝完整 ingest 映射。',
                           minimal_counterexample='pending_review raw，正文未改，processed_into 指向已建来源页。')
        self.trace = {key: self.appeal[key] for key in ('contract_version', 'operation_id',
                      'candidate_digest', 'dependencies_digest', 'rules_digest', 'mapping_digest',
                      'validator_version', 'review_prompt_version')}
        self.trace.update(gate='G2', result='fail', producer='trusted-test-runner', findings=[{
            'rule_id': 'STATE-001', 'severity': 'blocking', 'category': 'adr-timing',
            'target': 'raw/unprocessed/example.md', 'evidence': 'processed_into 在 pending_review 已存在',
            'expected': '只在 processed 存在', 'repairable': False}])
        self.failures = {'reports/adr-timing.json': self.trace}
        self.seen = set()
        self.calls = 0
        self.reserves = 0

    def reserve(self):
        self.reserves += 1
        return True

    def model(self, request, *, timeout):
        self.calls += 1
        self.assertGreater(timeout, 0)
        self.assertEqual(request['system'], SYSTEM_PROMPT)
        result = deepcopy(request['appeal'])
        result.update(disposition='validator_bug', proposal='以 AGENTS 为准，先补失败测试再修检查器。',
                      impact='保留 ADR 分歧；检查器新版本重新检验。')
        return result

    def auditor(self, transport='default'):
        return RuleAuditor(self.rules, self.mapping,
                           validator_version=self.manifest['validator_version'],
                           review_prompt_version=self.manifest['review_prompt_version'],
                           transport=self.model if transport == 'default' else transport)

    def run_audit(self, auditor=None, **kwargs):
        return (auditor or self.auditor()).audit(self.manifest, self.appeal, self.failures,
                                              seen_keys=self.seen, reserve_call=self.reserve, **kwargs)

    def test_adr_dispute_recommends_verifier_fix_without_changes(self):
        before = (ROOT / 'wiki/meta/adr/0001-state-storage.md').read_bytes()
        appeal = deepcopy(self.appeal)
        result = self.run_audit(evidence_documents={'ADR0001': before.decode('utf-8')})
        self.assertEqual(result.status, 'reviewed')
        self.assertEqual(result.report['disposition'], 'validator_bug')
        validate('appeal_report', result.report)
        self.assertTrue(result.requires_revalidation)
        self.assertFalse(result.requires_user_approval)
        self.assertEqual(self.appeal, appeal)
        self.assertEqual(before, (ROOT / 'wiki/meta/adr/0001-state-storage.md').read_bytes())
        self.assertEqual(self.rules, (ROOT / 'AGENTS.md').read_bytes())

    def test_four_dispositions_are_advice_only(self):
        for disposition in ('rule_valid', 'validator_bug', 'rule_change_needed', 'insufficient_evidence'):
            with self.subTest(disposition=disposition):
                self.seen.clear()
                def model(request, *, timeout):
                    report = self.model(request, timeout=timeout)
                    report['disposition'] = disposition
                    return report
                result = self.run_audit(self.auditor(model))
                self.assertEqual(result.report['disposition'], disposition)
                self.assertNotIn('approved', result.report)
                self.assertEqual(result.requires_revalidation, disposition in ('validator_bug', 'rule_change_needed'))
                self.assertEqual(result.requires_user_approval, disposition == 'rule_change_needed')
                if disposition == 'rule_change_needed':
                    self.assertIn('待用户决定', result.proposal_text)
                    self.assertIn('迁移计划', result.proposal_text)
                    self.assertIn('未回复不算批准', result.proposal_text)

    def test_missing_fields_whitespace_and_unknown_rules_rejected(self):
        original = deepcopy(self.appeal)
        for field in ('rule_ids', 'failure_refs', 'minimal_counterexample', 'evidence', 'goal_conflict'):
            self.appeal = deepcopy(original)
            del self.appeal[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_audit()
        self.appeal = deepcopy(original)
        self.appeal['evidence'] = ' \n '
        with self.assertRaises(AuditError):
            self.run_audit()
        self.appeal = deepcopy(original)
        self.appeal['rule_ids'] = ['MADE-UP-001']
        with self.assertRaises(AuditError):
            self.run_audit()
        self.assertEqual(self.calls, 0)

    def test_rule_must_exist_in_actual_blocking_failure(self):
        for update in ({'result': 'pass'}, {'findings': []}, {'candidate_digest': '1' * 64}):
            original = deepcopy(self.trace)
            self.trace.update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                self.run_audit()
            self.trace.clear()
            self.trace.update(original)
        self.failures.clear()
        with self.assertRaises(AuditError):
            self.run_audit()

    def test_all_manifest_bindings_invalidate_old_appeal(self):
        original = deepcopy(self.manifest)
        for field in ('operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
                      'mapping_digest', 'validator_version', 'review_prompt_version'):
            self.manifest = deepcopy(original)
            self.manifest[field] = '1' * 64 if field.endswith('digest') else 'changed'
            with self.subTest(field=field), self.assertRaises(AuditError):
                self.run_audit()

    def test_coordinated_binding_change_cannot_override_fixed_rules(self):
        self.manifest['rules_digest'] = self.appeal['rules_digest'] = '1' * 64
        self.trace['rules_digest'] = '1' * 64
        with self.assertRaises(AuditError):
            self.run_audit()

    def test_duplicates_do_not_consume_new_budget_even_after_proposal_changes(self):
        self.run_audit()
        self.appeal['proposal'] = '另一措辞不是新证据'
        result = self.run_audit()
        self.assertEqual(result.status, 'duplicate')
        self.assertEqual((self.calls, self.reserves), (1, 1))
        self.appeal['minimal_counterexample'] += '新增独立反例'
        self.assertEqual(self.run_audit().status, 'reviewed')
        self.assertEqual((self.calls, self.reserves), (2, 2))

    def test_shared_budget_denial_never_calls_transport(self):
        result = self.auditor().audit(self.manifest, self.appeal, self.failures,
                                     seen_keys=self.seen, reserve_call=lambda: False)
        self.assertEqual(result.status, 'budget_exhausted')
        self.assertEqual(self.calls, 0)
        self.assertFalse(self.seen)

    def test_absent_model_fails_closed(self):
        self.assertEqual(self.run_audit(self.auditor(None)).status, 'unavailable')
        self.assertEqual(self.reserves, 0)

    def test_transport_failure_consumes_attempt_and_is_not_approval(self):
        def broken(request, *, timeout):
            raise RuntimeError('service unavailable')
        result = self.run_audit(self.auditor(broken))
        self.assertEqual(result.status, 'error')
        self.assertIsNone(result.report)
        self.assertEqual(self.reserves, 1)
        self.assertEqual(self.run_audit().status, 'duplicate')

    def test_malformed_or_tampered_response_fails_closed(self):
        for field, value in (('candidate_digest', '1' * 64), ('rule_ids', ['RAW-001']),
                             ('disposition', 'submitted'), ('approved', True)):
            self.seen.clear()
            def tamper(request, *, timeout):
                report = self.model(request, timeout=timeout)
                report[field] = value
                return report
            with self.subTest(field=field):
                result = self.run_audit(self.auditor(tamper))
                self.assertEqual(result.status, 'error')
                self.assertIsNone(result.report)

    def test_timeout_is_bounded_and_late_response_not_consumed(self):
        release = threading.Event()
        finished = threading.Event()
        def slow(request, *, timeout):
            release.wait(1)
            finished.set()
            return self.model(request, timeout=timeout)
        try:
            result = self.run_audit(self.auditor(slow), timeout=0.01)
            self.assertEqual(result.status, 'error')
            self.assertIsNone(result.report)
            self.assertEqual(self.reserves, 1)
        finally:
            release.set()
            finished.wait(1)
        self.assertEqual(self.run_audit().status, 'duplicate')

    def test_invalid_timeout_rejected_before_model(self):
        for timeout in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(timeout=timeout), self.assertRaises(AuditError):
                self.run_audit(timeout=timeout)
        self.assertEqual(self.calls, 0)


if __name__ == '__main__':
    unittest.main()
