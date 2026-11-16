"""I5-B：纯记录反例与真实 loopback／I4 基线文件集成；合成资料，零模型。"""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.learning_book.baseline import Baseline
from tools.learning_book.content import project
from tools.learning_book.contracts import DeliveryError, canonical, digest, read_json, sha256
from tools.learning_book.records import LearningRecords, project_records, submission_key, validate_clock_assumption
from tools.tests import test_learning_book_i4 as fixture
from tools.tests.test_learning_book_i5 import observation

CAPTURED = "2026-11-10T00:00:00.000000Z"
BOUND = "2026-11-10T00:00:05.000000Z"
OBSERVED = "2026-11-10T01:00:00.000000Z"
TIME = 1794268810.5  # UTC 2026-11-10 00:00:10.5，合成记录。
CLOCK = {"schema": "learning-clock-assumption/1", "kind": "same_local_clock", "actorId": "test-operator",
         "statement": "合成测试假设同机时钟；不证明真实服务器精度。", "maxSkewSeconds": 0, "timestampResolutionSeconds": 0.000001}
SCOPE = {"deploymentId": "dep", "ownerId": "owner", "workspaceId": "ws-1", "scopeVerification": "configured_single_user"}


def attempt(**changes):
    value = {"submission_id": "s1", "page_id": "pg_1", "block_id": "blk_q1", "question_id": "q_1",
             "user_answer": "A", "is_correct": True, "timestamp": TIME}
    return {**value, **changes}


def state(attempts=None):
    value = observation()
    value["progress"] = {"status": "valid", "coverage": "complete", "valueAcquired": True, "diagnostics": [],
                         "value": {"book_id": "bk_1", "current_page_id": "pg_1", "visited_page_ids": ["pg_1"],
                                   "bookmarked_page_ids": [], "weak_chapters": [], "score": 99,
                                   "updated_at": 1, "quiz_attempts": [attempt()] if attempts is None else attempts}}
    return value


def basis():
    projected, _, structure = project(fixture.content(), "bk_1")
    return {"bindingStatus": "accepted", "issues": [], "snapshotId": "snap", "scope": deepcopy(SCOPE), "bookId": "bk_1",
            "content": projected, "capture": {"structure": structure}, "manifest": {"identity": {"contentDigest": digest(projected)}},
            "binding": {"purpose": "pre_learning", "capturedAt": CAPTURED, "boundAt": BOUND}}


def check(evidence):
    return {"binding": "baseline_consistent", "contentConsistent": True, "recordWindowStable": True,
            "sourceAvailability": "complete", "snapshotId": evidence["snapshotId"], "baselineIdentity": evidence["manifest"]["identity"]}


class RecordProjectionTests(unittest.TestCase):
    def run_projection(self, attempts=None, *, evidence=None, current=None, clock=CLOCK, values=None, record_scope="export-1"):
        evidence = basis() if evidence is None else evidence
        values = [state(attempts)] if values is None else values
        observations = [{"rawRef": f"raw/state-{i}.bin", "body": canonical(v), "observedAt": OBSERVED} for i, v in enumerate(values)]
        return project_records(observations, scope=SCOPE, book_id="bk_1", record_scope_id=record_scope,
                               evidence=evidence, current_check=check(evidence) if current is None else current, clock_assumption=clock)

    def test_C04_tuple_key_avoids_delimiter_collision_and_scopes(self):
        one = submission_key({**SCOPE, "ownerId": "a:b", "workspaceId": "c"}, "bk_1", "s")
        two = submission_key({**SCOPE, "ownerId": "a", "workspaceId": "b:c"}, "bk_1", "s")
        self.assertNotEqual(one["digest"], two["digest"])
        for key in ("ownerId", "workspaceId", "deploymentId"):
            self.assertNotEqual(submission_key({**SCOPE, key: "other"}, "bk_1", "s")["digest"], submission_key(SCOPE, "bk_1", "s")["digest"])
        self.assertEqual(one["components"], ["dep", "a:b", "c", "bk_1", "s"])

    def test_C04_multiple_pages_all_attempts_not_latest(self):
        values = [attempt(), attempt(submission_id="s2", page_id="pg_2", block_id="blk_q2", user_answer="B", is_correct=False),
                  attempt(submission_id="s3", user_answer="B", is_correct=False)]
        output = self.run_projection(values)
        self.assertEqual(len(output["records"]), 3)
        self.assertEqual([r["raw"] for r in output["records"]], values)
        self.assertEqual(output["upstreamSummaries"][0]["fields"]["score"], 99)
        self.assertEqual(output["logicalAttemptCount"], "unknown")

    def test_C04_identical_payload_dedup_keeps_all_raw_locations(self):
        output = self.run_projection([attempt(), attempt()], values=[state([attempt(), attempt()]), state([attempt()])])
        self.assertEqual(len(output["records"]), 1)
        row = output["records"][0]
        self.assertEqual(len(row["occurrences"]), 3)
        self.assertEqual([p["arrayIndex"] for p in row["occurrences"]], [0, 1, 0])
        self.assertFalse(row["identityConflict"])

    def test_C04_same_submission_conflicts_preserve_every_variant(self):
        for field, value in (("page_id", "pg_2"), ("block_id", "blk_q2"), ("question_id", "q_other"),
                             ("user_answer", "B"), ("is_correct", False), ("timestamp", TIME + 1), ("extension", "new")):
            with self.subTest(field=field):
                rows = self.run_projection([attempt(), attempt(**{field: value})])["records"]
                self.assertEqual(len(rows), 2)
                self.assertTrue(all(r["identityConflict"] and r["binding"]["status"] == "unknown" for r in rows))

    def test_C04_legacy_duplicates_not_merged_or_cross_export_identified(self):
        legacy = attempt()
        legacy.pop("submission_id")
        one = self.run_projection([legacy, legacy])
        two = self.run_projection([legacy, legacy], record_scope="export-2")
        self.assertEqual(len(one["records"]), 2)
        self.assertTrue(all(r["identityQuality"] == "legacy" for r in one["records"]))
        self.assertNotEqual(one["records"][0]["recordId"], two["records"][0]["recordId"])

    def test_C04_invalid_submission_and_bad_members_not_dropped(self):
        value = state([None, 3, attempt(submission_id=None), attempt(submission_id=" x "), attempt(submission_id="")])
        value["progress"].update(status="invalid", coverage="partial")
        rows = self.run_projection(values=[value])["records"]
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["raw"], None)
        self.assertEqual(rows[1]["raw"], 3)
        self.assertTrue(all(r["binding"]["status"] == "unknown" for r in rows[:4]))

    def test_C05_false_null_missing_and_bad_verdict_are_distinct(self):
        missing = attempt(submission_id="missing")
        missing.pop("is_correct")
        rows = self.run_projection([attempt(is_correct=False), attempt(submission_id="null", is_correct=None), missing,
                                    attempt(submission_id="bad", is_correct="false")])["records"]
        self.assertEqual([r["assessments"]["raw"]["method"] for r in rows], ["client_reported", "ungraded", "unknown", "unknown"])
        self.assertIs(rows[0]["assessments"]["raw"]["isCorrect"]["value"], False)
        self.assertIsNone(rows[1]["assessments"]["raw"]["isCorrect"]["value"])
        self.assertEqual(rows[2]["assessments"]["raw"]["isCorrect"], {"present": False})
        self.assertTrue(all(r["assessments"]["assessmentSync"] == "unknown" for r in rows))

    def test_C05_self_report_requires_known_type_and_preserves_disagreement(self):
        e = basis()
        q = e["content"]["pages"][0]["blocks"][1]["payload"]["questions"][0]
        q["question_type"] = "written"
        rows = self.run_projection([attempt(user_answer="self:correct", is_correct=False),
            attempt(submission_id="s2", user_answer="a written answer", is_correct=True)], evidence=e)["records"]
        self.assertEqual(rows[0]["assessments"]["raw"]["method"], "user_self_report")
        self.assertIn("self_report_verdict_disagreement", rows[0]["diagnostics"])
        self.assertEqual(rows[1]["assessments"]["raw"]["method"], "unknown")
        self.assertEqual(rows[0]["raw"]["user_answer"], "self:correct")
        self.assertNotIn("writtenAnswer", rows[0])

    def test_C05_unknown_history_does_not_assert_old_question_type(self):
        e = basis()
        e["bindingStatus"] = "candidate"
        row = self.run_projection(evidence=e)["records"][0]
        self.assertEqual(row["assessments"]["raw"]["method"], "unknown")
        self.assertEqual(row["assessments"]["raw"]["transportSource"], "client_reported")
        self.assertEqual(row["assessments"]["typeBasis"]["historicalBinding"], "unknown")
        self.assertEqual(row["assessments"]["comparisonToBaseline"]["result"], "correct")

    def test_C05_missing_attempt_observation_is_not_a_submission(self):
        output = self.run_projection([])
        self.assertEqual(output["records"], [])
        self.assertEqual(len(output["missingAttemptObservations"]), 2)
        self.assertTrue(all(r["kind"] == "missing_attempt" and "is_correct" not in r for r in output["missingAttemptObservations"]))

    def test_C06_choice_exact_keys_order_and_disagreement(self):
        rows = self.run_projection([attempt(is_correct=False), attempt(submission_id="s2", user_answer="B", is_correct=True)])["records"]
        self.assertEqual([r["assessments"]["comparisonToBaseline"]["result"] for r in rows], ["correct", "incorrect"])
        self.assertEqual(rows[0]["assessments"]["comparisonToBaseline"]["optionKeys"], ["B", "A"])
        self.assertTrue(all(r["assessments"]["comparisonToBaseline"]["disagreement"] for r in rows))
        self.assertIs(rows[0]["raw"]["is_correct"], False)

    def test_C06_choice_no_fuzzy_normalization_or_wrong_on_parse_failure(self):
        for answer in ("a", " A ", "37ms", "A/B", "", None, ["A"]):
            row = self.run_projection([attempt(user_answer=answer)])["records"][0]
            self.assertEqual(row["assessments"]["comparisonToBaseline"]["result"], "unknown")

    def test_C06_unsupported_invalid_choices_and_duplicate_identity(self):
        for mutation in (lambda q: q.update(correct_answer="A/B"), lambda q: q.update(options=["A", "B"]),
                         lambda q: q.update(question_type="multiple_choice"), lambda q: q.update(question_type=["choice"])):
            e = basis()
            mutation(e["content"]["pages"][0]["blocks"][1]["payload"]["questions"][0])
            self.assertEqual(self.run_projection(evidence=e)["records"][0]["assessments"]["comparisonToBaseline"]["result"], "unknown")
        e = basis()
        e["content"]["pages"][0]["blocks"][1]["payload"]["questions"] *= 2
        row = self.run_projection(evidence=e)["records"][0]
        self.assertEqual(row["binding"]["status"], "unknown")
        self.assertEqual(row["assessments"]["comparisonToBaseline"]["result"], "unknown")

    def test_C06_choice_requires_i4_supported_inventory(self):
        e = basis()
        e["capture"]["structure"]["questions"][0]["assessmentSupport"] = "unsupported"
        row = self.run_projection(evidence=e)["records"][0]
        self.assertEqual(row["assessments"]["comparisonToBaseline"]["result"], "unknown")

    def test_C07_both_capture_and_first_binding_times_required(self):
        for timestamp in (1794268801.0, 1794268804.0, 1794268805.0, 1794268805.0000005):
            row = self.run_projection([attempt(timestamp=timestamp)])["records"][0]
            self.assertEqual(row["binding"]["status"], "unknown")
        self.assertEqual(self.run_projection()["records"][0]["binding"]["status"], "baseline_consistent")

    def test_C07_missing_invalid_future_and_huge_record_times(self):
        for timestamp in (None, True, "today", -1, 0, 10 ** 400, TIME + 999999):
            row = self.run_projection([attempt(timestamp=timestamp)])["records"][0]
            self.assertEqual(row["binding"]["status"], "unknown")
        missing = attempt()
        missing.pop("timestamp")
        row = self.run_projection([missing])["records"][0]
        self.assertEqual(row["binding"]["status"], "unknown")
        self.assertNotIn("timestamp", row["raw"])

    def test_C07_clock_assumption_precision_and_invalid_declarations(self):
        self.assertEqual(self.run_projection(clock=None)["records"][0]["binding"]["status"], "unknown")
        self.assertEqual(self.run_projection(clock={**CLOCK, "maxSkewSeconds": 10})["records"][0]["binding"]["status"], "unknown")
        for bad in ({}, {**CLOCK, "maxSkewSeconds": True}, {**CLOCK, "timestampResolutionSeconds": 0},
                    {**CLOCK, "maxSkewSeconds": 10 ** 400}, {**CLOCK, "maxSkewSeconds": float("nan")}):
            with self.assertRaises(DeliveryError):
                validate_clock_assumption(bad)

    def test_C07_corrupt_clock_order_and_retrospective_unknown(self):
        for changes in ({"boundAt": "bad"}, {"boundAt": "2026-11-09T00:00:00Z"},
                        {"capturedAt": "bad"}, {"purpose": "retrospective"}):
            e = basis()
            e["binding"].update(changes)
            self.assertEqual(self.run_projection(evidence=e)["records"][0]["binding"]["status"], "unknown")

    def test_C08_current_drift_sources_unavailable_or_unstable_unknown(self):
        e = basis()
        for changes in ({"binding": "unknown"}, {"contentConsistent": False}, {"sourceAvailability": "partial"},
                        {"recordWindowStable": False}, {"baselineIdentity": {"changed": True}}):
            current = {**check(e), **changes}
            self.assertEqual(self.run_projection(current=current)["records"][0]["binding"]["status"], "unknown")

    def test_C08_no_mastery_unassisted_or_submission_version_claim(self):
        value = self.run_projection()
        self.assertEqual(value["records"][0]["binding"]["assurance"], "cooperative")
        self.assertEqual(value["records"][0]["binding"]["submissionContent"], "unknown")
        self.assertEqual(value["records"][0]["assistance"]["status"], "unknown")
        serialized = canonical(value).decode("utf-8")
        for forbidden in ("verified_at_submission", "mastery_passed", '"unassisted"'):
            self.assertNotIn(forbidden, serialized)

    def test_C02_invalid_file_preserves_good_rows_missing_file_not_empty_success(self):
        value = state([attempt(), 3])
        value["progress"].update(status="invalid", coverage="partial")
        result = self.run_projection(values=[value])
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["recordCoverage"], "partial")
        value["progress"] = {"status": "missing", "valueAcquired": False, "coverage": "partial", "diagnostics": []}
        result = self.run_projection(values=[value])
        self.assertEqual(result["records"], [])
        self.assertEqual(result["recordCoverage"], "partial")

    def test_C03_wrong_progress_book_quarantined_wrong_workspace_rejected(self):
        value = state()
        value["progress"]["value"]["book_id"] = "other"
        value["progress"].update(status="invalid", coverage="partial")
        result = self.run_projection(values=[value])
        self.assertEqual(result["records"], [])
        self.assertEqual(result["rejectedObservations"][0]["code"], "progress_book_identity")
        value = state()
        value["readerScope"]["workspaceId"] = "other"
        with self.assertRaises(DeliveryError):
            self.run_projection(values=[value])

    def test_C04_raw_pointer_hash_and_source_immutability(self):
        value = state([attempt(), attempt(submission_id="s2", extension={"nested": [1, None]})])
        before = canonical(value)
        output = self.run_projection(values=[value])
        for row in output["records"]:
            pointer = row["occurrences"][0]
            self.assertEqual(pointer["responseSha256"], sha256(before))
            self.assertEqual(value["progress"]["value"]["quiz_attempts"][pointer["arrayIndex"]], row["raw"])
        self.assertEqual(canonical(value), before)

    def test_C03_raw_ref_escape_and_conflicting_bytes_rejected(self):
        for ref in ("../state.bin", "C:/private", "\\private", "/state.bin"):
            with self.assertRaises(DeliveryError):
                project_records([{"rawRef": ref, "body": canonical(state()), "observedAt": OBSERVED}],
                                scope=SCOPE, book_id="bk_1", record_scope_id="export")
        with self.assertRaises(DeliveryError):
            project_records([{"rawRef": "raw/a", "body": canonical(state()), "observedAt": OBSERVED},
                             {"rawRef": "raw/a", "body": canonical(state([])), "observedAt": OBSERVED}],
                            scope=SCOPE, book_id="bk_1", record_scope_id="export")


class RecordServer(fixture.ContentServer):
    def __init__(self):
        super().__init__()
        self.learning = state()
        self.learning["readerScope"]["workspaceId"] = "workspace-1"
        self.state_reads = 0
        self.on_state = lambda _: None
        old = self.server.RequestHandlerClass
        fake = self
        class Handler(old):
            def do_GET(self):
                if self.path.endswith("/learning-state"):
                    fake.state_reads += 1
                    fake.on_state(fake.state_reads)
                    fake.requests.append({"method": "GET", "path": self.path, "workspace": self.headers.get("x-deeptutor-workspace")})
                    return self.send(200, fake.learning)
                return super().do_GET()
        self.server.RequestHandlerClass = Handler


class RecordWindowTests(unittest.TestCase):
    evidence_dir = None
    seed = fixture.BaselineTests.seed
    capture = fixture.BaselineTests.capture
    review = fixture.BaselineTests.review
    bind = fixture.BaselineTests.bind

    def setUp(self):
        with patch.object(fixture, "ContentServer", RecordServer):
            fixture.BaselineTests.setUp(self)
        self.config["learningStateReadBuild"] = {"baseCommit": fixture.UPSTREAM, "i4PatchSha256": "1" * 64,
                                                 "patchSha256": "3" * 64, "wheelSha256": "4" * 64}
        self.records = LearningRecords(self.store, self.backend)

    def frozen_bind(self):
        with patch("tools.learning_book.baseline.now", return_value=CAPTURED):
            self.bind()

    def observe(self, **kw):
        return self.records.observe_records("activity", clock_assumption=CLOCK, **kw)

    def tearDown(self):
        self.assertTrue(all(r["method"] == "GET" and r["path"] != "/api/books/bk_1" for r in self.fake.requests))
        if self.evidence_dir:
            output = Path(self.evidence_dir)
            folder = output / "observations"
            folder.mkdir(parents=True, exist_ok=True)
            reports = [read_json(p) for p in (self.store.root / "record-observations").glob("*/records.json")]
            (folder / (self._testMethodName + ".json")).write_bytes(canonical({"test": self.id(), "fixture": "synthetic_loopback_and_real_i4_files",
                "http": self.fake.requests, "contentReads": self.fake.reads, "stateReads": self.fake.state_reads,
                "results": [{"status": r["status"], "baselineEvidence": r["baselineEvidence"],
                             "records": r["records"], "currentCheck": r["currentCheck"]} for r in reports]}))
            if self._testMethodName == "test_C07_actual_binding_review_chain_and_fresh_reads":
                for path in (self.store.root / "record-observations").rglob("*"):
                    if path.is_file():
                        target = output / "examples" / "record-observation" / path.relative_to(self.store.root / "record-observations")
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(path.read_bytes())

    def test_C07_actual_binding_review_chain_and_fresh_reads(self):
        self.frozen_bind()
        reads = self.fake.reads
        result = self.observe()
        self.assertEqual(result["baselineEvidence"]["bindingStatus"], "accepted")
        self.assertEqual(result["records"][0]["binding"]["status"], "baseline_consistent")
        self.assertEqual(self.fake.reads - reads, 2)
        self.assertEqual(self.fake.state_reads, 2)
        self.assertEqual(len(result["records"][0]["occurrences"]), 2)
        self.assertTrue(result["currentCheck"]["recordWindowStable"])
        for occurrence in result["records"][0]["occurrences"]:
            body = (self.store.root / occurrence["rawRef"]).read_bytes()
            self.assertEqual(sha256(body), occurrence["responseSha256"])
        self.assertEqual({r["requestId"] for r in self.store.requests()}, {"inputs", "create"})

    def test_C07_no_baseline_and_explicit_candidate_keep_raw_unknown(self):
        result = self.observe()
        self.assertEqual(result["baselineEvidence"]["bindingStatus"], "missing")
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")
        self.capture()
        result = self.observe(snapshot_id="snapshot")
        self.assertEqual(result["baselineEvidence"]["bindingStatus"], "candidate")
        self.assertEqual(result["records"][0]["assessments"]["comparisonToBaseline"]["result"], "correct")

    def test_C07_tampered_binding_review_digest_not_accepted(self):
        self.frozen_bind()
        path = self.app._binding_path("activity")
        value = read_json(path)
        value["reviewDigest"] = "0" * 64
        path.write_bytes(canonical(value))
        result = self.observe()
        self.assertEqual(result["baselineEvidence"]["bindingStatus"], "invalid")
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")

    def test_C07_missing_review_request_and_corrupt_snapshot_do_not_lose_records(self):
        self.frozen_bind()
        (self.app._path("reviews", "review") / "request.json").unlink()
        self.assertEqual(self.observe()["baselineEvidence"]["bindingStatus"], "invalid")
        (self.app._snapshot_path("snapshot") / "content.json").write_bytes(b'{}')
        result = self.observe()
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")

    def test_C07_binding_commit_survives_missing_review_receipt(self):
        self.frozen_bind()
        (self.app._path("reviews", "review") / "result.json").unlink()
        value = self.app.load_learning_evidence("activity")
        self.assertEqual(value["bindingStatus"], "accepted")
        self.assertEqual(value["reviewReceiptStatus"], "missing_after_binding")
        self.assertEqual(self.observe()["records"][0]["binding"]["status"], "baseline_consistent")

    def test_C07_invalid_review_semantics_not_just_decision_pass(self):
        self.frozen_bind()
        path = self.app._path("reviews", "review") / "request.json"
        request = read_json(path)
        request["semantic"]["review"]["questionChecks"] = []
        request["digest"] = digest(request["semantic"])
        path.write_bytes(canonical(request))
        binding_path = self.app._binding_path("activity")
        binding = read_json(binding_path)
        binding["reviewDigest"] = digest(request["semantic"]["review"])
        binding_path.write_bytes(canonical(binding))
        self.assertEqual(self.observe()["baselineEvidence"]["bindingStatus"], "invalid")

    def test_C07_wrong_binding_scope_and_missing_capture_request(self):
        self.frozen_bind()
        path = self.app._binding_path("activity")
        original = path.read_bytes()
        binding = read_json(path)
        binding["scope"] = {**self.config["scope"], "ownerId": "other"}
        path.write_bytes(canonical(binding))
        self.assertEqual(self.observe()["records"][0]["binding"]["status"], "unknown")
        path.write_bytes(original)
        (self.app._path("captures", "capture") / "request.json").unlink()
        self.assertEqual(self.observe()["baselineEvidence"]["bindingStatus"], "invalid")

    def test_C07_unreadable_content_still_preserves_actual_progress(self):
        self.frozen_bind()
        self.fake.value = {}
        result = self.observe()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["records"][0]["raw"]["user_answer"], "A")
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")
        self.assertEqual(len(result["currentCheck"]["errors"]), 2)

    def test_C07_candidate_cannot_replace_first_binding(self):
        self.frozen_bind()
        self.fake.value["pages"][0]["title"] = "new candidate"
        self.capture("new-capture", "new-snapshot")
        result = self.observe(snapshot_id="new-snapshot")
        self.assertEqual(result["baselineEvidence"]["bindingStatus"], "candidate")
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")

    def test_C07_retrospective_binding_never_upgraded(self):
        with patch("tools.learning_book.baseline.now", return_value=CAPTURED):
            self.app.capture_baseline("activity", "capture", "snapshot", "retrospective")
            self.app.record_baseline_review("activity", "snapshot", "review", self.review())
        self.assertEqual(self.observe()["records"][0]["binding"]["status"], "unknown")

    def test_C08_current_drift_ignores_old_successful_check_id(self):
        self.frozen_bind()
        old = self.app.check_baseline("activity", "snapshot", "old-success")
        self.assertTrue(old["contentConsistent"])
        self.fake.value["pages"][0]["blocks"][1]["payload"]["questions"][0]["correct_answer"] = "B"
        result = self.observe()
        self.assertFalse(result["currentCheck"]["contentConsistent"])
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")
        self.assertEqual(result["records"][0]["assessments"]["comparisonToBaseline"]["result"], "correct")

    def test_C08_missing_local_original_separate_from_content_consistency(self):
        self.frozen_bind()
        (self.root / "package/original.md").unlink()
        result = self.observe()
        self.assertTrue(result["currentCheck"]["contentConsistent"])
        self.assertEqual(result["currentCheck"]["sourceAvailability"], "partial")
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")

    def test_C08_same_uri_resource_change_blocks_binding(self):
        fixture.BaselineTests.add_resource(self)
        self.frozen_bind()
        self.fake.resources["/files/outputs/picture.png"] = (200, b"\x89PNG\r\n\x1a\nchanged-bytes", "image/png")
        self.assertEqual(self.observe()["records"][0]["binding"]["status"], "unknown")

    def test_C14_same_count_and_updated_at_changed_answer_visible(self):
        self.frozen_bind()
        def change(number):
            if number == 2:
                self.fake.learning["progress"]["value"]["quiz_attempts"][0]["user_answer"] = "B"
        self.fake.on_state = change
        result = self.observe()
        self.assertFalse(result["currentCheck"]["recordWindowStable"])
        self.assertEqual(len(result["records"]), 2)
        self.assertTrue(all(r["identityConflict"] and r["binding"]["status"] == "unknown" for r in result["records"]))
        self.assertEqual(self.fake.reads, 6)  # 捕获 2，审查 2，本次 2；不嵌套重试。

    def test_C14_json_boolean_integer_change_not_python_equal(self):
        self.frozen_bind()
        def change(number):
            if number == 2:
                self.fake.learning["progress"]["value"]["quiz_attempts"][0]["is_correct"] = 1
                self.fake.learning["progress"].update(status="invalid", coverage="partial")
        self.fake.on_state = change
        result = self.observe()
        self.assertFalse(result["currentCheck"]["recordWindowStable"])
        self.assertTrue(all(r["binding"]["status"] == "unknown" for r in result["records"]))

    def test_C07_binding_time_change_during_window_not_hidden_by_same_digest(self):
        self.frozen_bind()
        def change(number):
            if number == 2:
                path = self.app._binding_path("activity")
                binding = read_json(path)
                binding["boundAt"] = "2026-11-10T00:00:20.000000Z"
                path.write_bytes(canonical(binding))
        self.fake.on_state = change
        result = self.observe()
        self.assertFalse(result["currentCheck"]["baselineEvidenceStable"])
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")

    def test_C07_damaged_snapshot_shape_preserves_progress(self):
        self.frozen_bind()
        folder = self.app._snapshot_path("snapshot")
        manifest = read_json(folder / "manifest.json")
        (folder / "content.json").write_bytes(canonical([]))
        manifest["files"]["content.json"] = digest([])
        manifest["identity"]["contentDigest"] = digest([])
        (folder / "manifest.json").write_bytes(canonical(manifest))
        (folder / "complete.json").write_bytes(canonical({"manifestDigest": digest(manifest)}))
        result = self.observe()
        self.assertEqual(result["baselineEvidence"]["bindingStatus"], "invalid")
        self.assertEqual(result["records"][0]["raw"]["user_answer"], "A")
        self.assertEqual(result["records"][0]["binding"]["status"], "unknown")

    def test_C03_activity_scope_mismatch_rejected_before_http(self):
        self.config["scope"]["workspaceId"] = "wrong"
        with self.assertRaises(DeliveryError):
            self.observe()
        self.assertEqual(self.fake.requests, [])

    def test_C03_public_single_read_rejects_escape_and_pathlike_number(self):
        context = self.app.learning_context("activity")
        for directory, number in ((self.root / "outside", 1), (self.store.root / "read", "../../outside"),
                                  (self.store.root / "read", True)):
            with self.assertRaises(DeliveryError):
                self.app.read_content_once(directory, number, context)
        self.assertEqual(self.fake.requests, [])
        self.assertFalse((self.root / "outside").exists())
