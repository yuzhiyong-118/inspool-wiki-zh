"""基于候选快照的保守门禁，不修改正式库。"""
import importlib.util
import json
import re
from pathlib import Path

from ..contracts import validate, digest, bytes_digest, candidate_digest, resolve_path

VALIDATOR_VERSION = 'gates-1.0'
MAPPING_PATH = 'tools/wiki_runtime/contracts/rules.json'
FLOW_FIELDS = {'processing_status', 'reviewed_at', 'processed_at', 'processed_into', 'ingest_group'}
REL_FIELDS = {'supports', 'contradicts', 'related_entities', 'related_concepts', 'related_sources', 'related_synthesis'}
BINDINGS = ('operation_id', 'candidate_digest', 'dependencies_digest', 'rules_digest', 'mapping_digest', 'validator_version', 'review_prompt_version')


def _scalar(value):
    if value.startswith(('"', '[')):
        parsed = json.loads(value)
        if not isinstance(parsed, (str, list)) or isinstance(parsed, list) and not all(isinstance(x, str) for x in parsed):
            raise ValueError('仅支持字符串及字符串列表')
    elif value.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", value):
            raise ValueError('畸形单引号字符串')
    elif value.startswith(('|', '>', '&', '*', '!', '{', ']', '}', '?', '`', '@')) or ': ' in value:
        raise ValueError('不支持或畸形 YAML 标量')


def raw_parts(data):
    """返回完整原始 FM 字段块和原始正文；不重序列化、不宽容丢弃 YAML。"""
    data.decode('utf-8')
    lines = data.splitlines(keepends=True)
    if not lines or lines[0].removeprefix(b'\xef\xbb\xbf').rstrip(b'\r\n') != b'---':
        return {}, data
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip(b'\r\n') == b'---'), None)
    if end is None:
        raise ValueError('frontmatter 缺少独立闭合标记')
    fields, current = {}, None
    for line in lines[1:end]:
        text = line.decode('utf-8').rstrip('\r\n')
        match = re.fullmatch(r'([A-Za-z_][A-Za-z_0-9-]*):(?:[ \t]+(.*))?', text)
        if match:
            current = match[1]
            if current in fields:
                raise ValueError('重复 frontmatter 字段: ' + current)
            value = match[2] or ''
            # Deliberately narrow grammar: unsupported YAML must never disappear.
            _scalar(value)
            fields[current] = line
        elif not text.strip() or text.lstrip().startswith('#'):
            # Comments/blank lines remain protected independently, even in flow fields.
            fields['@layout'] = fields.get('@layout', b'') + line
        elif current and re.fullmatch(r'[ \t]+- .+', text):
            _scalar(text.lstrip()[2:])
            fields[current] += line
        else:
            raise ValueError('未知或畸形 frontmatter 语法: ' + text)
    return fields, b''.join(lines[end + 1:])


def _health(root):
    spec = importlib.util.spec_from_file_location('_isolated_gate_health', Path(__file__).parents[2] / 'health.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WIKI_ROOT = Path(root) / 'wiki'
    module.RAW_ROOT = Path(root) / 'raw'
    module.META_DIR = module.WIKI_ROOT / 'meta'
    module.HEALTH_REPORT = module.WIKI_ROOT / 'health-report.md'
    return module, module.run_health()


def _flatten(checks):
    result = set()
    def walk(value, trail):
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, trail + (str(key),))
        elif isinstance(value, list):
            for child in value:
                walk(child, trail)
        elif value:
            result.add(trail + (str(value),))
    walk(checks, ())
    return result


def run_gates(manifest, candidate, dependency_snapshot, view, *,
              validator_version=VALIDATOR_VERSION, review_prompt_version='none'):
    """返回合法 gate_report 列表。畸形契约抛 ContractError；运行错误从不通过。

    调用者提供可信版本配置；view.root 是当前正式根，materialize() 是临时只读快照。
    G3/G4/G5 必需时标 unsupported，不能由模型提交的报告替代。
    """
    for kind, record in [('manifest', manifest), ('candidate', candidate), ('dependency_snapshot', dependency_snapshot)]:
        validate(kind, record)
    reports = []
    def report(gate):
        value = {'contract_version': '1.0', **{k: manifest[k] for k in BINDINGS},
                 'gate': gate, 'result': 'pass', 'findings': [], 'producer': 'deterministic-runner'}
        reports.append(value)
        return value
    def add(r, rule, target, evidence, expected, severity='blocking'):
        r['findings'].append(dict(rule_id=rule, severity=severity, category='deterministic',
                                  target=str(target), evidence=str(evidence), expected=expected, repairable=True))
        if severity == 'blocking':
            r['result'] = 'fail'
    root = Path(view.root)
    g0 = report('G0')
    try:
        if getattr(view, 'candidate', candidate) != candidate:
            raise ValueError('view 绑定了不同候选')
        expected = dict(operation_id=candidate['operation_id'], candidate_digest=candidate_digest(candidate),
                        dependencies_digest=digest(dependency_snapshot),
                        rules_digest=bytes_digest(resolve_path(root, 'AGENTS.md').read_bytes()),
                        mapping_digest=bytes_digest(resolve_path(root, MAPPING_PATH).read_bytes()),
                        validator_version=validator_version, review_prompt_version=review_prompt_version)
        for key, value in expected.items():
            if manifest[key] != value or (key == 'operation_id' and dependency_snapshot[key] != value):
                add(g0, 'BINDING-001', key, '绑定不一致', '重新读取输入并生成 manifest')
        allowed = set(manifest['allowed_paths'])
        for entry in dependency_snapshot['files'] + candidate['changes']:
            path, pre = entry['path'], entry['precondition']
            target = resolve_path(root, path)
            ok = not target.exists() if pre['kind'] == 'absent' else target.is_file() and bytes_digest(target.read_bytes()) == pre['sha256']
            if not ok:
                add(g0, 'BINDING-001', path, '文件前提已变化', '重读文件并重新审查')
        for change in candidate['changes']:
            for path in [change['path']] + ([change['source']] if change['action'] == 'move' else []):
                if path not in allowed:
                    add(g0, 'PATH-001', path, '不在精确文件白名单', '由可信运行器明确授权此文件')
                resolve_path(root, path)
                operation = manifest['operation_type']
                scope_ok = path.startswith(('wiki/', 'raw/'))
                if operation == 'rule_maintenance':
                    scope_ok = path == 'AGENTS.md' or path.startswith('wiki/')
                elif operation == 'tool_maintenance':
                    scope_ok = path.startswith('tools/')
                if not scope_ok:
                    add(g0, 'PATH-001', path, '操作类型不允许此业务路径', '使用对应维护操作并由可信运行器授权')
            if change['action'] == 'move' and (change['source'].startswith('raw/') or change['path'].startswith('raw/')):
                if not (manifest['operation_type'] == 'approve' and change['source'].startswith('raw/unprocessed/') and change['path'].startswith('raw/processed/')):
                    add(g0, 'PATH-001', change['path'], 'raw 迁移只允许 approve 的 unprocessed → processed', '按批准批次迁移，禁止跨层绕过状态检查')
            if change['action'] == 'move':
                if bytes_digest(resolve_path(root, change['source']).read_bytes()) != change['source_sha256']:
                    add(g0, 'BINDING-001', change['source'], '移动源哈希变化', '重建候选')
            if 'sha256' in change and bytes_digest(view.read_bytes(change['path'])) != change['sha256']:
                add(g0, 'BINDING-001', change['path'], '候选 payload 哈希不符', '重建候选')
        if hasattr(view, 'verify_dependencies'):
            view.verify_dependencies(dependency_snapshot)
    except Exception as exc:
        add(g0, 'CONTRACT-001', 'candidate', repr(exc), '修正输入或快照读取错误')
        g0['result'] = 'error'
    for gate in ('G1', 'G2'):
        r = report(gate)
        if g0['result'] != 'pass':
            add(r, 'BINDING-001', 'G0', '前置门禁未通过', '先修复 G0')
            r['result'] = 'error'
            continue
        try:
            if gate == 'G1':
                _raw_gate(manifest, candidate, view, r, add)
            else:
                _structure_gate(manifest, candidate, view, r, add)
        except Exception as exc:
            add(r, 'CONTRACT-001', gate, repr(exc), '修正未知或畸形输入后重跑')
            r['result'] = 'error'
    for gate in manifest['required_gates']:
        if gate not in ('G0', 'G1', 'G2'):
            r = report(gate)
            add(r, 'CONTRACT-001', gate, '此确定性执行器未实现该门禁', '交给可信运行器的独立实现')
            r['result'] = 'unsupported'
    if hasattr(view, 'dependency_snapshot') and g0['result'] == 'pass':
        try:
            view.verify_dependencies(dependency_snapshot)
            if digest(view.dependency_snapshot()) != manifest['dependencies_digest']:
                raise ValueError('检查读取集超出已绑定依赖；须先完整快照再冻结 manifest')
        except Exception as exc:
            add(g0, 'BINDING-001', 'dependency_snapshot', repr(exc), '预读完整候选及基线后重建绑定')
            for r in reports:
                if r['gate'] in ('G1', 'G2'):
                    add(r, 'BINDING-001', 'G0', '最终依赖绑定失效', '修复 G0 并重跑')
                    r['result'] = 'error'
    return [validate('gate_report', r) for r in reports]


def _raw_gate(manifest, candidate, view, r, add):
    for c in candidate['changes']:
        source = c.get('source', c['path'])
        if not source.startswith('raw/') and not c['path'].startswith('raw/'):
            continue
        if source == 'raw/index.md' and c['path'] == source:
            continue
        if c['action'] == 'delete':
            add(r, 'RAW-001', source, '禁止删除原始资料', '保留原始资料')
            continue
        oldpath = resolve_path(view.root, source)
        new = view.read_bytes(c['path'])
        if source.startswith('raw/assets/') or c['path'].startswith('raw/assets/'):
            if oldpath.exists() or manifest['operation_type'] not in ('capture', 'import') or not c['path'].startswith('raw/assets/'):
                add(r, 'RAW-001', c['path'], '既有原始附件只读；新附件仅允许采集/导入', '保留附件原始字节')
            continue
        newfm, body = raw_parts(new)
        if not oldpath.exists():
            if manifest['operation_type'] not in ('capture', 'import') or not c['path'].startswith('raw/unprocessed/'):
                add(r, 'RAW-001', c['path'], '仅采集/导入可登记新 raw', '在候选区采集并登记 unprocessed')
            continue
        oldfm, oldbody = raw_parts(oldpath.read_bytes())
        if oldbody != body:
            add(r, 'RAW-001', source, 'raw 正文原始字节变化', '保持正文每个字节')
        if {k: v for k, v in oldfm.items() if k not in FLOW_FIELDS} != {k: v for k, v in newfm.items() if k not in FLOW_FIELDS}:
            add(r, 'RAW-002', source, '非白名单 frontmatter 原始字段块变化', '仅修改五个流程字段')


def _structure_gate(manifest, candidate, view, r, add):
    changed = {c['path'] for c in candidate['changes']}
    with view.materialize() as staged:
        h, after = _health(staged)
        _, before = _health(view.root)
        baseline = _flatten(before['checks'])
        for item in sorted(_flatten(after['checks'])):
            touched = any(p.removeprefix('wiki/').removesuffix('.md') in '/'.join(item) for p in changed)
            severity = 'warning' if item in baseline and not touched else 'blocking'
            # AGENTS 推荐字段不升级为强制模板。
            if item[0] == 'frontmatter':
                severity = 'warning'
            add(r, 'FM-001' if item[0] == 'frontmatter' else 'HEALTH-001', '/'.join(item[:-1]) or 'wiki',
                ('基线: ' if item in baseline else '') + item[-1], '修复结构问题；推荐字段按需补充', severity)
        paths = [p for p in Path(staged).rglob('*.md') if p.relative_to(staged).parts[0] in ('wiki', 'raw')]
        names, rel = h.page_maps(paths)
        pages = {p.relative_to(staged).as_posix(): p for p in paths}
        content = {k: p for k, p in pages.items() if k.startswith(tuple('wiki/' + d + '/' for d in h.CONTENT_DIRS))}
        newpages = {k for k in content if k in changed and not resolve_path(view.root, k).exists()}
        index = h.parse_wikilinks(pages['wiki/index.md'].read_text(encoding='utf-8')) if 'wiki/index.md' in pages else []
        indexed = {h.resolve_page(x, names, rel) for x in index}
        for path in changed & set(pages):
            if not path.startswith('wiki/'):
                continue
            data = pages[path].read_bytes()
            raw_parts(data)  # 不将未知 YAML 静默解释为有效。
            text = data.decode('utf-8')
            for link in h.parse_wikilinks(text):
                target, _, anchor = link.partition('#')
                resolved = h.resolve_page(target, names, rel) if target else pages[path]
                if anchor and resolved:
                    target_text = h.link_text(resolved.read_text(encoding='utf-8'))
                    headings = {m[1].strip().rstrip('#').strip() for m in re.finditer(r'(?m)^#{1,6}\s+(.+)$', target_text)}
                    blocks = set(re.findall(r'(?m)\^([\w-]+)\s*$', target_text))
                    if anchor not in headings and not (anchor.startswith('^') and anchor[1:] in blocks):
                        add(r, 'HEALTH-001', path, '无效锚点 [[' + link + ']]', '使用实际标题或块 ID')
            if path in content and pages[path] not in indexed:
                add(r, 'INDEX-001', path, '候选内容页未收录索引', '更新 wiki/index.md')
        if manifest['operation_type'] == 'ingest':
            for new in newpages:
                incoming = []
                for old, page in content.items():
                    if old != new and any(h.resolve_page(x, names, rel) == pages[new] for x in h.parse_wikilinks(page.read_text(encoding='utf-8'))):
                        incoming.append(old)
                if not incoming:
                    add(r, 'REL-001', new, '新页无内容页入边', '补入内容页关系')
                for link in h.parse_wikilinks(pages[new].read_text(encoding='utf-8')):
                    old = h.resolve_page(link, names, rel)
                    if old is None or old == pages[new]:
                        continue
                    oldkey = old.relative_to(staged).as_posix()
                    if oldkey not in content or oldkey in newpages:
                        continue
                    oldtext = old.read_text(encoding='utf-8')
                    fields, oldbody = raw_parts(old.read_bytes())
                    fm_edges = h.parse_wikilinks(''.join(v.decode('utf-8') for k, v in fields.items() if k in REL_FIELDS))
                    body_edges = h.parse_wikilinks(oldbody.decode('utf-8'))
                    if not all(any(h.resolve_page(x, names, rel) == pages[new] for x in edges) for edges in (fm_edges, body_edges)):
                        add(r, 'REL-001', oldkey, '缺少指向 ' + new + ' 的关系字段/正文双通道反向边', '同时补 frontmatter 与正文关联说明')
                    if oldkey not in changed or not h.parse_frontmatter(oldtext).get('updated'):
                        add(r, 'REL-001', oldkey, '关联旧页未随候选更新', '更新旧页及 updated')
        _state_gate(manifest, candidate, view, pages, content, h, names, rel, changed, r, add)


def _state_gate(manifest, candidate, view, pages, content, h, names, rel, changed, r, add):
    operation = manifest['operation_type']
    wiki_changed = any(p in content for p in changed)
    if wiki_changed:
        required = {'wiki/index.md', 'wiki/log.md'}
        if operation == 'ingest':
            required |= {'wiki/meta/overview.md', 'raw/index.md'}
        for path in required - changed:
            add(r, 'INDEX-001', path, '缺少配套候选更新', '将配套文件纳入同一候选')
    raw_changes = [c for c in candidate['changes'] if c['path'].startswith(('raw/unprocessed/', 'raw/processed/'))]
    if operation == 'ingest' and wiki_changed and not raw_changes:
        add(r, 'STATE-001', 'raw/unprocessed', 'ingest 未包含原始资料状态', '同批更新选定 raw 为 pending_review')
    # 同一子目录或显式 ingest_group 是业务批次，不允许只推进其中一部分。
    selected = {c.get('source', c['path']) for c in raw_changes}
    originals = {}
    for path in (Path(view.root) / 'raw/unprocessed').rglob('*.md'):
        key = path.relative_to(view.root).as_posix()
        originals[key] = h.parse_frontmatter(path.read_text(encoding='utf-8'))
    if operation in ('ingest', 'approve'):
        for selected_path in selected:
            oldfm = originals.get(selected_path, {})
            parent = selected_path.rsplit('/', 1)[0]
            group = oldfm.get('ingest_group')
            peers = {key for key, fm in originals.items() if
                     (group and fm.get('ingest_group') == group) or
                     (parent != 'raw/unprocessed' and key.rsplit('/', 1)[0] == parent)}
            for peer in peers - selected:
                add(r, 'STATE-001' if operation == 'ingest' else 'APPROVE-002', peer,
                    '同批次 raw 未纳入候选', '整组处理，避免业务状态分裂')
    for c in raw_changes:
        if c['action'] == 'delete' or c['path'] not in pages:
            continue
        fm = h.parse_frontmatter(pages[c['path']].read_text(encoding='utf-8'))
        state = fm.get('processing_status')
        if operation == 'ingest':
            if state != 'pending_review' or c['action'] == 'move' or c['path'].startswith('raw/processed/'):
                add(r, 'STATE-001', c['path'], 'ingest 必须停留 pending_review/unprocessed', '保留原路径并设置 pending_review')
            sources = [h.resolve_page(x, names, rel) for x in h.parse_wikilinks(str(fm.get('processed_into', '')))]
            if not sources or any(p is None or not p.is_relative_to(Path(h.WIKI_ROOT) / 'sources') for p in sources):
                add(r, 'STATE-001', c['path'], '缺失有效来源页映射', '创建本地来源页并设置 processed_into')
            for path in {'wiki/index.md', 'wiki/log.md', 'wiki/meta/overview.md', 'raw/index.md'} - changed:
                add(r, 'STATE-001', path, 'pending_review 缺少配套更新', '同批完成 wiki/overview/log/raw index')
        elif operation == 'approve':
            old = c.get('source', '')
            if originals.get(old, {}).get('processing_status') != 'pending_review':
                add(r, 'APPROVE-002', old or c['path'], 'approve 原始状态并非 pending_review', '先完成 ingest 并审阅对应候选')
            if c['action'] != 'move' or not old.startswith('raw/unprocessed/') or not c['path'].startswith('raw/processed/') or state != 'processed' or not fm.get('reviewed_at'):
                add(r, 'APPROVE-002', c['path'], 'approve 迁移/状态/日期不配套', '同批迁移并设置 processed 与 reviewed_at')
            for p, page in pages.items():
                if p.startswith('wiki/') and old and old.removesuffix('.md') in page.read_text(encoding='utf-8'):
                    add(r, 'APPROVE-002', p, '残留旧 raw 路径 ' + old, '修正 frontmatter 与正文全部旧引用')
            for path in {'raw/index.md', 'wiki/log.md'} - changed:
                add(r, 'APPROVE-002', path, 'approve 缺少配套更新', '同批更新 raw index 与日志')
        elif operation in ('capture', 'import') and state != 'unprocessed':
            add(r, 'STATE-001', c['path'], '采集必须登记 unprocessed', '设置 unprocessed')
        elif operation not in ('capture', 'import', 'ingest', 'approve'):
            oldpath = resolve_path(view.root, c.get('source', c['path']))
            if oldpath.exists() and state != h.parse_frontmatter(oldpath.read_text(encoding='utf-8')).get('processing_status'):
                add(r, 'STATE-001', c['path'], '当前操作不允许推进 raw 状态', '使用 ingest 或 approve 流程')
