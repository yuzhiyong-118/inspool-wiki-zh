"""模型只能发送工具名与 JSON 参数；身份和权限来自可信 transport。

本模块不执行模型代码、不启动 shell、不写正式库、不调用 Executor。
生产 host 必须阻止模型使用其他文件/代码工具，并保护本模块及配置。
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from threading import RLock

from ..contracts import ContractError, canonical_json, validate_path


class PermissionDenied(PermissionError):
    """默认拒绝；调用方不得降级到 shell 或通用文件工具。"""


ROLES = frozenset({'worker', 'reviewer', 'auditor', 'coordinator'})
TOOLS = {
    'worker': frozenset({'read', 'candidate_write'}),
    'reviewer': frozenset({'read'}),
    'auditor': frozenset({'read'}),
    'coordinator': frozenset({'request_task'}),
}
_FORBIDDEN_PARTS = {'.git', '.wiki-runtime', '.codex', '.agents'}


def _overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def _check_chain(path: Path, *, missing=False) -> None:
    """拒绝每层重解析点、符号链接和文件硬链接；不消除恶意本地 TOCTOU。"""
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise PermissionDenied('路径不存在') from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PermissionDenied('拒绝 symlink/junction/reparse 路径')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise PermissionDenied('拒绝硬链接文件')
        if not stat.S_ISDIR(info.st_mode) and part != path:
            raise PermissionDenied('父路径不是目录')
        if part == path and not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise PermissionDenied('拒绝特殊文件')


def _root(value) -> Path:
    path = Path(value).absolute()
    _check_chain(path)
    if not path.is_dir():
        raise PermissionDenied('授权根必须是已存在目录')
    # 不能先 resolve 后检查，否则会隐藏 junction。
    if path != path.resolve():
        raise PermissionDenied('授权根不能使用路径别名')
    return path


def _path(root: Path, relative: str, *, missing=False) -> Path:
    try:
        validate_path(relative)
    except (ContractError, TypeError, ValueError):
        raise PermissionDenied('非法相对路径') from None
    if any(p.casefold() in _FORBIDDEN_PARTS for p in relative.split('/')):
        raise PermissionDenied('拒绝运行时与权限配置路径')
    path = root.joinpath(*relative.split('/'))
    _check_chain(root)
    _check_chain(path, missing=missing)
    if root not in path.parents:
        raise PermissionDenied('路径越界')
    # 明确拒绝大小写别名，避免与 Windows 路径策略出现分歧。
    cursor = root
    for name in relative.split('/'):
        if cursor.is_dir():
            names = os.listdir(cursor)
            if name not in names and name.casefold() in {n.casefold() for n in names}:
                raise PermissionDenied('拒绝大小写路径别名')
        cursor /= name
    return path


@dataclass(frozen=True)
class _Session:
    role: str
    reads: tuple[tuple[str, Path], ...]
    candidate: Path | None


class Gateway:
    """仅由可信 host 构造和持有；不作为模型可调用的管理工具公开。

    bind 返回已绑定身份的二参数工具函数。模型没有 session、role、scope 参数。
    若模型能执行 Python 或反射本对象，隔离前提已经不成立。
    """
    def __init__(self, formal_root, *, protected_roots=(), max_bytes=1024 * 1024):
        self._formal = _root(formal_root)
        self._protected = (self._formal, *(_root(p) for p in protected_roots))
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError('max_bytes 必须是正整数')
        self._max_bytes = max_bytes
        self._candidates: list[Path] = []
        self._lock = RLock()

    def bind(self, role, *, read_scopes=None, candidate_root=None):
        """host 认证 session 后调用；返回值只在该 session transport 上注册。"""
        if role not in ROLES:
            raise PermissionDenied('未知角色')
        scopes = read_scopes or {}
        if type(scopes) is not dict:
            raise PermissionDenied('read_scopes 必须由 host 固定')
        reads = []
        for name, root in scopes.items():
            if type(name) is not str or not name.isascii() or not name.isidentifier():
                raise PermissionDenied('非法 scope 名')
            reads.append((name, _root(root)))
        candidate = None
        with self._lock:
            if candidate_root is not None:
                if role != 'worker':
                    raise PermissionDenied('只有 Worker 可以拥有候选目录')
                candidate = _root(candidate_root)
                if any(_overlaps(candidate, p) for p in (*self._protected, *self._candidates)):
                    raise PermissionDenied('候选目录与受保护目录或其他 session 重叠')
                self._candidates.append(candidate)
            if role == 'worker' and candidate is None:
                raise PermissionDenied('Worker 必须有专属候选目录')
            if role == 'coordinator' and reads:
                raise PermissionDenied('Coordinator 只调度')
            session = _Session(role, tuple(reads), candidate)

        def call(tool, arguments):
            # 只允许数据，不支持对象、回调、隐式 role 或额外权限字段。
            try:
                encoded = canonical_json(arguments)
            except (ContractError, TypeError, ValueError, RecursionError):
                raise PermissionDenied('参数必须为 JSON 数据') from None
            if len(encoded) > self._max_bytes * 8:
                raise PermissionDenied('参数过大')
            if type(tool) is not str or tool not in TOOLS[session.role]:
                raise PermissionDenied('角色不允许此工具')
            if type(arguments) is not dict:
                raise PermissionDenied('参数必须为对象')
            with self._lock:
                return self._invoke(session, tool, arguments)

        return call

    def _invoke(self, session, tool, args):
        if tool == 'read':
            self._keys(args, {'scope', 'path'})
            if type(args['scope']) is not str:
                raise PermissionDenied('非法 scope')
            scopes = dict(session.reads)
            if args['scope'] not in scopes:
                raise PermissionDenied('未授权读取范围')
            path = _path(scopes[args['scope']], args['path'])
            if not path.is_file() or path.stat().st_size > self._max_bytes:
                raise PermissionDenied('只允许读取大小受限的普通文件')
            with path.open('rb') as stream:
                data = stream.read(self._max_bytes + 1)
            if len(data) > self._max_bytes:
                raise PermissionDenied('文件过大')
            _check_chain(path)
            return {'text': data.decode('utf-8')}
        if tool == 'candidate_write':
            self._keys(args, {'path', 'text'})
            if type(args['text']) is not str:
                raise PermissionDenied('text 必须为字符串')
            content = args['text'].encode('utf-8')
            if len(content) > self._max_bytes:
                raise PermissionDenied('候选文件过大')
            path = _path(session.candidate, args['path'], missing=True)
            # host 预建目录；模型不能创建目录/链接/可执行子进程。
            _check_chain(path.parent)
            if path.exists() and not path.is_file():
                raise PermissionDenied('目标不是普通文件')
            fd, temp = tempfile.mkstemp(prefix='.candidate-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                _check_chain(path, missing=True)
                os.replace(temp, path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            return {'written_bytes': len(content)}
        self._keys(args, {'target', 'task'})
        if args['target'] not in {'worker', 'reviewer', 'auditor'} or type(args['task']) is not str:
            raise PermissionDenied('非法调度请求')
        if len(args['task'].encode('utf-8')) > self._max_bytes:
            raise PermissionDenied('调度任务过大')
        # 返回数据供可信调度器处理；不执行字符串、不批准、不调用 Executor。
        return {'request': dict(args), 'executed': False}

    @staticmethod
    def _keys(args, expected):
        if set(args) != expected:
            raise PermissionDenied('参数缺失或包含未授权字段')
