"""I3 应用操作；编排一次明确请求，不自动确认或编译课程。"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import time

from .budget import Budget, ProcessStop
from .contracts import (DeliveryError, Package, canonical, contained, digest,
                        identifier, object_value, sha256, text)
from .deeptutor import DeepTutor, Response, multipart, parse_book_result, segment
from .evidence_store import EvidenceStore, atomic


GROUNDING_LIMITS = {"maxDirectFileSources": 16, "fileExcerptCharacters": 4000, "selectedFileContextCharacters": 80000,
                   "upstreamCommit": "60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db"}


class Production:
    def __init__(self, store: EvidenceStore, backend: DeepTutor, budget: Budget | None = None,
                 *, fault=None, preparation_guard=None, question_guard=None):
        self.store, self.backend, self.budget = store, backend, budget
        self.scope = backend.scope
        self.fault = fault or (lambda _: None)
        self.preparation_guard = preparation_guard
        self.question_guard = question_guard

    def _bind_preparation(self, semantic, manifest, *, parent=None, package=None, request_id=None):
        prior = None
        if request_id and (self.store.request_dir(request_id) / 'request.json').is_file():
            prior = self.store.request(request_id)['semantic'].get('knowledgePreparation')
        inherited = (parent or {}).get('knowledgePreparation')
        if self.preparation_guard is None:
            if prior is not None:
                # 已保存结果可以重读；若仍要 POST，_dispatch 会要求重新提供 guard。
                semantic['knowledgePreparation'] = prior
                saved = self.store.request(request_id)['semantic']
                if saved.get('productionReviewRef'):
                    semantic['productionReviewRef'] = saved['productionReviewRef']
                for key in ('preparationProvenanceRef', 'preparationContinuationRef'):
                    if key in saved: semantic[key] = saved[key]
            elif inherited is not None:
                raise DeliveryError('preparation_required', '该语料或活动已接入知识准备；不得省略接线', 'conflict')
            return
        if inherited is not None and semantic['operation'] in ('confirm-proposal','confirm-spine','prepare-quiz','publish-quiz','author-block','complete-authored-book'):
            from .preparation_continuation import active_preparation
            mapping = self._mapping(semantic['activityId'])
            origin = self.store.request(mapping['productionRequestId'])
            # 旧已接线请求无归档附件时保留原边界，不臆造准备历史。
            if origin['semantic'].get('preparationProvenanceRef'):
                active = active_preparation(self.store, mapping, origin)
                inherited = active['binding']
                if active['records']:
                    semantic['preparationContinuationRef'] = {'sequence':len(active['records']),
                        'digest':active['headDigest']}
        intent = semantic.get('payload', {}).get('user_intent')
        binding, observation = self.preparation_guard.validate(manifest, intent=intent, package=package,
            expected=inherited if semantic['operation'] not in ('publish-inputs', 'create') else None,
            operation=semantic['operation'], activity_id=semantic.get('activityId'),
            scope=self.scope, payload=semantic.get('payload'), include_review=True)
        semantic['knowledgePreparation'] = binding
        from .preparation_provenance import save_provenance
        fresh, _, _, archive = self.preparation_guard.checked(include_provenance=True)
        if fresh != binding:
            raise DeliveryError('preparation_changed', '保存依据前准备内容变化', 'conflict')
        semantic['preparationProvenanceRef'] = save_provenance(self.store, archive)
        if observation is not None:
            semantic['productionReviewRef'] = {'id': observation['review']['id'],
                'requestDigest': observation['request']['requestDigest'], 'digest': digest(observation)}
        return observation

    def _preparation_before_dispatch(self, request_id, stage, path, body, content_type):
        request = self.store.request(request_id)
        semantic = request['semantic']
        if semantic.get('questionPreparation'):
            from .question_preparation import need
            need(self.question_guard is not None, 'question_preparation_required')
            current, _, _ = self.question_guard.checked(semantic['questionPreparation']['mode'])
            need(current == semantic['questionPreparation'], 'question_preparation_changed')
            need(stage == 'book' and path == semantic['path'] and body == self._book_body(semantic),
                 'question_actual_payload')
        binding = semantic.get('knowledgePreparation')
        if binding is None:
            return
        if self.preparation_guard is None:
            raise DeliveryError('preparation_required', '新增发送须重新提供知识准备接线', 'failed')
        if semantic['operation'] in ('confirm-proposal','confirm-spine','prepare-quiz','publish-quiz','author-block','complete-authored-book'):
            from .preparation_continuation import active_preparation
            mapping = self._mapping(semantic['activityId'])
            origin = self.store.request(mapping['productionRequestId'])
            if origin['semantic'].get('preparationProvenanceRef'):
                active = active_preparation(self.store, mapping, origin)
                ref = {'sequence':len(active['records']), 'digest':active['headDigest']} if active['records'] else None
                if (binding != active['binding'] or semantic.get('preparationContinuationRef') != ref
                        or (active['records'] and semantic['payload']['expected_revision'] <
                            active['records'][-1]['request']['expectedRevision'])):
                    raise DeliveryError('preparation_continuation_stale', '待发步骤不对应当前有效续接', 'failed')
        if semantic.get('preparationProvenanceRef'):
            from .preparation_provenance import load_provenance
            load_provenance(self.store, semantic['preparationProvenanceRef'], binding)
        if semantic['operation'] == 'publish-inputs':
            manifest = request['audit']['package']
        elif semantic['operation'] == 'create':
            manifest = request['audit']['package']
        else:
            origin = self.store.request(semantic['productionRequestId'])
            manifest = origin['audit']['package']
        _, observation = self.preparation_guard.validate(manifest,
            intent=semantic.get('payload', {}).get('user_intent'), expected=binding,
            operation=semantic['operation'], activity_id=semantic.get('activityId'),
            scope=self.scope, payload=semantic.get('payload'), include_review=True)
        if observation is not None:
            ref = {'id': observation['review']['id'], 'requestDigest': observation['request']['requestDigest'],
                   'digest': digest(observation)}
            if (ref != semantic.get('productionReviewRef')
                    or request['audit'].get('productionReview') != observation):
                raise DeliveryError('production_review_changed', '当前步骤审阅与冻结的请求证据不一致', 'failed')
        if stage == 'book' and (path != semantic['path'] or body != self._book_body(semantic)):
            raise DeliveryError('preparation_actual_payload', '待发请求字节与已审参数不一致', 'failed')
        if stage in ('kb-create', 'kb-upload', 'kb-reindex'):
            _, package, _ = self.preparation_guard.checked()
            if package.corpus != semantic['corpus']:
                raise DeliveryError('preparation_corpus', '实际语料与已审映射不一致', 'failed')
            prefix = '/api/knowledge-bases/' + segment('account:kb:' + semantic['kbName'])
            if stage == 'kb-upload':
                expected_body, expected_type = multipart({}, package.inputs)
                expected_path = prefix + '/upload'
            elif stage == 'kb-create':
                expected_body, expected_type = multipart({'name': semantic['kbName'], 'rag_provider': semantic['ragProvider']})
                expected_path = '/api/knowledge-bases'
            else:
                expected_body, expected_type = multipart({})
                expected_path = prefix + '/reindex'
            if (path, body, content_type) != (expected_path, expected_body, expected_type):
                raise DeliveryError('preparation_actual_payload', '实际上传请求字节与已审投影不一致', 'failed')

    def _scope(self, scope):
        if scope != self.scope:
            raise DeliveryError("scope_mismatch", "回执与当前部署配置不符", "conflict")

    def _same_kb_scope(self, scope):
        return all(scope.get(k) == self.scope.get(k) for k in
                   ("deploymentId", "ownerId", "scopeVerification", "kbScopeDigest"))

    def _request(self, request_id, semantic, audit=None):
        identifier(request_id, "requestId")
        semantic = {"operation": semantic["operation"], "scope": self.scope, **semantic}
        existing = self.store.request_dir(request_id) / "request.json"
        if not existing.exists():
            self._reserve(semantic, request_id)
        value, created = self.store.prepare(request_id, semantic, audit=audit)
        self.fault("prepared")
        return value, self.store.receipt(request_id)

    def _reserve(self, semantic, request_id):
        operation = semantic["operation"]
        if operation == "publish-inputs":
            self.store.check_versions(semantic["corpus"])
            if semantic.get('reusedFrom'):
                origin, _ = self._corpus(semantic['reusedFrom'])
                if origin['semantic']['corpus'] != semantic['corpus']:
                    raise DeliveryError('reuse_corpus', '复用引用与本次实际语料不一致', 'conflict')
                return  # 仅记录新的复用事实，不预留/创建第二个远端语料。
            identity = {k: semantic[k] for k in ("corpusId", "corpusVersionId")}
            self.store.check_reservation(operation, identity, request_id, self.scope)
        elif operation == "create":
            if self.store.mapping(semantic["activityId"]):
                raise DeliveryError("activity_exists", "活动已经绑定书，不能重新创建或换部署", "conflict")
            self.store.check_reservation(operation, {"activityId": semantic["activityId"]}, request_id, self.scope)
        else:
            for prior in self.store.requests():
                other = prior["semantic"]
                if other.get("activityId") != semantic["activityId"]:
                    continue
                receipt = self.store.receipt(prior["requestId"])
                if receipt["status"] in ("prepared", "dispatching", "uncertain"):
                    raise DeliveryError("activity_reserved", "活动仍有未确认结果的生产步骤", "conflict")
                if (other["operation"] == operation and other.get("payload", {}).get("expected_revision") ==
                        semantic["payload"]["expected_revision"] and receipt["status"] == "succeeded"):
                    raise DeliveryError("confirmation_exists", "相同 revision 的确认已经成功", "conflict")
        # 明确失败不是隐式重试许可：必须关联前次已确定无副作用的请求。
        failed_ids = set()
        for prior in self.store.requests():
            other = prior["semantic"]
            key = ("corpusId", "corpusVersionId") if operation == "publish-inputs" else ("activityId",)
            if other["operation"] != operation or any(other.get(k) != semantic.get(k) for k in key):
                continue
            if operation == "publish-inputs" and any(other["scope"][k] != self.scope[k] for k in ("deploymentId", "ownerId")):
                continue
            receipt = self.store.receipt(prior["requestId"])
            if receipt["status"] == "failed":
                # 确认新 revision 属于独立编辑，而非对旧 token 的隐式重放。
                if operation.startswith("confirm-") and other["payload"]["expected_revision"] != semantic["payload"]["expected_revision"]:
                    continue
                failed_ids.add(prior["requestId"])
        if failed_ids and semantic.get("retryOf") not in failed_ids:
            raise DeliveryError("retry_link_required", "新请求须通过 retryOf 明确关联前次失败", "conflict")

    def _result(self, request_id):
        value = self.store.receipt(request_id)
        status = value["status"]
        if value.get("coverage") == "partial" or value.get("remotePresence") == "missing":
            status = "partial" if status == "succeeded" else status
        return {"operation": value["operation"], "requestId": request_id, "status": status,
                "receiptRef": str(self.store.request_dir(request_id) / "receipt.json"),
                "activityRef": value.get("activityId"), "errors": value.get("errors", []),
                "nextAction": ("review_next_stage" if status == "succeeded" else
                               "reconcile_without_reposting" if status == "uncertain" else "inspect_receipt"),
                "bookId": value.get("bookId"), "revision": value.get("revision"),
                "corpusReceiptRef": request_id if value["operation"] == "publish-inputs" and status == "succeeded" else None,
                "artifactRef": value.get("artifactRef"), "remotePresence": value.get("remotePresence"),
                "knowledgePreparationStatus": 'integrated_operator_supplied' if
                    self.store.request(request_id)['semantic'].get('knowledgePreparation') else 'legacy_not_integrated'}

    def _save_failure(self, request_id, exc, **fields):
        status = exc.status if exc.status in ("failed", "uncertain") else "uncertain"
        self.store.save_receipt(request_id, status, errors=[{"code": exc.code, "message": exc.message}], **fields)

    def _local_uncertain(self, request, *, book_id=None):
        request_id = request["requestId"]
        exc = DeliveryError("local_persistence", "远端可能成功，但本地证据提交失败；不得重建远端对象", "uncertain")
        try:
            self._save_failure(request_id, exc, activityId=request["semantic"].get("activityId"), bookId=book_id)
        except OSError:
            pass
        return {"operation": request["semantic"]["operation"], "requestId": request_id,
                "status": "uncertain", "receiptRef": str(self.store.request_dir(request_id) / "receipt.json"),
                "activityRef": request["semantic"].get("activityId"), "bookId": book_id,
                "errors": [{"code": exc.code, "message": exc.message}],
                "nextAction": "restore_state_directory_then_reconcile_without_reposting"}

    def _dispatch(self, request_id, stage, path, body, content_type="application/json", *, kb=False,
                  readonly=False):
        saved = self.store.response(request_id, stage)
        if saved:
            meta, raw = saved
            return Response(meta["status"], raw, meta["contentType"])
        if (self.store.stage_dir(request_id, stage) / "dispatching.json").exists() or readonly:
            raise DeliveryError("write_result_unknown", "缺少完整响应，不重发该写入阶段", "uncertain")
        try:
            self._preparation_before_dispatch(request_id, stage, path, body, content_type)
        except DeliveryError as exc:
            # 此阶段尚无 dispatch 标记；前置失败不能凭 conflict 状态变成未知写入。
            # 调用者仍会保留其他已发送阶段的 partial/uncertain 事实。
            raise DeliveryError(exc.code, exc.message, 'failed') from exc
        if not self.budget or not self.budget.running:
            raise DeliveryError("budget_required", "该阶段必须在独立预算监控下发送", "failed")
        self.budget.check()
        atomic(self.store.stage_dir(request_id, stage) / "request.bin", body, immutable=True)
        self.store.dispatch(request_id, stage, {"method": "POST", "path": path,
                            "contentType": content_type, "bodySha256": sha256(body),
                            "workspaceId": None if kb else self.scope["workspaceId"]})
        self.fault("dispatching")
        response = self.backend.request("POST", path, body, content_type, kb=kb)
        self.store.save_response(request_id, stage, response.status, response.body, response.content_type,
                                 wire_sha256=response.wire_sha256, redacted=response.redacted)
        self.fault("response_saved")
        return response

    def _status(self, response: Response, operation):
        if 200 <= response.status < 300:
            return
        # 固定路由的参数校验、认证拒绝、revision 409 在 mutation 前。
        known_empty = response.status in (401, 403, 422) or (response.status == 409 and (operation.startswith("confirm-") or operation in ('prepare-quiz','publish-quiz','author-block','complete-authored-book','append-extension')))
        raise DeliveryError("http_" + str(response.status), "上游未成功响应；保留原响应证据，禁止自动重放",
                            "failed" if known_empty else "uncertain")

    @contextmanager
    def _monitor(self, request_id):
        if self.budget is None:
            raise DeliveryError("budget_required", "需要有效 --budget-context，旧 I2 额度不可沿用", "failed")
        context = self.budget.context
        blocked = self.store.root / "budgets" / (digest(context["contextId"]) + ".blocked.json")
        if blocked.exists():
            raise DeliveryError("budget_latched", "该额度上下文已停止；需核对停止事实后另行授权", "failed")
        self.store.bind_budget(context, self.scope)
        if isinstance(self.budget.stop_control, ProcessStop):
            self.budget.stop_control.bind_endpoint(self.backend.config["baseUrl"])
        position_path = self.store.root / "budgets" / (digest(context["contextId"]) + ".position.json")
        if position_path.exists():
            from .contracts import read_json
            self.budget.floor = read_json(position_path).get("countedCalls", {})
        try:
            with self.budget.watch():
                yield
        finally:
            position = self.budget.position()
            if not position.get("error") and not position.get("missingRows"):
                atomic(position_path, canonical(position))
                self.budget.floor = position["countedCalls"]
            self.store.observation(request_id, "budget", {"contextId": context["contextId"],
                    "position": position, "events": self.budget.events,
                    "stopProcess": context.get("stopProcess")})
            if self.budget.blocked.is_set():
                atomic(blocked, canonical({"contextId": context["contextId"], "events": self.budget.events}), immutable=True)

    def _finish_book(self, request, response):
        semantic = request["semantic"]
        request_id, operation = request["requestId"], semantic["operation"]
        self._status(response, operation)
        result = parse_book_result(operation, response, semantic.get("bookId"))
        if operation == 'append-extension':
            value = response.json()
            publication = value.get('publication', {})
            actual = [{key: block.get(key) for key in ('id', 'type', 'title', 'params', 'payload')}
                      for block in value.get('blocks', [])]
            if (actual != semantic['payload']['blocks']
                    or publication.get('requestId') != request_id
                    or publication.get('requestDigest') != semantic['payload']['request_digest']
                    or publication.get('extensionId') != semantic['payload']['extension_id']
                    or publication.get('bookId') != semantic['bookId']
                    or publication.get('qualityReview') != 'unreviewed' or publication.get('modelCalls') != 0):
                raise DeliveryError('extension_response_binding', '扩展响应与原请求、内容或未审身份不符', 'uncertain')
        if operation in ('author-block', 'complete-authored-book'):
            publication = response.json().get('publication', {})
            if (publication.get('requestId') != request_id
                    or publication.get('requestDigest') != semantic['payload']['request_digest']
                    or publication.get('bookId') != semantic['bookId'] or publication.get('modelCalls') != 0):
                raise DeliveryError('author_response_binding', '作者交付响应与原请求不符', 'uncertain')
            if operation == 'author-block' and response.json()['block']['payload']['body'] != semantic['payload']['body']:
                raise DeliveryError('author_response_content', '作者正文回读字节不一致', 'uncertain')
        if operation in ('prepare-quiz', 'publish-quiz') and response.json()['block']['id'] != semantic['payload']['block_id']:
            raise DeliveryError('response_block','响应题块身份不符','uncertain')
        if semantic.get('questionPreparation'):
            from .question_preparation import need, validate_binding, publication_digest
            from .question_spec import question_digest
            value = response.json(); block = value['block']; pub = value.get('publication', {})
            need(block.get('metadata', {}).get('learning_question_binding') == semantic['questionPreparation']
                 and pub.get('requestId') == request_id and pub.get('requestDigest') == semantic['payload']['request_digest']
                 and pub.get('bookId') == semantic['bookId'] and pub.get('pageId') == semantic['payload']['page_id']
                 and pub.get('blockId') == semantic['payload']['block_id'], 'question_response_binding')
            validate_binding(semantic['questionPreparation'], block['payload']['questions'])
            if operation == 'publish-quiz':
                need(pub.get('modelCalls') == 0 and [question_digest(q) for q in block['payload']['questions']] ==
                     [question_digest(q) for q in self._wire_payload(semantic)['questions']], 'question_response_content')
        if operation != "create" and result["revision"] <= semantic["payload"]["expected_revision"]:
            raise DeliveryError("revision_not_advanced", "确认响应没有推进 revision", "uncertain")
        activity_id = semantic["activityId"]
        self.fault("before_mapping")
        if operation == "create":
            self.store.map_activity(activity_id, self.scope, result["bookId"], request_id)
        else:
            self._mapping(activity_id)
        self.store.save_receipt(request_id, "succeeded", activityId=activity_id,
            productionRequestId=request_id if operation == "create" else semantic["productionRequestId"],
            previousRequestId=semantic.get("previousRequestId"), **result,
            artifactRef=str(self.store.stage_dir(request_id, 'book' if self.store.response(request_id, 'book') else 'book-reconcile') / 'response.bin'),
            effectiveContextCoverage="unknown", knownUpstreamLimits=GROUNDING_LIMITS)
        self.store.rebuild_index()
        return self._result(request_id)

    def _mapping(self, activity_id):
        mapping = self.store.mapping(activity_id)
        if not mapping:
            raise DeliveryError("activity_missing", "活动尚未绑定书", "failed")
        self._scope(mapping["scope"])
        return mapping

    def _execute_book(self, request, receipt):
        request_id, semantic = request["requestId"], request["semantic"]
        if receipt["status"] == "failed":
            return self._result(request_id)
        try:
            saved = self.store.response(request_id, "book") or (
                self.store.response(request_id, 'book-reconcile') if semantic.get('questionPreparation')
                or semantic['operation'] in ('author-block', 'complete-authored-book') else None)
            if saved:
                if receipt["status"] == "succeeded":
                    # 映射可能在派生视图维护之前损坏；恢复同一事实，绝不重绑。
                    if semantic["operation"] == "create":
                        self.store.map_activity(semantic["activityId"], self.scope, receipt["bookId"], request_id)
                    return self._result(request_id)
                return self._finish_book(request, Response(saved[0]["status"], saved[1], saved[0]["contentType"]))
            if (self.store.stage_dir(request_id, "book") / "dispatching.json").exists():
                raise DeliveryError("write_result_unknown", "发送后缺少完整响应，必须核对", "uncertain")
            if receipt["status"] == "uncertain":
                return self._result(request_id)
            # 发送前重新核对被冻结的原文／投影及远端集合。
            self.backend.verify_scope()
            if semantic["operation"] == "create":
                corpus_request, corpus_receipt = self._corpus(semantic["corpusRequestId"])
                self._validate_originals(corpus_request)
                self._verify_corpus(corpus_request, corpus_receipt["kbRef"], corpus_receipt["taskId"])
            else:
                mapping = self._mapping(semantic["activityId"])
                origin = self.store.request(mapping["productionRequestId"])
                corpus_request, corpus_receipt = self._corpus(origin["semantic"]["corpusRequestId"])
                self._validate_originals(corpus_request)
                self._verify_corpus(corpus_request, corpus_receipt["kbRef"], corpus_receipt["taskId"])
                self._verify_book_present(mapping["bookId"], semantic["payload"]["expected_revision"])
                if semantic['operation'] in ('prepare-quiz', 'publish-quiz'):
                    body=semantic['payload']
                    page=self._read_json('/api/books/'+segment(mapping['bookId'])+'/pages/'+segment(body['page_id'])).get('page')
                    if (not isinstance(page,dict) or page.get('id')!=body['page_id'] or
                            page.get('book_id')!=mapping['bookId'] or
                            len([b for b in page.get('blocks',[]) if b.get('id')==body['block_id'] and b.get('type')=='quiz'])!=1):
                        raise DeliveryError('quiz_target','目标不是已映射课程中的唯一题块','failed')
                if semantic.get('questionPreparation'):
                    self._question_capability(mapping['bookId'])
                if semantic['operation'] == 'append-extension':
                    self._extension_capability(mapping['bookId'])
                if semantic['operation'] in ('author-block', 'complete-authored-book'):
                    self._author_capability(mapping['bookId'])
                    if semantic['operation'] == 'complete-authored-book':
                        current_plan = self.author_delivery_plan(semantic['activityId'])
                        if current_plan != semantic['payload']['plan']:
                            raise DeliveryError('author_plan_stale', '整书实际内容与冻结交付计划不符', 'failed')
            with self._monitor(request_id):
                response = self._dispatch(request_id, "book", semantic["path"], self._book_body(semantic))
                self._status(response, semantic["operation"])
            return self._finish_book(request, response)
        except DeliveryError as exc:
            # 只有 pre-dispatch 可观察性失败可当明确失败；远端发出后未知必须保留。
            marker = self.store.stage_dir(request_id, "book") / "dispatching.json"
            if marker.exists() and exc.code not in ("http_401", "http_403", "http_409", "http_422"):
                exc = DeliveryError(exc.code, exc.message, "uncertain")
            elif not marker.exists() and semantic.get('questionPreparation'):
                exc = DeliveryError(exc.code, exc.message, 'failed')
            try:
                self._save_failure(request_id, exc, activityId=semantic["activityId"], bookId=semantic.get("bookId"))
            except OSError:
                return self._local_uncertain(request, book_id=semantic.get("bookId"))
            return self._result(request_id)
        except OSError:
            return self._local_uncertain(request, book_id=semantic.get("bookId"))

    def _corpus(self, request_id):
        request, receipt = self.store.request(request_id), self.store.receipt(request_id)
        if not self._same_kb_scope(request["semantic"]["scope"]):
            raise DeliveryError("corpus_scope", "corpus 的账户资源作用域与当前配置不符", "conflict")
        if request["semantic"]["operation"] != "publish-inputs" or receipt["status"] != "succeeded":
            raise DeliveryError("corpus_not_ready", "create 必须引用成功且完整的 corpus 回执", "failed")
        return request, receipt

    def _validate_originals(self, request):
        # 每次模型创建前重验原始留存。定位变更需显式刷新独立 locator 证据。
        locators = self.store.request_dir(request["requestId"]) / "locators.json"
        from .contracts import read_json
        paths = read_json(locators)
        for source in request["semantic"]["corpus"]["sources"]:
            path = Path(paths["source:" + source["sourceId"]])
            if not path.is_file() or sha256(path.read_bytes()) != source["sha256"]:
                raise DeliveryError("source_missing", "成书前原始来源缺失或被替换", "failed")

    def create_activity(self, corpus_request_id: str, request_id: str, activity_id: str,
                        intent: str, *, retry_of=None, replacement_of=None):
        identifier(activity_id, "activityId")
        text(intent, "intent")
        with self.store.lock(self.scope):
            if replacement_of is not None:
                self._mapping(replacement_of)
                if not (self.store.root / 'baselines' / (digest(replacement_of) + '.json')).exists():
                    raise DeliveryError('author_replacement_unproven', '替代关系必须引用已有首次基线的旧活动', 'conflict')
            corpus_request, corpus_receipt = self._corpus(corpus_request_id)
            manifest = corpus_request["audit"]["package"]
            corpus = corpus_request["semantic"]["corpus"]
            saved_path = self.store.request_dir(request_id) / 'request.json'
            if self.preparation_guard is None and saved_path.is_file():
                saved_request = self.store.request(request_id)
                if saved_request['semantic'].get('knowledgePreparation'):
                    manifest = saved_request['audit']['package']
            if self.preparation_guard is not None:
                _, checked_package, _ = self.preparation_guard.checked()
                if checked_package.corpus != corpus:
                    raise DeliveryError('preparation_corpus', '已审映射与所选真实语料回执不一致', 'conflict')
                manifest = checked_package.manifest
            labels = {s["sourceId"]: s["metadata"].get("title") or s["sourceId"] for s in corpus["sources"]}
            refs = [{"kind": "file", "source_id": row["remotePath"],
                     "label": labels[row["sourceId"]],
                     "metadata": {"kb_name": corpus_receipt["kbRef"], "path": row["remotePath"]}}
                    for row in corpus["inputArtifacts"]]
            payload = {"user_intent": intent, "knowledge_bases": [corpus_receipt["kbRef"]],
                       "source_refs": refs, "language": manifest["language"],
                       "fallback_language": manifest["language"], "depth": manifest["depth"]}
            semantic = {"operation": "create", "activityId": activity_id, "corpusRequestId": corpus_request_id,
                        "corpusDigest": digest(corpus), "path": "/api/books", "payload": payload,
                        "suggestedGoal": manifest["learningGoal"], "goalOverridden": intent != manifest["learningGoal"],
                        "retryOf": retry_of}
            if replacement_of is not None:
                semantic['replacementOf'] = replacement_of
            parent = corpus_request['semantic']
            protected = any(r['semantic'].get('knowledgePreparation')
                and r['semantic'].get('corpus') == corpus and self._same_kb_scope(r['semantic']['scope'])
                for r in self.store.requests())
            if protected and not parent.get('knowledgePreparation'):
                parent = {**parent, 'knowledgePreparation': {'required': True}}
            self._bind_preparation(semantic, manifest, parent=parent, request_id=request_id)
            audit = {"budgetContextId": self.budget.context["contextId"] if self.budget else None}
            if 'knowledgePreparation' in semantic:
                audit['package'] = manifest
            request, receipt = self._request(request_id, semantic, audit)
            return self._execute_book(request, receipt)

    def confirm_proposal(self, activity_id, request_id, payload, expected_revision, *, retry_of=None):
        return self._confirm("confirm-proposal", activity_id, request_id, payload, expected_revision, retry_of)

    def revalidate_preparation(self, activity_id, continuation_id, expected_revision, reason, review=None):
        from .preparation_continuation import prepare_continuation
        if self.preparation_guard is None:
            raise DeliveryError('preparation_required', '重新核验须提供已审新准备', 'conflict')
        with self.store.lock(self.scope):
            mapping = self._mapping(activity_id)
            origin = self.store.request(mapping['productionRequestId'])
            for request in self.store.requests():
                if request['semantic'].get('activityId') == activity_id and self.store.receipt(request['requestId'])['status'] in ('prepared','dispatching','uncertain'):
                    raise DeliveryError('production_unresolved', '先对账解决活动中的未决请求，再续接准备', 'conflict')
            self.backend.verify_scope()
            self._verify_book_present(mapping['bookId'], expected_revision)
            return prepare_continuation(self.store, mapping, origin, self.preparation_guard,
                                        continuation_id, expected_revision, reason, review)

    def confirm_spine(self, activity_id, request_id, payload, expected_revision, *, retry_of=None):
        return self._confirm("confirm-spine", activity_id, request_id, payload, expected_revision, retry_of)

    def prepare_quiz(self, activity_id, request_id, page_id, block_id, templates, expected_revision, *, retry_of=None):
        """向已映射课程传递预审题；完整响应可重读，未知写入不重发。"""
        if self.question_guard is not None:
            return self._produce_questions('variant', activity_id, request_id, page_id, block_id,
                expected_revision, retry_of=retry_of, templates=templates)
        if any(r['semantic'].get('activityId') == activity_id and r['semantic'].get('questionPreparation')
               for r in self.store.requests()):
            raise DeliveryError('question_preparation_required', '受控活动不能降级到旧模板入口', 'conflict')
        identifier(page_id, 'pageId'); identifier(block_id, 'blockId')
        fields={'question_id','topic','question_type','difficulty','reference_question','reference_answer'}
        if (not isinstance(templates,list) or not 1<=len(templates)<=8 or
                any(not isinstance(t,dict) or set(t)!=fields or
                    any(not isinstance(v,str) or not v.strip() or len(v)>32768 for v in t.values()) or
                    t['question_type']!='choice' for t in templates) or
                len({t['question_id'] for t in templates})!=len(templates)):
            raise DeliveryError('prepared_templates','预审题必须为 1～8 个字段完整、ID 唯一的选择题模板')
        if type(expected_revision) is not int or expected_revision<1:
            raise DeliveryError('revision','必须显式给出正整数 expected_revision')
        with self.store.lock(self.scope):
            mapping=self._mapping(activity_id)
            body={'book_id':mapping['bookId'],'page_id':page_id,'block_id':block_id,
                'expected_revision':expected_revision,'params_override':{'num_questions':len(templates),
                    'question_type':'choice','prepared_templates':templates}}
            semantic={'operation':'prepare-quiz','activityId':activity_id,'bookId':mapping['bookId'],
                'productionRequestId':mapping['productionRequestId'],'payload':body,
                'path':'/api/books/regenerate-block','retryOf':retry_of}
            original = self.store.request(mapping['productionRequestId'])
            observation = None
            if original['semantic'].get('knowledgePreparation') or self.preparation_guard is not None:
                observation = self._bind_preparation(semantic, original['audit'].get('package', {}),
                    parent=original['semantic'], request_id=request_id)
            audit = {'budgetContextId':self.budget.context['contextId'] if self.budget else None}
            if observation is not None: audit['productionReview'] = observation
            request,receipt=self._request(request_id,semantic,audit)
            return self._execute_book(request,receipt)

    def _wire_payload(self, semantic):
        from .contracts import decode_json
        value = decode_json(canonical(semantic['payload']))
        if semantic.get('questionOptionOrders'):
            for question, order in zip(value['questions'], semantic['questionOptionOrders']):
                question['options'] = {key: question['options'][key] for key in order}
        return value

    def _book_body(self, semantic):
        if semantic.get('questionPreparation'):
            from .question_preparation import ordered_bytes
            return ordered_bytes(self._wire_payload(semantic))
        return canonical(semantic['payload'])

    def _question_capability(self, book_id):
        from .question_preparation import need
        build = self.backend.config.get('questionProductionBuild', {})
        need(build.get('capability') == 'learning-question-publication/1', 'question_build_required')
        value = self._read_json('/api/books/' + segment(book_id) + '/question-capability')
        need(value.get('schema') == build['capability'] and value.get('bookId') == book_id and
             value.get('implementationSha256') == build.get('moduleSha256') and
             value.get('singleWorker') is True, 'question_capability')

    def publish_quiz(self, activity_id, request_id, page_id, block_id, expected_revision, *, retry_of=None):
        return self._produce_questions('authored', activity_id, request_id, page_id, block_id,
                                       expected_revision, retry_of=retry_of)

    def _produce_questions(self, mode, activity_id, request_id, page_id, block_id, expected_revision,
                           *, retry_of=None, templates=None):
        from .question_preparation import need, publication_digest
        need(self.question_guard is not None, 'question_preparation_required')
        identifier(page_id, 'pageId'); identifier(block_id, 'blockId'); identifier(request_id, 'requestId')
        import re
        need(re.fullmatch(r'[A-Za-z0-9_-]{1,180}', request_id) is not None, 'question_request_id')
        need(type(expected_revision) is int and expected_revision >= 1, 'question_revision')
        with self.store.lock(self.scope):
            mapping = self._mapping(activity_id)
            need((self.store.request_dir(request_id) / 'request.json').exists() or
                 not (self.store.root / 'baselines' / (digest(activity_id) + '.json')).exists(),
                 'question_baseline_accepted')
            binding, archive, contents = self.question_guard.freeze(self.store, mode)
            origin = self.store.request(mapping['productionRequestId'])
            corpus, _ = self._corpus(origin['semantic']['corpusRequestId'])
            allowed_sources = {(s['sourceId'], s['sourceVersionId'], s['sha256'])
                               for s in corpus['semantic']['corpus']['sources']}
            need(all((s['sourceId'], s['sourceVersionId'], s['sha256']) in allowed_sources
                     for s in binding['sources']), 'question_corpus_sources')
            if templates is not None: need(templates == contents, 'question_templates_changed')
            body = {'book_id': mapping['bookId'], 'page_id': page_id, 'block_id': block_id,
                    'expected_revision': expected_revision, 'request_id': request_id, 'question_binding': binding}
            if mode == 'authored':
                body['questions'] = contents
            else:
                body['params_override'] = {'num_questions': len(contents), 'question_type': 'choice',
                                           'prepared_templates': contents}
            body['request_digest'] = publication_digest(body)
            semantic = {'operation': 'publish-quiz' if mode == 'authored' else 'prepare-quiz',
                'activityId': activity_id, 'bookId': mapping['bookId'],
                'productionRequestId': mapping['productionRequestId'], 'payload': body,
                'path': '/api/books/publish-quiz' if mode == 'authored' else '/api/books/regenerate-block',
                'retryOf': retry_of, 'questionPreparation': binding}
            if mode == 'authored': semantic['questionOptionOrders'] = [list(q['options']) for q in contents]
            original = self.store.request(mapping['productionRequestId'])
            observation = self._bind_preparation(semantic, original['audit'].get('package', {}),
                parent=original['semantic'], request_id=request_id)
            audit = {'budgetContextId': self.budget.context['contextId'] if self.budget else None}
            if observation is not None: audit['productionReview'] = observation
            request, receipt = self._request(request_id, semantic, audit)
            return self._execute_book(request, receipt)

    def _extension_capability(self, book_id):
        from .extensions import CAPABILITY, need
        build = self.backend.config.get('extensionBuild', {})
        need(build.get('capability') == CAPABILITY, 'extension_build_required')
        value = self._read_json('/api/books/' + segment(book_id) + '/extension-capability')
        need(value.get('schema') == CAPABILITY and value.get('bookId') == book_id
             and value.get('implementationSha256') == build.get('moduleSha256')
             and value.get('singleWorker') is True and value.get('chainVersion') == 1,
             'extension_capability')

    def append_extension(self, activity_id, request_id, page_id, extension_id, blocks, expected_revision,
                         *, position=None, retry_of=None):
        from .extensions import binding, need, request_digest, validate_blocks
        need(self.preparation_guard is not None and self.question_guard is not None,
             'extension_preparation_required')
        need(type(expected_revision) is int and expected_revision >= 1, 'extension_revision')
        candidates = validate_blocks(blocks)
        with self.store.lock(self.scope):
            mapping = self._mapping(activity_id)
            original = self.store.request(mapping['productionRequestId'])
            corpus, _ = self._corpus(original['semantic']['corpusRequestId'])
            budget_id = original['audit'].get('budgetContextId')
            if budget_id is not None:
                need(self.budget and self.budget.context['contextId'] == budget_id, 'extension_budget_context')
            payload = {'book_id': mapping['bookId'], 'page_id': page_id, 'operation': 'append_blocks',
                       'position': position, 'expected_revision': expected_revision, 'request_id': request_id,
                       'extension_id': extension_id, 'blocks': candidates}
            _, question_archive, _ = self.question_guard.checked('authored')
            payload['extension_binding'] = binding(activity_id, 'append_blocks',
                question_archive, corpus['semantic']['corpus'])
            payload['request_digest'] = request_digest(payload)
            semantic = {'operation': 'append-extension', 'activityId': activity_id, 'bookId': mapping['bookId'],
                        'productionRequestId': mapping['productionRequestId'], 'payload': payload,
                        'path': '/api/books/append-extension', 'retryOf': retry_of,
                        'extensionPreparation': payload['extension_binding']}
            observation = self._bind_preparation(semantic, original['audit'].get('package', {}),
                parent=original['semantic'], request_id=request_id)
            audit = {'budgetContextId': self.budget.context['contextId'] if self.budget else None}
            if observation is not None:
                audit['productionReview'] = observation
            request, receipt = self._request(request_id, semantic, audit)
            return self._execute_book(request, receipt)

    def _author_capability(self, book_id):
        from .authored_delivery import CAPABILITY, need
        build = self.backend.config.get('authoredDeliveryBuild', {})
        need(build.get('capability') == CAPABILITY, 'author_build_required')
        value = self._read_json('/api/books/' + segment(book_id) + '/author-delivery-capability')
        need(value.get('schema') == CAPABILITY and value.get('bookId') == book_id
             and value.get('implementationSha256') == build.get('moduleSha256')
             and value.get('singleWorker') is True, 'author_capability')

    def author_delivery_plan(self, activity_id):
        mapping = self._mapping(activity_id)
        content = self._read_json('/api/books/' + segment(mapping['bookId']) + '/content')
        from .authored_delivery import content_plan
        return content_plan(content, mapping['bookId'])

    def _author_parts(self, activity_id, request_id):
        from .authored_delivery import need
        mapping = self._mapping(activity_id)
        need(self.preparation_guard is not None, 'author_preparation_required')
        saved = self.store.request_dir(request_id) / 'request.json'
        need(saved.exists() or not (self.store.root / 'baselines' / (digest(activity_id) + '.json')).exists(),
             'author_baseline_accepted')
        original = self.store.request(mapping['productionRequestId'])
        corpus, _ = self._corpus(original['semantic']['corpusRequestId'])
        budget_id = original['audit'].get('budgetContextId')
        if budget_id is not None:
            need(self.budget and self.budget.context['contextId'] == budget_id, 'author_budget_context')
        return mapping, original, corpus

    def author_block(self, activity_id, request_id, page_id, operation, body, expected_revision,
                     *, block_id=None, title=None, position=None, retry_of=None):
        from .authored_delivery import binding, need, request_digest
        need(operation in ('insert', 'update') and type(expected_revision) is int and expected_revision >= 1,
             'author_operation')
        with self.store.lock(self.scope):
            mapping, original, corpus = self._author_parts(activity_id, request_id)
            payload = {'book_id': mapping['bookId'], 'page_id': page_id, 'operation': operation,
                       'block_id': block_id, 'title': title, 'body': body, 'position': position,
                       'expected_revision': expected_revision, 'request_id': request_id}
            payload['author_binding'] = binding(activity_id, operation,
                self.preparation_guard.checked()[0], corpus['semantic']['corpus'], body=body)
            payload['request_digest'] = request_digest(payload)
            semantic = {'operation': 'author-block', 'activityId': activity_id, 'bookId': mapping['bookId'],
                        'productionRequestId': mapping['productionRequestId'], 'payload': payload,
                        'path': '/api/books/author-block', 'retryOf': retry_of}
            observation = self._bind_preparation(semantic, original['audit'].get('package', {}),
                parent=original['semantic'], request_id=request_id)
            audit = {'budgetContextId': self.budget.context['contextId'] if self.budget else None}
            if observation is not None:
                audit['productionReview'] = observation
            request, receipt = self._request(request_id, semantic, audit)
            return self._execute_book(request, receipt)

    def complete_authored_book(self, activity_id, request_id, plan, expected_revision, *, retry_of=None):
        from .authored_delivery import binding, need, request_digest
        need(type(expected_revision) is int and expected_revision >= 1, 'author_revision')
        with self.store.lock(self.scope):
            mapping, original, corpus = self._author_parts(activity_id, request_id)
            if not (self.store.request_dir(request_id) / 'request.json').exists():
                need(plan == self.author_delivery_plan(activity_id), 'author_plan_stale')
            payload = {'book_id': mapping['bookId'], 'expected_revision': expected_revision,
                       'request_id': request_id, 'plan': plan}
            payload['author_binding'] = binding(activity_id, 'complete', self.preparation_guard.checked()[0],
                                                corpus['semantic']['corpus'], plan=plan)
            payload['request_digest'] = request_digest(payload)
            semantic = {'operation': 'complete-authored-book', 'activityId': activity_id,
                        'bookId': mapping['bookId'], 'productionRequestId': mapping['productionRequestId'],
                        'payload': payload, 'path': '/api/books/complete-authored-book', 'retryOf': retry_of}
            observation = self._bind_preparation(semantic, original['audit'].get('package', {}),
                parent=original['semantic'], request_id=request_id)
            audit = {'budgetContextId': self.budget.context['contextId'] if self.budget else None}
            if observation is not None:
                audit['productionReview'] = observation
            request, receipt = self._request(request_id, semantic, audit)
            return self._execute_book(request, receipt)

    def _confirm(self, operation, activity_id, request_id, payload, expected_revision, retry_of):
        if type(expected_revision) is not int or expected_revision < 1:
            raise DeliveryError("revision", "必须显式给出正整数 expected_revision")
        if payload is not None:
            object_value(payload, "payload")
        with self.store.lock(self.scope):
            mapping = self._mapping(activity_id)
            original = self.store.request(mapping["productionRequestId"])
            budget_id = original["audit"].get("budgetContextId")
            if self.budget and self.budget.context["contextId"] != budget_id:
                raise DeliveryError("budget_context_changed", "确认步骤必须共用创建时的累计额度上下文")
            body = {"book_id": mapping["bookId"], "expected_revision": expected_revision,
                    "proposal" if operation == "confirm-proposal" else "spine": payload}
            if operation == "confirm-spine":
                body["auto_compile"] = False
            previous = mapping["productionRequestId"]
            history = [r for r in self.store.requests() if r["semantic"].get("activityId") == activity_id
                       and self.store.receipt(r["requestId"])["status"] == "succeeded"]
            if history:
                previous = max(history, key=lambda r: self.store.receipt(r["requestId"]).get("revision", 0))["requestId"]
            semantic = {"operation": operation, "activityId": activity_id, "bookId": mapping["bookId"],
                        "productionRequestId": mapping["productionRequestId"], "previousRequestId": previous,
                        "path": "/api/books/" + operation, "payload": body, "retryOf": retry_of}
            observation = None
            if original['semantic'].get('knowledgePreparation') or self.preparation_guard is not None:
                observation = self._bind_preparation(semantic, original['audit'].get('package', {}),
                    parent=original['semantic'], request_id=request_id)
            # previousRequestId 是恢复关联而非本次有效输入；同 ID 重放沿用原关联。
            if (self.store.request_dir(request_id) / "request.json").exists():
                semantic["previousRequestId"] = self.store.request(request_id)["semantic"].get("previousRequestId")
            audit = {"budgetContextId": budget_id}
            if observation is not None: audit['productionReview'] = observation
            request, receipt = self._request(request_id, semantic, audit)
            return self._execute_book(request, receipt)

    def _read_json(self, path, *, kb=False):
        response = self.backend.read(path, kb=kb)
        if response.status != 200:
            raise DeliveryError("observe_http_" + str(response.status), "无法完成无生成核对", "uncertain")
        return response.json()

    def _verify_book_present(self, book_id, revision=None):
        value = self._read_json("/api/books")
        books = value.get("books")
        if not isinstance(books, list):
            raise DeliveryError("book_list", "上游书列表结构缺失", "uncertain")
        matches = [book for book in books if isinstance(book, dict) and book.get("id") == book_id]
        if len(matches) != 1:
            raise DeliveryError("book_missing", "已映射的书在当前作用域不可见；禁止按标题重绑", "uncertain")
        if revision is not None and matches[0].get("revision") != revision:
            raise DeliveryError("revision_stale", "当前 revision 与明确确认的版本不一致", "failed")
        return matches[0]

    def _verify_corpus(self, request, kb_ref, task_id, *, observe=True):
        corpus = request["semantic"]["corpus"]
        prefix = "/api/knowledge-bases/" + segment(kb_ref)
        listing = self._read_json(prefix + "/files", kb=True)
        files = listing.get("files")
        if not isinstance(files, list) or any(not isinstance(f, dict) for f in files):
            raise DeliveryError("file_list", "KB 文件列表不完整", "uncertain")
        names = [f.get("name") for f in files if f.get("type") != "folder"]
        expected = {row["remotePath"]: row["sha256"] for row in corpus["inputArtifacts"]}
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise DeliveryError("corpus_drift", "远端成员与冻结语料集合不符", "uncertain")
        for name, content_hash in expected.items():
            response = self.backend.read(prefix + "/files/" + segment(name), kb=True)
            if response.status != 200 or sha256(response.body) != content_hash:
                raise DeliveryError("remote_bytes", "远端原始字节与上传投影 hash 不符", "uncertain")
        run = self._read_json(prefix + "/indexing-run", kb=True).get("run")
        if observe:
            self.store.observation(request["requestId"], "corpus", {"kbRef": kb_ref, "files": listing, "run": run})
        if not isinstance(run, dict) or run.get("task_id") != task_id or not task_id:
            raise DeliveryError("index_task", "索引运行不属于已取得回执的上传任务", "uncertain")
        if run.get("state") in ("queued", "running", "pending"):
            raise DeliveryError("index_pending", "索引仍在运行", "uncertain")
        documents = run.get("documents")
        if (run.get("state") != "completed" or not run.get("usable_version")
                or not isinstance(documents, dict) or set(documents) != set(expected)
                or any(not isinstance(documents[n], dict) or documents[n].get("status") != "completed"
                       or documents[n].get("source_hash") != h for n, h in expected.items())):
            raise DeliveryError("index_incomplete", "索引失败、成员 hash 不符或缺少可用版本", "uncertain")
        return run

    def publish_learning_inputs(self, package: Package, request_id: str, *, retry_of=None):
        if contained(self.store.root, package.root) or contained(package.root, self.store.root):
            raise DeliveryError("root_overlap", "资料包根与项目回执目录必须分离")
        with self.store.lock(self.scope):
            semantic = {"operation": "publish-inputs", "corpus": package.corpus,
                        "corpusId": package.corpus["corpusId"], "corpusVersionId": package.corpus["corpusVersionId"],
                        "kbName": "lb-" + digest({k: package.corpus[k] for k in ("corpusId", "corpusVersionId")})[:32],
                        "ragProvider": self.backend.config["ragProvider"], "retryOf": retry_of}
            self._bind_preparation(semantic, package.manifest, package=package, request_id=request_id)
            # 同语料不同包／学习目标可复用，不让目标进入 corpus digest。
            self.store.check_versions(package.corpus)
            if self.preparation_guard is None and any(r['semantic'].get('knowledgePreparation')
                    and r['semantic'].get('corpus') == package.corpus
                    and self._same_kb_scope(r['semantic']['scope']) for r in self.store.requests()):
                raise DeliveryError('preparation_required', '该语料已有受控绑定；不得改走未接线复用', 'conflict')
            existing = self.store.request_dir(request_id) / 'request.json'
            if existing.is_file() and self.store.request(request_id)['semantic'].get('reusedFrom'):
                origin = self.store.request(request_id)['semantic']['reusedFrom']
                return self._reuse_guarded_corpus(semantic, package, request_id, origin)
            for prior in self.store.requests():
                other = prior["semantic"]
                if (other["operation"] == "publish-inputs" and self._same_kb_scope(other["scope"])
                        and other["corpus"] == package.corpus and prior["requestId"] != request_id
                        and self.store.receipt(prior["requestId"])["status"] == "succeeded"):
                    if other.get('knowledgePreparation') and self.preparation_guard is None:
                        raise DeliveryError('preparation_required', '复用受控语料不能绕过知识准备', 'conflict')
                    # 新 requestId 未被占用才能返回复用指针；不能掩盖已存在的同 ID 冲突。
                    if not (self.store.request_dir(request_id) / "request.json").exists():
                        if self.preparation_guard is not None:
                            return self._reuse_guarded_corpus(semantic, package, request_id, prior['requestId'])
                        receipt = self.store.receipt(prior["requestId"])
                        self.backend.verify_scope()
                        self._verify_corpus(prior, receipt["kbRef"], receipt["taskId"])
                        self._refresh_locators(prior["requestId"], package)
                        return {**self._result(prior["requestId"]), "requestedRequestId": request_id,
                                "reusedCorpus": True}
            request, receipt = self._request(request_id, semantic, {"package": package.manifest})
            self._refresh_locators(request_id, package)
            for name, data in package.inputs.items():
                atomic(self.store.request_dir(request_id) / "inputs" / name, data, immutable=True)
            if receipt["status"] == "succeeded":
                self.backend.verify_scope()
                self._verify_corpus(request, receipt["kbRef"], receipt["taskId"])
                return self._result(request_id)
            if receipt["status"] in ("failed", "uncertain"):
                return self._result(request_id)
            try:
                self.backend.verify_scope()
                with self._monitor(request_id):
                    result = self._publish(request, package.inputs)
                return result
            except DeliveryError as exc:
                # 任一 KB 阶段已有副作用时，不发布可用于 create 的成功 corpus。
                if any((self.store.stage_dir(request_id, s) / "dispatching.json").exists()
                       for s in ("kb-create", "kb-upload")):
                    exc = DeliveryError(exc.code, exc.message, "uncertain")
                try:
                    self._save_failure(request_id, exc, coverage="partial", kbName=semantic["kbName"])
                except OSError:
                    return self._local_uncertain(request)
                return self._result(request_id)
            except OSError:
                return self._local_uncertain(request)

    def _reuse_guarded_corpus(self, semantic, package, request_id, origin_id):
        origin, receipt = self._corpus(origin_id)
        if origin['semantic']['corpus'] != package.corpus:
            raise DeliveryError('reuse_corpus', '复用记录与实际语料不一致', 'conflict')
        if not semantic.get('knowledgePreparation'):
            raise DeliveryError('preparation_required', '复用受控语料须保留知识准备绑定', 'conflict')
        self.backend.verify_scope()
        self._verify_corpus(origin, receipt['kbRef'], receipt['taskId'])
        semantic['reusedFrom'] = origin_id
        request, current = self._request(request_id, semantic, {'package': package.manifest})
        self._refresh_locators(request_id, package)
        # 复用远端语料也须拥有自己的冻结输入，I4/I5按当前回执读取。
        for name, data in package.inputs.items():
            atomic(self.store.request_dir(request_id) / 'inputs' / name, data, immutable=True)
        # 新本地回执只证明复用了原 KB，不虚构上传响应，也不改写旧回执。
        if current['status'] != 'succeeded':
            self.store.save_receipt(request_id, 'succeeded', corpus=package.corpus,
                corpusDigest=digest(package.corpus), kbRef=receipt['kbRef'],
                kbOwnerId=receipt['kbOwnerId'], taskId=receipt['taskId'],
                usableVersion=receipt['usableVersion'], coverage='complete', reusedFrom=origin_id)
        self.store.rebuild_index()
        return {**self._result(request_id), 'reusedCorpus': True, 'reusedFrom': origin_id}

    def _refresh_locators(self, request_id, package):
        self.store.observation(request_id, "locators", {"locators": package.locators})
        atomic(self.store.request_dir(request_id) / "locators.json", canonical(package.locators))

    def _publish(self, request, inputs, *, readonly=False):
        request_id, semantic = request["requestId"], request["semantic"]
        body, mime = multipart({"name": semantic["kbName"], "rag_provider": semantic["ragProvider"]})
        if not self.store.response(request_id, "kb-create") and not readonly:
            # 发现同名 KB 只能停；稳定名称不构成该请求拥有它的证明。
            listing = self.backend.request("GET", "/api/knowledge-bases", kb=True)
            if listing.status != 200:
                raise DeliveryError("kb_inventory", "无法核对资源库是否存在同名 KB", "failed")
            bases = listing.value()
            if not isinstance(bases, list):
                raise DeliveryError("kb_inventory", "资源库列表包装不符合固定契约", "failed")
            if any(isinstance(k, dict) and k.get("name") == semantic["kbName"] for k in bases):
                raise DeliveryError("kb_preexists", "远端已有同名 KB，不能认领或覆盖", "uncertain")
        created = self._dispatch(request_id, "kb-create", "/api/knowledge-bases", body, mime, kb=True, readonly=readonly)
        self._status(created, "publish-inputs")
        value = created.json()
        kb_ref = value.get("id")
        if value.get("name") != semantic["kbName"] or kb_ref != "account:kb:" + semantic["kbName"]:
            raise DeliveryError("kb_identity", "KB 响应未证明预期账户资源身份", "uncertain")
        prefix = "/api/knowledge-bases/" + segment(kb_ref)
        if not self.store.response(request_id, "kb-upload") and not readonly:
            current = self._read_json(prefix + "/files", kb=True)
            if current.get("files") != []:
                raise DeliveryError("kb_not_empty", "新语料 KB 不是空集合，停止覆盖式上传", "uncertain")
            ready = self._read_json(prefix + "/indexing-readiness", kb=True)
            self.store.observation(request_id, "readiness", ready)
            # readiness 的 ready 仅代表配置；成功仍以原始字节及 indexing-run 为准。
            if ready.get("ready") is not True:
                raise DeliveryError("index_not_configured", "后端解析／索引配置未就绪", "uncertain")
        body, mime = multipart({}, inputs)
        uploaded = self._dispatch(request_id, "kb-upload", prefix + "/upload", body, mime, kb=True, readonly=readonly)
        self._status(uploaded, "publish-inputs")
        value = uploaded.json()
        task_id = value.get("task_id")
        if not isinstance(task_id, str) or not task_id or set(value.get("files", [])) != set(inputs):
            raise DeliveryError("upload_identity", "上传响应缺少任务身份或完整成员", "uncertain")
        upload_task_id = task_id
        recovered = self.store.response(request_id, "kb-reindex")
        if recovered:
            response = Response(recovered[0]["status"], recovered[1], recovered[0]["contentType"])
            self._status(response, "publish-inputs")
            task_id = response.json().get("task_id")
            if not isinstance(task_id, str) or not task_id:
                raise DeliveryError("index_recovery_identity", "重建响应缺少任务身份", "uncertain")
        deadline = time.monotonic() + float(self.backend.config.get("indexWaitSeconds", 30))
        while True:
            try:
                run = self._verify_corpus(request, kb_ref, task_id)
                break
            except DeliveryError as exc:
                if readonly or exc.code not in ("index_pending", "index_task") or time.monotonic() >= deadline:
                    raise
                self.budget.check()
                self.budget.blocked.wait(min(self.budget.interval, 1))
        self.store.save_receipt(request_id, "succeeded", corpus=semantic["corpus"],
            corpusDigest=digest(semantic["corpus"]), kbRef=kb_ref, kbOwnerId=self.backend.config["kbOwnerId"],
            taskId=task_id, uploadTaskId=upload_task_id, usableVersion=run["usable_version"], coverage="complete",
            effectiveContextCoverage="unknown", knownUpstreamLimits=GROUNDING_LIMITS,
            exceedsKnownFileExcerptLimit=any(a["utf8CharacterCount"] > GROUNDING_LIMITS["fileExcerptCharacters"]
                                            for a in semantic["corpus"]["inputArtifacts"]))
        self.store.rebuild_index()
        return self._result(request_id)

    def recover_inputs(self, request_id):
        """显式恢复已保存上传，重建原 KB 的索引，保留首次任务与每次响应。"""
        with self.store.lock(self.scope):
            request, receipt = self.store.request(request_id), self.store.receipt(request_id)
            semantic = request["semantic"]
            self._scope(semantic["scope"])
            if semantic["operation"] != "publish-inputs":
                raise DeliveryError("recovery_operation", "仅支持已有语料发布请求")
            if receipt["status"] == "succeeded":
                return self._result(request_id)
            created = self.store.response(request_id, "kb-create")
            uploaded = self.store.response(request_id, "kb-upload")
            if receipt["status"] != "uncertain" or not created or not uploaded:
                raise DeliveryError("recovery_unproven", "须先保存完整的建库和上传响应，再显式恢复")
            creation = Response(created[0]["status"], created[1], created[0]["contentType"])
            upload = Response(uploaded[0]["status"], uploaded[1], uploaded[0]["contentType"])
            self._status(creation, "publish-inputs")
            self._status(upload, "publish-inputs")
            kb_ref = creation.json().get("id")
            if kb_ref != "account:kb:" + semantic["kbName"]:
                raise DeliveryError("recovery_kb", "建库响应身份不符")
            inputs = {row["remotePath"]: b"" for row in semantic["corpus"]["inputArtifacts"]}
            if set(upload.json().get("files", [])) != set(inputs):
                raise DeliveryError("recovery_members", "上传响应的成员不符")
            self.backend.verify_scope()
            if not self.store.response(request_id, "kb-reindex"):
                try:
                    self._verify_corpus(request, kb_ref, upload.json().get("task_id"))
                    return self._publish(request, inputs, readonly=True)
                except DeliveryError as exc:
                    if exc.code not in ("index_task", "index_incomplete"):
                        raise
                current = self._read_json("/api/knowledge-bases/" + segment(kb_ref) + "/indexing-run", kb=True).get("run")
                if not isinstance(current, dict) or current.get("state") not in (
                        "completed", "failed", "partial", "cancelled", "interrupted"):
                    raise DeliveryError("index_running", "原索引尚未终止，不能并发重建")
                self.store.observation(request_id, "index-recovery", {"run": current, "uploadTaskId": upload.json().get("task_id")})
            try:
                with self._monitor(request_id):
                    body, mime = multipart({})
                    self._dispatch(request_id, "kb-reindex",
                                   "/api/knowledge-bases/" + segment(kb_ref) + "/reindex", body, mime, kb=True)
                    return self._publish(request, inputs)
            except DeliveryError as exc:
                self._save_failure(request_id, DeliveryError(exc.code, exc.message, "uncertain"))
                return self._result(request_id)

    def inspect_receipt(self, request_id, *, rebuild_index=False):
        # 不需要后端可用或预算，不发 HTTP。
        if rebuild_index:
            with self.store.lock(self.scope):
                self.store.rebuild_index()
        semantic = self.store.request(request_id)["semantic"]
        if semantic["operation"] == "publish-inputs" and self._same_kb_scope(semantic["scope"]):
            return self._result(request_id)
        self._scope(semantic["scope"])
        return self._result(request_id)

    def reconcile_request(self, request_id, *, candidate_book_id=None):
        with self.store.lock(self.scope):
            request, receipt = self.store.request(request_id), self.store.receipt(request_id)
            semantic = request["semantic"]
            operation = semantic["operation"]
            if operation != "publish-inputs" or not self._same_kb_scope(semantic["scope"]):
                self._scope(semantic["scope"])
            if receipt["status"] == "failed":
                return self._result(request_id)
            if receipt["status"] == "prepared" and not any(
                    (self.store.stage_dir(request_id, stage) / "dispatching.json").exists()
                    for stage in ("book", "kb-create", "kb-upload")):
                return {**self._result(request_id), "nextAction": "resume_original_request_with_valid_budget"}
            try:
                if operation != "publish-inputs":
                    saved = self.store.response(request_id, "book") or (
                        self.store.response(request_id, 'book-reconcile') if semantic.get('questionPreparation')
                        or operation in ('author-block', 'complete-authored-book') else None)
                    if operation in ('author-block', 'complete-authored-book') and not saved:
                        self.backend.verify_scope()
                        response = self.backend.read('/api/books/author-deliveries/' + segment(request_id)
                                                     + '?book_id=' + segment(semantic['bookId']))
                        if response.status == 200:
                            self.store.save_response(request_id, 'book-reconcile', response.status, response.body,
                                response.content_type, wire_sha256=response.wire_sha256, redacted=response.redacted)
                            self._finish_book(request, response)
                            self.store.observation(request_id, 'author-reconciled', response.json())
                            return self._result(request_id)
                        raise DeliveryError('author_unproven', '未取得原作者交付凭据；不重发正文或完成操作', 'uncertain')
                    if semantic.get('questionPreparation') and not saved:
                        self.backend.verify_scope()
                        response = self.backend.read('/api/books/quiz-publications/' + segment(request_id) +
                                                     '?book_id=' + segment(semantic['bookId']))
                        if response.status == 200:
                            # GET proves the exact original request. Never issue another POST.
                            self.store.save_response(request_id, 'book-reconcile', response.status, response.body,
                                response.content_type, wire_sha256=response.wire_sha256, redacted=response.redacted)
                            self._finish_book(request, response)
                            self.store.observation(request_id, 'question-reconciled', response.json())
                            return self._result(request_id)
                        raise DeliveryError('question_unproven', '未取得精确题目提交凭据；不重新生成或发布', 'uncertain')
                    if saved and receipt["status"] != "succeeded":
                        # 原始完整响应可恢复，无须再 POST 或 GET Book。
                        self._finish_book(request, Response(saved[0]["status"], saved[1], saved[0]["contentType"]))
                        receipt = self.store.receipt(request_id)
                    self.backend.verify_scope()
                    book_id = receipt.get("bookId") or semantic.get("bookId")
                    if candidate_book_id and book_id and candidate_book_id != book_id:
                        raise DeliveryError("candidate_mismatch", "候选书与已有稳定映射不同", "uncertain")
                    if book_id:
                        try:
                            book = self._verify_book_present(book_id)
                        except DeliveryError as exc:
                            if exc.code != "book_missing":
                                raise
                            self.store.observation(request_id, "remote-missing", {"bookId": book_id})
                            fields = {k: v for k, v in receipt.items() if k not in
                                      ("schemaVersion", "receiptId", "requestId", "requestDigest", "operation", "scope", "status", "recordedAt")}
                            fields["remotePresence"] = "missing"
                            self.store.save_receipt(request_id, receipt["status"], **fields)
                            return self._result(request_id)
                        self.store.observation(request_id, "book-list", {"book": book})
                    elif candidate_book_id:
                        book = self._verify_book_present(candidate_book_id)
                        self.store.observation(request_id, "unproven-candidate", {"book": book, "claimable": False,
                             "reason": "公开列表不能证明精确输入或生产请求归属"})
                    if receipt["status"] == "dispatching":
                        self.store.save_receipt(request_id, "uncertain", activityId=semantic["activityId"], bookId=book_id,
                            errors=[{"code": "unproven_remote", "message": "仅观察，无原请求成功证明，不认领候选"}])
                else:
                    self.backend.verify_scope()
                    stages = ("kb-create", "kb-upload", "kb-reindex")
                    if (receipt["status"] == "uncertain" and not any(
                            (self.store.stage_dir(request_id, stage) / "dispatching.json").exists()
                            or self.store.response(request_id, stage) for stage in stages)):
                        listing = self.backend.request("GET", "/api/knowledge-bases", kb=True)
                        if listing.status != 200 or not isinstance(listing.value(), list):
                            raise DeliveryError("kb_inventory", "无法核对资源库是否存在同名 KB", "uncertain")
                        if not any(isinstance(item, dict) and item.get("name") == semantic["kbName"]
                                   for item in listing.value()):
                            self._save_failure(request_id, DeliveryError("no_remote_write",
                                "无任何发送标记或完整响应，且远端不存在目标 KB；确认本次未产生远程写入", "failed"))
                            return self._result(request_id)
                    inputs = {row["remotePath"]: b"" for row in semantic["corpus"]["inputArtifacts"]}
                    # readonly 禁止缺响应的子阶段续发，inputs 只用于成员比对，不上传。
                    self._publish(request, inputs, readonly=True)
            except DeliveryError as exc:
                if receipt["status"] == "succeeded":
                    self.store.observation(request_id, "reconcile-error", {"code": exc.code})
                    return {**self._result(request_id), "status": "partial", "errors": [{"code": exc.code}],
                            "nextAction": "inspect_remote_without_rebinding"}
                self._save_failure(request_id, DeliveryError(exc.code, exc.message, "uncertain"),
                                   activityId=semantic.get("activityId"), bookId=receipt.get("bookId") or semantic.get("bookId"))
            return self._result(request_id)
