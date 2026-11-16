"""离线构建累计 I4＋I5 books wheel，检查归属和实际打包字节；不安装。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source, output = args.source.resolve(strict=True), args.output.resolve()
    here = Path(__file__).resolve().parent
    manifest = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
    if output.exists() or source == output or source in output.parents or output in source.parents:
        raise SystemExit("构建输出必须独立且不存在")
    if sha((here / "learning-state-read.patch").read_bytes()) != manifest["patchSha256"]:
        raise SystemExit("I5 补丁 hash 不符")
    if sha((here.parent / "i4-readonly-content.patch").read_bytes()) != manifest["i4BasePatchSha256"]:
        raise SystemExit("I4 补丁 hash 不符")
    ownership = manifest["ownershipEvidence"]
    if sha((source / ownership["manifest"]).read_bytes()) != ownership["sha256"]:
        raise SystemExit("模块归属清单不符")
    owned = json.loads((source / ownership["manifest"]).read_text(encoding="utf-8"))["paths"]
    targets = {name: data["patchedLfSha256"] for name, data in manifest["files"].items()}
    targets.update(manifest["inheritedFiles"])
    for name, expected in targets.items():
        if not any(name == p or name.startswith(p.rstrip("/") + "/") for p in owned):
            raise SystemExit("目标不属于 books: " + name)
        if sha((source / name).read_bytes().replace(b"\r\n", b"\n")) != expected:
            raise SystemExit("构建树字节不符: " + name)
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    result = subprocess.run([sys.executable, "-B", str(source / "scripts/build_modules.py"),
                             "--module", manifest["owningModule"], "--output", str(output)],
                            env=env, text=True, capture_output=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise SystemExit("构建失败，查看私有输出 build.log")
    wheel = output / "deeptutor_books-1.7.2-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        for name in targets:
            if archive.read(name) != (source / name).read_bytes():
                raise SystemExit("wheel 实际字节不符: " + name)
    provenance = {**manifest, "patched": True, "officialUnmodifiedRelease": False,
                  "wheel": wheel.name, "wheelSha256": sha(wheel.read_bytes()),
                  "actualPatchedFiles": {name: sha((source / name).read_bytes()) for name in targets},
                  "build": "upstream scripts/build_modules.py --module books; PIP_NO_INDEX=1; no-build-isolation/no-deps",
                  "installed": False}
    (output / "build-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"localPatchId": manifest["localPatchId"], "wheelSha256": provenance["wheelSha256"], "installed": False}))


if __name__ == "__main__":
    main()
