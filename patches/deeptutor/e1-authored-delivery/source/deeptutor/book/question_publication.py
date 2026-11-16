"""Local single-worker quiz publication; synchronous journal, no model calls.

This module is shipped as deeptutor.book.question_publication. Project contracts
are part of this local distribution, as is the existing RuntimeGuard bridge.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import threading

from tools.learning_book.contracts import canonical, decode_json, digest, sha256
from tools.learning_book.evidence_store import atomic
from tools.learning_book.question_preparation import (ordered_bytes, publication_digest,
    validate_binding, need, fields)
from tools.learning_book.question_spec import question_content, question_digest

CAPABILITY = 'learning-question-publication/1'
SAFETY_REVISION = 'learning-question-q3-fix/1'  # pinned with full install manifest
_inside = ContextVar('question_write', default=False)
_lock = threading.RLock()  # one backend worker; storage operations below never await


@contextmanager
def managed():
    with _lock:
        token = _inside.set(True)
        try:
            yield
        finally:
            _inside.reset(token)


def _journals(storage, book_id):
    root = storage.book_root(book_id) / 'question-writes'
    return sorted(root.glob('*.json')) if root.exists() else []


def _orders(blocks):
    return [{'blockId':block['id'], 'questions':[
        {'questionId':q.get('question_id'), 'keys':list(q.get('options', {}))}
        for q in block.get('payload', {}).get('questions', []) if isinstance(q, dict)]}
        for block in blocks if block.get('type') == 'quiz']


def _page_digest(value):
    return digest({'rule':'learning-question-page-write/1', 'page':value, 'optionOrders':_orders(value['blocks'])})


def _response_digest(value):
    return digest({'response':value, 'optionOrders':_orders([value['block']])})


def _model_digest(value):
    if value is None: return None
    data = value.model_dump(mode='json')
    return _page_digest(data) if 'blocks' in data else digest(data)


def _verify_record(record, book_id):
    """Validate recovery images BEFORE touching either live file."""
    need(record.get('schema') == 'learning-question-write/1' and record.get('state') in ('prepared', 'applied'),
         'question_journal_uncertain')
    need(digest(record['book']) == record['afterBook'] and _page_digest(record['page']) == record['afterPage'] and
         _response_digest(record['response']) == record['responseDigest'] and record['book']['id'] == book_id and
         record['page']['book_id'] == book_id and record['page']['id'] == record['pageId'] and
         record['response']['publication']['requestDigest'] == record['requestDigest'] and
         record['response']['publication']['requestId'] == record['requestId'], 'question_journal_uncertain')


def recover(storage, book_id):
    if _inside.get():
        return
    with managed():
        for path in _journals(storage, book_id):
            record = decode_json(path.read_bytes())
            need(record['schema'] == 'learning-question-write/1', 'question_journal')
            if record['state'] in ('applied', 'failed'):
                continue
            need(record['state'] == 'prepared', 'question_journal_uncertain')
            _verify_record(record, book_id)
            book = storage.load_book(book_id)
            page = storage.load_page(book_id, record['pageId'])
            bd, pd = _model_digest(book), _model_digest(page)
            # Page is persisted first. An after-book + before-page state is not
            # produced by this protocol and must not be guessed into success.
            need((bd, pd) in ((record['beforeBook'], record['beforePage']),
                (record['beforeBook'], record['afterPage']),
                (record['afterBook'], record['afterPage'])), 'question_journal_uncertain')
            from .models import Book, Page
            if pd != record['afterPage']:
                storage.save_page(Page.model_validate(record['page']))
            if bd != record['afterBook']:
                storage.save_book(Book.model_validate(record['book']))
            need(_model_digest(storage.load_book(book_id)) == record['afterBook'] and
                 _model_digest(storage.load_page(book_id, record['pageId'])) == record['afterPage'],
                 'question_journal_uncertain')
            record['state'] = 'applied'
            atomic(path, ordered_bytes(record))


def storage_barrier(storage, book_id, action, candidate=None):
    from .author_delivery import storage_barrier as author_storage_barrier
    author_storage_barrier(storage, book_id, action, candidate=candidate)
    if _inside.get():
        return
    if action.startswith('load_') or action.startswith('list_'):
        try:
            stable = not any(decode_json(p.read_bytes()).get('state') not in ('applied', 'failed') for p in _journals(storage, book_id))
        except (OSError, ValueError, TypeError, AttributeError):
            stable = False
        need(stable, 'question_journal_unstable')
        return
    recover(storage, book_id)
    book = storage.load_book(book_id) if action != 'load_book' else None
    if action.startswith('save_') or action.startswith('delete_'):
        # A completed publication is a protected activity. Native attempts and
        # progress remain writable; content changes require a new activity.
        controlled = bool(book and book.metadata.get('learning_question_controlled'))
        if controlled and action == 'save_book' and candidate is not None:
            def content(value):
                value = value.model_dump(mode='json')
                value.pop('updated_at', None)
                value.pop('chat_session_id', None)
                value.get('metadata', {}).pop('page_chat_sessions', None)
                return value
            need(content(book) == content(candidate), 'question_content_protected')
            return
        if action not in ('save_progress', 'save_learning_captures'):
            need(not controlled, 'question_content_protected')


def native_barrier(storage, book_id, action):
    recover(storage, book_id)
    book = storage.load_book(book_id)
    if not _inside.get() and book and book.metadata.get('learning_question_controlled'):
        need(action in ('pause', 'resume'), 'question_content_protected')


def unstable_summary(storage, book_id):
    """Library-only diagnostic; never writes or presents mixed content as ready."""
    from .models import BookStatus
    with managed():
        book = storage.load_book(book_id)
        if book is not None:
            book.status = BookStatus.ERROR
            book.metadata['learning_question_unstable'] = True
        return book


def _target(engine, payload):
    from .models import BlockType
    book_id = payload['book_id']
    book = engine.storage.load_book(book_id)
    need(book is not None, 'question_book_missing')
    need(book.revision == payload['expected_revision'], 'question_revision')
    need(book.status.value not in ('compiling', 'paused', 'error'), 'question_book_state')
    progress = engine.storage.load_progress(book_id)
    need(progress is None or not (progress.quiz_attempts or progress.visited_page_ids or progress.current_page_id),
         'question_learning_started')
    need(not book.metadata.get('learning_baseline_accepted'), 'question_baseline_accepted')
    pages = engine.storage.list_pages(book_id)
    from .generation import generation_state
    need(not any(generation_state(p).get('state') == 'running' for p in pages), 'question_generation_busy')
    page = engine.storage.load_page(book_id, payload['page_id'])
    need(page is not None and page.book_id == book_id, 'question_page')
    lesson = '\n\n'.join(str(b.payload.get('body', b.payload.get('content', ''))) for b in page.blocks
                         if b.type == BlockType.TEXT)
    need(sha256(lesson.encode('utf-8')) == payload['question_binding']['lessonSha256'], 'question_lesson_changed')
    blocks = [b for b in page.blocks if b.id == payload['block_id']]
    need(len(blocks) == 1 and blocks[0].type == BlockType.QUIZ, 'question_target')
    need(not blocks[0].metadata.get('learning_question_binding'), 'question_already_published')
    return book, page, blocks[0]


def publish(engine, payload, *, fault=lambda _: None, generated=False, original_digest=None):
    from .models import BlockStatus
    from tools.learning_book.contracts import identifier
    with _lock:
        recover(engine.storage, payload['book_id'])
        identifier(payload['request_id'], 'requestId')
        need(publication_digest(payload) == payload['request_digest'], 'question_request_digest')
        identity = original_digest if generated else payload['request_digest']
        need(identity is not None)
        questions = payload['questions']
        need(type(questions) is list and 1 <= len(questions) <= 8, 'question_count')
        for q in questions: question_content(q, authored=not generated)
        binding = validate_binding(payload['question_binding'], questions)
        need(binding['mode'] == ('variant' if generated else 'authored'), 'question_mode')
        path = engine.storage.book_root(payload['book_id']) / 'question-writes' / (digest(payload['request_id']) + '.json')
        if path.exists():
            record = decode_json(path.read_bytes())
            _verify_record(record, payload['book_id'])
            need(record['requestDigest'] == identity, 'question_request_conflict')
            need(record['state'] == 'applied', 'question_journal_uncertain')
            return record['response']
        with managed():
            book, page, block = _target(engine, payload)
            before_book, before_page = _model_digest(book), _model_digest(page)
            block.payload = {'questions': deepcopy(questions)}
            block.status = BlockStatus.READY
            block.error = ''
            block.metadata['learning_question_binding'] = binding
            book.metadata['learning_question_controlled'] = CAPABILITY
            book.revision += 1
            response = {'block': block.model_dump(mode='json'), 'book_revision': book.revision,
                        'publication': {'schema': CAPABILITY, 'bookId': book.id, 'pageId': page.id,
                            'blockId': block.id, 'requestId': payload['request_id'],
                            'requestDigest': identity, 'modelCalls': 'see_runtime_ledger' if generated else 0}}
            record = {'schema': 'learning-question-write/1', 'state': 'prepared',
                'requestDigest': identity, 'requestId': payload['request_id'],
                'pageId': page.id, 'beforeBook': before_book, 'beforePage': before_page,
                'afterBook': _model_digest(book), 'afterPage': _model_digest(page),
                'book': book.model_dump(mode='json'), 'page': page.model_dump(mode='json'),
                'response': response, 'responseDigest':_response_digest(response)}
            atomic(path, ordered_bytes(record), immutable=True)
            fault('prepared')
            engine.storage.save_page(page); fault('page')
            engine.storage.save_book(book); fault('book')
            need(_model_digest(engine.storage.load_page(book.id, page.id)) == record['afterPage'] and
                 _model_digest(engine.storage.load_book(book.id)) == record['afterBook'], 'question_commit')
            record['state'] = 'applied'; atomic(path, ordered_bytes(record)); fault('applied')
            return response


async def generate_variant(engine, payload):
    """Generate on a detached page, then commit through the same journal.

    The reservation is durable. A crash during model generation stays uncertain;
    no startup path replays the generation. Existing page/learning bytes survive.
    """
    from .blocks.base import BlockContext
    from .blocks.quiz import QuizGenerator
    from .models import BlockStatus
    from tools.learning_book.question_spec import TEMPLATE_FIELDS
    fields(payload, ('book_id', 'page_id', 'block_id', 'expected_revision', 'request_id',
                     'request_digest', 'question_binding', 'params_override'))
    need(type(payload['expected_revision']) is int and payload['expected_revision'] >= 1, 'question_revision')
    need(publication_digest(payload) == payload['request_digest'], 'question_request_digest')
    binding = validate_binding(payload['question_binding'])
    need(binding['mode'] == 'variant')
    params = payload['params_override']
    fields(params, ('num_questions', 'question_type', 'prepared_templates'))
    templates = params['prepared_templates']
    need(type(templates) is list and 1 <= len(templates) <= 8 and
         all(type(t) is dict and set(t) == set(TEMPLATE_FIELDS) for t in templates))
    need(type(params['num_questions']) is int and params['num_questions'] == len(templates) and
         params['question_type'] == 'choice' and [t['question_id'] for t in templates] == binding['questionIds'])
    for template in templates:
        need(set(template) == set(TEMPLATE_FIELDS) and template['question_type'] == 'choice' and
             all(type(v) is str and v.strip() and len(v) <= 32768 for v in template.values()))
    storage = engine.storage
    with _lock:
        recover(storage, payload['book_id'])
        book, page, block = _target(engine, payload)
        spine = storage.load_spine(book.id)
        need(spine is not None and spine.chapter_by_id(page.chapter_id) is not None, 'question_spine')
        reservation = storage.book_root(book.id) / 'question-writes' / (digest(payload['request_id']) + '.variant.json')
        need(not reservation.exists(), 'question_generation_not_replayed')
        atomic(reservation, ordered_bytes({'schema': 'learning-question-write/1', 'state': 'generating',
            'requestDigest': payload['request_digest'], 'requestId': payload['request_id']}), immutable=True)
    # No managed ContextVar escapes across await; all competing native writes
    # and stable reads see the pending reservation and fail closed.
    block.params = {**block.params, **payload['params_override']}
    from deeptutor.services.llm.metrics import current_usage, TurnUsage
    usage_token = current_usage.set(TurnUsage(session_id='book-' + book.id,
        turn_id=payload['request_id'], source='book:prepare_question_variant'))
    try:
        ctx = BlockContext(book_id=book.id, chapter=spine.chapter_by_id(page.chapter_id), page=page,
                           block=block, language=book.language, knowledge_bases=[])
        await QuizGenerator().generate(ctx)
        need(block.status == BlockStatus.READY and not block.error, 'question_generation_failed')
        questions = block.payload['questions']
        validate_binding(binding, questions)
        # Replace reservation and publish synchronously, under the same lock.
        with _lock:
            record = decode_json(reservation.read_bytes()); record['state'] = 'failed'
            atomic(reservation, ordered_bytes(record))
            commit = {k: deepcopy(v) for k, v in payload.items() if k != 'params_override'}
            commit['questions'] = questions
            commit['request_digest'] = publication_digest(commit)
            return publish(engine, commit, generated=True, original_digest=payload['request_digest'])
    except BaseException:
        with _lock:
            record = decode_json(reservation.read_bytes())
            record['state'] = 'failed'
            atomic(reservation, ordered_bytes(record))
        raise
    finally:
        current_usage.reset(usage_token)


def lookup(engine, book_id, request_id):
    storage_barrier(engine.storage, book_id, 'load_publication')
    path = engine.storage.book_root(book_id) / 'question-writes' / (digest(request_id) + '.json')
    if not path.is_file():
        return None
    value = decode_json(path.read_bytes())
    need(value['state'] == 'applied', 'question_journal_uncertain')
    _verify_record(value, book_id)
    return value['response']


def recover_all(storage):
    from tools.learning_book.contracts import DeliveryError
    unresolved = []
    for book_id in storage.list_book_ids():
        try:
            recover(storage, book_id)
        except DeliveryError as exc:
            unresolved.append({'bookId': book_id, 'code': exc.code})
        except (OSError, ValueError, KeyError, TypeError):
            unresolved.append({'bookId': book_id, 'code': 'question_journal_uncertain'})
    return unresolved
