"""受控学习扩展的共享契约、受保护内容投影与有界链核验。"""
from __future__ import annotations

from copy import deepcopy

from .content import REMOVED, project
from .contracts import DeliveryError, canonical, content_hash, digest, identifier
from .question_spec import question_content, question_digest

CAPABILITY = "learning-controlled-extension/1"
BINDING = "learning-extension-binding/1"
JOURNAL = "learning-extension-write/1"
QUALITY_UNREVIEWED = "unreviewed"
MAX_COMMITS = 1024
MAX_CHAIN_BYTES = 32 * 1024 * 1024
MAX_BLOCKS = 3


def need(condition, code="extension_contract"):
    if not condition:
        raise DeliveryError(code, "学习扩展请求、提交或内容链不符", "conflict")


def fields(value, keys, code="extension_fields"):
    need(type(value) is dict and set(value) == set(keys), code)


def request_digest(payload):
    value = deepcopy(payload)
    value.pop("request_digest", None)
    return digest({"rule": "learning-extension-request/1", "payload": value})


def binding(activity_id, operation, preparation, corpus, *, local_book=False):
    need(type(corpus.get("sources")) is list
         and all(type(source) is dict and all(key in source for key in ("sourceId", "sourceVersionId", "sha256"))
                 for source in corpus["sources"]), "extension_sources")
    return {
        "schema": BINDING,
        "activityBinding": "book_local" if local_book else "activity",
        "activityId": None if local_book else activity_id,
        "operation": operation,
        "preparationDigest": digest(preparation),
        "sourceDigest": digest([{key: source[key] for key in ("sourceId", "sourceVersionId", "sha256")}
                                for source in corpus["sources"]]),
        "qualityReview": QUALITY_UNREVIEWED,
    }


def validate_binding(value, *, operation=None, require_activity=False):
    fields(value, ("schema", "activityBinding", "activityId", "operation", "preparationDigest",
                   "sourceDigest", "qualityReview"), "extension_binding")
    need(value["schema"] == BINDING and value["activityBinding"] in ("activity", "book_local")
         and value["qualityReview"] == QUALITY_UNREVIEWED, "extension_binding")
    if value["activityBinding"] == "activity" or require_activity:
        need(value["activityBinding"] == "activity", "extension_activity_required")
        identifier(value["activityId"], "activityId")
    else:
        need(value["activityId"] is None, "extension_binding")
    need(value["operation"] in ("append_blocks", "supplement", "deep_dive", "remove_block", "regenerate_block")
         and (operation is None or value["operation"] == operation), "extension_operation")
    content_hash(value["preparationDigest"])
    content_hash(value["sourceDigest"])
    return deepcopy(value)


def _block_shape(block):
    required = {"id", "type", "title", "params", "payload"}
    need(type(block) is dict and required <= set(block)
         and set(block) <= required | {"source_anchors"}, "extension_block_fields")
    identifier(block["id"], "blockId")
    need(type(block["title"]) is str and len(block["title"]) <= 4000
         and type(block["params"]) is dict and type(block["payload"]) is dict, "extension_block_fields")
    anchors = block.get("source_anchors", [])
    need(type(anchors) is list and len(anchors) <= 16, "extension_source_anchors")
    for anchor in anchors:
        fields(anchor, ("kind", "kb_name", "ref", "snippet"), "extension_source_anchors")
        need(all(type(anchor[key]) is str and len(anchor[key]) <= 32768 for key in anchor),
             "extension_source_anchors")
    kind = block["type"]
    payload = block["payload"]
    if kind == "text":
        need(set(payload) in ({"format", "body"}, {"format", "body", "role"}), "extension_content")
        need(payload["format"] == "markdown" and type(payload["body"]) is str
             and bool(payload["body"].strip()) and len(payload["body"]) <= 262144
             and ("role" not in payload or type(payload["role"]) is str and len(payload["role"]) <= 1000),
             "extension_content")
    elif kind == "callout":
        need(set(payload) in ({"format", "body"}, {"format", "variant", "label", "body"}),
             "extension_content")
        need(payload["format"] == "markdown" and type(payload["body"]) is str
             and bool(payload["body"].strip()) and len(payload["body"]) <= 262144
             and ("variant" not in payload or type(payload["variant"]) is str and payload["variant"].strip())
             and ("label" not in payload or type(payload["label"]) is str and len(payload["label"]) <= 4000),
             "extension_content")
    elif kind == "section":
        fields(payload, ("format", "intro", "subsections", "key_takeaway", "focus", "role"), "extension_content")
        need(payload["format"] == "section" and type(payload["intro"]) is str
             and type(payload["key_takeaway"]) is str and type(payload["focus"]) is str
             and type(payload["role"]) is str and type(payload["subsections"]) is list
             and len(payload["subsections"]) <= 8, "extension_content")
        need(all(len(value) <= 32768 for value in (payload["intro"], payload["key_takeaway"])), "extension_content")
        meaningful = bool(payload["intro"].strip() or payload["key_takeaway"].strip())
        for subsection in payload["subsections"]:
            fields(subsection, ("heading", "role", "focus", "body", "target_words"), "extension_content")
            need(all(type(subsection[key]) is str for key in ("heading", "role", "focus", "body"))
                 and type(subsection["target_words"]) in (int, float)
                 and len(subsection["body"]) <= 32768, "extension_content")
            meaningful = meaningful or bool(subsection["body"].strip())
        need(meaningful, "extension_content")
    elif kind == "deep_dive":
        fields(payload, ("suggestions",), "extension_content")
        suggestions = payload["suggestions"]
        need(type(suggestions) is list and 1 <= len(suggestions) <= 4, "extension_content")
        for suggestion in suggestions:
            fields(suggestion, ("topic", "rationale"), "extension_content")
            need(all(type(suggestion[key]) is str and suggestion[key].strip()
                     for key in ("topic", "rationale")), "extension_content")
    elif kind == "quiz":
        need(set(payload) in ({"questions"}, {"questions", "topic"}), "extension_content")
        need("topic" not in payload or type(payload["topic"]) is str and len(payload["topic"]) <= 32768,
             "extension_content")
        questions = payload["questions"]
        need(type(questions) is list and 1 <= len(questions) <= 3, "extension_question_count")
        for question in questions:
            question_content(question, authored=False)
            identifier(question["question_id"], "questionId")
        need(len({q["question_id"] for q in questions}) == len(questions), "extension_question_identity")
    else:
        need(False, "extension_block_unsupported")
    return deepcopy(block)


def validate_blocks(blocks, *, max_count=MAX_BLOCKS):
    need(type(max_count) is int and 1 <= max_count <= 8, "extension_block_count")
    need(type(blocks) is list and 1 <= len(blocks) <= max_count, "extension_block_count")
    result = [_block_shape(block) for block in blocks]
    need(len({block["id"] for block in result}) == len(result), "extension_block_identity")
    return result


def _remove(value, kind):
    for name in REMOVED[kind]:
        value.pop(name, None)


def _protected_book(book):
    result = deepcopy(book)
    _remove(result, "book")
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        _remove(metadata, "book.metadata")
        metadata.pop("learning_extension_head", None)
    return result


def _protected_spine(spine):
    result = deepcopy(spine)
    _remove(result, "spine")
    return result


def _protected_page(page):
    result = deepcopy(page)
    _remove(result, "page")
    blocks = []
    for block in result.get("blocks", []):
        if block.get("type") == "user_note":
            continue
        item = deepcopy(block)
        _remove(item, "block")
        blocks.append(item)
    result["blocks"] = blocks
    return result


def protected_from_models(book, spine, pages):
    pages = sorted((deepcopy(page) for page in pages), key=lambda page: (page.get("order", 0), page.get("id", "")))
    raw = {
        "schema": "book-content-read/1",
        "book": book,
        "spine": spine,
        "pages": pages,
        "generation": {"working": False, "status": "ready"},
        "pageEnumeration": {"mode": "strict", "errors": [], "fileCount": len(pages), "returnedCount": len(pages)},
    }
    projection, _, _ = project(raw, book["id"])
    return protected_from_projection(projection)


def protected_from_projection(projection):
    return {
        "rule": "learning-protected-content/1",
        "book": _protected_book(projection["book"]),
        "spine": _protected_spine(projection["spine"]),
        "pages": [_protected_page(page) for page in projection["pages"]],
    }


def protected_digest(projection):
    return digest(protected_from_projection(projection))


def baseline_anchor(book_id, content_digest):
    identifier(book_id, "bookId")
    content_hash(content_digest)
    return digest({"rule": "learning-extension-baseline/1", "bookId": book_id, "contentDigest": content_digest})


def change_digest(change):
    fields(change, ("rule", "book", "spine", "pages"), "extension_change")
    need(change["rule"] == "learning-protected-content/1", "extension_change")
    return digest(change)


def apply_change(projection, change):
    fields(change, ("rule", "book", "spine", "pages"), "extension_change")
    need(change["rule"] == "learning-protected-content/1", "extension_change")
    result = deepcopy(projection)
    result["rule"] = "learning-protected-content/1"
    need(change["book"] == _protected_book(change["book"])
         and change["spine"] == _protected_spine(change["spine"]), "extension_change_projection")
    need(change["book"]["id"] == result["book"]["id"]
         and change["spine"]["book_id"] == result["book"]["id"], "extension_change_identity")
    result["book"] = deepcopy(change["book"])
    result["spine"] = deepcopy(change["spine"])
    by_id = {page["id"]: page for page in result["pages"]}
    for page in change["pages"]:
        need(page == _protected_page(page) and page["book_id"] == result["book"]["id"],
             "extension_change_projection")
        by_id[page["id"]] = deepcopy(page)
    result["pages"] = sorted(by_id.values(), key=lambda page: (page.get("order", 0), page.get("id", "")))
    return result


def _subsequence(before, after):
    position = 0
    for item in after:
        if position < len(before) and item == before[position]:
            position += 1
    return position == len(before)


def _validate_new_blocks(before_page, after_page, commit, before_pages):
    before_blocks = before_page["blocks"]
    after_blocks = after_page["blocks"]
    need(_subsequence(before_blocks, after_blocks), "extension_protected_block_changed")
    old_ids = {block["id"] for block in before_blocks}
    old_questions = {question.get("question_id") for page in before_pages
                     for block in page.get("blocks", []) for question in block.get("payload", {}).get("questions", [])}
    new_blocks = [block for block in after_blocks if block["id"] not in old_ids]
    need(new_blocks, "extension_no_increment")
    candidates = [{key: deepcopy(block[key]) for key in ("id", "type", "title", "params", "payload", "source_anchors")
                   if key in block} for block in new_blocks]
    validate_blocks(candidates, max_count=8)
    for block in new_blocks:
        metadata = block.get("metadata", {})
        need(metadata.get("learning_extension_id") == commit["extensionId"]
             and metadata.get("quality_review") == QUALITY_UNREVIEWED
             and metadata.get("ai_generated") is True, "extension_block_binding")
        if block["type"] == "quiz":
            need(all(question["question_id"] not in old_questions
                     for question in block["payload"]["questions"]), "extension_question_identity")


def _validate_append(before, after, commit):
    need(after["book"] == before["book"] and after["spine"] == before["spine"]
         and {page["id"] for page in after["pages"]} == {page["id"] for page in before["pages"]},
         "extension_append_structure")
    before_pages = {page["id"]: page for page in before["pages"]}
    after_pages = {page["id"]: page for page in after["pages"]}
    changed = [page_id for page_id in before_pages if before_pages[page_id] != after_pages[page_id]]
    need(len(changed) == 1, "extension_append_target")
    page_id = changed[0]
    before_page, after_page = before_pages[page_id], after_pages[page_id]
    need({key: value for key, value in before_page.items() if key != "blocks"}
         == {key: value for key, value in after_page.items() if key != "blocks"},
         "extension_append_page_fields")
    _validate_new_blocks(before_page, after_page, commit, before["pages"])


def _validate_deep_dive(before, after, commit):
    before_pages = {page["id"]: page for page in before["pages"]}
    after_pages = {page["id"]: page for page in after["pages"]}
    new_ids = set(after_pages) - set(before_pages)
    need(len(new_ids) == 1 and set(before_pages) <= set(after_pages), "extension_deep_dive_page")
    child_id = new_ids.pop()
    child = after_pages[child_id]
    changed = [page_id for page_id in before_pages if before_pages[page_id] != after_pages[page_id]]
    need(len(changed) == 1, "extension_deep_dive_parent")
    parent_id = changed[0]
    need(child.get("parent_page_id") == parent_id and child.get("learning_extension_id") == commit["extensionId"]
         and child.get("optional_extension") is True and child.get("links", []) == []
         and child.get("order") == len(before_pages), "extension_deep_dive_child")
    _validate_new_blocks({"blocks": []}, child, commit, before["pages"])
    before_parent, after_parent = before_pages[parent_id], after_pages[parent_id]
    need({key: value for key, value in before_parent.items() if key not in ("blocks", "links")}
         == {key: value for key, value in after_parent.items() if key not in ("blocks", "links")},
         "extension_deep_dive_parent_fields")
    before_links = before_parent.get("links", [])
    after_links = after_parent.get("links", [])
    need(after_links[:len(before_links)] == before_links and len(after_links) == len(before_links) + 1,
         "extension_deep_dive_link")
    link = after_links[-1]
    need(link.get("target_page_id") == child_id and link.get("relation") == "deepens"
         and link.get("label") == child.get("title"), "extension_deep_dive_link")
    before_ids = [block["id"] for block in before_parent["blocks"]]
    after_ids = [block["id"] for block in after_parent["blocks"]]
    need(len(before_ids) == len(set(before_ids)) and len(after_ids) == len(set(after_ids))
         and before_ids == after_ids, "extension_deep_dive_parent_blocks")
    before_blocks = {block["id"]: block for block in before_parent["blocks"]}
    after_blocks = {block["id"]: block for block in after_parent["blocks"]}
    target = None
    for block_id, before_block in before_blocks.items():
        after_block = after_blocks[block_id]
        if before_block == after_block:
            continue
        need(before_block.get("type") == "deep_dive" and target is None, "extension_deep_dive_parent_blocks")
        target = block_id
        need({key: value for key, value in before_block.items() if key != "metadata"}
             == {key: value for key, value in after_block.items() if key != "metadata"},
             "extension_deep_dive_parent_blocks")
        before_meta = before_block.get("metadata", {})
        after_meta = after_block.get("metadata", {})
        expected_meta = deepcopy(before_meta)
        previous_mapping = before_meta.get("deep_dive_pages", {})
        need(type(previous_mapping) is dict and link["label"] not in previous_mapping,
             "extension_deep_dive_mapping")
        expected_meta["deep_dive_pages"] = {**previous_mapping, link["label"]: child_id}
        if not before_meta.get("deep_dive_page_id"):
            expected_meta["deep_dive_page_id"] = child_id
        need(after_meta == expected_meta, "extension_deep_dive_mapping")
    need(target is not None, "extension_deep_dive_parent_blocks")
    before_chapters = before["spine"].get("chapters", [])
    after_chapters = after["spine"].get("chapters", [])
    need(after_chapters[:len(before_chapters)] == before_chapters
         and len(after_chapters) == len(before_chapters) + 1, "extension_deep_dive_spine")
    chapter = after_chapters[-1]
    need(chapter.get("deep_dive") is True and chapter.get("page_ids") == [child_id]
         and child.get("chapter_id") == chapter.get("id")
         and chapter.get("title") == child.get("title", "") + " (deep dive)"
         and chapter.get("learning_objectives") == child.get("learning_objectives")
         and chapter.get("content_type") == child.get("content_type")
         and chapter.get("order") == len(before_chapters), "extension_deep_dive_spine")
    expected_book = deepcopy(before["book"])
    expected_book["page_count"] += 1
    expected_book["chapter_count"] += 1
    need(after["book"] == expected_book, "extension_deep_dive_counts")
    expected_spine = deepcopy(before["spine"])
    expected_spine["chapters"] = after_chapters
    need(after["spine"] == expected_spine, "extension_deep_dive_spine")


def _single_changed_page(before, after):
    need(after["book"] == before["book"] and after["spine"] == before["spine"]
         and {page["id"] for page in after["pages"]} == {page["id"] for page in before["pages"]},
         "extension_block_structure")
    before_pages = {page["id"]: page for page in before["pages"]}
    after_pages = {page["id"]: page for page in after["pages"]}
    changed = [page_id for page_id in before_pages if before_pages[page_id] != after_pages[page_id]]
    need(len(changed) == 1, "extension_block_target")
    page_id = changed[0]
    before_page, after_page = before_pages[page_id], after_pages[page_id]
    need({key: value for key, value in before_page.items() if key != "blocks"}
         == {key: value for key, value in after_page.items() if key != "blocks"},
         "extension_block_page_fields")
    return before_page, after_page


def _owned_block(block):
    metadata = block.get("metadata", {})
    need(type(metadata.get("learning_extension_id")) is str
         and metadata.get("quality_review") == QUALITY_UNREVIEWED
         and metadata.get("ai_generated") is True, "extension_block_not_owned")


def _validate_remove(before, after, commit):
    before_page, after_page = _single_changed_page(before, after)
    before_blocks = before_page["blocks"]
    after_blocks = after_page["blocks"]
    before_ids = [block["id"] for block in before_blocks]
    after_ids = [block["id"] for block in after_blocks]
    need(len(before_ids) == len(set(before_ids)) and len(after_ids) == len(set(after_ids))
         and len(after_blocks) == len(before_blocks) - 1, "extension_remove_blocks")
    removed = [block for block in before_blocks if block["id"] not in set(after_ids)]
    need(len(removed) == 1 and after_blocks == [block for block in before_blocks if block["id"] != removed[0]["id"]],
         "extension_remove_blocks")
    _owned_block(removed[0])
    need(removed[0].get("type") != "quiz", "extension_quiz_protected")


def _validate_regenerate(before, after, commit):
    before_page, after_page = _single_changed_page(before, after)
    before_blocks = before_page["blocks"]
    after_blocks = after_page["blocks"]
    need([block["id"] for block in before_blocks] == [block["id"] for block in after_blocks],
         "extension_regenerate_blocks")
    changed = [index for index, pair in enumerate(zip(before_blocks, after_blocks)) if pair[0] != pair[1]]
    need(len(changed) == 1, "extension_regenerate_target")
    before_block = before_blocks[changed[0]]
    after_block = after_blocks[changed[0]]
    _owned_block(before_block)
    need(before_block.get("type") != "quiz" and after_block.get("type") == before_block.get("type"),
         "extension_quiz_protected")
    mutable = {"title", "params", "payload", "source_anchors", "metadata"}
    need({key: value for key, value in before_block.items() if key not in mutable}
         == {key: value for key, value in after_block.items() if key not in mutable},
         "extension_regenerate_identity")
    candidate = {key: deepcopy(after_block[key]) for key in
                 ("id", "type", "title", "params", "payload", "source_anchors") if key in after_block}
    validate_blocks([candidate])
    before_meta = deepcopy(before_block.get("metadata", {}))
    expected_meta = {**before_meta, "learning_extension_id": commit["extensionId"],
                     "learning_extension_request": commit["requestId"],
                     "learning_extension_operation": "regenerate_block",
                     "ai_generated": True, "quality_review": QUALITY_UNREVIEWED,
                     "learning_extension_supersedes": {
                         "extensionId": before_meta.get("learning_extension_id"),
                         "requestId": before_meta.get("learning_extension_request")}}
    need(after_block.get("metadata", {}) == expected_meta, "extension_regenerate_binding")


def validate_operation(before, after, commit):
    need(after["rule"] == before["rule"] == "learning-protected-content/1", "extension_operation")
    if commit["operation"] in ("append_blocks", "supplement"):
        _validate_append(before, after, commit)
    elif commit["operation"] == "deep_dive":
        _validate_deep_dive(before, after, commit)
    elif commit["operation"] == "remove_block":
        _validate_remove(before, after, commit)
    elif commit["operation"] == "regenerate_block":
        _validate_regenerate(before, after, commit)
    else:
        need(False, "extension_operation")


def validate_sources(baseline, commits):
    identities = set()
    for page in baseline["pages"]:
        for block in page.get("blocks", []):
            binding = block.get("metadata", {}).get("learning_question_binding")
            if binding:
                identities.add((binding.get("preparationDigest"), digest(binding.get("sources"))))
    need(len(identities) == 1, "extension_source_binding")
    preparation, sources = identities.pop()
    for commit in commits:
        binding = commit["binding"]
        need(binding["preparationDigest"] == preparation and binding["sourceDigest"] == sources,
             "extension_source_binding")


def commit_digest(commit):
    fields(commit, ("schema", "bookId", "requestId", "requestDigest", "extensionId", "sequence",
                    "previousCommitDigest", "beforeContentDigest", "afterContentDigest", "beforeRevision",
                    "afterRevision", "operation", "binding", "change", "response"), "extension_commit")
    return digest(commit)


def validate_commit(commit, *, book_id=None):
    commit_digest(commit)
    need(commit["schema"] == JOURNAL and type(commit["sequence"]) is int and commit["sequence"] >= 1
         and type(commit["beforeRevision"]) is int and type(commit["afterRevision"]) is int
         and commit["afterRevision"] > commit["beforeRevision"], "extension_commit")
    for key in ("previousCommitDigest", "beforeContentDigest", "afterContentDigest", "requestDigest"):
        content_hash(commit[key])
    identifier(commit["requestId"], "requestId")
    identifier(commit["extensionId"], "extensionId")
    if book_id is not None:
        need(commit["bookId"] == book_id, "extension_book")
    validate_binding(commit["binding"], operation=commit["operation"])
    return commit


def verify_chain(baseline_projection, current_projection, commits, *, book_id,
                 max_commits=MAX_COMMITS, max_bytes=MAX_CHAIN_BYTES):
    need(type(commits) is list and len(commits) <= max_commits, "extension_chain_capacity")
    need(len(canonical(commits)) <= max_bytes, "extension_chain_capacity")
    ordered = sorted(commits, key=lambda commit: commit.get("sequence", 0) if isinstance(commit, dict) else 0)
    current = protected_from_projection(baseline_projection)
    expected = protected_from_projection(current_projection)
    if ordered:
        validate_sources(current, ordered)
    previous_digest = None
    for index, commit in enumerate(ordered, 1):
        validate_commit(commit, book_id=book_id)
        need(commit["sequence"] == index, "extension_chain_sequence")
        anchor = baseline_anchor(book_id, commit["beforeContentDigest"]) if index == 1 else previous_digest
        need(commit["previousCommitDigest"] == anchor, "extension_chain_predecessor")
        need(digest(current) == commit["beforeContentDigest"], "extension_chain_input")
        before_state = current
        current = apply_change(current, commit["change"])
        validate_operation(before_state, current, commit)
        need(digest(current) == commit["afterContentDigest"], "extension_chain_output")
        previous_digest = commit_digest(commit)
    need(current == expected, "extension_chain_current")
    return {
        "status": "extension_consistent" if ordered else "baseline_consistent",
        "commitCount": len(ordered),
        "headDigest": previous_digest,
        "contentDigest": digest(current),
        "qualityReview": "mixed_per_extension" if ordered else "baseline_reviewed",
        "limits": {"maxCommits": max_commits, "maxBytes": max_bytes},
    }


def question_introductions(baseline_projection, commits):
    current = protected_from_projection(baseline_projection)
    introduced = []
    seen = set()
    for commit in sorted(commits, key=lambda item: item["sequence"]):
        after = apply_change(current, commit["change"])
        def questions(projection):
            return {(page["id"], block["id"], question["question_id"]): (page, block, question)
                    for page in projection["pages"] for block in page.get("blocks", [])
                    if block.get("type") == "quiz"
                    for question in block.get("payload", {}).get("questions", [])}
        before_questions = questions(current)
        after_questions = questions(after)
        for key in sorted(set(after_questions) - set(before_questions)):
            need(key not in seen, "extension_question_identity")
            seen.add(key)
            page, block, question = after_questions[key]
            introduced.append({"pageId": page["id"], "blockId": block["id"], "questionId": key[2],
                               "value": deepcopy(question), "commitDigest": commit_digest(commit),
                               "qualityReview": commit["binding"]["qualityReview"]})
        current = after
    return introduced


def question_evidence(blocks):
    result = []
    for block in validate_blocks(blocks):
        if block["type"] != "quiz":
            continue
        for question in block["payload"]["questions"]:
            result.append({"blockId": block["id"], "questionId": question["question_id"],
                           "questionDigest": question_digest(question), "qualityReview": QUALITY_UNREVIEWED})
    return result
