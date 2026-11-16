"""可信宿主 callback 的原生 SubAgent 桥接；不提供产品 SDK 或 OS 沙箱。"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import queue
import threading
import time
import uuid

from .backend import MAX_LINE_BYTES, _data, parse_json
from .readonly import QUERY_SYSTEM, LINT_SYSTEM, REVIEW_SYSTEM
from .supervisor import WORKER_SYSTEM
from ..review.content import PROMPT
from ..rule_audit.core import SYSTEM_PROMPT


class NativeError(ValueError):
    """拒绝无效调用；不回显任务、模型结果或宿主异常。"""


@dataclass(frozen=True)
class NativeRequest:
    request_id: str
    role: str
    system: str
    payload_json: str
    model_policy: str = 'inherit'
    fresh_context: bool = True
    tools: tuple = ()
    history: tuple = ()


@dataclass(frozen=True)
class NativeResult:
    """只能由可信 dispatcher 根据真实子会话记录构造，不能解析自模型输出。"""
    request_id: str
    role: str
    session_id: str
    output: object
    attestation: dict | None = None


# Only trusted runtime system constants select roles. Task text never does.
_ROUTES = {
    WORKER_SYSTEM: ('worker', {'system', 'input', 'documents'}),
    PROMPT: ('reviewer', {'system', 'input', 'reviewer_id'}),
    SYSTEM_PROMPT: ('auditor', {'system', 'prompt_version', 'rules', 'mapping',
                               'appeal', 'failure_reports', 'evidence_documents'}),
    QUERY_SYSTEM: ('query', {'system', 'question', 'documents', 'mode', 'validation_feedback'}),
    LINT_SYSTEM: ('lint', {'system', 'question', 'documents', 'mode', 'validation_feedback'}),
    REVIEW_SYSTEM: ('readonly-review', {'system', 'question', 'documents', 'proposal', 'mode'}),
}
_OUTPUT_KEYS = {
    'reviewer': {'contract_version', 'operation_id', 'candidate_digest', 'dependencies_digest',
                 'rules_digest', 'mapping_digest', 'validator_version', 'review_prompt_version',
                 'reviewer_id', 'result', 'findings', 'evidence_refs'},
    'auditor': {'contract_version', 'operation_id', 'candidate_digest', 'dependencies_digest',
                'rules_digest', 'mapping_digest', 'validator_version', 'review_prompt_version',
                'rule_ids', 'failure_refs', 'evidence', 'goal_conflict', 'minimal_counterexample',
                'proposal', 'impact', 'disposition'},
    'query': {'status', 'answer', 'citations', 'judgment'},
    'lint': {'status', 'findings'},
    'readonly-review': {'verdict', 'reason'},
}


def _json_object(value):
    try:
        if type(value) is dict:
            _data(value)
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        elif type(value) is str:
            raw = value.encode('utf-8')
        elif type(value) is bytes:
            raw = value
        else:
            raise ValueError('type')
        if len(raw) > MAX_LINE_BYTES:
            raise ValueError('size')
        result = parse_json(raw)
        if type(result) is not dict:
            raise ValueError('object')
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise NativeError('原生传输 JSON 无效或超限') from None


class InheritedTransport:
    """一个宿主生命周期复用一个实例；dispatcher 是受信代码而非模型工具。"""
    def __init__(self, dispatcher, *, parent_session_id):
        if (not callable(dispatcher) or type(parent_session_id) is not str or
                not parent_session_id.strip() or len(parent_session_id) > 256):
            raise NativeError('需要可信 dispatcher 和父会话标识')
        self._dispatcher = dispatcher
        self._parent = parent_session_id
        self._sessions = set()
        self._attestations = {}
        self._lock = threading.Lock()

    def _issue_attestation(self, record):
        from ..runtime.identity import TrustedAttestation
        token = uuid.uuid4().hex
        with self._lock:
            self._attestations[token] = dict(record)
        return TrustedAttestation(record, transport=self, token=token)

    def _consume_attestation(self, handle):
        from ..runtime.identity import AttestationError, TrustedAttestation, parse_attestation
        if type(handle) is not TrustedAttestation or handle._transport is not self:
            raise AttestationError('Attestation 不属于当前 InheritedTransport')
        with self._lock:
            record = self._attestations.get(handle._token)
            if record is None:
                raise AttestationError('Attestation 未登记或已消费')
            if handle._snapshot != record or dict(handle) != record:
                raise AttestationError('Attestation 字段在签发后被改绑')
            parsed = parse_attestation(
                record, request_id=record['request_id'],
                session_id=record['session_id'], role=record['role'],
            )
            del self._attestations[handle._token]
            return parsed

    def invoke_attested(self, envelope, *, timeout):
        if (type(timeout) not in (int, float) or not 0 < timeout <= 86400 or
                not math.isfinite(timeout)):
            raise NativeError('原生调用超时参数无效')
        deadline = time.monotonic() + timeout
        if type(envelope) is not dict:
            raise NativeError('原生调用必须来自可信运行器 envelope')
        value = _json_object(envelope)
        system = value.get('system')
        route = _ROUTES.get(system) if type(system) is str else None
        if route is None or set(value) != route[1]:
            raise NativeError('未知固定提示或 envelope 字段')
        role = route[0]
        if ((role in ('query', 'lint') and value['mode'] != role) or
                (role == 'readonly-review' and value['mode'] not in ('query', 'lint'))):
            raise NativeError('只读模式与固定角色不符')
        payload = {k: v for k, v in value.items() if k != 'system'}
        request = NativeRequest(uuid.uuid4().hex, role, system,
                                json.dumps(payload, ensure_ascii=False, allow_nan=False))
        mailbox = queue.Queue(maxsize=1)

        def invoke():
            try:
                result = self._dispatcher(request, timeout=max(0, deadline - time.monotonic()))
                # Reserve every observed session, including late or invalid output.
                with self._lock:
                    if (type(result) is not NativeResult or type(result.session_id) is not str or
                            not result.session_id.strip() or len(result.session_id) > 256):
                        raise NativeError('原生子会话标识无效')
                    reused = result.session_id in self._sessions or result.session_id == self._parent
                    self._sessions.add(result.session_id)
                    if (reused or result.request_id != request.request_id or result.role != role):
                        raise NativeError('原生子会话绑定无效或会话已使用')
                output = _json_object(result.output)
                keys = set(output)
                if (role == 'worker' and keys not in ({'changes'}, {'appeal'}) or
                        role != 'worker' and keys != _OUTPUT_KEYS[role]):
                    raise NativeError('原生结果含未知或缺失字段')
                attestation = result.attestation
                if attestation is not None:
                    from ..runtime.identity import parse_attestation
                    attestation = self._issue_attestation(parse_attestation(
                        attestation, request_id=request.request_id,
                        session_id=result.session_id, role=role,
                    ))
                mailbox.put((True, {'output': output, 'attestation': attestation}))
            except BaseException:
                mailbox.put((False, None))

        threading.Thread(target=invoke, daemon=True, name='wiki-native-subagent').start()
        try:
            ok, result = mailbox.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            raise NativeError('原生子会话超时；迟到结果无效') from None
        if time.monotonic() >= deadline:
            raise NativeError('原生子会话超时；迟到结果无效')
        if not ok:
            raise NativeError('原生子会话失败或结果无效')
        return result

    def __call__(self, envelope, *, timeout):
        return self.invoke_attested(envelope, timeout=timeout)['output']
