"""学习型入库的私有 S0 记录与纯协议校验；不接触存储或真实执行器。"""
from __future__ import annotations

import copy
import math
import re
from typing import Protocol, runtime_checkable

from tools.wiki_runtime.contracts import ContractError, canonical_json, digest

_HASH = re.compile(r'^[0-9a-f]{64}$')
_BUDGET_FIELDS = (
    'requests', 'pages', 'input_bytes', 'model_calls', 'active_seconds', 'repairs', 'appeals',
)
_INVOCATION_ROLES = (
    'Researcher', 'Worker', 'Tutor', 'Reviewer', 'Assessor', 'ConflictReviewer',
    'RuleAuditor', 'ExecutorG3',
)
INVOCATION_PORT_CONSUMERS = ('Worker', 'Reviewer', 'RuleAuditor', 'ExecutorG3')
_TERMINAL_STATES = frozenset({'applied', 'recovered'})
_ACCEPTED_STATES = frozenset({'prepared', 'applying', 'recovery_required', 'applied', 'recovered'})


@runtime_checkable
class InvocationPort(Protocol):
    def invoke(self, spec: dict, call, timeout: float) -> dict: ...

    def replay(self, spec: dict) -> dict: ...

    def remaining_run_time(self, run_id: str) -> float: ...


def _record(value, fields: tuple[str, ...], name: str) -> dict:
    if type(value) is not dict:
        raise ContractError(f'{name}: 应为对象')
    canonical_json(value)
    expected = set(fields)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ContractError(f'{name}: 字段不匹配，缺少={missing}，未知={unknown}')
    return value


def _text(value, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f'{location}: 必须是非空字符串')
    return value


def _hash(value, location: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ContractError(f'{location}: 应为 SHA-256 小写十六进制')
    return value


def _integer(value, location: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ContractError(f'{location}: 应为不小于 {minimum} 的整数')
    return value


def _number(value, location: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ContractError(f'{location}: 应为有限非负数值')
    return value


def _strings(value, location: str) -> list:
    if type(value) is not list or any(not isinstance(item, str) or not item for item in value):
        raise ContractError(f'{location}: 应为非空字符串数组')
    if len(set(value)) != len(value):
        raise ContractError(f'{location}: 不允许重复项')
    return value


def _nullable_text(value, location: str) -> str | None:
    if value is not None:
        _text(value, location)
    return value


def _budget(value, location: str, *, actual: bool = False) -> dict:
    fields = _BUDGET_FIELDS + (('tokens',) if actual else ())
    _record(value, fields, location)
    for field in _BUDGET_FIELDS:
        if field == 'active_seconds':
            _number(value[field], f'{location}.{field}')
        else:
            _integer(value[field], f'{location}.{field}')
    if actual and value['tokens'] is not None:
        _integer(value['tokens'], f'{location}.tokens')
    return value


def parse_task(record: dict) -> dict:
    from .loop_protocol import parse_workflow_ref

    fields = (
        'task_id', 'learning_task_id', 'workflow_ref', 'current_policy_digest',
        'submission_epoch', 'revision', 'state',
    )
    _record(record, fields, 'RuntimeTask')
    _text(record['task_id'], 'RuntimeTask.task_id')
    _text(record['learning_task_id'], 'RuntimeTask.learning_task_id')
    parse_workflow_ref(record['workflow_ref'])
    _hash(record['current_policy_digest'], 'RuntimeTask.current_policy_digest')
    _integer(record['submission_epoch'], 'RuntimeTask.submission_epoch', 1)
    _integer(record['revision'], 'RuntimeTask.revision', 1)
    if record['state'] not in (
        'ready', 'running', 'waiting', 'paused', 'blocked', 'completed', 'canceled',
    ):
        raise ContractError('RuntimeTask.state: 未知执行状态')
    return record


def task_digest(record: dict) -> str:
    return digest(parse_task(record))


def parse_run(record: dict) -> dict:
    fields = ('run_id', 'task_id', 'learning_task_id', 'state', 'execution_history')
    _record(record, fields, 'Run')
    for field in ('run_id', 'task_id', 'learning_task_id'):
        _text(record[field], f'Run.{field}')
    if record['state'] not in ('running', 'paused', 'blocked', 'completed'):
        raise ContractError('Run.state: 未知状态')
    if type(record['execution_history']) is not list:
        raise ContractError('Run.execution_history: 应为数组')
    for index, entry in enumerate(record['execution_history']):
        location = f'Run.execution_history[{index}]'
        _record(entry, ('invocation_id', 'role'), location)
        _text(entry['invocation_id'], f'{location}.invocation_id')
        if entry['role'] not in _INVOCATION_ROLES:
            raise ContractError(f'{location}.role: 未知角色')
    return record


def run_digest(record: dict) -> str:
    return digest(parse_run(record))


def parse_invocation_spec(record: dict) -> dict:
    fields = (
        'invocation_id', 'task_id', 'learning_task_id', 'run_id', 'operation_id',
        'lease_generation', 'policy_digest', 'role', 'kind', 'input_digest', 'requested_budget',
    )
    _record(record, fields, 'InvocationSpec')
    for field in ('invocation_id', 'task_id', 'learning_task_id', 'run_id', 'kind'):
        _text(record[field], f'InvocationSpec.{field}')
    _nullable_text(record['operation_id'], 'InvocationSpec.operation_id')
    _integer(record['lease_generation'], 'InvocationSpec.lease_generation', 1)
    _hash(record['policy_digest'], 'InvocationSpec.policy_digest')
    if record['role'] not in _INVOCATION_ROLES:
        raise ContractError('InvocationSpec.role: 未知角色')
    _hash(record['input_digest'], 'InvocationSpec.input_digest')
    _budget(record['requested_budget'], 'InvocationSpec.requested_budget')
    return record


def invocation_spec_digest(record: dict) -> str:
    return digest(parse_invocation_spec(record))


def parse_invocation(record: dict) -> dict:
    fields = ('spec', 'spec_digest', 'limit_check', 'reservation', 'send_state',
              'result_state', 'result', 'settlement')
    _record(record, fields, 'Invocation')
    parse_invocation_spec(record['spec'])
    if record['spec_digest'] != invocation_spec_digest(record['spec']):
        raise ContractError('Invocation.spec_digest: 与 spec 不匹配')
    checks = record['limit_check']
    _record(checks, ('task', 'run', 'concurrency', 'final_review_reserve'), 'Invocation.limit_check')
    if any(checks[field] != 'passed' for field in checks):
        raise ContractError('Invocation.limit_check: 原子限制检查必须全部通过')
    reservation = record['reservation']
    _record(reservation, ('state', 'budget'), 'Invocation.reservation')
    if reservation['state'] not in ('reserved', 'released'):
        raise ContractError('Invocation.reservation.state: 未知状态')
    _budget(reservation['budget'], 'Invocation.reservation.budget')
    if reservation['budget'] != record['spec']['requested_budget']:
        raise ContractError('Invocation.reservation.budget: 必须等于请求预留')
    if record['send_state'] not in ('not_sent', 'sent'):
        raise ContractError('Invocation.send_state: 未知状态')
    if record['result_state'] not in ('pending', 'succeeded', 'unknown'):
        raise ContractError('Invocation.result_state: 未知状态')
    canonical_json(record['result'])
    if record['result_state'] == 'succeeded':
        if type(record['result']) is not dict:
            raise ContractError('Invocation.result: 成功结果必须是对象')
    elif record['result'] is not None:
        raise ContractError('Invocation.result: 非成功状态不得保存成功结果')
    settlement = record['settlement']
    _record(settlement, ('state', 'actual_usage'), 'Invocation.settlement')
    if settlement['state'] not in ('unsettled', 'settled', 'released'):
        raise ContractError('Invocation.settlement.state: 未知状态')
    if settlement['state'] == 'settled':
        _budget(settlement['actual_usage'], 'Invocation.settlement.actual_usage', actual=True)
        if record['send_state'] != 'sent' or record['result_state'] == 'pending':
            raise ContractError('Invocation.settlement: 未发送或无结果时不能结算')
    elif settlement['actual_usage'] is not None:
        raise ContractError('Invocation.settlement.actual_usage: 未结算时不得记录实际消耗')
    if record['send_state'] == 'not_sent':
        if record['result_state'] != 'pending' or settlement['state'] == 'settled':
            raise ContractError('Invocation: 未发送记录不能有结果或结算')
    elif reservation['state'] != 'reserved' or settlement['state'] == 'released':
        raise ContractError('Invocation: 已发送记录不得释放预留')
    if record['result_state'] in ('succeeded', 'unknown') and record['send_state'] != 'sent':
        raise ContractError('Invocation: 结果必须先有发送记录')
    if reservation['state'] == 'released' and (
        record['send_state'] != 'not_sent' or settlement['state'] != 'released'
    ):
        raise ContractError('Invocation: 释放必须同时满足未发送和未结算')
    if settlement['state'] == 'released' and reservation['state'] != 'released':
        raise ContractError('Invocation: 结算释放与预留释放不一致')
    return record


def invocation_digest(record: dict) -> str:
    return digest(parse_invocation(record))


def new_invocation(spec: dict) -> dict:
    parse_invocation_spec(spec)
    record = {
        'spec': copy.deepcopy(spec),
        'spec_digest': invocation_spec_digest(spec),
        'limit_check': {
            'task': 'passed', 'run': 'passed', 'concurrency': 'passed',
            'final_review_reserve': 'passed',
        },
        'reservation': {'state': 'reserved', 'budget': copy.deepcopy(spec['requested_budget'])},
        'send_state': 'not_sent',
        'result_state': 'pending',
        'result': None,
        'settlement': {'state': 'unsettled', 'actual_usage': None},
    }
    return parse_invocation(record)


def transition_invocation(record: dict, action: str, *, result: dict | None = None,
                          actual_usage: dict | None = None,
                          proof_not_sent: bool = False) -> dict:
    parse_invocation(record)
    updated = copy.deepcopy(record)
    if action == 'send':
        if record['send_state'] != 'not_sent' or record['settlement']['state'] != 'unsettled':
            raise ContractError('Invocation: 只有未发送且未结算的记录可以发送')
        updated['send_state'] = 'sent'
    elif action in ('result', 'unknown'):
        if (record['send_state'] != 'sent' or record['result_state'] != 'pending'
                or record['settlement']['state'] != 'unsettled'):
            raise ContractError('Invocation: 只有已发送的待定记录可以保存结果')
        if action == 'result':
            if type(result) is not dict:
                raise ContractError('Invocation: 成功结果必须是对象')
            updated['result_state'] = 'succeeded'
            updated['result'] = copy.deepcopy(result)
        else:
            updated['result_state'] = 'unknown'
    elif action == 'settle':
        if (record['send_state'] != 'sent' or record['result_state'] == 'pending'
                or record['settlement']['state'] != 'unsettled'):
            raise ContractError('Invocation: 只有已有结果的记录可以结算一次')
        _budget(actual_usage, 'Invocation.settlement.actual_usage', actual=True)
        updated['settlement'] = {'state': 'settled', 'actual_usage': copy.deepcopy(actual_usage)}
    elif action == 'release':
        if (not proof_not_sent or record['send_state'] != 'not_sent'
                or record['result_state'] != 'pending'
                or record['settlement']['state'] != 'unsettled'):
            raise ContractError('Invocation: 只有证明未发送且未发生调用才能释放')
        updated['reservation']['state'] = 'released'
        updated['settlement']['state'] = 'released'
    else:
        raise ContractError(f'Invocation: 未知动作 {action!r}')
    return parse_invocation(updated)


def replay_invocation(record: dict, spec: dict) -> dict:
    parse_invocation(record)
    parse_invocation_spec(spec)
    original = record['spec']
    if spec['invocation_id'] != original['invocation_id']:
        raise ContractError('Invocation.replay: invocation_id 不匹配')
    if (spec['learning_task_id'], spec['run_id']) != (
        original['learning_task_id'], original['run_id']
    ):
        raise ContractError('Invocation.replay: 禁止跨 Task 或 Run 重放')
    if record['spec_digest'] != invocation_spec_digest(spec):
        raise ContractError('Invocation.replay: 相同 ID 不得绑定不同 spec')
    if record['result_state'] != 'succeeded':
        raise ContractError('Invocation.replay: 只有成功结果可重放，unknown 不得重发')
    return copy.deepcopy(record['result'])


def parse_execution_ownership(record: dict) -> dict:
    fields = ('task_id', 'learning_task_id', 'owner', 'generation', 'expires_at')
    _record(record, fields, 'ExecutionOwnership')
    _text(record['task_id'], 'ExecutionOwnership.task_id')
    _text(record['learning_task_id'], 'ExecutionOwnership.learning_task_id')
    _text(record['owner'], 'ExecutionOwnership.owner')
    _integer(record['generation'], 'ExecutionOwnership.generation', 1)
    _number(record['expires_at'], 'ExecutionOwnership.expires_at')
    return record


def execution_ownership_digest(record: dict) -> str:
    return digest(parse_execution_ownership(record))


def check_execution_ownership(record: dict, *, action: str, task_id: str, learning_task_id: str,
                              owner: str, generation: int, now: float,
                              accepted: bool = False) -> bool:
    parse_execution_ownership(record)
    if action not in ('renew', 'release', 'business_submit', 'recover'):
        raise ContractError(f'ExecutionOwnership: 未知动作 {action!r}')
    if (record['task_id'], record['learning_task_id']) != (task_id, learning_task_id):
        return False
    if action == 'recover' and accepted:
        return True
    return (
        record['owner'] == owner and record['generation'] == generation
        and type(now) in (int, float) and math.isfinite(now) and now < record['expires_at']
    )


def parse_review_credential(record: dict) -> dict:
    fields = (
        'credential_id', 'learning_task_id', 'invocation_id', 'role', 'identity', 'independent',
        'content_digest', 'evidence_digest', 'dependencies_digest', 'rules_digest', 'prompt_digest',
        'validator_version', 'review_config_digest', 'scope', 'result', 'valid',
    )
    _record(record, fields, 'ReviewCredential')
    for field in ('credential_id', 'learning_task_id', 'invocation_id', 'identity', 'validator_version'):
        _text(record[field], f'ReviewCredential.{field}')
    if record['role'] not in ('Reviewer', 'Assessor', 'ConflictReviewer', 'RuleAuditor'):
        raise ContractError('ReviewCredential.role: 不能由生成者签发审查凭据')
    if record['independent'] is not True:
        raise ContractError('ReviewCredential.independent: 必须具有独立身份')
    for field in ('content_digest', 'evidence_digest', 'dependencies_digest', 'rules_digest',
                  'prompt_digest', 'review_config_digest'):
        _hash(record[field], f'ReviewCredential.{field}')
    scope = record['scope']
    _record(scope, ('kind', 'objective_ids', 'candidate_digest', 'package_ref'), 'ReviewCredential.scope')
    _text(scope['kind'], 'ReviewCredential.scope.kind')
    _strings(scope['objective_ids'], 'ReviewCredential.scope.objective_ids')
    _hash(scope['candidate_digest'], 'ReviewCredential.scope.candidate_digest')
    package = scope['package_ref']
    _record(package, ('package_id', 'version', 'digest'), 'ReviewCredential.scope.package_ref')
    _text(package['package_id'], 'ReviewCredential.scope.package_ref.package_id')
    _integer(package['version'], 'ReviewCredential.scope.package_ref.version', 1)
    _hash(package['digest'], 'ReviewCredential.scope.package_ref.digest')
    if record['result'] not in ('pass', 'fail', 'changes_required'):
        raise ContractError('ReviewCredential.result: 未知结论')
    if type(record['valid']) is not bool:
        raise ContractError('ReviewCredential.valid: 应为布尔值')
    return record


def review_credential_digest(record: dict) -> str:
    return digest(parse_review_credential(record))


def parse_readiness(record: dict) -> dict:
    fields = (
        'learning_task_id', 'raw_batch_id', 'candidate_digest', 'coverage_digest',
        'assessments_digest', 'evidence_digest', 'dependencies_digest', 'rules_digest',
        'required_credentials', 'blockers', 'state',
    )
    _record(record, fields, 'Readiness')
    _text(record['learning_task_id'], 'Readiness.learning_task_id')
    _text(record['raw_batch_id'], 'Readiness.raw_batch_id')
    for field in ('candidate_digest', 'coverage_digest', 'assessments_digest', 'evidence_digest',
                  'dependencies_digest', 'rules_digest'):
        _hash(record[field], f'Readiness.{field}')
    if type(record['required_credentials']) is not list or not record['required_credentials']:
        raise ContractError('Readiness.required_credentials: 应为非空数组')
    refs = set()
    for index, requirement in enumerate(record['required_credentials']):
        location = f'Readiness.required_credentials[{index}]'
        _record(requirement, ('credential_ref', 'credential_digest', 'content_digest', 'role',
                              'scope_kind', 'objective_ids'), location)
        _text(requirement['credential_ref'], f'{location}.credential_ref')
        _hash(requirement['credential_digest'], f'{location}.credential_digest')
        _hash(requirement['content_digest'], f'{location}.content_digest')
        if requirement['role'] not in ('Reviewer', 'Assessor', 'ConflictReviewer', 'RuleAuditor'):
            raise ContractError(f'{location}.role: 未知审查角色')
        _text(requirement['scope_kind'], f'{location}.scope_kind')
        _strings(requirement['objective_ids'], f'{location}.objective_ids')
        if requirement['credential_ref'] in refs:
            raise ContractError('Readiness.required_credentials: 凭据引用重复')
        refs.add(requirement['credential_ref'])
    _strings(record['blockers'], 'Readiness.blockers')
    if record['state'] not in ('current', 'stale', 'superseded'):
        raise ContractError('Readiness.state: 未知状态')
    return record


def readiness_digest(record: dict) -> str:
    return digest(parse_readiness(record))


def parse_authorization(record: dict) -> dict:
    fields = (
        'authorization_ref', 'action', 'task_id', 'learning_task_id', 'raw_batch_id',
        'operation_id', 'policy_digest', 'submission_epoch', 'candidate_digest',
        'readiness_digest', 'dependencies_digest', 'rules_digest', 'state',
    )
    _record(record, fields, 'Authorization')
    for field in ('authorization_ref', 'task_id', 'learning_task_id', 'raw_batch_id', 'operation_id'):
        _text(record[field], f'Authorization.{field}')
    if record['action'] not in ('ingest', 'approve'):
        raise ContractError('Authorization.action: 未知动作')
    _hash(record['policy_digest'], 'Authorization.policy_digest')
    _integer(record['submission_epoch'], 'Authorization.submission_epoch', 1)
    for field in ('candidate_digest', 'readiness_digest', 'dependencies_digest', 'rules_digest'):
        _hash(record[field], f'Authorization.{field}')
    if record['state'] not in ('issued', 'revoked', 'consumed', 'expired'):
        raise ContractError('Authorization.state: 未知状态')
    return record


def authorization_digest(record: dict) -> str:
    return digest(parse_authorization(record))


def parse_collection_authorization(record: dict) -> dict:
    fields = ('authorization_ref', 'action', 'learning_task_id', 'operation_id',
              'scope_digest', 'rules_digest', 'state')
    _record(record, fields, 'CollectionAuthorization')
    _text(record['authorization_ref'], 'CollectionAuthorization.authorization_ref')
    if record['action'] not in ('capture', 'import'):
        raise ContractError('CollectionAuthorization.action: 仅允许 capture 或 import')
    _text(record['learning_task_id'], 'CollectionAuthorization.learning_task_id')
    _text(record['operation_id'], 'CollectionAuthorization.operation_id')
    _hash(record['scope_digest'], 'CollectionAuthorization.scope_digest')
    _hash(record['rules_digest'], 'CollectionAuthorization.rules_digest')
    if record['state'] not in ('issued', 'revoked', 'expired', 'consumed'):
        raise ContractError('CollectionAuthorization.state: 未知状态')
    return record


def collection_authorization_digest(record: dict) -> str:
    return digest(parse_collection_authorization(record))


def validate_collection_authorization(record: dict, *, action: str, learning_task_id: str,
                                      operation_id: str, scope_digest: str,
                                      rules_digest: str) -> bool:
    parse_collection_authorization(record)
    expected = {
        'action': action, 'learning_task_id': learning_task_id, 'operation_id': operation_id,
        'scope_digest': scope_digest, 'rules_digest': rules_digest,
    }
    return record['state'] == 'issued' and all(record[field] == value
                                                for field, value in expected.items())


def parse_admission(record: dict) -> dict:
    fields = (
        'task_id', 'learning_task_id', 'raw_batch_id', 'run_id', 'operation_id',
        'created_generation', 'policy_digest', 'submission_epoch', 'manifest_digest',
        'candidate_digest', 'readiness_digest', 'dependencies_digest', 'rules_digest',
        'authorization_ref',
    )
    _record(record, fields, 'Admission')
    for field in (
        'task_id', 'learning_task_id', 'raw_batch_id', 'run_id', 'operation_id',
        'authorization_ref',
    ):
        _text(record[field], f'Admission.{field}')
    _integer(record['created_generation'], 'Admission.created_generation', 1)
    _hash(record['policy_digest'], 'Admission.policy_digest')
    _integer(record['submission_epoch'], 'Admission.submission_epoch', 1)
    for field in (
        'manifest_digest', 'candidate_digest', 'readiness_digest', 'dependencies_digest',
        'rules_digest',
    ):
        _hash(record[field], f'Admission.{field}')
    return record


def admission_digest(record: dict) -> str:
    return digest(parse_admission(record))


def parse_execution_result_binding(record: dict) -> dict:
    fields = (
        'task_id', 'learning_task_id', 'raw_batch_id', 'operation_id', 'candidate_digest',
        'dependencies_digest', 'rules_digest', 'state', 'recovery_status',
    )
    _record(record, fields, 'ExecutionResultBinding')
    for field in ('task_id', 'learning_task_id', 'raw_batch_id', 'operation_id'):
        _text(record[field], f'ExecutionResultBinding.{field}')
    for field in ('candidate_digest', 'dependencies_digest', 'rules_digest'):
        _hash(record[field], f'ExecutionResultBinding.{field}')
    state = record['state']
    recovery = record['recovery_status']
    if state not in _ACCEPTED_STATES:
        raise ContractError('ExecutionResultBinding.state: 仅允许已接受状态，conflict 不是公共状态')
    valid_recovery = {
        'applied': {'not_needed'},
        'recovered': {'recovered'},
        'prepared': {'required'},
        'applying': {'required'},
        'recovery_required': {'required', 'in_progress', 'conflict'},
    }
    if recovery not in valid_recovery[state]:
        raise ContractError('ExecutionResultBinding.recovery_status: 与 state 不匹配')
    return record


def execution_result_binding_digest(record: dict) -> str:
    return digest(parse_execution_result_binding(record))


def validate_execution_result_binding(record: dict, admission: dict) -> dict:
    parse_execution_result_binding(record)
    parse_admission(admission)
    for field in ('task_id', 'learning_task_id', 'raw_batch_id', 'operation_id', 'candidate_digest',
                  'dependencies_digest', 'rules_digest'):
        if record[field] != admission[field]:
            raise ContractError(f'ExecutionResultBinding.{field}: 与 Admission 不匹配')
    return record


def project_execution_result(record: dict) -> dict:
    parse_execution_result_binding(record)
    state = record['state']
    return {
        'state': state,
        'accepted': True,
        'terminal': state in _TERMINAL_STATES,
        'applied': state == 'applied',
        'authorization_consumed': state == 'applied',
        'manual_reconciliation': state == 'recovery_required' and record['recovery_status'] == 'conflict',
    }


def certify_readiness(candidate: dict, candidate_preview: dict, understanding_records: list,
                      final_review_credential: dict, *, learning_task_id: str,
                      raw_batch_id: str, evidence_digest: str, dependencies_digest: str,
                      rules_digest: str) -> dict:
    from tools.wiki_runtime.contracts import candidate_digest as public_candidate_digest
    from tools.wiki_runtime.learning.artifact_protocol import assessment_digest
    from tools.wiki_runtime.persistence import (
        coverage_spec_digest, validate_candidate_coverage, validate_final_coverage,
    )

    candidate_digest = public_candidate_digest(candidate)
    validate_candidate_coverage(candidate, candidate_preview)
    if not validate_final_coverage(candidate_preview, understanding_records):
        raise ContractError('Readiness: 最终覆盖或必要独立理解凭据无效')
    coverage = {
        'candidate_id': candidate_preview['candidate_id'],
        'candidate_changes': candidate_preview['candidate_changes'],
        'dispositions': candidate_preview['coverage'],
    }
    coverage_digest = coverage_spec_digest(coverage)
    necessary = []
    classification_objectives = []
    for disposition in candidate_preview['coverage']:
        objective_id = disposition['objective_ref']
        if objective_id is not None and objective_id not in classification_objectives:
            classification_objectives.append(objective_id)
        if (disposition['teaching_disposition'] in ('required_objective', 'reuse_objective')
                and objective_id not in necessary):
            necessary.append(objective_id)
    if len(understanding_records) != len(necessary):
        raise ContractError('Readiness: 当前理解记录必须恰好覆盖全部必要目标且无无关记录')
    requirements = []
    assessment_digests = []
    for objective_id in necessary:
        matches = [record for record in understanding_records
                   if record.get('assessment', {}).get('objective_id') == objective_id]
        if len(matches) != 1:
            raise ContractError('Readiness: 必要目标必须有且只有一条当前理解记录')
        record = matches[0]
        if record.get('learning_task_id') != learning_task_id:
            raise ContractError('Readiness: 理解记录不得跨 Task 复用')
        rubric_review = parse_review_credential(record['rubric_review'])
        if (rubric_review['learning_task_id'] != learning_task_id
                or rubric_review['dependencies_digest'] != dependencies_digest
                or rubric_review['rules_digest'] != rules_digest):
            raise ContractError('Readiness: 本课 rubric 审查的 Task、依赖或规则绑定失效')
        assessment = record['assessment']
        assessor = parse_review_credential(record['assessor_review'])
        content_digest = assessment_digest(assessment)
        scope = assessor['scope']
        if (assessment['package_ref'] != candidate_preview['package_ref']
                or assessor['role'] != 'Assessor' or not assessor['valid']
                or assessor['result'] != 'pass' or assessor['content_digest'] != content_digest
                or assessor['learning_task_id'] != learning_task_id
                or scope['kind'] != 'understanding_assessment'
                or scope['objective_ids'] != [objective_id]
                or scope['candidate_digest'] != candidate_digest
                or scope['package_ref'] != candidate_preview['package_ref']):
            raise ContractError('Readiness: Assessor 未绑定具体 Assessment、目标和候选/包范围')
        for field, expected in [('evidence_digest', evidence_digest),
                                ('dependencies_digest', dependencies_digest),
                                ('rules_digest', rules_digest)]:
            if assessor[field] != expected:
                raise ContractError('Readiness: Assessor 证据、依赖或规则绑定失效')
        assessment_digests.append(content_digest)
        requirements.append({
            'credential_ref': assessor['credential_id'],
            'credential_digest': review_credential_digest(assessor),
            'content_digest': content_digest, 'role': 'Assessor',
            'scope_kind': 'understanding_assessment', 'objective_ids': [objective_id],
        })
    reviewer = parse_review_credential(final_review_credential)
    reviewer_scope = reviewer['scope']
    if (reviewer['role'] != 'Reviewer' or not reviewer['valid'] or reviewer['result'] != 'pass'
            or reviewer['learning_task_id'] != learning_task_id
            or reviewer['content_digest'] != coverage_digest
            or reviewer_scope['kind'] != 'final_candidate_coverage'
            or reviewer_scope['objective_ids'] != classification_objectives
            or reviewer_scope['candidate_digest'] != candidate_digest
            or reviewer_scope['package_ref'] != candidate_preview['package_ref']):
        raise ContractError('Readiness: Reviewer 未独立绑定最终候选和覆盖分类')
    for field, expected in [('evidence_digest', evidence_digest),
                            ('dependencies_digest', dependencies_digest),
                            ('rules_digest', rules_digest)]:
        if reviewer[field] != expected:
            raise ContractError('Readiness: Reviewer 证据、依赖或规则绑定失效')
    requirements.append({
        'credential_ref': reviewer['credential_id'],
        'credential_digest': review_credential_digest(reviewer),
        'content_digest': coverage_digest, 'role': 'Reviewer',
        'scope_kind': 'final_candidate_coverage', 'objective_ids': classification_objectives,
    })
    return parse_readiness({
        'learning_task_id': learning_task_id, 'raw_batch_id': raw_batch_id,
        'candidate_digest': candidate_digest, 'coverage_digest': coverage_digest,
        'assessments_digest': digest(assessment_digests), 'evidence_digest': evidence_digest,
        'dependencies_digest': dependencies_digest, 'rules_digest': rules_digest,
        'required_credentials': requirements, 'blockers': [], 'state': 'current',
    })


def _credentials_valid(context: dict, readiness: dict, admission: dict) -> bool:
    executor_package_ref = context['candidate_preview']['package_ref']
    credentials = {}
    for record in context['review_credentials']:
        parse_review_credential(record)
        if record['credential_id'] in credentials:
            return False
        credentials[record['credential_id']] = record
    for requirement in readiness['required_credentials']:
        credential = credentials.get(requirement['credential_ref'])
        if credential is None or not credential['valid'] or credential['result'] != 'pass':
            return False
        if review_credential_digest(credential) != requirement['credential_digest']:
            return False
        if credential['learning_task_id'] != admission['learning_task_id']:
            return False
        if credential['role'] != requirement['role']:
            return False
        if credential['content_digest'] != requirement['content_digest']:
            return False
        scope = credential['scope']
        if (scope['kind'] != requirement['scope_kind']
                or scope['objective_ids'] != requirement['objective_ids']
                or scope['candidate_digest'] != admission['candidate_digest']
                or scope['package_ref'] != executor_package_ref):
            return False
        for field in ('evidence_digest', 'dependencies_digest', 'rules_digest'):
            if credential[field] != readiness[field]:
                return False
    return True


def acceptance_check(executor_context: dict, admission: dict) -> bool:
    from .loop_protocol import (
        parse_learning_state, parse_policy_revision, runtime_binding_valid,
    )

    try:
        parse_admission(admission)
        task = parse_task(executor_context['runtime_task'])
        learning = parse_learning_state(executor_context['learning_state'])
        parse_policy_revision(executor_context['policy_revision'])
        run = parse_run(executor_context['run'])
        readiness = parse_readiness(executor_context['readiness'])
        authorization = parse_authorization(executor_context['authorization'])
        ownership = parse_execution_ownership(executor_context['ownership'])
        for field in ('task_id', 'learning_task_id', 'raw_batch_id', 'run_id', 'operation_id',
                      'manifest_digest', 'candidate_digest', 'dependencies_digest', 'rules_digest'):
            if admission[field] != executor_context[field]:
                return False
        for kind, record in (('admission', admission), ('authorization', authorization)):
            if not runtime_binding_valid(
                record, task, executor_context['policy_revision'], kind=kind,
            ):
                return False
        if (task['learning_task_id'] != admission['learning_task_id']
                or learning['task_id'] != task['task_id']
                or learning['learning_task_id'] != task['learning_task_id']
                or learning['state'] != 'awaiting_confirmation'
                or learning['knowledge_version'] != executor_context['candidate_preview']['package_ref']['version']
                or run['task_id'] != task['task_id']
                or run['learning_task_id'] != task['learning_task_id']
                or run['run_id'] != admission['run_id']
                or task['state'] != 'running' or run['state'] != 'running'):
            return False
        if executor_context['candidate']['operation_id'] != admission['operation_id']:
            return False
        if admission['created_generation'] != executor_context['current_generation']:
            return False
        if not check_execution_ownership(
            ownership, action='business_submit', task_id=admission['task_id'],
            learning_task_id=admission['learning_task_id'], owner=ownership['owner'],
            generation=admission['created_generation'], now=executor_context['now'],
        ):
            return False
        if readiness['state'] != 'current' or readiness['blockers']:
            return False
        expected_readiness = certify_readiness(
            executor_context['candidate'], executor_context['candidate_preview'],
            executor_context['understanding_records'],
            executor_context['final_review_credential'],
            learning_task_id=admission['learning_task_id'], raw_batch_id=admission['raw_batch_id'],
            evidence_digest=executor_context['evidence_digest'],
            dependencies_digest=admission['dependencies_digest'], rules_digest=admission['rules_digest'],
        )
        if expected_readiness != readiness:
            return False
        if readiness_digest(readiness) != admission['readiness_digest']:
            return False
        for field in ('learning_task_id', 'raw_batch_id', 'candidate_digest',
                      'dependencies_digest', 'rules_digest'):
            if readiness[field] != admission[field]:
                return False
        expected_authorization = {
            'authorization_ref': admission['authorization_ref'],
            'action': executor_context['action'],
            'task_id': admission['task_id'],
            'learning_task_id': admission['learning_task_id'],
            'raw_batch_id': admission['raw_batch_id'],
            'operation_id': admission['operation_id'],
            'policy_digest': admission['policy_digest'],
            'submission_epoch': admission['submission_epoch'],
            'candidate_digest': admission['candidate_digest'],
            'readiness_digest': admission['readiness_digest'],
            'dependencies_digest': admission['dependencies_digest'],
            'rules_digest': admission['rules_digest'],
        }
        if authorization['state'] != 'issued':
            return False
        if any(authorization[field] != value for field, value in expected_authorization.items()):
            return False
        return _credentials_valid(executor_context, readiness, admission)
    except (ContractError, KeyError, TypeError):
        return False


def lookup_terminal(executor_context: dict, admission: dict) -> dict | None:
    parse_admission(admission)
    matches = []
    for record in executor_context.get('terminal_results', []):
        parse_execution_result_binding(record)
        if record['operation_id'] != admission['operation_id']:
            continue
        validate_execution_result_binding(record, admission)
        if record['state'] in _TERMINAL_STATES:
            matches.append(record)
    if len(matches) > 1:
        raise ContractError('Executor.lookup_terminal: 同一身份存在多个终态')
    return copy.deepcopy(matches[0]) if matches else None


def plan_executor_acceptance(executor_context: dict, admission: dict) -> dict:
    terminal = lookup_terminal(executor_context, admission)
    if terminal is not None:
        return {
            'kind': 'terminal', 'result': project_execution_result(terminal),
            'new_review': False, 'new_budget': False,
        }
    if acceptance_check(executor_context, admission):
        return {'kind': 'proceed', 'result': None, 'new_review': True, 'new_budget': True}
    return {'kind': 'rejected', 'result': None, 'new_review': False, 'new_budget': False}
