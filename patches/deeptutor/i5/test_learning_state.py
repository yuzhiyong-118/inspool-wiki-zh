"""I5-A：实际 FastAPI、own/shared 存储和 ContextVar 隔离；零模型。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    sys.path.insert(0, str(source))
    with tempfile.TemporaryDirectory(prefix="i5a-upstream-") as runtime:
        os.environ["DEEPTUTOR_HOME"] = runtime
        import deeptutor
        deeptutor.__path__.insert(0, str(source / "deeptutor"))
        import deeptutor.api
        deeptutor.api.__path__.insert(0, str(source / "deeptutor/api"))
        import deeptutor.api.routers
        deeptutor.api.routers.__path__.insert(0, str(source / "deeptutor/api/routers"))
        original_connect = socket.socket.connect
        def guarded_connect(sock, address):
            caller = sys._getframe(1)
            if caller.f_code.co_name == "_fallback_socketpair" and caller.f_code.co_filename == socket.__file__:
                return original_connect(sock, address)
            raise AssertionError("network forbidden")
        with patch.object(socket.socket, "connect", guarded_connect), \
             patch.object(socket.socket, "connect_ex", side_effect=AssertionError("network forbidden")):
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
            from deeptutor.api.routers import book as router
            from deeptutor.book.engine import BookEngine
            from deeptutor.book.models import Book, BookStatus, Progress
            from deeptutor.book.storage import BookStorage
            from deeptutor.book.learning_overlay import BookLearningOverlay
            from deeptutor.book import learning_state_read as strict
            from deeptutor.multi_user import book_access
            from deeptutor.multi_user.book_access import ResolvedBook
            from deeptutor.multi_user.context import set_current_user, reset_current_user
            from deeptutor.multi_user.models import CurrentUser, UserScope
            from deeptutor.services.path_service import PathService
            from deeptutor.services.workspace.context import WorkspaceScope, workspace_context, current_workspace_id
            for module, relative in ((router, "deeptutor/api/routers/book.py"),
                                     (strict, "deeptutor/book/learning_state_read.py")):
                assert Path(module.__file__).resolve() == source / relative

            class Tests(unittest.TestCase):
                def setUp(self):
                    self.temp = tempfile.TemporaryDirectory(dir=runtime)
                    self.addCleanup(self.temp.cleanup)
                    self.root = Path(self.temp.name)
                    self.storage = BookStorage(path_service=PathService(self.root / "own"))
                    self.storage.save_book(Book(id="bk_1", status=BookStatus.READY))
                    self.engine = BookEngine(storage=self.storage)
                    self.resolved = ResolvedBook(self.engine, "own", "edit", True, True, self.storage)
                    self.resolver = patch.object(router, "resolve_book", return_value=self.resolved).start()
                    self.addCleanup(patch.stopall)
                    patch.object(router, "_auth_enabled", return_value=True).start()
                    app = FastAPI()
                    @app.middleware("http")
                    async def scope_context(request, call_next):
                        actor = request.headers.get("x-test-actor", "reader")
                        user = CurrentUser(actor, actor, "user", UserScope("user", actor, self.root))
                        token = set_current_user(user)
                        workspace = request.headers.get("x-deeptutor-workspace", "")
                        try:
                            # Existing context plumbing is real; credential
                            # authentication/header admission is not this fixture.
                            with workspace_context(WorkspaceScope(workspace, self.root, self.root)):
                                return await call_next(request)
                        finally:
                            reset_current_user(token)
                    app.include_router(router.router, prefix="/api")
                    self.client = TestClient(app)
                    self.progress = self.storage.path_service.get_book_progress_file("bk_1")
                    self.manifest = self.storage.path_service.get_book_manifest_file("bk_1")

                def get(self, status=200, **kw):
                    result = self.client.get("/api/books/bk_1/learning-state", **kw)
                    self.assertEqual(result.status_code, status, result.text[:500])
                    return result.json()

                def write(self, value, path=None):
                    target = path or self.progress
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

                def inventory(self):
                    return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in self.root.rglob("*") if p.is_file()}

                def test_all_book_states_no_resume_compile_or_business_writes(self):
                    for state in BookStatus:
                        self.storage.save_book(Book(id="bk_1", status=state))
                        before = self.inventory()
                        with patch.object(self.engine, "maybe_resume_on_open", new_callable=AsyncMock) as resume, \
                             patch.object(self.engine, "compile_page", new_callable=AsyncMock) as compile_page, \
                             patch.object(self.storage, "load_progress", side_effect=AssertionError("forgiving loader")), \
                             patch.object(self.storage, "save_progress", side_effect=AssertionError("write")), \
                             patch.object(self.storage, "save_book", side_effect=AssertionError("write")):
                            value = self.get()
                            self.assertEqual(value["schema"], strict.SCHEMA)
                            self.assertEqual(value["progress"]["status"], "missing")
                            resume.assert_not_called()
                            compile_page.assert_not_called()
                        self.assertEqual(before, self.inventory())

                def test_valid_empty_is_not_missing(self):
                    self.assertEqual(self.get()["progress"]["status"], "missing")
                    raw = Progress(book_id="bk_1").model_dump(mode="json")
                    self.write(raw)
                    value = self.get()["progress"]
                    self.assertEqual(value["status"], "valid")
                    self.assertEqual(value["coverage"], "complete")
                    self.assertEqual(value["value"], raw)

                def test_legacy_fields_never_defaulted_unknown_fields_preserved(self):
                    raw = {"book_id": "bk_1", "quiz_attempts": [{"page_id": "pg", "block_id": "bl", "extension": {"a": 1}}],
                           "future_field": {"timestamp": 3}}
                    self.write(raw)
                    item = self.get()["progress"]
                    self.assertEqual(item["status"], "valid")
                    self.assertEqual(item["coverage"], "partial")
                    self.assertEqual(item["value"], raw)
                    self.assertNotIn("timestamp", item["value"]["quiz_attempts"][0])
                    self.assertNotIn("score", item["value"])

                def test_mixed_bad_attempts_retained_with_index_diagnostics(self):
                    raw = {"book_id": "bk_1", "quiz_attempts": [{"page_id": "pg", "block_id": "bl", "is_correct": False},
                           27, {"page_id": 3, "block_id": "bl", "is_correct": "true", "timestamp": True}]}
                    self.write(raw)
                    item = self.get()["progress"]
                    self.assertEqual(item["status"], "invalid")
                    self.assertEqual(item["value"], raw)
                    pointers = {v["pointer"] for v in item["diagnostics"]}
                    self.assertTrue({"/quiz_attempts/1", "/quiz_attempts/2/is_correct", "/quiz_attempts/2/timestamp"} <= pointers)

                def test_null_false_and_missing_verdict_distinct(self):
                    raw = {"book_id": "bk_1", "quiz_attempts": [{"is_correct": None}, {"is_correct": False}, {}]}
                    self.write(raw)
                    values = self.get()["progress"]["value"]["quiz_attempts"]
                    self.assertIsNone(values[0]["is_correct"])
                    self.assertIs(values[1]["is_correct"], False)
                    self.assertNotIn("is_correct", values[2])

                def test_strict_json_invalid_no_raw_text_or_defaults(self):
                    for data in (b'{bad', b'{"book_id":"bk_1","book_id":"bk_2"}',
                                 b'{"book_id":"bk_1","score":NaN}', b'{"book_id":"bk_1","score":Infinity}',
                                 b'{"book_id":"bk_1","x":1e999}', b'{"book_id":"bk_1","x":"\\ud800"}', b'\xff'):
                        with self.subTest(data=data[:30]):
                            self.progress.write_bytes(data)
                            item = self.get()["progress"]
                            self.assertEqual(item["status"], "invalid")
                            self.assertFalse(item["valueAcquired"])
                            self.assertNotIn("value", item)
                            self.assertEqual(item["sha256"], hashlib.sha256(data).hexdigest())

                def test_wrong_book_id_and_root_types_invalid(self):
                    for raw in ({"book_id": "other"}, {}, [], None, 1):
                        self.write(raw)
                        item = self.get()["progress"]
                        self.assertEqual(item["status"], "invalid")
                        self.assertTrue(item["valueAcquired"])
                        self.assertEqual(item["value"], raw)

                def test_bad_navigation_types_not_coerced(self):
                    self.write({"book_id": "bk_1", "visited_page_ids": ["pg", 3], "weak_chapters": "ch", "score": True,
                                "updated_at": "today", "current_page_id": 2, "quiz_attempts": {}})
                    item = self.get()["progress"]
                    self.assertEqual(item["status"], "invalid")
                    self.assertEqual(len([d for d in item["diagnostics"] if d["code"] != "legacy_field_missing"]), 6)

                def test_own_mapping_original_manifest_not_defaulted(self):
                    raw = json.loads(self.manifest.read_text(encoding="utf-8"))
                    for metadata, expected in ((None, "missing"), ({}, "missing"), ({"page_chat_sessions": {}}, "valid"),
                                               ({"page_chat_sessions": {"pg": "session"}}, "valid")):
                        if metadata is None:
                            raw.pop("metadata", None)
                        else:
                            raw["metadata"] = metadata
                        self.write(raw, self.manifest)
                        item = self.get()["pageChatSessions"]
                        self.assertEqual(item["status"], expected)
                        if expected == "valid":
                            self.assertEqual(item["value"], metadata["page_chat_sessions"])
                        else:
                            self.assertNotIn("value", item)

                def test_mapping_bad_members_not_filtered_or_stringified(self):
                    raw = json.loads(self.manifest.read_text(encoding="utf-8"))
                    raw["metadata"] = {"page_chat_sessions": {"pg": "s", "bad": 3, " ": "x"}}
                    self.write(raw, self.manifest)
                    item = self.get()["pageChatSessions"]
                    self.assertEqual(item["status"], "invalid")
                    self.assertEqual(item["value"], raw["metadata"]["page_chat_sessions"])

                def test_canonical_missing_corrupt_or_identity_wrong_unavailable(self):
                    self.manifest.unlink()
                    self.get(409)
                    for data in ('{bad', '{"id":"other"}', '{"id":"bk_1","status":"invalid"}', '{"id":"bk_1","id":"bk_1"}'):
                        self.manifest.write_text(data, encoding="utf-8")
                        self.get(409)

                def test_denied_resolver_no_anonymous_fallback(self):
                    self.resolver.return_value = None
                    with patch.object(router, "get_book_engine", side_effect=AssertionError("fallback")):
                        self.get(404)

                def test_old_get_still_resumes_and_defaults(self):
                    with patch.object(self.engine, "maybe_resume_on_open", new_callable=AsyncMock) as resume:
                        result = self.client.get("/api/books/bk_1")
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.json()["progress"]["quiz_attempts"], [])
                    resume.assert_awaited_once_with("bk_1")
                    self.assertFalse(self.progress.exists())

                def test_actual_reader_context_reported_auth_and_local(self):
                    value = self.get(headers={"x-test-actor": "reader-2", "x-deeptutor-workspace": "ws-2"})
                    self.assertEqual(value["readerScope"], {"workspaceId": "ws-2", "actorId": "reader-2", "identityKind": "authenticated"})
                    with patch.object(router, "_auth_enabled", return_value=False):
                        self.assertEqual(self.get()["readerScope"]["identityKind"], "local_single_user")

                def test_actual_own_resolver_workspace_isolation(self):
                    other = BookStorage(path_service=PathService(self.root / "other-workspace"))
                    self.resolver.side_effect = book_access.resolve_book
                    from deeptutor.book import engine as engine_module
                    with patch.object(book_access, "get_book_storage", side_effect=lambda: self.storage if current_workspace_id() == "ws-own" else other), \
                         patch.object(book_access, "_auth_enabled", return_value=False), \
                         patch.object(engine_module, "get_book_engine", return_value=self.engine):
                        self.get(404, headers={"x-deeptutor-workspace": "ws-other"})
                        value = self.get(headers={"x-deeptutor-workspace": "ws-own"})
                        self.assertEqual(value["readerScope"]["workspaceId"], "ws-own")

                def shared(self):
                    reader_paths = PathService(self.root / "reader")
                    own = BookStorage(path_service=reader_paths)
                    self.resolver.side_effect = book_access.resolve_book
                    patch.object(book_access, "get_book_storage", return_value=own).start()
                    patch.object(book_access, "get_current_path_service", return_value=reader_paths).start()
                    patch.object(book_access, "_admin_storage", return_value=self.storage).start()
                    patch.object(book_access, "_auth_enabled", return_value=True).start()
                    permission = type("Permission", (), {"level_for": lambda *_: "read"})()
                    patch.object(book_access, "permission_for_user", return_value=permission).start()
                    return BookLearningOverlay(reader_paths), permission

                def test_actual_shared_resolver_only_reader_overlay_no_owner_leak(self):
                    self.write({"book_id": "bk_1", "quiz_attempts": [{"user_answer": "owner-private-answer"}]})
                    raw = json.loads(self.manifest.read_text(encoding="utf-8"))
                    raw["metadata"]["page_chat_sessions"] = {"pg": "owner-private-session"}
                    self.write(raw, self.manifest)
                    overlay, _ = self.shared()
                    self.write({"book_id": "bk_1", "quiz_attempts": [{"user_answer": "reader-answer"}]}, overlay._progress_path("bk_1"))
                    self.write({"pg": "reader-session"}, overlay._chat_path("bk_1"))
                    before = self.inventory()
                    with patch.object(BookLearningOverlay, "load_progress", side_effect=AssertionError("forgiving loader")), \
                         patch.object(BookLearningOverlay, "load_page_chat_sessions", side_effect=AssertionError("forgiving loader")), \
                         patch.object(BookLearningOverlay, "save_progress", side_effect=AssertionError("write")):
                        value = self.get()
                    self.assertNotIn("owner-private", json.dumps(value))
                    self.assertEqual(value["pageChatSessions"]["value"], {"pg": "reader-session"})
                    self.assertEqual(value["contentAccess"], {"source": "shared", "permission": "read"})
                    self.assertEqual(before, self.inventory())

                def test_shared_missing_overlay_no_creation_or_owner_fallback(self):
                    overlay, _ = self.shared()
                    self.assertFalse(overlay.book_root("bk_1").exists())
                    before = self.inventory()
                    value = self.get()
                    self.assertEqual(value["progress"]["status"], "missing")
                    self.assertEqual(value["pageChatSessions"]["status"], "missing")
                    self.assertEqual(before, self.inventory())
                    self.assertFalse(overlay.book_root("bk_1").exists())

                def test_shared_acl_denial_still_404(self):
                    _, permission = self.shared()
                    permission.level_for = lambda *_: "none"
                    self.get(404)

                def test_shared_mapping_states_and_bad_member_preserved(self):
                    overlay, _ = self.shared()
                    path = overlay._chat_path("bk_1")
                    for raw, status in (({}, "valid"), ({"pg": 4}, "invalid"), (None, "invalid"), (["s"], "invalid")):
                        self.write(raw, path)
                        item = self.get()["pageChatSessions"]
                        self.assertEqual(item["status"], status)
                        self.assertEqual(item["value"], raw)
                    path.write_text('{bad', encoding="utf-8")
                    self.assertEqual(self.get()["pageChatSessions"]["status"], "invalid")

                def test_observable_deletion_and_replacement_during_read(self):
                    self.write({"book_id": "bk_1"})
                    original = Path.open
                    for operation in ("delete", "replace"):
                        self.write({"book_id": "bk_1"})
                        def raced(path, *a, **kw):
                            if path == self.progress and a and a[0] == "rb":
                                path.unlink()
                                if operation == "replace":
                                    path.write_bytes(b'{"book_id":"bk_1","score":99}')
                            return original(path, *a, **kw)
                        with patch.object(Path, "open", raced):
                            item = self.get()["progress"]
                        self.assertEqual(item["status"], "changed")
                        self.assertNotIn("value", item)

                def test_observable_change_after_read_detected(self):
                    self.write({"book_id": "bk_1"})
                    original = strict._checked_path
                    calls = 0
                    def raced(path, root):
                        nonlocal calls
                        if path == self.progress:
                            calls += 1
                            if calls == 2:
                                path.write_bytes(b'{"book_id":"bk_1","score":100}')
                        return original(path, root)
                    with patch.object(strict, "_checked_path", raced):
                        self.assertEqual(self.get()["progress"]["status"], "changed")

                def test_unreadable_and_size_limit_not_missing(self):
                    self.write({"book_id": "bk_1"})
                    original = Path.open
                    def denied(path, *a, **kw):
                        if path == self.progress:
                            raise PermissionError("private absolute path must never escape")
                        return original(path, *a, **kw)
                    with patch.object(Path, "open", denied):
                        item = self.get()["progress"]
                    self.assertEqual(item["status"], "unreadable")
                    self.assertNotIn("private", json.dumps(item))
                    with patch.object(strict, "MAX_ITEM_BYTES", 5):
                        item = strict.read_item(self.progress, self.storage.path_service.workspace_root)
                    self.assertEqual(item["status"], "unreadable")

                def test_non_regular_file_rejected(self):
                    self.progress.mkdir()
                    self.assertEqual(self.get()["progress"]["status"], "invalid")

                def test_path_escape_helper_rejected_without_data(self):
                    outside = self.root / "outside.json"
                    outside.write_bytes(b'{"secret":"other reader"}')
                    item = strict.read_item(outside, self.storage.path_service.workspace_root)
                    self.assertEqual(item["status"], "invalid")
                    self.assertNotIn("value", item)
                    self.assertNotIn(str(self.root), json.dumps(item))

                def test_actual_directory_junction_cannot_escape_reader_store(self):
                    # Windows junctions do not require symlink privileges.
                    outside = self.root / "outside"
                    outside.mkdir()
                    (outside / "progress.json").write_bytes(b'{"book_id":"bk_1","secret":"owner"}')
                    link = self.storage.path_service.get_book_dir() / "book_link"
                    if os.name == "nt":
                        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
                        self.assertEqual(result.returncode, 0)
                    else:
                        link.symlink_to(outside, target_is_directory=True)
                    try:
                        item = strict.read_item(link / "progress.json", self.storage.path_service.workspace_root)
                        self.assertEqual(item["status"], "invalid")
                        self.assertNotIn("value", item)
                    finally:
                        if os.name == "nt":
                            link.rmdir()  # unlink only this verified junction, never traverse target
                        else:
                            link.unlink()
                    self.assertTrue((outside / "progress.json").is_file())

            class Result(unittest.TextTestResult):
                def __init__(self, *a, **kw):
                    super().__init__(*a, **kw)
                    self.records = []
                def addSuccess(self, test):
                    super().addSuccess(test)
                    self.records.append({"test": test.id().split(".")[-1], "outcome": "passed"})
            started = time.monotonic()
            result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
            names = ("deeptutor/api/routers/book.py", "deeptutor/book/learning_state_read.py", "deeptutor/book/storage.py")
            report = {"kind": "actual_fastapi_learning_state_storage_tests", "baseCommit": "60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db",
                      "subject": "wheel_extraction" if (source / "deeptutor_books-1.7.2.dist-info").is_dir() else "source_tree",
                      "recordedAt": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                      "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "tests": result.testsRun, "successful": result.wasSuccessful(), "results": result.records,
                      "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
                      "seconds": round(time.monotonic() - started, 3), "realModelCalls": 0, "outboundSocketConnect": "denied",
                      "sources": {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in names}}
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
