"""I5-C 选择／分页／隐私／分支及共享限额反例，实际公开路由另有 SQLite 测试。"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from tools.learning_book.conversations import ConversationReader, message_structure, public_value, select_sessions
from tools.learning_book.contracts import DeliveryError, canonical, load_deployment, sha256
from tools.learning_book.deeptutor import DeepTutor, Response
from tools.learning_book.evidence_store import EvidenceStore
from tools.learning_book.read_limits import ReadLimits


def session():
    return {"id": "s1", "session_id": "s1", "preferences": {"book_id": "bk_1", "book_page_id": "pg_1", "workspace_id": "ws"},
            "active_turns": [], "compressed_summary": "公开摘要，非原始回答", "messages": [
                {"id": 1, "session_id": "s1", "role": "user", "content": "why?", "created_at": 1.0, "parent_message_id": None, "events": [], "attachments": []},
                {"id": 2, "session_id": "s1", "role": "assistant", "content": "answer", "parent_message_id": 1,
                 "events": [{"type": "result", "content": "preview"}], "attachments": [], "created_at": 2.0,
                 "trace": {"turn_id": "t1", "total": 2, "last_seq": 5, "truncated": True}}]}


def mapping(value=None):
    return {"status": "valid", "coverage": "complete", "valueAcquired": True, "value": {"pg_1": "s1"} if value is None else value}


class Backend:
    def __init__(self, limits):
        self.scope = {"deploymentId": "dep", "ownerId": "owner", "workspaceId": "ws", "scopeVerification": "configured_single_user"}
        self.read_limits = limits
        self.detail, self.requests = session(), []
        self.events = [{"type": "result", "content": str(seq), "seq": seq, "session_id": "s1", "turn_id": "t1"} for seq in (2, 5)]
        self.on_read = lambda path: None
        self.event_transform = lambda value: value
        self.status, self.redacted = 200, False
    def read(self, path):
        self.read_limits.take("requests")
        self.requests.append(path)
        self.on_read(path)
        if "/events?" in path:
            query = parse_qs(urlsplit(path).query)
            after, limit = int(query["after_seq"][0]), int(query["limit"][0])
            rows = [deepcopy(e) for e in self.events if e["seq"] > after][:limit]
            end = rows[-1]["seq"] if rows else after
            last = self.events[-1]["seq"] if self.events else 0
            complete = end >= last
            value = self.event_transform({"session_id": "s1", "message_id": 2, "turn_id": "t1", "events": rows,
                "total": len(self.events), "last_seq": last, "next_seq": None if complete else end, "complete": complete})
        else:
            value = deepcopy(self.detail)
        data = canonical(value)
        self.read_limits.take("readBytes", len(data))
        return Response(self.status, data, "application/json", sha256(data), self.redacted)


class ConversationTests(unittest.TestCase):
    evidence_dir = None
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = EvidenceStore(self.root / "state")
        self.limits = ReadLimits()
        self.backend = Backend(self.limits)
        self.reader = ConversationReader(self.store, self.backend, self.limits)
        self.directory = self.store.root / "read"

    def collect(self, *, selected=None, explicit=None, verify=True):
        value = self.reader.collect(self.directory, book_id="bk_1", mapping=selected or mapping(), explicit=explicit, page_ids={"pg_1", "pg_2"})
        return self.reader.verify_boundaries(self.directory, value) if verify else value

    def errors(self, value):
        return {e["code"] for e in value["errors"]} | {e["code"] for s in value["sessions"] for e in s["errors"]} | {
            e["code"] for s in value["sessions"] for t in s["eventTraces"] for e in t["errors"]}

    def tearDown(self):
        if self.evidence_dir:
            out = Path(self.evidence_dir) / "observations"
            out.mkdir(parents=True, exist_ok=True)
            (out / (self._testMethodName + ".json")).write_bytes(canonical({"test": self.id(), "httpPaths": self.backend.requests,
                "limits": self.limits.summary(), "artifacts": [{"name": p.relative_to(self.store.root).as_posix(), "sha256": sha256(p.read_bytes())}
                    for p in self.directory.glob("*") if p.is_file()], "fixture": "synthetic_public_session_contract"}))

    def test_C10_empty_mapping_still_partial_history_and_unknown_assistance(self):
        value = self.collect(selected=mapping({}))
        self.assertEqual(value["historyCoverage"], "partial")
        self.assertEqual(value["allHistoricalSessions"], "unknown")
        self.assertEqual(value["assistance"]["status"], "unknown")
        self.assertEqual(self.backend.requests, [])

    def test_C09_mapping_explicit_dedup_and_historical_reverse_link(self):
        explicit = {"schema": "learning-session-selection/1", "sessions": [{"sessionId": "s1", "bookId": "bk_1", "pageId": "pg_1"}] * 2}
        value = self.collect(explicit=explicit)
        self.assertEqual(value["selectedCoverage"], "complete")
        self.assertEqual(value["selection"][0]["selectionSources"], ["current_mapping", "explicit"])
        self.assertEqual(value["assistance"]["status"], "observed")
        self.directory = self.store.root / "historical"
        value = self.collect(selected=mapping({}), explicit=explicit)
        self.assertEqual(value["sessions"][0]["linkKind"], "explicit_historical")

    def test_C09_conflicting_page_selection_never_fetches(self):
        value = self.collect(selected=mapping({"pg_1": "s1", "pg_2": "s1"}))
        self.assertIn("session_page_conflict", self.errors(value))
        self.assertFalse(self.backend.requests)

    def test_C09_wrong_book_page_workspace_and_missing_workspace_no_raw_capture(self):
        for field, wrong in (("book_id", "other"), ("book_page_id", "other"), ("workspace_id", "other"), ("workspace_id", None)):
            self.backend.detail = session()
            self.backend.detail["preferences"][field] = wrong
            value = self.collect()
            self.assertIn("session_reverse_scope", self.errors(value))
            self.assertFalse(any(self.directory.glob("*.bin")))

    def test_C09_wrong_message_scope_rejected_before_raw_capture(self):
        self.backend.detail["messages"][0]["session_id"] = "private-other"
        value = self.collect()
        self.assertIn("session_reverse_scope", self.errors(value))
        self.assertFalse(any(self.directory.glob("*.bin")))

    def test_C09_404_is_diagnostic_not_empty_history(self):
        self.backend.status = 404
        value = self.collect()
        self.assertIn("public_http_unavailable", self.errors(value))
        self.assertEqual(value["selectedCoverage"], "partial")

    def test_C10_invalid_mapping_and_selection_not_silently_ignored(self):
        value = self.collect(selected={"status": "invalid", "coverage": "partial", "valueAcquired": True, "value": {"pg_1": 3}})
        self.assertIn("invalid_session_selection", self.errors(value))
        self.assertIn("mapping_not_complete", self.errors(value))
        with self.assertRaises(DeliveryError):
            self.collect(explicit={})

    def test_C11_canonical_sequence_gaps_allowed_and_preview_preserved(self):
        value = self.collect()
        trace = value["sessions"][0]["eventTraces"][0]
        self.assertEqual([e["seq"] for e in trace["events"]], [2, 5])
        self.assertEqual(trace["coverage"], "complete")
        self.assertTrue(trace["previewTrace"]["truncated"])
        self.assertEqual(trace["preview"][0]["content"], "preview")
        self.assertEqual(value["historyCoverage"], "partial")

    def large(self):
        self.backend.events = [{"type": "result", "content": str(n), "seq": n, "session_id": "s1", "turn_id": "t1"} for n in range(1, 1002)]
        self.backend.detail["messages"][1]["trace"].update(total=1001, last_seq=1001)

    def test_C11_multiple_pages_and_full_boundary_reread(self):
        self.large()
        value = self.collect()
        self.assertEqual(value["selectedCoverage"], "complete")
        self.assertEqual(len(value["sessions"][0]["eventTraces"][0]["events"]), 1001)
        self.assertEqual(self.limits.used["eventPages"], 6)
        self.assertEqual(self.limits.used["events"], 2002)

    def test_C11_duplicate_out_of_order_and_conflicting_seq_partial(self):
        self.backend.events[1]["seq"] = 2
        self.backend.detail["messages"][1]["trace"]["last_seq"] = 2
        value = self.collect()
        self.assertIn("event_sequence_or_identity", self.errors(value))
        self.assertEqual(value["selectedCoverage"], "partial")

    def test_C11_bad_cursor_complete_and_statistics_partial(self):
        self.backend.event_transform = lambda value: {**value, "complete": False, "next_seq": 0}
        self.assertIn("event_cursor_stalled_or_invalid", self.errors(self.collect()))

    def test_C11_wrong_event_turn_not_written(self):
        self.backend.event_transform = lambda value: {**value, "turn_id": "foreign-private-turn"}
        value = self.collect()
        self.assertIn("event_page_identity_or_shape", self.errors(value))
        self.assertFalse(any(b"foreign-private-turn" in p.read_bytes() for p in self.directory.glob("*")))

    def test_C11_statistics_change_between_pages_partial(self):
        self.large()
        def mutate(path):
            if "after_seq=500&" in path and len(self.backend.events) == 1001:
                self.backend.events.append({"type": "result", "content": "new", "seq": 1002, "session_id": "s1", "turn_id": "t1"})
        self.backend.on_read = mutate
        self.assertIn("event_statistics_changed", self.errors(self.collect()))

    def test_C11_event_404_and_empty_canonical_turn_are_distinct(self):
        self.backend.events = []
        self.backend.detail["messages"][1]["trace"].update(total=0, last_seq=0)
        self.assertIn("preview_exceeds_canonical_total", self.errors(self.collect()))
        self.backend.detail["messages"][1]["events"] = []
        self.directory = self.store.root / "empty-canonical"
        self.assertEqual(self.collect()["sessions"][0]["eventTraces"][0]["coverage"], "complete")
        self.directory = self.store.root / "event-404"
        self.backend.on_read = lambda path: setattr(self.backend, "status", 404) if "/events?" in path else None
        self.assertIn("public_http_unavailable", self.errors(self.collect()))

    def test_C14_missing_message_time_is_coverage_gap(self):
        self.backend.detail["messages"][0].pop("created_at")
        value = self.collect()
        self.assertIn("message_time_missing_or_invalid", self.errors(value))
        self.assertEqual(value["selectedCoverage"], "partial")

    def test_C12_legacy_does_not_call_empty_complete_api(self):
        self.backend.detail["messages"][1]["trace"]["turn_id"] = None
        value = self.collect()
        self.assertIn("legacy_or_missing_canonical_turn", self.errors(value))
        self.assertFalse(any("/events?" in p for p in self.backend.requests))

    def test_C12_running_failed_annotations_and_attachments_preserved(self):
        self.backend.detail["active_turns"] = [{"id": "t1", "status": "running"}]
        self.backend.detail["messages"][0]["metadata"] = {"orphaned_failed_turn": {"error": "failed"}}
        self.backend.detail["messages"][0]["attachments"] = [{"url": "https://invalid.example/never-fetch"}]
        value = self.collect()
        self.assertTrue(value["sessions"][0]["unfinished"])
        self.assertEqual(value["sessions"][0]["attachmentCoverage"], "references_only")
        self.assertTrue(all(p.startswith("/api/sessions/") for p in self.backend.requests))

    def test_C13_private_metadata_never_saved_even_before_failure(self):
        self.backend.events[0]["metadata"] = {"model_turn": {"secret": "synthetic-private-marker"}}
        value = self.collect()
        self.assertIn("public_private_data", self.errors(value))
        self.assertFalse(any(b"synthetic-private-marker" in p.read_bytes() for p in self.directory.glob("*")))

    def test_C13_credential_redaction_and_nested_private_detail_rejected(self):
        self.backend.redacted = True
        self.assertIn("public_credential_echo", self.errors(self.collect()))
        self.backend.redacted = False
        self.backend.detail["messages"][0]["metadata"] = {"nested": [{"provider_response_state": {"x": 1}}]}
        self.assertIn("public_private_data", self.errors(self.collect()))
        self.assertFalse(any(self.directory.glob("*.bin")))

    def test_C13_plain_text_mentions_not_treated_as_private_structured_state(self):
        value = public_value(Response(200, canonical({"content": "what does model_turn mean?"}), "application/json"))
        self.assertIn("model_turn", value["content"])

    def test_C14_branch_selection_and_parent_links_kept_not_flattened(self):
        self.backend.detail["preferences"]["branch_selection"] = {"1": 3}
        self.backend.detail["messages"].append({"id": 3, "session_id": "s1", "role": "assistant", "parent_message_id": 1, "content": "alternative"})
        value = self.collect()
        self.assertEqual(value["sessions"][0]["detail"]["preferences"]["branch_selection"], {"1": 3})
        self.assertEqual(len(value["sessions"][0]["detail"]["messages"]), 3)

    def test_C14_cycles_missing_parents_duplicate_ids_and_unknown_roles_partial(self):
        messages = session()["messages"]
        messages[0]["parent_message_id"] = 2
        self.assertIn("message_parent_cycle", {e["code"] for e in message_structure(messages, "s1")})
        messages[0]["parent_message_id"] = 99
        messages.append({**messages[1], "role": "unknown"})
        codes = {e["code"] for e in message_structure(messages, "s1")}
        self.assertTrue({"parent_message_missing", "duplicate_message_identity", "unsupported_public_role"} <= codes)

    def test_C14_same_message_id_content_change_detected_by_full_reread(self):
        value = self.collect(verify=False)
        self.backend.detail["messages"][1]["content"] = "changed"
        self.reader.verify_boundaries(self.directory, value)
        self.assertFalse(value["boundaryVerified"])
        self.assertEqual(value["selectedCoverage"], "partial")

    def test_C14_event_content_change_same_counts_detected(self):
        value = self.collect(verify=False)
        self.backend.events[0]["content"] = "changed"
        self.reader.verify_boundaries(self.directory, value)
        self.assertFalse(value["boundaryVerified"])

    def test_C15_sessions_messages_pages_events_and_requests_limits_shared(self):
        for limit in ({"sessions": 1}, {"messages": 1}, {"eventPages": 1}, {"events": 1}, {"requests": 1}):
            self.limits = ReadLimits(limit)
            self.backend = Backend(self.limits)
            self.reader = ConversationReader(self.store, self.backend, self.limits)
            self.directory = self.store.root / ("limits-" + next(iter(limit)))
            selected = mapping({"pg_1": "s1", "pg_2": "s2"}) if "sessions" in limit else mapping()
            result = self.collect(selected=selected)
            self.assertEqual(result["selectedCoverage"], "partial")
            self.assertTrue(self.limits.hits)

    def test_C15_verify_uses_remaining_budget_not_reset(self):
        self.limits = ReadLimits({"events": 3})
        self.backend = Backend(self.limits)
        self.reader = ConversationReader(self.store, self.backend, self.limits)
        value = self.collect()
        self.assertEqual(value["selectedCoverage"], "partial")
        self.assertIn("events", self.limits.hits)

    def test_C03_directory_escape_rejected_before_read(self):
        with self.assertRaises(DeliveryError):
            self.reader.collect(self.root / "outside", book_id="bk_1", mapping=mapping())
        self.assertFalse(self.backend.requests)

    def test_C20_strict_http_allowlist_and_loopback_reads(self):
        fake = self.backend
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                response = fake.read(self.path)
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response.body)))
                self.end_headers()
                self.wfile.write(response.body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = {"deploymentId": "dep", "ownerId": "owner", "workspaceId": "ws", "kbOwnerId": "owner",
                      "scopeVerification": "configured_single_user", "baseUrl": f"http://127.0.0.1:{server.server_port}", "ragProvider": "llamaindex"}
            path = self.root / "deployment.json"
            path.write_bytes(canonical(config))
            backend = DeepTutor(load_deployment(path))
            reader = ConversationReader(self.store, backend)
            value = reader.collect(self.directory, book_id="bk_1", mapping=mapping())
            reader.verify_boundaries(self.directory, value)
            self.assertEqual(value["selectedCoverage"], "complete")
            for unsafe in ("/api/sessions", "/api/sessions/s1/threads", "/api/sessions/s1/ask-hint", "/api/sessions/s1/migrate-watching",
                           "/api/sessions/s1/messages/2/events?after_seq=0&limit=1001"):
                with self.assertRaises(DeliveryError):
                    backend.read(unsafe)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
