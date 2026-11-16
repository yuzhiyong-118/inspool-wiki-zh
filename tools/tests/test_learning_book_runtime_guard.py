"""运行门禁故障与并发计量；不调用模型。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from tools.learning_book.contracts import DeliveryError
from tools.learning_book.runtime_guard import RuntimeGuard, watchdog


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / 'usage.sqlite3'
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('CREATE TABLE llm_calls (call_id TEXT, usage_json TEXT)')
        self.owner = {'processId': 123, 'startedToken': 'a', 'executable': 'test'}
        self.stamp = 100.
        self.budget = self.root / 'budget.json'
        self.budget.write_text(json.dumps(dict(contextId='test', scope={}, ledger=str(self.ledger),
            baselineCallIds=[], pauseAt=80, limit=100)), encoding='utf-8')
        self.config = dict(controlDatabase=str(self.root/'control.sqlite3'), budget=str(self.budget),
                           scope={}, leaseSeconds=5, callTimeoutSeconds=20)
        self.guard = RuntimeGuard(self.config, clock=lambda: self.stamp, identity=lambda pid: self.owner)
        self.guard.initialize()
        self.guard.start(self.owner)

    def row(self, call, total):
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('INSERT INTO llm_calls VALUES (?, ?)', (call, json.dumps({'total_tokens':total})))

    def fails(self, code, fn):
        with self.assertRaises(DeliveryError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def test_idle_reading_and_restart_preserve_cumulative(self):
        self.row('historical', 12)
        for _ in range(100):
            self.stamp += 2
            self.guard.poll(supervisor=True)
        self.guard.start(self.owner)
        self.assertEqual(self.guard.status()['position']['totalTokens'], 12)

    def test_threshold_and_restart_cannot_clear_limit(self):
        self.row('x', 80)
        self.fails('budget_pause', lambda: self.guard.begin('new'))
        self.assertEqual(self.guard.status()['events'][-1]['reason'], 'budget_pause')
        self.fails('budget_pause', lambda: self.guard.start(self.owner))

    def test_missing_usage_and_corruption(self):
        self.guard.begin('x')
        self.fails('call_usage_missing', lambda: self.guard.finish('x'))
        self.fails('unsettled_calls', lambda: self.guard.start(self.owner))
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('DROP TABLE llm_calls')
        self.fails('call_usage_missing', self.guard.poll)

    def test_budget_pause_keeps_watchdog_alive_but_blocks_generation(self):
        self.row('x', 80)
        stopped = threading.Event()
        done, thread = watchdog(self.guard, stopped.set, interval=.01)
        self.assertFalse(stopped.wait(.05))
        done.set(); thread.join(2)
        self.fails('budget_pause', lambda: self.guard.begin('new'))

    def test_supervisor_loss_closes_admission_and_watchdog(self):
        self.stamp += 6
        stopped = threading.Event()
        done, thread = watchdog(self.guard, stopped.set, interval=.01)
        self.assertTrue(stopped.wait(2))
        done.set(); thread.join(2)
        self.fails('supervisor_lost', lambda: self.guard.begin('x'))

    def test_dead_supervisor_does_not_wait_for_lease(self):
        self.guard.identity = lambda pid: {**self.owner, 'startedToken':'reused'}
        self.fails('supervisor_lost', lambda: self.guard.begin('x'))

    def test_actual_active_timeout_and_unsettled_restart(self):
        self.guard.begin('slow')
        for _ in range(11):
            self.stamp += 2
            try:
                self.guard.poll(supervisor=True)
            except DeliveryError as exc:
                self.assertEqual(exc.code, 'active_call_timeout')
                break
        self.assertEqual(self.guard.status()['blocked'], 'active_call_timeout')
        self.fails('unsettled_calls', lambda: self.guard.start(self.owner))

    def test_parallel_membership_no_double_count_and_ledger_regression(self):
        self.guard.begin('a', turn_id='op-a', source='compile')
        self.guard.begin('b', turn_id='op-b', source='chat')
        self.row('a', 10); self.row('b', 20)
        self.guard.finish('b'); self.guard.finish('a')
        status = self.guard.status()
        self.assertEqual(sum(c['tokens'] for c in status['calls']), 30)
        self.assertEqual(status['position']['totalTokens'], 30)
        self.assertEqual(status['unattributedCallCount'], 0)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("DELETE FROM llm_calls WHERE call_id='a'")
        self.fails('usage_unknown', self.guard.poll)

    def test_control_db_loss_not_reinitialized_by_call(self):
        self.guard.database.unlink()
        self.fails('guard_unobservable', lambda: self.guard.begin('x'))


if __name__ == '__main__':
    unittest.main()
