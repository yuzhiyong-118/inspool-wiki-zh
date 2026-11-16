"""I3 的 JSON 契约、身份与只读资料校验（仅标准库）。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


class DeliveryError(Exception):
    def __init__(self, code: str, message: str, status: str = "invalid"):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha256(canonical(value))


def decode_json(data: str | bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))


def read_json(path: Path | str) -> Any:
    try:
        return decode_json(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise DeliveryError("json_invalid", "无法读取有效 JSON 文件") from exc


def text(value: Any, name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > 4000:
        raise DeliveryError("field_invalid", f"字段 {name} 必须是有效字符串")
    return value


def identifier(value: Any, name: str) -> str:
    value = text(value, name)
    if len(value) > 180 or any(ord(c) < 32 for c in value):
        raise DeliveryError("id_invalid", f"字段 {name} 不是有效稳定 ID")
    return value


def content_hash(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise DeliveryError("hash_invalid", "sha256 必须是 64 位小写十六进制")
    return value


def object_value(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise DeliveryError("field_invalid", f"字段 {name} 必须是对象")
    return value


def contained(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def safe_state_root(path: Path | str) -> Path:
    root = Path(path).resolve()
    repo = Path(__file__).resolve().parents[2]
    for part in ("raw", "wiki", "references", ".learning-validation", ".git", ".agents", ".codex"):
        target = repo / part
        if contained(root, target) or contained(target, root):
            raise DeliveryError("state_root", "回执目录不得覆盖正式库、参考源码或既有验证目录")
    return root


@dataclass(frozen=True)
class Package:
    manifest: dict
    corpus: dict
    inputs: dict[str, bytes]
    locators: dict
    root: Path


def validate_package(path: Path | str, package_root: Path | str | None = None) -> Package:
    path = Path(path).resolve(strict=True)
    root = Path(package_root).resolve(strict=True) if package_root else path.parent
    if not contained(path, root):
        raise DeliveryError("package_escape", "prepare.json 不在指定资料包根目录")
    value = object_value(read_json(path), "prepare")
    if type(value.get("schemaVersion")) is not int or value.get("schemaVersion") != 1 or value.get("preparationDecision") != "learn":
        raise DeliveryError("package_version", "只接受 schemaVersion=1、preparationDecision=learn")
    normalized = {k: identifier(value.get(k), k) for k in
                  ("packageId", "corpusId", "corpusVersionId")}
    normalized.update(schemaVersion=1, preparationDecision="learn",
                      learningGoal=text(value.get("learningGoal"), "learningGoal"),
                      language=text(value.get("language", "zh"), "language"),
                      depth=text(value.get("depth", "brief"), "depth"))
    if normalized["depth"] not in ("brief", "standard", "deep"):
        raise DeliveryError("depth", "depth 必须是 brief/standard/deep")
    sources, artifacts = value.get("sources"), value.get("inputArtifacts")
    if not isinstance(sources, list) or not sources or not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 16:
        raise DeliveryError("members", "本期必须有来源和 1 至 16 个输入提取物；更多资料须分包")
    source_keys, source_ids, artifact_ids, locators, inputs = set(), set(), set(), {}, {}
    normalized["sources"], normalized["inputArtifacts"] = [], []
    for source in sources:
        source = object_value(source, "source")
        row = {k: identifier(source.get(k), k) for k in ("sourceId", "sourceVersionId")}
        row["sha256"] = content_hash(source.get("sha256"))
        key = (row["sourceId"], row["sourceVersionId"])
        if key in source_keys or row["sourceId"] in source_ids:
            raise DeliveryError("duplicate_source", "同一资料包的来源身份重复")
        source_keys.add(key)
        source_ids.add(row["sourceId"])
        locator = Path(text(source.get("path"), "source.path"))
        original = (root / locator).resolve(strict=True)
        if not original.is_file() or sha256(original.read_bytes()) != row["sha256"]:
            raise DeliveryError("source_hash", "缺少原始文件或原文字节 hash 不符")
        metadata = object_value(source.get("metadata"), "source.metadata")
        if set(metadata) - {"title", "author", "externalUrl", "license", "capturedAt"}:
            raise DeliveryError("source_metadata", "来源元数据仅支持 title/author/externalUrl/license/capturedAt")
        for name, item in metadata.items():
            text(item, "metadata." + name, empty=True)
        row["metadata"] = metadata
        canonical(metadata)
        locators["source:" + row["sourceId"]] = str(original)
        normalized["sources"].append(row)
    for artifact in artifacts:
        artifact = object_value(artifact, "inputArtifact")
        row = {k: identifier(artifact.get(k), k) for k in
               ("inputArtifactId", "sourceId", "sourceVersionId")}
        if (row["sourceId"], row["sourceVersionId"]) not in source_keys:
            raise DeliveryError("source_reference", "提取物必须对应本包原文版本")
        if row["inputArtifactId"] in artifact_ids:
            raise DeliveryError("duplicate_artifact", "inputArtifactId 重复")
        artifact_ids.add(row["inputArtifactId"])
        row["sha256"] = content_hash(artifact.get("sha256"))
        row["mediaType"] = artifact.get("mediaType")
        if row["mediaType"] not in ("text/markdown", "text/plain"):
            raise DeliveryError("media_type", "首期只接受 UTF-8 Markdown 或纯文本")
        row["extraction"] = object_value(artifact.get("extraction"), "extraction")
        if set(row["extraction"]) - {"method", "version"}:
            raise DeliveryError("extraction_fields", "extraction 仅支持 method/version")
        text(row["extraction"].get("method"), "extraction.method")
        text(row["extraction"].get("version"), "extraction.version")
        row["coverage"] = object_value(artifact.get("coverage"), "coverage")
        if set(row["coverage"]) - {"status", "truncated", "note"}:
            raise DeliveryError("coverage_fields", "coverage 仅支持 status/truncated/note")
        if "note" in row["coverage"]:
            text(row["coverage"]["note"], "coverage.note", empty=True)
        if row["coverage"].get("status") != "complete" or row["coverage"].get("truncated") is not False:
            raise DeliveryError("partial_input", "不完整或未声明完整的提取物不能自动创建书", "partial")
        locator = Path(text(artifact.get("path"), "inputArtifact.path"))
        if locator.is_absolute() or ".." in locator.parts:
            raise DeliveryError("input_escape", "输入投影必须使用包内相对路径")
        target = (root / locator).resolve(strict=True)
        if not contained(target, root) or not target.is_file():
            raise DeliveryError("input_escape", "输入路径或符号链接越过资料包根")
        data = target.read_bytes()
        if not data or sha256(data) != row["sha256"]:
            raise DeliveryError("input_hash", "提取物为空或字节 hash 不符")
        try:
            row["utf8CharacterCount"] = len(data.decode("utf-8"))
        except UnicodeError as exc:
            raise DeliveryError("input_encoding", "提取物不是 UTF-8") from exc
        suffix = ".md" if row["mediaType"] == "text/markdown" else ".txt"
        row["remotePath"] = digest(row["inputArtifactId"])[:24] + suffix
        inputs[row["remotePath"]] = data  # 已固定的校验字节，上传时不再开文件。
        locators["artifact:" + row["inputArtifactId"]] = str(target)
        normalized["inputArtifacts"].append(row)
    used = {(a["sourceId"], a["sourceVersionId"]) for a in normalized["inputArtifacts"]}
    if used != source_keys:
        raise DeliveryError("unused_source", "包内每个来源必须有明确上传投影")
    corpus = {k: normalized[k] for k in ("corpusId", "corpusVersionId", "sources", "inputArtifacts")}
    return Package(normalized, corpus, inputs, locators, root)


def load_deployment(path: Path | str) -> dict:
    from urllib.parse import urlsplit
    config = object_value(read_json(path), "deployment")
    if set(config) - {"deploymentId", "ownerId", "workspaceId", "scopeVerification", "baseUrl", "kbOwnerId",
                      "ragProvider", "tokenEnv", "timeoutSeconds", "indexWaitSeconds", "contentReadBuild",
                      "learningStateReadBuild", "questionProductionBuild", "authoredDeliveryBuild", "extensionBuild"}:
        raise DeliveryError("deployment_fields", "部署配置包含不支持的字段；凭据只能通过 tokenEnv 引用")
    if "contentReadBuild" in config:
        build = object_value(config["contentReadBuild"], "contentReadBuild")
        if set(build) != {"baseCommit", "rendererCommit", "patchSha256", "wheelSha256"}:
            raise DeliveryError("content_build_fields", "contentReadBuild 只接受固定构建标识，不接受凭据")
        for name in ("baseCommit", "rendererCommit"):
            if not isinstance(build[name], str) or not re.fullmatch(r"[0-9a-f]{40}", build[name]):
                raise DeliveryError("content_build_commit", "构建提交必须是 40 位 commit hash")
        for name in ("patchSha256", "wheelSha256"):
            content_hash(build[name])
    if "learningStateReadBuild" in config:
        build = object_value(config["learningStateReadBuild"], "learningStateReadBuild")
        if set(build) != {"baseCommit", "i4PatchSha256", "patchSha256", "wheelSha256"}:
            raise DeliveryError("learning_state_build_fields", "learningStateReadBuild 仅接受独立只读能力的构建标识")
        if not isinstance(build["baseCommit"], str) or not re.fullmatch(r"[0-9a-f]{40}", build["baseCommit"]):
            raise DeliveryError("learning_state_build_commit", "构建提交必须是 40 位 commit hash")
        for name in ("i4PatchSha256", "patchSha256", "wheelSha256"):
            content_hash(build[name])
    if 'questionProductionBuild' in config:
        build = object_value(config['questionProductionBuild'], 'questionProductionBuild')
        if set(build) != {'capability', 'baseCommit', 'patchSha256', 'moduleSha256'} or build['capability'] != 'learning-question-publication/1':
            raise DeliveryError('question_build', '题目发行能力标识不完整')
        if build['baseCommit'] != '60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db':
            raise DeliveryError('question_build', '题目固定源码不符')
        for key in ('patchSha256', 'moduleSha256'): content_hash(build[key])
    if 'authoredDeliveryBuild' in config:
        build = object_value(config['authoredDeliveryBuild'], 'authoredDeliveryBuild')
        if set(build) != {'capability', 'baseCommit', 'patchSha256', 'moduleSha256'} or build['capability'] != 'learning-authored-delivery/1':
            raise DeliveryError('author_build', '作者交付发行能力标识不完整')
        if build['baseCommit'] != '60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db':
            raise DeliveryError('author_build', '作者交付固定源码不符')
        for key in ('patchSha256', 'moduleSha256'): content_hash(build[key])
    if 'extensionBuild' in config:
        build = object_value(config['extensionBuild'], 'extensionBuild')
        if set(build) != {'capability', 'baseCommit', 'patchSha256', 'moduleSha256'} or build['capability'] != 'learning-controlled-extension/1':
            raise DeliveryError('extension_build', '学习扩展发行能力标识不完整')
        if build['baseCommit'] != '60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db':
            raise DeliveryError('extension_build', '学习扩展固定源码不符')
        for key in ('patchSha256', 'moduleSha256'): content_hash(build[key])
    wait = config.get("indexWaitSeconds", 30)
    if not isinstance(wait, (int, float)) or not 0 <= wait <= 3600:
        raise DeliveryError("index_wait", "indexWaitSeconds 必须是 [0,3600] 内的数值")
    scope = {k: identifier(config.get(k), k) for k in ("deploymentId", "ownerId")}
    scope["workspaceId"] = text(config.get("workspaceId"), "workspaceId", empty=True)
    if any(ord(c) < 32 or ord(c) > 126 for c in scope["workspaceId"]):
        raise DeliveryError("workspace_id", "workspaceId 必须是有效 ASCII 标识或显式空字符串")
    verification = config.get("scopeVerification")
    if verification not in ("configured_single_user", "authenticated"):
        raise DeliveryError("scope_verification", "必须显式配置本地单用户绑定或认证绑定")
    url = text(config.get("baseUrl"), "baseUrl").rstrip("/")
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise DeliveryError("backend_url", "首期仅支持显式 loopback HTTP 服务根地址")
    scope["scopeVerification"] = verification
    kb_owner = identifier(config.get("kbOwnerId"), "kbOwnerId")
    if kb_owner != scope["ownerId"]:
        raise DeliveryError("kb_owner", "首期仅支持当前 owner 管理的专用 KB")
    public = {"baseUrl": url, "scope": scope, "kbOwnerId": kb_owner,
              "ragProvider": text(config.get("ragProvider"), "ragProvider")}
    scope["kbScopeDigest"] = digest({"baseUrl": url, "deploymentId": scope["deploymentId"],
        "ownerId": scope["ownerId"], "kbOwnerId": kb_owner, "scopeVerification": verification,
        "ragProvider": public["ragProvider"]})
    # KB 在 account 资源库；不继承 Book workspace。
    scope["configurationDigest"] = digest(public)
    config.update(baseUrl=url, scope=scope, kbOwnerId=kb_owner)
    if verification == "authenticated" and not config.get("tokenEnv"):
        raise DeliveryError("auth_config", "认证部署必须通过 tokenEnv 引用凭据")
    if "tokenEnv" in config and (not isinstance(config["tokenEnv"], str) or
                                not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", config["tokenEnv"])):
        raise DeliveryError("auth_config", "tokenEnv 必须是环境变量名称，不能直接填写凭据")
    return config
