"""v1 候选视图：不向正式库或候选目录写入任何字节。"""
from __future__ import annotations

import copy
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..contracts import (ContractError, bytes_digest, candidate_digest,
                         validate, validate_path)


class CandidateError(ContractError):
    """候选、文件前提或读取依赖失效，调用者必须停止。"""


def _reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & 0x400)


def _base(value):
    path = Path(os.path.abspath(value))
    for part in (path, *path.parents):
        if part.exists() and _reparse(part):
            raise CandidateError(f'拒绝 symlink/junction 根: {part}')
    if not path.is_dir():
        raise CandidateError(f'根目录不存在: {path}')
    return path.resolve(strict=True)


class CandidateView:
    """把候选叠加到构造时的文件基线，所有路径均为根相对 POSIX 字符串。

    ``allow_deletes`` 只启用删除的视图能力，不是业务授权。控制目录
    .git/.wiki-runtime/__pycache__ 不属于内容视图；payload 在库内时亦排除。
    在导出报告前须调用 verify_dependencies；目录枚举的新增文件检测属于
    本实例的内部防护，v1 文件型 dependency_snapshot 不能序列化此防护。
    """

    EXCLUDED = frozenset({'.git', '.wiki-runtime', '__pycache__'})

    def __init__(self, root, candidate, payload_root, *, allow_deletes=False):
        self.root = _base(root)
        self.payload_root = _base(payload_root)
        if self.root == self.payload_root:
            raise CandidateError('候选根不能等于正式库根')
        validate('candidate', candidate)
        self._candidate = copy.deepcopy(candidate)
        self.candidate_digest = candidate_digest(self._candidate)
        self._dependencies = {}
        self._enumerated = False
        self._baseline, self._directories = self._scan()
        self._overlay = {}
        self._removed = set()
        self._payloads = {}
        for change in self._candidate['changes']:
            path = change['path']
            self._check_target(path)
            self._expect(path, change['precondition'])
            action = change['action']
            if action == 'delete':
                if not allow_deletes:
                    raise CandidateError(f'删除能力未显式启用: {path}')
                self._removed.add(path)
                continue
            if action == 'move':
                source = change['source']
                self._expect(source, {'kind': 'hash', 'sha256': change['source_sha256']})
                self._removed.add(source)
                data = self._read_baseline(source)
            if 'payload_path' in change:
                payload = change['payload_path']
                data = self._read_file(self.payload_root, payload)
                if bytes_digest(data) != change['sha256']:
                    raise CandidateError(f'候选 payload 哈希不符: {payload}')
                self._payloads[payload] = change['sha256']
            self._overlay[path] = data
        # 所有最终文件（含未修改文件）都必须不存在大小写或父子冲突。
        paths = (set(self._baseline) - self._removed) | set(self._overlay)
        folded = {}
        for path in sorted(paths):
            key = path.casefold()
            if key in folded:
                raise CandidateError(f'大小写路径碰撞: {folded[key]} / {path}')
            folded[key] = path
        for key, path in folded.items():
            parts = key.split('/')
            if any('/'.join(parts[:i]) in folded for i in range(1, len(parts))):
                raise CandidateError(f'文件父子冲突: {path}')

    @property
    def candidate(self):
        return copy.deepcopy(self._candidate)

    def _safe_path(self, base, value):
        validate_path(value)
        if _base(base) != base:
            raise CandidateError(f'输入根已改变: {base}')
        current = base
        for component in value.split('/'):
            if current.exists() and not current.is_dir():
                raise CandidateError(f'父路径不是目录: {value}')
            if current.is_dir():
                aliases = [p.name for p in current.iterdir()
                           if p.name.casefold() == component.casefold()]
                if aliases and aliases != [component]:
                    raise CandidateError(f'大小写别名路径: {value}')
            current = current / component
            if current.exists() or current.is_symlink():
                if _reparse(current):
                    raise CandidateError(f'拒绝 symlink/junction: {value}')
        if not current.resolve(strict=False).is_relative_to(base):
            raise CandidateError(f'路径越界: {value}')
        return current

    def _read_file(self, base, value):
        target = self._safe_path(base, value)
        if not target.is_file():
            raise CandidateError(f'不是普通文件: {value}')
        before = target.stat()
        if before.st_nlink > 1:
            raise CandidateError(f'拒绝硬链接文件: {value}')
        data = target.read_bytes()
        checked = self._safe_path(base, value)
        after = checked.stat()
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
            raise CandidateError(f'读取期间文件改变: {value}')
        return data

    def _scan(self):
        _base(self.root)
        files, directories, aliases = {}, set(), {}
        def fail_walk(error):
            raise CandidateError(f'无法枚举基线目录: {error}') from error

        for parent, dirs, names in os.walk(self.root, followlinks=False, onerror=fail_walk):
            current = Path(parent)
            dirs[:] = sorted(d for d in dirs if d not in self.EXCLUDED
                             and current / d != self.payload_root)
            for name in [*dirs, *names]:
                path = current / name
                relative = path.relative_to(self.root).as_posix()
                validate_path(relative)
                if _reparse(path):
                    raise CandidateError(f'拒绝 symlink/junction: {relative}')
                key = relative.casefold()
                if key in aliases:
                    raise CandidateError(f'大小写路径碰撞: {aliases[key]} / {relative}')
                aliases[key] = relative
            for directory in dirs:
                directories.add((current / directory).relative_to(self.root).as_posix())
            for name in sorted(names):
                relative = (current / name).relative_to(self.root).as_posix()
                files[relative] = bytes_digest(self._read_file(self.root, relative))
        return files, directories

    def _check_target(self, path):
        self._safe_path(self.root, path)
        if any(part in self.EXCLUDED for part in path.split('/')):
            raise CandidateError(f'目标属于控制目录: {path}')
        target = self.root / path
        if target == self.payload_root or target.is_relative_to(self.payload_root):
            raise CandidateError(f'目标位于 payload 根: {path}')
        folded = path.casefold()
        if folded in {p.casefold() for p in self._directories}:
            raise CandidateError(f'文件目标已是目录: {path}')

    def _expect(self, path, precondition):
        target = self._safe_path(self.root, path)
        if precondition['kind'] == 'absent':
            if target.exists():
                raise CandidateError(f'必须不存在的目标已存在: {path}')
        else:
            if bytes_digest(self._read_file(self.root, path)) != precondition['sha256']:
                raise CandidateError(f'旧文件哈希不符: {path}')
        previous = self._dependencies.get(path)
        if previous is not None and previous != precondition:
            raise CandidateError(f'依赖前提冲突: {path}')
        self._dependencies[path] = copy.deepcopy(precondition)

    def _read_baseline(self, path):
        if path not in self._baseline:
            self._expect(path, {'kind': 'absent'})
            raise FileNotFoundError(path)
        expected = {'kind': 'hash', 'sha256': self._baseline[path]}
        self._expect(path, expected)
        data = self._read_file(self.root, path)
        if bytes_digest(data) != expected['sha256']:
            raise CandidateError(f'基线文件已改变: {path}')
        return data

    def read_bytes(self, path):
        validate_path(path)
        self._safe_path(self.root, path)
        if path in self._removed:
            raise FileNotFoundError(path)
        if path in self._overlay:
            self._verify_payloads()
            return self._overlay[path]
        return self._read_baseline(path)

    def read_text(self, path, encoding='utf-8'):
        return self.read_bytes(path).decode(encoding, errors='strict')

    def exists(self, path):
        """仅查询文件；目录不属于此文件视图。"""
        try:
            self.read_bytes(path)
            return True
        except FileNotFoundError:
            return False

    is_file = exists

    def iter_paths(self, prefix=''):
        if prefix:
            validate_path(prefix)
        self._enumerated = True
        self.verify_dependencies()
        paths = (set(self._baseline) - self._removed) | set(self._overlay)
        result = sorted(p for p in paths if not prefix or p == prefix or p.startswith(prefix + '/'))
        for path in result:
            if path in self._baseline:
                self._expect(path, {'kind': 'hash', 'sha256': self._baseline[path]})
        return iter(result)

    def dependency_snapshot(self):
        result = {'contract_version': '1.0', 'operation_id': self._candidate['operation_id'],
                  'files': [{'path': path, 'precondition': copy.deepcopy(precondition)}
                            for path, precondition in sorted(self._dependencies.items())]}
        return validate('dependency_snapshot', result)

    def _verify_payloads(self):
        for path, expected in self._payloads.items():
            if bytes_digest(self._read_file(self.payload_root, path)) != expected:
                raise CandidateError(f'候选 payload 已改变: {path}')

    def verify_dependencies(self, snapshot=None):
        """成功返回 True；失败抛异常，绝不自动刷新旧前提。"""
        snapshot = self.dependency_snapshot() if snapshot is None else snapshot
        validate('dependency_snapshot', snapshot)
        if snapshot['operation_id'] != self._candidate['operation_id']:
            raise CandidateError('依赖 operation_id 不匹配')
        # 外部快照可以增加依赖，不能通过省略条目跳过视图已读取的依赖。
        internal = self.dependency_snapshot()
        for entry in snapshot['files']:
            self._expect(entry['path'], entry['precondition'])
        for entry in internal['files']:
            self._expect(entry['path'], entry['precondition'])
        self._verify_payloads()
        if self._enumerated:
            files, directories = self._scan()
            if set(files) != set(self._baseline) or directories != self._directories:
                raise CandidateError('目录清单已改变（新增/删除/重命名）')
        return True

    @contextmanager
    def materialize(self, *, parent=None):
        """在独立新建临时目录中复制视图；退出即清理，不接受覆盖目标。"""
        base = _base(parent) if parent is not None else _base(tempfile.gettempdir())
        if base.is_relative_to(self.root) or base.is_relative_to(self.payload_root):
            raise CandidateError('临时目录父级不得位于正式库或 payload 内')
        with tempfile.TemporaryDirectory(prefix='wiki-candidate-', dir=base) as directory:
            destination = Path(directory)
            if (self.root.is_relative_to(destination) or self.payload_root.is_relative_to(destination)
                    or destination.is_relative_to(self.root) or destination.is_relative_to(self.payload_root)):
                raise CandidateError('物化目录与输入根重叠')
            for path in self.iter_paths():
                target = destination / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.read_bytes(path))
            self.verify_dependencies()
            yield destination
            self.verify_dependencies()
