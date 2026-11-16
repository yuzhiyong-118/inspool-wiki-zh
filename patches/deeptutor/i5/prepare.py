"""固定原始源码 → I4 → I5-A 增量补丁；不覆盖已有构建树。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
    if sha((here / "learning-state-read.patch").read_bytes()) != manifest["patchSha256"]:
        raise SystemExit("I5 patch hash 不符")
    if sha((here.parent / "i4-readonly-content.patch").read_bytes()) != manifest["i4BasePatchSha256"]:
        raise SystemExit("I4 基础补丁不符")
    output = args.output.resolve()
    subprocess.run([sys.executable, "-B", str(here.parent / "prepare_i4.py"),
                    "--source", str(args.source.resolve(strict=True)), "--output", str(output)], check=True)
    for name, hashes in manifest["files"].items():
        path = output / name
        expected = hashes["i4BaseLfSha256"]
        if (expected is None and path.exists()) or (expected is not None and sha(path.read_bytes().replace(b"\r\n", b"\n")) != expected):
            raise SystemExit("I5 前置目标不符: " + name)
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(output.parent)}
    patch = str(here / "learning-state-read.patch")
    for command in (["git", "apply", "--check", "--ignore-space-change", patch],
                    ["git", "apply", "--ignore-space-change", patch]):
        subprocess.run(command, cwd=output, env=env, check=True)
    for name, hashes in manifest["files"].items():
        if sha((output / name).read_bytes().replace(b"\r\n", b"\n")) != hashes["patchedLfSha256"]:
            raise SystemExit("应用后 I5 字节不符: " + name)
    for name, expected in manifest["inheritedFiles"].items():
        if sha((output / name).read_bytes().replace(b"\r\n", b"\n")) != expected:
            raise SystemExit("I4 继承字节不符: " + name)
    print(json.dumps({"localPatchId": manifest["localPatchId"], "isolatedCopy": True,
                      "patchSha256": manifest["patchSha256"], "installed": False}))


if __name__ == "__main__":
    main()
