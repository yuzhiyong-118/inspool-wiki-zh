"""复用宿主模型的通用会话；具体 SubAgent 调度由可信宿主提供。"""
from __future__ import annotations

from pathlib import Path

from .native import InheritedTransport
from .readonly import answer_query
from .supervisor import HostError, StandaloneHost


class AgentSession:
    """共享会话身份记录；只读入口不初始化写入运行器或私有状态。"""

    def __init__(self, root, dispatcher, *, parent_session_id, state_dir=None):
        self.root = Path(root).absolute()
        self.state_dir = state_dir
        self.transport = InheritedTransport(dispatcher, parent_session_id=parent_session_id)
        self._maintenance = None

    def query(self, question, **limits):
        if 'mode' in limits or 'transport' in limits:
            raise HostError('问答角色和 transport 由可信会话固定')
        return answer_query(self.root, question, self.transport, mode='query', **limits)

    def lint(self, question='检查所选页面的证据、冲突和关系语义', **limits):
        if 'mode' in limits or 'transport' in limits:
            raise HostError('检查角色和 transport 由可信会话固定')
        return answer_query(self.root, question, self.transport, mode='lint', **limits)

    def heal(self, operation_id, *, plan=None, min_refs=3, **limits):
        from .heal import build_heal_plan, run_heal_plan, verify_heal_plan
        if plan is None:
            plan = build_heal_plan(self.root, operation_id=operation_id, min_refs=min_refs)
        elif type(plan) is not dict or plan.get('operation_id') != operation_id:
            raise HostError('修复计划与本次操作身份不一致')
        verify_heal_plan(self.root, plan)
        if not plan['actions']:
            return dict(status='no_changes', applied=False, plan_digest=plan['plan_digest'])
        return run_heal_plan(self.maintenance, plan, **limits)

    def invoke_attested(self, envelope, *, timeout):
        return self.transport.invoke_attested(envelope, timeout=timeout)

    def learn(self, operation_id, task, allowed_paths, input_refs=(), **limits):
        return self.maintenance.run_learning_operation(
            operation_id, task, allowed_paths, input_refs, **limits,
        )

    @property
    def maintenance(self):
        """仅供可信宿主使用，不能注册为模型的任意工具。"""
        if self.state_dir is None:
            raise HostError('维护操作需要库外同卷的私有 state_dir；只读查询不需要')
        if self._maintenance is None:
            self._maintenance = StandaloneHost(self.root, self.state_dir,
                                               transport=self.transport)
        return self._maintenance
