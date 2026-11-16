"""进程级排他、本地不可变证据、可重建视图。没有业务进度镜像。"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import time
import uuid

from .contracts import DeliveryError, canonical, digest, read_json, safe_state_root, sha256


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic(path: Path, data: bytes, *, immutable: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != data:
            raise DeliveryError("evidence_conflict", "不可变证据已经存在且内容不一致", "conflict")
        return
    # 不重复目标文件名，避免 Windows 多层证据目录＋hash 文件名使临时
    # 路径越过 Win32 长度上限；仍在同目录、同卷原子发布。
    temp = path.with_name(".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temp, path)  # 完整文件一次发布；并发时不覆盖既有事实。
            except FileExistsError:
                if path.read_bytes() != data:
                    raise DeliveryError("evidence_conflict", "不可变证据并发冲突", "conflict")
        else:
            os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class EvidenceStore:
    def __init__(self, root: Path | str):
        self.root = safe_state_root(root)

    def request_dir(self, request_id: str) -> Path:
        return self.root / "requests" / digest(request_id)

    def request(self, request_id: str) -> dict:
        path = self.request_dir(request_id) / "request.json"
        if not path.is_file():
            raise DeliveryError("request_missing", "找不到该请求", "failed")
        value = read_json(path)
        if value.get("requestId") != request_id or value.get("digest") != digest(value.get("semantic")):
            raise DeliveryError("request_integrity", "请求身份或摘要损坏", "conflict")
        return value

    def requests(self):
        for path in sorted((self.root / "requests").glob("*/request.json")):
            value = read_json(path)
            yield self.request(value["requestId"])

    @contextmanager
    def lock(self, scope: dict):
        # KB 属于账户资源库，锁扩大到 deployment+owner；不同 Book workspace
        # 也不能同时向同一账户语料写入。锁文件保留，但锁本身随进程结束释放。
        # 首期进一步收窄为同一个 state root 的全局单写者，避免跨部署同活动
        # 在保存映射前各创建一本书；不要求不同部署并行生产。
        path = self.root / "locks" / "production.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise DeliveryError("scope_busy", "该后端已有项目生产操作在途", "busy") from exc
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def prepare(self, request_id: str, semantic: dict, *, audit: dict | None = None) -> tuple[dict, bool]:
        path = self.request_dir(request_id) / "request.json"
        if path.exists():
            value = self.request(request_id)
            if value["digest"] != digest(semantic):
                raise DeliveryError("request_conflict", "同 requestId 的有效输入不同", "conflict")
            return value, False
        value = {"schemaVersion": 1, "requestId": request_id, "digest": digest(semantic),
                 "semantic": semantic, "audit": audit or {}, "preparedAt": now()}
        atomic(path, canonical(value), immutable=True)
        self.save_receipt(request_id, "prepared")
        return value, True

    def receipt(self, request_id: str) -> dict:
        request = self.request(request_id)
        path = self.request_dir(request_id) / "receipt.json"
        if path.exists():
            receipt = read_json(path)
            if receipt.get("requestDigest") != request["digest"]:
                raise DeliveryError("receipt_integrity", "回执与请求摘要不匹配", "conflict")
            return receipt
        return {"requestId": request_id, "status": "prepared", "requestDigest": request["digest"],
                "operation": request["semantic"]["operation"], "scope": request["semantic"]["scope"]}

    def save_receipt(self, request_id: str, status: str, **fields) -> dict:
        request = self.request(request_id)
        value = {"schemaVersion": 1, "receiptId": "rcpt_" + uuid.uuid4().hex,
                 "requestId": request_id, "requestDigest": request["digest"],
                 "operation": request["semantic"]["operation"], "scope": request["semantic"]["scope"],
                 "status": status, "recordedAt": now(), **fields}
        directory = self.request_dir(request_id)
        atomic(directory / "receipts" / (value["receiptId"] + ".json"), canonical(value), immutable=True)
        atomic(directory / "receipt.json", canonical(value))
        return value

    def stage_dir(self, request_id: str, stage: str) -> Path:
        # stage 是内部常量，不接受路径字符串。
        if not stage.replace("-", "").replace("_", "").isalnum():
            raise DeliveryError("stage", "无效证据阶段")
        return self.request_dir(request_id) / "stages" / stage

    def dispatch(self, request_id: str, stage: str, request: dict):
        directory = self.stage_dir(request_id, stage)
        atomic(directory / "request.json", canonical(request), immutable=True)
        marker = directory / "dispatching.json"
        if marker.exists():
            raise DeliveryError("already_dispatching", "该阶段已发出，不能再次发送", "uncertain")
        atomic(marker, canonical({"at": now(), "requestDigest": digest(request)}), immutable=True)
        self.save_receipt(request_id, "dispatching", stage=stage)

    def response(self, request_id: str, stage: str) -> tuple[dict, bytes] | None:
        directory = self.stage_dir(request_id, stage)
        meta = directory / "response.json"
        if not meta.exists():
            return None
        value = read_json(meta)
        body = (directory / "response.bin").read_bytes()
        if sha256(body) != value.get("sha256"):
            raise DeliveryError("response_integrity", "远端响应证据损坏", "uncertain")
        return value, body

    def save_response(self, request_id: str, stage: str, status: int, body: bytes, content_type: str,
                      *, wire_sha256=None, redacted=False):
        directory = self.stage_dir(request_id, stage)
        atomic(directory / "response.bin", body, immutable=True)
        atomic(directory / "response.json", canonical({"status": status, "sha256": sha256(body),
               "contentType": content_type, "wireSha256": wire_sha256 or sha256(body),
               "redacted": redacted, "at": now()}), immutable=True)

    def observation(self, request_id: str, name: str, value: dict):
        atomic(self.request_dir(request_id) / "observations" / (name + "-" + uuid.uuid4().hex + ".json"),
               canonical({"at": now(), **value}), immutable=True)

    def mapping(self, activity_id: str) -> dict | None:
        path = self.root / "activities" / (digest(activity_id) + ".json")
        return read_json(path) if path.exists() else None

    def map_activity(self, activity_id: str, scope: dict, book_id: str, request_id: str):
        value = {"activityId": activity_id, "scope": scope, "bookId": book_id,
                 "productionRequestId": request_id}
        atomic(self.root / "activities" / (digest(activity_id) + ".json"), canonical(value), immutable=True)

    def check_reservation(self, operation: str, identity: dict, request_id: str, scope: dict):
        for request in self.requests():
            if request["requestId"] == request_id:
                continue
            semantic = request["semantic"]
            if semantic["operation"] != operation:
                continue
            matches = all(semantic.get(k) == v for k, v in identity.items())
            if not matches:
                continue
            # 活动全局稳定；corpus 则按 deployment+owner，不按 Book workspace。
            if operation == "publish-inputs" and any(semantic["scope"][k] != scope[k]
                                                    for k in ("deploymentId", "ownerId")):
                continue
            status = self.receipt(request["requestId"])["status"]
            if status != "failed":
                raise DeliveryError("identity_reserved", "同一活动、语料版本或确认步骤已有生产记录；先核对旧请求", "conflict")

    def check_versions(self, corpus: dict):
        for request in self.requests():
            previous = request["semantic"].get("corpus")
            if not previous:
                continue
            if ((previous["corpusId"], previous["corpusVersionId"]) ==
                    (corpus["corpusId"], corpus["corpusVersionId"]) and digest(previous) != digest(corpus)):
                raise DeliveryError("corpus_version_conflict", "同一语料版本的内容或成员被修改", "conflict")
            for kind, keys in (("sources", ("sourceId", "sourceVersionId")),
                               ("inputArtifacts", ("inputArtifactId",))):
                old = {tuple(v[k] for k in keys): v for v in previous[kind]}
                for row in corpus[kind]:
                    key = tuple(row[k] for k in keys)
                    if key in old and old[key] != row:
                        raise DeliveryError("version_conflict", "来源版本或提取物身份对应了不同内容", "conflict")

    def bind_budget(self, context: dict, scope: dict):
        # 重启同实例时可重新绑定经核验的 server PID，不允许借此重置额度／基线。
        value = {"context": {k: v for k, v in context.items() if k != "stopProcess"}, "scope": scope}
        atomic(self.root / "budgets" / (digest(context["contextId"]) + ".json"),
               canonical(value), immutable=True)

    def rebuild_index(self) -> dict:
        index = {r["requestId"]: {"operation": r["semantic"]["operation"],
                 "status": self.receipt(r["requestId"])["status"]} for r in self.requests()}
        atomic(self.root / "index.json", canonical(index))
        return index
