"""K1：有界本地读取、关联候选、背景观察及学习约定草案。零模型、零写入。"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import time

from ..contracts import bytes_digest, canonical_json, digest, validate_path
from ..isolation.gateway import _check_chain

KINDS = frozenset({'sources', 'concepts', 'entities', 'synthesis'})
SOURCE_FIELDS = {'sourceId', 'sourceVersionId', 'path', 'sha256', 'complete', 'mediaType'}
LIMITS = {'maxSources': 3, 'maxPages': 5, 'maxEntries': 10000,
          'maxFileBytes': 1024 * 1024, 'maxTotalBytes': 4 * 1024 * 1024, 'maxSeconds': 10}
HASH = re.compile(r'^[0-9a-f]{64}$')
MAX_CONTEXT_BYTES = 1536 * 1024


class PreparationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _need(condition, code):
    if not condition:
        raise PreparationError(code)


def _text(value, code, limit=4000):
    _need(type(value) is str and bool(value.strip()) and len(value) <= limit
          and not any(ord(c) < 32 and c not in '\n\t' for c in value), code)
    return value


def _fields(value, fields, code):
    _need(type(value) is dict and set(value) == set(fields), code)


def _strings(value, code, *, empty=True, maximum=32):
    _need(type(value) is list and len(value) <= maximum and (empty or bool(value)), code)
    for item in value:
        _text(item, code)
    _need(len(set(value)) == len(value), code)


def _sealed(body):
    value = dict(body, contextDigest=digest(body))
    _need(len(canonical_json(value)) <= MAX_CONTEXT_BYTES, 'context_output_limit')
    return value


def _unseal(context):
    _need(type(context) is dict and 'contextDigest' in context, 'context_shape')
    body = {k: v for k, v in context.items() if k != 'contextDigest'}
    _need(digest(body) == context['contextDigest'], 'context_digest')
    _need(body.get('schema') == 'knowledge-context/1', 'context_schema')
    _fields(body, {'schema', 'learnerId', 'observedAt', 'result', 'findings', 'artifactRefs',
        'nextAction', 'queryTerms', 'sources', 'index', 'documents', 'observations',
        'learningEvidence', 'coverage', 'assurance', 'sourceVersions'}, 'context_fields')
    _need(len(canonical_json(context)) <= MAX_CONTEXT_BYTES, 'context_size')
    _text(body['learnerId'], 'learner_id', 180)
    _need(type(body['index']) is dict and body['index'].get('locator') == 'wiki/index.md',
          'index_scope')
    _need(type(body['coverage']) is dict, 'coverage_shape')
    limits = _limits(body['coverage']['limits'])
    _need(type(body['sources']) is list and 1 <= len(body['sources']) <= limits['maxSources'],
          'context_sources')
    _need(type(body['documents']) is list and len(body['documents']) <= limits['maxPages'],
          'context_documents')
    for row in [*body['sources'], body['index'], *body['documents']]:
        _need(type(row) is dict and type(row.get('text')) is str
              and type(row.get('bytes')) is int and row['bytes'] >= 0, 'context_row_shape')
        validate_path(row['locator'])
        data = row['text'].encode('utf-8')
        _need(bytes_digest(data) == row['byteDigest'] and len(data) == row['bytes'],
              'context_text_binding')
    for row in body['sources']:
        _need(Path(row['locator']).suffix.lower() in ('.md', '.txt'), 'context_source_type')
        _text(row['sourceId'], 'source_identity', 180)
        _text(row['sourceVersionId'], 'source_identity', 180)
        _need(type(row['complete']) is bool, 'source_completeness')
    history = body['sourceVersions']
    _need(type(history) is list and len(history) <= 256, 'source_history_limit')
    known = {}
    for row in history:
        _fields(row, {'sourceId', 'sourceVersionId', 'byteDigest'}, 'history_fields')
        for key in ('sourceId', 'sourceVersionId'):
            _text(row[key], 'source_identity', 180)
        key = (row['sourceId'], row['sourceVersionId'])
        _need(key not in known and type(row['byteDigest']) is str
              and HASH.fullmatch(row['byteDigest']), 'history_identity')
        known[key] = row['byteDigest']
    _need(all(known.get((row['sourceId'], row['sourceVersionId'])) == row['byteDigest']
              for row in body['sources']), 'context_source_history')
    _need(body['result'] == ('needs_evidence' if any(not r['complete'] for r in body['sources'])
                            else 'ready_for_review'), 'context_result')
    for row in body['documents']:
        parts = row['locator'].split('/')
        _need(len(parts) >= 3 and parts[0] == 'wiki' and parts[1] in KINDS
              and row['locator'].endswith('.md') and not any(p.startswith('.') for p in parts),
              'context_document_scope')
    _need(body['learningEvidence'] == {'status': 'not_read', 'refs': []},
          'learning_record_adapter_not_available')
    expected = [_background(body['learnerId'], body['observedAt'], row)
                for row in body['documents']]
    if not expected:
        expected = [_unknown_background(body['learnerId'], body['observedAt'], body['queryTerms'])]
    _need(body['observations'] == expected, 'background_provenance')
    return body


def _background(learner, now, document):
    locator = document['locator']
    return {'observationId': 'background-' + digest(
        [learner, locator, document['byteDigest']])[:20], 'subject': learner,
        'topic': Path(locator).stem, 'basisType': 'material_available',
        'evidenceRefs': [{'id': locator, 'version': document['byteDigest'],
                          'digest': document['byteDigest']}],
        'observedAt': now, 'applicableVersion': 'unknown',
        'planningUse': 'connect_background',
        'limitation': '仅有本次实际读取的资料；未证明用户读过、理解或独立掌握。'}


def _unknown_background(learner, now, terms):
    return {'observationId': 'background-unknown', 'subject': learner,
        'topic': '、'.join(terms), 'basisType': 'unknown', 'evidenceRefs': [],
        'observedAt': now, 'applicableVersion': 'unknown', 'planningUse': 'clarify',
        'limitation': '有限元数据检索未选到相关页，不证明库中没有或用户不会。'}


def _root(value):
    path = Path(os.path.abspath(value))
    _check_chain(path)
    _need(path.is_dir(), 'root_not_directory')
    return path


def _path(root, value):
    validate_path(value)
    path = root / value
    _check_chain(path)
    _need(path.resolve().is_relative_to(root.resolve()), 'path_escape')
    return path


class _Reader:
    def __init__(self, limits):
        self.limits = limits
        self.used = 0
        self.deadline = time.monotonic() + limits['maxSeconds']

    def check(self):
        _need(time.monotonic() <= self.deadline, 'time_limit')

    def read(self, root, locator):
        self.check()
        path = _path(root, locator)
        _need(path.is_file(), 'not_regular_file')
        before = path.stat()
        remaining = self.limits['maxTotalBytes'] - self.used
        allowed = min(self.limits['maxFileBytes'], remaining)
        _need(allowed > 0 and before.st_size <= allowed, 'byte_limit')
        with path.open('rb') as stream:
            data = stream.read(allowed + 1)
        self.used += len(data)
        _need(len(data) <= allowed, 'byte_limit')
        _path(root, locator)
        after = path.stat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        _need(signature(before) == signature(after), 'changed_during_read')
        text = data.decode('utf-8')
        _need('\x00' not in text, 'non_text_input')
        self.check()
        return {'locator': locator, 'byteDigest': bytes_digest(data),
                'bytes': len(data), 'text': text}


def _limits(values):
    values = {} if values is None else values
    _need(type(values) is dict and not set(values) - set(LIMITS), 'limits_fields')
    merged = dict(LIMITS, **values)
    for key, maximum in LIMITS.items():
        _need(type(merged[key]) is int and 1 <= merged[key] <= maximum, 'limits_range')
    return merged


def _inventory(root, reader):
    """递归扫描目录元数据，不读页面正文；不跟随链接。"""
    entries, paths = 0, []
    def fail(_):
        raise PreparationError('inventory_unreadable')
    for kind in sorted(KINDS):
        directory = root / 'wiki' / kind
        if not directory.exists():
            continue
        _check_chain(directory)
        for current, dirs, names in os.walk(directory, followlinks=False, onerror=fail):
            reader.check()
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
            for name in sorted([*dirs, *names]):
                entries += 1
                _need(entries <= reader.limits['maxEntries'], 'inventory_limit')
                path = Path(current) / name
                _check_chain(path)
                if not name.startswith('.') and name.endswith('.md') and path.is_file():
                    paths.append(path.relative_to(root).as_posix())
    _need(len({p.casefold() for p in paths}) == len(paths), 'case_alias')
    return sorted(paths)


def _resolve_link(target, paths):
    target = target.split('|', 1)[0].split('#', 1)[0].strip()
    target = target.removeprefix('wiki/').removesuffix('.md')
    exact = 'wiki/' + target + '.md'
    if exact in paths:
        return [exact]
    kind = target.split('/', 1)[0] if '/' in target else None
    if kind and kind not in KINDS:
        return []
    return [p for p in paths if Path(p).stem == target.rsplit('/', 1)[-1]
            and (kind is None or p.split('/')[1] == kind)]


def _select(index, paths, terms, explicit, max_pages, check):
    scores = {p: sum(term.casefold() in Path(p).stem.casefold() for term in terms)
              for p in paths}
    reasons = {p: ['filename'] for p, score in scores.items() if score}
    ambiguities = []
    for line in index.splitlines():
        check()
        if not any(term.casefold() in line.casefold() for term in terms):
            continue
        for target in re.findall(r'\[\[([^\]]+)\]\]', line):
            matches = _resolve_link(target, paths)
            if len(matches) != 1:
                if len(matches) > 1:
                    if len(ambiguities) < 20:
                        ambiguities.append({'target': target[:1000], 'candidates': matches[:20],
                                            'truncated': len(matches) > 20})
                continue
            path = matches[0]
            scores[path] += 2
            reasons.setdefault(path, []).append('index')
    chosen = list(explicit)
    for path in explicit:
        _need(path in paths, 'explicit_page_missing')
        reasons[path] = ['explicit']
    ranked = sorted((p for p in paths if scores[p]), key=lambda p: (-scores[p], p))
    chosen += [p for p in ranked if p not in chosen]
    return chosen[:max_pages], reasons, ambiguities, len(chosen)


def inspect_context(wiki_root, source_root, request, *, previous=None):
    """根目录由调用者显式给出；仅读取指定原件、索引和有界相关页。"""
    _need(type(request) is dict and not set(request) - {
        'schema', 'learnerId', 'queryTerms', 'sources', 'wikiRefs', 'limits'}, 'request_fields')
    _need(request.get('schema') == 'knowledge-context-request/1', 'request_schema')
    learner = _text(request.get('learnerId'), 'learner_id', 180)
    terms = request.get('queryTerms')
    _strings(terms, 'query_terms', empty=False, maximum=12)
    explicit = request.get('wikiRefs', [])
    _strings(explicit, 'wiki_refs', maximum=20)
    limits = _limits(request.get('limits'))
    _need(len(explicit) <= limits['maxPages'], 'explicit_page_limit')
    reader = _Reader(limits)
    wiki_root, source_root = _root(wiki_root), _root(source_root)
    sources = request.get('sources')
    _need(type(sources) is list and 1 <= len(sources) <= limits['maxSources'], 'source_count')
    known = {}
    if previous is not None:
        old = _unseal(previous)
        _need(old['learnerId'] == learner, 'previous_learner_scope')
        known = {(r['sourceId'], r['sourceVersionId']): r['byteDigest']
                 for r in old['sourceVersions']}
    now = datetime.now(timezone.utc).isoformat()
    findings, originals, seen = [], [], set()
    for source in sources:
        _fields(source, SOURCE_FIELDS, 'source_fields')
        for key in ('sourceId', 'sourceVersionId'):
            _text(source[key], 'source_identity', 180)
        key = (source['sourceId'], source['sourceVersionId'])
        _need(source['sourceId'] not in seen, 'duplicate_source_identity')
        seen.add(source['sourceId'])
        _need(type(source['sha256']) is str and HASH.fullmatch(source['sha256']), 'source_hash')
        _need(type(source['complete']) is bool, 'source_completeness')
        _text(source['path'], 'source_path')
        _need(source['mediaType'] in ('text/markdown', 'text/plain') and
              Path(source['path']).suffix.lower() in ('.md', '.txt'), 'source_type')
        actual = reader.read(source_root, source['path'])
        _need(actual['bytes'] > 0, 'empty_source')
        _need(actual['byteDigest'] == source['sha256'], 'source_byte_mismatch')
        _need(key not in known or known[key] == actual['byteDigest'], 'source_version_conflict')
        known[key] = actual['byteDigest']
        _need(len(known) <= 256, 'source_history_limit')
        if not source['complete']:
            findings.append({'code': 'partial_source', 'ref': source['sourceId']})
        originals.append(dict(actual, sourceId=source['sourceId'],
                              sourceVersionId=source['sourceVersionId'],
                              complete=source['complete'], mediaType=source['mediaType']))
    index = reader.read(wiki_root, 'wiki/index.md')
    paths = _inventory(wiki_root, reader)
    chosen, reasons, ambiguous, candidates = _select(index['text'], paths, terms, explicit,
                                                     limits['maxPages'], reader.check)
    documents, observations = [], []
    for locator in chosen:
        document = reader.read(wiki_root, locator)
        title = Path(locator).stem
        matches = _resolve_link(title, paths)
        page_id = '[[' + title + ']]' if len(matches) == 1 else None
        document.update(pageId=page_id, selectionReasons=reasons[locator],
                        proposedRelation=('exact_duplicate' if any(
                            s['byteDigest'] == document['byteDigest'] for s in originals)
                            else 'related'), semanticStatus='unreviewed')
        documents.append(document)
        observations.append(_background(learner, now, document))
    if not documents:
        observations.append(_unknown_background(learner, now, terms))
    if ambiguous:
        findings.append({'code': 'ambiguous_wikilink', 'ref': 'wiki/index.md'})
    context = {'schema': 'knowledge-context/1', 'learnerId': learner, 'observedAt': now,
        'result': 'needs_evidence' if findings and any(f['code'] == 'partial_source'
                     for f in findings) else 'ready_for_review',
        'findings': findings, 'artifactRefs': [], 'nextAction': 'review_context_and_draft_brief',
        'queryTerms': terms, 'sources': originals, 'index': index, 'documents': documents,
        'sourceVersions': [{'sourceId': key[0], 'sourceVersionId': key[1], 'byteDigest': value}
                           for key, value in sorted(known.items())],
        'observations': observations, 'learningEvidence': {'status': 'not_read', 'refs': []},
        'coverage': {'inventoryDigest': digest(paths), 'listedPages': len(paths),
            'candidates': candidates, 'readPages': len(documents),
            'unreadCandidates': max(0, candidates-len(documents)), 'ambiguities': ambiguous,
            'bodySearch': False, 'wholeWikiExhausted': False, 'bytesRead': reader.used,
            'limits': limits}, 'assurance': 'cooperative_read_no_atomic_snapshot'}
    # 返回前重读已用文件；不把一次跨文件读取当原子快照。
    for root, rows in ((source_root, originals), (wiki_root, [index, *documents])):
        for row in rows:
            _need(reader.read(root, row['locator'])['byteDigest'] == row['byteDigest'],
                  'dependency_changed_during_inspection')
    _need(_inventory(wiki_root, reader) == paths, 'inventory_changed_during_inspection')
    context['coverage']['bytesRead'] = reader.used
    return _sealed(context)


def verify_context(context, wiki_root, source_root):
    """重验实际已读依赖和目录选择条件，返回定位变化，不自动重建旧观察。"""
    body = _unseal(context)
    reader = _Reader(_limits(body['coverage']['limits']))
    roots = (_root(wiki_root), _root(source_root))
    changes = []
    for root, rows in ((roots[1], body['sources']), (roots[0], [body['index'], *body['documents']])):
        for row in rows:
            try:
                current = reader.read(root, row['locator'])
                if current['byteDigest'] != row['byteDigest']:
                    changes.append({'ref': row['locator'], 'code': 'bytes_changed'})
            except (OSError, ValueError, UnicodeError):
                changes.append({'ref': row['locator'], 'code': 'dependency_unreadable'})
    if digest(_inventory(roots[0], reader)) != body['coverage']['inventoryDigest']:
        changes.append({'ref': 'wiki', 'code': 'selection_inventory_changed'})
    return {'result': 'stale' if changes else 'ready_for_review', 'findings': changes,
            'artifactRefs': [{'contextDigest': context['contextDigest']}],
            'nextAction': 'inspect_again' if changes else 'review_context_and_draft_brief',
            'assurance': 'cooperative_read_no_atomic_snapshot'}


def draft_learning_brief(context, request, *, wiki_root, source_root):
    """将外部准备者提出的目标组织成草案；不推断语义、不记录用户已认可。"""
    body = _unseal(context)
    current = verify_context(context, wiki_root, source_root)
    if current['result'] == 'stale':
        return dict(current, brief=None, briefRef=None, briefState='draft',
                    recognitionRequired=True)
    _need(type(request) is dict and not set(request) - {
        'briefId', 'version', 'goals', 'included', 'excluded', 'pacing',
        'prerequisites', 'userIntent'}, 'brief_request_fields')
    _text(request.get('briefId'), 'brief_id', 180)
    _need(type(request.get('version')) is int and request['version'] > 0, 'brief_version')
    user_intent = _text(request.get('userIntent'), 'user_intent')
    goals = request.get('goals', [])
    _need(type(goals) is list and len(goals) <= 10, 'goals')
    for goal in goals:
        _fields(goal, {'goalId', 'outcome', 'checkMethod'}, 'goal_fields')
        for key in goal:
            _text(goal[key], 'goal_text')
    _need(len({g['goalId'] for g in goals}) == len(goals), 'duplicate_goal')
    included, excluded = request.get('included', []), request.get('excluded', [])
    _strings(included, 'included'); _strings(excluded, 'excluded')
    _need(not set(included) & set(excluded), 'scope_overlap')
    pacing = request.get('pacing', {'sessionMinutes': None, 'totalMinutes': None, 'depth': 'brief'})
    _fields(pacing, {'sessionMinutes', 'totalMinutes', 'depth'}, 'pacing_fields')
    for key in ('sessionMinutes', 'totalMinutes'):
        _need(pacing[key] is None or type(pacing[key]) is int and 0 < pacing[key] <= 10080,
              'pacing_minutes')
    _need(pacing['depth'] in ('brief', 'standard', 'deep'), 'pacing_depth')
    if pacing['sessionMinutes'] is not None and pacing['totalMinutes'] is not None:
        _need(pacing['sessionMinutes'] <= pacing['totalMinutes'], 'pacing_order')
    prerequisites = request.get('prerequisites', [])
    _need(type(prerequisites) is list and len(prerequisites) <= 20, 'prerequisites')
    for pre in prerequisites:
        _fields(pre, {'topic', 'observationRef', 'handling'}, 'prerequisite_fields')
        _text(pre['topic'], 'prerequisite_topic')
        # 本阶段只有资料观察，不能据此签发“已知可用”的掌握结论。
        _need(pre['handling'] in ('计划补讲', '待澄清') and pre['observationRef'] is None,
              'prerequisite_evidence_not_available')
    missing = []
    if not goals: missing.append('学习后希望完成什么？')
    if not included: missing.append('本轮重点范围是什么？')
    if None in (pacing['sessionMinutes'], pacing['totalMinutes']):
        missing.append('本轮时间安排或可采用的时间默认值是什么？')
    if any(p['handling'] == '待澄清' for p in prerequisites):
        missing.append('关键前置知识是否需要补讲？')
    brief = None
    if goals and included:
        brief = {'schema': 'learning-brief/1', 'briefId': request['briefId'],
            'version': request['version'], 'learnerId': body['learnerId'], 'goals': goals,
            'backgroundRefs': [{'id': o['observationId'], 'digest': digest(o)}
                               for o in body['observations']],
            'prerequisites': prerequisites, 'included': included, 'excluded': excluded,
            'pacing': pacing}
    return copy.deepcopy({'result': 'needs_clarification' if missing else 'ready_for_review',
        'findings': [{'code': 'clarification_required', 'question': q} for q in missing],
        'artifactRefs': [{'contextDigest': context['contextDigest']}],
        'nextAction': 'clarify_learning_direction' if missing else 'review_draft_with_user_intent',
        'brief': brief, 'briefRef': None if brief is None else {
            'briefId': brief['briefId'], 'version': brief['version'], 'digest': digest(brief)},
        'userIntent': user_intent, 'intentAssurance': 'operator_supplied',
        'briefState': 'draft', 'recognitionRequired': True,
        'sourceReadiness': body['result'],
        'learningEvidenceStatus': body['learningEvidence']['status']})
