"""只读检查公开 Git 暂存树：白名单、私人目录、凭据、链接可达性、标题与 frontmatter。

检查对象是 Git 索引（暂存树），不是工作区：工作区存在但未跟踪的文件不构成发布可达性。

支持的链接语法：内联链接与图片（含尖括号目标）、引用式链接与图片（含短式与折叠式）、
HTML ``<a href>``。围栏代码块、行内代码与 HTML 注释内的示例不视为活跃引用。
``[[wikilink]]`` 不属于发布层语法，出现时报告为人工审查项。外部 URL 的锚点无法在本仓库内
验证，不做通过声明。任何无法解析的活跃写法都报告，不静默计为通过。
"""
import argparse
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = ('raw/', 'wiki/', 'data/', 'lessons/', 'docs/learning/',
             'docs/design/evidence/', 'references/', 'reference/',
             '.wiki-runtime/', '.learning-', '.tmp/', '.obsidian/', '.codex/',
             'tools/tests/fixtures/learning_book_i3/',
             'tools/tests/fixtures/learning_book_i4/')
SECRETS = re.compile(r'(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|'
                     r'-----BEGIN [A-Z ]*PRIVATE KEY-----|'
                     r'https?://[^\s/:]+:[^\s/@]+@(?!example\.))')

FENCE_RE = re.compile(r'^[ \t]{0,3}(?P<fence>```+|~~~+)[^\n]*\n.*?^[ \t]{0,3}(?P=fence)[ \t]*$',
                      re.M | re.S)
INLINE_CODE_RE = re.compile(r'`[^`\n]*`')
HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.S)
INLINE_LINK_RE = re.compile(
    r'(?P<bang>!?)\[(?P<label>[^\]\n]*)\]\((?P<target><[^>\n]*>|[^()\s]*)(?:\s+"[^"]*")?\)')
REF_USE_RE = re.compile(r'(?P<bang>!?)\[(?P<label>[^\]\n]+)\](?:\[(?P<ref>[^\]\n]*)\])?')
REF_DEF_RE = re.compile(r'^[ ]{0,3}\[(?P<ref>[^\]\n]+)\]:[ \t]*(?P<target><[^>\n]*>|\S+)[ \t]*$',
                        re.M)
HTML_TAG_RE = re.compile(r'<(a|img)\b(?P<attrs>[^>]*)>', re.I)
HTML_ATTR_RE = re.compile(
    r'\b(?P<name>href|src)\s*=\s*(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<bare>[^\s>]+))', re.I)
HTML_ALT_RE = re.compile(r'\balt\s*=\s*(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\'|(?P<bare>[^\s>]+))', re.I)
WIKI_LINK_RE = re.compile(r'\[\[[^\]]+\]\]')
HEADING_RE = re.compile(r'^(?P<hashes>#{1,6})[ \t]+(?P<text>.+?)[ \t]*#*[ \t]*$', re.M)
FRONTMATTER_RE = re.compile(r'\A---[ \t]*\r?\n(?P<body>.*?)(?:\r?\n)---[ \t]*(?:\r?\n|\Z)', re.S)
IMPORT_POINTER_RE = re.compile(r'\A@[^\s]+\s*$')
FIXTURE_HINT = ('/fixtures/', '/examples/')

BLOCKING = 'blocking'
REVIEW = 'review'


def path_error(name, allowed):
    parts = PurePosixPath(name).parts
    if name.startswith(FORBIDDEN) or '..' in parts:
        return '私人目录或非法路径'
    if any(p in {'__pycache__', 'node_modules', '.git'} for p in parts):
        return '缓存或嵌套仓库'
    if name.startswith('.claude/settings') or '.local.' in name or name.endswith(
            ('.sqlite', '.sqlite3', '.db', '.pem', '.key', '.pyc')):
        return '本机配置或运行文件'
    if name not in allowed:
        return '未登记到公开文件白名单'
    return None


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def index_entries(root):
    """返回 [(path, oid, mode, stage)]。"""
    raw = git(root, 'ls-files', '--stage', '-z').decode('utf-8')
    entries = []
    for entry in filter(None, raw.split('\0')):
        info, name = entry.split('\t', 1)
        mode, oid, stage = info.split()
        entries.append((name, oid, mode, stage))
    return entries


def read_blobs(root, entries):
    """用一次 git cat-file --batch 读取全部 blob 文本。"""
    if not entries:
        return {}
    request = ''.join(f'{oid}\n' for _, oid, _, _ in entries)
    raw = subprocess.run(['git', '-C', str(root), 'cat-file', '--batch'],
                         input=request.encode('ascii'), capture_output=True).stdout
    texts = {}
    pos = 0
    for _name, oid, _mode, _stage in entries:
        newline = raw.index(b'\n', pos)
        header = raw[pos:newline].decode('utf-8', errors='replace').split()
        size = int(header[2])
        start = newline + 1
        texts[_name] = raw[start:start + size].decode('utf-8-sig', errors='replace')
        pos = start + size + 1
    return texts


def _mask(match):
    """等长遮罩：非换行字符替换为空格，保持后续匹配的位置与行号不变。"""
    return re.sub(r'[^\n]', ' ', match.group(0))


def strip_inactive(text):
    """去掉 HTML 注释、围栏代码块与行内代码；保持长度与行号不变。"""
    text = HTML_COMMENT_RE.sub(_mask, text)
    text = FENCE_RE.sub(_mask, text)
    return INLINE_CODE_RE.sub(lambda m: ' ' * len(m.group(0)), text)


def strip_code(text):
    """兼容旧调用：只去掉代码块与行内代码。"""
    return strip_inactive(text)


def slugify(text):
    """GitHub 风格标题锚点（小写、去标点、空格转连字符）。"""
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'[`*_~]', '', text)
    out = []
    for ch in text.strip().lower():
        if ch.isalnum() or unicodedata.category(ch)[0] == 'L':
            out.append(ch)
        elif ch in {' ', '\t'}:
            out.append('-')
        elif ch in {'-', '_'}:
            out.append(ch)
    return re.sub(r'-+', '-', ''.join(out)).strip('-')


def active_headings(text):
    """正文中的活跃标题锚点集合。

    - 标题取自原文可见文字（行内代码中的文字保留在锚点里）。
    - 排除围栏代码块与 HTML 注释中的伪标题。
    - 生成结果全局唯一：与既有锚点冲突时追加 -1、-2 直到不冲突。
    """
    body = text
    match = FRONTMATTER_RE.match(text)
    if match:
        body = text[match.end():]
    masked = strip_inactive(body)
    anchors = set()
    for heading in HEADING_RE.finditer(masked):
        raw = body[heading.start('text'):heading.end('text')]
        slug = slugify(raw)
        if not slug:
            continue
        candidate = slug
        counter = 1
        while candidate in anchors:
            candidate = f'{slug}-{counter}'
            counter += 1
        anchors.add(candidate)
    return anchors


def headings_of(text):
    """兼容旧调用：活跃标题锚点集合。"""
    return active_headings(text)


def frontmatter_title(text):
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    for line in match.group('body').splitlines():
        if line.startswith('title:'):
            return line.split(':', 1)[1].strip().strip('"\'')
    return None


def has_h1(text):
    body = text
    match = FRONTMATTER_RE.match(text)
    if match:
        body = text[match.end():]
    body = strip_inactive(body)
    return any(line.startswith('# ') for line in body.splitlines())


def normalize_ref(key):
    return re.sub(r'\s+', ' ', key.strip().lower())


def is_absolute_local(target):
    if target.startswith('/') or target.startswith('\\'):
        return True
    return bool(re.match(r'^[A-Za-z]:[\\/]', target))


def resolve_link(source_path, target):
    """返回 (kind, resolved_path, anchor)。kind: relative/absolute/external/fragment/uri/escape。

    路径与片段分别做 URL 解码，纯片段链接同样解码。
    """
    if target.startswith(('http://', 'https://', 'mailto:', 'tel:', 'ftp://')):
        return 'external', None, ''
    if target.lower().startswith(('file:', 'vscode:', 'obsidian:')):
        return 'uri', None, ''
    if target.startswith('#'):
        return 'fragment', source_path, unquote(target[1:])
    path, sep, anchor = target.partition('#')
    path = path.split('?')[0]
    decoded_path = unquote(path)
    decoded_anchor = unquote(anchor) if sep else ''
    if is_absolute_local(decoded_path):
        return 'absolute', None, ''
    if not decoded_path:
        return 'fragment', source_path, decoded_anchor
    base = PurePosixPath(source_path).parent
    parts = []
    for part in (base / decoded_path).parts:
        if part == '.':
            continue
        if part == '..':
            if not parts:
                return 'escape', None, decoded_anchor
            parts.pop()
            continue
        parts.append(part)
    return 'relative', '/'.join(parts), decoded_anchor


def _clean_target(target):
    target = target.strip()
    if target.startswith('<') and target.endswith('>'):
        target = target[1:-1].strip()
    return target


def _read_target(body, pos):
    """读取链接目标：支持尖括号目标与配对括号。返回 (target, end) 或 (None, pos)。"""
    n = len(body)
    i = pos
    while i < n and body[i] in ' \t':
        i += 1
    if i < n and body[i] == '<':
        j = body.find('>', i + 1)
        if j == -1:
            return None, pos
        return body[i + 1:j].strip(), j + 1
    depth = 0
    start = i
    while i < n:
        ch = body[i]
        if ch == '\\' and i + 1 < n:
            i += 2
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                break
            depth -= 1
        elif ch in ' \t\n' and depth == 0:
            break
        i += 1
    return body[start:i], i


def _read_title(body, pos):
    """读取可选链接标题。返回 (title, end) 或 (None, pos)。"""
    n = len(body)
    i = pos
    while i < n and body[i] in ' \t':
        i += 1
    if i < n and body[i] in '"\'':
        quote = body[i]
        j = body.find(quote, i + 1)
        if j == -1:
            return None, pos
        return body[i + 1:j], j + 1
    if i < n and body[i] == '(':
        j = body.find(')', i + 1)
        if j == -1:
            return None, pos
        return body[i + 1:j], j + 1
    return None, pos


def _scan_inline_links(body):
    """扫描 [label](target) 与 ![label](target)。

    返回 [{start, end, label_start, label_end, target, bang, broken}]。
    broken=True 表示明显是链接但目标无法解析，必须报告而不是放行。
    """
    out = []
    n = len(body)
    i = 0
    while i < n:
        ch = body[i]
        if ch == '!' and i + 1 < n and body[i + 1] == '[':
            bang = True
            start = i
            label_open = i + 1
        elif ch == '[':
            bang = False
            start = i
            label_open = i
        else:
            i += 1
            continue
        label_close = body.find(']', label_open + 1)
        if label_close == -1:
            i = start + 1
            continue
        p = label_close + 1
        while p < n and body[p] in ' \t':
            p += 1
        if p >= n or body[p] != '(':
            i = start + 1
            continue
        target, after = _read_target(body, p + 1)
        title, after_title = _read_title(body, after)
        close = after_title
        while close < n and body[close] in ' \t':
            close += 1
        if target is None or close >= n or body[close] != ')':
            out.append({'start': start, 'end': label_close + 1,
                        'label_start': label_open + 1, 'label_end': label_close,
                        'target': None, 'bang': bang, 'broken': True})
            i = start + 1
            continue
        out.append({'start': start, 'end': close + 1,
                    'label_start': label_open + 1, 'label_end': label_close,
                    'target': _clean_target(target), 'bang': bang, 'broken': False})
        i = close + 1
    return out


def _scan_definitions(body):
    """扫描引用式链接定义，支持可选标题。返回 {ref_key: target}。"""
    definitions = {}
    pattern = re.compile(r'^[ ]{0,3}\[(?P<ref>[^\]\n]+)\]:[ \t]*', re.M)
    for match in pattern.finditer(body):
        target, after = _read_target(body, match.end())
        if target is None:
            continue
        _title, after_title = _read_title(body, after)
        close = after_title
        while close < len(body) and body[close] in ' \t':
            close += 1
        if close < len(body) and body[close] != '\n':
            continue
        definitions.setdefault(normalize_ref(match.group('ref')), _clean_target(target))
    return definitions


def link_targets(text):
    """产出 (line, label, target, kind)。kind: inline/image/ref/html/wiki/unresolved/broken。

    kind=unresolved 表示引用式链接缺少定义；kind=broken 表示明显是链接但无法解析。
    两者都必须报告，不能静默放行。
    """
    body = strip_inactive(text)
    results = []
    inline_spans = []

    for item in _scan_inline_links(body):
        inline_spans.append((item['start'], item['end']))
        label = text[item['label_start']:item['label_end']]
        line = body.count('\n', 0, item['start']) + 1
        if item['broken']:
            results.append((line, label, '', 'broken'))
            continue
        results.append((line, label, item['target'],
                        'image' if item['bang'] else 'inline'))

    # 定义行：从正文中屏蔽，避免与短式引用混淆
    definitions = _scan_definitions(body)
    masked = re.sub(r'^[ ]{0,3}\[[^\]\n]+\]:[ \t]*[^\n]*$',
                    lambda m: ' ' * len(m.group(0)), body, flags=re.M)

    for match in REF_USE_RE.finditer(masked):
        if any(start <= match.start() < end for start, end in inline_spans):
            continue
        label = text[match.start('label'):match.end('label')]
        explicit = match.group('ref')
        if explicit is not None:
            key = normalize_ref(explicit) or normalize_ref(label)
            if key in definitions:
                target = definitions[key]
            else:
                results.append((masked.count('\n', 0, match.start()) + 1, label, '',
                                'unresolved'))
                continue
        else:
            key = normalize_ref(label)
            if key not in definitions:
                continue
            target = definitions[key]
        results.append((masked.count('\n', 0, match.start()) + 1, label, target,
                        'image' if match.group('bang') else 'ref'))

    for match in HTML_TAG_RE.finditer(body):
        tag = match.group(1).lower()
        attrs = match.group('attrs')
        wanted = 'href' if tag == 'a' else 'src'
        attr = None
        for candidate in HTML_ATTR_RE.finditer(attrs):
            if candidate.group('name').lower() == wanted:
                attr = candidate
                break
        if attr is None:
            continue
        target = (attr.group('dq') or attr.group('sq') or attr.group('bare') or '').strip()
        line = body.count('\n', 0, match.start()) + 1
        if tag == 'a':
            close = body.find('</a>', match.end())
            inner = text[match.end():close] if close != -1 else ''
            label = re.sub(r'<[^>]+>', '', inner).strip()
            results.append((line, label, target, 'html'))
        else:
            alt = HTML_ALT_RE.search(attrs)
            label = ''
            if alt:
                label = (alt.group('dq') or alt.group('sq') or alt.group('bare') or '').strip()
            results.append((line, label, target, 'image'))

    for match in WIKI_LINK_RE.finditer(body):
        results.append((body.count('\n', 0, match.start()) + 1, match.group(0), '',
                        'wiki'))
    return results


def check_tree(files, allowed, worktree_root=None, exceptions=None):
    """files: {path: text}；allowed: 白名单集合；exceptions: 精确例外列表。"""
    issues = []
    tracked = set(files)
    exceptions = exceptions or []
    used_exceptions = set()

    def add(path, line, code, message, severity=BLOCKING):
        issues.append({'path': path, 'line': line, 'code': code,
                       'message': message, 'severity': severity})

    for path in sorted(files):
        reason = path_error(path, allowed)
        if reason:
            add(path, 0, 'path', reason)
            continue
        text = files[path]
        for match in SECRETS.finditer(text):
            line = text.count('\n', 0, match.start()) + 1
            hit = {'path': path, 'line': line, 'code': 'secret',
                   'message': '疑似凭据（不输出值）', 'severity': BLOCKING}
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
            for index, exc in enumerate(exceptions):
                if (exc.get('path') == path and exc.get('code', 'secret') == 'secret'
                        and exc.get('digest') == digest
                        and exc.get('line') in (None, line)
                        and exc.get('reason')):
                    used_exceptions.add(index)
                    hit['severity'] = REVIEW
                    hit['message'] = f"疑似凭据（已登记例外：{exc['reason']}）"
                    break
            add(path, line, hit['code'], hit['message'], hit['severity'])
        if not path.endswith('.md'):
            continue
        if text.startswith('---') and not FRONTMATTER_RE.match(text):
            add(path, 1, 'frontmatter', 'frontmatter 未闭合')
        exempt_title = (IMPORT_POINTER_RE.match(text.strip().splitlines()[0] if text.strip() else '')
                        is not None
                        or any(hint in path for hint in FIXTURE_HINT))
        if not exempt_title and not has_h1(text) and not frontmatter_title(text):
            add(path, 1, 'title', '缺少一级标题或 frontmatter title')
        for line, label, target, kind in link_targets(text):
            if kind == 'unresolved':
                add(path, line, 'ref', '引用式链接缺少定义', REVIEW)
                continue
            if kind == 'broken':
                add(path, line, 'unparsed-link',
                    '链接写法无法解析（目标缺失或括号未闭合），需人工确认后再发布')
                continue
            if kind == 'wiki':
                add(path, line, 'wiki', 'wikilink 不属于发布层语法，需人工确认', REVIEW)
                continue
            if kind in ('inline', 'ref', 'image') and label.strip() in {'', '---', '…', '...'}:
                add(path, line, 'empty-label', '空链接标签或占位标签')
            if kind == 'html' and not target:
                add(path, line, 'empty-target', 'HTML 链接目标为空')
                continue
            if not target:
                add(path, line, 'empty-target', '链接目标为空')
                continue
            kind_resolved, resolved, anchor = resolve_link(path, target)
            if kind_resolved == 'external':
                continue
            if kind_resolved == 'absolute':
                add(path, line, 'absolute-path', '链接指向本机绝对路径，发布后不可达')
                continue
            if kind_resolved == 'uri':
                add(path, line, 'uri', '链接使用非 http(s) URI，发布后不可达')
                continue
            if kind_resolved == 'escape':
                add(path, line, 'escape', '链接越出仓库根目录')
                continue
            if kind_resolved == 'fragment':
                if resolved in files:
                    if anchor and anchor not in active_headings(files[resolved]):
                        add(path, line, 'anchor', f'锚点 #{anchor} 在目标文档中不存在')
                continue
            if resolved in tracked:
                if anchor and resolved.endswith('.md'):
                    if anchor not in active_headings(files[resolved]):
                        add(path, line, 'anchor', f'锚点 #{anchor} 在目标文档中不存在')
                continue
            prefix = resolved.rstrip('/') + '/'
            if any(name.startswith(prefix) for name in tracked):
                # 目录链接：暂存树内存在受跟踪文件即视为可达
                continue
            if worktree_root is not None and (Path(worktree_root) / resolved).exists():
                add(path, line, 'unpublished-target',
                    f'链接目标未随仓库发布（工作区存在但未跟踪）：{resolved}')
            else:
                add(path, line, 'unpublished-target',
                    f'链接目标不在暂存树：{resolved or target}')
    for index, exc in enumerate(exceptions):
        if index not in used_exceptions:
            add(exc.get('path', '?'), exc.get('line', 0), 'exception-stale',
                f'精确例外未命中或文件摘要已变化，需重新登记：{exc.get("reason", "")}')
    return issues


def check(root=ROOT):
    entries = index_entries(root)
    manifest = json.loads(git(root, 'show', ':public-files.json'))
    allowed = set(manifest['files'])
    exceptions = manifest.get('exceptions', [])
    errors = []
    for name, oid, mode, stage in entries:
        if mode not in {'100644', '100755'} or stage != '0':
            errors.append({'path': name, 'line': 0, 'code': 'mode',
                           'message': '链接、子模块或未解决合并', 'severity': BLOCKING})
    files = {}
    normal = [e for e in entries if e[2] in {'100644', '100755'} and e[3] == '0']
    texts = read_blobs(root, normal)
    for name, _oid, _mode, _stage in normal:
        files[name] = texts.get(name, '')
    issues = check_tree(files, allowed, worktree_root=root, exceptions=exceptions)
    issues.extend(errors)
    return len(entries), issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='检查完整暂存树（默认行为）')
    parser.add_argument('--json', action='store_true', help='输出机器可读问题列表')
    args = parser.parse_args()
    try:
        count, issues = check()
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f'公开检查失败: {type(exc).__name__}')
        raise SystemExit(1)
    blocking = [i for i in issues if i['severity'] == BLOCKING]
    if args.json:
        print(json.dumps({'checked': count, 'issues': issues}, ensure_ascii=False, indent=1))
    else:
        for issue in issues:
            location = f"{issue['path']}:{issue['line']}" if issue['line'] else issue['path']
            marker = '' if issue['severity'] == BLOCKING else '（人工审查）'
            print(f"{location}: [{issue['code']}] {issue['message']}{marker}")
        print(f'检查 {count} 个公开文件，发现 {len(issues)} 项问题（阻断 {len(blocking)}）。')
    raise SystemExit(bool(blocking))


if __name__ == '__main__':
    main()
