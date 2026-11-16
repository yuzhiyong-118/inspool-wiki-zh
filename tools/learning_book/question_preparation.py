"""题目生产附件；冻结来源、规格与人工审查，不推断语义正确性。"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

from .contracts import DeliveryError, canonical, content_hash, decode_json, digest, identifier, sha256
from .evidence_store import atomic
from .question_spec import (MAX_BYTES, check_question, extract_authored, question_content,
                            question_digest, read_spec, render_variant_template, spec_digest,
                            validate_spec, verify_inputs)

BINDING = 'learning-question-binding/1'
PREPARATION = 'learning-question-preparation/1'
EVIDENCE = 'learning-question-evidence/1'
ARCHIVE_LIMIT = 8 * 1024 * 1024


def need(condition, code='question_binding'):
    if not condition:
        raise DeliveryError(code, '题目附件、内容版本或审查不符', 'conflict')


def fields(value, keys, code='question_fields'):
    need(type(value) is dict and set(value) == set(keys), code)


def ordered_bytes(value):
    # JSON 对象的显示顺序是题目内容的一部分；不能使用 canonical 往返归档。
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def read_bounded(path, limit=MAX_BYTES):
    path = Path(path)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        current = path.stat()
    need(len(data) <= limit and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
         (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) ==
         (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns), 'question_input_changed')
    return data


def publication_digest(payload):
    """无自引用的实际请求语义；显式保存选项顺序。"""
    value = deepcopy(payload)
    value.pop('request_digest', None)
    return digest({'rule': 'learning-question-request/1', 'payload': value,
                   'optionOrders': [list(q['options']) for q in value.get('questions', [])]})


def validate_binding(binding, questions=None):
    fields(binding, ('schema', 'specDigest', 'lessonRef', 'lessonSha256', 'sources', 'mode',
                     'questionIds', 'questionDigests', 'preparationDigest', 'reviewDigest'))
    need(binding['schema'] == BINDING and binding['mode'] in ('authored', 'variant'))
    for key in ('specDigest', 'lessonSha256', 'preparationDigest', 'reviewDigest'):
        content_hash(binding[key])
    identifier(binding['lessonRef'], 'lessonRef')
    need(type(binding['sources']) is list and 1 <= len(binding['sources']) <= 16)
    ids = set()
    for source in binding['sources']:
        fields(source, ('sourceId', 'sourceVersionId', 'sha256'))
        identifier(source['sourceId'], 'sourceId'); identifier(source['sourceVersionId'], 'sourceVersionId')
        content_hash(source['sha256'])
        need(source['sourceId'] not in ids); ids.add(source['sourceId'])
    qids = binding['questionIds']
    need(type(qids) is list and 1 <= len(qids) <= 8 and len(set(qids)) == len(qids))
    for key in qids: identifier(key, 'questionId')
    need(type(binding['questionDigests']) is dict and
         set(binding['questionDigests']) == (set(qids) if binding['mode'] == 'authored' else set()))
    for value in binding['questionDigests'].values(): content_hash(value)
    if questions is not None:
        need(type(questions) is list and [q['question_id'] for q in questions] == qids)
        if binding['mode'] == 'authored':
            need({q['question_id']: question_digest(q) for q in questions} == binding['questionDigests'])
    need(len(canonical(binding)) <= MAX_BYTES)
    return deepcopy(binding)


class QuestionPreparation:
    def __init__(self, descriptor):
        self.path = Path(descriptor).absolute()

    def checked(self, mode):
        raw = read_bounded(self.path)
        cfg = decode_json(raw)
        fields(cfg, ('schema', 'root', 'specPath', 'specDigest', 'lessonPath', 'sourceInputs', 'reviewPath'))
        need(cfg['schema'] == PREPARATION and mode in ('authored', 'variant'))
        content_hash(cfg['specDigest'])
        root = Path(cfg['root']).resolve(strict=True)
        need(Path(cfg['root']).is_absolute(), 'question_root')

        def local(name):
            need(type(name) is str and not Path(name).is_absolute())
            lexical = root / name
            result = lexical.resolve(strict=True)
            need(root in result.parents and result == lexical.absolute(), 'question_path')
            return result

        spec = read_spec(local(cfg['specPath']), expected_digest=cfg['specDigest'])
        need(all(item['mode'] == mode for item in spec['items']), 'question_mode')
        lesson = read_bounded(local(cfg['lessonPath']))
        need(type(cfg['sourceInputs']) is list, 'question_sources')
        sources, archived = {}, {}
        for row in cfg['sourceInputs']:
            fields(row, ('sourceId', 'sourceVersionId', 'path'))
            need(row['sourceId'] not in sources)
            data = read_bounded(local(row['path']))
            sources[row['sourceId']] = {'sourceVersionId': row['sourceVersionId'], 'content': data}
            archived[row['sourceId']] = {'sourceVersionId': row['sourceVersionId'], 'content': data.decode('utf-8')}
        verify_inputs(spec, source_inputs=sources, lesson_ref=spec['lessonRef'], lesson_bytes=lesson)
        review = decode_json(read_bounded(local(cfg['reviewPath'])))
        fields(review, ('schema', 'reviewId', 'reviewedBy', 'specDigest', 'mode', 'decision', 'checks', 'assurance'))
        need(review['schema'] == 'learning-question-preparation-review/1' and review['assurance'] == 'operator_supplied'
             and review['specDigest'] == spec_digest(spec) and review['mode'] == mode
             and review['decision'] == 'reviewed_for_production', 'question_review')
        identifier(review['reviewId'], 'reviewId'); identifier(review['reviewedBy'], 'reviewedBy')
        expected = []
        for item in spec['items']:
            qid = item['questionId']
            content = extract_authored(spec, qid) if mode == 'authored' else render_variant_template(
                spec, qid, source_inputs=sources, lesson_ref=spec['lessonRef'], lesson_bytes=lesson)
            expected.append({'questionId': qid, 'contentDigest': question_digest(content) if mode == 'authored'
                             else digest(content), 'reason': None})
        need(type(review['checks']) is list and len(review['checks']) == len(expected), 'question_review_checks')
        for actual, expected_row in zip(review['checks'], expected):
            fields(actual, ('questionId', 'contentDigest', 'reason'))
            need(actual['questionId'] == expected_row['questionId'] and actual['contentDigest'] == expected_row['contentDigest']
                 and type(actual['reason']) is str and bool(actual['reason'].strip()), 'question_review_checks')
        archive = {'schema': EVIDENCE, 'spec': spec, 'lesson': lesson.decode('utf-8'),
                   'sources': archived, 'productionReview': review}
        binding = {'schema': BINDING, 'specDigest': spec_digest(spec), 'lessonRef': spec['lessonRef'],
                   'lessonSha256': spec['lessonSha256'], 'sources': [
                       {k: s[k] for k in ('sourceId', 'sourceVersionId', 'sha256')} for s in spec['sources']],
                   'mode': mode, 'questionIds': [i['questionId'] for i in spec['items']],
                   'questionDigests': {i['questionId']: question_digest(extract_authored(spec, i['questionId']))
                                       for i in spec['items']} if mode == 'authored' else {},
                   'preparationDigest': digest(archive), 'reviewDigest': digest(review)}
        validate_binding(binding)
        contents = [extract_authored(spec, i['questionId']) if mode == 'authored' else render_variant_template(
            spec, i['questionId'], source_inputs=sources, lesson_ref=spec['lessonRef'], lesson_bytes=lesson)
            for i in spec['items']]
        if mode == 'authored':
            need(all(not check_question(spec, q['question_id'], q)['blocking'] for q in contents), 'question_literals')
        return binding, archive, contents

    def freeze(self, store, mode):
        binding, archive, contents = self.checked(mode)
        path = store.root / 'question-evidence' / binding['preparationDigest'] / 'preparation.json'
        data = ordered_bytes(archive)
        need(len(data) <= ARCHIVE_LIMIT, 'question_archive_size')
        atomic(path, data, immutable=True)
        return binding, archive, contents


def verify_archive(archive, binding):
    validate_binding(binding)
    fields(archive, ('schema', 'spec', 'lesson', 'sources', 'productionReview'))
    need(archive['schema'] == EVIDENCE and digest(archive) == binding['preparationDigest'], 'question_archive')
    spec = validate_spec(archive['spec'])
    need(spec_digest(spec) == binding['specDigest'] and spec['lessonSha256'] == binding['lessonSha256']
         and spec['lessonRef'] == binding['lessonRef'] and digest(archive['productionReview']) == binding['reviewDigest'])
    verify_inputs(spec, source_inputs={key: {'sourceVersionId': row['sourceVersionId'],
        'content': row['content'].encode('utf-8')} for key, row in archive['sources'].items()},
        lesson_ref=binding['lessonRef'], lesson_bytes=archive['lesson'].encode('utf-8'))
    need([{k: s[k] for k in ('sourceId', 'sourceVersionId', 'sha256')} for s in spec['sources']] == binding['sources'])
    need([i['questionId'] for i in spec['items']] == binding['questionIds'] and
         all(i['mode'] == binding['mode'] for i in spec['items']))
    for row in archive['sources'].values(): fields(row, ('sourceVersionId', 'content'))
    review = archive['productionReview']
    fields(review, ('schema', 'reviewId', 'reviewedBy', 'specDigest', 'mode', 'decision', 'checks', 'assurance'))
    need(review['schema'] == 'learning-question-preparation-review/1' and review['mode'] == binding['mode'] and
         review['specDigest'] == binding['specDigest'] and review['decision'] == 'reviewed_for_production' and
         review['assurance'] == 'operator_supplied', 'question_review')
    need(type(review['checks']) is list and len(review['checks']) == len(spec['items']))
    for item, check in zip(spec['items'], review['checks']):
        fields(check, ('questionId', 'contentDigest', 'reason'))
        content = extract_authored(spec, item['questionId']) if binding['mode'] == 'authored' else render_variant_template(
            spec, item['questionId'], source_inputs={k:{'sourceVersionId':r['sourceVersionId'],
                'content':r['content'].encode('utf-8')} for k,r in archive['sources'].items()},
            lesson_ref=spec['lessonRef'], lesson_bytes=archive['lesson'].encode('utf-8'))
        need(check['questionId'] == item['questionId'] and check['contentDigest'] == (
            question_digest(content) if binding['mode'] == 'authored' else digest(content)) and
            type(check['reason']) is str and bool(check['reason'].strip()), 'question_review_checks')
    return spec


def load_archive(store, binding):
    path = store.root / 'question-evidence' / binding['preparationDigest'] / 'preparation.json'
    archive = decode_json(read_bounded(path, ARCHIVE_LIMIT))
    verify_archive(archive, binding)
    return archive
