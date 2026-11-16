"""W1 固定路线导航与私有机械准备；不签发授权，不执行正式副作用。"""
from __future__ import annotations

from pathlib import Path

from tools.learning_book.evidence_store import atomic
from ..contracts import bytes_digest, canonical_json, digest, validate_path
from ..isolation.gateway import _check_chain
from .cli import _load
from .knowledge import prepare_knowledge, verify_knowledge
from .preparation import _root, draft_learning_brief, inspect_context, verify_context
from .preview import preview_wiki_changes
from .projection import build_learning_projection


ROUTES = {
    "learning": ("inspect-context", "draft-brief", "prepare-knowledge", "build-learning-projection"),
    "knowledge": ("inspect-context", "prepare-knowledge", "preview-wiki-changes"),
    "knowledge_and_learning": ("inspect-context", "draft-brief", "prepare-knowledge",
                               "build-learning-projection", "preview-wiki-changes"),
}
REQUIRED_INPUTS = {
    "inspect-context": {"contextRequest"},
    "draft-brief": {"briefRequest"},
    "prepare-knowledge": {"knowledgeRequest"},
    "build-learning-projection": {"projectionRequest"},
    "preview-wiki-changes": {"previewRequest", "candidate"},
}
OPTIONAL_INPUTS = {
    "previousContext", "knowledgeReview", "previousKnowledge", "previousProjection",
    "recognition", "projectionReview",
}
ROOTS = {
    "inspect-context": {"wiki", "source"},
    "build-learning-projection": {"projection", "recognition"},
    "preview-wiki-changes": {"payload"},
}
ORDER_FIELDS = {"schema", "route", "stages", "roots", "inputs", "prepare", "baselineScope",
                "unknownOperations"}


class OperationError(ValueError):
    def __init__(self, code, message, *, findings=None):
        self.code = code
        self.findings = findings or []
        super().__init__(message)


def _need(condition, code, message="工作单或依赖无效", *, findings=None):
    if not condition:
        raise OperationError(code, message, findings=findings)


def _input(order, key):
    value = order["inputs"].get(key)
    if value is None:
        return None
    _need(type(value) is str and value, "input_reference", "输入引用必须是相对路径")
    validate_path(value)
    return _load(order["_orderPath"].parent / value)


def _load_order(path):
    path = Path(path).absolute()
    order = _load(path)
    _need(type(order) is dict and set(order) == ORDER_FIELDS, "order_schema")
    _need(order["schema"] == "learning-operation-work-order/1", "order_schema")
    _need(order["route"] in ROUTES, "route_unknown")
    sequence = ROUTES[order["route"]]
    stages = order["stages"]
    _need(type(stages) is list and 1 <= len(stages) <= len(sequence)
          and stages == list(sequence[:len(stages)]), "route_stage_mismatch",
          "阶段必须是当前路线的固定前缀")
    _need(type(order["unknownOperations"]) is list
          and all(type(item) is str and item for item in order["unknownOperations"])
          and len(set(order["unknownOperations"])) == len(order["unknownOperations"]),
          "unknown_operations")
    required_roots = set().union(*(ROOTS.get(stage, set()) for stage in stages))
    _need(type(order["roots"]) is dict and set(order["roots"]) == required_roots, "order_roots")
    required_inputs = set().union(*(REQUIRED_INPUTS.get(stage, set()) for stage in stages))
    allowed_inputs = required_inputs | OPTIONAL_INPUTS
    _need(type(order["inputs"]) is dict and set(order["inputs"]) == allowed_inputs
          and all(order["inputs"].get(key) is not None for key in required_inputs),
          "input_missing", "缺少当前阶段所需输入引用")
    _need(type(order["prepare"]) is str and order["prepare"], "prepare_reference")
    validate_path(order["prepare"])
    _need(order["baselineScope"] in ("whole_root", "knowledge_content"), "baseline_scope")
    order = dict(order, _orderPath=path)
    order["_roots"] = {key: _root(path.parent / value) for key, value in order["roots"].items()}
    order["_inputs"] = {key: _input(order, key) for key in allowed_inputs}
    order["_orderDigest"] = bytes_digest(path.read_bytes())
    order["_inputDigest"] = digest({"order": {k: v for k, v in order.items() if not k.startswith("_")},
                                   "inputs": order["_inputs"]})
    return order


def _work_root(order, value, *, create):
    root = Path(value).absolute()
    probe = root
    while not probe.exists():
        probe = probe.parent
    _check_chain(probe)
    _need(not root.exists() or root.is_dir(), "work_root_invalid")
    for other in [order["_orderPath"].parent, *order["_roots"].values()]:
        _need(root != other and root not in other.parents and other not in root.parents,
              "work_root_overlap", "私有工作根不得与输入根或正式库重叠")
    if create:
        root.mkdir(parents=True, exist_ok=True)
        _check_chain(root)
    return root


def _status(order, work_root):
    missing = []
    for stage in order["stages"]:
        for key in REQUIRED_INPUTS.get(stage, set()):
            if order["_inputs"].get(key) is None:
                missing.append(key)
    next_actions = ["reconcile_original_identity_without_reposting"] if order["unknownOperations"] else [
        "prepare_next_with_expected_digests"]
    return {
        "operation": "inspect-task", "status": "ready", "route": order["route"],
        "capabilities": list(ROUTES[order["route"]]), "selectedStages": order["stages"],
        "minimumInputs": sorted(set().union(*(REQUIRED_INPUTS.get(stage, set()) for stage in order["stages"]))),
        "missingInputs": missing, "unknownOperations": order["unknownOperations"],
        "orderSha256": order["_orderDigest"], "inputsSha256": order["_inputDigest"],
        "workRoot": str(work_root), "runtimeTaskRequired": False,
        "formalWriteAuthorized": False, "coursePublishAuthorized": False,
        "nextActions": next_actions,
        "stableErrors": ["order_schema", "order_digest", "input_digest", "input_missing",
                         "route_stage_mismatch", "work_root_overlap", "artifact_conflict",
                         "dependency_stale", "review_required", "unknown_operation_reconcile"],
    }


def inspect_task(order_path, work_root, expected_order_sha256=None, expected_inputs_sha256=None):
    order = _load_order(order_path)
    if expected_order_sha256 is not None:
        _need(order["_orderDigest"] == expected_order_sha256, "order_digest", "工作单摘要与预期不符")
    if expected_inputs_sha256 is not None:
        _need(order["_inputDigest"] == expected_inputs_sha256, "input_digest", "JSON 输入摘要与预期不符")
    root = _work_root(order, work_root, create=False)
    return _status(order, root)


def _template(route, stages):
    sequence = ROUTES[route]
    selected = list(sequence[:stages])
    roots = {key: "../" + key for stage in selected for key in ROOTS.get(stage, set())}
    inputs = {key: None for key in OPTIONAL_INPUTS}
    for stage in selected:
        for key in REQUIRED_INPUTS.get(stage, set()):
            inputs[key] = key + ".json"
    return {
        "schema": "learning-operation-work-order/1", "route": route, "stages": selected,
        "roots": roots, "inputs": inputs, "prepare": "prepare.json",
        "baselineScope": "knowledge_content", "unknownOperations": [],
    }


def describe_input(route, stage_count=None):
    _need(route in ROUTES, "route_unknown")
    count = len(ROUTES[route]) if stage_count is None else stage_count
    _need(type(count) is int and 1 <= count <= len(ROUTES[route]), "route_stage_mismatch")
    order = _template(route, count)
    schemas = {
        "contextRequest": {"schema": "knowledge-context-request/1"},
        "briefRequest": {"schema": None, "fields": ["briefId", "version", "goals", "included",
            "excluded", "pacing", "prerequisites", "userIntent"]},
        "knowledgeRequest": {"schema": "knowledge-preparation-request/1"},
        "projectionRequest": {"schema": "learning-projection-request/1"},
        "previewRequest": {"schema": "wiki-preview-request/1"},
        "candidate": {"contract_version": "1.0", "fields": ["operation_id", "changes"]},
    }
    required = sorted(set().union(*(REQUIRED_INPUTS.get(stage, set()) for stage in order["stages"])))
    return {
        "operation": "describe-input", "status": "ready", "route": route,
        "workOrder": order,
        "inputTemplates": {key: {**schemas[key], "locator": order["inputs"].get(key),
                                  "operatorMustSupplyActualSemantics": True} for key in required},
        "usage": ["将 workOrder 保存为私有输入目录中的 order.json 并填入实际根及输入引用",
                  "按各 schema 提供真实来源、目标、主张、审阅和 payload；占位引用不构成语义输入",
                  "先运行 inspect-task 取得两个实际摘要，再把摘要显式传给 prepare-next"],
        "formalWriteAuthorized": False, "coursePublishAuthorized": False,
    }


def _execute(stage, order, values):
    roots, inputs = order["_roots"], order["_inputs"]
    common = {"wiki_root": roots["wiki"], "source_root": roots["source"]}
    if stage == "inspect-context":
        return inspect_context(roots["wiki"], roots["source"], inputs["contextRequest"],
                               previous=inputs["previousContext"])
    if stage == "draft-brief":
        return draft_learning_brief(values["inspect-context"], inputs["briefRequest"], **common)
    if stage == "prepare-knowledge":
        return prepare_knowledge(values["inspect-context"], inputs["knowledgeRequest"], **common,
                                 review=inputs["knowledgeReview"], previous=inputs["previousKnowledge"])
    if stage == "build-learning-projection":
        return build_learning_projection(values["inspect-context"], values["prepare-knowledge"],
            values["draft-brief"]["brief"], inputs["projectionRequest"], **common,
            projection_root=roots["projection"], recognition_root=roots["recognition"],
            prepare_path=order["prepare"], recognition=inputs["recognition"],
            review=inputs["projectionReview"], previous=inputs["previousProjection"])
    if stage == "preview-wiki-changes":
        return preview_wiki_changes(values["inspect-context"], values["prepare-knowledge"],
            inputs["candidate"], inputs["previewRequest"], **common, payload_root=roots["payload"],
            baseline_scope=order["baselineScope"])
    raise OperationError("route_stage_mismatch", "未知机械阶段")


def _verify_reuse(stage, order, values, artifact):
    if stage == "inspect-context":
        current = verify_context(artifact, order["_roots"]["wiki"], order["_roots"]["source"])
        _need(current["result"] == "ready_for_review", "dependency_stale", "原文或 wiki 依赖已变化",
              findings=current["findings"])
        return
    current = _execute(stage, order, values)
    _need(current == artifact, "dependency_stale", "重验结果与既有产物不一致")


def _passed(stage, value):
    if stage in ("inspect-context", "draft-brief"):
        return value.get("result") == "ready_for_review"
    if stage == "prepare-knowledge":
        return value.get("knowledgeState") == "reviewed_for_scope"
    if stage == "build-learning-projection":
        return value.get("projectionState") == "reviewed_for_scope"
    return value.get("previewState") == "ready_for_semantic_review"


def _artifact(stage, order, values, work_root):
    input_keys = {
        "inspect-context": {"contextRequest", "previousContext"},
        "draft-brief": {"briefRequest"},
        "prepare-knowledge": {"knowledgeRequest", "knowledgeReview", "previousKnowledge"},
        "build-learning-projection": {"projectionRequest", "recognition", "projectionReview", "previousProjection"},
        "preview-wiki-changes": {"previewRequest", "candidate"},
    }[stage]
    root_keys = ROOTS.get(stage, {"wiki", "source"}) | {"wiki", "source"}
    semantic = {"stage": stage,
                "inputs": {key: order["_inputs"].get(key) for key in sorted(input_keys)},
                "roots": {key: str(order["_roots"][key]) for key in sorted(root_keys)},
                "prior": {key: digest(value) for key, value in values.items()}}
    if stage == "build-learning-projection":
        semantic["prepare"] = order["prepare"]
    if stage == "preview-wiki-changes":
        semantic["baselineScope"] = order["baselineScope"]
    input_digest = digest(semantic)
    directory = work_root / "artifacts" / stage / input_digest
    result_path, binding_path = directory / "result.json", directory / "binding.json"
    expected_binding = {"schema": "learning-operation-artifact/1", "stage": stage,
                        "inputDigest": input_digest}
    if result_path.is_file():
        value = _load(result_path)
        expected_binding["artifactDigest"] = digest(value)
        if binding_path.is_file():
            _need(_load(binding_path) == expected_binding, "artifact_conflict", "产物绑定与内容不符")
        _verify_reuse(stage, order, values, value)
        if not binding_path.is_file():
            atomic(binding_path, canonical_json(expected_binding), immutable=True)
        return value, str(result_path), True
    _need(not binding_path.exists(), "artifact_conflict", "只有绑定而没有产物")
    value = _execute(stage, order, values)
    expected_binding["artifactDigest"] = digest(value)
    directory.mkdir(parents=True, exist_ok=True)
    atomic(result_path, canonical_json(value), immutable=True)
    atomic(binding_path, canonical_json(expected_binding), immutable=True)
    return value, str(result_path), False


def prepare_next(order_path, work_root, expected_order_sha256, expected_inputs_sha256):
    order = _load_order(order_path)
    _need(order["_orderDigest"] == expected_order_sha256, "order_digest", "工作单摘要与预期不符")
    _need(order["_inputDigest"] == expected_inputs_sha256, "input_digest", "JSON 输入摘要与预期不符")
    root = _work_root(order, work_root, create=False)
    if order["unknownOperations"]:
        return {"operation": "prepare-next", "status": "needs_review",
                "error": "unknown_operation_reconcile", "unknownOperations": order["unknownOperations"],
                "artifactRefs": [], "nextActions": ["reconcile_original_identity_without_reposting"],
                "formalWriteAuthorized": False, "coursePublishAuthorized": False}
    root.mkdir(parents=True, exist_ok=True)
    values, refs, reused = {}, [], []
    invocations = 0
    for stage in order["stages"]:
        try:
            value, ref, was_reused = _artifact(stage, order, values, root)
        except OperationError as exc:
            if exc.code == "dependency_stale":
                return {"operation": "prepare-next", "status": "stale", "stage": stage,
                        "error": exc.code, "findings": exc.findings, "artifactRefs": refs,
                        "nextActions": ["inspect_current_dependencies_then_create_new_review"],
                        "formalWriteAuthorized": False, "coursePublishAuthorized": False}
            raise
        invocations += 1
        values[stage] = value
        refs.append({"stage": stage, "artifactRef": ref, "reused": was_reused})
        if was_reused:
            reused.append(stage)
        if not _passed(stage, value):
            state = value.get("knowledgeState") or value.get("projectionState") or value.get("previewState") or value.get("result")
            return {"operation": "prepare-next", "status": "stale" if state == "stale" else "needs_review",
                    "stage": stage, "state": state, "error": "dependency_stale" if state == "stale" else "review_required",
                    "findings": value.get("findings", []), "reviewRequest": value.get("reviewRequest"),
                    "artifactRefs": refs, "nextActions": ["supply_scoped_review_or_evidence_then_reinspect"],
                    "observedToolInvocations": invocations, "hostToolTurns": "unknown",
                    "providerTokens": "unknown", "formalWriteAuthorized": False,
                    "coursePublishAuthorized": False, "modelCalls": 0}
    return {"operation": "prepare-next", "status": "succeeded", "route": order["route"],
            "completedStages": order["stages"], "artifactRefs": refs, "reusedStages": reused,
            "nextActions": ["use_existing_separately_authorized_entry_if_required"],
            "observedToolInvocations": invocations, "observedInputCorrections": 0,
            "hostToolTurns": "unknown", "providerTokens": "unknown",
            "contextBytesReadIncludingRecheck": values["inspect-context"]["coverage"]["bytesRead"],
            "runtimeTaskRequired": False, "formalWriteAuthorized": False,
            "coursePublishAuthorized": False, "modelCalls": 0}
