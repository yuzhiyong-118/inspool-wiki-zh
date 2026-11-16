"""I5 全窗口共用的可信操作者读取限额；失败／重试不会清零。"""
from .contracts import DeliveryError, sha256
from .deeptutor import DeepTutor

DEFAULT_LIMITS = {"sessions": 32, "messages": 10000, "events": 50000, "eventPages": 100,
                  "requests": 512, "readBytes": 256 * 1024 * 1024, "packageBytes": 256 * 1024 * 1024}


class ReadLimits:
    def __init__(self, overrides=None, *, saved=None, persist=None):
        overrides = overrides or {}
        if not isinstance(overrides, dict) or set(overrides) - DEFAULT_LIMITS.keys():
            raise DeliveryError("read_limits", "读取限额字段无效")
        self.limits = {**DEFAULT_LIMITS, **overrides}
        if any(type(v) is not int or not 1 <= v <= DEFAULT_LIMITS[k] for k, v in self.limits.items()):
            raise DeliveryError("read_limits", "首期仅允许可信操作者收紧默认限额")
        self.used = {k: 0 for k in DEFAULT_LIMITS}
        self.hits = []
        self.persist = persist or (lambda value: None)
        self.pending_request = False
        if saved is not None:
            if (not isinstance(saved, dict) or saved.get("limits") != self.limits or not isinstance(saved.get("used"), dict)
                    or set(saved["used"]) != set(self.used) or any(type(v) is not int or not 0 <= v <= self.limits[k] for k, v in saved["used"].items())):
                raise DeliveryError("read_limits_integrity", "已有读取限额证据无效", "conflict")
            self.used = dict(saved["used"])
            self.hits = list(saved.get("hits", []))
            self.pending_request = bool(saved.get("pendingRequest"))

    def take(self, kind, amount=1):
        if self.used[kind] + amount > self.limits[kind]:
            if kind not in self.hits:
                self.hits.append(kind)
            self.persist(self.summary())
            raise DeliveryError("read_limit_" + kind, "本次采集达到全局读取限额", "partial")
        self.used[kind] += amount
        self.persist(self.summary())

    def summary(self):
        return {"rule": "learning-read-limits/1", "limits": dict(self.limits), "used": dict(self.used),
                "hits": list(self.hits), "pendingRequest": self.pending_request}


class MeteredDeepTutor(DeepTutor):
    def __init__(self, config, limits):
        super().__init__(config)
        self.read_limits = limits

    def request(self, method, path, body=None, content_type="application/json", *, kb=False):
        if method != "GET":
            raise DeliveryError("read_only_backend", "采集后端只允许 GET")
        if self.read_limits.pending_request:
            raise DeliveryError("read_accounting_incomplete", "上次传输计量未完成，停止本 export 的新读取", "partial")
        self.read_limits.take("requests")
        self.read_limits.pending_request = True
        self.read_limits.persist(self.read_limits.summary())
        response = super().request(method, path, body, content_type, kb=kb)
        self.read_limits.take("readBytes", len(response.body))
        self.read_limits.pending_request = False
        self.read_limits.persist(self.read_limits.summary())
        binary_kb_download = path.startswith("/api/knowledge-bases/") and "/files/" in path
        if path.startswith("/api/") and response.status == 200 and not binary_kb_download:
            from .conversations import public_value
            try:
                public_value(response)
            except DeliveryError as exc:
                exc.safe_metadata = {"wireSha256": response.wire_sha256 or sha256(response.body)}
                raise
        return response
