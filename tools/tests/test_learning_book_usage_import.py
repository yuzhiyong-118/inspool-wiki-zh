from __future__ import annotations

import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tools.learning_book.contracts import DeliveryError, canonical, sha256
from tools.learning_book.evidence_store import atomic
from tools.learning_book.runtime_guard import RuntimeGuard
from tools.learning_book.usage_import import import_calls


class UsageImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime"
        self.state = self.root / "state"
        self.control = self.root / "control"
        for path in (self.runtime / "data/user", self.state, self.control):
            path.mkdir(parents=True)
        ledger = self.runtime / "data/user/usage.sqlite3"
        with closing(sqlite3.connect(ledger)) as db:
            db.execute("CREATE TABLE llm_calls (call_id TEXT PRIMARY KEY, started_at REAL NOT NULL,"
                       "session_id TEXT NOT NULL, turn_id TEXT NOT NULL, source TEXT NOT NULL, usage_json TEXT NOT NULL)")
        budget = {"schemaVersion": 1, "contextId": "usage-import-test", "scope": {},
                  "ledger": str(ledger), "baselineCallIds": [], "pauseAt": 800000, "limit": 1000000,
                  "pollSeconds": 1, "maxSilentSeconds": 120, "stopProcess": {}}
        atomic(self.control / "budget.json", canonical(budget))
        guard_config = {"controlDatabase": str(self.control / "control.sqlite3"),
                        "budget": str(self.control / "budget.json"), "scope": {}}
        atomic(self.control / "guard.json", canonical(guard_config))
        guard = RuntimeGuard(self.control / "guard.json")
        guard.initialize()
        guard.start()
        guard.block("operator_stop")
        self.config = self.control / "runtime.json"
        atomic(self.config, canonical({"schema": "learning-local-runtime/1", "runtime": str(self.runtime),
            "projectState": str(self.state), "controlDir": str(self.control), "python": str(self.root / "python"),
            "sitePackages": str(self.root / "site"), "node": str(self.root / "node"), "web": str(self.root / "web"),
            "guard": str(self.control / "guard.json"), "apiPort": 8136, "webPort": 3836,
            "installedFiles": {"placeholder": "unused"}}))
        self.payload = {"calls": [
            {"callId": "reported-1", "startedAt": 11.5, "sessionId": "book-1", "turnId": "turn-1",
             "source": "book:prepare_question_variant",
             "usage": {"call_id": "reported-1", "prompt_tokens": 100, "completion_tokens": 20,
                       "total_tokens": 120, "estimated": False, "status": "interrupted"}},
            {"callId": "estimated-1", "startedAt": 12.5, "sessionId": "", "turnId": "turn-2",
             "source": "book:regenerate_block",
             "usage": {"call_id": "estimated-1", "prompt_tokens": 30, "completion_tokens": 0,
                       "total_tokens": 30, "estimated": True, "status": "failed"}},
        ]}
        self.input = self.root / "input.json"
        self.input.write_text(json.dumps(self.payload), encoding="utf-8")
        self.source_hash = sha256(self.input.read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def import_now(self):
        return import_calls(self.config, self.input, self.source_hash)

    def test_import_preserves_audit_facts_floor_and_thresholds(self):
        before = json.loads((self.control / "budget.json").read_text(encoding="utf-8"))
        result = self.import_now()
        self.assertEqual(result["incrementTokens"], 150)
        self.assertEqual(result["after"]["totalTokens"], 150)
        self.assertEqual(result["after"]["reportedTokens"], 120)
        self.assertEqual(result["after"]["estimatedTokens"], 30)
        self.assertEqual(result["blockedPreserved"], "operator_stop")
        self.assertEqual(json.loads((self.control / "budget.json").read_text(encoding="utf-8")), before)
        with closing(sqlite3.connect(self.runtime / "data/user/usage.sqlite3")) as db:
            rows = db.execute("SELECT * FROM llm_calls ORDER BY call_id").fetchall()
        self.assertEqual(rows[0][0:5], ("estimated-1", 12.5, "", "turn-2", "book:regenerate_block"))
        self.assertEqual(json.loads(rows[0][5])["status"], "failed")
        self.assertTrue(json.loads(rows[0][5])["estimated"])

    def test_replay_is_zero_and_does_not_replace_rows(self):
        first = self.import_now()
        ledger = self.runtime / "data/user/usage.sqlite3"
        control = self.control / "control.sqlite3"
        before = (sha256(ledger.read_bytes()), sha256(control.read_bytes()))
        second = self.import_now()
        self.assertEqual(second["incrementTokens"], 0)
        self.assertEqual(second["imported"], [])
        self.assertEqual(set(second["replayed"]), {"reported-1", "estimated-1"})
        self.assertEqual((sha256(ledger.read_bytes()), sha256(control.read_bytes())), before)
        self.assertNotEqual(first["receiptRef"], "")

    def test_conflicting_call_id_rolls_back_every_insert(self):
        self.import_now()
        before = sha256((self.runtime / "data/user/usage.sqlite3").read_bytes())
        changed = copy.deepcopy(self.payload)
        changed["calls"][0]["usage"]["total_tokens"] = 121
        changed["calls"].append({"callId": "new-1", "startedAt": 13, "sessionId": "", "turnId": "",
            "source": "test", "usage": {"call_id": "new-1", "total_tokens": 9, "estimated": False, "status": "completed"}})
        self.input.write_text(json.dumps(changed), encoding="utf-8")
        self.source_hash = sha256(self.input.read_bytes())
        with self.assertRaises(DeliveryError) as caught:
            self.import_now()
        self.assertEqual(caught.exception.code, "usage_import_conflict")
        self.assertEqual(sha256((self.runtime / "data/user/usage.sqlite3").read_bytes()), before)

    def test_unsettled_call_rejects_import(self):
        guard = RuntimeGuard(self.control / "guard.json")
        guard.start()
        guard.begin("unknown-1", source="test")
        with self.assertRaises(DeliveryError) as caught:
            self.import_now()
        self.assertEqual(caught.exception.code, "usage_import_unsettled")

    def test_owned_running_process_rejects_import(self):
        import os
        from tools.learning_book.budget import process_identity
        atomic(self.control / "running.json", canonical({
            "state": "running", "supervisor": process_identity(os.getpid())}))
        with self.assertRaises(DeliveryError) as caught:
            self.import_now()
        self.assertEqual(caught.exception.code, "usage_import_running")


if __name__ == "__main__":
    unittest.main()
