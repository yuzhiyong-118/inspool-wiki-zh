"""核对固定 closeout 输入模块，创建独立 Q2 源码，不安装或触碰运行数据。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def sha(data): return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); here = Path(__file__).resolve().parent
    manifest = json.loads((here / 'manifest.json').read_text(encoding='utf-8'))
    patch = here / 'question-publication.patch'
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest['patchSha256']: raise SystemExit('patch mismatch')
    source, output = args.source.resolve(strict=True), args.output.resolve()
    if output.exists() or source == output or source in output.parents: raise SystemExit('output must be new and isolated')
    for name, hashes in manifest['files'].items():
        path = source / name
        if (hashes['before'] is None and path.exists()) or (hashes['before'] is not None and sha(path.read_bytes()) != hashes['before']):
            raise SystemExit('base mismatch: ' + name)
    for name, expected in manifest['inheritedFiles'].items():
        if sha((source/name).read_bytes()) != expected: raise SystemExit('inherited mismatch: '+name)
    output.mkdir(parents=True)
    shutil.copytree(source / 'deeptutor', output / 'deeptutor', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(output.parent)}
    for cmd in (['git', 'apply', '--check', str(patch)], ['git', 'apply', str(patch)]):
        subprocess.run(cmd, cwd=output, env=env, check=True)
    for name, hashes in manifest['files'].items():
        if sha((output / name).read_bytes()) != hashes['after']: raise SystemExit('result mismatch: ' + name)
    print(json.dumps({'patchId': manifest['localPatchId'], 'output': str(output), 'installed': False}))


if __name__ == '__main__': main()
