"""公共契约的正反例；不读写真实业务状态。"""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.wiki_runtime.contracts import (
    VERSION, ContractError, validate, validate_path, resolve_path,
    canonical_json, digest, bytes_digest, candidate_digest, bindings_match,
    validate_transition,
)

CONTRACTS = Path(__file__).resolve().parents[1] / 'wiki_runtime' / 'contracts'
ZERO = '0' * 64


def sample(kind):
    return json.loads((CONTRACTS / 'examples' / f'{kind}.valid.json').read_text(encoding='utf-8'))


class ContractTests(unittest.TestCase):
    def test_all_examples(self):
        for path in sorted((CONTRACTS / 'examples').glob('*.json')):
            kind, expected, _ = path.name.split('.')
            with self.subTest(sample=path.name):
                value = json.loads(path.read_text(encoding='utf-8'))
                if expected == 'valid':
                    self.assertIs(validate(kind, value), value)
                else:
                    with self.assertRaises(ContractError):
                        validate(kind, value)

    def test_version_operation_and_extra_field_refused(self):
        for key, value in [('contract_version', '2.0'), ('contract_version', '1.1'),
                           ('operation_type', 'auto_approve'), ('human_confirmed', True)]:
            record = sample('manifest')
            record[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ContractError):
                validate('manifest', record)

    def test_unknown_input_and_kind(self):
        record = sample('source_package')
        record['input_type'] = 'application/executable'
        with self.assertRaises(ContractError):
            validate('source_package', record)
        with self.assertRaises(ContractError):
            validate('../manifest', {})

    def test_hash_is_order_independent_but_byte_exact(self):
        self.assertEqual(digest({'中': [1], 'a': True}), digest({'a': True, '中': [1]}))
        self.assertNotEqual(bytes_digest(b'a\r\n'), bytes_digest(b'a\n'))
        self.assertNotEqual(bytes_digest(b'\xef\xbb\xbfa'), bytes_digest(b'a'))
        self.assertNotEqual(digest([1, 2]), digest([2, 1]))
        for value in [float('nan'), float('inf'), {'x': (1, 2)}, {1: 'x'}, '\ud800']:
            with self.subTest(value=repr(value)), self.assertRaises(ContractError):
                canonical_json(value)

    def test_paths_allow_unicode_nested_classification(self):
        path = 'wiki/concepts/分类/更深一层/中文 空格.md'
        self.assertEqual(validate_path(path), path)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(resolve_path(tmp, path).is_relative_to(Path(tmp).resolve()))

    def test_unsafe_windows_paths_refused(self):
        paths = ['', '/tmp/a', '//server/a', 'C:/a', 'C:a', 'a\\b', '../a', 'a/../b',
                 './a', 'a//b', 'a/', 'raw/a.md:secret', 'a/CON.md', 'NUL',
                 'x/lpt9.txt', 'AUX.foo', 'a./b', 'a /b', 'a\x00b', 'a/*']
        for path in paths:
            with self.subTest(path=path), self.assertRaises(ContractError):
                validate_path(path)

    def test_symlink_escape_refused_if_supported(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            link = Path(tmp) / 'escape'
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('宿主不允许建立 symlink')
            with self.assertRaises(ContractError):
                resolve_path(tmp, 'escape/file.md')

    def test_absence_is_explicit(self):
        record = sample('candidate')
        for wrong in [None, '', {'sha256': ZERO}, {'kind': 'absent', 'sha256': ZERO}]:
            record['changes'][0]['precondition'] = wrong
            with self.subTest(wrong=wrong), self.assertRaises(ContractError):
                validate('candidate', record)
        record['changes'][0]['precondition'] = {'kind': 'absent'}
        validate('candidate', record)

    def test_candidate_digest_binds_payload_and_preconditions(self):
        record = sample('candidate')
        initial = candidate_digest(record)
        record['changes'][0]['sha256'] = 'a' * 64
        self.assertNotEqual(initial, candidate_digest(record))
        record = sample('candidate')
        record['changes'][0]['precondition'] = {'kind': 'absent'}
        self.assertNotEqual(initial, candidate_digest(record))

    def test_conflicting_candidate_paths(self):
        for other in ['WIKI/INDEX.MD', 'wiki/index.md/child']:
            record = sample('candidate')
            second = copy.deepcopy(record['changes'][0])
            second['path'] = other
            record['changes'].append(second)
            with self.subTest(other=other), self.assertRaises(ContractError):
                validate('candidate', record)

    def test_move_and_move_update(self):
        move = {'action': 'move', 'source': 'raw/unprocessed/a.md', 'source_sha256': ZERO,
                'path': 'raw/processed/a.md', 'precondition': {'kind': 'absent'}}
        record = {'contract_version': VERSION, 'operation_id': 'approve-1', 'changes': [move]}
        validate('candidate', record)
        move['payload_path'] = 'payload/a.md'
        with self.assertRaises(ContractError):
            validate('candidate', record)
        move['sha256'] = 'a' * 64
        validate('candidate', record)
        del move['payload_path']
        with self.assertRaises(ContractError):
            validate('candidate', record)

    def test_move_chain_refused(self):
        move = {'action': 'move', 'source': 'a.md', 'source_sha256': ZERO,
                'path': 'b.md', 'precondition': {'kind': 'absent'}}
        second = {**move, 'source': 'b.md', 'path': 'c.md'}
        with self.assertRaises(ContractError):
            validate('candidate', {'contract_version': VERSION, 'operation_id': 'x', 'changes': [move, second]})

    def test_report_bindings_invalidate_each_version(self):
        report = sample('gate_report')
        keys = ('operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
                'mapping_digest', 'validator_version', 'review_prompt_version')
        expected = {k: report[k] for k in keys}
        self.assertTrue(bindings_match(report, **expected))
        for key in keys:
            changed = {**expected, key: 'changed'}
            with self.subTest(key=key):
                self.assertFalse(bindings_match(report, **changed))

    def test_blocking_findings_cannot_pass(self):
        finding = {'rule_id': 'RAW-001', 'severity': 'blocking', 'category': 'changed_body',
                   'target': 'raw/a.md', 'evidence': '字节变化', 'expected': '正文保持不变', 'repairable': True}
        for kind in ['gate_report', 'review_report']:
            record = sample(kind)
            record['findings'] = [finding]
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                validate(kind, record)

    def test_quality_claim_contradiction(self):
        for field in ['errors', 'missing']:
            record = sample('source_package')
            record['quality'][field] = ['缺页']
            with self.subTest(field=field), self.assertRaises(ContractError):
                validate('source_package', record)

    def test_no_model_authorization_fields(self):
        for kind in ['candidate', 'review_report', 'appeal_report']:
            record = sample(kind)
            record['human_confirmed'] = True
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                validate(kind, record)

    def test_state_machine_separate_from_raw(self):
        validate_transition('prepared', 'checking')
        validate_transition('applying', 'recovery_required')
        for before, after in [('prepared', 'applied'), ('awaiting_human', 'applying'),
                              ('failed', 'applied'), ('unprocessed', 'pending_review')]:
            with self.subTest(before=before, after=after), self.assertRaises(ContractError):
                validate_transition(before, after)

    def test_mapping_preserves_recommendations_and_dispute(self):
        mapping = json.loads((CONTRACTS / 'rules.json').read_text(encoding='utf-8'))
        rules = {rule['rule_id']: rule for rule in mapping['rules']}
        self.assertEqual(rules['FM-001']['level'], 'recommended')
        self.assertEqual(rules['RAW-001']['level'], 'mandatory')
        self.assertEqual(mapping['disputes'][0]['authority'], 'AGENTS.md')


if __name__ == '__main__':
    unittest.main()
