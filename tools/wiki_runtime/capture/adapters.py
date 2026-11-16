"""标准库离线适配器。所有输出只写显式候选区，原始字节不重写。"""
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
from types import MappingProxyType
from urllib.parse import unquote, urlsplit

from tools.wechat_article import html_to_markdown, parse as legacy_parse
from tools.wiki_runtime.contracts import (
    ContractError, bytes_digest, digest, resolve_path, validate, validate_path,
)

ADAPTERS = MappingProxyType({
    'markdown': MappingProxyType({'suffixes': ('.md', '.markdown'), 'input_type': 'markdown'}),
    'wechat': MappingProxyType({'suffixes': ('.html', '.htm'), 'input_type': 'wechat'}),
    'pdf': MappingProxyType({'suffixes': ('.pdf',), 'input_type': 'pdf'}),
})


def capabilities(adapter_id):
    """固定注册；未知类型拒绝，不运行输入携带的代码。"""
    if adapter_id not in ADAPTERS:
        raise ValueError(f'不支持的适配器: {adapter_id}')
    if adapter_id == 'pdf':
        from .pdf import capabilities as pdf_capabilities
        return pdf_capabilities()
    return {'adapter_id': adapter_id, 'version': '1.0', 'offline': True,
            'used_ocr': False, 'used_model': False,
            'input_type': ADAPTERS[adapter_id]['input_type']}


def identify(input_path):
    for name, info in ADAPTERS.items():
        if Path(input_path).suffix.lower() in info['suffixes']:
            return name
    raise ValueError('不支持的输入类型；不得降级为 Markdown')


class _Article(HTMLParser):
    """仅取 js_content 的完整子树；不吞入页尾脚本。"""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.parts = []
        self.resources = []
        self.blocks = []
        self.found = False
        self.closed = False
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.stack and not self.found and attrs.get('id') == 'js_content':
            self.found = True
            self.stack.append(tag)
            return
        if not self.stack:
            return
        if tag in ('script', 'style'):
            self.skip += 1
        if not self.skip:
            self.parts.append(self.get_starttag_text())
            if tag in ('p', 'section', 'h1', 'h2', 'h3', 'li', 'img'):
                self.blocks.append(self.getpos()[0])
            if tag in ('img', 'audio', 'video', 'source'):
                self.resources.append(attrs.get('data-src') or attrs.get('src') or '')
            if tag == 'a' and attrs.get('download') is not None:
                self.resources.append(attrs.get('href', ''))
        if tag not in ('img', 'br', 'hr', 'meta', 'link', 'input', 'source', 'wbr'):
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        if self.stack[-1] != tag:
            return  # malformed nesting remains unclosed and therefore partial
        self.stack.pop()
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
            return
        if not self.stack:
            self.closed = True
        elif not self.skip:
            self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        if self.stack and not self.skip:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f'&{name};')

    def handle_charref(self, name):
        self.handle_data(f'&#{name};')


def _markdown_resources(text):
    refs = re.findall(r'!?\[[^\]]*\]\(\s*<?([^\s)>]+)', text)
    refs += re.findall(r'^\s*\[[^\]]+\]:\s*<?([^\s>]+)', text, re.M)
    refs += re.findall(r'!\[\[([^\]|]+)', text)
    # Ordinary web hyperlinks are not attachments; image URLs always are.
    images = re.findall(r'!\[[^\]]*\]\(\s*<?([^\s)>]+)', text)
    return list(dict.fromkeys(r for r in refs if not r.startswith('#')
                             and (r in images or not urlsplit(r).scheme)))


def _analyse(data, adapter_id):
    errors, missing, locs, resources = [], [], [], []
    meta = {'title': '', 'author': '', 'published_at': ''}
    try:
        text = data.decode('utf-8', errors='strict')
    except UnicodeDecodeError:
        return '', meta, [], [], ['invalid_utf8'], [], ['严格 UTF-8 解码失败，已保留原件']
    if adapter_id == 'markdown':
        extracted = text
        m = re.search(r'^#\s+(.+)$', text, re.M)
        meta['title'] = m.group(1).strip() if m else ''
        body = text.lstrip('\ufeff')
        if body.startswith('---\n') or body.startswith('---\r\n'):
            fm = re.match(r'^---\r?\n(.*?)^---[ \t]*\r?\n', body, re.S | re.M)
            if not fm:
                errors.append('unclosed_frontmatter')
                body = ''
            else:
                body = body[fm.end():]
                for name, field in (('title', 'title'), ('author', 'author'), ('published_at', 'published_at')):
                    value = re.search(rf'^{name}:\s*(.*?)\s*$', fm.group(1), re.M)
                    if value:
                        meta[field] = value.group(1).strip('\"\'')
        resources = _markdown_resources(body)
        locs = [f'lines:{i}-{i}' for i, line in enumerate(text.splitlines(), 1) if line.strip()]
        if not body.strip():
            errors.append('empty_body')
    else:
        article = _Article()
        article.feed(text)
        article.close()
        extracted = html_to_markdown(''.join(article.parts))
        resources = article.resources
        locs = [f'element:#js_content;line:{i}' for i in article.blocks] or (
            ['element:#js_content'] if article.found else [])
        if not article.found:
            errors.append('missing_article_body')
        elif not article.closed:
            missing.append('truncated_html')
        if re.search(r'(?:id=[\"\'](?:js_verify|verify_container)|环境异常|访问过于频繁|请完成安全验证|captcha)', text, re.I):
            errors.append('verification_or_block_page')
        if not extracted.strip():
            errors.append('empty_body')
        try:
            old = legacy_parse(text)
            meta = {'title': old['title'] if old['title'] != '(无标题)' else '',
                    'author': old['author'] or '', 'published_at': old['publish_time'] or ''}
        except (ValueError, OverflowError, OSError):
            pass
        if not meta['title']:
            missing.append('article_title')
    if re.search(r'\[TRUNCATED\]|内容已截断|点击展开全文|阅读全文后续', text, re.I):
        missing.append('truncation_marker')
    return extracted, meta, locs, resources, errors, missing, ['严格 UTF-8 解码成功；保留原始字节；离线抽取，未进行网络请求']


def _outside_business(path, vault_root):
    runtime = vault_root / '.wiki-runtime'
    if path.is_relative_to(vault_root) and not path.is_relative_to(runtime):
        raise ValueError('库内候选输出仅允许位于 .wiki-runtime 内')
    # A symlink/junction named .wiki-runtime may point back into a control area.
    if runtime.exists():
        resolved_runtime = runtime.resolve()
        if resolved_runtime.is_relative_to(vault_root) and resolved_runtime != runtime:
            raise ValueError('.wiki-runtime 不得解析到库内其他目录')


def capture(input_path, candidate_root, package_path, *, vault_root, adapter_id=None,
            origin=None, source_id=None, attachments=None):
    """返回 (source_package dict, package_root Path)。

    package_path 必须是候选区内尚不存在的相对路径。attachments 为
    {原始资源引用: 本地 Path}；不提供时仅从输入文件同目录安全读取相对资源。
    失败解析也保留候选包；IO/范围/未知类型错误抛异常，不冒充规则失败。
    """
    input_path, vault_root = Path(input_path), Path(vault_root).resolve()
    candidate_root = Path(candidate_root).resolve()
    _outside_business(candidate_root, vault_root)
    validate_path(package_path)
    candidate_root.mkdir(parents=True, exist_ok=True)
    root = resolve_path(candidate_root, package_path)
    _outside_business(root, vault_root)
    if root.exists():
        raise FileExistsError(root)
    adapter_id = adapter_id or identify(input_path)
    if adapter_id == 'pdf':
        from .pdf import capture_pdf
        return capture_pdf(input_path, candidate_root, package_path, vault_root=vault_root,
                           adapter_id='pdf', origin=origin, source_id=source_id,
                           attachments=attachments)
    capabilities(adapter_id)
    data = input_path.read_bytes()
    extracted, meta, locs, resources, errors, missing, evidence = _analyse(data, adapter_id)
    original_path = 'originals/source' + ('.md' if adapter_id == 'markdown' else '.html')
    files = {original_path: data, 'extracted/content.md': extracted.encode('utf-8')}
    attached = []
    attachments = attachments or {}
    for ref in dict.fromkeys(resources):
        try:
            if ref in attachments:
                resource = Path(attachments[ref])
            else:
                parsed = urlsplit(ref)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    raise ValueError('离线资源未提供')
                resource = resolve_path(input_path.parent.resolve(), unquote(parsed.path))
            content = resource.read_bytes()
            if not content:
                raise ValueError('附件为空')
        except (OSError, ValueError):
            missing.append(f'attachment:{ref}')
            continue
        name = f'attachments/{len(attached) + 1:04d}' + resource.suffix.lower()
        try:
            validate_path(name)
        except ContractError:
            name = f'attachments/{len(attached) + 1:04d}.bin'
        files[name] = content
        attached.append({'path': name, 'sha256': bytes_digest(content),
                         'media_type': mimetypes.guess_type(resource.name)[0] or 'application/octet-stream'})
        # Bind the captured link to its package artifact, preserving originals unchanged.
        extracted = extracted.replace(ref, '../' + name)
        evidence.append(f'附件 {ref} -> {name}')
    files['extracted/content.md'] = extracted.encode('utf-8')
    original = {'path': original_path, 'sha256': bytes_digest(data),
                'media_type': 'text/markdown' if adapter_id == 'markdown' else 'text/html'}
    origin = origin or input_path.resolve().as_uri()
    source = dict(meta, origin=origin, acquired_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                  unavailable_fields=[key for key, value in meta.items() if not value])
    package = {'contract_version': '1.0', 'package_version': '1.0',
               'source_id': source_id or 'source-' + digest({'origin': origin}),
               'source_revision': digest([{'path': original_path, 'sha256': original['sha256']}]),
               'input_type': ADAPTERS[adapter_id]['input_type'], 'source': source,
               'originals': [original], 'extracted': {'path': 'extracted/content.md',
               'sha256': bytes_digest(files['extracted/content.md']), 'media_type': 'text/markdown'},
               'attachments': attached,
               'locators': [{'block_id': f'b{i}', 'artifact_path': original_path, 'location': loc}
                            for i, loc in enumerate(locs, 1)],
               'parser': {'adapter_id': adapter_id, 'adapter_version': '1.0', 'parser_version': 'offline-1',
                          'config_digest': digest({'offline': True}), 'used_ocr': False, 'used_model': False},
               'quality': {'status': 'failed' if errors else ('partial' if missing else 'complete'),
                           'errors': errors, 'missing': missing, 'evidence': evidence,
                           'statistics': {'blocks': len(locs), 'characters': len(extracted),
                                          'pages_total': 0, 'pages_extracted': 0}}}
    validate('source_package', package)
    root.mkdir(parents=True, exist_ok=False)
    for relative, payload in files.items():
        target = resolve_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(payload)
    validate_package(package, root)
    (root / 'source-package.json').write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding='utf-8')
    return package, root


def validate_package(package, package_root):
    """验证契约、真实文件哈希、UTF-8、修订及原件定位；不签发门禁通过。"""
    validate('source_package', package)
    adapter_id = package['parser']['adapter_id']
    if adapter_id not in ADAPTERS:
        raise ContractError(f'不支持的适配器: {adapter_id}')
    if package['input_type'] != ADAPTERS[adapter_id]['input_type']:
        raise ContractError('适配器与原始类型不符')
    if adapter_id == 'pdf':
        from .pdf import validate_pdf_package
        return validate_pdf_package(package, package_root)
    root = Path(package_root).resolve()
    records = package['originals'] + [package['extracted']] + package['attachments']
    seen = set()
    for record in records:
        key = record['path'].casefold()
        if key in seen:
            raise ContractError('资料包路径重复')
        seen.add(key)
        data = resolve_path(root, record['path']).read_bytes()
        if bytes_digest(data) != record['sha256']:
            raise ContractError(f'文件哈希不一致: {record["path"]}')
        if record in package['attachments'] and not data:
            raise ContractError('空附件')
    extracted = resolve_path(root, package['extracted']['path']).read_bytes().decode('utf-8', errors='strict')
    if package['quality']['status'] == 'complete' and not extracted.strip():
        raise ContractError('空抽取不能声称完整')
    revision = digest([{'path': item['path'], 'sha256': item['sha256']}
                       for item in sorted(package['originals'], key=lambda item: item['path'])])
    if revision != package['source_revision']:
        raise ContractError('source_revision 与原件清单不一致')
    original_paths = {item['path'] for item in package['originals']}
    if any(loc['artifact_path'] not in original_paths for loc in package['locators']):
        raise ContractError('定位未指向原件')
    if package['quality']['status'] == 'complete':
        if len(package['originals']) != 1:
            raise ContractError('适配器与原件数量不符')
        original = resolve_path(root, package['originals'][0]['path']).read_bytes()
        expected, _, _, resources, errors, missing, _ = _analyse(original, adapter_id)
        if errors or missing:
            raise ContractError('原件格式检查不允许 complete')
        resources = list(dict.fromkeys(resources))
        if len(resources) != len(package['attachments']):
            raise ContractError('附件覆盖不完整')
        for ref, attachment in zip(resources, package['attachments']):
            expected = expected.replace(ref, '../' + attachment['path'])
        if expected != extracted:
            raise ContractError('抽取内容与本适配器原件解析不一致')
    return package
