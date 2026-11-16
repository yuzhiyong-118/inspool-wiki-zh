#!/usr/bin/env python3
"""微信公众号文章解析器（零模型调用）。

默认预览、--full、--json 保持只读解析行为。
--raw 已接管：必须显式 --state-dir <库外同卷状态目录>
--candidate-dir <库外新候选目录>，原始 HTML 字节先进入统一 capture；
仅完整来源包可经 host import-package/Executor 登记 raw/unprocessed。
缺正文、截断、缺附件等情况仅留下候选报告，不推进 ingest/approve。
--out 仅导出库外普通新 Markdown 文件，拒绝覆盖及链接路径。

用法：
  python tools/wechat_article.py https://mp.weixin.qq.com/s/ARTICLE --full
  python tools/wechat_article.py https://mp.weixin.qq.com/s/ARTICLE --json
  python tools/wechat_article.py https://mp.weixin.qq.com/s/ARTICLE --raw --state-dir E:/wiki-state --candidate-dir E:/wechat-candidates/unique-article
  python tools/wechat_article.py https://mp.weixin.qq.com/s/ARTICLE --out E:/exports/new-article.md

路径父目录须预先建立。完整说明见 tools/wiki_runtime/host/WECHAT.md。
write_to_raw_unprocessed 的旧直写兼容入口已封闭；微信资料统一经受管 capture/import。
"""
import argparse
import html
import json
import re
import urllib.parse
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# === 常量 ===

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERER = "https://mp.weixin.qq.com/"
TIMEOUT = 20  # seconds

# Wiki repo layout
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_UNPROCESSED = REPO_ROOT / "raw" / "unprocessed"


# === 抓取 ===

def fetch(url: str) -> str:
    """只读预览兼容字符串接口；导入必须另取原始字节。"""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.wiki_runtime.host.wechat import fetch_bytes
    return fetch_bytes(url).decode("utf-8", errors="replace")


# === 解析 ===

def parse(body: str) -> dict:
    """从公众号 HTML 中解析结构化字段。"""

    # 标题
    m = re.search(r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>', body, re.S)
    title = re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else None

    # 公众号名 —— 4 种来源(按优先级)
    # 1) HTML 元素 <a id="js_name"> 或 <span id="js_name">
    # 2) JS 变量 var nickname = "..."
    # 3) JS 对象 nick_name: '...' / og:article:author
    # 4) HTML <strong class="profile_nickname">
    account = None

    # 路径 1:HTML 元素
    m = re.search(r'<a[^>]*id="js_name"[^>]*>([^<]+)</a>', body)
    if m:
        account = m.group(1).strip() or None
    if not account:
        m = re.search(r'<span[^>]*id="js_name"[^>]*>([^<]+)</span>', body)
        if m:
            account = m.group(1).strip() or None

    # 路径 2:裸 JS 变量
    if not account:
        m = re.search(r'var\s+nickname\s*=\s*"([^"]+)"', body)
        if m:
            account = m.group(1).strip() or None

    # 路径 3:JS 对象 / meta 标签
    if not account:
        m = re.search(r"nick_name\s*:\s*['\"]([^'\"]+)['\"]", body)
        if m:
            account = m.group(1).strip() or None
    if not account:
        m = re.search(r'<meta[^>]*property="og:article:author"[^>]*content="([^"]+)"', body)
        if m:
            account = m.group(1).strip() or None

    # 路径 4:HTML 兜底
    if not account:
        m = re.search(r'<strong[^>]*class="profile_nickname"[^>]*>(.*?)</strong>',
                      body, re.S)
        if m:
            account = re.sub(r'<[^>]+>', '', m.group(1)).strip() or None

    # 作者
    author = None
    m = re.search(r'var author\s*=\s*"([^"]+)"', body)
    if m:
        author = m.group(1).strip() or None
    if not author:
        m = re.search(r'<span[^>]*id="js_author_name"[^>]*>([^<]+)</span>', body)
        if m:
            author = m.group(1).strip() or None

    # 发布时间 —— 三种来源(按优先级尝试)
    # 1) JS 变量 var publish_time = "..."
    # 2) URL 编码 JSON blob 里的 publish_time: 1773194520
    # 3) HTML <em id="publish_time">
    publish_time = None
    publish_ts = None

    # 路径 1:裸 JS 变量
    m = re.search(r'var\s+publish_time\s*=\s*"([^"]+)"', body)
    if m:
        publish_time = m.group(1).strip() or None

    # 路径 2:URL 编码的 JSON blob("publish_time%22%3A1773194520)
    if not publish_time:
        m = re.search(r'publish_time%22%3A(\d{10})', body)
        if m:
            publish_ts = int(m.group(1))

    # 路径 2b:已解码的 JSON(理论上路径 1 已覆盖,这里是双保险)
    if not publish_time and not publish_ts:
        m = re.search(r'"publish_time"\s*:\s*(\d{10})', body)
        if m:
            publish_ts = int(m.group(1))

    # 路径 3:HTML 兜底
    if not publish_time and not publish_ts:
        m = re.search(r'<em[^>]*id="publish_time"[^>]*>([^<]+)</em>', body)
        if m:
            publish_time = m.group(1).strip() or None

    # 把 unix 秒转成可读字符串
    if publish_ts and not publish_time:
        publish_time = datetime.fromtimestamp(publish_ts).strftime("%Y-%m-%d %H:%M:%S")

    # 描述
    desc = None
    m = re.search(r'var msg_desc\s*=\s*"([^"]+)"', body)
    if m:
        desc = html.unescape(m.group(1)).strip() or None

    # 正文
    m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*)', body, re.S)
    if not m:
        raise ValueError("找不到 #js_content —— 可能不是有效公众号文章"
                         "(URL 无效 / 已删除 / 被风控限速)")
    chunk = m.group(1)
    end = re.search(r'</div>\s*<script', chunk)
    content_html = chunk[:end.start() + len('</div>')] if end else chunk

    markdown = html_to_markdown(content_html)
    char_count = len(re.sub(r'\s+', '', markdown))
    image_urls = re.findall(r'!\[图片\]\(([^)]+)\)', markdown)

    return {
        "title": title or "(无标题)",
        "account": account,
        "author": author,
        "publish_time": publish_time,
        "description": desc,
        "char_count": char_count,
        "image_count": len(image_urls),
        "image_urls": image_urls,
        "markdown": markdown,
    }


def html_to_markdown(raw: str) -> str:
    """公众号正文 HTML → 可读 Markdown。"""
    text = raw

    # 图片(优先 data-src,微信懒加载)
    text = re.sub(
        r'<img[^>]*?data-src="([^"]+)"[^>]*?>',
        lambda m: f'\n\n![图片]({m.group(1)})\n\n', text, flags=re.I)
    text = re.sub(
        r'<img[^>]*?src="([^"]+)"[^>]*?>',
        lambda m: f'\n\n![图片]({m.group(1)})\n\n', text, flags=re.I)

    # 链接
    text = re.sub(
        r'<a[^>]*?href="([^"]+)"[^>]*?>(.*?)</a>',
        lambda m: f'[{re.sub(r"<[^>]+>", "", m.group(2)).strip()}]({m.group(1)})',
        text, flags=re.S | re.I)

    # 标题
    text = re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n\n# \1\n\n', text, flags=re.S | re.I)
    text = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n\n## \1\n\n', text, flags=re.S | re.I)
    text = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n\n### \1\n\n', text, flags=re.S | re.I)

    # 粗体 / 斜体 / 代码
    text = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', text, flags=re.S | re.I)
    text = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', text, flags=re.S | re.I)
    text = re.sub(r'<code[^>]*>(.*?)</code>', r'`\1`', text, flags=re.S | re.I)
    text = re.sub(r'<pre[^>]*>(.*?)</pre>',
                  lambda m: '\n\n```\n' +
                  re.sub(r'<[^>]+>', '', m.group(1)).strip() + '\n```\n\n',
                  text, flags=re.S | re.I)

    # 段落 / 换行 / 列表 / 引用 / 分割线
    text = re.sub(r'<p[^>]*>', '\n\n', text, flags=re.I)
    text = re.sub(r'</p\s*>', '\n\n', text, flags=re.I)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
    text = re.sub(r'<li[^>]*>', '\n- ', text, flags=re.I)
    text = re.sub(r'</li\s*>', '', text, flags=re.I)
    text = re.sub(r'</?(ul|ol)[^>]*>', '\n', text, flags=re.I)
    text = re.sub(r'<blockquote[^>]*>', '\n\n> ', text, flags=re.I)
    text = re.sub(r'</blockquote\s*>', '\n\n', text, flags=re.I)
    text = re.sub(r'<hr\s*/?>', '\n\n---\n\n', text, flags=re.I)

    # 清理
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+\n', '\n', text)

    return text.strip()


# === 输出 ===

def to_markdown_doc(article: dict, url: str) -> str:
    """完整的 Markdown 文档(元信息头 + 正文)。"""
    meta_lines = [
        f"# {article['title']}",
        "",
        f"> 原文链接: {url}",
        f"> 公众号: **{article['account']}**" if article['account'] else "",
        f"> 作者: {article['author']}" if article['author'] else "",
        f"> 发布时间: {article['publish_time']}" if article['publish_time'] else "",
        f"> 字数: {article['char_count']} | 图片: {article['image_count']} 张",
        "",
    ]
    meta = "\n".join(line for line in meta_lines if line)
    if article.get('description'):
        meta += f"\n**摘要**: {article['description']}\n"
    return meta + "\n---\n\n" + article['markdown']


def make_preview(article: dict, n: int = 500) -> str:
    md = article['markdown']
    if len(md) <= n:
        return md
    return md[:n].rsplit('\n', 1)[0] + f"\n\n... (共 {article['char_count']} 字)"


def build_raw_filename(url: str) -> str:
    """从 URL 末尾生成可读文件名:wechat-<slug>-<short-id>.md"""
    # URL 末尾的 ID 取前 8 位作为短 ID
    short_id = re.search(r'/s/([^?#]+)', url)
    short_id = short_id.group(1)[:8] if short_id else 'unknown'

    # 第一次抓取后我们用标题作为 slug;这里先用 ID 占位,实际写入由 caller 替换
    return f"wechat-{short_id}.md"


def build_raw_frontmatter(article: dict, url: str) -> str:
    """生成 raw 文件的流程 frontmatter(AGENTS.md §Raw 流程元数据)。"""
    today = datetime.now().strftime("%Y-%m-%d")
    return (
        "---\n"
        f"type: raw-source\n"
        f"source_type: wechat-article\n"
        f"external_url: {url}\n"
        f"title: \"{article['title']}\"\n"
        f"account: \"{article['account'] or ''}\"\n"
        f"author: \"{article['author'] or ''}\"\n"
        f"publish_time: \"{article['publish_time'] or ''}\"\n"
        f"processing_status: unprocessed\n"
        f"fetched_at: {today}\n"
        f"---\n\n"
    )


def write_to_raw_unprocessed(article: dict, url: str) -> Path:
    """旧直写入口已封闭；微信资料必须使用受管 capture/import。"""
    from tools.wiki_runtime.runtime.migration import MigrationError
    raise MigrationError('微信 raw 直写已封闭；请使用 host.wechat.capture_url 受管入口')


# === CLI ===

def main(argv=None):
    # 兼容直接 python tools/wechat_article.py 与模块导入两种入口。
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from tools.wiki_runtime.host.wechat import capture_url, export_markdown
    ap = argparse.ArgumentParser(
        description="微信公众号文章解析器(inspool-wiki-zh 工具)",
        epilog="详见脚本顶部 docstring 中的文档章节。",
    )
    ap.add_argument("url", help="mp.weixin.qq.com/s/... 文章 URL")
    ap.add_argument("--full", action="store_true",
                    help="输出完整正文(默认只看开头 500 字)")
    ap.add_argument("--json", action="store_true", help="输出 JSON 格式")
    ap.add_argument("--out", help="导出库外普通新 Markdown 文件；拒绝覆盖")
    ap.add_argument("--raw", action="store_true",
                    help="完整来源包经 host/Executor 登记 unprocessed")
    ap.add_argument("--state-dir", help="显式库外同卷私有状态目录（--raw 必填）")
    ap.add_argument("--candidate-dir", help="显式库外全新可信候选目录（--raw 必填）")
    args = ap.parse_args(argv)
    if args.raw and (not args.state_dir or not args.candidate_dir):
        ap.error('--raw 需要显式 --state-dir 和 --candidate-dir，禁止直接写 raw')
    if args.raw and (args.out or args.json or args.full):
        ap.error('--raw 不可与 --out/--json/--full 混用')
    if args.out and args.json:
        ap.error('--out 不可与 --json 混用')
    if args.raw:
        try:
            report = capture_url(REPO_ROOT, args.state_dir, args.candidate_dir, args.url)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report['applied'] else 1
        except Exception as exc:
            print(f'采集拒绝: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 2

    try:
        print(f"Fetching: {args.url}", file=sys.stderr)
        body = fetch(args.url)
        article = parse(body)
    except urllib.error.HTTPError as e:
        print(f"HTTP 错误 {e.code}: {e.reason}", file=sys.stderr)
        print("(公众号文章如返回 401/403,通常是因为缺 Referer 或被风控限速)",
              file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"未知错误: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    # 输出路由
    if args.json:
        out = {k: v for k, v in article.items() if k != "markdown"}
        out["url"] = args.url
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    md_doc = to_markdown_doc(article, args.url)

    if args.out:
        try:
            export_markdown(REPO_ROOT, args.out, md_doc, state_dir=args.state_dir)
        except (ValueError, OSError) as exc:
            print(f'导出拒绝: {exc}', file=sys.stderr)
            return 2
        print(f"✓ 已写入: {args.out}", file=sys.stderr)
        print(f"  字数: {article['char_count']} | 图片: {article['image_count']} 张",
              file=sys.stderr)
        return

    if args.full:
        print(md_doc)
    else:
        print(md_doc.split('\n---\n\n')[0])
        print()
        print(make_preview(article, n=500))


if __name__ == "__main__":
    raise SystemExit(main())
