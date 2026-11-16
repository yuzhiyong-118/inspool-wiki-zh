"""I5-A：loopback HTTP 能力／身份边界；后续 exporter 尚未实现。"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from tools.learning_book.contracts import DeliveryError, canonical, load_deployment
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.learning_state import CAPABILITY


def observation():
    return {"schema": CAPABILITY, "bookId": "bk_1",
            "readerScope": {"actorId": "local-admin", "workspaceId": "ws-1", "identityKind": "local_single_user"},
            "contentAccess": {"source": "own", "permission": "edit"}, "diagnostics": [],
            "consistency": "per_item_observation",
            "progress": {"status": "valid", "valueAcquired": True, "coverage": "partial",
                         "value": {"book_id": "bk_1", "quiz_attempts": [{"page_id": "pg", "block_id": "bl", "is_correct": None}]},
                         "diagnostics": [{"code": "legacy_field_missing", "pointer": "/updated_at"}]},
            "pageChatSessions": {"status": "valid", "valueAcquired": True, "coverage": "complete",
                                 "value": {}, "diagnostics": []}}


class LearningStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_file = Path(self.temp.name) / "deployment.json"
        self.value, self.status = observation(), 200
        self.profile, self.requests = "configured-owner", []
        test = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                test.requests.append({"method": "GET", "path": self.path,
                                      "workspace": self.headers.get("x-deeptutor-workspace")})
                value = {"id": test.profile} if self.path == "/api/auth/profile" else test.value
                status = 200 if self.path == "/api/auth/profile" else test.status
                body = value if isinstance(value, bytes) else canonical(value)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_POST(self):
                test.requests.append({"method": "POST", "path": self.path})
                self.send_error(405)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close(), thread.join(3)))
        self.config = json.loads((Path(__file__).parents[1] / "learning_book/examples/deployment-i5.json").read_text(encoding="utf-8"))
        self.config.update(baseUrl=f"http://127.0.0.1:{self.server.server_port}", ownerId="configured-owner",
                           kbOwnerId="configured-owner", workspaceId="ws-1")

    def backend(self):
        self.config_file.write_bytes(canonical(self.config))
        return DeepTutor(load_deployment(self.config_file))

    def read(self):
        return self.backend().read_learning_state("bk_1")

    def test_local_identity_label_not_server_actor_and_original_bytes_preserved(self):
        original = canonical(self.value)
        response = self.read()
        self.assertEqual(response.body, original)
        self.assertEqual(response.json()["readerScope"]["actorId"], "local-admin")
        self.assertNotIn("timestamp", response.json()["progress"]["value"]["quiz_attempts"][0])
        self.assertEqual(self.requests, [{"method": "GET", "path": "/api/books/bk_1/learning-state", "workspace": "ws-1"}])

    def test_build_provenance_does_not_change_i3_scope_or_require_i4_capability(self):
        before = self.backend().scope
        self.config.pop("contentReadBuild")
        self.assertEqual(before, self.backend().scope)
        self.read()
        self.config.pop("learningStateReadBuild")
        self.assertEqual(before, self.backend().scope)

    def test_old_i4_config_works_but_cannot_read_new_capability(self):
        self.config.pop("learningStateReadBuild")
        backend = self.backend()
        backend.read_content("bk_1")
        self.requests.clear()
        with self.assertRaises(DeliveryError) as exc:
            backend.read_learning_state("bk_1")
        self.assertEqual(exc.exception.code, "learning_state_build")
        self.assertEqual(self.requests, [])

    def test_build_config_rejects_bad_fields_hashes_and_versions(self):
        valid = deepcopy(self.config["learningStateReadBuild"])
        for bad in ({**valid, "token": "not-a-real-secret"}, {**valid, "patchSha256": "wrong"},
                    {**valid, "baseCommit": "wrong"}):
            self.config["learningStateReadBuild"] = bad
            with self.assertRaises(DeliveryError):
                self.backend()
        self.config["learningStateReadBuild"] = {**valid, "baseCommit": "0" * 40}
        with self.assertRaises(DeliveryError):
            self.read()
        self.assertEqual(self.requests, [])

    def test_404_and_server_errors_never_fallback_or_post(self):
        for status in (404, 409, 500):
            self.status = status
            with self.assertRaises(DeliveryError) as exc:
                self.read()
            self.assertEqual(exc.exception.code, "learning_state_unavailable")
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(all(r["method"] == "GET" and r["path"].endswith("/learning-state") for r in self.requests))

    def test_old_shape_missing_schema_or_reader_scope_rejected(self):
        valid = observation()
        for value in ({"book": {"id": "bk_1"}, "progress": {}},
                      {k: v for k, v in valid.items() if k != "schema"},
                      {k: v for k, v in valid.items() if k != "readerScope"}):
            self.value = value
            with self.assertRaises(DeliveryError) as exc:
                self.read()
            self.assertEqual(exc.exception.code, "learning_state_shape")
        self.assertEqual(len(self.requests), 3)

    def test_wrong_workspace_or_book_not_associated(self):
        self.value["readerScope"]["workspaceId"] = "another"
        with self.assertRaises(DeliveryError) as exc:
            self.read()
        self.assertEqual(exc.exception.code, "learning_state_workspace")
        self.value = observation()
        self.value["bookId"] = "other"
        with self.assertRaises(DeliveryError):
            self.read()

    def authenticated(self):
        self.config.update(scopeVerification="authenticated", tokenEnv="INSPOOL_I5_TEST_TOKEN")
        self.value["readerScope"].update(actorId="configured-owner", identityKind="authenticated")
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"INSPOOL_I5_TEST_TOKEN": "synthetic-i5-boundary-token"}).start()

    def test_authenticated_profile_and_actual_reader_both_must_match(self):
        self.authenticated()
        self.assertEqual(self.read().status, 200)
        self.value["readerScope"]["actorId"] = "other"
        with self.assertRaises(DeliveryError) as exc:
            self.read()
        self.assertEqual(exc.exception.code, "learning_state_actor")
        self.value["readerScope"].update(actorId="configured-owner", identityKind="local_single_user")
        with self.assertRaises(DeliveryError):
            self.read()

    def test_authenticated_profile_failure_stops_before_state_get(self):
        self.authenticated()
        self.profile = "other"
        with self.assertRaises(DeliveryError) as exc:
            self.read()
        self.assertEqual(exc.exception.code, "owner_mismatch")
        self.assertEqual([r["path"] for r in self.requests], ["/api/auth/profile"])

    def test_reflected_token_not_returned_or_in_safe_error(self):
        self.authenticated()
        self.value["progress"]["value"]["future"] = "synthetic-i5-boundary-token"
        with self.assertRaises(DeliveryError) as exc:
            self.read()
        self.assertEqual(exc.exception.code, "learning_state_redacted")
        self.assertNotIn("synthetic-i5-boundary-token", str(exc.exception))

    def test_missing_invalid_and_changed_not_synthesized_into_empty(self):
        for status in ("missing", "unreadable", "changed", "invalid"):
            item = {"status": status, "coverage": "partial", "valueAcquired": False,
                    "diagnostics": [{"code": "example", "pointer": ""}]}
            self.value["progress"] = item
            self.assertEqual(self.read().json()["progress"], item)
        item = {"status": "invalid", "coverage": "partial", "valueAcquired": True,
                "value": {"book_id": "other", "quiz_attempts": [None, {"is_correct": "bad"}]},
                "diagnostics": [{"code": "book_identity", "pointer": "/book_id"}]}
        self.value["progress"] = item
        self.assertEqual(self.read().json()["progress"], item)

    def test_contradictory_or_old_defaulted_item_shapes_rejected(self):
        valid = deepcopy(self.value["progress"])
        for bad in ({}, {**valid, "status": "missing"}, {**valid, "status": "changed", "coverage": "complete"},
                    {**valid, "valueAcquired": False}, {**valid, "status": "unknown"},
                    {**valid, "value": {"book_id": "other"}}):
            self.value["progress"] = bad
            with self.assertRaises(DeliveryError):
                self.read()

    def test_invalid_valid_mapping_and_denied_access_shape_rejected(self):
        self.value["pageChatSessions"]["value"] = {"pg": 3}
        with self.assertRaises(DeliveryError):
            self.read()
        self.value = observation()
        self.value["contentAccess"]["permission"] = "none"
        with self.assertRaises(DeliveryError):
            self.read()

    def test_malformed_wire_and_unsafe_paths_rejected(self):
        self.value = b'{"schema":bad}'
        with self.assertRaises(DeliveryError):
            self.read()
        backend = self.backend()
        before = len(self.requests)
        for value in ("../bk_1", "bk_1?x=1", "bk_1/content"):
            with self.assertRaises(DeliveryError):
                backend.read_learning_state(value)
        for value in ("/api/books/bk_1", "/api/books/bk_1/learning-state?x=1", "/api/sessions/s/threads"):
            with self.assertRaises(DeliveryError):
                backend.read(value)
        self.assertEqual(before, len(self.requests))
