"""候选视图的临时库验收：不触碰真实资料。"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.wiki_runtime.candidate import CandidateError, CandidateView
from tools.wiki_runtime.contracts import ContractError, bytes_digest, validate


class CandidateViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'vault'
        self.payload = self.base / 'candidate'
        self.root.mkdir()
        self.payload.mkdir()
        self.serial = 0
        self.put(self.root, 'wiki/concepts/分类/旧 页.md', b'old\r\n')
        self.put(self.root, 'raw/unprocessed/材料.md', b'---\r\nprocessing_status: pending_review\r\n---\r\nBODY\x00\xff')

    def put(self, base, path, data):
        target = base / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return bytes_digest(data)

    def candidate(self, changes=()):
        return {'contract_version': '1.0', 'operation_id': 'test-02', 'changes': list(changes)}

    def write(self, path='wiki/sources/新 页.md', data=b'[[old]]\n', *, old=None):
        self.serial += 1
        payload_path = f'payload/{self.serial}.bin'
        return {'action': 'write', 'path': path, 'payload_path': payload_path,
                'sha256': self.put(self.payload, payload_path, data),
                'precondition': {'kind': 'absent'} if old is None else
                {'kind': 'hash', 'sha256': bytes_digest(old)}}

    def view(self, changes=(), **kwargs):
        return CandidateView(self.root, self.candidate(changes), self.payload, **kwargs)

    def test_overlay_new_replaced_and_untouched_recursive_chinese(self):
        old = 'wiki/concepts/分类/旧 页.md'
        view = self.view([self.write(), self.write(old, b'replaced', old=b'old\r\n')])
        self.assertEqual(view.read_text(old), 'replaced')
        self.assertEqual(view.read_bytes('wiki/sources/新 页.md'), b'[[old]]\n')
        self.assertEqual(list(view.iter_paths('wiki')), [old, 'wiki/sources/新 页.md'])
        self.assertEqual((self.root / old).read_bytes(), b'old\r\n')
        validate('dependency_snapshot', view.dependency_snapshot())
        self.assertTrue(view.verify_dependencies())

    def test_move_with_metadata_payload_preserves_formal_raw(self):
        source, target = 'raw/unprocessed/材料.md', 'raw/processed/材料.md'
        original = (self.root / source).read_bytes()
        amended = original.replace(b'pending_review', b'processed')
        move = {'action': 'move', 'source': source, 'source_sha256': bytes_digest(original),
                'path': target, 'precondition': {'kind': 'absent'},
                'payload_path': 'amended.md', 'sha256': self.put(self.payload, 'amended.md', amended)}
        view = self.view([move])
        self.assertFalse(view.exists(source))
        self.assertEqual(view.read_bytes(target), amended)
        with view.materialize(parent=self.base) as materialized:
            self.assertEqual((materialized / target).read_bytes(), amended)
            self.assertFalse((materialized / source).exists())
            self.assertNotEqual(materialized, self.root)
        self.assertFalse(materialized.exists())
        self.assertEqual((self.root / source).read_bytes(), original)
        self.assertFalse((self.root / target).exists())

    def test_plain_move_and_explicit_delete_capability(self):
        source = 'wiki/concepts/分类/旧 页.md'
        move = {'action': 'move', 'source': source, 'source_sha256': bytes_digest(b'old\r\n'),
                'path': 'wiki/concepts/新位置.md', 'precondition': {'kind': 'absent'}}
        self.assertEqual(self.view([move]).read_bytes(move['path']), b'old\r\n')
        delete = {'action': 'delete', 'path': source,
                  'precondition': {'kind': 'hash', 'sha256': bytes_digest(b'old\r\n')}}
        with self.assertRaises(CandidateError):
            self.view([delete])
        view = self.view([delete], allow_deletes=True)
        self.assertFalse(view.exists(source))
        self.assertTrue((self.root / source).exists())

    def test_old_hash_and_absent_preconditions(self):
        with self.assertRaises(CandidateError):
            self.view([self.write('wiki/concepts/分类/旧 页.md')])
        with self.assertRaises(CandidateError):
            self.view([self.write('wiki/concepts/分类/旧 页.md', old=b'wrong')])
        view = self.view([self.write()])
        self.put(self.root, 'wiki/sources/新 页.md', b'user edit')
        with self.assertRaises(CandidateError):
            view.verify_dependencies()

    def test_dependency_edits_and_missing_dependency_creation(self):
        view = self.view()
        path = 'wiki/concepts/分类/旧 页.md'
        self.assertEqual(view.read_bytes(path), b'old\r\n')
        snapshot = view.dependency_snapshot()
        self.put(self.root, path, b'user edit')
        with self.assertRaises(CandidateError):
            view.verify_dependencies(snapshot)
        with self.assertRaises(CandidateError):
            view.read_bytes(path)
        view = self.view()
        self.assertFalse(view.exists('wiki/missing.md'))
        self.put(self.root, 'wiki/missing.md', b'now exists')
        with self.assertRaises(CandidateError):
            view.verify_dependencies()

    def test_unread_baseline_cannot_silently_use_new_version(self):
        view = self.view()
        self.put(self.root, 'wiki/concepts/分类/旧 页.md', b'concurrent')
        with self.assertRaises(CandidateError):
            view.read_bytes('wiki/concepts/分类/旧 页.md')

    def test_enumeration_detects_new_file(self):
        view = self.view()
        list(view.iter_paths())
        self.put(self.root, 'wiki/concepts/用户新增.md', b'new')
        with self.assertRaises(CandidateError):
            view.verify_dependencies()

    def test_payload_tampering_and_candidate_defensive_copy(self):
        change = self.write()
        candidate = self.candidate([change])
        view = CandidateView(self.root, candidate, self.payload)
        candidate['changes'][0]['sha256'] = '0' * 64
        returned = view.candidate
        returned['changes'].clear()
        self.assertEqual(len(view.candidate['changes']), 1)
        self.put(self.payload, change['payload_path'], b'tampered')
        with self.assertRaises(CandidateError):
            view.read_bytes(change['path'])
        with self.assertRaises(CandidateError):
            view.verify_dependencies()
        with self.assertRaises(CandidateError):
            CandidateView(self.root, self.candidate([change]), self.payload)

    def test_duplicate_case_parent_child_and_move_chain_rejected(self):
        parent = self.write('wiki/new')
        child = dict(self.write('wiki/unrelated'), path='wiki/new/child.md')
        for changes in ([self.write('wiki/A.md'), self.write('wiki/a.md')], [parent, child]):
            with self.assertRaises(ContractError):
                self.view(changes)
        with self.assertRaises(CandidateError):
            self.view([self.write('wiki/concepts/分类/旧 页.md/child.md')])
        with self.assertRaises(CandidateError):
            self.view([self.write('wiki/CONCEPTS/new.md')])
        with self.assertRaises(CandidateError):
            self.view([self.write('wiki/concepts')])
        move = {'action': 'move', 'source': 'wiki/a', 'source_sha256': '0' * 64,
                'path': 'wiki/b', 'precondition': {'kind': 'absent'}}
        other = dict(move, source='wiki/b', path='wiki/c')
        with self.assertRaises(ContractError):
            self.view([move, other])

    def test_escape_and_payload_escape_rejected(self):
        for path in ('../outside', '/absolute', 'C:/outside', 'wiki\\file', 'wiki/a:stream'):
            change = self.write()
            change['path'] = path
            with self.assertRaises(ContractError):
                self.view([change])
        change = self.write()
        change['payload_path'] = '../outside'
        with self.assertRaises(ContractError):
            self.view([change])

    def test_materialization_cannot_write_under_inputs(self):
        view = self.view()
        for parent in (self.root, self.payload, self.root / 'wiki'):
            with self.assertRaises(CandidateError):
                with view.materialize(parent=parent):
                    self.fail('unsafe materialization accepted')
        with self.assertRaises(CandidateError):
            CandidateView(self.root, self.candidate(), self.root)

    def test_hardlink_rejected(self):
        source = self.root / 'wiki/concepts/分类/旧 页.md'
        try:
            os.link(source, self.root / 'hardlinked.md')
        except OSError as exc:
            self.skipTest(f'平台不支持 hardlink: {exc}')
        with self.assertRaises(CandidateError):
            self.view()

    def test_symlink_escape_and_payload_link_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.put(outside, 'secret.md', b'outside')
        try:
            (self.root / 'linked').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'平台无 symlink 权限: {exc}')
        with self.assertRaises(CandidateError):
            self.view()
        (self.root / 'linked').unlink()
        (self.payload / 'linked').symlink_to(outside, target_is_directory=True)
        change = self.write()
        change.update(payload_path='linked/secret.md', sha256=bytes_digest(b'outside'))
        with self.assertRaises(CandidateError):
            self.view([change])

    @unittest.skipUnless(os.name == 'nt', 'Windows junction 验收')
    def test_junction_escape_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        link = self.root / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            self.skipTest('当前环境无法创建 junction')
        self.addCleanup(link.rmdir)
        with self.assertRaises(CandidateError):
            self.view()
        with self.assertRaises(CandidateError):
            CandidateView(link, self.candidate(), self.payload)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction 验收')
    def test_payload_junction_and_root_replacement_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.put(outside, 'secret.md', b'outside')
        link = self.payload / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            self.skipTest('当前环境无法创建 junction')
        self.addCleanup(lambda: link.rmdir() if link.exists() else None)
        change = self.write()
        change.update(payload_path='junction/secret.md', sha256=bytes_digest(b'outside'))
        with self.assertRaises(CandidateError):
            self.view([change])
        view = self.view([self.write()])
        self.payload.rename(self.base / 'candidate-original')
        moved_link = self.base / 'candidate-original' / 'junction'
        self.addCleanup(lambda: moved_link.rmdir() if moved_link.exists() else None)
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.payload), str(outside)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0)
        # 根本身被替换同样拒绝，不能只检查根下各段。
        with self.assertRaises(CandidateError):
            view.verify_dependencies()
        self.payload.rmdir()
        moved_link.rmdir()

    def test_external_snapshot_cannot_omit_stale_internal_dependency(self):
        view = self.view()
        path = 'wiki/concepts/分类/旧 页.md'
        view.read_bytes(path)
        self.put(self.root, path, b'changed')
        empty = {'contract_version': '1.0', 'operation_id': 'test-02', 'files': []}
        with self.assertRaises(CandidateError):
            view.verify_dependencies(empty)

    def test_snapshot_operation_identity_and_strict_utf8(self):
        view = self.view()
        with self.assertRaises(UnicodeDecodeError):
            view.read_text('raw/unprocessed/材料.md')
        snapshot = view.dependency_snapshot()
        snapshot['operation_id'] = 'wrong'
        with self.assertRaises(CandidateError):
            view.verify_dependencies(snapshot)


if __name__ == '__main__':
    unittest.main()
