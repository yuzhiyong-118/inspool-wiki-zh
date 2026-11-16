"""微信接管回归：仅替换网络，正式门禁与 Executor 在临时库实跑。"""
import contextlib
from email.message import Message
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from tools import wechat_article
from tools.wiki_runtime.host import wechat

URL = 'https://mp.weixin.qq.com/s/fixture_Article-123'
HTML = '<h1 id="activity-name">测试标题</h1><div id="js_content"><p>不可改写原文</p></div>'.encode()


class WechatRolloutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'vault'
        self.root.mkdir()
        self.put('AGENTS.md', '# 规则\n')
        mapping = Path(__file__).parents[1] / 'wiki_runtime/contracts/rules.json'
        self.put('tools/wiki_runtime/contracts/rules.json', mapping.read_bytes())
        self.put('wiki/index.md', '# 索引\n')
        self.put('wiki/log.md', '# 日志\n')
        self.put('raw/index.md', '# 队列\n<!-- raw-queue:start -->\n<!-- raw-queue:end -->\n')
        self.state = self.base / 'state'
        self.candidate = self.base / 'candidate'

    def put(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode() if isinstance(data, str) else data)

    def capture(self, data=HTML, **kwargs):
        with patch.object(wechat, 'fetch_bytes', return_value=data):
            return wechat.capture_url(self.root, self.state, self.candidate, URL, **kwargs)

    def test_complete_uses_real_executor_preserves_original_and_registers(self):
        report = self.capture()
        self.assertEqual(report['status'], 'applied', report)
        files = list((self.root / 'raw/assets').rglob('source.html'))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), HTML)
        raw = list((self.root / 'raw/unprocessed').glob('*.md'))
        self.assertEqual(len(raw), 1)
        self.assertIn('unprocessed', raw[0].read_text(encoding='utf-8'))
        self.assertTrue(list((self.state / 'private/journals').glob('*.json')))
        self.assertNotIn('pending_review', raw[0].read_text(encoding='utf-8'))
        self.assertFalse((self.root / 'raw/processed').exists())

    def test_missing_attachment_stays_candidate(self):
        data = HTML.replace(b'</p>', b'</p><img data-src="https://mmbiz.qpic.cn/a.png">')
        report = self.capture(data)
        self.assertEqual(report['status'], 'candidate_only')
        self.assertEqual(report['quality']['status'], 'partial')
        self.assertFalse((self.root / 'raw/unprocessed').exists())
        self.assertFalse(self.state.exists())

    def test_invalid_utf8_preserved_as_failed_candidate(self):
        report = self.capture(HTML + b'\xff')
        self.assertEqual(report['quality']['status'], 'failed')
        self.assertEqual((self.candidate / 'package/originals/source.html').read_bytes(), HTML + b'\xff')

    def test_truncated_and_verification_pages_do_not_import(self):
        for body in (HTML.replace(b'</div>', b''), HTML + '环境异常'.encode()):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temp:
                with patch.object(wechat, 'fetch_bytes', return_value=body):
                    report = wechat.capture_url(self.root, self.state, Path(temp) / 'candidate', URL)
                self.assertFalse(report['applied'])
        self.assertFalse((self.root / 'raw/unprocessed').exists())

    def test_wrong_raw_path_is_rejected_by_real_import(self):
        with self.assertRaises(ValueError):
            self.capture(raw_path='raw/processed/escape.md')
        self.assertFalse((self.root / 'raw/processed').exists())

    def test_candidate_and_state_must_be_external_disjoint(self):
        for state, candidate in ((self.root / 'state', self.candidate),
                                 (self.state, self.root / 'raw/candidate'),
                                 (self.state, self.state / 'candidate'),
                                 (self.state, self.base)):
            with self.subTest(state=state, candidate=candidate), patch.object(wechat, 'fetch_bytes') as fetch:
                with self.assertRaises(ValueError):
                    wechat.capture_url(self.root, state, candidate, URL)
                fetch.assert_not_called()

    def test_size_limit_and_non_bytes_rejected(self):
        for data in (b'', 'decoded', b'x' * (wechat.MAX_HTML_BYTES + 1)):
            with self.subTest(kind=type(data)), self.assertRaises(ValueError):
                self.capture(data)
        self.assertFalse(self.candidate.exists())

    def test_urls_and_redirect_escape_rejected(self):
        for url in ('http://mp.weixin.qq.com/s/a', 'https://evil.test/s/a',
                    'https://mp.weixin.qq.com@evil.test/s/a', 'https://mp.weixin.qq.com:443/s/a',
                    'https://mp.weixin.qq.com/s/%2e%2e', 'https://mp.weixin.qq.com/s/a#x',
                    'https://mp.weixin.qq.com/s/a\n'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                wechat.validate_url(url)
        with self.assertRaises(ValueError):
            wechat._WechatRedirect().redirect_request(urllib.request.Request(URL), None, 302, '', {}, 'https://evil.test/s/x')

    def test_strict_network_boundary_preserves_bytes_and_checks_final_url(self):
        class Response(io.BytesIO):
            def __init__(self, data, url=URL):
                super().__init__(data)
                self.url = url
                self.headers = Message()
                self.headers['Content-Type'] = 'text/html; charset=utf-8'

            def geturl(self):
                return self.url

        for final_url, data, rejected in ((URL, HTML + b'\xff', False),
                                           ('https://evil.test/s/x', HTML, True),
                                           (URL, b'x' * (wechat.MAX_HTML_BYTES + 1), True)):
            with self.subTest(final_url=final_url, rejected=rejected):
                response = Response(data, final_url)
                with patch('urllib.request.build_opener') as opener:
                    opener.return_value.open.return_value = response
                    if rejected:
                        with self.assertRaises(ValueError):
                            wechat.fetch_bytes(URL)
                    else:
                        self.assertEqual(wechat.fetch_bytes(URL), data)
                    request = opener.return_value.open.call_args.args[0]
                    self.assertEqual(request.get_header('Accept-encoding'), 'identity')
        response = Response(HTML)
        response.headers['Content-Length'] = str(len(HTML) + 20)
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(ValueError):
                wechat.fetch_bytes(URL)

    def test_preview_fetch_reuses_strict_network_without_loss_in_import(self):
        with patch.object(wechat, 'fetch_bytes', return_value=HTML + b'\xff') as network:
            self.assertTrue(wechat_article.fetch(URL).endswith('\ufffd'))
            network.assert_called_once_with(URL)

    def test_export_rejects_formal_rules_existing_and_private(self):
        existing = self.base / 'old.md'
        existing.write_bytes(b'original')
        for target in (self.root / 'raw/unprocessed/x.md', self.root / 'AGENTS.md', existing,
                       self.base / 'AGENTS.md', self.state / 'private/x.md', self.base / 'script.py'):
            with self.subTest(target=target), self.assertRaises((ValueError, OSError)):
                wechat.export_markdown(self.root, target, 'new', state_dir=self.state)
        self.assertEqual(existing.read_bytes(), b'original')
        path = wechat.export_markdown(self.root, self.base / 'new.md', '新文')
        self.assertEqual(path.read_text(encoding='utf-8'), '新文')

    def test_export_rejects_hardlink(self):
        source = self.base / 'source.md'
        source.write_bytes(b'original')
        linked = self.base / 'linked.md'
        os.link(source, linked)
        with self.assertRaises(ValueError):
            wechat.export_markdown(self.root, linked, 'changed')
        self.assertEqual(source.read_bytes(), b'original')

    def test_symlink_ancestor_rejected(self):
        link = self.base / 'linked'
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('系统未授予 symlink 权限')
        with self.assertRaises(ValueError):
            wechat.export_markdown(self.root, link / 'x.md', 'changed')

    def test_cli_preview_full_json_preserved(self):
        for args in ([], ['--full'], ['--json']):
            with self.subTest(args=args), patch.object(wechat_article, 'fetch', return_value=HTML.decode()), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertIsNone(wechat_article.main([URL, *args]))
                self.assertIn('测试标题', output.getvalue())

    def test_cli_legacy_raw_cannot_bypass(self):
        with patch.object(wechat_article, 'write_to_raw_unprocessed') as direct, patch.object(wechat_article, 'fetch') as fetch:
            with self.assertRaises(SystemExit):
                wechat_article.main([URL, '--raw'])
            direct.assert_not_called()
            fetch.assert_not_called()

    def test_cli_raw_actual_host_route(self):
        with patch.object(wechat_article, 'REPO_ROOT', self.root), patch.object(wechat, 'fetch_bytes', return_value=HTML), contextlib.redirect_stdout(io.StringIO()) as output:
            code = wechat_article.main([URL, '--raw', '--state-dir', str(self.state), '--candidate-dir', str(self.candidate)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertIn('"applied": true', output.getvalue())


if __name__ == '__main__':
    unittest.main()
