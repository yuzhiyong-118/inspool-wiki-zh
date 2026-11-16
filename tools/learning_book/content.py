"""固定 DT renderer 的内容投影、结构诊断与保守资源依赖识别。"""
from __future__ import annotations

from copy import deepcopy
import re
from urllib.parse import quote, unquote, urlsplit

from .contracts import DeliveryError

RULE = "dt-book-content/1"
UPSTREAM = "60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db"
CAPABILITY = "book-content-read/1"
REMOVED = {
    "book": ("created_at", "updated_at", "revision", "status", "error", "stale_detected_at",
             "chat_session_id", "source", "permission", "can_edit", "can_delete"),
    "book.metadata": ("page_chat_sessions", "compile_started_at"),
    "spine": ("updated_at", "version"),
    "page": ("created_at", "updated_at", "status", "error"),
    "block": ("created_at", "updated_at", "status", "error"),
}
SUPPORTED_BLOCKS = {"text", "section", "callout", "quiz", "concept_graph", "deep_dive", "user_note"}


def supports_choice(question, *, valid_id=True):
    """I4／I5 共用的单答案选择题结构门禁；不承担来源忠实性判断。"""
    options = question.get("options")
    return (valid_id and question.get("question_type") == "choice"
            and isinstance(question.get("question"), str) and bool(question["question"].strip())
            and isinstance(options, dict) and len(options) >= 2
            and all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in options.items())
            and isinstance(question.get("correct_answer"), str) and question["correct_answer"] in options)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def project(value: dict, book_id: str) -> tuple[dict, dict, dict]:
    if (value.get("schema") != CAPABILITY or not isinstance(value.get("book"), dict)
            or not isinstance(value.get("pages"), list)
            or not isinstance(value.get("pageEnumeration"), dict)
            or value["pageEnumeration"].get("mode") != "strict"):
        raise DeliveryError("content_capability", "缺少已验收的完整只读内容能力", "failed")
    if value["book"].get("id") != book_id:
        raise DeliveryError("content_book", "内容 bookId 与活动不符", "conflict")
    findings, unsupported, questions, option_orders = [], [], [], []
    def finding(code, location, *, blocking=True):
        findings.append({"code": code, "location": location, "blocking": blocking})
    enumeration = value["pageEnumeration"]
    if (enumeration.get("errors") != [] or type(enumeration.get("fileCount")) is not int
            or enumeration.get("fileCount") != len(value["pages"])
            or enumeration.get("returnedCount") != len(value["pages"])):
        finding("enumeration_incomplete", "pageEnumeration")
    generation = value.get("generation")
    if not isinstance(generation, dict) or generation.get("working") is not False or generation.get("status") != "ready":
        finding("generation_not_ready", "generation")
    book, spine = value["book"], value.get("spine")
    if book.get("status") != "ready" or book.get("error"):
        finding("book_not_ready", "book")
    if book.get("stale_page_ids"):
        finding("book_sources_stale", "book.stale_page_ids")
    if not isinstance(spine, dict) or spine.get("book_id") != book_id or not isinstance(spine.get("chapters"), list):
        finding("spine_identity", "spine")
        spine = spine if isinstance(spine, dict) else {}
    pages = value["pages"]
    page_ids = [p.get("id") if isinstance(p, dict) else None for p in pages]
    if not pages or any(not isinstance(i, str) or not i for i in page_ids) or len(set(page_ids)) != len(page_ids):
        finding("page_identity", "pages")
    chapter_ids = []
    for ci, chapter in enumerate(spine.get("chapters", [])):
        if not isinstance(chapter, dict):
            finding("chapter_shape", f"spine.chapters[{ci}]")
            continue
        chapter_ids.append(chapter.get("id"))
        if not isinstance(chapter.get("page_ids"), list) or any(p not in page_ids for p in chapter.get("page_ids", [])):
            finding("page_reference_missing", f"spine.chapters[{ci}]")
    if any(not isinstance(i, str) or not i for i in chapter_ids) or len(set(chapter_ids)) != len(chapter_ids):
        finding("chapter_identity", "spine.chapters")
    if book.get("page_count") != len(pages):
        finding("manifest_page_count", "book")
    for pi, page in enumerate(pages):
        pl = f"pages[{pi}]"
        if not isinstance(page, dict):
            raise DeliveryError("page_shape", "页面不是对象", "failed")
        if page.get("book_id") != book_id:
            finding("page_book_identity", pl)
        if page.get("status") != "ready" or page.get("error"):
            finding("page_not_ready", pl)
        if isinstance(page.get('generation'),dict) and page['generation'].get('state')=='running':
            finding('page_generation_active',pl)
        refs = [p.get("target_page_id") for p in page.get("links", []) if isinstance(p, dict)]
        if page.get("parent_page_id"):
            refs.append(page["parent_page_id"])
        if any(ref not in page_ids for ref in refs):
            finding("page_reference_missing", pl)
        blocks = page.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            finding("empty_page", pl)
            blocks = []
        block_ids = [b.get("id") if isinstance(b, dict) else None for b in blocks]
        if any(not isinstance(i, str) or not i for i in block_ids) or len(set(block_ids)) != len(block_ids):
            finding("block_identity", pl)
        for bi, block in enumerate(blocks):
            bl = f"{pl}.blocks[{bi}]"
            if not isinstance(block, dict):
                raise DeliveryError("block_shape", "内容块不是对象", "failed")
            if block.get("status") != "ready" or block.get("error"):
                finding("block_not_ready", bl)
            payload = block.get("payload")
            if not isinstance(payload, dict):
                finding("payload_shape", bl)
                payload = {}
            if any("[generation failed]" in s.lower() for s in strings(payload)) or payload.get("success") is False or payload.get("error"):
                finding("generation_failure", bl)
            kind = block.get("type")
            if kind not in SUPPORTED_BLOCKS:
                unsupported.append({"location": bl, "kind": "block", "type": kind})
            if kind in ("text", "callout"):
                body = payload.get("body", payload.get("content", ""))
                if not isinstance(body, str) or not body.strip():
                    finding("empty_content", bl)
            if kind == "section" and not any(isinstance(s, str) and s.strip() for s in
                    [payload.get("intro"), *[s.get("body") for s in payload.get("subsections", []) if isinstance(s, dict)]]):
                finding("empty_content", bl)
            if kind == "deep_dive" and not any(isinstance(item, dict) and isinstance(item.get("rationale"), str)
                    and item["rationale"].strip() for item in payload.get("suggestions", [])):
                finding("empty_content", bl)
            if kind != "quiz":
                continue
            qs = payload.get("questions")
            if not isinstance(qs, list) or not qs:
                finding("empty_quiz", bl)
                continue
            ids = [q.get("question_id") if isinstance(q, dict) else None for q in qs]
            for qi, q in enumerate(qs):
                ql = f"{bl}.payload.questions[{qi}]"
                if not isinstance(q, dict):
                    finding("question_shape", ql)
                    continue
                qid = q.get("question_id")
                identity = {"pageId": page.get("id"), "blockId": block.get("id"), "questionId": qid}
                valid_id = isinstance(qid, str) and bool(qid.strip()) and ids.count(qid) == 1
                if not valid_id:
                    finding("question_identity", ql)
                if not isinstance(q.get("question"), str) or not q["question"].strip():
                    finding("empty_question", ql)
                options = q.get("options")
                option_orders.append({**identity, "questionIndex": qi, "optionKeys": list(options) if isinstance(options, dict) else None})
                supported = False
                if q.get("question_type") == "choice":
                    supported = supports_choice(q, valid_id=valid_id)
                    if not supported:
                        finding("invalid_choice", ql)
                else:
                    unsupported.append({"location": ql, "kind": "question", "type": q.get("question_type"), **identity})
                questions.append({**identity, "location": ql, "assessmentSupport": "supported" if supported else "unsupported"})
    projection = {"rule": RULE, "book": deepcopy(book), "spine": deepcopy(spine),
                  "pages": deepcopy(pages), "optionDisplayOrders": option_orders}
    extensions = {k: deepcopy(v) for k, v in value.items() if k not in
                  {"schema", "book", "spine", "pages", "generation", "pageEnumeration", "progress", "reading"}}
    if extensions:
        projection["responseExtensions"] = extensions
        unsupported.append({"location": "responseExtensions", "kind": "response", "type": "unknown_extensions"})
    def remove(obj, kind):
        for name in REMOVED[kind]:
            obj.pop(name, None)
    remove(projection["book"], "book")
    metadata = projection["book"].get("metadata")
    if isinstance(metadata, dict):
        remove(metadata, "book.metadata")
    remove(projection["spine"], "spine")
    for page in projection["pages"]:
        remove(page, "page")
        for block in page.get("blocks", []):
            remove(block, "block")
    observation = {"revision": book.get("revision"), "generation": generation,
                   "pageEnumeration": enumeration,
                   "states": [{"id": p["id"], "status": p.get("status"), "error": p.get("error"),
                               "blocks": [{"id": b.get("id"), "status": b.get("status"), "error": b.get("error")}
                                          for b in p.get("blocks", [])]} for p in pages]}
    check = {"findings": findings, "unsupported": unsupported, "questions": questions,
             "supportedChoiceCount": sum(q["assessmentSupport"] == "supported" for q in questions),
             "blocking": any(f["blocking"] for f in findings),
             "contentCoverage": "partial" if any(u["kind"] != "question" for u in unsupported) else "complete"}
    return projection, observation, check


def markdown_dependencies(markdown: str) -> tuple[list[str], list[str]]:
    """只支持可明确解析的图片语法；复杂／动态语法保守标 partial。"""
    issues = []
    lines, fence = [], None
    for line in markdown.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= fence[1] and not match[2].strip():
                fence = None
            lines.append("\n")
            continue
        if match:
            fence = (match[1][0], len(match[1]))
            if re.match(r"(?:mermaid|flow|seq|sequence)\b", match[2].strip(), re.I):
                issues.append("embedded_diagram_unsupported")
            lines.append("\n")
        elif re.match(r"^(?: {4}|\t)", line) and "![" in line:
            issues.append("indented_image_ambiguous")
            lines.append("\n")
        else:
            lines.append(line)
    markdown = "".join(lines)
    markdown = re.sub(r"(`+)([^\n]*?)\1", "", markdown)
    markdown = markdown.replace(r"\!", " ")
    if re.search(r"</?[A-Za-z][\w:-]*(?:\s|>)", markdown):
        issues.append("html_dependency_unsupported")
    # 代码不执行。图代码可能动态引用资源，留给覆盖诊断。
    if re.search(r"```(?:mermaid|flow|seq|sequence)\b", markdown, re.I):
        issues.append("embedded_diagram_unsupported")
    refs = {m.group(1).strip().lower(): m.group(2) for m in re.finditer(
        r'^\s*\[([^\]]+)\]:\s*<?([^\s<>]+)>?(?:\s+["\x27].*)?$', markdown, re.M)}
    found, matched = [], []
    pattern = r'!\[([^\]\n]*)\](?:\(\s*(?:<([^<>\n]+)>|([^\s()]+))(?:\s+["\x27][^\n]*?["\x27])?\s*\)|\[([^\]\n]*)\])'
    for match in re.finditer(pattern, markdown):
        matched.append(match.span())
        uri = match.group(2) or match.group(3)
        if uri is None:
            uri = refs.get((match.group(4) or match.group(1)).strip().lower())
        if uri:
            found.append(uri)
        else:
            issues.append("image_reference_missing")
    residue = markdown
    for start, end in reversed(matched):
        residue = residue[:start] + " " * (end - start) + residue[end:]
    def shortcut(match):
        uri = refs.get(match[1].strip().lower())
        if uri:
            found.append(uri)
            return " " * len(match[0])
        return match[0]
    residue = re.sub(r"!\[([^\]\n]+)\](?![\[(])", shortcut, residue)
    if "![" in residue:
        issues.append("image_syntax_unsupported")
    return found, sorted(set(issues))


def dependencies(value: dict) -> tuple[list[dict], list[dict]]:
    refs, issues = [], []
    for pi, page in enumerate(value["pages"]):
        for bi, block in enumerate(page["blocks"]):
            location = f"pages[{pi}].blocks[{bi}]"
            payload, kind = block["payload"], block.get("type")
            fields = []
            if kind == "text":
                fields.append(("body", payload.get("body", payload.get("content", ""))))
            elif kind == "section":
                fields.append(("intro", payload.get("intro", "")))
                fields.extend((f"subsections[{si}].body", s.get("body", ""))
                              for si, s in enumerate(payload.get("subsections", [])) if isinstance(s, dict))
            elif kind == "quiz":
                for qi, q in enumerate(payload.get("questions", [])):
                    if isinstance(q, dict):
                        fields.extend((f"questions[{qi}].{k}", q.get(k, "")) for k in ("question", "explanation"))
                        if isinstance(q.get("options"), dict):
                            fields.extend((f"questions[{qi}].options[{oi}]", v) for oi, v in enumerate(q["options"].values()))
            elif kind == "concept_graph":
                # 固定概览图内联保存，代码／节点存在外部资源或 HTML 时不声称闭包完整。
                graph_content = [payload.get("code", {}), payload.get("graph", {})]
                if any(re.search(r'https?://|<img\b|<image\b|image\s*:|javascript:|data:', s, re.I) for s in strings(graph_content)):
                    issues.append({"code": "graph_dependency_unsupported", "location": location})
                index = payload.get("index", {})
                if isinstance(index, dict):
                    fields.extend((f"index.chapters[{ci}].summary", c.get("summary", ""))
                                  for ci, c in enumerate(index.get("chapters", [])) if isinstance(c, dict))
            elif kind == "deep_dive":
                fields.extend((f"suggestions[{si}].rationale", s.get("rationale", ""))
                              for si, s in enumerate(payload.get("suggestions", [])) if isinstance(s, dict))
            elif kind == "user_note":
                fields.append(("body", payload.get("body", payload.get("content", ""))))
            elif kind != "callout":
                issues.append({"code": "block_resources_unsupported", "location": location})
            for field, content in fields:
                if not isinstance(content, str):
                    issues.append({"code": "render_field_shape", "location": location + "." + field})
                    continue
                uris, errors = markdown_dependencies(content)
                for uri in uris:
                    refs.append({"uri": uri, "location": location + ".payload." + field})
                issues.extend({"code": code, "location": location + ".payload." + field} for code in errors)
    return refs, issues


def resource_path(uri: str, base_url: str) -> str | None:
    """只允许同部署输出位图；拒绝 query/fragment/多重编码/逃逸/主动内容。"""
    try:
        parsed, base = urlsplit(uri), urlsplit(base_url)
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            return None
        if parsed.netloc and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            return None
        if parsed.scheme and not parsed.netloc:
            return None
        path = unquote(parsed.path)
        if "%" in path or "\\" in path or any(ord(c) < 32 for c in path):
            return None
        if not path.startswith("/files/outputs/"):
            return None
        parts = path[len("/files/outputs/"):].split("/")
        if any(p in ("", ".", "..") or ":" in p for p in parts):
            return None
        if not re.search(r"\.(png|jpg|jpeg|gif|webp)$", parts[-1], re.I):
            return None
        return "/files/outputs/" + "/".join(quote(p, safe="-_.~") for p in parts)
    except ValueError:
        return None
