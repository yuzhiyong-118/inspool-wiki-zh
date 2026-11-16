"""固定 DeepTutor 1.7.2 HTTP 契约；无自动重试、无 Book GET 恢复副作用。"""
from __future__ import annotations

from dataclasses import dataclass
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts import DeliveryError, decode_json, digest, object_value, sha256


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    content_type: str
    wire_sha256: str | None = None
    redacted: bool = False

    def value(self):
        try:
            return decode_json(self.body)
        except (ValueError, UnicodeError, DeliveryError) as exc:
            raise DeliveryError("response_shape", "上游响应不是完整 JSON 对象", "uncertain") from exc

    def json(self) -> dict:
        try:
            return object_value(self.value(), "response")
        except DeliveryError as exc:
            raise DeliveryError("response_shape", "上游响应不是完整 JSON 对象", "uncertain") from exc


def multipart(fields: dict, files: dict[str, bytes] | None = None) -> tuple[bytes, str]:
    files = files or {}
    boundary = "i3-" + digest({"fields": fields, "files": {k: sha256(v) for k, v in files.items()}})
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
    for filename, data in files.items():
        mime = "text/markdown" if filename.endswith(".md") else "text/plain"
        parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), data, b"\r\n"])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def segment(value: str) -> str:
    return quote(value, safe="")


class DeepTutor:
    def __init__(self, config: dict):
        self.config, self.scope = config, config["scope"]
        self.timeout = float(config.get("timeoutSeconds", 60))
        if not 0 < self.timeout <= 3600:
            raise DeliveryError("timeout", "timeoutSeconds 必须在 (0,3600] 内")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method: str, path: str, body: bytes | None = None,
                content_type: str = "application/json", *, kb: bool = False) -> Response:
        headers = {"Accept": "application/json"}
        token = None
        if body is not None:
            headers["Content-Type"] = content_type
        if not kb:
            headers["x-deeptutor-workspace"] = self.scope["workspaceId"]
        token_env = self.config.get("tokenEnv")
        if token_env:
            token = os.environ.get(token_env)
            if not token:
                raise DeliveryError("credential_missing", "凭据环境引用未设置", "failed")
            headers["Authorization"] = "Bearer " + token
        request = Request(self.config["baseUrl"] + path, data=body, headers=headers, method=method)
        try:
            try:
                stream = self.opener.open(request, timeout=self.timeout)
            except HTTPError as exc:
                stream = exc
            with stream:
                data = stream.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise DeliveryError("response_size", "响应超过本期上限", "uncertain")
                expected = stream.headers.get("Content-Length")
                if expected is not None and len(data) != int(expected):
                    raise DeliveryError("response_truncated", "响应字节不完整", "uncertain")
                wire_hash = sha256(data)
                safe = data.replace(token.encode(), b"[REDACTED]") if token else data
                return Response(stream.code, safe, stream.headers.get("Content-Type", ""),
                                wire_hash, safe != data)
        except DeliveryError:
            raise
        except (OSError, URLError, ValueError) as exc:
            raise DeliveryError("transport_unknown", "HTTP 传输未取得完整响应；写入结果待核对", "uncertain") from exc
        except Exception as exc:
            # 不输出带 URL/凭据/服务端细节的异常原文。
            raise DeliveryError("transport_unknown", "HTTP 响应读取失败", "uncertain") from exc

    def read(self, path: str, *, kb: bool = False) -> Response:
        # 所有调用点只能选择固定的纯观察路径；尤其不提供 GET /books/{id}。
        allowed = (path in ("/api/books", "/api/auth/profile") or
                   re.fullmatch(r"/api/books/[A-Za-z0-9_-]+/(content|learning-state|question-capability|author-delivery-capability|extension-capability|extension-evidence|extension-context)", path) is not None or
                   re.fullmatch(r"/api/books/(quiz-publications|author-deliveries|extensions)/[A-Za-z0-9_-]{1,180}\?book_id=[A-Za-z0-9_-]+", path) is not None or
                   re.fullmatch(r"/api/sessions/[A-Za-z0-9_-]{1,180}(?:/organization)?", path) is not None or
                   re.fullmatch(r"/api/sessions/[A-Za-z0-9_-]{1,180}/messages/[1-9][0-9]*/events\?after_seq=[0-9]+&limit=(?:[1-9][0-9]{0,2}|1000)", path) is not None or
                   (path.startswith("/api/knowledge-bases/") and
                    (path.endswith(("/files", "/indexing-run", "/indexing-readiness")) or "/files/" in path)) or
                   (path.startswith("/api/books/") and
                    (path.endswith("/spine") or "/pages/" in path)))
        if not allowed:
            raise DeliveryError("read_side_effect", "该读取未被列入无生成副作用清单")
        return self.request("GET", path, kb=kb)

    def read_content(self, book_id: str) -> Response:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", book_id):
            raise DeliveryError("book_id", "bookId 不符合固定上游存储身份规则")
        response = self.read("/api/books/" + book_id + "/content")
        if response.status != 200:
            raise DeliveryError("content_unavailable", "只读内容入口不可用；不回退普通整书读取", "failed")
        if response.redacted:
            raise DeliveryError("content_redacted", "去敏响应不能成为完整原始内容证据", "partial")
        return response

    def read_resource(self, uri: str) -> Response:
        from .content import resource_path
        path = resource_path(uri, self.config["baseUrl"])
        if path is None:
            raise DeliveryError("resource_unsupported", "资源不在同部署静态位图读取范围", "partial")
        return self.request("GET", path)

    def read_learning_state(self, book_id: str) -> Response:
        from .content import UPSTREAM
        from .learning_state import validate_learning_state
        if not re.fullmatch(r"[A-Za-z0-9_-]+", book_id):
            raise DeliveryError("book_id", "bookId 不符合固定上游存储身份规则")
        build = self.config.get("learningStateReadBuild")
        if not isinstance(build, dict) or build.get("baseCommit") != UPSTREAM:
            raise DeliveryError("learning_state_build", "须明确配置固定源码的 learning-state 构建；不回退旧读取")
        self.verify_scope()
        response = self.read("/api/books/" + book_id + "/learning-state")
        if response.redacted:
            raise DeliveryError("learning_state_redacted", "去敏响应不能成为完整原始学习记录", "partial")
        if response.status != 200:
            raise DeliveryError("learning_state_unavailable", "严格学习状态入口不可用；不回退旧 Book GET", "partial")
        validate_learning_state(response.json(), book_id, self.scope)
        return response

    def verify_scope(self):
        if self.config.get("tokenEnv") and not os.environ.get(self.config["tokenEnv"]):
            raise DeliveryError("credential_missing", "凭据环境引用未设置", "failed")
        if self.scope["scopeVerification"] == "authenticated":
            response = self.read("/api/auth/profile")
            if response.status != 200 or response.json().get("id") != self.scope["ownerId"]:
                raise DeliveryError("owner_mismatch", "后端认证身份与配置 owner 不符", "conflict")
        # 匿名部署仅是受控配置绑定，不伪造服务端身份认证。


def parse_book_result(operation: str, response: Response, expected_book: str | None = None) -> dict:
    value = response.json()
    def revision(number):
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise DeliveryError("response_revision", "响应缺少有效 revision", "uncertain")
        return number
    if operation == 'append-extension':
        blocks = value.get('blocks')
        publication = value.get('publication', {})
        if (not isinstance(blocks, list) or not blocks
                or any(not isinstance(block, dict) or block.get('status') != 'ready'
                       or block.get('metadata', {}).get('quality_review') != 'unreviewed' for block in blocks)
                or publication.get('schema') != 'learning-controlled-extension/1'):
            raise DeliveryError('response_extension', '扩展响应缺少完整新块、未审状态或提交身份', 'uncertain')
        return {'bookId': expected_book, 'revision': revision(value.get('book_revision')),
                'artifact': 'learning_extension', 'observedStatus': 'ready', 'qualityReview': 'unreviewed'}
    if operation == 'author-block':
        block = value.get('block')
        publication = value.get('publication', {})
        if (not isinstance(block, dict) or block.get('type') != 'text' or block.get('status') != 'ready'
                or not block.get('payload', {}).get('body') or publication.get('schema') != 'learning-authored-delivery/1'):
            raise DeliveryError('response_author_block', '未取得完整作者正文块及交付身份', 'uncertain')
        return {'bookId': expected_book, 'revision': revision(value.get('book_revision')),
                'artifact': 'author_block', 'observedStatus': block['status'], 'qualityReview': 'required'}
    if operation == 'complete-authored-book':
        book = value.get('book')
        generation = value.get('generation', {})
        publication = value.get('publication', {})
        if (not isinstance(book, dict) or book.get('id') != expected_book or book.get('status') != 'ready'
                or generation.get('status') != 'ready' or generation.get('working') is not False
                or publication.get('schema') != 'learning-authored-delivery/1'):
            raise DeliveryError('response_author_completion', '整书未完成或交付身份不符', 'uncertain')
        rev = revision(value.get('book_revision'))
        if revision(book.get('revision')) != rev:
            raise DeliveryError('response_revision', '整书响应 revision 不一致', 'uncertain')
        return {'bookId': expected_book, 'revision': rev, 'artifact': 'authored_book',
                'observedStatus': 'ready', 'deliveryReadiness': 'complete'}
    if operation in ('prepare-quiz', 'publish-quiz'):
        block=value.get('block')
        if (not isinstance(block,dict) or not block.get('id') or block.get('type')!='quiz' or
                block.get('status')!='ready' or not block.get('payload',{}).get('questions')):
            raise DeliveryError('response_quiz','未取得完整可审查的题块','uncertain')
        return {'bookId':expected_book,'revision':revision(value.get('book_revision')),
                'artifact':'quiz','observedStatus':block['status'],'qualityReview':'required'}
    if operation in ("create", "confirm-proposal"):
        book = value.get("book")
        part = "proposal" if operation == "create" else "spine"
        if (not isinstance(book, dict) or not isinstance(book.get("id"), str) or not book["id"]
                or not isinstance(value.get(part), dict) or not value[part]):
            raise DeliveryError("response_identity", "响应缺少 book 或阶段产物身份", "uncertain")
        if expected_book and book["id"] != expected_book:
            raise DeliveryError("response_book", "响应 bookId 不匹配", "uncertain")
        if operation == "confirm-proposal" and value["spine"].get("book_id") != book["id"]:
            raise DeliveryError("response_spine", "spine 未绑定同一 bookId", "uncertain")
        rev = revision(book.get("revision"))
        if operation != "create" and revision(value.get("book_revision")) != rev:
            raise DeliveryError("response_revision", "book 与确认响应 revision 不一致", "uncertain")
        return {"bookId": book["id"], "revision": rev, "artifact": part,
                "observedStatus": book.get("status", "unknown")}
    pages = value.get("pages")
    if not isinstance(pages, list) or not pages:
        raise DeliveryError("response_pages", "确认响应缺少页面壳", "uncertain")
    ids = set()
    for page in pages:
        if (not isinstance(page, dict) or not isinstance(page.get("id"), str) or not page["id"] or page["id"] in ids
                or page.get("book_id") != expected_book or not isinstance(page.get("status"), str)):
            raise DeliveryError("response_page_identity", "页面壳身份或实际状态缺失", "uncertain")
        ids.add(page["id"])
    return {"bookId": expected_book, "revision": revision(value.get("book_revision")),
            "artifact": "pages", "pages": [{"pageId": p["id"], "status": p["status"]} for p in pages],
            "deliveryReadiness": "not_evaluated", "autoCompile": False}
