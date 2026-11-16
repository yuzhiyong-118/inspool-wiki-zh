"""公开模板不覆盖私人资料；强制加入的私人路径仍被发布检查拒绝。"""
from pathlib import Path
import tempfile
import unittest

from tools.init_workspace import initialize
from tools.check_public_release import path_error, SECRETS


class PublicWorkspaceTests(unittest.TestCase):
    def test_initialize_preserves_existing_private_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'wiki').mkdir()
            index = root / 'wiki/index.md'
            index.write_bytes(b'private existing content\r\n')
            created = initialize(root)
            self.assertNotIn('wiki/index.md', created)
            self.assertEqual(index.read_bytes(), b'private existing content\r\n')
            self.assertEqual(initialize(root), [])
            self.assertIn('- 未处理：0', (root / 'raw/index.md').read_text(encoding='utf-8'))

    def test_private_files_denied_even_when_allowlisted(self):
        paths = ['raw/unprocessed/secret.md', 'wiki/index.md',
                 'docs/design/evidence/output.json', '.claude/settings.json',
                 'config.local.json', 'state.sqlite3', '../outside.md']
        for name in paths:
            with self.subTest(name=name):
                self.assertIsNotNone(path_error(name, set(paths)))

    def test_unreviewed_new_file_is_denied(self):
        self.assertIsNotNone(path_error('tools/new.py', {'README.md'}))
        self.assertIsNone(path_error('README.md', {'README.md'}))

    def test_credential_patterns_without_live_secrets(self):
        self.assertIsNotNone(SECRETS.search('sk-' + 'a' * 30))
        self.assertIsNotNone(SECRETS.search('-----BEGIN ' + 'PRIVATE KEY-----'))
