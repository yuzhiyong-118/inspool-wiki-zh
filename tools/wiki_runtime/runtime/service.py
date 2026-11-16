"""S1 的学习状态、动态授权、Admission 绑定与执行结果归并。"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import sqlite3
import time
import uuid

from tools.wiki_runtime.contracts import digest, validate
from .invocation import (
    RuntimeInvocationPort, _concurrency_limit, _reserve_budget, _zero_budget,
)
from .loop import RuntimeLoop
from .loop_protocol import parse_learning_state, parse_policy_revision, runtime_binding_valid
from .protocol import (
    _hash, _record, _text, admission_digest, check_execution_ownership,
    parse_admission, parse_authorization, parse_execution_ownership,
    parse_execution_result_binding, parse_readiness, parse_review_credential, parse_run,
    parse_task, project_execution_result, readiness_digest, review_credential_digest,
    validate_execution_result_binding,
)
from .storage import RuntimeStore, RuntimeStoreError, _json, _load


_SERVICE_SCHEMA = """
CREATE TABLE IF NOT EXISTS readiness_records (
    readiness_digest TEXT PRIMARY KEY,
    learning_task_id TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS readiness_records_no_update
BEFORE UPDATE OF record_json ON readiness_records
BEGIN SELECT RAISE(ABORT, 'Readiness content is immutable'); END;
CREATE TABLE IF NOT EXISTS readiness_projections (
    readiness_digest TEXT PRIMARY KEY REFERENCES readiness_records(readiness_digest),
    state TEXT NOT NULL CHECK (state IN ('current', 'stale', 'superseded')),
    reason TEXT
);
CREATE TABLE IF NOT EXISTS review_credentials (
    credential_id TEXT PRIMARY KEY,
    learning_task_id TEXT NOT NULL,
    credential_digest TEXT NOT NULL UNIQUE,
    record_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS review_credentials_no_update
BEFORE UPDATE OF record_json ON review_credentials
BEGIN SELECT RAISE(ABORT, 'ReviewCredential content is immutable'); END;
CREATE TABLE IF NOT EXISTS credential_projections (
    credential_id TEXT PRIMARY KEY REFERENCES review_credentials(credential_id),
    state TEXT NOT NULL CHECK (state IN ('valid', 'invalid')),
    reason TEXT
);
CREATE TABLE IF NOT EXISTS unattested_review_evidence (
    evidence_id TEXT PRIMARY KEY,
    learning_task_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authorizations (
    authorization_ref TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    operation_id TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS authorizations_operation
ON authorizations(operation_id, authorization_ref);
CREATE TABLE IF NOT EXISTS operation_admissions (
    operation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    admission_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    binding_state TEXT NOT NULL CHECK (binding_state IN ('active', 'superseded_by_pause'))
);
CREATE TRIGGER IF NOT EXISTS operation_admissions_no_rebind
BEFORE UPDATE OF admission_digest, record_json ON operation_admissions
BEGIN SELECT RAISE(ABORT, 'operation admission binding is immutable'); END;
CREATE TABLE IF NOT EXISTS execution_results (
    operation_id TEXT PRIMARY KEY,
    admission_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    result_digest TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_bindings (
    operation_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(task_id),
    binding_digest TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS maintenance_bindings_no_rebind
BEFORE UPDATE OF binding_digest, record_json ON maintenance_bindings
BEGIN SELECT RAISE(ABORT, 'maintenance binding is immutable'); END;
CREATE TABLE IF NOT EXISTS maintenance_results (
    operation_id TEXT PRIMARY KEY,
    binding_digest TEXT NOT NULL,
    record_json TEXT NOT NULL,
    result_digest TEXT NOT NULL
);
"""


class RuntimeServiceError(RuntimeError):
    pass


class AuthorizationError(RuntimeServiceError):
    pass


class AdmissionError(RuntimeServiceError):
    pass


class ExecutionReconcileError(RuntimeServiceError):
    pass


class RuntimeService:
    def __init__(self, store: RuntimeStore, *, executor=None, clock=time.time):
        self.store = store
        self.executor = executor
        self.clock = clock
        self.port = RuntimeInvocationPort(store, clock=clock)
        self.loop = RuntimeLoop(store, clock=clock)
        self.store.mutate(self._initialize)

    @staticmethod
    def _initialize(connection) -> None:
        statement = ''
        for line in _SERVICE_SCHEMA.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                connection.execute(statement)
                statement = ''
        if statement.strip():
            raise RuntimeServiceError('service schema v1 定义不完整')

    @contextmanager
    def _barrier(self):
        if self.executor is None:
            raise RuntimeServiceError('该动态操作需要配置 Executor acceptance_barrier')
        with self.executor.acceptance_barrier():
            yield

    @staticmethod
    def _task_row(connection, task_id: str):
        row = connection.execute(
            'SELECT * FROM tasks WHERE task_id=?', (task_id,),
        ).fetchone()
        if row is None:
            raise RuntimeServiceError('Task 不存在: ' + task_id)
        return row

    def _task(self, connection, task_id: str) -> dict:
        return parse_task(_load(self._task_row(connection, task_id)['record_json']))

    @staticmethod
    def _save_task(connection, task: dict) -> None:
        parse_task(task)
        connection.execute(
            'UPDATE tasks SET record_json=?, current_policy_digest=? WHERE task_id=?',
            (_json(task), task['current_policy_digest'], task['task_id']),
        )

    def create_task(self, *, policy: dict, task: dict, run: dict, ownership: dict,
                    learning_state: dict | None, concurrency_limit: int = 1,
                    final_review_reserve: dict | None = None) -> dict:
        parse_policy_revision(policy)
        parse_task(task)
        parse_run(run)
        parse_execution_ownership(ownership)
        if learning_state is not None:
            parse_learning_state(learning_state)
        limit = _concurrency_limit(concurrency_limit)
        reserve = _reserve_budget(final_review_reserve)
        if (task['current_policy_digest'] != policy['policy_digest']
                or run['task_id'] != task['task_id']
                or run['learning_task_id'] != task['learning_task_id']
                or ownership['task_id'] != task['task_id']
                or ownership['learning_task_id'] != task['learning_task_id']
                or learning_state is not None and (
                    learning_state['task_id'] != task['task_id']
                    or learning_state['learning_task_id'] != task['learning_task_id'])):
            raise RuntimeServiceError('create_task 的 Task／Run／ownership／学习状态绑定不一致')
        if task['state'] != 'running' or run['state'] != 'running':
            raise RuntimeServiceError('新 Task 与 Run 必须为 running')
        for field, value in reserve.items():
            if value > policy['budget'][field]:
                raise RuntimeServiceError('最终审查留额不得大于 Task 预算')

        def create(connection):
            existing_policy = connection.execute(
                'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
                (policy['policy_digest'],),
            ).fetchone()
            if existing_policy is not None and _load(existing_policy['record_json']) != policy:
                raise RuntimeServiceError('PolicyRevision 摘要不匹配')
            if existing_policy is None:
                connection.execute(
                    'INSERT INTO policy_revisions VALUES (?, ?, ?)',
                    (policy['policy_digest'], policy['revision'], _json(policy)),
                )
            for table, key, value in (
                ('tasks', 'task_id', task['task_id']), ('runs', 'run_id', run['run_id']),
                ('execution_ownerships', 'task_id', ownership['task_id']),
            ):
                if connection.execute(
                    f'SELECT 1 FROM {table} WHERE {key}=?', (value,),
                ).fetchone() is not None:
                    raise RuntimeServiceError(f'相同身份不得重复创建: {value}')
            connection.execute(
                'INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)',
                (task['task_id'], task['learning_task_id'], task['current_policy_digest'],
                 _json(task), limit, _json(reserve)),
            )
            zeros = _zero_budget()
            connection.execute(
                'INSERT INTO task_finance VALUES (?, ?, ?, ?, 0, NULL)',
                (task['task_id'], _json(policy['budget']), _json(zeros), _json(zeros)),
            )
            connection.execute(
                'INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)',
                (run['run_id'], run['task_id'], run['learning_task_id'], _json(run),
                 limit, _json(reserve)),
            )
            connection.execute(
                'INSERT INTO run_finance VALUES (?, ?, ?, ?, 0, NULL)',
                (run['run_id'], _json(policy['budget']), _json(zeros), _json(zeros)),
            )
            connection.execute(
                'INSERT INTO execution_ownerships VALUES (?, ?, ?, ?, ?, ?)',
                (ownership['task_id'], ownership['learning_task_id'], ownership['owner'],
                 ownership['generation'], ownership['expires_at'], _json(ownership)),
            )
            if learning_state is not None:
                connection.execute(
                    'INSERT INTO learning_states VALUES (?, ?)',
                    (task['task_id'], _json(learning_state)),
                )
            return {
                'task': copy.deepcopy(task), 'run': copy.deepcopy(run),
                'learning_state': copy.deepcopy(learning_state),
            }

        return self.store.mutate(create)

    def accept_event(self, event: dict) -> dict:
        return self.loop.accept_event(event)

    def plan_pending(self, planner) -> list[dict]:
        return self.loop.plan_pending(planner)

    def claim_step(self, claimed_by: str, **kwargs) -> dict | None:
        return self.loop.claim_step(claimed_by, **kwargs)

    def submit_step_result(self, result: dict, **kwargs) -> dict:
        return self.loop.submit_step_result(result, **kwargs)

    def answer_wait(self, answer: dict, *, proposal: dict | None = None) -> dict:
        return self.loop.answer_wait(answer, proposal=proposal)

    def switch_policy(self, task_id: str, policy: dict) -> dict:
        parse_policy_revision(policy)

        def switch(connection):
            existing = connection.execute(
                'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
                (policy['policy_digest'],),
            ).fetchone()
            if existing is not None and _load(existing['record_json']) != policy:
                raise RuntimeServiceError('PolicyRevision 摘要不匹配')
            if existing is None:
                connection.execute(
                    'INSERT INTO policy_revisions VALUES (?, ?, ?)',
                    (policy['policy_digest'], policy['revision'], _json(policy)),
                )
            task = self._task(connection, task_id)
            if policy['policy_digest'] == task['current_policy_digest']:
                return task
            current = self._policy(connection, task['current_policy_digest'])
            if policy['revision'] <= current['revision']:
                raise RuntimeServiceError('Task 只能切换到更新的 PolicyRevision')
            task['current_policy_digest'] = policy['policy_digest']
            task['revision'] += 1
            self._save_task(connection, task)
            from .protocol import _BUDGET_FIELDS

            def update_budget(table, key, identity, reserve):
                row = connection.execute(
                    f'SELECT * FROM {table} WHERE {key}=?', (identity,),
                ).fetchone()
                account = {
                    'reserved': _load(row['reserved_json']), 'actual': _load(row['actual_json']),
                    'blocked': bool(row['blocked']), 'block_reason': row['block_reason'],
                }
                shortfall = []
                for field in _BUDGET_FIELDS:
                    committed = account['reserved'][field] + account['actual'][field]
                    if committed > policy['budget'][field] or reserve[field] > policy['budget'][field]:
                        shortfall.append(field)
                if shortfall and not account['blocked']:
                    account['blocked'] = True
                    account['block_reason'] = '新策略低于已承诺消耗或最终留额: ' + ','.join(shortfall)
                connection.execute(
                    f'UPDATE {table} SET budget_json=?, blocked=?, block_reason=? WHERE {key}=?',
                    (_json(policy['budget']), int(account['blocked']),
                     account['block_reason'], identity),
                )

            task_row = self._task_row(connection, task_id)
            update_budget('task_finance', 'task_id', task_id,
                          _load(task_row['final_review_reserve_json']))
            runs = connection.execute(
                'SELECT run_id, final_review_reserve_json FROM runs WHERE task_id=? '
                "AND json_extract(record_json, '$.state')='running'", (task_id,),
            ).fetchall()
            for run in runs:
                update_budget('run_finance', 'run_id', run['run_id'],
                              _load(run['final_review_reserve_json']))
            return task

        return self.store.mutate(switch)

    def save_readiness(self, record: dict) -> dict:
        parse_readiness(record)
        if record['state'] != 'current':
            raise RuntimeServiceError('只保存内容为 current 的 Readiness；失效写状态投影')
        digest_value = readiness_digest(record)

        def save(connection):
            existing = connection.execute(
                'SELECT record_json FROM readiness_records WHERE readiness_digest=?',
                (digest_value,),
            ).fetchone()
            if existing is not None:
                if _load(existing['record_json']) != record:
                    raise RuntimeServiceError('Readiness 摘要绑定冲突')
                return record
            connection.execute(
                'INSERT INTO readiness_records VALUES (?, ?, ?)',
                (digest_value, record['learning_task_id'], _json(record)),
            )
            connection.execute(
                'INSERT INTO readiness_projections VALUES (?, ?, NULL)',
                (digest_value, 'current'),
            )
            return copy.deepcopy(record)

        return self.store.mutate(save)

    def save_review_credential(self, record: dict) -> dict:
        parse_review_credential(record)
        digest_value = review_credential_digest(record)

        def save(connection):
            existing = connection.execute(
                'SELECT record_json FROM review_credentials WHERE credential_id=?',
                (record['credential_id'],),
            ).fetchone()
            if existing is not None:
                if _load(existing['record_json']) != record:
                    raise RuntimeServiceError('相同 credential_id 不得重绑')
                return record
            connection.execute(
                'INSERT INTO review_credentials VALUES (?, ?, ?, ?)',
                (record['credential_id'], record['learning_task_id'], digest_value, _json(record)),
            )
            connection.execute(
                'INSERT INTO credential_projections VALUES (?, ?, NULL)',
                (record['credential_id'], 'valid' if record['valid'] else 'invalid'),
            )
            return copy.deepcopy(record)

        return self.store.mutate(save)

    def save_unattested_review_evidence(self, record: dict) -> dict:
        fields = ('evidence_id', 'learning_task_id', 'operation_id', 'content_digest',
                  'review_digest', 'validator_version')
        _record(record, fields, 'UnattestedReviewEvidence')
        for field in ('evidence_id', 'learning_task_id', 'operation_id', 'validator_version'):
            _text(record[field], 'UnattestedReviewEvidence.' + field)
        from .protocol import _hash
        _hash(record['content_digest'], 'UnattestedReviewEvidence.content_digest')
        _hash(record['review_digest'], 'UnattestedReviewEvidence.review_digest')

        def save(connection):
            existing = connection.execute(
                'SELECT record_json FROM unattested_review_evidence WHERE evidence_id=?',
                (record['evidence_id'],),
            ).fetchone()
            if existing is not None and _load(existing['record_json']) != record:
                raise RuntimeServiceError('相同 unattested evidence_id 不得重绑')
            if existing is None:
                connection.execute(
                    'INSERT INTO unattested_review_evidence VALUES (?, ?, ?, ?)',
                    (record['evidence_id'], record['learning_task_id'],
                     record['operation_id'], _json(record)),
                )
            return copy.deepcopy(record)

        return self.store.mutate(save)

    def invalidate_readiness(self, value: str, *, reason: str) -> None:
        _text(reason, 'invalidate_readiness.reason')
        with self._barrier():
            def invalidate(connection):
                updated = connection.execute(
                    "UPDATE readiness_projections SET state='stale', reason=? "
                    'WHERE readiness_digest=?', (reason, value),
                )
                if updated.rowcount != 1:
                    raise RuntimeServiceError('Readiness 不存在')
            self.store.mutate(invalidate)

    def invalidate_credential(self, credential_id: str, *, reason: str) -> None:
        _text(reason, 'invalidate_credential.reason')
        with self._barrier():
            def invalidate(connection):
                updated = connection.execute(
                    "UPDATE credential_projections SET state='invalid', reason=? "
                    'WHERE credential_id=?', (reason, credential_id),
                )
                if updated.rowcount != 1:
                    raise RuntimeServiceError('ReviewCredential 不存在')
            self.store.mutate(invalidate)

    def _credential_requirements_valid(self, connection, readiness: dict,
                                       knowledge_version: int) -> bool:
        for requirement in readiness['required_credentials']:
            row = connection.execute(
                'SELECT c.record_json, p.state FROM review_credentials c '
                'JOIN credential_projections p ON p.credential_id=c.credential_id '
                'WHERE c.credential_id=?', (requirement['credential_ref'],),
            ).fetchone()
            if row is None or row['state'] != 'valid':
                return False
            credential = parse_review_credential(_load(row['record_json']))
            if (not credential['valid'] or credential['result'] != 'pass'
                    or review_credential_digest(credential) != requirement['credential_digest']
                    or credential['learning_task_id'] != readiness['learning_task_id']
                    or credential['role'] != requirement['role']
                    or credential['content_digest'] != requirement['content_digest']):
                return False
            scope = credential['scope']
            if (scope['kind'] != requirement['scope_kind']
                    or scope['objective_ids'] != requirement['objective_ids']
                    or scope['candidate_digest'] != readiness['candidate_digest']
                    or scope['package_ref']['version'] != knowledge_version):
                return False
            for field in ('evidence_digest', 'dependencies_digest', 'rules_digest'):
                if credential[field] != readiness[field]:
                    return False
        return True

    def issue_ingest_authorization(self, *, task_id: str, operation_id: str,
                                   readiness_digest: str,
                                   authorization_ref: str | None = None) -> dict:
        _text(operation_id, 'issue_ingest_authorization.operation_id')
        reference = authorization_ref or uuid.uuid4().hex
        _text(reference, 'Authorization.authorization_ref')

        def issue(connection):
            existing = connection.execute(
                'SELECT record_json FROM authorizations WHERE authorization_ref=?', (reference,),
            ).fetchone()
            if existing is not None:
                record = parse_authorization(_load(existing['record_json']))
                if (record['task_id'], record['operation_id'], record['readiness_digest']) != (
                    task_id, operation_id, readiness_digest
                ):
                    raise AuthorizationError('相同 authorization_ref 不得重绑')
                return record
            if self.executor._journal(operation_id).exists():
                raise AuthorizationError('已有 Executor WAL 的 operation 不得再签发新授权')
            task = self._task(connection, task_id)
            if task['state'] != 'running':
                raise AuthorizationError('只有 running Task 可以签发 ingest 授权')
            learning = self.loop._learning(connection, task_id)
            if learning['state'] != 'awaiting_confirmation':
                raise AuthorizationError('学习状态尚未到达 awaiting_confirmation')
            readiness_row = connection.execute(
                'SELECT r.record_json, p.state FROM readiness_records r '
                'JOIN readiness_projections p ON p.readiness_digest=r.readiness_digest '
                'WHERE r.readiness_digest=?', (readiness_digest,),
            ).fetchone()
            if readiness_row is None or readiness_row['state'] != 'current':
                raise AuthorizationError('Readiness 不存在或已失效')
            readiness = parse_readiness(_load(readiness_row['record_json']))
            if (readiness['learning_task_id'] != task['learning_task_id']
                    or readiness['blockers']
                    or not self._credential_requirements_valid(
                        connection, readiness, learning['knowledge_version'])):
                raise AuthorizationError('Readiness 的学习绑定、阻断或凭据投影无效')
            record = {
                'authorization_ref': reference, 'action': 'ingest',
                'task_id': task_id, 'learning_task_id': task['learning_task_id'],
                'raw_batch_id': readiness['raw_batch_id'], 'operation_id': operation_id,
                'policy_digest': task['current_policy_digest'],
                'submission_epoch': task['submission_epoch'],
                'candidate_digest': readiness['candidate_digest'],
                'readiness_digest': readiness_digest,
                'dependencies_digest': readiness['dependencies_digest'],
                'rules_digest': readiness['rules_digest'], 'state': 'issued',
            }
            parse_authorization(record)
            connection.execute(
                "UPDATE authorizations SET record_json=json_set(record_json, '$.state', 'expired') "
                'WHERE operation_id=? AND authorization_ref<>? '
                "AND json_extract(record_json, '$.state')='issued'",
                (operation_id, reference),
            )
            connection.execute(
                'INSERT INTO authorizations VALUES (?, ?, ?, ?)',
                (reference, task_id, operation_id, _json(record)),
            )
            return record

        with self._barrier():
            return self.store.mutate(issue)

    def get_ingest_authorization(self, authorization_ref: str) -> dict:
        rows = self.store.read('SELECT record_json FROM authorizations')
        for row in rows:
            record = parse_authorization(_load(row['record_json']))
            if record['authorization_ref'] == authorization_ref:
                return record
        raise AuthorizationError('Authorization 不存在')

    def revoke_ingest_authorization(self, authorization_ref: str) -> dict:
        with self._barrier():
            def revoke(connection):
                row = connection.execute(
                    'SELECT record_json FROM authorizations WHERE authorization_ref=?',
                    (authorization_ref,),
                ).fetchone()
                if row is None:
                    raise AuthorizationError('Authorization 不存在')
                selected = parse_authorization(_load(row['record_json']))
                rows = connection.execute(
                    'SELECT record_json FROM authorizations WHERE operation_id=?',
                    (selected['operation_id'],),
                ).fetchall()
                records = [parse_authorization(_load(item['record_json'])) for item in rows]
                if any(record['state'] == 'consumed' for record in records):
                    raise AuthorizationError('已 consumed 授权是历史事实，不能撤销')
                for record in records:
                    if record['state'] != 'revoked':
                        record['state'] = 'revoked'
                        connection.execute(
                            'UPDATE authorizations SET record_json=? WHERE authorization_ref=?',
                            (_json(record), record['authorization_ref']),
                        )
                    if record['authorization_ref'] == authorization_ref:
                        selected = record
                return selected
            return self.store.mutate(revoke)

    def build_admission(self, *, run_id: str, operation_id: str, manifest_digest: str,
                        readiness_digest: str, authorization_ref: str) -> dict:
        def build(connection):
            from .knowledge_ingest import reject_cross_type
            reject_cross_type(connection, operation_id)
            if connection.execute(
                'SELECT 1 FROM maintenance_bindings WHERE operation_id=?', (operation_id,),
            ).fetchone() is not None:
                raise AdmissionError('维护 operation 不得改绑学习 Admission')
            auth_row = connection.execute(
                'SELECT record_json FROM authorizations WHERE authorization_ref=?',
                (authorization_ref,),
            ).fetchone()
            if auth_row is None:
                raise AdmissionError('Authorization 不存在')
            authorization = parse_authorization(_load(auth_row['record_json']))
            if (authorization['action'] != 'ingest' or authorization['state'] != 'issued'
                    or authorization['operation_id'] != operation_id
                    or authorization['readiness_digest'] != readiness_digest):
                raise AdmissionError('Authorization 动作、状态或操作绑定无效')
            task = self._task(connection, authorization['task_id'])
            learning = self.loop._learning(connection, task['task_id'])
            policy = self._policy(connection, task['current_policy_digest'])
            if not runtime_binding_valid(authorization, task, policy, kind='authorization'):
                raise AdmissionError('Authorization 的 policy／submission_epoch 已失效')
            readiness_row = connection.execute(
                'SELECT p.state, r.record_json FROM readiness_records r '
                'JOIN readiness_projections p ON p.readiness_digest=r.readiness_digest '
                'WHERE r.readiness_digest=?', (readiness_digest,),
            ).fetchone()
            if readiness_row is None or readiness_row['state'] != 'current':
                raise AdmissionError('Readiness 已失效')
            readiness = parse_readiness(_load(readiness_row['record_json']))
            if not self._credential_requirements_valid(
                    connection, readiness, learning['knowledge_version']):
                raise AdmissionError('Readiness 凭据投影或知识版本已失效')
            run_row = connection.execute(
                'SELECT record_json FROM runs WHERE run_id=?', (run_id,),
            ).fetchone()
            if run_row is None:
                raise AdmissionError('Run 不存在')
            run = parse_run(_load(run_row['record_json']))
            if run['state'] != 'running' or run['task_id'] != task['task_id']:
                raise AdmissionError('Run 不属于当前活动 Task')
            ownership_row = connection.execute(
                'SELECT record_json FROM execution_ownerships WHERE task_id=?', (task['task_id'],),
            ).fetchone()
            ownership = parse_execution_ownership(_load(ownership_row['record_json']))
            if not check_execution_ownership(
                ownership, action='business_submit', task_id=task['task_id'],
                learning_task_id=task['learning_task_id'], owner=ownership['owner'],
                generation=ownership['generation'], now=self.clock(),
            ):
                raise AdmissionError('当前 ExecutionOwnership 已失效')
            record = {
                'task_id': task['task_id'], 'learning_task_id': task['learning_task_id'],
                'raw_batch_id': authorization['raw_batch_id'], 'run_id': run_id,
                'operation_id': operation_id, 'created_generation': ownership['generation'],
                'policy_digest': task['current_policy_digest'],
                'submission_epoch': task['submission_epoch'],
                'manifest_digest': manifest_digest,
                'candidate_digest': authorization['candidate_digest'],
                'readiness_digest': readiness_digest,
                'dependencies_digest': authorization['dependencies_digest'],
                'rules_digest': authorization['rules_digest'],
                'authorization_ref': authorization_ref,
            }
            parse_admission(record)
            value = admission_digest(record)
            existing = connection.execute(
                'SELECT admission_digest, record_json, binding_state FROM operation_admissions '
                'WHERE operation_id=?', (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing['admission_digest'] != value or _load(existing['record_json']) != record:
                    raise AdmissionError('operation→admission_digest 不可重绑')
                if existing['binding_state'] != 'active':
                    raise AdmissionError('已 superseded 的 operation 不得恢复旧 Admission')
                return record
            connection.execute(
                'INSERT INTO operation_admissions VALUES (?, ?, ?, ?, ?)',
                (operation_id, task['task_id'], value, _json(record), 'active'),
            )
            return record

        return self.store.mutate(build)

    @staticmethod
    def _policy(connection, policy_digest: str) -> dict:
        row = connection.execute(
            'SELECT record_json FROM policy_revisions WHERE policy_digest=?', (policy_digest,),
        ).fetchone()
        if row is None:
            raise RuntimeServiceError('PolicyRevision 不存在')
        return parse_policy_revision(_load(row['record_json']))

    def pause(self, task_id: str) -> dict:
        with self._barrier():
            def pause(connection):
                task = self._task(connection, task_id)
                if task['state'] in ('completed', 'canceled'):
                    raise RuntimeServiceError('终态 Task 不能暂停')
                if task['state'] == 'paused':
                    return task
                task['submission_epoch'] += 1
                task['revision'] += 1
                task['state'] = 'paused'
                self._save_task(connection, task)
                connection.execute(
                    "UPDATE runs SET record_json=json_set(record_json, '$.state', 'paused') "
                    'WHERE task_id=? AND json_extract(record_json, \'$.state\')=\'running\'',
                    (task_id,),
                )
                bindings = connection.execute(
                    'SELECT operation_id, record_json FROM operation_admissions '
                    "WHERE task_id=? AND binding_state='active'", (task_id,),
                ).fetchall()
                for binding in bindings:
                    accepted = connection.execute(
                        'SELECT 1 FROM execution_results WHERE operation_id=?',
                        (binding['operation_id'],),
                    ).fetchone()
                    journal_exists = self.executor._journal(binding['operation_id']).exists()
                    if accepted is None and not journal_exists:
                        connection.execute(
                            "UPDATE operation_admissions SET binding_state='superseded_by_pause' "
                            'WHERE operation_id=?', (binding['operation_id'],),
                        )
                        admission = parse_admission(_load(binding['record_json']))
                        connection.execute(
                            "UPDATE authorizations SET record_json=json_set(record_json, '$.state', 'expired') "
                            'WHERE authorization_ref=? AND json_extract(record_json, \'$.state\')=\'issued\'',
                            (admission['authorization_ref'],),
                        )
                return task
            return self.store.mutate(pause)

    def resume(self, task_id: str, *, run: dict, ownership: dict,
               concurrency_limit: int = 1) -> dict:
        parse_run(run)
        parse_execution_ownership(ownership)
        limit = _concurrency_limit(concurrency_limit)
        with self._barrier():
            def resume(connection):
                task = self._task(connection, task_id)
                if task['state'] != 'paused':
                    raise RuntimeServiceError('只有 paused Task 可以 resume')
                if (run['task_id'] != task_id or run['learning_task_id'] != task['learning_task_id']
                        or run['state'] != 'running' or ownership['task_id'] != task_id
                        or ownership['learning_task_id'] != task['learning_task_id']):
                    raise RuntimeServiceError('resume 必须在同一 Task 下创建新 Run／ownership')
                old = connection.execute(
                    'SELECT generation FROM execution_ownerships WHERE task_id=?', (task_id,),
                ).fetchone()
                if ownership['generation'] <= old['generation']:
                    raise RuntimeServiceError('resume ownership generation 必须递增')
                task_row = self._task_row(connection, task_id)
                policy = self._policy(connection, task['current_policy_digest'])
                reserve = _load(task_row['final_review_reserve_json'])
                connection.execute(
                    'INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)',
                    (run['run_id'], task_id, run['learning_task_id'], _json(run), limit, _json(reserve)),
                )
                zeros = _zero_budget()
                connection.execute(
                    'INSERT INTO run_finance VALUES (?, ?, ?, ?, 0, NULL)',
                    (run['run_id'], _json(policy['budget']), _json(zeros), _json(zeros)),
                )
                connection.execute(
                    'UPDATE execution_ownerships SET owner=?, generation=?, expires_at=?, record_json=? '
                    'WHERE task_id=? AND generation=?',
                    (ownership['owner'], ownership['generation'], ownership['expires_at'],
                     _json(ownership), task_id, old['generation']),
                )
                task['state'] = 'running'
                task['revision'] += 1
                self._save_task(connection, task)
                return {'task': task, 'run': run, 'ownership': ownership}
            return self.store.mutate(resume)

    def _dynamic_context(self, connection, admission: dict) -> dict:
        parse_admission(admission)
        binding = connection.execute(
            'SELECT * FROM operation_admissions WHERE operation_id=?', (admission['operation_id'],),
        ).fetchone()
        if (binding is None or binding['binding_state'] != 'active'
                or binding['admission_digest'] != admission_digest(admission)
                or _load(binding['record_json']) != admission):
            raise AdmissionError('operation→Admission 绑定不存在、已失效或不匹配')
        task = self._task(connection, admission['task_id'])
        policy = self._policy(connection, admission['policy_digest'])
        if not runtime_binding_valid(admission, task, policy, kind='admission'):
            raise AdmissionError('Admission 的 Task／policy／submission_epoch 已失效')
        run_row = connection.execute(
            'SELECT record_json FROM runs WHERE run_id=?', (admission['run_id'],),
        ).fetchone()
        if run_row is None:
            raise AdmissionError('Run 不存在')
        run = parse_run(_load(run_row['record_json']))
        if (task['state'] != 'running' or run['state'] != 'running'
                or run['task_id'] != task['task_id']
                or run['learning_task_id'] != task['learning_task_id']):
            raise AdmissionError('Task／Run 当前不可提交')
        for table, key, value in (
            ('task_finance', 'task_id', task['task_id']), ('run_finance', 'run_id', run['run_id']),
        ):
            finance = connection.execute(
                f'SELECT blocked, block_reason FROM {table} WHERE {key}=?', (value,),
            ).fetchone()
            if finance['blocked']:
                raise AdmissionError('预算已阻断: ' + finance['block_reason'])
        learning = self.loop._learning(connection, task['task_id'])
        if learning['state'] != 'awaiting_confirmation':
            raise AdmissionError('LearningState 当前不可应用')
        readiness_row = connection.execute(
            'SELECT r.record_json, p.state FROM readiness_records r '
            'JOIN readiness_projections p ON p.readiness_digest=r.readiness_digest '
            'WHERE r.readiness_digest=?', (admission['readiness_digest'],),
        ).fetchone()
        if readiness_row is None or readiness_row['state'] != 'current':
            raise AdmissionError('Readiness 已失效')
        readiness = parse_readiness(_load(readiness_row['record_json']))
        if readiness['blockers'] or not self._credential_requirements_valid(
                connection, readiness, learning['knowledge_version']):
            raise AdmissionError('Readiness 阻断、凭据投影或知识版本失效')
        auth_row = connection.execute(
            'SELECT record_json FROM authorizations WHERE authorization_ref=?',
            (admission['authorization_ref'],),
        ).fetchone()
        if auth_row is None:
            raise AdmissionError('Authorization 不存在')
        authorization = parse_authorization(_load(auth_row['record_json']))
        if (authorization['state'] != 'issued'
                or not runtime_binding_valid(authorization, task, policy, kind='authorization')):
            raise AdmissionError('Authorization 已撤销、失效或绑定不匹配')
        for field in ('task_id', 'learning_task_id', 'raw_batch_id', 'operation_id',
                      'candidate_digest', 'readiness_digest', 'dependencies_digest', 'rules_digest'):
            if authorization[field] != admission[field]:
                raise AdmissionError('Authorization 与 Admission 字段不一致: ' + field)
        ownership_row = connection.execute(
            'SELECT record_json FROM execution_ownerships WHERE task_id=?', (task['task_id'],),
        ).fetchone()
        ownership = parse_execution_ownership(_load(ownership_row['record_json']))
        now = self.clock()
        if not check_execution_ownership(
            ownership, action='business_submit', task_id=task['task_id'],
            learning_task_id=task['learning_task_id'], owner=ownership['owner'],
            generation=admission['created_generation'], now=now,
        ):
            raise AdmissionError('ExecutionOwnership generation 或期限无效')
        credentials = []
        for requirement in readiness['required_credentials']:
            row = connection.execute(
                'SELECT record_json FROM review_credentials WHERE credential_id=?',
                (requirement['credential_ref'],),
            ).fetchone()
            credentials.append(parse_review_credential(_load(row['record_json'])))
        return {
            'runtime_task': task, 'learning_state': learning, 'policy_revision': policy,
            'run': run, 'readiness': readiness, 'authorization': authorization,
            'ownership': ownership, 'review_credentials': credentials,
            'task_id': task['task_id'], 'learning_task_id': task['learning_task_id'],
            'raw_batch_id': admission['raw_batch_id'], 'run_id': run['run_id'],
            'operation_id': admission['operation_id'],
            'current_generation': ownership['generation'], 'now': now,
            'manifest_digest': admission['manifest_digest'],
            'candidate_digest': admission['candidate_digest'],
            'dependencies_digest': admission['dependencies_digest'],
            'rules_digest': admission['rules_digest'], 'action': 'ingest',
        }

    @contextmanager
    def acceptance_context(self, admission: dict):
        connection = self.store._connection()
        try:
            self.store._check_schema(connection)
            connection.execute('BEGIN IMMEDIATE')
            self.store._check_schema(connection)
            context = self._dynamic_context(connection, admission)
            yield context
            connection.execute('COMMIT')
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise RuntimeStoreError(f'acceptance_context SQLite 失败: {exc}') from exc
        except Exception:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise

    def reconcile_execution(self, record: dict) -> dict:
        parse_execution_result_binding(record)
        rows = self.store.read(
            "SELECT record_json FROM operation_admissions WHERE operation_id='"
            + record['operation_id'].replace("'", "''") + "'"
        )
        if not rows:
            raise ExecutionReconcileError('执行结果没有原 operation→Admission 绑定')
        admission = parse_admission(_load(rows[0]['record_json']))
        validate_execution_result_binding(record, admission)
        if self.executor is None:
            raise ExecutionReconcileError('执行结果归并缺少 Executor WAL 核验入口')
        try:
            self.executor.verify_execution(record, admission)
        except Exception as exc:
            raise ExecutionReconcileError('执行结果归并被真实 WAL 核验拒绝: ' + str(exc)) from exc

        def reconcile(connection):
            binding = connection.execute(
                'SELECT admission_digest, record_json FROM operation_admissions WHERE operation_id=?',
                (record['operation_id'],),
            ).fetchone()
            if binding is None:
                raise ExecutionReconcileError('执行结果没有原 operation→Admission 绑定')
            admission = parse_admission(_load(binding['record_json']))
            validate_execution_result_binding(record, admission)
            if binding['admission_digest'] != admission_digest(admission):
                raise ExecutionReconcileError('Admission 摘要不匹配')
            result_digest = digest(record)
            existing = connection.execute(
                'SELECT record_json, result_digest FROM execution_results WHERE operation_id=?',
                (record['operation_id'],),
            ).fetchone()
            if existing is not None:
                current = parse_execution_result_binding(_load(existing['record_json']))
                if existing['result_digest'] == result_digest:
                    return project_execution_result(current)
                if current['state'] in ('applied', 'recovered'):
                    raise ExecutionReconcileError('Executor 终态不得被其他结果覆盖')
                if current['recovery_status'] == 'conflict':
                    raise ExecutionReconcileError('conflict 必须人工对账；修复后使用新 operation')
                allowed = {
                    'prepared': {'prepared', 'applying', 'recovery_required', 'applied', 'recovered'},
                    'applying': {'applying', 'recovery_required', 'applied', 'recovered'},
                    'recovery_required': {'recovery_required', 'recovered'},
                }
                if record['state'] not in allowed[current['state']]:
                    raise ExecutionReconcileError('Executor 结果不得回退或绕过恢复语义')
            connection.execute(
                'INSERT INTO execution_results VALUES (?, ?, ?, ?) '
                'ON CONFLICT(operation_id) DO UPDATE SET '
                'record_json=excluded.record_json, result_digest=excluded.result_digest',
                (record['operation_id'], binding['admission_digest'], _json(record), result_digest),
            )
            if record['state'] == 'applied':
                auth = connection.execute(
                    'SELECT record_json FROM authorizations WHERE authorization_ref=?',
                    (admission['authorization_ref'],),
                ).fetchone()
                authorization = parse_authorization(_load(auth['record_json']))
                if authorization['state'] != 'consumed':
                    authorization['state'] = 'consumed'
                    connection.execute(
                        'UPDATE authorizations SET record_json=? WHERE authorization_ref=?',
                        (_json(authorization), authorization['authorization_ref']),
                    )
                learning = self.loop._learning(connection, admission['task_id'])
                learning['state'] = 'applied'
                self.loop._save_learning(connection, learning, self._task(connection, admission['task_id']))
                task = self._task(connection, admission['task_id'])
                task['state'] = 'completed'
                self._save_task(connection, task)
                connection.execute(
                    "UPDATE runs SET record_json=json_set(record_json, '$.state', 'completed') "
                    'WHERE run_id=?', (admission['run_id'],),
                )
            return project_execution_result(record)

        return self.store.mutate(reconcile)

    @staticmethod
    def _maintenance_binding(record: dict) -> dict:
        fields = (
            'task_id', 'learning_task_id', 'run_id', 'operation_id', 'operation_type',
            'workflow_id', 'policy_digest', 'submission_epoch', 'created_generation',
            'manifest_digest', 'candidate_digest', 'dependencies_digest', 'rules_digest',
        )
        _record(record, fields, 'MaintenanceBinding')
        for field in ('task_id', 'learning_task_id', 'run_id', 'operation_id',
                      'operation_type', 'workflow_id'):
            _text(record[field], 'MaintenanceBinding.' + field)
        if record['operation_type'] == 'ingest':
            raise RuntimeServiceError('学习 ingest 不得使用维护绑定代替 Admission')
        _hash(record['policy_digest'], 'MaintenanceBinding.policy_digest')
        if type(record['submission_epoch']) is not int or record['submission_epoch'] < 1:
            raise RuntimeServiceError('MaintenanceBinding.submission_epoch 应为正整数')
        if type(record['created_generation']) is not int or record['created_generation'] < 1:
            raise RuntimeServiceError('MaintenanceBinding.created_generation 应为正整数')
        for field in ('manifest_digest', 'candidate_digest', 'dependencies_digest', 'rules_digest'):
            _hash(record[field], 'MaintenanceBinding.' + field)
        return record

    @staticmethod
    def _maintenance_binding_digest(record: dict) -> str:
        return digest(RuntimeService._maintenance_binding(record))

    def load_maintenance_binding(self, operation_id: str) -> dict | None:
        _text(operation_id, 'load_maintenance_binding.operation_id')
        rows = self.store.read(
            "SELECT record_json FROM maintenance_bindings WHERE operation_id='"
            + operation_id.replace("'", "''") + "'"
        )
        if not rows:
            return None
        return copy.deepcopy(self._maintenance_binding(_load(rows[0]['record_json'])))

    def bind_maintenance(self, binding: dict) -> dict:
        candidate = copy.deepcopy(self._maintenance_binding(binding))

        def bind(connection):
            from .knowledge_ingest import reject_cross_type
            reject_cross_type(connection, candidate['operation_id'])
            value = self._maintenance_binding_digest(candidate)
            existing = connection.execute(
                'SELECT binding_digest, record_json FROM maintenance_bindings WHERE operation_id=?',
                (candidate['operation_id'],),
            ).fetchone()
            if existing is not None:
                if (existing['binding_digest'] != value
                        or _load(existing['record_json']) != candidate):
                    raise RuntimeServiceError('maintenance operation 不得重绑 Task、Run 或候选')
                return candidate
            if connection.execute(
                'SELECT 1 FROM operation_admissions WHERE operation_id=?',
                (candidate['operation_id'],),
            ).fetchone() is not None:
                raise RuntimeServiceError('同一 operation 不得混用学习 Admission 与维护绑定')
            task = self._task(connection, candidate['task_id'])
            policy = self._policy(connection, task['current_policy_digest'])
            run_row = connection.execute(
                'SELECT record_json FROM runs WHERE run_id=?', (candidate['run_id'],),
            ).fetchone()
            if run_row is None:
                raise RuntimeServiceError('维护 Run 不存在')
            run = parse_run(_load(run_row['record_json']))
            if (task['state'] != 'running' or run['state'] != 'running'
                    or run['task_id'] != task['task_id']
                    or run['learning_task_id'] != task['learning_task_id']
                    or candidate['learning_task_id'] != task['learning_task_id']
                    or candidate['workflow_id'] != task['workflow_ref']['workflow_id']
                    or candidate['policy_digest'] != task['current_policy_digest']
                    or candidate['submission_epoch'] != task['submission_epoch']
                    or candidate['policy_digest'] != policy['policy_digest']):
                raise RuntimeServiceError('维护绑定与当前 Task／Run／PolicyRevision 不一致')
            connection.execute(
                'INSERT INTO maintenance_bindings VALUES (?, ?, ?, ?)',
                (candidate['operation_id'], candidate['task_id'], value, _json(candidate)),
            )
            return candidate

        return self.store.mutate(bind)

    def _maintenance_dynamic_context(self, connection, binding: dict) -> dict:
        candidate = self._maintenance_binding(binding)
        row = connection.execute(
            'SELECT binding_digest, record_json FROM maintenance_bindings WHERE operation_id=?',
            (candidate['operation_id'],),
        ).fetchone()
        if (row is None or row['binding_digest'] != self._maintenance_binding_digest(candidate)
                or _load(row['record_json']) != candidate):
            raise RuntimeServiceError('维护 operation 绑定不存在或不匹配')
        return self._submission_context(connection, candidate)

    def _submission_context(self, connection, candidate: dict) -> dict:
        """共用任务/预算/所有权检查；调用者须先验证所属类型的不可变绑定。"""
        task = self._task(connection, candidate['task_id'])
        policy = self._policy(connection, candidate['policy_digest'])
        run_row = connection.execute(
            'SELECT record_json FROM runs WHERE run_id=?', (candidate['run_id'],),
        ).fetchone()
        if run_row is None:
            raise RuntimeServiceError('维护 Run 不存在')
        run = parse_run(_load(run_row['record_json']))
        if (task['state'] != 'running' or run['state'] != 'running'
                or run['task_id'] != task['task_id']
                or run['learning_task_id'] != task['learning_task_id']
                or candidate['learning_task_id'] != task['learning_task_id']
                or candidate['workflow_id'] != task['workflow_ref']['workflow_id']
                or candidate['policy_digest'] != task['current_policy_digest']
                or candidate['submission_epoch'] != task['submission_epoch']
                or candidate['policy_digest'] != policy['policy_digest']):
            raise RuntimeServiceError('维护 Task／Run／policy／submission_epoch 当前不可提交')
        for table, key, value in (
            ('task_finance', 'task_id', task['task_id']), ('run_finance', 'run_id', run['run_id']),
        ):
            finance = connection.execute(
                f'SELECT blocked, block_reason FROM {table} WHERE {key}=?', (value,),
            ).fetchone()
            if finance['blocked']:
                raise RuntimeServiceError('维护预算已阻断: ' + finance['block_reason'])
        ownership_row = connection.execute(
            'SELECT record_json FROM execution_ownerships WHERE task_id=?', (task['task_id'],),
        ).fetchone()
        ownership = parse_execution_ownership(_load(ownership_row['record_json']))
        now = self.clock()
        if not check_execution_ownership(
            ownership, action='business_submit', task_id=task['task_id'],
            learning_task_id=task['learning_task_id'], owner=ownership['owner'],
            generation=candidate['created_generation'], now=now,
        ):
            raise RuntimeServiceError('维护 ExecutionOwnership 已失效')
        return {'runtime_task': task, 'run': run, 'policy_revision': policy,
                'ownership': ownership, 'maintenance_binding': candidate, 'now': now}

    @contextmanager
    def maintenance_acceptance_context(self, binding: dict):
        connection = self.store._connection()
        try:
            self.store._check_schema(connection)
            connection.execute('BEGIN IMMEDIATE')
            self.store._check_schema(connection)
            context = self._maintenance_dynamic_context(connection, binding)
            yield context
            connection.execute('COMMIT')
        except sqlite3.Error as exc:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise RuntimeStoreError(f'maintenance_acceptance_context SQLite 失败: {exc}') from exc
        except Exception:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise

    def reconcile_maintenance(self, binding: dict, result: dict) -> dict:
        candidate = self._maintenance_binding(binding)
        try:
            validate('execution_result', result)
        except Exception as exc:
            raise ExecutionReconcileError('维护 Executor 结果未通过封闭 schema 校验') from exc
        if (result.get('operation_id') != candidate['operation_id']
                or result.get('state') not in (
                    'prepared', 'applying', 'recovery_required', 'applied', 'recovered',
                )):
            raise ExecutionReconcileError('维护 Executor 结果的操作或状态无效')
        expected_recovery = {
            'applied': {'not_needed'}, 'recovered': {'recovered'},
            'prepared': {'required'}, 'applying': {'required'},
            'recovery_required': {'required', 'conflict'},
        }
        if result['recovery_status'] not in expected_recovery[result['state']]:
            raise ExecutionReconcileError('维护 Executor state 与 recovery_status 不一致')
        for field in ('candidate_digest', 'dependencies_digest', 'rules_digest'):
            if result.get(field) != candidate[field]:
                raise ExecutionReconcileError('维护 Executor 结果与绑定不一致: ' + field)
        if self.executor is None:
            raise ExecutionReconcileError('维护结果归并缺少 Executor WAL 核验入口')
        self.executor.verify_maintenance(result, candidate)

        def reconcile(connection):
            binding_row = connection.execute(
                'SELECT binding_digest, record_json FROM maintenance_bindings WHERE operation_id=?',
                (candidate['operation_id'],),
            ).fetchone()
            if (binding_row is None
                    or binding_row['binding_digest'] != self._maintenance_binding_digest(candidate)
                    or _load(binding_row['record_json']) != candidate):
                raise ExecutionReconcileError('维护结果没有原 operation 绑定')
            result_digest = digest(result)
            existing = connection.execute(
                'SELECT record_json, result_digest FROM maintenance_results WHERE operation_id=?',
                (candidate['operation_id'],),
            ).fetchone()
            if existing is not None:
                current = _load(existing['record_json'])
                if existing['result_digest'] == result_digest:
                    return {'state': current['state'], 'applied': current['state'] == 'applied',
                            'execution': current}
                if current['state'] in ('applied', 'recovered'):
                    raise ExecutionReconcileError('维护 Executor 终态不得被其他结果覆盖')
                if current.get('recovery_status') == 'conflict':
                    raise ExecutionReconcileError('维护 conflict 必须人工对账并使用新 operation')
                allowed = {
                    'prepared': {'prepared', 'applying', 'recovery_required', 'applied', 'recovered'},
                    'applying': {'applying', 'recovery_required', 'applied', 'recovered'},
                    'recovery_required': {'recovery_required', 'recovered'},
                }
                if result['state'] not in allowed[current['state']]:
                    raise ExecutionReconcileError('维护 Executor 结果不得回退或绕过恢复')
            connection.execute(
                'INSERT INTO maintenance_results VALUES (?, ?, ?, ?) '
                'ON CONFLICT(operation_id) DO UPDATE SET '
                'record_json=excluded.record_json, result_digest=excluded.result_digest',
                (candidate['operation_id'], binding_row['binding_digest'], _json(result), result_digest),
            )
            if result['state'] in ('applied', 'recovered') or result.get('recovery_status') == 'conflict':
                task = self._task(connection, candidate['task_id'])
                task['state'] = 'completed' if result['state'] == 'applied' else 'blocked'
                task['revision'] += 1
                self._save_task(connection, task)
                connection.execute(
                    "UPDATE runs SET record_json=json_set(record_json, '$.state', ?) WHERE run_id=?",
                    ('completed' if result['state'] == 'applied' else 'blocked', candidate['run_id']),
                )
            return {'state': result['state'], 'applied': result['state'] == 'applied',
                    'execution': copy.deepcopy(result)}

        return self.store.mutate(reconcile)
