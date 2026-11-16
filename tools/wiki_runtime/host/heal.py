"""只读 heal 计划与可信宿主接入；建议不携带写权限或免审凭证。"""
from __future__ import annotations

import copy
from difflib import get_close_matches
import importlib.util
from pathlib import Path
import tempfile

from ..candidate import CandidateView
from ..contracts import canonical_json, digest
from .supervisor import HostError


def _view(root, operation_id):
    return CandidateView(root, dict(contract_version='1.0', operation_id=operation_id,
                                    changes=[]), Path(tempfile.gettempdir()))


def _health(root):
    spec = importlib.util.spec_from_file_location('_heal_readonly_health',
                                                Path(__file__).parents[2] / 'health.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.WIKI_ROOT, module.RAW_ROOT = root / 'wiki', root / 'raw'
    module.HEALTH_REPORT = module.WIKI_ROOT / 'health-report.md'
    return module


def build_heal_plan(root, *, operation_id='heal-plan', min_refs=3):
    """纯只读扫描；完整文件/目录前提绑定，分类子目录递归保留。

    模糊匹配只给出建议；缺页只报告待判定，不自动授权新页或生成桩。
    """
    if type(min_refs) is not int or min_refs < 1:
        raise HostError('min_refs 必须为正整数')
    view = _view(root, operation_id)
    paths = list(view.iter_paths())
    root = view.root
    h = _health(root)
    wiki = [p for p in paths if p.startswith('wiki/') and p.endswith('.md')
            and p != 'wiki/health-report.md']
    content = [p for p in wiki if p.split('/')[1] in h.CONTENT_DIRS]
    maps = h.page_maps([root / p for p in paths if p.endswith('.md')
                       and p.startswith(('wiki/', 'raw/')) and p != 'wiki/health-report.md'])
    actions, affected, refs, missing = [], set(), set(), {}
    # Preserve each ambiguous destination. A basename collision never selects a winner.
    options = {p: p[5:-3] for p in content}
    for path in content:
        for target in h.parse_wikilinks(view.read_text(path)):
            base = target.split('#', 1)[0]
            if not base or base.startswith(('raw/', 'wiki/raw/')) or h.page_exists(base, *maps):
                continue
            missing.setdefault(base, set()).add(path)
            matches = get_close_matches(base.rsplit('/', 1)[-1].casefold(),
                                        sorted({Path(p).stem.casefold() for p in options}),
                                        n=5, cutoff=0.85)
            candidates = sorted(p for p in options if Path(p).stem.casefold() in matches)
            actions.append(dict(type='review_broken_link', path=path, target=target,
                                candidates=candidates, requires_review=True))
            affected.add(path)
            refs.update(candidates)
    for target, referrers in sorted(missing.items()):
        if len(referrers) >= min_refs:
            actions.append(dict(type='investigate_missing_page', target=target,
                                referrers=sorted(referrers), requires_review=True,
                                instruction='核查来源和概念边界；本计划不授权新建桩页。'))
    if 'wiki/index.md' in paths:
        links = h.parse_index_links(view.read_text('wiki/index.md'))
        absent = sorted(p for p in wiki if p not in ('wiki/index.md', 'wiki/log.md')
                        and not any(h.resolve_page(link, *maps) == root / p for link in links))
        orphan = sorted(link for link in links if not h.page_exists(link, *maps))
        if absent or orphan:
            actions.append(dict(type='review_index', path='wiki/index.md',
                                missing_pages=absent, unresolved_entries=orphan, requires_review=True))
            affected.add('wiki/index.md')
            refs.update(absent)
    if actions:
        affected.update(('wiki/index.md', 'wiki/log.md'))
    refs.update(affected)
    # 给处理者附带内容页引用的证据节点；索引/日志不用于展开整个库。
    evidence_seeds = sorted(refs - {'wiki/index.md', 'wiki/log.md'})
    for path in evidence_seeds:
        for link in h.parse_wikilinks(view.read_text(path)):
            resolved = h.resolve_page(link, *maps)
            if resolved is not None:
                refs.add(resolved.relative_to(root).as_posix())
    # 来源页的 raw_note/原始资料双链也作为输入，正文仍只读。
    for path in sorted(refs):
        if path.startswith('wiki/sources/'):
            for link in h.parse_wikilinks(view.read_text(path)):
                resolved = h.resolve_page(link, *maps)
                if resolved is not None and resolved.is_relative_to(root / 'raw'):
                    refs.add(resolved.relative_to(root).as_posix())
    refs.update(p for p in ('AGENTS.md', 'tools/wiki_runtime/contracts/rules.json') if p in paths)
    if len(refs) > 128:
        raise HostError('heal 证据输入超过宿主 128 项上限；请分成明确范围的小批维护任务')
    task = ('审查 heal 计划中的建议，结合原文核实后仅修改 allowed_paths 内的页面。'
            '模糊改链和索引删项均需独立内容审查，不得按确定性派生产物免审。'
            '保留冲突和限定条件，维护索引、日志、必要反向边；不要自动建立桩页。'
            '无法确定目标时保留链接并记录待确认。建议数据：' + canonical_json(actions).decode('utf-8'))
    view.verify_dependencies()
    plan = dict(plan_version='1.0', operation_id=operation_id, operation_type='lint',
                root=str(root), min_refs=min_refs, dry_run=True, actions=actions,
                allowed_paths=sorted(affected), input_refs=sorted(refs), task=task,
                baseline=dict(snapshot=view.dependency_snapshot(), directories=sorted(view._directories)))
    plan['plan_digest'] = digest(plan)
    return plan


def verify_heal_plan(root, plan):
    """重新只读复算；不能靠改 JSON 的 scope/task 或刷新快照扩大计划。"""
    expected = build_heal_plan(root, operation_id=plan['operation_id'], min_refs=plan['min_refs'])
    if expected != plan:
        raise HostError('heal 计划或输入依赖已变化；请重新生成并审阅计划')
    return True


def run_heal_plan(host, plan, **limits):
    """可信宿主 API，不可直接注册为模型工具；共享宿主协调器预算。"""
    allowed = {'max_calls', 'max_seconds', 'call_timeout', 'apply', 'environment_retries'}
    if set(limits) - allowed:
        raise HostError('heal 仅允许预算与 apply 选项，不能覆盖任务、角色或路径')
    plan = copy.deepcopy(plan)
    verify_heal_plan(host.root, plan)
    if not plan['actions']:
        return dict(status='no_changes', applied=False, plan_digest=plan['plan_digest'])
    return host.run_operation(plan['operation_id'], plan['operation_type'], plan['task'],
                              plan['allowed_paths'], plan['input_refs'],
                              expected_baseline=plan['baseline'], **limits)
