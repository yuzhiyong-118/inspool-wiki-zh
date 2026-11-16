"""有界私有学习投影：认可依据、知识范围、I3 字节与投影审阅分别绑定。"""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile

from tools.learning_book.contracts import validate_package
from ..contracts import digest
from ..host.backend import parse_json
from .knowledge import _bounded, verify_knowledge
from .package_protocol import package_ref
from .preparation import (
    HASH, LIMITS, _Reader, _fields, _need, _root, _strings, _text, _unseal, draft_learning_brief,
)


def _stop(state, code, **extra):
    result = dict(result=state if state != 'needs_review' else 'ready_for_review',
        projectionState=state, findings=[{'code': code}], artifactRefs=[],
        nextAction='review_current_inputs', mapping=None, previewOnly=True,
        formalWriteAuthorized=False, coursePublishAuthorized=False, **extra)
    _bounded(result, 'projection_output_limit', 1536 * 1024)
    return result


def _ref(record):
    return {'id': record['id'], 'digest': digest(record)}


def _history(previous, mapping, package):
    maps, sources = [], []
    if previous is not None:
        _need(type(previous) is dict and 'projectionDigest' in previous, 'previous_projection_shape')
        _need(previous['projectionDigest'] == digest({k: v for k, v in previous.items()
            if k != 'projectionDigest'}), 'previous_projection_digest')
        maps, sources = copy.deepcopy(previous['mapVersions']), copy.deepcopy(previous['sourceVersions'])
        _need({'mapId': previous['mapping']['mapId'], 'version': previous['mapping']['version'],
               'digest': digest(previous['mapping'])} in maps, 'previous_map_history_binding')
        _need(all({'sourceId': s['sourceId'], 'sourceVersionId': s['sourceVersionId'],
                   'digest': s['sha256']} in sources for s in previous['prepare']['sources']),
              'previous_source_history_binding')
    def extend(history, current, fields, keys, code):
        _need(type(history) is list and len(history) <= 256, 'projection_history_limit')
        seen = {}
        for row in history:
            _fields(row, fields, 'projection_history_fields')
            identity = tuple(row[k] for k in keys)
            for k in keys: _need(type(row[k]) in (str, int), 'projection_history_identity')
            _need(identity not in seen and type(row['digest']) is str and HASH.fullmatch(row['digest']),
                  'projection_history_identity')
            seen[identity] = row
        for row in current:
            identity = tuple(row[k] for k in keys)
            _need(identity not in seen or row == seen[identity], code)
            if identity not in seen: history.append(row); seen[identity] = row
        _need(len(history) <= 256, 'projection_history_limit')
        return history
    maps = extend(maps, [{'mapId': mapping['mapId'], 'version': mapping['version'], 'digest': digest(mapping)}],
        {'mapId', 'version', 'digest'}, ('mapId', 'version'), 'projection_map_version_conflict')
    sources = extend(sources, [{'sourceId': s['sourceId'], 'sourceVersionId': s['sourceVersionId'],
        'digest': s['sha256']} for s in package.manifest['sources']],
        {'sourceId', 'sourceVersionId', 'digest'}, ('sourceId', 'sourceVersionId'),
        'projection_source_version_conflict')
    return maps, sources


def _brief(context, brief, intent, wiki_root, source_root):
    _fields(brief, {'schema', 'briefId', 'version', 'learnerId', 'goals', 'backgroundRefs',
                    'prerequisites', 'included', 'excluded', 'pacing'}, 'brief_fields')
    _need(brief['schema'] == 'learning-brief/1' and brief['learnerId'] == context['learnerId'],
          'brief_subject')
    # 复用 K1 目标／时间／前置约束；允许只引用本次观察的子集，空时按 unknown。
    draft = draft_learning_brief(context, {k: brief[k] for k in (
        'briefId', 'version', 'goals', 'prerequisites', 'included', 'excluded', 'pacing')} |
        {'userIntent': intent}, wiki_root=wiki_root, source_root=source_root)
    _need(type(brief['backgroundRefs']) is list and len(brief['backgroundRefs']) <= 5,
          'background_refs')
    observations = [{'id': o['observationId'], 'digest': digest(o)} for o in context['observations']]
    for row in brief['backgroundRefs']:
        _fields(row, {'id', 'digest'}, 'background_ref_fields')
        _need(row in observations, 'background_binding')
    _need(len({digest(r) for r in brief['backgroundRefs']}) == len(brief['backgroundRefs']),
          'duplicate_background_ref')
    return draft


def _recognition(brief, recognition, intent, root):
    if recognition is None:
        return 'needs_clarification', 'recognition_missing'
    _fields(recognition, {'id', 'briefRef', 'submittedBy', 'attributedAuthor', 'recordedAt',
        'statement', 'defaults', 'assurance', 'evidenceRef', 'scope', 'acceptedIntent'},
        'recognition_fields')
    for key in ('id', 'submittedBy', 'attributedAuthor', 'recordedAt', 'acceptedIntent'):
        _text(recognition[key], 'recognition_text')
    _need(recognition['assurance'] == 'operator_supplied', 'recognition_assurance')
    _strings(recognition['defaults'], 'recognition_defaults')
    expected = {'briefId': brief['briefId'], 'version': brief['version'], 'digest': digest(brief)}
    if recognition['briefRef'] != expected:
        return 'stale', 'recognition_brief_stale'
    scope = {'goalIds': [g['goalId'] for g in brief['goals']], **{k: brief[k]
        for k in ('included', 'excluded', 'pacing')}}
    if (recognition['attributedAuthor'] != brief['learnerId'] or recognition['scope'] != scope
            or recognition['acceptedIntent'] != intent):
        return 'needs_clarification', 'recognition_scope_mismatch'
    evidence = recognition['evidenceRef']
    _fields(evidence, {'locator', 'byteDigest'}, 'recognition_evidence_fields')
    reader = _Reader(LIMITS)
    observed = reader.read(_root(root), evidence['locator'])
    if observed['byteDigest'] != evidence['byteDigest']:
        return 'stale', 'recognition_evidence_stale'
    _need(type(recognition['statement']) is str and 0 < len(recognition['statement']) <= 65536,
          'recognition_statement')
    _need(recognition['statement'] == observed['text'], 'recognition_statement_binding')
    return None, None


def _prepare(root, locator):
    """先封闭且有界读取，再使用原生 I3 归一化；禁止它放宽原件路径。"""
    root = _root(root)
    reader = _Reader(LIMITS)
    observed = reader.read(root, locator)
    manifest = parse_json(observed['text'])
    _fields(manifest, {'schemaVersion', 'packageId', 'corpusId', 'corpusVersionId',
        'preparationDecision', 'learningGoal', 'language', 'depth', 'sources', 'inputArtifacts'},
        'prepare_fields')
    _need(type(manifest['sources']) is list and 1 <= len(manifest['sources']) <= 3
          and type(manifest['inputArtifacts']) is list and 1 <= len(manifest['inputArtifacts']) <= 16,
          'projection_members')
    expected_source = {'sourceId', 'sourceVersionId', 'sha256', 'path', 'metadata'}
    expected_artifact = {'inputArtifactId', 'sourceId', 'sourceVersionId', 'sha256', 'path',
                         'mediaType', 'extraction', 'coverage'}
    deps = {locator: observed['byteDigest']}
    fixed = {locator: observed['text'].encode('utf-8')}
    for rows, fields in ((manifest['sources'], expected_source),
                          (manifest['inputArtifacts'], expected_artifact)):
        for row in rows:
            _fields(row, fields, 'prepare_member_fields')
            data = reader.read(root, row['path'])
            _need(data['bytes'] > 0 and data['byteDigest'] == row['sha256'], 'projection_byte_mismatch')
            deps[row['path']] = data['byteDigest']
            fixed[row['path']] = data['text'].encode('utf-8')
    # 原生 I3 只读取已经固定且有界的临时副本，不重新无界打开外部文件。
    with tempfile.TemporaryDirectory(prefix='knowledge-projection-') as directory:
        snapshot = Path(directory)
        _need(snapshot.name.startswith('knowledge-projection-'), 'projection_snapshot_scope')
        for path, data in fixed.items():
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        package = validate_package(snapshot / locator, snapshot)
    # 返回对象仅使用固定 manifest/inputs；不导出已清理的临时定位。
    from tools.learning_book.contracts import Package
    locators = {('source:' + r['sourceId']): str(root / r['path']) for r in manifest['sources']}
    locators.update({('artifact:' + r['inputArtifactId']): str(root / r['path'])
                     for r in manifest['inputArtifacts']})
    package = Package(package.manifest, package.corpus, package.inputs, locators, root)
    # 原生归一化期间的协作变化也必须检测。
    for path, byte_digest in deps.items():
        _need(reader.read(root, path)['byteDigest'] == byte_digest, 'projection_changed_during_read')
    _need(all(package.inputs[a['remotePath']] == reader.read(root, original['path'])['text'].encode('utf-8')
        for a, original in zip(package.manifest['inputArtifacts'], manifest['inputArtifacts'])),
        'projection_input_snapshot')
    return manifest, package, deps


def _coverage(request, brief, prepared, package):
    knowledge = prepared['package']
    sources = {s['source_id']: s for s in knowledge['sources']}
    native = {s['sourceId']: s for s in package.manifest['sources']}
    artifacts = {a['inputArtifactId']: a for a in package.manifest['inputArtifacts']}
    bindings = request['sourceBindings']
    _need(type(bindings) is list and len(bindings) == len(native), 'binding_coverage')
    bound, direct = {}, set()
    for row in bindings:
        _need(type(row) is dict, 'binding_shape')
        _fields(row, {'mode', 'sourceId', 'sourceVersionId', 'byteDigest'} |
            ({'knowledgeSourceRef'} if row.get('mode') == 'direct_source' else set()), 'binding_fields')
        _need(row['mode'] in ('direct_source', 'authored_projection'), 'binding_mode')
        _text(row['sourceId'], 'binding_identity', 180)
        sid = row['sourceId']
        _need(sid in native and sid not in bound, 'binding_identity')
        _need((row['sourceVersionId'], row['byteDigest']) ==
              (native[sid]['sourceVersionId'], native[sid]['sha256']), 'binding_bytes')
        if row['mode'] == 'direct_source':
            ref = row['knowledgeSourceRef']
            _fields(ref, {'source_id', 'version', 'content_digest'}, 'knowledge_source_ref')
            _need(type(ref['source_id']) is str and ref['source_id'] in sources, 'knowledge_source_identity')
            original = sources[ref['source_id']]
            _need(ref == {k: original[k] for k in ref} and ref['content_digest'] == row['byteDigest'],
                  'direct_source_binding')
            identity = (ref['source_id'], ref['version'])
            _need(identity not in direct, 'duplicate_direct_source')
            direct.add(identity)
        elif sid in sources:
            _need((row['sourceVersionId'], row['byteDigest']) !=
                  (sources[sid]['version'], sources[sid]['content_digest']), 'authored_self_evidence')
            _need(row['sourceVersionId'] != sources[sid]['version'], 'authored_source_version_collision')
        bound[sid] = row
    checks = {c['claimId']: c for c in prepared['claimChecks']}
    evid = {e['evidence_id']: e for e in knowledge['evidence']}
    goals = {g['goalId'] for g in brief['goals']}
    rows = request['coverage']
    _need(type(rows) is list and 1 <= len(rows) <= 80, 'coverage_rows')
    selected, covered_goals, covered_artifacts, identities = set(), set(), set(), set()
    for row in rows:
        _fields(row, {'goalId', 'claimIds', 'evidenceIds', 'artifactId', 'disposition', 'reason'},
                'coverage_fields')
        for key in ('goalId', 'artifactId', 'reason'): _text(row[key], 'coverage_text')
        for key in ('claimIds', 'evidenceIds'): _strings(row[key], 'coverage_refs', empty=False, maximum=40)
        _need(row['goalId'] in goals and row['artifactId'] in artifacts, 'coverage_reference')
        _need(row['disposition'] in ('required', 'optional'), 'coverage_disposition')
        key = (row['goalId'], row['artifactId'])
        _need(key not in identities, 'coverage_duplicate'); identities.add(key)
        _need(set(row['claimIds']) <= set(checks) and set(row['evidenceIds']) <= set(evid), 'coverage_reference')
        for cid in row['claimIds']:
            _need(checks[cid]['state'] == 'reviewed_for_scope' and
                  bool(set(row['evidenceIds']) & set(checks[cid]['supportEvidenceIds'])), 'coverage_support')
        _need(all(any(eid in checks[cid]['supportEvidenceIds'] for cid in row['claimIds'])
                  for eid in row['evidenceIds']), 'unreviewed_coverage_evidence')
        binding = bound[artifacts[row['artifactId']]['sourceId']]
        if binding['mode'] == 'direct_source':
            _need(all(evid[eid]['source_id'] == binding['knowledgeSourceRef']['source_id']
                      for eid in row['evidenceIds']), 'direct_evidence_source')
        selected.update(row['claimIds']); covered_goals.add(row['goalId']); covered_artifacts.add(row['artifactId'])
    _need(covered_goals == goals and covered_artifacts == set(artifacts), 'incomplete_goal_or_artifact_coverage')
    excluded = request['excludedClaims']
    _need(type(excluded) is list and len(excluded) <= 10, 'excluded_claims')
    seen = set()
    for row in excluded:
        _fields(row, {'claimId', 'reason'}, 'excluded_fields')
        for key in row: _text(row[key], 'excluded_text')
        _need(row['claimId'] not in seen, 'duplicate_exclusion'); seen.add(row['claimId'])
    _need(seen == set(checks) - selected, 'excluded_claim_coverage')


def build_learning_projection(context, prepared, brief, request, *, wiki_root, source_root,
        projection_root, recognition_root, prepare_path='prepare.json', recognition=None, review=None,
        previous=None):
    """读取外部准备者已物化的 prepare 和课文，导出已核对 manifest／映射；不发布。"""
    _bounded(request, 'projection_request_limit')
    _fields(request, {'schema', 'mapId', 'version', 'intent', 'sourceBindings', 'coverage', 'excludedClaims'},
            'projection_request_fields')
    _need(request['schema'] == 'learning-projection-request/1', 'projection_schema')
    for key in ('mapId', 'intent'): _text(request[key], 'projection_text')
    _need(type(request['version']) is int and request['version'] > 0, 'projection_version')
    body = _unseal(context)
    current = verify_knowledge(context, prepared, wiki_root=wiki_root, source_root=source_root)
    if current['knowledgeState'] != 'reviewed_for_scope':
        return _stop(current['knowledgeState'], 'knowledge_not_reviewed_for_scope')
    draft = _brief(context, brief, request['intent'], wiki_root, source_root)
    if draft['result'] != 'ready_for_review':
        return _stop(draft['result'], 'brief_incomplete')
    state, code = _recognition(brief, recognition, request['intent'], recognition_root)
    if state: return _stop(state, code)
    manifest, package, dependencies = _prepare(projection_root, prepare_path)
    _need(package.manifest['depth'] == brief['pacing']['depth'], 'projection_depth_scope')
    _coverage(request, brief, current, package)
    # 审查附件在最后加入，避免其摘要与 mapping 自身循环依赖。
    mapping = {'schema': 'preparation-map/1', 'mapId': request['mapId'], 'version': request['version'],
        'briefRef': {'briefId': brief['briefId'], 'version': brief['version'], 'digest': digest(brief)},
        'recognitionRef': _ref(recognition), 'packageRef': package_ref(current['package']),
        'reviewRef': _ref(current['reviewObservation']), 'prepareRef': {
            'packageId': package.manifest['packageId'], 'normalizedManifestDigest': digest(package.manifest)},
        'intent': request['intent'], **{k: copy.deepcopy(request[k])
            for k in ('sourceBindings', 'coverage', 'excludedClaims')}}
    artifact_refs = [{'artifactId': a['inputArtifactId'], 'byteDigest': a['sha256']}
                     for a in package.manifest['inputArtifacts']]
    review_request = {'schema': 'learning-projection-review-request/1',
        'mappingDigest': digest(mapping), 'artifactRefs': artifact_refs,
        'briefRef': mapping['briefRef'], 'recognitionRef': mapping['recognitionRef'],
        'packageRef': mapping['packageRef'], 'prepareRef': mapping['prepareRef'],
        'basisRefs': [mapping['reviewRef']],
        'purpose': '审实际上传全文、目标适切性、认可范围、新事实及判分依据；不等同实际生成课件I4。'}
    review_request['requestDigest'] = digest(review_request)
    common = {'reviewRequest': review_request, 'prepare': manifest,
              'prepareRef': mapping['prepareRef'], 'dependencies': dependencies,
              'draftMapping': copy.deepcopy(mapping), 'temporaryMaterialization': True}
    if review is None: return _stop('needs_review', 'projection_review_missing', **common)
    _fields(review, {'schema', 'id', 'requestDigest', 'reviewedBy', 'recordedAt', 'decision',
        'reason', 'basisRefs', 'artifactRefs', 'assurance'}, 'projection_review_fields')
    _need(review['schema'] == 'learning-projection-review/1'
          and review['assurance'] == 'operator_supplied', 'projection_review_assurance')
    for key in ('id', 'reviewedBy', 'recordedAt', 'reason'): _text(review[key], 'projection_review_text')
    if review['requestDigest'] != review_request['requestDigest']:
        return _stop('stale', 'projection_review_stale', **common)
    _need(review['basisRefs'] == review_request['basisRefs']
          and review['artifactRefs'] == artifact_refs, 'projection_review_scope')
    _need(review['decision'] in ('reviewed_for_scope', 'needs_evidence', 'needs_clarification', 'rejected'),
          'projection_review_decision')
    if review['decision'] != 'reviewed_for_scope':
        return _stop(review['decision'], 'projection_review_' + review['decision'], **common)
    mapping['projectionReviewRef'] = _ref(review)
    map_versions, source_versions = _history(previous, mapping, package)
    # 最终读回：学习认可、K2 和 prepare 分别有自己的失效原因。
    state, code = _recognition(brief, recognition, request['intent'], recognition_root)
    if state: return _stop(state, code)
    final = verify_knowledge(context, prepared, wiki_root=wiki_root, source_root=source_root)
    if final['knowledgeState'] != 'reviewed_for_scope': return _stop('stale', 'knowledge_changed')
    _, reread, deps = _prepare(projection_root, prepare_path)
    if digest(reread.manifest) != digest(package.manifest) or deps != dependencies:
        return _stop('stale', 'projection_changed')
    result = dict(result='ready_for_review', projectionState='reviewed_for_scope', findings=[],
        artifactRefs=[mapping['prepareRef']], nextAction='inspect_actual_release_or_candidate',
        mapping=mapping, **common, previewOnly=True, formalWriteAuthorized=False,
        coursePublishAuthorized=False, assurance='operator_supplied_no_host_authentication', modelCalls=0)
    result.update(mapVersions=map_versions, sourceVersions=source_versions)
    result['projectionDigest'] = digest(result)
    _bounded(result, 'projection_output_limit', 1536 * 1024)
    return result


def check_release_request_binding(projection, actual_intent, actual_manifest_digest):
    """仅检查实际请求与已审导出绑定，不代替网络操作、I4 或发布授权。"""
    _need(type(projection) is dict and 'projectionDigest' in projection, 'projection_result_shape')
    _need(projection['projectionDigest'] == digest({k: v for k, v in projection.items()
        if k != 'projectionDigest'}), 'projection_result_digest')
    _need(projection['projectionState'] == 'reviewed_for_scope', 'projection_not_reviewed')
    matched = (actual_intent == projection['mapping']['intent'] and actual_manifest_digest ==
               projection['mapping']['prepareRef']['normalizedManifestDigest'])
    return {'result': 'ready_for_review' if matched else 'stale', 'bindingMatched': matched,
            'actualCourseI4StillRequired': True, 'coursePublishAuthorized': False,
            'limitation': '仅比较所提供请求值；调用者须从真实I3请求/回执取得值，不能当宿主证明。'}
