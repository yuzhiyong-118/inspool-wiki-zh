"""批准测试只操作临时目录；模拟流不代表获得真人认证。"""
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.host.approval import ApprovalError, ApprovalHandle, ApprovalStore


def context():
    manifest = {'operation_type': 'approve', 'operation_id': 'op-1',
                'scope': ['raw/unprocessed/a.md'], 'candidate_digest': 'version-1',
                'task': '归档批次', 'dependencies_digest': 'dependency-1',
                'rules_digest': 'rules-1', 'mapping_digest': 'mapping-1',
                'validator_version': 'validator-1', 'review_prompt_version': 'prompt-1'}
    return dict(manifest=manifest, manifest_digest=digest(manifest),
        candidate={'changes': [{'action': 'move', 'source': 'raw/unprocessed/a.md',
                                'path': 'raw/processed/a.md'}]},
        snapshot={'files': {'wiki/index.md': 'hash-1'}}, operation_type='approve',
        source_paths=['raw/unprocessed/a.md'],
        bindings={'operation_id': 'op-1', 'candidate_digest': 'version-1',
                  'dependencies_digest': 'dependency-1', 'rules_digest': 'rules-1',
                  'mapping_digest': 'mapping-1', 'validator_version': 'validator-1',
                  'review_prompt_version': 'prompt-1'})


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'private'
        self.store = ApprovalStore(self.root)
        self.context = context()

    def approve(self, store=None, context=None, **kwargs):
        value = self.context if context is None else context
        # Explicitly trusted unit-test seam only; the production API has no bypass.
        with patch('tools.wiki_runtime.host.approval._terminal', return_value=True):
            return (store or self.store).approve_interactive(value,
                input_stream=io.StringIO(digest(value) + '\n'), output_stream=io.StringIO(), **kwargs)

    def test_restart_lookup_opaque_and_forgery(self):
        handle = self.approve()
        self.assertTrue(self.store.verify(self.context, handle))
        restart = ApprovalStore(self.root)
        self.assertTrue(restart.verify(self.context, handle))
        self.assertTrue(restart.verify(self.context, restart.lookup(self.context)))
        for fake in ({'confirmed': True}, {'ref': digest(self.context)}, digest(self.context), True, None):
            self.assertFalse(restart.verify(self.context, fake))
        with self.assertRaises(TypeError):
            ApprovalHandle(digest(self.context), 'fake', 'fake')
        with self.assertRaises(TypeError):
            json.dumps(handle)

    def test_pipe_real_subprocess_cannot_approve(self):
        program = ('import json,sys; from tools.wiki_runtime.host.approval import ApprovalStore; '
                   'ApprovalStore(sys.argv[1]).approve_interactive(json.loads(sys.argv[2]))')
        result = subprocess.run([sys.executable, '-B', '-c', program, str(self.root),
            json.dumps(self.context)], input=digest(self.context) + '\n', text=True,
            capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TTY', result.stderr)
        self.assertIsNone(self.store.lookup(self.context))

    def test_fake_isatty_without_real_fd_is_rejected(self):
        source = io.StringIO(digest(self.context) + '\n')
        source.isatty = lambda: True
        with self.assertRaises(ApprovalError):
            self.store.approve_interactive(self.context, input_stream=source, output_stream=source)

    def test_exact_digest_required_and_terminal_escaped(self):
        value = copy.deepcopy(self.context)
        value['manifest']['task'] = '\x1b[2J\r\n\u202e'
        value['manifest_digest'] = digest(value['manifest'])
        output = io.StringIO()
        with patch('tools.wiki_runtime.host.approval._terminal', return_value=True):
            with self.assertRaises(ApprovalError):
                self.store.approve_interactive(value, input_stream=io.StringIO('yes\n'), output_stream=output)
        self.assertNotIn('\x1b', output.getvalue())
        self.assertNotIn('\u202e', output.getvalue())
        self.assertIn('\\u001b', output.getvalue())
        self.assertIsNone(self.store.lookup(value))

    def test_every_context_component_bound(self):
        handle = self.approve()
        for field in ('scope', 'task', 'operation_id', 'candidate_digest', 'dependencies_digest',
                      'rules_digest', 'mapping_digest', 'validator_version', 'review_prompt_version'):
            value = copy.deepcopy(self.context)
            value['manifest'][field] = ['other'] if field == 'scope' else 'other'
            value['manifest_digest'] = digest(value['manifest'])
            if field in value['bindings']:
                value['bindings'][field] = 'other'
            self.assertFalse(self.store.verify(value, handle), field)
        for field in ('candidate', 'snapshot', 'bindings'):
            value = copy.deepcopy(self.context)
            value[field]['extra'] = 'changed'
            self.assertFalse(self.store.verify(value, handle), field)
        value = copy.deepcopy(self.context)
        value['source_paths'] = ['other']
        self.assertFalse(self.store.verify(value, handle))

    def test_expiry_and_clock_rollback(self):
        with patch('tools.wiki_runtime.host.approval.time.time', return_value=100):
            handle = self.approve(ttl_seconds=10)
        for now in (99, 110, 111):
            with patch('tools.wiki_runtime.host.approval.time.time', return_value=now):
                self.assertFalse(self.store.verify(self.context, handle))
        with patch('tools.wiki_runtime.host.approval.time.time', return_value=109):
            self.assertTrue(self.store.verify(self.context, handle))

    def test_revoke_restart_and_reissue(self):
        old = self.approve()
        self.store.revoke(self.context)
        restart = ApprovalStore(self.root)
        self.assertIsNone(restart.lookup(self.context))
        self.assertFalse(restart.verify(self.context, old))
        new = self.approve(store=restart)
        self.assertTrue(restart.verify(self.context, new))
        self.assertFalse(restart.verify(self.context, old))

    def test_tampered_record_fails_closed(self):
        handle = self.approve()
        path = self.root / (digest(self.context) + '.json')
        record = json.loads(path.read_bytes())
        record['payload']['expires_at'] += 100000
        path.write_text(json.dumps(record), encoding='utf-8')
        self.assertFalse(self.store.verify(self.context, handle))
        with self.assertRaises(ApprovalError):
            self.approve()

    def test_broken_and_changed_key_never_overwritten(self):
        handle = self.approve()
        key = self.root / 'approval.key'
        key.write_bytes(b'broken')
        with self.assertRaises(ApprovalError):
            ApprovalStore(self.root)
        self.assertEqual(key.read_bytes(), b'broken')
        self.assertFalse(self.store.verify(self.context, handle))
        key.write_bytes(b'x' * 32)
        self.assertFalse(self.store.verify(self.context, handle))
        self.assertFalse(ApprovalStore(self.root).verify(self.context, handle))

    def test_hardlink_key_and_record_rejected(self):
        handle = self.approve()
        for path in (self.root / 'approval.key', self.root / (digest(self.context) + '.json')):
            alias = Path(self.temp.name) / 'alias'
            os.link(path, alias)
            try:
                self.assertFalse(self.store.verify(self.context, handle))
            finally:
                alias.unlink()

    def test_missing_key_with_records_not_regenerated(self):
        self.approve()
        (self.root / 'approval.key').unlink()
        with self.assertRaises(ApprovalError):
            ApprovalStore(self.root)
        self.assertFalse((self.root / 'approval.key').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows junction 专项')
    def test_windows_junction_root_rejected(self):
        alias = Path(self.temp.name) / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.root)],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaises(ApprovalError):
            ApprovalStore(alias)

    def test_symlink_root_rejected_when_available(self):
        alias = Path(self.temp.name) / 'alias'
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('当前 Windows 不允许创建 symlink')
        with self.assertRaises(ApprovalError):
            ApprovalStore(alias)

    def test_normal_operations_and_invalid_ttl_rejected(self):
        value = copy.deepcopy(self.context)
        value['operation_type'] = value['manifest']['operation_type'] = 'ingest'
        value['manifest_digest'] = digest(value['manifest'])
        with self.assertRaises(ApprovalError):
            self.approve(context=value)
        for ttl in (0, -1, True, float('nan'), float('inf')):
            with self.assertRaises(ApprovalError):
                self.approve(ttl_seconds=ttl)


if __name__ == '__main__':
    unittest.main()
