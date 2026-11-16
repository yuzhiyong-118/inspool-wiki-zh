"""heal 只读计划、旧入口拒绝和真实 Worker/Reviewer/Executor 临时库联测。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools.tests import test_executor_recovery as fixtures
from tools.wiki_runtime.host.heal import build_heal_plan, run_heal_plan, verify_heal_plan
from tools.wiki_runtime.host.supervisor import StandaloneHost, HostError


SCRIPT = Path(__file__).resolve().parents[1] / 'heal.py'
NESTED = 'wiki/concepts/用户分类/更深/existing-concept.md'


class HealRolloutTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ExecutorTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root, self.base = self.fixture.root, self.fixture.base
        self.fixture.write(NESTED, self.fixture.text.replace('synthesis', 'concept'))
        self.fixture.write(fixtures.PAGE, self.fixture.text + '\n[[existing-concep]]\n')
        for path in ('wiki/index.md', 'wiki/log.md'):
            self.fixture.write(path, (self.root / path).read_text(encoding='utf-8') +
                               '[[concepts/用户分类/更深/existing-concept]]\n')
        self.envelopes = []
        self.changes = {'changes': [dict(action='write', path=p,
            text=(self.root / p).read_text(encoding='utf-8').replace('[[existing-concep]]',
                  '[[existing-concept]]') + '\n')
            for p in (fixtures.PAGE, 'wiki/index.md', 'wiki/log.md')]}

    def transport(self, envelope, *, timeout):
        self.envelopes.append(copy.deepcopy(envelope))
        if envelope['system'].startswith('你是中文知识库的处理者'):
            return copy.deepcopy(self.changes)
        return self.fixture.reviewer(envelope, timeout=timeout)

    def host(self):
        return StandaloneHost(self.root, self.base / 'host', transport=self.transport)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), '--root', str(self.root), *args],
                              cwd=self.base, capture_output=True, encoding='utf-8', timeout=30)

    def test_default_and_json_are_readonly(self):
        before = self.fixture.snapshot()
        result = self.cli('--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertTrue(plan['dry_run'])
        self.assertEqual(plan['operation_type'], 'lint')
        self.assertEqual(before, self.fixture.snapshot())
        self.assertFalse((self.root / '.wiki-runtime').exists())
        self.assertEqual(self.cli().returncode, 0)

    def test_apply_explicitly_rejected_without_any_write(self):
        before = self.fixture.snapshot()
        result = self.cli('--apply', '--plan', '.wiki-runtime/candidates/must-not-exist.json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('可信宿主 dispatcher', result.stderr)
        self.assertIn('run_heal_plan', result.stderr)
        self.assertEqual(before, self.fixture.snapshot())
        self.assertFalse((self.root / '.wiki-runtime').exists())

    def test_export_only_candidate_area_and_no_overwrite(self):
        before = self.fixture.snapshot()
        for output in ('wiki/index.md', 'raw/no.md', '../escape.json'):
            self.assertEqual(self.cli('--plan', output).returncode, 2)
            self.assertEqual(before, self.fixture.snapshot())
        output = '.wiki-runtime/candidates/heal.json'
        result = self.cli('--plan', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, self.fixture.snapshot())
        exported = json.loads((self.root / output).read_text(encoding='utf-8'))
        self.assertTrue(verify_heal_plan(self.root, exported))
        self.assertEqual(self.cli('--plan', output).returncode, 2)

    def test_nested_paths_and_exact_plan_scope(self):
        plan = build_heal_plan(self.root)
        action = next(a for a in plan['actions'] if a['type'] == 'review_broken_link')
        self.assertEqual(action['candidates'], [NESTED])
        self.assertTrue(action['requires_review'])
        self.assertIn(NESTED, plan['input_refs'])
        self.assertEqual(set(plan['allowed_paths']), {fixtures.PAGE, 'wiki/index.md', 'wiki/log.md'})
        self.assertFalse(any(p.startswith('raw/') for p in plan['allowed_paths']))
        self.assertNotIn('AGENTS.md', plan['allowed_paths'])

    def test_moved_nested_link_resolves_without_reorganization(self):
        self.fixture.write(fixtures.PAGE, self.fixture.text + '\n[[concepts/existing-concept]]\n')
        plan = build_heal_plan(self.root)
        self.assertFalse(any(a['type'] == 'review_broken_link' for a in plan['actions']))
        self.assertTrue((self.root / NESTED).exists())

    def test_ambiguous_fuzzy_targets_remain_review_suggestions(self):
        duplicate = 'wiki/entities/另一分类/existing-concept.md'
        self.fixture.write(duplicate, self.fixture.text)
        before = self.fixture.snapshot()
        plan = build_heal_plan(self.root)
        action = next(a for a in plan['actions'] if a['type'] == 'review_broken_link')
        self.assertEqual(action['candidates'], sorted([NESTED, duplicate]))
        self.assertTrue(action['requires_review'])
        self.assertEqual(before, self.fixture.snapshot())

    def test_snapshot_change_and_scope_tampering_rejected(self):
        plan = build_heal_plan(self.root)
        for field, value in [('allowed_paths', ['AGENTS.md']), ('task', '直接应用'),
                             ('operation_type', 'index_rebuild')]:
            changed = copy.deepcopy(plan)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(HostError):
                verify_heal_plan(self.root, changed)
        self.fixture.write(NESTED, '用户并发修改\n')
        with self.assertRaises(HostError):
            run_heal_plan(self.host(), plan, apply=True)
        self.assertEqual(self.envelopes, [])

    def test_new_empty_directory_invalidates_plan(self):
        plan = build_heal_plan(self.root)
        (self.root / 'wiki/concepts/新分类').mkdir()
        with self.assertRaises(HostError):
            verify_heal_plan(self.root, plan)

    def test_change_between_verification_and_host_baseline_is_rejected(self):
        plan = build_heal_plan(self.root)
        host = self.host()
        original = host.run_operation
        def raced(*args, **kwargs):
            self.fixture.write(fixtures.RAW, '并发原文\n')
            return original(*args, **kwargs)
        with patch.object(host, 'run_operation', side_effect=raced), self.assertRaises(HostError):
            run_heal_plan(host, plan, apply=True)
        self.assertEqual(self.envelopes, [])

    def test_pipeline_has_two_independent_reviews_and_shared_budget(self):
        raw_before = (self.root / fixtures.RAW).read_bytes()
        plan = build_heal_plan(self.root, operation_id='heal-real')
        result = run_heal_plan(self.host(), plan, apply=True, max_calls=3,
                               max_seconds=120, call_timeout=20)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(result['state']['calls'], 3)
        self.assertEqual(len(self.fixture.calls), 2)
        self.assertIn('[[existing-concept]]', (self.root / fixtures.PAGE).read_text(encoding='utf-8'))
        self.assertNotIn('tools', self.envelopes[1])
        self.assertEqual((self.root / fixtures.RAW).read_bytes(), raw_before)

    def test_executor_cannot_bypass_or_refill_review_budget(self):
        before = self.fixture.snapshot()
        result = run_heal_plan(self.host(), build_heal_plan(self.root, operation_id='heal-budget'),
                               apply=True, max_calls=2, max_seconds=120, call_timeout=20)
        self.assertFalse(result['applied'])
        self.assertEqual(result['state']['calls'], 2)
        self.assertEqual(len(self.fixture.calls), 1)
        self.assertEqual(before, self.fixture.snapshot())

    def test_frequent_missing_page_does_not_authorize_stub(self):
        for index in range(3):
            path = f'wiki/concepts/用户分类/ref-{index}.md'
            self.fixture.write(path, self.fixture.text + '\n[[missing-page]]\n')
        plan = build_heal_plan(self.root)
        self.assertTrue(any(a['type'] == 'investigate_missing_page' for a in plan['actions']))
        self.assertFalse(any('missing-page' in p for p in plan['allowed_paths']))
        before = self.fixture.snapshot()
        self.changes = {'changes': [dict(action='write', path='wiki/concepts/missing-page.md', text='桩') ]}
        result = run_heal_plan(self.host(), plan, apply=True, max_calls=1,
                               max_seconds=60, call_timeout=10)
        self.assertFalse(result['applied'])
        self.assertFalse((self.root / 'wiki/concepts/missing-page.md').exists())
        self.assertEqual(before, self.fixture.snapshot())
        self.assertEqual(self.fixture.calls, [])


if __name__ == '__main__':
    unittest.main()
