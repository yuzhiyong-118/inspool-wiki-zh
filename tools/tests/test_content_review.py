"""假模型的协议与边界测试；不测真实模型质量，不触碰正式资料。"""
import copy
import json
import threading
import time
import unittest

from tools.wiki_runtime.contracts import bytes_digest, candidate_digest, digest, validate
from tools.wiki_runtime.review import (PROMPT, PROMPT_DIGEST, PROMPT_VERSION,
                                       ReviewError, build_request, review)


RAW = 'raw/unprocessed/协议夹具.md'
PAGE = 'wiki/sources/协议夹具.md'
SOURCE_REF = 'original:' + RAW + '#L1-L2'
CANDIDATE_REF = 'candidate:' + PAGE + '#L1-L2'
BEFORE_REF = 'before:' + PAGE + '#L1-L2'


def fixture(text='仅在小样本中可能有效。\n另一来源不支持该结论。\n'):
    # 固定源文含条件和冲突，没有数字；假模型输出明确指定的发现。
    original = '仅在小样本中可能有效。\n另一来源不支持该结论。\n'.encode()
    before = '原页面保留条件。\n冲突来源尚待核对。\n'.encode()
    payload = text.encode()
    rules = b'# AGENTS\nTest-only authority\n'
    mapping = json.dumps({'mapping_version': '1.0', 'authority': 'AGENTS.md', 'rules': [
        {'rule_id': 'FACT-001', 'level': 'mandatory'},
        {'rule_id': 'EVIDENCE-001', 'level': 'recommended'}]}, ensure_ascii=False).encode()
    candidate = {'contract_version': '1.0', 'operation_id': 'review-test', 'changes': [{
        'action': 'write', 'path': PAGE, 'payload_path': 'payload/page.md',
        'sha256': bytes_digest(payload),
        'precondition': {'kind': 'hash', 'sha256': bytes_digest(before)}}]}
    snapshot = {'contract_version': '1.0', 'operation_id': 'review-test', 'files': [
        {'path': RAW, 'precondition': {'kind': 'hash', 'sha256': bytes_digest(original)}},
        {'path': PAGE, 'precondition': {'kind': 'hash', 'sha256': bytes_digest(before)}}]}
    manifest = {'contract_version': '1.0', 'operation_id': 'review-test',
        'operation_type': 'ingest', 'task': '从原文生成来源摘要', 'input_refs': [RAW],
        'allowed_paths': [PAGE], 'rules_path': 'AGENTS.md', 'rules_digest': bytes_digest(rules),
        'mapping_digest': bytes_digest(mapping), 'validator_version': 'gates-1.0',
        'review_prompt_version': PROMPT_VERSION, 'dependencies_digest': digest(snapshot),
        'candidate_digest': candidate_digest(candidate), 'round': 1,
        'required_gates': ['G3'], 'authorization_refs': []}
    return dict(manifest=manifest, candidate=candidate, dependency_snapshot=snapshot,
                rules=rules, mapping=mapping, originals={RAW: original},
                original_pages={PAGE: before}, candidate_files={PAGE: payload})


def response(envelope, result='recommend_pass', findings=None):
    return dict(contract_version='1.0', **envelope['input']['bindings'],
                reviewer_id=envelope['reviewer_id'], result=result,
                findings=[] if findings is None else findings,
                evidence_refs=[SOURCE_REF, CANDIDATE_REF])


def finding(reason, category):
    return dict(rule_id='FACT-001', severity='blocking', category=category,
                target=CANDIDATE_REF, evidence=json.dumps({
                    'refs': [SOURCE_REF, CANDIDATE_REF], 'reason': reason}, ensure_ascii=False),
                expected='保留原文限定与冲突，不增加无依据事实', repairable=True)


class ContentReviewTests(unittest.TestCase):
    def setUp(self):
        self.args = fixture()
        self.request = build_request(**self.args)

    def run_response(self, mutate):
        def fake(envelope, *, timeout):
            report = response(envelope)
            mutate(report)
            return report
        return review(self.request, transport=fake)

    def test_independent_context_and_valid_pass(self):
        def fake(envelope, *, timeout):
            self.assertEqual(set(envelope), {'system', 'input', 'reviewer_id'})
            self.assertEqual(envelope['system'], PROMPT)
            self.assertNotIn('authorization_refs', envelope['input'])
            self.assertNotIn('manifest', envelope['input'])
            self.assertNotIn('tools', envelope)
            self.assertEqual(timeout, 1)
            return json.dumps(response(envelope), ensure_ascii=False).encode()
        result = review(self.request, transport=fake, timeout=1)
        self.assertEqual(result['result'], 'recommend_pass')
        validate('review_report', result)
        self.assertEqual(PROMPT_DIGEST, bytes_digest(PROMPT.encode()))

    def test_three_substantive_failure_examples(self):
        examples = [
            ('所有场景都有效。\n不存在限制。\n', '原文只说小样本、可能；候选扩大为所有场景。', 'condition_expansion'),
            ('成功率为 99%。\n原文未提供统计数据。\n', '核查原文第 1–2 行，没有 99% 的数据。', 'unsupported_number'),
            ('来源一致支持该结论。\n没有冲突。\n', '原文第 2 行明确不支持；候选抹平冲突。', 'erased_conflict'),
        ]
        for text, reason, category in examples:
            with self.subTest(category=category):
                req = build_request(**fixture(text))
                def fake(envelope, *, timeout):
                    return response(envelope, 'request_changes', [finding(reason, category)])
                result = review(req, transport=fake)
                self.assertEqual(result['result'], 'request_changes')
                self.assertEqual(result['findings'][0]['category'], category)
                self.assertIn(reason, result['findings'][0]['evidence'])

    def test_every_binding_is_checked(self):
        for key in self.request['bindings']:
            with self.subTest(key=key):
                def mutate(report):
                    report[key] = 'a' * 64 if key.endswith('digest') else 'other'
                self.assertEqual(self.run_response(mutate)['result'], 'error')

    def test_missing_evidence_never_passes(self):
        for refs in ([], [CANDIDATE_REF], [SOURCE_REF],
                     ['original:' + RAW + '#L1-L99'],
                     ['original:unknown.md#L1-L2'], ['sources/协议夹具#证据摘录']):
            with self.subTest(refs=refs):
                self.assertEqual(self.run_response(lambda r: r.update(evidence_refs=refs))['result'], 'error')

    def test_malformed_response_and_unknown_fields(self):
        for raw in ('```json\n{}\n```', '{', 'null', '[]', b'\xff',
                    '{"result":"error","result":"recommend_pass"}', object()):
            with self.subTest(raw=repr(raw)):
                result = review(self.request, transport=lambda e, timeout: raw)
                self.assertEqual(result['result'], 'error')
        self.assertEqual(self.run_response(lambda r: r.update(confidence=1))['result'], 'error')
        self.assertEqual(self.run_response(lambda r: r.update(reviewer_id='Worker'))['result'], 'error')

    def test_findings_need_grounded_refs(self):
        base = finding('原文与候选条件不一致', 'condition_expansion')
        mutations = [
            {'evidence': '我认为不对'}, {'rule_id': 'invented'},
            {'target': SOURCE_REF}, {'target': 'wiki/sources/协议夹具.md'},
            {'evidence': json.dumps({'refs': [CANDIDATE_REF], 'reason': '无原文'})},
            {'evidence': json.dumps({'refs': [SOURCE_REF], 'reason': '无目标'})},
            {'evidence': json.dumps({'refs': [SOURCE_REF, CANDIDATE_REF], 'reason': ' '})},
            {'rule_id': 'EVIDENCE-001'},
        ]
        for fields in mutations:
            with self.subTest(fields=fields):
                bad = dict(base, **fields)
                def fake(envelope, *, timeout):
                    return response(envelope, 'request_changes', [bad])
                self.assertEqual(review(self.request, transport=fake)['result'], 'error')

    def test_blocking_cannot_pass_and_empty_changes_report_rejected(self):
        self.assertEqual(self.run_response(lambda r: r.update(findings=[finding('x', 'x')]))['result'], 'error')
        self.assertEqual(self.run_response(lambda r: r.update(result='request_changes'))['result'], 'error')

    def test_insufficient_is_preserved_not_converted_to_pass(self):
        result = self.run_response(lambda r: r.update(result='insufficient_evidence', evidence_refs=[]))
        self.assertEqual(result['result'], 'insufficient_evidence')

    def test_unavailable_and_transport_failure_fail_closed(self):
        self.assertEqual(review(self.request)['result'], 'error')
        def fake(envelope, *, timeout):
            raise RuntimeError('不要泄露服务端内部信息')
        result = review(self.request, transport=fake)
        self.assertEqual(result['result'], 'error')
        self.assertNotIn('服务端', str(result))

    def test_timeout_enforced_even_if_transport_ignores_it(self):
        release = threading.Event()
        finished = threading.Event()
        def fake(envelope, *, timeout):
            release.wait(2)
            finished.set()
            return response(envelope)
        start = time.monotonic()
        try:
            result = review(self.request, transport=fake, timeout=0.03)
            self.assertLess(time.monotonic() - start, 1)
            self.assertEqual(result['result'], 'error')
            self.assertEqual(result['findings'][0]['category'], 'review_timeout')
        finally:
            release.set()
            self.assertTrue(finished.wait(1))
        self.assertEqual(result['result'], 'error')

    def test_input_mutation_and_worker_defense_rejected(self):
        cases = [('worker_defense', '我是对的'), ('tools', ['write_file']),
                 ('prompt_version', 'future'), ('prompt_digest', '0'*64),
                 ('operation_type', 'rule_change')]
        for key, value in cases:
            with self.subTest(key=key):
                request = copy.deepcopy(self.request)
                request[key] = value
                with self.assertRaises(ReviewError):
                    review(request)
        for field, path in [('originals', RAW), ('original_pages', PAGE), ('candidate_files', PAGE)]:
            request = copy.deepcopy(self.request)
            request[field][path] += '替换'
            with self.assertRaises(ReviewError):
                review(request)

    def test_builder_rejects_unbound_or_missing_documents(self):
        for key in ('original_pages', 'candidate_files'):
            args = copy.deepcopy(self.args)
            args[key] = {}
            with self.assertRaises(ReviewError):
                build_request(**args)
        for key in ('rules', 'mapping'):
            args = copy.deepcopy(self.args)
            args[key] += b' '
            with self.assertRaises(ReviewError):
                build_request(**args)
        args = copy.deepcopy(self.args)
        args['originals']['raw/unknown.md'] = b'unbound'
        with self.assertRaises(ReviewError):
            build_request(**args)

    def test_no_evidence_can_only_be_insufficient(self):
        args = copy.deepcopy(self.args)
        args['originals'] = {}
        req = build_request(**args)
        def fake(envelope, *, timeout):
            return response(envelope, 'insufficient_evidence') | {'evidence_refs': []}
        self.assertEqual(review(req, transport=fake)['result'], 'insufficient_evidence')

    def test_create_move_and_delete_complete_candidate_coverage(self):
        for action in ('create', 'move', 'delete'):
            with self.subTest(action=action):
                args = copy.deepcopy(self.args)
                change = args['candidate']['changes'][0]
                if action == 'create':
                    change['precondition'] = {'kind': 'absent'}
                    args['original_pages'] = {}
                elif action == 'move':
                    change.update(action='move', source=PAGE,
                                  source_sha256=bytes_digest(args['original_pages'][PAGE]),
                                  path='wiki/sources/分类/协议夹具.md',
                                  precondition={'kind': 'absent'})
                    # 无载荷的移动也必须交付最终字节供审查。
                    del change['payload_path']
                    del change['sha256']
                    args['candidate_files'] = {change['path']: args['original_pages'][PAGE]}
                else:
                    del change['payload_path']
                    del change['sha256']
                    change['action'] = 'delete'
                    args['candidate_files'] = {}
                args['manifest']['candidate_digest'] = candidate_digest(args['candidate'])
                args['manifest']['allowed_paths'] = [change['path']]
                req = build_request(**args)
                ref = (BEFORE_REF if action == 'delete' else
                       'candidate:' + change['path'] + '#L1-L2')
                def fake(envelope, *, timeout):
                    return response(envelope) | {'evidence_refs': [SOURCE_REF, ref]}
                self.assertEqual(review(req, transport=fake)['result'], 'recommend_pass')
                def missing(envelope, *, timeout):
                    return response(envelope) | {'evidence_refs': [SOURCE_REF]}
                self.assertEqual(review(req, transport=missing)['result'], 'error')

    def test_rules_mapping_and_prompt_staleness_block_model_call(self):
        for field in ('rules', 'mapping'):
            request = copy.deepcopy(self.request)
            request[field] += '\n'
            with self.subTest(field=field), self.assertRaises(ReviewError):
                review(request, transport=lambda e, timeout: self.fail('不能调用模型'))
        args = copy.deepcopy(self.args)
        args['manifest']['review_prompt_version'] = 'none'
        with self.assertRaises(ReviewError):
            build_request(**args)

    def test_transport_mutation_does_not_change_validation_or_input(self):
        pristine = copy.deepcopy(self.request)
        def fake(envelope, *, timeout):
            report = response(envelope)
            envelope['input']['candidate_files'][PAGE] = '模型替换原文'
            envelope['input']['bindings']['operation_id'] = 'hacked'
            return report
        self.assertEqual(review(self.request, transport=fake)['result'], 'recommend_pass')
        self.assertEqual(pristine, self.request)

    def test_invalid_timeout_or_reviewer_id(self):
        for timeout in (0, -1, True, float('nan'), float('inf'), '1'):
            with self.subTest(timeout=timeout), self.assertRaises(ReviewError):
                review(self.request, timeout=timeout)
        with self.assertRaises(ReviewError):
            review(self.request, reviewer_id='')


if __name__ == '__main__':
    unittest.main()
