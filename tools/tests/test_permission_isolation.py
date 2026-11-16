"""T10：仅临时树测试；网关测试不等于当前 Codex app 已强制隔离。"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.wiki_runtime.isolation import Gateway, PermissionDenied, inspect_deployment
from tools.wiki_runtime.isolation.gateway import TOOLS


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.formal = self.root / 'formal'
        self.candidate = self.root / 'candidate'
        self.other = self.root / 'other'
        self.private = self.root / 'trusted'
        for path in (self.formal, self.candidate, self.other, self.private):
            path.mkdir()
        for name in ('AGENTS.md', 'checker.py', 'approval.json', 'page.md'):
            (self.formal / name).write_text('original', encoding='utf-8')
        (self.private / 'journal.json').write_text('trusted', encoding='utf-8')
        self.gateway = Gateway(self.formal, protected_roots=[self.private], max_bytes=256)
        self.worker = self.gateway.bind('worker', candidate_root=self.candidate,
                                        read_scopes={'wiki': self.formal})
        self.reviewer = self.gateway.bind('reviewer', read_scopes={'wiki': self.formal})
        self.auditor = self.gateway.bind('auditor', read_scopes={'wiki': self.formal})
        self.coordinator = self.gateway.bind('coordinator')

    def test_worker_writes_own_candidate_and_reads_fixed_scope(self):
        self.assertEqual(self.worker('candidate_write', {'path': '草稿.md', 'text': '候选'}),
                         {'written_bytes': 6})
        self.assertEqual((self.candidate / '草稿.md').read_text(encoding='utf-8'), '候选')
        self.assertEqual(self.worker('read', {'scope': 'wiki', 'path': 'page.md'}),
                         {'text': 'original'})
        self.assertEqual((self.formal / 'page.md').read_text(), 'original')

    def test_reviewer_and_auditor_read_only(self):
        for channel in (self.reviewer, self.auditor):
            self.assertEqual(channel('read', {'scope': 'wiki', 'path': 'page.md'})['text'], 'original')
            with self.assertRaises(PermissionDenied):
                channel('candidate_write', {'path': 'x.md', 'text': 'x'})

    def test_coordinator_returns_data_without_execution(self):
        request = {'target': 'worker', 'task': 'os.remove("AGENTS.md")'}
        self.assertEqual(self.coordinator('request_task', request),
                         {'request': request, 'executed': False})
        with self.assertRaises(PermissionDenied):
            self.coordinator('read', {'scope': 'wiki', 'path': 'page.md'})
        self.assertTrue((self.formal / 'AGENTS.md').exists())

    def test_all_roles_deny_shell_formal_write_checker_and_credential_tools(self):
        for channel in (self.worker, self.reviewer, self.auditor, self.coordinator):
            for tool in ('shell', 'exec_command', 'write_file', 'apply_patch', 'approve',
                         'apply', 'recover', 'sign_report', 'bind', 'set_role', 'checker_write'):
                with self.subTest(tool=tool), self.assertRaises(PermissionDenied):
                    channel(tool, {'path': str(self.formal / 'checker.py'), 'text': 'pass'})
        self.assertEqual((self.formal / 'checker.py').read_text(), 'original')

    def test_role_and_session_forgery_are_extra_fields(self):
        for extra in ('role', 'session', 'scope', 'approved', 'approval_check', 'verified'):
            args = {'path': 'x.md', 'text': 'x', extra: 'executor'}
            with self.subTest(extra=extra), self.assertRaises(PermissionDenied):
                self.worker('candidate_write', args)

    def test_read_scope_cannot_be_selected_as_arbitrary_root(self):
        for scope in ('trusted', str(self.private), '../trusted', 'candidate'):
            with self.assertRaises(PermissionDenied):
                self.worker('read', {'scope': scope, 'path': 'journal.json'})

    def test_path_traversal_absolute_windows_alias_and_protected_parts_denied(self):
        for path in ('../formal/AGENTS.md', '/formal/x', 'C:/x', 'C:\\x',
                     '//server/share/x', 'a/../x', 'a//x', './x', 'x:stream',
                     'NUL', 'x. ', '.wiki-runtime/approval.json', '.git/config', '.codex/x'):
            with self.subTest(path=path), self.assertRaises(PermissionDenied):
                self.worker('candidate_write', {'path': path, 'text': 'attack'})

    def test_cannot_write_another_worker_candidate(self):
        second = self.gateway.bind('worker', candidate_root=self.other)
        second('candidate_write', {'path': 'other.md', 'text': 'second'})
        with self.assertRaises(PermissionDenied):
            self.worker('candidate_write', {'path': '../other/other.md', 'text': 'attack'})
        self.assertEqual((self.other / 'other.md').read_text(), 'second')

    def test_host_rejects_writable_roots_overlapping_formal_or_private(self):
        for path in (self.formal, self.private, self.root, self.candidate):
            with self.assertRaises(PermissionDenied):
                self.gateway.bind('worker', candidate_root=path)
        (self.candidate / 'nested').mkdir()
        with self.assertRaises(PermissionDenied):
            self.gateway.bind('worker', candidate_root=self.candidate / 'nested')

    def test_host_rejects_invalid_role_and_role_scope_combinations(self):
        with self.assertRaises(PermissionDenied):
            self.gateway.bind('executor')
        with self.assertRaises(PermissionDenied):
            self.gateway.bind('reviewer', candidate_root=self.other)
        with self.assertRaises(PermissionDenied):
            self.gateway.bind('worker')
        with self.assertRaises(PermissionDenied):
            self.gateway.bind('coordinator', read_scopes={'wiki': self.formal})

    def test_symlink_write_and_read_rejected(self):
        link = self.candidate / 'escape'
        try:
            link.symlink_to(self.formal, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'宿主不能创建 symlink：{exc}')
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        with self.assertRaises(PermissionDenied):
            self.worker('candidate_write', {'path': 'escape/AGENTS.md', 'text': 'attack'})

    @unittest.skipUnless(os.name == 'nt', 'Windows junction 专项')
    def test_junction_write_and_registration_rejected(self):
        link = self.candidate / 'junction'
        # 固定 cmd builtin，仅连接临时夹具；不修改账户、ACL 或真实库。
        result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(self.formal)],
                                capture_output=True, text=True)
        if result.returncode:
            self.skipTest('宿主不能创建临时 junction：' + result.stderr)
        self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        with self.assertRaises(PermissionDenied):
            self.worker('candidate_write', {'path': 'junction/AGENTS.md', 'text': 'attack'})
        with self.assertRaises(PermissionDenied):
            self.gateway.bind('reviewer', read_scopes={'escape': link})

    def test_hardlink_write_and_read_rejected(self):
        link = self.candidate / 'hard.md'
        try:
            os.link(self.formal / 'AGENTS.md', link)
        except OSError as exc:
            self.skipTest(f'宿主不能创建 hardlink：{exc}')
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        with self.assertRaises(PermissionDenied):
            self.worker('candidate_write', {'path': 'hard.md', 'text': 'attack'})
        with self.assertRaises(PermissionDenied):
            self.worker('read', {'scope': 'wiki', 'path': 'AGENTS.md'})
        self.assertEqual((self.formal / 'AGENTS.md').read_text(), 'original')

    def test_existing_directory_and_missing_parent_refused(self):
        (self.candidate / 'directory').mkdir()
        for path in ('directory', 'missing/x.md'):
            with self.assertRaises(PermissionDenied):
                self.worker('candidate_write', {'path': path, 'text': 'x'})

    def test_case_alias_rejected_and_original_candidate_can_be_updated(self):
        self.worker('candidate_write', {'path': 'Draft.md', 'text': 'first'})
        with self.assertRaises(PermissionDenied):
            self.worker('candidate_write', {'path': 'draft.md', 'text': 'attack'})
        self.worker('candidate_write', {'path': 'Draft.md', 'text': 'second'})
        self.assertEqual((self.candidate / 'Draft.md').read_text(), 'second')
        self.assertEqual([p.name for p in self.candidate.iterdir()], ['Draft.md'])

    def test_non_json_and_oversized_input_denied(self):
        for args in ({'path': 'x', 'text': lambda: None}, {'path': 'x', 'text': 'x' * 257},
                     [], {'path': 'x', 'text': b'x'}):
            with self.assertRaises(PermissionDenied):
                self.worker('candidate_write', args)

    def test_formal_direct_access_still_possible_in_unisolated_process(self):
        # 重要反证：网关拒绝不能保护仍持有同权限 Path/shell 的宿主。
        (self.formal / 'page.md').write_text('direct bypass', encoding='utf-8')
        report = inspect_deployment(self.formal)
        self.assertEqual(report['status'], 'not_verified')
        self.assertFalse(report['may_apply'])

    def test_preflight_cannot_be_promoted_by_profile_or_forged_probe(self):
        profile = {'profile_version': '1.0', 'backend': 'restricted-tool-gateway',
                   'model_tools_only': True, 'executor_out_of_band': True}
        catalog = {role: sorted(names) for role, names in TOOLS.items()}
        report = inspect_deployment(self.formal, profile=profile, tool_catalog=catalog)
        self.assertTrue(report['tool_catalog_shape_valid'])
        self.assertFalse(report['enforced'])
        for field in ('verified', 'probe_result'):
            forged = dict(profile, **{field: True})
            report = inspect_deployment(self.formal, profile=forged, tool_catalog=catalog)
            self.assertEqual(report['status'], 'not_verified')
            self.assertFalse(report['may_apply'])
            self.assertTrue(any('profile 字段' in p for p in report['problems']))

    def test_unknown_or_missing_catalog_tool_fails_closed(self):
        for extra in ('exec_command', 'approval', 'python', 'write_file'):
            catalog = {role: sorted(names) for role, names in TOOLS.items()}
            catalog['worker'].append(extra)
            self.assertFalse(inspect_deployment(self.formal, tool_catalog=catalog)
                             ['tool_catalog_shape_valid'])

    def test_preflight_read_only_and_cli_never_reports_pass(self):
        before = {p.name: p.read_bytes() for p in self.formal.iterdir()}
        result = subprocess.run([os.sys.executable, '-B', '-m',
                                 'tools.wiki_runtime.isolation', '--root', str(self.formal)],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['may_apply'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.formal.iterdir()})


if __name__ == '__main__':
    unittest.main()
