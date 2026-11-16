"""S1 T6：derived、Python API 与全局切变的真实临时库回归。"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import health, heal, raw_index
from tools.wiki_runtime.capture import capture
from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.executor import Executor
from tools.wiki_runtime.host import cli as host_cli_module
from tools.wiki_runtime.host.derived import (
    _derived_runtime_context, apply_derived_record, build_raw_index, check_derivation,
    maintenance_binding,
)
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.runtime.service import ExecutionReconcileError, RuntimeServiceError
from tools.wiki_runtime.runtime.migration import (
    MigrationError, freeze_legacy_entries, supersede_pending,
)
from tools.wiki_runtime.runtime.storage import RuntimeStore


PROJECT = Path(__file__).resolve().parents[2]
RULES = PROJECT / 'tools/wiki_runtime/contracts/rules.json'


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root, self.state = self.base / 'vault', self.base / 'state'
        for folder in ('raw/unprocessed', 'raw/processed', 'wiki/meta'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        (self.root / 'AGENTS.md').write_text('# 临时规则\n', encoding='utf-8')
        rules = self.root / 'tools/wiki_runtime/contracts/rules.json'
        rules.parent.mkdir(parents=True)
        rules.write_bytes(RULES.read_bytes())
        (self.root / 'raw/index.md').write_text(
            '# 手写说明\n' + raw_index.render_queue(self.root / 'raw') + '\n尾注\n',
            encoding='utf-8',
        )
        (self.root / 'wiki/index.md').write_text('# 索引\n', encoding='utf-8')
        (self.root / 'wiki/log.md').write_text('# 日志\n', encoding='utf-8')

    def host_cli(self, command, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = [command, '--root', str(self.root), '--state-dir', str(self.state), *map(str, args)]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = host_cli_module.main(argv)
        output = stdout.getvalue() if code != 2 else stderr.getvalue()
        return code, json.loads(output)

    def rows(self, query):
        store = RuntimeStore(self.state)
        try:
            return store.read(query)
        finally:
            store.close()

    def task(self, task_id):
        return json.loads(self.rows(
            "SELECT record_json FROM tasks WHERE task_id='" + task_id + "'"
        )[0]['record_json'])

    def prepare_legacy(self, operation_id):
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            bundle = build_raw_index(
                self.root, host.operations / digest(operation_id), operation_id,
            )
            executor = Executor(
                self.root, host.private / 'journals', deterministic_check=check_derivation,
            )
            record = {
                'kind': 'derived', 'bundle': bundle,
                'context': executor._context(
                    bundle['manifest'], bundle['candidate'], bundle['snapshot'],
                ),
                'config': {'root': str(self.root), 'operation_id': operation_id,
                           'operation_type': 'index_rebuild'},
                'packages': [],
            }
            host._save_pending(operation_id, record)
        finally:
            host.close()

    def test_derived_apply_uses_maintenance_runtime_and_terminal_replay(self):
        (self.root / 'raw/unprocessed/note.md').write_text(
            '---\nprocessing_status: unprocessed\n---\n合成原文\n', encoding='utf-8',
        )
        code, result = self.host_cli('raw-index', '--operation-id', 'derived-raw', '--apply')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['applied'])
        ids = result['runtime_ids']
        self.assertEqual(self.task(ids['task_id'])['state'], 'completed')
        bindings = self.rows('SELECT * FROM maintenance_bindings')
        results = self.rows('SELECT * FROM maintenance_results')
        self.assertEqual(len(bindings), 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(self.rows('SELECT * FROM operation_admissions'), [])
        self.assertEqual(self.rows('SELECT * FROM authorizations'), [])
        self.assertEqual(self.rows('SELECT * FROM learning_states'), [])
        journal_path = self.state / 'private/journals' / (digest('derived-raw') + '.json')
        journal = json.loads(journal_path.read_bytes())
        self.assertEqual(journal['state'], 'applied')
        self.assertNotIn('admission_digest', journal)
        self.assertIn('未处理：1', (self.root / 'raw/index.md').read_text(encoding='utf-8'))

        code, replay = self.host_cli('apply', '--operation-id', 'derived-raw')
        self.assertEqual(code, 0, replay)
        self.assertEqual(replay['status'], 'applied')
        self.assertEqual(len(self.rows('SELECT * FROM maintenance_results')), 1)
        self.assertEqual(len(list((self.state / 'private/journals').glob('*.json'))), 1)

    def test_health_is_a_derived_maintenance_task(self):
        code, result = self.host_cli(
            'health', '--operation-id', 'derived-health', '--no-report', '--write-graph', '--apply',
        )
        self.assertEqual(code, 0, result)
        self.assertTrue(result['applied'])
        self.assertTrue((self.root / 'wiki/meta/graph.json').is_file())
        self.assertIn('health |', (self.root / 'wiki/log.md').read_text(encoding='utf-8'))
        binding = json.loads(self.rows('SELECT record_json FROM maintenance_bindings')[0]['record_json'])
        self.assertEqual(binding['operation_type'], 'health')
        self.assertEqual(binding['workflow_id'], 'derived-maintenance-v1')

    def test_import_package_remains_unprocessed_and_does_not_create_learning_records(self):
        source = self.base / 'source.md'
        source.write_text('# 新资料\n\n这是合成来源正文。\n', encoding='utf-8')
        _package, package_root = capture(source, self.base / 'packages', 'source-1', vault_root=self.root)
        before_wiki = {path.relative_to(self.root): path.read_bytes()
                       for path in (self.root / 'wiki').rglob('*') if path.is_file()}
        code, result = self.host_cli(
            'import-package', '--operation-id', 'derived-capture', '--package-root', package_root,
            '--raw-path', 'raw/unprocessed/imported.md', '--apply',
        )
        self.assertEqual(code, 0, result)
        self.assertTrue(result['applied'])
        imported = (self.root / 'raw/unprocessed/imported.md').read_text(encoding='utf-8')
        self.assertIn('processing_status: "unprocessed"', imported)
        after_wiki = {path.relative_to(self.root): path.read_bytes()
                      for path in (self.root / 'wiki').rglob('*') if path.is_file()}
        self.assertEqual(before_wiki, after_wiki)
        self.assertEqual(self.rows('SELECT * FROM learning_states'), [])
        self.assertEqual(self.rows('SELECT * FROM operation_admissions'), [])

    def test_all_five_python_apis_reject_direct_write_and_keep_read_only_previews(self):
        patches = patch.multiple(
            health, WIKI_ROOT=self.root / 'wiki', RAW_ROOT=self.root / 'raw',
            META_DIR=self.root / 'wiki/meta', GRAPH_JSON=self.root / 'wiki/meta/graph.json',
            HEALTH_REPORT=self.root / 'wiki/health-report.md',
        )
        patches.start()
        self.addCleanup(patches.stop)
        heal_patch = patch.object(heal, 'WIKI_ROOT', self.root / 'wiki')
        heal_patch.start()
        self.addCleanup(heal_patch.stop)
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        writes = (
            lambda: raw_index.refresh_index(apply=True),
            lambda: heal.run_heal(dry_run=False),
            lambda: heal.heal_missing_pages([], dry_run=False),
            lambda: heal.heal_broken_links([], dry_run=False),
            lambda: heal.heal_index_sync([], dry_run=False),
        )
        for write in writes:
            with self.subTest(write=write), self.assertRaisesRegex(MigrationError, '已封闭'):
                write()
        self.assertIsInstance(raw_index.refresh_index(apply=False), str)
        self.assertTrue(heal.run_heal(dry_run=True)['dry_run'])
        self.assertEqual(heal.heal_missing_pages([], dry_run=True), [])
        self.assertEqual(heal.heal_broken_links([], dry_run=True), [])
        self.assertIsInstance(heal.heal_index_sync([], dry_run=True), list)
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.state / '.wiki-runtime/learning/runtime.db').exists())

    def test_new_runtime_waits_until_legacy_pending_is_superseded(self):
        self.prepare_legacy('legacy-pending')
        freeze_legacy_entries(self.root, self.state)
        code, rejected = self.host_cli('raw-index', '--operation-id', 'new-managed')
        self.assertEqual(code, 2, rejected)
        self.assertIn('尚未完成切变', rejected['message'])
        new_journal = self.state / 'private/journals' / (digest('new-managed') + '.json')
        self.assertFalse(new_journal.exists())
        self.assertFalse((self.state / 'private/pending' / (digest('new-managed') + '.json')).exists())
        self.assertFalse((self.state / '.wiki-runtime/learning/runtime.db').exists())
        supersede_pending(
            'legacy-pending', '旧预算不可继承', root=self.root, state_dir=self.state,
        )
        code, applied = self.host_cli('raw-index', '--operation-id', 'new-managed', '--apply')
        self.assertEqual(code, 0, applied)
        self.assertTrue(applied['applied'])
        self.assertTrue(new_journal.exists())
        self.assertFalse((self.state / 'private/journals' / (digest('legacy-pending') + '.json')).exists())

    def test_acceptance_fault_has_no_wal_and_same_operation_can_retry(self):
        self.host_cli('raw-index', '--operation-id', 'acceptance-fault')
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            record = host.load_pending('acceptance-fault')

            def fault(event, index):
                if event == 'after_acceptance_before_prepare':
                    raise RuntimeError('接受点故障')

            executor = Executor(
                self.root, host.private / 'journals', deterministic_check=check_derivation,
                fault=fault,
            )
            with self.assertRaisesRegex(RuntimeError, '接受点故障'):
                apply_derived_record(host, record, executor)
            journal = host.private / 'journals' / (digest('acceptance-fault') + '.json')
            self.assertFalse(journal.exists())
        finally:
            host.close()
        code, result = self.host_cli('apply', '--operation-id', 'acceptance-fault')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['applied'])

    def test_wal_after_reconcile_fault_recovers_original_binding(self):
        self.host_cli('raw-index', '--operation-id', 'reconcile-fault')
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            record = host.load_pending('reconcile-fault')
            executor = Executor(
                self.root, host.private / 'journals', deterministic_check=check_derivation,
            )
            with patch.object(
                host.runtime, 'reconcile_maintenance', side_effect=RuntimeError('归并前崩溃'),
            ):
                with self.assertRaisesRegex(RuntimeError, '归并前崩溃'):
                    apply_derived_record(host, record, executor)
            journal = host.private / 'journals' / (digest('reconcile-fault') + '.json')
            self.assertEqual(json.loads(journal.read_bytes())['state'], 'applied')
            binding = json.loads(self.rows('SELECT record_json FROM maintenance_bindings')[0]['record_json'])
            self.assertEqual(self.task(binding['task_id'])['state'], 'running')
            self.assertEqual(self.rows('SELECT * FROM maintenance_results'), [])
        finally:
            host.close()
        code, result = self.host_cli('apply', '--operation-id', 'reconcile-fault')
        self.assertEqual(code, 0, result)
        self.assertTrue(result['applied'])
        self.assertEqual(self.task(result['runtime_ids']['task_id'])['state'], 'completed')
        self.assertEqual(len(self.rows('SELECT * FROM maintenance_results')), 1)

    def test_private_helpers_and_wechat_cannot_bypass_runtime(self):
        from tools import wechat_article
        writes = (
            lambda: raw_index._refresh_index(apply=True),
            lambda: heal._run_heal(dry_run=False),
            lambda: heal._heal_missing_pages([], dry_run=False),
            lambda: heal._heal_broken_links([], dry_run=False),
            lambda: heal._heal_index_sync([], dry_run=False),
            lambda: wechat_article.write_to_raw_unprocessed({}, 'https://example.invalid/synthetic'),
        )
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        for write in writes:
            with self.subTest(write=write), self.assertRaises(MigrationError):
                write()
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_maintenance_binding_fences_old_ownership_generation(self):
        self.host_cli('raw-index', '--operation-id', 'generation-fence')
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            record = host.load_pending('generation-fence')
            context = _derived_runtime_context(host, 'generation-fence')
            binding = host.runtime.bind_maintenance(
                maintenance_binding(context, record['bundle']),
            )

            def replace_owner(connection):
                row = connection.execute(
                    'SELECT record_json FROM execution_ownerships WHERE task_id=?',
                    (binding['task_id'],),
                ).fetchone()
                ownership = json.loads(row['record_json'])
                ownership['owner'] = 'replacement-owner'
                ownership['generation'] += 1
                connection.execute(
                    'UPDATE execution_ownerships SET owner=?, generation=?, record_json=? '
                    'WHERE task_id=?',
                    (ownership['owner'], ownership['generation'], json.dumps(ownership),
                     binding['task_id']),
                )

            host.runtime.store.mutate(replace_owner)
            with self.assertRaisesRegex(RuntimeServiceError, 'ExecutionOwnership'):
                with host.runtime.maintenance_acceptance_context(binding):
                    pass
            self.assertFalse((host.private / 'journals' / (digest('generation-fence') + '.json')).exists())
        finally:
            host.close()

    def test_terminal_replay_ignores_policy_switch_and_later_vault_changes(self):
        code, applied = self.host_cli('raw-index', '--operation-id', 'terminal-policy', '--apply')
        self.assertEqual(code, 0, applied)
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            task_id = applied['runtime_ids']['task_id']
            policy = json.loads(host.runtime.store.read(
                "SELECT record_json FROM policy_revisions"
            )[0]['record_json'])
            policy['revision'] += 1
            policy['budget']['active_seconds'] += 1
            policy['policy_digest'] = digest({key: value for key, value in policy.items()
                                               if key != 'policy_digest'})
            host.runtime.switch_policy(task_id, policy)
        finally:
            host.close()
        with (self.root / 'raw/index.md').open('a', encoding='utf-8') as stream:
            stream.write('\n后续人工编辑\n')
        journal = self.state / 'private/journals' / (digest('terminal-policy') + '.json')
        before = journal.read_bytes()
        code, replay = self.host_cli('apply', '--operation-id', 'terminal-policy')
        self.assertEqual(code, 0, replay)
        self.assertEqual(replay['status'], 'applied')
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(len(self.rows('SELECT * FROM maintenance_results')), 1)

    def test_applied_conflict_forgery_is_rejected_without_changing_projection(self):
        code, applied = self.host_cli('raw-index', '--operation-id', 'forged-result', '--apply')
        self.assertEqual(code, 0, applied)
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            binding = host.runtime.load_maintenance_binding('forged-result')
            stored = json.loads(self.rows(
                'SELECT record_json FROM maintenance_results'
            )[0]['record_json'])
            forged = dict(stored, recovery_status='conflict')
            with self.assertRaisesRegex(ExecutionReconcileError, 'recovery_status'):
                host.runtime.reconcile_maintenance(binding, forged)
            current = json.loads(self.rows(
                'SELECT record_json FROM maintenance_results'
            )[0]['record_json'])
            self.assertEqual(current, stored)
            self.assertEqual(self.task(binding['task_id'])['state'], 'completed')
        finally:
            host.close()

    def test_learning_task_creation_waits_for_cutover(self):
        self.prepare_legacy('learning-create-pending')
        freeze_legacy_entries(self.root, self.state)
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            with self.assertRaisesRegex(MigrationError, '尚未完成切变'):
                host.create_learning_task()
            self.assertIsNone(host._runtime)
            self.assertFalse((self.state / '.wiki-runtime/learning/runtime.db').exists())
        finally:
            host.close()

    def test_prepared_conflict_forgery_preserves_result_task_and_run(self):
        self.host_cli('raw-index', '--operation-id', 'prepared-conflict')
        host = StandaloneHost(self.root, self.state, offline=True)
        try:
            record = host.load_pending('prepared-conflict')

            def fault(event, index):
                if event == 'after_prepare':
                    raise RuntimeError('保留 prepared')

            executor = Executor(
                self.root, host.private / 'journals', deterministic_check=check_derivation,
                fault=fault,
            )
            prepared = apply_derived_record(host, record, executor)
            self.assertEqual(prepared['status'], 'prepared')
            binding = host.runtime.load_maintenance_binding('prepared-conflict')
            stored = json.loads(self.rows(
                'SELECT record_json FROM maintenance_results'
            )[0]['record_json'])
            forged = dict(stored, recovery_status='conflict')
            with self.assertRaisesRegex(ExecutionReconcileError, 'recovery_status'):
                host.runtime.reconcile_maintenance(binding, forged)
            current = json.loads(self.rows(
                'SELECT record_json FROM maintenance_results'
            )[0]['record_json'])
            self.assertEqual(current, stored)
            self.assertEqual(self.task(binding['task_id'])['state'], 'running')
            run = json.loads(self.rows(
                "SELECT record_json FROM runs WHERE run_id='" + binding['run_id'] + "'"
            )[0]['record_json'])
            self.assertEqual(run['state'], 'running')
        finally:
            host.close()


if __name__ == '__main__':
    unittest.main()
