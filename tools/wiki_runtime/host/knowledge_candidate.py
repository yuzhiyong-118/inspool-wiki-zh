"""已审知识候选的接收与咨询审阅；正式写入须另走专用知识准入。"""
from __future__ import annotations

import copy
from pathlib import Path

from ..contracts import candidate_digest, digest, canonical_json
from ..evidence.content_view import ContentView
from ..evidence.preview import _BoundedView, preview_wiki_changes
from ..evidence.package_protocol import package_ref
from ..evidence.managed_raw import managed_extracted
from ..gates import run_gates
from ..gates.core import VALIDATOR_VERSION, MAPPING_PATH
from ..review import PROMPT_VERSION, build_request, review
from .supervisor import HostError
from tools.learning_book.evidence_store import atomic


def view_for(host, record):
    kind = ContentView if record['knowledge']['baseline_scope'] == 'knowledge_content' else _BoundedView
    return kind(host.root, record['bundle']['candidate'], record['bundle']['payload_root'])


def verify_adoption(host, record):
    k, bundle = record['knowledge'], record['bundle']
    result = preview_wiki_changes(k['context'], k['prepared'], bundle['candidate'], k['request'],
        wiki_root=host.root, source_root=k['source_root'], payload_root=bundle['payload_root'],
        baseline_scope=k['baseline_scope'])
    if (result['previewState'] != 'ready_for_semantic_review'
            or result['snapshot'] != bundle['snapshot']
            or digest(k['prepared']) != k['preparedDigest']):
        raise HostError('已接收知识候选或实际依据失效，不能刷新原前提')
    view = view_for(host, record)
    list(view.iter_paths())
    reports = run_gates(bundle['manifest'], bundle['candidate'], bundle['snapshot'], view,
                        review_prompt_version=PROMPT_VERSION)
    if not all(r['result'] == 'pass' for r in reports):
        raise HostError('已接收候选的当前确定性门禁未通过')
    view.verify_dependencies(bundle['snapshot'])
    return view


def inspect_adopted(host, record):
    import difflib
    from ..executor.core import _safe
    from ..contracts import bytes_digest
    k, bundle = record['knowledge'], record['bundle']
    current = 'current'
    try: verify_adoption(host, record)
    except (HostError,OSError,ValueError,KeyError,TypeError): current = 'stale_or_unavailable'
    diffs = []
    for change in bundle['candidate']['changes']:
        before = bytes.fromhex(k['before'][change['path']]) if change['precondition']['kind']=='hash' else b''
        if change['precondition']['kind']=='hash' and bytes_digest(before) != change['precondition']['sha256']:
            raise HostError('冻结原页不对应候选前提')
        target = _safe(Path(bundle['payload_root']),change['payload_path'])
        with target.open('rb') as stream: after = stream.read(1024*1024+1)
        if len(after)>1024*1024 or bytes_digest(after)!=change['sha256']:
            raise HostError('冻结候选内容损坏')
        try:
            diff=''.join(difflib.unified_diff(before.decode('utf-8').splitlines(True),
                after.decode('utf-8').splitlines(True),fromfile=change['path'],tofile=change['path']))
        except UnicodeError: diff='二进制差异；核对原件和候选SHA-256。'
        diffs.append({'path':change['path'],'action':change['action'],
                      'before_sha256':bytes_digest(before),'after_sha256':bytes_digest(after),'diff':diff})
    from .knowledge_ingest import inspect_admission
    admission = inspect_admission(host,record)
    return {'status':admission['state'] if admission['state'] in ('applied','recovered','recovery_required') else k['status'],
        'contentReviewState':k['status'],'applied':admission.get('state')=='applied','operation_id':record['config']['operation_id'],
        'context':record['context'],'context_digest':digest(record['context']),'diffs':diffs,
        'opinion':k['opinion'],'currentValidation':current,'usableForTransfer':current=='current'
            and k['status']=='reviewed_for_transfer' and (k['opinion'] or {}).get('result')=='recommend_pass',
        'formalWriteAuthorized':False,'knowledgeAdmission':admission,'knowledgeEvidence':{'prepared':k['prepared'],
            'queryCoverage':k['context']['coverage'],'previewRequest':k['request']}}


def adopt(host, operation_id, context, prepared, candidate, request, *, source_root, payload_root,
          baseline_scope='knowledge_content', max_calls=2, max_seconds=300, call_timeout=60):
    from ..runtime.migration import assert_runtime_creation_allowed
    if candidate['operation_id'] != operation_id:
        raise HostError('接收操作必须保留原候选身份')
    if type(max_calls) is not int or not 1 <= max_calls <= 8 or not 0 < call_timeout <= max_seconds <= 900:
        raise HostError('接收审阅预算超限')
    assert_runtime_creation_allowed(host.root, host.state_dir, operation_id)
    with host._lock:
        pending = host._record_path(operation_id)
        if pending.exists():
            saved = host.load_pending(operation_id)
            if (saved.get('kind') != 'knowledge_candidate' or saved['bundle']['candidate'] != candidate
                    or saved['knowledge']['prepared'] != prepared or saved['knowledge']['context'] != context
                    or saved['knowledge']['request'] != request or saved['knowledge']['baseline_scope'] != baseline_scope
                    or saved['knowledge']['source_root'] != str(Path(source_root).absolute())
                    or any(saved['config'][k] != v for k,v in
                        (('max_calls',max_calls),('max_seconds',max_seconds),('call_timeout',call_timeout)))):
                raise HostError('同操作接收输入变化，拒绝覆盖')
            verify_adoption(host, saved)
            return {'status':saved['knowledge']['status'], 'operation_id':operation_id,
                    'applied':False, 'replayed':True, 'nextAction':'inspect_or_review_knowledge'}
        result = preview_wiki_changes(context, prepared, candidate, request, wiki_root=host.root,
            source_root=source_root, payload_root=payload_root, baseline_scope=baseline_scope)
        if result['previewState'] != 'ready_for_semantic_review':
            raise HostError('仅接收当前确定性预览通过的知识候选')
        directory = host.operations/digest(operation_id)
        if directory.exists(): raise HostError('接收目录已存在，拒绝隐式重置')
        source_view = (ContentView if baseline_scope == 'knowledge_content' else _BoundedView)(host.root,candidate,payload_root)
        source_view.iter_paths()
        fixed = {c['payload_path']:source_view.read_bytes(c['path']) for c in candidate['changes']}
        source_view.verify_dependencies()
        payload = directory/'adopted'/'payload'
        payload.mkdir(parents=True,exist_ok=False)
        for name,data in fixed.items(): atomic(payload/name, data, immutable=True)
        bundle = {'candidate':copy.deepcopy(candidate), 'snapshot':result['snapshot'], 'payload_root':str(payload)}
        k = {'context':copy.deepcopy(context), 'prepared':copy.deepcopy(prepared), 'preparedDigest':digest(prepared),
            'request':copy.deepcopy(request), 'source_root':str(Path(source_root).absolute()),
            'baseline_scope':baseline_scope, 'status':'pending_review', 'opinion':None,
            'before':{c['path']:source_view._read_baseline(c['path']).hex() for c in candidate['changes']
                if c['precondition']['kind']=='hash'}}
        view = (ContentView if baseline_scope == 'knowledge_content' else _BoundedView)(host.root,candidate,payload)
        list(view.iter_paths())
        if view.dependency_snapshot() != result['snapshot']: raise HostError('接收物化期间依赖变化')
        refs = [r['rawLocator'] for r in request['rawBindings']]
        for row in request['rawBindings']:
            if row['bindingMode'] == 'managed_extracted': refs.append(managed_extracted(view,row['rawLocator'])[0])
        first = result['deterministicReports'][0]
        manifest = {'contract_version':'1.0', 'operation_id':operation_id,'operation_type':'ingest',
            'task':request['intent'], 'input_refs':sorted(set(refs)),
            'allowed_paths':sorted(c['path'] for c in candidate['changes']), 'rules_path':'AGENTS.md',
            **{key:first[key] for key in ('rules_digest','mapping_digest','dependencies_digest','candidate_digest')},
            'validator_version':VALIDATOR_VERSION,'review_prompt_version':PROMPT_VERSION,
            'round':1,'required_gates':['G0','G1','G2'],'authorization_refs':[]}
        bundle['manifest'] = manifest
        config = {'root':str(host.root), 'operation_id':operation_id, 'operation_type':'ingest',
            'task':request['intent'], 'allowed_paths':manifest['allowed_paths'], 'input_refs':manifest['input_refs'],
            'source_packages':[], 'max_calls':max_calls, 'max_seconds':max_seconds,
            'call_timeout':call_timeout, 'environment_retries':0}
        # runtime_managed标记新世代操作，避免被cutover误当legacy；不代表正式准入。
        record = {'kind':'knowledge_candidate','runtime_managed':True,'config':config,'bundle':bundle,
            'context':{'operation_id':operation_id,'candidate_digest':candidate_digest(candidate),
                'knowledge_package_ref':package_ref(prepared['package']),
                'knowledge_review_ref':{'id':prepared['reviewObservation']['id'],
                    'digest':digest(prepared['reviewObservation'])}, 'baseline_scope':baseline_scope,
                'formal_application':'non_teaching_admission_unavailable'}, 'knowledge':k}
        verify_adoption(host, record)
        host._save_pending(operation_id, record)
        return {'status':'pending_review','operation_id':operation_id,'applied':False,
                'nextAction':'inspect_or_review_knowledge','formalWriteAuthorized':False}


def review_adopted(host, operation_id):
    if host.offline: raise HostError('独立内容审阅需要已配置的真实宿主 transport')
    with host._lock:
        record = host.load_pending(operation_id)
        if record.get('kind') != 'knowledge_candidate': raise HostError('不是知识接收候选')
        view = verify_adoption(host, record)
        if record['knowledge']['opinion'] is not None:
            return {'status':record['knowledge']['status'],'applied':False,
                    'opinion':record['knowledge']['opinion'],'replayed':True,'formalWriteAuthorized':False}
        bundle = record['bundle']; manifest = bundle['manifest']; candidate = bundle['candidate']
        originals = {p:view._read_baseline(p) for p in manifest['input_refs']}
        before = {c['path']:view._read_baseline(c['path']) for c in candidate['changes'] if c['precondition']['kind']=='hash'}
        after = {c['path']:view.read_bytes(c['path']) for c in candidate['changes']}
        rr = build_request(manifest,candidate,bundle['snapshot'],rules=view.read_bytes('AGENTS.md'),
            mapping=view.read_bytes(MAPPING_PATH),originals=originals,original_pages=before,candidate_files=after)
        from ..coordinator import Coordinator
        coordinator_config = dict(record['config']);coordinator_config.pop('root')
        coordinator = Coordinator(host.root,host.operations/digest(operation_id)/'review-runtime',
            runtime=host.runtime,registry=host.registry,**coordinator_config)
        try:
            opinion = coordinator._call(lambda timeout:review(rr,transport=host.transport,timeout=timeout),
                role='Reviewer',kind='content_review',invocation_id=operation_id+'-adopted-review',payload=rr)
            from ..executor import Executor
            with Executor(host.root,host.private/'journals').acceptance_barrier():
                current = host.load_pending(operation_id)
                # 模型调用期间其他可信Host可能已签发授权；不能用旧record整体覆盖。
                fixed = lambda r: {key:r[key] for key in ('kind','config','bundle','context')}
                fields = ('context','prepared','preparedDigest','request','source_root','baseline_scope','before')
                if (fixed(current)!=fixed(record) or any(current['knowledge'][key]!=record['knowledge'][key]
                                                         for key in fields)):
                    raise HostError('审阅期间原接收候选或准备依据变化')
                verify_adoption(host, current)
                current['knowledge'].update(opinion=opinion, status='reviewed_for_transfer' if
                    opinion['result']=='recommend_pass' else 'needs_changes')
                host._save_pending(operation_id, current)
                record = current
        finally:
            coordinator.close()
        return {'status':record['knowledge']['status'],'applied':False,'opinion':opinion,
            'formalWriteAuthorized':False,'nextAction':'non_teaching_admission_unavailable'}
