"""可信 Host 的知识正式接线；模型 JSON 与学习准入均不授予此权限。"""
from __future__ import annotations

import copy
import secrets
import time

from ..contracts import digest
from ..coordinator import Coordinator
from ..executor import Executor, ExecutionError
from ..runtime import knowledge_ingest as runtime
from .knowledge_candidate import verify_adoption
from .supervisor import HostError


def preparation_digest(record):
    k = record['knowledge']
    return digest({key:k[key] for key in ('context','prepared','preparedDigest','request',
                                         'source_root','baseline_scope')})


def coordinator(host, record):
    config = dict(record['config']); config.pop('root')
    return Coordinator(host.root, host.operations/digest(config['operation_id'])/'review-runtime',
                       runtime=host.runtime, registry=host.registry, **config)


def validate_binding(record, admission):
    runtime.parse_knowledge_admission(admission)
    k = record['knowledge']; b = record['bundle']; a = k.get('authorization')
    if (not isinstance(a,dict) or a.get('schema')!='knowledge-ingest-host-authorization/1'
            or a.get('sequence')!='knowledge_only' or not a.get('reason')
            or a.get('allowed_paths')!=b['manifest']['allowed_paths']
            or a.get('operation_id')!=record['config']['operation_id']
            or digest(a)!=admission['authorization_digest']
            or preparation_digest(record)!=admission['preparation_digest']
            or digest(b['manifest'])!=admission['manifest_digest']
            or k['baseline_scope']!=admission['view_scope']):
        raise HostError('知识准入与原宿主授权、准备依据或候选范围不一致')


def check_current_inputs(host, operation_id, admission):
    record = host.load_pending(operation_id)
    validate_binding(record,admission)
    opinion = record['knowledge']['opinion']
    if opinion is not None and opinion['result']!='recommend_pass':
        raise HostError('当前独立内容审阅要求修改，不能新提交该候选')
    return verify_adoption(host,record)


def admit(host, operation_id, *, authorization_reason, sequence):
    """仅由已获用户授权的可信宿主调用；reason 是审计说明，不是模型凭据。"""
    if (type(authorization_reason) is not str or not authorization_reason.strip()
            or len(authorization_reason)>2000):
        raise HostError('须记录可信宿主实际收到的本次整理授权依据')
    if sequence != 'knowledge_only':
        raise HostError('本入口不认证先学后入库的解除条件；不得把缺失学习证据当已完成')
    from ..runtime.migration import assert_runtime_creation_allowed
    assert_runtime_creation_allowed(host.root,host.state_dir,operation_id)
    # 与提交共用 OS 接受锁，多个进程不能为同一 pending 竞相覆盖宿主授权。
    with host._lock, Executor(host.root,host.private/'journals').acceptance_barrier():
        record = host.load_pending(operation_id)
        if record.get('kind')!='knowledge_candidate': raise HostError('仅接纳原知识候选')
        if record['knowledge']['baseline_scope']!='knowledge_content':
            raise HostError('知识正式准入要求明确完整的 knowledge_content 范围')
        opinion = record['knowledge']['opinion']
        if opinion is not None and opinion['result']!='recommend_pass':
            raise HostError('已有独立审阅要求修改，不能换次调用为同一候选争取通过')
        verify_adoption(host,record)
        auth = record['knowledge'].get('authorization')
        if auth:
            if auth['reason']!=authorization_reason or auth['sequence']!=sequence:
                raise HostError('原知识整理授权不可重绑')
        else:
            auth = {'schema':'knowledge-ingest-host-authorization/1','id':secrets.token_hex(16),
                'operation_id':operation_id,'reason':authorization_reason,'sequence':sequence,
                'allowed_paths':record['bundle']['manifest']['allowed_paths'],'issued_at':time.time()}
            record['knowledge']['authorization'] = auth
            host._save_pending(operation_id,record)
        c = coordinator(host,record)
        try:
            ids = c.runtime_ids
            task = host.runtime.store.mutate(lambda db: host.runtime._task(db,ids['task_id']))
            manifest = record['bundle']['manifest']
            admission = {'schema':runtime.SCHEMA, **ids,'operation_id':operation_id,
                'workflow_id':task['workflow_ref']['workflow_id'],
                'policy_digest':task['current_policy_digest'],'submission_epoch':task['submission_epoch'],
                'created_generation':c.ownership['generation'],'manifest_digest':digest(manifest),
                **{k:manifest[k] for k in ('candidate_digest','dependencies_digest','rules_digest','mapping_digest')},
                'preparation_digest':preparation_digest(record),'authorization_digest':digest(auth),
                'view_scope':'knowledge_content'}
            validate_binding(record,admission)
            runtime.bind(host.runtime,admission)
        finally: c.close()
        return {'status':'admitted','applied':False,'operation_id':operation_id,
            'admissionDigest':digest(admission),'nextAction':'apply_same_candidate_with_final_G3'}


def execute(host, record, *, recover=False):
    operation_id = record['config']['operation_id']
    admission = runtime.load(host.runtime,operation_id)
    if admission is None:
        return {'status':'knowledge_admission_required','applied':False,
                'reason':'须通过已授权的可信宿主为原候选建立专用非教学准入'}
    validate_binding(record,admission)
    executor = Executor(host.root,host.private/'journals',view_scope='knowledge_content')
    host.runtime.executor = executor

    def finish(result):
        result = runtime.reconcile(host.runtime,admission,result)
        return {'status':result['state'],'applied':result['applied'],'execution':result['execution'],
                'admissionDigest':digest(admission)}

    # 终态和已接受 WAL 的恢复不重审、不重新授权，不能被自己已写的基线变化卡住。
    if recover: return finish(executor.recover(operation_id))
    terminal = executor.lookup_terminal(record['bundle'],admission)
    if terminal is not None: return finish(terminal)
    if host.offline: raise HostError('新正式提交需要已配置的最终 G3 transport')
    runtime.check_current(host.runtime,admission)
    check_current_inputs(host,operation_id,admission)
    c = coordinator(host,record)
    try:
        executor.reviewer = host.transport
        executor.review_timeout = record['config']['call_timeout']
        executor.invocation_port = c.port
        executor.acceptance_context = lambda original: runtime.acceptance(host.runtime,original,
            lambda: check_current_inputs(host,operation_id,original))
        return finish(executor.apply(record['bundle'],admission=admission))
    finally: c.close()


def revoke(host, record):
    admission = runtime.load(host.runtime,record['config']['operation_id'])
    if admission is None: return {'status':'knowledge_admission_required','applied':False}
    validate_binding(record,admission)
    host.runtime.executor = Executor(host.root,host.private/'journals')
    return runtime.revoke(host.runtime,admission)


def inspect_admission(host, record):
    admission = runtime.load(host.runtime,record['config']['operation_id'])
    if admission is None: return {'state':'not_admitted','formalWriteAuthorized':False}
    validate_binding(record,admission)
    row = host.runtime.store.mutate(lambda db: db.execute(
        'SELECT revoked FROM knowledge_ingest_admissions WHERE operation_id=?',
        (admission['operation_id'],)).fetchone()[0])
    # 不将已保存准入当作当前条件通过；最终动态校验仍在 Executor 接受锁内。
    executor = Executor(host.root,host.private/'journals',view_scope=admission['view_scope'])
    pending_execution = None
    try: result = executor.lookup_terminal(record['bundle'],admission)
    except ExecutionError as exc:
        if '必须先 recover' not in str(exc): raise
        result = None; pending_execution = 'recovery_required'
    return {'state':result['state'] if result else pending_execution or ('revoked' if row else 'admitted'),
        'admissionDigest':digest(admission),'formalWriteAuthorized':False,
        'authorizationReason':record['knowledge']['authorization']['reason'],
        'execution':result,'requiresFinalDynamicValidation':result is None}
