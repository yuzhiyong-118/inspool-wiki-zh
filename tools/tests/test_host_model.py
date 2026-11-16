"""用真实回环 HTTP 检查模型边界，不连接外部付费服务。"""
import contextlib
import http.server
import json
import threading
import time
import unittest

from tools.wiki_runtime.host.model import MAX_RESPONSE_BYTES, ModelError, ResponsesTransport


def reply(text='{"ok":true}'):
    return {'status': 'completed', 'output': [{
        'type': 'message', 'role': 'assistant', 'status': 'completed',
        'content': [{'type': 'output_text', 'text': text}],
    }]}


@contextlib.contextmanager
def server(payload=None, *, status=200, delay=0, location=None, trickle=False):
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            received.append((self.path, dict(self.headers), self.rfile.read(int(self.headers['Content-Length']))))
            time.sleep(delay)
            data = payload if type(payload) is bytes else json.dumps(reply() if payload is None else payload).encode()
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                if location:
                    self.send_header('Location', location)
                self.end_headers()
                if trickle:
                    for item in data:
                        self.wfile.write(bytes([item]))
                        self.wfile.flush()
                        time.sleep(0.02)
                else:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    httpd.daemon_threads = True
    worker = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{httpd.server_port}/v1', received
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join()


def config(url='https://api.openai.com/v1'):
    return dict(provider='openai_responses', base_url=url, model='explicit-test-model',
                api_key_env='TEST_KEY', timeout_seconds=2, max_output_tokens=100)


def transport(url, **updates):
    options = config(url)
    options.update(updates)
    return ResponsesTransport(options, environ={'TEST_KEY': 'secret-for-local-test'})


class HostModelTests(unittest.TestCase):
    def test_real_http_shape_and_independent_messages(self):
        with server() as (url, seen):
            model = transport(url)
            for role in ('worker', 'reviewer'):
                self.assertEqual(model({'system': '只返回 JSON', 'role': role, 'input': {'model': 'untrusted'}}, timeout=1), {'ok': True})
            self.assertEqual(len(seen), 2)
            for index, (path, headers, raw) in enumerate(seen):
                self.assertEqual(path, '/v1/responses')
                self.assertEqual(headers['Authorization'], 'Bearer secret-for-local-test')
                self.assertNotIn(b'secret-for-local-test', raw)
                body = json.loads(raw)
                self.assertEqual(set(body), {'model', 'input', 'text', 'store', 'tools', 'max_output_tokens'})
                self.assertEqual(body['model'], 'explicit-test-model')
                self.assertIs(body['store'], False)
                self.assertEqual(body['tools'], [])
                self.assertEqual(body['text'], {'format': {'type': 'json_object'}})
                self.assertEqual([m['role'] for m in body['input']], ['system', 'user'])
                user = json.loads(body['input'][1]['content'])
                self.assertEqual(user['role'], ('worker', 'reviewer')[index])
                self.assertEqual(user['input']['model'], 'untrusted')

    def test_fail_closed_configuration(self):
        bad = [dict(model=''), dict(api_key_env=''), dict(provider='other'),
               dict(base_url='http://example.com/v1'), dict(base_url='https://user:secret@example.com'),
               dict(base_url='https://example.com?key=secret'), dict(timeout_seconds=float('nan')),
               dict(timeout_seconds=True), dict(timeout_seconds=10 ** 1000),
               dict(max_output_tokens=0), dict(max_output_tokens=True),
               dict(unknown='value')]
        for update in bad:
            with self.subTest(update=update), self.assertRaises(ModelError):
                transport('https://api.openai.com/v1', **update) if 'base_url' not in update else ResponsesTransport(dict(config(), **update), environ={'TEST_KEY': 'secret'})
        for env in ({}, {'TEST_KEY': ''}, {'TEST_KEY': 'secret\r\ninjection'}):
            with self.assertRaises(ModelError):
                ResponsesTransport(config(), environ=env)

    def test_redirect_never_forwards_authorization(self):
        with server() as (target, forwarded):
            for code in (301, 302, 303, 307, 308):
                with server(status=code, location=target + '/responses') as (url, _seen):
                    with self.subTest(code=code), self.assertRaises(ModelError):
                        transport(url)({'system': 'JSON'}, timeout=1)
            self.assertEqual(forwarded, [])

    def test_reasoning_metadata_with_message_but_never_tools(self):
        valid = reply()
        valid['output'].insert(0, {'type': 'reasoning', 'summary': []})
        with server(valid) as (url, _seen):
            self.assertEqual(transport(url)({'system': 'JSON'}, timeout=1), {'ok': True})
        for tool_type in ('function_call', 'mcp_call', 'shell_call', 'unknown'):
            invalid = reply()
            invalid['output'].insert(0, {'type': 'reasoning', 'summary': []})
            invalid['output'].append({'type': tool_type, 'arguments': '{}'})
            with server(invalid) as (url, _seen):
                with self.subTest(tool_type=tool_type), self.assertRaises(ModelError):
                    transport(url)({'system': 'JSON'}, timeout=1)

    def test_reject_malformed_and_unsafe_output(self):
        cases = [b'{"status":"completed","status":"completed"}', b'not JSON',
                 reply('{"a":1,"a":2}'), reply('{"a":NaN}'), reply('{"a":1e999}'),
                 reply('[]'), reply('```json\n{}\n```'), reply('{} {}'),
                 dict(reply(), status='incomplete'), dict(reply(), error={'message': 'secret-for-local-test'}),
                 dict(reply(), incomplete_details={'reason': 'max_output_tokens'})]
        refusal = reply()
        refusal['output'][0]['content'] = [{'type': 'refusal', 'refusal': 'secret-for-local-test'}]
        calls = reply()
        calls['output'].append({'type': 'function_call', 'name': 'write', 'arguments': '{}'})
        cases.extend([refusal, calls, dict(reply(), output=[{'type': 'function_call'}]),
                      b'x' * (MAX_RESPONSE_BYTES + 1)])
        for payload in cases:
            with server(payload) as (url, _seen):
                with self.subTest(kind=str(type(payload))), self.assertRaises(ModelError) as caught:
                    transport(url)({'system': 'JSON'}, timeout=1)
                self.assertNotIn('secret-for-local-test', str(caught.exception))

    def test_timeout_budget_is_never_extended(self):
        for configured, caller, trickle in ((2, .06, False), (.06, 2, False), (2, .06, True)):
            with server(delay=0 if trickle else .3, trickle=trickle) as (url, _seen):
                model = transport(url, timeout_seconds=configured)
                started = time.monotonic()
                with self.assertRaises(ModelError):
                    model({'system': 'JSON'}, timeout=caller)
                self.assertLess(time.monotonic() - started, .25)

    def test_invalid_input_makes_no_request(self):
        with server() as (url, seen):
            model = transport(url)
            for envelope in ({}, {'system': ''}, {'system': 'JSON', 'input': float('nan')}, {'system': 'JSON', 'input': object()}):
                with self.assertRaises(ModelError):
                    model(envelope, timeout=1)
            for timeout in (0, True, float('inf'), -1):
                with self.assertRaises(ModelError):
                    model({'system': 'JSON'}, timeout=timeout)
            self.assertEqual(seen, [])


if __name__ == '__main__':
    unittest.main()
