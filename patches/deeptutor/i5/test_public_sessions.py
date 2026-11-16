"""I5-C 前置：真实 FastAPI／SQLite 公共 GET，无生成或业务写，注入隐私反例。"""
import argparse
import asyncio
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    root = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(source), str(root)]
    with tempfile.TemporaryDirectory(prefix="i5c-upstream-") as runtime:
        os.environ["DEEPTUTOR_HOME"] = runtime
        import deeptutor
        deeptutor.__path__.insert(0, str(source / "deeptutor"))
        import deeptutor.api
        deeptutor.api.__path__.insert(0, str(source / "deeptutor/api"))
        import deeptutor.api.routers
        deeptutor.api.routers.__path__.insert(0, str(source / "deeptutor/api/routers"))
        connect = socket.socket.connect
        def guarded(sock, address):
            caller = sys._getframe(1)
            if caller.f_code.co_name == "_fallback_socketpair" and caller.f_code.co_filename == socket.__file__:
                return connect(sock, address)
            raise AssertionError("network forbidden")
        with patch.object(socket.socket, "connect", guarded), patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network forbidden")):
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from deeptutor.api.routers import sessions as router
            from deeptutor.services.session.sqlite_store import SQLiteSessionStore
            from deeptutor.services.workspace.context import WorkspaceScope, workspace_context, current_workspace_id
            from tools.learning_book.conversations import public_value
            from tools.learning_book.deeptutor import Response
            from tools.learning_book.contracts import DeliveryError
            assert Path(router.__file__).resolve() == source / "deeptutor/api/routers/sessions.py"
            assert Path(sys.modules[SQLiteSessionStore.__module__].__file__).resolve() == source / "deeptutor/services/session/sqlite_store.py"
            class Tests(unittest.TestCase):
                def setUp(self):
                    self.temp = tempfile.TemporaryDirectory(dir=runtime)
                    self.addCleanup(self.temp.cleanup)
                    self.root = Path(self.temp.name)
                    self.store = SQLiteSessionStore(self.root / "reader.sqlite3")
                    self.other = SQLiteSessionStore(self.root / "other.sqlite3")
                    patch.object(router, "get_session_store", side_effect=lambda: self.other if current_workspace_id() == "other" else self.store).start()
                    self.addCleanup(patch.stopall)
                    async def seed():
                        with workspace_context(WorkspaceScope("reader", self.root, self.root)):
                            await self.store.create_session(session_id="s1")
                            await self.store.update_session_preferences("s1", {"book_id": "bk_1", "book_page_id": "pg_1"})
                            user = await self.store.add_message("s1", "user", "why?")
                            assistant = await self.store.add_message("s1", "assistant", "because", parent_message_id=user)
                            await self.store.begin_turn("s1", turn_id="t1")
                            await self.store.link_turn_message("t1", assistant)
                            for number in range(5):
                                await self.store.append_turn_event("t1", {"type": "text", "content": str(number)})
                        return user, assistant
                    self.user, self.assistant = asyncio.run(seed())
                    app = FastAPI()
                    @app.middleware("http")
                    async def scoped(request, call_next):
                        workspace = request.headers.get("x-deeptutor-workspace", "reader")
                        with workspace_context(WorkspaceScope(workspace, self.root, self.root)):
                            return await call_next(request)
                    app.include_router(router.router, prefix="/api/sessions")
                    self.client = TestClient(app)

                def trace(self, after=0, limit=2):
                    return self.client.get(f"/api/sessions/s1/messages/{self.assistant}/events?after_seq={after}&limit={limit}")

                def dump(self):
                    with closing(sqlite3.connect(self.store.db_path)) as conn:
                        return list(conn.iterdump())

                def test_public_detail_organization_events_zero_business_writes(self):
                    before = self.dump()
                    file_hash = hashlib.sha256(Path(self.store.db_path).read_bytes()).hexdigest()
                    for path in ("/api/sessions/s1", "/api/sessions/s1/organization"):
                        self.assertEqual(self.client.get(path).status_code, 200)
                    self.assertEqual(self.trace().status_code, 200)
                    self.assertEqual(self.dump(), before)
                    self.assertEqual(hashlib.sha256(Path(self.store.db_path).read_bytes()).hexdigest(), file_hash)

                def test_canonical_preview_identity_and_event_pagination(self):
                    detail = self.client.get("/api/sessions/s1").json()
                    msg = next(m for m in detail["messages"] if m["id"] == self.assistant)
                    self.assertEqual(msg["trace"]["turn_id"], "t1")
                    pages = [self.trace(0).json(), self.trace(2).json(), self.trace(4).json()]
                    self.assertEqual([len(p["events"]) for p in pages], [2, 2, 1])
                    self.assertEqual([p["complete"] for p in pages], [False, False, True])
                    self.assertTrue(all(p["session_id"] == "s1" and p["turn_id"] == "t1" and p["total"] == 5 for p in pages))
                    self.assertTrue(all(e["session_id"] == "s1" and e["turn_id"] == "t1" for p in pages for e in p["events"]))

                def test_legacy_empty_complete_does_not_represent_old_events(self):
                    mid = asyncio.run(self.store.add_message("s1", "assistant", "old", events=[{"type": "result", "content": "legacy"}]))
                    detail = self.client.get("/api/sessions/s1").json()
                    msg = next(m for m in detail["messages"] if m["id"] == mid)
                    self.assertTrue(msg["events"])
                    self.assertIsNone(msg["trace"]["turn_id"])
                    trace = self.client.get(f"/api/sessions/s1/messages/{mid}/events").json()
                    self.assertEqual(trace["events"], [])
                    self.assertTrue(trace["complete"])

                def test_actual_workspace_database_isolation_and_message_pairing(self):
                    self.assertEqual(self.client.get("/api/sessions/s1", headers={"x-deeptutor-workspace": "other"}).status_code, 404)
                    self.assertEqual(self.client.get(f"/api/sessions/other/messages/{self.assistant}/events").status_code, 404)
                    self.assertEqual(self.client.get("/api/sessions/missing").status_code, 404)

                def test_private_event_injection_rejected_before_any_raw_capture(self):
                    asyncio.run(self.store.append_turn_event("t1", {"type": "tool_result", "content": "public",
                        "metadata": {"provider_response_state": {"marker": "synthetic-private-marker"}}}))
                    response = self.trace(after=5)
                    self.assertIn("provider_response_state", response.text)
                    with self.assertRaises(DeliveryError) as exc:
                        public_value(Response(200, response.content, "application/json"))
                    self.assertEqual(exc.exception.code, "public_private_data")
                    self.assertNotIn("synthetic-private-marker", str(exc.exception))

                def test_detail_redacts_top_level_metadata_but_not_private_event_payload(self):
                    mid = asyncio.run(self.store.add_message("s1", "assistant", "old", metadata={"model_turn": {"private": True}, "public": 1}))
                    detail = self.client.get("/api/sessions/s1").json()
                    message = next(m for m in detail["messages"] if m["id"] == mid)
                    self.assertNotIn("model_turn", message["metadata"])
                    self.assertEqual(message["metadata"]["public"], 1)

                def test_running_turns_and_attachments_are_public_observations(self):
                    asyncio.run(self.store.add_message("s1", "user", "file", attachments=[{"url": "https://invalid.example/no-fetch", "name": "file"}]))
                    value = self.client.get("/api/sessions/s1").json()
                    self.assertTrue(value["active_turns"])
                    self.assertEqual(value["active_turns"][0]["id"], "t1")
                    self.assertTrue(value["messages"][-1]["attachments"])

                def test_failed_orphan_annotation_is_observation_not_synthetic_reply(self):
                    async def seed_failure():
                        await self.store.create_session(session_id="failed")
                        await self.store.begin_turn("failed", turn_id="failed-turn")
                        await self.store.add_message("failed", "user", "question", metadata={"turn_id": "failed-turn"})
                        await self.store.transition_turn("failed-turn", "failed", error="synthetic-error", failure_code="test_failure")
                    asyncio.run(seed_failure())
                    before = self.dump()
                    value = self.client.get("/api/sessions/failed").json()
                    self.assertEqual(len(value["messages"]), 1)
                    self.assertEqual(value["messages"][0]["metadata"]["orphaned_failed_turn"]["failure_code"], "test_failure")
                    self.assertEqual(self.dump(), before)

                def test_preview_large_content_is_distinct_from_canonical_full_event(self):
                    payload = "x" * 50000
                    asyncio.run(self.store.append_turn_event("t1", {"type": "tool_result", "content": payload}))
                    detail = self.client.get("/api/sessions/s1").json()
                    message = next(m for m in detail["messages"] if m["id"] == self.assistant)
                    preview = next(e for e in message["events"] if e["type"] == "tool_result")
                    self.assertLess(len(preview["content"]), len(payload))
                    full = self.trace(after=5).json()
                    self.assertEqual(full["events"][0]["content"], payload)

            start = time.monotonic()
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
            names = ("deeptutor/api/routers/sessions.py", "deeptutor/services/session/sqlite_store.py", "deeptutor/services/session/provider_response_state.py")
            report = {"kind": "actual_public_session_fastapi_sqlite_tests", "recordedAt": datetime.now(timezone.utc).isoformat(),
                      "tests": result.testsRun, "successful": result.wasSuccessful(), "failures": len(result.failures),
                      "errors": len(result.errors), "skipped": len(result.skipped), "seconds": round(time.monotonic()-start, 3),
                      "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "sources": {n: hashlib.sha256((source/n).read_bytes()).hexdigest() for n in names},
                      "realModelCalls": 0, "outboundConnections": "denied_except_stdlib_socketpair",
                      "privacyObservation": "event_endpoint_can_return_private_metadata; project_rejects_entire_raw_response"}
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
            return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
