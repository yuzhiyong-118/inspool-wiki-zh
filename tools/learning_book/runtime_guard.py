"""本机单 worker 的模型调用门禁。只保存监督事实，token 正本仍为上游账本。"""
from __future__ import annotations

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

from .budget import Budget, process_identity
from .contracts import DeliveryError, read_json


class RuntimeGuard:
    def __init__(self, config, *, clock=time.time, identity=process_identity):
        self.config = read_json(config) if isinstance(config, (str, Path)) else config
        self.database = Path(self.config["controlDatabase"]).resolve()
        self.clock, self.identity = clock, identity
        self.budget = Budget(read_json(self.config["budget"]), self.config["scope"], stop=lambda: None)
        self.lease = float(self.config.get("leaseSeconds", 5))
        self.timeout = float(self.config.get("callTimeoutSeconds", 600))
        if not 1 <= self.lease <= 30 or not 1 <= self.timeout <= 3600:
            raise DeliveryError("guard_config", "监督租约／调用时限无效")

    @contextmanager
    def transaction(self):
        # mode=rw：丢失控制库不得悄悄创建一个空库绕过门禁。
        try:
            db = sqlite3.connect(self.database.as_uri() + "?mode=rw", uri=True, timeout=2)
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            finally:
                db.close()
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
            raise DeliveryError("guard_unobservable", "无法读取运行监督状态", "failed") from exc

    def initialize(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (call_id TEXT PRIMARY KEY, started REAL NOT NULL,
                    finished REAL, state TEXT NOT NULL, session_id TEXT, turn_id TEXT, source TEXT);
                CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, stamp REAL, reason TEXT);
            """)

    @staticmethod
    def _read(db):
        row = db.execute("SELECT value FROM control WHERE id=1").fetchone()
        if row is None:
            raise DeliveryError("guard_not_started", "监督器尚未启动", "failed")
        return json.loads(row[0])

    @staticmethod
    def _write(db, value):
        db.execute("INSERT OR REPLACE INTO control VALUES (1, ?)", (json.dumps(value, allow_nan=False),))

    def _reason(self, db, control, *, heartbeat=True):
        if control.get("blocked"):
            return control["blocked"]
        if control.get("budgetDigest") != self._budget_digest():
            return "budget_config_changed"
        if heartbeat:
            age = self.clock() - control["heartbeat"]
            if age < -1 or age > self.lease:
                return "supervisor_lost"
            try:
                owner = self.identity(control["owner"]["processId"])
                if any(owner[k] != control["owner"][k] for k in ("processId", "startedToken", "executable")):
                    return "supervisor_lost"
            except DeliveryError:
                return "supervisor_lost"
        self.budget.floor = control.get("floor", {})
        position = self.budget.position()
        reason = self.budget.reason(position)
        if reason:
            return reason
        control["position"] = position
        control["floor"] = position["countedCalls"]
        for call_id, started in db.execute("SELECT call_id, started FROM calls WHERE state='active'"):
            if call_id not in position["countedCalls"] and self.clock() - started > self.timeout:
                return "active_call_timeout"
        return None

    def _budget_digest(self):
        from .contracts import digest
        # Fresh read detects changes; explicit restart is needed to apply an authorized budget change.
        return digest({k:v for k,v in read_json(self.config["budget"]).items() if k != 'stopProcess'})

    def _block(self, db, control, reason):
        if not control.get("blocked"):
            control["blocked"] = reason
            db.execute("INSERT INTO events(stamp, reason) VALUES (?, ?)", (self.clock(), reason))
        self._write(db, control)

    def start(self, owner=None):
        # 初始化由安装／显式接入完成。运行期间丢库不能自动丢弃历史 floor。
        position = self.budget.check()
        with self.transaction() as db:
            row = db.execute("SELECT value FROM control WHERE id=1").fetchone()
            old = json.loads(row[0]) if row else {}
            if old:
                self.budget.floor = old.get("floor", {})
                position = self.budget.check()
            unsettled = list(db.execute("SELECT call_id, state FROM calls WHERE state IN ('active','metering_unknown')"))
            active = {r[0] for r in unsettled}
            if any(state == 'metering_unknown' and not self._reported_call(call_id)
                   for call_id, state in unsettled):
                raise DeliveryError("unsettled_calls", "上次流式调用缺供应商用量；不能用估算解除暂停", "uncertain")
            if active - position["countedCalls"].keys():
                raise DeliveryError("unsettled_calls", "上次存在未计量在途调用；先核对实际用量，不能重置预算", "uncertain")
            db.execute("UPDATE calls SET state='settled_after_restart' WHERE state IN ('active','metering_unknown')")
            self._write(db, {"owner": owner or self.identity(os.getpid()), "heartbeat": self.clock(),
                "budgetDigest": self._budget_digest(), "blocked": None,
                "floor": position["countedCalls"], "position": position})

    def poll(self, *, supervisor=False):
        with self.transaction() as db:
            control = self._read(db)
            reason = self._reason(db, control)
            if reason:
                self._block(db, control, reason)
            else:
                if supervisor:
                    control["heartbeat"] = self.clock()
                self._write(db, control)
        if reason:
            raise DeliveryError(reason, "模型调用已暂停；查看运行状态和停止记录", "failed")
        return control

    def begin(self, call_id, *, session_id="", turn_id="", source=""):
        with self.transaction() as db:
            control = self._read(db)
            reason = self._reason(db, control)
            if reason:
                self._block(db, control, reason)
            else:
                db.execute("INSERT INTO calls VALUES (?, ?, NULL, 'active', ?, ?, ?)",
                           (call_id, self.clock(), session_id, turn_id, source))
                self._write(db, control)
        if reason:
            raise DeliveryError(reason, "模型调用前门禁关闭", "failed")

    def _reported_call(self, call_id):
        try:
            with closing(sqlite3.connect(self.budget.ledger.as_uri() + '?mode=ro', uri=True, timeout=2)) as ledger:
                row = ledger.execute('SELECT usage_json FROM llm_calls WHERE call_id=?', (call_id,)).fetchone()
            value = json.loads(row[0]) if row else None
            return isinstance(value, dict) and value.get('estimated') is False
        except (OSError, sqlite3.Error, ValueError, TypeError):
            return False

    def finish(self, call_id, *, require_reported=False):
        with self.transaction() as db:
            control = self._read(db)
            self.budget.floor = control.get("floor", {})
            position = self.budget.position()
            reason = self.budget.reason(position)
            if (call_id not in position.get("countedCalls", {}) or
                    (require_reported and not self._reported_call(call_id))):
                reason = "call_usage_missing"
            if reason:
                self._block(db, control, reason)
            else:
                control.update(position=position, floor=position["countedCalls"])
                self._write(db, control)
            db.execute("UPDATE calls SET finished=?, state=? WHERE call_id=?",
                       (self.clock(), "metering_unknown" if reason == "call_usage_missing" else "finished", call_id))
        if reason:
            raise DeliveryError(reason, "调用结束计量触发暂停", "failed")

    def block(self, reason):
        with self.transaction() as db:
            self._block(db, self._read(db), reason)

    def status(self):
        with self.transaction() as db:
            control = self._read(db)
            calls = [dict(zip(("callId", "startedAt", "finishedAt", "state", "sessionId", "turnId", "source"), r))
                     for r in db.execute("SELECT * FROM calls ORDER BY started, call_id")]
            events = [{"at": r[0], "reason": r[1]} for r in db.execute("SELECT stamp, reason FROM events ORDER BY id")]
        self.budget.floor = control.get('floor', {})
        position = self.budget.position()
        counted = position.get("countedCalls", {})
        # Membership by unique call_id, never overlapping before/after differences.
        for call in calls:
            call["tokens"] = counted.get(call["callId"])
        return {"position": {k: v for k, v in position.items() if k != "countedCalls"},
                "pauseAt": self.budget.context["pauseAt"], "limit": self.budget.context["limit"],
                "blocked": control.get("blocked"), "heartbeat": control["heartbeat"],
                "calls": calls, "events": events,
                "unattributedCallCount": len(counted.keys() - {c["callId"] for c in calls})}


def configured_guard():
    path = os.environ.get("LEARNING_BOOK_GUARD")
    return RuntimeGuard(path) if path else None


def watchdog(guard, stop, *, interval=.25):
    """API 端独立线程：监督器失联时停止在途调用，空闲阅读没有账本超时。"""
    done = threading.Event()
    def run():
        while not done.wait(interval):
            try:
                guard.poll()
            except Exception as exc:
                from tools.learning_book.contracts import DeliveryError
                if isinstance(exc, DeliveryError) and exc.code in ('budget_pause', 'budget_exceeded'):
                    continue
                stop()
                return
    thread = threading.Thread(target=run, name="learning-runtime-lease", daemon=True)
    thread.start()
    return done, thread
