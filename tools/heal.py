#!/usr/bin/env python3
"""只读 heal 计划入口。

历史 Python 修复函数仅保留给可信维护代码兼容，不能注册为模型工具。
CLI 不调用它们的写模式；语义修改必须交可信宿主 Worker/Reviewer/Executor。
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path

# Import the canonical health module so heal stays in sync with health checks.
try:
    from tools import health
except ModuleNotFoundError:
    import health


WIKI_ROOT = health.WIKI_ROOT
CONTENT_DIRS = health.CONTENT_DIRS


def resolution_maps():
    pages = health.all_wiki_pages(include_meta=True)
    pages += [p for p in (WIKI_ROOT / "index.md", WIKI_ROOT / "log.md") if p.exists()]
    pages += list(health.RAW_ROOT.rglob("*.md"))
    return health.page_maps(pages)


def normalize_name(name: str) -> str:
    """Normalize a page name for fuzzy comparison."""
    return re.sub(r"[\s_-]+", "", name.lower())


def classify_stub(target: str, referrers: list[Path]) -> str:
    """Guess whether a missing target should live in entities/ or concepts/."""
    target_lower = target.lower()
    # Simple heuristics
    entity_markers = ["公司", "团队", "人", "作者", "产品", "项目", "工具", "框架", "平台", "模型"]
    concept_markers = ["方法", "理论", "原则", "模式", "范式", "架构", "协议", "算法", "策略"]

    # Inspect referrers for directory hints
    for ref in referrers:
        top = ref.relative_to(WIKI_ROOT).parts[0]
        if top == "entities":
            return "entities"
        if top == "concepts":
            return "concepts"

    # Inspect target name
    for marker in entity_markers:
        if marker in target_lower:
            return "entities"
    for marker in concept_markers:
        if marker in target_lower:
            return "concepts"

    # Default to concept when ambiguous
    return "concepts"


def slugify_filename(name: str) -> str:
    """Convert a wikilink target into a safe filename stem."""
    # Strip folder prefix and anchor
    name = Path(name.split("#")[0]).name
    if name.endswith(".md"):
        name = name[:-3]
    # Replace unsafe characters
    name = re.sub(r'[\\/:*?"<>|]', " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def collect_link_frequencies(non_meta_pages: list[Path]) -> dict[str, list[Path]]:
    """Return mapping from missing link target -> list of referring page Paths."""
    pages_by_name, pages_by_rel = resolution_maps()

    frequencies = defaultdict(list)
    for page in non_meta_pages:
        text = page.read_text(encoding="utf-8")
        for link in health.parse_wikilinks(text):
            if link.startswith(("#", "raw/", "wiki/raw/")):
                continue
            if not health.page_exists(link, pages_by_name, pages_by_rel):
                target = link.split("#")[0]
                target = Path(target).name
                if target.endswith(".md"):
                    target = target[:-3]
                if target and page not in frequencies[target]:
                    frequencies[target].append(page)
    return dict(frequencies)


def heal_missing_pages(non_meta_pages: list[Path], min_refs: int = 3, dry_run: bool = True) -> list[dict]:
    """只读预览保留；写模式必须交给可信 Host 的 heal 工作流。"""
    if dry_run:
        return _heal_missing_pages(non_meta_pages, min_refs=min_refs, dry_run=True)
    from tools.wiki_runtime.runtime.migration import MigrationError
    raise MigrationError('heal_missing_pages 直写已封闭；请使用 AgentSession.heal 受管入口')


def _heal_missing_pages(non_meta_pages: list[Path], min_refs: int = 3, dry_run: bool = True) -> list[dict]:
    """Create stub pages for missing targets referenced >= min_refs times."""
    if not dry_run:
        from tools.wiki_runtime.runtime.migration import MigrationError
        raise MigrationError('私有 missing-pages 直写实现同样已封闭')
    frequencies = collect_link_frequencies(non_meta_pages)
    actions = []

    for target, referrers in sorted(frequencies.items(), key=lambda x: -len(x[1])):
        if len(referrers) < min_refs:
            continue

        kind = classify_stub(target, referrers)
        filename = slugify_filename(target)
        if not filename:
            continue

        stub_path = WIKI_ROOT / kind / f"{filename}.md"
        if stub_path.exists():
            continue

        today = datetime.now().strftime("%Y-%m-%d")
        page_type = "entity" if kind == "entities" else "concept"
        content = f"""---
type: {page_type}
status: stub
title: {filename}
updated: {today}
related_sources: []
related_entities: []
related_concepts: []
---

# {filename}

> 本页由 `tools/heal.py` 自动生成的 stub，因被引用 {len(referrers)} 次但缺少独立页面。
> 来源引用：{', '.join(sorted({r.stem for r in referrers}))}

待补充内容。

## 相关页面

"""
        actions.append({
            "type": "create_stub",
            "path": stub_path.relative_to(WIKI_ROOT).as_posix(),
            "target": target,
            "referrers": [r.relative_to(WIKI_ROOT).as_posix() for r in referrers],
            "content": content,
        })

        if not dry_run:
            stub_path.parent.mkdir(parents=True, exist_ok=True)
            stub_path.write_text(content, encoding="utf-8")

    return actions


def heal_broken_links(non_meta_pages: list[Path], dry_run: bool = True) -> list[dict]:
    """只读预览保留；写模式必须交给可信 Host 的 heal 工作流。"""
    if dry_run:
        return _heal_broken_links(non_meta_pages, dry_run=True)
    from tools.wiki_runtime.runtime.migration import MigrationError
    raise MigrationError('heal_broken_links 直写已封闭；请使用 AgentSession.heal 受管入口')


def _heal_broken_links(non_meta_pages: list[Path], dry_run: bool = True) -> list[dict]:
    """Fix wikilink spellings when a close existing page exists."""
    if not dry_run:
        from tools.wiki_runtime.runtime.migration import MigrationError
        raise MigrationError('私有 broken-links 直写实现同样已封闭')
    pages_by_name, pages_by_rel = resolution_maps()
    unique_names = [k for k, group in pages_by_name.items() if len(group) == 1]
    existing_normals = {normalize_name(k): k for k in unique_names + list(pages_by_rel)}

    actions = []
    for page in non_meta_pages:
        text = page.read_text(encoding="utf-8")
        original = text
        # Find each wikilink and replace if close match exists
        def replacer(match: re.Match) -> str:
            full = match.group(1)
            if "|" in full:
                target, alias = full.split("|", 1)
                target = target.strip()
                alias = alias.strip()
            else:
                target = full.strip()
                alias = None

            base = target.split("#")[0]
            anchor = target.split("#", 1)[1] if "#" in target else ""
            if not base or base.startswith(("raw/", "wiki/raw/")):
                return match.group(0)

            if health.page_exists(base, pages_by_name, pages_by_rel):
                return match.group(0)

            norm = normalize_name(base)
            if norm in existing_normals:
                fixed = existing_normals[norm]
            else:
                close = get_close_matches(norm, existing_normals.keys(), n=1, cutoff=0.85)
                if not close:
                    return match.group(0)
                fixed = existing_normals[close[0]]

            new_target = fixed + (f"#{anchor}" if anchor else "")
            if alias:
                return f"[[{new_target}|{alias}]]"
            return f"[[{new_target}]]"

        new_text = re.sub(r"\[\[([^\]]+)\]\]", replacer, text)
        if new_text != original:
            actions.append({
                "type": "fix_links",
                "path": page.relative_to(WIKI_ROOT).as_posix(),
            })
            if not dry_run:
                page.write_text(new_text, encoding="utf-8")

    return actions


def heal_index_sync(all_pages: list[Path], dry_run: bool = True) -> list[dict]:
    """只读预览保留；写模式必须交给可信 Host 的 heal 工作流。"""
    if dry_run:
        return _heal_index_sync(all_pages, dry_run=True)
    from tools.wiki_runtime.runtime.migration import MigrationError
    raise MigrationError('heal_index_sync 直写已封闭；请使用 AgentSession.heal 受管入口')


def _heal_index_sync(all_pages: list[Path], dry_run: bool = True) -> list[dict]:
    """Synchronize wiki/index.md: remove orphan entries and append missing pages."""
    if not dry_run:
        from tools.wiki_runtime.runtime.migration import MigrationError
        raise MigrationError('私有 index-sync 直写实现同样已封闭')
    index_path = WIKI_ROOT / "index.md"
    if not index_path.exists():
        return [{"type": "error", "message": "wiki/index.md not found"}]

    index_text = index_path.read_text(encoding="utf-8")
    original_text = index_text
    actions = []

    special_pages = [WIKI_ROOT / "index.md", WIKI_ROOT / "log.md"]
    check_pages = list(all_pages) + [p for p in special_pages if p.exists()]
    page_names = {p.stem: p for p in check_pages}
    page_rel_paths = {p.relative_to(WIKI_ROOT).as_posix()[:-3]: p for p in check_pages}

    index_links = health.parse_index_links(index_text)

    # Remove orphan entries
    orphan_links = []
    for link in index_links:
        clean = link.split("#")[0]
        if clean and clean not in page_names and clean not in page_rel_paths:
            orphan_links.append(link)
            # Simple line removal: remove lines that contain this link
            pattern = re.compile(r"^.*\[\[" + re.escape(link) + r"(\|[^\]]+)?\]\].*$\n?", re.MULTILINE)
            index_text = pattern.sub("", index_text)

    if orphan_links:
        actions.append({
            "type": "remove_orphans",
            "entries": orphan_links,
        })

    # Add missing pages under appropriate sections
    missing_pages = []
    section_map = {
        "sources": "## 来源页",
        "entities": "## 实体页",
        "concepts": "## 概念页",
        "synthesis": "## 综合页",
        "meta": "## 总览",
    }
    dir_to_section = {
        "sources": "来源页",
        "entities": "实体页",
        "concepts": "概念页",
        "synthesis": "综合页",
        "meta": "总览",
    }

    for page in all_pages:
        name = page.stem
        rel = page.relative_to(WIKI_ROOT).as_posix()[:-3]
        if name in index_links or rel in index_links:
            continue
        missing_pages.append(page)

    # Group missing pages by top-level dir
    grouped = defaultdict(list)
    for page in missing_pages:
        top = page.relative_to(WIKI_ROOT).parts[0]
        grouped[top].append(page)

    for top, pages in grouped.items():
        section_title = section_map.get(top)
        if not section_title:
            continue

        # Find the section in index text
        section_re = re.compile(rf"(^|\n){re.escape(section_title)}\s*\n")
        match = section_re.search(index_text)
        if not match:
            continue

        insert_pos = match.end()
        insert_lines = []
        for page in sorted(pages, key=lambda p: p.stem):
            link_target = page.relative_to(WIKI_ROOT).as_posix()[:-3]
            insert_lines.append(f"- [[{link_target}]]\n")

        # Insert after section header
        index_text = index_text[:insert_pos] + "".join(insert_lines) + index_text[insert_pos:]
        actions.append({
            "type": "add_missing",
            "section": dir_to_section.get(top, top),
            "pages": [p.relative_to(WIKI_ROOT).as_posix() for p in pages],
        })

    if index_text != original_text and not dry_run:
        index_path.write_text(index_text, encoding="utf-8")

    return actions


def run_heal(dry_run: bool = True, min_refs: int = 3) -> dict:
    """历史可信 Python 预览 API；正式修复仅由 Runtime Host 工作流执行。"""
    if not dry_run:
        from tools.wiki_runtime.runtime.migration import MigrationError
        raise MigrationError('run_heal 直写已封闭；请使用 AgentSession.heal 受管入口')
    return _run_heal(dry_run=True, min_refs=min_refs)


def _run_heal(dry_run: bool = True, min_refs: int = 3) -> dict:
    if not dry_run:
        from tools.wiki_runtime.runtime.migration import MigrationError
        raise MigrationError('私有 run-heal 直写实现同样已封闭')
    all_pages = health.all_wiki_pages(include_meta=True)
    non_meta_pages = health.all_wiki_pages(include_meta=False)

    report = {
        "dry_run": dry_run,
        "timestamp": datetime.now().isoformat(),
        "actions": [],
    }

    report["actions"].extend(_heal_index_sync(all_pages, dry_run=dry_run))
    report["actions"].extend(_heal_broken_links(non_meta_pages, dry_run=dry_run))
    report["actions"].extend(_heal_missing_pages(non_meta_pages, min_refs=min_refs, dry_run=dry_run))

    return report


def format_report(report: dict) -> str:
    """Format heal report for terminal display."""
    mode = "【dry-run 预览】" if report["dry_run"] else "【实际修复】"
    lines = [f"{mode} Heal 报告\n"]

    actions = report["actions"]
    if not actions:
        lines.append("无需修复。")
        return "\n".join(lines)

    grouped = defaultdict(list)
    for action in actions:
        grouped[action["type"]].append(action)

    if "remove_orphans" in grouped:
        entries = [a for act in grouped["remove_orphans"] for a in act["entries"]]
        lines.append(f"🧹 移除 index 僵尸条目：{len(entries)} 项")
        for e in entries[:10]:
            lines.append(f"   - [[{e}]]")
        if len(entries) > 10:
            lines.append(f"   - ... 还有 {len(entries) - 10} 项")
        lines.append("")

    if "add_missing" in grouped:
        total = sum(len(a["pages"]) for a in grouped["add_missing"])
        lines.append(f"➕ 补充 index 遗漏页面：{total} 项")
        for act in grouped["add_missing"]:
            lines.append(f"   分区 [{act['section']}]：{len(act['pages'])} 项")
            for p in act["pages"][:5]:
                lines.append(f"      - {p}")
            if len(act["pages"]) > 5:
                lines.append(f"      - ... 还有 {len(act['pages']) - 5} 项")
        lines.append("")

    if "fix_links" in grouped:
        paths = [a["path"] for a in grouped["fix_links"]]
        lines.append(f"🔗 自动修复断链：{len(paths)} 个文件")
        for p in paths[:10]:
            lines.append(f"   - {p}")
        if len(paths) > 10:
            lines.append(f"   - ... 还有 {len(paths) - 10} 个")
        lines.append("")

    if "create_stub" in grouped:
        stubs = grouped["create_stub"]
        lines.append(f"🌱 自动补建 stub 页：{len(stubs)} 项（被引用 >= 3 次）")
        for a in stubs[:10]:
            lines.append(f"   - {a['path']}（来自 {len(a['referrers'])} 个引用）")
        if len(stubs) > 10:
            lines.append(f"   - ... 还有 {len(stubs) - 10} 项")
        lines.append("")

    if report["dry_run"]:
        lines.append("未执行修改。请导出 --plan，再由可信宿主 run_heal_plan 处理并独立审查。")
    else:
        lines.append("已完成实际修改。建议再运行 `python tools/health.py` 验证。")

    return "\n".join(lines)


def main():
    # Force UTF-8 output on Windows consoles that default to gbk
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="Healer for inspool-wiki-zh")
    parser.add_argument("--apply", action="store_true", help="需可信宿主 dispatcher；本地 CLI 拒绝直接应用")
    parser.add_argument("--root", type=Path, default=WIKI_ROOT.parent, help="显式知识库根目录")
    parser.add_argument("--plan", type=Path, help="导出 JSON 到库内 .wiki-runtime/candidates 下的新文件")
    parser.add_argument("--operation-id", default="heal-plan", help="绑定计划的操作 ID")
    parser.add_argument("--min-refs", type=int, default=3, help="报告高频缺页的引用阈值，不自动造桩")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.apply:
        parser.error('--apply 未连接可信宿主 dispatcher，拒绝直接写入。先运行 '
                     '--plan .wiki-runtime/candidates/heal-plan.json；再由可信宿主调用 '
                     'AgentSession.heal 或 host.heal.run_heal_plan(session.maintenance, plan, apply=True)。'
                     '复用当前宿主模型，无需独立 API。')
    # Direct script execution from an unrelated cwd also finds the bundled runtime.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.wiki_runtime.host.heal import build_heal_plan
    from tools.wiki_runtime.host.approval import _check_path
    try:
        root = args.root.absolute()
        if not (root / 'wiki').is_dir():
            raise ValueError('wiki 根目录不存在')
        plan = build_heal_plan(root, operation_id=args.operation_id, min_refs=args.min_refs)
        data = json.dumps(plan, ensure_ascii=False, indent=2) + '\n'
        if args.plan:
            output = args.plan if args.plan.is_absolute() else root / args.plan
            _check_path(output.absolute())
            candidate_root = root.resolve() / '.wiki-runtime/candidates'
            if not output.resolve().is_relative_to(candidate_root) or output.resolve() == candidate_root:
                raise ValueError('--plan 输出只能位于库内 .wiki-runtime/candidates 候选区')
            output.parent.mkdir(parents=True, exist_ok=True)
            _check_path(output.absolute())
            with output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(data)
        if args.json:
            print(data, end='')
        else:
            print(f'【dry-run 计划】{len(plan["actions"])} 项待审建议；允许路径 {len(plan["allowed_paths"])} 个。')
            print('模糊改链仅供审查，不自动造桩。使用 --json 查看详情，或 '
                  '--plan .wiki-runtime/candidates/heal-plan.json 导出候选区计划。')
            print('应用入口：AgentSession.heal / host.heal.run_heal_plan；独立 Reviewer 与 Executor 共用预算。')
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
