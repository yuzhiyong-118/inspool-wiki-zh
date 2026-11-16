"""有界完整基线上的 ingest 候选预览；仅复用 G0–G2，不签发正式凭据。"""
from __future__ import annotations

import os

from ..candidate import CandidateView
from ..contracts import bytes_digest, candidate_digest, digest, validate, validate_path
from ..gates import run_gates
from ..gates.core import MAPPING_PATH, VALIDATOR_VERSION, raw_parts
from ..isolation.gateway import _check_chain
from ..persistence.protocol import compile_candidate, validate_candidate_coverage
from .knowledge import _bounded, verify_knowledge
from .package_protocol import package_ref
from .preparation import LIMITS, _Reader, _fields, _need, _root, _text


class _BoundedView(CandidateView):
    """沿用候选视图语义；有界预检＋每次读取限额，保证级别仍为协作快照。"""
    def __init__(self, root, candidate, payload_root):
        self.reader = _Reader(dict(LIMITS, maxTotalBytes=64 * 1024 * 1024, maxSeconds=20))
        super().__init__(root, candidate, payload_root)

    def _scan(self):
        count = total = 0
        def fail(_):
            raise ValueError('baseline_unreadable')
        for parent, dirs, names in os.walk(self.root, followlinks=False, onerror=fail):
            self.reader.check()
            dirs[:] = sorted(d for d in dirs if d not in self.EXCLUDED)
            for name in [*dirs, *names]:
                count += 1
                _need(count <= 512, 'preview_baseline_entry_limit')
                path = self.root / os.path.relpath(os.path.join(parent, name), self.root)
                _check_chain(path)
                if path.is_file():
                    size = path.stat().st_size
                    _need(size <= 1024 * 1024, 'preview_baseline_file_limit')
                    total += size
                    _need(total <= 4 * 1024 * 1024, 'preview_baseline_byte_limit')
        return super()._scan()

    def _read_file(self, base, value):
        # 基线可以包含原始二进制附件；只有语义需要的 Markdown 才由旧门禁解码。
        self.reader.check()
        path = self._safe_path(base, value)
        _check_chain(path)
        _need(path.is_file(), 'preview_not_regular_file')
        before = path.stat()
        allowed = min(self.reader.limits['maxFileBytes'],
                      self.reader.limits['maxTotalBytes'] - self.reader.used)
        _need(allowed > 0 and before.st_size <= allowed, 'preview_read_limit')
        with path.open('rb') as stream:
            data = stream.read(allowed + 1)
        self.reader.used += len(data)
        _need(len(data) <= allowed, 'preview_read_limit')
        _check_chain(self._safe_path(base, value))
        after = path.stat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        _need(signature(before) == signature(after), 'preview_changed_during_read')
        self.reader.check()
        return data


def preview_wiki_changes(context, prepared, candidate, request, *, wiki_root, source_root, payload_root,
                         baseline_scope='whole_root'):
    _need(baseline_scope in ('whole_root', 'knowledge_content'), 'preview_baseline_scope')
    _bounded(request, 'preview_request_limit')
    _bounded(candidate, 'preview_candidate_limit')
    _fields(request, {'schema', 'intent', 'coverageSpec', 'rawBindings'}, 'preview_request_fields')
    _need(request['schema'] == 'wiki-preview-request/1', 'preview_request_schema')
    _text(request['intent'], 'preview_intent')
    current = verify_knowledge(context, prepared, wiki_root=wiki_root, source_root=source_root)
    if current['knowledgeState'] != 'reviewed_for_scope':
        return {'result': current['result'], 'previewState': current['knowledgeState'],
            'findings': [{'code': 'knowledge_not_reviewed_for_scope'}], 'artifactRefs': [],
            'nextAction': 'complete_knowledge_review', 'previewOnly': True, 'formalWriteAuthorized': False}
    root, payload = _root(wiki_root), _root(payload_root)
    _need(not root.is_relative_to(payload) and not payload.is_relative_to(root), 'preview_root_overlap')
    validate('candidate', candidate)
    _need(1 <= len(candidate['changes']) <= 64, 'preview_change_limit')
    _need(all(c['action'] == 'write' and c['path'].startswith(('wiki/', 'raw/'))
              for c in candidate['changes']), 'preview_write_scope')
    if baseline_scope == 'knowledge_content':
        from .content_view import ContentView
        view = ContentView(root, candidate, payload)
    else:
        view = _BoundedView(root, candidate, payload)
    # 完整基线包括规则映射；不把缺少正式库配套文件的镜像当作同一正式库。
    paths = list(view.iter_paths())
    view.read_bytes('AGENTS.md'); view.read_bytes(MAPPING_PATH)
    snapshot = view.dependency_snapshot()
    preview = compile_candidate(package_ref(current['package']), request['coverageSpec'], digest(snapshot))
    validate_candidate_coverage(candidate, preview)
    _need(request['coverageSpec']['candidate_id'] == candidate['operation_id'], 'preview_candidate_identity')
    claims = {c['claimId']: c for c in current['claimChecks']}
    selected = set()
    for row in preview['coverage']:
        _need(row['teaching_disposition'] == 'non_teaching' and row['objective_ref'] is None,
              'preview_no_L2_credentials')
        path, cid = row['candidate_path'], row['claim_id']
        is_content = any(path.startswith('wiki/' + kind + '/')
                         for kind in ('sources', 'concepts', 'entities', 'synthesis'))
        if is_content:
            _need(type(cid) is str and cid in claims and claims[cid]['state'] == 'reviewed_for_scope'
                  and row['evidence_disposition'] == 'supported', 'preview_claim_binding')
            selected.add(cid)
        else:
            _need(cid is None and row['evidence_disposition'] == 'mechanical', 'preview_mechanical_binding')
    _need(bool(selected), 'preview_empty_knowledge_scope')
    raw_bindings = request['rawBindings']
    _need(type(raw_bindings) is list and 1 <= len(raw_bindings) <= 3, 'preview_raw_bindings')
    originals = {s['source_id']: s for s in current['package']['sources']}
    mapped, raw_paths, findings = set(), set(), []
    for row in raw_bindings:
        _fields(row, {'sourceId', 'rawLocator', 'byteDigest', 'bindingMode'}, 'preview_raw_binding_fields')
        for key in ('sourceId', 'rawLocator'): _text(row[key], 'preview_raw_binding_text')
        sid, path = row['sourceId'], row['rawLocator']
        validate_path(path)
        _check_chain(root / path, missing=True)
        _need(sid in originals and sid not in mapped and path not in raw_paths
              and path.startswith('raw/unprocessed/') and path.endswith('.md'), 'preview_raw_identity')
        _need(row['bindingMode'] in ('whole', 'body', 'managed_extracted'), 'preview_raw_binding_mode')
        if not (root / path).is_file():
            findings.append({'code': 'raw_capture_required', 'ref': path}); continue
        original = view._read_baseline(path)
        if row['bindingMode'] == 'managed_extracted':
            from .managed_raw import managed_extracted
            _, expected = managed_extracted(view, path)
        else:
            expected = original if row['bindingMode'] == 'whole' else raw_parts(original)[1]
        _need(bytes_digest(original) == row['byteDigest']
              and bytes_digest(expected) == originals[sid]['content_digest'], 'preview_raw_source_bytes')
        mapped.add(sid); raw_paths.add(path)
    actual_raw = {c['path'] for c in candidate['changes']
                  if c['path'].startswith(('raw/unprocessed/', 'raw/processed/'))}
    if not findings: _need(actual_raw == raw_paths, 'preview_raw_change_coverage')
    evidence = {e['evidence_id']: e for e in current['package']['evidence']}
    for cid in selected:
        if not any(evidence[eid]['source_id'] in mapped for eid in claims[cid]['supportEvidenceIds']):
            findings.append({'code': 'claim_raw_capture_required', 'ref': cid})
    if findings:
        return {'result': 'needs_evidence', 'previewState': 'needs_evidence', 'findings': findings,
            'artifactRefs': [package_ref(current['package'])], 'candidatePreview': preview,
            'nextAction': 'capture_and_register_original_before_ingest', 'previewOnly': True,
            'formalWriteAuthorized': False}
    # 这里只构造检查输入，不创建受信 manifest／授权。operation_type 不能切换来绕过 ingest。
    snapshot = view.dependency_snapshot()
    manifest = {'contract_version': '1.0', 'operation_id': candidate['operation_id'],
        'operation_type': 'ingest', 'task': request['intent'], 'input_refs': sorted(raw_paths),
        'allowed_paths': sorted(c['path'] for c in candidate['changes']), 'rules_path': 'AGENTS.md',
        'rules_digest': bytes_digest(view.read_bytes('AGENTS.md')),
        'mapping_digest': bytes_digest(view.read_bytes(MAPPING_PATH)),
        'validator_version': VALIDATOR_VERSION, 'review_prompt_version': 'none',
        'dependencies_digest': digest(snapshot), 'candidate_digest': candidate_digest(candidate),
        'round': 1, 'required_gates': ['G0', 'G1', 'G2'], 'authorization_refs': []}
    reports = run_gates(manifest, candidate, snapshot, view)
    view.verify_dependencies()
    fresh = verify_knowledge(context, prepared, wiki_root=wiki_root, source_root=source_root)
    stale = fresh['knowledgeState'] != 'reviewed_for_scope'
    passed = all(r['result'] == 'pass' for r in reports) and not stale
    result = {'result': 'stale' if stale else 'ready_for_review' if passed else 'needs_evidence',
        'previewState': 'stale' if stale else 'ready_for_semantic_review' if passed else 'needs_evidence',
        'candidatePreview': preview, 'candidateDigest': candidate_digest(candidate),
        'snapshot': snapshot, 'deterministicReports': reports, 'findings': [],
        'artifactRefs': [package_ref(current['package'])], 'nextAction': 'independent_candidate_review' if passed
            else 'repair_candidate_or_dependencies', 'previewOnly': True, 'formalWriteAuthorized': False,
        'readinessIssued': False, 'assurance': 'bounded_cooperative_preview_not_executor_admission',
        'baselineFileCount': len(paths), 'baselineScope': baseline_scope,
        'temporaryMaterialization': True, 'modelCalls': 0}
    if baseline_scope == 'knowledge_content':
        from .content_view import content_scope
        result['contentScope'] = content_scope()
    result['previewDigest'] = digest(result)
    _bounded(result, 'preview_output_limit', 1536 * 1024)
    return result
