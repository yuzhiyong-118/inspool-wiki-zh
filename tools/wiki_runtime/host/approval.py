"""独立 owner 终端的批准存储；不向模型 JSON 通道提供签发接口。"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
import time

from ..contracts import canonical_json, digest


class ApprovalError(ValueError):
    """批准拒绝或私有存储不可信。"""


_MINT = object()
_OPERATIONS = frozenset(('approve', 'rule_maintenance', 'tool_maintenance'))
_BINDINGS = frozenset(('operation_id', 'candidate_digest', 'dependencies_digest',
                      'rules_digest', 'mapping_digest', 'validator_version', 'review_prompt_version'))


class ApprovalHandle:
    """只在可信 Python host 内传递；字符串、dict 或引用均不是凭据。"""
    __slots__ = ('_digest', '_nonce', '_mac')

    def __init__(self, context_digest=None, nonce=None, mac=None, *, _mint=None):
        if _mint is not _MINT:
            raise TypeError('ApprovalHandle 只能由可信批准存储创建')
        self._digest, self._nonce, self._mac = context_digest, nonce, mac

    def __repr__(self):
        return '<ApprovalHandle opaque>'

    def __reduce__(self):
        raise TypeError('批准凭据不能序列化到模型通道')


def _terminal(stream):
    try:
        return bool(stream.isatty() and os.isatty(stream.fileno()))
    except (AttributeError, OSError, ValueError):
        return False


def _check_path(path):
    """逐层拒绝符号链接、Windows reparse/junction 和文件硬链接。"""
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & 0x400 or
                not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)) or
                (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
            raise ApprovalError('私有批准路径包含链接或重解析点')


def _context_digest(context):
    if type(context) is not dict or set(context) != {
            'manifest', 'manifest_digest', 'candidate', 'snapshot',
            'operation_type', 'source_paths', 'bindings'}:
        raise ApprovalError('需要 Executor 完整批准上下文')
    manifest, candidate = context['manifest'], context['candidate']
    if (context['operation_type'] not in _OPERATIONS or
            type(manifest) is not dict or type(candidate) is not dict or
            type(context['snapshot']) is not dict or
            type(context['bindings']) is not dict or
            set(context['bindings']) != _BINDINGS or
            type(context['source_paths']) is not list or
            manifest.get('operation_type') != context['operation_type'] or
            digest(manifest) != context['manifest_digest'] or
            any(manifest.get(k) != v for k, v in context['bindings'].items())):
        raise ApprovalError('批准上下文不一致或不是敏感维护操作')
    try:
        sources = sorted(c['source'] for c in candidate['changes'] if c['action'] == 'move')
    except (KeyError, TypeError) as exc:
        raise ApprovalError('候选变更不完整') from exc
    if sources != context['source_paths']:
        raise ApprovalError('批准来源批次与候选不一致')
    return digest(context)


class ApprovalStore:
    def __init__(self, private_root):
        self.root = Path(os.path.abspath(private_root))
        _check_path(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        _check_path(self.root)
        if not self.root.is_dir():
            raise ApprovalError('批准根不是目录')
        key_path = self.root / 'approval.key'
        _check_path(key_path)
        if not key_path.exists() and any(self.root.iterdir()):
            raise ApprovalError('非空批准目录缺少密钥；需要 owner 对账，不能自动重置')
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
        self._key = self._read_key()

    def _read_key(self):
        path = self.root / 'approval.key'
        _check_path(path)
        if not path.is_file() or path.stat().st_size != 32:
            raise ApprovalError('批准密钥损坏；不会覆盖或自动重置')
        key = path.read_bytes()
        if len(key) != 32:
            raise ApprovalError('批准密钥损坏；不会覆盖或自动重置')
        return key

    def _check_key(self):
        if not hmac.compare_digest(self._read_key(), self._key):
            raise ApprovalError('批准密钥已变化')

    def _mac(self, payload):
        return hmac.new(self._key, canonical_json(payload), hashlib.sha256).hexdigest()

    def _load(self, context_digest):
        self._check_key()
        path = self.root / (context_digest + '.json')
        _check_path(path)
        try:
            if not path.is_file() and path.exists():
                raise ApprovalError('批准记录不是普通文件')
            if path.stat().st_size > 16384:
                raise ApprovalError('批准记录过大')
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        if len(data) > 16384:
            raise ApprovalError('批准记录过大')
        try:
            record = json.loads(data)
            payload, mac = record['payload'], record['mac']
            if (set(record) != {'payload', 'mac'} or
                    set(payload) != {'context_digest', 'nonce', 'issued_at', 'expires_at', 'revoked'} or
                    payload['context_digest'] != context_digest or
                    type(payload['revoked']) is not bool or
                    type(payload['nonce']) is not str or
                    any(type(payload[k]) not in (int, float) or not math.isfinite(payload[k])
                        for k in ('issued_at', 'expires_at')) or
                    type(mac) is not str or not hmac.compare_digest(self._mac(payload), mac)):
                raise ApprovalError('批准记录认证失败')
            return record
        except (ValueError, TypeError, KeyError) as exc:
            raise ApprovalError('批准记录损坏或认证失败') from exc

    def _save(self, context_digest, payload):
        self._check_key()
        target = self.root / (context_digest + '.json')
        _check_path(target)
        record = {'payload': payload, 'mac': self._mac(payload)}
        fd, temporary = tempfile.mkstemp(prefix='.approval-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(canonical_json(record))
                stream.flush()
                os.fsync(stream.fileno())
            self._check_key()
            _check_path(target)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return record

    @staticmethod
    def _handle(record):
        payload = record['payload']
        return ApprovalHandle(payload['context_digest'], payload['nonce'], record['mac'], _mint=_MINT)

    def approve_interactive(self, context, *, input_stream=None, output_stream=None, ttl_seconds=86400):
        context_digest = _context_digest(context)
        if type(ttl_seconds) not in (int, float) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ApprovalError('TTL 必须为有限正数')
        source = sys.stdin if input_stream is None else input_stream
        output = sys.stdout if output_stream is None else output_stream
        if not _terminal(source) or not _terminal(output):
            raise ApprovalError('必须由 owner 独立终端 TTY 确认；管道/模型 JSONL 不可批准')
        # ASCII JSON safely escapes terminal controls, bidi characters and line breaks.
        summary = {'operation_type': context['operation_type'], 'manifest': context['manifest'],
                   'candidate': context['candidate'], 'source_paths': context['source_paths'],
                   'bindings': context['bindings'], 'snapshot': context['snapshot']}
        output.write('待批准完整范围、批次、候选及版本摘要（转义 JSON）：\n')
        output.write(json.dumps(summary, sort_keys=True, ensure_ascii=True) + '\n')
        output.write('context SHA256: ' + context_digest + '\n')
        output.write('请核对独立 host 显示的 diff；输入上述完整 SHA256 才批准：\n')
        output.flush()
        if source.readline(1024).rstrip('\r\n') != context_digest:
            raise ApprovalError('批准摘要不匹配；未签发凭据')
        # Recheck after interaction; a damaged record is never silently overwritten.
        self._load(context_digest)
        now = time.time()
        record = self._save(context_digest, dict(context_digest=context_digest,
            nonce=secrets.token_hex(32), issued_at=now, expires_at=now + ttl_seconds, revoked=False))
        return self._handle(record)

    def lookup(self, context):
        record = self._load(_context_digest(context))
        if record is None:
            return None
        payload, now = record['payload'], time.time()
        if payload['revoked'] or not payload['issued_at'] <= now < payload['expires_at']:
            return None
        return self._handle(record)

    def verify(self, context, handle):
        if type(handle) is not ApprovalHandle:
            return False
        try:
            current = self.lookup(context)
            return (current is not None and
                all(hmac.compare_digest(getattr(current, key), getattr(handle, key))
                    for key in ApprovalHandle.__slots__))
        except (ApprovalError, OSError, ValueError, TypeError, AttributeError):
            return False

    def revoke(self, context):
        context_digest = _context_digest(context)
        record = self._load(context_digest)
        if record is not None:
            payload = record['payload']
            payload['revoked'] = True
            self._save(context_digest, payload)
