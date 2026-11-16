"""显式知识内容范围：完整 wiki/raw、根规则及规则映射，不扫描运行环境。"""
from __future__ import annotations

import os
from pathlib import Path

from ..contracts import bytes_digest, digest
from ..gates.core import MAPPING_PATH
from ..isolation.gateway import _check_chain
from .preparation import LIMITS, _Reader, _need, _root
from .preview import _BoundedView


CONTENT_ROOTS = ('wiki', 'raw')
CONTENT_FILES = ('AGENTS.md', MAPPING_PATH)


def content_scope():
    return {'schema': 'knowledge-content-scope/1',
        'recursiveRoots': list(CONTENT_ROOTS), 'files': list(CONTENT_FILES),
        'otherPaths': 'outside_preview_scope', 'executorAdmission': False}


def _scan_content(root, reader, read_file):
    files, directories, aliases = {}, set(), {}
    total = 0

    def add(path):
        nonlocal total
        relative = path.relative_to(root).as_posix()
        _need(len(aliases) < 512, 'preview_baseline_entry_limit')
        _need(relative.casefold() not in aliases, 'preview_case_alias')
        aliases[relative.casefold()] = relative
        _check_chain(path)
        if path.is_dir():
            directories.add(relative)
        else:
            _need(path.is_file(), 'preview_not_regular_file')
            size = path.stat().st_size
            _need(size <= 1024 * 1024, 'preview_baseline_file_limit')
            total += size
            _need(total <= 4 * 1024 * 1024, 'preview_baseline_byte_limit')
            files[relative] = bytes_digest(read_file(root, relative))

    def fail(_):
        raise ValueError('baseline_unreadable')

    for name in CONTENT_ROOTS:
        directory = root / name
        _check_chain(directory, missing=True)
        if not directory.exists():
            continue
        _need(directory.is_dir(), 'preview_content_root_type')
        add(directory)
        for parent, dirs, names in os.walk(directory, followlinks=False, onerror=fail):
            reader.check()
            # 不排除 wiki/raw 内的隐藏文件或子目录，避免整组/链接检查漏项。
            for name in sorted([*dirs, *names]):
                add(Path(parent) / name)
            dirs.sort()
    for name in CONTENT_FILES:
        reader.check()
        path = root / name
        _check_chain(path)
        add(path)
    return files, directories


class ContentView(_BoundedView):
    """视图直接绑定真实根；物化只复制已声明的完整知识内容范围。"""
    def _scan(self):
        return _scan_content(self.root, self.reader, self._read_file)


def content_listing(root):
    """事务中的同范围目录盘点；依赖哈希由 Executor 单独逐项重核。"""
    reader = _Reader(dict(LIMITS, maxTotalBytes=64 * 1024 * 1024, maxSeconds=20))
    files, directories = _scan_content(Path(root), reader, lambda base, relative: b'')
    return sorted(files), sorted(directories)


def inspect_content_baseline(root):
    """只读盘点及重检，用于证明实际仓库范围可读，不签发候选准入。"""
    root = _root(root)
    reader = _Reader(dict(LIMITS, maxTotalBytes=64 * 1024 * 1024, maxSeconds=20))
    # 复用同一安全/有界原始字节读取；这里没有候选 overlay 或物化。
    view = ContentView.__new__(ContentView)
    view.root, view.reader = root, reader
    first, dirs = _scan_content(root, reader, view._read_file)
    second, final_dirs = _scan_content(root, reader, view._read_file)
    _need(first == second and dirs == final_dirs, 'preview_content_changed')
    result = {'schema': 'knowledge-content-baseline/1', 'scope': content_scope(),
        'files': first, 'directories': sorted(dirs), 'fileCount': len(first),
        'bytesRead': reader.used, 'consistency': 'cooperative_rechecked',
        'formalWriteAuthorized': False, 'modelCalls': 0}
    result['baselineDigest'] = digest(result)
    return result
