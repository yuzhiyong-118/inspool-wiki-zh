"""I4：只读采集、不可变内容证据、外部审查与首次基线绑定。"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import uuid

from .content import CAPABILITY, RULE, UPSTREAM, dependencies, project, resource_path
from .contracts import (DeliveryError, canonical, contained, content_hash, digest, identifier,
                        object_value, read_json, sha256, text)
from .evidence_store import atomic
from .production import Production


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class Baseline:
    def __init__(self, store, backend, *, fault=None):
        self.store, self.backend, self.scope = store, backend, backend.scope
        self.production = Production(store, backend)
        self.fault = fault or (lambda _: None)
        build = object_value(backend.config.get("contentReadBuild"), "contentReadBuild")
        if build.get("baseCommit") != UPSTREAM or build.get("rendererCommit") != UPSTREAM:
            raise DeliveryError("content_build", "只接受固定源码与 renderer 的补丁构建")
        self.build = {"baseCommit": UPSTREAM, "rendererCommit": UPSTREAM,
                      "patchSha256": content_hash(build.get("patchSha256")),
                      "wheelSha256": content_hash(build.get("wheelSha256")),
                      "capability": CAPABILITY, "verification": "configured_build"}

    def _path(self, namespace, key):
        return self.store.root / namespace / digest(identifier(key, namespace + "Id"))

    def _operation(self, namespace, key, semantic):
        directory = self._path(namespace, key)
        path = directory / "request.json"
        record = {"id": key, "semantic": semantic, "digest": digest(semantic)}
        atomic(path, canonical(record), immutable=True)
        result = directory / "result.json"
        if result.exists():
            value = read_json(result)
            if value.get("requestDigest") != record["digest"]:
                raise DeliveryError("read_receipt_integrity", "只读操作回执与输入不符", "conflict")
            return directory, record, value
        return directory, record, None

    def _result(self, directory, request, operation, status, **fields):
        value = {"operation": operation, "status": status, "requestDigest": request["digest"],
                 "requestId": request["id"],
                 "receiptRef": (directory / "result.json").relative_to(self.store.root).as_posix(),
                 "recordedAt": now(), "errors": [], "nextAction": "inspect_baseline_evidence", **fields}
        snapshot_id = fields.get("snapshotId")
        if snapshot_id and (self._snapshot_path(snapshot_id) / "complete.json").exists():
            value["artifactRef"] = (self._snapshot_path(snapshot_id) / "manifest.json").relative_to(self.store.root).as_posix()
        atomic(directory / "result.json", canonical(value), immutable=True)
        return value

    def _context(self, activity_id):
        mapping = self.production._mapping(identifier(activity_id, "activityId"))
        origin = self.store.request(mapping["productionRequestId"])
        receipt = self.store.receipt(mapping["productionRequestId"])
        semantic = origin["semantic"]
        if (semantic.get("operation") != "create" or semantic.get("scope") != self.scope
                or semantic.get("activityId") != activity_id or receipt.get("status") != "succeeded"
                or receipt.get("bookId") != mapping["bookId"]):
            raise DeliveryError("production_mapping", "活动缺少同作用域的成功生产证据", "conflict")
        for request in self.store.requests():
            if request["semantic"].get("activityId") == activity_id:
                if self.store.receipt(request["requestId"])["status"] in ("prepared", "dispatching", "uncertain"):
                    raise DeliveryError("production_unresolved", "该活动仍有未确认的生产结果", "conflict")
        corpus, corpus_receipt = self.production._corpus(semantic["corpusRequestId"])
        if (corpus_receipt.get("coverage") != "complete"
                or corpus_receipt.get("corpusDigest") != digest(corpus["semantic"]["corpus"])
                or corpus_receipt.get("corpus") != corpus["semantic"]["corpus"]):
            raise DeliveryError("corpus_receipt_integrity", "语料回执与冻结语料不一致", "conflict")
        return mapping, corpus, corpus_receipt

    def _sources(self, mapping, corpus, receipt):
        issues = []
        try:
            self.production._validate_originals(corpus)
            for artifact in corpus["semantic"]["corpus"]["inputArtifacts"]:
                path = self.store.request_dir(corpus["requestId"]) / "inputs" / artifact["remotePath"]
                if not path.is_file() or sha256(path.read_bytes()) != artifact["sha256"]:
                    raise DeliveryError("input_evidence_missing", "冻结输入证据缺失或变更", "partial")
        except (DeliveryError, OSError) as exc:
            issues.append({"code": exc.code if isinstance(exc, DeliveryError) else "local_source_unreadable", "kind": "local_sources"})
        try:
            run = self.production._verify_corpus(corpus, receipt["kbRef"], receipt["taskId"], observe=False)
            if run["usable_version"] != receipt.get("usableVersion"):
                raise DeliveryError("corpus_usable_version", "语料索引版本发生漂移", "partial")
        except DeliveryError as exc:
            issues.append({"code": exc.code, "kind": "remote_corpus"})
        source_mapping = {"activityId": mapping["activityId"], "bookId": mapping["bookId"], "scope": self.scope,
                          "productionRequestId": mapping["productionRequestId"], "corpusRequestId": corpus["requestId"],
                          "corpus": corpus["semantic"]["corpus"], "kbRef": receipt["kbRef"],
                          "taskId": receipt["taskId"], "usableVersion": receipt["usableVersion"]}
        origin = self.store.request(mapping['productionRequestId'])
        binding = origin['semantic'].get('knowledgePreparation')
        if binding is not None:
            from .preparation_provenance import load_provenance
            ref = origin['semantic'].get('preparationProvenanceRef')
            try:
                load_provenance(self.store, ref, binding)
                from .preparation_continuation import active_preparation
                active = active_preparation(self.store, mapping, origin)
                source_mapping['preparation'] = {'status':'available', 'originRef':ref,
                    'activeRef':active['provenanceRef'], 'binding':active['binding'],
                    'continuations':active['records'], 'sourceOriginalsVerified':False}
            except (DeliveryError, OSError, ValueError, TypeError) as exc:
                issues.append({'code':'preparation_provenance_missing_or_invalid','kind':'preparation'})
                source_mapping['preparation'] = {'status':'unavailable','sourceOriginalsVerified':False}
        return {"status": "complete" if not issues else "partial", "issues": issues,
                "mapping": source_mapping, "sourceMappingDigest": digest(source_mapping)}

    def _resources(self, projection):
        refs, issues = dependencies(projection)
        grouped = {}
        for ref in refs:
            grouped.setdefault(ref["uri"], []).append(ref["location"])
        rows, assets, total = [], {}, 0
        for index, (uri, locations) in enumerate(grouped.items()):
            path = resource_path(uri, self.backend.config["baseUrl"])
            row = {"uri": uri, "locations": locations, "status": "unsupported"}
            if index >= 64:
                row["reason"] = "resource_count_limit"
            elif total >= 32 * 1024 * 1024:
                row.update(status="partial", reason="resource_bytes_limit")
            elif path is None:
                row["reason"] = "resource_uri_unsupported"
            elif not self.scope["workspaceId"]:
                # General 的固定下载路由可能回退到 partner workspace，响应
                # 未证明字节来自当前 workspace；不能伪造同作用域完整性。
                row["reason"] = "general_output_scope_unproven"
            else:
                try:
                    response = self.backend.read_resource(uri)
                    row.update(httpStatus=response.status, wireSha256=response.wire_sha256, redacted=response.redacted)
                    mime = response.content_type.split(";", 1)[0].strip().lower()
                    total += len(response.body)
                    if response.status != 200:
                        row.update(status="missing", reason="resource_http")
                    elif response.redacted:
                        row.update(status="partial", reason="resource_redacted")
                    elif len(response.body) > 8 * 1024 * 1024 or total > 32 * 1024 * 1024:
                        row.update(status="partial", reason="resource_bytes_limit")
                    elif mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"} or image_type(response.body) != mime:
                        row.update(status="unsupported", reason="resource_type")
                    else:
                        content_digest = sha256(response.body)
                        asset = "assets/" + content_digest + ".bin"
                        row.update(status="complete", sha256=content_digest, length=len(response.body), mime=mime, path=asset)
                        assets[asset] = response.body
                except DeliveryError as exc:
                    row.update(status="missing", reason=exc.code)
            rows.append(row)
        # wireHash 不用于身份；下载字节 hash、MIME、位置、URI 均进入身份。
        manifest = {"rule": RULE, "resources": rows, "issues": issues,
                    "status": "complete" if not issues and all(r["status"] == "complete" for r in rows) else "partial"}
        return manifest, assets

    def learning_context(self, activity_id):
        """供只读采集共用的 I3 活动／语料门禁；不读取或重建学习状态。"""
        return self._context(activity_id)

    def read_content_once(self, directory, number, context):
        """一次内容／资源／来源观测，无隐含重试；调用方组织窗口。"""
        directory = Path(directory)
        if (directory.resolve() != directory.absolute() or not contained(directory.resolve(), self.store.root)
                or type(number) is not int or number < 1):
            raise DeliveryError("content_read_path", "单轮读取只能写入本 state 的安全证据目录")
        mapping, corpus, receipt = context
        if mapping.get("scope") != self.scope:
            raise DeliveryError("scope_mismatch", "单轮读取的活动 scope 不符", "conflict")
        round_dir = directory / f"r{number}"
        started = now()
        self.backend.verify_scope()
        sources = self._sources(mapping, corpus, receipt)
        response = self.backend.read_content(mapping["bookId"])
        atomic(round_dir / "response.bin", response.body, immutable=True)
        self.fault("raw")
        value = response.json()
        extension = None
        book_value = value.get("book") if isinstance(value, dict) else None
        metadata = book_value.get("metadata") or {} if isinstance(book_value, dict) else {}
        if metadata.get("learning_extension_head") is not None:
            from .deeptutor import segment
            extension_response = self.backend.read('/api/books/' + segment(mapping["bookId"]) + '/extension-evidence')
            if extension_response.status != 200:
                raise DeliveryError("extension_evidence_read", "扩展内容证据没有完整可读", "uncertain")
            atomic(round_dir / "extension.bin", extension_response.body, immutable=True)
            extension = extension_response.json()
            if (extension.get("schema") != "learning-extension-evidence/1"
                    or extension.get("bookId") != mapping["bookId"]
                    or extension.get("head") != metadata.get("learning_extension_head")):
                raise DeliveryError("extension_evidence_identity", "扩展证据与当前 Book 链头不符", "conflict")
        try:
            projection, observation, structure = project(value, mapping["bookId"])
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise DeliveryError("content_shape", "只读响应的内容结构不完整，原始响应已保留", "failed") from exc
        from .question_evidence import collect
        questions = collect(self.store, mapping['activityId'], projection)
        if questions is not None:
            self.production._question_capability(mapping['bookId'])
        if value["book"].get("knowledge_bases") != [receipt["kbRef"]]:
            structure["findings"].append({"code": "book_corpus_reference", "location": "book.knowledge_bases", "blocking": True})
            structure["blocking"] = True
        try:
            resources, assets = self._resources(projection)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise DeliveryError("render_shape", "内容渲染字段无法完整识别", "failed") from exc
        for name, data in assets.items():
            atomic(round_dir / name, data, immutable=True)
        content_digest = digest(projection)
        identity = {"rule": RULE, "contentDigest": content_digest,
                    "resourceManifestDigest": digest(resources), "sourceMappingDigest": sources["sourceMappingDigest"]}
        boundary = {"identity": identity, "observation": observation, "sourceStatus": sources["status"],
                    "sourceIssues": sources["issues"], "structure": structure}
        if questions is not None: boundary['questionEvidenceDigest'] = digest(questions)
        if extension is not None: boundary['extensionDigest'] = digest(extension)
        record = {"startedAt": started, "finishedAt": now(), "identity": identity,
                  "boundaryDigest": digest(boundary), "responseSha256": sha256(response.body),
                  "wireSha256": response.wire_sha256, "observation": observation,
                  "sources": sources, "resources": resources, "structure": structure}
        if extension is not None: record['extension'] = extension
        atomic(round_dir / "read.json", canonical(record), immutable=True)
        self.fault("round")
        return {"record": record, "projection": projection, "assets": assets, "raw": response.body,
                'questions': questions, 'extension': extension}

    def _round(self, directory, number, context):
        # 保持 I4 的内部挂钩与原来的三对重试行为。
        return self.read_content_once(directory, number, context)

    def _pair(self, directory, context):
        last = None
        for pair in range(3):
            first = self._round(directory, pair * 2 + 1, context)
            second = self._round(directory, pair * 2 + 2, context)
            last = (first, second)
            if first["record"]["boundaryDigest"] == second["record"]["boundaryDigest"]:
                return last, True, pair + 1
        return last, False, 3

    def _snapshot_path(self, snapshot_id):
        return self._path("snapshots", snapshot_id)

    def _file(self, directory, name):
        # manifest 文件名即使被修改也不能越出包；不跟随链接到包外。
        path = directory / name
        if Path(name).is_absolute() or not contained(path.resolve(), directory.resolve()) or ".." in Path(name).parts:
            raise DeliveryError("snapshot_path", "证据包含越界路径", "conflict")
        return path

    def load_snapshot(self, snapshot_id):
        try:
            return self._load_snapshot(snapshot_id)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise DeliveryError("snapshot_integrity", "快照文件缺失或结构损坏", "conflict") from exc

    def _load_snapshot(self, snapshot_id):
        directory = self._snapshot_path(snapshot_id)
        if directory.resolve() != directory.absolute():
            raise DeliveryError("snapshot_path", "快照目录不能通过链接重定向", "conflict")
        marker = read_json(self._file(directory, "complete.json"))
        manifest_bytes = self._file(directory, "manifest.json").read_bytes()
        manifest = read_json(self._file(directory, "manifest.json"))
        if manifest.get('schema') not in ('learning-content-snapshot/1', 'learning-content-snapshot/2'):
            raise DeliveryError('snapshot_version', '不支持的快照版本', 'conflict')
        if marker.get("manifestDigest") != sha256(manifest_bytes) or manifest.get("snapshotId") != snapshot_id:
            raise DeliveryError("snapshot_integrity", "快照完成标记或身份损坏", "conflict")
        if manifest.get("scope") != self.scope:
            raise DeliveryError("scope_mismatch", "快照作用域与部署不一致", "conflict")
        files = manifest.get("files")
        if not isinstance(files, dict) or not {"content.json", "resources.json", "sources.json", "capture.json"} <= files.keys():
            raise DeliveryError("snapshot_integrity", "快照文件目录不完整", "conflict")
        for name, expected in files.items():
            if sha256(self._file(directory, name).read_bytes()) != expected:
                raise DeliveryError("snapshot_integrity", "快照文件 hash 不符", "conflict")
        content, resources, sources = (read_json(directory / name) for name in ("content.json", "resources.json", "sources.json"))
        self._verify_questions(manifest, content, lambda name:read_json(self._file(directory, name)))
        identity = {"rule": RULE, "contentDigest": digest(content), "resourceManifestDigest": digest(resources),
                    "sourceMappingDigest": sources["sourceMappingDigest"]}
        if sources["sourceMappingDigest"] != digest(sources["mapping"]) or identity != manifest.get("identity"):
            raise DeliveryError("snapshot_integrity", "快照内容／资源／来源摘要不符", "conflict")
        for row in resources.get("resources", []):
            if row.get("status") == "complete":
                if files.get(row.get("path")) != row.get("sha256"):
                    raise DeliveryError("snapshot_integrity", "资源 manifest 未对应实际包文件", "conflict")
        return manifest

    def capture_baseline(self, activity_id, capture_id, snapshot_id, purpose, declaration=None):
        identifier(snapshot_id, "snapshotId")
        if purpose not in ("pre_learning", "retrospective"):
            raise DeliveryError("purpose", "purpose 必须是 pre_learning 或 retrospective")
        if purpose == "pre_learning":
            declaration = object_value(declaration, "declaration")
            declaration = {"actorId": identifier(declaration.get("actorId"), "actorId"),
                           "statement": text(declaration.get("statement"), "statement")}
        elif declaration is not None:
            raise DeliveryError("declaration", "retrospective 不接受学习前冻结声明")
        semantic = {"activityId": identifier(activity_id, "activityId"), "snapshotId": snapshot_id,
                    "scope": self.scope, "purpose": purpose, "declaration": declaration, "rule": RULE, "build": self.build}
        with self.store.lock(self.scope):
            directory, request, result = self._operation("captures", capture_id, semantic)
            if result:
                if result.get("snapshotId"):
                    self.load_snapshot(snapshot_id)
                return result
            final = self._snapshot_path(snapshot_id)
            if final.exists():
                manifest = self.load_snapshot(snapshot_id)
                if manifest.get("captureDigest") != request["digest"] or manifest.get("captureId") != capture_id:
                    raise DeliveryError("snapshot_conflict", "snapshotId 已对应其他捕获，不可覆盖", "conflict")
                return self._result(directory, request, "capture-baseline", manifest["resultStatus"],
                                    activityRef=activity_id, snapshotId=snapshot_id, captureStatus=manifest["captureStatus"],
                                    identity=manifest["identity"], recovered=True)
            context = self._context(activity_id)
            attempt = directory / "a" / uuid.uuid4().hex[:16]
            attempt.mkdir(parents=True)
            try:
                pair, stable, pairs = self._pair(attempt, context)
                first, second = pair
                record = second["record"]
                readiness_codes = {"enumeration_incomplete", "generation_not_ready", "book_not_ready", "page_not_ready", "block_not_ready"}
                partial = (record["sources"]["status"] != "complete" or record["resources"]["status"] != "complete"
                           or record["structure"]["contentCoverage"] != "complete"
                           or any(f["code"] in readiness_codes for f in record["structure"]["findings"]))
                status = "inconsistent" if not stable else "partial" if partial else "stable_complete"
                result_status = "succeeded" if status == "stable_complete" else "partial"
                capture = {"captureId": capture_id, "purpose": purpose, "declaration": declaration,
                           "startedAt": first["record"]["startedAt"], "capturedAt": second["record"]["finishedAt"],
                           "pairsRead": pairs, "stable": stable, "structure": record["structure"],
                           "rounds": [first["record"], second["record"]], "build": self.build,
                           "assurance": "cooperative", "atomicSnapshot": False}
                staging = self.store.root / "snapshots" / (".staging-" + uuid.uuid4().hex)
                artifacts = {"content.json": canonical(second["projection"]),
                             "resources.json": canonical(record["resources"]), "sources.json": canonical(record["sources"]),
                             "capture.json": canonical(capture), "raw/round-1.bin": first["raw"], "raw/round-2.bin": second["raw"],
                             **first["assets"], **second["assets"]}
                questions = second.get('questions')
                if questions is not None:
                    from .question_preparation import ordered_bytes
                    artifacts['questions.json'] = ordered_bytes(questions)
                for name, data in artifacts.items():
                    atomic(staging / name, data, immutable=True)
                    self.fault("assets" if name.startswith("assets/") else "content")
                manifest = {"schema": "learning-content-snapshot/1", "snapshotId": snapshot_id,
                            "captureId": capture_id, "captureDigest": request["digest"], "activityId": activity_id,
                            "bookId": context[0]["bookId"], "scope": self.scope, "identity": record["identity"],
                            "captureStatus": status, "resultStatus": result_status,
                            "files": {name: sha256(data) for name, data in artifacts.items()}}
                if questions is not None:
                    manifest.update(schema='learning-content-snapshot/2', questionEvidenceDigest=digest(questions))
                atomic(staging / "manifest.json", canonical(manifest), immutable=True)
                self.fault("manifest")
                for name, expected in manifest["files"].items():
                    if sha256((staging / name).read_bytes()) != expected:
                        raise DeliveryError("staging_integrity", "发布前文件校验失败", "failed")
                atomic(staging / "complete.json", canonical({"manifestDigest": digest(manifest)}), immutable=True)
                self.fault("complete")
                os.rename(staging, final)
                self.fault("published")
                self.load_snapshot(snapshot_id)
                return self._result(directory, request, "capture-baseline", result_status, activityRef=activity_id,
                                    snapshotId=snapshot_id, captureStatus=status, identity=record["identity"],
                                    structuralBlocking=record["structure"]["blocking"],
                                    nextAction="external_quality_review" if status == "stable_complete" else "inspect_capture_diagnostics")
            except DeliveryError as exc:
                atomic(attempt / "failure.json", canonical({"at": now(), "code": exc.code}), immutable=True)
                return self._result(directory, request, "capture-baseline", "failed", activityRef=activity_id,
                                    captureStatus="failed", errors=[{"code": exc.code, "message": exc.message}])

    def _binding_path(self, activity_id):
        return self.store.root / "baselines" / (digest(activity_id) + ".json")

    def _check(self, activity_id, snapshot_id, directory):
        manifest = self.load_snapshot(snapshot_id)
        if manifest["activityId"] != activity_id:
            raise DeliveryError("snapshot_activity", "快照不属于该活动", "conflict")
        context = self._context(activity_id)
        pair, stable, pairs = self._pair(directory, context)
        return self.evaluate_content_observations(activity_id, snapshot_id, *pair, pairs_read=pairs, stable=stable)

    def evaluate_content_observations(self, activity_id, snapshot_id, first, second, *, pairs_read=1, stable=True):
        """复用 I4 一致性门禁；不发 HTTP，不执行嵌套重试。

        参数是本次窗口两端的 read_content_once 返回值，不能传旧 checkId。
        I5 还需 load_learning_evidence 验证首次绑定／审查链。
        """
        manifest = self.load_snapshot(snapshot_id)
        if manifest["activityId"] != activity_id:
            raise DeliveryError("snapshot_activity", "快照不属于该活动", "conflict")
        stable = stable and first["record"]["boundaryDigest"] == second["record"]["boundaryDigest"]
        current = second["record"]
        source_status = current["sources"]["status"]
        extension_result = None
        if current.get('extension') is not None:
            from .extensions import question_introductions, verify_chain
            baseline_content = read_json(self._snapshot_path(snapshot_id) / 'content.json')
            try:
                extension_result = verify_chain(baseline_content, second['projection'], current['extension']['commits'],
                                                book_id=manifest['bookId'])
                extension_result['questions'] = []
                for introduced in question_introductions(baseline_content, current['extension']['commits']):
                    key = (introduced['pageId'], introduced['blockId'], introduced['questionId'])
                    orders = [row.get('optionKeys') for row in second['projection'].get('optionDisplayOrders', [])
                              if (row.get('pageId'), row.get('blockId'), row.get('questionId')) == key]
                    extension_result['questions'].append({**introduced,
                        'optionKeys': orders[0] if len(orders) == 1 else None,
                        'i4Support': any((row.get('pageId'), row.get('blockId'), row.get('questionId')) == key
                            and row.get('assessmentSupport') == 'supported'
                            for row in current['structure']['questions'])})
            except DeliveryError as exc:
                extension_result = {'status': 'unknown', 'issues': [exc.code]}
            content_ok = extension_result['status'] == 'extension_consistent'
        else:
            content_ok = current["identity"] == manifest["identity"]
        consistent = (stable and manifest["captureStatus"] == "stable_complete" and content_ok
                      and current["resources"]["status"] == "complete"
                      and not current["structure"]["blocking"])
        path = self._binding_path(activity_id)
        binding = read_json(path) if path.exists() else None
        bound = binding and binding.get("snapshotId") == snapshot_id and binding.get("identity") == manifest["identity"] and binding.get("scope") == self.scope
        binding_status = ('extension_consistent' if extension_result is not None else 'baseline_consistent') if consistent and bound and source_status == 'complete' else 'unknown'
        result = {"snapshotId": snapshot_id, "activityRef": activity_id, "currentIdentity": current["identity"],
                "baselineIdentity": manifest["identity"], "contentConsistent": consistent,
                "sourceAvailability": source_status, "sourceIssues": current["sources"]["issues"],
                "binding": binding_status, "assurance": "cooperative", "submissionContent": "unknown", "atomicSnapshot": False,
                "pairsRead": pairs_read, "current": current}
        if extension_result is not None:
            result['extension'] = extension_result
        return result

    def load_learning_evidence(self, activity_id, snapshot_id=None):
        """校验实际首次绑定及其不可变审查请求，候选快照不升级为已绑定。

        缺失／损坏基线允许调用方继续取回原记录，返回明确诊断；活动与
        I3 scope 的错误仍由 learning_context 拒绝。无远端读取／状态修复。
        """
        context = self.learning_context(activity_id)
        result = {"activityId": activity_id, "bookId": context[0]["bookId"], "scope": self.scope,
                  "bindingStatus": "missing", "issues": [], "evidenceRefs": []}

        def read_evidence(path):
            path = Path(path)
            if path.resolve() != path.absolute() or not contained(path.resolve(), self.store.root):
                raise DeliveryError("baseline_evidence_path", "基线证据不能重定向或越界", "conflict")
            data = path.read_bytes()
            value = read_json(path)
            result["evidenceRefs"].append({"ref": path.relative_to(self.store.root).as_posix(), "sha256": sha256(data)})
            return value

        try:
            path = self._binding_path(activity_id)
            binding = read_evidence(path) if path.exists() else None
            if binding is not None and not isinstance(binding, dict):
                raise DeliveryError("baseline_binding_shape", "绑定文件不是对象", "conflict")
            if snapshot_id is None:
                snapshot_id = binding.get("snapshotId") if binding else None
            if snapshot_id is None:
                result["issues"].append("baseline_missing")
                return result
            identifier(snapshot_id, "snapshotId")
            manifest = self.load_snapshot(snapshot_id)
            if manifest["activityId"] != activity_id or manifest["bookId"] != context[0]["bookId"]:
                raise DeliveryError("snapshot_activity", "快照不属于当前活动及书", "conflict")
            snapshot = self._snapshot_path(snapshot_id)
            for name in ("manifest.json", "complete.json", *manifest["files"]):
                # 包内文件原字节由 load_snapshot 校验；仅登记引用供后续搬运。
                file = self._file(snapshot, name)
                result["evidenceRefs"].append({"ref": file.relative_to(self.store.root).as_posix(), "sha256": sha256(file.read_bytes())})
            capture, sources, content = (read_json(snapshot / name) for name in ("capture.json", "sources.json", "content.json"))
            result.update(snapshotId=snapshot_id, manifest=manifest, capture=capture, sources=sources,
                          content=content, bindingStatus="candidate")
            if (manifest.get("schema") not in ("learning-content-snapshot/1", "learning-content-snapshot/2") or content.get("rule") != RULE
                    or content.get("book", {}).get("id") != context[0]["bookId"]
                    or sources.get("mapping", {}).get("scope") != self.scope
                    or sources["mapping"].get("activityId") != activity_id
                    or sources["mapping"].get("bookId") != context[0]["bookId"]):
                raise DeliveryError("baseline_snapshot_contract", "快照契约或来源作用域不符", "conflict")
            capture_request = read_evidence(self._path("captures", manifest["captureId"]) / "request.json")
            semantic = capture_request["semantic"]
            if (capture_request.get("id") != manifest["captureId"] or capture_request.get("digest") != digest(semantic)
                    or manifest.get("captureDigest") != capture_request["digest"]
                    or any(semantic.get(k) != v for k, v in {"activityId": activity_id, "snapshotId": snapshot_id,
                        "scope": self.scope, "rule": RULE, "purpose": capture["purpose"],
                        "declaration": capture["declaration"], "build": capture["build"]}.items())
                    or capture.get("captureId") != manifest["captureId"]):
                raise DeliveryError("baseline_capture_evidence", "捕获请求与快照证据不符", "conflict")
            if binding is None:
                result["issues"].append("baseline_not_bound")
                return result
            if binding.get("snapshotId") != snapshot_id:
                result["issues"].append("candidate_not_accepted_baseline")
                return result
            expected = {"schema": "learning-baseline-binding/1", "activityId": activity_id,
                        "bookId": manifest["bookId"], "snapshotId": snapshot_id, "scope": self.scope,
                        "identity": manifest["identity"], "capturedAt": capture["capturedAt"],
                        "purpose": capture["purpose"], "assurance": "cooperative", "submissionContent": "unknown"}
            if any(binding.get(k) != v for k, v in expected.items()):
                raise DeliveryError("baseline_binding_identity", "首次绑定与完整快照不符", "conflict")
            review_id = identifier(binding.get("reviewId"), "reviewId")
            request = read_evidence(self._path("reviews", review_id) / "request.json")
            semantic = request["semantic"]
            review = semantic["review"]
            build = semantic.get("build", {})
            if (build.get("baseCommit") != UPSTREAM or build.get("rendererCommit") != UPSTREAM
                    or build.get("capability") != CAPABILITY):
                raise DeliveryError("baseline_review_build", "审查请求未标明固定只读构建", "conflict")
            content_hash(build.get("patchSha256"))
            content_hash(build.get("wheelSha256"))
            if (request.get("id") != review_id or request.get("digest") != digest(semantic)
                    or review.get("reviewId") != review_id or digest(review) != binding.get("reviewDigest")
                    or any(semantic.get(k) != v for k, v in {"activityId": activity_id,
                        "snapshotId": snapshot_id, "scope": self.scope, "rule": RULE}.items())
                    or self._review_reasons(review, manifest, capture, sources)
                    or manifest["captureStatus"] != "stable_complete" or sources["status"] != "complete"
                    or capture.get("stable") is not True or capture.get("atomicSnapshot") is not False
                    or len(capture["rounds"]) != 2 or any(r["identity"] != manifest["identity"] for r in capture["rounds"])
                    or capture["structure"]["blocking"] or capture["structure"]["supportedChoiceCount"] < 1):
                raise DeliveryError("baseline_review_evidence", "实际绑定缺少完整的通过审查证据", "conflict")
            receipt_path = self._path("reviews", review_id) / "result.json"
            if receipt_path.exists():
                receipt = read_evidence(receipt_path)
                if (receipt.get("requestDigest") != request["digest"] or receipt.get("requestId") != review_id
                        or receipt.get("snapshotId") != snapshot_id or receipt.get("baselineBound") is not True):
                    raise DeliveryError("baseline_review_receipt", "审查回执与已提交绑定矛盾", "conflict")
                result["reviewReceiptStatus"] = "present"
            else:
                # I4 的绑定先于回执提交；崩溃后的绑定事实不能由缺回执抹去。
                result["reviewReceiptStatus"] = "missing_after_binding"
            result.update(bindingStatus="accepted", binding=binding, review=review)
        except (DeliveryError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            result["bindingStatus"] = "invalid"
            result["issues"].append(exc.code if isinstance(exc, DeliveryError) else "baseline_evidence_invalid")
        return result

    def check_baseline(self, activity_id, snapshot_id, check_id):
        semantic = {"activityId": activity_id, "snapshotId": snapshot_id, "scope": self.scope, "rule": RULE, "build": self.build}
        with self.store.lock(self.scope):
            directory, request, result = self._operation("checks", check_id, semantic)
            if result:
                self.load_snapshot(snapshot_id)
                return result
            try:
                value = self._check(activity_id, snapshot_id, directory / "a" / uuid.uuid4().hex[:16])
                return self._result(directory, request, "check-baseline",
                                    "succeeded" if value["contentConsistent"] and value["sourceAvailability"] == "complete" else "partial", **value)
            except DeliveryError as exc:
                return self._result(directory, request, "check-baseline", "partial", activityRef=activity_id,
                                    snapshotId=snapshot_id, binding="unknown", assurance="cooperative", submissionContent="unknown",
                                    errors=[{"code": exc.code, "message": exc.message}])

    @staticmethod
    def quality_review_reasons(review, manifest, capture, sources, question_evidence=None):
        reasons = []
        def require(condition, code):
            if not condition:
                reasons.append(code)
        require(review.get("schema") == "baseline-quality-review/1", "review_schema")
        require(review.get("snapshotId") == manifest["snapshotId"] and review.get("activityId") == manifest["activityId"], "review_identity")
        require(review.get("identity") == manifest["identity"], "review_digests")
        actor = review.get("actor")
        require(isinstance(actor, dict) and isinstance(actor.get("actorId"), str) and bool(actor["actorId"].strip())
                and actor.get("role") in ("user", "external_preparer_agent"), "review_actor")
        require(review.get("decision") == "pass", "review_decision")
        require(review.get("sourceFidelityChecked") is True, "source_fidelity_not_checked")
        findings = review.get("findings")
        require(isinstance(findings, list) and all(isinstance(f, dict) and isinstance(f.get("description"), str)
                and f.get("severity") in ("blocking", "note") and f.get("status") in ("open", "resolved")
                and not (f["severity"] == "blocking" and f["status"] == "open") for f in findings), "review_findings")
        require(review.get("unsupportedAcknowledged") == capture["structure"]["unsupported"], "unsupported_not_acknowledged")
        evidence = review.get("sourceEvidence")
        evidence = evidence if isinstance(evidence, list) else []
        source_keys = {(s["sourceId"], s["sourceVersionId"], s["sha256"]) for s in sources["mapping"]["corpus"]["sources"]}
        valid_evidence = [e for e in evidence if isinstance(e, dict)
                          and (e.get("sourceId"), e.get("sourceVersionId"), e.get("sha256")) in source_keys
                          and isinstance(e.get("evidenceId"), str) and e["evidenceId"].strip()
                          and isinstance(e.get("locator"), str) and e["locator"].strip()
                          and isinstance(e.get("checkedClaims"), str) and e["checkedClaims"].strip()]
        require({(e["sourceId"], e["sourceVersionId"], e["sha256"]) for e in valid_evidence} == source_keys, "review_source_evidence")
        evidence_ids = [e["evidenceId"] for e in valid_evidence]
        require(len(evidence_ids) == len(set(evidence_ids)), "review_evidence_identity")
        checks = review.get("questionChecks")
        checks = checks if isinstance(checks, list) else []
        valid_checks = [c for c in checks if isinstance(c, dict) and c.get("decision") == "pass"
                        and c.get("evidenceId") in evidence_ids and isinstance(c.get("explanation"), str) and c["explanation"].strip()]
        expected = {digest({k: q[k] for k in ("pageId", "blockId", "questionId")})
                    for q in capture["structure"]["questions"] if q["assessmentSupport"] == "supported"}
        actual = [digest({k: q.get(k) for k in ("pageId", "blockId", "questionId")}) for q in valid_checks]
        require(set(actual) == expected and len(actual) == len(expected), "review_question_semantics")
        if manifest.get('schema') == 'learning-content-snapshot/2':
            if question_evidence is None:
                reasons.append('question_evidence_required')
            else:
                from .question_evidence import review_reasons
                reasons.extend(review_reasons(review, question_evidence))
        return reasons

    def _review_reasons(self, review, manifest, capture, sources):
        evidence = read_json(self._file(self._snapshot_path(manifest['snapshotId']), 'questions.json')) if manifest.get('schema') == 'learning-content-snapshot/2' else None
        return self.quality_review_reasons(review, manifest, capture, sources, evidence)

    @staticmethod
    def _verify_questions(manifest, content, read):
        from .question_evidence import blocks, verify
        from .question_preparation import need
        need(manifest['schema'] in ('learning-content-snapshot/1', 'learning-content-snapshot/2'), 'snapshot_version')
        controlled = any(value[0] is not None for value in blocks(content).values()) or bool(
            content['book'].get('metadata', {}).get('learning_question_controlled'))
        if manifest['schema'] == 'learning-content-snapshot/2':
            need(controlled and 'questions.json' in manifest['files'], 'question_evidence_required')
            evidence = read('questions.json')
            need(digest(evidence) == manifest.get('questionEvidenceDigest'), 'question_evidence_digest')
            verify(evidence, content, activity_id=manifest['activityId'])
            return evidence
        need(not controlled and 'questions.json' not in manifest['files'] and
             'questionEvidenceDigest' not in manifest, 'question_version_downgrade')
        return None

    def record_baseline_review(self, activity_id, snapshot_id, review_id, review):
        review = object_value(review, "review")
        if review.get("reviewId") != review_id:
            raise DeliveryError("review_id", "reviewId 与审查文件不一致")
        semantic = {"activityId": activity_id, "snapshotId": snapshot_id, "scope": self.scope,
                    "review": review, "rule": RULE, "build": self.build}
        with self.store.lock(self.scope):
            directory, request, result = self._operation("reviews", review_id, semantic)
            if result:
                self.load_snapshot(snapshot_id)
                return result
            manifest = self.load_snapshot(snapshot_id)
            snapshot = self._snapshot_path(snapshot_id)
            capture, sources = read_json(snapshot / "capture.json"), read_json(snapshot / "sources.json")
            reasons = self._review_reasons(review, manifest, capture, sources)
            if manifest["activityId"] != activity_id:
                reasons.append("snapshot_activity")
            if manifest["captureStatus"] != "stable_complete":
                reasons.append("capture_incomplete")
            if capture["structure"]["blocking"] or capture["structure"]["supportedChoiceCount"] < 1:
                reasons.append("structural_gate")
            if sources["status"] != "complete":
                reasons.append("sources_incomplete")
            check = None
            try:
                check = self._check(activity_id, snapshot_id, directory / "a" / uuid.uuid4().hex[:16])
                if not check["contentConsistent"] or check["sourceAvailability"] != "complete":
                    reasons.append("current_not_consistent")
            except DeliveryError as exc:
                reasons.append(exc.code)
            binding_path = self._binding_path(activity_id)
            if binding_path.exists():
                binding = read_json(binding_path)
                if binding.get("scope") != self.scope or binding.get("snapshotId") != snapshot_id or binding.get("identity") != manifest["identity"]:
                    reasons.append("baseline_already_bound")
            if not reasons:
                if not binding_path.exists():
                    atomic(binding_path, canonical({"schema": "learning-baseline-binding/1", "activityId": activity_id,
                           "bookId": manifest["bookId"], "scope": self.scope, "snapshotId": snapshot_id,
                           "identity": manifest["identity"], "reviewId": review_id, "reviewDigest": digest(review),
                           "boundAt": now(), "capturedAt": capture["capturedAt"], "purpose": capture["purpose"],
                           "assurance": "cooperative", "submissionContent": "unknown"}), immutable=True)
                self.fault("binding")
            existing_binding = read_json(binding_path) if binding_path.exists() else None
            actually_bound = bool(existing_binding and existing_binding.get("snapshotId") == snapshot_id
                                  and existing_binding.get("identity") == manifest["identity"] and existing_binding.get("scope") == self.scope)
            return self._result(directory, request, "review-baseline", "succeeded" if not reasons else "partial",
                                activityRef=activity_id, snapshotId=snapshot_id, decision=review.get("decision"),
                                qualityReviewAssurance="author_judgment", baselineBound=actually_bound, gatePassed=not reasons,
                                gateReasons=sorted(set(reasons)), currentCheck=check,
                                binding="baseline_consistent" if not reasons else "unknown",
                                assurance="cooperative", submissionContent="unknown")
