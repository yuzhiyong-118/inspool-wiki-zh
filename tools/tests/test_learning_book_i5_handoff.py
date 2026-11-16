"""I5-D/E：真实 loopback、不可变包、移动验证和故障恢复；全部资料为合成。"""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tools.learning_book.contracts import DeliveryError, canonical, read_json
from tools.learning_book.handoff import Handoff, verify_handoff
from tools.tests import test_learning_book_i4 as fixture
from tools.tests import test_learning_book_i5_records as record_fixture
from tools.tests.test_learning_book_i5_conversations import Backend as SessionBackend
from tools.learning_book.read_limits import ReadLimits

PYTHON = getattr(sys, "_base_executable", sys.executable)
CHILD = '''
import json,os,sys,time
from pathlib import Path
from tools.learning_book.contracts import DeliveryError,load_deployment,read_json
from tools.learning_book.deeptutor import DeepTutor
from tools.learning_book.evidence_store import EvidenceStore
from tools.learning_book.handoff import Handoff
config,state,key,clock,boundary,hold,release=sys.argv[1:]
fired=[]
def fault(name):
    if name==boundary and not fired:
        fired.append(name)
        if hold:
            Path(hold).write_text("locked")
            until=time.monotonic()+15
            while not Path(release).exists():
                if time.monotonic()>until: raise RuntimeError("test lock timeout")
                time.sleep(.02)
        else: os._exit(47)
try:
    result=Handoff(EvidenceStore(state),DeepTutor(load_deployment(config)),fault=fault).export_learning_results("activity",key,clock_assumption=read_json(clock))
    print(json.dumps(result))
except DeliveryError as exc:
    print(json.dumps({"status":exc.status,"code":exc.code}))
    sys.exit(4 if exc.status=="busy" else 2)
'''


class IntegratedServer(record_fixture.RecordServer):
    def __init__(self):
        super().__init__()
        self.session_backend = SessionBackend(ReadLimits())
        self.session_backend.detail["preferences"]["workspace_id"] = "workspace-1"
        self.learning["pageChatSessions"] = {"status": "valid", "valueAcquired": True, "coverage": "complete", "diagnostics": [],
                                             "value": {"pg_1": "s1"}}
        old, fake = self.server.RequestHandlerClass, self
        class Handler(old):
            def do_GET(self):
                if self.path.startswith("/api/sessions/"):
                    fake.requests.append({"method": "GET", "path": self.path, "workspace": self.headers.get("x-deeptutor-workspace")})
                    response = fake.session_backend.read(self.path)
                    return self.send(response.status, response.body)
                return super().do_GET()
        self.server.RequestHandlerClass = Handler


class HandoffTests(unittest.TestCase):
    evidence_dir = None
    example_refs = {}
    seed, capture, review, bind = fixture.BaselineTests.seed, fixture.BaselineTests.capture, fixture.BaselineTests.review, fixture.BaselineTests.bind
    def setUp(self):
        with patch.object(fixture, "ContentServer", IntegratedServer):
            fixture.BaselineTests.setUp(self)
        self.config["learningStateReadBuild"] = {"baseCommit": fixture.UPSTREAM, "i4PatchSha256": "1" * 64,
                                                 "patchSha256": "3" * 64, "wheelSha256": "4" * 64}
        with patch("tools.learning_book.baseline.now", return_value=record_fixture.CAPTURED):
            self.bind()
        self.exporter = Handoff(self.store, self.backend)

    def export(self, key="export", **kw):
        return self.exporter.export_learning_results("activity", key, clock_assumption=record_fixture.CLOCK, **kw)

    def tearDown(self):
        if not self.evidence_dir:
            return
        output = Path(self.evidence_dir)
        observations = output / "observations"
        observations.mkdir(parents=True, exist_ok=True)
        outcomes = []
        for path in (self.store.root / "exports").glob("*/result.json"):
            value = read_json(path)
            outcomes.append({k: value[k] for k in ("status", "exportId", "artifactRef", "diagnosticRef", "recovered") if k in value})
        (observations / (self._testMethodName + ".json")).write_bytes(canonical({"test": self.id(),
            "fixture": "synthetic_loopback_real_files_and_owned_child_processes", "requests": self.fake.requests, "results": outcomes}))
        if self._testMethodName == "test_C18_portable_complete_bundle_and_actual_raw_references":
            target = output / "examples/normal"
            shutil.copytree(self.root / "copied-handoff", target)
            self.example_refs["normal"] = target.relative_to(output).as_posix()
        if self._testMethodName == "test_C15_limits_shared_across_retries_and_partial_has_real_bytes":
            result = read_json(next((self.store.root / "exports").glob("*/result.json")))
            target = output / "examples/partial"
            shutil.copytree(self.store.root / result["artifactRef"], target)
            self.example_refs["partial"] = target.relative_to(output).as_posix()

    def artifact_path(self, result):
        self.assertIsNotNone(result["artifactRef"], result)
        return self.store.root / result["artifactRef"]

    def test_C18_portable_complete_bundle_and_actual_raw_references(self):
        result = self.export()
        root = self.artifact_path(result)
        verified = verify_handoff(root)
        self.assertEqual(verified["verification"], "valid")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(verified["bytesVerified"], read_json(root / "handoff.json")["limits"]["used"]["packageBytes"])
        self.assertEqual(read_json(root / "records.json")["records"][0]["binding"]["status"], "baseline_consistent")
        self.assertEqual(read_json(root / "conversations.json")["selectedCoverage"], "complete")
        moved = self.root / "copied-handoff"
        shutil.copytree(root, moved)
        old_state = self.root / "hidden-original-state"
        self.assertEqual(self.store.root.parent, self.root)
        self.assertEqual(old_state.parent, self.root)
        self.store.root.rename(old_state)
        self.assertEqual(verify_handoff(moved)["verification"], "valid")

    def test_C17_completed_export_returns_historical_fact_without_http(self):
        first = self.export()
        count = len(self.fake.requests)
        self.fake.learning["progress"]["value"]["score"] = 0
        (self.root / "package/original.md").unlink()
        self.assertEqual(self.export(), first)
        self.assertEqual(len(self.fake.requests), count)

    def test_C17_export_id_conflict_and_no_production_reservation(self):
        self.export()
        with self.assertRaises(DeliveryError):
            self.export(snapshot_id="different")
        self.assertEqual({r["requestId"] for r in self.store.requests()}, {"inputs", "create"})

    def test_C18_hash_tamper_missing_file_and_path_escape_rejected(self):
        root = self.artifact_path(self.export())
        records = (root / "records.json").read_bytes()
        (root / "records.json").write_bytes(records + b" ")
        with self.assertRaises(DeliveryError):
            verify_handoff(root)
        (root / "records.json").write_bytes(records)
        (root / "conversations.json").unlink()
        with self.assertRaises(DeliveryError):
            verify_handoff(root)

    def test_C18_raw_source_fields_named_rawref_not_rewritten(self):
        self.fake.learning["progress"]["value"]["quiz_attempts"][0]["extension"] = {"rawRef": "../../literal-user-text"}
        root = self.artifact_path(self.export())
        raw = read_json(root / "records.json")["records"][0]["raw"]
        self.assertEqual(raw["extension"]["rawRef"], "../../literal-user-text")
        self.assertEqual(verify_handoff(root)["verification"], "valid")

    def test_C15_full_window_changes_retry_whole_round_at_most_three(self):
        def mutate(number):
            self.fake.learning["progress"]["value"]["score"] = number
        self.fake.on_state = mutate
        result = self.export()
        handoff = read_json(self.artifact_path(result) / "handoff.json")
        self.assertEqual(handoff["roundsAttempted"], 3)
        self.assertEqual(handoff["collectionStatus"], "inconsistent")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self.fake.state_reads, 6)

    def test_C15_prior_round_submission_conflict_not_hidden_by_later_stability(self):
        def mutate(number):
            if number == 2:
                self.fake.learning["progress"]["value"]["quiz_attempts"][0]["user_answer"] = "B"
        self.fake.on_state = mutate
        root = self.artifact_path(self.export())
        row = read_json(root / "records.json")["records"][0]
        self.assertTrue(row["identityConflict"])
        self.assertEqual(row["binding"]["status"], "unknown")
        self.assertTrue((root / "prior-rounds.json").exists())

    def test_C15_limits_shared_across_retries_and_partial_has_real_bytes(self):
        result = self.export(limits={"eventPages": 1})
        root = self.artifact_path(result)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(verify_handoff(root)["verification"], "valid")
        self.assertIn("eventPages", read_json(root / "handoff.json")["limits"]["hits"])

    def test_C15_package_limit_publishes_diagnostic_not_fake_empty_package(self):
        result = self.export(limits={"packageBytes": 300})
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["artifactRef"])
        self.assertFalse(read_json(self.store.root / result["diagnosticRef"])["validHandoffPublished"])

    def test_C13_private_event_bytes_never_enter_published_or_attempt_files(self):
        self.fake.session_backend.events[0]["metadata"] = {"model_turn": {"marker": "synthetic-hidden-replay"}}
        result = self.export()
        self.assertEqual(result["status"], "partial")
        for folder in (self.store.root / "handoffs", self.store.root / "export-attempts"):
            self.assertFalse(any(b"synthetic-hidden-replay" in p.read_bytes() for p in folder.rglob("*") if p.is_file()))

    def test_C07_missing_baseline_and_missing_original_keep_unknown_records(self):
        self.app._binding_path("activity").unlink()
        root = self.artifact_path(self.export())
        self.assertEqual(read_json(root / "records.json")["records"][0]["binding"]["status"], "unknown")
        (self.root / "package/original.md").unlink()
        root = self.artifact_path(self.export("missing-original"))
        self.assertEqual(read_json(root / "handoff.json")["sources"]["statusAtCollection"], "partial")

    def declaration(self, **kw):
        value = {"schema": "learning-completion-declaration/1", "attributedAuthor": {"actorId": "learner", "role": "user"},
            "submittedBy": {"actorId": "external", "role": "external_agent"}, "scope": {**{k: self.config["scope"][k] for k in
            ("deploymentId", "ownerId", "workspaceId")}, "bookId": "bk_1", "activityId": "activity"},
            "declaredAt": record_fixture.CAPTURED, "statement": "合成用户结束声明", "provenance": {"kind": "agent_forwarded", "reference": "test-input"}}
        return {**value, **kw}

    def test_C19_optional_attributed_declaration_retained_later_activity_not_erased(self):
        root = self.artifact_path(self.export(completion_declaration=self.declaration()))
        completion = read_json(root / "handoff.json")["completion"]
        self.assertEqual(completion["status"], "declared_complete")
        self.assertTrue(completion["laterActivityObserved"])
        self.assertEqual(completion["currentCompletion"], "unknown")
        self.assertEqual(completion["attributionAssurance"], "operator_supplied")

    def test_C19_no_declaration_not_inferred_from_score_or_ready(self):
        root = self.artifact_path(self.export())
        self.assertEqual(read_json(root / "handoff.json")["completion"]["status"], "unknown")
        bad = self.declaration(scope={"wrong": True})
        with self.assertRaises(DeliveryError):
            self.export("wrong-declaration", completion_declaration=bad)

    def test_C16_each_fault_restarts_entire_attempt_or_restores_published_fact(self):
        fixture.BaselineTests.add_resource(self)
        # 新资源会使当前内容不同于首次基线，但不阻止事实导出／恢复测试。
        for boundary in ("raw", "records", "baseline", "assets", "manifest", "complete", "published"):
            fired = []
            def fail(name):
                if name == boundary and not fired:
                    fired.append(name)
                    raise RuntimeError("synthetic fault")
            self.exporter.fault = fail
            with self.assertRaises(RuntimeError):
                self.export(boundary)
            self.assertEqual(fired, [boundary])
            count = len(self.fake.requests)
            self.exporter.fault = lambda _: None
            result = self.export(boundary)
            self.assertEqual(verify_handoff(self.artifact_path(result))["verification"], "valid")
            self.assertEqual(len(self.fake.requests) == count, boundary == "published")

    def test_C16_persisted_request_budget_not_reset_on_interrupted_export(self):
        self.exporter.fault = lambda name: (_ for _ in ()).throw(RuntimeError("exit")) if name == "raw" else None
        with self.assertRaises(RuntimeError):
            self.export(limits={"requests": 5})
        self.exporter.fault = lambda _: None
        result = self.export(limits={"requests": 5})
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["artifactRef"])
        diagnostic = read_json(self.store.root / result["diagnosticRef"])
        self.assertEqual(diagnostic["limits"]["used"]["requests"], 5)

    def child_args(self, key, boundary="", hold="", release=""):
        config_path, clock_path = self.root / "child-deployment.json", self.root / "child-clock.json"
        config_path.write_bytes(canonical({k: v for k, v in self.config.items() if k != "scope"}))
        clock_path.write_bytes(canonical(record_fixture.CLOCK))
        return [PYTHON, "-B", "-c", CHILD, str(config_path), str(self.store.root), key, str(clock_path), boundary, str(hold), str(release)]

    def test_C16_actual_process_exit_each_boundary_and_restart(self):
        fixture.BaselineTests.add_resource(self)
        for boundary in ("raw", "records", "baseline", "assets", "manifest", "complete", "published"):
            key = "actual-exit-" + boundary
            child = subprocess.run(self.child_args(key, boundary), capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(child.returncode, 47, child.stderr)
            count = len(self.fake.requests)
            result = self.export(key)
            self.assertEqual(verify_handoff(self.artifact_path(result))["verification"], "valid")
            self.assertEqual(len(self.fake.requests) == count, boundary == "published")

    def test_C17_actual_two_export_processes_share_os_lock(self):
        hold, release = self.root / "locked", self.root / "release"
        first = subprocess.Popen(self.child_args("lock-first", "raw", hold, release), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            until = time.monotonic() + 10
            while not hold.exists() and first.poll() is None and time.monotonic() < until:
                time.sleep(.02)
            self.assertTrue(hold.exists())
            second = subprocess.run(self.child_args("lock-second"), capture_output=True, text=True, encoding="utf-8", timeout=15)
            self.assertEqual(second.returncode, 4, second.stderr)
            self.assertEqual(json.loads(second.stdout)["status"], "busy")
            release.write_text("release")
            stdout, stderr = first.communicate(timeout=20)
            self.assertEqual(first.returncode, 0, stderr)
            self.assertIsNotNone(json.loads(stdout)["artifactRef"])
        finally:
            if first.poll() is None:
                release.write_text("release")
                first.communicate(timeout=20)

    def test_C18_actual_directory_junction_rejected_and_missing_artifact_not_reused(self):
        root = self.artifact_path(self.export())
        folder, redirected = root / "baseline", self.root / "outside-baseline"
        self.assertTrue(root in folder.parents and redirected.parent == self.root)
        folder.rename(redirected)
        if os.name == "nt":
            created = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(folder), str(redirected)], capture_output=True)
            self.assertEqual(created.returncode, 0)
        else:
            folder.symlink_to(redirected, target_is_directory=True)
        try:
            with self.assertRaises(DeliveryError):
                verify_handoff(root)
        finally:
            folder.rmdir() if os.name == "nt" else folder.unlink()
        # 移动完整导出目录后，旧成功回执不能伪装本地仍有交付。
        moved = self.root / "removed-artifact"
        self.assertTrue(self.store.root in root.parents and moved.parent == self.root)
        root.rename(moved)
        with self.assertRaises(DeliveryError):
            self.export()

    def test_C20_cli_json_exit_codes_and_verify_needs_no_deployment_or_network(self):
        from contextlib import redirect_stdout
        import io
        from tools.learning_book.cli import main
        config = self.root / "cli-deployment.json"
        config.write_bytes(canonical({k: v for k, v in self.config.items() if k != "scope"}))
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["export-results", "--activity", "activity", "--export-id", "cli", "--deployment", str(config), "--state-dir", str(self.store.root)])
        self.assertEqual(code, 0)
        result = json.loads(output.getvalue())
        import socket
        with patch.object(socket.socket, "connect", side_effect=AssertionError("offline")), redirect_stdout(io.StringIO()) as verified:
            code = main(["verify-handoff", "--package", str(self.artifact_path(result))])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(verified.getvalue())["verification"], "valid")
        limits = self.root / "limits.json"
        limits.write_bytes(canonical({"eventPages": 1}))
        with redirect_stdout(io.StringIO()) as partial:
            code = main(["export-results", "--activity", "activity", "--export-id", "cli-partial", "--deployment", str(config), "--state-dir", str(self.store.root), "--limits", str(limits)])
        self.assertEqual(code, 7)
        self.assertEqual(json.loads(partial.getvalue())["status"], "partial")

    def test_C20_json_schema_normal_partial_and_diagnostic_contracts(self):
        import jsonschema
        schema = read_json(Path(__file__).parents[1] / "learning_book/schemas/learning-handoff.schema.json")
        jsonschema.Draft202012Validator.check_schema(schema)
        for key, options in (("schema-normal", {}), ("schema-partial", {"limits": {"eventPages": 1}})):
            root = self.artifact_path(self.export(key, **options))
            for name, definition in (("handoff.json", "handoff"), ("manifest.json", "manifest"), ("records.json", "records"), ("conversations.json", "conversations")):
                validator = jsonschema.Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/" + definition})
                validator.validate(read_json(root / name))
        diagnostic = self.export("schema-diagnostic", limits={"packageBytes": 300})
        jsonschema.Draft202012Validator({"$defs": schema["$defs"], "$ref": "#/$defs/diagnostic"}).validate(read_json(self.store.root / diagnostic["diagnosticRef"]))

    def test_C19_agent_statement_and_future_time_not_user_completion(self):
        declaration = self.declaration(attributedAuthor={"actorId": "agent", "role": "external_agent"})
        root = self.artifact_path(self.export(completion_declaration=declaration))
        self.assertEqual(read_json(root / "handoff.json")["completion"]["status"], "agent_statement_only")
        with self.assertRaises(DeliveryError):
            self.export("future-declaration", completion_declaration=self.declaration(declaredAt="2999-01-01T00:00:00.000000Z"))

    def test_C13_known_credential_echo_never_persisted(self):
        self.config["tokenEnv"] = "INSPOOL_TEST_HANDOFF_TOKEN"
        self.fake.learning["progress"]["value"]["quiz_attempts"][0]["extension"] = "synthetic-only-secret"
        with patch.dict(os.environ, {"INSPOOL_TEST_HANDOFF_TOKEN": "synthetic-only-secret"}):
            result = self.export()
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["artifactRef"])
        self.assertFalse(any(b"synthetic-only-secret" in p.read_bytes() for p in (self.store.root / "export-attempts").rglob("*") if p.is_file()))

    def test_C18_resigned_manifest_path_escape_still_rejected(self):
        from tools.learning_book.contracts import digest
        root = self.artifact_path(self.export())
        manifest = read_json(root / "manifest.json")
        manifest["files"]["../outside.bin"] = "0" * 64
        (root / "manifest.json").write_bytes(canonical(manifest))
        (root / "complete.json").write_bytes(canonical({"manifestSha256": digest(manifest)}))
        with self.assertRaises(DeliveryError):
            verify_handoff(root)

    def test_C18_resigned_unsupported_versions_and_extra_assurance_claims_rejected(self):
        from tools.learning_book.contracts import digest
        root = self.artifact_path(self.export())
        original = {name: (root / name).read_bytes() for name in ("records.json", "handoff.json", "manifest.json", "complete.json")}
        cases = [("records.json", lambda value: value.update(schema="unsupported/2")),
                 ("records.json", lambda value: value["records"][0]["assistance"].update(status="unassisted")),
                 ("records.json", lambda value: value["records"][0]["assessments"]["comparisonToBaseline"].update(historicalBinding="verified_at_submission")),
                 ("handoff.json", lambda value: value["completion"].update(attributionAssurance="authenticated"))]
        for name, change in cases:
            for path, data in original.items():
                (root / path).write_bytes(data)
            value = read_json(root / name)
            change(value)
            (root / name).write_bytes(canonical(value))
            manifest = read_json(root / "manifest.json")
            manifest["files"][name] = digest(value)
            (root / "manifest.json").write_bytes(canonical(manifest))
            (root / "complete.json").write_bytes(canonical({"manifestSha256": digest(manifest)}))
            with self.assertRaises(DeliveryError):
                verify_handoff(root)
