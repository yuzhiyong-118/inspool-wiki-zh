"""核对 Q2 完整发行物，应用 Q3 修复，派生八个 wheel 与独立 site；无安装／网络。"""
import argparse
import ast
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import zipfile

HERE=Path(__file__).resolve().parent


def sha(data): return hashlib.sha256(data).hexdigest()


def build(base, output):
    base=base.resolve(strict=True);output=output.resolve()
    manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    if output.exists() or base==output or base in output.parents: raise ValueError('new separate output required')
    if sha((base/'release.json').read_bytes())!=manifest['parentReleaseSha256']: raise ValueError('parent receipt mismatch')
    receipt=json.loads((base/'release.json').read_text(encoding='utf-8'))
    patch=HERE/'question-runtime-fixes.patch'
    if sha(patch.read_bytes())!=manifest['patchSha256']: raise ValueError('patch mismatch')
    inputs={}
    for name,expected in receipt['installedFiles'].items():
        path=(base/'site'/name).resolve(strict=True)
        if (base/'site').resolve() not in path.parents or sha(path.read_bytes())!=expected:raise ValueError('parent bytes mismatch')
        inputs[name]=path.read_bytes()
    wheels=[]
    for name,expected in manifest['inputWheels'].items():
        path=base/'wheels'/name
        if sha(path.read_bytes())!=expected:raise ValueError('input wheel mismatch')
        wheels.append(path)
    if len(wheels)!=8:raise ValueError('eight inputs required')
    for name,value in manifest['files'].items():
        if sha(inputs[name].replace(b'\r\n',b'\n'))!=value['before']:raise ValueError('source before mismatch')
    source=output/'source';source.mkdir(parents=True)
    for name,data in inputs.items():
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data.replace(b'\r\n',b'\n') if name in manifest['files'] else data)
    env={**os.environ,'GIT_CEILING_DIRECTORIES':str(output.parent)}
    for args in (['git','apply','--check',str(patch)],['git','apply',str(patch)]):subprocess.run(args,cwd=source,env=env,check=True)
    for name,value in manifest['files'].items():
        raw=(source/name).read_bytes().replace(b'\r\n',b'\n')
        (source/name).write_bytes(raw)
        if sha(raw)!=value['after']:raise ValueError('patched source mismatch')
        ast.parse(raw)
    installed={};receipts=[];used=set()
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as archive:
            members={n:archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        for name,value in manifest['files'].items():
            if name not in members:continue
            if sha(members[name].replace(b'\r\n',b'\n'))!=value['before']:raise ValueError('wheel before mismatch')
            members[name]=(source/name).read_bytes();used.add(name)
        records=[n for n in members if n.endswith('.dist-info/RECORD')]
        if len(records)!=1:raise ValueError('RECORD identity')
        record=records[0];lines=io.StringIO();writer=csv.writer(lines,lineterminator='\n')
        for name,data in sorted(members.items()):
            if name!=record:writer.writerow([name,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(),len(data)])
        writer.writerow([record,'','']);members[record]=lines.getvalue().encode()
        target=output/'wheels'/wheel.name;target.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in sorted(members.items()):
                if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('unsafe wheel path')
                dest=output/'site'/name
                if dest.exists():raise ValueError('wheel overlap')
                dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data);archive.writestr(name,data)
                if '.dist-info/' not in name:installed[name]=sha(data)
        receipts.append({'name':wheel.name,'inputSha256':sha(wheel.read_bytes()),'outputSha256':sha(target.read_bytes())})
    if used!=set(manifest['files']) or set(installed)!=set(inputs):raise ValueError('coverage mismatch')
    value={'schema':'learning-question-wheels/1','patchSha256':manifest['patchSha256'],
        'parentPatchSha256':manifest['parentPatchSha256'],'parentReleaseSha256':manifest['parentReleaseSha256'],
        'wheels':receipts,'installedFiles':installed,'realModelCalls':0,'networkCalls':0,
        'method':'verified Q2 wheel delta; RECORD refreshed; isolated source and site'}
    (output/'release.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return {'output':str(output),'wheels':len(wheels),'businessFiles':len(installed),'installedInExistingRuntime':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base-release',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(build(args.base_release,args.output)))
