"""候选采集的离线实质回归；只写 TemporaryDirectory。"""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.wiki_runtime.capture import ADAPTERS, capabilities, capture, identify, validate_package
from tools.wiki_runtime.contracts import ContractError, bytes_digest

FIXTURES = Path(__file__).parent / 'fixtures' / 'capture'


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.vault = self.base / 'vault'
        self.vault.mkdir()
        self.candidates = self.base / 'candidates'

    def run_capture(self, data=None, *, file=None, **kwargs):
        if file is None:
            file = self.base / 'source.md'
            file.write_bytes(data)
        return capture(file, self.candidates, kwargs.pop('package_path', 'p1'),
                       vault_root=self.vault, **kwargs)

    def test_markdown_preserves_bytes_bom_crlf_and_hashes(self):
        data = '\ufeff# 标题\r\n\r\n正文。\r\n'.encode()
        p, root = self.run_capture(data)
        self.assertEqual(p['quality']['status'], 'complete')
        self.assertEqual((root / p['originals'][0]['path']).read_bytes(), data)
        self.assertEqual(p['extracted']['sha256'], bytes_digest(data))
        self.assertEqual(validate_package(p, root), p)
        self.assertTrue((root / 'source-package.json').is_file())

    def test_same_origin_reparse_and_new_revision(self):
        first, _ = self.run_capture(b'# One\ntext', origin='https://example.org/article')
        same, _ = self.run_capture(b'# One\ntext', origin='https://example.org/article', package_path='p2')
        changed, _ = self.run_capture(b'# Two\ntext', origin='https://example.org/article', package_path='p3')
        self.assertEqual(first['source_id'], changed['source_id'])
        self.assertEqual(first['source_revision'], same['source_revision'])
        self.assertNotEqual(first['source_revision'], changed['source_revision'])

    def test_wechat_complete_nested_body_and_excluded_footer(self):
        p, root = self.run_capture(file=FIXTURES / 'article.html')
        self.assertEqual(p['input_type'], 'wechat')
        self.assertEqual(p['quality']['status'], 'complete')
        self.assertEqual(p['source']['author'], '作者甲')
        text = (root / p['extracted']['path']).read_text(encoding='utf-8')
        self.assertIn('第二个段落', text)
        self.assertNotIn('不要把页尾', text)
        self.assertTrue(p['locators'])

    def test_verification_and_truncation(self):
        p, _ = self.run_capture(file=FIXTURES / 'verify.html')
        self.assertEqual(p['quality']['status'], 'failed')
        self.assertIn('verification_or_block_page', p['quality']['errors'])
        p, _ = self.run_capture(file=FIXTURES / 'truncated.html', package_path='p2')
        self.assertEqual(p['quality']['status'], 'partial')
        self.assertIn('truncated_html', p['quality']['missing'])

    def test_invalid_utf8_and_empty_frontmatter_body(self):
        p, _ = self.run_capture(b'\xff')
        self.assertEqual(p['quality']['status'], 'failed')
        p, _ = self.run_capture(b'---\ntitle: empty\n---\n', package_path='p2')
        self.assertIn('empty_body', p['quality']['errors'])
        p, _ = self.run_capture(b'---\ntitle: broken', package_path='p3')
        self.assertIn('unclosed_frontmatter', p['quality']['errors'])

    def test_markdown_local_attachment_and_missing_remote(self):
        (self.base / 'image.png').write_bytes(b'png bytes')
        p, root = self.run_capture(b'# Image\n![x](image.png)\n[x](#heading)')
        self.assertEqual(p['quality']['status'], 'complete')
        self.assertEqual(len(p['attachments']), 1)
        self.assertIn('../attachments/0001.png', (root / p['extracted']['path']).read_text())
        p, _ = self.run_capture(b'# Image\n![x](https://example.org/image)', package_path='p2')
        self.assertEqual(p['quality']['status'], 'partial')

    def test_wechat_resource_mapping(self):
        file = self.base / 'article.html'
        file.write_text('<h1 id="activity-name">Image</h1><div id="js_content"><p>正文</p>'
                        '<img data-src="https://example.org/a.png"></div>', encoding='utf-8')
        p, _ = self.run_capture(file=file)
        self.assertEqual(p['quality']['status'], 'partial')
        image = self.base / 'a.png'
        image.write_bytes(b'PNG')
        p, _ = self.run_capture(file=file, package_path='p2', attachments={'https://example.org/a.png': image})
        self.assertEqual(p['quality']['status'], 'complete')

    def test_attachment_traversal_is_not_read(self):
        (self.base / 'secret.txt').write_text('secret')
        folder = self.base / 'input'
        folder.mkdir()
        file = folder / 'source.md'
        file.write_text('# Title\n![bad](../secret.txt)')
        p, _ = self.run_capture(file=file)
        self.assertEqual(p['quality']['status'], 'partial')
        self.assertEqual(p['attachments'], [])

    def test_output_paths_and_business_area_rejected(self):
        file = self.base / 'source.md'
        file.write_text('# title\nbody')
        for name in ('../escape', '/absolute', 'C:/escape', 'nested/../../escape'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_capture(file=file, package_path=name)
        for area in ('raw', 'wiki', 'tools', '.git', ''):
            with self.assertRaises(ValueError):
                capture(file, self.vault / area / 'candidates', 'p', vault_root=self.vault)
        self.assertFalse((self.vault / 'raw').exists())
        with self.assertRaises(ValueError):
            capture(file, self.vault, 'p', vault_root=self.vault)
        p, root = capture(file, self.vault / '.wiki-runtime' / 'candidates', 'p', vault_root=self.vault)
        self.assertEqual(p['quality']['status'], 'complete')
        self.assertTrue(root.is_relative_to(self.vault / '.wiki-runtime'))

    def test_no_overwrite_tamper_and_revision_validation(self):
        p, root = self.run_capture(b'# title\nbody')
        with self.assertRaises(FileExistsError):
            self.run_capture(b'# changed')
        changed = copy.deepcopy(p)
        changed['source_revision'] = '0' * 64
        with self.assertRaises(ContractError):
            validate_package(changed, root)
        (root / p['extracted']['path']).write_bytes(b'tampered')
        with self.assertRaises(ContractError):
            validate_package(p, root)

    def test_false_complete_claim_is_rejected(self):
        p, root = self.run_capture(file=FIXTURES / 'truncated.html')
        p['quality'].update(status='complete', missing=[], errors=[])
        with self.assertRaises(ContractError):
            validate_package(p, root)

    def test_forged_adapter_and_input_type_cannot_bypass_checks(self):
        p, root = self.run_capture(b'# title\nbody')
        for status in ('complete', 'partial', 'failed'):
            for field, value in (('adapter_id', 'bogus'), ('input_type', 'pdf')):
                with self.subTest(status=status, field=field):
                    forged = copy.deepcopy(p)
                    forged['quality']['status'] = status
                    if field == 'adapter_id':
                        forged['parser'][field] = value
                    else:
                        forged[field] = value
                    with self.assertRaises(ContractError):
                        validate_package(forged, root)

    def test_interruption_has_no_success_manifest(self):
        with patch('tools.wiki_runtime.capture.adapters.validate_package', side_effect=RuntimeError('interrupt')):
            with self.assertRaises(RuntimeError):
                self.run_capture(b'# title\nbody')
        self.assertFalse((self.candidates / 'p1' / 'source-package.json').exists())
        self.assertTrue((self.candidates / 'p1' / 'originals' / 'source.md').is_file())

    def test_symlink_output_escape_rejected(self):
        self.candidates.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        try:
            (self.candidates / 'link').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            if os.name != 'nt':
                self.skipTest(f'当前环境未允许创建 symlink: {exc}')
            result = subprocess.run(['cmd', '/c', 'mklink', '/J',
                                     str(self.candidates / 'link'), str(outside)],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                self.skipTest('当前 Windows 未允许创建 symlink/junction')
        with self.assertRaises(ValueError):
            self.run_capture(b'# title\nbody', package_path='link/escaped')
        self.assertEqual(list(outside.iterdir()), [])

    def test_registry_unknown_and_import_without_writes(self):
        self.assertEqual(identify('x.md'), 'markdown')
        self.assertTrue(capabilities('wechat')['offline'])
        with self.assertRaises(ValueError):
            identify('fake.bin')
        with self.assertRaises(ValueError):
            capabilities('input:run-code')
        with self.assertRaises(TypeError):
            ADAPTERS['evil'] = {}
        repo = Path(__file__).resolve().parents[2]
        code = f'import sys; sys.path.insert(0, {str(repo)!r}); import tools.wiki_runtime.capture'
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=self.base, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.base.iterdir()), [self.vault])


if __name__ == '__main__':
    unittest.main()
