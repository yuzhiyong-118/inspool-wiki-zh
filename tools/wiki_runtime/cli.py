"""Wiki 候选采集与检查入口；这些命令不会应用正式变更。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "wiki_runtime"

from .contracts import (VERSION, ContractError, bytes_digest, candidate_digest,
                        canonical_json, digest, resolve_path, validate)


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, data):
    Path(path).write_bytes(canonical_json(data) + b"\n")


def _run_directory(root, run_dir):
    """运行产物不可进入知识、原件、代码或控制文件区。"""
    root, run_dir = Path(root).resolve(strict=True), Path(run_dir).resolve()
    if run_dir == root or root.is_relative_to(run_dir):
        raise ContractError("运行目录不能覆盖或包含库根")
    if run_dir.is_relative_to(root):
        rel = run_dir.relative_to(root)
        if not rel.parts or rel.parts[0] != ".wiki-runtime":
            raise ContractError("库内运行目录必须位于 .wiki-runtime")
    return root, run_dir


def prepare(root, candidate, payload_root, run_dir, *, operation_type, allowed_paths,
            task="校验候选修改"):
    """冻结候选和全部读取前提；返回 manifest，不签发授权。"""
    from .candidate import CandidateView
    validate("candidate", candidate)
    root, run_dir = _run_directory(root, run_dir)
    if run_dir.exists():
        raise ContractError("运行目录已存在，拒绝覆盖；请使用新的目录")
    payload_root = Path(payload_root).resolve(strict=True)
    if payload_root == run_dir or payload_root.is_relative_to(run_dir):
        raise ContractError("输入候选区不能位于待创建运行目录")
    view = CandidateView(root, candidate, payload_root)
    list(view.iter_paths())  # 将候选验证依赖的目录清单和全部文件前提冻结。
    snapshot = view.dependency_snapshot()
    mapping = Path(__file__).parent / "contracts/rules.json"
    manifest = {
        "contract_version": VERSION, "operation_id": candidate["operation_id"],
        "operation_type": operation_type, "task": task, "input_refs": [],
        "allowed_paths": list(allowed_paths), "rules_path": "AGENTS.md",
        "rules_digest": bytes_digest((root / "AGENTS.md").read_bytes()),
        "mapping_digest": bytes_digest(mapping.read_bytes()),
        "validator_version": "gates-1.0", "review_prompt_version": "none",
        "dependencies_digest": digest(snapshot), "candidate_digest": candidate_digest(candidate),
        "round": 1, "required_gates": ["G0", "G1", "G2"], "authorization_refs": [],
    }
    validate("manifest", manifest)
    # 先验证所有内容，再创建独占目录；检查后修改 payload 也不能影响本轮记录。
    payloads = {}
    for change in candidate["changes"]:
        if "payload_path" in change:
            data = resolve_path(payload_root, change["payload_path"]).read_bytes()
            if bytes_digest(data) != change["sha256"]:
                raise ContractError("候选载荷哈希不匹配")
            payloads[change["payload_path"]] = data
    view.verify_dependencies(snapshot)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "payload").mkdir()
    for name, data in payloads.items():
        target = resolve_path(run_dir / "payload", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _write(run_dir / "candidate.json", candidate)
    _write(run_dir / "dependencies.json", snapshot)
    _write(run_dir / "manifest.json", manifest)
    _write(run_dir / "location.json", {"root": str(root)})
    return manifest


def check(run_dir):
    """重新读取冻结记录并运行确定性检查；报告只供诊断，不是 apply 凭据。"""
    from .candidate import CandidateView
    from .gates import run_gates
    run_dir = Path(run_dir).resolve(strict=True)
    root, _ = _run_directory(_load(run_dir / "location.json")["root"], run_dir)
    candidate, manifest = _load(run_dir / "candidate.json"), _load(run_dir / "manifest.json")
    snapshot = _load(run_dir / "dependencies.json")
    validate("dependency_snapshot", snapshot)
    view = CandidateView(root, candidate, run_dir / "payload")
    list(view.iter_paths())
    # 防止 prepare/check 之间新增、删去未在旧文件清单中的页面。
    if digest(view.dependency_snapshot()) != digest(snapshot):
        raise ContractError("库快照已变化，需重新 prepare，不能沿用通过结果")
    reports = run_gates(manifest, candidate, snapshot, view)
    result = {"stage": "deterministic_check", "reports": reports,
              "passed": bool(reports) and all(r["result"] == "pass" for r in reports),
              "applied": False, "authorization": "none"}
    _write(run_dir / "check-result.json", result)
    return result


def main(argv=None):
    actual = sys.argv[1:] if argv is None else list(argv)
    if actual and actual[0] == 'host':
        from .host.cli import main as host_main
        return host_main(actual[1:])
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser('host', help='独立受限工具入口：模型、owner 批准与正式执行')
    capture = sub.add_parser("capture", help="从本地 MD、HTML 或 PDF 生成候选资料包")
    capture.add_argument("input")
    capture.add_argument("--root", required=True)
    capture.add_argument("--candidate-root", required=True)
    capture.add_argument("--package", required=True)
    capture.add_argument("--adapter")
    capture.add_argument("--origin")
    pre = sub.add_parser("prepare", help="冻结检查输入；不写正式库")
    pre.add_argument("--root", required=True)
    pre.add_argument("--candidate", required=True)
    pre.add_argument("--payload-root", required=True)
    pre.add_argument("--run-dir", required=True)
    pre.add_argument("--operation-type", required=True)
    pre.add_argument("--allow", action="append", default=[])
    pre.add_argument("--task", default="校验候选修改")
    chk = sub.add_parser("check", help="验证冻结候选；不应用")
    chk.add_argument("run_dir")
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            from .capture import capture as capture_input
            package, package_root = capture_input(
                args.input, args.candidate_root, args.package, vault_root=args.root,
                adapter_id=args.adapter, origin=args.origin)
            result = {"package_root": str(package_root), "package": package}
            code = 0 if package["quality"]["status"] == "complete" else 1
        elif args.command == "prepare":
            result = prepare(args.root, _load(args.candidate), args.payload_root, args.run_dir,
                             operation_type=args.operation_type, allowed_paths=args.allow, task=args.task)
            code = 0
        else:
            result = check(args.run_dir)
            code = 0 if result["passed"] else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (ValueError, OSError, KeyError, TypeError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc), "applied": False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
