"""K1 真实临时文件／CLI 验证；不调用模型，不写正式知识库。"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.wiki_runtime.contracts import bytes_digest, digest
from tools.wiki_runtime.evidence.preparation import (
    PreparationError, draft_learning_brief, inspect_context, verify_context,
)

REPO = Path(__file__).resolve().parents[2]


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='knowledge-k1-')
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.name.startswith('knowledge-k1-'))
        self.addCleanup(self.temp.cleanup)
        self.project = self.root / 'project'
        self.inbox = self.root / 'inbox'
        self.inbox.mkdir()
        self.write('wiki/index.md', '# 索引\n- [[备份]]：本地备份与摘要校验\n')
        self.write('wiki/concepts/运维/备份.md', '# 备份\n先停止服务，再复制并校验。\n[[sources/原始规程]]\n')
        self.write('wiki/sources/原始规程.md', '# 来源\n这是资料摘要，不是学习记录。\n')
        self.source = self.inbox / 'source.md'
        self.source.write_text('# 本例\n备份后核对摘要。\n', encoding='utf-8')
        self.request = {'schema': 'knowledge-context-request/1', 'learnerId': 'learner-1',
            'queryTerms': ['备份'], 'sources': [self.source_record()]}
        self.brief_request = {'briefId': 'brief-1', 'version': 1,
            'userIntent': '希望能完成本地备份，二十分钟，需要补讲启动命令。',
            'goals': [{'goalId': 'goal-1', 'outcome': '能按本例完成备份和摘要校验。',
                       'checkMethod': '列出步骤并说明摘要作用。'}],
            'included': ['本地备份'], 'excluded': ['分布式恢复'],
            'pacing': {'sessionMinutes': 20, 'totalMinutes': 20, 'depth': 'brief'},
            'prerequisites': [{'topic': '启动命令', 'observationRef': None, 'handling': '计划补讲'}]}

    def write(self, path, text):
        target = self.project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        return target

    def source_record(self):
        return {'sourceId': 'source-1', 'sourceVersionId': 'v1', 'path': 'source.md',
                'sha256': bytes_digest(self.source.read_bytes()), 'complete': True,
                'mediaType': 'text/markdown'}

    def inspect(self, **kwargs):
        return inspect_context(self.project, self.inbox, self.request, **kwargs)

    def draft(self, context, request=None):
        return draft_learning_brief(context, self.brief_request if request is None else request,
                                     wiki_root=self.project, source_root=self.inbox)

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): bytes_digest(p.read_bytes())
                for p in self.root.rglob('*') if p.is_file()}

    def test_recursive_selection_and_actual_read_scope(self):
        result = self.inspect()
        self.assertEqual(result['result'], 'ready_for_review')
        self.assertEqual(result['documents'][0]['locator'], 'wiki/concepts/运维/备份.md')
        self.assertEqual(result['coverage']['listedPages'], 2)
        self.assertEqual(result['coverage']['readPages'], 1)
        self.assertFalse(result['coverage']['bodySearch'])
        self.assertFalse(result['coverage']['wholeWikiExhausted'])
        self.assertEqual(result['documents'][0]['semanticStatus'], 'unreviewed')

    def test_no_files_or_runtime_state_written(self):
        before = self.inventory()
        context = self.inspect()
        self.assertEqual(verify_context(context, self.project, self.inbox)['result'], 'ready_for_review')
        self.draft(context)
        self.assertEqual(before, self.inventory())

    def test_background_is_not_mastery_or_learning_record(self):
        context = self.inspect()
        observed = context['observations'][0]
        self.assertEqual(observed['basisType'], 'material_available')
        self.assertEqual(observed['planningUse'], 'connect_background')
        self.assertEqual(context['learningEvidence'], {'status': 'not_read', 'refs': []})
        result = self.draft(context)
        self.assertEqual(result['briefState'], 'draft')
        self.assertTrue(result['recognitionRequired'])
        self.assertNotIn('confirmed', result['brief'])

    def test_no_match_is_unknown_not_new_or_unskilled(self):
        self.request['queryTerms'] = ['火星探测']
        result = self.inspect()
        self.assertEqual(result['documents'], [])
        self.assertEqual(result['observations'][0]['basisType'], 'unknown')
        self.assertFalse(result['coverage']['wholeWikiExhausted'])

    def test_page_limit_is_counted_and_unread_candidates_recorded(self):
        self.write('wiki/concepts/备份校验.md', '# 校验\n核对摘要。')
        self.request['limits'] = {'maxPages': 1}
        result = self.inspect()
        self.assertEqual(result['coverage']['readPages'], 1)
        self.assertGreater(result['coverage']['unreadCandidates'], 0)

    def test_ambiguous_wikilinks_do_not_create_fake_page_identity(self):
        self.write('wiki/concepts/另一个分类/备份.md', '# 不同资料\n另一种备份。')
        result = self.inspect()
        self.assertTrue(result['coverage']['ambiguities'])
        self.assertTrue(all(p['pageId'] is None for p in result['documents']))

    def test_explicit_refs_allow_local_source_page_and_deny_out_of_scope(self):
        self.request['wikiRefs'] = ['wiki/sources/原始规程.md']
        self.assertEqual(self.inspect()['documents'][0]['locator'], 'wiki/sources/原始规程.md')
        self.request['wikiRefs'] = ['AGENTS.md']
        with self.assertRaises(PreparationError): self.inspect()

    def test_original_hash_mismatch_rejected(self):
        self.source.write_text('改变的原文', encoding='utf-8')
        with self.assertRaisesRegex(PreparationError, 'source_byte_mismatch'): self.inspect()

    def test_version_conflict_across_observations_rejected(self):
        previous = self.inspect()
        self.source.write_text('新版本正文', encoding='utf-8')
        self.request['sources'][0] = self.source_record()
        with self.assertRaisesRegex(PreparationError, 'source_version_conflict'):
            self.inspect(previous=previous)
        self.request['sources'][0]['sourceVersionId'] = 'v2'
        self.assertEqual(self.inspect(previous=previous)['sources'][0]['sourceVersionId'], 'v2')

    def test_moving_original_preserves_source_identity(self):
        previous = self.inspect()
        self.source.rename(self.inbox / 'moved.md')
        self.request['sources'][0]['path'] = 'moved.md'
        current = self.inspect(previous=previous)
        for key in ('sourceId', 'sourceVersionId', 'byteDigest'):
            self.assertEqual(previous['sources'][0][key], current['sources'][0][key])

    def test_version_history_survives_intermediate_versions_and_batches(self):
        first = self.inspect()
        self.source.write_text('第二版本', encoding='utf-8')
        self.request['sources'][0] = self.source_record()
        self.request['sources'][0]['sourceVersionId'] = 'v2'
        second = self.inspect(previous=first)
        self.assertEqual(len(second['sourceVersions']), 2)
        self.source.write_text('伪装成原先第一版本的新正文', encoding='utf-8')
        self.request['sources'][0] = self.source_record()
        with self.assertRaisesRegex(PreparationError, 'source_version_conflict'):
            self.inspect(previous=second)

    def test_temporarily_removed_source_keeps_its_version_history(self):
        first = self.inspect()
        other = self.inbox / 'other.md'
        other.write_text('另一批资料', encoding='utf-8')
        self.request['sources'] = [{'sourceId': 'other', 'sourceVersionId': 'v1',
            'path': 'other.md', 'sha256': bytes_digest(other.read_bytes()),
            'complete': True, 'mediaType': 'text/markdown'}]
        second = self.inspect(previous=first)
        self.source.write_text('换内容重新使用旧版本', encoding='utf-8')
        self.request['sources'] = [self.source_record()]
        with self.assertRaisesRegex(PreparationError, 'source_version_conflict'):
            self.inspect(previous=second)

    def test_partial_original_remains_explicitly_not_ready(self):
        self.request['sources'][0]['complete'] = False
        context = self.inspect()
        self.assertEqual(context['result'], 'needs_evidence')
        self.assertEqual(self.draft(context)['sourceReadiness'], 'needs_evidence')

    def test_old_page_content_change_invalidates_context_and_draft(self):
        context = self.inspect()
        self.write('wiki/concepts/运维/备份.md', '# 新内容\n新的备份规定。')
        self.assertEqual(verify_context(context, self.project, self.inbox)['result'], 'stale')
        result = self.draft(context)
        self.assertEqual(result['result'], 'stale')
        self.assertIsNone(result['brief'])

    def test_inventory_change_and_page_move_require_reinspection(self):
        context = self.inspect()
        original = self.project / 'wiki/concepts/运维/备份.md'
        original.rename(self.project / 'wiki/concepts/备份.md')
        checked = verify_context(context, self.project, self.inbox)
        self.assertEqual(checked['result'], 'stale')
        self.assertIn('selection_inventory_changed', {r['code'] for r in checked['findings']})
        moved = self.inspect(previous=context)
        self.assertEqual(moved['documents'][0]['byteDigest'], context['documents'][0]['byteDigest'])

    def test_adding_page_invalidates_selection_without_claiming_old_fact_false(self):
        context = self.inspect()
        self.write('wiki/entities/备份工具.md', '# 工具\n另一条候选。')
        checked = verify_context(context, self.project, self.inbox)
        self.assertEqual(checked['findings'], [{'ref': 'wiki', 'code': 'selection_inventory_changed'}])

    def test_context_text_tampering_rejected_even_if_outer_digest_recomputed(self):
        context = self.inspect()
        context['documents'][0]['text'] = '替换后的正文'
        context['contextDigest'] = digest({k: v for k, v in context.items() if k != 'contextDigest'})
        with self.assertRaisesRegex(PreparationError, 'context_text_binding'):
            self.draft(context)

    def test_forged_mastery_background_rejected_after_rehash(self):
        context = self.inspect()
        context['observations'][0]['basisType'] = 'learning_record'
        context['observations'][0]['planningUse'] = 'use_within_evidence_scope'
        context['contextDigest'] = digest({k: v for k, v in context.items() if k != 'contextDigest'})
        with self.assertRaisesRegex(PreparationError, 'background_provenance'):
            self.draft(context)

    def test_nested_context_wrong_types_rejected(self):
        context = self.inspect()
        context['documents'][0]['text'] = 42
        context['contextDigest'] = digest({k: v for k, v in context.items() if k != 'contextDigest'})
        with self.assertRaisesRegex(PreparationError, 'context_row_shape'):
            self.draft(context)

    def test_context_cannot_request_secret_document_path(self):
        context = self.inspect()
        row = context['documents'][0]
        row['locator'] = '.codex/secret.md'
        context['contextDigest'] = digest({k: v for k, v in context.items() if k != 'contextDigest'})
        with self.assertRaisesRegex(PreparationError, 'context_document_scope'):
            self.draft(context)

    def test_missing_goals_and_time_generate_clarification_not_empty_course(self):
        request = {'briefId': 'brief-1', 'version': 1, 'userIntent': '想看看资料，可以学些什么？'}
        result = self.draft(self.inspect(), request)
        self.assertEqual(result['result'], 'needs_clarification')
        self.assertIsNone(result['brief'])
        self.assertEqual(len(result['findings']), 3)

    def test_duplicate_goals_and_inconsistent_time_rejected(self):
        request = copy.deepcopy(self.brief_request)
        request['goals'].append(copy.deepcopy(request['goals'][0]))
        with self.assertRaisesRegex(PreparationError, 'duplicate_goal'):
            self.draft(self.inspect(), request)
        request = copy.deepcopy(self.brief_request)
        request['pacing']['totalMinutes'] = 10
        with self.assertRaisesRegex(PreparationError, 'pacing_order'):
            self.draft(self.inspect(), request)

    def test_material_observation_cannot_skip_prerequisite(self):
        request = copy.deepcopy(self.brief_request)
        request['prerequisites'][0]['handling'] = '已知可用'
        with self.assertRaisesRegex(PreparationError, 'prerequisite_evidence_not_available'):
            self.draft(self.inspect(), request)

    def test_unknown_fields_duplicate_sources_and_boolean_limits_rejected(self):
        self.request['confirmed'] = True
        with self.assertRaisesRegex(PreparationError, 'request_fields'): self.inspect()
        del self.request['confirmed']
        self.request['sources'].append(copy.deepcopy(self.request['sources'][0]))
        with self.assertRaisesRegex(PreparationError, 'duplicate_source_identity'): self.inspect()
        self.request['sources'].pop()
        self.request['limits'] = {'maxPages': True}
        with self.assertRaisesRegex(PreparationError, 'limits_range'): self.inspect()

    def test_byte_limit_and_path_escape_rejected(self):
        self.request['limits'] = {'maxFileBytes': 1}
        with self.assertRaisesRegex(PreparationError, 'byte_limit'): self.inspect()
        del self.request['limits']
        self.request['sources'][0]['path'] = '../outside.md'
        with self.assertRaises(ValueError): self.inspect()

    def test_time_limit_stops_before_reading(self):
        with patch('tools.wiki_runtime.evidence.preparation.time.monotonic', side_effect=[0, 100]):
            with self.assertRaisesRegex(PreparationError, 'time_limit'):
                self.inspect()

    def test_empty_and_binary_utf8_source_rejected(self):
        self.source.write_bytes(b'')
        self.request['sources'][0] = self.source_record()
        with self.assertRaisesRegex(PreparationError, 'empty_source'): self.inspect()
        self.source.write_bytes(b'abc\x00def')
        self.request['sources'][0] = self.source_record()
        with self.assertRaisesRegex(PreparationError, 'non_text_input'): self.inspect()

    def test_hardlinked_source_rejected(self):
        try: os.link(self.source, self.inbox / 'hardlink.md')
        except OSError as exc: self.skipTest(str(exc))
        with self.assertRaises(PermissionError): self.inspect()

    def test_cli_inspect_check_and_draft_with_stdout_only(self):
        request_path = self.root / 'request.json'
        context_path = self.root / 'context.json'
        request_path.write_text(json.dumps(self.request), encoding='utf-8')
        base = [sys.executable, '-X', 'utf8', '-B', '-m', 'tools.wiki_runtime.evidence.cli']
        common = ['--wiki-root', str(self.project), '--source-root', str(self.inbox)]
        def run(args):
            return subprocess.run(base+args+common, cwd=REPO, capture_output=True,
                                  encoding='utf-8', timeout=20)
        before = self.inventory()
        inspected = run(['inspect-context', '--request', str(request_path)])
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertEqual(before, self.inventory())
        context_path.write_text(inspected.stdout, encoding='utf-8')
        checked = run(['check-context', '--context', str(context_path)])
        self.assertEqual(checked.returncode, 0, checked.stderr)
        request_path.write_text(json.dumps(self.brief_request), encoding='utf-8')
        drafted = run(['draft-brief', '--context', str(context_path), '--request', str(request_path)])
        self.assertEqual(drafted.returncode, 0, drafted.stderr)
        self.assertEqual(json.loads(drafted.stdout)['briefState'], 'draft')
        for mutate in (lambda c: c['sources'][0].update(text=42),
                       lambda c: c.update(documents=[42])):
            malformed = json.loads(inspected.stdout)
            mutate(malformed)
            malformed['contextDigest'] = digest({k: v for k, v in malformed.items()
                                                 if k != 'contextDigest'})
            context_path.write_text(json.dumps(malformed), encoding='utf-8')
            for operation in ('check-context', 'draft-brief'):
                args = [operation, '--context', str(context_path)]
                if operation == 'draft-brief': args += ['--request', str(request_path)]
                invalid = run(args)
                self.assertEqual(invalid.returncode, 3, invalid.stderr)
                self.assertEqual(json.loads(invalid.stdout)['result'], 'rejected')
                self.assertNotIn('Traceback', invalid.stderr)
        self.request['confirmed'] = True
        request_path.write_text(json.dumps(self.request), encoding='utf-8')
        rejected = run(['inspect-context', '--request', str(request_path)])
        self.assertEqual(rejected.returncode, 3)
        self.assertNotIn(str(self.inbox), rejected.stdout)


if __name__ == '__main__':
    unittest.main()
