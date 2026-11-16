"""Q1 离线契约：真实失败原件、反例、来源/版本与 Schema 对照，无模型。"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.learning_book.contracts import DeliveryError, canonical, sha256
from tools.learning_book.question_spec import (MAX_BYTES, MAX_TEXT, TEMPLATE_FIELDS,
    check_question, compare_questions, extract_authored, question_digest, read_spec,
    render_variant_template, spec_digest, validate_spec, verify_inputs)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / 'tools/learning_book/examples/questions'


class QuestionSpecTests(unittest.TestCase):
    def setUp(self):
        self.authored = read_spec(EXAMPLES / 'authored.json')
        self.variant = read_spec(EXAMPLES / 'variant.json')
        self.qid = self.authored['items'][0]['questionId']
        self.question = extract_authored(self.authored, self.qid)
        self.inputs = {'source_inputs': {'baiyu': {'sourceVersionId': '1',
            'content': (EXAMPLES / 'source.md').read_bytes()}},
            'lesson_ref': self.authored['lessonRef'], 'lesson_bytes': (EXAMPLES / 'lesson.md').read_bytes()}

    def assert_invalid(self, spec):
        with self.assertRaises(DeliveryError):
            validate_spec(spec)


    def test_QN02_negated_scenario_is_not_semantically_approved(self):
        self.question['question'] = 'BY-042 核验 F-017 与 F-071，不存在编号不一致。应如何处置？'
        result = check_question(self.variant, self.qid, self.question)
        self.assertFalse(result['blocking'])
        self.assertEqual(result['status'], 'pending_review')
        self.assertEqual(result['semanticStatus'], 'not_evaluated')

    def test_QN03_equivalent_wording_does_not_require_trigger_word(self):
        self.question['question'] = 'BY-042 纸单写 F-017，封签却为 F-071。应如何处置？'
        result = check_question(self.variant, self.qid, self.question)
        self.assertEqual(result['findings'], [])
        self.assertEqual(result['status'], 'pending_review')

    def test_QN04_two_misconceptions_may_use_same_rule(self):
        spec = validate_spec(self.authored)
        self.assertEqual(len(spec['items'][0]['misconceptions']), 2)
        self.assertIn('C3', spec['items'][0]['misconceptions'][1]['reason'])
        self.assertEqual(check_question(spec, self.qid, self.question)['status'], 'pending_review')

    def test_QN05_option_order_text_answer_and_explanation_change_version(self):
        for kind in ('order', 'text', 'answer', 'explanation'):
            changed = deepcopy(self.question)
            if kind == 'order':
                changed['options'] = {k: changed['options'][k] for k in 'BACD'}
            elif kind == 'text':
                changed['options']['B'] += '（改动）'
            elif kind == 'answer':
                changed['correct_answer'] = 'B'
            else:
                changed['explanation'] += '（改动）'
            with self.subTest(kind=kind):
                result = compare_questions(self.question, changed)
                self.assertFalse(result['sameContent'])
                self.assertTrue(result['requiresReview'])
        self.assertTrue(compare_questions(self.question, deepcopy(self.question))['sameContent'])

    def test_QN06_source_lesson_versions_and_bytes_are_verified(self):
        self.assertEqual(verify_inputs(self.authored, **self.inputs)['status'], 'verified')
        for kind in ('source_version', 'source_bytes', 'lesson_ref', 'lesson_bytes', 'missing_source'):
            inputs = deepcopy(self.inputs)
            if kind == 'source_version':
                inputs['source_inputs']['baiyu']['sourceVersionId'] = '2'
            elif kind == 'source_bytes':
                inputs['source_inputs']['baiyu']['content'] += b'changed'
            elif kind == 'missing_source':
                inputs['source_inputs'] = {}
            elif kind == 'lesson_ref':
                inputs['lesson_ref'] += '@2'
            else:
                inputs['lesson_bytes'] += b'changed'
            with self.subTest(kind=kind), self.assertRaises(DeliveryError):
                verify_inputs(self.authored, **inputs)

    def test_QN06_same_id_changed_spec_requires_new_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spec.json'
            path.write_bytes(canonical(self.authored))
            frozen = spec_digest(read_spec(path))
            changed = deepcopy(self.authored)
            changed['objectives'][0]['description'] += '（改动）'
            path.write_bytes(canonical(changed))
            with self.assertRaises(DeliveryError) as caught:
                read_spec(path, expected_digest=frozen)
            self.assertEqual(caught.exception.code, 'question_spec_changed')

    def test_QN06_references_must_close(self):
        for kind in ('source', 'objective', 'misconception'):
            spec = deepcopy(self.authored)
            item = spec['items'][0]
            if kind == 'source': item['sourceRefs'] = ['missing']
            elif kind == 'objective': item['targetObjectiveId'] = 'missing'
            else: item['misconceptions'][0]['sourceRefs'] = ['missing']
            with self.subTest(kind=kind): self.assert_invalid(spec)

    def test_QN07_invalid_modes_type_answer_identity_and_explanation(self):
        for kind in ('mixed', 'type', 'multi_answer', 'duplicate', 'empty', 'id_mismatch'):
            spec = deepcopy(self.authored); item = spec['items'][0]
            if kind == 'mixed': item['referenceTemplate'] = self.variant['items'][0]['referenceTemplate']
            elif kind == 'type': item['authoredItem']['question_type'] = 'short_answer'
            elif kind == 'multi_answer': item['authoredItem']['correct_answer'] = ['A', 'B']
            elif kind == 'duplicate': spec['items'].append(deepcopy(item))
            elif kind == 'empty': item['authoredItem']['explanation'] = ' '
            else: item['authoredItem']['question_id'] = 'other'
            with self.subTest(kind=kind): self.assert_invalid(spec)

    def test_QN08_unknown_fields_rejected_at_every_object_level(self):
        for path in ((), ('sources', 0), ('objectives', 0), ('items', 0),
                     ('items', 0, 'criteria'), ('items', 0, 'misconceptions', 0),
                     ('items', 0, 'authoredItem'), ('items', 0, 'authoredItem', 'options')):
            spec = deepcopy(self.authored); target = spec
            for part in path: target = target[part]
            target['extra'] = 'no'
            with self.subTest(path=path): self.assert_invalid(spec)

    def test_QN08_duplicate_keys_and_invalid_json_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spec.json'
            for raw in (b'{"schema":"x","schema":"y"}', b'{"n":NaN}', b'{', b'\xff', b'[' * 1100):
                path.write_bytes(raw)
                with self.subTest(raw=raw[:20]), self.assertRaises(DeliveryError): read_spec(path)
            with self.assertRaises(DeliveryError): read_spec(path.with_name('absent.json'))

    def test_QN08_byte_boundary_and_multibyte_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spec.json'; data = canonical(self.authored)
            path.write_bytes(data + b' ' * (MAX_BYTES - len(data)))
            self.assertEqual(read_spec(path)['specId'], self.authored['specId'])
            path.write_bytes(path.read_bytes() + b' ')
            with self.assertRaises(DeliveryError): read_spec(path)
        spec = deepcopy(self.authored)
        spec['items'][0]['hints'] = [('中' * 16000) + str(i) for i in range(8)]
        self.assert_invalid(spec)  # 字符上限未到，但 UTF-8 总字节已超限。

    def test_spec_changed_during_read_is_rejected(self):
        path = EXAMPLES / 'authored.json'; stat = path.stat()
        before = SimpleNamespace(st_dev=stat.st_dev, st_ino=stat.st_ino,
                                 st_size=stat.st_size, st_mtime_ns=stat.st_mtime_ns)
        after = deepcopy(before); after.st_mtime_ns += 1
        with patch('tools.learning_book.question_spec.os.fstat', side_effect=[before, after]):
            with self.assertRaises(DeliveryError) as caught:
                read_spec(path)
        self.assertEqual(caught.exception.code, 'question_spec_changed')

    def test_duplicate_source_objective_misconception_and_literal_conflict(self):
        for kind in ('source', 'objective', 'misconception', 'literal'):
            spec = deepcopy(self.authored)
            if kind == 'source': spec['sources'].append(deepcopy(spec['sources'][0]))
            elif kind == 'objective': spec['objectives'].append(deepcopy(spec['objectives'][0]))
            elif kind == 'misconception': spec['items'][0]['misconceptions'].append(deepcopy(spec['items'][0]['misconceptions'][0]))
            else: spec['items'][0]['criteria']['forbiddenLiterals'] = ['BY-042']
            with self.subTest(kind=kind): self.assert_invalid(spec)

    def test_QN09_rendered_template_contains_verified_source_goal_and_exception(self):
        first = render_variant_template(self.variant, self.qid, **self.inputs)
        second = render_variant_template(deepcopy(self.variant), self.qid, **self.inputs)
        self.assertEqual(first, second)
        self.assertEqual(set(first), TEMPLATE_FIELDS)
        body = first['reference_question']
        for required in ('编号冲突', '不豁免', '例外', 'scenarioConditions', 'allowedChanges',
                         'sourceVersionId', self.variant['lessonSha256'], spec_digest(self.variant)):
            self.assertIn(required, body)
        self.assertEqual(first['reference_answer'], self.variant['items'][0]['referenceTemplate']['reference_answer'])

    def test_QN09_render_overflow_rejected_not_truncated(self):
        spec = deepcopy(self.variant)
        spec['items'][0]['referenceTemplate']['reference_question'] = 'x' * MAX_TEXT
        with self.assertRaises(DeliveryError): render_variant_template(spec, self.qid, **self.inputs)

    def test_QN09_excerpt_must_be_actual_verbatim_bytes(self):
        spec = deepcopy(self.variant); spec['sources'][0]['excerpt'] = '并不存在的规则'
        with self.assertRaises(DeliveryError): render_variant_template(spec, self.qid, **self.inputs)

    def test_QN10_authored_extraction_preserves_all_fields_and_order(self):
        self.authored['items'][0]['authoredItem']['options'] = {k: self.question['options'][k] for k in 'DACB'}
        result = extract_authored(self.authored, self.qid)
        self.assertEqual(result, self.authored['items'][0]['authoredItem'])
        self.assertEqual(list(result['options']), list('DACB'))
        result['options']['A'] = 'mutation'
        self.assertNotEqual(result, self.authored['items'][0]['authoredItem'])
        self.assertNotEqual(spec_digest(self.authored), spec_digest(read_spec(EXAMPLES / 'authored.json')))

    def test_check_blocks_forbidden_literals_and_wrong_id(self):
        spec = deepcopy(self.variant); spec['items'][0]['criteria']['forbiddenLiterals'] = ['新造规则']
        self.question['explanation'] += '新造规则'; self.question['question_id'] = 'wrong'
        result = check_question(spec, self.qid, self.question)
        self.assertEqual({f['code'] for f in result['findings']}, {'forbidden_literal_present', 'question_id_mismatch'})
        self.assertEqual(result['status'], 'blocked')

    def test_invalid_final_question_is_diagnostic_not_crash(self):
        for value in (None, [], {}, dict(self.question, correct_answer=['A'])):
            with self.subTest(value=value):
                result = check_question(self.variant, self.qid, value)
                self.assertTrue(result['blocking']); self.assertIsNone(result['questionDigest'])

    def test_schema_and_validator_agree_on_structural_samples(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / 'tools/learning_book/schemas/question-spec.schema.json').read_bytes())
        Draft202012Validator.check_schema(schema); validator = Draft202012Validator(schema)
        for path in [EXAMPLES / 'authored.json', EXAMPLES / 'variant.json', *sorted((EXAMPLES / 'invalid').glob('*.json'))]:
            value = json.loads(path.read_bytes()); expected = path.parent.name != 'invalid'
            with self.subTest(path=path.name):
                self.assertEqual(validator.is_valid(value), expected)
                if expected: validate_spec(value)
                else: self.assert_invalid(value)
        # 引用闭合、跨记录 ID 唯一及字节界限属于显式的应用附加规则。
        self.assertIn('x-relationalRules', schema)

    def test_schema_and_validator_agree_on_nested_structural_rejections(self):
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(json.loads((ROOT / 'tools/learning_book/schemas/question-spec.schema.json').read_bytes()))
        replacements = [(['sources', 0, 'sourceId'], True), (['sources', 0, 'sha256'], 'A' * 64),
            (['items', 0, 'questionId'], 'bad\nidentifier'),
            (['items', 0, 'authoredItem', 'explanation'], '  '),
            (['items', 0, 'authoredItem', 'options'], {'A': 'only one'}),
            (['items', 0, 'criteria', 'scenarioConditions'], []),
            (['items', 0, 'hints'], [str(n) for n in range(9)]),
            (['items', 0, 'criteria', 'requiredLiterals'], ['same', 'same'])]
        for path, value in replacements:
            spec = deepcopy(self.authored); parent = spec
            for part in path[:-1]: parent = parent[part]
            parent[path[-1]] = value
            with self.subTest(path=path):
                self.assertFalse(validator.is_valid(spec)); self.assert_invalid(spec)

    def test_input_mutation_cannot_change_returned_validated_spec(self):
        result = validate_spec(self.authored); before = spec_digest(result)
        self.authored['items'][0]['authoredItem']['question'] = 'changed'
        self.assertEqual(spec_digest(result), before)


if __name__ == '__main__':
    unittest.main()
