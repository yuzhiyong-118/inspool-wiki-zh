import asyncio
import os
from pathlib import Path
import tempfile
import unittest


class EditorialBridge(unittest.TestCase):
    def test_body_edit_clears_generated_transition_title_edit_retains_it(self):
        with tempfile.TemporaryDirectory(prefix="editorial-bridge-") as temp:
            os.environ["DEEPTUTOR_HOME"] = temp
            from deeptutor.book.engine import BookEngine
            from deeptutor.book.storage import BookStorage
            from deeptutor.book.models import Book, Page, Block
            from deeptutor.services.path_service import PathService
            storage = BookStorage(path_service=PathService(Path(temp)))
            storage.save_book(Book(id="bk_edit", status="ready"))
            storage.save_page(Page(id="pg_edit", book_id="bk_edit", status="ready", blocks=[
                Block(id="blk_edit", type="text", status="ready",
                      payload={"body": "old", "bridge_text": "See the removed figure."})
            ]))
            engine = BookEngine(storage=storage)
            asyncio.run(engine.update_block(book_id="bk_edit", page_id="pg_edit",
                                           block_id="blk_edit", title="new"))
            self.assertIn("bridge_text", storage.load_page("bk_edit", "pg_edit").blocks[0].payload)
            asyncio.run(engine.update_block(book_id="bk_edit", page_id="pg_edit",
                                           block_id="blk_edit", body="reviewed"))
            block = storage.load_page("bk_edit", "pg_edit").blocks[0]
            self.assertNotIn("bridge_text", block.payload)
            self.assertEqual(block.payload["body"], "reviewed")
            self.assertTrue(block.metadata["edited_by_user"])


if __name__ == "__main__":
    unittest.main()
