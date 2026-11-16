"""K4后连接修复的组合验收；临时文件、本机HTTP和明确合成语义观察。"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from tools.tests import test_knowledge_preparation_k4 as k4
from tools.tests import test_knowledge_preparation_k3 as k3
from tools.tests import test_learning_book_i5_handoff as i5
from tools.learning_book.baseline import Baseline
from tools.learning_book.contracts import DeliveryError, canonical, digest, read_json, sha256
from tools.learning_book.evidence_store import atomic
from tools.learning_book.preparation_provenance import save_provenance, load_provenance, verify_provenance
from tools.learning_book.preparation_continuation import active_preparation
from tools.learning_book.handoff import verify_handoff
from tools.wiki_runtime.host.supervisor import StandaloneHost, HostError
from tools.wiki_runtime.host.cli import _review_record


class LearningIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.c=k4.ConnectionTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.f,self.h,self.app=self.c.f,self.c.http,self.c.app

    def sources(self,activity):
        mapping=self.app._mapping(activity)
        origin=self.h.store.request(mapping['productionRequestId'])
        corpus,receipt=self.app._corpus(origin['semantic']['corpusRequestId'])
        baseline=Baseline.__new__(Baseline);baseline.store=self.h.store;baseline.production=self.app;baseline.scope=self.app.scope
        return baseline._sources(mapping,corpus,receipt)

    def refresh_after_wiki_change(self):
        self.f.k.write('wiki/index.md',(self.f.project/'wiki/index.md').read_text(encoding='utf-8')+'\n合法的新维护备注。\n')
        self.f.k.context=self.f.k.inspect();self.f.knowledge=self.f.k.prepare(self.f.k.review())
        self.f.brief_request['version']=2;self.f.refresh_brief()
        self.f.request['version']=2;self.f.recognition=self.f.make_recognition()
        for name,value in [('context',self.f.k.context),('knowledge',self.f.knowledge),('brief',self.f.brief),
                           ('request',self.f.request),('recognition',self.f.recognition),('review',self.f.review())]:
            self.f.save(self.f.root/(name+'.json'),value)

    def continuation_review(self,rr):
        return {'schema':'learning-preparation-continuation-review/1','id':'synthetic-revalidation-review',
            'requestDigest':rr['requestDigest'],'reviewedBy':'synthetic-reviewer','recordedAt':'2026-11-12',
            'decision':'reviewed_for_scope','reason':'合成控制流验证，不冒充真实语义审阅。','assurance':'operator_supplied'}

    def test_reuse_create_I4_sources_complete_and_no_reupload(self):
        self.c.publish();posts=self.h.fake.writes()
        reuse=self.app.publish_learning_inputs(self.c.package(),'alias')
        self.assertTrue(reuse['reusedCorpus']);self.assertEqual(self.h.fake.writes(),posts)
        created=self.app.create_activity('alias','alias-create','alias-activity',self.f.intent)
        self.assertEqual(created['status'],'succeeded',created)
        result=self.sources('alias-activity')
        self.assertEqual(result['status'],'complete',result)
        self.assertEqual(result['mapping']['preparation']['status'],'available')
        archive=load_provenance(self.h.store,result['mapping']['preparation']['activeRef'])
        self.assertEqual(archive['knowledge']['package']['claims'][0]['claim_id'],'c1')
        for row in self.c.package().manifest['inputArtifacts']:
            (self.h.store.request_dir('guarded-upload')/'inputs'/row['remotePath']).unlink()
        self.assertEqual(self.sources('alias-activity')['status'],'complete')
        self.assertEqual(self.h.fake.writes(),posts+1)

    def test_missing_or_tampered_provenance_remains_partial(self):
        self.c.create();result=self.sources('guarded-activity')
        path=self.h.store.root/result['mapping']['preparation']['activeRef']['path']
        path.write_bytes(b'{}')
        current=self.sources('guarded-activity')
        self.assertEqual(current['status'],'partial')
        self.assertTrue(any(x['kind']=='preparation' for x in current['issues']))

    def test_wiki_change_revalidation_same_activity_continues_without_recreate(self):
        created=self.c.create();original=copy.deepcopy(self.h.store.request('guarded-create'))
        self.refresh_after_wiki_change();payload={'title':'合成规程'}
        with self.assertRaises(DeliveryError):
            self.app.confirm_proposal('guarded-activity','before-revalidation',payload,created['revision'])
        before=self.h.fake.writes()
        pending=self.app.revalidate_preparation('guarded-activity','refresh-1',created['revision'],'知识索引正常演进')
        self.assertEqual(pending['status'],'needs_review')
        review=self.continuation_review(pending['reviewRequest'])
        accepted=self.app.revalidate_preparation('guarded-activity','refresh-1',created['revision'],'知识索引正常演进',review)
        self.assertEqual(accepted['status'],'succeeded')
        self.assertEqual(self.h.fake.writes(),before)
        self.c.operation_review('confirm-proposal',{'book_id':created['bookId'],
            'expected_revision':created['revision'],'proposal':payload})
        result=self.app.confirm_proposal('guarded-activity','continued-confirm',payload,created['revision'])
        self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(result['bookId'],created['bookId'])
        self.assertEqual(self.h.fake.writes('/api/books'),1)
        self.assertEqual(self.h.store.request('guarded-create'),original)
        saved=self.h.store.request('continued-confirm')['semantic']
        self.assertIn('preparationContinuationRef',saved)
        current=self.sources('guarded-activity')['mapping']['preparation']
        self.assertNotEqual(current['originRef'],current['activeRef'])
        self.assertEqual(len(current['continuations']),1)

    def test_bad_review_or_wrong_revision_cannot_accept_continuation(self):
        created=self.c.create();self.refresh_after_wiki_change()
        with self.assertRaises(DeliveryError):
            self.app.revalidate_preparation('guarded-activity','bad',created['revision']+10,'变更')
        p=self.app.revalidate_preparation('guarded-activity','bad',created['revision'],'变更')
        review=self.continuation_review(p['reviewRequest']);review['requestDigest']='0'*64
        with self.assertRaises(DeliveryError):
            self.app.revalidate_preparation('guarded-activity','bad',created['revision'],'变更',review)
        mapping=self.app._mapping('guarded-activity')
        self.assertEqual(active_preparation(self.h.store,mapping,self.h.store.request('guarded-create'))['records'],[])

    def test_scope_or_uploaded_header_change_requires_other_workflow(self):
        created=self.c.create();self.refresh_after_wiki_change()
        self.f.brief['pacing']['depth']='standard';self.f.manifest['depth']='standard';self.f.save_manifest()
        self.f.recognition=self.f.make_recognition()
        for name,value in [('brief',self.f.brief),('recognition',self.f.recognition),('review',self.f.review())]:
            self.f.save(self.f.root/(name+'.json'),value)
        with self.assertRaises(DeliveryError):
            self.app.revalidate_preparation('guarded-activity','scope',created['revision'],'扩大范围')

    def reseal_archive(self,a):
        k,m=a['knowledge'],a['mapping'];kr=k['reviewRequest'];ko=k['reviewObservation']
        kr['requestDigest']=digest({x:y for x,y in kr.items() if x!='requestDigest'})
        ko['requestDigest']=kr['requestDigest']
        k['reportDigest']=digest({x:y for x,y in k.items() if x!='reportDigest'})
        m['reviewRef']={'id':ko['id'],'digest':digest(ko)}
        pr=a['projectionReview'];pr['basisRefs']=[m['reviewRef']]
        rr={'schema':'learning-projection-review-request/1',
            'mappingDigest':digest({x:y for x,y in m.items() if x!='projectionReviewRef'}),
            'artifactRefs':pr['artifactRefs'],**{x:m[x] for x in ('briefRef','recognitionRef','packageRef','prepareRef')},
            'basisRefs':pr['basisRefs'],'purpose':'审实际上传全文、目标适切性、认可范围、新事实及判分依据；不等同实际生成课件I4。'}
        pr['requestDigest']=digest(rr);m['projectionReviewRef']={'id':pr['id'],'digest':digest(pr)}
        a['binding']['mappingDigest']=digest(m)

    def test_rehashed_archive_with_wrong_knowledge_package_is_rejected(self):
        a=copy.deepcopy(self.c.guard.checked(include_provenance=True)[3])
        a['knowledge']['reviewRequest']['packageRef']['package_id']='wrong-package'
        self.reseal_archive(a)
        with self.assertRaises(DeliveryError):verify_provenance(a)

    def test_rehashed_archive_with_wrong_projection_artifact_is_rejected(self):
        a=copy.deepcopy(self.c.guard.checked(include_provenance=True)[3])
        a['projectionReview']['artifactRefs'][0]['artifactId']='wrong-artifact'
        self.reseal_archive(a)
        with self.assertRaises(DeliveryError):verify_provenance(a)

    def test_rehashed_archive_cannot_invent_support_without_relation(self):
        from tools.wiki_runtime.evidence.package_protocol import package_ref
        a=copy.deepcopy(self.c.guard.checked(include_provenance=True)[3])
        k=a['knowledge'];k['package']['relations']=[];k['request']['relations']=[]
        k['reviewRequest']['scope']['relationDigests']=[];k['reviewObservation']['relations']=[]
        k['package']['content_digest']=digest({key:value for key,value in k['package'].items() if key!='content_digest'})
        ref=package_ref(k['package']);k['reviewRequest']['packageRef']=ref;a['mapping']['packageRef']=ref
        k['packageVersions']=[ref]
        self.reseal_archive(a)
        with self.assertRaises(DeliveryError):verify_provenance(a)

    def test_existing_conflict_cannot_be_relabelled_as_duplicate(self):
        f=self.f;f.k.add_old();f.knowledge=f.k.prepare(f.k.old_review())
        f.save(f.root/'knowledge.json',f.knowledge);f.save(f.root/'review.json',f.review())
        a=copy.deepcopy(self.c.guard.checked(include_provenance=True)[3])
        self.assertTrue(a['existingDocuments'])
        self.assertTrue(a['knowledge']['package']['existing_knowledge'])
        a['knowledge']['reviewObservation']['comparisons'][0]['decision']='exact_duplicate'
        self.reseal_archive(a)
        with self.assertRaises(DeliveryError):verify_provenance(a)


class PortablePreparationTests(unittest.TestCase):
    def setUp(self):
        self.c=k4.ConnectionTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.x=i5.HandoffTests();self.x.setUp();self.addCleanup(self.x.doCleanups)
        f=self.c.f;f.k.add_old();f.knowledge=f.k.prepare(f.k.old_review())
        f.save(f.root/'knowledge.json',f.knowledge);f.save(f.root/'review.json',f.review())
        binding,package,_,archive=self.c.guard.checked(include_provenance=True)
        x=self.x;ref=save_provenance(x.store,archive)
        x.store.prepare('guarded-inputs',{'operation':'publish-inputs','scope':x.config['scope'],'corpus':package.corpus},
            audit={'package':package.manifest})
        x.store.save_receipt('guarded-inputs','succeeded',corpus=package.corpus,corpusDigest=digest(package.corpus),
            coverage='complete',kbRef='account:kb:test',taskId='task',usableVersion='usable-v1')
        atomic(x.store.request_dir('guarded-inputs')/'locators.json',canonical(package.locators))
        for name,data in package.inputs.items():atomic(x.store.request_dir('guarded-inputs')/'inputs'/name,data)
        x.fake.inputs=dict(package.inputs)
        x.store.prepare('guarded-create',{'operation':'create','scope':x.config['scope'],'activityId':'guarded',
            'corpusRequestId':'guarded-inputs','knowledgePreparation':binding,'preparationProvenanceRef':ref},
            audit={'package':package.manifest})
        x.store.map_activity('guarded',x.config['scope'],'bk_1','guarded-create')
        x.store.save_receipt('guarded-create','succeeded',bookId='bk_1',activityId='guarded')

    def test_I4_I5_portable_package_can_resolve_brief_claims_and_evidence_offline(self):
        result=self.x.exporter.export_learning_results('guarded','with-preparation')
        path=self.x.artifact_path(result)
        self.assertEqual(verify_handoff(path)['verification'],'valid')
        h=read_json(path/'handoff.json');self.assertIn('preparationEvidence',h)
        entry=h['preparationEvidence']['refMap'][0]
        archive=read_json(path/entry['artifact'])
        self.assertEqual(archive['brief']['briefId'],'brief')
        self.assertTrue(archive['knowledge']['package']['evidence'])
        self.assertTrue(archive['knowledge']['package']['existing_knowledge'])
        self.assertIn('无需停服',archive['existingDocuments'][0]['text'])
        self.assertFalse(archive['sourceOriginalsVerified'])
        copied=self.x.root/'portable';shutil.copytree(path,copied)
        # 删除源准备附件后仍可离线核对交接内原字节；原文仍external。
        for item in h['preparationEvidence']['refMap']:
            (self.x.store.root/item['oldRef']).unlink()
        self.assertEqual(verify_handoff(copied)['verification'],'valid')
        (copied/entry['artifact']).write_text('{}',encoding='utf-8')
        with self.assertRaises(DeliveryError):verify_handoff(copied)


class CandidateAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.f=k3.PreviewTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.calls=[]
        self.host=StandaloneHost(self.f.project,self.f.root/'host-state',transport=self.transport)
        self.addCleanup(self.host.close)

    def transport(self,envelope,*,timeout):
        self.calls.append(copy.deepcopy(envelope))
        self.assertTrue(envelope['system'].startswith('你是独立内容审查者'))
        rr=envelope['input'];refs=[]
        for kind,key in [('original','originals'),('candidate','candidate_files')]:
            for path,text in rr[key].items():
                n=next(i+1 for i,s in enumerate(text.splitlines()) if s.strip())
                refs.append(f'{kind}:{path}#L{n}-L{n}')
        return dict(contract_version='1.0',**rr['bindings'],reviewer_id=envelope['reviewer_id'],
                    result='recommend_pass',findings=[],evidence_refs=refs)

    def adopt(self):
        f=self.f
        return self.host.adopt_knowledge_candidate('preview',f.k.context,f.knowledge,f.candidate,f.request,
            source_root=f.inbox,payload_root=f.payload)

    def test_adopt_inspect_review_consume_same_candidate_without_worker_or_apply(self):
        f=self.f
        # OS接受锁属于控制面；不把其首次建立当作正式知识写入。
        inventory=lambda:{p.relative_to(f.project).as_posix():sha256(p.read_bytes()) for p in f.project.rglob('*')
                          if p.is_file() and p.relative_to(f.project).parts[0]!='.wiki-runtime'}
        before=inventory();result=self.adopt()
        self.assertEqual(result['status'],'pending_review');self.assertEqual(self.calls,[])
        inspected=_review_record(self.host,'preview')
        self.assertTrue(inspected['diffs'])
        self.assertIn('knowledge_package_ref',inspected['context'])
        self.assertFalse(inspected['usableForTransfer'])
        reviewed=self.host.review_knowledge_candidate('preview')
        self.assertEqual(reviewed['status'],'reviewed_for_transfer',reviewed)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(reviewed['formalWriteAuthorized'])
        self.assertTrue(self.host.review_knowledge_candidate('preview')['replayed'])
        self.assertEqual(len(self.calls),1)
        inspected=_review_record(self.host,'preview')
        self.assertEqual(inspected['status'],'reviewed_for_transfer')
        self.assertEqual(inspected['opinion'],reviewed['opinion'])
        self.assertTrue(inspected['knowledgeEvidence']['prepared']['package']['claims'])
        self.assertTrue(inspected['usableForTransfer'])
        self.assertEqual(self.host.apply_pending('preview')['status'],'knowledge_admission_required')
        self.assertEqual(self.host.recover('preview')['status'],'knowledge_admission_required')
        with self.assertRaises(HostError):self.host.approve_pending('preview')
        self.assertEqual(before,inventory())

    def test_adopt_copy_is_immutable_to_original_payload_changes_and_detects_vault_stale(self):
        self.adopt();before=self.host.load_pending('preview')['bundle']['candidate']
        (self.f.payload/'wiki/index.md').write_text('changed external payload',encoding='utf-8')
        self.assertEqual(_review_record(self.host,'preview')['status'],'pending_review')
        self.assertEqual(self.host.load_pending('preview')['bundle']['candidate'],before)
        self.f.k.write('wiki/meta/added.md','# 合法新页\n')
        inspected=_review_record(self.host,'preview')
        self.assertEqual(inspected['currentValidation'],'stale_or_unavailable')
        self.assertFalse(inspected['usableForTransfer'])

    def test_missing_knowledge_review_or_changed_candidate_cannot_adopt(self):
        old=self.f.knowledge;self.f.knowledge=self.f.k.prepare()
        with self.assertRaises(HostError):self.adopt()
        self.f.knowledge=old;self.adopt()
        self.f.candidate=copy.deepcopy(self.f.candidate);self.f.candidate['changes'][0]['sha256']='0'*64
        with self.assertRaises(HostError):self.adopt()

    def make_managed_raw(self):
        from tools.wiki_runtime.capture import capture
        from tools.wiki_runtime.host.derived import _capture_outputs
        from tools.wiki_runtime.host.supervisor import update_raw_metadata
        from tools import raw_index
        f=self.f
        package,folder=capture(f.k.source,f.root/'capture','package',vault_root=f.project,
            source_id='managed-test')
        (f.project/f.raw_path).unlink()
        f.k.write('raw/index.md','# 素材\n'+raw_index.START+'\n'+raw_index.END+'\n')
        outputs=_capture_outputs(f.project,package,folder,f.raw_path)
        for path,data in outputs.items():
            target=f.project/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        f.raw=outputs[f.raw_path]
        extracted=folder/package['extracted']['path']
        f.k.source.write_bytes(extracted.read_bytes())
        f.k.context_request['sources'][0]=f.k.source_record('s1',f.k.source)
        f.k.context=f.k.inspect()
        f.k.request['evidence'][0]=f.k.evidence('e1','s1',2,'本合成规程复制前必须停服。')
        f.k.rebind_relations();f.knowledge=f.k.prepare(f.k.review())
        f.values[f.raw_path]=update_raw_metadata(f.raw,{'processing_status':'pending_review',
            'processed_into':'[[sources/规程来源]]'}).decode('utf-8')
        f.rebuild();f.request['rawBindings'][0]['bindingMode']='managed_extracted'
        return f.project/'raw/assets'/package['source_id']/package['source_revision']/package['extracted']['path']

    def test_standard_capture_thin_raw_preview_adopt_and_review(self):
        extracted=self.make_managed_raw()
        self.assertTrue(extracted.is_file())
        self.assertEqual(self.adopt()['status'],'pending_review')
        opinion=self.host.review_knowledge_candidate('preview')
        self.assertEqual(opinion['status'],'reviewed_for_transfer',opinion)
        self.assertIn(extracted.relative_to(self.f.project).as_posix(),self.calls[0]['input']['originals'])

    def test_managed_extraction_changed_cannot_be_used_as_verified_original(self):
        extracted=self.make_managed_raw();extracted.write_text('伪造抽取\n',encoding='utf-8')
        with self.assertRaises((HostError,ValueError)):self.adopt()

    def test_after_cutover_adopt_review_and_new_operation_are_not_legacy(self):
        from tools.wiki_runtime.runtime.migration import freeze_legacy_entries,assert_runtime_creation_allowed
        freeze_legacy_entries(self.f.project,self.host.state_dir)
        self.adopt()
        self.assertTrue(self.host.load_pending('preview')['runtime_managed'])
        self.assertEqual(self.host.review_knowledge_candidate('preview')['status'],'reviewed_for_transfer')
        assert_runtime_creation_allowed(self.f.project,self.host.state_dir,'new-operation')
        candidate=copy.deepcopy(self.f.candidate);candidate['operation_id']='new-operation'
        request=copy.deepcopy(self.f.request);request['coverageSpec']['candidate_id']='new-operation'
        result=self.host.adopt_knowledge_candidate('new-operation',self.f.k.context,self.f.knowledge,candidate,request,
            source_root=self.f.inbox,payload_root=self.f.payload)
        self.assertEqual(result['status'],'pending_review')


if __name__=='__main__': unittest.main()
