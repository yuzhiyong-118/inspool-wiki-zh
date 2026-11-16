"""K2 临时库与真实子进程检查。语义记录是合成测试输入，不冒充真实评审。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.wiki_runtime.contracts import bytes_digest, digest
from tools.wiki_runtime.evidence.package_protocol import evidence_digest, evidence_claim_relation_digest
from tools.wiki_runtime.evidence.preparation import PreparationError, inspect_context
from tools.wiki_runtime.evidence.knowledge import (
    partition_knowledge, prepare_knowledge, text_lines, verify_knowledge,
)

REPO = Path(__file__).resolve().parents[2]


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='knowledge-k2-')
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.name.startswith('knowledge-k2-'))
        self.addCleanup(self.temp.cleanup)
        self.project = self.root / 'project'
        self.inbox = self.root / 'inbox'
        self.inbox.mkdir()
        self.write('wiki/index.md', '# 索引\n- [[备份]]：备份步骤\n')
        self.old = self.write('wiki/concepts/运维/备份.md', '# 备份\n本合成规程复制前无需停服。\n')
        self.source = self.inbox / 'source.md'
        self.source.write_bytes('# 合成规程\r\n本合成规程复制前必须停服。\r\n复制后应核对摘要。\r\n'.encode())
        self.context_request = {'schema': 'knowledge-context-request/1', 'learnerId': 'synthetic',
            'queryTerms': ['备份'], 'sources': [self.source_record('s1', self.source)]}
        self.context = self.inspect()
        e = self.evidence('e1', 's1', 2, '本合成规程复制前必须停服。')
        self.request = {'schema': 'knowledge-preparation-request/1', 'packageId': 'knowledge',
            'version': 1, 'intent': '仅核验本合成规程，不发布课程或写库。',
            'evidence': [e], 'claims': [self.claim('c1', '复制前必须停服。')],
            'relations': [self.relation(e, 'c1')], 'conflicts': [], 'existingKnowledge': [],
            'sourceObservations': [self.observation('s1', 'e1')]}

    def write(self, locator, text):
        path = self.project / locator
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def source_record(self, sid, path):
        return {'sourceId': sid, 'sourceVersionId': 'v1', 'path': path.name,
            'sha256': bytes_digest(path.read_bytes()), 'complete': True, 'mediaType': 'text/markdown'}

    def inspect(self):
        return inspect_context(self.project, self.inbox, self.context_request)

    def evidence(self, eid, sid, line, excerpt):
        source = next(s for s in self.context['sources'] if s['sourceId'] == sid)
        return {'evidence_id': eid, 'source_id': sid, 'source_version': source['sourceVersionId'],
            'source_digest': source['byteDigest'], 'locator': {'start_line': line, 'end_line': line},
            'excerpt': excerpt, 'extraction_state': 'complete'}

    def claim(self, cid, text):
        return {'claim_id': cid, 'text': text, 'conditions': ['本合成规程'],
                'attribution': '合成规程规定', 'evidence_status': 'supported'}

    def relation(self, e, cid, relation='supports'):
        return {'evidence_id': e['evidence_id'], 'evidence_digest': evidence_digest(e),
            'claim_id': cid, 'relation': relation, 'conditions': ['本合成规程'],
            'verification_status': 'verified'}

    def observation(self, sid, eid):
        return {'sourceId': sid, 'canonicalLocator': 'synthetic:' + sid, 'sourceType': 'first_party',
            'topics': ['本例备份'], 'publishedAt': None, 'acquiredBy': '合成测试原件',
            'originId': 'synthetic-origin', 'upstreamSourceIds': [], 'basisEvidenceIds': [eid],
            'reason': '合成测试声明，不是认证。'}

    def prepare(self, review=None, previous=None):
        return prepare_knowledge(self.context, self.request, wiki_root=self.project,
                                 source_root=self.inbox, review=review, previous=previous)

    def review(self, prepared=None):
        p = self.prepare() if prepared is None else prepared
        rr = p['reviewRequest']
        return {'schema': 'knowledge-review-observation/1', 'id': 'synthetic-review',
            'requestDigest': rr['requestDigest'], 'reviewer': 'synthetic-operator',
            'recordedAt': '2026-11-11', 'assurance': 'operator_supplied',
            'basisEvidenceIds': rr['scope']['evidenceIds'],
            'claims': [{'ref': c['claim_id'], 'decision': 'reviewed_for_scope',
                        'conditions': c['conditions'], 'reason': '合成评审输入。'}
                       for c in p['package']['claims']],
            'relations': [{'ref': d, 'decision': 'accepted', 'reason': '合成评审输入。'}
                          for d in rr['scope']['relationDigests']],
            'conflicts': [], 'comparisons': [],
            'documents': [{'ref': d, 'decision': 'irrelevant', 'reason': '合成审查认为本轮无关系；非真实语义结果。'}
                          for d in rr['scope']['documentLocators']],
            'sources': [{'ref': s, 'decision': 'reviewed_for_scope', 'reason': '合成来源。'}
                        for s in rr['scope']['sourceIds']]}

    def rebind_relations(self):
        by_id = {e['evidence_id']: e for e in self.request['evidence']}
        for row in self.request['relations']:
            row['evidence_digest'] = evidence_digest(by_id[row['evidence_id']])

    def inventory(self):
        return {p.relative_to(self.root).as_posix(): bytes_digest(p.read_bytes())
                for p in self.root.rglob('*') if p.is_file()}

    def test_missing_review_is_not_approval(self):
        before = self.inventory()
        result = self.prepare()
        self.assertEqual(result['knowledgeState'], 'needs_review')
        self.assertFalse(result['formalWriteAuthorized'])
        self.assertEqual(before, self.inventory())

    def test_valid_scoped_observation_and_recheck(self):
        result = self.prepare(self.review())
        self.assertEqual(result['knowledgeState'], 'reviewed_for_scope')
        self.assertEqual(result, verify_knowledge(self.context, result,
                         wiki_root=self.project, source_root=self.inbox))
        self.assertFalse(result['formalWriteAuthorized'])
        self.assertIsNone(result['independence']['independentCorroborationCount'])

    def test_forged_excerpt_rejected_even_rehashed(self):
        self.request['evidence'][0]['excerpt'] = '这是伪造的摘录。'
        self.rebind_relations()
        with self.assertRaisesRegex(PreparationError, 'excerpt_mismatch'): self.prepare()

    def test_wrong_line_rejected(self):
        self.request['evidence'][0]['locator']['end_line'] = 99
        self.rebind_relations()
        with self.assertRaises(ValueError): self.prepare()

    def test_newline_policy_and_raw_bytes(self):
        self.assertEqual(text_lines('甲\r\n乙\n'), ['甲', '乙'])
        self.assertEqual(text_lines('甲\r乙\n\n'), ['甲\r乙', ''])
        p = self.prepare()
        self.assertEqual(p['package']['sources'][0]['content_digest'], bytes_digest(self.source.read_bytes()))
        self.assertEqual(p['package']['sources'][0]['readable_range']['end_line'], 3)

    def test_unicode_whitespace_and_bom_not_normalized(self):
        for excerpt in (' 本合成规程复制前必须停服。', '\ufeff本合成规程复制前必须停服。'):
            self.request['evidence'][0]['excerpt'] = excerpt
            self.rebind_relations()
            with self.assertRaisesRegex(PreparationError, 'excerpt_mismatch'): self.prepare()

    def test_supported_without_relation_is_missing_evidence(self):
        self.request['relations'] = []
        self.assertEqual(self.prepare()['knowledgeState'], 'needs_evidence')

    def test_partial_source_and_extraction_block_even_reviewed(self):
        for partial_source in (True, False):
            if partial_source:
                self.context_request['sources'][0]['complete'] = False
                self.context = self.inspect()
            else:
                self.context_request['sources'][0]['complete'] = True
                self.context = self.inspect()
                self.request['evidence'][0]['extraction_state'] = 'partial'
                self.rebind_relations()
            self.assertEqual(self.prepare()['knowledgeState'], 'needs_evidence')
            self.assertEqual(self.prepare(self.review())['knowledgeState'], 'needs_evidence')

    def test_real_excerpt_without_support_rejected_by_observation(self):
        self.request['claims'][0]['text'] = '备份能保证不会出现任何数据损坏。'
        review = self.review()
        review['relations'][0].update(decision='rejected', reason='摘录只规定停服，不支持零损坏保证。')
        result = self.prepare(review)
        self.assertEqual(result['knowledgeState'], 'needs_evidence')
        self.assertEqual(result['claimChecks'][0]['answerUse'], 'blocked')

    def test_conditions_not_silently_broadened(self):
        self.request['claims'][0]['conditions'] = []
        self.assertIn('support_condition_mismatch', self.prepare(self.review())['claimChecks'][0]['blockers'])

    def test_qualification_must_be_in_claim_scope(self):
        qualifier = copy.deepcopy(self.request['relations'][0])
        qualifier.update(relation='qualifies', conditions=['仅版本二'])
        self.request['relations'].append(qualifier)
        self.assertIn('unapplied_qualification', self.prepare(self.review())['claimChecks'][0]['blockers'])

    def add_conflict(self):
        self.request['claims'].append(self.claim('c2', '复制前无需停服。'))
        self.request['relations'].append(self.relation(self.request['evidence'][0], 'c2', 'contradicts'))
        self.request['conflicts'] = [{'conflict_id': 'f1', 'claim_ids': ['c1', 'c2'],
            'evidence_ids': ['e1'], 'status': 'unresolved', 'resolution': None}]

    def test_unresolved_conflict_is_retained_and_blocked(self):
        self.add_conflict()
        p = self.prepare(self.review())
        self.assertEqual(p['knowledgeState'], 'needs_evidence')
        self.assertEqual(p['package']['conflicts'], self.request['conflicts'])
        with self.assertRaisesRegex(PreparationError, 'partition_conflicted_claim'):
            partition_knowledge(p, ['c1'], package_id='split', version=1, reason='不能隐藏另一方。')

    def test_resolution_text_alone_not_enough(self):
        self.add_conflict()
        self.request['conflicts'][0].update(status='resolved', resolution='以第一项为准。')
        self.assertEqual(self.prepare(self.review())['knowledgeState'], 'needs_evidence')

    def test_empty_or_unrelated_conflict_rejected(self):
        self.add_conflict()
        for key in ('claim_ids', 'evidence_ids'):
            original = self.request['conflicts'][0][key]
            self.request['conflicts'][0][key] = []
            with self.assertRaisesRegex(PreparationError, 'empty_conflict_scope'): self.prepare()
            self.request['conflicts'][0][key] = original
        self.request['relations'] = self.request['relations'][:1]
        with self.assertRaisesRegex(PreparationError, 'unrelated_conflict_scope'): self.prepare()

    def test_partial_reviews_stay_needs_review_not_missing_evidence(self):
        for kind in ('sources', 'relations', 'claims', 'documents'):
            review = self.review()
            review[kind] = []
            self.assertEqual(self.prepare(review)['knowledgeState'], 'needs_review', kind)

    def test_unreviewed_old_page_cannot_disappear_from_scope(self):
        review = self.review()
        review['documents'] = []
        result = self.prepare(review)
        self.assertEqual(result['knowledgeState'], 'needs_review')
        self.assertEqual(result['comparisonChecks'][0]['decision'], 'needs_review')
        review['documents'] = [{'ref': self.context['documents'][0]['locator'],
            'decision': 'relations_complete', 'reason': '缺少关系记录。'}]
        with self.assertRaisesRegex(PreparationError, 'document_relation_coverage'): self.prepare(review)

    def test_counterevidence_without_conflict_blocks(self):
        self.request['relations'].append(self.relation(self.request['evidence'][0], 'c1', 'contradicts'))
        self.assertIn('unresolved_counterevidence', self.prepare(self.review())['claimChecks'][0]['blockers'])

    def test_unrelated_claim_explicit_partition_needs_new_review(self):
        self.add_conflict()
        e = self.evidence('e3', 's1', 3, '复制后应核对摘要。')
        self.request['evidence'].append(e)
        self.request['claims'].append(self.claim('c3', '复制后核对摘要。'))
        self.request['relations'].append(self.relation(e, 'c3'))
        p = self.prepare(self.review())
        split = partition_knowledge(p, ['c3'], package_id='split', version=1, reason='仅交付摘要校验部分。')
        self.assertEqual(split['excludedClaimIds'], ['c1', 'c2'])
        q = prepare_knowledge(self.context, split['request'], wiki_root=self.project, source_root=self.inbox)
        self.assertEqual(q['knowledgeState'], 'needs_review')
        self.assertEqual(len(q['package']['evidence']), 2)

    def add_old(self):
        self.request['existingKnowledge'] = [{'claim_id': 'c1', 'target': '[[备份]]',
            'relation': 'supersedes', 'reason': '同规程新一手证据纠正旧摘要。'}]

    def old_review(self, decision='corrects_old'):
        review = self.review()
        review['documents'][0].update(decision='relations_complete', reason='已检查本页与全包主张，关系已列出。')
        review['comparisons'] = [{'ref': digest(self.request['existingKnowledge'][0]),
            'decision': decision, 'reason': '原规程明文停服，旧摘要无依据，保留原页等待人工修订。',
            'basisEvidenceIds': ['e1'], 'oldEvidence': {'locator': 'wiki/concepts/运维/备份.md',
                'start_line': 2, 'end_line': 2, 'excerpt': '本合成规程复制前无需停服。'}}]
        return review

    def test_new_evidence_can_correct_old_page_without_writing_it(self):
        self.add_old()
        before = self.inventory()
        result = self.prepare(self.old_review())
        self.assertEqual(result['knowledgeState'], 'reviewed_for_scope')
        self.assertEqual(before, self.inventory())

    def test_old_same_condition_unresolved_and_missing_review(self):
        self.add_old()
        partial = self.old_review()
        partial['comparisons'] = []
        self.assertEqual(self.prepare(partial)['knowledgeState'], 'needs_review')
        self.assertEqual(self.prepare(self.old_review('unresolved'))['knowledgeState'], 'needs_evidence')

    def test_version_difference_recorded_without_voting(self):
        self.add_old()
        review = self.old_review('version_change')
        review['comparisons'][0]['reason'] = '此合成观察假定旧摘要适用旧版本；测试状态不证明真实语义。'
        self.assertEqual(self.prepare(review)['knowledgeState'], 'reviewed_for_scope')

    def test_old_excerpt_forgery_or_unread_target_rejected(self):
        self.add_old()
        review = self.old_review()
        review['comparisons'][0]['oldEvidence']['excerpt'] = '伪造旧页。'
        with self.assertRaisesRegex(PreparationError, 'excerpt_mismatch'): self.prepare(review)
        self.request['existingKnowledge'][0]['target'] = '[[未读页]]'
        with self.assertRaisesRegex(PreparationError, 'existing_target_not_read'): self.prepare()

    def test_old_page_source_index_and_inventory_changes_stale(self):
        self.add_old()
        p = self.prepare(self.old_review())
        for path in (self.old, self.source, self.project / 'wiki/index.md'):
            old = path.read_bytes()
            path.write_bytes(old + '\n变更'.encode())
            self.assertEqual(verify_knowledge(self.context, p, wiki_root=self.project,
                source_root=self.inbox)['result'], 'stale')
            path.write_bytes(old)
        self.write('wiki/concepts/新增.md', '# 新增')
        self.assertEqual(self.prepare()['result'], 'stale')

    def test_changed_package_or_intent_review_stale(self):
        review = self.review()
        self.request['intent'] = '新的明确整理范围。'
        self.assertEqual(self.prepare(review)['result'], 'stale')

    def test_package_version_history_inherits_across_versions(self):
        first = self.prepare()
        self.request['version'] = 2
        second = self.prepare(previous=first)
        self.request['version'] = 1
        self.request['claims'][0]['text'] = '同版本伪装的新内容。'
        with self.assertRaisesRegex(PreparationError, 'package_version_conflict'):
            self.prepare(previous=second)

    def test_self_reported_authenticated_review_rejected(self):
        for value in ('host_authenticated', 'G3', 'pass'):
            review = self.review()
            review['assurance'] = value
            with self.assertRaisesRegex(PreparationError, 'review_assurance'): self.prepare(review)

    def test_explicit_claim_rejection_preserved(self):
        review = self.review()
        review['claims'][0].update(decision='rejected', reason='合成拒绝决定。')
        p = self.prepare(review)
        self.assertEqual(p['knowledgeState'], 'rejected')
        self.assertEqual(p['claimChecks'][0]['state'], 'rejected')

    def test_resolved_conflict_requires_scoped_basis_and_safe_claims(self):
        self.add_conflict()
        self.request['conflicts'][0].update(status='resolved', resolution='明文支持c1，c2不成立。')
        review = self.review()
        review['conflicts'] = [{'ref': 'f1', 'decision': 'resolved_for_scope',
            'safeClaimIds': ['c1'], 'basisEvidenceIds': ['e1'], 'reason': '摘录支持c1，反驳c2。'}]
        p = self.prepare(review)
        self.assertEqual(p['claimChecks'][0]['state'], 'reviewed_for_scope')
        self.assertNotEqual(p['claimChecks'][1]['state'], 'reviewed_for_scope')
        review['conflicts'][0]['safeClaimIds'] = ['unknown']
        with self.assertRaisesRegex(PreparationError, 'conflict_review_scope'): self.prepare(review)

    def test_malformed_review_is_not_reported_as_stale(self):
        with self.assertRaisesRegex(PreparationError, 'review_binding_shape'): self.prepare({})

    def test_byte_identical_sources_merge_even_with_different_origin_claims(self):
        path = self.inbox / 'copy.md'
        path.write_bytes(self.source.read_bytes())
        self.context_request['sources'].append(self.source_record('s2', path))
        self.context = self.inspect()
        e = self.evidence('e2', 's2', 2, '本合成规程复制前必须停服。')
        self.request['evidence'].append(e)
        obs = self.observation('s2', 'e2')
        obs['originId'] = 'different-claimed-origin'
        self.request['sourceObservations'].append(obs)
        self.assertEqual(self.prepare()['independence']['declaredGroups'], [['s1', 's2']])

    def test_review_unknown_duplicate_and_out_of_scope_refs(self):
        for mode in ('duplicate', 'outside', 'field'):
            review = self.review()
            if mode == 'duplicate': review['claims'].append(copy.deepcopy(review['claims'][0]))
            elif mode == 'outside': review['claims'][0]['ref'] = 'unknown'
            else: review['claims'][0]['pass'] = True
            with self.assertRaises(PreparationError): self.prepare(review)

    def test_rehashed_report_cannot_grant_new_result(self):
        p = self.prepare()
        p['knowledgeState'] = 'reviewed_for_scope'
        p['reportDigest'] = digest({k: v for k, v in p.items() if k != 'reportDigest'})
        with self.assertRaisesRegex(PreparationError, 'prepared_result_mismatch'):
            verify_knowledge(self.context, p, wiki_root=self.project, source_root=self.inbox)

    def test_same_upstream_and_unknown_never_count_as_independent(self):
        for sid in ('s2', 's3'):
            path = self.inbox / (sid + '.md')
            path.write_bytes(('# ' + sid + '\n转载共同原文。\n').encode())
            self.context_request['sources'].append(self.source_record(sid, path))
        self.context = self.inspect()
        for sid in ('s2', 's3'):
            e = self.evidence('e' + sid, sid, 2, '转载共同原文。')
            self.request['evidence'].append(e)
            obs = self.observation(sid, e['evidence_id'])
            obs.update(sourceType='repost', upstreamSourceIds=['s1'])
            self.request['sourceObservations'].append(obs)
        p = self.prepare()
        self.assertEqual(p['independence']['declaredGroups'], [['s1', 's2', 's3']])
        self.assertIsNone(p['independence']['independentCorroborationCount'])
        self.request['sourceObservations'][0]['originId'] = None
        self.assertIn('s1', self.prepare()['independence']['unknownSourceIds'])

    def test_source_cycle_and_origin_without_basis_rejected(self):
        self.request['sourceObservations'][0]['basisEvidenceIds'] = []
        with self.assertRaisesRegex(PreparationError, 'origin_without_basis'): self.prepare()
        self.request['sourceObservations'][0]['upstreamSourceIds'] = ['s1']
        with self.assertRaisesRegex(PreparationError, 'source_upstream_reference'): self.prepare()

    def test_bounded_counts_and_unknown_request_fields(self):
        self.request['claims'] *= 11
        with self.assertRaisesRegex(PreparationError, 'knowledge_count'): self.prepare()
        self.request['claims'] = self.request['claims'][:1]
        self.request['confirmed'] = True
        with self.assertRaisesRegex(PreparationError, 'knowledge_request_fields'): self.prepare()

    def run_cli(self, operation, *args):
        return subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m',
            'tools.wiki_runtime.evidence.knowledge_cli', operation,
            '--wiki-root', str(self.project), '--source-root', str(self.inbox),
            '--context', str(self.root / 'context.json'), *args], cwd=REPO,
            capture_output=True, text=True, encoding='utf-8')

    def save(self, name, value):
        p = self.root / name
        p.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return str(p)

    def test_actual_cli_missing_review_scoped_and_check(self):
        self.save('context.json', self.context)
        req = self.save('request.json', self.request)
        a = self.run_cli('prepare-knowledge', '--request', req)
        self.assertEqual(a.returncode, 2, a.stderr)
        self.assertEqual(json.loads(a.stdout)['knowledgeState'], 'needs_review')
        rev = self.save('review.json', self.review())
        b = self.run_cli('prepare-knowledge', '--request', req, '--review', rev)
        self.assertEqual(b.returncode, 0, b.stderr)
        prepared = self.save('prepared.json', json.loads(b.stdout))
        c = self.run_cli('check-knowledge', '--prepared', prepared)
        self.assertEqual(c.returncode, 0, c.stderr)
        self.assertEqual(json.loads(c.stdout), json.loads(b.stdout))

    def test_actual_cli_nested_malformed_and_duplicate_json_rejected(self):
        self.save('context.json', self.context)
        for value in (dict(self.request, evidence=[7]), dict(self.request, claims=[{'claim_id': []}])):
            p = self.run_cli('prepare-knowledge', '--request', self.save('bad.json', value))
            self.assertEqual(p.returncode, 3, p.stderr)
            self.assertEqual(json.loads(p.stdout)['result'], 'rejected')
            self.assertNotIn('Traceback', p.stderr)
        path = self.root / 'duplicate.json'
        path.write_text('{"schema":1,"schema":2}', encoding='utf-8')
        p = self.run_cli('prepare-knowledge', '--request', str(path))
        self.assertEqual(p.returncode, 3)
        self.assertEqual(json.loads(p.stdout)['result'], 'rejected')


if __name__ == '__main__':
    unittest.main()
