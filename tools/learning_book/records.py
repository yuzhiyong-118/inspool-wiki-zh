"""I5-B：原始作答观察、条件复核和协作级历史绑定；不拥有可写进度。"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import uuid

from .baseline import Baseline, now
from .content import supports_choice
from .contracts import DeliveryError, canonical, decode_json, digest, identifier, sha256, text
from .evidence_store import atomic
from .learning_state import validate_learning_state

RECORD_RULE = "learning-records/1"
KEY_RULE = "scoped-submission/1"
CHOICE_RULE = "choice-key/1"
NON_CHOICE = frozenset(("short_answer", "fill_blank", "written"))


def _finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _identifier(value):
    try:
        return isinstance(value, str) and value == value.strip() and bool(identifier(value, "recordId"))
    except DeliveryError:
        return False


def _instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|\+00:00)", value):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        fraction = re.search(r"\.(\d+)", value)
        return timestamp, 10 ** -len(fraction[1]) if fraction else 1.0
    except (ValueError, OverflowError, OSError):
        return None


def validate_clock_assumption(value):
    if value is None:
        return None
    fields = {"schema", "kind", "maxSkewSeconds", "timestampResolutionSeconds", "actorId", "statement"}
    if (not isinstance(value, dict) or set(value) != fields or value["schema"] != "learning-clock-assumption/1"
            or value["kind"] != "same_local_clock"):
        raise DeliveryError("clock_assumption", "时钟声明必须明确同机假设、精度、偏差及实际声明人")
    identifier(value["actorId"], "actorId")
    text(value["statement"], "statement")
    for name, minimum in (("maxSkewSeconds", 0), ("timestampResolutionSeconds", 0.000001)):
        number = value[name]
        if not _finite_number(number) or not minimum <= number <= 3600:
            raise DeliveryError("clock_assumption", "时钟偏差或精度超出有限声明范围")
    return deepcopy(value)


def submission_key(scope, book_id, submission_id):
    if not _identifier(submission_id):
        return None
    components = [scope["deploymentId"], scope["ownerId"], scope["workspaceId"], book_id, submission_id]
    return {"rule": KEY_RULE, "components": components,
            "digest": digest({"rule": KEY_RULE, "components": components})}


def _questions(evidence):
    content = evidence.get("content", {}) if evidence else {}
    if not isinstance(content, dict):
        return {}
    pages = content.get("pages", [])
    if not isinstance(pages, list):
        return {}
    page_counts = Counter(p.get("id") for p in pages if isinstance(p, dict) and isinstance(p.get("id"), str))
    index, orders = defaultdict(list), content.get("optionDisplayOrders", [])
    orders = orders if isinstance(orders, list) else []
    capture = evidence.get("capture", {}) if evidence else {}
    structure = capture.get("structure", {}) if isinstance(capture, dict) else {}
    supported_rows = structure.get("questions", []) if isinstance(structure, dict) else []
    supported_rows = supported_rows if isinstance(supported_rows, list) else []
    for page in pages:
        if not isinstance(page, dict) or not _identifier(page.get("id")):
            continue
        blocks = page.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        counts = Counter(b.get("id") for b in blocks if isinstance(b, dict) and isinstance(b.get("id"), str))
        for block in blocks:
            if not isinstance(block, dict) or block.get("type") != "quiz" or not _identifier(block.get("id")):
                continue
            payload = block.get("payload", {})
            questions = payload.get("questions", []) if isinstance(payload, dict) else []
            for qi, question in enumerate(questions if isinstance(questions, list) else []):
                if not isinstance(question, dict) or not _identifier(question.get("question_id")):
                    continue
                key = (page["id"], block["id"], question["question_id"])
                matching_orders = [o.get("optionKeys") for o in orders if isinstance(o, dict) and
                    (o.get("pageId"), o.get("blockId"), o.get("questionId"), o.get("questionIndex")) == (*key, qi)]
                index[key].append({"value": question, "uniqueContainers": page_counts[key[0]] == 1 and counts[key[1]] == 1,
                                   "i4Support": any(isinstance(row, dict) and row.get("assessmentSupport") == "supported" and
                                       (row.get("pageId"), row.get("blockId"), row.get("questionId")) == key for row in supported_rows),
                                   "optionKeys": matching_orders[0] if len(matching_orders) == 1 else None})
    return index


def _question_key(raw):
    if not isinstance(raw, dict):
        return None
    key = tuple(raw.get(name) for name in ("page_id", "block_id", "question_id"))
    return key if all(_identifier(value) for value in key) else None


def _comparison(raw, question, evidence):
    result = {"rule": CHOICE_RULE, "result": "unknown", "historicalBinding": "unknown",
              "snapshotId": evidence.get("snapshotId") if evidence else None}
    if question is None:
        result["reason"] = "question_missing_or_ambiguous"
        return result
    q = question["value"]
    kind = q.get("question_type")
    result["questionType"] = kind
    options = q.get("options")
    supported = question["i4Support"] and supports_choice(q)
    if not supported:
        result["reason"] = "unsupported_question"
        return result
    answer = raw.get("user_answer")
    if not isinstance(answer, str) or answer not in options:
        result["reason"] = "answer_not_exact_option_key"
        return result
    result.update(result="correct" if answer == q["correct_answer"] else "incorrect",
                  optionKeys=question["optionKeys"], correctAnswer=q["correct_answer"])
    if type(raw.get("is_correct")) is bool:
        result["disagreement"] = raw["is_correct"] != (result["result"] == "correct")
    return result


def _time_reasons(raw, occurrences, evidence, clock):
    if clock is None:
        return ["clock_assumption_missing"]
    binding = evidence.get("binding", {})
    captured, bound = _instant(binding.get("capturedAt")), _instant(binding.get("boundAt"))
    observed = [_instant(o["observedAt"]) for o in occurrences]
    timestamp = raw.get("timestamp")
    if not _finite_number(timestamp) or timestamp < 946684800:
        return ["record_time_missing_or_invalid"]
    if captured is None or bound is None or not all(observed):
        return ["binding_or_observation_time_invalid"]
    skew = clock["maxSkewSeconds"]
    resolution = max(clock["timestampResolutionSeconds"], 1 if type(timestamp) is int else math.ulp(timestamp))
    earliest, latest = timestamp - skew - resolution, timestamp + skew + resolution
    observation_lower = min(o[0] - o[1] for o in observed)
    if bound[0] < captured[0] or max(captured[0], bound[0]) > observation_lower:
        return ["clock_order_anomaly"]
    if latest > observation_lower:
        return ["record_time_future_or_uncertain"]
    if earliest <= max(captured[0] + captured[1], bound[0] + bound[1]):
        return ["record_before_binding_or_precision_boundary"]
    return []


def project_records(observations, *, scope, book_id, record_scope_id, evidence=None, current_check=None, clock_assumption=None):
    """纯投影。调用方须保存 observations 的原始公开字节及本次采集证据。

    evidence 来自 Baseline.load_learning_evidence，current_check 来自本次
    evaluate_content_observations；这是可复用业务函数，不是认证或文件校验替代物。
    """
    identifier(record_scope_id, "recordScopeId")
    clock = validate_clock_assumption(clock_assumption)
    evidence, current_check = evidence or {}, current_check or {}
    index = _questions(evidence)
    extension_questions = {}
    for row in current_check.get('extension', {}).get('questions', []):
        key = (row.get('pageId'), row.get('blockId'), row.get('questionId'))
        extension_questions[key] = row
        index.setdefault(key, []).append({'value': row['value'], 'uniqueContainers': True,
                                         'i4Support': row['i4Support'], 'optionKeys': row['optionKeys']})
    entries, summaries, errors, rejected, readers = {}, [], [], [], []
    statuses, seen_sources, scoped_keys = [], {}, defaultdict(set)
    for observation in observations:
        ref, body = observation["rawRef"], observation["body"]
        if (not isinstance(ref, str) or not ref or ref.startswith("/") or Path(ref).is_absolute()
                or any(ord(c) < 32 for c in ref) or any(part in ("", ".", "..") for part in ref.split("/"))
                or "\\" in ref or ":" in ref):
            raise DeliveryError("record_raw_ref", "原响应必须使用包／state 内的安全相对引用")
        if ref in seen_sources:
            if seen_sources[ref] != sha256(body):
                raise DeliveryError("record_raw_conflict", "同原始引用对应了不同响应字节", "conflict")
            continue
        seen_sources[ref] = sha256(body)
        try:
            value = decode_json(body)
            canonical(value)  # 不接受溢出 float／不可编码 surrogate 的所谓完整原值。
            validate_learning_state(value, book_id, scope)
        except (ValueError, TypeError, UnicodeError, AttributeError) as exc:
            raise DeliveryError("record_response_json", "原始响应不是有限、完整的严格 JSON") from exc
        if value["readerScope"] not in readers:
            readers.append(deepcopy(value["readerScope"]))
        item = value["progress"]
        statuses.append({"rawRef": ref, "status": item["status"], "coverage": item["coverage"],
                         "valueAcquired": item["valueAcquired"], "diagnostics": deepcopy(item["diagnostics"])})
        if not item["valueAcquired"]:
            errors.append({"code": "progress_not_acquired", "rawRef": ref})
            continue
        progress = item["value"]
        if not isinstance(progress, dict) or progress.get("book_id") != book_id:
            rejected.append({"code": "progress_book_identity", "rawRef": ref, "pointer": "/progress/value"})
            continue
        summaries.append({"rawRef": ref, "pointer": "/progress/value", "fields": {
            k: deepcopy(progress[k]) for k in ("score", "weak_chapters", "current_page_id", "visited_page_ids",
                                             "bookmarked_page_ids", "updated_at") if k in progress}})
        attempts = progress.get("quiz_attempts")
        if not isinstance(attempts, list):
            errors.append({"code": "attempts_missing_or_invalid", "rawRef": ref})
            continue
        for position, raw in enumerate(attempts):
            occurrence = {"rawRef": ref, "responseSha256": sha256(body), "pointer": f"/progress/value/quiz_attempts/{position}",
                          "arrayIndex": position, "observedAt": observation["observedAt"]}
            submission = raw.get("submission_id") if isinstance(raw, dict) else None
            stable = submission_key(scope, book_id, submission)
            legacy = isinstance(raw, dict) and ("submission_id" not in raw or submission == "")
            quality = "stable" if stable else "legacy" if legacy else "invalid"
            identity = stable or {"rule": "export-local-occurrence/1", "recordScopeId": record_scope_id,
                                  "rawRef": ref, "pointer": occurrence["pointer"]}
            payload_digest = digest(raw)
            group = digest({"identity": identity, "payloadDigest": payload_digest})
            if group not in entries:
                entries[group] = {"recordId": digest({"rule": RECORD_RULE, "recordScopeId": record_scope_id, "group": group}),
                                  "identityQuality": quality, "identity": identity, "raw": deepcopy(raw), "occurrences": []}
            entries[group]["occurrences"].append(occurrence)
            if stable:
                scoped_keys[stable["digest"]].add(payload_digest)
    reader_consistent = len(readers) <= 1
    if not reader_consistent:
        errors.append({"code": "reader_changed_during_observation"})
    baseline_reasons = list(evidence.get("issues", []))
    if evidence.get("bindingStatus") != "accepted":
        baseline_reasons.append("accepted_binding_unavailable")
    if evidence.get("binding", {}).get("purpose") != "pre_learning":
        baseline_reasons.append("not_pre_learning_baseline")
    if (current_check.get("binding") not in ("baseline_consistent", "extension_consistent")
            or current_check.get("contentConsistent") is not True
            or current_check.get("sourceAvailability") != "complete" or current_check.get("recordWindowStable") is not True):
        baseline_reasons.append("fresh_complete_record_window_unavailable")
    if (evidence.get("scope") != scope or evidence.get("bookId") != book_id or
            current_check.get("snapshotId") != evidence.get("snapshotId") or
            current_check.get("baselineIdentity") != evidence.get("manifest", {}).get("identity")):
        baseline_reasons.append("baseline_context_mismatch")
    if not reader_consistent:
        baseline_reasons.append("reader_changed_during_observation")
    records, observed_questions = [], set()
    for row in entries.values():
        raw, problems = row["raw"], []
        key = _question_key(raw)
        if key:
            observed_questions.add(key)
        else:
            problems.append("question_identity_missing_or_invalid")
        matches = index.get(key, []) if key else []
        question = matches[0] if len(matches) == 1 and matches[0]["uniqueContainers"] else None
        if question is None:
            problems.append("question_missing_or_ambiguous")
        conflict = row["identityQuality"] == "stable" and len(scoped_keys[row["identity"]["digest"]]) > 1
        if conflict:
            problems.append("identity_conflict")
        if not isinstance(raw, dict):
            problems.append("attempt_not_object")
            raw_fields = {}
        else:
            raw_fields = raw
            for field in ("user_answer", "submission_id"):
                if field in raw and not isinstance(raw[field], str):
                    problems.append("invalid_" + field)
            if "is_correct" in raw and raw["is_correct"] is not None and type(raw["is_correct"]) is not bool:
                problems.append("invalid_verdict")
        if row["identityQuality"] == "invalid":
            problems.append("submission_identity_invalid")
        reasons = list(baseline_reasons) + problems
        if not reasons:
            reasons.extend(_time_reasons(raw_fields, row["occurrences"], evidence, clock))
        extension = extension_questions.get(key)
        binding = "unknown" if reasons else "extension_consistent" if extension is not None else "baseline_consistent"
        comparison = _comparison(raw_fields, question, evidence)
        verdict_present = "is_correct" in raw_fields
        verdict = {"present": verdict_present}
        if verdict_present:
            verdict["value"] = deepcopy(raw_fields["is_correct"])
        kind = question["value"].get("question_type") if question else None
        method = "unknown"
        if verdict_present and raw_fields["is_correct"] is None:
            method = "ungraded"
        elif binding in ("baseline_consistent", "extension_consistent") and kind == "choice" and type(raw_fields.get("is_correct")) is bool:
            method = "client_reported"
        elif (binding in ("baseline_consistent", "extension_consistent") and isinstance(kind, str) and kind in NON_CHOICE and
              type(raw_fields.get("is_correct")) is bool and
              raw_fields.get("user_answer") in ("self:correct", "self:incorrect")):
            method = "user_self_report"
            if type(raw_fields.get("is_correct")) is bool and raw_fields["is_correct"] != (raw_fields["user_answer"] == "self:correct"):
                problems.append("self_report_verdict_disagreement")
        assessment = {"raw": {"method": method, "isCorrect": verdict,
                      "transportSource": "client_reported" if type(raw_fields.get("is_correct")) is bool else "unknown"},
                      "comparisonToBaseline": comparison, "assessmentSync": "unknown"}
        if question:
            assessment["typeBasis"] = {"snapshotId": evidence.get("snapshotId"),
                                       "questionType": kind, "historicalBinding": binding}
        binding_evidence = {"status": binding, "assurance": "cooperative", "submissionContent": "unknown",
                            "reasons": sorted(set(reasons))}
        if extension is not None:
            binding_evidence.update(commitDigest=extension["commitDigest"], qualityReview=extension["qualityReview"])
            if question:
                assessment["typeBasis"]["extensionCommitDigest"] = extension["commitDigest"]
                assessment["typeBasis"]["qualityReview"] = extension["qualityReview"]
        row.update(identityConflict=conflict, assessments=assessment,
                   binding=binding_evidence, diagnostics=sorted(set(problems)), assistance={"status": "unknown"})
        records.append(row)
    missing = [{"kind": "missing_attempt", "meaning": "not_observed_in_selected_responses", "snapshotId": evidence.get("snapshotId"),
                "pageId": key[0], "blockId": key[1], "questionId": key[2], "coverage": "partial" if errors or rejected else "selected_responses"}
               for key, questions in index.items() if key not in observed_questions and len(questions) == 1 and questions[0]["uniqueContainers"]]
    return {"schema": RECORD_RULE, "recordScopeId": record_scope_id, "scope": deepcopy(scope), "bookId": book_id,
            "readerScopes": readers, "records": records, "missingAttemptObservations": missing,
            "upstreamSummaries": summaries, "progressObservations": statuses,
            "recordCoverage": "complete" if statuses and not errors and not rejected and all(s["status"] == "valid" and s["coverage"] == "complete" for s in statuses) else "partial",
            "logicalAttemptCount": "unknown", "clockAssumption": clock, "errors": errors, "rejectedObservations": rejected,
            "limitations": ["cooperative_content_binding", "submission_content_unknown", "assistance_unknown", "not_a_mastery_assessment"]}


class LearningRecords:
    """一次进度窗口的只读观察，无重试／无可搬运包发布，供 I5-B 验证。

    I5-D 将以共享单轮接口把会话读取纳入更大的窗口，不能将本操作嵌套
    成额外的三层重试。每次调用新 observationId；既有 checkId 不作输入。
    """
    def __init__(self, store, backend):
        self.store, self.backend, self.scope = store, backend, backend.scope
        self.baseline = Baseline(store, backend)

    def observe_records(self, activity_id, *, snapshot_id=None, clock_assumption=None):
        clock = validate_clock_assumption(clock_assumption)
        with self.store.lock(self.scope):
            context = self.baseline.learning_context(activity_id)
            evidence = self.baseline.load_learning_evidence(activity_id, snapshot_id)
            observation_id = "records-" + uuid.uuid4().hex
            directory = self.store.root / "record-observations" / uuid.uuid4().hex[:16]
            content_errors = []
            def read_boundary(number):
                try:
                    return self.baseline.read_content_once(directory, number, context)
                except DeliveryError as exc:
                    content_errors.append({"code": exc.code, "boundary": number})
                    atomic(directory / f"boundary-{number}-error.json", canonical(content_errors[-1]), immutable=True)
                    return None
            first = read_boundary(1)
            observations = []
            for number in (1, 2):
                response = self.backend.read_learning_state(context[0]["bookId"])
                path = directory / f"state-{number}.bin"
                atomic(path, response.body, immutable=True)
                observations.append({"rawRef": path.relative_to(self.store.root).as_posix(), "body": response.body, "observedAt": now()})
            second = read_boundary(2)
            check = {"binding": "unknown", "contentConsistent": False, "sourceAvailability": "unknown"}
            if "manifest" in evidence and first is not None and second is not None:
                try:
                    check = self.baseline.evaluate_content_observations(activity_id, evidence["snapshotId"], first, second)
                except DeliveryError as exc:
                    content_errors.append({"code": exc.code, "boundary": "comparison"})
            end_evidence = self.baseline.load_learning_evidence(activity_id, evidence.get("snapshotId", snapshot_id))
            evidence_stable = canonical({k: evidence[k] for k in ("bindingStatus", "issues", "evidenceRefs")}) == canonical(
                {k: end_evidence[k] for k in ("bindingStatus", "issues", "evidenceRefs")})
            if not evidence_stable:
                content_errors.append({"code": "baseline_evidence_changed", "boundary": "comparison"})
                check["binding"] = "unknown"
            values = [decode_json(o["body"]) for o in observations]
            stable = canonical({k: values[0][k] for k in ("readerScope", "contentAccess", "progress", "pageChatSessions")}) == canonical(
                {k: values[1][k] for k in ("readerScope", "contentAccess", "progress", "pageChatSessions")})
            check.update(recordWindowStable=stable, baselineEvidenceStable=evidence_stable,
                         observationId=observation_id, errors=content_errors)
            for observation, number, label in ((first, 1, "firstContentReadRef"), (second, 2, "lastContentReadRef")):
                if observation is not None:
                    check[label] = (directory / f"r{number}/read.json").relative_to(self.store.root).as_posix()
            atomic(directory / "current-check.json", canonical(check), immutable=True)
            result = project_records(observations, scope=self.scope, book_id=context[0]["bookId"], record_scope_id=observation_id,
                                     evidence=evidence, current_check=check, clock_assumption=clock)
            result.update(activityId=activity_id, observationId=observation_id, currentCheck=check,
                          baselineEvidence={k: evidence[k] for k in ("bindingStatus", "issues", "evidenceRefs")},
                          artifactRef=(directory / "records.json").relative_to(self.store.root).as_posix(),
                          status="succeeded" if stable and not content_errors and result["recordCoverage"] == "complete" else "partial",
                          scopeOfObservation="progress_only_not_full_handoff")
            atomic(directory / "records.json", canonical(result), immutable=True)
            return result
