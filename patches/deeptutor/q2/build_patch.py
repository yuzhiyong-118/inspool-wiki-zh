"""维护用：从固定 closeout 模块生成 Q2 增量补丁，不修改输入。"""
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path


def sha(data): return hashlib.sha256(data).hexdigest()


def changed(source):
    result = {}
    name = 'deeptutor/book/storage.py'
    text = (source / name).read_text(encoding='utf-8')
    tree = ast.parse(text); lines = text.splitlines(True)
    inserts = []
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BookStorage')
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef): continue
        args = {a.arg for a in method.args.args}
        expr = ('book_id' if 'book_id' in args else 'book.id' if 'book' in args else
                'page.book_id' if 'page' in args else 'spine.book_id' if 'spine' in args else
                'progress.book_id' if 'progress' in args else None)
        if expr is None or not method.name.startswith(('load_', 'save_', 'delete_', 'list_pages')): continue
        node = method.body[0]
        line = node.end_lineno if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str) else node.lineno - 1
        candidate = ', candidate=book' if method.name == 'save_book' else ''
        inserts.append((line, '        from .question_publication import storage_barrier\n'
                        f'        storage_barrier(self, {expr}, {method.name!r}{candidate})\n'))
    for line, extra in sorted(inserts, reverse=True): lines.insert(line, extra)
    result[name] = ''.join(lines)
    name = 'deeptutor/api/routers/book.py'
    text = (source / name).read_text(encoding='utf-8')
    text = text.replace('action not in {"pause", "resume"}',
                        'action not in {"pause", "resume", "pause_book", "resume_book"}')
    needle = '    book = resolved.engine.load_book(book_id)\n'
    pos = text.index(needle, text.index('def _claim_content_mutation('))
    text = text[:pos] + '''    from deeptutor.book.question_publication import native_barrier
    from tools.learning_book.contracts import DeliveryError
    try:
        native_barrier(resolved.engine.storage, book_id, action)
    except DeliveryError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
''' + text[pos:]
    # Managed variants reuse the existing HTTP operation, but never its unsafe
    # in-place generation branch. Native legacy calls remain unchanged for old books.
    needle = 'class RegenerateBlockRequest(BaseModel):\n'
    text = text.replace(needle, needle + '    model_config = {"extra": "forbid"}\n    question_binding: dict[str, Any] | None = None\n    request_id: str | None = None\n    request_digest: str | None = None\n', 1)
    pos = text.index('    resolved = ', text.index('async def regenerate_block('))
    text = text[:pos] + '''    if req.question_binding is not None:
        resolved = _resolve_book_or_404(req.book_id, edit=True)
        from tools.learning_book.contracts import DeliveryError
        try:
            if resolved.is_shared:
                raise HTTPException(status_code=409, detail={"code": "question_own_book_required"})
            result = await resolved.engine.prepare_question_variant(req.model_dump(exclude_none=True))
            from deeptutor.book.event_hub import get_book_stream
            await get_book_stream(req.book_id).book_event("block_ready", {"book_id": req.book_id,
                "page_id": req.page_id, "block": result["block"], "request_id": req.request_id})
            return result
        except DeliveryError as exc:
            status = 503 if exc.code in ("question_journal_uncertain", "question_commit") else 409
            raise HTTPException(status_code=status, detail={"code": exc.code}) from exc
''' + text[pos:]
    text += '''

class PublishQuizRequest(BaseModel):
    model_config = {"extra": "forbid", "strict": True}
    book_id: str = Field(min_length=1, max_length=180)
    page_id: str = Field(min_length=1, max_length=180)
    block_id: str = Field(min_length=1, max_length=180)
    expected_revision: int = Field(ge=1)
    request_id: str = Field(min_length=1, max_length=180)
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    questions: list[dict[str, Any]] = Field(min_length=1, max_length=8)
    question_binding: dict[str, Any]


@router.get("/books/{book_id}/question-capability")
async def question_capability(book_id: str):
    resolved = _resolve_book_or_404(book_id, edit=True)
    if resolved.is_shared:
        raise HTTPException(status_code=409, detail={"code": "question_own_book_required"})
    from deeptutor.book.question_publication import CAPABILITY
    import deeptutor.book.question_publication as implementation
    from pathlib import Path
    from tools.learning_book.contracts import sha256
    return {"schema": CAPABILITY, "bookId": book_id, "singleWorker": True,
            "implementationSha256": sha256(Path(implementation.__file__).read_bytes()),
            "snapshotVersions": [1, 2], "handoffVersions": [1, 2]}


@router.post("/books/publish-quiz")
async def publish_quiz(req: PublishQuizRequest):
    resolved = _resolve_book_or_404(req.book_id, edit=True)
    from tools.learning_book.contracts import DeliveryError
    try:
        if resolved.is_shared:
            raise HTTPException(status_code=409, detail={"code": "question_own_book_required"})
        result = resolved.engine.publish_quiz(req.model_dump())
        from deeptutor.book.event_hub import get_book_stream
        await get_book_stream(req.book_id).book_event("block_ready", {"book_id": req.book_id,
            "page_id": req.page_id, "block": result["block"], "request_id": req.request_id})
        return result
    except DeliveryError as exc:
        status = 503 if exc.code in ("question_journal_uncertain", "question_commit") else 409
        raise HTTPException(status_code=status, detail={"code": exc.code}) from exc


@router.get("/books/quiz-publications/{request_id}")
async def quiz_publication(request_id: str, book_id: str = Query(...)):
    resolved = _resolve_book_or_404(book_id, edit=True)
    from deeptutor.book.question_publication import lookup
    from tools.learning_book.contracts import DeliveryError
    try:
        value = lookup(resolved.engine, book_id, request_id)
    except DeliveryError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Publication not found")
    return value
'''
    result[name] = text
    needle = '    return await asyncio.to_thread(_read)\n'
    pos = text.index(needle, text.index('async def get_book_content('))
    text = text[:pos] + '''    try:
        return await asyncio.to_thread(_read)
    except Exception as exc:
        from tools.learning_book.contracts import DeliveryError
        if isinstance(exc, DeliveryError):
            raise HTTPException(status_code=409, detail={"code": exc.code}) from exc
        raise
''' + text[pos + len(needle):]
    result[name] = text
    name = 'deeptutor/book/engine.py'
    text = (source / name).read_text(encoding='utf-8')
    needle = '            book = self.storage.load_book(book_id)\n            if book is not None:\n                books.append(book)'
    replacement = '''            try:
                book = self.storage.load_book(book_id)
            except Exception as exc:
                from tools.learning_book.contracts import DeliveryError
                if not isinstance(exc, DeliveryError) or exc.code != "question_journal_unstable":
                    raise
                from .question_publication import unstable_summary
                book = unstable_summary(self.storage, book_id)
            if book is not None:
                books.append(book)'''
    if text.count(needle) != 1: raise ValueError('list_books seam mismatch')
    text = text.replace(needle, replacement, 1)
    pos = text.index('\n', text.index('class BookEngine:')) + 1
    # Insert before the first method but after the class docstring.
    cls = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == 'BookEngine')
    node = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    pos = sum(len(line) for line in text.splitlines(True)[:min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1])
    text = text[:pos] + '''    def publish_quiz(self, payload):
        from .question_publication import publish
        return publish(self, payload)

    async def prepare_question_variant(self, payload):
        from .question_publication import generate_variant
        return await generate_variant(self, payload)

''' + text[pos:]
    result[name] = text
    result['deeptutor/book/question_publication.py'] = (Path(__file__).parent / 'question_publication.py').read_text(encoding='utf-8')
    # The legacy wheel predates the verified closeout installed generation
    # marker fix. Carry the verified file into the derived wheel explicitly.
    result['deeptutor/book/generation.py'] = (source/'deeptutor/book/generation.py').read_text(encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args(); here = Path(__file__).parent
    inherited = json.loads((here.parent / 'closeout/manifest.json').read_text(encoding='utf-8'))
    for name in ('deeptutor/book/engine.py', 'deeptutor/book/storage.py', 'deeptutor/api/routers/book.py', 'deeptutor/book/generation.py'):
        if sha((args.source / name).read_bytes().replace(b'\r\n', b'\n')) != inherited['sourceFiles'][name]['after']:
            raise SystemExit('closeout base mismatch: ' + name)
    patch, files = [], {}
    for name, new in changed(args.source).items():
        before = (args.source / name).read_text(encoding='utf-8') if (args.source / name).exists() else ''
        ast.parse(new)
        patch.extend(difflib.unified_diff(before.splitlines(True), new.splitlines(True),
                     fromfile='a/' + name if before else '/dev/null', tofile='b/' + name))
        files[name] = {'before': sha(before.encode()) if before else None, 'after': sha(new.encode())}
    data = ''.join(patch).encode('utf-8'); (here / 'question-publication.patch').write_bytes(data)
    inherited_files = {name:sha((args.source/name).read_bytes().replace(b'\r\n',b'\n')) for name in (
        'deeptutor/services/llm/metrics.py', 'deeptutor/book/blocks/quiz.py',
        'deeptutor/book/learning_state_read.py', 'deeptutor/agents/question/pipeline.py')}
    if inherited_files['deeptutor/services/llm/metrics.py'] != inherited['sourceFiles']['deeptutor/services/llm/metrics.py']['after']:
        raise SystemExit('closeout metrics base mismatch')
    (here / 'manifest.json').write_text(json.dumps({'baseCommit': inherited['baseCommit'],
        'inherits': '../closeout/manifest.json', 'localPatchId': 'learning-question-q2/1',
        'patchSha256': sha(data), 'files': files, 'inheritedFiles':inherited_files,
        'baseBooksWheelSha256':'9891fc9fe48d4989a8341c169172e2901214bd8a4293167e8bd1bb8891a31bd0',
        'wheelBaseOverrides':{
            'deeptutor/book/engine.py':'8225321b36ff2221e02e857d83b1fb6bc4fee1ef5edf5e13905c9842c9433b70',
            'deeptutor/api/routers/book.py':'c9d14eb133b5125a2fbfb77bd7e15b1b694a2d0675f7ed6964f8094afd86ac5b',
            'deeptutor/book/generation.py':'6d939a5cf99515c7d706f5114381a6fbbd6c79199f1bb8db9c115b27a376641a'},
        'baseDifference':'closeout wheel lacks installed generation overview and previousOperationId/retryOf distinction; router has CRCRLF and pause_book names. Q2 retains verified installed lifecycle fixes and supports both pause action spellings.'}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__': main()
