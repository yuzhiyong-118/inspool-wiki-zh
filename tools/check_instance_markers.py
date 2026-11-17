"""扫描公开仓库中的「实例级私人痕迹」形态，供设计迁移的复核方独立复现。

这个工具是**复核辅助**，不是发布门禁的一部分：`tools/check_public_release.py`
管的是可达性、凭据形态、标题与 frontmatter、锚点与越界路径，不管隐私语义。
两者覆盖的东西不同，不能互相替代。

它回答的问题是：公开树里还有没有「某一次个人运行」的痕迹形态——实例控制身份、
试学地址、对象标识、课程活动标识、私有课程项目名、个人选择、实例运行标签、
实例目录名、本机端口、实例账本金额。

用法::

    python -B tools/check_instance_markers.py            # 扫当前暂存树
    python -B tools/check_instance_markers.py --commits  # 逐个扫未推送区间的提交
    python -B tools/check_instance_markers.py --range f2cea87..main

退出码：0 表示没有命中，1 表示有命中。

局限（必须与结论一起说，不能只报「0 命中」）
------------------------------------------------
1. **它判的是形态，不是语义。** 命中说明「这里有个人运行的痕迹形态」，
   需要人工判断它是不是私人内容；不命中**不能**证明内容已脱敏。设计参数
   （授权额度、暂停线、门禁与回归计数、发行物文件数）刻意保留并被排除在
   命中之外，但界线由人划定。
2. **它只看得见公开仓库自身。** 迁移当时真正起作用的排查是把私有源文件
   逐行建索引、再与公开侧比对「逐字相同且带个人语义」的候选——那一轮需要
   私有工作区，无法在本仓库内复现。本工具是那一轮的**形态子集**。
3. **它扫不到语义等价但措辞完全不同的泄漏。** 同一件事写成「累计用量」
   和写成「本窗口新增计量」，前者命中、后者可能不命中。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --- 明确私人形态：命中即需处理 ---
BLOCKING = [
    ('实例控制身份', re.compile(r'\barchitecture-cumulative[\w-]*')),
    ('试学地址', re.compile(r'https?://127\.0\.0\.1:\d+/[^\s`）)、，；<>]*')),
    ('课程活动标识', re.compile(r'\b(?:geo-flow-agent|system-architecture)-\d{8}\b')),
    ('私有课程项目名', re.compile(r'\bgeo_flow\b|\bGeoFlow\b')),
    ('对象标识', re.compile(r'\b(?:bk|pg|blk)_[0-9a-f]{8,}\b')),
    ('个人选择', re.compile(r'用户选择[^。；\n]{0,40}不备份|用户已选择[^。；\n]{0,30}作为真实课程')),
    ('实例运行标签', re.compile(r'\bprepared-quiz-\d+\b|\bquiz_regeneration_interrupted\b')),
    ('实例目录名', re.compile(r'\bruntime-i\d+\b')),
    ('本机端口（散文）', re.compile(r'(?<![\w.])(?:API 8136|Web 3836|网页 3836)(?![\d.])')),
    ('本机端口（成对）', re.compile(r'(?<![\w./])(?:端口\s*)?\d{4}/\d{4}(?![\d/])')),
    ('旧式累计用量', re.compile(
        r'累计(?:至|为)?\s*[\d,]{5,}(?![,\d])(?!\s*、[\d,]+ 暂停)'
        r'|\d+\s*条／[\d,]{5,}|[\d,]{5,}\s*tokens')),
]

# --- 语境数字：账本类关键词后接大数，且不是授权额度 ---
LEDGER_KEY = re.compile(
    r'(?:账本|合并视角|实报|失败估算|合计新增|首轮增量|超额|续测计量|阶段基线|终值|增量|累计)')
NUMBER = re.compile(r'\d{1,3}(?:,\d{3})+|\d{5,}')
# 数字之前的额度语境：这些是设计参数（授权额度、暂停线），刻意保留
QUOTA_BEFORE = re.compile(r'另批|获准|授权|上限|暂停|额度|限额|总额')
# 数字之后的额度语境。前缀不允许含数字——否则额度词属于后面另一个量，
# 不能用来排除当前这个数字（「账本 567,049、80 万暂停」里的 567,049 是账本金额）。
QUOTA_AFTER = re.compile(r'^[^\d\n]{0,4}?(?:暂停|上限|额度|限额|授权|获准|另批|总额)')
# 关键词之后搜索数字的窗口要够长，否则表格单元格里的金额会被截断而漏掉
GAP_WINDOW = 40

# 已判定为「授权额度／暂停线」的设计参数取值。批次 I 与批次 J 反复核对过：
# 这些数值本身是设计参数，公开它们不泄漏个人运行记录。
#
# 为什么需要这个集合：授权额度在句子里常常不带额度标记——
# 「本轮累计输入＋输出 **1,000,000 原始 tokens**」这一句里没有任何「上限」字样，
# 要到下一句的「800,000 时停止新增调用并暂停」才点明它是额度。局部上下文判断
# 在这种句式下必然失效，所以额度值本身需要被认出来。
#
# 代价：一个真实账本金额若恰好等于某个额度值，会被一并排除。因为该数值已经
# 以额度身份公开，不构成额外泄漏；额度值改变时这里需要同步更新。
AUTHORIZED_QUOTA = re.compile(
    r'^(?:1,000,000|800,000|300,000|200,000|30,000|24,000)$')


def _quota_context(before, gap_head, after):
    """判断这个数字是不是「授权额度」而非「实例账本金额」。

    三处都查：关键词之前的少量上下文、关键词与数字之间的整段（跨句时额度词
    常在这一段里）、数字之后的紧邻上下文。
    """
    if QUOTA_BEFORE.search(before[-14:]):
        return True
    if QUOTA_BEFORE.search(gap_head):
        return True
    return bool(QUOTA_AFTER.match(after[:8]))


def scan_text(text):
    """返回 [(类别, 行号, 片段)]，行号从 1 起。"""
    out = []
    for name, pat in BLOCKING:
        for m in pat.finditer(text):
            line = text.count('\n', 0, m.start()) + 1
            out.append((name, line, m.group(0)[:60]))
    for m in LEDGER_KEY.finditer(text):
        gap = text[m.end():m.end() + GAP_WINDOW]
        nm = NUMBER.search(gap)
        if not nm:
            continue
        before = text[max(0, m.start() - 14):m.end()]
        gap_head = gap[:nm.start()]
        after = text[m.end() + nm.end():m.end() + nm.end() + 8]
        if AUTHORIZED_QUOTA.match(nm.group(0)):
            continue
        if _quota_context(before, gap_head, after):
            continue
        line = text.count('\n', 0, m.start()) + 1
        out.append(('实例账本金额', line, (m.group(0) + nm.group(0))[:60]))
    return out


def _git(*args):
    return subprocess.run(['git', '-C', str(ROOT), *args],
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace').stdout


def _markdown_blobs(rev):
    """一次 cat-file --batch 读完某个修订的 Markdown 内容。"""
    tree = _git('ls-tree', '-r', rev)
    items = []
    for line in tree.splitlines():
        if '\t' not in line:
            continue
        meta, path = line.split('\t', 1)
        if path.lower().endswith('.md'):
            items.append((path, meta.split()[2]))
    if not items:
        return []
    request = ''.join(oid + '\n' for _, oid in items).encode('ascii')
    proc = subprocess.run(['git', '-C', str(ROOT), 'cat-file', '--batch'],
                          input=request, capture_output=True)
    data = proc.stdout
    out = []
    pos = 0
    for path, _oid in items:
        nl = data.find(b'\n', pos)
        if nl < 0:
            break
        header = data[pos:nl].decode('ascii', 'replace').split()
        if len(header) < 3:
            pos = nl + 1
            continue
        size = int(header[2])
        start = nl + 1
        out.append((path, data[start:start + size].decode('utf-8', 'replace')))
        pos = start + size + 1
    return out


def _worktree_markdown():
    """工作区里已跟踪的 Markdown（等价于暂存树内容，因为未跟踪文件不发布）。"""
    names = [n for n in _git('ls-files').splitlines()
             if n.strip().lower().endswith('.md')]
    out = []
    for path in names:
        try:
            text = (ROOT / path).read_bytes().decode('utf-8', 'replace')
        except OSError:
            continue
        out.append((path, text))
    return out


def _report(title, items):
    print(title)
    if not items:
        print('  0 命中')
        return 0
    total = 0
    for path, hits in items:
        for name, line, snippet in hits:
            total += 1
            print('  [%s] %s:%d  %s' % (name, path, line, snippet))
    print('  合计 %d 处' % total)
    return total


def main():
    ap = argparse.ArgumentParser(description='扫描公开仓库中的实例级私人痕迹形态')
    ap.add_argument('--commits', action='store_true',
                    help='逐个扫描未推送区间的每个提交')
    ap.add_argument('--range', dest='range_', default='f2cea87..main',
                    help='配合 --commits 使用的修订区间（默认 f2cea87..main）')
    ap.add_argument('--rev', default=None,
                    help='扫描指定修订的树（默认当前工作区）')
    args = ap.parse_args()

    total = 0
    if args.rev:
        blobs = _markdown_blobs(args.rev)
        items = []
        for path, text in blobs:
            hits = scan_text(text)
            if hits:
                items.append((path, hits))
        total += _report('=== 修订 %s ===' % args.rev, items)
    elif args.commits:
        commits = [c for c in _git('log', '--format=%H %s', args.range_).strip().splitlines() if c]
        for line in commits:
            sha, subject = line.split(' ', 1)
            tags = [t for t in _git('tag', '--points-at', sha).splitlines() if t]
            blobs = _markdown_blobs(sha)
            items = []
            for path, text in blobs:
                hits = scan_text(text)
                if hits:
                    items.append((path, hits))
            label = tags[0] if tags else '-'
            print('--- %s %s %s' % (sha[:8], label, subject[:40]))
            if items:
                total += _report('    命中', items)
            else:
                print('    0 命中')
    else:
        items = []
        for path, text in _worktree_markdown():
            hits = scan_text(text)
            if hits:
                items.append((path, hits))
        total += _report('=== 当前工作区（已跟踪 Markdown）===', items)

    print()
    if total:
        print('结论：%d 处实例级私人痕迹形态命中，需人工判定并处理。' % total)
        return 1
    print('结论：0 处命中。注意这只说明「没有命中已知形态」，不等于内容已脱敏；'
          '形态之外的语义泄漏需要人工判断。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
