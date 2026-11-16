"""只读知识准备：旧包组装、原文定位、范围审校观察。无模型或正式写入。"""
from __future__ import annotations

import copy

from ..contracts import ContractError, canonical_json, digest
from .package_protocol import build_package, evidence_claim_relation_digest, package_ref
from .preparation import PreparationError, _fields, _need, _strings, _text, _unseal, verify_context

MAX_REQUEST_BYTES = 1024 * 1024
COUNTS = {'evidence': 40, 'claims': 10, 'relations': 80, 'conflicts': 10,
          'existingKnowledge': 30, 'sourceObservations': 3}


def text_lines(text):
    """1 起算；仅 CRLF→LF，保留裸 CR、BOM、Unicode 与空白；末尾换行不另算空行。"""
    rows = text.replace('\r\n', '\n').split('\n')
    if rows[-1] == '' and len(rows) > 1:
        rows.pop()
    return rows


def _excerpt(text, locator, excerpt):
    _fields(locator, {'start_line', 'end_line'}, 'line_fields')
    start, end = locator['start_line'], locator['end_line']
    rows = text_lines(text)
    _need(type(start) is int and type(end) is int and 1 <= start <= end <= len(rows),
          'line_range')
    _need(type(excerpt) is str and '\r\n' not in excerpt
          and excerpt == '\n'.join(rows[start-1:end]), 'excerpt_mismatch')


def _bounded(value, code, maximum=MAX_REQUEST_BYTES):
    _need(len(canonical_json(value)) <= maximum, code)


def _rows(value, maximum, code):
    _need(type(value) is list and len(value) <= maximum, code)
    _need(all(type(row) is dict for row in value), code)
    return value


def _observations(rows, sources, evidence):
    _need(len(rows) == len(sources), 'source_observation_coverage')
    by_id = {}
    for row in rows:
        _fields(row, {'sourceId', 'canonicalLocator', 'sourceType', 'topics', 'publishedAt',
            'acquiredBy', 'originId', 'upstreamSourceIds', 'basisEvidenceIds', 'reason'},
            'source_observation_fields')
        sid = row['sourceId']
        _text(sid, 'observation_source', 180)
        _need(sid in sources and sid not in by_id, 'source_observation_identity')
        for field in ('canonicalLocator', 'acquiredBy', 'reason'):
            _text(row[field], 'source_observation_text')
        _need(row['sourceType'] in ('first_party', 'report', 'repost', 'unknown'),
              'source_observation_type')
        for field in ('topics', 'upstreamSourceIds', 'basisEvidenceIds'):
            _strings(row[field], 'source_observation_list')
        _need(set(row['upstreamSourceIds']) <= set(sources)
              and sid not in row['upstreamSourceIds'], 'source_upstream_reference')
        _need(set(row['basisEvidenceIds']) <= set(evidence), 'source_basis_reference')
        for field in ('originId', 'publishedAt'):
            if row[field] is not None:
                _text(row[field], 'source_optional_text')
        _need(row['originId'] is None or bool(row['basisEvidenceIds']), 'origin_without_basis')
        by_id[sid] = row
    def visit(sid, stack):
        _need(sid not in stack, 'source_lineage_cycle')
        for parent in by_id[sid]['upstreamSourceIds']:
            visit(parent, stack | {sid})
    for sid in by_id:
        visit(sid, set())
    # 共同上游、相同声明上游、相同字节均合并；未知身份不默认为独立。
    groups = [{sid} for sid in sources]
    for a in sources:
        for b in sources:
            same = (sources[a]['content_digest'] == sources[b]['content_digest']
                    or b in by_id[a]['upstreamSourceIds']
                    or by_id[a]['originId'] is not None
                    and by_id[a]['originId'] == by_id[b]['originId'])
            if same:
                ga = next(g for g in groups if a in g)
                gb = next(g for g in groups if b in g)
                if ga is not gb:
                    ga.update(gb); groups.remove(gb)
    return {'declaredGroups': [sorted(g) for g in groups],
        'unknownSourceIds': [sid for sid, row in by_id.items() if row['originId'] is None],
        'independentCorroborationCount': None, 'assurance': 'operator_supplied',
        'limitation': '分组仅约束来源依赖声明，不认证上游或独立性，不以篇数裁决真伪。'}


def _comparison(context, package):
    docs = {d['locator']: d for d in context['documents']}
    targets = {}
    for row in package['existing_knowledge']:
        # 不猜同名页面：使用本次实际已读 locator 或唯一 pageId。
        matches = [d for d in docs.values()
                   if row['target'] == d['locator'] or d['pageId'] is not None
                   and row['target'] == d['pageId']]
        _need(len(matches) == 1, 'existing_target_not_read_or_ambiguous')
        targets[row['target']] = matches[0]['locator']
    body = {'schema': 'knowledge-comparison/1', 'queryTerms': context['queryTerms'],
        'coverage': context['coverage'], 'observedAt': context['observedAt'],
        'documents': [{k: d[k] for k in ('pageId', 'locator', 'byteDigest')}
                      for d in docs.values()], 'targets': targets,
        'limitation': '只比较实际已读页；旧页自身不是其原始来源的认证。'}
    return dict(body, comparisonDigest=digest(body))


def _review(review, request, package, context, comparison):
    """输入是操作者提供的观察，不签发认证；缺项保持待审。"""
    maps = {key: {} for key in ('claims', 'relations', 'conflicts', 'comparisons', 'sources', 'documents')}
    if review is None:
        return maps
    _bounded(review, 'review_size')
    _fields(review, {'schema', 'id', 'requestDigest', 'reviewer', 'recordedAt', 'assurance',
                     'basisEvidenceIds', *maps}, 'review_fields')
    _need(review['schema'] == 'knowledge-review-observation/1', 'review_schema')
    _need(review['assurance'] == 'operator_supplied', 'review_assurance')
    for key in ('id', 'reviewer', 'recordedAt'):
        _text(review[key], 'review_attribution')
    _need(review['requestDigest'] == request['requestDigest'], 'review_binding_stale')
    evid = {e['evidence_id']: e for e in package['evidence']}
    _strings(review['basisEvidenceIds'], 'review_basis', empty=False, maximum=40)
    _need(set(review['basisEvidenceIds']) <= set(evid), 'review_basis_reference')
    candidates = {
        'claims': {c['claim_id']: c for c in package['claims']},
        'relations': {evidence_claim_relation_digest(r): r for r in package['relations']},
        'conflicts': {c['conflict_id']: c for c in package['conflicts']},
        'comparisons': {digest(c): c for c in package['existing_knowledge']},
        'sources': {s['source_id']: s for s in package['sources']},
        'documents': {d['locator']: d for d in context['documents']}}
    decisions = {
        'claims': {'reviewed_for_scope', 'needs_evidence', 'rejected'},
        'relations': {'accepted', 'out_of_scope', 'needs_evidence', 'rejected'},
        'conflicts': {'resolved_for_scope', 'unresolved', 'needs_evidence'},
        'comparisons': {'exact_duplicate', 'related', 'new', 'condition_difference',
                        'version_change', 'corrects_old', 'unresolved', 'insufficient'},
        'sources': {'reviewed_for_scope', 'unknown'},
        'documents': {'relations_complete', 'irrelevant', 'needs_evidence'}}
    for kind in maps:
        for row in _rows(review[kind], 80, 'review_rows'):
            fields = {'ref', 'decision', 'reason'}
            if kind == 'claims': fields.add('conditions')
            if kind == 'conflicts': fields |= {'safeClaimIds', 'basisEvidenceIds'}
            if kind == 'comparisons': fields |= {'oldEvidence', 'basisEvidenceIds'}
            _fields(row, fields, 'review_row_fields')
            _text(row['ref'], 'review_reference')
            _need(row['ref'] in candidates[kind] and row['ref'] not in maps[kind],
                  'review_reference')
            _need(row['decision'] in decisions[kind], 'review_decision')
            _text(row['reason'], 'review_reason')
            original = candidates[kind][row['ref']]
            if kind == 'claims':
                _strings(row['conditions'], 'review_conditions')
                _need(row['conditions'] == original['conditions'], 'review_claim_scope')
            if kind in ('conflicts', 'comparisons'):
                _strings(row['basisEvidenceIds'], 'review_local_basis', empty=False, maximum=40)
                _need(set(row['basisEvidenceIds']) <= set(review['basisEvidenceIds']),
                      'review_local_basis_reference')
            if kind == 'conflicts':
                _strings(row['safeClaimIds'], 'conflict_safe_claims', maximum=10)
                _need(set(row['safeClaimIds']) <= set(original['claim_ids'])
                      and set(row['basisEvidenceIds']) <= set(original['evidence_ids']),
                      'conflict_review_scope')
                _need(row['decision'] == 'resolved_for_scope' or not row['safeClaimIds'],
                      'unresolved_safe_claims')
                _need(row['decision'] != 'resolved_for_scope' or original['status'] == 'resolved',
                      'unresolved_package_conflict')
            if kind == 'comparisons':
                old = row['oldEvidence']
                _fields(old, {'locator', 'start_line', 'end_line', 'excerpt'}, 'old_evidence_fields')
                _need(old['locator'] == comparison['targets'][original['target']],
                      'comparison_target_binding')
                document = next(d for d in context['documents'] if d['locator'] == old['locator'])
                _excerpt(document['text'], {k: old[k] for k in ('start_line', 'end_line')}, old['excerpt'])
            if kind == 'documents':
                linked = row['ref'] in comparison['targets'].values()
                _need(row['decision'] != 'relations_complete' or linked, 'document_relation_coverage')
                _need(row['decision'] != 'irrelevant' or not linked, 'document_exclusion_conflict')
            maps[kind][row['ref']] = row
    return maps


def _history(previous):
    if previous is None:
        return []
    _unpack(previous)
    history = previous['packageVersions']
    _need(type(history) is list and len(history) <= 256, 'package_history_limit')
    identities = set()
    from .package_protocol import parse_package_ref
    for row in history:
        parse_package_ref(row)
        key = (row['package_id'], row['version'])
        _need(key not in identities, 'package_history_duplicate')
        identities.add(key)
    _need(package_ref(previous['package']) in history, 'package_history_binding')
    return copy.deepcopy(history)


def _unpack(prepared):
    _need(type(prepared) is dict and prepared.get('schema') == 'knowledge-preparation/1',
          'prepared_shape')
    _bounded(prepared, 'prepared_size', 2 * 1024 * 1024)
    _need('reportDigest' in prepared and digest({k: v for k, v in prepared.items()
        if k != 'reportDigest'}) == prepared['reportDigest'], 'prepared_digest')


def prepare_knowledge(context, request, *, wiki_root, source_root, review=None, previous=None):
    """外部 Agent 提出语义内容；程序只验证字节／引用并记录范围判断。"""
    _bounded(request, 'request_size')
    _fields(request, {'schema', 'packageId', 'version', 'intent', *COUNTS}, 'knowledge_request_fields')
    _need(request['schema'] == 'knowledge-preparation-request/1', 'knowledge_request_schema')
    _text(request['intent'], 'knowledge_intent')
    for key, maximum in COUNTS.items():
        _rows(request[key], maximum, 'knowledge_count')
    _need(bool(request['claims']), 'empty_claim_scope')
    body = _unseal(context)
    current = verify_context(context, wiki_root, source_root)
    if current['result'] == 'stale':
        return dict(current, package=None, knowledgeState='stale', formalWriteAuthorized=False)
    actual = {s['sourceId']: s for s in body['sources']}
    _need(len(actual) == len(body['sources']), 'duplicate_source_identity')
    sources = [{'source_id': sid, 'locator': 'source:' + sid, 'version': s['sourceVersionId'],
        'content_digest': s['byteDigest'], 'readable_range': {'start_line': 1,
        'end_line': len(text_lines(s['text'])), 'complete': s['complete']}}
        for sid, s in actual.items()]
    try:
        package = build_package({'package_id': request['packageId'], 'version': request['version'],
            'sources': sources, 'evidence': request['evidence'], 'relations': request['relations'],
            'existing_knowledge': request['existingKnowledge']}, request['claims'], request['conflicts'])
    except ContractError as exc:
        raise PreparationError('invalid_knowledge_package') from exc
    history = _history(previous)
    ref = package_ref(package)
    same = [r for r in history if (r['package_id'], r['version']) == (ref['package_id'], ref['version'])]
    _need(not same or same[0] == ref, 'package_version_conflict')
    if not same: history.append(ref)
    _need(len(history) <= 256, 'package_history_limit')
    evidence = {e['evidence_id']: e for e in package['evidence']}
    for e in evidence.values():
        _excerpt(actual[e['source_id']]['text'], e['locator'], e['excerpt'])
    for conflict in package['conflicts']:
        _need(bool(conflict['claim_ids']) and bool(conflict['evidence_ids']), 'empty_conflict_scope')
        pairs = {(r['claim_id'], r['evidence_id']) for r in package['relations']}
        _need(all(any((cid, eid) in pairs for eid in conflict['evidence_ids'])
                  for cid in conflict['claim_ids'])
              and all(any((cid, eid) in pairs for cid in conflict['claim_ids'])
                      for eid in conflict['evidence_ids']), 'unrelated_conflict_scope')
    by_source = {s['source_id']: s for s in sources}
    independence = _observations(request['sourceObservations'], by_source, evidence)
    comparison = _comparison(body, package)
    rr = {'schema': 'knowledge-review-request/1', 'packageRef': ref,
        'contextDigest': context['contextDigest'], 'comparisonRef': comparison['comparisonDigest'],
        'sourceObservationsDigest': digest(request['sourceObservations']), 'intent': request['intent'],
        'scope': {'claimIds': [c['claim_id'] for c in package['claims']],
            'evidenceIds': list(evidence),
            'relationDigests': [evidence_claim_relation_digest(r) for r in package['relations']],
            'conflictIds': [c['conflict_id'] for c in package['conflicts']],
            'comparisonDigests': [digest(c) for c in package['existing_knowledge']],
            'sourceIds': list(actual), 'documentLocators': [d['locator'] for d in body['documents']]},
        'assurance': 'review_requested_not_authenticated'}
    rr['requestDigest'] = digest(rr)
    if review is not None:
        _need(type(review) is dict and type(review.get('requestDigest')) is str,
              'review_binding_shape')
    if review is not None and review['requestDigest'] != rr['requestDigest']:
        return {'result': 'stale', 'knowledgeState': 'stale', 'package': package,
            'findings': [{'code': 'review_binding_stale'}], 'artifactRefs': [ref],
            'nextAction': 'review_current_request', 'reviewRequest': rr, 'formalWriteAuthorized': False}
    reviewed = _review(review, rr, package, body, comparison)
    checks = []
    for claim in package['claims']:
        cid = claim['claim_id']
        blockers, pending, accepted_supports = [], [], []
        support_pending = False
        cr = reviewed['claims'].get(cid)
        if cr is None: pending.append('claim_review_missing')
        elif cr['decision'] != 'reviewed_for_scope': blockers.append('claim_' + cr['decision'])
        if claim['evidence_status'] != 'supported': blockers.append('claim_not_supported')
        related = [r for r in package['relations'] if r['claim_id'] == cid]
        complete_supports = [r for r in related if r['relation'] == 'supports'
            and actual[evidence[r['evidence_id']]['source_id']]['complete']
            and evidence[r['evidence_id']]['extraction_state'] == 'complete']
        if not complete_supports:
            blockers.append('no_complete_support')
        elif not any(set(r['conditions']) == set(claim['conditions']) for r in complete_supports):
            blockers.append('no_scope_matched_support')
        covered_conflicts = [c for c in package['conflicts'] if cid in c['claim_ids']]
        safe_conflicts = []
        for conflict in covered_conflicts:
            observed = reviewed['conflicts'].get(conflict['conflict_id'])
            if (conflict['status'] != 'resolved' or not observed
                    or observed['decision'] != 'resolved_for_scope' or cid not in observed['safeClaimIds']):
                blockers.append('unresolved_conflict')
            else: safe_conflicts.append(conflict)
        for relation in related:
            e = evidence[relation['evidence_id']]
            rv = reviewed['relations'].get(evidence_claim_relation_digest(relation))
            if rv is None:
                if relation in complete_supports and set(relation['conditions']) == set(claim['conditions']):
                    support_pending = True
                pending.append('relation_review_missing'); continue
            if rv['decision'] == 'needs_evidence': blockers.append('relation_needs_evidence')
            if rv['decision'] != 'accepted': continue
            if relation['relation'] == 'supports':
                if (not actual[e['source_id']]['complete'] or e['extraction_state'] != 'complete'):
                    blockers.append('partial_support')
                elif set(relation['conditions']) != set(claim['conditions']):
                    blockers.append('support_condition_mismatch')
                elif relation['verification_status'] != 'verified':
                    blockers.append('support_not_verified')
                elif reviewed['sources'].get(e['source_id'], {}).get('decision') != 'reviewed_for_scope':
                    support_pending = True
                    pending.append('source_review_missing')
                else: accepted_supports.append(e['evidence_id'])
            elif relation['relation'] == 'contradicts' and not any(
                    e['evidence_id'] in c['evidence_ids'] for c in safe_conflicts):
                blockers.append('unresolved_counterevidence')
            elif relation['relation'] == 'qualifies' and not set(relation['conditions']) <= set(claim['conditions']):
                blockers.append('unapplied_qualification')
        for old in [r for r in package['existing_knowledge'] if r['claim_id'] == cid]:
            rv = reviewed['comparisons'].get(digest(old))
            if rv is None: pending.append('comparison_review_missing')
            elif rv['decision'] in ('unresolved', 'insufficient'): blockers.append('existing_knowledge_unresolved')
            elif old['relation'] in ('contradicts', 'supersedes') and rv['decision'] not in (
                    'condition_difference', 'version_change', 'corrects_old'):
                blockers.append('existing_conflict_not_addressed')
        if not accepted_supports:
            (pending if support_pending else blockers).append('no_reviewed_complete_support')
        for document in body['documents']:
            dr = reviewed['documents'].get(document['locator'])
            if dr is None: pending.append('document_review_missing')
            elif dr['decision'] == 'needs_evidence': blockers.append('document_comparison_insufficient')
        state = ('rejected' if cr is not None and cr['decision'] == 'rejected'
                 else 'needs_evidence' if blockers else 'needs_review' if pending else 'reviewed_for_scope')
        checks.append({'claimId': cid, 'state': state, 'blockers': sorted(set(blockers)),
                       'pending': sorted(set(pending)), 'supportEvidenceIds': accepted_supports,
                       'answerUse': 'scoped_candidate_only' if state == 'reviewed_for_scope' else 'blocked'})
    state = ('rejected' if any(c['state'] == 'rejected' for c in checks)
             else 'needs_evidence' if any(c['state'] == 'needs_evidence' for c in checks)
             else 'needs_review' if any(c['state'] == 'needs_review' for c in checks)
             else 'reviewed_for_scope')
    # 包外来源／冲突没有删掉；可用片段只是分包建议，不能整包放行。
    result = {'schema': 'knowledge-preparation/1', 'contextDigest': context['contextDigest'],
        'request': copy.deepcopy(request), 'package': package, 'packageVersions': history,
        'comparison': comparison, 'independence': independence, 'reviewRequest': rr,
        'comparisonChecks': [{'locator': d['locator'],
            'decision': reviewed['documents'].get(d['locator'], {}).get('decision', 'needs_review')}
            for d in body['documents']],
        'reviewObservation': copy.deepcopy(review), 'claimChecks': checks, 'knowledgeState': state,
        'result': state if state in ('needs_evidence', 'rejected') else 'ready_for_review',
        'findings': [{'code': c['state'], 'ref': c['claimId']} for c in checks
                     if c['state'] != 'reviewed_for_scope'], 'artifactRefs': [ref],
        'nextAction': 'prepare_scoped_projection_or_candidate' if state == 'reviewed_for_scope'
                      else 'supply_evidence_or_scoped_review',
        'assurance': 'operator_supplied_no_host_authentication',
        'formalWriteAuthorized': False, 'modelCalls': 0}
    # 语义观察输入处理期间也可能修改文件；返回前再次检查协作依赖。
    current = verify_context(context, wiki_root, source_root)
    if current['result'] == 'stale':
        return dict(current, package=None, knowledgeState='stale', formalWriteAuthorized=False)
    result['reportDigest'] = digest(result)
    _bounded(result, 'prepared_size', 2 * 1024 * 1024)
    return result


def verify_knowledge(context, prepared, *, wiki_root, source_root):
    """重算实际依赖和全部确定性结果；报告 hash 本身不是审校认证。"""
    _unpack(prepared)
    _need(prepared['contextDigest'] == context['contextDigest'], 'prepared_context_binding')
    current = prepare_knowledge(context, prepared['request'], wiki_root=wiki_root,
        source_root=source_root, review=prepared['reviewObservation'], previous=prepared)
    if current['result'] != 'stale':
        _need(current == prepared, 'prepared_result_mismatch')
    return current


def partition_knowledge(prepared, claim_ids, *, package_id, version, reason):
    """显式导出未受冲突影响的请求草案；保留原报告引用与排除清单，须另行审校。"""
    _unpack(prepared)
    _strings(claim_ids, 'partition_claim_ids', empty=False, maximum=10)
    _text(reason, 'partition_reason')
    _text(package_id, 'partition_package_id', 180)
    _need(type(version) is int and version > 0, 'partition_version')
    package = prepared['package']
    _need(package_id != package['package_id'], 'partition_new_identity_required')
    wanted = set(claim_ids)
    all_ids = {c['claim_id'] for c in package['claims']}
    _need(wanted < all_ids, 'partition_scope')
    # 不能借分包删去相反证据或冲突另一方。
    _need(not any(wanted & set(c['claim_ids']) for c in package['conflicts']),
          'partition_conflicted_claim')
    request = copy.deepcopy(prepared['request'])
    request.update(packageId=package_id, version=version)
    request['claims'] = [c for c in request['claims'] if c['claim_id'] in wanted]
    request['relations'] = [r for r in request['relations'] if r['claim_id'] in wanted]
    request['conflicts'] = []
    request['existingKnowledge'] = [r for r in request['existingKnowledge'] if r['claim_id'] in wanted]
    # 原件／Evidence／来源观察全部保留，避免去掉上游或反证；仅缩小主张。
    return {'request': request, 'parentReportDigest': prepared['reportDigest'],
            'parentPackageRef': package_ref(package), 'excludedClaimIds': sorted(all_ids - wanted),
            'reason': reason, 'reviewRequired': True, 'formalWriteAuthorized': False}
