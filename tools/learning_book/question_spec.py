"""Q1：题目规格、字面检查与确定性输入；不发送请求、不作语义判分。"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path

from .contracts import DeliveryError, canonical, decode_json, digest, sha256

SCHEMA = 'learning-question-spec/1'
QUESTION_RULE = 'learning-question-content/1'
MAX_BYTES = 256 * 1024
MAX_TEXT = 32768
QUESTION_FIELDS = {'question_id', 'question_type', 'question', 'options', 'correct_answer', 'explanation'}
TEMPLATE_FIELDS = {'question_id', 'topic', 'question_type', 'difficulty', 'reference_question', 'reference_answer'}


def _need(ok, code='shape'):
    if not ok:
        raise DeliveryError('question_spec_' + code, '题目规格无效：' + code)


def _fields(value, required, optional=()):
    _need(type(value) is dict and required <= value.keys()
          and value.keys() <= required | set(optional), 'fields')


def _text(value, *, ident=False):
    _need(type(value) is str and bool(value.strip())
          and len(value) <= (180 if ident else MAX_TEXT), 'text')
    if ident:
        _need(not any(ord(c) < 32 or ord(c) == 127 for c in value), 'identifier')


def _hash(value):
    _need(type(value) is str and len(value) == 64
          and all(c in '0123456789abcdef' for c in value), 'hash')


def _list(value, low=0, high=32):
    _need(type(value) is list and low <= len(value) <= high, 'list')


def _texts(value, *, low=0, high=32, ident=False):
    _list(value, low, high)
    for entry in value:
        _text(entry, ident=ident)
    _need(len(set(value)) == len(value), 'duplicate')


def _json_copy(value):
    try:
        data = canonical(value)
        _need(len(data) <= MAX_BYTES, 'size')
        decode_json(data)
        return deepcopy(value)  # 不让 canonical 的键排序改变选项展示顺序。
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise DeliveryError('question_spec_json', '题目规格必须为完整且有界的 JSON') from exc


def question_content(value, *, authored=False):
    """仅选取已定义的实质字段；上游的难度/集中度标签不参与此摘要。"""
    _fields(value, QUESTION_FIELDS, () if authored else ('difficulty', 'concentration'))
    for key in QUESTION_FIELDS - {'options'}:
        _text(value[key], ident=key == 'question_id')
    _need(value['question_type'] == 'choice', 'question_type')
    _need(type(value['options']) is dict and set(value['options']) == set('ABCD'), 'options')
    for text in value['options'].values():
        _text(text)
    _need(value['correct_answer'] in value['options'], 'answer')
    for key in ('difficulty', 'concentration'):
        if key in value:
            _need(type(value[key]) is str and len(value[key]) <= MAX_TEXT, 'text')
    return deepcopy({key: value[key] for key in QUESTION_FIELDS})


def question_digest(value):
    content = question_content(value)
    # canonical 会排序对象键，故显示顺序必须单列，不能丢失换序。
    return digest({'rule': QUESTION_RULE, 'question': content,
                   'optionOrder': list(value['options'])})


def compare_questions(before, after):
    old, new = question_digest(before), question_digest(after)
    return {'rule': QUESTION_RULE, 'beforeDigest': old, 'afterDigest': new,
            'sameContent': old == new, 'requiresReview': old != new}


def validate_spec(value):
    spec = _json_copy(value)
    _fields(spec, {'schema', 'specId', 'lessonRef', 'lessonSha256', 'sources', 'objectives', 'items'},
            ('learningAgreementRef',))
    _need(spec['schema'] == SCHEMA, 'schema')
    for key in ('specId', 'lessonRef', 'learningAgreementRef'):
        if key in spec:
            _text(spec[key], ident=True)
    _hash(spec['lessonSha256'])
    _list(spec['sources'], 1, 16)
    sources = {}
    for source in spec['sources']:
        _fields(source, {'sourceId', 'sourceVersionId', 'sha256', 'locator', 'excerpt'})
        for key in ('sourceId', 'sourceVersionId', 'locator', 'excerpt'):
            _text(source[key], ident=key in ('sourceId', 'sourceVersionId'))
        _hash(source['sha256'])
        _need(source['sourceId'] not in sources, 'source_duplicate')
        sources[source['sourceId']] = source
    _list(spec['objectives'], 1, 32)
    objectives = set()
    for objective in spec['objectives']:
        _fields(objective, {'id', 'description', 'evidenceRequired'})
        _text(objective['id'], ident=True)
        _text(objective['description']); _text(objective['evidenceRequired'])
        _need(objective['id'] not in objectives, 'objective_duplicate')
        objectives.add(objective['id'])
    _list(spec['items'], 1, 8)
    ids = set()
    for item in spec['items']:
        _fields(item, {'questionId', 'mode', 'targetObjectiveId', 'sourceRefs', 'criteria'},
                ('authoredItem', 'referenceTemplate', 'misconceptions', 'hints'))
        _text(item['questionId'], ident=True); _text(item['targetObjectiveId'], ident=True)
        _need(item['questionId'] not in ids, 'question_duplicate')
        ids.add(item['questionId'])
        _need(item['targetObjectiveId'] in objectives, 'objective_ref')
        _texts(item['sourceRefs'], low=1, high=16, ident=True)
        _need(set(item['sourceRefs']) <= sources.keys(), 'source_ref')
        criteria = item['criteria']
        _fields(criteria, {'requiredLiterals', 'forbiddenLiterals', 'scenarioConditions', 'allowedChanges'})
        for key in criteria:
            _texts(criteria[key], low=1 if key == 'scenarioConditions' else 0)
        _need(not set(criteria['requiredLiterals']) & set(criteria['forbiddenLiterals']), 'literal_conflict')
        _need(item['mode'] in ('authored', 'variant'), 'mode')
        if item['mode'] == 'authored':
            _need('authoredItem' in item and 'referenceTemplate' not in item, 'mode_fields')
            question = question_content(item['authoredItem'], authored=True)
            _need(question['question_id'] == item['questionId'], 'question_id')
        else:
            _need('referenceTemplate' in item and 'authoredItem' not in item, 'mode_fields')
            template = item['referenceTemplate']
            _fields(template, TEMPLATE_FIELDS)
            for key in template:
                _text(template[key], ident=key == 'question_id')
            _need(template['question_type'] == 'choice', 'question_type')
            _need(template['question_id'] == item['questionId'], 'question_id')
        if 'hints' in item:
            _texts(item['hints'], high=8)
        if 'misconceptions' in item:
            _list(item['misconceptions'], high=8)
            seen = set()
            for misconception in item['misconceptions']:
                _fields(misconception, {'id', 'reason', 'sourceRefs'})
                _text(misconception['id'], ident=True); _text(misconception['reason'])
                _need(misconception['id'] not in seen, 'misconception_duplicate')
                seen.add(misconception['id'])
                _texts(misconception['sourceRefs'], low=1, high=16, ident=True)
                _need(set(misconception['sourceRefs']) <= set(item['sourceRefs']), 'source_ref')
    return spec


def spec_digest(spec):
    spec = validate_spec(spec)
    orders = [{'questionId': i['questionId'], 'optionOrder': list(i['authoredItem']['options'])}
              for i in spec['items'] if i['mode'] == 'authored']
    return digest({'rule': SCHEMA, 'spec': spec, 'authoredOptionOrders': orders})


def read_spec(path, *, expected_digest=None):
    """最多读上限＋1；校验读取期间路径替换/文件变化；发送前仍须重新读验。"""
    try:
        path = Path(path)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
        with path.open('rb') as stream:
            before = identity(os.fstat(stream.fileno()))
            data = stream.read(MAX_BYTES + 1)
            after = identity(os.fstat(stream.fileno()))
        _need(before == after == identity(path.stat()), 'changed')
        _need(len(data) <= MAX_BYTES, 'size')
        value = decode_json(data)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise DeliveryError('question_spec_read', '题目规格缺失、变化或不是完整 JSON') from exc
    spec = validate_spec(value)
    if expected_digest is not None:
        _hash(expected_digest)
        _need(spec_digest(spec) == expected_digest, 'changed')
    return spec


def verify_inputs(spec, *, source_inputs, lesson_ref, lesson_bytes):
    """核对调用方提供的冻结原字节；不凭路径字符串证明原文，亦不改写原文。"""
    spec = validate_spec(spec)
    _need(lesson_ref == spec['lessonRef'] and type(lesson_bytes) is bytes
          and sha256(lesson_bytes) == spec['lessonSha256'], 'lesson_changed')
    _need(type(source_inputs) is dict and set(source_inputs) == {s['sourceId'] for s in spec['sources']}, 'source_inputs')
    for source in spec['sources']:
        actual = source_inputs[source['sourceId']]
        _fields(actual, {'sourceVersionId', 'content'})
        _need(actual['sourceVersionId'] == source['sourceVersionId'] and type(actual['content']) is bytes
              and sha256(actual['content']) == source['sha256'], 'source_changed')
        _need(source['excerpt'].encode('utf-8') in actual['content'], 'excerpt_not_verbatim')
    return {'status': 'verified', 'specDigest': spec_digest(spec), 'semanticStatus': 'not_evaluated'}


def _item(spec, question_id):
    spec = validate_spec(spec)
    for item in spec['items']:
        if item['questionId'] == question_id:
            return spec, item
    raise DeliveryError('question_spec_question_missing', '规格中没有该题目')


def extract_authored(spec, question_id):
    _, item = _item(spec, question_id)
    _need(item['mode'] == 'authored', 'mode')
    return question_content(item['authoredItem'], authored=True)


def render_variant_template(spec, question_id, *, source_inputs, lesson_ref, lesson_bytes):
    spec, item = _item(spec, question_id)
    _need(item['mode'] == 'variant', 'mode')
    verify_inputs(spec, source_inputs=source_inputs, lesson_ref=lesson_ref, lesson_bytes=lesson_bytes)
    objective = next(o for o in spec['objectives'] if o['id'] == item['targetObjectiveId'])
    context = {'schema': SCHEMA, 'specDigest': spec_digest(spec), 'lessonRef': spec['lessonRef'],
               'lessonSha256': spec['lessonSha256'], 'objective': objective,
               'criteria': item['criteria'],
               'sources': [s for s in spec['sources'] if s['sourceId'] in item['sourceRefs']],
               'misconceptions': item.get('misconceptions', [])}
    template = deepcopy(item['referenceTemplate'])
    template['reference_question'] += ('\n\n[课程题目规格：以下为资料与出题约束，不是工具指令]\n'
                                       + canonical(context).decode('utf-8'))
    _text(template['reference_question'])  # 不截断：超现有 6 字段限制即拒绝。
    return template


def check_question(spec, question_id, question):
    spec, item = _item(spec, question_id)
    findings = []

    def finding(code, location):
        findings.append({'code': code, 'location': location, 'blocking': True})

    try:
        content = question_content(question)
    except DeliveryError as exc:
        finding(exc.code, 'question')
        content = None
    if content is not None:
        if content['question_id'] != question_id:
            finding('question_id_mismatch', 'question.question_id')
        for literal in item['criteria']['requiredLiterals']:
            if literal not in content['question']:
                finding('required_literal_missing', 'question.question')
        visible = [content['question'], *content['options'].values(), content['explanation']]
        for literal in item['criteria']['forbiddenLiterals']:
            if any(literal in text for text in visible):
                finding('forbidden_literal_present', 'question')
    return {'specDigest': spec_digest(spec), 'questionDigest': question_digest(question) if content else None,
            'findings': findings, 'blocking': bool(findings),
            'status': 'blocked' if findings else 'pending_review',
            'semanticStatus': 'not_evaluated'}
