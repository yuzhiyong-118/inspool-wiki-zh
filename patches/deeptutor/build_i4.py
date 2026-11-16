"""离线构建 books 补丁 wheel，并记录实际发行物 hash；不安装。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
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
    patch_dir = Path(__file__).resolve().parent
    manifest = json.loads((patch_dir / "manifest.json").read_text(encoding="utf-8"))
    if output.exists() or source == output or source in output.parents or output in source.parents:
        raise SystemExit("构建输出必须为独立且不存在的目录")
    if sha((patch_dir / "i4-readonly-content.patch").read_bytes()) != manifest["patchSha256"]:
        raise SystemExit("补丁清单 hash 不符")
    for name, values in manifest["files"].items():
        if sha((source / name).read_bytes().replace(b"\r\n", b"\n")) != values["patchedLfSha256"]:
            raise SystemExit("构建树不是已核对的补丁字节: " + name)
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    result = subprocess.run([sys.executable, "-B", str(source / "scripts/build_modules.py"),
                             "--module", "books", "--output", str(output)], env=env, text=True, capture_output=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise SystemExit("构建失败；查看私有输出目录 build.log")
    wheel = output / "deeptutor_books-1.7.2-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as archive:
        for name in manifest["files"]:
            if archive.read(name) != (source / name).read_bytes():
                raise SystemExit("wheel 与构建树目标字节不符")
    provenance = {**manifest, "patched": True, "officialUnmodifiedRelease": False,
                  "wheel": wheel.name, "wheelSha256": sha(wheel.read_bytes()),
                  "actualPatchedFiles": {name: sha((source / name).read_bytes()) for name in manifest["files"]},
                  "build": "fixed upstream scripts/build_modules.py --module books; pip --no-build-isolation --no-deps; PIP_NO_INDEX=1",
                  "installed": False}
    (output / "build-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"localPatchId": provenance["localPatchId"], "wheel": wheel.name, "wheelSha256": provenance["wheelSha256"], "installed": False}))


if __name__ == "__main__":
    main()
