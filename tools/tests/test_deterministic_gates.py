"""确定性门禁临时库回归；不触及业务资料。"""
import copy
import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.wiki_runtime.contracts import bytes_digest, candidate_digest, digest, ContractError
from tools.wiki_runtime.gates import run_gates, raw_parts


class FakeView:
    def __init__(self, root, candidate, payload):
        self.root, self.candidate, self.payload = root, candidate, payload

    def read_bytes(self, path):
        for c in self.candidate['changes']:
            if c['path'] == path:
                return self.payload[c['payload_path']] if 'payload_path' in c else (self.root / c['source']).read_bytes()
        return (self.root / path).read_bytes()

    @contextlib.contextmanager
    def materialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            shutil.copytree(self.root, target, dirs_exist_ok=True)
            for c in self.candidate['changes']:
                path = target / c['path']
                if c['action'] == 'delete':
                    path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self.read_bytes(c['path']))
                if c['action'] == 'move':
                    (target / c['source']).unlink()
            yield target


class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('AGENTS.md', '# 规则')
        self.write('tools/wiki_runtime/contracts/rules.json', '{}')
        self.write('wiki/index.md', '# 索引')
        self.write('wiki/log.md', '# 日志')
        self.write('raw/index.md', '# 素材')
        self.payload, self.changes = {}, []

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode('utf-8') if isinstance(text, str) else text)

    def change(self, path, text, action='write', source=None):
        data = text.encode('utf-8') if isinstance(text, str) else text
        payload = str(len(self.payload)) + '.md'
        self.payload[payload] = data
        old = self.root / path
        pre = dict(kind='hash', sha256=bytes_digest(old.read_bytes())) if old.exists() else dict(kind='absent')
        c = dict(action=action, path=path, payload_path=payload, sha256=bytes_digest(data), precondition=pre)
        if source:
            c.update(source=source, source_sha256=bytes_digest((self.root / source).read_bytes()))
        self.changes.append(c)

    def inputs(self, operation='health'):
        c = dict(contract_version='1.0', operation_id='test', changes=self.changes)
        s = dict(contract_version='1.0', operation_id='test', files=[])
        m = dict(contract_version='1.0', operation_id='test', operation_type=operation, task='测试', input_refs=[],
                 allowed_paths=[p for x in self.changes for p in [x['path']] + ([x['source']] if 'source' in x else [])],
                 rules_path='AGENTS.md', rules_digest=bytes_digest((self.root / 'AGENTS.md').read_bytes()),
                 mapping_digest=bytes_digest((self.root / 'tools/wiki_runtime/contracts/rules.json').read_bytes()),
                 validator_version='gates-1.0', review_prompt_version='none', dependencies_digest=digest(s),
                 candidate_digest=candidate_digest(c), round=1, required_gates=['G0', 'G1', 'G2'], authorization_refs=[])
        return m, c, s, FakeView(self.root, c, self.payload)

    def run_case(self, operation='health'):
        return {r['gate']: r for r in run_gates(*self.inputs(operation))}

    def test_read_only_no_mutation_and_bound_reports(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.run_case()
        self.assertEqual(result['G0']['result'], 'pass')
        self.assertEqual(result['G1']['result'], 'pass')
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_bad_contract_raises(self):
        args = self.inputs()
        args[0]['unknown'] = True
        self.assertRaises(ContractError, run_gates, *args)

    def test_binding_scope_and_versions(self):
        self.change('wiki/meta/x.md', '# 页面')
        for key, value in [('candidate_digest', '0' * 64), ('rules_digest', '0' * 64), ('mapping_digest', '0' * 64),
                           ('dependencies_digest', '0' * 64), ('validator_version', 'unknown'), ('review_prompt_version', 'unknown'), ('allowed_paths', [])]:
            with self.subTest(key=key):
                args = self.inputs()
                args[0][key] = value
                self.assertNotEqual(run_gates(*args)[0]['result'], 'pass')

    def test_changed_dependency_rejected(self):
        args = self.inputs()
        args[2]['files'].append(dict(path='wiki/log.md', precondition=dict(kind='hash', sha256='0' * 64)))
        args[0]['dependencies_digest'] = digest(args[2])
        self.assertEqual(run_gates(*args)[0]['result'], 'fail')

    def test_changed_payload_rejected(self):
        self.change('wiki/meta/a.md', '# a')
        args = self.inputs()
        self.payload['0.md'] = b'# tampered'
        self.assertEqual(run_gates(*args)[0]['result'], 'fail')

    def test_raw_body_byte_protection(self):
        self.write('raw/unprocessed/a.md', b'---\r\nprocessing_status: unprocessed\r\n---\r\nbody\r\n')
        self.change('raw/unprocessed/a.md', b'---\r\nprocessing_status: pending_review\r\n---\r\nbody\n')
        self.assertEqual(self.run_case()['G1']['result'], 'fail')

    def test_raw_non_whitelist_change(self):
        self.write('raw/unprocessed/a.md', '---\ntitle: 原题\n---\n正文')
        self.change('raw/unprocessed/a.md', '---\ntitle: 篡改\n---\n正文')
        self.assertEqual(self.run_case()['G1']['findings'][0]['rule_id'], 'RAW-002')

    def test_raw_allowed_metadata_and_bom(self):
        self.write('raw/unprocessed/a.md', b'\xef\xbb\xbf---\r\ntitle: old\r\n---\r\nbody')
        self.change('raw/unprocessed/a.md', b'\xef\xbb\xbf---\r\ntitle: old\r\nprocessing_status: pending_review\r\n---\r\nbody')
        self.assertEqual(self.run_case()['G1']['result'], 'pass')

    def test_malformed_yaml_fails_closed(self):
        for data in [b'---\nkey: a\nkey: b\n---\nbody', b'---\nx: |\n  hidden\n---\nbody', b'---\nx: a\n nested: changed\n---\nbody', b'---\nx: "unfinished\n---\nbody', b'---\nx: a']:
            self.assertRaises(ValueError, raw_parts, data)

    def test_move_payload_protects_body(self):
        self.write('raw/unprocessed/a.md', '---\nprocessing_status: pending_review\n---\n正文')
        self.change('raw/processed/a.md', '---\nprocessing_status: processed\nreviewed_at: 2026-10-26\n---\n正文', action='move', source='raw/unprocessed/a.md')
        self.assertEqual(self.run_case('approve')['G1']['result'], 'pass')

    def test_invalid_heading_anchor_and_local_anchor(self):
        self.change('wiki/meta/a.md', '# 目标\n[[#不存在]]')
        self.assertTrue(any('锚点' in f['evidence'] for f in self.run_case()['G2']['findings']))

    def test_valid_anchor_alias(self):
        self.change('wiki/meta/a.md', '# 目标\n[[#目标|别名]]')
        self.assertFalse(any('锚点' in f['evidence'] for f in self.run_case()['G2']['findings']))

    def test_recommendations_not_mandatory(self):
        self.change('wiki/concepts/nested/a.md', '# 新页\n' + '中文内容。' * 60)
        self.change('wiki/index.md', '[[concepts/nested/a]]')
        self.change('wiki/log.md', '# 更新')
        fm = [x for x in self.run_case()['G2']['findings'] if x['rule_id'] == 'FM-001']
        self.assertTrue(fm)
        self.assertTrue(all(x['severity'] == 'warning' for x in fm))

    def test_new_source_missing_and_pending_companions(self):
        self.write('raw/unprocessed/a.md', '---\nprocessing_status: unprocessed\n---\n正文')
        self.change('raw/unprocessed/a.md', '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/missing]]"\n---\n正文')
        result = self.run_case('ingest')['G2']
        self.assertTrue(any('来源页映射' in x['evidence'] for x in result['findings']))
        self.assertTrue(any('配套' in x['evidence'] for x in result['findings']))

    def test_ingest_cannot_move_processed(self):
        self.write('raw/unprocessed/a.md', '正文')
        self.change('raw/processed/a.md', '正文', action='move', source='raw/unprocessed/a.md')
        self.assertEqual(self.run_case('ingest')['G0']['result'], 'fail')

    def test_reverse_edge_two_channels_only_ingest_new_to_old(self):
        for relation, body in [('', '[[sources/new]]'), ('related_sources:\n  - "[[sources/new]]"\n', ''), ('', '')]:
            with self.subTest(relation=relation, body=body):
                self.payload, self.changes = {}, []
                self.write('wiki/entities/deep/old.md', '---\nupdated: 2026-10-25\n---\n# 旧页')
                self.change('wiki/entities/deep/old.md', '---\nupdated: 2026-10-26\n' + relation + '---\n# 旧页\n' + body)
                self.change('wiki/sources/new.md', '---\ntype: source\n---\n# 新来源\n[[entities/old]]')
                findings = self.run_case('ingest')['G2']['findings']
                self.assertTrue(any('双通道' in x['evidence'] for x in findings))

    def test_g3_g4_g5_never_fake_pass(self):
        args = self.inputs()
        args[0]['required_gates'] += ['G3', 'G4', 'G5']
        reports = run_gates(*args)
        self.assertTrue(all(r['result'] == 'unsupported' for r in reports if r['gate'] in ('G3', 'G4', 'G5')))

    def test_reverse_edge_both_channels_accepted(self):
        self.write('wiki/entities/deep/old.md', '---\nupdated: 2026-10-25\n---\n# 旧页')
        self.change('wiki/entities/deep/old.md', '---\nupdated: 2026-10-26\nrelated_sources:\n  - "[[sources/new]]"\n---\n# 旧页\n证据来自 [[sources/new]]')
        self.change('wiki/sources/new.md', '---\ntype: source\n---\n# 新来源\n[[entities/old]]')
        self.assertFalse(any(x['rule_id'] == 'REL-001' for x in self.run_case('ingest')['G2']['findings']))

    def test_capture_accepts_new_binary_assets(self):
        self.change('raw/assets/original.pdf', b'%PDF-1.7\x00\xff\xfe\x80')
        reports = self.run_case('capture')
        self.assertEqual(reports['G0']['result'], 'pass')
        self.assertEqual(reports['G1']['result'], 'pass')

    def test_existing_binary_assets_immutable(self):
        self.write('raw/assets/a.png', b'\x89PNG\xff')
        self.change('raw/assets/a.png', b'\x89PNG\xfe')
        self.assertEqual(self.run_case('capture')['G1']['result'], 'fail')

    def test_operation_scope_even_with_allowed_paths(self):
        for path in ('AGENTS.md', 'tools/evil.py', '.wiki-runtime/state.json'):
            with self.subTest(path=path):
                self.changes, self.payload = [], {}
                self.change(path, '# changed')
                self.assertEqual(self.run_case('ingest')['G0']['result'], 'fail')

    def test_raw_move_cannot_escape_to_wiki(self):
        self.write('raw/unprocessed/a.md', '正文')
        self.change('wiki/sources/stolen.md', '正文', action='move', source='raw/unprocessed/a.md')
        self.assertEqual(self.run_case('move')['G0']['result'], 'fail')

    def test_group_partial_processing_is_rejected(self):
        for key in ('a', 'b'):
            self.write('raw/unprocessed/' + key + '.md', '---\nprocessing_status: pending_review\ningest_group: same\n---\n正文')
        self.change('raw/unprocessed/a.md', '---\nprocessing_status: pending_review\ningest_group: same\n---\n正文')
        self.assertTrue(any('同批次' in f['evidence'] for f in self.run_case('ingest')['G2']['findings']))

    def test_approve_stale_raw_path_is_never_baseline_exempt(self):
        self.write('raw/unprocessed/a.md', '---\nprocessing_status: pending_review\n---\n正文')
        self.write('wiki/sources/a.md', '---\nraw_note: "[[raw/unprocessed/a]]"\n---\n原始资料 [[raw/unprocessed/a]]')
        self.change('raw/processed/a.md', '---\nprocessing_status: processed\nreviewed_at: 2026-10-26\n---\n正文', action='move', source='raw/unprocessed/a.md')
        self.assertTrue(any('残留旧 raw 路径' in f['evidence'] for f in self.run_case('approve')['G2']['findings']))


if __name__ == '__main__':
    unittest.main()
