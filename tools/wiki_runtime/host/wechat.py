"""微信 owner 入口：原始字节进入离线 capture，完整包才交既有 Executor。"""
from __future__ import annotations

from argparse import Namespace
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import uuid

from .approval import _check_path
from ..executor.core import _safe

MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 8 * 1024 * 1024


def validate_url(url):
    """只接收规范 HTTPS 微信文章地址；每一跳重定向同样验证。"""
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
        raise ValueError('微信 URL 含非法字符')
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'https' or parts.netloc != 'mp.weixin.qq.com'
            or not re.fullmatch(r'/s/[A-Za-z0-9_-]+', parts.path) or parts.fragment):
        raise ValueError('只允许 https://mp.weixin.qq.com/s/<文章ID>')
    return url


class _WechatRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bytes(url):
    """独立严格抓取，保留响应原始 HTML 字节；不使用有损预览 fetch。"""
    from tools.wechat_article import UA, REFERER, TIMEOUT
    validate_url(url)
    request = urllib.request.Request(url, headers={
        'User-Agent': UA, 'Referer': REFERER, 'Accept': 'text/html,application/xhtml+xml',
        'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(_WechatRedirect())
    with opener.open(request, timeout=TIMEOUT) as response:
        validate_url(response.geturl())
        if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
            raise ValueError('响应不是 HTML')
        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('不接受压缩响应，以免把解压数据冒充原件')
        declared = response.headers.get('Content-Length')
        if declared is not None:
            if not re.fullmatch(r'[0-9]+', declared) or int(declared) > MAX_HTML_BYTES:
                raise ValueError('响应长度无效或超过 8 MiB')
        data = response.read(MAX_HTML_BYTES + 1)
        if declared is not None and int(declared) != len(data):
            raise ValueError('响应字节数与 Content-Length 不符，拒绝截断响应')
    _html_size(data)
    return data


def _html_size(data):
    if type(data) is not bytes or not data or len(data) > MAX_HTML_BYTES:
        raise ValueError('HTML 必须为非空原始字节且不超过 8 MiB')


def _absolute_checked(path):
    path = Path(os.path.abspath(path))
    _check_path(path)
    # 复用执行器检查大小写别名、逐段 reparse/hardlink 与路径逃逸。
    return _safe(path.parent, path.name)


def _disjoint(path, other):
    return not (path == other or path.is_relative_to(other) or other.is_relative_to(path))


def _outside(path, root, state_dir=None):
    root = _absolute_checked(root)
    if path.is_relative_to(root) or path == root:
        raise ValueError('输出必须位于正式库外')
    if state_dir is not None and not _disjoint(path, _absolute_checked(state_dir)):
        raise ValueError('输出不得位于或包含私有状态目录')
    forbidden = {'.git', '.agents', '.codex', '.claude', '.github', '.wiki-runtime', 'private', 'operations'}
    if any(part.casefold() in forbidden for part in path.parts):
        raise ValueError('输出不得进入规则、代码或私有状态目录')
    for ancestor in path.parents:
        if ((ancestor / '.git').exists() or (ancestor / 'AGENTS.md').exists()
                or (ancestor / 'private/pending.key').exists()):
            raise ValueError('输出不得进入代码库、规则目录或私有状态树')


def export_markdown(root, output, document, *, state_dir=None):
    """仅导出库外普通新 .md 文件；从不覆盖已有原始资料。"""
    target = _absolute_checked(output)
    _outside(target, root, state_dir)
    if target.suffix.lower() != '.md' or target.name.casefold() in ('agents.md', 'skill.md', 'gemini.md', 'claude.md'):
        raise ValueError('导出仅允许普通 Markdown 文件，不能是规则入口')
    data = document.encode('utf-8')
    if len(data) > MAX_EXPORT_BYTES:
        raise ValueError('导出超过 8 MiB')
    if not target.parent.is_dir():
        raise ValueError('导出父目录必须已存在')
    _absolute_checked(target)
    with target.open('xb') as stream:
        stream.write(data)
    return target


def capture_url(root, state_dir, candidate_dir, url, *, raw_path=None,
                operation_id=None, apply=True):
    """可信 Python host API，非模型工具；网络是唯一可替换的测试边界。"""
    from .cli import _prepare_derived
    from .supervisor import StandaloneHost
    from ..capture import capture
    from ..contracts import bytes_digest
    if type(apply) is not bool:
        raise ValueError('apply 必须是可信宿主布尔配置')
    validate_url(url)
    root = _absolute_checked(root)
    state = _absolute_checked(state_dir)
    candidate = _absolute_checked(candidate_dir)
    _outside(candidate, root, state)
    if not _disjoint(candidate, root) or candidate.exists() or not candidate.parent.is_dir():
        raise ValueError('可信候选目录必须是库外、父目录已存在的全新目录')
    if not _disjoint(state, root):
        raise ValueError('state-dir 必须在库外且不得包含库')
    existing_state = state
    while not existing_state.exists():
        existing_state = existing_state.parent
    if existing_state.stat().st_dev != root.stat().st_dev:
        raise ValueError('state-dir 与正式库必须同卷')
    data = fetch_bytes(url)
    _html_size(data)
    _absolute_checked(candidate)
    candidate.mkdir(exist_ok=False)
    original = _safe(candidate, 'response.html')
    with original.open('xb') as stream:
        stream.write(data)
    package, package_root = capture(original, candidate, 'package', vault_root=root,
                                    adapter_id='wechat', origin=url)
    report = {'status': 'candidate_only', 'applied': False, 'candidate_dir': str(candidate),
              'package_root': str(package_root), 'quality': package['quality']}
    if package['quality']['status'] != 'complete':
        return report
    host = StandaloneHost(root, state, offline=True)
    args = Namespace(command='import-package', operation_id=operation_id or 'wechat-' + uuid.uuid4().hex,
                     package_root=str(package_root), apply=apply,
                     raw_path=raw_path or ('raw/unprocessed/wechat-' + bytes_digest(url.encode())[:16] + '.md'))
    try:
        report.update(_prepare_derived(host, args))
        return report
    finally:
        host.close()
