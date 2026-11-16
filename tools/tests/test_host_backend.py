"""独立 JSONL 后端的真实子进程和封闭协议回归；只操作临时树。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.wiki_runtime.host.backend import (MAX_DEPTH, MAX_LINE_BYTES, MAX_NODES,
                                             RoleBackend, parse_json, probe_backend)


class HostBackendTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='wiki-backend-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ('formal', 'private', 'candidate'):
            (self.root / name).mkdir()
        (self.root / 'formal' / 'page.md').write_text('authorized', encoding='utf-8')
        (self.root / 'private' / 'journal.json').write_text('sensitive-test-sentinel', encoding='utf-8')
        self.config = {'formal_root': str(self.root / 'formal'), 'role': 'worker',
                       'candidate_root': str(self.root / 'candidate'),
                       'read_scopes': {'wiki': str(self.root / 'formal')},
                       'protected_roots': [str(self.root / 'private')]}

    def run_backend(self, wire, config=None):
        result = subprocess.run([sys.executable, '-B', '-m', 'tools.wiki_runtime.host.backend',
                                 '--bootstrap', json.dumps(self.config if config is None else config)],
                                input=wire, capture_output=True,
                                cwd=Path(__file__).resolve().parents[2], timeout=20)
        self.assertEqual(result.stderr, b'')
        return result, [json.loads(line) for line in result.stdout.splitlines()]

    def test_real_subprocess_role_and_escape_probes(self):
        report = probe_backend()
        self.assertTrue(report['passed'], report)
        self.assertTrue(report['protected_bytes_unchanged'])
        self.assertFalse(report['os_isolation_verified'])
        self.assertFalse(report['desktop_session_restricted'])
        self.assertEqual({row['role'] for row in report['roles']},
                         {'worker', 'reviewer', 'auditor', 'coordinator'})
        for row in report['roles']:
            self.assertEqual(len(row['descriptor']['source_sha256']), 64)
            self.assertTrue(row['malformed_frames_rejected'])

    def test_json_frames_fail_closed_and_channel_recovers(self):
        invalid = [b'null', b'[]', b'{"tool":"read"}',
                   b'{"tool":"read","arguments":{},"role":"worker"}',
                   b'{"tool":"read","arguments":{"x":1e999}}',
                   b'{"tool":"read","arguments":{"x":Infinity}}',
                   b'{"tool":"read","arguments":{"x":1,"x":2}}', b'\xff', b'{bad']
        good = json.dumps({'tool': 'read', 'arguments': {'scope': 'wiki', 'path': 'page.md'}}).encode()
        result, answers = self.run_backend(b'\n'.join(invalid + [good]) + b'\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(answers), len(invalid) + 1)
        self.assertTrue(all(answer == {'ok': False, 'error': {'code': 'invalid_request'}}
                            for answer in answers[:-1]))
        self.assertEqual(answers[-1], {'ok': True, 'result': {'text': 'authorized'}})

    def test_line_limit_closes_channel_without_tail_execution(self):
        tail = json.dumps({'tool': 'candidate_write', 'arguments': {'path': 'tail.md', 'text': 'x'}}).encode()
        result, answers = self.run_backend(b' ' * (MAX_LINE_BYTES + 1) + b'\n' + tail + b'\n')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(answers, [{'ok': False, 'error': {'code': 'invalid_request'}}])
        self.assertFalse((self.root / 'candidate' / 'tail.md').exists())

    def test_depth_node_and_python_object_limits(self):
        for raw in ('[' * (MAX_DEPTH + 1) + '0' + ']' * (MAX_DEPTH + 1),
                    json.dumps([0] * MAX_NODES)):
            with self.assertRaises(ValueError):
                parse_json(raw)
        backend = RoleBackend(**self.config)
        answer = backend.invoke('candidate_write', {'path': 'x', 'text': object()})
        self.assertEqual(answer, {'ok': False, 'error': {'code': 'invalid_request'}})

    def test_bootstrap_unknown_identity_and_permission_fields_refused(self):
        for extra in ('session', 'approved', 'verified', 'callback', 'tools'):
            result, answers = self.run_backend(b'', {**self.config, extra: 'sensitive-test-sentinel'})
            self.assertEqual(result.returncode, 2)
            self.assertEqual(answers, [{'ok': False, 'error': {'code': 'invalid_bootstrap'}}])
            self.assertNotIn(b'sensitive-test-sentinel', result.stdout)
        result, answers = self.run_backend(b'', {**self.config, 'role': 'executor'})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(answers[0]['error']['code'], 'invalid_bootstrap')

    def test_denial_does_not_reflect_private_bytes_or_paths(self):
        wire = json.dumps({'tool': 'read', 'arguments': {'scope': str(self.root / 'private'),
                                                       'path': 'journal.json'}}).encode() + b'\n'
        result, answers = self.run_backend(wire)
        self.assertEqual(answers, [{'ok': False, 'error': {'code': 'denied'}}])
        self.assertNotIn(b'sensitive-test-sentinel', result.stdout)
        self.assertNotIn(str(self.root).encode(), result.stdout)

    def test_catalog_is_copied_and_bootstrap_role_is_fixed(self):
        backend = RoleBackend(**self.config)
        backend.catalog()[0]['parameters']['properties'].clear()
        self.assertTrue(backend.catalog()[0]['parameters']['properties'])
        for name in ('role', 'session', 'read_scopes', 'candidate_root', 'approved'):
            response = backend.invoke('candidate_write', {'path': 'x.md', 'text': 'x', name: 'trusted'})
            self.assertFalse(response['ok'])


if __name__ == '__main__':
    unittest.main()
