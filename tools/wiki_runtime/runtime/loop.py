"""S1 的持久 Event、Step、Wait 与 WorkItem 循环。"""
from __future__ import annotations

import copy
import math
import time

from tools.wiki_runtime.contracts import ContractError, digest
from .loop_protocol import (
    follow_up_digest, learning_state_digest, parse_event, parse_learning_state,
    parse_policy_revision, parse_retry_policy, parse_step, parse_step_result, parse_wait,
    parse_work_item, replay_event, replay_step_result, wait_digest,
)
from .protocol import _record, _text, parse_task
from .storage import RuntimeStore, _json, _load


_LOOP_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_states (
    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    producer TEXT NOT NULL,
    event_id TEXT NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    receipt_sequence INTEGER NOT NULL UNIQUE,
    envelope_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (producer, event_id)
);
CREATE INDEX IF NOT EXISTS events_pending
ON events(task_id, receipt_sequence);
CREATE TABLE IF NOT EXISTS steps (
    step_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS steps_task ON steps(task_id);
CREATE TABLE IF NOT EXISTS work_items (
    work_item_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    step_id TEXT NOT NULL REFERENCES steps(step_id),
    schedule_key TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS work_items_pending
ON work_items(task_id);
CREATE TABLE IF NOT EXISTS step_results (
    step_id TEXT NOT NULL REFERENCES steps(step_id),
    attempt INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (step_id, attempt, generation)
);
CREATE TABLE IF NOT EXISTS step_invocations (
    step_id TEXT NOT NULL REFERENCES steps(step_id),
    attempt INTEGER NOT NULL,
    generation INTEGER NOT NULL,
    invocation_id TEXT NOT NULL,
    binding_kind TEXT NOT NULL CHECK (binding_kind IN ('original', 'replayed')),
    PRIMARY KEY (step_id, attempt, generation)
);
CREATE TABLE IF NOT EXISTS dependency_projections (
    dependency_digest TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('current', 'stale')),
    reason TEXT
);
CREATE TABLE IF NOT EXISTS waits (
    wait_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wait_answers (
    answer_id TEXT PRIMARY KEY,
    wait_id TEXT NOT NULL REFERENCES waits(wait_id),
    answer_revision INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('accepted', 'superseded')),
    UNIQUE (wait_id, answer_revision)
);
CREATE TABLE IF NOT EXISTS retry_policies (
    step_id TEXT NOT NULL REFERENCES steps(step_id),
    failure_fingerprint TEXT NOT NULL,
    failure_count INTEGER NOT NULL CHECK (failure_count >= 1),
    record_json TEXT NOT NULL,
    PRIMARY KEY (step_id, failure_fingerprint)
);
"""


class LoopError(RuntimeError):
    pass


class LoopConflictError(LoopError):
    pass


class LoopBusyError(LoopError):
    pass


def _proposal(value, *, task_revision: int) -> dict:
    fields = ('task_revision', 'learning_state', 'task_state', 'steps', 'waits', 'work_items')
    _record(value, fields, 'LoopProposal')
    if value['task_revision'] != task_revision:
        raise LoopConflictError('规划提交的 Task revision 已变化')
    if value['task_state'] is not None:
        _text(value['task_state'], 'LoopProposal.task_state')
        if value['task_state'] in ('completed', 'canceled', 'paused'):
            raise LoopConflictError('通用规划不得直接封闭或暂停 Task；只能由受信归并／暂停协议处理')
    if (isinstance(value['learning_state'], dict)
            and value['learning_state'].get('state') == 'applied'):
        raise LoopConflictError('通用规划不得自报 applied；必须核验 Executor WAL 后归并')
    for field in ('steps', 'waits', 'work_items'):
        if type(value[field]) is not list:
            raise ContractError(f'LoopProposal.{field}: 应为数组')
    return value


def empty_proposal(task_revision: int, **changes) -> dict:
    proposal = {
        'task_revision': task_revision,
        'learning_state': None,
        'task_state': None,
        'steps': [],
        'waits': [],
        'work_items': [],
    }
    unknown = set(changes) - set(proposal)
    if unknown:
        raise ValueError(f'未知规划字段: {sorted(unknown)}')
    proposal.update(changes)
    return proposal


class RuntimeLoop:
    def __init__(self, store: RuntimeStore, *, clock=time.time):
        self.store = store
        self.clock = clock
        self.store.mutate(self._initialize)

    @staticmethod
    def _initialize(connection) -> None:
        for statement in _LOOP_SCHEMA.split(';'):
            if statement.strip():
                connection.execute(statement)

    @staticmethod
    def _task(connection, task_id: str) -> dict:
        row = connection.execute(
            'SELECT record_json FROM tasks WHERE task_id=?', (task_id,),
        ).fetchone()
        if row is None:
            raise LoopConflictError('Task 不存在: ' + task_id)
        return parse_task(_load(row['record_json']))

    @staticmethod
    def _current_stop_policy(connection, task: dict) -> dict:
        row = connection.execute(
            'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
            (task['current_policy_digest'],),
        ).fetchone()
        if row is None:
            raise LoopConflictError('Task 当前 PolicyRevision 不存在')
        return parse_policy_revision(_load(row['record_json']))['stop_policy']

    @staticmethod
    def _learning(connection, task_id: str) -> dict:
        row = connection.execute(
            'SELECT record_json FROM learning_states WHERE task_id=?', (task_id,),
        ).fetchone()
        if row is None:
            raise LoopConflictError('LearningState 不存在: ' + task_id)
        return parse_learning_state(_load(row['record_json']))

    @staticmethod
    def _save_task(connection, task: dict) -> None:
        parse_task(task)
        connection.execute(
            'UPDATE tasks SET record_json=? WHERE task_id=?',
            (_json(task), task['task_id']),
        )

    @staticmethod
    def _save_learning(connection, record: dict, task: dict) -> None:
        parse_learning_state(record)
        if (record['task_id'], record['learning_task_id']) != (
            task['task_id'], task['learning_task_id']
        ):
            raise LoopConflictError('LearningState 不得跨 Task 绑定')
        previous = connection.execute(
            'SELECT record_json FROM learning_states WHERE task_id=?', (task['task_id'],),
        ).fetchone()
        old = parse_learning_state(_load(previous['record_json']))
        if old != record:
            connection.execute(
                "INSERT INTO dependency_projections VALUES (?, 'stale', ?) "
                "ON CONFLICT(dependency_digest) DO UPDATE SET state='stale', reason=excluded.reason",
                (learning_state_digest(old), 'LearningState 已变化'),
            )
        connection.execute(
            'UPDATE learning_states SET record_json=? WHERE task_id=?',
            (_json(record), task['task_id']),
        )

    @staticmethod
    def _dependencies_current(connection, step: dict) -> bool:
        for dependency in step['dependency_digests']:
            row = connection.execute(
                'SELECT state FROM dependency_projections WHERE dependency_digest=?',
                (dependency,),
            ).fetchone()
            if row is not None and row['state'] != 'current':
                return False
        return True

    def invalidate_dependency(self, dependency_digest: str, *, reason: str) -> None:
        _text(reason, 'invalidate_dependency.reason')
        from .protocol import _hash
        _hash(dependency_digest, 'invalidate_dependency.dependency_digest')
        self.store.mutate(lambda connection: connection.execute(
            "INSERT INTO dependency_projections VALUES (?, 'stale', ?) "
            "ON CONFLICT(dependency_digest) DO UPDATE SET state='stale', reason=excluded.reason",
            (dependency_digest, reason),
        ))

    def accept_event(self, event: dict) -> dict:
        candidate = copy.deepcopy(event)
        parse_event(candidate)
        if candidate['processing_state'] != 'pending':
            raise ContractError('新 Event 必须为 pending')

        def accept(connection):
            existing = connection.execute(
                'SELECT record_json FROM events WHERE producer=? AND event_id=?',
                (candidate['producer'], candidate['event_id']),
            ).fetchone()
            if existing is not None:
                try:
                    return replay_event(_load(existing['record_json']), candidate)
                except ContractError as exc:
                    raise LoopConflictError(str(exc)) from exc
            task = self._task(connection, candidate['task_id'])
            if task['state'] in ('completed', 'canceled'):
                raise LoopConflictError('终态 Task 不接受新 Event')
            sequence = connection.execute(
                'SELECT coalesce(max(receipt_sequence), 0) + 1 FROM events'
            ).fetchone()[0]
            record = dict(candidate, receipt_sequence=sequence, processing_state='pending')
            parse_event(record)
            connection.execute(
                'INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)',
                (record['producer'], record['event_id'], record['task_id'], sequence,
                 digest({field: record[field] for field in (
                     'task_id', 'type', 'target_version', 'payload_digest',
                 )}), _json(record)),
            )
            return record

        return self.store.mutate(accept)

    def _pending_snapshot(self) -> list[dict]:
        rows = self.store.read(
            "SELECT record_json FROM events WHERE json_extract(record_json, '$.processing_state')="
            "'pending' ORDER BY receipt_sequence"
        )
        snapshot = []
        for row in rows:
            event = parse_event(_load(row['record_json']))
            task_rows = self.store.read(
                "SELECT record_json FROM tasks WHERE task_id='" + event['task_id'].replace("'", "''") + "'"
            )
            task = parse_task(_load(task_rows[0]['record_json']))
            learning_rows = self.store.read(
                "SELECT record_json FROM learning_states WHERE task_id='"
                + event['task_id'].replace("'", "''") + "'"
            )
            snapshot.append({
                'event': event,
                'task': task,
                'learning_state': parse_learning_state(_load(learning_rows[0]['record_json'])),
            })
        return snapshot

    def plan_pending(self, planner) -> list[dict]:
        if not callable(planner):
            raise TypeError('planner 必须可调用')
        snapshot = self._pending_snapshot()
        proposals = []
        for frozen in snapshot:
            proposal = planner(copy.deepcopy(frozen))
            proposals.append((frozen, proposal))
        results = []
        for frozen, proposal in proposals:
            results.append(self.store.mutate(
                lambda connection, frozen=frozen, proposal=proposal: self._commit_plan(
                    connection, frozen, proposal,
                )
            ))
        return results

    def _commit_plan(self, connection, frozen: dict, proposal: dict) -> dict:
        event = frozen['event']
        row = connection.execute(
            'SELECT record_json FROM events WHERE producer=? AND event_id=?',
            (event['producer'], event['event_id']),
        ).fetchone()
        current = replay_event(_load(row['record_json']), event)
        if current['processing_state'] == 'processed':
            return current
        if current['processing_state'] != 'pending':
            raise LoopConflictError('Event 当前不可规划')
        task = self._task(connection, event['task_id'])
        if task['state'] != 'running':
            raise LoopConflictError('只有 running Task 可以提交规划')
        learning = self._learning(connection, task['task_id'])
        if learning_state_digest(learning) != learning_state_digest(frozen['learning_state']):
            raise LoopConflictError('Event 冻结的 LearningState 已变化，必须基于新快照重新规划')
        self._apply_proposal(connection, task, proposal)
        current['processing_state'] = 'processed'
        connection.execute(
            'UPDATE events SET record_json=? WHERE producer=? AND event_id=? '
            "AND json_extract(record_json, '$.processing_state')='pending'",
            (_json(current), event['producer'], event['event_id']),
        )
        return current

    def _apply_proposal(self, connection, task: dict, proposal: dict) -> None:
        _proposal(proposal, task_revision=task['revision'])
        for step in proposal['steps']:
            parse_step(step)
            if step['task_id'] != task['task_id'] or step['state'] != 'pending':
                raise LoopConflictError('新 Step 必须属于当前 Task 且为 pending')
            if step['capability_id'] not in task['workflow_ref']['allowed_capabilities']:
                raise LoopConflictError('Step 能力不在 WorkflowRef 允许集合内')
            existing = connection.execute(
                'SELECT record_json FROM steps WHERE step_id=?', (step['step_id'],),
            ).fetchone()
            if existing is not None:
                if _load(existing['record_json']) != step:
                    raise LoopConflictError('相同 Step ID 不得绑定不同内容')
            else:
                connection.execute(
                    'INSERT INTO steps VALUES (?, ?, ?)',
                    (step['step_id'], step['task_id'], _json(step)),
                )
        for wait in proposal['waits']:
            parse_wait(wait)
            if wait['task_id'] != task['task_id'] or wait['consumption_state'] != 'pending':
                raise LoopConflictError('新 Wait 必须属于当前 Task 且为 pending')
            target = connection.execute(
                'SELECT task_id FROM steps WHERE step_id=?', (wait['target_step_id'],),
            ).fetchone()
            if target is None or target['task_id'] != task['task_id']:
                raise LoopConflictError('Wait 的 target_step_id 无效')
            connection.execute(
                'INSERT INTO waits VALUES (?, ?, ?)',
                (wait['wait_id'], wait['task_id'], _json(wait)),
            )
        for item in proposal['work_items']:
            parse_work_item(item)
            if (item['task_id'] != task['task_id'] or item['state'] != 'pending'
                    or item['claimed_by'] is not None or item['lease_expires_at'] is not None):
                raise LoopConflictError('新 WorkItem 必须为未领取的当前 Task 工作')
            step_row = connection.execute(
                'SELECT record_json FROM steps WHERE step_id=?', (item['step_id'],),
            ).fetchone()
            if step_row is None:
                raise LoopConflictError('WorkItem 引用的 Step 不存在')
            step = parse_step(_load(step_row['record_json']))
            if step['task_id'] != task['task_id'] or item['generation'] != step['generation']:
                raise LoopConflictError('WorkItem 与 Step generation 不一致')
            expected_key = f"{step['step_id']}:attempt-{step['attempt']}:generation-{step['generation']}"
            if item['schedule_key'] != expected_key:
                raise LoopConflictError('WorkItem.schedule_key 与 Step 确认键不一致')
            connection.execute(
                'INSERT INTO work_items VALUES (?, ?, ?, ?, ?)',
                (item['work_item_id'], item['task_id'], item['step_id'],
                 item['schedule_key'], _json(item)),
            )
        if proposal['learning_state'] is not None:
            self._save_learning(connection, proposal['learning_state'], task)
        if proposal['task_state'] is not None:
            changed = dict(task, state=proposal['task_state'])
            self._save_task(connection, changed)

    def schedule_step(self, step: dict) -> dict:
        candidate = copy.deepcopy(step)
        parse_step(candidate)
        if candidate['state'] != 'pending':
            raise LoopConflictError('新业务 Step 必须为 pending')

        def schedule(connection):
            existing = connection.execute(
                'SELECT record_json FROM steps WHERE step_id=?', (candidate['step_id'],)
            ).fetchone()
            if existing is not None:
                current = parse_step(_load(existing['record_json']))
                immutable = (
                    'step_id', 'task_id', 'capability_id', 'implementation_digest',
                    'input_digest', 'dependency_digests',
                )
                if any(current[field] != candidate[field] for field in immutable):
                    raise LoopConflictError('相同 Step ID 不得重绑')
                return {'step': current, 'replayed': True}
            task = self._task(connection, candidate['task_id'])
            item = {
                'work_item_id': 'work-' + candidate['step_id'],
                'task_id': candidate['task_id'], 'step_id': candidate['step_id'],
                'ready_at': self.clock(),
                'schedule_key': (
                    f"{candidate['step_id']}:attempt-{candidate['attempt']}:"
                    f"generation-{candidate['generation']}"
                ),
                'claimed_by': None, 'generation': candidate['generation'],
                'lease_expires_at': None, 'state': 'pending',
            }
            self._apply_proposal(connection, task, empty_proposal(
                task['revision'], steps=[candidate], work_items=[item],
            ))
            return {'step': candidate, 'work_item': item, 'replayed': False}

        return self.store.mutate(schedule)

    def claim_step(self, claimed_by: str, *, lease_seconds: float = 30.0,
                   now: float | None = None, invocation_id: str | None = None,
                   step_id: str | None = None) -> dict | None:
        _text(claimed_by, 'claim_step.claimed_by')
        if invocation_id is not None:
            _text(invocation_id, 'claim_step.invocation_id')
        if step_id is not None:
            _text(step_id, 'claim_step.step_id')
        if (type(lease_seconds) not in (int, float) or not math.isfinite(lease_seconds)
                or lease_seconds <= 0):
            raise ValueError('lease_seconds 必须有限且为正')
        now = self.clock() if now is None else now
        if type(now) not in (int, float) or not math.isfinite(now):
            raise ValueError('now 必须为有限时间')

        def claim(connection):
            active_tasks = {row[0] for row in connection.execute(
                'SELECT task_id FROM work_items '
                "WHERE json_extract(record_json, '$.state')='claimed' "
                'AND json_extract(record_json, \'$.lease_expires_at\')>?', (now,),
            ).fetchall()}
            candidates = connection.execute(
                'SELECT w.record_json, t.record_json AS task_json, s.record_json AS step_json '
                'FROM work_items w JOIN tasks t ON t.task_id=w.task_id '
                'JOIN steps s ON s.step_id=w.step_id '
                "WHERE json_extract(t.record_json, '$.state')='running' "
                "ORDER BY json_extract(w.record_json, '$.ready_at'), w.work_item_id"
            ).fetchall()
            blocked_tasks, busy_tasks = set(), set()
            for row in candidates:
                item = parse_work_item(_load(row['record_json']))
                if item['task_id'] in blocked_tasks or item['task_id'] in busy_tasks:
                    continue
                if step_id is not None and item['step_id'] != step_id:
                    continue
                if item['task_id'] in active_tasks:
                    recoverable = connection.execute(
                        'SELECT 1 FROM step_invocations si '
                        'JOIN invocations i ON i.invocation_id=si.invocation_id '
                        'JOIN steps s ON s.step_id=si.step_id '
                        'WHERE si.step_id=? AND si.generation=? '
                        "AND si.attempt=json_extract(s.record_json, '$.attempt') "
                        "AND json_extract(i.record_json, '$.result_state')='succeeded'",
                        (item['step_id'], item['generation']),
                    ).fetchone()
                    if recoverable is None:
                        continue
                if item['state'] not in ('pending', 'claimed'):
                    continue
                if item['state'] == 'pending' and item['ready_at'] > now:
                    continue
                task = parse_task(_load(row['task_json']))
                step = parse_step(_load(row['step_json']))
                stop_policy = self._current_stop_policy(connection, task)
                if (not self._dependencies_current(connection, step)
                        or step['attempt'] > stop_policy['max_step_attempts']):
                    step['state'] = item['state'] = 'blocked'
                    connection.execute(
                        'UPDATE steps SET record_json=? WHERE step_id=?',
                        (_json(step), step['step_id']),
                    )
                    connection.execute(
                        'UPDATE work_items SET record_json=? WHERE work_item_id=?',
                        (_json(item), item['work_item_id']),
                    )
                    self._save_task(connection, dict(task, state='blocked'))
                    blocked_tasks.add(task['task_id'])
                    continue
                takeover = item['state'] == 'claimed'
                bound_invocation = invocation_id
                if takeover:
                    previous = connection.execute(
                        'SELECT invocation_id FROM step_invocations '
                        'WHERE step_id=? AND attempt=? AND generation=?',
                        (step['step_id'], step['attempt'], step['generation']),
                    ).fetchone()
                    if previous is None:
                        raise LoopConflictError('接管必须绑定原 generation 的 Invocation')
                    bound_invocation = previous['invocation_id']
                    invocation_row = connection.execute(
                        'SELECT record_json FROM invocations WHERE invocation_id=?',
                        (bound_invocation,),
                    ).fetchone()
                    if invocation_row is None:
                        raise LoopConflictError('接管绑定的原 Invocation 不存在')
                    from .protocol import parse_invocation
                    invocation = parse_invocation(_load(invocation_row['record_json']))
                    if invocation['result_state'] == 'pending':
                        busy_tasks.add(task['task_id'])
                        continue
                    if invocation['result_state'] == 'unknown':
                        step['state'] = item['state'] = 'blocked'
                        connection.execute(
                            'UPDATE steps SET record_json=? WHERE step_id=?',
                            (_json(step), step['step_id']),
                        )
                        connection.execute(
                            'UPDATE work_items SET record_json=? WHERE work_item_id=?',
                            (_json(item), item['work_item_id']),
                        )
                        self._save_task(connection, dict(task, state='blocked'))
                        return {'invocation_unknown': True, 'step_id': step['step_id']}
                    if invocation['result_state'] != 'succeeded':
                        raise LoopConflictError('只有原 Invocation 成功时才允许接管归并')
                    item['generation'] += 1
                    step['generation'] += 1
                elif invocation_id is not None and connection.execute(
                    'SELECT 1 FROM step_invocations WHERE invocation_id=?', (invocation_id,),
                ).fetchone() is not None:
                    raise LoopConflictError('新业务 attempt 不得复用已绑定的 Invocation ID')
                item.update(
                    claimed_by=claimed_by, lease_expires_at=now + lease_seconds, state='claimed',
                )
                item['schedule_key'] = (
                    f"{step['step_id']}:attempt-{step['attempt']}:generation-{step['generation']}"
                )
                step['state'] = 'running'
                updated = connection.execute(
                    'UPDATE work_items SET record_json=?, schedule_key=? WHERE work_item_id=? '
                    "AND json_extract(record_json, '$.generation')=?",
                    (_json(item), item['schedule_key'], item['work_item_id'],
                     item['generation'] - int(takeover)),
                )
                if updated.rowcount != 1:
                    return None
                connection.execute(
                    'UPDATE steps SET record_json=? WHERE step_id=? '
                    "AND json_extract(record_json, '$.generation')=?",
                    (_json(step), step['step_id'], step['generation'] - int(takeover)),
                )
                if bound_invocation is not None:
                    connection.execute(
                        'INSERT INTO step_invocations VALUES (?, ?, ?, ?, ?)',
                        (step['step_id'], step['attempt'], step['generation'], bound_invocation,
                         'replayed' if takeover else 'original'),
                    )
                return {
                    'work_item': item, 'step': step, 'task': task,
                    'takeover': takeover, 'requires_invocation_replay': takeover,
                    'invocation_id': bound_invocation,
                }
            return None

        claimed = self.store.mutate(claim)
        if claimed is not None and claimed.get('invocation_unknown'):
            raise LoopConflictError('原 Invocation 为 unknown；Step 已阻断，禁止无限换代或重发')
        return claimed

    def submit_step_result(self, result: dict, *, work_item_id: str, claimed_by: str,
                           proposal: dict | None = None, now: float | None = None,
                           invocation_id: str | None = None) -> dict:
        candidate = copy.deepcopy(result)
        parse_step_result(candidate)
        now = self.clock() if now is None else now

        def submit(connection):
            existing = connection.execute(
                'SELECT record_json FROM step_results WHERE step_id=? AND attempt=? AND generation=?',
                (candidate['step_id'], candidate['attempt'], candidate['generation']),
            ).fetchone()
            if existing is not None:
                try:
                    return replay_step_result(_load(existing['record_json']), candidate)
                except ContractError as exc:
                    raise LoopConflictError(str(exc)) from exc
            item_row = connection.execute(
                'SELECT record_json FROM work_items WHERE work_item_id=?', (work_item_id,),
            ).fetchone()
            step_row = connection.execute(
                'SELECT record_json FROM steps WHERE step_id=?', (candidate['step_id'],),
            ).fetchone()
            if item_row is None or step_row is None:
                raise LoopConflictError('StepResult 的 Step／WorkItem 不存在')
            item = parse_work_item(_load(item_row['record_json']))
            step = parse_step(_load(step_row['record_json']))
            if (item['step_id'] != step['step_id'] or item['state'] != 'claimed'
                    or item['claimed_by'] != claimed_by
                    or item['generation'] != candidate['generation']
                    or item['lease_expires_at'] <= now):
                raise LoopConflictError('StepResult 的 WorkItem 领取身份或 generation 已失效')
            if (step['attempt'], step['generation']) != (
                candidate['attempt'], candidate['generation']
            ) or step['input_digest'] != candidate['input_digest']:
                raise LoopConflictError('StepResult 的 attempt／generation／input_digest 不匹配')
            if not self._dependencies_current(connection, step):
                raise LoopConflictError('StepResult 的依赖已失效')
            binding = connection.execute(
                'SELECT invocation_id, binding_kind FROM step_invocations '
                'WHERE step_id=? AND attempt=? AND generation=?',
                (step['step_id'], step['attempt'], step['generation']),
            ).fetchone()
            if binding is None:
                if invocation_id is not None:
                    raise LoopConflictError('StepResult 的 Invocation 未在领取时绑定')
            else:
                if invocation_id != binding['invocation_id']:
                    raise LoopConflictError('StepResult 必须使用领取时绑定的 Invocation')
                from .protocol import parse_invocation
                invocation_row = connection.execute(
                    'SELECT record_json FROM invocations WHERE invocation_id=?', (invocation_id,),
                ).fetchone()
                if invocation_row is None:
                    raise LoopConflictError('绑定的 Invocation 不存在')
                invocation = parse_invocation(_load(invocation_row['record_json']))
                if invocation['result_state'] != 'succeeded':
                    raise LoopConflictError('pending／unknown Invocation 不得归并为成功 StepResult')
                if invocation['result'].get('step_result_digest') != candidate['result_digest']:
                    raise LoopConflictError('Invocation 实际返回未绑定 StepResult 业务内容摘要')
                spec = invocation['spec']
                if (spec['task_id'] != step['task_id']
                        or spec['input_digest'] != step['input_digest']):
                    raise LoopConflictError('Invocation 的 Task 或输入与 Step 不匹配')
            for artifact in candidate['artifact_digests']:
                if connection.execute(
                    'SELECT 1 FROM artifacts WHERE artifact_digest=?', (artifact,),
                ).fetchone() is None:
                    raise LoopConflictError('StepResult 引用了未发布产物')
            task = self._task(connection, step['task_id'])
            if task['state'] != 'running':
                raise LoopConflictError('只有 running Task 可以接受新 StepResult')
            selected = empty_proposal(task['revision']) if proposal is None else proposal
            _proposal(selected, task_revision=task['revision'])
            expected_follow_ups = set()
            for follow_up in selected['work_items']:
                follow_step = next(
                    (item for item in selected['steps']
                     if item['step_id'] == follow_up['step_id']), None,
                )
                if follow_step is None:
                    follow_row = connection.execute(
                        'SELECT record_json FROM steps WHERE step_id=?', (follow_up['step_id'],)
                    ).fetchone()
                    if follow_row is None:
                        raise LoopConflictError('后续 WorkItem 缺少对应 Step 定义')
                    follow_step = parse_step(_load(follow_row['record_json']))
                expected_follow_ups.add(follow_up_digest(follow_step, follow_up))
            if expected_follow_ups != set(candidate['follow_up_digests']):
                raise LoopConflictError('StepResult.follow_up_digests 与实际后续工作不一致')
            if len(selected['waits']) > 1:
                raise LoopConflictError('一个 StepResult 最多创建一个 Wait')
            expected_wait = wait_digest(selected['waits'][0]) if selected['waits'] else None
            if candidate['wait_request_digest'] != expected_wait:
                raise LoopConflictError('StepResult.wait_request_digest 与实际 Wait 不一致')
            expected_domain = (
                learning_state_digest(selected['learning_state'])
                if selected['learning_state'] is not None else None
            )
            if candidate['domain_change_digest'] != expected_domain:
                raise LoopConflictError('StepResult.domain_change_digest 与领域变化不一致')
            if candidate['failure'] is not None and (
                selected['steps'] or selected['waits'] or selected['work_items']
                or selected['learning_state'] is not None or selected['task_state'] is not None
            ):
                raise LoopConflictError('失败 StepResult 不得携带后续业务变更')
            connection.execute(
                'INSERT INTO step_results VALUES (?, ?, ?, ?)',
                (candidate['step_id'], candidate['attempt'], candidate['generation'],
                 _json(candidate)),
            )
            step['result_digest'] = candidate['result_digest']
            if candidate['failure'] is not None:
                step['state'] = item['state'] = 'blocked'
                self._record_failure(connection, task, step, candidate['failure'], now)
            elif selected['waits']:
                step['state'] = 'waiting'
                item['state'] = 'completed'
                selected['task_state'] = 'waiting'
            else:
                step['state'] = 'completed'
                item['state'] = 'completed'
            connection.execute(
                'UPDATE steps SET record_json=? WHERE step_id=?', (_json(step), step['step_id']),
            )
            connection.execute(
                'UPDATE work_items SET record_json=? WHERE work_item_id=?',
                (_json(item), item['work_item_id']),
            )
            self._apply_proposal(connection, task, selected)
            return candidate

        return self.store.mutate(submit)

    def _record_failure(self, connection, task: dict, step: dict, failure: dict,
                        now: float) -> None:
        policy_row = connection.execute(
            'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
            (task['current_policy_digest'],),
        ).fetchone()
        policy = _load(policy_row['record_json'])['stop_policy']
        row = connection.execute(
            'SELECT failure_count FROM retry_policies WHERE step_id=? AND failure_fingerprint=?',
            (step['step_id'], failure['fingerprint']),
        ).fetchone()
        count = 1 if row is None else row['failure_count'] + 1
        stopped = (step['attempt'] >= policy['max_step_attempts']
                   or count >= policy['identical_failure_limit']
                   or failure['category'] in ('evidence', 'wait'))
        retry = {
            'error_category': failure['category'],
            'failure_fingerprint': failure['fingerprint'],
            'attempt_limit': policy['max_step_attempts'],
            'not_before': now,
            'stop_reason': failure['reason'] if stopped else None,
        }
        parse_retry_policy(retry)
        connection.execute(
            'INSERT INTO retry_policies VALUES (?, ?, ?, ?) '
            'ON CONFLICT(step_id, failure_fingerprint) DO UPDATE SET '
            'failure_count=excluded.failure_count, record_json=excluded.record_json',
            (step['step_id'], failure['fingerprint'], count, _json(retry)),
        )
        if stopped:
            blocked = dict(task, state='blocked')
            self._save_task(connection, blocked)

    def retry_step(self, step_id: str, failure_fingerprint: str) -> dict:
        def retry(connection):
            step_row = connection.execute(
                'SELECT record_json FROM steps WHERE step_id=?', (step_id,),
            ).fetchone()
            policy_row = connection.execute(
                'SELECT record_json, failure_count FROM retry_policies '
                'WHERE step_id=? AND failure_fingerprint=?', (step_id, failure_fingerprint),
            ).fetchone()
            if step_row is None or policy_row is None:
                raise LoopConflictError('RetryPolicy 或 Step 不存在')
            step = parse_step(_load(step_row['record_json']))
            policy = parse_retry_policy(_load(policy_row['record_json']))
            task = self._task(connection, step['task_id'])
            current = self._current_stop_policy(connection, task)
            if (task['state'] != 'running' or step['state'] != 'blocked'
                    or policy['stop_reason'] is not None
                    or step['attempt'] >= min(
                        policy['attempt_limit'], current['max_step_attempts'])
                    or policy_row['failure_count'] >= current['identical_failure_limit']):
                raise LoopConflictError('RetryPolicy 已停止或 Step 当前不可重试')
            step['attempt'] += 1
            step['generation'] += 1
            step['state'] = 'pending'
            step['result_digest'] = None
            item = {
                'work_item_id': f"{step_id}:retry-{step['attempt']}-{step['generation']}",
                'task_id': step['task_id'], 'step_id': step_id,
                'ready_at': policy['not_before'],
                'schedule_key': f"{step_id}:attempt-{step['attempt']}:generation-{step['generation']}",
                'claimed_by': None, 'generation': step['generation'],
                'lease_expires_at': None, 'state': 'pending',
            }
            parse_work_item(item)
            connection.execute(
                'UPDATE steps SET record_json=? WHERE step_id=?', (_json(step), step_id),
            )
            connection.execute(
                'INSERT INTO work_items VALUES (?, ?, ?, ?, ?)',
                (item['work_item_id'], item['task_id'], item['step_id'],
                 item['schedule_key'], _json(item)),
            )
            return {'step': step, 'work_item': item}

        return self.store.mutate(retry)

    def answer_wait(self, answer: dict, *, proposal: dict | None = None) -> dict:
        fields = (
            'answer_id', 'wait_id', 'answer_revision', 'answer_digest', 'answer_ref',
            'knowledge_version', 'question_version', 'rubric_version',
        )
        _record(answer, fields, 'WaitAnswer')
        for field in ('answer_id', 'wait_id'):
            _text(answer[field], 'WaitAnswer.' + field)
        for field in ('answer_revision', 'knowledge_version', 'question_version', 'rubric_version'):
            if type(answer[field]) is not int or answer[field] < 1:
                raise ContractError('WaitAnswer.' + field + ': 应为正整数')
        from .protocol import _hash, _nullable_text
        _hash(answer['answer_digest'], 'WaitAnswer.answer_digest')
        _nullable_text(answer['answer_ref'], 'WaitAnswer.answer_ref')

        def respond(connection):
            existing = connection.execute(
                'SELECT record_json, state FROM wait_answers WHERE answer_id=?',
                (answer['answer_id'],),
            ).fetchone()
            if existing is not None:
                if _load(existing['record_json']) != answer:
                    raise LoopConflictError('相同 answer_id 不得绑定不同回答')
                return {'answer': copy.deepcopy(answer), 'state': existing['state'],
                        'replayed': True}
            wait_row = connection.execute(
                'SELECT record_json FROM waits WHERE wait_id=?', (answer['wait_id'],),
            ).fetchone()
            if wait_row is None:
                raise LoopConflictError('Wait 不存在')
            wait = parse_wait(_load(wait_row['record_json']))
            task = self._task(connection, wait['task_id'])
            learning = self._learning(connection, task['task_id'])
            previous = connection.execute(
                'SELECT max(answer_revision) FROM wait_answers WHERE wait_id=?',
                (wait['wait_id'],),
            ).fetchone()[0]
            if previous is not None and answer['answer_revision'] <= previous:
                raise LoopConflictError('回答修订必须递增')
            versions = (answer['knowledge_version'], answer['question_version'],
                        answer['rubric_version'])
            expected = (learning['knowledge_version'], wait['question_version'],
                        wait['rubric_version'])
            current = (versions == expected and wait['knowledge_version'] == learning['knowledge_version']
                       and wait['consumption_state'] != 'superseded'
                       and task['state'] in ('waiting', 'running'))
            if wait['consumption_state'] == 'consumed' and wait['answer_policy'] != 'ordered_revisions':
                current = False
            state = 'accepted' if current else 'superseded'
            if current:
                selected = empty_proposal(task['revision']) if proposal is None else proposal
                _proposal(selected, task_revision=task['revision'])
                if not selected['work_items']:
                    raise LoopConflictError('有效回答必须登记后续判分工作')
                wait['consumption_state'] = 'consumed'
                connection.execute(
                    'UPDATE waits SET record_json=? WHERE wait_id=?', (_json(wait), wait['wait_id']),
                )
                selected['task_state'] = 'running'
                self._apply_proposal(connection, task, selected)
            elif proposal is not None:
                raise LoopConflictError('过期回答不得携带后续工作')
            connection.execute(
                'INSERT INTO wait_answers VALUES (?, ?, ?, ?, ?)',
                (answer['answer_id'], answer['wait_id'], answer['answer_revision'],
                 _json(answer), state),
            )
            return {'answer': copy.deepcopy(answer), 'state': state, 'replayed': False}

        return self.store.mutate(respond)
