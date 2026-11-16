"""I4/I5 的题目附件闭合和最终版本审查。旧 /1 摘要不变。"""
from copy import deepcopy

from .contracts import DeliveryError, digest, sha256, decode_json
from .question_preparation import EVIDENCE, fields, load_archive, need, validate_binding, verify_archive, publication_digest
from .question_spec import check_question, question_digest, render_variant_template


def blocks(content):
    orders = {(r['pageId'], r['blockId'], r['questionId']): r['optionKeys']
              for r in content.get('optionDisplayOrders', [])}
    result = {}
    for page in content['pages']:
        for block in page.get('blocks', []) if isinstance(page.get('blocks'), list) else []:
            if not isinstance(block, dict) or block.get('type') != 'quiz': continue
            payload = block.get('payload') if isinstance(block.get('payload'), dict) else {}
            questions = deepcopy(payload.get('questions', []))
            if not isinstance(questions, list): questions = []
            for q in questions:
                if not isinstance(q, dict): continue
                key = (page['id'], block['id'], q.get('question_id'))
                if key in orders and isinstance(q.get('options'), dict):
                    need(set(orders[key]) == set(q['options']), 'question_option_order')
                    q['options'] = {k: q['options'][k] for k in orders[key]}
            metadata = block.get('metadata') if isinstance(block.get('metadata'), dict) else {}
            result[(page['id'], block['id'])] = (metadata.get('learning_question_binding'), questions)
    return result


def collect(store, activity_id, content):
    actual = blocks(content)
    expected, publications = {}, {}
    controlled = False
    for request in store.requests():
        semantic = request['semantic']
        if semantic.get('activityId') != activity_id or not semantic.get('questionPreparation'): continue
        controlled = True
        receipt = store.receipt(request['requestId'])
        if receipt['status'] == 'failed': continue
        need(receipt['status'] == 'succeeded', 'question_production_unresolved')
        key = (semantic['payload']['page_id'], semantic['payload']['block_id'])
        need(key not in expected, 'question_multiple_publications')
        expected[key] = semantic['questionPreparation']
        saved = store.response(request['requestId'], 'book') or store.response(request['requestId'], 'book-reconcile')
        need(saved is not None and not saved[0].get('redacted'), 'question_publication_evidence')
        wire = store.stage_dir(request['requestId'], 'book') / 'request.bin'
        need(wire.is_file(), 'question_publication_evidence')
        publications[key] = {'request':decode_json(wire.read_bytes()), 'response':decode_json(saved[1])}
    observed = {key: value[0] for key, value in actual.items() if value[0] is not None}
    if not controlled and not observed and not content['book'].get('metadata', {}).get('learning_question_controlled'):
        return None
    need(expected == observed and bool(expected), 'question_binding_missing_or_changed')
    rows = []
    for key, binding in sorted(expected.items()):
        archive = load_archive(store, binding)
        questions = actual[key][1]
        validate_binding(binding, questions)
        checks = [check_question(archive['spec'], q['question_id'], q) for q in questions]
        rows.append({'pageId': key[0], 'blockId': key[1], 'binding': binding, 'archive': archive,
                     'questions': questions, 'questionDigests': [question_digest(q) for q in questions],
                     'checks': checks, 'production':publications[key]})
    evidence = {'schema': EVIDENCE, 'activityId': activity_id, 'bookId': content['book']['id'], 'blocks': rows}
    verify(evidence, content, activity_id=activity_id)
    return evidence


def verify(evidence, content, *, activity_id=None):
    fields(evidence, ('schema', 'activityId', 'bookId', 'blocks'))
    need(evidence['schema'] == EVIDENCE and evidence['bookId'] == content['book']['id'] and
         (activity_id is None or evidence['activityId'] == activity_id), 'question_evidence_identity')
    actual = blocks(content)
    need(type(evidence['blocks']) is list and bool(evidence['blocks']), 'question_evidence_empty')
    seen = set()
    for row in evidence['blocks']:
        fields(row, ('pageId', 'blockId', 'binding', 'archive', 'questions', 'questionDigests', 'checks', 'production'))
        key = (row['pageId'], row['blockId'])
        need(key not in seen and key in actual, 'question_evidence_target'); seen.add(key)
        binding = validate_binding(row['binding'], row['questions'])
        spec = verify_archive(row['archive'], binding)
        fields(row['production'], ('request', 'response'))
        wire, response = row['production']['request'], row['production']['response']
        fields(wire, ('book_id', 'page_id', 'block_id', 'expected_revision', 'request_id', 'request_digest',
                      'question_binding', 'questions' if binding['mode'] == 'authored' else 'params_override'))
        need(wire['book_id'] == content['book']['id'] and wire['page_id'] == key[0] and wire['block_id'] == key[1]
             and wire['question_binding'] == binding and publication_digest(wire) == wire['request_digest'], 'question_publication_request')
        publication = response['publication']
        need(publication['requestId'] == wire['request_id'] and publication['requestDigest'] == wire['request_digest']
             and publication['bookId'] == wire['book_id'] and publication['pageId'] == key[0]
             and publication['blockId'] == key[1] and response['block']['id'] == key[1]
             and response['block'].get('metadata', {}).get('learning_question_binding') == binding
             and [question_digest(q) for q in response['block']['payload']['questions']] == row['questionDigests'],
             'question_publication_content_changed')
        if binding['mode'] == 'authored':
            need([question_digest(q) for q in wire['questions']] == row['questionDigests'], 'question_authored_changed')
        else:
            archive = row['archive']
            templates = [render_variant_template(spec, item['questionId'], source_inputs={
                k:{'sourceVersionId':r['sourceVersionId'],'content':r['content'].encode('utf-8')}
                for k,r in archive['sources'].items()}, lesson_ref=spec['lessonRef'], lesson_bytes=archive['lesson'].encode('utf-8'))
                for item in spec['items']]
            need(wire['params_override'] == {'num_questions':len(templates),'question_type':'choice',
                 'prepared_templates':templates}, 'question_variant_request_changed')
        page = next(p for p in content['pages'] if p['id'] == row['pageId'])
        extension_aware = content['book'].get('metadata', {}).get('learning_extension_head') is not None
        lesson = '\n\n'.join(str(b['payload'].get('body', b['payload'].get('content', '')))
                             for b in page['blocks'] if b['type'] == 'text'
                             and not (extension_aware and b.get('metadata', {}).get('learning_extension_id')))
        need(sha256(lesson.encode('utf-8')) == binding['lessonSha256'], 'question_lesson_changed')
        need(binding == actual[key][0] and [question_digest(q) for q in actual[key][1]] == row['questionDigests']
             and [question_digest(q) for q in row['questions']] == row['questionDigests'], 'question_evidence_content')
        checks = [check_question(spec, q['question_id'], q) for q in row['questions']]
        need(checks == row['checks'], 'question_evidence_checks')
    need(seen == {key for key, value in actual.items() if value[0] is not None}, 'question_evidence_inventory')
    return evidence


def review_reasons(review, evidence):
    """Require an explicit final-content judgment for each immutable version."""
    expected = {}
    for row in evidence['blocks']:
        spec = row['archive']['spec']
        for q, qdigest in zip(row['questions'], row['questionDigests']):
            item = next(i for i in spec['items'] if i['questionId'] == q['question_id'])
            key = (row['pageId'], row['blockId'], q['question_id'])
            expected[key] = (row['binding']['specDigest'], qdigest, item['targetObjectiveId'])
    checks = review.get('questionProductionChecks')
    reasons = []
    if any(c['blocking'] for row in evidence['blocks'] for c in row['checks']):
        reasons.append('question_constraint_findings')
    if not isinstance(checks, list): return reasons + ['question_final_review_required']
    seen = set()
    for c in checks:
        if not isinstance(c, dict): return reasons + ['question_final_review_invalid']
        key = (c.get('pageId'), c.get('blockId'), c.get('questionId'))
        if (key in seen or key not in expected or
                (c.get('specDigest'), c.get('questionDigest'), c.get('targetObjectiveId')) != expected.get(key) or
                c.get('decision') != 'pass' or not isinstance(c.get('reason'), str) or not c['reason'].strip() or
                any(c.get(k) is not True for k in ('sourceFidelityChecked', 'goalAlignmentChecked',
                                                 'answerUniqueChecked', 'explanationChecked'))):
            reasons.append('question_final_review_invalid')
        seen.add(key)
    if seen != set(expected): reasons.append('question_final_review_incomplete')
    return sorted(set(reasons))
