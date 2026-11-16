"""S1 Task 0 的持久循环封闭协议与真实旧入口基线。"""
import copy
import inspect
import json
from pathlib import Path
import unittest
from unittest import mock

from tools import heal, raw_index
from tools.wiki_runtime.contracts import ContractError, digest
from tools.wiki_runtime.executor import Executor
from tools.wiki_runtime.host import cli as host_cli
from tools.wiki_runtime.host.heal import run_heal_plan
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.runtime.migration import MigrationError
from tools.wiki_runtime.runtime import (
    acceptance_check, admission_digest, authorization_digest, capability_manifest_digest,
    event_digest, event_envelope_digest, invocation_spec_digest, learning_state_digest,
    parse_admission, parse_authorization, parse_capability_manifest, parse_event,
    parse_invocation_spec, parse_learning_state, parse_policy_revision, parse_retry_policy,
    parse_step, parse_step_result, parse_task, parse_wait, parse_work_item, parse_workflow_ref,
    policy_revision_digest, replay_event, replay_step_result, retry_policy_digest,
    runtime_binding_valid, step_digest, step_result_digest, task_digest, wait_digest,
    work_item_digest, workflow_ref_digest,
)

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'learning_s0'


def no_duplicate_keys(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('JSON 不允许重复键')
    return result


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'),
                      object_pairs_hook=no_duplicate_keys)


def rehash_step_result(record):
    body = {field: record[field] for field in (
        'artifact_digests', 'domain_change_digest', 'wait_request_digest',
        'follow_up_digests', 'failure',
    )}
    record['result_digest'] = digest(body)
    return record


def rehash_policy(record):
    body = {field: record[field] for field in (
        'revision', 'budget', 'stop_policy', 'creation_reason',
    )}
    record['policy_digest'] = digest(body)
    return record


class LoopProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_fixture('protocol_records.json')['valid']
        cls.loop = load_fixture('loop_protocol_records.json')
        cls.valid = cls.loop['valid']
        cls.invalid = cls.loop['invalid']

    def test_every_loop_record_is_closed_and_has_stable_digest(self):
        cases = [
            ('workflow_ref', parse_workflow_ref, workflow_ref_digest),
            ('learning_state', parse_learning_state, learning_state_digest),
            ('policy_revision', parse_policy_revision, policy_revision_digest),
            ('event', parse_event, event_digest),
            ('step', parse_step, step_digest),
            ('wait', parse_wait, wait_digest),
            ('work_item', parse_work_item, work_item_digest),
            ('step_result', parse_step_result, step_result_digest),
            ('retry_policy', parse_retry_policy, retry_policy_digest),
            ('capability_manifest', parse_capability_manifest, capability_manifest_digest),
        ]
        for name, parser, digest_function in cases:
            with self.subTest(record=name):
                record = self.valid[name]
                self.assertIs(parser(record), record)
                self.assertRegex(digest_function(record), r'^[0-9a-f]{64}$')
                reordered = dict(reversed(list(record.items())))
                self.assertEqual(digest_function(record), digest_function(reordered))
                unknown = copy.deepcopy(record)
                unknown['unexpected'] = True
                with self.assertRaises(ContractError):
                    parser(unknown)
        self.assertEqual(self.base['task']['workflow_ref'], self.valid['workflow_ref'])
        self.assertEqual(self.base['executor_context']['policy_revision'],
                         self.valid['policy_revision'])

    def test_runtime_task_and_learning_state_are_separate(self):
        task = self.base['task']
        self.assertIs(parse_task(task), task)
        self.assertRegex(task_digest(task), r'^[0-9a-f]{64}$')
        self.assertEqual(task['state'], 'running')
        self.assertEqual(self.valid['learning_state']['state'], 'awaiting_confirmation')
        for teaching_state in ('preparing', 'studying', 'assessing', 'understanding_verified'):
            changed = copy.deepcopy(task)
            changed['state'] = teaching_state
            with self.subTest(state=teaching_state), self.assertRaises(ContractError):
                parse_task(changed)
        old_task = {
            'learning_task_id': 'task-learning-1', 'state': 'studying',
            'waiting_on': None, 'blocked': False, 'recovery_point': None,
        }
        with self.assertRaises(ContractError):
            parse_task(old_task)
        learning = copy.deepcopy(self.valid['learning_state'])
        learning['state'] = 'paused'
        with self.assertRaises(ContractError):
            parse_learning_state(learning)

    def test_policy_digest_binds_content_and_current_task_revision(self):
        policy = self.valid['policy_revision']
        with self.assertRaises(ContractError):
            parse_policy_revision(self.invalid['policy_wrong_digest'])
        changed = copy.deepcopy(policy)
        changed['budget']['model_calls'] += 1
        with self.assertRaises(ContractError):
            parse_policy_revision(changed)
        rehash_policy(changed)
        parse_policy_revision(changed)
        self.assertNotEqual(policy_revision_digest(policy), policy_revision_digest(changed))
        spec = copy.deepcopy(self.base['invocation_spec'])
        self.assertTrue(runtime_binding_valid(spec, self.base['task'], policy,
                                               kind='invocation_spec'))
        self.assertFalse(runtime_binding_valid(spec, self.base['task'], changed,
                                                kind='invocation_spec'))

    def test_invocation_admission_and_authorization_reject_stale_bindings(self):
        task = self.base['task']
        policy = self.valid['policy_revision']
        records = [
            ('invocation_spec', self.base['invocation_spec']),
            ('admission', self.base['admission']),
            ('authorization', self.base['authorization']),
        ]
        for kind, original in records:
            self.assertTrue(runtime_binding_valid(original, task, policy, kind=kind))
            for field, value in (
                ('task_id', 'task-other'), ('learning_task_id', 'task-learning-other'),
                ('policy_digest', '0' * 64),
            ):
                changed = copy.deepcopy(original)
                changed[field] = value
                with self.subTest(kind=kind, field=field):
                    self.assertFalse(runtime_binding_valid(changed, task, policy, kind=kind))
            if kind != 'invocation_spec':
                changed = copy.deepcopy(original)
                changed['submission_epoch'] = task['submission_epoch'] + 1
                with self.subTest(kind=kind, field='submission_epoch'):
                    self.assertFalse(runtime_binding_valid(changed, task, policy, kind=kind))
        paused = copy.deepcopy(task)
        paused['submission_epoch'] += 1
        paused['state'] = 'paused'
        for kind, original in records[1:]:
            with self.subTest(kind=kind, paused=True):
                self.assertFalse(runtime_binding_valid(original, paused, policy, kind=kind))

    def test_acceptance_rechecks_runtime_learning_policy_and_epoch(self):
        context = copy.deepcopy(self.base['executor_context'])
        context['readiness'] = copy.deepcopy(self.base['readiness'])
        context['authorization'] = copy.deepcopy(self.base['authorization'])
        context['review_credentials'] = copy.deepcopy(self.base['review_credentials'])
        admission = copy.deepcopy(self.base['admission'])
        self.assertTrue(acceptance_check(context, admission))
        mutations = [
            ('runtime_task', 'submission_epoch', 2),
            ('runtime_task', 'current_policy_digest', '0' * 64),
            ('runtime_task', 'state', 'paused'),
            ('learning_state', 'state', 'studying'),
            ('learning_state', 'knowledge_version', 2),
            ('run', 'task_id', 'task-other'),
            ('policy_revision', 'revision', 2),
        ]
        for target, field, value in mutations:
            changed = copy.deepcopy(context)
            changed[target][field] = value
            with self.subTest(target=target, field=field):
                self.assertFalse(acceptance_check(changed, admission))

    def test_event_replay_uses_complete_business_envelope(self):
        event = self.valid['event']
        changed_receipt = copy.deepcopy(event)
        changed_receipt['receipt_sequence'] = 99
        changed_receipt['processing_state'] = 'processed'
        self.assertEqual(event_envelope_digest(event), event_envelope_digest(changed_receipt))
        self.assertNotEqual(event_digest(event), event_digest(changed_receipt))
        replayed = replay_event(event, changed_receipt)
        self.assertEqual(replayed, event)
        self.assertIsNot(replayed, event)
        for name in ('event_cross_task', 'event_cross_type', 'event_cross_version'):
            candidate = self.invalid[name]
            self.assertEqual(candidate['payload_digest'], event['payload_digest'])
            with self.subTest(case=name), self.assertRaises(ContractError):
                replay_event(event, candidate)
        changed_payload = copy.deepcopy(event)
        changed_payload['payload_digest'] = '0' * 64
        with self.assertRaises(ContractError):
            replay_event(event, changed_payload)

    def test_step_result_requires_digest_and_replays_only_identical_result(self):
        result = self.valid['step_result']
        self.assertEqual(result['result_digest'], self.valid['step']['result_digest'])
        self.assertEqual(replay_step_result(result, copy.deepcopy(result)), result)
        with self.assertRaises(ContractError):
            parse_step_result(self.invalid['step_result_missing_digest'])
        with self.assertRaises(ContractError):
            parse_step_result(self.invalid['step_result_stale_digest'])
        changed_result = copy.deepcopy(result)
        changed_result['artifact_digests'] = ['a' * 64]
        rehash_step_result(changed_result)
        parse_step_result(changed_result)
        with self.assertRaises(ContractError):
            replay_step_result(result, changed_result)
        changed_input = copy.deepcopy(result)
        changed_input['input_digest'] = '0' * 64
        parse_step_result(changed_input)
        with self.assertRaises(ContractError):
            replay_step_result(result, changed_input)
        changed_generation = copy.deepcopy(result)
        changed_generation['generation'] += 1
        with self.assertRaises(ContractError):
            replay_step_result(result, changed_generation)

    def test_wait_work_item_and_static_scope_guards(self):
        item = copy.deepcopy(self.valid['work_item'])
        item['claimed_by'] = None
        with self.assertRaises(ContractError):
            parse_work_item(item)
        wait = copy.deepcopy(self.valid['wait'])
        wait['knowledge_version'] = 0
        with self.assertRaises(ContractError):
            parse_wait(wait)
        for field in ('knowledge_version', 'question_version', 'rubric_version'):
            wait = copy.deepcopy(self.valid['wait'])
            wait[field] = None
            with self.subTest(wait_version=field), self.assertRaises(ContractError):
                parse_wait(wait)
        wait = copy.deepcopy(self.valid['wait'])
        for field in ('knowledge_version', 'question_version', 'rubric_version'):
            wait[field] = None
        with self.assertRaises(ContractError):
            parse_wait(wait)
        wait['condition_type'] = 'source_available'
        parse_wait(wait)
        with self.assertRaises(ContractError):
            parse_capability_manifest(self.invalid['capability_with_permissions'])
        with self.assertRaises(ContractError):
            parse_retry_policy(self.invalid['retry_with_progress_claim'])
        manifest = self.valid['capability_manifest']
        self.assertEqual(set(manifest), {
            'capability_id', 'implementation_digest', 'contract_version', 'required_checks',
            'usage_visibility', 'cancellation',
        })
        self.assertNotIn('schema_migration', self.valid['policy_revision'])


class LegacyInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = load_fixture('legacy_inventory.json')
        cls.entries = {entry['entry_id']: entry for entry in cls.inventory['write_entrypoints']}

    def assert_preview_then_reject(self, preview, write, *targets):
        before = {path: path.read_bytes() if path.exists() else None for path in targets}
        preview()
        for path, original in before.items():
            current = path.read_bytes() if path.exists() else None
            self.assertEqual(current, original, f'预览修改了 {path}')
        with self.assertRaisesRegex(MigrationError, '已封闭'):
            write()
        for path, original in before.items():
            current = path.read_bytes() if path.exists() else None
            self.assertEqual(current, original, f'拒绝后仍修改了 {path}')

    def make_wiki(self, temporary):
        root = Path(temporary) / 'wiki'
        concepts = root / 'concepts'
        concepts.mkdir(parents=True)
        index = root / 'index.md'
        index.write_text('# 索引\n\n## 概念页\n- [[old-page]]\n', encoding='utf-8')
        existing = concepts / 'existing.md'
        existing.write_text('# Existing\n', encoding='utf-8')
        page = concepts / 'page.md'
        page.write_text('[[existng]]\n', encoding='utf-8')
        maps = ({'existing': [existing]}, {'concepts/existing': [existing]})
        return root, index, existing, page, maps

    def test_inventory_covers_host_derived_and_all_python_write_branches(self):
        required = {
            'host_run_apply', 'host_apply_pending', 'host_heal_plan',
            'derived_raw_index', 'derived_health', 'derived_import_package',
            'refresh_index', 'run_heal', 'heal_missing_pages', 'heal_broken_links',
            'heal_index_sync', 'wechat_raw_write',
        }
        self.assertEqual(set(self.entries), required)
        self.assertTrue(callable(StandaloneHost.run_operation))
        self.assertTrue(callable(StandaloneHost.apply_pending))
        self.assertTrue(callable(run_heal_plan))
        derived = inspect.getsource(host_cli._prepare_derived)
        for builder in ('build_raw_index', 'build_health', 'build_capture'):
            self.assertIn(builder, derived)
        apply_record = inspect.getsource(host_cli._apply_record)
        self.assertIn('apply_derived_record', apply_record)
        self.assertNotIn('executor.apply', apply_record)
        self.assertNotIn('executor.recover', apply_record)
        self.assertIn('runtime_managed', derived)
        for entry_id in ('derived_raw_index', 'derived_health', 'derived_import_package'):
            self.assertIn('--apply', self.entries[entry_id]['write_condition'])
        raw_write = self.entries['derived_raw_index']
        self.assertIn('tools/raw_index.py --write', raw_write['write_condition'])
        self.assertIn('health._apply_via_host', raw_write['write_path'])
        self.assertIn('health._apply_via_host("raw-index"', inspect.getsource(raw_index.main))
        self.assertIn('非 derived', self.entries['host_apply_pending']['write_condition'])

    def test_five_python_api_write_paths_match_source_and_previews_stay_separate(self):
        signatures = {
            'refresh_index': (raw_index.refresh_index, 'apply'),
            'run_heal': (heal.run_heal, 'dry_run'),
            'heal_missing_pages': (heal.heal_missing_pages, 'dry_run'),
            'heal_broken_links': (heal.heal_broken_links, 'dry_run'),
            'heal_index_sync': (heal.heal_index_sync, 'dry_run'),
        }
        for entry_id, (function, parameter) in signatures.items():
            with self.subTest(entry=entry_id):
                self.assertIn(parameter, inspect.signature(function).parameters)
                self.assertIn(parameter, self.entries[entry_id]['write_condition'])
                self.assertIn(parameter, self.entries[entry_id]['preview_condition'])
                source = inspect.getsource(function)
                self.assertIn('MigrationError', source)
                self.assertIn('已封闭', source)
                self.assertNotIn('legacy_write_guard', source)
        previews = set(self.inventory['read_only_previews'])
        for preview in (
            'refresh_index(apply=False)', 'run_heal(dry_run=True)',
            'heal_missing_pages(dry_run=True)', 'heal_broken_links(dry_run=True)',
            'heal_index_sync(dry_run=True)', 'tools/health.py 默认/--json',
            'tools/raw_index.py 默认',
        ):
            self.assertIn(preview, previews)
        self.assertFalse(any('--apply' in item for item in previews))
        self.assertTrue(self.inventory['candidate_only_entrypoints'])

    def test_refresh_index_preview_does_not_write_and_apply_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            raw = Path(temporary) / 'raw'
            (raw / 'unprocessed').mkdir(parents=True)
            (raw / 'processed').mkdir()
            index = raw / 'index.md'
            index.write_text(
                '# 队列\n<!-- raw-queue:start -->\n旧内容\n<!-- raw-queue:end -->\n',
                encoding='utf-8',
            )
            with mock.patch.object(raw_index.health, 'RAW_ROOT', raw):
                self.assert_preview_then_reject(
                    lambda: raw_index.refresh_index(apply=False),
                    lambda: raw_index.refresh_index(apply=True), index,
                )
            self.assertIn('旧内容', index.read_text(encoding='utf-8'))

    def test_missing_pages_preview_does_not_create_and_write_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'wiki'
            concepts = root / 'concepts'
            concepts.mkdir(parents=True)
            referrer = concepts / 'referrer.md'
            target = concepts / '新页面.md'
            with mock.patch.object(heal, 'WIKI_ROOT', root), mock.patch.object(
                heal, 'collect_link_frequencies', return_value={'新页面': [referrer]},
            ):
                self.assert_preview_then_reject(
                    lambda: heal.heal_missing_pages([], min_refs=1, dry_run=True),
                    lambda: heal.heal_missing_pages([], min_refs=1, dry_run=False), target,
                )
            self.assertFalse(target.exists())

    def test_broken_links_preview_does_not_write_and_write_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root, _index, _existing, page, maps = self.make_wiki(temporary)
            with mock.patch.object(heal, 'WIKI_ROOT', root), mock.patch.object(
                heal, 'resolution_maps', return_value=maps,
            ):
                self.assert_preview_then_reject(
                    lambda: heal.heal_broken_links([page], dry_run=True),
                    lambda: heal.heal_broken_links([page], dry_run=False), page,
                )
            self.assertEqual(page.read_text(encoding='utf-8'), '[[existng]]\n')

    def test_index_sync_preview_does_not_write_and_write_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root, index, existing, _page, _maps = self.make_wiki(temporary)
            with mock.patch.object(heal, 'WIKI_ROOT', root):
                self.assert_preview_then_reject(
                    lambda: heal.heal_index_sync([existing], dry_run=True),
                    lambda: heal.heal_index_sync([existing], dry_run=False), index,
                )
            self.assertIn('old-page', index.read_text(encoding='utf-8'))

    def test_run_heal_preview_does_not_write_and_write_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root, index, existing, page, maps = self.make_wiki(temporary)
            def pages(*, include_meta):
                return [existing] if include_meta else [page]
            with mock.patch.object(heal, 'WIKI_ROOT', root), mock.patch.object(
                heal.health, 'all_wiki_pages', side_effect=pages,
            ), mock.patch.object(heal, 'resolution_maps', return_value=maps), mock.patch.object(
                heal, 'collect_link_frequencies', return_value={},
            ):
                self.assert_preview_then_reject(
                    lambda: heal.run_heal(dry_run=True),
                    lambda: heal.run_heal(dry_run=False), index, page,
                )
            self.assertIn('old-page', index.read_text(encoding='utf-8'))
            self.assertEqual(page.read_text(encoding='utf-8'), '[[existng]]\n')

    def test_wal_active_lock_and_runtime_paths_are_fixed(self):
        baseline = self.inventory['executor_baseline']
        self.assertEqual(baseline['journal_root'], '<state_dir>/private/journals')
        self.assertEqual(baseline['active_path'],
                         '<project_root>/.wiki-runtime/executor-active.json')
        self.assertEqual(baseline['lock_path'], '<project_root>/.wiki-runtime/executor.lock')
        self.assertEqual(baseline['runtime_db_path'],
                         '<project_root>/.wiki-runtime/learning/runtime.db')
        self.assertFalse(baseline['wal_relocation_allowed'])
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'wiki-root'
            root.mkdir()
            journal_root = Path(temporary) / 'state' / 'private' / 'journals'
            executor = Executor(root, journal_root)
            self.assertEqual(executor._active, root / '.wiki-runtime' / 'executor-active.json')
            self.assertEqual(executor._journal('operation-1'),
                             journal_root / (digest('operation-1') + '.json'))
            self.assertIn('_acceptance_lock', inspect.getsource(Executor._lock))
            with executor.acceptance_barrier():
                self.assertTrue((root / '.wiki-runtime/executor.lock').exists())



if __name__ == '__main__':
    unittest.main()
