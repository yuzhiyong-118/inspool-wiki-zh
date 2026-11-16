"""需固定 DeepTutor 补丁发行物的本地测试；无真实模型。"""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.learning_book.runtime_guard import RuntimeGuard


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_attempt_nested_stream_and_fail_closed(self):
        from deeptutor.services.llm.metrics import CallMeasurement, measure_provider_call, instrument_client, current_usage, TurnUsage
        from deeptutor.services.llm.provider_core.base import LLMResponse
        from deeptutor.services.llm import usage_ledger
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger=root/'usage.sqlite3'
            with closing(sqlite3.connect(ledger)) as db, db:
                db.execute('CREATE TABLE llm_calls (call_id TEXT PRIMARY KEY, started_at REAL, session_id TEXT, turn_id TEXT, source TEXT, usage_json TEXT)')
            budget = root/'budget.json'
            budget.write_text(json.dumps(dict(contextId='test',scope={},ledger=str(ledger),baselineCallIds=[],pauseAt=80,limit=100)),encoding='utf-8')
            guard_config=root/'guard.json'
            guard_config.write_text(json.dumps(dict(controlDatabase=str(root/'guard.sqlite3'),budget=str(budget),scope={})),encoding='utf-8')
            guard=RuntimeGuard(guard_config);guard.initialize();guard.start()
            calls=[]
            async def transport(**kwargs):
                calls.append(kwargs)
                # An adapter under the same measurement must not admit/charge twice.
                nested=CallMeasurement(messages=[])
                self.assertFalse(nested.enabled)
                return LLMResponse(content='ok',usage={'prompt_tokens':3,'completion_tokens':2,'total_tokens':5})
            token=current_usage.set(TurnUsage(session_id='s',turn_id='t',source='test-native'))
            try:
                with patch.dict(os.environ,{'LEARNING_BOOK_GUARD':str(guard_config)}), patch.object(usage_ledger,'ledger_path',return_value=ledger):
                    await asyncio.gather(measure_provider_call(transport,messages=[]),measure_provider_call(transport,messages=[]))
                    class FakeStream:
                        def __aiter__(self):
                            async def chunks():
                                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='ok'))],
                                    usage={'prompt_tokens':3,'completion_tokens':2,'total_tokens':5})
                            return chunks()
                    async def sdk(**kwargs):
                        if kwargs.get('stream'):
                            calls.append(kwargs)
                            return FakeStream()
                        return await transport(**kwargs)
                    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=sdk)))
                    instrument_client(client)
                    await client.chat.completions.create(messages=[])
                    stream=await client.chat.completions.create(messages=[],stream=True)
                    async for _ in stream:pass
                    self.assertEqual(len(calls),4)
                    guard.block('test_pause')
                    with self.assertRaises(Exception):
                        await measure_provider_call(transport,messages=[])
                    self.assertEqual(len(calls),4)
            finally:
                current_usage.reset(token)
            state=guard.status()
            self.assertEqual(state['position']['totalTokens'],20)
            self.assertEqual(len(state['calls']),4)
            self.assertTrue(all(c['state']=='finished' and c['turnId']=='t' and c['sessionId']=='s' for c in state['calls']))


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from deeptutor.book.storage import BookStorage
        from deeptutor.book.models import Page, Block, BlockType, BlockStatus, PageStatus
        from deeptutor.services.path_service import PathService
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.storage=BookStorage(path_service=PathService(workspace_root=Path(self.temp.name)))
        self.page=Page(id='p',book_id='b',status=PageStatus.READY,
            blocks=[Block(id='q',type=BlockType.QUIZ,status=BlockStatus.READY,payload={'questions':[{'answer':'old'}]})])
        self.storage.save_page(self.page)

    async def test_cancel_failure_success_and_read_only_no_replay(self):
        from deeptutor.book.generation import track_generation, generation_state
        from deeptutor.book.models import PageStatus
        host=SimpleNamespace(storage=self.storage)
        entered=asyncio.Event();release=asyncio.Event()
        @track_generation
        async def operation(self,*,book_id,page_id,fail=False):
            page=self.storage.load_page(book_id,page_id)
            page.blocks[0].payload={'questions':[{'answer':'provisional'}]}
            self.storage.save_page(page)
            entered.set();await release.wait()
            if fail: raise ValueError('injected')
            page.status=PageStatus.READY
            page.blocks[0].payload={'questions':[{'answer':'new'}]}
            self.storage.save_page(page)
            return page
        task=asyncio.create_task(operation(host,book_id='b',page_id='p'))
        await entered.wait()
        pending=self.storage.load_page('b','p')
        self.assertEqual(generation_state(pending)['state'],'running')
        from deeptutor.book.engine import BookEngine
        from deeptutor.book.models import Book
        engine=BookEngine(storage=self.storage)
        self.assertTrue(engine.generation_summary('b',book=Book(id='b'),pages=[pending])['working'])
        self.storage.save_book(Book(id='b'))
        from deeptutor.api.routers import book as router
        from fastapi import HTTPException
        resolved=SimpleNamespace(engine=engine,is_shared=False)
        with patch.object(router,'get_current_user',return_value=SimpleNamespace(is_admin=False)):
            with self.assertRaises(HTTPException) as busy:
                router._claim_content_mutation(resolved,'b',None,'update_block')
            self.assertEqual(busy.exception.status_code,409)
            self.assertEqual(router._claim_content_mutation(resolved,'b',None,'pause'),2)
        from tools.tests.test_learning_book_i4 import content
        from tools.learning_book.content import project
        value=content();value['pages'][0]['generation']={'state':'running'}
        self.assertTrue(any(f['code']=='page_generation_active' for f in project(value,'bk_1')[2]['findings']))
        with self.assertRaisesRegex(ValueError,'generation_busy'):
            await operation(host,book_id='b',page_id='p')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        after=self.storage.load_page('b','p')
        self.assertEqual(after.blocks[0].payload,self.page.blocks[0].payload)
        self.assertEqual(generation_state(after)['state'],'cancelled')
        old_id=generation_state(after)['operationId']
        release.set()
        with self.assertRaises(ValueError):await operation(host,book_id='b',page_id='p',fail=True)
        result=await operation(host,book_id='b',page_id='p')
        self.assertEqual(generation_state(result)['state'],'completed')
        self.assertEqual(result.blocks[0].payload['questions'][0]['answer'],'new')
        self.assertNotEqual(generation_state(result)['operationId'],old_id)
        for _ in range(3):
            self.assertEqual(self.storage.load_page('b','p').model_dump(), result.model_dump())

    async def test_restart_keeps_last_complete_and_old_data(self):
        from deeptutor.book.generation import generation_state
        original=self.page.model_dump(mode='json')
        self.page.generation=dict(state='running',executor='dead-process',operationId='o',lastComplete=original)
        self.page.blocks[0].payload={'questions':[]}
        self.storage.save_page(self.page)
        restored=self.storage.load_page('b','p')
        self.assertEqual(restored.blocks[0].payload,original['blocks'][0]['payload'])
        self.assertEqual(generation_state(restored)['state'],'interrupted')
        self.assertTrue(generation_state(restored)['showingLastComplete'])
        self.assertEqual(generation_state(restored)['transportResult'],'unknown')
        from deeptutor.book.engine import BookEngine
        from deeptutor.book.models import Book, BookStatus
        summary=BookEngine(storage=self.storage).generation_summary('b',book=Book(id='b',status=BookStatus.READY),pages=[restored])
        self.assertTrue(summary['operation_interrupted'])
        self.assertFalse(summary['interrupted'])
        self.assertEqual(restored.model_dump(),self.storage.load_page('b','p').model_dump())

    async def test_actual_process_termination_at_four_commit_points(self):
        from deeptutor.book.generation import generation_state
        fixture=Path(__file__).parent/'fixtures/learning_book_closeout/generation_child.py'
        root=Path(self.temp.name)
        for point in ('accepted','generating','before_commit','after_commit'):
            with self.subTest(point=point):
                self.storage.save_page(self.page)
                (root/'checkpoint').unlink(missing_ok=True)
                env={**os.environ,'PYTHONPATH':os.pathsep.join(sys.path),'PYTHONUTF8':'1'}
                process=subprocess.Popen([sys.executable,'-B',str(fixture),str(root),point],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env)
                try:
                    deadline=time.monotonic()+15
                    while not (root/'checkpoint').exists() and time.monotonic()<deadline and process.poll() is None:
                        time.sleep(.02)
                    self.assertTrue((root/'checkpoint').exists(),f'child exit={process.poll()}')
                finally:
                    if process.poll() is None:process.terminate()
                    process.wait(timeout=5)
                restored=self.storage.load_page('b','p')
                if point=='after_commit':
                    self.assertEqual(generation_state(restored)['state'],'completed')
                    self.assertEqual(restored.blocks[0].payload,{'answer':'complete-new'})
                else:
                    self.assertEqual(generation_state(restored)['state'],'interrupted')
                    self.assertEqual(restored.blocks[0].payload,self.page.blocks[0].payload)


if __name__=='__main__':unittest.main()
