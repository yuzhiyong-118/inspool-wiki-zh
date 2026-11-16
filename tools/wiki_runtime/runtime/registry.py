"""静态可信能力注册；不提供插件发现、热更新或权限矩阵。"""
from __future__ import annotations

import copy

from tools.wiki_runtime.contracts import ContractError
from .loop_protocol import parse_capability_manifest, parse_step, parse_workflow_ref
from .protocol import parse_invocation_spec


ROLE_CAPABILITIES = {
    'Researcher': 'researcher',
    'Worker': 'worker',
    'Tutor': 'tutor',
    'Reviewer': 'reviewer',
    'Assessor': 'assessor',
    'ConflictReviewer': 'conflict-reviewer',
    'RuleAuditor': 'rule-auditor',
    'ExecutorG3': 'executor-g3',
}


class CapabilityError(ContractError):
    pass


class CapabilityRegistry:
    def __init__(self, manifests=()):
        self._manifests = {}
        self._revoked = set()
        for manifest in manifests:
            self.register(manifest)

    def register(self, manifest: dict) -> dict:
        record = copy.deepcopy(parse_capability_manifest(manifest))
        capability_id = record['capability_id']
        existing = self._manifests.get(capability_id)
        if existing is not None and existing != record:
            raise CapabilityError('相同 capability_id 不得绑定不同实现: ' + capability_id)
        self._manifests[capability_id] = record
        return copy.deepcopy(record)

    def revoke(self, capability_id: str) -> None:
        if capability_id not in self._manifests:
            raise CapabilityError('不能撤销未注册能力: ' + capability_id)
        self._revoked.add(capability_id)

    def manifests(self) -> list[dict]:
        return [copy.deepcopy(self._manifests[key]) for key in sorted(self._manifests)]

    def require(self, capability_id: str, *, implementation_digest: str | None = None,
                required_checks=()) -> dict:
        manifest = self._manifests.get(capability_id)
        if manifest is None or capability_id in self._revoked:
            raise CapabilityError('能力缺失或已撤销: ' + capability_id)
        if (implementation_digest is not None
                and manifest['implementation_digest'] != implementation_digest):
            raise CapabilityError('能力实现摘要已变化: ' + capability_id)
        if not set(manifest['required_checks']) <= set(required_checks):
            raise CapabilityError('Workflow 未保留能力必需检查: ' + capability_id)
        return copy.deepcopy(manifest)

    def validate_workflow(self, workflow: dict) -> dict:
        record = parse_workflow_ref(workflow)
        for capability_id in record['allowed_capabilities']:
            self.require(
                capability_id, required_checks=record['required_checks'],
            )
        return record

    def validate_step(self, step: dict, workflow: dict) -> dict:
        record = parse_step(step)
        selected = self.validate_workflow(workflow)
        if record['capability_id'] not in selected['allowed_capabilities']:
            raise CapabilityError('Step 能力不在 Workflow 允许集合内')
        self.require(
            record['capability_id'], implementation_digest=record['implementation_digest'],
            required_checks=selected['required_checks'],
        )
        return record

    def validate_invocation(self, spec: dict, workflow: dict) -> dict:
        record = parse_invocation_spec(spec)
        selected = self.validate_workflow(workflow)
        capability_id = ROLE_CAPABILITIES.get(record['role'])
        if capability_id not in selected['allowed_capabilities']:
            raise CapabilityError('Invocation 角色不在 Workflow 允许集合内')
        self.require(capability_id, required_checks=selected['required_checks'])
        return record


class RegisteredInvocationPort:
    """在统一 InvocationPort 前增加静态能力检查，不增加另一套账本。"""

    def __init__(self, port, registry: CapabilityRegistry, workflow: dict):
        self.port = port
        self.registry = registry
        self.workflow = copy.deepcopy(parse_workflow_ref(workflow))

    def invoke(self, spec: dict, call, timeout: float) -> dict:
        self.registry.validate_invocation(spec, self.workflow)
        return self.port.invoke(spec, call, timeout)

    def replay(self, spec: dict) -> dict:
        self.registry.validate_invocation(spec, self.workflow)
        return self.port.replay(spec)

    def remaining_run_time(self, run_id: str) -> float:
        return self.port.remaining_run_time(run_id)


def default_registry() -> CapabilityRegistry:
    """内置合成实现的静态声明；摘要只标识本版调用适配器。"""
    from tools.wiki_runtime.contracts import digest

    contracts = {
        'worker': 'candidate-1', 'reviewer': 'review-1', 'rule-auditor': 'audit-1',
        'executor-g3': 'review-1', 'researcher': 'research-1', 'tutor': 'teach-1',
        'assessor': 'assessment-1', 'conflict-reviewer': 'review-1',
    }
    manifests = []
    for capability_id, contract in contracts.items():
        checks = ['G3'] if capability_id in ('reviewer', 'executor-g3') else []
        manifests.append({
            'capability_id': capability_id,
            'implementation_digest': digest({'builtin_capability': capability_id, 'version': 1}),
            'contract_version': contract,
            'required_checks': checks,
            'usage_visibility': 'partial',
            'cancellation': 'best_effort',
        })
    return CapabilityRegistry(manifests)
