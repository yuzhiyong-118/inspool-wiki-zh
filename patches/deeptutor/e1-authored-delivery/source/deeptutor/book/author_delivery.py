"""Authored text and whole-book delivery with synchronous request journals."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import threading
import time

from tools.learning_book.contracts import decode_json, digest, identifier, sha256
from tools.learning_book.evidence_store import atomic
from tools.learning_book.question_preparation import ordered_bytes
from tools.learning_book.authored_delivery import CAPABILITY, content_plan, fields, need, request_digest

_inside = ContextVar("author_write", default=False)
_lock = threading.RLock()


@contextmanager
def coordinated():
    with _lock:
        yield


@contextmanager
def managed():
    with _lock:
        token = _inside.set(True)
        try:
            yield
        finally:
            _inside.reset(token)


def _model(value):
    return None if value is None else digest(value.model_dump(mode="json"))


def _journal_path(storage, book_id, request_id):
    return storage.book_root(book_id) / "author-writes" / (digest(request_id) + ".json")


def _journals(storage, book_id):
    root = storage.book_root(book_id) / "author-writes"
    return sorted(root.glob("*.json")) if root.exists() else []


def _verify(record, book_id):
    need(record.get("schema") == "learning-authored-write/1" and record.get("state") in ("prepared", "applied"),
         "author_journal_uncertain")
    need(record["book"]["id"] == book_id and record["afterBook"] == _model_data(record["book"])
         and record["responseDigest"] == digest(record["response"])
         and record["response"]["publication"]["requestId"] == record["requestId"]
         and record["response"]["publication"]["requestDigest"] == record["requestDigest"],
         "author_journal_uncertain")
    pages = record["pages"]
    need(type(pages) is list and pages and record["afterPages"] == [_model_data(page) for page in pages]
         and all(page["book_id"] == book_id for page in pages), "author_journal_uncertain")


def _model_data(value):
    return digest(value)


def recover(storage, book_id):
    if _inside.get():
        return
    with managed():
        for path in _journals(storage, book_id):
            record = decode_json(path.read_bytes())
            need(record.get("schema") == "learning-authored-write/1", "author_journal")
            if record["state"] in ("applied", "failed"):
                continue
            need(record["state"] == "prepared", "author_journal_uncertain")
            _verify(record, book_id)
            book = storage.load_book(book_id)
            pages = [storage.load_page(book_id, page["id"]) for page in record["pages"]]
            need(_model(book) in (record["beforeBook"], record["afterBook"]), "author_journal_uncertain")
            current = [_model(page) for page in pages]
            need(all(value in (before, after) for value, before, after in
                     zip(current, record["beforePages"], record["afterPages"])), "author_journal_uncertain")
            from .models import Book, Page
            for page, data, after in zip(pages, record["pages"], record["afterPages"]):
                if _model(page) != after:
                    storage.save_page(Page.model_validate(data))
            if _model(book) != record["afterBook"]:
                storage.save_book(Book.model_validate(record["book"]))
            need(_model(storage.load_book(book_id)) == record["afterBook"]
                 and [_model(storage.load_page(book_id, page["id"])) for page in record["pages"]]
                 == record["afterPages"], "author_journal_uncertain")
            record["state"] = "applied"
            atomic(path, ordered_bytes(record))


def recover_all(storage):
    from tools.learning_book.contracts import DeliveryError
    unresolved = []
    for book_id in storage.list_book_ids():
        try:
            recover(storage, book_id)
        except (DeliveryError, OSError, ValueError, KeyError, TypeError) as exc:
            unresolved.append({"bookId": book_id,
                               "code": exc.code if isinstance(exc, DeliveryError) else "author_journal_uncertain"})
    return unresolved


def _target(engine, payload):
    from .generation import generation_state
    book = engine.storage.load_book(payload["book_id"])
    need(book is not None, "author_book_missing")
    need(book.status.value in ("compiling", "spine_ready"), "author_book_state")
    need(book.revision == payload["expected_revision"], "author_revision")
    need(not book.metadata.get("learning_baseline_accepted"), "author_baseline_accepted")
    progress = engine.storage.load_progress(book.id)
    need(progress is None or not (progress.quiz_attempts or progress.visited_page_ids or progress.current_page_id),
         "author_learning_started")
    pages, enumeration = engine.storage.list_pages_strict(book.id)
    need(pages and not enumeration["errors"], "author_content_enumeration")
    need(not engine.is_worker_live(book.id)
         and not any(generation_state(page).get("state") == "running" for page in pages),
         "author_generation_busy")
    return book, pages


def _publication(payload):
    return {"schema": CAPABILITY, "bookId": payload["book_id"], "requestId": payload["request_id"],
            "requestDigest": payload["request_digest"], "modelCalls": 0}


def _commit(engine, payload, book, pages, before_book, before_pages, response, *, fault, save_page):
    path = _journal_path(engine.storage, book.id, payload["request_id"])
    record = {"schema": "learning-authored-write/1", "state": "prepared",
              "requestId": payload["request_id"], "requestDigest": payload["request_digest"],
              "beforeBook": before_book, "beforePages": before_pages,
              "afterBook": _model(book), "afterPages": [_model(page) for page in pages],
              "book": book.model_dump(mode="json"), "pages": [page.model_dump(mode="json") for page in pages],
              "response": response, "responseDigest": digest(response)}
    atomic(path, ordered_bytes(record), immutable=True)
    fault("prepared")
    if save_page is not None:
        engine.storage.save_page(save_page)
        fault("page")
    engine.storage.save_book(book)
    fault("book")
    need(_model(engine.storage.load_book(book.id)) == record["afterBook"]
         and [_model(engine.storage.load_page(book.id, page.id)) for page in pages] == record["afterPages"],
         "author_commit")
    record["state"] = "applied"
    atomic(path, ordered_bytes(record))
    fault("applied")
    return response


def write_block(engine, payload, *, fault=lambda _: None):
    from .models import Block, BlockStatus, BlockType
    fields(payload, ("book_id", "page_id", "operation", "block_id", "title", "body", "position",
                     "expected_revision", "request_id", "request_digest", "author_binding"))
    identifier(payload["request_id"], "requestId")
    need(request_digest(payload) == payload["request_digest"], "author_request_digest")
    need(payload["operation"] in ("insert", "update") and type(payload["body"]) is str
         and payload["body"].strip() and len(payload["body"]) <= 262144, "author_body")
    need(type(payload["expected_revision"]) is int and payload["expected_revision"] >= 1, "author_revision")
    fields(payload["author_binding"], ("schema", "activityId", "operation", "preparationDigest",
                                      "sourceDigest", "bodySha256"))
    need(payload["author_binding"]["schema"] == "learning-authored-binding/1"
         and payload["author_binding"]["operation"] == payload["operation"]
         and payload["author_binding"]["bodySha256"] == sha256(payload["body"].encode("utf-8")),
         "author_binding")
    with _lock:
        recover(engine.storage, payload["book_id"])
        path = _journal_path(engine.storage, payload["book_id"], payload["request_id"])
        if path.exists():
            record = decode_json(path.read_bytes())
            _verify(record, payload["book_id"])
            need(record["requestDigest"] == payload["request_digest"], "author_request_conflict")
            need(record["state"] == "applied", "author_journal_uncertain")
            return record["response"]
        book, pages = _target(engine, payload)
        page = engine.storage.load_page(book.id, payload["page_id"])
        need(page is not None and page.book_id == book.id, "author_page")
        before_book, before_pages = _model(book), [_model(page)]
        if payload["operation"] == "insert":
            block = Block(type=BlockType.TEXT, status=BlockStatus.READY, title=payload["title"] or "",
                          params={"role": "authored"}, payload={"format": "markdown", "body": payload["body"]})
            position = payload["position"]
            need(position is None or type(position) is int, "author_position")
            if position is None or position >= len(page.blocks) or position < 0:
                page.blocks.append(block)
            else:
                page.blocks.insert(position, block)
        else:
            matches = [item for item in page.blocks if item.id == payload["block_id"]
                       and item.type == BlockType.TEXT]
            need(len(matches) == 1, "author_target")
            block = matches[0]
            block.payload = {**block.payload, "body": payload["body"], "format": "markdown"}
            block.status = BlockStatus.READY
            block.error = ""
            if payload["title"] is not None:
                need(type(payload["title"]) is str and len(payload["title"]) <= 4000, "author_title")
                block.title = payload["title"]
        block.metadata = {**(block.metadata or {}), "edited_by_user": True,
                          "learning_author_request": payload["request_id"]}
        block.updated_at = time.time()
        engine.compiler._finalize_page_status(page)
        need(page.status.value == "ready", "author_page_not_ready")
        book.revision += 1
        book.updated_at = time.time()
        book.metadata = {**(book.metadata or {}), "learning_author_delivery": CAPABILITY}
        response = {"block": block.model_dump(mode="json"), "book_revision": book.revision,
                    "publication": _publication(payload)}
        with managed():
            return _commit(engine, payload, book, [page], before_book, before_pages, response,
                           fault=fault, save_page=page)


def complete_book(engine, payload, *, fault=lambda _: None):
    from .models import BookStatus
    fields(payload, ("book_id", "expected_revision", "request_id", "request_digest", "plan", "author_binding"))
    identifier(payload["request_id"], "requestId")
    need(request_digest(payload) == payload["request_digest"], "author_request_digest")
    need(type(payload["expected_revision"]) is int and payload["expected_revision"] >= 1, "author_revision")
    fields(payload["author_binding"], ("schema", "activityId", "operation", "preparationDigest",
                                      "sourceDigest", "planDigest"))
    need(payload["author_binding"]["schema"] == "learning-authored-binding/1"
         and payload["author_binding"]["operation"] == "complete", "author_binding")
    need(payload["plan"].get("bookId") == payload["book_id"]
         and payload["author_binding"].get("planDigest") == digest(payload["plan"]), "author_plan")
    with _lock:
        recover(engine.storage, payload["book_id"])
        path = _journal_path(engine.storage, payload["book_id"], payload["request_id"])
        if path.exists():
            record = decode_json(path.read_bytes())
            _verify(record, payload["book_id"])
            need(record["requestDigest"] == payload["request_digest"], "author_request_conflict")
            need(record["state"] == "applied", "author_journal_uncertain")
            return record["response"]
        book, pages = _target(engine, payload)
        need(book.status != BookStatus.READY, "author_already_completed")
        pages, enumeration = engine.storage.list_pages_strict(book.id)
        spine = engine.storage.load_spine(book.id)
        content = {"schema": "book-content-read/1", "book": book.model_dump(mode="json"),
                   "spine": spine.model_dump(mode="json") if spine else None,
                   "pages": [page.model_dump(mode="json") for page in pages],
                   "pageEnumeration": enumeration}
        need(content_plan(content, book.id) == payload["plan"], "author_plan")
        for page in pages:
            need(page.status.value == "ready" and page.blocks, "author_page_not_ready")
            need(all(block.status.value == "ready" and not block.error for block in page.blocks),
                 "author_block_not_ready")
            states = [_content_state(block) for block in page.blocks]
            need(None not in states, "author_content_unsupported")
            need(all(state is True or state == "structural" for state in states),
                 "author_content_empty")
            need(any(state is True for state in states), "author_content_empty")
        before_book, before_pages = _model(book), [_model(page) for page in pages]
        book.status = BookStatus.READY
        book.metadata = {key: value for key, value in (book.metadata or {}).items()
                         if key not in {"pause_reason", "pause_kind"}}
        book.metadata["learning_author_delivery"] = CAPABILITY
        book.revision += 1
        book.updated_at = time.time()
        response = {"book": book.model_dump(mode="json"), "generation": engine.generation_overview(book),
                    "book_revision": book.revision, "publication": _publication(payload)}
        with managed():
            return _commit(engine, payload, book, pages, before_book, before_pages, response,
                           fault=fault, save_page=None)


def _meaningful(value):
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_meaningful(item) for item in value.values())
    if isinstance(value, list):
        return any(_meaningful(item) for item in value)
    return False


def _items_text(payload, key, fields):
    items = payload.get(key)
    return type(items) is list and any(type(item) is dict
        and any(_meaningful(item.get(field)) for field in fields) for item in items)


def _content_state(block):
    kind = block.type.value
    payload = block.payload
    if kind in ("concept_graph", "progress_dashboard"):
        return "structural"
    if kind == "text":
        value = payload.get("body") if payload.get("body") is not None else payload.get("content")
        return type(value) is str and bool(value.strip())
    fields_by_type = {
        "callout": ("body",), "user_note": ("body", "content"),
        "code": ("code", "explanation"), "animation": ("summary", "key_points", "description"),
        "section": ("intro", "key_takeaway"), "deep_dive": (),
    }
    if kind in ("figure", "interactive"):
        code = payload.get("code")
        visual = type(code) is dict and _meaningful(code.get("content"))
        return visual or _meaningful(payload.get("description"))
    if kind in fields_by_type:
        present = any(_meaningful(payload.get(field)) for field in fields_by_type[kind])
        if kind == "section":
            present = present or _items_text(payload, "subsections", ("body",))
        if kind == "deep_dive":
            present = _items_text(payload, "suggestions", ("rationale",))
        return present
    if kind in ("quiz", "diagnostic", "pretest", "retrieval_practice", "error_diagnosis", "module_test"):
        return _items_text(payload, "questions", ("question",))
    if kind == "flash_cards":
        return _items_text(payload, "cards", ("front", "back"))
    if kind == "timeline":
        return _items_text(payload, "events", ("title", "description"))
    return None


def storage_barrier(storage, book_id, action, candidate=None):
    if _inside.get():
        return
    try:
        stable = not any(decode_json(path.read_bytes()).get("state") not in ("applied", "failed")
                         for path in _journals(storage, book_id))
    except (OSError, ValueError, TypeError, AttributeError):
        stable = False
    need(stable, "author_journal_unstable")


def lookup(engine, book_id, request_id):
    with _lock:
        recover(engine.storage, book_id)
        path = _journal_path(engine.storage, book_id, request_id)
        if not path.is_file():
            return None
        record = decode_json(path.read_bytes())
        need(record["state"] == "applied", "author_journal_uncertain")
        _verify(record, book_id)
        return record["response"]
