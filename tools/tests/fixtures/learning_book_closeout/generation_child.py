"""独立测试进程在指定提交点等待被父测试终止。"""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

from deeptutor.book.generation import track_generation
from deeptutor.book.storage import BookStorage
from deeptutor.services.path_service import PathService

root=Path(sys.argv[1]);point=sys.argv[2]
host=SimpleNamespace(storage=BookStorage(path_service=PathService(workspace_root=root)))

async def pause(name):
    if point==name:
        (root/'checkpoint').write_text(name)
        await asyncio.Event().wait()

@track_generation
async def operation(self,*,book_id,page_id):
    await pause('accepted')
    page=self.storage.load_page(book_id,page_id)
    page.blocks[0].payload={'answer':'working'}
    self.storage.save_page(page)
    await pause('generating')
    page.blocks[0].payload={'answer':'complete-new'}
    self.storage.save_page(page)
    await pause('before_commit')
    return page

async def main():
    await operation(host,book_id='b',page_id='p')
    await pause('after_commit')

asyncio.run(main())
