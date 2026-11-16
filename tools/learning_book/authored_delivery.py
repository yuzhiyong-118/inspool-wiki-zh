"""E1 作者正文交付共享契约；纯确定性摘要与计划，不生成正文。"""
from __future__ import annotations

from .contracts import DeliveryError, digest, sha256


CAPABILITY = "learning-authored-delivery/1"


def need(condition, code="author_binding"):
    if not condition:
        raise DeliveryError(code, "作者正文、整书计划或交付绑定不符", "conflict")


def fields(value, keys, code="author_fields"):
    need(type(value) is dict and set(value) == set(keys), code)


def request_digest(payload):
    value = {key: item for key, item in payload.items() if key != "request_digest"}
    return digest({"rule": "learning-authored-request/1", "payload": value})


def binding(activity_id, operation, preparation, corpus, *, body=None, plan=None):
    value = {"schema": "learning-authored-binding/1", "activityId": activity_id,
             "operation": operation, "preparationDigest": digest(preparation),
             "sourceDigest": digest(corpus["sources"])}
    if body is not None:
        need(type(body) is str and 0 < len(body.strip()) and len(body) <= 262144, "author_body")
        value["bodySha256"] = sha256(body.encode("utf-8"))
    if plan is not None:
        value["planDigest"] = digest(plan)
    return value


def content_plan(content, book_id):
    need(type(content) is dict and content.get("schema") == "book-content-read/1", "author_content_capability")
    book = content.get("book")
    need(type(book) is dict and book.get("id") == book_id, "author_content_book")
    pages = content.get("pages")
    need(type(pages) is list and pages, "author_content_empty")
    enumeration = content.get("pageEnumeration")
    need(type(enumeration) is dict and enumeration.get("mode") == "strict"
         and enumeration.get("errors") == []
         and enumeration.get("fileCount") == enumeration.get("returnedCount") == len(pages),
         "author_content_enumeration")
    spine = content.get("spine")
    need(type(spine) is dict and spine.get("book_id") == book_id
         and type(spine.get("chapters")) is list, "author_content_spine")
    chapter_pages = {}
    chapter_ids = []
    for chapter in spine["chapters"]:
        need(type(chapter) is dict and type(chapter.get("id")) is str
             and type(chapter.get("page_ids")) is list and bool(chapter["page_ids"])
             and all(type(page_id) is str and page_id for page_id in chapter["page_ids"]),
             "author_content_spine")
        chapter_ids.append(chapter["id"])
        for page_id in chapter["page_ids"]:
            need(page_id not in chapter_pages, "author_content_spine")
            chapter_pages[page_id] = chapter["id"]
    need(len(set(chapter_ids)) == len(chapter_ids) and chapter_pages
         and book.get("page_count") == len(pages) == len(chapter_pages)
         and book.get("chapter_count") == len(chapter_ids), "author_content_spine")
    result = []
    for page in pages:
        need(type(page) is dict and page.get("book_id") == book_id and type(page.get("id")) is str
             and chapter_pages.get(page["id"]) == page.get("chapter_id"), "author_content_page")
        blocks = page.get("blocks")
        need(type(blocks) is list and blocks, "author_content_empty")
        rows = []
        for block in blocks:
            need(type(block) is dict and type(block.get("id")) is str and type(block.get("type")) is str
                 and type(block.get("payload")) is dict, "author_content_block")
            rows.append({"blockId": block["id"], "type": block["type"],
                         "payloadDigest": digest(block["payload"])})
        need(len({row["blockId"] for row in rows}) == len(rows), "author_content_block")
        result.append({"pageId": page["id"], "blocks": rows})
    need(len({page["pageId"] for page in result}) == len(result)
         and {page["pageId"] for page in result} == set(chapter_pages), "author_content_page")
    for page in pages:
        refs = [link.get("target_page_id") for link in page.get("links", []) if type(link) is dict]
        if page.get("parent_page_id"):
            refs.append(page["parent_page_id"])
        need(all(ref in chapter_pages for ref in refs), "author_content_reference")
    return {"schema": "learning-authored-book-plan/1", "bookId": book_id, "pages": result}
