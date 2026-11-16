"""统一 Invocation 的原子预留、条件发送、保守结算与受控恢复。"""
from __future__ import annotations

import copy
import math
import threading
import time
import uuid

from tools.wiki_runtime.contracts import ContractError, canonical_json
from .loop_protocol import parse_policy_revision, runtime_binding_valid
from .protocol import (
    _BUDGET_FIELDS, _budget, _integer, check_execution_ownership, invocation_spec_digest,
    new_invocation, parse_execution_ownership, parse_invocation, parse_invocation_spec,
    parse_run, parse_task, replay_invocation, transition_invocation,
)
from .storage import RuntimeStore, _json, _load


class InvocationError(RuntimeError):
    pass


class InvocationNotFoundError(InvocationError):
    pass


class InvocationConflictError(InvocationError):
    pass


class InvocationBusyError(InvocationError):
    pass


class InvocationLimitError(InvocationError):
    pass


class RecoveryEvidenceError(InvocationError):
    pass


def _zero_budget() -> dict:
    return {field: 0.0 if field == 'active_seconds' else 0 for field in _BUDGET_FIELDS}


def _reserve_budget(value) -> dict:
    if value is None:
        return _zero_budget()
    return copy.deepcopy(_budget(value, 'final_review_reserve'))


def _concurrency_limit(value) -> int:
    return _integer(value, 'concurrency_limit', 1)


def _account(row) -> dict:
    return {
        'budget': _load(row['budget_json']),
        'reserved': _load(row['reserved_json']),
        'actual': _load(row['actual_json']),
        'blocked': bool(row['blocked']),
        'block_reason': row['block_reason'],
    }


def _usage_with_unknown_tokens(requested: dict) -> dict:
    usage = copy.deepcopy(requested)
    usage['tokens'] = None
    return usage


def _unknown_result(invocation_id: str, resource_state: str = 'draining') -> dict:
    return {
        'invocation_id': invocation_id,
        'state': 'unknown',
        'result': None,
        'resource_state': resource_state,
    }


class RuntimeInvocationPort:
    def __init__(self, store: RuntimeStore, *, clock=time.time):
        self.store = store
        self.clock = clock

    def _check_execution_eligibility(self, connection, spec: dict) -> None:
        task_row = connection.execute(
            'SELECT record_json FROM tasks WHERE task_id=?', (spec['task_id'],)
        ).fetchone()
        run_row = connection.execute(
            'SELECT record_json FROM runs WHERE run_id=?', (spec['run_id'],)
        ).fetchone()
        policy_row = connection.execute(
            'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
            (spec['policy_digest'],),
        ).fetchone()
        ownership_row = connection.execute(
            'SELECT record_json FROM execution_ownerships WHERE task_id=?', (spec['task_id'],)
        ).fetchone()
        if None in (task_row, run_row, policy_row, ownership_row):
            raise InvocationConflictError('Invocation 的执行资格记录不完整')
        task = parse_task(_load(task_row['record_json']))
        run = parse_run(_load(run_row['record_json']))
        policy = parse_policy_revision(_load(policy_row['record_json']))
        ownership = parse_execution_ownership(_load(ownership_row['record_json']))
        if (not runtime_binding_valid(spec, task, policy, kind='invocation_spec')
                or run_row is None or run['task_id'] != spec['task_id']
                or run['learning_task_id'] != spec['learning_task_id']
                or task['state'] != 'running' or run['state'] != 'running'):
            raise InvocationConflictError('Invocation 的 Task/Run/policy 绑定或状态无效')
        if not check_execution_ownership(
            ownership, action='business_submit', task_id=spec['task_id'],
            learning_task_id=spec['learning_task_id'], owner=ownership['owner'],
            generation=spec['lease_generation'], now=self.clock(),
        ):
            raise InvocationConflictError('Invocation 的 ExecutionOwnership 已失效')
        for table, key, value in (
            ('task_finance', 'task_id', spec['task_id']),
            ('run_finance', 'run_id', spec['run_id']),
        ):
            account = connection.execute(
                f'SELECT blocked, block_reason FROM {table} WHERE {key}=?', (value,)
            ).fetchone()
            if account is None or account['blocked']:
                reason = '财务账户不存在' if account is None else account['block_reason']
                raise InvocationLimitError(f'Invocation 财务状态不可发送: {reason}')

    def register_policy_revision(self, record: dict) -> dict:
        parse_policy_revision(record)

        def register(connection):
            existing = connection.execute(
                'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
                (record['policy_digest'],),
            ).fetchone()
            if existing is not None:
                if _load(existing['record_json']) != record:
                    raise InvocationConflictError('PolicyRevision 摘要不匹配')
                return copy.deepcopy(record)
            connection.execute(
                'INSERT INTO policy_revisions VALUES (?, ?, ?)',
                (record['policy_digest'], record['revision'], _json(record)),
            )
            return copy.deepcopy(record)

        return self.store.mutate(register)

    def register_task(self, record: dict, *, concurrency_limit: int = 1,
                      final_review_reserve: dict | None = None) -> dict:
        parse_task(record)
        limit = _concurrency_limit(concurrency_limit)
        reserve = _reserve_budget(final_review_reserve)

        def register(connection):
            policy_row = connection.execute(
                'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
                (record['current_policy_digest'],),
            ).fetchone()
            if policy_row is None:
                raise InvocationConflictError('Task 引用的 PolicyRevision 不存在')
            policy = parse_policy_revision(_load(policy_row['record_json']))
            for field, value in reserve.items():
                if value > policy['budget'][field]:
                    raise InvocationConflictError('最终审查留额不得大于 Task 预算')
            existing = connection.execute(
                'SELECT record_json, concurrency_limit, final_review_reserve_json '
                'FROM tasks WHERE task_id=?', (record['task_id'],)
            ).fetchone()
            if existing is not None:
                if (_load(existing['record_json']) != record
                        or existing['concurrency_limit'] != limit
                        or _load(existing['final_review_reserve_json']) != reserve):
                    raise InvocationConflictError('相同 Task ID 不得绑定不同注册内容')
                return copy.deepcopy(record)
            connection.execute(
                'INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)',
                (record['task_id'], record['learning_task_id'], record['current_policy_digest'],
                 _json(record), limit, _json(reserve)),
            )
            zeros = _zero_budget()
            connection.execute(
                'INSERT INTO task_finance VALUES (?, ?, ?, ?, 0, NULL)',
                (record['task_id'], _json(policy['budget']), _json(zeros), _json(zeros)),
            )
            return copy.deepcopy(record)

        return self.store.mutate(register)

    def register_run(self, record: dict, budget: dict | None = None, *,
                     concurrency_limit: int = 1,
                     final_review_reserve: dict | None = None) -> dict:
        parse_run(record)
        limit = _concurrency_limit(concurrency_limit)
        reserve = _reserve_budget(final_review_reserve)
        if budget is not None:
            _budget(budget, 'Run.budget')

        def register(connection):
            task_row = connection.execute(
                'SELECT t.record_json, t.current_policy_digest, t.final_review_reserve_json, '
                'f.budget_json FROM tasks t JOIN task_finance f ON f.task_id=t.task_id '
                'WHERE t.task_id=?', (record['task_id'],)
            ).fetchone()
            if task_row is None:
                raise InvocationConflictError('Run 引用的 Task 不存在')
            task = parse_task(_load(task_row['record_json']))
            if task['learning_task_id'] != record['learning_task_id']:
                raise InvocationConflictError('Run 不得跨 learning_task_id 绑定')
            selected_budget = (copy.deepcopy(budget) if budget is not None
                               else _load(task_row['budget_json']))
            selected_reserve = (copy.deepcopy(reserve) if final_review_reserve is not None
                                else _load(task_row['final_review_reserve_json']))
            for field, value in selected_reserve.items():
                if value > selected_budget[field]:
                    raise InvocationConflictError('最终审查留额不得大于 Run 预算')
            existing = connection.execute(
                'SELECT r.record_json, r.concurrency_limit, r.final_review_reserve_json, '
                'f.budget_json FROM runs r JOIN run_finance f ON f.run_id=r.run_id '
                'WHERE r.run_id=?', (record['run_id'],)
            ).fetchone()
            if existing is not None:
                if (_load(existing['record_json']) != record
                        or existing['concurrency_limit'] != limit
                        or _load(existing['final_review_reserve_json']) != selected_reserve
                        or _load(existing['budget_json']) != selected_budget):
                    raise InvocationConflictError('相同 Run ID 不得绑定不同注册内容')
                return copy.deepcopy(record)
            connection.execute(
                'INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)',
                (record['run_id'], record['task_id'], record['learning_task_id'],
                 _json(record), limit, _json(selected_reserve)),
            )
            zeros = _zero_budget()
            connection.execute(
                'INSERT INTO run_finance VALUES (?, ?, ?, ?, 0, NULL)',
                (record['run_id'], _json(selected_budget), _json(zeros), _json(zeros)),
            )
            return copy.deepcopy(record)

        return self.store.mutate(register)

    def register_execution_ownership(self, record: dict) -> dict:
        parse_execution_ownership(record)

        def register(connection):
            task = connection.execute(
                'SELECT learning_task_id FROM tasks WHERE task_id=?', (record['task_id'],)
            ).fetchone()
            if task is None or task['learning_task_id'] != record['learning_task_id']:
                raise InvocationConflictError('ExecutionOwnership 的 Task 绑定无效')
            connection.execute(
                'INSERT INTO execution_ownerships VALUES (?, ?, ?, ?, ?, ?)',
                (record['task_id'], record['learning_task_id'], record['owner'],
                 record['generation'], record['expires_at'], _json(record)),
            )
            return copy.deepcopy(record)

        return self.store.mutate(register)

    def get_invocation(self, invocation_id: str) -> dict:
        rows = self.store.read(
            "SELECT record_json FROM invocations WHERE invocation_id='"
            + invocation_id.replace("'", "''") + "'"
        )
        if not rows:
            raise InvocationNotFoundError(invocation_id)
        return parse_invocation(_load(rows[0]['record_json']))

    def get_execution(self, invocation_id: str) -> dict:
        escaped = invocation_id.replace("'", "''")
        rows = self.store.read(
            'SELECT i.resource_state, e.execution_token, e.recovery_epoch, '
            'e.send_state, e.result_state FROM invocations i '
            'JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
            f"WHERE i.invocation_id='{escaped}'"
        )
        if not rows:
            raise InvocationNotFoundError(invocation_id)
        return dict(rows[0])

    @staticmethod
    def _check_finance(account: dict, requested: dict, reserve: dict, role: str,
                       scope: str) -> None:
        if account['blocked']:
            raise InvocationLimitError(f'{scope} 已因实际超额阻断: {account["block_reason"]}')
        for field in _BUDGET_FIELDS:
            retained = reserve[field] if role != 'ExecutorG3' else 0
            available = account['budget'][field] - retained
            committed = account['reserved'][field] + account['actual'][field]
            requested_value = requested[field]
            if not math.isfinite(committed + requested_value):
                raise InvocationLimitError(f'{scope}.{field} 财务数值无效')
            if committed + requested_value > available:
                raise InvocationLimitError(f'{scope}.{field} 剩余额度不足')

    @staticmethod
    def _reserve_account(account: dict, requested: dict) -> None:
        for field in _BUDGET_FIELDS:
            account['reserved'][field] += requested[field]

    @staticmethod
    def _save_account(connection, scope: str, scope_id: str, account: dict) -> None:
        table = 'task_finance' if scope == 'task' else 'run_finance'
        key = 'task_id' if scope == 'task' else 'run_id'
        connection.execute(
            f'UPDATE {table} SET reserved_json=?, actual_json=?, blocked=?, block_reason=? '
            f'WHERE {key}=?',
            (_json(account['reserved']), _json(account['actual']),
             int(account['blocked']), account['block_reason'], scope_id),
        )

    @staticmethod
    def _settle_account(account: dict, requested: dict, actual: dict, scope: str) -> None:
        over = []
        for field in _BUDGET_FIELDS:
            remaining = account['reserved'][field] - requested[field]
            if remaining < 0 and math.isclose(remaining, 0.0, abs_tol=1e-12):
                remaining = 0
            if remaining < 0:
                raise InvocationError(f'{scope}.{field} 预留结算为负')
            account['reserved'][field] = remaining
            account['actual'][field] += actual[field]
            committed = account['reserved'][field] + account['actual'][field]
            if not math.isfinite(committed):
                raise InvocationError(f'{scope}.{field} 结算数值无效')
            if committed > account['budget'][field]:
                over.append(field)
        if over:
            account['blocked'] = True
            account['block_reason'] = '实际消耗超额: ' + ','.join(over)

    def _accounts(self, connection, spec: dict) -> tuple[dict, dict]:
        task = connection.execute(
            'SELECT * FROM task_finance WHERE task_id=?', (spec['task_id'],)
        ).fetchone()
        run = connection.execute(
            'SELECT * FROM run_finance WHERE run_id=?', (spec['run_id'],)
        ).fetchone()
        if task is None or run is None:
            raise InvocationConflictError('Task/Run 财务账户不存在')
        return _account(task), _account(run)

    def _settle_finance(self, connection, spec: dict, actual: dict) -> None:
        task, run = self._accounts(connection, spec)
        self._settle_account(task, spec['requested_budget'], actual, 'Task')
        self._settle_account(run, spec['requested_budget'], actual, 'Run')
        self._save_account(connection, 'task', spec['task_id'], task)
        self._save_account(connection, 'run', spec['run_id'], run)

    def _release_unsent_finance(self, connection, spec: dict) -> None:
        task, run = self._accounts(connection, spec)
        for scope, account in (('task', task), ('run', run)):
            for field in _BUDGET_FIELDS:
                remaining = account['reserved'][field] - spec['requested_budget'][field]
                if remaining < 0 and math.isclose(remaining, 0.0, abs_tol=1e-12):
                    remaining = 0
                if remaining < 0:
                    raise InvocationError(f'{scope}.{field} 未发送释放为负')
                account['reserved'][field] = remaining
            self._save_account(connection, scope, spec[f'{scope}_id'], account)

    def _reserve_in_transaction(self, connection, spec: dict):
        parse_invocation_spec(spec)
        spec_digest = invocation_spec_digest(spec)
        existing = connection.execute(
            'SELECT i.record_json, i.resource_state, e.execution_token, e.recovery_epoch '
            'FROM invocations i JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
            'WHERE i.invocation_id=?', (spec['invocation_id'],)
        ).fetchone()
        if existing is not None:
            record = parse_invocation(_load(existing['record_json']))
            if record['spec_digest'] != spec_digest:
                raise InvocationConflictError('相同 invocation_id 不得绑定不同 spec')
            execution = {
                'execution_token': existing['execution_token'],
                'recovery_epoch': existing['recovery_epoch'],
                'resource_state': existing['resource_state'],
            }
            return record, execution, False

        task_row = connection.execute(
            'SELECT * FROM tasks WHERE task_id=?', (spec['task_id'],)
        ).fetchone()
        run_row = connection.execute(
            'SELECT * FROM runs WHERE run_id=?', (spec['run_id'],)
        ).fetchone()
        policy_row = connection.execute(
            'SELECT record_json FROM policy_revisions WHERE policy_digest=?',
            (spec['policy_digest'],),
        ).fetchone()
        if task_row is None or run_row is None or policy_row is None:
            raise InvocationConflictError('Invocation 的 Task/Run/PolicyRevision 引用不存在')
        task = parse_task(_load(task_row['record_json']))
        run = parse_run(_load(run_row['record_json']))
        policy = parse_policy_revision(_load(policy_row['record_json']))
        if (not runtime_binding_valid(spec, task, policy, kind='invocation_spec')
                or run_row['task_id'] != spec['task_id']
                or run['learning_task_id'] != spec['learning_task_id']
                or task['state'] != 'running' or run['state'] != 'running'):
            raise InvocationConflictError('Invocation 的 Task/Run/policy 绑定或状态无效')
        self._check_execution_eligibility(connection, spec)
        for scope, key, limit in (
            ('Task', 'task_id', task_row['concurrency_limit']),
            ('Run', 'run_id', run_row['concurrency_limit']),
        ):
            active = connection.execute(
                'SELECT count(*) FROM invocations '
                f'WHERE {key}=? AND resource_state IN '
                "('not_started', 'inflight', 'draining')",
                (spec[key],),
            ).fetchone()[0]
            if active >= limit:
                raise InvocationLimitError(f'{scope} 并发槽已满')
        task_account, run_account = self._accounts(connection, spec)
        self._check_finance(task_account, spec['requested_budget'],
                            _load(task_row['final_review_reserve_json']), spec['role'], 'Task')
        self._check_finance(run_account, spec['requested_budget'],
                            _load(run_row['final_review_reserve_json']), spec['role'], 'Run')
        self._reserve_account(task_account, spec['requested_budget'])
        self._reserve_account(run_account, spec['requested_budget'])
        self._save_account(connection, 'task', spec['task_id'], task_account)
        self._save_account(connection, 'run', spec['run_id'], run_account)
        record = new_invocation(spec)
        connection.execute(
            'INSERT INTO invocations VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (spec['invocation_id'], spec['task_id'], spec['run_id'], spec['policy_digest'],
             record['spec_digest'], _json(spec), _json(record), 'not_started'),
        )
        execution = {
            'execution_token': uuid.uuid4().hex,
            'recovery_epoch': 1,
            'resource_state': 'not_started',
        }
        connection.execute(
            'INSERT INTO invocation_executions VALUES (?, ?, ?, ?, ?)',
            (spec['invocation_id'], execution['execution_token'], 1, 'not_sent', 'pending'),
        )
        return record, execution, True

    def _reserve(self, spec: dict):
        return self.store.mutate(lambda connection: self._reserve_in_transaction(connection, spec))

    def _claim_send(self, invocation_id: str, execution: dict):
        def claim(connection):
            row = connection.execute(
                'SELECT i.record_json, i.resource_state, e.execution_token, e.recovery_epoch '
                'FROM invocations i JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
                'WHERE i.invocation_id=? AND i.resource_state=\'not_started\' '
                'AND e.send_state=\'not_sent\' AND e.execution_token=? AND e.recovery_epoch=?',
                (invocation_id, execution['execution_token'], execution['recovery_epoch']),
            ).fetchone()
            if row is None:
                return None
            current = parse_invocation(_load(row['record_json']))
            self._check_execution_eligibility(connection, current['spec'])
            updated = connection.execute(
                'UPDATE invocation_executions SET send_state=\'sent\' '
                'WHERE invocation_id=? AND execution_token=? AND recovery_epoch=? '
                'AND send_state=\'not_sent\'',
                (invocation_id, execution['execution_token'], execution['recovery_epoch']),
            )
            if updated.rowcount != 1:
                return None
            record = transition_invocation(_load(row['record_json']), 'send')
            connection.execute(
                'UPDATE invocations SET record_json=?, resource_state=\'inflight\' '
                'WHERE invocation_id=? AND resource_state=\'not_started\'',
                (_json(record), invocation_id),
            )
            return {
                'execution_token': row['execution_token'],
                'recovery_epoch': row['recovery_epoch'],
            }

        return self.store.mutate(claim)

    def _complete_success(self, invocation_id: str, execution: dict, result: dict,
                          actual_usage: dict) -> dict:
        def complete(connection):
            row = connection.execute(
                'SELECT i.record_json, i.resource_state, e.send_state, e.result_state '
                'FROM invocations i JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
                'WHERE i.invocation_id=? AND e.execution_token=? AND e.recovery_epoch=?',
                (invocation_id, execution['execution_token'], execution['recovery_epoch']),
            ).fetchone()
            if row is None:
                return None
            record = parse_invocation(_load(row['record_json']))
            if record['result_state'] == 'unknown':
                return record
            if row['resource_state'] != 'inflight' or row['send_state'] != 'sent':
                raise InvocationError('只有当前 inflight 执行者可以保存成功结果')
            returned = transition_invocation(record, 'result', result=result)
            settled = transition_invocation(returned, 'settle', actual_usage=actual_usage)
            self._settle_finance(connection, settled['spec'], actual_usage)
            connection.execute(
                'UPDATE invocations SET record_json=?, resource_state=\'released\' '
                'WHERE invocation_id=?', (_json(settled), invocation_id),
            )
            connection.execute(
                'UPDATE invocation_executions SET result_state=\'succeeded\' '
                'WHERE invocation_id=?', (invocation_id,),
            )
            return settled

        settled = self.store.mutate(complete)
        if settled is None or settled['result_state'] != 'succeeded':
            return _unknown_result(invocation_id, self.get_execution(invocation_id)['resource_state'])
        return copy.deepcopy(settled['result'])

    def _complete_unknown(self, invocation_id: str, execution: dict) -> dict:
        def unknown(connection):
            row = connection.execute(
                'SELECT i.record_json, i.resource_state FROM invocations i '
                'JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
                'WHERE i.invocation_id=? AND e.execution_token=? AND e.recovery_epoch=?',
                (invocation_id, execution['execution_token'], execution['recovery_epoch']),
            ).fetchone()
            if row is None:
                return None
            record = parse_invocation(_load(row['record_json']))
            if record['result_state'] == 'unknown':
                return record
            if record['result_state'] != 'pending' or record['send_state'] != 'sent':
                raise InvocationError('只有已发送的 pending 调用可归并 unknown')
            marked = transition_invocation(record, 'unknown')
            actual = _usage_with_unknown_tokens(marked['spec']['requested_budget'])
            settled = transition_invocation(marked, 'settle', actual_usage=actual)
            self._settle_finance(connection, settled['spec'], actual)
            connection.execute(
                'UPDATE invocations SET record_json=?, resource_state=\'draining\' '
                'WHERE invocation_id=?', (_json(settled), invocation_id),
            )
            connection.execute(
                'UPDATE invocation_executions SET result_state=\'unknown\' '
                'WHERE invocation_id=?', (invocation_id,),
            )
            return settled

        record = self.store.mutate(unknown)
        resource = self.get_execution(invocation_id)['resource_state']
        return _unknown_result(invocation_id, resource)

    @staticmethod
    def _decode_transport(output) -> tuple[dict, dict | None]:
        if type(output) is not dict:
            raise ContractError('Invocation transport 必须返回结果对象')
        if 'actual_usage' in output:
            if set(output) != {'result', 'actual_usage'}:
                raise ContractError('带用量的 transport 返回必须只含 result 与 actual_usage')
            result = output['result']
            actual = output['actual_usage']
            _budget(actual, 'Invocation.actual_usage', actual=True)
        else:
            result = output
            actual = None
        if type(result) is not dict:
            raise ContractError('Invocation result 必须是对象')
        canonical_json(result)
        return copy.deepcopy(result), copy.deepcopy(actual)

    def _late_transport_finished(self, invocation_id: str, execution: dict) -> None:
        try:
            record = self.get_invocation(invocation_id)
            if record['result_state'] == 'unknown':
                self.confirm_resource_released(invocation_id, {
                    'execution_token': execution['execution_token'],
                    'recovery_epoch': execution['recovery_epoch'],
                    'completed': True,
                })
        except (InvocationError, RuntimeError, ContractError):
            return

    def invoke(self, spec: dict, call, timeout: float) -> dict:
        parse_invocation_spec(spec)
        if not callable(call):
            raise TypeError('call 必须可调用')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError('timeout 必须是有限非负数')
        record, execution, _created = self._reserve(spec)
        if record['result_state'] == 'succeeded':
            return replay_invocation(record, spec)
        if record['result_state'] == 'unknown':
            return _unknown_result(spec['invocation_id'], execution['resource_state'])
        if execution['resource_state'] != 'not_started':
            raise InvocationBusyError('相同 invocation_id 已有活跃执行者')
        claimed = self._claim_send(spec['invocation_id'], execution)
        if claimed is None:
            current = self.get_invocation(spec['invocation_id'])
            if current['result_state'] == 'succeeded':
                return replay_invocation(current, spec)
            if current['result_state'] == 'unknown':
                return _unknown_result(spec['invocation_id'],
                                       self.get_execution(spec['invocation_id'])['resource_state'])
            raise InvocationBusyError('发送条件迁移已由其他执行者取得')
        outcome = {}
        finished = threading.Event()

        def transport():
            try:
                outcome['output'] = call()
            except BaseException as exc:
                outcome['error'] = exc
            finally:
                self._late_transport_finished(spec['invocation_id'], claimed)
                finished.set()

        threading.Thread(target=transport, name=f'invocation-{spec["invocation_id"]}',
                         daemon=True).start()
        if not finished.wait(timeout):
            unknown = self._complete_unknown(spec['invocation_id'], claimed)
            if finished.is_set():
                self.confirm_resource_released(spec['invocation_id'], {
                    'execution_token': claimed['execution_token'],
                    'recovery_epoch': claimed['recovery_epoch'],
                    'completed': True,
                })
                unknown['resource_state'] = 'released'
            return unknown
        if 'error' in outcome:
            unknown = self._complete_unknown(spec['invocation_id'], claimed)
            self.confirm_resource_released(spec['invocation_id'], {
                'execution_token': claimed['execution_token'],
                'recovery_epoch': claimed['recovery_epoch'],
                'completed': True,
            })
            unknown['resource_state'] = 'released'
            return unknown
        try:
            result, actual = self._decode_transport(outcome['output'])
        except (ContractError, TypeError, ValueError):
            unknown = self._complete_unknown(spec['invocation_id'], claimed)
            self.confirm_resource_released(spec['invocation_id'], {
                'execution_token': claimed['execution_token'],
                'recovery_epoch': claimed['recovery_epoch'],
                'completed': True,
            })
            unknown['resource_state'] = 'released'
            return unknown
        if actual is None:
            actual = _usage_with_unknown_tokens(record['spec']['requested_budget'])
        return self._complete_success(spec['invocation_id'], claimed, result, actual)

    def replay(self, spec: dict) -> dict:
        parse_invocation_spec(spec)
        record = self.get_invocation(spec['invocation_id'])
        if record['spec_digest'] != invocation_spec_digest(spec):
            raise InvocationConflictError('相同 invocation_id 不得绑定不同 spec')
        if record['result_state'] == 'succeeded':
            return replay_invocation(record, spec)
        if record['result_state'] == 'unknown':
            return _unknown_result(spec['invocation_id'],
                                   self.get_execution(spec['invocation_id'])['resource_state'])
        raise InvocationBusyError('pending Invocation 只能查询或等待，不能接管')

    def remaining_run_time(self, run_id: str) -> float:
        escaped = run_id.replace("'", "''")
        rows = self.store.read(
            f"SELECT * FROM run_finance WHERE run_id='{escaped}'"
        )
        if not rows:
            raise InvocationNotFoundError(run_id)
        account = _account(rows[0])
        remaining = (account['budget']['active_seconds']
                     - account['reserved']['active_seconds']
                     - account['actual']['active_seconds'])
        return max(0.0, remaining)

    def confirm_resource_released(self, invocation_id: str, evidence: dict) -> dict:
        if type(evidence) is not dict:
            raise RecoveryEvidenceError('结束证据必须是对象')
        token = evidence.get('execution_token')
        epoch = evidence.get('recovery_epoch')
        if not isinstance(token, str) or not token or type(epoch) is not int or epoch < 1:
            raise RecoveryEvidenceError('结束证据缺少 execution_token/recovery_epoch')

        def confirm(connection):
            row = connection.execute(
                'SELECT i.record_json, i.resource_state FROM invocations i '
                'JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
                'WHERE i.invocation_id=? AND e.execution_token=? AND e.recovery_epoch=?',
                (invocation_id, token, epoch),
            ).fetchone()
            if row is None:
                raise RecoveryEvidenceError('结束证据不匹配当前 execution_token/recovery_epoch')
            record = parse_invocation(_load(row['record_json']))
            if row['resource_state'] == 'released':
                return record
            if row['resource_state'] == 'not_started':
                if evidence.get('proof_not_sent') is not True:
                    raise RecoveryEvidenceError('not_started 释放必须证明未发送')
                released = transition_invocation(record, 'release', proof_not_sent=True)
                self._release_unsent_finance(connection, released['spec'])
            else:
                if not (evidence.get('completed') is True
                        or evidence.get('executor_stopped') is True):
                    raise RecoveryEvidenceError('已发送调用必须有可信完成或停止证据')
                released = record
                if record['result_state'] == 'pending':
                    marked = transition_invocation(record, 'unknown')
                    actual = _usage_with_unknown_tokens(marked['spec']['requested_budget'])
                    released = transition_invocation(marked, 'settle', actual_usage=actual)
                    self._settle_finance(connection, released['spec'], actual)
                elif record['result_state'] != 'unknown':
                    raise RecoveryEvidenceError('成功调用已完成结算，不接受迟到结果覆盖')
            connection.execute(
                'UPDATE invocations SET record_json=?, resource_state=\'released\' '
                'WHERE invocation_id=?', (_json(released), invocation_id),
            )
            connection.execute(
                'UPDATE invocation_executions SET result_state=? WHERE invocation_id=?',
                (released['result_state'], invocation_id),
            )
            return released

        return self.store.mutate(confirm)

    def recover_invocation(self, invocation_id: str, evidence: dict) -> dict:
        if type(evidence) is not dict or evidence.get('executor_stopped') is not True:
            raise RecoveryEvidenceError('接管必须提供 executor_stopped=true 的明确证据')
        token = evidence.get('execution_token')
        epoch = evidence.get('recovery_epoch')
        if not isinstance(token, str) or not token or type(epoch) is not int or epoch < 1:
            raise RecoveryEvidenceError('接管证据缺少 execution_token/recovery_epoch')

        def recover(connection):
            row = connection.execute(
                'SELECT i.record_json, i.resource_state FROM invocations i '
                'JOIN invocation_executions e ON e.invocation_id=i.invocation_id '
                'WHERE i.invocation_id=? AND e.execution_token=? AND e.recovery_epoch=?',
                (invocation_id, token, epoch),
            ).fetchone()
            if row is None:
                raise RecoveryEvidenceError('接管证据不匹配当前执行者')
            if row['resource_state'] == 'released':
                raise RecoveryEvidenceError('已释放调用不需要接管')
            record = parse_invocation(_load(row['record_json']))
            if record['send_state'] == 'sent' and record['result_state'] == 'pending':
                marked = transition_invocation(record, 'unknown')
                actual = _usage_with_unknown_tokens(marked['spec']['requested_budget'])
                record = transition_invocation(marked, 'settle', actual_usage=actual)
                self._settle_finance(connection, record['spec'], actual)
            resource_state = ('not_started' if record['send_state'] == 'not_sent'
                              else 'draining')
            new_execution = {
                'execution_token': uuid.uuid4().hex,
                'recovery_epoch': epoch + 1,
            }
            connection.execute(
                'UPDATE invocations SET record_json=?, resource_state=? WHERE invocation_id=?',
                (_json(record), resource_state, invocation_id),
            )
            connection.execute(
                'UPDATE invocation_executions SET execution_token=?, recovery_epoch=?, '
                'result_state=? WHERE invocation_id=? AND execution_token=? AND recovery_epoch=?',
                (new_execution['execution_token'], new_execution['recovery_epoch'],
                 record['result_state'], invocation_id, token, epoch),
            )
            return {**new_execution, 'resource_state': resource_state,
                    'invocation': copy.deepcopy(record)}

        return self.store.mutate(recover)
