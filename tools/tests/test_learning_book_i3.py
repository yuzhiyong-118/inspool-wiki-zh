"""I3：真实 loopback HTTP 假服务、持久证据、故障与跨进程验收，无模型。"""
from __future__ import annotations

from collections import Counter
from contextlib import closing, contextmanager
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import unquote

from tools.learning_book.budget import Budget, ProcessStop, process_identity
from tools.learning_book.cli import main
from tools.learning_book.contracts import (DeliveryError, canonical, digest, load_deployment,
                                            read_json, sha256, validate_package)
from tools.learning_book.deeptutor import DeepTutor, Response, parse_book_result
from tools.learning_book.evidence_store import EvidenceStore, atomic
from tools.learning_book.production import Production

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures" / "learning_book_i3"
PYTHON = getattr(sys, "_base_executable", sys.executable)


def make_package(root, *, content=b"# Source\r\n37 milliseconds.\r\n"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "original.md").write_bytes(content)
    (root / "input.md").write_bytes(content)
    source = {"sourceId": "src-1", "sourceVersionId": "src-v1", "sha256": sha256(content),
              "path": "original.md", "metadata": {"title": "测试来源", "author": "作者一"}}
    artifact = {"inputArtifactId": "input-1", "sourceId": "src-1", "sourceVersionId": "src-v1",
                "sha256": sha256(content), "path": "input.md", "mediaType": "text/markdown",
                "extraction": {"method": "copy", "version": "1"},
                "coverage": {"status": "complete", "truncated": False}}
    value = {"schemaVersion": 1, "packageId": "pkg-1", "preparationDecision": "learn",
             "sources": [source], "inputArtifacts": [artifact], "corpusId": "corpus-1",
             "corpusVersionId": "cv-1", "learningGoal": "学习重试约定", "language": "zh", "depth": "brief"}
    (root / "prepare.json").write_bytes(canonical(value))
    return value


class FakeDT:
    def __init__(self):
        self.requests = []
        self.kbs = {}
        self.books = {}
        self.mode = "ok"
        self.index_mode = "ok"
        self.owner = "owner-1"
        self.delay = 0
        fake = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *args):
                pass
            def send(self, status, data, binary=False):
                data = data if binary else canonical(data)
                self.send_response(status)
                self.send_header("Content-Type", "application/octet-stream" if binary else "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (OSError, BrokenPipeError):
                    pass
            def do_GET(self):
                path = unquote(self.path)
                fake.requests.append(("GET", path, dict(self.headers), b""))
                if path == "/api/auth/profile":
                    return self.send(200, {"id": fake.owner})
                if path == "/api/knowledge-bases":
                    return self.send(200, [{"id": k, "name": v["name"]} for k, v in fake.kbs.items()])
                if path.startswith("/api/knowledge-bases/"):
                    tail = path[len("/api/knowledge-bases/"):]
                    kb_id, _, action = tail.partition("/")
                    if kb_id not in fake.kbs:
                        return self.send(404, {"detail": "missing"})
                    kb = fake.kbs[kb_id]
                    if action == "files":
                        return self.send(200, {"files": [{"name": n, "type": "file", "size": len(b)} for n, b in kb["files"].items()]})
                    if action.startswith("files/"):
                        name = action[len("files/"):]
                        if name not in kb["files"]:
                            return self.send(404, {})
                        return self.send(200, kb["files"][name], binary=True)
                    if action == "indexing-readiness":
                        return self.send(200, {"ready": True, "parser": {"ready": True}})
                    if action == "indexing-run":
                        run = {"task_id": kb.get("task", "old"), "state": "completed", "usable_version": "version-1",
                               "documents": {n: {"status": "completed", "source_hash": sha256(b)} for n, b in kb["files"].items()}}
                        if fake.index_mode == "failed":
                            run["state"] = "failed"
                        elif fake.index_mode == "running":
                            run["state"] = "running"
                        elif fake.index_mode == "oldhash":
                            for d in run["documents"].values():
                                d["source_hash"] = "0" * 64
                        elif fake.index_mode == "noversion":
                            run["usable_version"] = None
                        elif fake.index_mode == "oldtask":
                            run["task_id"] = "old-task"
                        return self.send(200, {"run": run})
                if path == "/api/books":
                    workspace = self.headers.get("x-deeptutor-workspace")
                    return self.send(200, {"books": [b for b in fake.books.values() if b["workspace"] == workspace], "can_create": True})
                if path.startswith('/api/books/') and '/pages/' in path:
                    book_id,page_id=path[len('/api/books/'):].split('/pages/')
                    return self.send(200,{'page':{'id':page_id,'book_id':book_id,'blocks':[{'id':'q','type':'quiz'}]}})
                if path.startswith("/api/books/") and path.endswith("/spine"):
                    return self.send(200, {"spine": {"book_id": path.split("/")[3], "chapters": []}})
                if path.startswith("/api/books/") and len(path.split("/")) == 4:
                    # 测试不允许误调此处，否则视为发生生成副作用。
                    fake.mode = "unsafe_get_invoked"
                    return self.send(500, {})
                return self.send(404, {})
            def do_POST(self):
                path = unquote(self.path)
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                fake.requests.append(("POST", path, dict(self.headers), body))
                if fake.delay:
                    time.sleep(fake.delay)
                if path.endswith("/reindex"):
                    kb = fake.kbs[path.split("/")[3]]
                    kb["task"] = "reindex-task-" + str(len(fake.requests))
                    fake.index_mode = "ok"
                    return self.send(200, {"task_id": kb["task"]})
                if path == "/api/knowledge-bases" or path.endswith("/upload"):
                    message = BytesParser(policy=default).parsebytes(
                        ("Content-Type: " + self.headers["Content-Type"] + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + body)
                    fields, files = {}, {}
                    for part in message.iter_parts():
                        if part.get_filename():
                            files[part.get_filename()] = part.get_payload(decode=True)
                        else:
                            fields[part.get_param("name", header="content-disposition")] = part.get_payload(decode=True).decode()
                    if path == "/api/knowledge-bases":
                        kb_id = "account:kb:" + fields["name"]
                        fake.kbs[kb_id] = {"name": fields["name"], "files": {}}
                        return self.send(200, {"name": fields["name"], "id": kb_id, "files": [], "task_id": None})
                    kb_id = path.split("/")[3]
                    kb = fake.kbs[kb_id]
                    kb["files"].update(files)
                    kb["task"] = "upload-task-" + str(len(fake.requests))
                    return self.send(200, {"task_id": kb["task"], "files": list(files)})
                value = json.loads(body)
                if path == "/api/books":
                    if any(not row.get("label") or not row.get("kind") for row in value["source_refs"]):
                        return self.send(500, {"detail": "TopicSource requires label and kind"})
                    book_id = "bk-" + str(len(fake.books) + 1)
                    book = {"id": book_id, "title": "同名书", "revision": 1, "status": "draft",
                            "workspace": self.headers.get("x-deeptutor-workspace"),
                            "knowledge_bases": value["knowledge_bases"]}
                    fake.books[book_id] = book
                    response = {"book": book, "proposal": {"title": "提案"}}
                    if fake.mode == "echo_auth":
                        response["echo"] = self.headers.get("Authorization", "")
                    if fake.mode == "drop":
                        self.close_connection = True
                        self.connection.shutdown(2)
                        return
                    if fake.mode == "committed500":
                        return self.send(500, {"detail": "committed then failed"})
                    if fake.mode == "missing_identity":
                        return self.send(200, {"proposal": {"title": "提案"}})
                    return self.send(200, response)
                if path == '/api/books/regenerate-block':
                    book=fake.books[value['book_id']]
                    if book['revision']!=value['expected_revision']:
                        return self.send(409,{'detail':'revision conflict'})
                    book['revision']+=1
                    return self.send(200,{'block':{'id':value['block_id'],'type':'quiz','status':'ready',
                        'payload':{'questions':[{'answer':'C'}]}},'book_revision':book['revision']})
                if path in ("/api/books/confirm-proposal", "/api/books/confirm-spine"):
                    book = fake.books[value["book_id"]]
                    if fake.mode == "race409":
                        book["revision"] += 1
                    if book["revision"] != value["expected_revision"]:
                        return self.send(409, {"detail": "revision conflict"})
                    book["revision"] += 1
                    if fake.mode == "invalid_after_revision":
                        return self.send(400, {"detail": "invalid after mutation"})
                    if path.endswith("confirm-proposal"):
                        book["status"] = "spine_ready"
                        return self.send(200, {"book": book, "spine": {"book_id": book["id"], "chapters": [{"id": "ch-1"}]},
                                               "book_revision": book["revision"]})
                    pages = [{"id": "overview", "book_id": book["id"], "status": "ready"},
                             {"id": "main", "book_id": book["id"], "status": "pending"}]
                    return self.send(200, {"pages": pages, "book_revision": book["revision"]})
                return self.send(404, {})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    def writes(self, path=None):
        return len([r for r in self.requests if r[0] == "POST" and (path is None or r[1] == path)])


class DeliveryTests(unittest.TestCase):
    evidence_dir = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package_root = self.root / "package"
        self.manifest = make_package(self.package_root)
        self.fake = FakeDT()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.fake.close)
        self.config_path = self.root / "deployment.json"
        self.config_path.write_bytes(canonical({"deploymentId": "dep-1", "ownerId": "owner-1", "workspaceId": "",
            "scopeVerification": "configured_single_user", "baseUrl": self.fake.url, "kbOwnerId": "owner-1",
            "ragProvider": "llamaindex", "indexWaitSeconds": 0.2}))
        self.config = load_deployment(self.config_path)
        self.store = EvidenceStore(self.root / "state")
        self.backend = DeepTutor(self.config)
        self.ledger = self.root / "usage.sqlite3"
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("CREATE TABLE llm_calls(call_id TEXT,usage_json TEXT)")
            db.execute("INSERT INTO llm_calls VALUES (?,?)", ("baseline", "{}"))
        self.context = {"contextId": "test-allowance", "scope": self.config["scope"], "ledger": str(self.ledger),
                        "baselineCallIds": ["baseline"], "pauseAt": 800, "limit": 1000,
                        "pollSeconds": 0.03, "maxSilentSeconds": 10,
                        "localEmbedding": {"provider": "local_fake", "metering": "not_available"}}
        self.stops = []
        self.budget = Budget(self.context, self.config["scope"], stop=lambda: self.stops.append("stopped"))
        self.app = Production(self.store, self.backend, self.budget)
        self.traces = []

    def test_I6_reconcile_proves_no_remote_write_before_allowing_retry(self):
        app = Production(self.store, self.backend)
        initial = app.publish_learning_inputs(self.package(), "no-remote-write")
        self.assertEqual(initial["status"], "failed")
        self.assertEqual(self.store.receipt("no-remote-write")["status"], "failed")
        self.store.save_receipt("no-remote-write", "uncertain")
        before = self.fake.writes()
        result = self.app.reconcile_request("no-remote-write")
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["errors"][0]["code"], "no_remote_write")
        self.assertEqual(self.fake.writes(), before)
        retry = self.app.publish_learning_inputs(self.package(), "no-remote-write-retry",
                                                 retry_of="no-remote-write")
        self.assertEqual(retry["status"], "succeeded", retry)

        other_store = EvidenceStore(self.root / "state-existing-remote")
        other_app = Production(other_store, self.backend)
        existing = other_app.publish_learning_inputs(self.package(), "existing-remote-not-claimed")
        self.assertEqual(existing["status"], "failed")
        other_store.save_receipt("existing-remote-not-claimed", "uncertain")
        before = self.fake.writes()
        result = other_app.reconcile_request("existing-remote-not-claimed")
        self.assertEqual(result["status"], "uncertain", result)
        self.assertEqual(self.fake.writes(), before)

    def test_I6_recover_completed_upload_by_recorded_reindex_without_reupload(self):
        make_package(self.root / "package")
        package = validate_package(self.root / "package/prepare.json")
        self.fake.index_mode = "failed"
        result = self.app.publish_learning_inputs(package, "recover-upload")
        self.assertEqual(result["status"], "uncertain")
        original_upload = self.store.response("recover-upload", "kb-upload")[1]
        self.context = {**self.context, "contextId": "same-allowance-recovery"}
        self.app.budget = Budget(self.context, self.config["scope"], stop=lambda: None)
        recovered = self.app.recover_inputs("recover-upload")
        self.assertEqual(recovered["status"], "succeeded")
        receipt = self.store.receipt("recover-upload")
        self.assertNotEqual(receipt["taskId"], receipt["uploadTaskId"])
        self.assertEqual(self.store.response("recover-upload", "kb-upload")[1], original_upload)
        writes = self.fake.writes()
        self.assertEqual(self.app.recover_inputs("recover-upload")["status"], "succeeded")
        self.assertEqual(self.app.reconcile_request("recover-upload")["status"], "succeeded")
        self.assertEqual(self.fake.writes(), writes)
        self.assertEqual(sum(path.endswith("/upload") for method, path, *_ in self.fake.requests if method == "POST"), 1)
        self.assertEqual(sum(path.endswith("/reindex") for method, path, *_ in self.fake.requests if method == "POST"), 1)

    def test_I6_recover_refuses_active_index_or_changed_original_bytes(self):
        make_package(self.root / "package")
        package = validate_package(self.root / "package/prepare.json")
        self.fake.index_mode = "failed"
        self.app.publish_learning_inputs(package, "recover-guard")
        writes = self.fake.writes()
        self.fake.index_mode = "running"
        with self.assertRaises(DeliveryError) as active:
            self.app.recover_inputs("recover-guard")
        self.assertEqual(active.exception.code, "index_pending")
        self.assertEqual(self.fake.writes(), writes)
        self.fake.index_mode = "failed"
        kb = next(iter(self.fake.kbs.values()))
        name = next(iter(kb["files"]))
        kb["files"][name] = b"changed original"
        with self.assertRaises(DeliveryError) as drift:
            self.app.recover_inputs("recover-guard")
        self.assertEqual(drift.exception.code, "remote_bytes")
        self.assertEqual(self.fake.writes(), writes)

    def trace(self, label, *request_ids):
        self.traces.append({"label": label, "httpPostCount": self.fake.writes(),
                            "bookPostCount": self.fake.writes("/api/books"),
                            "requests": self.request_projection(request_ids)})

    def request_projection(self, request_ids):
        result = []
        for request_id in request_ids:
            request = self.store.request(request_id)
            receipt = self.store.receipt(request_id)
            stages = []
            for path in sorted((self.store.request_dir(request_id) / "stages").glob("*")):
                response = self.store.response(request_id, path.name)
                stages.append({"stage": path.name, "dispatching": (path / "dispatching.json").exists(),
                               "response": response[0] if response else None})
            result.append({"requestId": request_id, "requestDigest": request["digest"],
                           "status": receipt["status"], "bookId": receipt.get("bookId"),
                           "errors": receipt.get("errors", []), "stages": stages})
        return result

    def tearDown(self):
        if self.evidence_dir is not None:
            requests = list(self.store.requests())
            value = {"kind": "sanitized_test_observation", "test": self.id(),
                     "http": [{"method": method, "path": path, "bodySha256": sha256(body)}
                              for method, path, headers, body in self.fake.requests],
                     "requests": self.request_projection([r["requestId"] for r in requests]),
                     "checkpoints": self.traces}
            Path(self.evidence_dir).mkdir(parents=True, exist_ok=True)
            (Path(self.evidence_dir) / (self._testMethodName + ".json")).write_bytes(canonical(value))
            if self._testMethodName == "test_A11_three_wrappers_and_lazy_pages":
                examples = Path(self.evidence_dir).parent / "examples"
                examples.mkdir(parents=True, exist_ok=True)
                files = {"corpus-request.json": self.store.request("publish-1"),
                         "corpus-receipt.json": self.store.receipt("publish-1"),
                         "production-request.json": self.store.request("create-1"),
                         "production-receipt.json": self.store.receipt("create-1"),
                         "activity-mapping.json": self.store.mapping("activity-1"),
                         "lazy-pages-receipt.json": self.store.receipt("spine-1")}
                for name, record in files.items():
                    data = canonical(record).decode().replace(str(self.root).replace("\\", "\\\\"), "$TEST_ROOT")
                    (examples / name).write_text(data, encoding="utf-8")

    def package(self):
        return validate_package(self.package_root / "prepare.json")

    def update(self, value=None):
        (self.package_root / "prepare.json").write_bytes(canonical(value or self.manifest))

    def publish(self):
        result = self.app.publish_learning_inputs(self.package(), "publish-1")
        self.assertEqual("succeeded", result["status"], result)
        return result

    def create(self):
        self.publish()
        result = self.app.create_activity("publish-1", "create-1", "activity-1", "学习目标")
        self.assertEqual("succeeded", result["status"], result)
        return result

    def add_usage(self, call_id, tokens, *, estimated=False):
        usage = {} if tokens is None else {"total_tokens": tokens, "estimated": estimated}
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("INSERT INTO llm_calls VALUES (?,?)", (call_id, json.dumps(usage)))

    def test_A01_identity_move_distinct_sources_versions(self):
        original = self.package()
        moved = self.root / "moved"
        shutil.copytree(self.package_root, moved)
        self.assertEqual(original.corpus, validate_package(moved / "prepare.json").corpus)
        source = dict(self.manifest["sources"][0], sourceId="source-other", sourceVersionId="v-other",
                      metadata={"author": "另一作者"})
        artifact = dict(self.manifest["inputArtifacts"][0], inputArtifactId="input-other", sourceId="source-other", sourceVersionId="v-other")
        self.manifest["sources"].append(source)
        self.manifest["inputArtifacts"].append(artifact)
        self.update()
        self.assertEqual(2, len(self.package().inputs))
        self.publish()
        self.manifest["sources"][0]["metadata"]["author"] = "偷偷修改作者"
        self.update()
        with self.assertRaises(DeliveryError) as error:
            self.app.publish_learning_inputs(self.package(), "publish-new")
        self.assertEqual("corpus_version_conflict", error.exception.code)

    def test_A02_reject_before_remote_write(self):
        for mode in ("source_missing", "source_hash", "input_hash", "escape", "encoding", "partial", "duplicate", "source_limit"):
            with self.subTest(mode=mode):
                self.manifest = make_package(self.package_root)
                if mode == "source_missing":
                    (self.package_root / "original.md").unlink()
                elif mode == "source_hash":
                    self.manifest["sources"][0]["sha256"] = "0" * 64
                elif mode == "input_hash":
                    self.manifest["inputArtifacts"][0]["sha256"] = "0" * 64
                elif mode == "escape":
                    self.manifest["inputArtifacts"][0]["path"] = "../outside.md"
                elif mode == "encoding":
                    (self.package_root / "input.md").write_bytes(b"\xff\xfe")
                    self.manifest["inputArtifacts"][0]["sha256"] = sha256(b"\xff\xfe")
                elif mode == "partial":
                    self.manifest["inputArtifacts"][0]["coverage"]["truncated"] = True
                elif mode == "source_limit":
                    self.manifest["inputArtifacts"] = [dict(self.manifest["inputArtifacts"][0], inputArtifactId="input-" + str(i)) for i in range(17)]
                else:
                    self.manifest["inputArtifacts"].append(self.manifest["inputArtifacts"][0])
                self.update()
                with self.assertRaises((DeliveryError, OSError)):
                    self.package()
                self.assertEqual(0, self.fake.writes())

    def test_A02_symlink_escape(self):
        target = self.root / "outside.md"
        target.write_bytes((self.package_root / "input.md").read_bytes())
        link = self.package_root / "linked.md"
        try:
            link.symlink_to(target)
        except OSError:
            if os.name != "nt":
                raise
            # Windows junction 不要求符号链接特权，覆盖相同的目录解析逃逸。
            directory = self.root / "outside-dir"
            directory.mkdir()
            (directory / "input.md").write_bytes(target.read_bytes())
            link = self.package_root / "linked-dir"
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "New-Item -ItemType Junction -Path " + quote(link) + " -Target " + quote(directory) + " | Out-Null"],
                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(0, result.returncode, "创建测试 junction 失败")
            self.manifest["inputArtifacts"][0]["path"] = "linked-dir/input.md"
        else:
            self.manifest["inputArtifacts"][0]["path"] = "linked.md"
        self.update()
        with self.assertRaises(DeliveryError):
            self.package()
        self.assertEqual(0, self.fake.writes())

    def test_A03_upload_fixed_bytes(self):
        package = self.package()
        expected = dict(package.inputs)
        (self.package_root / "input.md").write_bytes(b"replaced after validation")
        self.assertEqual("succeeded", self.app.publish_learning_inputs(package, "publish-1")["status"])
        self.assertEqual(expected, next(iter(self.fake.kbs.values()))["files"])

    def test_A03_known_context_limits_remain_unknown_coverage(self):
        self.manifest = make_package(self.package_root, content=("来源正文" * 1200).encode("utf-8"))
        self.create()
        corpus = self.store.receipt("publish-1")
        book = self.store.receipt("create-1")
        self.assertTrue(corpus["exceedsKnownFileExcerptLimit"])
        self.assertEqual(4000, corpus["knownUpstreamLimits"]["fileExcerptCharacters"])
        self.assertEqual("unknown", book["effectiveContextCoverage"])
        self.assertEqual(4800, corpus["corpus"]["inputArtifacts"][0]["utf8CharacterCount"])

    def test_A04_dedup_conflict_activity_and_uncertain_reservations(self):
        result = self.create()
        writes = self.fake.writes()
        self.assertEqual(result, self.app.create_activity("publish-1", "create-1", "activity-1", "学习目标"))
        self.assertEqual(writes, self.fake.writes())
        for request_id, intent in (("create-1", "different"), ("create-new", "学习目标")):
            with self.assertRaises(DeliveryError):
                self.app.create_activity("publish-1", request_id, "activity-1", intent)
        self.fake.mode = "drop"
        result = self.app.create_activity("publish-1", "create-2", "activity-2", "学习目标")
        self.assertEqual("uncertain", result["status"])
        with self.assertRaises(DeliveryError):
            self.app.create_activity("publish-1", "create-3", "activity-2", "学习目标")
        self.assertEqual(writes + 1, self.fake.writes())

    def test_A06_prepared_resume_and_saved_response_recovery(self):
        self.publish()
        class Crash(BaseException):
            pass
        def run_fault(point, request_id, activity_id):
            def fault(stage):
                if stage == point:
                    raise Crash()
            app = Production(self.store, self.backend, self.budget, fault=fault)
            with self.assertRaises(Crash):
                app.create_activity("publish-1", request_id, activity_id, "学习目标")
        run_fault("prepared", "c-prepared", "a-prepared")
        self.assertEqual(0, self.fake.writes("/api/books"))
        self.assertEqual("succeeded", self.app.create_activity("publish-1", "c-prepared", "a-prepared", "学习目标")["status"])
        for point in ("response_saved", "before_mapping"):
            with self.subTest(point=point):
                # 故障模拟发生在 HTTP 成功后的本地边界；新预算对象模拟重启。
                budget = Budget(dict(self.context, contextId="allow-" + point), self.config["scope"], stop=lambda: None)
                self.budget = budget
                self.app = Production(self.store, self.backend, budget)
                before = self.fake.writes("/api/books")
                run_fault(point, "c-" + point, "a-" + point)
                read_app = Production(self.store, self.backend)
                result = read_app.reconcile_request("c-" + point)
                self.assertEqual("succeeded", result["status"], result)
                self.assertEqual(before + 1, self.fake.writes("/api/books"))
                self.assertEqual(result["bookId"], self.store.mapping("a-" + point)["bookId"])

    def test_A06_dispatch_marker_never_reposts(self):
        self.publish()
        class Crash(BaseException):
            pass
        app = Production(self.store, self.backend, self.budget,
                         fault=lambda point: (_ for _ in ()).throw(Crash()) if point == "dispatching" else None)
        with self.assertRaises(Crash):
            app.create_activity("publish-1", "c-dispatch", "a-dispatch", "学习目标")
        self.assertEqual(0, self.fake.writes("/api/books"))
        result = Production(self.store, self.backend).create_activity("publish-1", "c-dispatch", "a-dispatch", "学习目标")
        self.assertEqual("uncertain", result["status"])
        self.assertEqual(0, self.fake.writes("/api/books"))

    def test_A07_server_committed_drop_and_500(self):
        self.publish()
        for mode in ("drop", "committed500", "missing_identity"):
            with self.subTest(mode=mode):
                budget = Budget(dict(self.context, contextId=mode), self.config["scope"], stop=lambda: None)
                app = Production(self.store, self.backend, budget)
                self.fake.mode = mode
                before = self.fake.writes("/api/books")
                result = app.create_activity("publish-1", "c-" + mode, "a-" + mode, "学习目标")
                self.assertEqual("uncertain", result["status"])
                self.assertEqual("uncertain", app.create_activity("publish-1", "c-" + mode, "a-" + mode, "学习目标")["status"])
                result = Production(self.store, self.backend).reconcile_request("c-" + mode, candidate_book_id=list(self.fake.books)[-1])
                self.assertEqual("uncertain", result["status"])
                self.assertEqual(before + 1, self.fake.writes("/api/books"))
                self.assertIsNone(self.store.mapping("a-" + mode))

    def test_A08_reuse_drift_and_different_bytes(self):
        self.publish()
        before = self.fake.writes()
        result = self.app.publish_learning_inputs(self.package(), "publish-reuse")
        self.assertTrue(result["reusedCorpus"])
        self.assertEqual(before, self.fake.writes())
        kb = next(iter(self.fake.kbs.values()))
        kb["files"]["unknown.md"] = b"extra"
        result = self.app.create_activity("publish-1", "create-1", "activity-1", "学习目标")
        self.assertEqual("uncertain", result["status"])
        self.assertEqual(before, self.fake.writes())
        del kb["files"]["unknown.md"]
        kb["files"][next(iter(kb["files"]))] = b"different"
        self.assertEqual("partial", self.app.reconcile_request("publish-1")["status"])
        self.assertEqual(before, self.fake.writes())

    def test_A09_ready_does_not_prove_indexing(self):
        for mode in ("failed", "oldhash", "noversion", "oldtask"):
            with self.subTest(mode=mode):
                self.fake.index_mode = mode
                self.manifest["corpusVersionId"] = "cv-" + mode
                self.update()
                result = self.app.publish_learning_inputs(self.package(), "p-" + mode)
                self.assertEqual("uncertain", result["status"])
                with self.assertRaises(DeliveryError):
                    self.app.create_activity("p-" + mode, "c-" + mode, "a-" + mode, "目标")
                budget = Budget(dict(self.context, contextId="next-" + mode), self.config["scope"], stop=lambda: None)
                self.app = Production(self.store, self.backend, budget)

    def test_A10_raw_byte_hash_not_preview(self):
        self.publish()
        self.assertTrue(any("/files/" in path for method, path, _, _ in self.fake.requests))
        self.assertFalse(any("preview" in path for method, path, _, _ in self.fake.requests))
        actual = next(iter(next(iter(self.fake.kbs.values()))["files"].values()))
        self.assertNotEqual(sha256(actual), sha256(actual.replace(b"\r\n", b"\n")))

    def test_A11_three_wrappers_and_lazy_pages(self):
        result = self.create()
        self.assertEqual(1, result["revision"])
        result = self.app.confirm_proposal("activity-1", "proposal-1", None, 1)
        self.assertEqual("succeeded", result["status"], result)
        result = self.app.confirm_spine("activity-1", "spine-1", None, 2)
        self.assertEqual("succeeded", result["status"], result)
        receipt = self.store.receipt("spine-1")
        self.assertEqual(["ready", "pending"], [p["status"] for p in receipt["pages"]])
        self.assertEqual("not_evaluated", receipt["deliveryReadiness"])
        last = [r for r in self.fake.requests if r[1] == "/api/books/confirm-spine"][0]
        self.assertIs(json.loads(last[3])["auto_compile"], False)
        for operation, value in (("create", {}), ("confirm-proposal", {"book": {"id": "b", "revision": 2}, "spine": {}}),
                                 ("confirm-spine", {"pages": [], "book_revision": 3})):
            with self.assertRaises(DeliveryError):
                parse_book_result(operation, Response(200, canonical(value), "application/json"), "b")

    def test_A12_stale_revision_and_400_after_mutation(self):
        self.create()
        before = self.fake.writes()
        result = self.app.confirm_proposal("activity-1", "bad-token", None, 99)
        self.assertEqual("failed", result["status"])
        self.assertEqual(before, self.fake.writes())
        self.fake.mode = "invalid_after_revision"
        result = self.app.confirm_proposal("activity-1", "invalid-proposal", {"invalid": True}, 1)
        self.assertEqual("uncertain", result["status"])
        self.assertEqual(2, self.fake.books["bk-1"]["revision"])
        self.app.reconcile_request("invalid-proposal")
        self.assertEqual(before + 1, self.fake.writes())
        with self.assertRaises(DeliveryError):
            self.app.confirm_proposal("activity-1", "new-id", None, 2)

    def test_A12_real_http_revision_conflict_remains_failed(self):
        self.create()
        self.fake.mode = "race409"
        result = self.app.confirm_proposal("activity-1", "race-token", None, 1)
        self.assertEqual("failed", result["status"])
        self.assertFalse(self.budget.blocked.is_set())
        before = self.fake.writes()
        self.assertEqual("failed", self.app.reconcile_request("race-token")["status"])
        self.assertEqual(before, self.fake.writes())

    def test_A13_scope_general_kb_and_owner(self):
        self.create()
        for method, path, headers, body in self.fake.requests:
            normalized = {k.lower(): v for k, v in headers.items()}
            if "/knowledge-bases" in path:
                self.assertNotIn("x-deeptutor-workspace", normalized)
            elif path.startswith("/api/books"):
                self.assertEqual("", normalized.get("x-deeptutor-workspace"))
        for field in ("deploymentId", "workspaceId", "ownerId"):
            config = dict(self.config)
            config["scope"] = dict(self.config["scope"], **{field: "wrong"})
            with self.assertRaises(DeliveryError):
                Production(self.store, DeepTutor(config)).reconcile_request("create-1")
        config = dict(self.config, tokenEnv="I3_TEST_ONLY_TOKEN")
        config["scope"] = dict(self.config["scope"], scopeVerification="authenticated")
        old = os.environ.get("I3_TEST_ONLY_TOKEN")
        os.environ["I3_TEST_ONLY_TOKEN"] = "test-secret-not-a-real-key"
        try:
            fake_backend = DeepTutor(config)
            fake_backend.verify_scope()
            self.fake.owner = "other-owner"
            with self.assertRaises(DeliveryError):
                fake_backend.verify_scope()
        finally:
            if old is None:
                del os.environ["I3_TEST_ONLY_TOKEN"]
            else:
                os.environ["I3_TEST_ONLY_TOKEN"] = old

    def test_A13_account_corpus_reused_across_book_workspaces(self):
        self.publish()
        config_json = read_json(self.config_path)
        config_json["workspaceId"] = "workspace-two"
        self.config_path.write_bytes(canonical(config_json))
        config = load_deployment(self.config_path)
        self.assertEqual(self.config["scope"]["kbScopeDigest"], config["scope"]["kbScopeDigest"])
        context = dict(self.context, contextId="workspace-allowance", scope=config["scope"])
        app = Production(self.store, DeepTutor(config), Budget(context, config["scope"], stop=lambda: None))
        before = self.fake.writes()
        result = app.publish_learning_inputs(self.package(), "publish-other-workspace")
        self.assertTrue(result["reusedCorpus"])
        self.assertEqual(before, self.fake.writes())
        self.assertEqual("succeeded", app.inspect_receipt("publish-1")["status"])
        result = app.create_activity("publish-1", "create-in-workspace", "activity-two", "目标")
        self.assertEqual("succeeded", result["status"])
        self.assertEqual("workspace-two", self.fake.books[result["bookId"]]["workspace"])

    def test_credentials_not_persisted_when_backend_echoes_header(self):
        self.publish()
        secret = "synthetic-test-value-never-a-real-key"
        config = dict(self.config, tokenEnv="I3_REDACTION_TEST_TOKEN")
        previous = os.environ.get("I3_REDACTION_TEST_TOKEN")
        os.environ["I3_REDACTION_TEST_TOKEN"] = secret
        try:
            self.fake.mode = "echo_auth"
            app = Production(self.store, DeepTutor(config), self.budget)
            self.assertEqual("succeeded", app.create_activity("publish-1", "echo", "echo-activity", "目标")["status"])
            meta, body = self.store.response("echo", "book")
            self.assertTrue(meta["redacted"])
            self.assertNotEqual(meta["wireSha256"], meta["sha256"])
            self.assertNotIn(secret.encode(), body)
            for path in self.store.root.rglob("*"):
                if path.is_file():
                    self.assertNotIn(secret.encode(), path.read_bytes())
        finally:
            if previous is None:
                del os.environ["I3_REDACTION_TEST_TOKEN"]
            else:
                os.environ["I3_REDACTION_TEST_TOKEN"] = previous

    def test_A14_local_show_zero_budget_and_no_resume_get(self):
        self.create()
        app = Production(self.store, self.backend)
        before = len(self.fake.requests)
        self.assertEqual("succeeded", app.inspect_receipt("create-1")["status"])
        self.assertEqual(before, len(self.fake.requests))
        self.assertEqual("succeeded", app.reconcile_request("create-1")["status"])
        with self.assertRaises(DeliveryError):
            self.backend.read("/api/books/bk-1")
        self.assertNotEqual("unsafe_get_invoked", self.fake.mode)
        result = app.create_activity("publish-1", "no-allowance", "activity-no-budget", "学习目标")
        self.assertEqual("failed", result["status"])
        self.assertEqual(1, self.fake.writes("/api/books"))

    def test_A15_cumulative_usage_and_missing_fail_closed(self):
        self.create()
        self.add_usage("call-1", 600)
        self.add_usage("estimated-1", 150, estimated=True)
        position = self.budget.position()
        self.assertEqual((750, 600, 150), (position["totalTokens"], position["reportedTokens"], position["estimatedTokens"]))
        self.assertEqual("succeeded", self.app.confirm_proposal("activity-1", "proposal-1", None, 1)["status"])
        self.add_usage("call-2", 51)
        before = self.fake.writes()
        result = self.app.confirm_spine("activity-1", "spine-1", None, 2)
        self.assertEqual("failed", result["status"])
        self.assertEqual(before, self.fake.writes())
        self.add_usage("missing", None)
        self.assertEqual(1, self.budget.position()["missingRows"])
        with self.assertRaises(DeliveryError):
            self.budget.check()

    def test_A15_monitor_independent_and_stop_failure_visible(self):
        self.publish()
        self.fake.delay = 0.25
        def add():
            time.sleep(0.08)
            self.add_usage("inflight", 900)
        thread = threading.Thread(target=add)
        thread.start()
        result = self.app.create_activity("publish-1", "inflight", "a-inflight", "学习目标")
        thread.join()
        self.assertEqual("uncertain", result["status"])
        self.assertEqual([], self.stops)
        self.assertIn({"event": "generation_blocked"}, self.budget.events)
        def fail():
            raise RuntimeError("fake failure")
        budget = Budget(dict(self.context, contextId="stop-failure"), self.config["scope"], stop=fail)
        budget.trip("test")
        self.assertIn({"event": "stop_failed"}, budget.events)
        with self.assertRaises(DeliveryError):
            budget.check()

    def test_A15_stale_and_missing_ledger_stop_monitor(self):
        for mode in ("stale", "missing"):
            with self.subTest(mode=mode):
                stopped = []
                budget = Budget(dict(self.context, maxSilentSeconds=.1), self.config["scope"], stop=lambda: stopped.append(True))
                with self.assertRaises(DeliveryError):
                    with budget.watch():
                        if mode == "missing":
                            # 模拟配置指向的账本不可读；不与 Windows 短时读句柄争抢 rename。
                            budget.ledger = self.root / "missing.sqlite3"
                        budget.blocked.wait(.4)
                self.assertEqual([True], stopped)
                self.assertTrue(budget.blocked.is_set())

    def test_A16_index_rebuild_remote_missing_and_mapping_restore(self):
        self.create()
        (self.store.root / "index.json").write_text("broken")
        self.app.inspect_receipt("create-1", rebuild_index=True)
        self.assertEqual("succeeded", read_json(self.store.root / "index.json")["create-1"]["status"])
        before = self.fake.writes()
        mapping_path = self.store.root / "activities" / (digest("activity-1") + ".json")
        original = mapping_path.read_bytes()
        mapping_path.unlink()
        self.app.create_activity("publish-1", "create-1", "activity-1", "学习目标")
        self.assertEqual(original, mapping_path.read_bytes())
        self.fake.books.clear()
        self.assertEqual("partial", self.app.reconcile_request("create-1")["status"])
        self.assertEqual("missing", self.store.receipt("create-1")["remotePresence"])
        self.assertEqual(before, self.fake.writes())

    def test_A06_actual_process_exit_boundaries(self):
        self.publish()
        budget_path = self.root / "budget.json"
        budget_path.write_bytes(canonical(self.context))
        code = """
import os,sys
from tools.learning_book.contracts import load_deployment,read_json
from tools.learning_book.budget import Budget
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.evidence_store import EvidenceStore
from tools.learning_book.production import Production
config=load_deployment(sys.argv[1]); budget=Budget(read_json(sys.argv[2]),config['scope'],stop=lambda:None)
point=sys.argv[4]
app=Production(EvidenceStore(sys.argv[3]),DeepTutor(config),budget,fault=lambda p:os._exit(72) if p==point else None)
app.create_activity('publish-1','child-'+point,'child-activity-'+point,'学习目标')
"""
        for point in ("prepared", "dispatching", "response_saved", "before_mapping"):
            with self.subTest(point=point):
                result = subprocess.run([PYTHON, "-B", "-c", code, str(self.config_path), str(budget_path),
                                         str(self.store.root), point], cwd=REPO, capture_output=True, timeout=15)
                self.assertEqual(72, result.returncode, result.stderr)
                request_id, activity_id = "child-" + point, "child-activity-" + point
                self.trace("after_process_exit_" + point, request_id)
                before = self.fake.writes("/api/books")
                if point == "prepared":
                    self.assertEqual("prepared", self.app.reconcile_request(request_id)["status"])
                    self.assertEqual("succeeded", self.app.create_activity("publish-1", request_id, activity_id, "学习目标")["status"])
                    self.assertEqual(before + 1, self.fake.writes("/api/books"))
                elif point == "dispatching":
                    self.assertEqual("uncertain", self.app.reconcile_request(request_id)["status"])
                    self.assertEqual(before, self.fake.writes("/api/books"))
                else:
                    result = Production(self.store, self.backend).reconcile_request(request_id)
                    self.assertEqual("succeeded", result["status"], result)
                    self.assertEqual(before, self.fake.writes("/api/books"))
                self.trace("after_recovery_" + point, request_id)
        self.assertEqual(3, self.fake.writes("/api/books"))

    def test_A05_competing_production_processes_only_one_post(self):
        self.publish()
        self.fake.delay = .5
        budget_path = self.root / "budget.json"
        budget_path.write_bytes(canonical(self.context))
        code = """
import json,sys
from tools.learning_book.contracts import load_deployment,read_json
from tools.learning_book.budget import Budget
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.evidence_store import EvidenceStore
from tools.learning_book.production import Production
c=load_deployment(sys.argv[1]); b=Budget(read_json(sys.argv[2]),c['scope'],stop=lambda:None)
app=Production(EvidenceStore(sys.argv[3]),DeepTutor(c),b)
print(json.dumps(app.create_activity('publish-1','first-process','first-activity','目标')))
"""
        process = subprocess.Popen([PYTHON, "-B", "-c", code, str(self.config_path), str(budget_path), str(self.store.root)],
            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            deadline = time.monotonic() + 5
            while not self.fake.writes("/api/books") and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(1, self.fake.writes("/api/books"))
            with self.assertRaises(DeliveryError) as error:
                self.app.create_activity("publish-1", "second-process", "second-activity", "目标")
            self.assertEqual("busy", error.exception.status)
            output, errors = process.communicate(timeout=10)
            self.assertEqual(0, process.returncode, errors)
            self.assertEqual("succeeded", json.loads(output)["status"])
            self.assertEqual(1, self.fake.writes("/api/books"))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(5)
            process.stdout.close()
            process.stderr.close()

    def test_A15_persisted_budget_cannot_reset_baseline_or_ledger(self):
        self.create()
        self.add_usage("call", 700)
        self.assertEqual("succeeded", self.app.confirm_proposal("activity-1", "proposal", None, 1)["status"])
        position_path = self.store.root / "budgets" / (digest(self.context["contextId"]) + ".position.json")
        self.assertEqual(700, read_json(position_path)["totalTokens"])
        # 即使新 CLI 进程读取，也不能把旧账本已计量行删掉后重新获得额度。
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("DELETE FROM llm_calls WHERE call_id='call'")
        new_budget = Budget(self.context, self.config["scope"], stop=lambda: None)
        result = Production(self.store, self.backend, new_budget).confirm_spine("activity-1", "spine", None, 2)
        self.assertEqual("failed", result["status"])
        before = self.fake.writes()
        changed = dict(self.context, baselineCallIds=[])
        app = Production(self.store, self.backend, Budget(changed, self.config["scope"], stop=lambda: None))
        # 使用另一个活动也不能改同一个 contextId 的基线。
        result = app.create_activity("publish-1", "reset-budget", "reset-activity", "学习目标")
        self.assertEqual("uncertain", result["status"])
        self.assertEqual(before, self.fake.writes())

    def test_A06_local_mapping_disk_failure_preserves_remote_fact(self):
        self.publish()
        original = self.store.map_activity
        def fail(*args, **kwargs):
            raise OSError("simulated disk failure")
        self.store.map_activity = fail
        result = self.app.create_activity("publish-1", "disk-failure", "disk-activity", "学习目标")
        self.assertEqual("uncertain", result["status"])
        self.assertEqual(1, self.fake.writes("/api/books"))
        self.store.map_activity = original
        self.assertEqual("succeeded", Production(self.store, self.backend).reconcile_request("disk-failure")["status"])
        self.assertEqual(1, self.fake.writes("/api/books"))

    def test_A04_uncertain_corpus_cannot_be_bypassed(self):
        self.fake.index_mode = "oldtask"
        result = self.app.publish_learning_inputs(self.package(), "publish-1")
        self.assertEqual("uncertain", result["status"])
        before = self.fake.writes()
        with self.assertRaises(DeliveryError):
            self.app.publish_learning_inputs(self.package(), "publish-2")
        self.app.reconcile_request("publish-1")
        self.assertEqual(before, self.fake.writes())

    def test_A04_failed_request_needs_explicit_link_and_new_id(self):
        self.publish()
        app = Production(self.store, self.backend)
        self.assertEqual("failed", app.create_activity("publish-1", "no-budget", "retry-activity", "学习目标")["status"])
        self.assertEqual("failed", self.app.create_activity("publish-1", "no-budget", "retry-activity", "学习目标")["status"])
        self.assertEqual(0, self.fake.writes("/api/books"))
        with self.assertRaises(DeliveryError):
            self.app.create_activity("publish-1", "new-no-link", "retry-activity", "学习目标")
        result = self.app.create_activity("publish-1", "new-linked", "retry-activity", "学习目标", retry_of="no-budget")
        self.assertEqual("succeeded", result["status"])

    def test_missing_original_blocks_confirmations(self):
        self.create()
        before = self.fake.writes()
        (self.package_root / "original.md").unlink()
        self.assertEqual("failed", self.app.confirm_proposal("activity-1", "proposal-1", None, 1)["status"])
        self.assertEqual(before, self.fake.writes())

    def test_cli_json_and_return_codes(self):
        result = subprocess.run([PYTHON, "-B", "-m", "tools.learning_book.cli", "validate", "--package",
                                 str(self.package_root / "prepare.json")], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("succeeded", json.loads(result.stdout)["status"])
        result = subprocess.run([PYTHON, "-B", "-m", "tools.learning_book.cli", "nonsense"],
                                cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(2, result.returncode)
        self.assertEqual("invalid", json.loads(result.stdout)["status"])
        self.assertNotIn("Traceback", result.stderr)

    def test_formal_roots_rejected(self):
        for root in (REPO, REPO / "wiki" / "state", REPO / "raw" / "state", REPO / ".learning-validation" / "state"):
            with self.assertRaises(DeliveryError):
                EvidenceStore(root)


class ProcessTests(unittest.TestCase):
    def test_A05_cross_process_lock_and_crash_release(self):
        with tempfile.TemporaryDirectory() as temp:
            code = "from tools.learning_book.evidence_store import EvidenceStore; import sys,time; s=EvidenceStore(sys.argv[1]);\nwith s.lock({}):\n print('locked',flush=True); time.sleep(60)"
            process = subprocess.Popen([PYTHON, "-B", "-u", "-c", code, temp], cwd=REPO,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual("locked", process.stdout.readline().strip())
                store = EvidenceStore(temp)
                with self.assertRaises(DeliveryError) as error:
                    with store.lock({}):
                        pass
                self.assertEqual("busy", error.exception.status)
                process.kill()
                process.wait(5)
                with store.lock({}):
                    pass
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(5)
                process.stdout.close()
                process.stderr.close()

    def test_A15_owned_process_stop_and_identity_rejection(self):
        executable = getattr(sys, "_base_executable", sys.executable)
        process = subprocess.Popen([executable, "-B", "-c", "import time; time.sleep(60)"],
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            identity = process_identity(process.pid)
            receipt = {**identity, "ownership": "dedicated_single_worker"}
            ProcessStop(receipt).verify()  # Windows 可有自身的系统 conhost。
            with self.assertRaises(DeliveryError):
                ProcessStop(dict(receipt, startedToken="wrong"))()
            self.assertIsNone(process.poll())
            control = ProcessStop(receipt)
            control.bind_endpoint("http://127.0.0.1:9")
            with self.assertRaises(DeliveryError) as error:
                control.verify()
            self.assertEqual("process_endpoint", error.exception.code)
            ProcessStop(receipt)()
            process.wait(5)
            self.assertIsNotNone(process.returncode)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(5)

    def test_A15_budget_monitor_blocks_generation_without_stopping_http_process(self):
        executable = getattr(sys, "_base_executable", sys.executable)
        code = """
import json,sys,time
from tools.tests.test_learning_book_i3 import FakeDT
fake=FakeDT()
fake.delay=.5
print(json.dumps({'url':fake.url}),flush=True)
time.sleep(60)
"""
        process = subprocess.Popen([executable, "-B", "-u", "-c", code], cwd=REPO,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            url = json.loads(process.stdout.readline())["url"]
            identity = {**process_identity(process.pid), "ownership": "dedicated_single_worker"}
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                make_package(root / "package")
                config_path = root / "deployment.json"
                config_path.write_bytes(canonical({"deploymentId": "stop-test", "ownerId": "owner", "workspaceId": "",
                    "scopeVerification": "configured_single_user", "baseUrl": url, "kbOwnerId": "owner", "ragProvider": "llamaindex"}))
                config = load_deployment(config_path)
                ledger = root / "usage.sqlite3"
                with closing(sqlite3.connect(ledger)) as db, db:
                    db.execute("CREATE TABLE llm_calls(call_id TEXT,usage_json TEXT)")
                context = {"contextId": "stop-actual-process", "scope": config["scope"], "ledger": str(ledger),
                    "baselineCallIds": [], "pauseAt": 80, "limit": 100, "pollSeconds": .03,
                    "maxSilentSeconds": 10, "stopProcess": identity}
                budget = Budget(context, config["scope"])
                app = Production(EvidenceStore(root / "state"), DeepTutor(config), budget)
                self.assertEqual("succeeded", app.publish_learning_inputs(validate_package(root / "package/prepare.json"), "pub")["status"])
                def add_usage():
                    time.sleep(.15)
                    with closing(sqlite3.connect(ledger)) as db, db:
                        db.execute("INSERT INTO llm_calls VALUES (?,?)", ("crossed", '{"total_tokens":90}'))
                monitor = threading.Thread(target=add_usage)
                monitor.start()
                result = app.create_activity("pub", "create", "activity", "学习目标")
                monitor.join(5)
                self.assertEqual("uncertain", result["status"], result)
                self.assertIsNone(process.returncode)
                self.assertIn({"event": "generation_blocked"}, budget.events)
                self.assertIsNone(app.store.mapping("activity"))
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(5)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
