#!/usr/bin/env python3
"""从 raw frontmatter 刷新队列快照；默认预览，只改标记内区域。"""

import argparse
import os
import sys
import tempfile
from collections import Counter

try:
    import health
except ModuleNotFoundError:
    from tools import health

START = "<!-- raw-queue:start -->"
END = "<!-- raw-queue:end -->"
STATES = (("unprocessed", "未处理"), ("pending_review", "待确认"), ("processed", "已处理"))


def render_queue(raw_root=None):
    raw_root = health.RAW_ROOT if raw_root is None else raw_root
    records = []
    for folder in ("unprocessed", "processed"):
        for path in sorted((raw_root / folder).rglob("*.md")):
            fm = health.parse_frontmatter(path.read_text(encoding="utf-8"))
            state = fm.get("processing_status", "未标记")
            target = "raw/" + path.relative_to(raw_root).as_posix()[:-3]
            sources = health.parse_wikilinks(str(fm.get("processed_into", "")))
            records.append((state, target, sources))
    counts = Counter(state for state, _, _ in records)
    lines = [START, "", "## 队列概览", ""]
    for state, label in STATES:
        lines.append(f"- {label}：{counts[state]}")
    unknown = [(s, p, refs) for s, p, refs in records if s not in dict(STATES)]
    if unknown:
        lines.append(f"- 状态待补正：{len(unknown)}")
    for state, label in (*STATES, (None, "状态待补正")):
        selected = unknown if state is None else [r for r in records if r[0] == state]
        if not selected:
            continue
        lines += ["", f"## {label}素材", "", "| 文件 | 来源页 | 状态 |", "|---|---|---|"]
        for status, target, sources in selected:
            refs = "、".join(f"[[{s}]]" for s in sources) or "待 ingest"
            lines.append(f"| [[{target}]] | {refs} | {status} |")
    return "\n".join(lines + ["", END])


def refresh_index(apply=False):
    """默认只读预览；正式写入必须使用带 state_dir 的 Runtime CLI。"""
    if not apply:
        return _refresh_index(apply=False)
    from tools.wiki_runtime.runtime.migration import MigrationError
    raise MigrationError(
        'refresh_index(apply=True) 已封闭；请使用 raw_index.py --write --state-dir 的受管入口'
    )


def _refresh_index(apply=False):
    if apply:
        from tools.wiki_runtime.runtime.migration import MigrationError
        raise MigrationError('私有 raw-index 直写实现同样已封闭；请使用 Runtime CLI')
    index = health.RAW_ROOT / "index.md"
    original = index.read_bytes()
    text = original.decode("utf-8")
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) >= text.index(END):
        raise ValueError("raw/index.md 必须有且仅有一对 raw-queue 标记；拒绝覆盖手写内容")
    newline = "\r\n" if "\r\n" in text else "\n"
    generated = render_queue().replace("\n", newline)
    updated = text[:text.index(START)] + generated + text[text.index(END) + len(END):]
    if not apply:
        return generated
    if updated.encode("utf-8") == original:
        return "raw/index.md 已同步"
    # A single-file replacement is atomic; this is not a vault-wide transaction.
    fd, tmp = tempfile.mkstemp(prefix=".raw-index-", dir=index.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated.encode("utf-8"))
        if index.read_bytes() != original:
            raise RuntimeError("raw/index.md 已被修改，请重读后重试")
        os.replace(tmp, index)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return "已刷新 raw/index.md 的队列区域"


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="经 host Executor 门禁更新队列，保留其余说明")
    parser.add_argument("--state-dir", help="写操作必填：正式库外、同卷的专属私有状态目录")
    parser.add_argument("--operation-id", help="可选的 host 操作标识")
    args = parser.parse_args()
    if args.write:
        if not args.state_dir:
            parser.error("旧写入口已迁移到 host Executor；请显式添加 --state-dir <库外同卷专属目录>，可选 --operation-id。不会自动选择状态目录。")
        return health._apply_via_host("raw-index", health.RAW_ROOT.parent, args.state_dir, args.operation_id)
    try:
        print(refresh_index())
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
