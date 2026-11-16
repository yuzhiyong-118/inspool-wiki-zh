"""临时库、真实 CandidateView/G0–G2/T06；假 transport 不代表模型语义质量。"""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import time
import unittest

from tools.wiki_runtime.candidate import CandidateView
from tools.wiki_runtime.capture import capture, validate_package
from tools.wiki_runtime.contracts import bytes_digest, candidate_digest, digest, validate
from tools.wiki_runtime.executor import Executor, ExecutionError
from tools.wiki_runtime.review import PROMPT_VERSION

BASE = Path(__file__).resolve().parents[1] / 'wiki_runtime/contracts'
RAW = 'raw/unprocessed/原文.md'
PAGE = 'wiki/synthesis/结论.md'
SOURCE = 'wiki/sources/来源.md'


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root, self.payload = self.base / 'vault', self.base / 'payload'
        self.root.mkdir()
        self.payload.mkdir()
        self.journal = self.base / 'private'
        self.write('AGENTS.md', '# 规则\n原始资料正文只读。\n')
        self.write('tools/wiki_runtime/contracts/rules.json', (BASE / 'rules.json').read_bytes())
        self.write(RAW, '---\nprocessing_status: unprocessed\n---\n仅在小样本中可能有效。\n')
        self.text = ('---\ntype: synthesis\nstatus: active\ntopic: 测试\nupdated: 2026-10-26\n---\n# 结论\n'
                     + '保留适用条件与不确定性，原文仅在小样本中可能有效。' * 25 + '\n')
        self.write(PAGE, self.text)
        self.write('wiki/index.md', '# 索引\n[[synthesis/结论]]\n')
        self.write('wiki/log.md', '# 日志\n## [2026-10-26] init | 测试\n[[synthesis/结论]]\n')
        self.write('raw/index.md', '# 素材\n- 未处理：1\n- 待确认：0\n- 已处理：0\n'
                   '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | unprocessed |\n')
        self.calls = []

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode() if isinstance(data, str) else data)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and '.wiki-runtime' not in p.parts}

    def reviewer(self, envelope, *, timeout):
        self.calls.append(timeout)
        request = envelope['input']
        evidence = ['original:' + p + '#L1-L1' for p in request['originals']]
        evidence += ['candidate:' + p + '#L1-L1' for p in request['candidate_files']]
        evidence += ['before:' + c['path'] + '#L1-L1' for c in request['candidate']['changes'] if c['action'] == 'delete']
        return dict(contract_version='1.0', **request['bindings'], reviewer_id=envelope['reviewer_id'],
                    result='recommend_pass', findings=[], evidence_refs=evidence)

    def executor(self, **kwargs):
        options = dict(reviewer=self.reviewer, reserve_call=lambda: True)
        options.update(kwargs)
        return Executor(self.root, self.journal, **options)

    def bundle(self, values=None, operation='inspool', moves=None, operation_id='execution-test'):
        if values is None:
            values = {p: (self.root / p).read_bytes() + b'\n' for p in (PAGE, 'wiki/index.md', 'wiki/log.md')}
        changes = []
        for index, (path, data) in enumerate(values.items()):
            data = data.encode() if isinstance(data, str) else data
            name = str(index) + '.md'
            (self.payload / name).write_bytes(data)
            target = self.root / path
            pre = dict(kind='hash', sha256=bytes_digest(target.read_bytes())) if target.exists() else dict(kind='absent')
            change = dict(action='write', path=path, payload_path=name, sha256=bytes_digest(data), precondition=pre)
            if moves and path in moves:
                change.update(action='move', source=moves[path], source_sha256=bytes_digest((self.root / moves[path]).read_bytes()))
            changes.append(change)
        candidate = dict(contract_version='1.0', operation_id=operation_id, changes=changes)
        view = CandidateView(self.root, candidate, self.payload)
        list(view.iter_paths())
        snapshot = view.dependency_snapshot()
        manifest = dict(contract_version='1.0', operation_id=operation_id, operation_type=operation, task='保留原文条件',
            input_refs=[RAW], allowed_paths=list(values) + list((moves or {}).values()), rules_path='AGENTS.md',
            rules_digest=bytes_digest((self.root / 'AGENTS.md').read_bytes()),
            mapping_digest=bytes_digest((BASE / 'rules.json').read_bytes()), validator_version='gates-1.0',
            review_prompt_version=PROMPT_VERSION, candidate_digest=candidate_digest(candidate),
            dependencies_digest=digest(snapshot), round=1, required_gates=['G0', 'G1', 'G2'], authorization_refs=[])
        return dict(manifest=manifest, candidate=candidate, snapshot=snapshot, payload_root=str(self.payload),
                    reports=[{'result': 'pass'}], review={'result': 'recommend_pass'})

    def fault(self, event, index):
        def inject(actual_event, actual_index):
            if (actual_event, actual_index) == (event, index):
                raise RuntimeError('注入故障')
        return inject

    def test_apply_and_repeat_are_idempotent(self):
        bundle = self.bundle()
        executor = self.executor()
        result = executor.apply(bundle)
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual(len(self.calls), 1)
        after = self.snapshot()
        self.assertEqual(executor.apply(bundle), result)
        self.assertEqual(executor.recover('execution-test'), result)
        self.assertEqual(self.snapshot(), after)

    def test_executor_reuses_coordinator_budget_without_reset(self):
        from tools.wiki_runtime.coordinator import Coordinator
        params = dict(operation_id='shared-budget', operation_type='inspool', task='共享预算',
                      allowed_paths=[PAGE, 'wiki/index.md', 'wiki/log.md'], input_refs=[RAW],
                      max_calls=1, max_seconds=120, call_timeout=30)
        coordinator = Coordinator(self.root, self.base / 'coordinator', **params)
        self.assertTrue(coordinator.reserve_call())
        before = self.snapshot()
        with self.assertRaisesRegex(ExecutionError, '预算'):
            self.executor(reserve_call=coordinator.reserve_call,
                          remaining_timeout=coordinator.remaining_timeout).apply(
                              self.bundle(operation_id='shared-budget'))
        self.assertFalse(self.calls)  # 预算耗尽后连独立模型调用也不能发起。
        self.assertEqual(before, self.snapshot())
        restarted = Coordinator(self.root, self.base / 'coordinator', **params)
        self.assertFalse(restarted.reserve_call())

    def test_each_write_boundary_recovers_and_repeats(self):
        bundle = self.bundle()
        before = self.snapshot()
        for event in ('before_intent', 'after_intent', 'after_replace', 'after_write', 'after_done'):
            for index in range(3):
                with self.subTest(event=event, index=index):
                    bundle['manifest']['operation_id'] = bundle['candidate']['operation_id'] = bundle['snapshot']['operation_id'] = event + str(index)
                    bundle['manifest']['candidate_digest'] = candidate_digest(bundle['candidate'])
                    bundle['manifest']['dependencies_digest'] = digest(bundle['snapshot'])
                    result = self.executor(fault=self.fault(event, index)).apply(bundle)
                    self.assertEqual(result['state'], 'recovery_required', result)
                    executor = self.executor()
                    recovered = executor.recover(event + str(index))
                    self.assertEqual(recovered['state'], 'recovered', recovered)
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(executor.recover(event + str(index)), recovered)
                    self.assertEqual(executor.apply(bundle), recovered)

    def test_user_edit_blocks_entire_recovery_before_any_rollback(self):
        bundle = self.bundle()
        result = self.executor(fault=self.fault('after_done', 2)).apply(bundle)
        self.assertEqual(result['state'], 'recovery_required')
        self.write(PAGE, '用户随后编辑\n')
        before = self.snapshot()
        result = self.executor().recover('execution-test')
        self.assertEqual(result['recovery_status'], 'conflict')
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ExecutionError):
            Executor(self.root, self.base / 'other-private').apply(self.bundle(operation_id='other'))

    def test_recovery_edit_during_hook_is_not_overwritten(self):
        self.executor(fault=self.fault('after_done', 2)).apply(self.bundle())
        def edit(event, index):
            if event == 'recover_after_intent' and index == 2:
                self.write('wiki/log.md', '用户在恢复期间编辑\n')
        before_page = (self.root / PAGE).read_bytes()
        result = self.executor(fault=edit).recover('execution-test')
        self.assertEqual(result['recovery_status'], 'conflict')
        self.assertEqual((self.root / 'wiki/log.md').read_text(encoding='utf-8'), '用户在恢复期间编辑\n')
        self.assertEqual((self.root / PAGE).read_bytes(), before_page)

    def test_each_recovery_boundary_can_resume(self):
        before = self.snapshot()
        for event in ('recover_before_intent', 'recover_after_intent', 'recover_after_write', 'recover_after_done'):
            for index in range(3):
                operation_id = event + str(index)
                with self.subTest(event=event, index=index):
                    bundle = self.bundle(operation_id=operation_id)
                    self.executor(fault=self.fault('after_done', 2)).apply(bundle)
                    first = self.executor(fault=self.fault(event, index)).recover(operation_id)
                    self.assertEqual(first['state'], 'recovery_required')
                    result = self.executor().recover(operation_id)
                    self.assertEqual(result['state'], 'recovered', result)
                    self.assertEqual(self.snapshot(), before)

    def test_forged_pass_cannot_skip_review_or_budget(self):
        bundle = self.bundle()
        bundle['manifest']['required_gates'] = []
        for kwargs in (dict(reviewer=None), dict(reserve_call=None), dict(reserve_call=lambda: False)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ExecutionError):
                self.executor(**kwargs).apply(bundle)
        self.assertEqual(self.calls, [])

    def test_deterministic_callback_cannot_exempt_semantic_maintenance(self):
        bundle = self.bundle(operation='inspool')
        before = self.snapshot()
        checks = []
        def false_exemption(*args):
            checks.append(args)
            return True
        with self.assertRaises(ExecutionError):
            self.executor(reviewer=None, deterministic_check=false_exemption).apply(bundle)
        self.assertEqual(checks, [])
        self.assertEqual(self.snapshot(), before)

    def test_reviewer_failure_timeout_and_late_edit(self):
        bundle = self.bundle()
        def slow(envelope, *, timeout):
            time.sleep(.05)
            return self.reviewer(envelope, timeout=timeout)
        with self.assertRaises(ExecutionError):
            self.executor(reviewer=slow, review_timeout=.005).apply(bundle)
        time.sleep(.06)
        def edit(envelope, *, timeout):
            self.write(PAGE, '用户并发编辑\n')
            return self.reviewer(envelope, timeout=timeout)
        with self.assertRaises(ValueError):
            self.executor(reviewer=edit).apply(bundle)
        self.assertEqual((self.root / PAGE).read_text(encoding='utf-8'), '用户并发编辑\n')

    def test_hash_scope_payload_and_versions_are_checked(self):
        for field, value in [('allowed_paths', []), ('rules_digest', '0' * 64), ('validator_version', 'fake')]:
            bundle = self.bundle()
            bundle['manifest'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.executor().apply(bundle)
        bundle = self.bundle()
        (self.payload / '0.md').write_bytes(b'fake payload')
        with self.assertRaises(ValueError):
            self.executor().apply(bundle)

    def test_missing_new_file_precondition_and_hardlinks_are_rejected(self):
        bundle = self.bundle({'wiki/meta/新页.md': '# 新页\n', 'wiki/index.md': '# 索引\n', 'wiki/log.md': '# 日志\n'})
        self.write('wiki/meta/新页.md', '用户抢先创建')
        with self.assertRaises(ValueError):
            self.executor().apply(bundle)
        (self.root / 'wiki/meta/新页.md').unlink()
        os.link(self.root / PAGE, self.root / 'wiki/meta/hard.md')
        with self.assertRaises(ValueError):
            self.executor().apply(self.bundle())

    def test_index_reordering_does_not_require_new_human_approval(self):
        bundle = self.bundle({'wiki/index.md': '# 索引\n\n[[synthesis/结论]]\n'}, operation='index_rebuild')
        result = self.executor(reviewer=None, reserve_call=None).apply(bundle)
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual(self.calls, [])

    def ingest_values(self):
        return {RAW: '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/来源]]"\n---\n仅在小样本中可能有效。\n',
            SOURCE: '---\ntype: source\nstatus: active\ntopic: 测试\nupdated: 2026-10-26\nraw_note: "[[raw/unprocessed/原文]]"\nrelated_synthesis: ["[[synthesis/结论]]"]\n---\n# 来源\n'
                    + '保留原始限定与来源证据。' * 30 + '\n参见 [[synthesis/结论]]\n',
            PAGE: self.text.replace('---\n#', 'related_sources: ["[[sources/来源]]"]\n---\n#') + '\n证据来自 [[sources/来源]]\n',
            'wiki/index.md': '# 索引\n[[synthesis/结论]]\n[[sources/来源]]\n[[meta/overview]]\n',
            'wiki/log.md': '# 日志\n## [2026-10-26] ingest | 来源\n[[sources/来源]]\n',
            'wiki/meta/overview.md': '# 总览\n[[sources/来源]]\n',
            'raw/index.md': '# 素材\n- 未处理：0\n- 待确认：1\n- 已处理：0\n| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | pending_review | [[sources/来源]] |\n'}

    def test_ingest_orders_pending_after_all_companions(self):
        values = self.ingest_values()
        def inspect(event, index):
            if event == 'after_done' and index < len(values) - 1:
                self.assertIn(b'processing_status: unprocessed', (self.root / RAW).read_bytes())
            if event == 'before_intent' and index == len(values) - 1:
                for path, text in values.items():
                    if path != RAW:
                        self.assertEqual((self.root / path).read_bytes(), text.encode())
        result = self.executor(fault=inspect).apply(self.bundle(values, operation='ingest'))
        self.assertEqual(result['state'], 'applied', result)

    def approve_bundle(self, operation_id='execution-test'):
        self.write(RAW, '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/来源]]"\n---\n仅在小样本中可能有效。\n')
        self.write(SOURCE, '---\nraw_note: "[[raw/unprocessed/原文]]"\n---\n# 来源\n原始资料 [[raw/unprocessed/原文]]\n' + '原文有条件。' * 40)
        self.write('wiki/index.md', '# 索引\n[[synthesis/结论]]\n[[sources/来源]]\n')
        values = {'raw/processed/原文.md': '---\nprocessing_status: processed\nprocessed_into: "[[sources/来源]]"\nreviewed_at: 2026-10-26\n---\n仅在小样本中可能有效。\n',
            SOURCE: (self.root / SOURCE).read_text(encoding='utf-8').replace('raw/unprocessed/', 'raw/processed/'),
            'wiki/index.md': (self.root / 'wiki/index.md').read_bytes() + b'\n',
            'wiki/log.md': '# 日志\n## [2026-10-26] approve | 来源\n[[sources/来源]]\n',
            'raw/index.md': '# 素材\n- 未处理：0\n- 待确认：0\n- 已处理：1\n| 素材 | 状态 |\n| [[raw/processed/原文]] | processed | [[sources/来源]] |\n'}
        return self.bundle(values, operation='approve', moves={'raw/processed/原文.md': RAW}, operation_id=operation_id)

    def test_approve_forgery_binding_and_move_metadata(self):
        bundle = self.approve_bundle()
        with self.assertRaises(ExecutionError):
            self.executor().apply(bundle, approval={'user_confirmed': True})
        expected = self.executor()._context(bundle['manifest'], bundle['candidate'], bundle['snapshot'])
        secret = object()
        def check(context, approval):
            self.assertEqual(context['source_paths'], [RAW])
            return context == expected and approval is secret
        executor = self.executor(approval_check=check)
        with self.assertRaises(ExecutionError):
            executor.apply(bundle, approval={'user_confirmed': True})
        result = executor.apply(bundle, approval=secret)
        self.assertEqual(result['state'], 'applied', result)
        self.assertFalse((self.root / RAW).exists())
        self.assertIn(b'processing_status: processed', (self.root / 'raw/processed/原文.md').read_bytes())
        self.assertNotIn('raw/unprocessed/原文', (self.root / SOURCE).read_text(encoding='utf-8'))
        self.assertEqual(executor.apply(bundle, approval=secret), result)

    def test_approve_every_primitive_failure_rolls_back_move_and_metadata(self):
        bundle = self.approve_bundle()
        before = self.snapshot()
        for index in range(len(bundle['candidate']['changes']) + 1):
            with self.subTest(index=index):
                operation_id = 'move' + str(index)
                bundle = self.bundle({c['path']: (self.payload / c['payload_path']).read_bytes()
                                      for c in bundle['candidate']['changes']}, operation='approve',
                                      moves={'raw/processed/原文.md': RAW}, operation_id=operation_id)
                result = self.executor(approval_check=lambda context, approval: True,
                    fault=self.fault('after_write', index)).apply(bundle, approval=object())
                self.assertEqual(result['state'], 'recovery_required', result)
                recovered = self.executor().recover(operation_id)
                self.assertEqual(recovered['state'], 'recovered', recovered)
                self.assertEqual(self.snapshot(), before)

    def test_capture_without_trusted_package_is_rejected(self):
        bundle = self.bundle({'raw/unprocessed/新来源.md': '---\nprocessing_status: unprocessed\n---\n伪造正文\n',
                              'raw/index.md': '# 素材\n- 未处理：2\n- 待确认：0\n- 已处理：0\n'
                              '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | unprocessed |\n| [[raw/unprocessed/新来源]] | unprocessed |\n'}, operation='capture')
        with self.assertRaisesRegex(ExecutionError, '可信资料包'):
            self.executor().apply(bundle)

    def test_rule_and_tool_maintenance_require_host_authorization(self):
        for operation, path in [('rule_maintenance', 'AGENTS.md'), ('tool_maintenance', 'tools/validator.py')]:
            with self.subTest(operation=operation):
                bundle = self.bundle({path: '# 受信代码候选\n'}, operation=operation)
                with self.assertRaisesRegex(ExecutionError, 'G4'):
                    self.executor().apply(bundle, approval={'user_confirmed': True})

    def test_private_journal_overlap_and_root_lock(self):
        with self.assertRaises(ExecutionError):
            Executor(self.root, self.root / 'wiki/journal')
        with self.assertRaises(ExecutionError):
            self.executor().apply(dict(self.bundle(), payload_root=str(self.base)))
        executor = self.executor()
        with executor._lock():
            with self.assertRaises(ExecutionError):
                Executor(self.root, self.base / 'other').apply(self.bundle())

    def test_initial_and_commit_journal_boundaries(self):
        before = self.snapshot()
        for event in ('before_prepare', 'after_prepare', 'before_active', 'after_active', 'after_applying', 'after_commit'):
            with self.subTest(event=event):
                bundle = self.bundle(operation_id=event)
                executor = self.executor(fault=self.fault(event, -1))
                if event == 'before_prepare':
                    with self.assertRaises(RuntimeError):
                        executor.apply(bundle)
                    self.assertEqual(self.snapshot(), before)
                    continue
                result = executor.apply(bundle)
                recovered = self.executor().recover(event)
                if event == 'after_commit':
                    self.assertEqual(result['state'], 'applied')
                    self.assertEqual(recovered['state'], 'applied')
                else:
                    self.assertEqual(recovered['state'], 'recovered', recovered)
                    self.assertEqual(self.snapshot(), before)

    def test_non_target_dependency_edit_and_new_directory_stop_apply(self):
        original = (self.root / RAW).read_bytes()
        edited = '---\nprocessing_status: unprocessed\n---\n用户改原文\n'.encode()
        for kind in ('source', 'file', 'directory'):
            with self.subTest(kind=kind):
                bundle = self.bundle(operation_id=kind)
                def edit(event, index):
                    if event == 'after_done' and index == 0:
                        if kind == 'source':
                            self.write(RAW, edited)
                        elif kind == 'file':
                            self.write('wiki/user-new.md', '用户新页\n')
                        else:
                            (self.root / 'wiki/user-dir').mkdir()
                result = self.executor(fault=edit).apply(bundle)
                self.assertEqual(result['state'], 'recovery_required', result)
                self.assertEqual(self.executor().recover(kind)['state'], 'recovered')
                if kind == 'file':
                    self.assertEqual((self.root / 'wiki/user-new.md').read_bytes(), '用户新页\n'.encode())
                    (self.root / 'wiki/user-new.md').unlink()
                elif kind == 'directory':
                    (self.root / 'wiki/user-dir').rmdir()
                else:
                    self.assertEqual((self.root / RAW).read_bytes(), edited)
                    self.write(RAW, original)

    def test_final_approval_revoked_during_review_is_rejected(self):
        bundle = self.approve_bundle()
        valid = [True]
        def reviewer(envelope, *, timeout):
            valid[0] = False
            return self.reviewer(envelope, timeout=timeout)
        before = self.snapshot()
        with self.assertRaisesRegex(ExecutionError, '批准已失效'):
            self.executor(reviewer=reviewer, approval_check=lambda context, approval: valid[0]).apply(bundle, approval=object())
        self.assertEqual(self.snapshot(), before)

    def test_atomic_replace_race_retains_actual_user_bytes_and_stops_recovery(self):
        user = '用户在最终哈希与原子替换之间写入\n'.encode()
        bundle = self.bundle()
        def edit(event, index):
            if event == 'before_replace' and index == 0:
                self.write(PAGE, user)
        result = self.executor(fault=edit).apply(bundle)
        self.assertEqual(result['state'], 'recovery_required', result)
        backups = list(self.journal.glob('replaced-*.bin'))
        self.assertTrue(any(p.read_bytes() == user for p in backups))
        before = self.snapshot()
        recovered = self.executor().recover('execution-test')
        self.assertEqual(recovered['recovery_status'], 'conflict', recovered)
        self.assertEqual(self.snapshot(), before)

    def test_new_target_race_never_overwrites_created_user_file(self):
        values = {'wiki/meta/新页.md': '# 新页\n' + '候选内容。' * 60,
                  'wiki/index.md': '# 索引\n[[synthesis/结论]]\n[[meta/新页]]\n',
                  'wiki/log.md': '# 日志\n## [2026-10-26] init | 新页\n[[meta/新页]]\n'}
        bundle = self.bundle(values)
        def edit(event, index):
            if event == 'before_replace' and index == 0:
                self.write('wiki/meta/新页.md', '用户同时创建\n')
        result = self.executor(fault=edit).apply(bundle)
        self.assertEqual(result['state'], 'recovery_required', result)
        self.assertEqual((self.root / 'wiki/meta/新页.md').read_bytes(), '用户同时创建\n'.encode())

    def test_approval_is_bound_to_entire_candidate_and_scope(self):
        bundle = self.approve_bundle()
        context = self.executor()._context(bundle['manifest'], bundle['candidate'], bundle['snapshot'])
        bundle['manifest']['task'] = '更换任务'
        with self.assertRaises(ExecutionError):
            self.executor(approval_check=lambda actual, approval: actual == context).apply(bundle, approval=object())

    def test_capture_uses_authenticated_package_and_rejects_tampering(self):
        package = json.loads((BASE / 'examples/source_package.valid.json').read_bytes())
        package_root = self.base / 'package'
        original = '仅在小样本中可能有效。\n'.encode()
        for item in [*package['originals'], package['extracted']]:
            file = package_root / item['path']
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(original)
            item['sha256'] = bytes_digest(original)
        values = {'raw/unprocessed/新来源.md': b'---\nprocessing_status: unprocessed\n---\n' + original,
            'raw/index.md': '# 素材\n- 未处理：2\n- 待确认：0\n- 已处理：0\n'
            '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | unprocessed |\n| [[raw/unprocessed/新来源]] | unprocessed |\n'}
        bundle = self.bundle(values, operation='capture')
        with self.assertRaisesRegex(ExecutionError, '可信资料包验证拒绝'):
            self.executor(package_check=lambda context, packages: False).apply(bundle, source_packages=[(package, package_root)])
        bad = copy.deepcopy(package)
        bad['quality']['status'] = 'partial'
        with self.assertRaisesRegex(ExecutionError, '人工处理'):
            self.executor(package_check=lambda context, packages: True).apply(bundle, source_packages=[(bad, package_root)])
        extracted = package_root / package['extracted']['path']
        extracted.write_bytes(b'tampered')
        with self.assertRaisesRegex(ExecutionError, '哈希无效'):
            self.executor(package_check=lambda context, packages: True).apply(bundle, source_packages=[(package, package_root)])
        extracted.write_bytes(original)
        result = self.executor(package_check=lambda context, packages: True).apply(bundle, source_packages=[(package, package_root)])
        self.assertEqual(result['state'], 'applied', result)

    def test_real_capture_validate_package_and_apply_preserves_original(self):
        package, package_root = capture(self.root / RAW, self.base / 'captured', 'plain-md', vault_root=self.root)
        validate_package(package, package_root)
        original = (package_root / package['originals'][0]['path']).read_bytes()
        extracted = (package_root / package['extracted']['path']).read_bytes()
        values = {'raw/unprocessed/采集记录.md': extracted,
            'raw/assets/采集原件.md': original,
            'raw/index.md': '# 素材\n- 未处理：2\n- 待确认：0\n- 已处理：0\n'
            '| 素材 | 状态 |\n| [[raw/unprocessed/原文]] | unprocessed |\n| [[raw/unprocessed/采集记录]] | unprocessed |\n'}
        def trusted(context, packages):
            if len(packages) != 1 or packages[0][0] != package or packages[0][1] != package_root:
                return False
            validate_package(*packages[0])
            return context['operation_type'] == 'capture'
        result = self.executor(package_check=trusted).apply(self.bundle(values, operation='capture'),
                                                          source_packages=[(package, package_root)])
        self.assertEqual(result['state'], 'applied', result)
        self.assertEqual((self.root / 'raw/assets/采集原件.md').read_bytes(), (self.root / RAW).read_bytes())

    def test_symbolic_directory_is_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        link = self.root / 'wiki/redirect'
        try:
            os.symlink(outside, link, target_is_directory=True)
        except OSError as exc:
            self.skipTest('本机没有 symlink 创建权限: ' + str(exc))
        try:
            with self.assertRaises(ValueError):
                self.executor().apply(self.bundle())
        finally:
            link.unlink()

    def test_real_process_exit_after_new_file_link_is_recoverable(self):
        values = {'wiki/meta/新页.md': '# 新页\n' + '完整候选内容。' * 50,
                  'wiki/index.md': '# 索引\n[[synthesis/结论]]\n[[meta/新页]]\n',
                  'wiki/log.md': '# 日志\n## [2026-10-26] init | 新页\n[[meta/新页]]\n'}
        bundle = self.bundle(values)
        path = self.base / 'bundle.json'
        path.write_text(json.dumps(bundle), encoding='utf-8')
        script = '''
import json, os, sys
from tools.wiki_runtime.executor import Executor
def reviewer(envelope, *, timeout):
    request = envelope['input']
    refs = ['original:' + p + '#L1-L1' for p in request['originals']]
    refs += ['candidate:' + p + '#L1-L1' for p in request['candidate_files']]
    return dict(contract_version='1.0', **request['bindings'], reviewer_id=envelope['reviewer_id'], result='recommend_pass', findings=[], evidence_refs=refs)
def fault(event, index):
    if event == 'after_replace' and index == 0:
        os._exit(87)
bundle = json.loads(open(sys.argv[3], encoding='utf-8').read())
Executor(sys.argv[1], sys.argv[2], reviewer=reviewer, reserve_call=lambda: True, fault=fault).apply(bundle)
'''
        before = self.snapshot()
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.root), str(self.journal), str(path)],
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 87, result.stderr)
        self.assertEqual((self.root / 'wiki/meta/新页.md').stat().st_nlink, 2)
        recovered = self.executor().recover('execution-test')
        self.assertEqual(recovered['state'], 'recovered', recovered)
        self.assertEqual(self.snapshot(), before)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction 回归')
    def test_windows_junction_is_rejected_without_touching_target(self):
        outside = self.base / 'junction-outside'
        outside.mkdir()
        sentinel = outside / 'sentinel.txt'
        sentinel.write_bytes(b'user data')
        link = self.root / 'wiki/junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(ValueError):
                self.executor().apply(self.bundle())
            self.assertEqual(sentinel.read_bytes(), b'user data')
        finally:
            link.rmdir()


if __name__ == '__main__':
    unittest.main()
