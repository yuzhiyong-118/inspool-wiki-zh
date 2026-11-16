"""离线派生固定八模块 wheel；只改 Q2 清单文件，重算 RECORD，独立解包验收。"""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile


def sha(data): return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--wheel',action='append',required=True,type=Path)
    args=parser.parse_args(); here=Path(__file__).resolve().parent
    manifest=json.loads((here/'manifest.json').read_text(encoding='utf-8'))
    if len(args.wheel)!=8 or args.output.exists(): raise SystemExit('eight disjoint inputs and a new output required')
    source=args.source.resolve(strict=True); output=args.output.resolve(); output.mkdir(parents=True)
    used, installed, receipts=set(), {}, []
    for wheel in args.wheel:
        wheel=wheel.resolve(strict=True)
        if wheel.name.startswith('deeptutor_books-') and sha(wheel.read_bytes()) != manifest['baseBooksWheelSha256']:
            raise SystemExit('fixed books wheel mismatch')
        with zipfile.ZipFile(wheel) as archive:
            members={n:archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        for name, hashes in manifest['files'].items():
            if name in members:
                if sha(members[name].replace(b'\r\n',b'\n')) not in (hashes['before'],manifest.get('wheelBaseOverrides',{}).get(name)):
                    raise SystemExit('wheel base mismatch: '+name)
                data=(source/name).read_bytes()
                if sha(data.replace(b'\r\n',b'\n'))!=hashes['after']: raise SystemExit('source mismatch: '+name)
                members[name]=data; used.add(name)
        for name, expected in manifest['inheritedFiles'].items():
            if name in members and sha(members[name].replace(b'\r\n',b'\n')) != expected:
                raise SystemExit('inherited wheel capability mismatch: '+name)
        if wheel.name.startswith('deeptutor_books-'):
            name='deeptutor/book/question_publication.py'; members[name]=(source/name).read_bytes(); used.add(name)
        records=[n for n in members if n.endswith('.dist-info/RECORD')]
        if len(records)!=1: raise SystemExit('RECORD missing')
        record=records[0]; lines=io.StringIO(); writer=csv.writer(lines,lineterminator='\n')
        for name,data in sorted(members.items()):
            if name!=record:
                writer.writerow([name,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode(),len(data)])
        writer.writerow([record,'','']); members[record]=lines.getvalue().encode()
        target=output/'wheels'/wheel.name; target.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in sorted(members.items()):
                if Path(name).is_absolute() or '..' in Path(name).parts: raise SystemExit('unsafe wheel path')
                archive.writestr(name,data)
                # Materialize all files, including dist-info, without pip/network or hard links.
                destination=output/'site'/name
                if destination.exists(): raise SystemExit('wheel ownership overlap: '+name)
                destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(data)
                if '.dist-info/' not in name: installed[name]=sha(data)
        receipts.append({'name':wheel.name,'inputSha256':sha(wheel.read_bytes()),'outputSha256':sha(target.read_bytes())})
    if used!=set(manifest['files']): raise SystemExit('missing patch owner')
    receipt={'schema':'learning-question-wheels/1','patchSha256':manifest['patchSha256'],'wheels':receipts,
             'installedFiles':installed,'realModelCalls':0,'networkCalls':0,'method':'fixed wheel members; refreshed RECORD; isolated extraction'}
    (output/'release.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'wheels':len(receipts),'businessFiles':len(installed),'output':str(output),'installedInExistingRuntime':False}))


if __name__=='__main__': main()
