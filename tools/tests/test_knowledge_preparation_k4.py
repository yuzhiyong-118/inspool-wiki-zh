"""K4 接线回归：私有临时库及本机 HTTP 替身；不访问真实服务/模型。"""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tools.tests import test_knowledge_preparation_k3 as k3
from tools.tests import test_learning_book_i3 as i3
from tools.learning_book.contracts import DeliveryError, Package, canonical, digest
from tools.learning_book.knowledge_preparation import PreparationGuard
from tools.learning_book.production import Production
from tools.wiki_runtime.evidence.content_view import ContentView, inspect_content_baseline
from tools.wiki_runtime.evidence.preview import preview_wiki_changes


class ContentTests(unittest.TestCase):
    def setUp(self):
        self.f = k3.PreviewTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)

    def preview(self):
        f = self.f
        return preview_wiki_changes(f.k.context, f.knowledge, f.candidate, f.request,
            wiki_root=f.project, source_root=f.inbox, payload_root=f.payload,
            baseline_scope='knowledge_content')

    def test_content_scope_runs_real_gates_ignoring_only_declared_noncontent(self):
        f = self.f
        extra = f.project/'references'; extra.mkdir()
        for n in range(513): (extra/str(n)).write_text('outside content', encoding='utf-8')
        result = self.preview()
        self.assertEqual(result['previewState'], 'ready_for_semantic_review')
        self.assertEqual([r['result'] for r in result['deterministicReports']], ['pass']*3)
        self.assertEqual(result['contentScope']['recursiveRoots'], ['wiki', 'raw'])
        self.assertFalse(result['formalWriteAuthorized'])
        self.assertTrue(all(not p['path'].startswith('references/') for p in result['snapshot']['files']))

    def test_actual_content_changes_and_new_entries_invalidate_view(self):
        f = self.f; view = ContentView(f.project, f.candidate, f.payload)
        list(view.iter_paths())
        f.k.write('wiki/meta/new.md', '# 新增\n')
        with self.assertRaises(ValueError): view.verify_dependencies()

    def test_entire_raw_group_not_cropped(self):
        f = self.f
        f.raw_path = 'raw/unprocessed/group/a.md'
        before = f.project/'raw/unprocessed/规程.md'
        target = f.project/f.raw_path; target.parent.mkdir(); before.rename(target)
        (target.parent/'b.md').write_bytes(f.raw)
        f.values[f.raw_path] = f.values.pop('raw/unprocessed/规程.md')
        f.rebuild()
        result = self.preview()
        self.assertEqual(result['previewState'], 'needs_evidence')
        self.assertTrue(any(x['rule_id']=='STATE-001' for r in result['deterministicReports'] for x in r['findings']))

    def test_binary_assets_and_hidden_files_included(self):
        f = self.f; f.k.write('wiki/.private-note.md', '# 私有也在范围内\n')
        path=f.project/'raw/assets/img.png';path.parent.mkdir();path.write_bytes(b'\x89PNG\xff')
        report=inspect_content_baseline(f.project)
        self.assertIn('wiki/.private-note.md', report['files'])
        self.assertIn('raw/assets/img.png', report['files'])
        self.assertFalse(report['formalWriteAuthorized'])

    def test_report_scope_cannot_change_later_scans(self):
        first=inspect_content_baseline(self.f.project)
        first['scope']['recursiveRoots'].clear();first['scope']['files'].clear()
        second=inspect_content_baseline(self.f.project)
        self.assertIn(self.f.raw_path,second['files'])
        self.assertIn('AGENTS.md',second['files'])


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.f=k3.ProjectionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        self.descriptor=f.root/'connection.json'
        for name,value in [('context',f.k.context),('knowledge',f.knowledge),('brief',f.brief),
                           ('request',f.request),('recognition',f.recognition),('review',f.review())]:
            f.save(f.root/(name+'.json'), value)
        self.config={'schema':'knowledge-preparation-connection/1',
            'wikiRoot':str(f.project),'sourceRoot':str(f.inbox),'projectionRoot':str(f.folder),
            'recognitionRoot':str(f.recognition_root),**{k:k+'.json' for k in
                ('context','knowledge','brief','request','recognition','review')},
            'previous':None,'prepare':'prepare.json','operationReview':None}
        self.save_config()
        self.guard=PreparationGuard(self.descriptor)
        self.http=i3.DeliveryTests();self.http.setUp();self.addCleanup(self.http.doCleanups)
        h=self.http
        self.app=Production(h.store,h.backend,h.budget,preparation_guard=self.guard)

    def save_config(self):
        self.f.save(self.descriptor,self.config)

    def package(self): return self.guard.checked()[1]

    def publish(self):
        result=self.app.publish_learning_inputs(self.package(),'guarded-upload')
        self.assertEqual(result['status'],'succeeded',result)
        return result

    def create(self):
        self.publish()
        result=self.app.create_activity('guarded-upload','guarded-create','guarded-activity',self.f.intent)
        self.assertEqual(result['status'],'succeeded',result)
        return result

    def operation_review(self, operation, payload):
        rr=self.guard.review_request(operation,'guarded-activity',self.http.app.scope,payload)
        review={'schema':'learning-production-review/1','id':'synthetic-step-review',
            'requestDigest':rr['requestDigest'],'reviewedBy':'synthetic-reviewer','recordedAt':'2026-11-12',
            'decision':'reviewed_for_scope','reason':'仅控制链合成测试，非实际语义审校。','assurance':'operator_supplied'}
        self.f.save(self.f.root/'step-review.json',review)
        self.config['operationReview']='step-review.json';self.save_config()
        return review

    def test_guarded_actual_http_upload_create_persist_binding(self):
        self.create()
        for rid in ('guarded-upload','guarded-create'):
            saved=self.http.store.request(rid)
            self.assertIn('knowledgePreparation',saved['semantic'])
            self.assertEqual(saved['digest'],digest(saved['semantic']))
        self.assertEqual(self.http.fake.writes('/api/books'),1)
        self.assertEqual(self.http.app.inspect_receipt('guarded-create')['knowledgePreparationStatus'],
                         'integrated_operator_supplied')

    def test_actual_intent_mismatch_no_book_post(self):
        self.publish()
        with self.assertRaises(DeliveryError):
            self.app.create_activity('guarded-upload','wrong','wrong-activity','新主题')
        self.assertEqual(self.http.fake.writes('/api/books'),0)

    def test_forged_python_package_inputs_blocked_before_any_post(self):
        p=self.package();forged=Package(p.manifest,p.corpus,{k:b'forged' for k in p.inputs},p.locators,p.root)
        with self.assertRaises(DeliveryError): self.app.publish_learning_inputs(forged,'forged')
        self.assertEqual(self.http.fake.writes(),0)

    def test_actual_upload_body_not_manifest_claim_is_checked(self):
        original=self.app._dispatch
        def tamper(rid,stage,path,body,content_type='application/json',**kw):
            if stage=='kb-upload': body+=b'forged'
            return original(rid,stage,path,body,content_type,**kw)
        self.app._dispatch=tamper
        result=self.app.publish_learning_inputs(self.package(),'forged-body')
        self.assertEqual(result['status'],'uncertain') # KB 已创建，原副作用不能抹掉。
        self.assertFalse(any(p.endswith('/upload') for m,p,*_ in self.http.fake.requests if m=='POST'))

    def test_dependency_change_at_last_dispatch_blocks_send(self):
        original=self.app._dispatch
        def change(rid,stage,*args,**kw):
            if stage=='kb-create': self.f.k.source.write_text('changed',encoding='utf-8')
            return original(rid,stage,*args,**kw)
        self.app._dispatch=change
        result=self.app.publish_learning_inputs(self.package(),'stale')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.http.fake.writes(),0)

    def test_omit_guard_and_new_id_cannot_downgrade_corpus(self):
        self.publish()
        with self.assertRaises(DeliveryError):
            self.http.app.create_activity('guarded-upload','unguarded','other',self.f.intent)
        with self.assertRaises(DeliveryError):
            self.http.app.publish_learning_inputs(self.package(),'unguarded-upload')
        self.assertEqual(self.http.fake.writes('/api/books'),0)

    def test_new_guarded_reuse_has_own_local_receipt_without_reupload(self):
        self.publish();posts=self.http.fake.writes()
        result=self.app.publish_learning_inputs(self.package(),'guarded-reuse')
        self.assertTrue(result['reusedCorpus'])
        self.assertEqual(result['requestId'],'guarded-reuse')
        self.assertEqual(self.http.fake.writes(),posts)
        self.assertEqual(self.http.store.request('guarded-reuse')['semantic']['reusedFrom'],'guarded-upload')

    def test_legacy_reuse_upgrade_preserves_old_semantic_but_requires_guard(self):
        self.http.app.publish_learning_inputs(self.package(),'legacy')
        old=copy.deepcopy(self.http.store.request('legacy'))
        self.publish()
        self.assertEqual(self.http.store.request('legacy'),old)
        with self.assertRaises(DeliveryError):
            self.http.app.create_activity('legacy','bypass-old','other',self.f.intent)

    def test_second_brief_can_reuse_same_corpus_with_actual_new_header(self):
        self.create()
        self.f.brief['briefId']='second-brief';self.f.brief['pacing']['depth']='standard'
        self.f.manifest['depth']='standard';self.f.save_manifest()
        self.f.intent='再次学习本规程停服要求。';self.f.request.update(mapId='second-map',intent=self.f.intent)
        self.f.recognition=self.f.make_recognition()
        for name,value in [('brief',self.f.brief),('request',self.f.request),
                           ('recognition',self.f.recognition),('review',self.f.review())]:
            self.f.save(self.f.root/(name+'.json'),value)
        result=self.app.create_activity('guarded-upload','second-create','second',self.f.intent)
        self.assertEqual(result['status'],'succeeded',result)
        actual=self.http.store.request('second-create')['semantic']['payload']
        self.assertEqual(actual['depth'],'standard');self.assertEqual(actual['user_intent'],self.f.intent)
        writes=self.http.fake.writes()
        reread=self.http.app.create_activity('guarded-upload','second-create','second',self.f.intent)
        self.assertEqual(reread['status'],'succeeded')
        self.assertEqual(self.http.fake.writes(),writes)

    def test_confirm_null_or_missing_separate_review_cannot_post(self):
        created=self.create();posts=self.http.fake.writes()
        for payload in (None,{'title':'偏题'}):
            with self.assertRaises(DeliveryError):
                self.app.confirm_proposal('guarded-activity','confirm',payload,created['revision'])
        with self.assertRaises(DeliveryError):
            self.http.app.confirm_proposal('guarded-activity','confirm2',{},created['revision'])
        self.assertEqual(self.http.fake.writes(),posts)

    def test_confirm_exact_payload_review_does_not_cover_different_payload(self):
        created=self.create();payload={'title':'合成规程'}
        body={'book_id':created['bookId'],'expected_revision':created['revision'],'proposal':payload}
        self.operation_review('confirm-proposal',body)
        with self.assertRaises(DeliveryError):
            self.app.confirm_proposal('guarded-activity','bad-confirm',{'title':'different'},created['revision'])
        result=self.app.confirm_proposal('guarded-activity','confirm',payload,created['revision'])
        self.assertEqual(result['status'],'succeeded',result)
        saved=self.http.store.request('confirm')
        self.assertIn('productionReviewRef',saved['semantic'])
        self.assertEqual(saved['semantic']['productionReviewRef']['digest'],digest(saved['audit']['productionReview']))
        (self.f.root/'step-review.json').unlink()
        posts=self.http.fake.writes()
        reread=self.http.app.confirm_proposal('guarded-activity','confirm',payload,created['revision'])
        self.assertEqual(reread['status'],'succeeded');self.assertEqual(self.http.fake.writes(),posts)

    def test_step_review_cannot_change_between_prepare_and_dispatch(self):
        created=self.create();payload={'title':'合成规程'}
        body={'book_id':created['bookId'],'expected_revision':created['revision'],'proposal':payload}
        review=self.operation_review('confirm-proposal',body)
        original=self.app._dispatch
        def replace(rid,stage,*args,**kw):
            if stage=='book':
                self.f.save(self.f.root/'step-review.json',{**review,'id':'different-review'})
            return original(rid,stage,*args,**kw)
        self.app._dispatch=replace;posts=self.http.fake.writes()
        result=self.app.confirm_proposal('guarded-activity','changed-review',payload,created['revision'])
        self.assertEqual(result['status'],'failed');self.assertEqual(self.http.fake.writes(),posts)

    def test_unknown_write_recovery_never_reposts_and_readonly_ignores_today_staleness(self):
        self.publish()
        def fault(point):
            if point=='dispatching': raise RuntimeError('simulated crash')
        self.app.fault=fault
        with self.assertRaises(RuntimeError):
            self.app.create_activity('guarded-upload','crash','crash-activity',self.f.intent)
        writes=self.http.fake.writes()
        self.f.k.source.write_text('changed',encoding='utf-8')
        result=self.http.app.reconcile_request('crash')
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(self.http.fake.writes(),writes)

    def test_reindex_post_cannot_omit_guard(self):
        self.http.fake.index_mode='failed'
        result=self.app.publish_learning_inputs(self.package(),'guarded-upload')
        self.assertEqual(result['status'],'uncertain')
        before=self.http.fake.writes()
        result=self.http.app.recover_inputs('guarded-upload')
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(self.http.fake.writes(),before)

    def test_real_cli_offline_check_and_parse_knowledge_connection_flag(self):
        result=subprocess.run([sys.executable,'-X','utf8','-B','-m',
            'tools.wiki_runtime.evidence.integration_cli','check-preparation',
            '--knowledge-preparation',str(self.descriptor)],cwd=k3.REPO,capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(json.loads(result.stdout)['coursePublishAuthorized'])
        from tools.learning_book.cli import parser
        args=parser().parse_args(['create','--state-dir','state','--deployment','dep','--request-id','x',
            '--corpus-receipt','y','--activity-id','z','--intent','goal',
            '--knowledge-preparation',str(self.descriptor)])
        self.assertEqual(args.knowledge_preparation,str(self.descriptor))

    def test_real_production_cli_uses_connection_with_local_http_only(self):
        from tools.learning_book.budget import process_identity
        from tools.learning_book.contracts import load_deployment
        code="from tools.tests.test_learning_book_i3 import FakeDT; import sys,json; f=FakeDT(); print(json.dumps({'url':f.url}),flush=True); sys.stdin.read(); f.close()"
        process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-X','utf8','-B','-u','-c',code],cwd=k3.REPO,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            url=json.loads(process.stdout.readline())['url']
            cfg=json.loads(self.http.config_path.read_text(encoding='utf-8'));cfg['baseUrl']=url
            config_path=self.f.save(self.http.root/'cli-deployment.json',cfg)
            scope=load_deployment(config_path)['scope']
            context={**self.http.context,'scope':scope,'stopProcess':{
                **process_identity(process.pid),'ownership':'dedicated_single_worker'}}
            budget=self.f.save(self.http.root/'cli-budget.json',context)
            common=['--deployment',config_path,'--state-dir',str(self.http.store.root),
                '--budget-context',budget,'--knowledge-preparation',str(self.descriptor)]
            operations=[['publish-inputs','--request-id','cli-upload','--package',str(self.f.folder/'prepare.json')],
                ['create','--request-id','cli-create','--corpus-receipt','cli-upload',
                 '--activity-id','cli-activity','--intent',self.f.intent]]
            for operation in operations:
                result=subprocess.run([sys.executable,'-X','utf8','-B','-m','tools.learning_book.cli',
                    *operation,*common],cwd=k3.REPO,capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                value=json.loads(result.stdout)
                self.assertEqual(value['knowledgePreparationStatus'],'integrated_operator_supplied')
        finally:
            process.stdin.close()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
            process.stdout.close();process.stderr.close()


if __name__=='__main__': unittest.main()
