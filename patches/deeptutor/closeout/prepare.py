"""固定源码 → I4 → I5 → I6 → 收尾补丁，输出独立构建树。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def lf(path):return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--with-web',action='store_true')
    args=p.parse_args();here=Path(__file__).resolve().parent;out=args.output.resolve()
    manifest=json.loads((here/'manifest.json').read_text(encoding='utf-8'))
    i6=here.parent/'i6';inherited=json.loads((i6/'manifest.json').read_text(encoding='utf-8'))
    if sha(i6/'manifest.json')!=manifest['i6ManifestSha256']:raise SystemExit('I6 manifest changed')
    for name,digest in manifest['patches'].items():
        if sha(here/name)!=digest:raise SystemExit('patch hash mismatch')
    if sha(here/'dependencies.lock')!=manifest['dependenciesSha256']:raise SystemExit('dependency lock mismatch')
    subprocess.run([sys.executable,'-B',str(here.parent/'i5/prepare.py'),'--source',str(args.source.resolve(strict=True)),
                    '--output',str(out)],check=True)
    env={**os.environ,'GIT_CEILING_DIRECTORIES':str(out.parent),'PYTHONUTF8':'1'}
    def apply(patch,cwd):
        for extra in (['--check'],[]):
            subprocess.run(['git','apply','--ignore-space-change',*extra,str(patch)],cwd=cwd,env=env,check=True)
    for patch in inherited['patches']:
        path=i6/patch['file']
        if sha(path)!=patch['sha256']:raise SystemExit('I6 patch mismatch')
        apply(path,out)
    for name,hashes in manifest['sourceFiles'].items():
        path=out/name
        if (hashes['before'] is None and path.exists()) or (hashes['before'] is not None and lf(path)!=hashes['before']):
            raise SystemExit('source base mismatch: '+name)
    apply(here/'closeout.patch',out)
    for name,hashes in manifest['sourceFiles'].items():
        if lf(out/name)!=hashes['after']:raise SystemExit('patched source mismatch: '+name)
    if args.with_web:
        shutil.copytree(args.source/'web',out/'web',ignore=shutil.ignore_patterns('node_modules','.next','*.log'))
        apply(here/'web-closeout.patch',out/'web')
    print(json.dumps({'prepared':True,'sourceFilesVerified':len(manifest['sourceFiles']),'web':args.with_web}))


if __name__=='__main__':main()
