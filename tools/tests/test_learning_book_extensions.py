"""学习扩展共享契约与内容链的纯确定性检查。"""
from copy import deepcopy
import unittest

from tools.learning_book.content import project
from tools.learning_book.contracts import DeliveryError, digest
from tools.learning_book.extensions import (apply_change, baseline_anchor, binding, commit_digest,
    protected_digest, protected_from_models, protected_from_projection, request_digest,
    validate_binding, validate_blocks, verify_chain)


def source_projection(book, spine, pages):
    raw = {"schema": "book-content-read/1", "book": book, "spine": spine, "pages": pages,
           "generation": {"working": False, "status": "ready"},
           "pageEnumeration": {"mode": "strict", "errors": [], "fileCount": len(pages), "returnedCount": len(pages)}}
    return project(raw, book["id"])[0]


def commit(book_id, sequence, before, after, previous, revision, bind):
    value = {"schema": "learning-extension-write/1", "bookId": book_id,
             "requestId": f"request-{sequence}", "requestDigest": digest(sequence),
             "extensionId": f"extension-{sequence}", "sequence": sequence,
             "previousCommitDigest": previous, "beforeContentDigest": digest(before),
             "afterContentDigest": digest(after), "beforeRevision": revision[0], "afterRevision": revision[1],
             "operation": "append_blocks", "binding": bind, "change": after,
             "response": {"book_revision": revision[1]}}
    return value


class ExtensionContractTests(unittest.TestCase):
    def setUp(self):
        self.book = {"id": "bk_1", "revision": 11, "status": "ready", "page_count": 1,
                     "chapter_count": 1, "metadata": {"learning_question_controlled": "q3"},
                     "created_at": 1, "updated_at": 1}
        self.spine = {"book_id": "bk_1", "version": 1, "updated_at": 1,
                      "chapters": [{"id": "ch_1", "page_ids": ["pg_1"]}]}
        self.pages = [{"id": "pg_1", "book_id": "bk_1", "chapter_id": "ch_1", "order": 0,
                       "status": "ready", "created_at": 1, "updated_at": 1,
                       "blocks": [{"id": "txt_1", "type": "text", "status": "ready", "created_at": 1,
                                   "updated_at": 1, "payload": {"body": "原文", "format": "markdown"}}]}]
        self.bind = binding("activity", "append_blocks", {"checked": True},
                            {"sources": [{"sourceId": "s1", "sourceVersionId": "v1", "sha256": digest("s1")}]})
        self.pages[0]["blocks"].append({"id": "quiz_1", "type": "quiz", "status": "ready",
            "payload": {"questions": []}, "metadata": {"learning_question_binding": {
                "preparationDigest": self.bind["preparationDigest"],
                "sources": [{"sourceId": "s1", "sourceVersionId": "v1", "sha256": digest("s1")}]}}})
        self.base = source_projection(self.book, self.spine, self.pages)

    def test_01_binding_requires_explicit_unreviewed_and_activity(self):
        self.assertEqual(validate_binding(self.bind, operation="append_blocks", require_activity=True)["qualityReview"],
                         "unreviewed")
        local = binding(None, "append_blocks", {"checked": True}, {"sources": []}, local_book=True)
        self.assertIsNone(validate_binding(local)["activityId"])
        with self.assertRaises(DeliveryError):
            validate_binding(local, require_activity=True)
        changed = deepcopy(self.bind)
        changed["qualityReview"] = "reviewed"
        with self.assertRaises(DeliveryError):
            validate_binding(changed)

    def test_02_block_validation_is_typed_and_bounded(self):
        text = {"id": "blk_new", "type": "text", "title": "", "params": {},
                "payload": {"format": "markdown", "body": "补充"}}
        self.assertEqual(validate_blocks([text])[0]["id"], "blk_new")
        for payload in ({"format": "markdown", "body": "  "},
                        {"format": "markdown", "body": "正文", "content": "后备字段"}):
            invalid = deepcopy(text)
            invalid["payload"] = payload
            with self.assertRaises(DeliveryError):
                validate_blocks([invalid])
        section = {"id": "blk_section", "type": "section", "title": "", "params": {},
                   "payload": {"format": "section", "intro": "引言", "key_takeaway": "结论",
                               "focus": "主题", "role": "core", "subsections": [
                                   {"heading": "小节", "role": "core", "focus": "细节", "body": "正文",
                                    "target_words": 100}]}}
        self.assertEqual(validate_blocks([section])[0]["type"], "section")
        empty_section = deepcopy(section)
        empty_section["payload"]["intro"] = ""
        empty_section["payload"]["key_takeaway"] = ""
        empty_section["payload"]["subsections"] = []
        with self.assertRaises(DeliveryError):
            validate_blocks([empty_section])
        unknown = deepcopy(text)
        unknown["type"] = "interactive"
        with self.assertRaises(DeliveryError):
            validate_blocks([unknown])

    def test_03_notes_and_revision_do_not_change_protected_digest(self):
        before = protected_digest(self.base)
        book = deepcopy(self.book)
        book["revision"] = 99
        book["metadata"]["learning_extension_head"] = {"sequence": 4}
        pages = deepcopy(self.pages)
        pages[0]["blocks"].append({"id": "note_1", "type": "user_note", "status": "ready",
            "payload": {"body": "个人笔记", "format": "markdown", "author": "user"}})
        current = source_projection(book, self.spine, pages)
        self.assertEqual(protected_digest(current), before)

    def test_04_chain_replays_with_revision_gaps_and_physical_reordering(self):
        first_after = protected_from_models(self.book, self.spine, self.pages)
        new_page = deepcopy(self.pages[0])
        new_page["blocks"].append({"id": "blk_new", "type": "text", "status": "ready",
                                   "title": "", "params": {},
                                   "payload": {"format": "markdown", "body": "补充"},
                                   "metadata": {"learning_extension_id": "extension-1",
                                                "quality_review": "unreviewed", "ai_generated": True}})
        first_after = protected_from_models(self.book, self.spine, new_page and [new_page])
        before = protected_from_projection(self.base)
        first = commit("bk_1", 1, before, first_after, baseline_anchor("bk_1", digest(before)), (11, 12), self.bind)
        second_page = deepcopy(new_page)
        second_page["blocks"].append({"id": "blk_new_2", "type": "callout", "status": "ready",
                                      "title": "", "params": {},
                                      "payload": {"format": "markdown", "body": "提示"},
                                      "metadata": {"learning_extension_id": "extension-2",
                                                   "quality_review": "unreviewed", "ai_generated": True}})
        second_after = protected_from_models(self.book, self.spine, [second_page])
        second = commit("bk_1", 2, first_after, second_after, commit_digest(first), (20, 21), self.bind)
        current = apply_change(apply_change(before, first["change"]), second["change"])
        result = verify_chain(self.base, current, [second, first], book_id="bk_1")
        self.assertEqual(result["commitCount"], 2)
        self.assertEqual(result["status"], "extension_consistent")

    def test_05_missing_fork_predecessor_and_tampering_fail(self):
        changed_page = deepcopy(self.pages[0])
        changed_page["blocks"].append({"id": "blk_new", "type": "text", "status": "ready",
                                       "title": "", "params": {},
                                   "payload": {"format": "markdown", "body": "补充"},
                                       "metadata": {"learning_extension_id": "extension-1",
                                                    "quality_review": "unreviewed", "ai_generated": True}})
        after = protected_from_models(self.book, self.spine, [changed_page])
        before = protected_from_projection(self.base)
        first = commit("bk_1", 1, before, after, baseline_anchor("bk_1", digest(before)), (11, 12), self.bind)
        for label, mutate, code in (
            ("sequence", lambda value: value.update(sequence=2), "extension_chain_sequence"),
            ("predecessor", lambda value: value.update(previousCommitDigest=digest("wrong")),
             "extension_chain_predecessor"),
            ("content", lambda value: value["change"]["pages"][0]["blocks"][0]["payload"].update(body="篡改"),
             "extension_protected_block_changed"),
        ):
            with self.subTest(label=label):
                invalid = deepcopy(first)
                mutate(invalid)
                with self.assertRaises(DeliveryError) as caught:
                    verify_chain(self.base, after, [invalid], book_id="bk_1")
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(DeliveryError):
            verify_chain(self.base, after, [], book_id="bk_1")

    def test_06_capacity_is_explicit_not_truncated(self):
        with self.assertRaises(DeliveryError) as caught:
            verify_chain(self.base, self.base, [{}], book_id="bk_1", max_commits=0)
        self.assertEqual(caught.exception.code, "extension_chain_capacity")

    def test_07_request_digest_covers_semantics(self):
        payload = {"book_id": "bk_1", "request_id": "r1", "operation": "append_blocks"}
        value = request_digest(payload)
        payload["request_digest"] = value
        self.assertEqual(request_digest(payload), value)
        payload["operation"] = "deep_dive"
        self.assertNotEqual(request_digest(payload), value)

    def test_08_scoped_llm_budget_stops_before_extra_provider_call(self):
        import asyncio
        from unittest.mock import AsyncMock
        from deeptutor.book.blocks._llm_writer import extension_call_budget
        from deeptutor.services.llm.metrics import measure_provider_call
        from deeptutor.services.llm.provider_core.base import LLMResponse
        async def scenario():
            provider = AsyncMock(return_value=LLMResponse(content="ok", finish_reason="stop"))
            with extension_call_budget(1):
                await measure_provider_call(provider)
                with self.assertRaises(DeliveryError) as caught:
                    await measure_provider_call(provider)
                self.assertEqual(caught.exception.code, "extension_generation_budget")
            self.assertEqual(provider.await_count, 1)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
