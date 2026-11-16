"""实际 FastAPI 路由和 BookStorage 测试；独立临时 runtime，无模型。"""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    sys.path.insert(0, str(source))
    with tempfile.TemporaryDirectory(prefix="i4-upstream-") as runtime:
        os.environ["DEEPTUTOR_HOME"] = runtime
        # 模块 wheel 使用 namespace 父包；从独立解包目录测试时只叠加其
        # 源码搜索位置，其他模块依赖仍来自固定 venv，不改 site-packages。
        import deeptutor
        deeptutor.__path__.insert(0, str(source / "deeptutor"))
        import deeptutor.api
        deeptutor.api.__path__.insert(0, str(source / "deeptutor/api"))
        import deeptutor.api.routers
        deeptutor.api.routers.__path__.insert(0, str(source / "deeptutor/api/routers"))
        # Windows asyncio 的 socketpair 本身需要 loopback connect；仅放行
        # 标准库这个内部调用，其他连接（含本机模型服务）一律拒绝。
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
            from deeptutor.book.models import Book, BookStatus, Chapter, Page, PageLink, Spine
            from deeptutor.book.storage import BookStorage
            from deeptutor.multi_user import book_access
            from deeptutor.multi_user.book_access import ResolvedBook
            from deeptutor.services.path_service import PathService
            assert Path(router.__file__).resolve() == source / "deeptutor/api/routers/book.py"
            import deeptutor.book.storage
            assert Path(deeptutor.book.storage.__file__).resolve() == source / "deeptutor/book/storage.py"

            class Tests(unittest.TestCase):
                def setUp(self):
                    self.temp = tempfile.TemporaryDirectory(dir=runtime)
                    self.addCleanup(self.temp.cleanup)
                    self.root = Path(self.temp.name)
                    self.storage = BookStorage(path_service=PathService(self.root))
                    self.storage.save_book(Book(id="bk_1", status=BookStatus.READY, page_count=1))
                    self.storage.save_page(Page(id="pg_1", book_id="bk_1", chapter_id="ch_1"))
                    self.storage.save_spine(Spine(book_id="bk_1", chapters=[Chapter(id="ch_1", page_ids=["pg_1"])]))
                    self.engine = BookEngine(storage=self.storage)
                    self.resolved = ResolvedBook(self.engine, "own", "edit", True, True, self.storage)
                    self.resolver = patch.object(router, "resolve_book", return_value=self.resolved).start()
                    self.addCleanup(patch.stopall)
                    app = FastAPI()
                    app.include_router(router.router, prefix="/api")
                    self.client = TestClient(app)

                def get(self):
                    response = self.client.get("/api/books/bk_1/content")
                    self.assertEqual(response.status_code, 200)
                    return response.json()

                def codes(self):
                    return {v["code"] for v in self.get()["pageEnumeration"]["errors"]}

                def inventory(self):
                    return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in self.root.rglob("*") if p.is_file()}

                def test_new_route_all_states_zero_resume_or_business_writes(self):
                    for state in BookStatus:
                        book = self.storage.load_book("bk_1")
                        book.status = state
                        self.storage.save_book(book)
                        before = self.inventory()
                        with patch.object(self.engine, "maybe_resume_on_open", new_callable=AsyncMock) as resume, \
                             patch.object(self.engine, "compile_page", new_callable=AsyncMock) as compile_page, \
                             patch.object(self.storage, "save_book", side_effect=AssertionError("write")), \
                             patch.object(self.storage, "save_page", side_effect=AssertionError("write")), \
                             patch.object(self.storage, "save_progress", side_effect=AssertionError("write")), \
                             patch.object(self.resolved.learning, "load_progress", side_effect=AssertionError("progress read")):
                            value = self.get()
                            self.assertEqual(value["generation"]["status"], state.value)
                            self.assertEqual(value["schema"], "book-content-read/1")
                            self.assertNotIn("progress", value)
                            resume.assert_not_called()
                            compile_page.assert_not_called()
                        self.assertEqual(before, self.inventory())

                def test_old_get_still_resumes_even_without_blocks(self):
                    with patch.object(self.engine, "maybe_resume_on_open", new_callable=AsyncMock) as resume:
                        response = self.client.get("/api/books/bk_1?include_blocks=false")
                    self.assertEqual(response.status_code, 200)
                    resume.assert_awaited_once_with("bk_1")

                def test_denied_uses_real_resolver_404(self):
                    self.resolver.side_effect = None
                    # 使用真实 router 权限失败路径，不能退入匿名注入引擎。
                    self.resolver.return_value = None
                    with patch.object(router, "_auth_enabled", return_value=True):
                        self.assertEqual(self.client.get("/api/books/bk_1/content").status_code, 404)

                def test_real_access_resolution_uses_selected_workspace_and_owner(self):
                    empty = BookStorage(path_service=PathService(self.root / "other-workspace"))
                    user = type("User", (), {"is_admin": True})()
                    with patch.object(book_access, "get_current_user", return_value=user), \
                         patch.object(book_access, "get_book_storage", return_value=empty), \
                         patch.object(book_access, "_auth_enabled", return_value=True):
                        self.assertIsNone(book_access.resolve_book("bk_1"))
                    from deeptutor.book import engine as engine_module
                    with patch.object(book_access, "get_current_user", return_value=user), \
                         patch.object(book_access, "get_book_storage", return_value=self.storage), \
                         patch.object(engine_module, "get_book_engine", return_value=self.engine):
                        resolved = book_access.resolve_book("bk_1")
                        self.assertIs(resolved.engine.storage, self.storage)

                def test_shared_route_does_not_read_learning_overlay(self):
                    book = self.storage.load_book("bk_1")
                    book.metadata["page_chat_sessions"] = {"pg_1": "private-owner-session"}
                    book.chat_session_id = "private-top-session"
                    self.storage.save_book(book)
                    learning = type("Learning", (), {"load_page_chat_sessions": lambda *a: (_ for _ in ()).throw(AssertionError())})()
                    self.resolver.return_value = ResolvedBook(self.engine, "shared", "read", False, False, learning)
                    value = self.get()
                    self.assertEqual(value["book"]["source"], "shared")
                    self.assertFalse(value["book"]["can_edit"])
                    self.assertNotIn("page_chat_sessions", value["book"]["metadata"])
                    self.assertNotIn("chat_session_id", value["book"])

                def test_real_shared_resolver_acl_read_and_deny(self):
                    empty = BookStorage(path_service=PathService(self.root / "reader-workspace"))
                    user = type("User", (), {"is_admin": False})()
                    self.resolver.side_effect = book_access.resolve_book
                    for level in ("none", "read"):
                        permission = type("Permission", (), {"level_for": lambda _self, _book: level})()
                        with patch.object(book_access, "get_current_user", return_value=user), \
                             patch.object(book_access, "get_book_storage", return_value=empty), \
                             patch.object(book_access, "_admin_storage", return_value=self.storage), \
                             patch.object(book_access, "_auth_enabled", return_value=True), \
                             patch.object(router, "_auth_enabled", return_value=True), \
                             patch.object(book_access, "permission_for_user", return_value=permission):
                            response = self.client.get("/api/books/bk_1/content")
                        self.assertEqual(response.status_code, 404 if level == "none" else 200)
                        if level == "read":
                            self.assertEqual(response.json()["book"]["source"], "shared")
                            self.assertFalse(response.json()["book"]["can_edit"])

                def test_enumerates_orphan_storage_page(self):
                    self.storage.save_page(Page(id="pg_orphan", book_id="bk_1"))
                    value = self.get()
                    self.assertEqual({p["id"] for p in value["pages"]}, {"pg_1", "pg_orphan"})
                    self.assertEqual(value["pageEnumeration"]["fileCount"], 2)
                    self.assertIn("manifest_page_count", self.codes())

                def test_corrupt_page_not_silently_skipped(self):
                    (self.storage.path_service.get_book_pages_dir("bk_1") / "bad.json").write_text("{bad")
                    self.assertIn("page_unreadable_or_invalid", self.codes())
                    self.assertEqual(len(self.storage.list_pages("bk_1")), 1)

                def test_duplicate_json_keys_invalid(self):
                    self.storage.path_service.get_book_page_file("bk_1", "pg_1").write_text('{"id":"pg_1","id":"pg_2"}')
                    self.assertIn("page_unreadable_or_invalid", self.codes())

                def test_missing_explicit_page_identity_invalid(self):
                    self.storage.path_service.get_book_page_file("bk_1", "pg_1").write_text('{"book_id":"bk_1"}')
                    self.assertIn("page_unreadable_or_invalid", self.codes())

                def test_cross_book_page(self):
                    self.storage.save_page(Page(id="pg_x", book_id="bk_1"))
                    path = self.storage.path_service.get_book_page_file("bk_1", "pg_x")
                    value = json.loads(path.read_text())
                    value["book_id"] = "bk_other"
                    path.write_text(json.dumps(value))
                    self.assertIn("page_book_identity", self.codes())

                def test_duplicate_id_and_filename_mismatch(self):
                    page = self.storage.path_service.get_book_page_file("bk_1", "pg_1")
                    page.with_name("pg_alias.json").write_bytes(page.read_bytes())
                    self.assertTrue({"duplicate_page_id", "page_file_identity"} <= self.codes())

                def test_missing_spine_reference(self):
                    self.storage.path_service.get_book_page_file("bk_1", "pg_1").unlink()
                    self.assertIn("referenced_page_missing", self.codes())

                def test_missing_parent_or_link_reference(self):
                    self.storage.save_page(Page(id="pg_1", book_id="bk_1", parent_page_id="pg_missing",
                                                links=[PageLink(target_page_id="pg_also_missing")]))
                    self.assertIn("referenced_page_missing", self.codes())

                def test_missing_spine(self):
                    self.storage.path_service.get_book_spine_file("bk_1").unlink()
                    self.assertIn("spine_missing_or_invalid", self.codes())

                def test_missing_pages_directory(self):
                    self.storage.path_service.get_book_page_file("bk_1", "pg_1").unlink()
                    self.storage.path_service.get_book_pages_dir("bk_1").rmdir()
                    self.assertIn("page_inventory_unreadable", self.codes())

                def test_deletion_during_read_is_reported(self):
                    original = Path.read_text
                    target = self.storage.path_service.get_book_page_file("bk_1", "pg_1")
                    def remove(path, *a, **kw):
                        if path == target:
                            path.unlink()
                        return original(path, *a, **kw)
                    with patch.object(Path, "read_text", remove):
                        codes = self.codes()
                    self.assertIn("page_unreadable_or_invalid", codes)
                    self.assertIn("page_inventory_changed", codes)

                def test_changes_during_read_are_reported(self):
                    original = Path.read_text
                    target = self.storage.path_service.get_book_page_file("bk_1", "pg_1")
                    def change(path, *a, **kw):
                        value = original(path, *a, **kw)
                        if path == target:
                            path.write_text(value + " ")
                        return value
                    with patch.object(Path, "read_text", change):
                        self.assertIn("page_inventory_changed", self.codes())

                def test_safe_diagnostics_do_not_expose_paths(self):
                    directory = self.storage.path_service.get_book_pages_dir("bk_1")
                    (directory / "private-secret-filename.json").write_text("not json")
                    diagnostic = json.dumps(self.get()["pageEnumeration"])
                    self.assertNotIn("private-secret", diagnostic)
                    self.assertNotIn(str(self.root), diagnostic)

            started = time.monotonic()
            result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
            report = {"kind": "actual_fastapi_storage_tests", "baseCommit": "60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db",
                      "subject": "wheel_extraction" if (source / "deeptutor_books-1.7.2.dist-info").is_dir() else "source_tree",
                      "recordedAt": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                      "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                      "skipped": len(result.skipped), "seconds": round(time.monotonic() - started, 3),
                      "realModelCalls": 0, "outboundSocketConnect": "denied",
                      "sources": {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (source / "deeptutor/book/storage.py", source / "deeptutor/api/routers/book.py")}}
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
