"""I5-D/E：有界只读采集、可搬运不可变交接包、离线完整性验证。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import os
import uuid

from .baseline import Baseline, now
from .content import RULE
from .contracts import DeliveryError, canonical, contained, decode_json, digest, identifier, read_json, sha256, text
from .conversations import ConversationReader, public_value
from .evidence_store import atomic
from .learning_state import validate_learning_state
from .read_limits import MeteredDeepTutor, ReadLimits
from .records import _instant, project_records, submission_key, validate_clock_assumption

SCHEMA = "learning-handoff/1"
EXPORTER = "learning-handoff-exporter/1"


def _safe_file(root, name):
    if (not isinstance(name, str) or not name or name.startswith("/") or "\\" in name or ":" in name
            or any(ord(c) < 32 for c in name) or any(p in ("", ".", "..") for p in name.split("/"))):
        raise DeliveryError("handoff_path", "交接引用包含无效相对路径", "conflict")
    path = root / name
    if path.resolve() != path.absolute() or not contained(path.resolve(), root):
        raise DeliveryError("handoff_path", "交接文件或符号链接越界／重定向", "conflict")
    return path


def _selection(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"schema", "sessions"} or value["schema"] != "learning-session-selection/1"
            or not isinstance(value["sessions"], list)):
        raise DeliveryError("session_selection", "显式会话文件形状无效")
    rows = {}
    for row in value["sessions"]:
        if not isinstance(row, dict) or set(row) != {"sessionId", "bookId", "pageId"}:
            raise DeliveryError("session_selection", "显式会话必须包含 sessionId/bookId/pageId")
        for name in row:
            identifier(row[name], name)
        rows[digest(row)] = row
    return {"schema": value["schema"], "sessions": [rows[k] for k in sorted(rows)]}


def _declaration(value, kind, scope, activity, book):
    if value is None:
        return None
    required = {"schema", "attributedAuthor", "submittedBy", "scope", "declaredAt", "statement", "provenance"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != f"learning-{kind}-declaration/1":
        raise DeliveryError("declaration_shape", "声明须含实际归属、转交者、scope、时间、原文和来源")
    expected = {k: scope[k] for k in ("deploymentId", "ownerId", "workspaceId")}
    expected.update(activityId=activity, bookId=book)
    if value["scope"] != expected:
        raise DeliveryError("declaration_scope", "声明不属于当前学习活动", "conflict")
    for key in ("attributedAuthor", "submittedBy"):
        actor = value[key]
        if not isinstance(actor, dict) or set(actor) != {"actorId", "role"} or actor["role"] not in ("user", "external_agent"):
            raise DeliveryError("declaration_actor", "声明必须区分实际归属人与转交者")
        identifier(actor["actorId"], "actorId")
    when = _instant(value["declaredAt"])
    if when is None or when[0] > datetime.now(timezone.utc).timestamp() + 1:
        raise DeliveryError("declaration_time", "声明时间无效或尚未发生")
    text(value["statement"], "statement")
    if not isinstance(value["provenance"], dict) or set(value["provenance"]) != {"kind", "reference"}:
        raise DeliveryError("declaration_provenance", "声明需保留实际输入来源")
    if value["provenance"]["kind"] not in ("operator_file", "agent_forwarded"):
        raise DeliveryError("declaration_provenance", "声明来源须明确为操作者输入或 Agent 转交")
    text(value["provenance"]["reference"], "reference")
    return deepcopy(value)


def _completion(declaration, records, conversations):
    result = {"status": "unknown", "currentCompletion": "unknown", "attributionAssurance": "operator_supplied",
              "laterActivityObserved": "unknown", "declaration": declaration}
    if declaration is None:
        return result
    when = _instant(declaration["declaredAt"])[0]
    times = [r["raw"].get("timestamp") for r in records["records"] if isinstance(r["raw"], dict)]
    times.extend(m.get("created_at") for s in conversations["sessions"] for m in s.get("detail", {}).get("messages", []) if isinstance(m, dict))
    latest = datetime.now(timezone.utc).timestamp() + 1
    later = any(type(t) in (int, float) and 946684800 <= t <= latest and t > when for t in times)
    result.update(status="declared_complete" if declaration["attributedAuthor"]["role"] == "user" else "agent_statement_only",
                  laterActivityObserved=later, timeAssurance="reported_times_only")
    # 即使没有看到后续记录，也不是已结束的独立证明。
    return result


def _relative_tree(value, store_root, package_root):
    """在新交接层改写本次 state 引用；旧 I4 JSON 另以原字节和 refMap 搬运。"""
    if isinstance(value, list):
        return [_relative_tree(v, store_root, package_root) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"raw", "detail", "events", "preview", "previewTrace", "fields"}:
                result[key] = deepcopy(item)
            elif key in {"rawRef", "firstContentReadRef", "lastContentReadRef"} and isinstance(item, str):
                target = (store_root / item).absolute()
                if not contained(target, package_root):
                    raise DeliveryError("handoff_reference", "本次读取引用不在采集尝试目录", "conflict")
                result[key] = target.relative_to(package_root).as_posix()
            else:
                result[key] = _relative_tree(item, store_root, package_root)
        return result
    return value


def verify_handoff(package):
    """仅本地字节／引用验证，不访问原 state、来源 locator、网络或模型。"""
    try:
        root = Path(package).absolute()
        if root.resolve() != root:
            raise DeliveryError("handoff_path", "交接根目录不能重定向", "conflict")
        marker = read_json(_safe_file(root, "complete.json"))
        manifest_bytes = _safe_file(root, "manifest.json").read_bytes()
        manifest = decode_json(manifest_bytes)
        if manifest.get("schema") not in (SCHEMA, 'learning-handoff/2', 'learning-handoff/3') or marker.get("manifestSha256") != sha256(manifest_bytes):
            raise DeliveryError("handoff_manifest", "交接完成标记或契约不符", "conflict")
        files = manifest.get("files")
        if not isinstance(files, dict) or not {"handoff.json", "records.json", "conversations.json", "request.json"} <= set(files):
            raise DeliveryError("handoff_files", "交接清单不完整", "conflict")
        actual = set()
        for path in root.rglob("*"):
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise DeliveryError("handoff_path", "交接目录含重定向", "conflict")
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
        if actual != set(files) | {"manifest.json", "complete.json"}:
            raise DeliveryError("handoff_inventory", "交接文件增减与清单不符", "conflict")
        for name, expected in files.items():
            if sha256(_safe_file(root, name).read_bytes()) != expected:
                raise DeliveryError("handoff_hash", "交接文件 hash 不符", "conflict")
        handoff, records, conversations, request = (read_json(root / name) for name in ("handoff.json", "records.json", "conversations.json", "request.json"))
        from .preparation_handoff import verify_preparation
        verify_preparation(handoff, lambda name:_safe_file(root, name).read_bytes())
        if records.get("schema") != "learning-records/1" or conversations.get("schema") != "learning-conversations/1":
            raise DeliveryError("handoff_schema", "交接内部记录／会话版本不受支持", "conflict")
        if (handoff.get("schema") != manifest['schema'] or handoff.get("exportId") != manifest.get("exportId")
                or handoff.get("activityId") != manifest.get("activityId") or handoff.get("backendScope") != manifest.get("backendScope")
                or request.get("digest") != digest(request.get("semantic")) or request["digest"] != manifest.get("requestDigest")
                or request.get("exportId") != manifest["exportId"] or request["semantic"].get("scope") != manifest["backendScope"]):
            raise DeliveryError("handoff_identity", "交接活动／作用域／请求身份不符", "conflict")
        if (records.get("scope") != handoff["backendScope"] or records.get("recordScopeId") != handoff["exportId"]
                or records.get("bookId") != handoff["bookId"] or conversations.get("bookId") != handoff["bookId"]):
            raise DeliveryError("handoff_scope", "学习记录作用域不符", "conflict")
        def wrapper_refs(value):
            if isinstance(value, list):
                for item in value:
                    wrapper_refs(item)
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key in {"raw", "detail", "events", "preview", "previewTrace", "fields"}:
                        continue
                    if key in {"rawRef", "currentCheckRef", "priorRoundObservationsRef", "firstContentReadRef", "lastContentReadRef"} and item is not None:
                        if item not in files or not _safe_file(root, item).is_file():
                            raise DeliveryError("handoff_reference", "交接包装引用缺失／越界", "conflict")
                    else:
                        wrapper_refs(item)
        wrapper_refs(records)
        wrapper_refs(conversations)
        wrapper_refs(handoff)
        if handoff.get("priorRoundObservationsRef"):
            wrapper_refs(read_json(root / handoff["priorRoundObservationsRef"]))
        for record in records["records"]:
            assessment = record["assessments"]
            if (assessment["raw"].get("method") not in ("unknown", "ungraded", "client_reported", "user_self_report")
                    or assessment.get("assessmentSync") != "unknown" or assessment["comparisonToBaseline"].get("historicalBinding") != "unknown"
                    or record.get("assistance", {}).get("status") not in ("unknown", "observed")
                    or (record["binding"].get("status") == "unknown" and assessment.get("typeBasis", {}).get("historicalBinding", "unknown") != "unknown")):
                raise DeliveryError("handoff_assessment_claim", "交接包含超出证据的评分／独立作答声明", "conflict")
            if record.get("identityQuality") == "stable" and record.get("identity") != submission_key(handoff["backendScope"], handoff["bookId"], record["raw"].get("submission_id")):
                raise DeliveryError("handoff_submission_key", "提交作用域 key 与原值不符", "conflict")
            if record["binding"].get("status") not in ("unknown", "baseline_consistent", "extension_consistent"):
                raise DeliveryError("handoff_assurance", "历史关联状态超出契约", "conflict")
            if record["binding"].get("status") == "extension_consistent" and record["binding"].get("qualityReview") != "unreviewed":
                raise DeliveryError("handoff_assurance", "扩展关联缺少明确的未审状态", "conflict")
            for occurrence in record["occurrences"]:
                if type(occurrence.get("arrayIndex")) is not int or occurrence["arrayIndex"] < 0 or occurrence.get("pointer") != f"/progress/value/quiz_attempts/{occurrence['arrayIndex']}":
                    raise DeliveryError("handoff_raw_pointer", "作答指针不是实际数组位置", "conflict")
                raw = _safe_file(root, occurrence["rawRef"]).read_bytes()
                if sha256(raw) != occurrence["responseSha256"]:
                    raise DeliveryError("handoff_raw_hash", "作答原响应摘要不符", "conflict")
                response = decode_json(raw)
                validate_learning_state(response, handoff["bookId"], handoff["backendScope"])
                value = response
                for part in occurrence["pointer"].lstrip("/").split("/"):
                    part = part.replace("~1", "/").replace("~0", "~")
                    value = value[int(part)] if isinstance(value, list) else value[part]
                if canonical(value) != canonical(record["raw"]):
                    raise DeliveryError("handoff_raw_pointer", "作答指针未指向实际原值", "conflict")
                if record["binding"].get("assurance") != "cooperative" or record["binding"].get("submissionContent") != "unknown":
                    raise DeliveryError("handoff_assurance", "记录包含超出范围的历史保证", "conflict")
        for boundary in conversations.get("boundaries", []) + conversations.get("verificationReads", []):
            if boundary.get("captured"):
                raw = _safe_file(root, boundary["rawRef"]).read_bytes()
                if sha256(raw) != boundary["sha256"] or digest(decode_json(raw)) != boundary["valueDigest"]:
                    raise DeliveryError("handoff_conversation_raw", "会话原响应身份不符", "conflict")
        baseline = handoff["baselineEvidence"]
        for entry in baseline.get("refMap", []):
            if sha256(_safe_file(root, entry["artifact"]).read_bytes()) != entry["sha256"]:
                raise DeliveryError("handoff_baseline_hash", "搬运基线字节不符", "conflict")
        ref_map = {r["oldRef"]: r for r in baseline["refMap"]}
        question_evidence = None
        extension_evidence = None
        if manifest['schema'] in ('learning-handoff/2', 'learning-handoff/3'):
            from .question_preparation import fields, need
            from .question_evidence import verify as verify_questions
            from .content import project
            ref = handoff.get('questionEvidence')
            fields(ref, ('path', 'sha256', 'contentReadRef'))
            raw = _safe_file(root, ref['path']).read_bytes()
            need(sha256(raw) == ref['sha256'], 'question_handoff_hash')
            question_evidence = decode_json(raw)
            observed = decode_json(_safe_file(root, ref['contentReadRef']).read_bytes())
            projection, _, _ = project(observed, handoff['bookId'])
            verify_questions(question_evidence, projection, activity_id=handoff['activityId'])
        elif 'questionEvidence' in handoff:
            raise DeliveryError('question_version_downgrade', '旧包不能携带可忽略的必需题目附件', 'conflict')
        if manifest['schema'] == 'learning-handoff/3':
            from .question_preparation import fields, need
            ref = handoff.get('extensionEvidence')
            fields(ref, ('path', 'sha256', 'contentReadRef'))
            raw = _safe_file(root, ref['path']).read_bytes()
            need(sha256(raw) == ref['sha256'], 'extension_handoff_hash')
            extension_evidence = decode_json(raw)
        elif 'extensionEvidence' in handoff:
            raise DeliveryError('question_version_downgrade', '旧包不能携带可忽略的扩展证据', 'conflict')
        if manifest['schema'] == SCHEMA:
            from .question_evidence import blocks
            from .content import project
            for name in files:
                if name.startswith('w') and name.endswith(('/r1/response.bin', '/r2/response.bin')):
                    observed = decode_json(_safe_file(root, name).read_bytes())
                    projection, _, _ = project(observed, handoff['bookId'])
                    if any(v[0] is not None for v in blocks(projection).values()) or projection['book'].get('metadata', {}).get('learning_question_controlled'):
                        raise DeliveryError('question_version_downgrade', '受控题目不能降级旧交接包', 'conflict')
        if len(ref_map) != len(baseline["refMap"]):
            raise DeliveryError("handoff_baseline_refs", "基线映射包含重复旧引用", "conflict")
        snapshot_manifest = [old for old in ref_map if old.startswith("snapshots/") and old.endswith("/manifest.json")]
        if snapshot_manifest:
            if len(snapshot_manifest) != 1:
                raise DeliveryError("handoff_baseline_refs", "基线快照不唯一", "conflict")
            old_manifest = snapshot_manifest[0]
            prefix = old_manifest.rsplit("/", 1)[0]
            def old_value(old):
                return read_json(root / ref_map[old]["artifact"])
            sm = old_value(old_manifest)
            complete = old_value(prefix + "/complete.json")
            if (complete.get("manifestDigest") != ref_map[old_manifest]["sha256"] or sm.get("scope") != handoff["backendScope"]
                    or sm.get("activityId") != handoff["activityId"] or sm.get("bookId") != handoff["bookId"]):
                raise DeliveryError("handoff_snapshot_identity", "搬运快照的标记／作用域不符", "conflict")
            for name, expected in sm["files"].items():
                if ref_map[prefix + "/" + name]["sha256"] != expected:
                    raise DeliveryError("handoff_snapshot_file", "搬运快照文件目录不完整", "conflict")
            content, resources, sources, capture = (old_value(prefix + "/" + name) for name in ("content.json", "resources.json", "sources.json", "capture.json"))
            snapshot_questions = Baseline._verify_questions(sm, content, lambda name:old_value(prefix + '/' + name))
            if snapshot_questions is not None and question_evidence is None:
                raise DeliveryError('question_evidence_required', '新版快照要求新版交接能力', 'conflict')
            identity = {"rule": RULE, "contentDigest": digest(content), "resourceManifestDigest": digest(resources),
                        "sourceMappingDigest": digest(sources["mapping"])}
            if identity != sm["identity"] or identity != baseline["identity"] or sources["sourceMappingDigest"] != identity["sourceMappingDigest"]:
                raise DeliveryError("handoff_snapshot_digests", "搬运内容／资源／来源身份不符", "conflict")
            capture_request = old_value("captures/" + digest(sm["captureId"]) + "/request.json")
            if capture_request["digest"] != digest(capture_request["semantic"]) or capture_request["digest"] != sm["captureDigest"]:
                raise DeliveryError("handoff_capture_request", "搬运捕获请求不符", "conflict")
        if extension_evidence is not None:
            from .extensions import verify_chain
            from .content import project
            from .question_preparation import need
            ref = handoff['extensionEvidence']
            observed = decode_json(_safe_file(root, ref['contentReadRef']).read_bytes())
            current_projection, _, _ = project(observed, handoff['bookId'])
            need(extension_evidence.get('schema') == 'learning-extension-evidence/1'
                 and extension_evidence.get('bookId') == handoff['bookId']
                 and extension_evidence.get('head') == observed['book'].get('metadata', {}).get('learning_extension_head'),
                 'extension_handoff_identity')
            chain = verify_chain(content, current_projection, extension_evidence['commits'], book_id=handoff['bookId'])
            current_check = read_json(_safe_file(root, handoff['currentCheckRef']))
            need(chain['status'] == current_check.get('extension', {}).get('status') == 'extension_consistent',
                 'extension_handoff_chain')
            extension_questions = {(row['pageId'], row['blockId'], row['questionId']): row
                                   for row in current_check.get('extension', {}).get('questions', [])}
            for record in records['records']:
                if record['binding']['status'] != 'extension_consistent':
                    continue
                key = (record['raw'].get('page_id'), record['raw'].get('block_id'), record['raw'].get('question_id'))
                question = extension_questions.get(key)
                need(question is not None and record['binding'].get('commitDigest') == question['commitDigest']
                     and question['qualityReview'] == 'unreviewed', 'extension_handoff_question_binding')
        elif any(r['binding']['status'] == 'extension_consistent' for r in records['records']):
            raise DeliveryError('extension_evidence_required', '扩展作答缺少可离线核验的提交证据', 'conflict')
        if baseline.get("bindingStatus") == "accepted":
            binding_entry = ref_map[baseline["bindingRef"]]
            binding = read_json(root / binding_entry["artifact"])
            review_request = read_json(root / ref_map[baseline["reviewRequestRef"]]["artifact"])
            if (binding.get("reviewDigest") != digest(review_request["semantic"]["review"])
                    or review_request.get("digest") != digest(review_request.get("semantic"))
                    or binding.get("scope") != handoff["backendScope"] or binding.get("bookId") != handoff["bookId"]
                    or binding.get("identity") != baseline.get("identity") or not snapshot_manifest
                    or Baseline.quality_review_reasons(review_request["semantic"]["review"], sm, capture, sources, snapshot_questions)
                    or binding.get("capturedAt") != capture["capturedAt"] or binding.get("purpose") != capture["purpose"]):
                raise DeliveryError("handoff_baseline_binding", "搬运的绑定与审查来源不符", "conflict")
        if any(r["binding"]["status"] in ("baseline_consistent", "extension_consistent") for r in records["records"]):
            current = read_json(_safe_file(root, handoff["currentCheckRef"]))
            expected = 'extension_consistent' if any(r['binding']['status'] == 'extension_consistent' for r in records['records']) else 'baseline_consistent'
            if (baseline.get("bindingStatus") != "accepted" or binding.get("purpose") != "pre_learning"
                    or current.get("binding") not in (('extension_consistent',) if expected == 'extension_consistent' else ('baseline_consistent', 'extension_consistent'))
                    or current.get("recordWindowStable") is not True
                    or current.get("sourceAvailability") != "complete" or records.get("clockAssumption") is None):
                raise DeliveryError("handoff_historical_binding", "历史关联缺少实际审查／本次窗口／时钟依据", "conflict")
        byte_count = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
        verified_limits = ReadLimits(handoff["limits"]["limits"], saved=handoff["limits"])
        if byte_count > verified_limits.used["packageBytes"]:
            raise DeliveryError("handoff_byte_accounting", "包实际字节超出已固定的计量", "conflict")
        if (handoff.get("exporter") != EXPORTER or handoff.get("assurance") != "cooperative" or handoff.get("atomicSnapshot") is not False
                or handoff.get("submissionContent") != "unknown" or handoff.get("sources", {}).get("retention") != "external"
                or handoff.get("completion", {}).get("currentCompletion") != "unknown"
                or handoff.get("completion", {}).get("attributionAssurance") != "operator_supplied"
                or handoff.get("resultStatus") not in ("succeeded", "partial") or handoff.get("collectionStatus") not in ("stable", "inconsistent")
                or type(handoff.get("roundsAttempted")) is not int or not 1 <= handoff["roundsAttempted"] <= 3):
            raise DeliveryError("handoff_guarantees", "交接包含超出本版本的保证", "conflict")
        return {"status": "succeeded", "verification": "valid", "exportId": manifest["exportId"],
                "activityId": manifest["activityId"], "manifestSha256": sha256(manifest_bytes), "filesVerified": len(files),
                "bytesVerified": byte_count,
                "collectionStatus": handoff["collectionStatus"], "sourceRetention": "external",
                "sourceOriginalsVerified": False, "resultStatus": handoff["resultStatus"]}
    except DeliveryError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, UnicodeError) as exc:
        raise DeliveryError("handoff_integrity", "交接文件缺失或结构损坏", "conflict") from exc


class Handoff:
    def __init__(self, store, backend, *, fault=None):
        self.store, self.backend, self.scope = store, backend, backend.scope
        self.fault = fault or (lambda _: None)

    def export_learning_results(self, activity_id, export_id, *, snapshot_id=None, sessions=None, collection_declaration=None,
                                completion_declaration=None, clock_assumption=None, limits=None):
        identifier(activity_id, "activityId")
        identifier(export_id, "exportId")
        if snapshot_id is not None:
            identifier(snapshot_id, "snapshotId")
        semantic = {"exporter": EXPORTER, "activityId": activity_id, "scope": self.scope, "snapshotId": snapshot_id,
                    "sessions": _selection(sessions), "collectionDeclaration": collection_declaration, "completionDeclaration": completion_declaration,
                    "clockAssumption": validate_clock_assumption(clock_assumption), "limits": ReadLimits(limits).limits,
                    "build": {k: deepcopy(self.backend.config.get(k)) for k in ("contentReadBuild", "learningStateReadBuild")}, "contentRule": RULE}
        request = {"exportId": export_id, "semantic": semantic, "digest": digest(semantic)}
        op = self.store.root / "exports" / digest(export_id)
        final = self.store.root / "handoffs" / digest(export_id)[:24]
        with self.store.lock(self.scope):
            for target in (op, final):
                if target.resolve() != target.absolute():
                    raise DeliveryError("handoff_path", "交接操作目录不能重定向", "conflict")
            atomic(op / "request.json", canonical(request), immutable=True)
            if final.exists():
                verified = verify_handoff(final)
                manifest = read_json(final / "manifest.json")
                if manifest["exportId"] != export_id or manifest["requestDigest"] != request["digest"]:
                    raise DeliveryError("export_conflict", "exportId 或目录已对应其他输入", "conflict")
                return self._receipt(op, final, request, verified["resultStatus"], recovered=not (op / "result.json").exists())
            if (op / "result.json").exists():
                value = read_json(op / "result.json")
                if value.get("requestDigest") != request["digest"]:
                    raise DeliveryError("export_receipt_integrity", "导出回执与请求不符", "conflict")
                if value.get("artifactRef") is not None:
                    raise DeliveryError("export_artifact_missing", "历史交接包丢失，不能将回执当完整交付", "conflict")
                return value
            saved = read_json(op / "limits.json") if (op / "limits.json").exists() else None
            quota = ReadLimits(limits, saved=saved, persist=lambda v: atomic(op / "limits.json", canonical(v)))
            backend = MeteredDeepTutor(self.backend.config, quota)
            baseline = Baseline(self.store, backend, fault=self.fault)
            context = baseline.learning_context(activity_id)
            book = context[0]["bookId"]
            collection_decl = _declaration(collection_declaration, "collection", self.scope, activity_id, book)
            completion_decl = _declaration(completion_declaration, "completion", self.scope, activity_id, book)
            attempt = self.store.root / "export-attempts" / uuid.uuid4().hex[:16]
            attempt.mkdir(parents=True)
            atomic(attempt / "request.json", canonical(request), immutable=True)
            try:
                outcome, previous = None, []
                for number in range(1, 4):
                    outcome = self._round(attempt, number, activity_id, snapshot_id, semantic["sessions"], quota, backend, baseline, context)
                    previous.append(outcome)
                    if outcome["stable"] or quota.hits or quota.pending_request:
                        break
                if outcome is None:
                    raise DeliveryError("export_no_observation", "没有取得采集观察", "partial")
                evidence = outcome["baseline"]
                projection_basis = evidence if evidence["bindingStatus"] != "invalid" else {}
                observations = outcome["observations"]
                records = project_records(observations, scope=self.scope, book_id=book, record_scope_id=export_id, evidence=projection_basis,
                                          current_check=outcome["check"], clock_assumption=semantic["clockAssumption"])
                prior_records = [project_records(r["observations"], scope=self.scope, book_id=book, record_scope_id=export_id,
                    evidence=projection_basis, current_check={}, clock_assumption=semantic["clockAssumption"]) for r in previous[:-1]]
                variants = {}
                for observed in [*prior_records, records]:
                    for row in observed["records"]:
                        if row["identityQuality"] == "stable":
                            variants.setdefault(row["identity"]["digest"], set()).add(digest(row["raw"]))
                for row in records["records"]:
                    if row["identityQuality"] == "stable" and len(variants[row["identity"]["digest"]]) > 1:
                        row["identityConflict"] = True
                        row["binding"]["status"] = "unknown"
                        row["binding"]["reasons"].append("prior_round_identity_conflict")
                        row["assessments"]["raw"]["method"] = "ungraded" if row["assessments"]["raw"]["isCorrect"] == {"present": True, "value": None} else "unknown"
                        if "typeBasis" in row["assessments"]:
                            row["assessments"]["typeBasis"]["historicalBinding"] = "unknown"
                if prior_records:
                    self._save(attempt / "prior-rounds.json", _relative_tree({"meaning": "failed_round_observations_not_merged_into_final_snapshot", "rounds": prior_records}, self.store.root, attempt), "records")
                if records["rejectedObservations"] or any(r["rejectedObservations"] for r in prior_records):
                    raise DeliveryError("export_record_scope", "进度包含其他书的记录；仅保留独立诊断", "partial")
                conversations = outcome["conversations"]
                for row in records["records"]:
                    if isinstance(row["raw"], dict):
                        page = row["raw"].get("page_id")
                        links = [s for s in conversations["sessions"] if page in s["pageIds"] and s.get("detail", {}).get("messages")]
                        if links:
                            row["assistance"] = {"status": "observed", "sessionIds": [s["sessionId"] for s in links], "temporalRelationToAnswer": "unknown"}
                records = _relative_tree(records, self.store.root, attempt)
                conversations = _relative_tree(conversations, self.store.root, attempt)
                self._save(attempt / "records.json", records, "records")
                self._save(attempt / "conversations.json", conversations, "records")
                baseline_evidence = self._copy_baseline(attempt, baseline, evidence)
                source_status = outcome["lastContent"]["record"]["sources"]["status"] if outcome["lastContent"] else "unknown"
                content_complete = bool(outcome["lastContent"] and outcome["lastContent"]["record"]["resources"]["status"] == "complete"
                    and not outcome["lastContent"]["record"]["structure"]["blocking"]
                    and outcome["lastContent"]["record"]["structure"]["contentCoverage"] == "complete")
                result_status = "succeeded" if (outcome["stable"] and records["recordCoverage"] == "complete" and conversations["selectedCoverage"] == "complete"
                    and content_complete and source_status == "complete" and not outcome["errors"] and evidence["bindingStatus"] != "invalid"
                    and not any(r["identityConflict"] for r in records["records"])) else "partial"
                handoff = {"schema": SCHEMA, "exporter": EXPORTER, "exportId": export_id, "activityId": activity_id,
                    "bookId": book, "backendScope": self.scope, "build": semantic["build"], "recordedAt": now(),
                    "collectionStatus": "stable" if outcome["stable"] else "inconsistent", "resultStatus": result_status,
                    "roundsAttempted": outcome["number"], "atomicSnapshot": False, "assurance": "cooperative", "submissionContent": "unknown",
                    "baselineEvidence": baseline_evidence, "sources": {"retention": "external", "statusAtCollection": source_status,
                        "mapping": outcome["lastContent"]["record"]["sources"].get("mapping") if outcome["lastContent"] else None},
                    "collectionDeclaration": collection_decl, "completion": _completion(completion_decl, records, conversations),
                    "currentCheckRef": f"w{outcome['number']}/check.json", "priorRoundObservationsRef": "prior-rounds.json" if prior_records else None,
                    "coverage": {"records": records["recordCoverage"], "content": "complete" if content_complete else "partial", "selectedConversations": conversations["selectedCoverage"],
                                 "allHistoricalSessions": "unknown", "history": "partial", "attachments": "references_only"},
                    "limits": quota.summary(), "errors": outcome["errors"],
                    "limitations": ["source_originals_external", "cooperative_window_not_transaction", "aba_not_excluded", "not_mastery_proof"]}
                from .preparation_handoff import copy_preparation
                preparation = copy_preparation(self.store, handoff['sources']['mapping'], attempt)
                if preparation is not None:
                    handoff['preparationEvidence'] = preparation
                questions = outcome['lastContent'].get('questions') if outcome['lastContent'] else None
                question_controlled = any(r['semantic'].get('activityId') == activity_id and
                    r['semantic'].get('questionPreparation') for r in self.store.requests())
                if question_controlled and questions is None:
                    raise DeliveryError('question_evidence_required', '题目绑定缺失或当前内容不可核对；未发布交接包', 'partial')
                if questions is not None:
                    from .question_preparation import ordered_bytes
                    data = ordered_bytes(questions)
                    atomic(attempt / 'questions.json', data, immutable=True)
                    handoff.update(schema='learning-handoff/2', questionEvidence={'path': 'questions.json',
                        'sha256': sha256(data), 'contentReadRef': f"w{outcome['number']}/r2/response.bin"})
                extension = outcome['lastContent'].get('extension') if outcome['lastContent'] else None
                if extension is not None:
                    extension_path = attempt / f"w{outcome['number']}/r2/extension.bin"
                    if not extension_path.is_file():
                        raise DeliveryError('extension_evidence_required', '本次扩展原始证据缺失；未发布交接包', 'partial')
                    handoff.update(schema='learning-handoff/3', extensionEvidence={
                        'path': extension_path.relative_to(attempt).as_posix(), 'sha256': sha256(extension_path.read_bytes()),
                        'contentReadRef': f"w{outcome['number']}/r2/response.bin"})
                files = {p.relative_to(attempt).as_posix(): sha256(p.read_bytes()) for p in sorted(attempt.rglob("*")) if p.is_file()}
                files["handoff.json"] = "0" * 64
                manifest = {"schema": handoff['schema'], "exportId": export_id, "activityId": activity_id, "backendScope": self.scope,
                            "requestDigest": request["digest"], "files": files}
                base_size = sum(p.stat().st_size for p in attempt.rglob("*") if p.is_file())
                package_size = 0
                for _ in range(20):
                    handoff["limits"] = quota.summary()
                    handoff["limits"]["used"]["packageBytes"] += package_size
                    files["handoff.json"] = digest(handoff)
                    size = base_size + len(canonical(handoff)) + len(canonical(manifest)) + len(canonical({"manifestSha256": "0" * 64}))
                    if size == package_size:
                        break
                    package_size = size
                else:
                    raise DeliveryError("export_size_accounting", "交接字节计量没有收敛", "partial")
                quota.take("packageBytes", package_size)
                self._save(attempt / "handoff.json", handoff, "records")
                self._save(attempt / "manifest.json", manifest, "manifest")
                self._save(attempt / "complete.json", {"manifestSha256": digest(manifest)}, "complete")
                verify_handoff(attempt)
                final.parent.mkdir(parents=True, exist_ok=True)
                os.rename(attempt, final)
                self.fault("published")
                return self._receipt(op, final, request, result_status)
            except DeliveryError as exc:
                diagnostic = {"schema": "learning-handoff-diagnostic/1", "exportId": export_id, "activityId": activity_id,
                              "status": "partial", "code": exc.code, "limits": quota.summary(), "validHandoffPublished": False,
                              "attemptRef": attempt.relative_to(self.store.root).as_posix(), **getattr(exc, "safe_metadata", {})}
                atomic(op / "diagnostic.json", canonical(diagnostic), immutable=True)
                return self._receipt(op, None, request, "partial", diagnosticRef=(op / "diagnostic.json").relative_to(self.store.root).as_posix())

    def _save(self, path, value, boundary):
        atomic(path, canonical(value), immutable=True)
        self.fault(boundary)

    def _receipt(self, op, final, request, status, **extra):
        path = op / "result.json"
        if path.exists():
            result = read_json(path)
            if result.get("requestDigest") != request["digest"]:
                raise DeliveryError("export_receipt_integrity", "导出回执损坏", "conflict")
            return result
        result = {"operation": "export-results", "status": status, "exportId": request["exportId"], "requestDigest": request["digest"],
                  "receiptRef": path.relative_to(self.store.root).as_posix(), "recordedAt": now(),
                  "artifactRef": final.relative_to(self.store.root).as_posix() if final else None, **extra}
        atomic(path, canonical(result), immutable=True)
        return result

    def _copy_baseline(self, directory, baseline, evidence):
        result = {"bindingStatus": evidence["bindingStatus"], "issues": evidence["issues"], "refMap": [],
                  "sourceRetention": "external", "snapshotId": evidence.get("snapshotId")}
        if evidence["bindingStatus"] == "invalid":
            return result
        if "manifest" in evidence:
            result["identity"] = evidence["manifest"]["identity"]
        for entry in evidence["evidenceRefs"]:
            old = entry["ref"]
            if old.startswith("baselines/") and evidence["bindingStatus"] != "accepted":
                continue
            data = _safe_file(self.store.root, old).read_bytes()
            if sha256(data) != entry["sha256"]:
                raise DeliveryError("export_baseline_changed", "搬运时基线证据变化", "partial")
            if old.endswith(".json") or "/raw/" in old:
                from .deeptutor import Response
                public_value(Response(200, data, "application/json"))
            name = f"baseline/f{len(result['refMap'])}.bin"
            atomic(directory / name, data, immutable=True)
            result["refMap"].append({"oldRef": old, "artifact": name, "sha256": entry["sha256"]})
            self.fault("assets" if "/assets/" in old else "baseline")
            if old.startswith("baselines/"):
                result["bindingRef"] = old
            if old.startswith("reviews/") and old.endswith("/request.json"):
                result["reviewRequestRef"] = old
        return result

    def _round(self, attempt, number, activity, snapshot_id, sessions, quota, backend, baseline, context):
        directory = attempt / f"w{number}"
        evidence = baseline.load_learning_evidence(activity, snapshot_id)
        errors = []
        def content(which):
            try:
                value = baseline.read_content_once(directory, which, context)
                if value["assets"]:
                    self.fault("assets")
                return value
            except DeliveryError as exc:
                errors.append({"code": exc.code, "boundary": which, **getattr(exc, "safe_metadata", {})})
                return None
        def progress(which):
            response = backend.read_learning_state(context[0]["bookId"])
            public_value(response)
            path = directory / f"state-{which}.bin"
            atomic(path, response.body, immutable=True)
            self.fault("raw")
            return {"body": response.body, "rawRef": path.relative_to(self.store.root).as_posix(), "observedAt": now()}
        first = content(1)
        start = progress(1)
        start_value = decode_json(start["body"])
        # 包字节由发布前完整清单精确计量；传输／消息／分页仍共用 quota。
        reader = ConversationReader(self.store, backend, quota, writer=lambda p, data: atomic(p, data, immutable=True))
        pages = {p["id"] for p in first["projection"]["pages"]} if first else None
        conversations = reader.collect(directory, book_id=context[0]["bookId"], mapping=start_value["pageChatSessions"], explicit=sessions, page_ids=pages)
        try:
            end = progress(2)
        except DeliveryError as exc:
            errors.append({"code": exc.code, "boundary": "ending_progress", **getattr(exc, "safe_metadata", {})})
            end = None
        reader.verify_boundaries(directory, conversations)
        last = content(2)
        final_evidence = baseline.load_learning_evidence(activity, evidence.get("snapshotId", snapshot_id))
        evidence_stable = canonical({k: evidence[k] for k in ("bindingStatus", "issues", "evidenceRefs")}) == canonical(
            {k: final_evidence[k] for k in ("bindingStatus", "issues", "evidenceRefs")})
        state_stable = end is not None and canonical(start_value) == canonical(decode_json(end["body"]))
        content_stable = first is not None and last is not None and first["record"]["boundaryDigest"] == last["record"]["boundaryDigest"]
        stable = state_stable and content_stable and evidence_stable and conversations["boundaryVerified"]
        check = {"binding": "unknown", "contentConsistent": False, "sourceAvailability": "unknown"}
        if first and last and "manifest" in evidence:
            try:
                check = baseline.evaluate_content_observations(activity, evidence["snapshotId"], first, last)
            except DeliveryError as exc:
                errors.append({"code": exc.code, "boundary": "baseline_comparison"})
        check["recordWindowStable"] = stable and conversations["selectedCoverage"] == "complete"
        if not stable:
            check["binding"] = "unknown"
        self._save(directory / "check.json", check, "round")
        return {"number": number, "stable": stable, "baseline": evidence, "check": check, "observations": [start] + ([end] if end else []),
                "conversations": conversations, "lastContent": last, "errors": errors}
