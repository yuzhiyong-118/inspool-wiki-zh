"""持久循环的封闭纯协议；不实现存储、调度或外部调用。"""
from __future__ import annotations

import copy

from tools.wiki_runtime.contracts import ContractError, digest
from .protocol import (
    _budget, _hash, _integer, _nullable_text, _number, _record, _strings, _text,
    parse_admission, parse_authorization, parse_invocation_spec, parse_task,
)


def _hashes(value, location: str) -> list:
    if type(value) is not list:
        raise ContractError(f'{location}: 应为摘要数组')
    for index, item in enumerate(value):
        _hash(item, f'{location}[{index}]')
    if len(set(value)) != len(value):
        raise ContractError(f'{location}: 不允许重复项')
    return value


def _nullable_version(value, location: str) -> int | None:
    if value is not None:
        _integer(value, location, 1)
    return value


def parse_workflow_ref(record: dict) -> dict:
    fields = (
        'workflow_id', 'implementation_digest', 'contract_version', 'required_checks',
        'allowed_capabilities',
    )
    _record(record, fields, 'WorkflowRef')
    _text(record['workflow_id'], 'WorkflowRef.workflow_id')
    _hash(record['implementation_digest'], 'WorkflowRef.implementation_digest')
    _text(record['contract_version'], 'WorkflowRef.contract_version')
    _strings(record['required_checks'], 'WorkflowRef.required_checks')
    _strings(record['allowed_capabilities'], 'WorkflowRef.allowed_capabilities')
    return record


def workflow_ref_digest(record: dict) -> str:
    return digest(parse_workflow_ref(record))


def parse_learning_state(record: dict) -> dict:
    fields = ('task_id', 'learning_task_id', 'state', 'knowledge_version')
    _record(record, fields, 'LearningState')
    _text(record['task_id'], 'LearningState.task_id')
    _text(record['learning_task_id'], 'LearningState.learning_task_id')
    if record['state'] not in (
        'preparing', 'lesson_ready', 'studying', 'assessing', 'understanding_verified',
        'awaiting_confirmation', 'applying', 'applied', 'canceled',
    ):
        raise ContractError('LearningState.state: 未知学习阶段')
    _integer(record['knowledge_version'], 'LearningState.knowledge_version', 1)
    return record


def learning_state_digest(record: dict) -> str:
    return digest(parse_learning_state(record))


def parse_policy_revision(record: dict) -> dict:
    fields = ('revision', 'policy_digest', 'budget', 'stop_policy', 'creation_reason')
    _record(record, fields, 'PolicyRevision')
    _integer(record['revision'], 'PolicyRevision.revision', 1)
    _hash(record['policy_digest'], 'PolicyRevision.policy_digest')
    _budget(record['budget'], 'PolicyRevision.budget')
    stop = record['stop_policy']
    _record(stop, ('max_step_attempts', 'identical_failure_limit'), 'PolicyRevision.stop_policy')
    _integer(stop['max_step_attempts'], 'PolicyRevision.stop_policy.max_step_attempts', 1)
    _integer(stop['identical_failure_limit'], 'PolicyRevision.stop_policy.identical_failure_limit', 1)
    _text(record['creation_reason'], 'PolicyRevision.creation_reason')
    body = {field: record[field] for field in fields if field != 'policy_digest'}
    if record['policy_digest'] != digest(body):
        raise ContractError('PolicyRevision.policy_digest: 与不可变策略内容不匹配')
    return record


def policy_revision_digest(record: dict) -> str:
    return parse_policy_revision(record)['policy_digest']


def parse_event(record: dict) -> dict:
    fields = (
        'event_id', 'producer', 'task_id', 'type', 'payload_digest', 'payload_ref',
        'target_version', 'causation_id', 'receipt_sequence', 'processing_state',
    )
    _record(record, fields, 'Event')
    for field in ('event_id', 'producer', 'task_id', 'type'):
        _text(record[field], f'Event.{field}')
    _hash(record['payload_digest'], 'Event.payload_digest')
    _nullable_text(record['payload_ref'], 'Event.payload_ref')
    _integer(record['target_version'], 'Event.target_version', 1)
    _nullable_text(record['causation_id'], 'Event.causation_id')
    _integer(record['receipt_sequence'], 'Event.receipt_sequence', 1)
    if record['processing_state'] not in ('pending', 'processed', 'blocked'):
        raise ContractError('Event.processing_state: 未知状态')
    return record


def event_envelope_digest(record: dict) -> str:
    parse_event(record)
    return digest({field: record[field] for field in (
        'task_id', 'type', 'target_version', 'payload_digest',
    )})


def event_digest(record: dict) -> str:
    return digest(parse_event(record))


def replay_event(record: dict, candidate: dict) -> dict:
    parse_event(record)
    parse_event(candidate)
    if (candidate['producer'], candidate['event_id']) != (record['producer'], record['event_id']):
        raise ContractError('Event.replay: producer＋event_id 不匹配')
    if event_envelope_digest(candidate) != event_envelope_digest(record):
        raise ContractError('Event.replay: 同一事件键不得绑定不同业务信封')
    return copy.deepcopy(record)


def parse_step(record: dict) -> dict:
    fields = (
        'step_id', 'task_id', 'capability_id', 'implementation_digest', 'input_digest',
        'dependency_digests', 'attempt', 'generation', 'state', 'result_digest',
    )
    _record(record, fields, 'Step')
    for field in ('step_id', 'task_id', 'capability_id'):
        _text(record[field], f'Step.{field}')
    for field in ('implementation_digest', 'input_digest'):
        _hash(record[field], f'Step.{field}')
    _hashes(record['dependency_digests'], 'Step.dependency_digests')
    _integer(record['attempt'], 'Step.attempt', 1)
    _integer(record['generation'], 'Step.generation', 1)
    if record['state'] not in ('pending', 'running', 'waiting', 'completed', 'blocked'):
        raise ContractError('Step.state: 未知状态')
    if record['result_digest'] is not None:
        _hash(record['result_digest'], 'Step.result_digest')
    if record['state'] == 'completed' and record['result_digest'] is None:
        raise ContractError('Step.result_digest: 已完成步骤必须绑定结果摘要')
    return record


def step_digest(record: dict) -> str:
    return digest(parse_step(record))


def parse_wait(record: dict) -> dict:
    fields = (
        'wait_id', 'task_id', 'condition_type', 'target_step_id', 'knowledge_version',
        'question_version', 'rubric_version', 'answer_policy', 'consumption_state',
        'continuation_condition',
    )
    _record(record, fields, 'Wait')
    for field in ('wait_id', 'task_id', 'condition_type', 'target_step_id'):
        _text(record[field], f'Wait.{field}')
    for field in ('knowledge_version', 'question_version', 'rubric_version'):
        _nullable_version(record[field], f'Wait.{field}')
        if record['condition_type'] == 'user_answer' and record[field] is None:
            raise ContractError(f'Wait.{field}: 用户回答等待必须绑定版本')
    if record['answer_policy'] not in ('single_current', 'ordered_revisions'):
        raise ContractError('Wait.answer_policy: 未知回答策略')
    if record['consumption_state'] not in ('pending', 'consumed', 'superseded'):
        raise ContractError('Wait.consumption_state: 未知状态')
    _text(record['continuation_condition'], 'Wait.continuation_condition')
    return record


def wait_digest(record: dict) -> str:
    return digest(parse_wait(record))


def parse_work_item(record: dict) -> dict:
    fields = (
        'work_item_id', 'task_id', 'step_id', 'ready_at', 'schedule_key', 'claimed_by',
        'generation', 'lease_expires_at', 'state',
    )
    _record(record, fields, 'WorkItem')
    for field in ('work_item_id', 'task_id', 'step_id', 'schedule_key'):
        _text(record[field], f'WorkItem.{field}')
    _number(record['ready_at'], 'WorkItem.ready_at')
    _nullable_text(record['claimed_by'], 'WorkItem.claimed_by')
    _integer(record['generation'], 'WorkItem.generation', 1)
    if record['lease_expires_at'] is not None:
        _number(record['lease_expires_at'], 'WorkItem.lease_expires_at')
    if record['state'] not in ('pending', 'claimed', 'completed', 'blocked'):
        raise ContractError('WorkItem.state: 未知状态')
    if record['state'] == 'claimed' and (
        record['claimed_by'] is None or record['lease_expires_at'] is None
    ):
        raise ContractError('WorkItem: 已领取工作必须绑定执行者与租约')
    return record


def work_item_digest(record: dict) -> str:
    return digest(parse_work_item(record))


def follow_up_digest(step: dict, work_item: dict) -> str:
    return digest({'step': step_digest(step), 'work_item': work_item_digest(work_item)})


def _step_result_body(record: dict) -> dict:
    return {field: record[field] for field in (
        'artifact_digests', 'domain_change_digest', 'wait_request_digest',
        'follow_up_digests', 'failure',
    )}


def parse_step_result(record: dict) -> dict:
    fields = (
        'step_id', 'attempt', 'generation', 'input_digest', 'result_digest',
        'artifact_digests', 'domain_change_digest', 'wait_request_digest',
        'follow_up_digests', 'failure',
    )
    _record(record, fields, 'StepResult')
    _text(record['step_id'], 'StepResult.step_id')
    _integer(record['attempt'], 'StepResult.attempt', 1)
    _integer(record['generation'], 'StepResult.generation', 1)
    _hash(record['input_digest'], 'StepResult.input_digest')
    _hash(record['result_digest'], 'StepResult.result_digest')
    _hashes(record['artifact_digests'], 'StepResult.artifact_digests')
    if record['domain_change_digest'] is not None:
        _hash(record['domain_change_digest'], 'StepResult.domain_change_digest')
    if record['wait_request_digest'] is not None:
        _hash(record['wait_request_digest'], 'StepResult.wait_request_digest')
    _hashes(record['follow_up_digests'], 'StepResult.follow_up_digests')
    failure = record['failure']
    if failure is not None:
        _record(failure, ('category', 'fingerprint', 'reason'), 'StepResult.failure')
        _text(failure['category'], 'StepResult.failure.category')
        _hash(failure['fingerprint'], 'StepResult.failure.fingerprint')
        _text(failure['reason'], 'StepResult.failure.reason')
    if record['result_digest'] != digest(_step_result_body(record)):
        raise ContractError('StepResult.result_digest: 与结果内容不匹配')
    return record


def step_result_digest(record: dict) -> str:
    return digest(parse_step_result(record))


def replay_step_result(record: dict, candidate: dict) -> dict:
    parse_step_result(record)
    parse_step_result(candidate)
    key = ('step_id', 'attempt', 'generation')
    if any(candidate[field] != record[field] for field in key):
        raise ContractError('StepResult.replay: 原确认键不匹配')
    for field in ('input_digest', 'result_digest'):
        if candidate[field] != record[field]:
            raise ContractError(f'StepResult.replay: 同一确认键的 {field} 不同')
    return copy.deepcopy(record)


def parse_retry_policy(record: dict) -> dict:
    fields = ('error_category', 'failure_fingerprint', 'attempt_limit', 'not_before', 'stop_reason')
    _record(record, fields, 'RetryPolicy')
    if record['error_category'] not in ('environment', 'content', 'evidence', 'wait'):
        raise ContractError('RetryPolicy.error_category: 未知错误类别')
    _hash(record['failure_fingerprint'], 'RetryPolicy.failure_fingerprint')
    _integer(record['attempt_limit'], 'RetryPolicy.attempt_limit', 1)
    _number(record['not_before'], 'RetryPolicy.not_before')
    _nullable_text(record['stop_reason'], 'RetryPolicy.stop_reason')
    return record


def retry_policy_digest(record: dict) -> str:
    return digest(parse_retry_policy(record))


def parse_capability_manifest(record: dict) -> dict:
    fields = (
        'capability_id', 'implementation_digest', 'contract_version', 'required_checks',
        'usage_visibility', 'cancellation',
    )
    _record(record, fields, 'CapabilityManifest')
    _text(record['capability_id'], 'CapabilityManifest.capability_id')
    _hash(record['implementation_digest'], 'CapabilityManifest.implementation_digest')
    _text(record['contract_version'], 'CapabilityManifest.contract_version')
    _strings(record['required_checks'], 'CapabilityManifest.required_checks')
    if record['usage_visibility'] not in ('exact', 'partial', 'unknown'):
        raise ContractError('CapabilityManifest.usage_visibility: 未知用量可见性')
    if record['cancellation'] not in ('confirmed', 'best_effort', 'unavailable'):
        raise ContractError('CapabilityManifest.cancellation: 未知取消能力')
    return record


def capability_manifest_digest(record: dict) -> str:
    return digest(parse_capability_manifest(record))


def runtime_binding_valid(record: dict, task: dict, policy: dict, *, kind: str) -> bool:
    parsers = {
        'invocation_spec': parse_invocation_spec,
        'admission': parse_admission,
        'authorization': parse_authorization,
    }
    if kind not in parsers:
        raise ContractError(f'RuntimeBinding: 未知记录类型 {kind!r}')
    parse_task(task)
    parse_policy_revision(policy)
    parsers[kind](record)
    if task['current_policy_digest'] != policy['policy_digest']:
        return False
    expected = {
        'task_id': task['task_id'],
        'learning_task_id': task['learning_task_id'],
        'policy_digest': policy['policy_digest'],
    }
    if kind in ('admission', 'authorization'):
        expected['submission_epoch'] = task['submission_epoch']
    return all(record[field] == value for field, value in expected.items())
