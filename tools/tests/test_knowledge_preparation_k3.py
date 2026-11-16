"""K3 临时文件、原生 prepare／候选 G0–G2 及真实 CLI。语义输入均标为合成。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.tests import test_knowledge_preparation_k2 as k2_fixture
from tools.wiki_runtime.contracts import bytes_digest, digest
from tools.wiki_runtime.evidence.preparation import PreparationError, draft_learning_brief
from tools.wiki_runtime.evidence.projection import build_learning_projection, check_release_request_binding
from tools.wiki_runtime.evidence.preview import preview_wiki_changes

REPO = k2_fixture.REPO


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.k = k2_fixture.KnowledgeTests()
        self.k.setUp()
        self.addCleanup(self.k.doCleanups)
        self.root, self.project, self.inbox = self.k.root, self.k.project, self.k.inbox
        self.knowledge = self.k.prepare(self.k.review())
        self.folder = self.root / 'projection'
        self.folder.mkdir()
        self.recognition_root = self.root / 'recognition'
        self.recognition_root.mkdir()
        self.statement = '合成用户要求：学习本规程的停服要求，二十分钟，范围仅本规程，不学习分布式。\n'
        (self.recognition_root / 'request.txt').write_bytes(self.statement.encode())
        self.brief_request = {'briefId': 'brief', 'version': 1, 'userIntent': self.statement,
            'goals': [{'goalId': 'g-stop', 'outcome': '能说明本规程停服要求。', 'checkMethod': '列出操作顺序。'}],
            'included': ['本规程停服要求'], 'excluded': ['分布式'],
            'pacing': {'sessionMinutes': 20, 'totalMinutes': 20, 'depth': 'brief'}, 'prerequisites': []}
        self.refresh_brief()
        self.intent = '学习本规程停服要求。'
        (self.folder / 'source.md').write_bytes(self.k.source.read_bytes())
        (self.folder / 'lesson.md').write_bytes(self.k.source.read_bytes())
        source_hash = bytes_digest(self.k.source.read_bytes())
        self.manifest = {'schemaVersion': 1, 'packageId': 'learning', 'corpusId': 'corpus',
            'corpusVersionId': 'v1', 'preparationDecision': 'learn', 'learningGoal': self.intent,
            'language': 'zh', 'depth': 'brief', 'sources': [{'sourceId': 'upload', 'sourceVersionId': 'v1',
                'sha256': source_hash, 'path': 'source.md', 'metadata': {'title': '合成规程'}}],
            'inputArtifacts': [{'inputArtifactId': 'lesson', 'sourceId': 'upload', 'sourceVersionId': 'v1',
                'sha256': source_hash, 'path': 'lesson.md', 'mediaType': 'text/markdown',
                'extraction': {'method': 'verbatim', 'version': '1'},
                'coverage': {'status': 'complete', 'truncated': False}}]}
        self.save_manifest()
        self.request = {'schema': 'learning-projection-request/1', 'mapId': 'mapping', 'version': 1,
            'intent': self.intent, 'sourceBindings': [{'mode': 'direct_source', 'sourceId': 'upload',
                'sourceVersionId': 'v1', 'byteDigest': source_hash, 'knowledgeSourceRef': {
                    'source_id': 's1', 'version': 'v1', 'content_digest': source_hash}}],
            'coverage': [{'goalId': 'g-stop', 'claimIds': ['c1'], 'evidenceIds': ['e1'],
                'artifactId': 'lesson', 'disposition': 'required', 'reason': '合成目标覆盖。'}],
            'excludedClaims': []}
        self.recognition = self.make_recognition()

    def refresh_brief(self):
        self.brief = draft_learning_brief(self.k.context, self.brief_request,
            wiki_root=self.project, source_root=self.inbox)['brief']

    def make_recognition(self):
        return {'id': 'synthetic-recognition', 'briefRef': {'briefId': self.brief['briefId'],
            'version': self.brief['version'], 'digest': digest(self.brief)}, 'submittedBy': 'synthetic-operator',
            'attributedAuthor': 'synthetic', 'recordedAt': '2026-11-11', 'statement': self.statement,
            'defaults': [], 'assurance': 'operator_supplied', 'evidenceRef': {'locator': 'request.txt',
                'byteDigest': bytes_digest(self.statement.encode())}, 'scope': {
                'goalIds': [g['goalId'] for g in self.brief['goals']], **{k: self.brief[k]
                    for k in ('included', 'excluded', 'pacing')}}, 'acceptedIntent': self.intent}

    def save(self, path, value):
        path = Path(path)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        return str(path)

    def save_manifest(self):
        self.save(self.folder / 'prepare.json', self.manifest)

    def build(self, *, recognition=True, review=None, previous=None):
        return build_learning_projection(self.k.context, self.knowledge, self.brief, self.request,
            wiki_root=self.project, source_root=self.inbox, projection_root=self.folder,
            recognition_root=self.recognition_root,
            recognition=self.recognition if recognition else None, review=review, previous=previous)

    def review(self):
        pending = self.build()
        rr = pending['reviewRequest']
        return {'schema': 'learning-projection-review/1', 'id': 'synthetic-projection-review',
            'requestDigest': rr['requestDigest'], 'reviewedBy': 'synthetic-operator',
            'recordedAt': '2026-11-11', 'decision': 'reviewed_for_scope',
            'reason': '合成流程输入，不是实际语义评测或用户认可认证。',
            'basisRefs': rr['basisRefs'], 'artifactRefs': rr['artifactRefs'], 'assurance': 'operator_supplied'}

    def test_missing_recognition_stops_before_projection(self):
        result = self.build(recognition=False)
        self.assertEqual(result['projectionState'], 'needs_clarification')
        self.assertIsNone(result['mapping'])
        self.assertNotIn('prepare', result)

    def test_direct_projection_requires_separate_actual_artifact_review(self):
        pending = self.build()
        self.assertEqual(pending['projectionState'], 'needs_review')
        self.assertIsNone(pending['mapping'])
        before = self.k.inventory()
        result = self.build(review=self.review())
        self.assertEqual(result['projectionState'], 'reviewed_for_scope')
        self.assertIn('projectionReviewRef', result['mapping'])
        self.assertFalse(result['coursePublishAuthorized'])
        self.assertEqual(before, self.k.inventory())

    def test_actual_intent_and_manifest_binding(self):
        result = self.build(review=self.review())
        md = result['prepareRef']['normalizedManifestDigest']
        self.assertTrue(check_release_request_binding(result, self.intent, md)['bindingMatched'])
        self.assertEqual(check_release_request_binding(result, '换成其他主题', md)['result'], 'stale')
        self.assertFalse(check_release_request_binding(result, self.intent, '0'*64)['bindingMatched'])

    def test_wrong_subject_scope_or_intent_need_clarification(self):
        for key in ('attributedAuthor', 'acceptedIntent', 'scope'):
            old = self.recognition[key]
            self.recognition[key] = 'different' if key != 'scope' else {}
            self.assertEqual(self.build()['projectionState'], 'needs_clarification')
            self.recognition[key] = old

    def test_recognition_version_or_actual_evidence_stales(self):
        old = self.recognition['briefRef']['digest']
        self.recognition['briefRef']['digest'] = '0'*64
        self.assertEqual(self.build()['projectionState'], 'stale')
        self.recognition['briefRef']['digest'] = old
        (self.recognition_root / 'request.txt').write_text('改了要求', encoding='utf-8')
        self.assertEqual(self.build()['projectionState'], 'stale')

    def test_statement_must_match_actual_evidence(self):
        self.recognition['statement'] = '伪造用户同意'
        with self.assertRaisesRegex(PreparationError, 'recognition_statement_binding'): self.build()

    def test_forged_authentication_and_embedded_confirmed_rejected(self):
        self.recognition['assurance'] = 'host_authenticated'
        with self.assertRaisesRegex(PreparationError, 'recognition_assurance'): self.build()
        self.recognition['assurance'] = 'operator_supplied'
        self.brief['confirmed'] = True
        with self.assertRaisesRegex(PreparationError, 'brief_fields'): self.build()

    def test_unknown_background_or_mastery_not_accepted(self):
        self.brief['backgroundRefs'] = [{'id': 'not-read', 'digest': '0'*64}]
        with self.assertRaisesRegex(PreparationError, 'background_binding'): self.build()

    def test_missing_pacing_or_pending_prerequisite_needs_clarification(self):
        self.brief['pacing']['totalMinutes'] = None
        self.assertEqual(self.build()['projectionState'], 'needs_clarification')

    def test_partial_knowledge_or_no_semantic_review_blocks(self):
        self.knowledge = self.k.prepare()
        self.assertEqual(self.build()['projectionState'], 'needs_review')

    def test_target_and_artifact_coverage_required(self):
        self.request['coverage'] = []
        with self.assertRaisesRegex(PreparationError, 'coverage_rows'): self.build()

    def test_unreviewed_or_invented_claim_rejected(self):
        self.request['coverage'][0]['claimIds'] = ['invented']
        with self.assertRaisesRegex(PreparationError, 'coverage_reference'): self.build()

    def test_direct_original_bytes_and_evidence_source_binding(self):
        self.request['sourceBindings'][0]['knowledgeSourceRef']['content_digest'] = '0'*64
        with self.assertRaisesRegex(PreparationError, 'direct_source_binding'): self.build()

    def test_duplicate_source_bindings_rejected(self):
        self.request['sourceBindings'] *= 2
        with self.assertRaisesRegex(PreparationError, 'binding_coverage'): self.build()

    def test_authored_projection_supported(self):
        data = '# 外部编写讲义\n本合成规程复制前停服。\n'.encode()
        (self.folder / 'source.md').write_bytes(data)
        (self.folder / 'lesson.md').write_bytes(data)
        h = bytes_digest(data)
        self.manifest['sources'][0]['sha256'] = h
        self.manifest['inputArtifacts'][0]['sha256'] = h
        self.save_manifest()
        self.request['sourceBindings'] = [{'mode': 'authored_projection', 'sourceId': 'upload',
            'sourceVersionId': 'v1', 'byteDigest': h}]
        result = self.build(review=self.review())
        self.assertEqual(result['projectionState'], 'reviewed_for_scope')
        self.assertNotIn('knowledgeSourceRef', result['mapping']['sourceBindings'][0])

    def test_upload_source_subset_does_not_require_all_knowledge_sources(self):
        other = self.inbox / 'other.md'
        other.write_text('另一份未选资料。\n', encoding='utf-8')
        self.k.context_request['sources'].append(self.k.source_record('s2', other))
        self.k.context = self.k.inspect()
        obs = self.k.observation('s2', 'e1'); obs['originId'] = None
        self.k.request['sourceObservations'].append(obs)
        self.knowledge = self.k.prepare(self.k.review())
        self.refresh_brief(); self.recognition = self.make_recognition()
        self.assertEqual(len(self.build(review=self.review())['mapping']['sourceBindings']), 1)

    def test_artifact_change_after_review_is_stale_even_if_manifest_rehashed(self):
        review = self.review()
        data = '# 修改的上传正文\n复制前停服。\n'.encode()
        (self.folder / 'lesson.md').write_bytes(data)
        self.manifest['inputArtifacts'][0]['sha256'] = bytes_digest(data)
        self.save_manifest()
        self.assertEqual(self.build(review=review)['projectionState'], 'stale')

    def test_projection_review_rejects_new_fact_and_out_of_scope(self):
        for decision in ('needs_evidence', 'needs_clarification', 'rejected'):
            review = self.review(); review['decision'] = decision
            self.assertEqual(self.build(review=review)['projectionState'], decision)

    def test_actual_artifact_review_scope_cannot_be_omitted(self):
        review = self.review(); review['artifactRefs'] = []
        with self.assertRaisesRegex(PreparationError, 'projection_review_scope'): self.build(review=review)

    def test_prepare_unknown_field_and_original_path_escape_rejected(self):
        self.manifest['learningBrief'] = {'confirmed': True}; self.save_manifest()
        with self.assertRaisesRegex(PreparationError, 'prepare_fields'): self.build()
        del self.manifest['learningBrief']
        self.manifest['sources'][0]['path'] = '../inbox/source.md'; self.save_manifest()
        with self.assertRaises(ValueError): self.build()

    def test_unread_old_page_or_source_change_stales_projection(self):
        self.k.old.write_text('旧页变了。', encoding='utf-8')
        self.assertEqual(self.build()['projectionState'], 'stale')

    def test_map_versions_preserved_in_explicit_previous_chain(self):
        review=self.review();first=self.build(review=review)
        self.assertEqual(first['mapping'],self.build(review=review,previous=first)['mapping'])
        self.request['version']=2;self.request['coverage'][0]['reason']='新的范围说明。'
        second=self.build(review=self.review(),previous=first)
        self.request['version']=1
        with self.assertRaisesRegex(PreparationError,'projection_map_version_conflict'):
            self.build(review=self.review(),previous=second)

    def test_projection_is_normalized_from_fixed_snapshot(self):
        from unittest.mock import patch
        from tools.learning_book.contracts import validate_package as native
        calls=[]
        def checked(path,root):
            self.assertNotEqual(Path(root),self.folder)
            self.assertTrue(Path(root).name.startswith('knowledge-projection-'))
            calls.append(str(root));return native(path,root)
        with patch('tools.wiki_runtime.evidence.projection.validate_package',side_effect=checked):
            self.build()
        self.assertTrue(calls)
        self.assertTrue(all(not Path(p).exists() for p in calls))

    def test_previous_cannot_drop_own_map_or_source_history(self):
        review=self.review();first=self.build(review=review)
        for field,code in (('mapVersions','previous_map_history_binding'),
                           ('sourceVersions','previous_source_history_binding')):
            old=copy.deepcopy(first);old[field]=[]
            old['projectionDigest']=digest({k:v for k,v in old.items() if k!='projectionDigest'})
            with self.assertRaisesRegex(PreparationError,code):
                self.build(review=review,previous=old)

    def test_uploaded_source_same_version_cannot_change_with_previous(self):
        first=self.build(review=self.review())
        data='# 新编写讲义\n本合成规程复制前停服。\n'.encode();h=bytes_digest(data)
        for name in ('source.md','lesson.md'):(self.folder/name).write_bytes(data)
        self.manifest['sources'][0]['sha256']=h
        self.manifest['inputArtifacts'][0]['sha256']=h;self.save_manifest()
        self.request['version']=2
        self.request['sourceBindings']=[{'mode':'authored_projection','sourceId':'upload',
            'sourceVersionId':'v1','byteDigest':h}]
        with self.assertRaisesRegex(PreparationError,'projection_source_version_conflict'):
            self.build(review=self.review(),previous=first)
        self.manifest['sources'][0]['sourceVersionId']='v2'
        self.manifest['inputArtifacts'][0]['sourceVersionId']='v2';self.save_manifest()
        self.request['sourceBindings'][0]['sourceVersionId']='v2'
        self.assertEqual(self.build(review=self.review(),previous=first)['projectionState'],'reviewed_for_scope')

    def run_cli(self, *extra):
        return subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m',
            'tools.wiki_runtime.evidence.projection_cli', 'build-learning-projection',
            '--wiki-root', str(self.project), '--source-root', str(self.inbox),
            '--context', self.save(self.root/'context.json', self.k.context),
            '--knowledge', self.save(self.root/'knowledge.json', self.knowledge),
            '--request', self.save(self.root/'request.json', self.request),
            '--brief', self.save(self.root/'brief.json', self.brief), '--projection-root', str(self.folder),
            '--recognition-root', str(self.recognition_root), *extra], cwd=REPO,
            capture_output=True, text=True, encoding='utf-8')

    def test_actual_projection_cli_missing_and_scoped(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(json.loads(r.stdout)['projectionState'], 'needs_clarification')
        r = self.run_cli('--recognition', self.save(self.root/'recognition.json', self.recognition),
            '--review', self.save(self.root/'review.json', self.review()))
        self.assertEqual(r.returncode, 0, r.stderr+r.stdout)
        self.assertFalse(json.loads(r.stdout)['coursePublishAuthorized'])


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.k = k2_fixture.KnowledgeTests(); self.k.setUp(); self.addCleanup(self.k.doCleanups)
        self.root, self.project, self.inbox = self.k.root, self.k.project, self.k.inbox
        self.payload = self.root/'payload'; self.payload.mkdir()
        self.k.write('AGENTS.md', (REPO/'AGENTS.md').read_text(encoding='utf-8'))
        self.k.write('tools/wiki_runtime/contracts/rules.json',
                     (REPO/'tools/wiki_runtime/contracts/rules.json').read_text(encoding='utf-8'))
        self.raw_path = 'raw/unprocessed/规程.md'
        self.raw = b'---\nprocessing_status: unprocessed\n---\n' + self.k.source.read_bytes()
        path = self.project/self.raw_path; path.parent.mkdir(parents=True); path.write_bytes(self.raw)
        self.k.write('raw/index.md', '# 素材\n- 未处理：1\n- 待确认：0\n- 已处理：0\n| 素材 | 状态 |\n| [[raw/unprocessed/规程]] | unprocessed |\n')
        self.k.write('wiki/log.md', '# 日志\n')
        self.k.write('wiki/meta/overview.md', '# 总览\n')
        # K2 基线中的旧页在此只是待比较背景；使用合成审校输入验证程序控制。
        self.k.context = self.k.inspect()
        self.knowledge = self.k.prepare(self.k.review())
        prose = '本页记录虚构规程的停服要求，适用范围仅本合成规程，不表示现实环境通用事实。' * 4
        source = '---\ntype: source\ntitle: 规程来源\nraw_note: "[[raw/unprocessed/规程]]"\nupdated: 2026-11-11\nrelated_concepts:\n  - "[[备份]]"\n---\n# 规程来源\n'+prose+'\n本合成规程复制前停服。见 [[备份]]。\n'
        old = '---\ntype: concept\ntitle: 备份\nupdated: 2026-11-11\nsupports:\n  - "[[sources/规程来源]]"\n---\n# 备份\n'+prose+'\n本次停服要求见 [[sources/规程来源]]；旧规程摘要保留待修订。\n'
        self.values = {'wiki/sources/规程来源.md': source, 'wiki/concepts/运维/备份.md': old,
            'wiki/index.md': '# 索引\n[[备份]]\n[[sources/规程来源]]\n[[meta/overview]]\n',
            'wiki/log.md': '# 日志\n## [2026-11-11] ingest | 规程来源\n[[sources/规程来源]]\n',
            'wiki/meta/overview.md': '# 总览\n虚构规程停服要求见 [[sources/规程来源]]。\n',
            'raw/index.md': '# 素材\n- 未处理：0\n- 待确认：1\n- 已处理：0\n| 素材 | 状态 |\n| [[raw/unprocessed/规程]] | pending_review | [[sources/规程来源]] |\n',
            self.raw_path: '---\nprocessing_status: pending_review\nprocessed_into: "[[sources/规程来源]]"\n---\n'+self.k.source.read_bytes().decode()}
        self.rebuild()

    def rebuild(self):
        changes, planned, coverage = [], [], []
        for i,(path,text) in enumerate(self.values.items()):
            data=text.encode(); target=self.payload/path; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data); before=self.project/path
            changes.append({'action':'write','path':path,'payload_path':path,'sha256':bytes_digest(data),
                'precondition':{'kind':'hash','sha256':bytes_digest(before.read_bytes())} if before.exists() else {'kind':'absent'}})
            cid='c1' if path.startswith(('wiki/sources/','wiki/concepts/')) else None
            planned.append({'change_id':str(i),'candidate_path':path,'action':'write','source':None,'claim_id':cid})
            coverage.append({'change_id':str(i),'candidate_path':path,'claim_id':cid,
                'evidence_disposition':'supported' if cid else 'mechanical','teaching_disposition':'non_teaching',
                'objective_ref':None,'reason':'合成预览；无学习门禁，不是正式授权。'})
        self.candidate={'contract_version':'1.0','operation_id':'preview','changes':changes}
        self.request={'schema':'wiki-preview-request/1','intent':'合成知识整理候选，不要求学习。',
            'coverageSpec':{'candidate_id':'preview','candidate_changes':planned,'dispositions':coverage},
            'rawBindings':[{'sourceId':'s1','rawLocator':self.raw_path,'byteDigest':bytes_digest(self.raw),'bindingMode':'body'}]}

    def preview(self):
        return preview_wiki_changes(self.k.context,self.knowledge,self.candidate,self.request,
            wiki_root=self.project,source_root=self.inbox,payload_root=self.payload)

    def test_real_ingest_preview_without_learning_and_no_formal_write(self):
        before=self.k.inventory();result=self.preview()
        self.assertEqual(result['previewState'],'ready_for_semantic_review',result.get('deterministicReports'))
        self.assertTrue(result['previewOnly']);self.assertFalse(result['formalWriteAuthorized'])
        self.assertFalse(result['readinessIssued']);self.assertEqual(before,self.k.inventory())
        self.assertEqual([r['gate'] for r in result['deterministicReports']],['G0','G1','G2'])

    def test_missing_backlink_reuses_real_G2_failure(self):
        self.values['wiki/concepts/运维/备份.md']=self.values['wiki/concepts/运维/备份.md'].replace('[[sources/规程来源]]','停服规程')
        self.rebuild();result=self.preview()
        self.assertEqual(result['previewState'],'needs_evidence')
        self.assertTrue(any(f['rule_id']=='REL-001' for r in result['deterministicReports'] for f in r['findings']))

    def test_missing_index_log_overview_or_raw_state_fails(self):
        del self.values['wiki/meta/overview.md'];self.rebuild()
        self.assertEqual(self.preview()['previewState'],'needs_evidence')

    def test_raw_body_change_reuses_real_G1(self):
        self.values[self.raw_path]+='伪造原文\n';self.rebuild()
        result=self.preview()
        self.assertEqual(result['previewState'],'needs_evidence')
        self.assertTrue(any(r['gate']=='G1' and r['result']=='fail' for r in result['deterministicReports']))

    def test_missing_capture_cannot_directly_become_ingest(self):
        (self.project/self.raw_path).unlink();self.rebuild()
        result=self.preview()
        self.assertEqual(result['nextAction'],'capture_and_register_original_before_ingest')
        self.assertIn('raw_capture_required',[f['code'] for f in result['findings']])

    def test_payload_changed_after_declared_hash_rejected(self):
        (self.payload/'wiki/index.md').write_text('不同内容',encoding='utf-8')
        with self.assertRaises(ValueError):self.preview()

    def test_learning_credentials_and_unknown_claim_rejected(self):
        self.request['coverageSpec']['dispositions'][0].update(teaching_disposition='required_objective',objective_ref='fake')
        with self.assertRaisesRegex(PreparationError,'preview_no_L2_credentials'):self.preview()

    def test_unbounded_baseline_rejected_before_full_scan(self):
        extra=self.project/'references';extra.mkdir()
        for i in range(513):(extra/str(i)).write_text('',encoding='utf-8')
        with self.assertRaisesRegex(PreparationError,'preview_baseline_entry_limit'):self.preview()

    def test_overlapping_roots_rejected(self):
        with self.assertRaisesRegex(PreparationError,'preview_root_overlap'):
            preview_wiki_changes(self.k.context,self.knowledge,self.candidate,self.request,
                wiki_root=self.project,source_root=self.inbox,payload_root=self.project)

    def test_unmodified_binary_attachment_is_compatible(self):
        asset=self.project/'raw/assets/example.png';asset.parent.mkdir(parents=True)
        asset.write_bytes(b'\x89PNG\x00\xff\xfe\x01')
        self.assertEqual(self.preview()['previewState'],'ready_for_semantic_review')

    def test_invalid_raw_locator_rejected_before_capture_suggestion(self):
        self.request['rawBindings'][0]['rawLocator']='raw/unprocessed/../../outside.md'
        with self.assertRaises(ValueError):self.preview()

    def test_actual_preview_cli(self):
        def save(name,obj):
            p=self.root/name;p.write_text(json.dumps(obj,ensure_ascii=False),encoding='utf-8');return str(p)
        r=subprocess.run([sys.executable,'-X','utf8','-B','-m','tools.wiki_runtime.evidence.projection_cli',
            'preview-wiki-changes','--wiki-root',str(self.project),'--source-root',str(self.inbox),
            '--payload-root',str(self.payload),'--context',save('context.json',self.k.context),
            '--knowledge',save('knowledge.json',self.knowledge),'--candidate',save('candidate.json',self.candidate),
            '--request',save('request.json',self.request)],cwd=REPO,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(r.returncode,0,r.stderr+r.stdout)
        self.assertFalse(json.loads(r.stdout)['formalWriteAuthorized'])


if __name__ == '__main__':
    unittest.main()
