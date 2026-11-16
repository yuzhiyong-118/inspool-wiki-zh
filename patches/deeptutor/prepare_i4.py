"""从固定源码准备隔离构建树；不改原始源码或已安装包。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess

BASE = "60fb3bdfddb30b7740c7ce3bd9b28d908f2af6db"
FILES = {
    "deeptutor/api/routers/book.py": "84bcf22c7eb6eacd8ac40142e0e44908e365a6881f04dd394b0e340a85521ade",
    "deeptutor/book/storage.py": "cb9d9e79fd6e8ee75bf368a908bd7443b576fc23597de755f86f2c7094a95847",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--without-patch", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() or source == output or source in output.parents or output in source.parents:
        raise SystemExit("output 必须是独立且尚不存在的目录")
    for name, expected in FILES.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise SystemExit("固定源码 hash 不符: " + name)
    output.mkdir(parents=True)
    # 仅复制 Python 模块构建所需源码，不复制运行数据、前端依赖和凭据。
    for name in ("deeptutor", "deeptutor_cli", "scripts"):
        shutil.copytree(source / name, output / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", ".env"))
    for name in ("build_support.py", "build_metadata.py", "pyproject.toml", "README.md", "LICENSE", "AGENTS.md"):
        shutil.copy2(source / name, output / name)
    patch = Path(__file__).with_name("i4-readonly-content.patch")
    if not args.without_patch:
        manifest = json.loads(Path(__file__).with_name("manifest.json").read_text(encoding="utf-8"))
        if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["patchSha256"]:
            raise SystemExit("补丁 hash 与清单不一致")
        env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(output.parent)}
        # 输出树位于本项目仓库内时也按独立树应用，不让父仓库前缀使 git
        # 把所有补丁路径跳过后仍返回 0。
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=output, env=env, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=output, env=env, check=True)
        for name in FILES:
            normalized = (output / name).read_bytes().replace(b"\r\n", b"\n")
            if hashlib.sha256(normalized).hexdigest() != manifest["files"][name]["patchedLfSha256"]:
                raise SystemExit("补丁目标实际字节与清单不符: " + name)
    print(json.dumps({"baseCommit": BASE, "isolatedCopy": True, "patchApplied": not args.without_patch,
                      "patchSha256": hashlib.sha256(patch.read_bytes()).hexdigest() if patch.exists() else None}))


if __name__ == "__main__":
    main()
