"""Q3 缺口回归：真实工具组合／dispatch、HTTP 健康读取、实账本流式计量；零模型。"""
import asyncio
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock

from tools.learning_book.contracts import read_json,sha256,canonical,DeliveryError
from tools.tests import test_learning_question_integration as q2
from tools.tests.test_learning_question_integration import prepare,EXAMPLES


class ToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_composer_and_forged_dispatch_are_disabled_only_for_prepared_path(self):
        from deeptutor.agents.question.pipeline import QuestionPipeline,_BaseLoopHost
        from deeptutor.core.context import UnifiedContext
        context=UnifiedContext(session_id='s',user_message='x',active_capability='deep_question',language='zh')
        with patch('deeptutor.agents.question.pipeline.get_llm_config',return_value=SimpleNamespace(binding='openai',model='fake')):
            regular=QuestionPipeline(language='zh',builtin_tool_whitelist=set())
            self.assertIn('workspace_read',regular._resolved_tools(context))
            prepared=QuestionPipeline(language='zh',kb_name='not-to-be-read',allow_tools=False,builtin_tool_whitelist=set())
        # No replacement of _resolved_tools, _use_native_tools or the registry.
        await prepared._prepare_pageindex_tools()
        self.assertEqual(prepared._resolved_tools(context),[])
        self.assertEqual(prepared._build_llm_tool_schemas(context),[])
        self.assertFalse(prepared._use_native_tools(context))
        host=_BaseLoopHost(pipeline=prepared,stream=SimpleNamespace(),context=context,client=SimpleNamespace())
        with patch('deeptutor.agents.question.pipeline.dispatch_tool_calls',new=AsyncMock()) as dispatch:
            for name in ('workspace_read','write_note','rag','ask_user'):
                with self.assertRaises(PermissionError):
                    await host.dispatch_tools(iteration=1,tool_calls=[{'id':'forged','function':{'name':name,'arguments':'{}'}}])
            dispatch.assert_not_awaited()


class BookTests(unittest.TestCase):
    setUp=q2.QuestionIntegration.setUp
    stop_server=q2.QuestionIntegration.stop_server
    publish=q2.QuestionIntegration.publish

    def bytes(self):
        return {p.relative_to(self.root/'runtime').as_posix():p.read_bytes()
                for p in (self.root/'runtime').rglob('*') if p.is_file()}

    def manager(self):
        from deeptutor.book import kb_health
        kb='test';base=self.root/'kb-manager';raw=base/kb/'raw';raw.mkdir(parents=True)
        book=self.storage.load_book('bk_1');book.knowledge_bases=[kb];self.storage.save_book(book)
        file=raw/'source.md';file.write_text('old source',encoding='utf-8')
        manager=SimpleNamespace(base_dir=base,list_knowledge_bases=lambda:[kb],get_metadata=lambda key:{})
        self.stack.enter_context(patch.object(kb_health,'_current_manager',return_value=manager))
        return kb_health,kb,file

    def health(self):
        response=self.backend.request('GET','/api/books/bk_1/health')
        self.assertEqual(response.status,200,response.body)
        return response.json()['kb_drift']

    def test_controlled_missing_fingerprint_is_unknown_and_entire_store_readonly(self):
        self.manager();self.assertEqual(self.publish()['status'],'succeeded')
        before=self.bytes()
        for _ in range(2):
            report=self.health();self.assertTrue(report['read_only']);self.assertEqual(report['observation'],'unknown')
            self.assertEqual(report['baseline_status'],'missing')
        self.assertEqual(self.bytes(),before)

    def test_real_source_drift_preserves_question_binding_and_attempt_without_writes(self):
        kh,kb,file=self.manager()
        book=self.storage.load_book('bk_1');docs=kh.fingerprint_kb_documents_batch([kb])
        book.kb_document_fingerprints=docs;book.kb_fingerprints={kb:kh.digest_documents(docs[kb])}
        self.storage.save_book(book)
        self.assertEqual(self.publish()['status'],'succeeded')
        from deeptutor.book.models import Progress,QuizAttempt
        self.storage.save_progress(Progress(book_id='bk_1',quiz_attempts=[QuizAttempt(page_id='pg_1',block_id='quiz',question_id='baiyu-choice-1',user_answer='A',is_correct=True)]))
        before=self.bytes();report=self.health();self.assertEqual(report['observation'],'unchanged')
        self.assertEqual(self.bytes(),before)
        file.write_text('changed source',encoding='utf-8')
        report=self.health();self.assertEqual(report['observation'],'drift');self.assertTrue(report['has_drift'])
        self.assertEqual(report['stale_page_ids'],['pg_1']);self.assertEqual(self.bytes(),before)
        with self.assertRaises(DeliveryError):
            book=self.storage.load_book('bk_1');book.title='unsafe edit';self.storage.save_book(book)

    def test_observation_error_and_old_scheme_are_unknown_not_green_and_not_written(self):
        kh,kb,_=self.manager();book=self.storage.load_book('bk_1');book.kb_fingerprints={kb:'old-scheme'}
        self.storage.save_book(book);self.assertEqual(self.publish()['status'],'succeeded');before=self.bytes()
        self.assertEqual(self.health()['baseline_status'],'scheme_mismatch')
        with patch.object(kh,'fingerprint_kb_documents_batch',side_effect=OSError('unavailable')):
            report=self.health();self.assertEqual(report['observation'],'unknown')
            self.assertEqual(report['diagnostic'],'kb_observation_unavailable')
        self.assertEqual(self.bytes(),before)

    def test_legacy_book_retains_fingerprint_maintenance_behavior(self):
        self.manager();before=self.bytes();report=self.health()
        self.assertNotIn('read_only',report);self.assertNotEqual(self.bytes(),before)
        self.assertTrue(self.storage.load_book('bk_1').kb_fingerprints)

    def test_old_module_fingerprint_cannot_satisfy_fixed_capability(self):
        old=Path(__file__).resolve().parents[2]/'.learning-validation/learning-question-q2/release-06/site/deeptutor/book/question_publication.py'
        self.backend.config['questionProductionBuild']['moduleSha256']=sha256(old.read_bytes())
        with patch.object(self.backend,'request',wraps=self.backend.request) as requests:
            result=self.publish()
        self.assertEqual(result['status'],'failed')
        self.assertFalse(any(c.args[0]=='POST' for c in requests.call_args_list))
        self.assertEqual(self.storage.load_book('bk_1').revision,1)

    def test_real_generator_pipeline_prompt_has_no_workspace_tools_without_composer_stubs(self):
        from deeptutor.agents.question import pipeline
        self.production.question_guard=prepare(self.root/'variant','variant')
        outputs=[]
        async def create(**kwargs):
            outputs.append(kwargs)
            text='``FINISH``\n'+json.dumps(read_json(EXAMPLES/'authored.json')['items'][0]['authoredItem'],ensure_ascii=False)
            class Stream:
                def __aiter__(self):
                    async def items():
                        yield SimpleNamespace(usage=None,choices=[SimpleNamespace(finish_reason='stop',delta=SimpleNamespace(content=text,tool_calls=None))])
                    return items()
                async def close(self):pass
            return Stream()
        with (patch.object(pipeline,'get_llm_config',return_value=SimpleNamespace(binding='openai',model='fake')),
              patch.object(pipeline,'build_openai_client',return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))):
            result=self.production.prepare_quiz('activity','fixed-variant','pg_1','quiz',None,1)
        self.assertEqual(result['status'],'succeeded',result);self.assertEqual(len(outputs),1)
        self.assertFalse(outputs[0].get('tools'))
        self.assertNotIn('workspace_read',json.dumps(outputs[0]['messages']))


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.ledger=self.root/'usage.sqlite3'
        with closing(sqlite3.connect(self.ledger)) as db,db:
            db.execute('CREATE TABLE llm_calls(call_id TEXT PRIMARY KEY,started_at REAL,session_id TEXT,turn_id TEXT,source TEXT,usage_json TEXT)')
        from tools.learning_book.runtime_guard import RuntimeGuard
        budget=self.root/'budget.json';budget.write_bytes(canonical({'contextId':'test','scope':{},'ledger':str(self.ledger),
            'baselineCallIds':[],'pauseAt':80000,'limit':100000}))
        cfg=self.root/'guard.json';cfg.write_bytes(canonical({'controlDatabase':str(self.root/'control.sqlite3'),'budget':str(budget),'scope':{}}))
        self.guard=RuntimeGuard(cfg);self.guard.initialize();self.guard.start()
        self.env=patch.dict(os.environ,{'LEARNING_BOOK_GUARD':str(cfg)});self.env.start();self.addCleanup(self.env.stop)
        self.lp=patch('deeptutor.services.llm.usage_ledger.ledger_path',return_value=self.ledger);self.lp.start();self.addCleanup(self.lp.stop)

    def chunk(self,reason=None,usage=None):
        return SimpleNamespace(choices=[SimpleNamespace(index=0,finish_reason=reason,delta=SimpleNamespace(content='x',tool_calls=None))],usage=usage)

    async def stream(self,items):
        from deeptutor.services.llm.metrics import instrument_client
        parent=self
        class Provider:
            closed=False
            def __aiter__(self):
                async def generate():
                    for item in items:
                        if isinstance(item,BaseException):raise item
                        yield item
                return generate()
            async def close(self): self.closed=True
        provider=Provider();self.provider=provider
        async def create(**kwargs):return provider
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        instrument_client(client,model='fake',provider='replay')
        return await client.chat.completions.create(stream=True,messages=[])

    def records(self):
        with closing(sqlite3.connect(self.ledger)) as db:
            return [json.loads(r[0]) for r in db.execute('SELECT usage_json FROM llm_calls ORDER BY rowid')]

    async def test_stream_creation_failure_without_usage_blocks_restart(self):
        from deeptutor.services.llm.metrics import instrument_client
        async def fail(**kwargs):raise RuntimeError('provider unavailable before stream')
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
        instrument_client(client)
        with self.assertRaises(DeliveryError):await client.chat.completions.create(stream=True,messages=[])
        self.assertEqual(self.records()[0]['status'],'failed');self.assertTrue(self.records()[0]['estimated'])
        self.assertEqual(self.guard.status()['calls'][0]['state'],'metering_unknown')
        with self.assertRaises(DeliveryError):self.guard.start()

    async def test_terminal_and_reported_usage_then_close_is_completed_once(self):
        stream=await self.stream([self.chunk('stop',{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5})])
        await anext(stream);await stream.close();await stream.close()
        self.assertEqual(len(self.records()),1);self.assertEqual(self.records()[0]['status'],'completed')
        self.assertEqual(self.records()[0]['total_tokens'],5);self.assertTrue(self.provider.closed)
        self.guard.start();self.assertEqual(self.guard.status()['position']['totalTokens'],5)

    async def test_close_reads_usage_trailer_after_observed_terminal(self):
        stream=await self.stream([self.chunk('stop'),SimpleNamespace(choices=[],usage={'prompt_tokens':4,'completion_tokens':3,'total_tokens':7})])
        await anext(stream);await stream.close()
        self.assertEqual(self.records()[0]['status'],'completed');self.assertEqual(self.records()[0]['total_tokens'],7)

    async def test_missing_trailer_timeout_is_bounded_and_blocks_restart(self):
        from deeptutor.services.llm.metrics import MeasuredStream,CallMeasurement
        class Waiting:
            closed=False
            def __aiter__(self):return self
            async def __anext__(self):await asyncio.Event().wait()
            async def close(self):self.closed=True
        meter=CallMeasurement(messages=[]);provider=Waiting();stream=MeasuredStream(provider,meter)
        stream.iterator=provider;stream._observe(self.chunk('stop'))
        with self.assertRaises(DeliveryError):await asyncio.wait_for(stream.close(),timeout=2)
        self.assertTrue(provider.closed)
        with self.assertRaises(DeliveryError):self.guard.start()

    async def test_missing_report_keeps_estimate_but_blocks_calls_and_restart(self):
        stream=await self.stream([self.chunk('stop')]);await anext(stream)
        with self.assertRaises(DeliveryError):await stream.close()
        self.assertTrue(self.records()[0]['estimated']);self.assertTrue(self.provider.closed)
        self.assertEqual(self.guard.status()['calls'][0]['state'],'metering_unknown')
        with self.assertRaises(DeliveryError):self.guard.begin('new')
        with self.assertRaises(DeliveryError) as e:self.guard.start()
        self.assertEqual(e.exception.code,'unsettled_calls')

    async def test_cancellation_with_report_is_interrupted(self):
        stream=await self.stream([self.chunk(None,{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}),asyncio.CancelledError()])
        await anext(stream)
        with self.assertRaises(asyncio.CancelledError):await anext(stream)
        await stream.close();self.assertEqual(self.records()[0]['status'],'interrupted')

    async def test_provider_error_is_failed_even_after_terminal(self):
        stream=await self.stream([self.chunk('stop',{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5}),RuntimeError('transport')])
        await anext(stream)
        with self.assertRaises(RuntimeError):await anext(stream)
        await stream.close();self.assertEqual(self.records()[0]['status'],'failed')

    async def test_length_is_truncated_and_early_close_is_not_completed(self):
        stream=await self.stream([self.chunk('length',{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5})])
        await anext(stream);await stream.close();self.assertEqual(self.records()[0]['status'],'truncated')
        stream=await self.stream([self.chunk(None,{'prompt_tokens':3,'completion_tokens':2,'total_tokens':5})])
        await anext(stream);await stream.close();self.assertEqual(self.records()[1]['status'],'interrupted')



class InstallSafetyTests(unittest.TestCase):
    def test_verified_fixed_chain_and_hybrid_source_rejected(self):
        from tools.learning_book.local_install import verify_question_install
        root=Path(__file__).resolve().parents[2]
        release=Path(os.environ['LEARNING_QUESTION_Q2_RELEASE'])
        fix=read_json(root/'patches/deeptutor/q3-fix/manifest.json')
        parent=read_json(root/'patches/deeptutor/q2/manifest.json')
        required=set(parent['files'])|set(parent['inheritedFiles'])|set(fix['files'])
        author_path=root/'patches/deeptutor/e1-authored-delivery/manifest.json'
        if author_path.is_file() and (release/'site/deeptutor/book/author_delivery.py').is_file():
            author=read_json(author_path)
            required|=set(author['files'])
        extension_path=root/'patches/deeptutor/controlled-extension/manifest.json'
        if extension_path.is_file() and (release/'site/deeptutor/book/extension_delivery.py').is_file():
            extension=read_json(extension_path)
            required|=set(extension['files'])
        with tempfile.TemporaryDirectory() as temp:
            site=Path(temp);installed={}
            for name in required:
                path=site/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes((release/'site'/name).read_bytes());installed[name]=sha256(path.read_bytes())
            build={'capability':'learning-question-publication/1','baseCommit':fix['baseCommit'],
                'patchSha256':fix['patchSha256'],'moduleSha256':installed['deeptutor/book/question_publication.py']}
            files=verify_question_install(site,installed,build)
            self.assertEqual(files['tools/learning_book/runtime_guard.py'],sha256((root/'tools/learning_book/runtime_guard.py').read_bytes()))
            if author_path.is_file() and (release/'site/deeptutor/book/author_delivery.py').is_file():
                missing=site/'deeptutor/book/author_delivery.py'; original=missing.read_bytes(); missing.unlink()
                with self.assertRaises(DeliveryError): verify_question_install(site,installed,build)
                missing.write_bytes(original)
            for name in fix['files']:
                with self.subTest(file=name):
                    path=site/name;original=path.read_bytes()
                    path.write_bytes((root/'.learning-validation/learning-question-q2/release-06/site'/name).read_bytes())
                    altered={**installed,name:sha256(path.read_bytes())}
                    with self.assertRaises(DeliveryError):verify_question_install(site,altered,build)
                    path.write_bytes(original)


if __name__=='__main__':unittest.main()
