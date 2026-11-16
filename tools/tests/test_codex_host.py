"""Codex 协议替身与真实本地子进程测试；不调用模型、不读取登录凭据。"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

from tools.wiki_runtime.host.codex import (CodexDispatcher, CodexDraft, CodexError,
                                          JsonRpcClient)
from tools.wiki_runtime.host.native import (InheritedTransport, NativeError,
                                           NativeRequest, NativeResult, _ROUTES)
from tools.wiki_runtime.host.readonly import QUERY_SYSTEM


def request():
    return NativeRequest('req', 'query', QUERY_SYSTEM, json.dumps({
        'question': '问题', 'documents': {}, 'mode': 'query', 'validation_feedback': ''}))


def output():
    return {'status': 'insufficient_evidence', 'answer': '资料不足',
            'citations': [], 'judgment': 'inference'}


class FakeClient:
    def __init__(self):
        self.calls, self.events, self.closed = [], [], False
        self.model, self.provider, self.parent_id = 'actual-parent-model', 'actual-provider', 'parent'
        self.child_id, self.sandbox = 'fresh-1', {'type': 'readOnly', 'networkAccess': False}
        self.text = json.dumps(output())
        self.config = {'config': {'mcp_servers': {'node_repl': {'token': 'PRIVATE'}}},
                       'layers': [{'config': {'mcp_servers': {'other': {}}}}]}
        self.tool = False

    def call(self, method, params, *, timeout):
        assert timeout > 0
        self.calls.append((method, params))
        if method == 'initialize':
            return {}
        if method == 'thread/read':
            return {'thread': {'id': self.parent_id, 'model': self.model,
                               'modelProvider': self.provider}}
        if method == 'config/read':
            return self.config
        if method == 'thread/start':
            return {'thread': {'id': self.child_id}, 'model': self.model,
                    'modelProvider': self.provider, 'approvalPolicy': 'never', 'sandbox': self.sandbox}
        if method == 'turn/start':
            self.events = [{'method': 'item/completed', 'params': {
                'threadId': self.child_id, 'turnId': 'turn-1', 'item': {
                    'type': 'commandExecution' if self.tool else 'agentMessage',
                    'id': 'message-1', 'text': self.text}}},
                {'method': 'turn/completed', 'params': {'threadId': self.child_id,
                    'turn': {'id': 'turn-1', 'status': 'completed', 'error': None}}}]
            return {'turn': {'id': 'turn-1'}}
        raise AssertionError(method)

    def notify(self, method, params, *, timeout):
        self.calls.append((method, params))

    def next_event(self, *, timeout):
        return self.events.pop(0)

    def close(self):
        self.closed = True


class CodexDispatcherTests(unittest.TestCase):
    def create(self):
        client = FakeClient()
        dispatcher = CodexDispatcher(parent_session_id='parent', cwd=str(Path.cwd()), client=client)
        self.addCleanup(dispatcher.close)
        return dispatcher, client

    def test_native_default_refuses_without_any_rpc(self):
        dispatcher, client = self.create()
        with self.assertRaisesRegex(CodexError, 'tool_isolation_verified=false'):
            dispatcher(request(), timeout=1)
        self.assertEqual(client.calls, [])

    def test_all_six_roles_refuse_through_real_native_bridge_before_rpc(self):
        # A query-only negative test cannot establish that reviewer/auditor or
        # repair routes cannot accidentally bypass the same closed boundary.
        dispatcher, client = self.create()
        transport = InheritedTransport(dispatcher, parent_session_id='parent')
        seen = set()
        for system, (role, fields) in _ROUTES.items():
            envelope = {key: {} for key in fields}
            envelope['system'] = system
            if 'mode' in fields:
                envelope['mode'] = role if role in ('query', 'lint') else 'query'
            with self.subTest(role=role):
                with self.assertRaises(NativeError):
                    transport(envelope, timeout=2)
                self.assertEqual(client.calls, [])
            seen.add(role)
        self.assertEqual(seen, {'worker', 'reviewer', 'auditor', 'query',
                                'lint', 'readonly-review'})

    def test_inspect_has_no_model_call_and_no_config_secret(self):
        dispatcher, client = self.create()
        report = dispatcher.inspect()
        self.assertEqual(report['model'], client.model)
        self.assertEqual(report['mcp_servers'], ['node_repl', 'other'])
        self.assertFalse(report['tool_isolation_verified'])
        self.assertFalse(report['native_compatible'])
        self.assertNotIn('PRIVATE', json.dumps(report))
        self.assertNotIn('thread/start', [m for m, _ in client.calls])
        self.assertNotIn('turn/start', [m for m, _ in client.calls])

    def test_draft_real_metadata_new_context_and_isolation_caveat(self):
        dispatcher, client = self.create()
        result = dispatcher.draft(request(), timeout=5)
        self.assertIs(type(result), CodexDraft)
        self.assertNotIsInstance(result, NativeResult)
        self.assertEqual(result.session_id, 'fresh-1')
        self.assertEqual(result.model, 'actual-parent-model')
        self.assertFalse(result.tool_isolation_verified)
        self.assertFalse(result.applied)
        self.assertEqual(result.output, output())
        params = next(p for m, p in client.calls if m == 'thread/start')
        self.assertEqual(params['baseInstructions'], QUERY_SYSTEM)
        self.assertEqual(params['modelProvider'], 'actual-provider')
        self.assertEqual(params['sandbox'], 'read-only')
        self.assertEqual(params['approvalPolicy'], 'never')
        self.assertEqual(params['environments'], [])
        self.assertTrue(params['ephemeral'])
        self.assertFalse(params['allowProviderModelFallback'])
        self.assertEqual(params['config']['mcp_servers'], {
            'node_repl': {'enabled': False}, 'other': {'enabled': False}})
        self.assertTrue(all(v is False for v in params['config']['features'].values()))
        methods = [m for m, p in client.calls]
        self.assertNotIn('thread/resume', methods)
        self.assertNotIn('thread/fork', methods)
        self.assertNotIn('config/value/write', methods)
        self.assertEqual(methods.count('initialize'), 1)

    def test_reuse_single_client_initialize_once_fresh_sessions(self):
        dispatcher, client = self.create()
        first = dispatcher.draft(request(), timeout=5)
        client.child_id = 'fresh-2'
        second = dispatcher.draft(replace(request(), request_id='req-2'), timeout=5)
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(sum(m == 'initialize' for m, _ in client.calls), 1)
        with self.assertRaisesRegex(CodexError, '标识'):
            dispatcher.draft(request(), timeout=5)

    def test_missing_parent_model_never_falls_back(self):
        dispatcher, client = self.create()
        client.model = None
        with self.assertRaisesRegex(CodexError, '元数据'):
            dispatcher.draft(request(), timeout=5)
        self.assertTrue(client.closed)
        self.assertNotIn('thread/start', [m for m, _ in client.calls])

    def test_strict_json_no_markdown_duplicates_or_extra_fields(self):
        for text in ('```json\n{}\n```', '{"a":1,"a":2}',
                     json.dumps(dict(output(), approved=True)), '[]'):
            with self.subTest(text=text):
                dispatcher, client = self.create()
                client.text = text
                with self.assertRaises(ValueError):
                    dispatcher.draft(request(), timeout=5)
                self.assertTrue(client.closed)

    def test_sandbox_mismatch_or_tool_item_stops(self):
        dispatcher, client = self.create()
        client.sandbox = {'type': 'workspaceWrite'}
        with self.assertRaisesRegex(CodexError, '沙箱'):
            dispatcher.draft(request(), timeout=5)
        self.assertNotIn('turn/start', [m for m, _ in client.calls])
        dispatcher, client = self.create()
        client.tool = True
        with self.assertRaisesRegex(CodexError, '工具'):
            dispatcher.draft(request(), timeout=5)
        self.assertTrue(client.closed)

    def test_untrusted_request_variants_rejected_before_rpc(self):
        variants = [replace(request(), model_policy='override'),
                    replace(request(), tools=('shell',)), replace(request(), tools=[]),
                    replace(request(), history=('parent history',)),
                    replace(request(), fresh_context=False), replace(request(), role='worker'),
                    replace(request(), payload_json='{}'),
                    replace(request(), system='untrusted system'),
                    replace(request(), request_id='')]
        for value in variants:
            dispatcher, client = self.create()
            with self.assertRaises(ValueError):
                dispatcher.draft(value, timeout=2)
            self.assertEqual(client.calls, [])

    def test_dispatcher_lock_wait_obeys_timeout(self):
        dispatcher, client = self.create()
        dispatcher._lock.acquire()
        try:
            with self.assertRaisesRegex(CodexError, '锁超时'):
                dispatcher.inspect(timeout=.03)
        finally:
            dispatcher._lock.release()
        self.assertEqual(client.calls, [])

    def test_invalid_timeout_rejected_before_rpc(self):
        for timeout in (0, -1, True, float('inf'), float('nan'), 86401):
            dispatcher, client = self.create()
            with self.assertRaises(CodexError):
                dispatcher.draft(request(), timeout=timeout)
            self.assertEqual(client.calls, [])


class JsonRpcClientTests(unittest.TestCase):
    def create(self, script, **limits):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        client = JsonRpcClient([sys.executable, '-u', '-c', script], cwd=temp.name, **limits)
        self.addCleanup(client.close)
        return client

    def test_round_trip_and_notification(self):
        client = self.create('''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({'method':'progress','params':{}}),flush=True)
 print(json.dumps({'id':r['id'],'result':{'ok':True}}),flush=True)
''')
        self.assertEqual(client.call('read', {}, timeout=3), {'ok': True})
        self.assertEqual(client.next_event(timeout=1)['method'], 'progress')

    def test_timeout_kills_child(self):
        client = self.create('import time; time.sleep(30)')
        with self.assertRaisesRegex(CodexError, '超时'):
            client.call('read', {}, timeout=.1)
        self.assertIsNotNone(client._process.poll())

    def test_blocked_pipe_write_obeys_timeout(self):
        client = self.create('import time; time.sleep(30)')
        with self.assertRaisesRegex(CodexError, '超时'):
            client.call('read', {'text': 'x' * (1024 * 1024)}, timeout=.1)
        self.assertIsNotNone(client._process.poll())

    def test_server_approval_dynamic_tool_and_unknown_request_denied(self):
        for method in ('item/commandExecution/requestApproval', 'item/tool/call',
                       'item/permissions/requestApproval', 'unknown/server/request'):
            with self.subTest(method=method):
                script = '''import sys,json,time
json.loads(sys.stdin.readline())
print(json.dumps({'id':'server-request','method':METHOD,'params':{}}),flush=True)
response=json.loads(sys.stdin.readline())
assert 'error' in response and 'result' not in response
time.sleep(30)
'''.replace('METHOD', repr(method))
                client = self.create(script)
                with self.assertRaisesRegex(CodexError, '已拒绝'):
                    client.call('read', {}, timeout=3)
                self.assertIsNotNone(client._process.poll())

    def test_bad_response_and_oversized_stream_stop(self):
        scripts = ["print('not-json',flush=True)",
                   "print('x'*2048,flush=True)",
                   "print('{\"id\":99,\"result\":{}}',flush=True)"]
        for script in scripts:
            client = self.create('import time; ' + script + '; time.sleep(30)',
                                 max_line_bytes=1024)
            with self.assertRaises(CodexError):
                client.call('read', {}, timeout=3)
            self.assertIsNotNone(client._process.poll())

    def test_stderr_budget_queue_flood_and_outgoing_limit(self):
        scripts = ["import sys; sys.stderr.write('x'*4096);sys.stderr.flush()",
                   "import json; [print(json.dumps({'method':'progress','params':{}}),flush=True) for _ in range(100)]"]
        for script in scripts:
            client = self.create(script + '; import time; time.sleep(30)',
                                 max_line_bytes=1024, max_total_bytes=2048, max_queue=2)
            with self.assertRaises(CodexError):
                client.call('read', {}, timeout=3)
            self.assertIsNotNone(client._process.poll())
        client = self.create('import time; time.sleep(30)', max_line_bytes=128)
        with self.assertRaisesRegex(CodexError, '输入超限'):
            client.call('read', {'text': 'x' * 1024}, timeout=3)
        self.assertIsNotNone(client._process.poll())

    def test_shell_shims_refused(self):
        for path in ('codex.cmd', 'codex.bat', 'codex.ps1'):
            with self.assertRaises(CodexError):
                JsonRpcClient([path], cwd=Path.cwd())


if __name__ == '__main__':
    unittest.main()
