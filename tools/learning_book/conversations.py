"""I5-C：有限选择的公开教学会话；拒绝私有 replay 字节落盘。"""
from copy import deepcopy
from pathlib import Path
import re

from .contracts import DeliveryError, canonical, contained, digest, sha256
from .evidence_store import atomic
from .read_limits import MeteredDeepTutor, ReadLimits
from .deeptutor import DeepTutor

PRIVATE_KEYS = frozenset(("provider_response_state", "model_turn", "provider_replay", "provider_replay_state",
                          "responses_output_items", "thinking_blocks", "reasoning_content"))


def public_value(response):
    """调用方先执行本门禁，再保存 body；拒绝响应仅保留安全错误和 wire hash。"""
    if response.redacted:
        raise DeliveryError("public_credential_echo", "凭据回显响应未捕获", "partial")
    value = response.json()
    try:
        canonical(value)
        pending, visited = [(value, 0)], 0
        while pending:
            node, depth = pending.pop()
            visited += 1
            if depth > 64 or visited > 1000000:
                raise DeliveryError("public_structure_limit", "公共响应结构超限，未捕获", "partial")
            if isinstance(node, dict):
                if PRIVATE_KEYS.intersection(node):
                    raise DeliveryError("public_private_data", "响应包含私有模型状态，未捕获", "partial")
                pending.extend((item, depth + 1) for item in node.values() if isinstance(item, (dict, list)))
            elif isinstance(node, list):
                pending.extend((item, depth + 1) for item in node if isinstance(item, (dict, list)))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DeliveryError("public_json_invalid", "公共响应不是有限完整 JSON，未捕获", "partial") from exc
    return value


def _id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,180}", value) is not None


def select_sessions(mapping, explicit, book_id, page_ids):
    errors, selections = [], {}
    def add(session, page, source):
        if not _id(session) or not _id(page) or (page_ids is not None and page not in page_ids):
            errors.append({"code": "invalid_session_selection", "source": source})
            return
        row = selections.setdefault(session, {"sessionId": session, "bookId": book_id, "pageIds": [], "selectionSources": []})
        if page not in row["pageIds"]:
            row["pageIds"].append(page)
        if source not in row["selectionSources"]:
            row["selectionSources"].append(source)
    if mapping.get("valueAcquired") and isinstance(mapping.get("value"), dict):
        for page, session in mapping["value"].items():
            add(session, page, "current_mapping")
    if mapping.get("status") != "valid" or mapping.get("coverage") != "complete":
        errors.append({"code": "mapping_not_complete"})
    if explicit is not None:
        if not isinstance(explicit, dict) or set(explicit) != {"schema", "sessions"} or explicit.get("schema") != "learning-session-selection/1" or not isinstance(explicit.get("sessions"), list):
            raise DeliveryError("session_selection", "显式会话选择必须使用 learning-session-selection/1")
        for row in explicit["sessions"]:
            if not isinstance(row, dict) or set(row) != {"sessionId", "bookId", "pageId"} or row.get("bookId") != book_id:
                errors.append({"code": "explicit_session_scope"})
                continue
            add(row.get("sessionId"), row.get("pageId"), "explicit")
    return [selections[key] for key in sorted(selections)], errors


def message_structure(messages, session_id):
    errors, identities, parents = [], {}, {}
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or type(message.get("id")) not in (str, int) or not str(message["id"]):
            errors.append({"code": "message_identity", "index": index})
            continue
        mid = str(message["id"])
        if mid in identities:
            errors.append({"code": "duplicate_message_identity", "index": index})
        identities[mid] = message
        if message.get("session_id") != session_id:
            errors.append({"code": "message_session_identity", "index": index})
        if message.get("role") not in ("user", "assistant"):
            errors.append({"code": "unsupported_public_role", "index": index})
        if type(message.get("created_at")) not in (int, float) or message["created_at"] < 0:
            errors.append({"code": "message_time_missing_or_invalid", "index": index})
        if "parent_message_id" not in message:
            errors.append({"code": "parent_link_missing", "index": index})
        parent = message.get("parent_message_id")
        if parent is not None:
            parents[mid] = str(parent)
    for mid, parent in parents.items():
        if parent not in identities:
            errors.append({"code": "parent_message_missing", "messageId": mid})
    done = set()
    for mid in identities:
        visiting = set()
        current = mid
        while current in identities and current not in done:
            if current in visiting:
                errors.append({"code": "message_parent_cycle", "messageId": mid})
                break
            visiting.add(current)
            current = parents.get(current)
        done.update(visiting)
    return errors


class ConversationReader:
    def __init__(self, store, backend, limits=None, *, writer=None):
        self.store, self.backend = store, backend
        self.limits = limits or getattr(backend, "read_limits", None) or ReadLimits()
        if isinstance(backend, DeepTutor) and not isinstance(backend, MeteredDeepTutor):
            self.backend = MeteredDeepTutor(backend.config, self.limits)
        def save(path, data):
            if not path.exists():
                self.limits.take("packageBytes", len(data))
            atomic(path, data, immutable=True)
        self.writer = writer or save
        self.counter = 0

    def _read(self, directory, path, *, event_page=False, expected_session=None, expected_event=None):
        self.counter += 1
        result = {"requestPath": path, "captured": False}
        response = None
        try:
            if event_page:
                self.limits.take("eventPages")
            response = self.backend.read(path)
            result.update(httpStatus=response.status, wireSha256=response.wire_sha256 or sha256(response.body))
            if response.status != 200:
                raise DeliveryError("public_http_unavailable", "所选公共记录不可用", "partial")
            value = public_value(response)
            if expected_session is not None:
                sid, book, page, workspace = expected_session
                prefs = value.get("preferences")
                if (value.get("id") != sid or value.get("session_id", sid) != sid or not isinstance(prefs, dict)
                        or prefs.get("book_id") != book or prefs.get("book_page_id") != page or prefs.get("workspace_id") != workspace
                        or any(isinstance(m, dict) and m.get("session_id") not in (None, sid)
                               for m in (value["messages"] if isinstance(value.get("messages"), list) else []))):
                    raise DeliveryError("session_reverse_scope", "会话实际作用域不符，原字节未捕获", "partial")
                result["expectedSessionScope"] = list(expected_session)
                if isinstance(value.get("messages"), list):
                    result["messageCountInResponse"] = len(value["messages"])
                    self.limits.take("messages", len(value["messages"]))
            if expected_event is not None:
                sid, mid, turn = expected_event
                if (value.get("session_id") != sid or str(value.get("message_id")) != str(mid) or value.get("turn_id") != turn
                        or any(isinstance(e, dict) and (e.get("session_id") != sid or e.get("turn_id") != turn)
                               for e in (value["events"] if isinstance(value.get("events"), list) else []))):
                    raise DeliveryError("event_page_identity_or_shape", "事件实际作用域不符，原字节未捕获", "partial")
                result["expectedEventScope"] = list(expected_event)
            if event_page and isinstance(value.get("events"), list):
                self.limits.take("events", len(value["events"]))
            raw_path = directory / f"c{self.counter}.bin"
            self.writer(raw_path, response.body)
            result.update(captured=True, rawRef=raw_path.relative_to(self.store.root).as_posix(),
                          sha256=sha256(response.body), valueDigest=digest(value))
            return value, result
        except DeliveryError as exc:
            result.update(getattr(exc, "safe_metadata", {}))
            result["error"] = {"code": exc.code}
            error_path = directory / f"c{self.counter}.error.json"
            self.writer(error_path, canonical(result))
            return None, result

    def collect(self, directory, *, book_id, mapping, explicit=None, page_ids=None):
        directory = Path(directory)
        if directory.resolve() != directory.absolute() or not contained(directory.resolve(), self.store.root):
            raise DeliveryError("conversation_path", "会话证据必须在当前 state 安全目录")
        selected, errors = select_sessions(mapping, explicit, book_id, page_ids)
        result = {"schema": "learning-conversations/1", "bookId": book_id, "selection": selected, "sessions": [],
                  "errors": errors, "unvisitedSessions": [], "allHistoricalSessions": "unknown", "historyCoverage": "partial",
                  "boundaryVerified": False, "assistance": {"status": "unknown"}, "boundaries": []}
        for index, selection in enumerate(selected):
            try:
                self.limits.take("sessions")
            except DeliveryError as exc:
                result["errors"].append({"code": exc.code})
                result["unvisitedSessions"] = selected[index:]
                break
            sid = selection["sessionId"]
            row = {**deepcopy(selection), "status": "partial", "errors": [], "eventTraces": [], "reads": []}
            result["sessions"].append(row)
            if len(selection["pageIds"]) != 1:
                row["errors"].append({"code": "session_page_conflict"})
                continue
            value, read = self._read(directory, "/api/sessions/" + sid,
                                     expected_session=(sid, book_id, selection["pageIds"][0], self.backend.scope["workspaceId"]))
            row["reads"].append(read)
            if value is None:
                row["errors"].append(read["error"])
                continue
            prefs = value.get("preferences")
            if (value.get("id") != sid or value.get("session_id", sid) != sid or not isinstance(prefs, dict)
                    or prefs.get("book_id") != book_id or prefs.get("book_page_id") != selection["pageIds"][0]
                    or prefs.get("workspace_id") != self.backend.scope["workspaceId"]):
                row["errors"].append({"code": "session_reverse_scope"})
                row["quarantinedRawRef"] = read["rawRef"]
                continue
            row.update(detail=value, linkKind="current_mapping" if "current_mapping" in selection["selectionSources"] else "explicit_historical",
                       unfinished=bool(value.get("active_turns")), attachmentCoverage="references_only")
            if not isinstance(value.get("active_turns"), list):
                row["errors"].append({"code": "active_turn_state_missing_or_invalid"})
            result["boundaries"].append(read)
            messages = value.get("messages")
            if not isinstance(messages, list):
                row["errors"].append({"code": "messages_missing"})
                continue
            row["errors"].extend(message_structure(messages, sid))
            row["messageKeys"] = [{"rule": "scoped-message/1", "components": [self.backend.scope[k] for k in
                ("deploymentId", "ownerId", "workspaceId")] + [sid, str(m["id"])],
                "digest": digest({"rule": "scoped-message/1", "components": [self.backend.scope[k] for k in
                    ("deploymentId", "ownerId", "workspaceId")] + [sid, str(m["id"])]}),
                "rawRef": read["rawRef"], "pointer": f"/messages/{i}"}
                for i, m in enumerate(messages) if isinstance(m, dict) and type(m.get("id")) in (str, int) and str(m["id"])]
            if messages:
                result["assistance"] = {"status": "observed", "temporalRelationToAnswers": "unknown"}
            for message in messages:
                if not isinstance(message, dict):
                    continue
                trace = message.get("trace")
                if message.get("role") != "assistant":
                    continue
                entry = {"messageId": message.get("id"), "preview": deepcopy(message.get("events")),
                         "previewTrace": deepcopy(trace), "pages": [], "events": [], "coverage": "partial", "errors": []}
                row["eventTraces"].append(entry)
                if not isinstance(trace, dict) or not _id(trace.get("turn_id")) or not re.fullmatch(r"[1-9][0-9]*", str(message.get("id", ""))):
                    entry["errors"].append({"code": "legacy_or_missing_canonical_turn"})
                    continue
                self._events(directory, sid, message["id"], trace, entry, result)
            row["messageCoverage"] = "complete" if not row["errors"] else "partial"
        return result

    def _events(self, directory, sid, mid, trace, entry, result):
        after, total, last, seen = 0, None, None, set()
        while True:
            path = f"/api/sessions/{sid}/messages/{mid}/events?after_seq={after}&limit=500"
            value, read = self._read(directory, path, event_page=True, expected_event=(sid, mid, trace["turn_id"]))
            entry["pages"].append(read)
            if value is None:
                entry["errors"].append(read["error"])
                return
            events = value.get("events")
            if (value.get("session_id") != sid or str(value.get("message_id")) != str(mid) or value.get("turn_id") != trace["turn_id"]
                    or type(value.get("total")) is not int or value["total"] < 0 or type(value.get("last_seq")) is not int
                    or value["last_seq"] < 0 or type(value.get("complete")) is not bool or not isinstance(events, list)):
                entry["errors"].append({"code": "event_page_identity_or_shape"})
                return
            if total is None:
                total, last = value["total"], value["last_seq"]
                if trace.get("total") != total or trace.get("last_seq") != last:
                    entry["errors"].append({"code": "preview_trace_boundary_changed"})
                    return
                if isinstance(entry.get("preview"), list) and len(entry["preview"]) > total:
                    entry["errors"].append({"code": "preview_exceeds_canonical_total"})
                    return
            if (total, last) != (value["total"], value["last_seq"]):
                entry["errors"].append({"code": "event_statistics_changed"})
                return
            for event in events:
                if (not isinstance(event, dict) or type(event.get("seq")) is not int or event["seq"] <= after
                        or event["seq"] in seen or event.get("session_id") != sid or event.get("turn_id") != trace["turn_id"]):
                    entry["errors"].append({"code": "event_sequence_or_identity"})
                    return
                after = event["seq"]
                seen.add(after)
                entry["events"].append(event)
            result["boundaries"].append(read)
            if value["complete"]:
                if value.get("next_seq") is not None or after != last or len(seen) != total:
                    entry["errors"].append({"code": "event_completion_inconsistent"})
                else:
                    entry["coverage"] = "complete_candidate"
                return
            if not events or value.get("next_seq") != after or after >= last or len(seen) >= total:
                entry["errors"].append({"code": "event_cursor_stalled_or_invalid"})
                return

    def verify_boundaries(self, directory, collection):
        stable, reads = True, []
        for boundary in collection["boundaries"]:
            value, read = self._read(Path(directory), boundary["requestPath"], event_page="/events?" in boundary["requestPath"],
                                     expected_session=boundary.get("expectedSessionScope"), expected_event=boundary.get("expectedEventScope"))
            reads.append(read)
            if value is None or read.get("valueDigest") != boundary["valueDigest"]:
                stable = False
        collection["verificationReads"] = reads
        collection["boundaryVerified"] = stable
        if not stable:
            collection["errors"].append({"code": "conversation_boundary_changed_or_incomplete"})
        for row in collection["sessions"]:
            for trace in row["eventTraces"]:
                if trace["coverage"] == "complete_candidate":
                    trace["coverage"] = "complete" if stable else "partial"
            row["status"] = "succeeded" if stable and not row["errors"] and all(t["coverage"] == "complete" for t in row["eventTraces"]) else "partial"
        collection["selectedCoverage"] = "complete" if stable and not collection["errors"] and not collection["unvisitedSessions"] and all(r["status"] == "succeeded" for r in collection["sessions"]) else "partial"
        return collection
