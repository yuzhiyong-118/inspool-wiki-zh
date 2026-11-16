"""I4：loopback HTTP、真实文件／进程、上游响应反例；零模型。"""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import unquote

from tools.learning_book.baseline import Baseline
from tools.learning_book.cli import main
from tools.learning_book.content import (CAPABILITY, RULE, UPSTREAM, dependencies,
                                         markdown_dependencies, project, resource_path)
from tools.learning_book.contracts import (DeliveryError, canonical, digest, load_deployment,
                                          read_json, sha256, validate_package)
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.evidence_store import EvidenceStore, atomic
from tools.tests.test_learning_book_i3 import make_package

FIXTURES = Path(__file__).parent / "fixtures/learning_book_i4"
PYTHON = getattr(sys, "_base_executable", sys.executable)


def content():
    def block(key, kind, payload):
        return {"id": key, "type": kind, "status": "ready", "error": "", "title": key,
                "params": {}, "payload": payload, "source_anchors": [], "metadata": {}, "created_at": 1, "updated_at": 1}
    question = {"question_id": "q_1", "question": "首个等待时间？", "question_type": "choice",
                "options": {"B": "74ms", "A": "37ms"}, "correct_answer": "A", "explanation": "来源为 37ms。"}
    pages = [{"id": "pg_1", "book_id": "bk_1", "chapter_id": "ch_1", "title": "第一节", "order": 1,
              "status": "ready", "error": "", "blocks": [block("blk_text", "text", {"body": "首次等待 37ms。"}),
                  block("blk_q1", "quiz", {"questions": [deepcopy(question)]})],
              "links": [], "parent_page_id": "", "created_at": 1, "updated_at": 1},
             {"id": "pg_2", "book_id": "bk_1", "chapter_id": "ch_2", "title": "第二节", "order": 2,
              "status": "ready", "error": "", "blocks": [block("blk_q2", "quiz", {"questions": [deepcopy(question)]})],
              "links": [], "parent_page_id": "", "created_at": 1, "updated_at": 1}]
    return {"schema": CAPABILITY, "book": {"id": "bk_1", "revision": 7, "status": "ready", "title": "测试书",
                "page_count": 2, "knowledge_bases": ["account:kb:test"], "metadata": {}, "created_at": 1, "updated_at": 1},
            "spine": {"book_id": "bk_1", "version": 1, "updated_at": 1, "chapters": [
                {"id": "ch_1", "page_ids": ["pg_1"], "order": 1}, {"id": "ch_2", "page_ids": ["pg_2"], "order": 2}]},
            "pages": pages, "generation": {"status": "ready", "working": False},
            "pageEnumeration": {"mode": "strict", "fileCount": 2, "returnedCount": 2, "errors": []}}


class ContentServer:
    def __init__(self):
        self.value, self.status, self.reads = content(), 200, 0
        self.requests, self.inputs, self.resources = [], {}, {}
        self.on_content = lambda _: None
        self.owner = "owner"
        self.task, self.version = "task", "usable-v1"
        fake = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def send(self, status, data, mime="application/json"):
                body = data if isinstance(data, bytes) else canonical(data)
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                path = unquote(self.path)
                fake.requests.append({"method": "GET", "path": path, "workspace": self.headers.get("x-deeptutor-workspace")})
                if path == "/api/auth/profile":
                    return self.send(200, {"id": fake.owner})
                if path.endswith("/content"):
                    fake.reads += 1
                    fake.on_content(fake.reads)
                    return self.send(fake.status, fake.value)
                if path.endswith("/files"):
                    return self.send(200, {"files": [{"name": name, "type": "file"} for name in fake.inputs]})
                if "/files/" in path and path.startswith("/api/knowledge-bases/"):
                    name = path.rsplit("/", 1)[1]
                    return self.send(200, fake.inputs[name], "application/octet-stream") if name in fake.inputs else self.send(404, {})
                if path.endswith("/indexing-run"):
                    return self.send(200, {"run": {"task_id": fake.task, "state": "completed", "usable_version": fake.version,
                        "documents": {name: {"status": "completed", "source_hash": sha256(data)} for name, data in fake.inputs.items()}}})
                if path.startswith("/files/outputs/"):
                    status, data, mime = fake.resources.get(path, (404, b"", "image/png"))
                    return self.send(status, data, mime)
                return self.send(500, {"unsafe_or_unknown_get": True})
            def do_POST(self):
                fake.requests.append({"method": "POST", "path": self.path})
                return self.send(405, {})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)


class BaselineTests(unittest.TestCase):
    evidence_dir = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.fake = ContentServer()
        self.addCleanup(self.fake.close)
        make_package(self.root / "package")
        self.package = validate_package(self.root / "package/prepare.json")
        self.config_path = self.root / "deployment.json"
        self.config_path.write_bytes(canonical({"deploymentId": "dep", "ownerId": "owner", "workspaceId": "workspace-1",
            "kbOwnerId": "owner", "scopeVerification": "configured_single_user", "baseUrl": self.fake.url, "ragProvider": "llamaindex",
            "contentReadBuild": {"baseCommit": UPSTREAM, "rendererCommit": UPSTREAM, "patchSha256": "1" * 64, "wheelSha256": "2" * 64}}))
        self.config = load_deployment(self.config_path)
        self.store = EvidenceStore(self.root / "state")
        self.backend = DeepTutor(self.config)
        self.app = Baseline(self.store, self.backend)
        self.seed()

    def seed(self, activity="activity", book_id="bk_1", request_id="create"):
        if not (self.store.request_dir("inputs") / "request.json").exists():
            corpus = self.package.corpus
            self.store.prepare("inputs", {"operation": "publish-inputs", "scope": self.config["scope"], "corpus": corpus})
            self.store.save_receipt("inputs", "succeeded", corpus=corpus, corpusDigest=digest(corpus), coverage="complete",
                                    kbRef="account:kb:test", taskId="task", usableVersion="usable-v1")
            atomic(self.store.request_dir("inputs") / "locators.json", canonical(self.package.locators))
            for name, data in self.package.inputs.items():
                atomic(self.store.request_dir("inputs") / "inputs" / name, data)
            self.fake.inputs = dict(self.package.inputs)
        self.store.prepare(request_id, {"operation": "create", "scope": self.config["scope"],
                                       "activityId": activity, "corpusRequestId": "inputs"})
        self.store.map_activity(activity, self.config["scope"], book_id, request_id)
        self.store.save_receipt(request_id, "succeeded", bookId=book_id, activityId=activity)

    def capture(self, capture="capture", snapshot="snapshot", **kw):
        return self.app.capture_baseline("activity", capture, snapshot, "pre_learning",
                                        {"actorId": "preparer", "statement": "已暂停协作编辑，正在采集学习前内容。"}, **kw)

    def review(self, review_id="review", snapshot="snapshot"):
        manifest = self.app.load_snapshot(snapshot)
        path = self.app._snapshot_path(snapshot)
        capture = read_json(path / "capture.json")
        return {"schema": "baseline-quality-review/1", "reviewId": review_id, "snapshotId": snapshot, "activityId": "activity",
                "identity": manifest["identity"], "actor": {"actorId": "test-preparer", "role": "external_preparer_agent"},
                "decision": "pass", "sourceFidelityChecked": True, "findings": [],
                "unsupportedAcknowledged": capture["structure"]["unsupported"],
                "sourceEvidence": [{"evidenceId": "e1", "sourceId": "src-1", "sourceVersionId": "src-v1",
                                    "sha256": self.package.corpus["sources"][0]["sha256"],
                                    "locator": "original.md#L2", "checkedClaims": "测试来源明确 37 milliseconds。"}],
                "questionChecks": [{"pageId": q["pageId"], "blockId": q["blockId"], "questionId": q["questionId"],
                                    "decision": "pass", "evidenceId": "e1", "explanation": "测试选择题 A 对应 37ms。"}
                                   for q in capture["structure"]["questions"] if q["assessmentSupport"] == "supported"]}

    def bind(self):
        self.assertEqual(self.capture()["captureStatus"], "stable_complete")
        result = self.app.record_baseline_review("activity", "snapshot", "review", self.review())
        self.assertTrue(result["baselineBound"], result)
        return result

    def tearDown(self):
        self.assertFalse(any(r["method"] != "GET" or (r["path"].startswith("/api/books/") and not r["path"].endswith("/content"))
                             for r in self.fake.requests), self.fake.requests)
        if self.evidence_dir:
            target = Path(self.evidence_dir) / "observations"
            target.mkdir(parents=True, exist_ok=True)
            results = []
            for kind in ("captures", "checks", "reviews"):
                for p in (self.store.root / kind).glob("*/result.json"):
                    row = read_json(p)
                    results.append({k: row[k] for k in ("operation", "status", "captureStatus", "structuralBlocking", "baselineBound", "gateReasons", "binding") if k in row})
            (target / (self._testMethodName + ".json")).write_bytes(canonical({"test": self.id(), "http": self.fake.requests,
                "contentReadCount": self.fake.reads, "results": results, "fixture": "synthetic_contract_unless_named_replay"}))
            if self._testMethodName == "test_B15_aba_and_retrospective_never_submission_proof":
                examples = Path(self.evidence_dir) / "examples"
                snapshot = self.app._snapshot_path("snapshot")
                for path in snapshot.rglob("*"):
                    if path.is_file():
                        target = examples / "snapshot" / path.relative_to(snapshot)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(path.read_bytes())
                examples.mkdir(parents=True, exist_ok=True)
                (examples / "quality-review.json").write_bytes(canonical(self.review()))
                (examples / "baseline-binding.json").write_bytes(self.app._binding_path("activity").read_bytes())
                (examples / "check.json").write_bytes((self.app._path("checks", "aba") / "result.json").read_bytes())
                (examples / "capture-result.json").write_bytes((self.app._path("captures", "capture") / "result.json").read_bytes())

    def test_B02_missing_capability_never_falls_back(self):
        for index, value in enumerate(({}, {**content(), "schema": "old"}, {k: v for k, v in content().items() if k != "pageEnumeration"})):
            self.fake.value = value
            result = self.capture(f"cap-{index}", f"snap-{index}")
            self.assertEqual(result["status"], "failed")
        self.fake.status = 404
        self.assertEqual(self.capture("not-found", "snap-nf")["status"], "failed")
        self.assertEqual(self.fake.reads, 4)

    def test_B04_projection_preserves_semantics_orders_and_nested_timestamps(self):
        original = content()
        baseline = digest(project(original, "bk_1")[0])
        for mutation in (lambda v: v["pages"][0]["blocks"][1]["payload"]["questions"][0].update(correct_answer="B"),
                         lambda v: v["spine"]["chapters"].reverse(),
                         lambda v: v["book"].update(futureSemantic={"x": 1}),
                         lambda v: v["pages"][0]["blocks"][0]["payload"].update(updated_at="semantic"),
                         lambda v: v["pages"][0]["blocks"][1]["payload"]["questions"][0].update(options={"A": "37ms", "B": "74ms"})):
            changed = deepcopy(original)
            mutation(changed)
            self.assertNotEqual(baseline, digest(project(changed, "bk_1")[0]))
        changed = deepcopy(original)
        changed["book"].update(updated_at=100, revision=9, metadata={"page_chat_sessions": {"x": "session"}, "compile_started_at": 10})
        changed["pages"][0]["updated_at"] = 100
        changed["progress"] = {"attempts": [1]}
        changed["spine"]["version"] = 100
        self.assertEqual(baseline, digest(project(changed, "bk_1")[0]))

    def test_B05_all_pages_scoped_question_ids_and_duplicates(self):
        self.capture()
        cap = read_json(self.app._snapshot_path("snapshot") / "capture.json")
        self.assertEqual(cap["structure"]["supportedChoiceCount"], 2)
        self.assertFalse(cap["structure"]["blocking"])
        self.fake.value["pages"][0]["blocks"][1]["payload"]["questions"] *= 2
        self.capture("duplicate", "duplicate")
        cap = read_json(self.app._snapshot_path("duplicate") / "capture.json")
        self.assertTrue(cap["structure"]["blocking"])
        self.assertEqual(cap["structure"]["supportedChoiceCount"], 1)

    def test_B06_failure_placeholder_invalid_choice_and_unsupported_kept(self):
        value = content()
        q = value["pages"][0]["blocks"][1]["payload"]["questions"][0]
        q.update(question="[Generation failed] topic", correct_answer="N/A", question_type="written")
        value["pages"][1]["blocks"][0]["payload"]["questions"][0]["correct_answer"] = "A/C"
        self.fake.value = value
        self.capture()
        manifest = self.app.load_snapshot("snapshot")
        cap = read_json(self.app._snapshot_path("snapshot") / "capture.json")
        codes = {f["code"] for f in cap["structure"]["findings"]}
        self.assertTrue({"generation_failure", "invalid_choice"} <= codes)
        self.assertEqual(len(cap["structure"]["unsupported"]), 1)
        stored = read_json(self.app._snapshot_path("snapshot") / "content.json")
        self.assertEqual(stored["pages"][0]["blocks"][1]["payload"]["questions"][0], q)
        result = self.app.record_baseline_review("activity", "snapshot", "review", self.review())
        self.assertFalse(result["baselineBound"])
        self.assertIn("structural_gate", result["gateReasons"])
        self.assertEqual(manifest["identity"], self.app.load_snapshot("snapshot")["identity"])


    def add_resource(self, uri="/files/outputs/picture.png"):
        self.fake.value["pages"][0]["blocks"][0]["payload"]["body"] += f"\n![图]({uri})"
        self.fake.resources["/files/outputs/picture.png"] = (200, b"\x89PNG\r\n\x1a\nfixture-bytes", "image/png")

    def test_B08_resource_same_uri_changed_bytes_changes_binding(self):
        self.add_resource()
        self.bind()
        self.fake.resources["/files/outputs/picture.png"] = (200, b"\x89PNG\r\n\x1a\nnew-bytes", "image/png")
        result = self.app.check_baseline("activity", "snapshot", "check")
        self.assertEqual(result["binding"], "unknown")
        self.assertEqual(result["currentIdentity"]["contentDigest"], result["baselineIdentity"]["contentDigest"])
        self.assertNotEqual(result["currentIdentity"]["resourceManifestDigest"], result["baselineIdentity"]["resourceManifestDigest"])

    def test_B08_missing_redirect_bad_mime_and_oversize_resources_partial(self):
        self.add_resource()
        for index, response in enumerate(((404, b"", "image/png"), (302, b"", "image/png"),
                     (200, b"<script>anything</script>", "image/png"), (200, b"\x89PNG\r\n\x1a\n" + b"x" * (8*1024*1024), "image/png"))):
            self.fake.resources["/files/outputs/picture.png"] = response
            self.assertEqual(self.capture(str(index), str(index))["captureStatus"], "partial")

    def test_B08_external_escape_and_active_resources_zero_requests(self):
        for index, uri in enumerate(("https://example.invalid/a.png", "/api/books/bk_1", "/files/outputs/../a.png",
                                     "/files/outputs/%252e%252e/a.png", "/files/outputs/a.svg", "//example.invalid/a.png")):
            self.fake.value = content()
            self.add_resource(uri)
            self.assertEqual(self.capture(str(index), str(index))["captureStatus"], "partial")
        self.assertFalse(any(r["path"].startswith("/files/outputs/") for r in self.fake.requests))

    def test_B08_general_resources_scope_unproven(self):
        config = deepcopy(self.config)
        config["scope"]["workspaceId"] = ""
        app = Baseline(self.store, DeepTutor(config))
        self.add_resource()
        projection = project(self.fake.value, "bk_1")[0]
        resources, assets = app._resources(projection)
        self.assertEqual(resources["status"], "partial")
        self.assertFalse(assets)
        self.assertFalse(self.fake.requests)

    def test_B08_markdown_reference_and_conservative_unknown_syntax(self):
        refs, issues = markdown_dependencies('![a][img]\n\n[img]: /files/outputs/a.png\n[普通来源](https://example.invalid)')
        self.assertEqual(refs, ["/files/outputs/a.png"])
        self.assertFalse(issues)
        self.assertTrue(markdown_dependencies('![a](url(with-parentheses).png)')[1])
        self.assertTrue(markdown_dependencies('<img src="secret">')[1])
        self.assertEqual(markdown_dependencies('![img]\n\n[img]: /files/outputs/a.png')[0], ["/files/outputs/a.png"])
        self.assertFalse(markdown_dependencies('```python\n![code](/files/outputs/not-real.png)\n```')[0])
        self.assertFalse(markdown_dependencies('`![code](/files/outputs/not-real.png)`')[0])
        self.assertFalse(markdown_dependencies(r'\![literal](/files/outputs/not-real.png)')[0])

    def test_B09_retry_independent_pairs_and_finite_inconsistency(self):
        def once(number):
            if number == 2:
                self.fake.value["book"]["title"] = "changed"
        self.fake.on_content = once
        self.assertEqual(self.capture()["captureStatus"], "stable_complete")
        self.assertEqual(self.fake.reads, 4)
        self.fake.on_content = lambda number: self.fake.value["book"].update(title=str(number))
        self.assertEqual(self.capture("unstable", "unstable")["captureStatus"], "inconsistent")
        self.assertEqual(self.fake.reads, 10)

    def test_B10_scope_unknown_production_and_source_drift(self):
        config = deepcopy(self.config)
        config["scope"]["ownerId"] = "other"
        other = Baseline(self.store, DeepTutor(config))
        with self.assertRaises(DeliveryError):
            other.capture_baseline("activity", "wrong", "wrong", "retrospective")
        self.store.save_receipt("create", "uncertain", bookId="bk_1")
        with self.assertRaises(DeliveryError):
            self.capture("unknown", "unknown")
        self.store.save_receipt("create", "succeeded", bookId="bk_1")
        self.fake.inputs[next(iter(self.fake.inputs))] = b"changed"
        self.assertEqual(self.capture("drift", "drift")["captureStatus"], "partial")

    def test_B10_missing_source_preserves_content_fact_separately(self):
        self.bind()
        (self.root / "package/original.md").unlink()
        result = self.app.check_baseline("activity", "snapshot", "missing-source")
        self.assertTrue(result["contentConsistent"])
        self.assertEqual(result["sourceAvailability"], "partial")
        self.assertEqual(result["binding"], "unknown")

    def test_B11_crash_each_boundary_restarts_whole_pair(self):
        for boundary in ("raw", "round", "content", "assets", "manifest", "complete", "published"):
            self.fake.value = content()
            self.add_resource()
            cap, snap = "cap-" + boundary, "snap-" + boundary
            def fault(step):
                if step == boundary:
                    raise RuntimeError("simulated crash")
            self.app.fault = fault
            before = self.fake.reads
            with self.assertRaises(RuntimeError):
                self.capture(cap, snap)
            published = self.app._snapshot_path(snap) / "complete.json"
            self.assertEqual(published.exists(), boundary == "published")
            self.app.fault = lambda _: None
            reads = self.fake.reads
            self.assertEqual(self.capture(cap, snap)["status"], "succeeded")
            self.assertEqual(self.fake.reads - reads, 0 if boundary == "published" else 2)
            self.assertGreater(self.fake.reads, before)

    def test_B11_tampered_snapshot_or_asset_rejected(self):
        self.add_resource()
        self.capture()
        directory = self.app._snapshot_path("snapshot")
        next((directory / "assets").glob("*.bin")).write_bytes(b"changed")
        with self.assertRaises(DeliveryError):
            self.app.load_snapshot("snapshot")
        result = self.app.check_baseline("activity", "snapshot", "tampered")
        self.assertEqual(result["binding"], "unknown")

    def test_B11_missing_marker_and_manifest_path_escape_rejected(self):
        self.capture()
        directory = self.app._snapshot_path("snapshot")
        marker = (directory / "complete.json").read_bytes()
        (directory / "complete.json").unlink()
        self.assertEqual(self.app.check_baseline("activity", "snapshot", "no-marker")["binding"], "unknown")
        (directory / "complete.json").write_bytes(marker)
        manifest = read_json(directory / "manifest.json")
        manifest["files"]["../outside.json"] = "0" * 64
        (directory / "manifest.json").write_bytes(canonical(manifest))
        (directory / "complete.json").write_bytes(canonical({"manifestDigest": digest(manifest)}))
        with self.assertRaises(DeliveryError) as error:
            self.app.load_snapshot("snapshot")
        self.assertEqual(error.exception.code, "snapshot_path")

    def test_B06_empty_missing_ids_unknown_types_and_nonready(self):
        value = content()
        value["pages"][0]["blocks"][0]["payload"]["body"] = ""
        q = value["pages"][0]["blocks"][1]["payload"]["questions"][0]
        q.pop("question_id")
        value["pages"][1]["blocks"][0]["payload"]["questions"][0]["question_type"] = "future_type"
        _, _, check = project(value, "bk_1")
        self.assertEqual(check["supportedChoiceCount"], 0)
        self.assertTrue({"empty_content", "question_identity", "invalid_choice"} <= {f["code"] for f in check["findings"]})
        self.fake.value["pages"][0]["status"] = "partial"
        self.assertEqual(self.capture()["captureStatus"], "partial")

    def test_B02_malformed_content_is_retained_as_failed_read(self):
        self.fake.value["pages"][0]["blocks"] = "invalid-shape"
        row = self.capture()
        self.assertEqual(row["captureStatus"], "failed")
        self.assertTrue(list(self.app._path("captures", "capture").glob("a/*/r1/response.bin")))

    def test_B12_ids_immutable_reuse_and_no_production_namespace(self):
        result = self.capture()
        self.assertEqual(result, self.capture())
        self.assertEqual(self.fake.reads, 2)
        with self.assertRaises(DeliveryError):
            self.capture("capture", "different-snapshot")
        with self.assertRaises(DeliveryError):
            self.capture("another-capture", "snapshot")
        self.assertEqual(len(list(self.store.requests())), 2)

    def test_B12_actual_process_single_writer(self):
        code = "from tools.learning_book.evidence_store import EvidenceStore; from tools.learning_book.contracts import DeliveryError; import sys; s=EvidenceStore(sys.argv[1]);\ntry:\n with s.lock({}): print('acquired')\nexcept DeliveryError as e: print(e.status)"
        with self.store.lock(self.config["scope"]):
            child = subprocess.run([PYTHON, "-B", "-c", code, str(self.store.root)], text=True, capture_output=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "busy")

    def test_B11_actual_process_exit_and_recovery(self):
        declaration = {"actorId": "preparer", "statement": "已暂停协作编辑，正在采集学习前内容。"}
        code = "from tools.learning_book.baseline import Baseline; from tools.learning_book.contracts import load_deployment; from tools.learning_book.deeptutor import DeepTutor; from tools.learning_book.evidence_store import EvidenceStore; import sys,os,json; b=Baseline(EvidenceStore(sys.argv[1]),DeepTutor(load_deployment(sys.argv[2])),fault=lambda step:os._exit(47) if step==sys.argv[3] else None); b.capture_baseline('activity',sys.argv[4],sys.argv[4],'pre_learning',json.loads(sys.argv[5]))"
        for step in ("raw", "round", "content", "manifest", "complete", "published"):
            key = "process-" + step
            child = subprocess.run([PYTHON, "-B", "-c", code, str(self.store.root), str(self.config_path), step, key,
                                    json.dumps(declaration)], capture_output=True, text=True, timeout=20)
            self.assertEqual(child.returncode, 47, child.stderr)
            before = self.fake.reads
            result = self.capture(key, key)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(self.fake.reads - before, 0 if step == "published" else 2)

    def test_B08_resource_changes_between_reads_exhausts_three_pairs(self):
        self.add_resource()
        def change(number):
            self.fake.resources["/files/outputs/picture.png"] = (200, b"\x89PNG\r\n\x1a\n" + str(number).encode(), "image/png")
        self.fake.on_content = change
        self.assertEqual(self.capture()["captureStatus"], "inconsistent")
        self.assertEqual(self.fake.reads, 6)

    def test_B10_remote_index_version_and_book_corpus_reference(self):
        self.fake.version = "new-index-version"
        self.assertEqual(self.capture()["captureStatus"], "partial")
        self.fake.version = "usable-v1"
        self.fake.value["book"]["knowledge_bases"] = ["account:kb:other"]
        self.capture("wrong-kb", "wrong-kb")
        row = self.app.record_baseline_review("activity", "wrong-kb", "wrong-kb-review", self.review("wrong-kb-review", "wrong-kb"))
        self.assertIn("structural_gate", row["gateReasons"])

    def test_B14_binding_crash_preserves_committed_fact_after_drift(self):
        self.capture()
        def fault(step):
            if step == "binding":
                raise RuntimeError("crash after binding")
        self.app.fault = fault
        with self.assertRaises(RuntimeError):
            self.app.record_baseline_review("activity", "snapshot", "review", self.review())
        self.app.fault = lambda _: None
        self.fake.value["book"]["title"] = "changed after bind"
        row = self.app.record_baseline_review("activity", "snapshot", "review", self.review())
        self.assertTrue(row["baselineBound"])
        self.assertFalse(row["gatePassed"])
        self.assertEqual(row["binding"], "unknown")

    def test_B16_check_and_review_cli_and_missing_build(self):
        self.capture()
        review_file = self.root / "review.json"
        review_file.write_bytes(canonical(self.review()))
        shared = ["--activity", "activity", "--snapshot-id", "snapshot", "--deployment", str(self.config_path), "--state-dir", str(self.store.root)]
        for operation, options in (("review-baseline", ["--review-id", "review", "--review-file", str(review_file)]),
                                   ("check-baseline", ["--check-id", "check"])):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main([operation, *shared, *options])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["binding"], "baseline_consistent")
        config = deepcopy(self.config)
        config.pop("contentReadBuild")
        with self.assertRaises(DeliveryError):
            Baseline(self.store, DeepTutor(config))

    def test_B13_incomplete_reviews_and_current_drift_do_not_bind(self):
        self.capture()
        variants = []
        for key in ("sourceFidelityChecked", "sourceEvidence", "identity", "questionChecks", "actor"):
            row = self.review()
            row.pop(key)
            variants.append(row)
        row = self.review()
        row["findings"] = [{"severity": "blocking", "status": "open", "description": "来源冲突"}]
        variants.append(row)
        for index, row in enumerate(variants):
            row["reviewId"] = str(index)
            result = self.app.record_baseline_review("activity", "snapshot", str(index), row)
            self.assertFalse(result["baselineBound"])
        self.fake.value["book"]["title"] = "edited after review"
        result = self.app.record_baseline_review("activity", "snapshot", "review", self.review())
        self.assertIn("current_not_consistent", result["gateReasons"])
        self.assertFalse(self.app._binding_path("activity").exists())

    def test_B14_first_binding_and_no_drift_hiding_by_new_snapshot(self):
        result = self.bind()
        self.assertEqual(result, self.app.record_baseline_review("activity", "snapshot", "review", self.review()))
        self.fake.value["book"]["title"] = "new content"
        self.capture("new", "new")
        review = self.review("new-review", "new")
        result = self.app.record_baseline_review("activity", "new", "new-review", review)
        self.assertIn("baseline_already_bound", result["gateReasons"])
        self.assertEqual(read_json(self.app._binding_path("activity"))["snapshotId"], "snapshot")

    def test_B15_aba_and_retrospective_never_submission_proof(self):
        self.bind()
        self.fake.value["book"]["title"] = "temporarily edited"
        self.fake.value = content()
        result = self.app.check_baseline("activity", "snapshot", "aba")
        self.assertEqual(result["binding"], "baseline_consistent")
        self.assertEqual(result["submissionContent"], "unknown")
        self.assertEqual(result["assurance"], "cooperative")
        result = self.app.capture_baseline("activity", "retro", "retro", "retrospective")
        self.assertEqual(result["captureStatus"], "stable_complete")
        cap = read_json(self.app._snapshot_path("retro") / "capture.json")
        self.assertIsNone(cap["declaration"])
        self.assertNotIn("verified_at_submission", json.dumps(result))

    def test_B16_json_cli_no_budget_and_config_build_keeps_i3_scope(self):
        config_without = read_json(self.config_path)
        config_without.pop("contentReadBuild")
        other = self.root / "other.json"
        other.write_bytes(canonical(config_without))
        self.assertEqual(load_deployment(other)["scope"], self.config["scope"])
        declaration = self.root / "freeze.json"
        declaration.write_bytes(canonical({"actorId": "test", "statement": "协作冻结"}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["capture-baseline", "--activity", "activity", "--capture-id", "cli", "--snapshot-id", "cli",
                "--purpose", "pre_learning", "--declaration", str(declaration), "--deployment", str(self.config_path), "--state-dir", str(self.store.root)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["captureStatus"], "stable_complete")


if __name__ == "__main__":
    unittest.main()
