"""交叉核对 I5-A 实际源码、wheel、报告与冻结旧证据；不导入产品或访问网络。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def verify_artifacts(folder, report):
    artifacts = report.get("artifacts", {})
    for name, expected in artifacts.items():
        require(sha(folder / name) == expected, "artifact hash: " + name)
    return len(artifacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="I5-A 最终构建树")
    parser.add_argument("--original-source", type=Path, required=True, help="未修改固定源码")
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    patch_dir = Path(__file__).resolve().parent
    evidence = root / "docs/design/evidence/learning-book-i5/i5-a"
    manifest = read(patch_dir / "manifest.json")
    build = read(evidence / "upstream-build.json")
    require(sha(patch_dir / "learning-state-read.patch") == manifest["patchSha256"], "I5 patch")
    require(sha(patch_dir.parent / "i4-readonly-content.patch") == manifest["i4BasePatchSha256"], "I4 patch")
    require(sha(args.wheel) == build["wheelSha256"], "actual wheel")
    for name, value in manifest.items():
        require(build.get(name) == value, "build provenance: " + name)
    require(build["installed"] is False, "installation claim")
    with zipfile.ZipFile(args.wheel) as archive:
        for name, expected in build["actualPatchedFiles"].items():
            require(sha(args.source / name) == expected, "source: " + name)
            require(archive.read(name) == (args.source / name).read_bytes(), "wheel content: " + name)
    reports = {}
    for name, count in (("test-results.json", 14), ("upstream-source-tests.json", 25),
                        ("upstream-wheel-tests.json", 25), ("i4-upstream-wheel-regression.json", 19),
                        ("i3-regression/test-results.json", 36), ("i4-regression/test-results.json", 29)):
        report = read(evidence / name)
        actual_count = report.get("testCount", report.get("tests"))
        require(actual_count == count and report.get("successful", True) is True, "test result: " + name)
        require(not report.get("failures", 0) and not report.get("errors", 0) and not report.get("skipped", 0), "test failure: " + name)
        if "sources" in report:
            require(report["sources"] == build["actualPatchedFiles"] if count == 25 else
                    all(report["sources"][p] == build["actualPatchedFiles"][p] for p in report["sources"]), "reported source identity: " + name)
            script = patch_dir / "test_learning_state.py" if count == 25 else patch_dir.parent / "test_readonly_content.py"
            require(report["testScriptSha256"] == sha(script), "upstream test script changed")
        for path, expected in report.get("implementationSha256", {}).items():
            require(sha(root / path) == expected, "project source changed: " + path)
        reports[name] = {"testCount": count, "sha256": sha(evidence / name),
                         "artifactCount": verify_artifacts((evidence / name).parent, report)}
    audit = read(root / "docs/design/evidence/learning-book-i5-design/source-review.json")
    for item in audit["sources"]:
        require(sha(args.original_source / item["path"]) == item["sha256"], "original source modified")
    old_root = root / "docs/design/evidence/learning-book-i4"
    old = read(old_root / "verification.json")
    old_artifacts = 0
    for name, entry in old["reports"].items():
        require(sha(old_root / name) == entry["sha256"], "frozen I4 report changed")
        old_artifacts += verify_artifacts((old_root / name).parent, read(old_root / name))
    config = read(root / "tools/learning_book/examples/deployment-i5.json")
    require(config["learningStateReadBuild"]["wheelSha256"] == build["wheelSha256"] and
            config["learningStateReadBuild"]["patchSha256"] == manifest["patchSha256"], "example build identity")
    documents = [root / name for name in ("docs/design/learning-book-i5-plan.md", "docs/design/learning-book-implementation-tasks.md",
        "docs/design/learning-architecture-convergence-handoff.md", "docs/design/README.md", "tools/learning_book/README.md",
        "patches/deeptutor/i5/README.md", "docs/design/evidence/learning-book-i5/README.md")]
    links = 0
    for path in documents:
        text = path.read_text(encoding="utf-8")
        require(text.count("```") % 2 == 0, "unclosed fence: " + str(path))
        for target in re.findall(r"\]\(([^\s)]+)\)", text):
            if "://" in target or target.startswith("#"):
                continue
            target = target.split("#")[0]
            # This report is published atomically below, after all other checks.
            if target.endswith("i5-a/verification.json"):
                continue
            require((path.parent / target).exists(), "missing document link: " + target)
            links += 1
    result = {"kind": "i5_a_delivery_verification", "successful": True,
              "recordedAt": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
              "reports": reports, "patchSha256": manifest["patchSha256"], "wheelSha256": build["wheelSha256"],
              "originalSourceFilesUnchanged": len(audit["sources"]), "frozenI4ArtifactsVerified": old_artifacts,
              "localDocumentLinksChecked": links, "realModelCalls": 0, "realEmbeddingCalls": 0,
              "existingRuntimeStarted": False, "installed": False, "completedSubtasks": ["I5-A"],
              "pendingSubtasks": ["I5-B", "I5-C", "I5-D", "I5-E", "I6"],
              "deliveryFiles": {p.relative_to(root).as_posix(): sha(p) for p in
                                [*sorted(patch_dir.glob("*.py")), patch_dir / "manifest.json", patch_dir / "learning-state-read.patch"]}}
    target = evidence / "verification.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"successful": True, "reports": len(reports), "originalSourceFiles": len(audit["sources"]),
                      "frozenI4Artifacts": old_artifacts, "localLinks": links}))


if __name__ == "__main__":
    main()
