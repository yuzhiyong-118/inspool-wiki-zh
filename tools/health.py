#!/usr/bin/env python3
"""Health check for inspool-wiki-zh.

Zero-external-dependency script that performs deterministic structural checks
on the wiki. This is the canonical implementation source for /health_wiki.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


WIKI_ROOT = Path(__file__).parent.parent / "wiki"
RAW_ROOT = Path(__file__).parent.parent / "raw"
META_DIR = WIKI_ROOT / "meta"
GRAPH_JSON = META_DIR / "graph.json"
HEALTH_REPORT = WIKI_ROOT / "health-report.md"

# Content directories (excluding meta/)
CONTENT_DIRS = ["sources", "entities", "concepts", "synthesis"]

# Required frontmatter fields
SOURCE_REQUIRED = {"type", "title", "raw_note", "updated"}
KNOWLEDGE_REQUIRED = {"type", "title", "updated"}


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text.strip()


def parse_frontmatter(text: str) -> dict:
    """Parse YAML frontmatter into a dict (minimal parser)."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = parts[1]
    result = {}
    current_key = None
    current_list = None
    for line in fm.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # List item under current key
        if stripped.startswith("- ") and current_key is not None:
            value = stripped[2:].strip()
            if current_list is None:
                current_list = []
                result[current_key] = current_list
            current_list.append(value)
            continue
        # New key
        if ":" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            current_key = key
            current_list = None
            result[key] = value if value else ""
    return result


def link_text(text: str) -> str:
    """Ignore examples in fenced/inline code and Obsidian comments."""
    text = re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1\s*$", "", text)
    text = re.sub(r"(?s)%%.*?%%|<!--.*?-->", "", text)
    return re.sub(r"(`+)[^`\n]*\1", "", text)


def page_maps(pages: list[Path]):
    names = defaultdict(list)
    paths = {}
    for page in sorted(set(pages)):
        names[page.stem].append(page)
        if page.is_relative_to(WIKI_ROOT):
            paths[page.relative_to(WIKI_ROOT).as_posix()[:-3]] = page
        elif page.is_relative_to(RAW_ROOT):
            paths["raw/" + page.relative_to(RAW_ROOT).as_posix()[:-3]] = page
    return dict(names), paths


def resolve_page(target: str, names: dict, paths: dict):
    """Resolve exact paths first; allow a unique moved note within its type."""
    target = target.split("|", 1)[0].split("#", 1)[0].replace("\\", "/").removesuffix(".md")
    target = target.removeprefix("inspool-wiki-zh/").removeprefix("wiki/")
    if target in paths:
        return paths[target]
    candidates = names.get(target.rsplit("/", 1)[-1], [])
    if isinstance(candidates, Path):  # Compatibility with existing heal callers.
        candidates = [candidates]
    if "/" in target:
        top = target.split("/", 1)[0]
        if top not in CONTENT_DIRS:
            return None  # Never silently relocate an explicit raw path.
        candidates = [p for p in candidates if p.is_relative_to(WIKI_ROOT / top)]
    return candidates[0] if len(candidates) == 1 else None


def all_wiki_pages(include_meta: bool = True) -> list[Path]:
    """Return all markdown files under wiki/ except index.md and log.md."""
    pages = []
    for p in WIKI_ROOT.rglob("*.md"):
        if p == HEALTH_REPORT:
            continue  # A generated report is not a knowledge page.
        rel = p.relative_to(WIKI_ROOT)
        if not include_meta and rel.parts[0] == "meta":
            continue
        if rel.name in {"index.md", "log.md"}:
            continue
        if rel.name == ".gitkeep":
            continue
        pages.append(p)
    return sorted(pages)


def content_pages() -> list[Path]:
    """Return content pages in sources/entities/concepts/synthesis."""
    pages = []
    for dirname in CONTENT_DIRS:
        dirpath = WIKI_ROOT / dirname
        if not dirpath.exists():
            continue
        for p in dirpath.rglob("*.md"):
            if p.name in {".gitkeep", "index.md", "log.md"}:
                continue
            pages.append(p)
    return sorted(pages)


def page_exists(target: str, pages_by_name: dict[str, Path], pages_by_rel: dict[str, Path]) -> bool:
    """Check if a wikilink target exists as a file."""
    return resolve_page(target, pages_by_name, pages_by_rel) is not None


def parse_wikilinks(text: str) -> list[str]:
    """Extract [[wikilink]] targets from text, handling [[target|alias]]."""
    targets = []
    for match in re.findall(r"\[\[([^\]]+)\]\]", link_text(text)):
        # Handle alias syntax: target|alias -> target
        target = match.split("|")[0].strip()
        if target:
            targets.append(target)
    return targets


def parse_index_links(index_text: str) -> set[str]:
    """Parse wiki/index.md for linked targets."""
    return set(parse_wikilinks(index_text))


def parse_log_entries(log_text: str) -> set[str]:
    """Parse wiki/log.md for ingest titles."""
    titles = set()
    for line in log_text.splitlines():
        if line.startswith("## ") and "ingest" in line:
            # Extract title after the pipe
            if "|" in line:
                title = line.split("|", 1)[1].strip()
                titles.add(title)
    return titles


def check_broken_links(pages: list[Path], pages_by_name: dict[str, Path], pages_by_rel: dict[str, Path]) -> dict:
    """Check 1: broken wikilinks."""
    broken = defaultdict(list)
    for page in pages:
        text = page.read_text(encoding="utf-8")
        links = parse_wikilinks(text)
        for link in links:
            if link.startswith("#"):
                continue  # Local anchors do not refer to another file.
            if not page_exists(link, pages_by_name, pages_by_rel):
                broken[page.relative_to(WIKI_ROOT).as_posix()].append(link)
    return dict(broken)


def check_frontmatter(pages: list[Path]) -> dict:
    """Check 2: frontmatter required fields."""
    missing = {}
    for page in pages:
        text = page.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        ptype = fm.get("type", "")
        if ptype == "source":
            required = SOURCE_REQUIRED
        else:
            required = KNOWLEDGE_REQUIRED
        absent = sorted(f for f in required if f not in fm or fm[f] in ("", None, []))
        if absent:
            missing[page.relative_to(WIKI_ROOT).as_posix()] = absent
    return missing


def check_index_sync(all_pages: list[Path]) -> dict:
    """Check 3: index sync."""
    index_path = WIKI_ROOT / "index.md"
    if not index_path.exists():
        return {"missing_index": True, "orphan_entries": [], "missing_pages": []}
    index_text = index_path.read_text(encoding="utf-8")
    index_links = parse_index_links(index_text)

    # Include index.md and log.md as valid link targets
    special_pages = [WIKI_ROOT / "index.md", WIKI_ROOT / "log.md"]
    check_pages = list(all_pages) + [p for p in special_pages if p.exists()]

    page_names, page_rel_paths = page_maps(check_pages)
    # Pages linked in index but not on disk
    orphan_entries = []
    for link in index_links:
        link_clean = link.split("#")[0]
        if link_clean and not page_exists(link, page_names, page_rel_paths):
            orphan_entries.append(link)
    # Pages on disk but not in index
    missing_pages = []
    for page in all_pages:
        if page not in {resolve_page(link, page_names, page_rel_paths) for link in index_links}:
            missing_pages.append(page.relative_to(WIKI_ROOT).as_posix())
    return {"orphan_entries": sorted(orphan_entries), "missing_pages": sorted(missing_pages)}


def check_path_residue(pages: list[Path]) -> dict:
    """Only a missing raw target is residue; pending-review paths are valid."""
    residue = defaultdict(list)
    for page in pages:
        text = page.read_text(encoding="utf-8")
        matches = [link.split("#", 1)[0].removeprefix("inspool-wiki-zh/")
                   for link in parse_wikilinks(text)
                   if link.removeprefix("inspool-wiki-zh/").startswith("raw/unprocessed/")]
        if matches:
            for target in sorted(set(matches)):
                candidate = RAW_ROOT.parent / target
                if not candidate.exists() and not Path(str(candidate) + ".md").exists():
                    residue[page.relative_to(WIKI_ROOT).as_posix()].append(target)
    return dict(residue)


def check_raw_queue(names: dict, paths: dict) -> list[str]:
    """Validate raw state, queue snapshot and reciprocal source mapping."""
    issues = []
    raw_index = RAW_ROOT / "index.md"
    index_text = raw_index.read_text(encoding="utf-8") if raw_index.exists() else ""
    if not raw_index.exists():
        issues.append("raw/index.md 不存在")
    rows = {}
    for line in index_text.splitlines():
        if not line.startswith("|"):
            continue
        links = parse_wikilinks(line)
        for target in links:
            if target.startswith("raw/"):
                rows.setdefault(target.removesuffix(".md"), []).append(line)
    counts = {"unprocessed": 0, "pending_review": 0, "processed": 0}
    actual = set()
    for folder in ("unprocessed", "processed"):
        for raw in sorted((RAW_ROOT / folder).rglob("*.md")):
            key = "raw/" + raw.relative_to(RAW_ROOT).as_posix()[:-3]
            actual.add(key)
            fm = parse_frontmatter(raw.read_text(encoding="utf-8"))
            state = fm.get("processing_status", "")
            if state not in counts:
                issues.append(f"{key}: processing_status 缺失或无效")
            else:
                counts[state] += 1
                if (folder == "processed") != (state == "processed"):
                    issues.append(f"{key}: 状态 {state} 与目录不一致")
            row = rows.get(key, [])
            if len(row) != 1:
                issues.append(f"{key}: raw/index 收录次数应为 1，实际 {len(row)}")
            elif state and not re.search(r"\|\s*" + re.escape(state) + r"\s*\|", row[0]):
                issues.append(f"{key}: raw/index 状态不一致")
            if state == "processed" and not fm.get("reviewed_at"):
                issues.append(f"{key}: processed 缺少 reviewed_at")
            if state not in ("pending_review", "processed"):
                continue
            targets = parse_wikilinks(str(fm.get("processed_into", "")))
            if not targets:
                issues.append(f"{key}: 缺少 processed_into 来源页链接")
            for target in targets:
                source = resolve_page(target, names, paths)
                if source is None or not source.is_relative_to(WIKI_ROOT / "sources"):
                    issues.append(f"{key}: processed_into 来源页不存在或类型错误 ({target})")
                    continue
                source_fm = parse_frontmatter(source.read_text(encoding="utf-8"))
                back = parse_wikilinks(str(source_fm.get("raw_note", "")))
                if raw not in {resolve_page(t, names, paths) for t in back}:
                    issues.append(f"{key}: 来源页 raw_note 未回指当前 raw")
                if row and source not in {resolve_page(t, names, paths) for t in parse_wikilinks(row[0])}:
                    issues.append(f"{key}: raw/index 来源页与 processed_into 不一致")
    for key in sorted(rows.keys() - actual):
        issues.append(f"{key}: raw/index 条目在流程目录中不存在")
    for label, state in (("未处理", "unprocessed"), ("待确认", "pending_review"), ("已处理", "processed")):
        match = re.search(r"(?m)^- " + label + r"：\s*(\d+)\s*$", index_text)
        if not match or int(match.group(1)) != counts[state]:
            issues.append(f"raw/index {label}计数应为 {counts[state]}")
    return issues


def check_empty_and_stubs(pages: list[Path]) -> dict:
    """Check 5: empty or stub files."""
    empty = []
    stubs = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        body = strip_frontmatter(text)
        char_count = len(body.replace(" ", "").replace("\n", ""))
        if char_count == 0:
            empty.append(page.relative_to(WIKI_ROOT).as_posix())
        elif char_count < 100:
            stubs.append(page.relative_to(WIKI_ROOT).as_posix())
    return {"empty": empty, "stubs": stubs}


def check_log_coverage(source_pages: list[Path], log_text: str) -> list[str]:
    """Check 6: source pages without a corresponding ingest log entry."""
    missing = []
    for page in source_pages:
        rel = page.relative_to(WIKI_ROOT).as_posix()
        name = page.stem
        # A source page is covered if the log mentions its path, stem, or title
        if name not in log_text and rel not in log_text:
            missing.append(rel)
    return missing


def build_graph(pages: list[Path]) -> dict:
    """Build graph.json from wikilinks and frontmatter relations."""
    nodes = []
    edges = []
    node_ids = {}
    names, paths = page_maps(pages)

    for page in pages:
        rel = page.relative_to(WIKI_ROOT).as_posix()[:-3]
        name = page.stem
        node_ids[page] = rel
        text = page.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        node_type = fm.get("type", "unknown")
        nodes.append({
            "id": rel,
            "label": name,
            "path": rel,
            "type": node_type,
        })

    # Edges from wikilinks and frontmatter relation fields
    relations = defaultdict(set)
    for page in pages:
        name = node_ids[page]
        text = page.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        links = set(parse_wikilinks(strip_frontmatter(text)))
        for link in links:
            target = resolve_page(link, names, paths)
            if target in node_ids and target != page:
                relations[(name, node_ids[target])].add("body")
        for field in ["supports", "contradicts", "related_entities", "related_concepts",
                      "related_sources", "related_synthesis"]:
            for link in parse_wikilinks(str(fm.get(field, ""))):
                target = resolve_page(link, names, paths)
                if target in node_ids and target != page:
                    relations[(name, node_ids[target])].add(field)

    for (source, target), kinds in sorted(relations.items()):
        edges.append({
            "source": source,
            "target": target,
            "weight": 1,
            "relations": sorted(kinds),
        })

    return {"schema_version": 2, "nodes": nodes, "edges": edges}


def compute_graph_stats(graph: dict, pages: list[Path]) -> dict:
    """Compute statistics for lint thresholds."""
    # Lint thresholds describe knowledge pages, not meta/navigation documents.
    content_ids = {p.relative_to(WIKI_ROOT).as_posix()[:-3] for p in pages}
    nodes = [n for n in graph.get("nodes", []) if n["id"] in content_ids]
    edges = [e for e in graph.get("edges", [])
             if e["source"] in content_ids and e["target"] in content_ids]
    if not nodes:
        return {
            "content_page_count": len(pages),
            "avg_outgoing_links": 0.0,
            "node_count": 0,
            "edge_count": 0,
            "edge_to_node_ratio": 0.0,
            "high_degree_node_ratio": 0.0,
        }

    out_degrees = defaultdict(int)
    for edge in edges:
        out_degrees[edge["source"]] += 1

    total_out = sum(out_degrees.values())
    avg_out = total_out / len(nodes) if nodes else 0.0
    high_degree = sum(1 for d in out_degrees.values() if d >= 2)

    return {
        "content_page_count": len(pages),
        "avg_outgoing_links": round(avg_out, 2),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "edge_to_node_ratio": round(len(edges) / len(nodes), 2) if nodes else 0.0,
        "high_degree_node_ratio": round(high_degree / len(nodes), 2) if nodes else 0.0,
        "navigation_node_count": len(graph.get("nodes", [])) - len(nodes),
    }


def run_health() -> dict:
    """Run all health checks and return structured report."""
    pages = all_wiki_pages(include_meta=True)
    content = content_pages()
    non_meta_pages = all_wiki_pages(include_meta=False)
    # Broken-link resolver must include meta pages too: non-meta pages legitimately
    # link to meta/* docs (e.g. [[meta/workflow]], [[meta/integration-plan]]).
    # It also accepts raw/ paths since source pages reference raw_note via wikilinks.
    targets = list(pages) + [WIKI_ROOT / "index.md", WIKI_ROOT / "log.md"]
    # Raw files live under raw/ (outside the wiki tree); their stems and rel paths
    # should resolve too. We map both forms so [[raw/unprocessed/x]] works.
    if RAW_ROOT.exists():
        targets.extend(RAW_ROOT.rglob("*.md"))
    pages_by_name, pages_by_rel = page_maps([p for p in targets if p.exists()])
    # Append-only historical records may point to deliberately removed pages.
    live_pages = [p for p in pages if p != META_DIR / "audit-log.md"]

    report = {
        "timestamp": datetime.now().isoformat(),
        "checks": {},
        "stats": {},
    }

    report["checks"]["broken_links"] = check_broken_links(live_pages, pages_by_name, pages_by_rel)
    report["checks"]["frontmatter"] = check_frontmatter(non_meta_pages)
    report["checks"]["index_sync"] = check_index_sync(pages)
    report["checks"]["path_residue"] = check_path_residue(live_pages)
    report["checks"]["empty_and_stubs"] = check_empty_and_stubs(non_meta_pages)

    log_path = WIKI_ROOT / "log.md"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    source_pages = [p for p in pages if p.relative_to(WIKI_ROOT).parts[0] == "sources"]
    report["checks"]["log_coverage"] = check_log_coverage(source_pages, log_text)
    report["checks"]["raw_queue"] = check_raw_queue(pages_by_name, pages_by_rel)
    report["checks"]["duplicate_names"] = {
        name: [p.relative_to(WIKI_ROOT).as_posix() for p in group if p.is_relative_to(WIKI_ROOT)]
        for name, group in pages_by_name.items()
        if len([p for p in group if p.is_relative_to(WIKI_ROOT)]) > 1
    }

    graph = build_graph(pages)
    report["stats"] = compute_graph_stats(graph, content)
    graph["stats"] = report["stats"]
    report["graph"] = graph

    return report


def count_problems(report: dict) -> int:
    """Count total problems across all checks."""
    total = 0
    checks = report["checks"]
    total += sum(len(v) for v in checks["broken_links"].values())
    total += sum(len(v) for v in checks["frontmatter"].values())
    total += len(checks["index_sync"].get("orphan_entries", []))
    total += len(checks["index_sync"].get("missing_pages", []))
    total += int(checks["index_sync"].get("missing_index", False))
    total += sum(len(v) for v in checks["path_residue"].values())
    total += len(checks["empty_and_stubs"]["empty"])
    total += len(checks["empty_and_stubs"]["stubs"])
    total += len(checks["log_coverage"])
    total += len(checks.get("raw_queue", []))
    total += len(checks.get("duplicate_names", {}))
    return total


def format_report(report: dict) -> str:
    """Format report as markdown for terminal display."""
    checks = report["checks"]
    stats = report["stats"]
    total = count_problems(report)

    lines = ["【Health 检查报告】\n"]

    def section(title: str, ok: bool, details: list[str]):
        icon = "✅" if ok else "⚠️"
        lines.append(f"{icon} {title}")
        for d in details[:20]:  # limit details
            lines.append(f"   - {d}")
        if len(details) > 20:
            lines.append(f"   - ... 还有 {len(details) - 20} 项")
        lines.append("")

    # Broken links
    broken = checks["broken_links"]
    details = [f"{src} → [[{tgt}]]" for src, tgts in broken.items() for tgt in tgts]
    section("1. 死链检测", not broken, details or ["无死链"])

    # Frontmatter
    fm = checks["frontmatter"]
    details = [f"{page} 缺失: {', '.join(fields)}" for page, fields in fm.items()]
    section("2. Frontmatter 必填字段合规", not fm, details or ["全部合规"])

    # Index sync
    sync = checks["index_sync"]
    details = []
    if sync.get("missing_index"):
        details.append("wiki/index.md 不存在")
    else:
        for entry in sync.get("orphan_entries", []):
            details.append(f"僵尸条目: [[{entry}]]")
        for page in sync.get("missing_pages", []):
            details.append(f"遗漏页面: {page}")
    section("3. Index 同步检查", not details, details or ["已同步"])

    # Path residue
    residue = checks["path_residue"]
    details = [f"{src}: {path}" for src, paths in residue.items() for path in paths]
    section("4. 路径残留检查", not residue, details or ["无残留"])

    # Empty/stubs
    es = checks["empty_and_stubs"]
    details = [f"空文件: {p}" for p in es["empty"]] + [f"桩文件: {p}" for p in es["stubs"]]
    section("5. 空文件 / 桩文件检测", not details, details or ["无空文件/桩文件"])

    # Log coverage
    coverage = checks["log_coverage"]
    details = [f"{p}" for p in coverage]
    section("6. Log 覆盖检查", not coverage, details or ["全部有日志"])
    queue = checks.get("raw_queue", [])
    section("7. Raw 队列与来源映射", not queue, queue or ["状态、索引与来源回链一致"])
    duplicates = checks.get("duplicate_names", {})
    details = [f"{name}: {', '.join(group)}（请使用明确路径）" for name, group in duplicates.items()]
    section("8. 同名页面提示", not details, details or ["无重名歧义"])

    lines.append(f"总计：{total} 项问题")
    lines.append("")
    lines.append("统计：")
    for k, v in stats.items():
        lines.append(f"  {k}: {v}")

    return "\n".join(lines)


def _applied_health_status(result, state_dir):
    """Read the exact Executor-committed log bytes, never rerun health afterward."""
    import base64
    import hashlib
    from tools.wiki_runtime.contracts import digest

    execution = result["execution"]
    journal_path = Path(state_dir) / "private/journals" / (digest(execution["operation_id"]) + ".json")
    journal = json.loads(journal_path.read_bytes())
    if journal["state"] != "applied" or journal["manifest"]["candidate_digest"] != execution["candidate_digest"]:
        raise ValueError("health journal 与已应用候选不一致")
    step = next(s for s in journal["steps"] if s["path"] == "wiki/log.md")
    old = b"" if step["old"] is None else base64.b64decode(step["old"], validate=True)
    new = base64.b64decode(step["new"], validate=True)
    applied = next(s for s in execution["applied"] if s["path"] == "wiki/log.md")
    if (step["status"] != "done" or hashlib.sha256(new).hexdigest() != applied["sha256"]
            or not new.startswith(old)):
        raise ValueError("health journal 日志字节未绑定到应用结果")
    entry = new[len(old):].decode("utf-8")
    match = re.match(r"\n\n## \[\d{4}-\d{2}-\d{2}\] health \| 确定性结构检查\n\n- 检查结果：(\d+) 项问题。\n", entry)
    if not match:
        raise ValueError("health journal 缺少确定性检查结果")
    return int(int(match[1]) > 0)


def _apply_via_host(command, root, state_dir, operation_id=None, extra=(), *, health_exit_status=False):
    """Owner CLI compatibility adapter; never registered as a model tool.

    Direct ``python tools/health.py`` also needs the repository package root.
    The host validates the explicit private state path and applies via Executor.
    """
    package_root = str(Path(__file__).resolve().parent.parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    from tools.wiki_runtime.host.cli import main as host_main
    argv = [command, "--root", str(root), "--state-dir", str(state_dir), "--apply"]
    if operation_id is not None:
        argv.extend(["--operation-id", operation_id])
    if not health_exit_status:
        return host_main(argv + list(extra))
    import contextlib
    import io
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = host_main(argv + list(extra))
    print(output.getvalue(), end="")
    if code:
        return code
    try:
        return _applied_health_status(json.loads(output.getvalue()), state_dir)
    except (ValueError, OSError, KeyError, StopIteration, TypeError) as exc:
        print(f"无法读取同次已应用 health 检查结果：{exc}", file=sys.stderr)
        return 2


def main():
    # Force UTF-8 output on Windows consoles that default to gbk
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="Health check for inspool-wiki-zh")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--save", action="store_true", help="经 host Executor 门禁保存报告并追加 health 日志")
    parser.add_argument("--graph-only", action="store_true", help="经门禁生成图并追加日志；退出码仅表示应用结果（映射 --no-report --write-graph）")
    parser.add_argument("--write-graph", action="store_true", help="经 host Executor 门禁生成图并追加日志")
    parser.add_argument("--state-dir", help="写操作必填：正式库外、同卷的专属私有状态目录")
    parser.add_argument("--operation-id", help="可选的 host 操作标识")
    args = parser.parse_args()

    if args.save or args.write_graph or args.graph_only:
        if not args.state_dir:
            parser.error("旧写入口已迁移到 host Executor；请显式添加 --state-dir <库外同卷专属目录>，可选 --operation-id。不会自动选择状态目录；--graph-only 也会经门禁追加 health 日志。")
        extra = []
        if args.graph_only or not args.save:
            extra.append("--no-report")
        if args.write_graph or args.graph_only:
            extra.append("--write-graph")
        return _apply_via_host("health", WIKI_ROOT.parent, args.state_dir, args.operation_id, extra,
                               health_exit_status=not args.graph_only)

    if not WIKI_ROOT.exists():
        print(f"Error: wiki root not found: {WIKI_ROOT}", file=sys.stderr)
        sys.exit(1)

    report = run_health()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        text = format_report(report)
        print(text)
    return 1 if count_problems(report) else 0


if __name__ == "__main__":
    sys.exit(main())
