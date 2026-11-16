"""Q2：真实窄路由／BookEngine／HTTP，固定发行源码；仅夹具数据，无模型。"""
from contextlib import ExitStack, closing
from copy import deepcopy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

from tools.learning_book.contracts import canonical, decode_json, digest, load_deployment, read_json, sha256, validate_package, DeliveryError
from tools.learning_book.question_preparation import QuestionPreparation, ordered_bytes, publication_digest
from tools.learning_book.question_spec import question_digest, spec_digest, extract_authored, render_variant_template
from tools.learning_book.evidence_store import EvidenceStore, atomic
from tools.learning_book.production import Production
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.budget import Budget
from tools.learning_book.baseline import Baseline
from tools.tests.test_learning_book_i3 import make_package
from tools.tests import test_learning_book_i4 as i4

EXAMPLES = Path(__file__).resolve().parents[1] / 'learning_book/examples/questions'


def prepare(root, mode='authored', *, option_order=True):
    root.mkdir(parents=True, exist_ok=True)
    spec = read_json(EXAMPLES / (mode + '.json'))
    spec['sources'][0].update(sourceId='src-1', sourceVersionId='src-v1')
    for item in spec['items']:
        item['sourceRefs'] = ['src-1']
        for misconception in item.get('misconceptions', []): misconception['sourceRefs'] = ['src-1']
        if mode == 'authored' and option_order:
            options = item['authoredItem']['options']; item['authoredItem']['options'] = {k: options[k] for k in ('C','A','D','B')}
    for name in ('source.md', 'lesson.md'): shutil.copyfile(EXAMPLES / name, root / name)
    (root / 'spec.json').write_bytes(ordered_bytes(spec))
    sources = {'src-1': {'sourceVersionId':'src-v1', 'content':(root / 'source.md').read_bytes()}}
    contents = [extract_authored(spec, item['questionId']) if mode == 'authored' else render_variant_template(
        spec, item['questionId'], source_inputs=sources, lesson_ref=spec['lessonRef'], lesson_bytes=(root/'lesson.md').read_bytes()) for item in spec['items']]
    review = {'schema':'learning-question-preparation-review/1','reviewId':'pre-review','reviewedBy':'test-reviewer',
        'specDigest':spec_digest(spec),'mode':mode,'decision':'reviewed_for_production','assurance':'operator_supplied',
        'checks':[{'questionId':q['question_id'],'contentDigest':question_digest(q) if mode == 'authored' else digest(q),
                   'reason':'合成案例：依据 C3 核对目标、条件与答案；仅供测试。'} for q in contents]}
    (root/'review.json').write_bytes(canonical(review))
    descriptor = {'schema':'learning-question-preparation/1','root':str(root.resolve()),'specPath':'spec.json',
        'specDigest':spec_digest(spec),'lessonPath':'lesson.md','sourceInputs':[
            {'sourceId':'src-1','sourceVersionId':'src-v1','path':'source.md'}],'reviewPath':'review.json'}
    (root/'question-preparation.json').write_bytes(canonical(descriptor))
    return QuestionPreparation(root/'question-preparation.json')


class QuestionIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='question-q2-'); self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {'DEEPTUTOR_HOME':str(self.root/'home')}))
        from fastapi import FastAPI, HTTPException
        import uvicorn
        from deeptutor.api.routers import book as router
        from deeptutor.book.engine import BookEngine
        from deeptutor.book.models import Book, Page, Chapter, Spine, Block, BlockType, Progress
        from deeptutor.book.storage import BookStorage
        from deeptutor.services.path_service import PathService
        import deeptutor.book.question_publication as impl
        self.implementation = impl
        self.guard = prepare(self.root/'question')
        make_package(self.root/'package', content=(EXAMPLES/'source.md').read_bytes())
        self.package = validate_package(self.root/'package/prepare.json')
        self.storage = BookStorage(path_service=PathService(workspace_root=self.root/'runtime'))
        self.storage.save_book(Book(id='bk_1', status='ready', page_count=1, chapter_count=1,
            knowledge_bases=['account:kb:test'], language='zh', metadata={'page_chat_sessions':{}}))
        self.storage.save_spine(Spine(book_id='bk_1',chapters=[Chapter(id='ch_1',page_ids=['pg_1'])]))
        self.storage.save_page(Page(id='pg_1',book_id='bk_1',chapter_id='ch_1',status='ready',blocks=[
            Block(id='text',type='text',status='ready',payload={'body':(EXAMPLES/'lesson.md').read_text(encoding='utf-8')}),
            Block(id='quiz',type=BlockType.QUIZ,status='pending')]))
        self.engine = BookEngine(storage=self.storage)
        self.auth_calls=[]; self.authorized=True
        self.resolved = SimpleNamespace(engine=self.engine, is_shared=False, can_edit=True, learning=self.storage,
            source='own', permission='edit',
            capabilities=lambda:{}, load_progress=lambda key:self.storage.load_progress(key) or Progress(book_id=key),
            load_page_chat_sessions=lambda key:{})
        def resolve(key, **kwargs):
            self.auth_calls.append((key,kwargs))
            if not self.authorized or key != 'bk_1': raise HTTPException(status_code=404)
            return self.resolved
        self.stack.enter_context(patch.object(router, '_resolve_book_or_404', side_effect=resolve))
        self.stack.enter_context(patch.object(router, 'get_current_user',return_value=SimpleNamespace(is_admin=False,id='local-test')))
        self.stack.enter_context(patch.object(router, '_auth_enabled', return_value=False))
        self.stack.enter_context(patch('deeptutor.services.workspace.context.current_workspace_id', return_value=''))
        app = FastAPI()
        @app.get('/api/books')
        def listing(): return {'books':[self.storage.load_book('bk_1').model_dump(mode='json')]}
        @app.get('/api/knowledge-bases/{kb}/files')
        def files(kb): return {'files':[{'name':n,'type':'file'} for n in self.package.inputs]}
        @app.get('/api/knowledge-bases/{kb}/files/{name}')
        def file(kb,name):
            from fastapi.responses import Response
            return Response(self.package.inputs[name], media_type='application/octet-stream')
        @app.get('/api/knowledge-bases/{kb}/indexing-run')
        def indexing(kb): return {'run':{'task_id':'task','state':'completed','usable_version':'usable-v1',
            'documents':{n:{'status':'completed','source_hash':sha256(b)} for n,b in self.package.inputs.items()}}}
        app.include_router(router.router,prefix='/api')
        sock=socket.socket(); sock.bind(('127.0.0.1',0)); self.port=sock.getsockname()[1]
        self.server=uvicorn.Server(uvicorn.Config(app, log_level='critical', lifespan='off', access_log=False))
        self.thread=threading.Thread(target=lambda:self.server.run(sockets=[sock]),daemon=True); self.thread.start()
        self.addCleanup(self.stop_server)
        deadline=time.monotonic()+10
        while not self.server.started and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue(self.server.started)
        config={'deploymentId':'test-q2','ownerId':'owner','workspaceId':'','scopeVerification':'configured_single_user',
            'kbOwnerId':'owner','baseUrl':f'http://127.0.0.1:{self.port}','ragProvider':'llamaindex',
            'contentReadBuild':{'baseCommit':'60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db',
                'rendererCommit':'60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db','patchSha256':'1'*64,'wheelSha256':'2'*64},
            'questionProductionBuild':{'capability':impl.CAPABILITY,'baseCommit':'60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db',
                'patchSha256':read_json(Path(__file__).resolve().parents[2]/'patches/deeptutor'/
                    ('q3-fix' if getattr(impl,'SAFETY_REVISION',None)=='learning-question-q3-fix/1' else 'q2')/'manifest.json')['patchSha256'],
                'moduleSha256':sha256(Path(impl.__file__).read_bytes())}}
        config['learningStateReadBuild']={'baseCommit':i4.UPSTREAM,'i4PatchSha256':'1'*64,'patchSha256':'3'*64,'wheelSha256':'4'*64}
        self.config_path=self.root/'deployment.json'; self.config_path.write_bytes(canonical(config)); self.config=load_deployment(self.config_path)
        self.store=EvidenceStore(self.root/'state'); self.backend=DeepTutor(self.config)
        self.fake=SimpleNamespace(inputs={})
        i4.BaselineTests.seed(self)
        self.ledger=self.root/'usage.sqlite3'
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('CREATE TABLE llm_calls(call_id TEXT PRIMARY KEY,started_at REAL,session_id TEXT,turn_id TEXT,source TEXT,usage_json TEXT)')
        self.budget_context={'contextId':'q2-test','scope':self.config['scope'],'ledger':str(self.ledger),
            'baselineCallIds':[],'pauseAt':800,'limit':1000,'pollSeconds':.03,'maxSilentSeconds':10}
        self.budget=Budget(self.budget_context,self.config['scope'],stop=lambda:None)
        self.production=Production(self.store,self.backend,self.budget,question_guard=self.guard)
        self.baseline=Baseline(self.store,self.backend)

    def stop_server(self):
        self.server.should_exit=True; self.thread.join(5)
        self.assertFalse(self.thread.is_alive())

    def publish(self, request='qpub', revision=1, **kwargs):
        return self.production.publish_quiz('activity',request,'pg_1','quiz',revision,**kwargs)

    def wire(self, request='qpub'):
        return self.production._wire_payload(self.store.request(request)['semantic'])

    def answer(self):
        # Actual quiz-attempt route + native progress. Assessment/session side
        # services are outside this question-content contract and stay stubbed.
        with patch('deeptutor.services.session.get_sqlite_session_store',return_value=SimpleNamespace(get_session=AsyncMock(return_value=None))), \
                patch('deeptutor.learning.assessment.record_assessment',new=AsyncMock()):
            for _ in range(2):
                response=self.backend.request('POST','/api/books/quiz-attempt',canonical({'book_id':'bk_1','page_id':'pg_1',
                    'block_id':'quiz','question_id':'baiyu-choice-1','submission_id':'s1','user_answer':'A','is_correct':True}))
                self.assertEqual(response.status,200,response.body)
        self.assertEqual(len(self.storage.load_progress('bk_1').quiz_attempts),1)

    def test_QI01_real_cli_http_zero_model_preserves_option_order(self):
        from tools.learning_book.cli import main
        from deeptutor.agents.question.pipeline import QuestionPipeline
        output=io.StringIO()
        with patch('tools.learning_book.cli.load_budget',return_value=self.budget), patch.object(QuestionPipeline,'run',new=AsyncMock()) as model, contextlib.redirect_stdout(output):
            code=main(['publish-quiz','--activity','activity','--request-id','cli-q','--deployment',str(self.config_path),
                '--state-dir',str(self.store.root),'--page-id','pg_1','--block-id','quiz','--budget-context','synthetic-test-stop',
                '--question-preparation',str(self.guard.path),'--expected-revision','1'])
        self.assertEqual(code,0,output.getvalue()); model.assert_not_called()
        binding,_,questions=self.guard.checked('authored')
        value=self.storage.load_page('bk_1','pg_1').blocks[1]
        self.assertEqual([question_digest(q) for q in value.payload['questions']], [question_digest(q) for q in questions])
        self.assertEqual(list(value.payload['questions'][0]['options']),['C','A','D','B'])
        self.assertEqual(value.metadata['learning_question_binding'],binding)
        self.assertEqual(self.budget.position()['totalTokens'],0)
        self.assertTrue(any(kw.get('edit') for _,kw in self.auth_calls))

    def test_QI02_replay_conflict_revision_and_lost_response(self):
        self.assertEqual(self.publish()['status'],'succeeded')
        before=self.storage.load_book('bk_1').revision
        self.assertEqual(self.publish()['status'],'succeeded'); self.assertEqual(before,self.storage.load_book('bk_1').revision)
        body=self.wire(); body['questions'][0]['explanation']+='changed'; body['request_digest']=publication_digest(body)
        self.assertEqual(self.backend.request('POST','/api/books/publish-quiz',ordered_bytes(body)).status,409)
        with self.assertRaises(DeliveryError): self.publish('stale',1)
        # Project cannot rely on a lost response. Reconcile reads exact journal identity.
        self.store.stage_dir('qpub','book').joinpath('response.bin').unlink()
        self.store.stage_dir('qpub','book').joinpath('response.json').unlink()
        self.store.save_receipt('qpub','uncertain',activityId='activity',bookId='bk_1')
        with patch.object(self.backend,'request',wraps=self.backend.request) as calls:
            self.assertEqual(self.production.reconcile_request('qpub')['status'],'succeeded')
            self.assertEqual(self.publish()['status'],'succeeded')
            self.assertTrue(Path(self.store.receipt('qpub')['artifactRef']).is_file())
        self.assertFalse(any(c.args[0]=='POST' for c in calls.call_args_list))

    def test_QI02_concurrent_http_writers_only_one_commit(self):
        from concurrent.futures import ThreadPoolExecutor
        self.production.fault=lambda name: (_ for _ in ()).throw(RuntimeError('freeze')) if name=='prepared' else None
        with self.assertRaises(RuntimeError): self.publish()
        bodies=[self.wire(),self.wire()]
        bodies[1]['request_id']='competitor'; bodies[1]['request_digest']=publication_digest(bodies[1])
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses=list(executor.map(lambda b:self.backend.request('POST','/api/books/publish-quiz',ordered_bytes(b)),bodies))
        self.assertEqual(sorted(r.status for r in responses),[200,409])
        self.assertEqual(self.storage.load_book('bk_1').revision,2)

    def test_QI02_real_process_exit_each_journal_boundary_and_extra_edit_uncertain(self):
        self.production.fault=lambda name: (_ for _ in ()).throw(RuntimeError('freeze')) if name=='prepared' else None
        with self.assertRaises(RuntimeError): self.publish()
        body_file=self.root/'wire.json'; body_file.write_bytes(ordered_bytes(self.wire()))
        from deeptutor.book.storage import BookStorage
        from deeptutor.services.path_service import PathService
        script='''
import os,sys
from pathlib import Path
from deeptutor.book.storage import BookStorage
from deeptutor.book.engine import BookEngine
from deeptutor.services.path_service import PathService
from deeptutor.book.question_publication import publish
from tools.learning_book.contracts import read_json
storage=BookStorage(path_service=PathService(workspace_root=Path(sys.argv[1])))
def fault(name):
 if name==sys.argv[3]: os._exit(47)
publish(BookEngine(storage=storage),read_json(sys.argv[2]),fault=fault)
'''
        for boundary in ('prepared','page','book','applied'):
            copy=self.root/boundary; shutil.copytree(self.root/'runtime',copy)
            child=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(copy),str(body_file),boundary],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(child.returncode,47,child.stderr)
            storage=BookStorage(path_service=PathService(workspace_root=copy))
            self.assertEqual(self.implementation.recover_all(storage),[])
            self.assertEqual(storage.load_book('bk_1').revision,2)
        copy=self.root/'uncertain'; shutil.copytree(self.root/'runtime',copy)
        child=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(copy),str(body_file),'prepared'],capture_output=True,timeout=30)
        self.assertEqual(child.returncode,47)
        storage=BookStorage(path_service=PathService(workspace_root=copy))
        path=storage.path_service.get_book_page_file('bk_1','pg_1'); changed=read_json(path); changed['title']='unrelated edit'
        path.write_bytes(ordered_bytes(changed)); before=path.read_bytes()
        self.assertEqual(self.implementation.recover_all(storage),[{'bookId':'bk_1','code':'question_journal_uncertain'}])
        self.assertEqual(path.read_bytes(),before)
        with self.assertRaises(DeliveryError): storage.load_page('bk_1','pg_1')

    def test_QI03_native_content_cannot_replace_but_attempt_storage_survives(self):
        self.assertEqual(self.publish()['status'],'succeeded')
        response=self.backend.request('POST','/api/books/regenerate-block',canonical({'book_id':'bk_1','page_id':'pg_1','block_id':'quiz','expected_revision':2}))
        self.assertEqual(response.status,409)
        from deeptutor.book.models import Progress, QuizAttempt
        progress=Progress(book_id='bk_1',quiz_attempts=[QuizAttempt(page_id='pg_1',block_id='quiz',question_id='baiyu-choice-1',user_answer='A')])
        self.storage.save_progress(progress)
        self.assertEqual(self.storage.load_progress('bk_1').model_dump(),progress.model_dump())
        book=self.storage.load_book('bk_1'); book.metadata['page_chat_sessions']={'pg_1':'session-fixture'}
        self.storage.save_book(book)
        self.assertEqual(self.storage.load_book('bk_1').metadata['page_chat_sessions'],{'pg_1':'session-fixture'})
        page=self.storage.load_page('bk_1','pg_1'); page.blocks[1].payload['questions'][0]['explanation']='changed'
        with self.assertRaises(DeliveryError): self.storage.save_page(page)
        with self.assertRaises(DeliveryError): self.storage.delete_book('bk_1')

    def test_QI04_changed_input_between_freeze_and_dispatch_blocks_egress(self):
        def fault(name):
            if name=='prepared': (self.root/'question/source.md').write_text('changed',encoding='utf-8')
        self.production.fault=fault
        with patch.object(self.backend,'request',wraps=self.backend.request) as calls:
            self.assertEqual(self.publish()['status'],'failed')
        self.assertFalse(any(c.args[0]=='POST' for c in calls.call_args_list))
        self.assertEqual(self.storage.load_book('bk_1').revision,1)

    def test_QI04_changed_review_before_dispatch_and_omitted_guard(self):
        def fault(name):
            if name=='prepared':
                review=read_json(self.root/'question/review.json'); review['checks'][0]['reason']='different review'
                (self.root/'question/review.json').write_bytes(canonical(review))
        self.production.fault=fault
        with patch.object(self.backend,'request',wraps=self.backend.request) as calls:
            self.assertEqual(self.publish()['status'],'failed')
        self.assertFalse(any(c.args[0]=='POST' for c in calls.call_args_list))

    def test_QI04_publish_requires_exact_existing_K_step_review(self):
        from tools.learning_book.knowledge_preparation import PreparationGuard
        guard=PreparationGuard(self.root/'connection.json')
        binding={'normalizedManifestDigest':digest({}),'intent':'fixture'}
        payload={'book_id':'bk_1','expected_revision':1,'questions':[]}
        request=guard.review_request('publish-quiz','activity',self.config['scope'],payload,binding=binding)
        review={'schema':'learning-production-review/1','id':'step-review','requestDigest':request['requestDigest'],
            'reviewedBy':'reviewer','recordedAt':'2026-11-12','decision':'reviewed_for_scope',
            'reason':'合成步骤测试：只许可指定 book/revision/题目。','assurance':'operator_supplied'}
        (self.root/'step.json').write_bytes(canonical(review))
        with patch.object(guard,'checked',return_value=(binding,None,{'operationReview':'step.json'})):
            result=guard.validate({},operation='publish-quiz',activity_id='activity',scope=self.config['scope'],
                payload=payload,expected=binding,include_review=True)
            self.assertEqual(result[1]['request'],request)
            with self.assertRaises(DeliveryError):
                guard.validate({},operation='publish-quiz',activity_id='activity',scope=self.config['scope'],
                    payload={**payload,'expected_revision':2},expected=binding)

    def test_QI03_preexisting_baseline_and_shared_scope_cannot_publish(self):
        atomic(self.baseline._binding_path('activity'),canonical({'historical':'legacy baseline fixture'}))
        with self.assertRaises(DeliveryError): self.publish()
        self.baseline._binding_path('activity').unlink()
        self.resolved.is_shared=True
        self.assertEqual(self.publish()['status'],'failed')

    def test_QI07_ready_quiz_draft_book_cannot_accept_baseline(self):
        from deeptutor.book.models import BookStatus
        book=self.storage.load_book('bk_1'); book.status=BookStatus.DRAFT; self.storage.save_book(book)
        self.assertEqual(self.publish()['status'],'succeeded')
        self.app=self.baseline
        result=i4.BaselineTests.capture(self)
        self.assertEqual(result['captureStatus'],'partial')

    def test_QI06_semantic_drift_is_never_machine_accepted(self):
        self.production.question_guard=prepare(self.root/'variant','variant')
        binding,_,_=self.production.question_guard.checked('variant')
        question=extract_authored(read_json(EXAMPLES/'authored.json'),'baiyu-choice-1')
        question['question_id']=binding['questionIds'][0]
        question['question']='BY-042 的 F-017 与 F-071 不存在编号不一致，完整封签时应如何处置？'
        calls=self.variant_provider(['FINISH\n'+json.dumps(question,ensure_ascii=False)])
        self.assertEqual(self.production.prepare_quiz('activity','drift','pg_1','quiz',None,1)['status'],'succeeded')
        self.app=self.baseline
        self.assertEqual(i4.BaselineTests.capture(self)['captureStatus'],'stable_complete')
        review=i4.BaselineTests.review(self)
        result=self.baseline.record_baseline_review('activity','snapshot','review',review)
        self.assertIn('question_final_review_required',result['gateReasons'])
        self.assertFalse(result['baselineBound']); self.assertEqual(len(calls),1)

    def test_QI02_journal_crash_boundaries_and_uncertain_extra_edit(self):
        # Freeze an actual request without dispatching; journal fault injection then restart storage.
        def stop(name):
            if name=='prepared': raise RuntimeError('stop before project dispatch')
        self.production.fault=stop
        with self.assertRaises(RuntimeError): self.publish()
        body=self.wire()
        def fail(name):
            if name=='page': raise OSError('injected crash')
        with self.assertRaises(OSError): self.implementation.publish(self.engine,body,fault=fail)
        with self.assertRaises(DeliveryError): self.storage.load_book('bk_1')
        self.implementation.recover_all(self.storage)
        self.assertEqual(self.storage.load_book('bk_1').revision,2)
        self.assertEqual(self.implementation.lookup(self.engine,'bk_1','qpub')['publication']['requestDigest'],body['request_digest'])

    def test_QI02_corrupt_recovery_image_and_option_order_never_overwrite(self):
        self.production.fault=lambda name: (_ for _ in ()).throw(RuntimeError('freeze')) if name=='prepared' else None
        with self.assertRaises(RuntimeError): self.publish()
        body=self.wire()
        def fail(name):
            if name=='prepared': raise OSError('stop before content changes')
        with self.assertRaises(OSError): self.implementation.publish(self.engine,body,fault=fail)
        path=self.storage.book_root('bk_1')/'question-writes'/(digest('qpub')+'.json')
        original=read_json(path)
        page_path=self.storage.path_service.get_book_page_file('bk_1','pg_1'); before=page_path.read_bytes()
        for kind in ('text','order','response'):
            changed=deepcopy(original)
            if kind=='text': changed['page']['title']='corrupted image'
            elif kind=='order':
                q=changed['page']['blocks'][1]['payload']['questions'][0]
                q['options']={k:q['options'][k] for k in reversed(q['options'])}
            else: changed['response']['book_revision']=99
            path.write_bytes(ordered_bytes(changed))
            self.assertEqual(self.implementation.recover_all(self.storage),[{'bookId':'bk_1','code':'question_journal_uncertain'}])
            self.assertEqual(page_path.read_bytes(),before)
            self.assertTrue(self.engine.list_books()[0].metadata['learning_question_unstable'])
            response=self.backend.read('/api/books/bk_1/content')
            self.assertEqual(response.status,409)

    def accept(self):
        self.assertEqual(self.publish()['status'],'succeeded')
        self.app=self.baseline
        capture=i4.BaselineTests.capture(self)
        self.assertEqual(capture['captureStatus'],'stable_complete',capture)
        manifest=self.baseline.load_snapshot('snapshot'); self.assertEqual(manifest['schema'],'learning-content-snapshot/2')
        from jsonschema import Draft202012Validator
        schema_dir=EXAMPLES.parents[1]/'schemas'
        Draft202012Validator(read_json(schema_dir/'learning-content-snapshot-v2.schema.json')).validate(manifest)
        Draft202012Validator(read_json(schema_dir/'question-evidence.schema.json')).validate(
            read_json(self.baseline._snapshot_path('snapshot')/'questions.json'))
        review=i4.BaselineTests.review(self)
        result=self.baseline.record_baseline_review('activity','snapshot','review',review)
        self.assertFalse(result['baselineBound']); self.assertIn('question_final_review_required',result['gateReasons'])
        q=read_json(self.baseline._snapshot_path('snapshot')/'questions.json')['blocks'][0]
        review['reviewId']='review-full'
        review['questionProductionChecks']=[{'pageId':'pg_1','blockId':'quiz','questionId':q['questions'][0]['question_id'],
            'specDigest':q['binding']['specDigest'],'questionDigest':q['questionDigests'][0],
            'targetObjectiveId':'conflict','decision':'pass','sourceFidelityChecked':True,'goalAlignmentChecked':True,
            'answerUniqueChecked':True,'explanationChecked':True,'reason':'合成题按 C3 隔离登记；仅 A 满足条件。'}]
        accepted=self.baseline.record_baseline_review('activity','snapshot','review-full',review)
        self.assertTrue(accepted['baselineBound'],accepted)
        self.assertEqual(self.baseline.load_learning_evidence('activity')['bindingStatus'],'accepted')

    def test_QI07_final_question_review_required_and_schema2(self):
        self.accept()

    def test_QI08_handoff2_move_verify_missing_and_tampered_evidence(self):
        from tools.learning_book.handoff import Handoff, verify_handoff
        from deeptutor.book.models import Progress, QuizAttempt
        self.accept()
        self.answer()
        result=Handoff(self.store,self.backend).export_learning_results('activity','q2-export')
        self.assertEqual(result['status'],'succeeded',result)
        package=self.store.root/result['artifactRef']; self.assertEqual(read_json(package/'handoff.json')['schema'],'learning-handoff/2')
        from jsonschema import Draft202012Validator
        schema_dir=EXAMPLES.parents[1]/'schemas'
        Draft202012Validator(read_json(schema_dir/'learning-handoff-v2.schema.json')).validate(read_json(package/'handoff.json'))
        self.assertTrue(Draft202012Validator(read_json(schema_dir/'learning-handoff.schema.json')).is_valid(read_json(package/'handoff.json')))
        moved=self.root/'moved'; shutil.copytree(package,moved)
        self.assertEqual(verify_handoff(moved)['verification'],'valid')
        content=(moved/'questions.json').read_bytes(); (moved/'questions.json').unlink()
        with self.assertRaises(DeliveryError): verify_handoff(moved)
        (moved/'questions.json').write_bytes(content.replace(b'BY-042',b'BY-099'))
        with self.assertRaises(DeliveryError): verify_handoff(moved)

    def test_QI08_native_marker_deletion_cannot_downgrade_collection(self):
        self.assertEqual(self.publish()['status'],'succeeded')
        path=self.storage.path_service.get_book_page_file('bk_1','pg_1')
        page=read_json(path); del page['blocks'][1]['metadata']['learning_question_binding']
        path.write_bytes(ordered_bytes(page))  # adversarial fixture, never production editing
        self.app=self.baseline
        result=i4.BaselineTests.capture(self)
        self.assertEqual(result['status'],'failed',result)

    def test_QI08_variant_payload_drift_with_unchanged_binding_is_rejected(self):
        self.production.question_guard=prepare(self.root/'variant','variant')
        binding,_,_=self.production.question_guard.checked('variant')
        question=extract_authored(read_json(EXAMPLES/'authored.json'),'baiyu-choice-1')
        question['question_id']=binding['questionIds'][0]
        self.variant_provider(['FINISH\n'+json.dumps(question,ensure_ascii=False)])
        self.assertEqual(self.production.prepare_quiz('activity','variant-drift','pg_1','quiz',None,1)['status'],'succeeded')
        path=self.storage.path_service.get_book_page_file('bk_1','pg_1')
        page=read_json(path); page['blocks'][1]['payload']['questions'][0]['explanation']+=' changed after publication'
        path.write_bytes(ordered_bytes(page))
        self.app=self.baseline
        self.assertEqual(i4.BaselineTests.capture(self)['status'],'failed')

    def test_QI09_missing_capability_and_legacy_downgrade_rejected(self):
        del self.backend.config['questionProductionBuild']
        self.assertEqual(self.publish()['status'],'failed')
        # Even a failed controlled request cannot silently become legacy generation.
        self.production.question_guard=None
        with self.assertRaises(DeliveryError):
            self.production.prepare_quiz('activity','legacy','pg_1','quiz',[],1)

    def test_QI03_wrong_page_type_and_learning_started_refused(self):
        self.production.fault=lambda name: (_ for _ in ()).throw(RuntimeError('freeze')) if name=='prepared' else None
        with self.assertRaises(RuntimeError): self.publish()
        body=self.wire()
        for changes in ({'page_id':'other'}, {'block_id':'text'}, {'expected_revision':2}):
            changed={**body,**changes}; changed['request_digest']=publication_digest(changed)
            self.assertEqual(self.backend.request('POST','/api/books/publish-quiz',ordered_bytes(changed)).status,409)
        from deeptutor.book.models import Progress
        self.storage.save_progress(Progress(book_id='bk_1',visited_page_ids=['pg_1']))
        self.assertEqual(self.backend.request('POST','/api/books/publish-quiz',ordered_bytes(body)).status,409)
        self.assertEqual(self.storage.load_book('bk_1').revision,1)

    def test_QI10_fixed_install_backup_restore_new_process_preserves_evidence_and_attempt(self):
        from tools.learning_book.local_install import enroll
        from tools.learning_book.local_backup import backup, restore
        from tools.learning_book.runtime import load_config, verify_build
        from deeptutor.book.models import Progress, QuizAttempt
        self.accept()
        self.answer()
        before=self.storage.load_page('bk_1','pg_1').model_dump(mode='json')
        progress=self.storage.load_progress('bk_1').model_dump(mode='json')
        release=Path(os.environ['LEARNING_QUESTION_Q2_RELEASE']).resolve(strict=True)
        site=self.root/'independent-site'; shutil.copytree(release/'site',site)
        ledger=self.root/'runtime/data/user/usage.sqlite3'; ledger.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(self.ledger,ledger)
        budget_from=self.root/'budget-from.json'; budget_from.write_bytes(canonical(self.budget_context))
        web=self.root/'web'; web.mkdir(); (web/'server.js').write_text('// isolated unused web fixture',encoding='utf-8')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); web_port=sock.getsockname()[1]
        result=enroll(runtime=self.root/'runtime',project_state=self.store.root,control=self.root/'control',
            python=sys.executable,site=site,node=sys.executable,web=web,deployment=self.config_path,
            budget_from=budget_from,wheels=list((release/'wheels').glob('*.whl')),context_id='q2-restored-budget',
            api_port=self.port,web_port=web_port)
        config=load_config(result['config']); verify_build(config)
        self.stop_server()
        backup(config,self.root/'backup')
        restore(self.root/'backup',self.root/'restored')
        script='''
import json,sys
from pathlib import Path
from deeptutor.book.storage import BookStorage
from deeptutor.book.engine import BookEngine
from deeptutor.services.path_service import PathService
from deeptutor.book.question_publication import recover_all,lookup
from tools.learning_book.contracts import digest,load_deployment
from tools.learning_book.evidence_store import EvidenceStore
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.baseline import Baseline
root=Path(sys.argv[1]); storage=BookStorage(path_service=PathService(workspace_root=root/'runtime'))
assert not recover_all(storage)
baseline=Baseline(EvidenceStore(root/'state'),DeepTutor(load_deployment(sys.argv[2])))
print(json.dumps({'pageDigest':digest(storage.load_page('bk_1','pg_1').model_dump(mode='json')),
 'progressDigest':digest(storage.load_progress('bk_1').model_dump(mode='json')),
 'bindingStatus':baseline.load_learning_evidence('activity')['bindingStatus'],
 'requestId':lookup(BookEngine(storage=storage),'bk_1','qpub')['publication']['requestId']}))
'''
        env={**os.environ,'PYTHONPATH':os.pathsep.join((str(site),str(Path(__file__).resolve().parents[2])))}
        child=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(self.root/'restored'),str(self.config_path)],
            env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertEqual(child.returncode,0,child.stderr)
        observed=decode_json(child.stdout)
        self.assertEqual(observed,{'pageDigest':digest(before),'progressDigest':digest(progress),'bindingStatus':'accepted','requestId':'qpub'})

    def variant_provider(self, outputs, *, metered=False):
        from deeptutor.agents.question import pipeline
        calls=[]
        async def create(**kwargs):
            from deeptutor.services.llm.metrics import current_usage
            collector=current_usage.get()
            calls.append({**deepcopy(kwargs),'_scope':{'source':collector.source,'turnId':collector.turn_id,
                'sessionId':collector.session_id} if collector else None})
            need_index=len(calls)-1
            if need_index >= len(outputs): raise RuntimeError('unexpected extra fake provider attempt')
            text=outputs[need_index]
            class Stream:
                def __aiter__(self):
                    async def items():
                        yield SimpleNamespace(usage={'prompt_tokens':3,'completion_tokens':2,'total_tokens':5},
                            choices=[SimpleNamespace(finish_reason='stop',delta=SimpleNamespace(content=text,tool_calls=None))])
                    return items()
                async def close(self): pass
            return Stream()
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        stack=ExitStack()
        if metered:
            from tools.learning_book.runtime_guard import RuntimeGuard
            from deeptutor.services.llm.metrics import instrument_client
            budget=self.root/'runtime-budget.json'; budget.write_bytes(canonical(self.budget_context))
            guard_path=self.root/'runtime-guard.json'; guard_path.write_bytes(canonical({
                'controlDatabase':str(self.root/'runtime-control.sqlite3'),'budget':str(budget),'scope':self.config['scope']}))
            runtime_guard=RuntimeGuard(guard_path); runtime_guard.initialize(); runtime_guard.start()
            stack.enter_context(patch.dict(os.environ,{'LEARNING_BOOK_GUARD':str(guard_path)}))
            stack.enter_context(patch('deeptutor.services.llm.usage_ledger.ledger_path',return_value=self.ledger))
            instrument_client(client)
        stack.enter_context(patch.object(pipeline,'get_llm_config',return_value=SimpleNamespace(binding='openai',model='q2-fake')))
        stack.enter_context(patch.object(pipeline,'build_openai_client',return_value=client))
        self.addCleanup(stack.close)
        return calls

    def test_QI05_variant_observes_real_prompt_and_stays_pending_review(self):
        self.production.question_guard=prepare(self.root/'variant','variant')
        binding,archive,templates=self.production.question_guard.checked('variant')
        question=extract_authored(read_json(EXAMPLES/'authored.json'),'baiyu-choice-1')
        question['question_id']=binding['questionIds'][0]
        calls=self.variant_provider(['FINISH\n'+json.dumps(question,ensure_ascii=False)],metered=True)
        result=self.production.prepare_quiz('activity','variant-1','pg_1','quiz',None,1)
        self.assertEqual(result['status'],'succeeded',result)
        self.assertEqual(len(calls),1,calls)
        self.assertEqual(calls[0]['_scope'],{'source':'book:prepare_question_variant','turnId':'variant-1','sessionId':'book-bk_1'})
        self.assertEqual(self.budget.position()['totalTokens'],5)  # synthetic SDK usage only, no business tokens
        user=calls[0]['messages'][1]['content']
        self.assertIn(templates[0]['reference_question'],user)
        self.assertIn(binding['specDigest'],user)
        self.assertIn('完整封签不能豁免',user)
        self.assertEqual(self.storage.load_page('bk_1','pg_1').blocks[1].metadata['learning_question_binding'],binding)

    def test_QI06_format_failure_and_failed_repair_never_commits(self):
        self.production.question_guard=prepare(self.root/'variant','variant')
        calls=self.variant_provider(['FINISH\n{}','FINISH\n{}'])
        before=self.storage.load_page('bk_1','pg_1').model_dump()
        result=self.production.prepare_quiz('activity','variant-fail','pg_1','quiz',None,1)
        self.assertEqual(result['status'],'failed',result)
        self.assertEqual(len(calls),2)
        self.assertEqual(self.storage.load_page('bk_1','pg_1').model_dump(),before)
        self.assertEqual(self.storage.load_book('bk_1').revision,1)


if __name__=='__main__': unittest.main()
