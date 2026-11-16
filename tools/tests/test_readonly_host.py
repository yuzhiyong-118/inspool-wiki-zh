"""真实只读宿主，临时知识库及可信假模型传输。"""
import hashlib
from pathlib import Path
import tempfile
import time
import unittest

from tools.wiki_runtime.host.readonly import answer_query, ReadonlyError


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.envelopes = []

    def __call__(self, envelope, *, timeout):
        self.envelopes.append(envelope)
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def answer(**changes):
    return dict({'status': 'answered', 'answer': '甲工具支持本地双链。',
                 'citations': ['wiki/sources/甲.md#关键观点'], 'judgment': 'fact'}, **changes)


PASS = {'verdict': 'pass', 'reason': '引用支持结论。'}
FAIL = {'verdict': 'fail', 'reason': '来源未支持该强断言。'}


class ReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('wiki/index.md', '# 索引\n- [[sources/甲]]\n- [[concepts/乙]]\n')
        self.write('wiki/sources/甲.md', '# 甲\n## 关键观点\n甲工具支持本地双链。\n')
        self.write('wiki/concepts/乙.md', '# 乙\n乙是本地关系。\n')
        self.write('raw/unprocessed/秘密.md', '不许向模型提供 raw 原文。')
        self.write('private/key', 'secret')

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_query_verified_and_no_writes(self):
        before = self.snapshot()
        transport = FakeTransport(answer(), PASS)
        result = answer_query(self.root, '甲支持什么？', transport)
        self.assertEqual(result['status'], 'answered')
        self.assertFalse(result['applied'])
        self.assertEqual(result['calls'], 2)
        self.assertEqual(before, self.snapshot())
        documents = transport.envelopes[0]['documents']
        self.assertEqual(next(iter(documents)), 'wiki/index.md')
        self.assertEqual(set(documents), {'wiki/index.md', 'wiki/sources/甲.md', 'wiki/concepts/乙.md'})
        self.assertNotIn('validation_feedback', transport.envelopes[1])

    def test_explicit_inputs_take_priority(self):
        transport = FakeTransport(answer(), PASS)
        result = answer_query(self.root, '甲？', transport, input_refs=['wiki/sources/甲.md'])
        self.assertEqual(result['status'], 'answered')
        self.assertNotIn('wiki/concepts/乙.md', result['scope'])
        self.assertTrue(result['partial_scope'])

    def test_moved_classification_resolves_index(self):
        path = self.root / 'wiki/concepts/乙.md'
        moved = path.parent / '用户分类' / path.name
        moved.parent.mkdir()
        path.rename(moved)
        transport = FakeTransport(answer(), PASS)
        result = answer_query(self.root, '甲？', transport)
        self.assertEqual(result['status'], 'answered')
        self.assertIn('wiki/concepts/用户分类/乙.md', result['scope'])

    def test_forged_or_unread_citations_fail_closed(self):
        for ref in ('wiki/sources/不存在.md', 'raw/unprocessed/秘密.md',
                    'wiki/sources/甲.md#不存在', 'wiki/sources/甲.md#L0-L2',
                    'wiki/sources/甲.md#L1-L999', 'wiki/../private/key.md',
                    'https://example.com/source'):
            with self.subTest(ref=ref):
                transport = FakeTransport(answer(citations=[ref]), answer(citations=[ref]))
                result = answer_query(self.root, '甲？', transport)
                self.assertEqual(result['status'], 'insufficient_evidence')
                self.assertEqual(result['citations'], [])
                self.assertEqual(result['calls'], 2)

    def test_valid_line_citation(self):
        transport = FakeTransport(answer(citations=['wiki/sources/甲.md#L2-L3']), PASS)
        self.assertEqual(answer_query(self.root, '甲？', transport)['status'], 'answered')

    def test_cross_scope_input_rejected_before_model(self):
        for ref in ('raw/unprocessed/秘密.md', 'wiki/private/secret.md', 'wiki/../private/key'):
            transport = FakeTransport()
            result = answer_query(self.root, '秘密？', transport, input_refs=[ref])
            self.assertEqual(result['status'], 'insufficient_evidence')
            self.assertEqual(result['calls'], 0)

    def test_unknown_role_tool_and_approval_rejected(self):
        for key in ('role', 'tool', 'tools', 'approved', 'changes', 'executor'):
            transport = FakeTransport(answer(**{key: 'worker'}), answer(**{key: 'worker'}))
            result = answer_query(self.root, '甲？', transport)
            self.assertEqual(result['status'], 'insufficient_evidence')

    def test_rejected_strong_assertion_repairs_under_shared_budget(self):
        transport = FakeTransport(answer(answer='甲永远不会失败。'), FAIL, answer(), PASS)
        result = answer_query(self.root, '甲？', transport)
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['calls'], 4)
        self.assertEqual(result['answer'], '甲工具支持本地双链。')

    def test_failed_review_never_defaults_to_pass(self):
        for review in (FAIL, {'verdict': 'pass', 'reason': '好', 'approved': True}, RuntimeError('secret')):
            transport = FakeTransport(answer(), review, answer(), review)
            result = answer_query(self.root, '甲？', transport)
            self.assertEqual(result['status'], 'insufficient_evidence')
            self.assertNotIn('secret', str(result))

    def test_inference_and_conflict_are_reviewed(self):
        for judgment in ('inference', 'conflict'):
            transport = FakeTransport(answer(judgment=judgment, citations=[
                'wiki/sources/甲.md', 'wiki/concepts/乙.md']), PASS)
            result = answer_query(self.root, '比较？', transport)
            self.assertEqual(result['judgment'], judgment)
            self.assertEqual(result['calls'], 2)

    def test_source_required_for_answer(self):
        transport = FakeTransport(answer(citations=[]), answer(citations=[]))
        self.assertEqual(answer_query(self.root, '甲？', transport)['status'], 'insufficient_evidence')

    def test_insufficient_evidence_cannot_smuggle_unreviewed_claim(self):
        transport = FakeTransport(answer(status='insufficient_evidence', citations=[], answer='无来源的强断言'))
        result = answer_query(self.root, '甲？', transport)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertNotIn('强断言', result['answer'])

    def test_large_library_page_limit_and_byte_limit(self):
        for index in range(25):
            self.write(f'wiki/concepts/页{index:02d}.md', '# 页\n')
        self.write('wiki/index.md', '\n'.join(f'[[concepts/页{index:02d}]]' for index in range(25)))
        transport = FakeTransport({'status': 'insufficient_evidence', 'answer': '证据不足',
                                   'citations': [], 'judgment': 'inference'})
        result = answer_query(self.root, '甲？', transport)
        self.assertEqual(len(result['scope']), 21)
        self.assertTrue(result['partial_scope'])
        self.write('wiki/concepts/页00.md', '大' * (400 * 1024))
        result = answer_query(self.root, '甲？', FakeTransport())
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(result['calls'], 0)

    def test_global_deadline_is_shared_by_generation_and_review(self):
        calls = []
        def timed(envelope, *, timeout):
            calls.append(timeout)
            time.sleep(0.025)
            return answer() if len(calls) == 1 else PASS
        result = answer_query(self.root, '甲？', timed, max_seconds=0.045, call_timeout=1)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertLessEqual(len(calls), 2)
        time.sleep(0.04)

    def test_budget_prevents_unreviewed_answer(self):
        transport = FakeTransport(answer(), PASS)
        result = answer_query(self.root, '甲？', transport, max_calls=1)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertEqual(len(transport.envelopes), 1)

    def test_host_bounds_transport_that_ignores_timeout(self):
        def slow(envelope, *, timeout):
            time.sleep(0.08)
            return answer()
        start = time.monotonic()
        result = answer_query(self.root, '甲？', slow, call_timeout=0.02)
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertLess(time.monotonic() - start, 0.5)
        time.sleep(0.09)  # finish the trusted test transport before temporary cleanup

    def test_dependency_and_directory_changes_stop_answer(self):
        for mutation in ('content', 'directory'):
            count = [0]
            def changing(envelope, *, timeout):
                count[0] += 1
                if mutation == 'content':
                    self.write('wiki/sources/甲.md', '# 已改变')
                else:
                    self.write('wiki/concepts/新增.md', '# 新增')
                return answer()
            result = answer_query(self.root, '甲？', changing)
            self.assertEqual(result['status'], 'insufficient_evidence')
            self.assertEqual(count[0], 1)

    def test_lint_reports_without_writes(self):
        before = self.snapshot()
        lint = {'status': 'completed', 'findings': [{'path': 'wiki/concepts/乙.md',
                'reason': '定义缺少来源支撑。', 'evidence_refs': ['wiki/concepts/乙.md#L1-L2']}]}
        transport = FakeTransport(lint, PASS)
        result = answer_query(self.root, '检查语义', transport, mode='lint')
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['applied'])
        self.assertEqual(result['findings'], lint['findings'])
        self.assertEqual(before, self.snapshot())

    def test_lint_rejects_repair_action(self):
        lint = {'status': 'completed', 'findings': [], 'changes': []}
        result = answer_query(self.root, '检查语义', FakeTransport(lint, lint), mode='lint')
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['findings'], [])

    def test_invalid_budgets_rejected(self):
        for options in ({'max_calls': True}, {'max_seconds': float('nan')}, {'call_timeout': 0}):
            with self.assertRaises(ReadonlyError):
                answer_query(self.root, '甲？', FakeTransport(), **options)


if __name__ == '__main__':
    unittest.main()
