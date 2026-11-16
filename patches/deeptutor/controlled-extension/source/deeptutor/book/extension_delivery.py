"""Controlled learning extensions with one authoritative commit per request."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import threading
import time

from tools.learning_book.contracts import DeliveryError, decode_json, digest, identifier
from tools.learning_book.evidence_store import atomic
from tools.learning_book.extensions import (CAPABILITY, JOURNAL, apply_change, baseline_anchor,
    commit_digest, need, protected_from_models, protected_from_projection, request_digest,
    validate_binding, validate_blocks)
from tools.learning_book.question_preparation import ordered_bytes

_inside = ContextVar("extension_write", default=False)
_lock = threading.RLock()


@contextmanager
def managed():
    with _lock:
        token = _inside.set(True)
        try:
            yield
        finally:
            _inside.reset(token)


def inside():
    return _inside.get()


def _journal_path(storage, book_id, request_id):
    return storage.book_root(book_id) / "extension-writes" / (digest(request_id) + ".json")


def _journals(storage, book_id):
    root = storage.book_root(book_id) / "extension-writes"
    return sorted(root.glob("*.json")) if root.exists() else []


def _model(value):
    return None if value is None else digest(value.model_dump(mode="json"))


def _verify(record, book_id):
    need(type(record) is dict and record.get("schema") == JOURNAL
         and record.get("state") in ("prepared", "applied"), "extension_journal_uncertain")
    expected = {"schema", "state", "commit", "commitDigest", "book", "spine", "pages",
                "beforeBook", "beforeSpine", "beforePages", "afterBook", "afterSpine", "afterPages",
                "responseDigest"}
    need(set(record) == expected and record["commitDigest"] == commit_digest(record["commit"])
         and record["responseDigest"] == digest(record["commit"]["response"]), "extension_journal_uncertain")
    commit = record["commit"]
    need(commit["bookId"] == book_id and _model_data(record["book"]) == record["afterBook"]
         and _model_data(record["spine"]) == record["afterSpine"]
         and [_model_data(page) for page in record["pages"]] == record["afterPages"]
         and all(page["book_id"] == book_id for page in record["pages"]), "extension_journal_uncertain")


def _model_data(value):
    return None if value is None else digest(value)


def _recover_locked(storage, book_id):
    from .author_delivery import recover as recover_authors
    from .question_publication import recover as recover_questions
    recover_authors(storage, book_id)
    recover_questions(storage, book_id)
    _recover_extensions(storage, book_id)


def recover(storage, book_id):
    if _inside.get():
        _recover_locked(storage, book_id)
        return
    with managed():
        _recover_locked(storage, book_id)


def _recover_extensions(storage, book_id):
    from .models import Book, Page, Spine
    for path in _journals(storage, book_id):
        record = decode_json(path.read_bytes())
        _verify(record, book_id)
        if record["state"] == "applied":
            continue
        book = storage.load_book(book_id)
        spine = storage.load_spine(book_id)
        pages = [storage.load_page(book_id, page["id"]) for page in record["pages"]]
        need(_model(book) in (record["beforeBook"], record["afterBook"])
             and _model(spine) in (record["beforeSpine"], record["afterSpine"]),
             "extension_journal_uncertain")
        current = [_model(page) for page in pages]
        need(all(value in (before, after) for value, before, after in
                 zip(current, record["beforePages"], record["afterPages"])), "extension_journal_uncertain")
        if _model(spine) != record["afterSpine"]:
            need(record["spine"] is not None, "extension_journal_uncertain")
            storage.save_spine(Spine.model_validate(record["spine"]))
        for page, data, after in zip(pages, record["pages"], record["afterPages"]):
            if _model(page) != after:
                storage.save_page(Page.model_validate(data))
        if _model(book) != record["afterBook"]:
            storage.save_book(Book.model_validate(record["book"]))
        need(_model(storage.load_book(book_id)) == record["afterBook"]
             and _model(storage.load_spine(book_id)) == record["afterSpine"]
             and [_model(storage.load_page(book_id, page["id"])) for page in record["pages"]]
             == record["afterPages"], "extension_journal_uncertain")
        record["state"] = "applied"
        atomic(path, ordered_bytes(record))


def recover_all(storage):
    unresolved = []
    for book_id in storage.list_book_ids():
        try:
            recover(storage, book_id)
            from .extension_generation import reconcile_candidates
            reconcile_candidates(storage, book_id)
        except (DeliveryError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            unresolved.append({"bookId": book_id,
                               "code": exc.code if isinstance(exc, DeliveryError) else "extension_journal_uncertain"})
    return unresolved


def storage_barrier(storage, book_id, action, candidate=None):
    if _inside.get():
        return
    try:
        stable = not any(decode_json(path.read_bytes()).get("state") != "applied"
                         for path in _journals(storage, book_id))
    except (OSError, ValueError, TypeError, AttributeError):
        stable = False
    if action in ("save_progress", "load_progress", "save_learning_captures", "load_learning_captures",
                  "load_learning_capture"):
        return
    need(stable, "extension_journal_unstable")


def _source_binding(pages, operation):
    from tools.learning_book.extensions import BINDING, QUALITY_UNREVIEWED
    bindings = [block.metadata.get("learning_question_binding") for page in pages for block in page.blocks
                if block.metadata.get("learning_question_binding")]
    need(bindings, "extension_source_binding")
    identities = {(binding.get("preparationDigest"), digest(binding.get("sources"))) for binding in bindings}
    need(len(identities) == 1, "extension_source_binding")
    preparation, sources = identities.pop()
    return {"schema": BINDING, "activityBinding": "book_local", "activityId": None,
            "operation": operation, "preparationDigest": preparation, "sourceDigest": sources,
            "qualityReview": QUALITY_UNREVIEWED}


def extension_context(engine, book_id, operation):
    book = engine.storage.load_book(book_id)
    need(book is not None and book.metadata.get("learning_question_controlled"), "extension_controlled_book_required")
    pages, enumeration = engine.storage.list_pages_strict(book_id)
    need(pages and not enumeration["errors"], "extension_content_enumeration")
    need(operation in ("append_blocks", "supplement", "deep_dive", "remove_block", "regenerate_block"),
         "extension_operation")
    return extension_context_for_pages(pages, operation)


def extension_context_for_pages(pages, operation):
    return _source_binding(pages, operation)


def _target(engine, payload):
    from .generation import generation_state
    from .question_publication import CAPABILITY as QUESTION_CAPABILITY
    book = engine.storage.load_book(payload["book_id"])
    need(book is not None, "extension_book_missing")
    need(book.metadata.get("learning_question_controlled") == QUESTION_CAPABILITY,
         "extension_controlled_book_required")
    need(book.status.value == "ready", "extension_book_state")
    need(book.revision == payload["expected_revision"], "extension_revision")
    pages, enumeration = engine.storage.list_pages_strict(book.id)
    expected_binding = _source_binding(pages, payload["extension_binding"]["operation"])
    actual_binding = payload["extension_binding"]
    need(actual_binding["preparationDigest"] == expected_binding["preparationDigest"]
         and actual_binding["sourceDigest"] == expected_binding["sourceDigest"], "extension_source_binding")
    if actual_binding["activityBinding"] == "book_local":
        need(actual_binding == expected_binding, "extension_source_binding")
    need(pages and not enumeration["errors"], "extension_content_enumeration")
    need(not engine.is_worker_live(book.id)
         and not any(generation_state(page).get("state") == "running" for page in pages),
         "extension_generation_busy")
    page = engine.storage.load_page(book.id, payload["page_id"])
    need(page is not None and page.book_id == book.id, "extension_page")
    return book, page, pages


def _existing_identity(pages):
    block_ids = {block.id for page in pages for block in page.blocks}
    question_ids = {question.get("question_id") for page in pages for block in page.blocks
                    for question in block.payload.get("questions", [])
                    if block.type.value == "quiz" and isinstance(question, dict)}
    return block_ids, question_ids


def _new_block(value, payload):
    from .models import Block, BlockStatus, BlockType
    metadata = {"learning_extension_id": payload["extension_id"],
                "learning_extension_request": payload["request_id"],
                "learning_extension_operation": payload["operation"],
                "ai_generated": True, "quality_review": "unreviewed"}
    if value["type"] == "deep_dive":
        metadata["deep_dive_pages"] = {}
    return Block(id=value["id"], type=BlockType(value["type"]), status=BlockStatus.READY,
                 title=value["title"], params=deepcopy(value["params"]), payload=deepcopy(value["payload"]),
                 source_anchors=deepcopy(value.get("source_anchors", [])), metadata=metadata)


def _head(book):
    value = (book.metadata or {}).get("learning_extension_head")
    if value is None:
        return {"sequence": 0, "commitDigest": None, "afterContentDigest": None}
    need(type(value) is dict and set(value) == {"sequence", "commitDigest", "afterContentDigest"}
         and type(value["sequence"]) is int and value["sequence"] >= 1,
         "extension_head")
    return value


def _commit(engine, payload, book, spine, pages, affected, response, *, fault,
            after_book=None, after_spine=None, model_calls=0, reused_from=None):
    before_protected = protected_from_models(book.model_dump(mode="json"), spine.model_dump(mode="json"),
                                             [page.model_dump(mode="json") for page in pages])
    head = _head(book)
    if head["sequence"]:
        need(head["afterContentDigest"] == digest(before_protected), "extension_content_changed")
    before_revision = book.revision
    book = after_book or book
    spine = after_spine or spine
    book.revision = before_revision + 1
    book.updated_at = time.time()
    after_models = {page.id: page for page in pages}
    after_models.update({page.id: page for page in affected})
    after_pages = sorted(after_models.values(), key=lambda page: (page.order, page.id))
    change = protected_from_models(book.model_dump(mode="json"), spine.model_dump(mode="json"),
                                   [page.model_dump(mode="json") for page in affected])
    after_protected = apply_change(before_protected, change)
    actual_after = protected_from_models(book.model_dump(mode="json"), spine.model_dump(mode="json"),
                                         [page.model_dump(mode="json") for page in after_pages])
    need(after_protected == actual_after, "extension_commit_projection")
    sequence = head["sequence"] + 1
    previous = head["commitDigest"] or baseline_anchor(book.id, digest(before_protected))
    response["publication"] = {"schema": CAPABILITY, "bookId": book.id, "requestId": payload["request_id"],
                               "requestDigest": payload["request_digest"], "extensionId": payload["extension_id"],
                               "sequence": sequence, "qualityReview": "unreviewed", "modelCalls": model_calls}
    if reused_from is not None:
        response["reusedFromRequestId"] = reused_from
    commit = {"schema": JOURNAL, "bookId": book.id, "requestId": payload["request_id"],
              "requestDigest": payload["request_digest"], "extensionId": payload["extension_id"],
              "sequence": sequence, "previousCommitDigest": previous,
              "beforeContentDigest": digest(before_protected), "afterContentDigest": digest(after_protected),
              "beforeRevision": before_revision, "afterRevision": book.revision,
              "operation": payload["operation"], "binding": deepcopy(payload["extension_binding"]),
              "change": change, "response": response}
    commit_id = commit_digest(commit)
    book.metadata = {**(book.metadata or {}), "learning_extension_head": {
        "sequence": sequence, "commitDigest": commit_id, "afterContentDigest": digest(after_protected)}}
    record = {"schema": JOURNAL, "state": "prepared", "commit": commit, "commitDigest": commit_id,
              "book": book.model_dump(mode="json"), "spine": spine.model_dump(mode="json"),
              "pages": [page.model_dump(mode="json") for page in affected],
              "beforeBook": None, "beforeSpine": _model(spine), "beforePages": [],
              "afterBook": _model(book), "afterSpine": _model(spine),
              "afterPages": [_model(page) for page in affected], "responseDigest": digest(response)}
    return record


def append_blocks(engine, payload, *, fault=lambda _: None, original_digest=None, model_calls=0, reused_from=None):
    expected = {"book_id", "page_id", "operation", "position", "expected_revision", "request_id",
                "request_digest", "extension_id", "blocks", "extension_binding"}
    need(type(payload) is dict and set(payload) == expected, "extension_fields")
    operation = payload["operation"]
    need(operation in ("append_blocks", "supplement"), "extension_operation")
    identifier(payload["request_id"], "requestId")
    identifier(payload["extension_id"], "extensionId")
    expected_digest = original_digest or request_digest(payload)
    need(expected_digest == payload["request_digest"], "extension_request_digest")
    need(type(payload["expected_revision"]) is int and payload["expected_revision"] >= 1,
         "extension_revision")
    validate_binding(payload["extension_binding"], operation=operation)
    candidates = validate_blocks(payload["blocks"])
    if operation == "supplement":
        need([block["type"] for block in candidates] == ["callout", "text", "quiz"]
             and len(candidates[2]["payload"]["questions"]) == 1, "extension_supplement_group")
    elif any(block["type"] == "quiz" for block in candidates):
        need(len(candidates) == 1 and len(candidates[0]["payload"]["questions"]) == 1,
             "extension_question_count")
    with managed():
        path = _journal_path(engine.storage, payload["book_id"], payload["request_id"])
        if path.exists():
            record = decode_json(path.read_bytes())
            _verify(record, payload["book_id"])
            need(record["commit"]["requestDigest"] == payload["request_digest"], "extension_request_conflict")
            need(record["state"] == "applied", "extension_journal_uncertain")
            return record["commit"]["response"]
        recover(engine.storage, payload["book_id"])
        book, page, pages = _target(engine, payload)
        block_ids, question_ids = _existing_identity(pages)
        for candidate in candidates:
            need(candidate["id"] not in block_ids, "extension_block_identity")
            if candidate["type"] == "quiz":
                need(all(question["question_id"] not in question_ids
                         for question in candidate["payload"]["questions"]), "extension_question_identity")
        new_blocks = [_new_block(candidate, payload) for candidate in candidates]
        position = payload["position"]
        need(position is None or type(position) is int, "extension_position")
        if position is None or position < 0 or position >= len(page.blocks):
            page.blocks.extend(new_blocks)
        else:
            page.blocks[position:position] = new_blocks
        page.updated_at = time.time()
        engine.compiler._finalize_page_status(page)
        need(page.status.value == "ready", "extension_page_not_ready")
        spine = engine.storage.load_spine(book.id)
        need(spine is not None, "extension_spine")
        response = {"blocks": [block.model_dump(mode="json") for block in new_blocks],
                    "book_revision": book.revision + 1}
        record = _commit(engine, payload, book, spine, pages, [page], response, fault=fault,
                         model_calls=model_calls, reused_from=reused_from)
        previous_book = engine.storage.load_book(book.id)
        record["beforeBook"] = _model(previous_book)
        original_page = engine.storage.load_page(book.id, page.id)
        record["beforePages"] = [_model(original_page)]
        _verify(record, book.id)
        atomic(path, ordered_bytes(record), immutable=True)
        fault("prepared")
        engine.storage.save_page(page)
        fault("page")
        engine.storage.save_book(book)
        fault("book")
        need(_model(engine.storage.load_book(book.id)) == record["afterBook"]
             and _model(engine.storage.load_page(book.id, page.id)) == record["afterPages"][0],
             "extension_commit")
        record["state"] = "applied"
        atomic(path, ordered_bytes(record))
        fault("applied")
        return response


def _owned_target(page, block_id):
    block = page.block_by_id(block_id)
    metadata = block.metadata if block is not None else {}
    need(block is not None and type(metadata.get("learning_extension_id")) is str
         and metadata.get("quality_review") == "unreviewed"
         and metadata.get("ai_generated") is True, "extension_block_not_owned")
    need(block.type.value != "quiz", "extension_quiz_protected")
    return block


def _commit_page(engine, payload, book, spine, pages, page, response, *, fault,
                 model_calls=0, reused_from=None):
    record = _commit(engine, payload, book, spine, pages, [page], response, fault=fault,
                     model_calls=model_calls, reused_from=reused_from)
    path = _journal_path(engine.storage, payload["book_id"], payload["request_id"])
    record["beforeBook"] = _model(engine.storage.load_book(book.id))
    record["beforePages"] = [_model(engine.storage.load_page(book.id, page.id))]
    _verify(record, book.id)
    atomic(path, ordered_bytes(record), immutable=True)
    fault("prepared")
    engine.storage.save_page(page)
    fault("page")
    engine.storage.save_book(book)
    fault("book")
    need(_model(engine.storage.load_book(book.id)) == record["afterBook"]
         and _model(engine.storage.load_page(book.id, page.id)) == record["afterPages"][0],
         "extension_commit")
    record["state"] = "applied"
    atomic(path, ordered_bytes(record))
    fault("applied")
    return response


def _block_commit_payload(payload, operation, extra=()):
    expected = {"book_id", "page_id", "block_id", "expected_revision", "request_id",
                "request_digest", "extension_id", "extension_binding", "operation"} | set(extra)
    need(type(payload) is dict and set(payload) == expected and payload["operation"] == operation,
         "extension_fields")
    identifier(payload["request_id"], "requestId")
    identifier(payload["extension_id"], "extensionId")
    need(type(payload["expected_revision"]) is int and payload["expected_revision"] >= 1,
         "extension_revision")
    validate_binding(payload["extension_binding"], operation=operation)


def _replay_block_commit(engine, payload):
    path = _journal_path(engine.storage, payload["book_id"], payload["request_id"])
    if not path.exists():
        return None
    record = decode_json(path.read_bytes())
    _verify(record, payload["book_id"])
    need(record["commit"]["requestDigest"] == payload["request_digest"], "extension_request_conflict")
    need(record["state"] == "applied", "extension_journal_uncertain")
    return record["commit"]["response"]


def remove_block(engine, payload, *, fault=lambda _: None, original_digest=None, model_calls=0, reused_from=None):
    _block_commit_payload(payload, "remove_block", ("target_digest",))
    expected_digest = original_digest or request_digest(payload)
    need(expected_digest == payload["request_digest"], "extension_request_digest")
    with managed():
        replay = _replay_block_commit(engine, payload)
        if replay is not None:
            return replay
        recover(engine.storage, payload["book_id"])
        book, page, pages = _target(engine, payload)
        target = _owned_target(page, payload["block_id"])
        need(payload["target_digest"] == digest(target.model_dump(mode="json")), "extension_target_changed")
        page.blocks = [block for block in page.blocks if block.id != target.id]
        page.updated_at = time.time()
        engine.compiler._finalize_page_status(page)
        need(page.status.value == "ready", "extension_page_not_ready")
        spine = engine.storage.load_spine(book.id)
        need(spine is not None, "extension_spine")
        response = {"ok": True, "blockId": target.id, "book_revision": book.revision + 1}
        return _commit_page(engine, payload, book, spine, pages, page, response, fault=fault,
                            model_calls=model_calls, reused_from=reused_from)


def regenerate_block(engine, payload, *, fault=lambda _: None, original_digest=None,
                     model_calls=0, reused_from=None):
    from .models import Block
    _block_commit_payload(payload, "regenerate_block", ("block", "target_digest"))
    expected_digest = original_digest or request_digest(payload)
    need(expected_digest == payload["request_digest"], "extension_request_digest")
    candidate = validate_blocks([payload["block"]])[0]
    with managed():
        replay = _replay_block_commit(engine, payload)
        if replay is not None:
            return replay
        recover(engine.storage, payload["book_id"])
        book, page, pages = _target(engine, payload)
        target = _owned_target(page, payload["block_id"])
        need(payload["target_digest"] == digest(target.model_dump(mode="json")), "extension_target_changed")
        need(candidate["id"] == target.id and candidate["type"] == target.type.value,
             "extension_regenerate_identity")
        data = target.model_dump(mode="json")
        for key in ("title", "params", "payload"):
            data[key] = deepcopy(candidate[key])
        data["source_anchors"] = deepcopy(candidate.get("source_anchors", []))
        data["status"] = "ready"
        data["error"] = ""
        data["metadata"] = {**(target.metadata or {}),
            "learning_extension_id": payload["extension_id"],
            "learning_extension_request": payload["request_id"],
            "learning_extension_operation": "regenerate_block",
            "ai_generated": True, "quality_review": "unreviewed",
            "learning_extension_supersedes": {"extensionId": target.metadata.get("learning_extension_id"),
                                               "requestId": target.metadata.get("learning_extension_request")}}
        replacement = Block.model_validate(data)
        page.blocks = [replacement if block.id == target.id else block for block in page.blocks]
        page.updated_at = time.time()
        engine.compiler._finalize_page_status(page)
        need(page.status.value == "ready", "extension_page_not_ready")
        spine = engine.storage.load_spine(book.id)
        need(spine is not None, "extension_spine")
        response = {"block": replacement.model_dump(mode="json"), "book_revision": book.revision + 1}
        return _commit_page(engine, payload, book, spine, pages, page, response, fault=fault,
                            model_calls=model_calls, reused_from=reused_from)


def lookup(engine, book_id, request_id):
    with managed():
        recover(engine.storage, book_id)
        path = _journal_path(engine.storage, book_id, request_id)
        if not path.is_file():
            return None
        record = decode_json(path.read_bytes())
        _verify(record, book_id)
        need(record["state"] == "applied", "extension_journal_uncertain")
        return record["commit"]["response"]


def evidence(engine, book_id):
    with managed():
        recover(engine.storage, book_id)
        book = engine.storage.load_book(book_id)
        need(book is not None, "extension_book_missing")
        commits = []
        for path in _journals(engine.storage, book_id):
            record = decode_json(path.read_bytes())
            _verify(record, book_id)
            need(record["state"] == "applied", "extension_journal_unstable")
            commits.append(record["commit"])
        commits.sort(key=lambda commit: commit["sequence"])
        head = _head(book)
        need(len(commits) == head["sequence"]
             and (not commits or commit_digest(commits[-1]) == head["commitDigest"]
                  and commits[-1]["afterContentDigest"] == head["afterContentDigest"]),
             "extension_chain_current")
        return {"schema": "learning-extension-evidence/1", "bookId": book_id,
                "head": head, "commits": commits}


def deep_dive(engine, payload, *, fault=lambda _: None, original_digest=None, model_calls=0, reused_from=None):
    from .models import Chapter, Page, PageLink, PageStatus
    expected = {"book_id", "parent_page_id", "block_id", "topic", "chapter_id", "page",
                "expected_revision", "request_id", "request_digest", "extension_id", "extension_binding"}
    need(type(payload) is dict and set(payload) in (expected, expected | {"custom_topic"}), "extension_fields")
    identifier(payload["request_id"], "requestId")
    identifier(payload["extension_id"], "extensionId")
    expected_digest = original_digest or request_digest(payload)
    need(expected_digest == payload["request_digest"], "extension_request_digest")
    payload = dict(payload, operation="deep_dive")
    need(type(payload["expected_revision"]) is int and payload["expected_revision"] >= 1,
         "extension_revision")
    validate_binding(payload["extension_binding"], operation="deep_dive")
    custom_topic = payload.get("custom_topic", False)
    need(type(custom_topic) is bool, "extension_fields")
    need(type(payload["topic"]) is str and payload["topic"].strip()
         and len(payload["topic"]) <= (160 if custom_topic else 500), "extension_topic")
    topic = payload["topic"].strip()
    candidate = payload["page"]
    need(type(candidate) is dict and set(candidate) == {"id", "title", "learning_objectives", "content_type", "blocks"},
         "extension_page_fields")
    blocks = validate_blocks(candidate["blocks"], max_count=8)
    need(all(block["type"] in ("section", "text", "callout") for block in blocks),
         "extension_deep_dive_block_type")
    with managed():
        path = _journal_path(engine.storage, payload["book_id"], payload["request_id"])
        if path.exists():
            record = decode_json(path.read_bytes())
            _verify(record, payload["book_id"])
            need(record["commit"]["requestDigest"] == payload["request_digest"], "extension_request_conflict")
            need(record["state"] == "applied", "extension_journal_uncertain")
            return record["commit"]["response"]
        recover(engine.storage, payload["book_id"])
        target = dict(payload)
        target["page_id"] = payload["parent_page_id"]
        book, parent, pages = _target(engine, target)
        spine = engine.storage.load_spine(book.id)
        need(spine is not None, "extension_spine")
        before_book = deepcopy(book)
        before_spine = deepcopy(spine)
        need(all(chapter.id != payload["chapter_id"] for chapter in spine.chapters)
             and all(page.id != candidate["id"] for page in pages), "extension_page_identity")
        block = parent.block_by_id(payload["block_id"])
        need(block is not None and block.type.value == "deep_dive", "extension_deep_dive_target")
        suggestions = block.payload.get("suggestions", [])
        need(custom_topic or any(item.get("topic") == topic for item in suggestions if isinstance(item, dict)),
             "extension_deep_dive_topic")
        pages_by_topic = dict(block.metadata.get("deep_dive_pages") or {})
        need(topic not in pages_by_topic, "extension_deep_dive_exists")
        block_ids, question_ids = _existing_identity(pages)
        for candidate_block in blocks:
            need(candidate_block["id"] not in block_ids, "extension_block_identity")
            if candidate_block["type"] == "quiz":
                need(all(question["question_id"] not in question_ids
                         for question in candidate_block["payload"]["questions"]), "extension_question_identity")
        chapter = Chapter(id=payload["chapter_id"], title=topic + " (deep dive)",
                          learning_objectives=[item for item in candidate["learning_objectives"] if isinstance(item, str)],
                          content_type=candidate["content_type"], summary="Sub-chapter spawned from " + parent.title,
                          order=len(spine.chapters), page_ids=[candidate["id"]])
        chapter.__pydantic_extra__ = {**(chapter.__pydantic_extra__ or {}), "deep_dive": True}
        child = Page(id=candidate["id"], book_id=book.id, chapter_id=chapter.id,
                     title=candidate["title"], learning_objectives=chapter.learning_objectives,
                     content_type=candidate["content_type"], status=PageStatus.READY, order=len(pages),
                     blocks=[_new_block(item, payload) for item in blocks], parent_page_id=parent.id)
        child.__pydantic_extra__ = {**(child.__pydantic_extra__ or {}),
            "learning_extension_id": payload["extension_id"], "optional_extension": True}
        spine.chapters.append(chapter)
        parent.links.append(PageLink(target_page_id=child.id, relation="deepens", label=topic))
        pages_by_topic[topic] = child.id
        block.metadata = {**(block.metadata or {}), "deep_dive_pages": pages_by_topic,
                          "deep_dive_page_id": block.metadata.get("deep_dive_page_id") or child.id}
        parent.updated_at = time.time()
        book.page_count = len(pages) + 1
        book.chapter_count = len(spine.chapters)
        response = {"page": child.model_dump(mode="json"), "book_revision": book.revision + 1}
        record = _commit(engine, payload, before_book, before_spine, pages, [parent, child], response, fault=fault,
                         after_book=book, after_spine=spine, model_calls=model_calls, reused_from=reused_from)
        previous_book = engine.storage.load_book(book.id)
        previous_parent = engine.storage.load_page(book.id, parent.id)
        record["beforeBook"] = _model(previous_book)
        record["beforeSpine"] = _model(before_spine)
        record["beforePages"] = [_model(previous_parent), None]
        _verify(record, book.id)
        atomic(path, ordered_bytes(record), immutable=True)
        fault("prepared")
        engine.storage.save_spine(spine)
        fault("spine")
        engine.storage.save_page(child)
        fault("child")
        engine.storage.save_page(parent)
        fault("parent")
        engine.storage.save_book(book)
        fault("book")
        need(_model(engine.storage.load_book(book.id)) == record["afterBook"]
             and _model(engine.storage.load_spine(book.id)) == record["afterSpine"]
             and [_model(engine.storage.load_page(book.id, page.id)) for page in (parent, child)]
             == record["afterPages"], "extension_commit")
        record["state"] = "applied"
        atomic(path, ordered_bytes(record))
        fault("applied")
        return response
