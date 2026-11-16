"""无 API 配置的通用宿主门面；模型调度替身不代表产品权限验收。"""
import json
import unittest
from unittest.mock import patch

from tools.tests import test_readonly_host as fixtures
from tools.wiki_runtime.host.agent import AgentSession
from tools.wiki_runtime.host.native import NativeResult
from tools.wiki_runtime.host.supervisor import HostError


class AgentSessionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReadonlyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.requests = []
        self.outputs = []

    def dispatch(self, request, *, timeout):
        self.requests.append(request)
        return NativeResult(request.request_id, request.role,
                            'child-' + request.request_id, self.outputs.pop(0))

    def session(self, **options):
        return AgentSession(self.fixture.root, self.dispatch,
                            parent_session_id='parent-session', **options)

    def test_query_without_api_or_private_state(self):
        state = self.fixture.root.parent / (self.fixture.root.name + '-unused')
        before = self.fixture.snapshot()
        self.outputs = [fixtures.answer(), fixtures.PASS]
        with patch.dict('os.environ', {}, clear=True), patch(
                'tools.wiki_runtime.host.supervisor.ResponsesTransport',
                side_effect=AssertionError('API must not be created')):
            session = self.session(state_dir=state)
            result = session.query('甲支持什么？')
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([r.role for r in self.requests], ['query', 'readonly-review'])
        self.assertTrue(all(r.model_policy == 'inherit' for r in self.requests))
        self.assertIsNone(session._maintenance)
        self.assertFalse(state.exists())
        self.assertEqual(self.fixture.snapshot(), before)

    def test_lint_is_separate_readonly_role(self):
        self.outputs = [{'status': 'completed', 'findings': []}, fixtures.PASS]
        before = self.fixture.snapshot()
        result = self.session().lint()
        self.assertEqual(result['status'], 'completed', result)
        self.assertFalse(result['applied'])
        self.assertEqual([r.role for r in self.requests], ['lint', 'readonly-review'])
        self.assertEqual(self.fixture.snapshot(), before)

    def test_independent_review_does_not_inherit_generation_feedback(self):
        self.outputs = [fixtures.answer(), fixtures.PASS]
        self.session().query('甲支持什么？')
        generation = json.loads(self.requests[0].payload_json)
        review = json.loads(self.requests[1].payload_json)
        self.assertIn('validation_feedback', generation)
        self.assertNotIn('validation_feedback', review)
        self.assertTrue(all(r.tools == r.history == () for r in self.requests))

    def test_no_state_dir_cannot_create_maintenance_runner(self):
        session = self.session()
        before = self.fixture.snapshot()
        with self.assertRaisesRegex(HostError, 'state_dir'):
            session.maintenance
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.requests, [])

    def test_query_cannot_switch_role_or_transport(self):
        for method in (self.session().query, self.session().lint):
            for option in ({'mode': 'lint'}, {'transport': self.dispatch}):
                with self.subTest(option=tuple(option)), self.assertRaises(HostError):
                    method('问题', **option)
        self.assertEqual(self.requests, [])
