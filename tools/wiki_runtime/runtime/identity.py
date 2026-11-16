"""可信宿主审查身份与不可复用证据；模型正文不能签发身份。"""
from __future__ import annotations

import copy

from tools.wiki_runtime.contracts import ContractError, digest
from .protocol import (
    _hash, _record, _text, parse_review_credential, review_credential_digest,
)


ATTESTATION_FIELDS = (
    'request_id', 'session_id', 'role', 'independent', 'context_digest',
)


class AttestationError(ContractError):
    pass


def parse_attestation(record: dict, *, request_id: str, session_id: str, role: str) -> dict:
    try:
        _record(record, ATTESTATION_FIELDS, 'Attestation')
        _text(record['request_id'], 'Attestation.request_id')
        _text(record['session_id'], 'Attestation.session_id')
        _text(record['role'], 'Attestation.role')
        _hash(record['context_digest'], 'Attestation.context_digest')
        if record['independent'] is not True:
            raise AttestationError('Attestation 未证明独立上下文')
        if (record['request_id'] != request_id or record['session_id'] != session_id
                or record['role'] != role):
            raise AttestationError('Attestation 与 dispatcher 会话绑定不一致')
    except (ContractError, TypeError) as exc:
        raise AttestationError(str(exc)) from exc
    return copy.deepcopy(record)


class TrustedAttestation(dict):
    """由 InheritedTransport 私有登记的一次性身份句柄。"""
    def __init__(self, record, *, transport, token):
        super().__init__(copy.deepcopy(record))
        self._transport = transport
        self._token = token
        self._snapshot = copy.deepcopy(record)

    def __deepcopy__(self, memo):
        return self

    def consume(self, *, role, review_request):
        if type(self) is not TrustedAttestation:
            raise AttestationError('Attestation 可信句柄类型无效')
        record = self._transport._consume_attestation(self)
        if record['role'] != role.lower():
            raise AttestationError('Attestation 角色与本次审查职责不匹配')
        if record['context_digest'] != digest(review_request):
            raise AttestationError('Attestation 未绑定本次冻结审查输入')
        return record


def invoke_with_optional_attestation(transport, envelope: dict, *, timeout: float):
    from ..host.native import InheritedTransport
    if isinstance(transport, InheritedTransport):
        return transport.invoke_attested(envelope, timeout=timeout)
    return {'output': transport(envelope, timeout=timeout), 'attestation': None}


def record_review_identity(service, *, attestation: TrustedAttestation | None, invocation_id: str,
                           learning_task_id: str, operation_id: str, role: str,
                           content_digest: str, evidence_digest: str,
                           dependencies_digest: str, rules_digest: str,
                           review_config: dict, review_request: dict,
                           opinion: dict, package_ref: dict,
                           objective_ids: list[str], scope_kind: str) -> dict:
    """Attestation 只证明宿主身份；真实 L3 仍需完整 Readiness 绑定。"""
    if attestation is None:
        service.save_unattested_review_evidence({
            'evidence_id': 'unattested-' + invocation_id,
            'learning_task_id': learning_task_id,
            'operation_id': operation_id,
            'content_digest': content_digest,
            'review_digest': digest(opinion),
            'validator_version': review_config['validator_version'],
        })
        return {'credential_reuse': 'disabled', 'credential': None}
    if type(attestation) is not TrustedAttestation:
        raise AttestationError('普通字典不是可信 Attestation；必须经 InheritedTransport 签发')
    attestation = attestation.consume(role=role, review_request=review_request)
    result = {
        'recommend_pass': 'pass', 'request_changes': 'changes_required',
        'insufficient_evidence': 'fail', 'reviewed': 'pass', 'error': 'fail',
    }.get(opinion.get('result', opinion.get('status')))
    if result is None:
        raise AttestationError('审查结论不能映射为凭据结果')
    credential = {
        'credential_id': 'credential-' + invocation_id,
        'learning_task_id': learning_task_id,
        'invocation_id': invocation_id,
        'role': role,
        'identity': attestation['session_id'],
        'independent': True,
        'content_digest': content_digest,
        'evidence_digest': evidence_digest,
        'dependencies_digest': dependencies_digest,
        'rules_digest': rules_digest,
        'prompt_digest': digest(review_request.get('system', '')),
        'review_config_digest': digest(review_config),
        'validator_version': review_config['validator_version'],
        'scope': {
            'kind': scope_kind,
            'objective_ids': objective_ids,
            'candidate_digest': content_digest,
            'package_ref': package_ref,
        },
        'result': result,
        'valid': result == 'pass',
    }
    parse_review_credential(credential)
    service.save_review_credential(credential)
    return {
        'credential_reuse': 'bound_only',
        'credential': copy.deepcopy(credential),
        'credential_digest': review_credential_digest(credential),
    }
