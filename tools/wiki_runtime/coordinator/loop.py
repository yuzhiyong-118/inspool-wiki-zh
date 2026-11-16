"""Runtime 驱动的有界候选 Step Driver；正式写入仍仅属于 Executor。"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import math
from pathlib import Path
import queue
import re
import threading
import time

from ..candidate import CandidateView
from ..cli import _run_directory
from ..contracts import (ContractError, bindings_match, bytes_digest, candidate_digest,
                         canonical_json, digest, resolve_path, validate,
                         validate_path, validate_transition)
from ..gates import run_gates, VALIDATOR_VERSION
from ..review import build_request, review, PROMPT_VERSION
from ..review.content import PROMPT
from ..rule_audit.core import AuditBudgetExhausted
from ..runtime.identity import invoke_with_optional_attestation, record_review_identity
from ..runtime.invocation import InvocationError, InvocationLimitError
from ..runtime.registry import ROLE_CAPABILITIES, RegisteredInvocationPort, default_registry
from ..runtime.service import RuntimeService
from ..runtime.storage import RuntimeStore

BINDINGS = ('operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest',
            'mapping_digest', 'validator_version', 'review_prompt_version')
MAPPING = 'tools/wiki_runtime/contracts/rules.json'
CAPABILITIES = ('worker', 'reviewer', 'rule-auditor', 'executor-g3', 'researcher',
                'tutor', 'assessor', 'conflict-reviewer')


def requires_review(operation, candidate, view):
    """由真实差异复算审查需求，不接受调用方的 semantic=False。"""
    validate('candidate', candidate)
    operation = operation['operation_type'] if isinstance(operation, dict) else operation
    if not candidate['changes']:
        return False
    if operation != 'index_rebuild':
        return True

    def prose(data):
        text = data.decode('utf-8')
        text = re.sub(r'\[\[([^\]\r\n]+)\]\]',
                      lambda m: m[1].split('|', 1)[1] if '|' in m[1] else '', text)
        return re.sub(r'\s+', '', text)

    for change in candidate['changes']:
        if change['action'] != 'write' or change['path'] not in ('wiki/index.md', 'raw/index.md'):
            return True
        old = resolve_path(view.root, change['path'])
        if prose(old.read_bytes() if old.exists() else b'') != prose(view.read_bytes(change['path'])):
            return True
    return False


@dataclass(frozen=True)
class LoopResult:
    status: str
    reason: str
    bundle: dict | None
    state: dict


class _Stop(Exception):
    pass


class _Seen(set):
    def __init__(self, values, save):
        super().__init__(values)
        self.save = save

    def add(self, key):
        super().add(key)
        self.save(sorted(self))


def _bounded(fn, timeout):
    box = queue.Queue(maxsize=1)

    def invoke():
        try:
            box.put((True, fn()))
        except BaseException as exc:
            box.put((False, exc))

    threading.Thread(target=invoke, daemon=True).start()
    try:
        ok, result = box.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError('调用超时；迟到结果无效') from None
    if not ok:
        raise result
    return result


def _budget(*, model_call=True, active_seconds=0.0, repairs=0, appeals=0,
            input_bytes=0, pages=1):
    return {
        'requests': int(model_call), 'pages': pages if model_call else 0,
        'input_bytes': input_bytes if model_call else 0,
        'model_calls': int(model_call), 'active_seconds': float(active_seconds),
        'repairs': repairs, 'appeals': appeals,
    }


class InvocationUnknownError(RuntimeError):
    pass


class StepDriver:
    """一个业务 Step 只对应一个 Invocation；不在 Driver 内另设计数账本。"""

    def __init__(self, coordinator):
        from weakref import ref
        self._coordinator = ref(coordinator)

    @staticmethod
    def _step_result(claim):
        result = {
            'step_id': claim['step']['step_id'], 'attempt': claim['step']['attempt'],
            'generation': claim['step']['generation'],
            'input_digest': claim['step']['input_digest'], 'artifact_digests': [],
            'domain_change_digest': None, 'wait_request_digest': None,
            'follow_up_digests': [], 'failure': None,
        }
        result['result_digest'] = digest({field: result[field] for field in (
            'artifact_digests', 'domain_change_digest', 'wait_request_digest',
            'follow_up_digests', 'failure',
        )})
        return result

    @staticmethod
    def _persisted_output(coordinator, invocation_id):
        record = coordinator.port.port.get_invocation(invocation_id)
        if record['result_state'] != 'succeeded':
            raise InvocationError('Step 尚未完成，且原 Invocation 没有可归并成功结果')
        return copy.deepcopy(record['result']['output'])

    def _execute(self, coordinator, spec, call):
        config = coordinator.config
        invocation_id = spec['invocation_id']
        timeout = min(config['call_timeout'], coordinator._remaining())
        capability = ROLE_CAPABILITIES[spec['role']]
        implementation = coordinator.registry.require(
            capability, required_checks=coordinator.workflow['required_checks'],
        )['implementation_digest']
        step_id = 'step-' + digest({
            'operation_id': config['operation_id'], 'invocation_id': invocation_id,
        })
        step = {
            'step_id': step_id, 'task_id': coordinator.runtime_ids['task_id'],
            'capability_id': capability, 'implementation_digest': implementation,
            'input_digest': spec['input_digest'], 'dependency_digests': [],
            'attempt': 1, 'generation': 1, 'state': 'pending', 'result_digest': None,
        }
        coordinator.runtime.loop.schedule_step(step)
        claim = coordinator.runtime.claim_step(
            coordinator.ownership['owner'], lease_seconds=timeout + 1.0,
            invocation_id=invocation_id, step_id=step_id,
        )
        if claim is None:
            return self._persisted_output(coordinator, invocation_id)
        step_result = self._step_result(claim)

        def transport():
            started = time.monotonic()
            output = call(timeout)
            actual = copy.deepcopy(spec['requested_budget'])
            actual['active_seconds'] = max(0.0, time.monotonic() - started)
            actual['tokens'] = None
            return {'result': {
                'output': output, 'step_result_digest': step_result['result_digest'],
            }, 'actual_usage': actual}

        result = (coordinator.port.replay(spec) if call is None
                  else coordinator.port.invoke(spec, transport, timeout))
        if (result.get('state') == 'unknown'
                and result.get('invocation_id') == invocation_id):
            raise InvocationUnknownError('Invocation 结果 unknown；不得作为业务结果或自动重发')
        if result.get('step_result_digest') != step_result['result_digest']:
            raise InvocationError('Invocation 结果与当前 StepResult 摘要不匹配')
        coordinator.runtime.submit_step_result(
            step_result, work_item_id=claim['work_item']['work_item_id'],
            claimed_by=claim['work_item']['claimed_by'], invocation_id=invocation_id,
        )
        return copy.deepcopy(result['output'])

    def invoke(self, *, role, kind, invocation_id, payload, call,
               model_call=True, repairs=0, appeals=0):
        coordinator = self._coordinator()
        config = coordinator.config
        requested = _budget(
            model_call=model_call, active_seconds=config['call_timeout'] if model_call else 0,
            repairs=repairs, appeals=appeals,
            input_bytes=len(canonical_json(payload)), pages=1,
        )
        spec = {
            'invocation_id': invocation_id,
            'task_id': coordinator.runtime_ids['task_id'],
            'learning_task_id': coordinator.runtime_ids['learning_task_id'],
            'run_id': coordinator.runtime_ids['run_id'],
            'operation_id': config['operation_id'],
            'lease_generation': coordinator.ownership['generation'],
            'policy_digest': coordinator.policy['policy_digest'],
            'role': role, 'kind': kind, 'input_digest': digest(payload),
            'requested_budget': requested,
        }
        return self._execute(coordinator, spec, call)

    def replay(self, invocation_id):
        coordinator = self._coordinator()
        record = coordinator.port.port.get_invocation(invocation_id)
        if record['spec']['operation_id'] != coordinator.config['operation_id']:
            raise InvocationError('不得跨 operation 重放 Coordinator Invocation')
        return self._execute(coordinator, record['spec'], None)


class Coordinator:
    def __init__(self, root, run_dir, *, operation_id, operation_type, task,
                 allowed_paths, max_calls, max_seconds, call_timeout,
                 input_refs=(), environment_retries=1, source_packages=(),
                 runtime=None, registry=None, learning_state=None):
        for name, value in [('max_calls', max_calls), ('environment_retries', environment_retries)]:
            if type(value) is not int or value < (1 if name == 'max_calls' else 0):
                raise ValueError(name + ' 必须明确配置有界整数')
        for value in (max_seconds, call_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('必须明确配置有限正数时间预算')
        self.root, self.run_dir = _run_directory(root, run_dir)
        self.lock = threading.Lock()
        allowed_paths, input_refs = list(allowed_paths), list(input_refs)
        for path in allowed_paths + input_refs:
            validate_path(path)
        packages = [copy.deepcopy(validate('source_package', p)) for p in source_packages]
        self.config = dict(root=str(self.root), operation_id=operation_id,
            operation_type=operation_type, task=task, allowed_paths=list(allowed_paths),
            input_refs=list(input_refs), max_calls=max_calls, max_seconds=max_seconds,
            call_timeout=call_timeout, environment_retries=environment_retries,
            source_packages=packages)
        self.state_path = self.run_dir / 'state.json'
        self.versions = dict(rules_digest=bytes_digest(resolve_path(self.root, 'AGENTS.md').read_bytes()),
            mapping_digest=bytes_digest(resolve_path(self.root, MAPPING).read_bytes()),
            validator_version=VALIDATOR_VERSION, review_prompt_version=PROMPT_VERSION)
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding='utf-8'))
            if self.state['config'] != self.config:
                raise ContractError('运行配置与持久记录不一致，拒绝重置预算')
            if 'runtime_ids' not in self.state:
                raise ContractError('旧 Coordinator pending 必须先 drain 或 supersede，不能重置为 Runtime')
            self.stale = self.state['versions'] != self.versions
            created_at = self.state['started_at']
        else:
            if self.run_dir.exists():
                raise ContractError('运行目录已存在且没有可信状态，拒绝覆盖')
            self.run_dir.mkdir(parents=True)
            created_at = time.time()
            self.state = dict(config=self.config, versions=self.versions, state='prepared',
                started_at=created_at, deadline=created_at + max_seconds, calls=0,
                candidates=0, environment_errors=0, seen_keys=[], audit_attempts=0,
                history=[], reason='', credential_reuse='disabled')
            self.stale = False

        identity = digest({'operation_id': operation_id, 'root': str(self.root)})
        self.runtime_ids = {
            'task_id': 'task-' + identity,
            'learning_task_id': 'learning-' + identity,
            'run_id': 'run-' + identity,
        }
        if self.state.get('runtime_ids', self.runtime_ids) != self.runtime_ids:
            raise ContractError('Coordinator 的 Runtime 身份不得重绑')
        self.state['runtime_ids'] = copy.deepcopy(self.runtime_ids)
        self._owns_store = runtime is None
        self.runtime = runtime or RuntimeService(RuntimeStore(self.run_dir / 'runtime'))
        self.registry = registry or default_registry()
        self.workflow = {
            'workflow_id': 'bounded-candidate-v1',
            'implementation_digest': digest({
                'workflow': 'bounded-candidate-v1', 'version': 1,
                'capabilities': self.registry.manifests(),
            }),
            'contract_version': 'candidate-1',
            'required_checks': ['G0', 'G1', 'G2', 'G3'],
            'allowed_capabilities': list(CAPABILITIES),
        }
        self.registry.validate_workflow(self.workflow)
        base_port = self.runtime.port
        if isinstance(base_port, RegisteredInvocationPort):
            base_port = base_port.port
        self.port = RegisteredInvocationPort(base_port, self.registry, self.workflow)
        self.runtime.port = self.port
        self.driver = StepDriver(self)
        budget = {
            'requests': max_calls, 'pages': 1000000, 'input_bytes': 256 * 1024 * 1024,
            'model_calls': max_calls, 'active_seconds': float(max_seconds),
            'repairs': 3, 'appeals': 1,
        }
        policy_body = {
            'revision': 1, 'budget': budget,
            'stop_policy': {
                'max_step_attempts': environment_retries + 1,
                'identical_failure_limit': environment_retries + 1,
            },
            'creation_reason': 'Coordinator 旧参数适配为不可变 Runtime PolicyRevision',
        }
        self.policy = dict(policy_body, policy_digest=digest(policy_body))
        task_id = self.runtime_ids['task_id']
        existing = self.runtime.store.read(
            "SELECT record_json FROM tasks WHERE task_id='" + task_id + "'"
        )
        if existing:
            saved_task = json.loads(existing[0]['record_json'])
            if (saved_task['workflow_ref'] != self.workflow
                    or saved_task['current_policy_digest'] != self.policy['policy_digest']):
                raise ContractError('Runtime Task 的 Workflow 或 PolicyRevision 与旧配置不一致')
            ownership_row = self.runtime.store.read(
                "SELECT record_json FROM execution_ownerships WHERE task_id='" + task_id + "'"
            )[0]
            self.ownership = json.loads(ownership_row['record_json'])
        else:
            self.ownership = {
                'task_id': self.runtime_ids['task_id'],
                'learning_task_id': self.runtime_ids['learning_task_id'],
                'owner': 'coordinator-' + identity,
                'generation': 1, 'expires_at': created_at + max_seconds,
            }
            task_record = {
                'task_id': self.runtime_ids['task_id'],
                'learning_task_id': self.runtime_ids['learning_task_id'],
                'workflow_ref': self.workflow,
                'current_policy_digest': self.policy['policy_digest'],
                'submission_epoch': 1, 'revision': 1, 'state': 'running',
            }
            run_record = {**self.runtime_ids, 'state': 'running', 'execution_history': []}
            learning_record = None if learning_state is None else {
                'task_id': self.runtime_ids['task_id'],
                'learning_task_id': self.runtime_ids['learning_task_id'],
                'state': learning_state, 'knowledge_version': 1,
            }
            self.runtime.create_task(
                policy=self.policy, task=task_record, run=run_record,
                ownership=self.ownership, learning_state=learning_record,
                concurrency_limit=max(4, max_calls + 2),
            )
        self.state['deadline'] = self.ownership['expires_at']
        self._save()

    def close(self):
        if self._owns_store:
            self.runtime.store.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def worker_payload_root(self):
        return self.run_dir / 'worker-payload'

    def _save(self):
        if hasattr(self, 'runtime'):
            task_id = self.runtime_ids['task_id']
            accounts = self.runtime.store.read(
                "SELECT reserved_json, actual_json FROM task_finance WHERE task_id='" + task_id + "'"
            )
            if accounts:
                reserved = json.loads(accounts[0]['reserved_json'])
                actual = json.loads(accounts[0]['actual_json'])
                self.state['calls'] = reserved['model_calls'] + actual['model_calls']
                self.state['repairs'] = reserved['repairs'] + actual['repairs']
                self.state['appeals'] = reserved['appeals'] + actual['appeals']
            invocations = self.runtime.store.read(
                "SELECT record_json FROM invocations WHERE task_id='" + task_id + "'"
            )
            records = [json.loads(row['record_json']) for row in invocations]
            self.state['audit_attempts'] = sum(
                record['spec']['role'] == 'RuleAuditor' for record in records
            )
            self.state['environment_errors'] = sum(
                record['spec']['kind'] == 'environment_retry' for record in records
            )
            self.state['candidates'] = len(list(self.run_dir.glob('round-*/manifest.json')))
            self.state['deadline'] = self.ownership['expires_at']
        temporary = self.run_dir / 'state.tmp'
        temporary.write_bytes(canonical_json(self.state) + b'\n')
        temporary.replace(self.state_path)

    def _transition(self, state, reason=''):
        old = self.state['state']
        if state != old:
            validate_transition(old, state)
        self.state['state'] = state
        self.state['reason'] = reason
        self.state['history'].append(dict(state=state, reason=reason, at=time.time()))
        self._save()

    def _remaining(self):
        wall_remaining = self.ownership['expires_at'] - time.time()
        active_remaining = self.port.remaining_run_time(self.runtime_ids['run_id'])
        remaining = min(wall_remaining, active_remaining)
        if remaining <= 0:
            raise _Stop('全任务时间预算耗尽')
        return min(self.config['call_timeout'], remaining)

    def _reserve(self):
        """旧 Executor 适配只创建统一预留；新学习路径不得使用此入口。"""
        invocation_id = self.config['operation_id'] + '-legacy-reserve-' + str(self.state['calls'] + 1)
        payload = {'legacy_reservation': invocation_id}
        spec = {
            'invocation_id': invocation_id, **self.runtime_ids,
            'operation_id': self.config['operation_id'],
            'lease_generation': self.ownership['generation'],
            'policy_digest': self.policy['policy_digest'], 'role': 'Worker',
            'kind': 'legacy_executor_reservation', 'input_digest': digest(payload),
            'requested_budget': _budget(active_seconds=0),
        }
        try:
            record, _execution, _created = self.port.port._reserve(spec)
        except InvocationError:
            return False
        self._save()
        return record['result_state'] == 'pending'

    def reserve_call(self):
        return self._reserve()

    def remaining_timeout(self):
        return self._remaining()

    def _call(self, fn, *, model=True, role='Worker', kind='model', invocation_id=None,
              payload=None, repairs=0, appeals=0):
        if not model:
            return _bounded(lambda: fn(self._remaining()), self._remaining())
        self._remaining()
        actual_id = invocation_id.format(attempt=1)
        try:
            result = self.driver.invoke(
                role=role, kind=kind, invocation_id=actual_id,
                payload=payload if payload is not None else {'invocation_id': actual_id},
                call=fn, repairs=repairs, appeals=appeals,
            )
            self._save()
            self._remaining()
            return result
        except InvocationUnknownError as exc:
            self._save()
            raise _Stop(str(exc)) from exc
        except InvocationLimitError as exc:
            self._save()
            raise _Stop('budget_exhausted: ' + str(exc)) from exc
        except (TimeoutError, OSError, RuntimeError) as exc:
            self._save()
            raise _Stop('调用环境失败: ' + type(exc).__name__) from exc

    def _charge_repair(self, round_number):
        payload = {'operation_id': self.config['operation_id'], 'repair_round': round_number}
        invocation_id = self.config['operation_id'] + '-repair-' + str(round_number)
        self.driver.invoke(
            role='Worker', kind='candidate_repair', invocation_id=invocation_id,
            payload=payload, call=lambda _timeout: {'repair_round': round_number},
            model_call=False, repairs=1,
        )
        self._save()

    def _current(self, manifest, snapshot, view):
        self._remaining()
        for key, path in [('rules_digest', 'AGENTS.md'), ('mapping_digest', MAPPING)]:
            if bytes_digest(resolve_path(self.root, path).read_bytes()) != manifest[key]:
                raise _Stop('规则版本变化，旧报告失效，须人工重新建立操作')
        view.verify_dependencies(snapshot)
        if digest(view.dependency_snapshot()) != digest(snapshot):
            raise _Stop('读取依赖变化，旧报告失效')

    def _round_number(self):
        if self.state['state'] == 'checking' and self.state['candidates'] > 0:
            return self.state['candidates']
        return self.state['candidates'] + 1

    def _worker_invocation_id(self, round_number):
        prefix = self.config['operation_id'] + '-worker-round-' + str(round_number) + '-'
        matches = []
        rows = self.runtime.store.read(
            "SELECT record_json FROM invocations WHERE task_id='"
            + self.runtime_ids['task_id'] + "'"
        )
        for row in rows:
            invocation = json.loads(row['record_json'])
            spec = invocation['spec']
            if (spec['operation_id'] == self.config['operation_id']
                    and spec['kind'] == 'candidate_generation'
                    and spec['invocation_id'].startswith(prefix)):
                matches.append(spec['invocation_id'])
        if len(matches) != 1:
            raise ContractError('恢复 round 必须对应唯一持久 Worker Invocation')
        return matches[0]

    def _freeze(self, response, round_number):
        candidate = copy.deepcopy(validate('candidate', response['candidate']))
        if candidate['operation_id'] != self.config['operation_id']:
            raise ContractError('Worker operation_id 不匹配')
        if round_number > 3:
            raise _Stop('三个候选机会耗尽')
        supplied_root = Path(response['payload_root']).resolve(strict=True)
        controlled_root = self.worker_payload_root.resolve(strict=True)
        if supplied_root != controlled_root and not supplied_root.is_relative_to(controlled_root):
            raise ContractError('Worker 载荷根必须位于请求指定的受控候选目录')
        self.state['candidates'] = round_number
        directory = self.run_dir / ('round-' + str(round_number))
        payload = directory / 'payload'
        directory.mkdir(exist_ok=True)
        payload.mkdir(exist_ok=True)
        candidate_path = directory / 'candidate.json'
        if candidate_path.exists():
            if json.loads(candidate_path.read_text(encoding='utf-8')) != candidate:
                raise ContractError('恢复 round 的候选与持久 Worker 结果不一致')
        else:
            candidate_path.write_bytes(canonical_json(candidate) + b'\n')
        for change in candidate['changes']:
            if 'payload_path' in change:
                data = resolve_path(supplied_root, change['payload_path']).read_bytes()
                if bytes_digest(data) != change['sha256']:
                    raise ContractError('候选载荷摘要不匹配')
                target = resolve_path(payload, change['payload_path'])
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.read_bytes() != data:
                        raise ContractError('恢复 round 的既有载荷与 Worker 结果不一致')
                else:
                    target.write_bytes(data)
        view = CandidateView(self.root, candidate, payload)
        list(view.iter_paths())
        snapshot = view.dependency_snapshot()
        dependencies_path = directory / 'dependencies.json'
        if dependencies_path.exists():
            if json.loads(dependencies_path.read_text(encoding='utf-8')) != snapshot:
                raise ContractError('恢复 round 的依赖快照与当前候选不一致')
        else:
            dependencies_path.write_bytes(canonical_json(snapshot) + b'\n')
        semantic = requires_review(self.config['operation_type'], candidate, view)
        manifest = dict(contract_version='1.0', operation_id=self.config['operation_id'],
            operation_type=self.config['operation_type'], task=self.config['task'],
            input_refs=self.config['input_refs'], allowed_paths=self.config['allowed_paths'],
            rules_path='AGENTS.md', **self.versions, dependencies_digest=digest(snapshot),
            candidate_digest=candidate_digest(candidate), round=self.state['candidates'],
            required_gates=['G0', 'G1', 'G2'] + (['G3'] if semantic else []), authorization_refs=[])
        validate('manifest', manifest)
        manifest_path = directory / 'manifest.json'
        if manifest_path.exists():
            if json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
                raise ContractError('恢复 round 的 manifest 绑定不一致')
        else:
            manifest_path.write_bytes(canonical_json(manifest) + b'\n')
        self._save()
        return manifest, candidate, snapshot, payload, view, semantic, directory

    def _review_request(self, manifest, candidate, snapshot, view):
        originals = {p: resolve_path(self.root, p).read_bytes() for p in self.config['input_refs']}
        before, after = {}, {}
        for change in candidate['changes']:
            if change['action'] == 'move':
                path = change['source']
                before[path] = resolve_path(self.root, path).read_bytes()
            elif change['precondition']['kind'] == 'hash':
                path = change['path']
                before[path] = resolve_path(self.root, path).read_bytes()
            if change['action'] != 'delete':
                after[change['path']] = view.read_bytes(change['path'])
        return build_request(manifest, candidate, snapshot,
            rules=resolve_path(self.root, 'AGENTS.md').read_bytes(),
            mapping=resolve_path(self.root, MAPPING).read_bytes(), originals=originals,
            original_pages=before, candidate_files=after)

    def _review_call(self, request_review, transport, timeout, manifest):
        identity = {}
        envelope = {'system': PROMPT, 'input': copy.deepcopy(request_review),
                    'reviewer_id': 'independent-reviewer'}

        def attested_transport(value, *, timeout):
            result = invoke_with_optional_attestation(transport, value, timeout=timeout)
            identity.update(result)
            return result['output']

        opinion = review(request_review, transport=attested_transport, timeout=timeout)
        return {'opinion': opinion, 'attestation': identity.get('attestation'),
                'envelope': envelope, 'manifest': manifest}

    def _record_review_identity(self, response, invocation_id):
        manifest = response['manifest']
        opinion = response['opinion']
        identity = record_review_identity(
            self.runtime, attestation=response['attestation'],
            invocation_id=invocation_id,
            learning_task_id=self.runtime_ids['learning_task_id'],
            operation_id=self.config['operation_id'], role='Reviewer',
            content_digest=manifest['candidate_digest'], evidence_digest=digest(response['envelope']),
            dependencies_digest=manifest['dependencies_digest'], rules_digest=manifest['rules_digest'],
            review_config={'validator_version': VALIDATOR_VERSION,
                           'review_prompt_version': PROMPT_VERSION,
                           'reviewer_id': 'independent-reviewer'},
            review_request=response['envelope'], opinion=opinion,
            package_ref={'package_id': 'candidate-' + self.config['operation_id'],
                         'version': manifest['round'], 'digest': manifest['candidate_digest']},
            objective_ids=[], scope_kind='candidate_content_review',
        )
        self.state['credential_reuse'] = identity['credential_reuse']
        self._save()

    def run(self, worker, *, reviewer=None, auditor=None):
        """Worker／Reviewer／Auditor 全部经统一 Invocation；成功也不代表已应用。"""
        bundle, feedback, current = None, {}, None
        try:
            if self.state['state'] in ('awaiting_human', 'failed'):
                return LoopResult(self.state['state'], self.state['reason'], None, copy.deepcopy(self.state))
            if self.state['state'] == 'ready_to_apply':
                self._transition('checking', '重启后旧报告不作为凭据')
                raise _Stop('已完成运行须交 Executor 重验；重启不重放批准')
            if self.state['state'] != 'checking':
                self._transition('checking')
            if self.stale:
                raise _Stop('版本已变化，旧报告失效')
            self._remaining()
            if worker is None or not callable(worker):
                raise _Stop('未配置 Worker 模型')
            if any(p['input_type'] in ('pdf', 'audio', 'video') or p['parser']['used_ocr']
                   or p['parser']['used_model'] or p['quality']['status'] != 'complete'
                   for p in self.config['source_packages']) or any(
                   Path(p).suffix.lower() in ('.pdf', '.png', '.jpg', '.jpeg', '.wav', '.mp3', '.mp4')
                   for p in self.config['input_refs']):
                raise _Stop('PDF 或多模态来源保持人工暂停策略')
            for path in self.config['input_refs']:
                data = resolve_path(self.root, path).read_bytes()
                text = data.decode('utf-8-sig')
                if text.startswith('---\n') or text.startswith('---\r\n'):
                    header = re.split(r'(?m)^---\s*$', text, maxsplit=2)[1]
                    if re.search(r'(?im)^\s*(?:input_type|source_type|original_type|original_input_type):\s*[\"\x27]?(?:pdf|audio|video|image)\b', header) or re.search(
                        r'(?im)^\s*(?:used_ocr|used_model):\s*true\b', header):
                        raise _Stop('raw 原类型或解析标记要求人工暂停')
            self.worker_payload_root.mkdir(exist_ok=True)
            while True:
                round_number = self._round_number()
                if round_number > 3:
                    raise _Stop('三个候选机会耗尽')
                if self.state['state'] == 'checking' and self.state['candidates'] > 0:
                    response = self.driver.replay(self._worker_invocation_id(round_number))
                else:
                    request = dict(
                        task=self.config['task'], operation_id=self.config['operation_id'],
                        operation_type=self.config['operation_type'],
                        input_refs=self.config['input_refs'],
                        allowed_paths=self.config['allowed_paths'], round=round_number,
                        payload_root=str(self.worker_payload_root),
                        feedback=copy.deepcopy(feedback),
                    )
                    worker_id = (
                        self.config['operation_id'] + '-worker-round-' + str(request['round'])
                        + '-input-' + digest(request) + '-attempt-{attempt}'
                    )
                    response = self._call(
                        lambda timeout: worker(copy.deepcopy(request), timeout=timeout),
                        role='Worker', kind='candidate_generation',
                        invocation_id=worker_id, payload=request,
                    )
                if type(response) is not dict or not set(response) <= {'candidate', 'payload_root', 'appeal'}:
                    raise ContractError('Worker 返回未知字段；不接受自报批准或报告')
                if 'appeal' in response:
                    if current is None or set(response) != {'appeal'}:
                        raise ContractError('申诉必须单独针对当前失败候选')
                    manifest, candidate, snapshot, payload, view, semantic, directory = current
                    self._current(manifest, snapshot, view)
                    if auditor is None:
                        raise _Stop('未配置规则审查模型')
                    if self.state['audit_attempts'] >= 1:
                        raise _Stop('一次规则争议审查机会已使用；不重复申诉')
                    if self.state['state'] != 'checking':
                        self._transition('checking')
                    self._transition('rule_review')
                    self._save()
                    def save_seen(keys):
                        self.state['seen_keys'] = keys
                        self._save()
                    seen = _Seen(self.state['seen_keys'], save_seen)
                    audit_id = self.config['operation_id'] + '-rule-audit-round-' + str(self.state['candidates'])
                    def managed_audit(audit_request, *, timeout):
                        try:
                            return self._call(
                                lambda actual_timeout: auditor.transport(audit_request, timeout=actual_timeout),
                                role='RuleAuditor', kind='rule_appeal', invocation_id=audit_id,
                                payload=audit_request, appeals=1,
                            )
                        except _Stop as exc:
                            if 'budget_exhausted' in str(exc):
                                raise AuditBudgetExhausted(str(exc)) from exc
                            raise
                    result = auditor.audit(manifest, response['appeal'], feedback['failures'],
                        seen_keys=seen, managed_call=managed_audit, timeout=self._remaining())
                    self._remaining()
                    (directory / 'audit.json').write_bytes(canonical_json(dict(
                        status=result.status, report=result.report, reason=result.reason)) + b'\n')
                    if result.status != 'reviewed':
                        raise _Stop('规则审查停止: ' + result.status)
                    if not bindings_match(result.report, **{k: manifest[k] for k in BINDINGS}):
                        raise _Stop('规则审查绑定失效')
                    if result.report['disposition'] != 'rule_valid':
                        raise _Stop('规则审查转人工: ' + result.report['disposition'])
                    feedback['audit'] = result.report
                    self._transition('repairing', '规则有效，使用剩余候选机会修复')
                    continue
                if not {'candidate', 'payload_root'} <= set(response):
                    raise ContractError('Worker 未提供候选及载荷根')
                if self.state['state'] != 'checking':
                    self._transition('checking')
                current = self._freeze(response, round_number)
                manifest, candidate, snapshot, payload, view, semantic, directory = current
                self._current(manifest, snapshot, view)
                reports = self._call(lambda timeout: run_gates(manifest, candidate, snapshot, view,
                    review_prompt_version=PROMPT_VERSION), model=False)
                reports = [r for r in reports if r['gate'] in ('G0', 'G1', 'G2')]
                if {r['gate'] for r in reports} != {'G0', 'G1', 'G2'}:
                    raise _Stop('缺少必需确定性门禁')
                opinion = None
                if all(r['result'] == 'pass' for r in reports) and semantic:
                    if reviewer is None:
                        raise _Stop('未配置独立内容审查模型')
                    request_review = self._review_request(manifest, candidate, snapshot, view)
                    review_id = self.config['operation_id'] + '-review-round-' + str(self.state['candidates']) + '-attempt-{attempt}'
                    response = self._call(
                        lambda timeout: self._review_call(request_review, reviewer, timeout, manifest),
                        role='Reviewer', kind='candidate_review', invocation_id=review_id,
                        payload=request_review,
                    )
                    opinion = response['opinion']
                    actual_review_id = review_id.format(attempt=1)
                    self._record_review_identity(response, actual_review_id)
                    (directory / ('review-call-' + str(self.state['calls']) + '.json')).write_bytes(
                        canonical_json(opinion) + b'\n')
                    if opinion['result'] == 'error':
                        raise _Stop('内容审查不可用或响应无效；错误结果不自动重发')
                    gate = dict(contract_version='1.0', **{k: manifest[k] for k in BINDINGS},
                        gate='G3', result='pass' if opinion['result'] == 'recommend_pass' else 'fail',
                        findings=opinion['findings'], producer='coordinator-content-review')
                    reports.append(validate('gate_report', gate))
                    if opinion['result'] == 'insufficient_evidence':
                        raise _Stop('内容审查证据不足')
                self._current(manifest, snapshot, view)
                for report in reports:
                    validate('gate_report', report)
                    if not bindings_match(report, **{k: manifest[k] for k in BINDINGS}):
                        raise _Stop('门禁报告版本失效')
                (directory / 'reports.json').write_bytes(canonical_json(dict(reports=reports, review=opinion)) + b'\n')
                (directory / 'reports').mkdir(exist_ok=True)
                for report in reports:
                    (directory / 'reports' / (report['gate'] + '.json')).write_bytes(canonical_json(report) + b'\n')
                if all(r['result'] == 'pass' for r in reports):
                    bundle = dict(manifest=manifest, candidate=candidate, snapshot=snapshot,
                        payload_root=str(payload), reports=reports, review=opinion)
                    self._transition('ready_to_apply', '候选通过；未执行正式写入或签发用户批准')
                    return LoopResult('ready_to_apply', self.state['reason'], bundle, copy.deepcopy(self.state))
                if any(r['result'] in ('error', 'unsupported') for r in reports):
                    raise _Stop('确定性门禁错误，不能降级通过')
                self._charge_repair(self.state['candidates'])
                feedback = dict(manifest=manifest, failures={
                    'reports/' + r['gate'] + '.json': r for r in reports if r['result'] == 'fail'}, review=opinion)
                self._transition('repairing', '候选未通过，反馈具体失败')
        except (Exception,) as exc:
            reason = str(exc) if isinstance(exc, _Stop) else '运行停止: ' + type(exc).__name__
            if self.state['state'] in ('prepared',):
                self._transition('failed', reason)
            else:
                self._transition('awaiting_human', reason)
            return LoopResult(self.state['state'], reason, None, copy.deepcopy(self.state))
