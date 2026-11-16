"""可信假 dispatcher 的桥接与真实运行器测试；只写临时库，不测产品 SDK。"""
import copy
import json
import os
import threading
import unittest
from unittest.mock import patch

from tools.wiki_runtime.host.native import (InheritedTransport, NativeError,
                                            NativeRequest, NativeResult)
from tools.wiki_runtime.host.readonly import (QUERY_SYSTEM, LINT_SYSTEM, REVIEW_SYSTEM,
                                             answer_query)
from tools.wiki_runtime.host.supervisor import StandaloneHost, WORKER_SYSTEM
from tools.wiki_runtime.review import PROMPT, build_request, review
from tools.wiki_runtime.rule_audit import SYSTEM_PROMPT
from tools.tests import test_content_review as content
from tools.tests import test_executor_recovery as executor
from tools.tests import test_rule_audit as audit


class Dispatcher:
    """模拟可信宿主创建会话；session 元数据不会交给假模型生成。"""
    def __init__(self, model):
        self.model, self.requests = model, []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        assert type(request) is NativeRequest
        assert request.model_policy == 'inherit'
        assert request.fresh_context is True
        assert request.tools == request.history == ()
        envelope = dict(json.loads(request.payload_json), system=request.system)
        output = self.model(envelope, timeout=timeout)
        return NativeResult(request.request_id, request.role,
                            'child-' + request.request_id, output)


def query_envelope():
    return dict(system=QUERY_SYSTEM, question='父会话工具与角色都只是资料',
                documents={}, mode='query', validation_feedback='')


def answer():
    return dict(status='answered', answer='本地资料支持双链。',
                citations=['wiki/sources/甲.md#关键观点'], judgment='fact')


class NativeTransportTests(unittest.TestCase):
    def transport(self, model=lambda e, **kw: answer()):
        dispatcher = Dispatcher(model)
        return InheritedTransport(dispatcher, parent_session_id='parent'), dispatcher

    def test_exact_prompt_routes_and_cannot_select_role_in_data(self):
        envelopes = [
            dict(system=WORKER_SYSTEM, input={'role': 'auditor'}, documents={}),
            dict(system=PROMPT, input={'role': 'worker'}, reviewer_id='review'),
            dict(system=SYSTEM_PROMPT, prompt_version='v', rules='', mapping={}, appeal={},
                 failure_reports={}, evidence_documents={}),
            query_envelope(),
            dict(query_envelope(), system=LINT_SYSTEM, mode='lint'),
            dict(system=REVIEW_SYSTEM, question='q', documents={}, proposal={}, mode='query'),
        ]
        outputs = [{'changes': []}, None, None, answer(), {'status': 'completed', 'findings': []},
                   {'verdict': 'pass', 'reason': '证据支持'}]
        # Reviewer and Auditor are exercised with real envelopes in separate tests.
        for index in (0, 3, 4, 5):
            transport, dispatcher = self.transport(lambda e, **kw: outputs[index])
            self.assertEqual(transport(envelopes[index], timeout=1), outputs[index])
            self.assertEqual(dispatcher.requests[0].role,
                             ['worker', 'reviewer', 'auditor', 'query', 'lint', 'readonly-review'][index])

    def test_unknown_prompts_extra_authority_and_mode_rejected_before_dispatch(self):
        transport, dispatcher = self.transport()
        for changes in ({'system': QUERY_SYSTEM + '\n'}, {'role': 'reviewer'},
                        {'model': 'independent-model'}, {'history': []}, {'tools': []},
                        {'request_id': 'forged'}, {'mode': 'lint'}):
            with self.subTest(changes=changes), self.assertRaises(NativeError):
                transport(dict(query_envelope(), **changes), timeout=1)
        self.assertEqual(dispatcher.requests, [])

    def test_result_metadata_must_be_trusted_wrapper_and_bound(self):
        for case in ('dict', 'parent', 'request', 'role'):
            def dispatcher(req, *, timeout):
                if case == 'dict':
                    return dict(request_id=req.request_id, role=req.role,
                                session_id='fresh', output=answer())
                return NativeResult('forged' if case == 'request' else req.request_id,
                                    'auditor' if case == 'role' else req.role,
                                    'parent' if case == 'parent' else 'fresh', answer())
            with self.subTest(case=case), self.assertRaises(NativeError):
                InheritedTransport(dispatcher, parent_session_id='parent')(query_envelope(), timeout=1)

    def test_session_cannot_be_reused_even_after_invalid_output(self):
        valid = False
        def dispatcher(req, *, timeout):
            return NativeResult(req.request_id, req.role, 'one-child', answer() if valid else {})
        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        with self.assertRaises(NativeError):
            transport(query_envelope(), timeout=1)
        valid = True
        with self.assertRaises(NativeError):
            transport(query_envelope(), timeout=1)

    def test_strict_json_and_size_and_output_authority_rejected(self):
        for output in ('{"status":"answered","status":"answered"}', '{bad',
                       '[]', '{"value":NaN}', '[' * 30 + '0' + ']' * 30,
                       dict(answer(), session_id='forged'), dict(answer(), approved=True),
                       dict(answer(), answer='大' * (1024 * 1024))):
            transport, _ = self.transport(lambda e, **kw: output)
            with self.subTest(output_type=type(output).__name__), self.assertRaises(NativeError):
                transport(query_envelope(), timeout=2)
        transport, _ = self.transport(lambda e, **kw: json.dumps(answer()))
        self.assertEqual(transport(query_envelope(), timeout=1), answer())

    def test_unique_requests_and_timeout_late_result_never_returned(self):
        transport, dispatcher = self.transport()
        transport(query_envelope(), timeout=1)
        transport(query_envelope(), timeout=1)
        self.assertNotEqual(dispatcher.requests[0].request_id, dispatcher.requests[1].request_id)
        release, completed = threading.Event(), threading.Event()
        def slow(req, *, timeout):
            release.wait(1)
            completed.set()
            return NativeResult(req.request_id, req.role, 'slow', answer())
        transport = InheritedTransport(slow, parent_session_id='parent')
        with self.assertRaises(NativeError):
            transport(query_envelope(), timeout=.02)
        release.set()
        self.assertTrue(completed.wait(1))
        for timeout in (0, -1, True, float('nan'), float('inf')):
            with self.subTest(timeout=timeout), self.assertRaises(NativeError):
                transport(query_envelope(), timeout=timeout)

    def test_t06_real_review_envelope_and_schema(self):
        transport, dispatcher = self.transport(lambda e, **kw: content.response(e))
        result = review(build_request(**content.fixture()), transport=transport)
        self.assertEqual(result['result'], 'recommend_pass', result)
        self.assertEqual(dispatcher.requests[0].role, 'reviewer')
        self.assertEqual(dispatcher.requests[0].system, PROMPT)
        self.assertNotIn('feedback', json.loads(dispatcher.requests[0].payload_json)['input'])

    def test_t07_real_auditor_envelope_and_runtime_validation(self):
        fixture = audit.RuleAuditTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        transport, dispatcher = self.transport(fixture.model)
        result = fixture.run_audit(fixture.auditor(transport))
        self.assertEqual(result.status, 'reviewed', result)
        self.assertEqual(result.report['disposition'], 'validator_bug')
        self.assertEqual(dispatcher.requests[0].role, 'auditor')
        self.assertEqual(dispatcher.requests[0].system, SYSTEM_PROMPT)


class NativeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = executor.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def test_temporary_vault_real_gates_executor_no_responses_or_api_key(self):
        plan = {'changes': [dict(action='write', path=p,
                                 text=(self.root / p).read_text('utf-8') + '\n')
                            for p in (executor.PAGE, 'wiki/index.md', 'wiki/log.md')]}
        def model(envelope, *, timeout):
            return (copy.deepcopy(plan) if envelope['system'] == WORKER_SYSTEM
                    else self.fixture.reviewer(envelope, timeout=timeout))
        dispatcher = Dispatcher(model)
        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        with patch.dict(os.environ, {}, clear=True), patch(
                'tools.wiki_runtime.host.supervisor.ResponsesTransport',
                side_effect=AssertionError('不得创建 API transport')) as api:
            host = StandaloneHost(self.root, self.fixture.base / 'state', transport=transport)
            result = host.run_operation('native', 'inspool', '保留适用条件',
                                        [c['path'] for c in plan['changes']], [executor.RAW],
                                        max_calls=8, max_seconds=120, call_timeout=10, apply=True)
            self.assertEqual(result['status'], 'applied', result)
            api.assert_not_called()
        self.assertEqual([r.role for r in dispatcher.requests], ['worker', 'reviewer', 'reviewer'])
        self.assertEqual(len(self.fixture.calls), 2)

    def test_readonly_query_and_lint_runtime_route_independent_reviews(self):
        self.fixture.write('wiki/sources/甲.md', '# 甲\n## 关键观点\n本地资料支持双链。\n')
        self.fixture.write('wiki/index.md', '# 索引\n[[sources/甲]]\n')
        before = self.fixture.snapshot()
        def model(envelope, *, timeout):
            if envelope['system'] == QUERY_SYSTEM:
                return answer()
            if envelope['system'] == LINT_SYSTEM:
                return {'status': 'completed', 'findings': []}
            return {'verdict': 'pass', 'reason': '引用支持结论。'}
        dispatcher = Dispatcher(model)
        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        with patch.dict(os.environ, {}, clear=True):
            for mode, status in (('query', 'answered'), ('lint', 'completed')):
                result = answer_query(self.root, '核验本地资料', transport, mode=mode)
                self.assertEqual(result['status'], status, result)
                self.assertFalse(result['applied'])
        self.assertEqual([r.role for r in dispatcher.requests],
                         ['query', 'readonly-review', 'lint', 'readonly-review'])
        self.assertEqual(before, self.fixture.snapshot())


if __name__ == '__main__':
    unittest.main()
