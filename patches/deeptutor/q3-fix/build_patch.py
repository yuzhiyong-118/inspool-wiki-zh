"""从已验 Q2 八模块派生三个 Q3 修复；不改旧发行物、清单或运行数据。"""
import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def sha(data): return hashlib.sha256(data).hexdigest()


def replace(text, before, after):
    if text.count(before) != 1: raise ValueError('固定源码接缝不唯一')
    return text.replace(before, after, 1)


def changes(source):
    result={}
    name='deeptutor/agents/question/pipeline.py'; text=(source/name).read_text(encoding='utf-8')
    text=replace(text,'        builtin_tool_whitelist: set[str] | None = None,\n',
        '        builtin_tool_whitelist: set[str] | None = None,\n        allow_tools: bool = True,\n')
    text=replace(text,'        self.builtin_tool_whitelist = builtin_tool_whitelist\n',
        '        self.builtin_tool_whitelist = builtin_tool_whitelist\n        self.allow_tools = allow_tools\n')
    text=replace(text,'        if not self.kb_name:\n            return\n',
        '        if not self.allow_tools or not self.kb_name:\n            return\n')
    text=replace(text,'    def _resolved_tools(self, context: UnifiedContext) -> list[str]:\n',
        '    def _resolved_tools(self, context: UnifiedContext) -> list[str]:\n        if not self.allow_tools:\n            return []\n')
    text=replace(text,'        too_many = None\n',
        '        if not self._pipeline.allow_tools:\n            raise PermissionError("tools_disabled_for_prepared_questions")\n        too_many = None\n')
    result[name]=text
    name='deeptutor/book/question_publication.py';text=(source/name).read_text(encoding='utf-8')
    result[name]=replace(text,"CAPABILITY = 'learning-question-publication/1'\n",
        "CAPABILITY = 'learning-question-publication/1'\nSAFETY_REVISION = 'learning-question-q3-fix/1'  # pinned with full install manifest\n")
    name='deeptutor/book/blocks/quiz.py';text=(source/name).read_text(encoding='utf-8')
    result[name]=replace(text,'                                    "builtin_tool_whitelist": set()}','                                    "builtin_tool_whitelist": set(), "allow_tools": False}')
    name='deeptutor/book/engine.py';text=(source/name).read_text(encoding='utf-8')
    result[name]=replace(text,'        from .kb_health import mark_drift_on_book\n\n        report = mark_drift_on_book(book_id, storage=self.storage)', '''        from .kb_health import mark_drift_on_book, detect_kb_drift, _scheme_changed
        from .question_publication import CAPABILITY

        book = self.storage.load_book(book_id)
        if book is not None and book.metadata.get("learning_question_controlled") == CAPABILITY:
            baseline = ("missing" if book.knowledge_bases and not book.kb_fingerprints else
                        "scheme_mismatch" if _scheme_changed(book.kb_fingerprints) else "available")
            try:
                value = detect_kb_drift(book, storage=self.storage).to_dict()
                value.update(read_only=True, baseline_status=baseline,
                    observation="unknown" if baseline != "available" else
                                "drift" if value["has_drift"] else "unchanged")
                return value
            except Exception:
                return {"book_id": book_id, "has_drift": False, "read_only": True,
                    "observation": "unknown", "baseline_status": baseline,
                    "diagnostic": "kb_observation_unavailable", "stale_page_ids": list(book.stale_page_ids)}
        report = mark_drift_on_book(book_id, storage=self.storage)''')
    result[name]=replace(result[name],'        """Compute and persist the current KB drift report for *book_id*."""',
        '        """Observe controlled books read-only; legacy books retain drift maintenance."""')
    name='deeptutor/services/llm/metrics.py';text=(source/name).read_text(encoding='utf-8')
    text=replace(text,'    def finish(self, response: Any = None, *, status: str = "completed") -> None:',
        '    def finish(self, response: Any = None, *, status: str = "completed", require_reported_usage: bool = False) -> None:')
    text=replace(text,'            self.runtime_guard.finish(self.call_id)',
        '            self.runtime_guard.finish(self.call_id, require_reported=require_reported_usage)')
    start=text.index('class MeasuredStream:'); end=text.index('\ndef instrument_client(',start)
    text=text[:start]+(HERE/'measured_stream.py').read_text(encoding='utf-8')+'\n\n'+text[end:]
    text=replace(text,'            meter.finish(status="failed")\n',
        '            meter.finish(status="failed", require_reported_usage=bool(kwargs.get("stream")))\n')
    result[name]=text
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True,type=Path)
    args=parser.parse_args();source=args.source.resolve(strict=True)
    accepted=json.loads((REPO/'docs/design/evidence/learning-question-q2/release.json').read_text(encoding='utf-8'))
    for name,expected in accepted['installedFiles'].items():
        if sha((source/name).read_bytes())!=expected: raise ValueError('Q2 实际字节不符: '+name)
    patch=[];files={}
    for name,after in changes(source).items():
        before=(source/name).read_text(encoding='utf-8');ast.parse(after)
        files[name]={'before':sha(before.encode()),'after':sha(after.encode())}
        patch.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
    raw=''.join(patch).encode();(HERE/'question-runtime-fixes.patch').write_bytes(raw)
    parent=json.loads((HERE.parent/'q2/manifest.json').read_text(encoding='utf-8'))
    (HERE/'manifest.json').write_text(json.dumps({'baseCommit':parent['baseCommit'],
        'localPatchId':'learning-question-q3-fix/1','inherits':'../q2/manifest.json',
        'parentPatchSha256':parent['patchSha256'],'parentReleaseSha256':sha((REPO/'docs/design/evidence/learning-question-q2/release.json').read_bytes()),
        'patchSha256':sha(raw),'files':files,'inputWheels':{w['name']:w['outputSha256'] for w in accepted['wheels']}},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__': main()
