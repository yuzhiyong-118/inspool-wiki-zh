"""I5-A HTTP 边界验证；不重建 Progress，不改写原始记录。"""
from .contracts import DeliveryError

CAPABILITY = "book-learning-state-read/1"
STATUSES = frozenset(("valid", "missing", "invalid", "unreadable", "changed"))


def _shape(message):
    raise DeliveryError("learning_state_shape", message, "partial")


def _diagnostics(value):
    return (isinstance(value, list) and all(isinstance(d, dict) and
            isinstance(d.get("code"), str) and bool(d["code"]) and
            isinstance(d.get("pointer", ""), str) for d in value))


def validate_learning_state(value: dict, book_id: str, scope: dict) -> None:
    if value.get("schema") != CAPABILITY or value.get("bookId") != book_id:
        _shape("响应缺少严格学习状态能力或对应 bookId")
    reader = value.get("readerScope")
    if (not isinstance(reader, dict) or not isinstance(reader.get("actorId"), str) or
            not reader["actorId"].strip() or reader.get("identityKind") not in
            ("authenticated", "local_single_user")):
        _shape("响应缺少实际读者身份及身份强度")
    if reader.get("workspaceId") != scope["workspaceId"]:
        raise DeliveryError("learning_state_workspace", "实际读者 workspace 与活动配置不符", "conflict")
    if scope["scopeVerification"] == "authenticated" and (reader["identityKind"] != "authenticated" or
                                                        reader["actorId"] != scope["ownerId"]):
        raise DeliveryError("learning_state_actor", "实际认证读者与 owner 不符", "conflict")
    # Anonymous owner is a configured I3 label, not the server's local-admin id.
    access = value.get("contentAccess")
    if (not isinstance(access, dict) or access.get("source") not in ("own", "shared") or
            access.get("permission") not in ("read", "edit")):
        _shape("响应缺少现有内容访问作用域")
    if value.get("consistency") != "per_item_observation" or not _diagnostics(value.get("diagnostics")):
        _shape("响应缺少逐项观测边界或诊断")
    for name in ("progress", "pageChatSessions"):
        item = value.get(name)
        if not isinstance(item, dict):
            _shape("响应缺少存储项")
        status = item.get("status")
        if (not isinstance(status, str) or status not in STATUSES or
                type(item.get("valueAcquired")) is not bool or
                item.get("coverage") not in ("complete", "partial") or
                not _diagnostics(item.get("diagnostics"))):
            _shape("存储项状态或诊断不完整")
        acquired = item["valueAcquired"]
        if (acquired != ("value" in item) or (status == "valid" and not acquired) or
                (status in ("missing", "unreadable", "changed") and acquired) or
                (status != "valid" and item["coverage"] != "partial")):
            _shape("存储状态与原值捕获声明冲突")
        if status == "valid":
            raw = item["value"]
            if not isinstance(raw, dict):
                _shape("有效存储项不是原始 JSON 对象")
            if name == "progress" and raw.get("book_id") != book_id:
                _shape("有效进度未绑定当前书")
            if name == "pageChatSessions" and any(not key.strip() or not isinstance(session, str) or
                                                   not session.strip() for key, session in raw.items()):
                _shape("有效页边映射含非法成员")
