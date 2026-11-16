"""原生 HTTP/Book WebSocket 适配器 + 真 BookEngine；仅模型生成器是本地替身。"""
import asyncio
from contextlib import closing, ExitStack, nullcontext
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from tools.learning_book.runtime_guard import RuntimeGuard


class NativeGuardTests(unittest.TestCase):
    def test_native_compile_regenerate_and_background_child_calls(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from deeptutor.api.routers import book as router
        from deeptutor.book.engine import BookEngine
        from deeptutor.book.models import Book, Spine, Chapter, Page, PageStatus, Block, BlockStatus, BlockType
        from deeptutor.book.storage import BookStorage
        from deeptutor.services.path_service import PathService
        from deeptutor.services.llm.metrics import measure_provider_call
        from deeptutor.services.llm.provider_core.base import LLMResponse
        from deeptutor.services.llm import usage_ledger
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            root=Path(temp);ledger=root/'usage.sqlite3'
            with closing(sqlite3.connect(ledger)) as db, db:
                db.execute('CREATE TABLE llm_calls(call_id TEXT PRIMARY KEY,started_at REAL,session_id TEXT,turn_id TEXT,source TEXT,usage_json TEXT)')
            (root/'budget.json').write_text(json.dumps(dict(contextId='native',scope={},ledger=str(ledger),baselineCallIds=[],pauseAt=80,limit=100)),encoding='utf-8')
            (root/'guard.json').write_text(json.dumps(dict(controlDatabase=str(root/'control.sqlite3'),budget=str(root/'budget.json'),scope={})),encoding='utf-8')
            guard=RuntimeGuard(root/'guard.json');guard.initialize();guard.start()
            stack.enter_context(patch.dict(os.environ,{'LEARNING_BOOK_GUARD':str(root/'guard.json')}))
            stack.enter_context(patch.object(usage_ledger,'ledger_path',return_value=ledger))
            storage=BookStorage(path_service=PathService(workspace_root=root/'workspace'))
            storage.save_book(Book(id='b'))
            chapter=Chapter(id='ch',page_ids=['p'])
            storage.save_spine(Spine(book_id='b',chapters=[chapter]))
            storage.save_page(Page(id='p',book_id='b',chapter_id='ch',status=PageStatus.READY,
                blocks=[Block(id='q',type=BlockType.QUIZ,status=BlockStatus.READY,payload={'questions':[{'answer':'C'}]})]))
            engine=BookEngine(storage=storage)
            # Workspace activity is an unrelated host concern; keep actual generation source/lifecycle decorators.
            engine._compile_page_now=engine._compile_page_now.__wrapped__.__get__(engine,BookEngine)
            egress=[]
            async def provider(**kwargs):
                egress.append(1)
                return LLMResponse(content='fixture',usage={'prompt_tokens':2,'completion_tokens':1,'total_tokens':3})
            async def work():
                await measure_provider_call(provider,messages=[])
                await asyncio.create_task(measure_provider_call(provider,messages=[]))
            async def compile_page(**kwargs):
                await work()
                page=kwargs['page'];page.status=PageStatus.READY
                for block in page.blocks:block.status=BlockStatus.READY
                storage.save_page(page);return page
            async def generate(ctx):
                await work();ctx.block.status=BlockStatus.READY
            engine.compiler.compile_page=compile_page
            engine.compiler.attach_bridge_text=AsyncMock()
            engine._maybe_finalize_book=AsyncMock()
            resolved=SimpleNamespace(engine=engine,is_shared=False,can_edit=True)
            stack.enter_context(patch.object(router,'_resolve_book_or_404',return_value=resolved))
            stack.enter_context(patch.object(router,'get_current_user',return_value=SimpleNamespace(is_admin=False)))
            stack.enter_context(patch('deeptutor.services.workspace.knowledge.learning_source_access',side_effect=lambda refs:nullcontext()))
            stack.enter_context(patch('deeptutor.book.blocks.base.get_block_registry',return_value={BlockType.QUIZ:SimpleNamespace(generate=generate)}))
            stack.enter_context(patch('deeptutor.api.routers.auth.ws_require_auth',new=AsyncMock(return_value=None)))
            stack.enter_context(patch('deeptutor.multi_user.context.reset_current_user'))
            stack.enter_context(patch('deeptutor.services.workspace.activity.acquire_activity',return_value=SimpleNamespace(close=lambda:None)))
            stack.enter_context(patch.object(router.logger,'error'))
            stack.enter_context(patch('deeptutor.services.workspace.context.resolve_workspace_scope',return_value=SimpleNamespace(archived=False)))
            app=FastAPI();app.include_router(router.router,prefix='/api');app.include_router(router.ws_router,prefix='/ws')
            with TestClient(app) as client:
                response=client.post('/api/books/compile-page',json={'book_id':'b','page_id':'p','force':True})
                self.assertEqual(response.status_code,200,response.text)
                with client.websocket_connect('/ws/books') as ws:
                    ws.send_json({'type':'regenerate_block','book_id':'b','page_id':'p','block_id':'q'})
                    result={}
                    for _ in range(30):
                        result=ws.receive_json()
                        if result['type'] in ('regenerate_block_result','error'):break
                    self.assertEqual(result['type'],'regenerate_block_result',result)
                guard.block('fixture_budget_pause')
                failed=client.post('/api/books/regenerate-block',json={'book_id':'b','page_id':'p','block_id':'q'})
                self.assertEqual(failed.status_code,500)
            status=guard.status()
            self.assertEqual(len(egress),4)
            self.assertEqual(status['position']['totalTokens'],12)
            self.assertEqual({r['source'] for r in status['calls']},{'book:_compile_page_now','book:regenerate_block'})
            self.assertEqual(len({r['turnId'] for r in status['calls']}),2)


if __name__=='__main__':unittest.main()
