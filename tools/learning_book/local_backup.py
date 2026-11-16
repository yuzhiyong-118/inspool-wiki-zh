"""停服备份／隔离恢复；运行数据与项目证据按原字节保存。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from .contracts import DeliveryError, canonical, read_json, sha256
from .evidence_store import atomic
from .runtime import controller_lock, load_config, status, _port_free


def inventory(root, *, exclude=()):
    root = Path(root).resolve(strict=True)
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        if Path(directory)==root:
            dirs[:]=[name for name in dirs if name not in exclude]
        for name in dirs + names:
            path = Path(directory)/name
            if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
                raise DeliveryError('backup_link', '备份范围包含链接／junction，需明确整理后再备份')
        for name in names:
            path=Path(directory)/name
            files[path.relative_to(root).as_posix()] = {'sha256':sha256(path.read_bytes()),'bytes':path.stat().st_size}
    return files


def verify_backup(package):
    package=Path(package).resolve(strict=True)
    value=read_json(package/'manifest.json')
    if value.get('schema')!='learning-local-backup/1':
        raise DeliveryError('backup_schema','备份格式无效')
    actual=inventory(package)
    actual.pop('manifest.json',None)
    if actual != value['files']:
        raise DeliveryError('backup_integrity','备份文件清单／字节不一致','failed')
    return value


def backup(config, target):
    target=Path(target).resolve()
    if target.exists():
        raise DeliveryError('backup_exists','目标必须不存在','conflict')
    roots={name:Path(config[key]).resolve(strict=True) for name,key in
           [('runtime','runtime'),('state','projectState'),('control','controlDir')]}
    if any(root==target or root in target.parents or target in root.parents for root in roots.values()):
        raise DeliveryError('backup_overlap','备份目标与数据目录不得包含彼此')
    with controller_lock(config):
        live=status(config)
        if any(live.get('processes',{}).values()):
            raise DeliveryError('backup_running','先停止受管服务，再执行备份','busy')
        _port_free(config['apiPort']);_port_free(config['webPort'])
        def inventories():
            return {name:inventory(root,exclude=('controller-lock',) if name=='control' else ()) for name,root in roots.items()}
        before=inventories()
        temp=target.with_name('.b'+uuid.uuid4().hex[:8])
        temp.mkdir(parents=True)
        # 失败的临时目录保留，便于检查；不递归删除用户数据。
        for name,root in roots.items():
            shutil.copytree(root,temp/name,ignore=(lambda directory,names: ['controller-lock'] if Path(directory)==root and name=='control' else []))
        after=inventories()
        copied={name:inventory(temp/name) for name in roots}
        if before != after or after != copied:
            raise DeliveryError('backup_changed','停服数据在复制期间变化；未发布备份','uncertain')
        value={'schema':'learning-local-backup/1','files':inventory(temp),
               'runtimeConfig':config,'ledgerPolicy':'preserve_all_calls_and_baseline',
               'sourceOriginals':'only_files_inside_runtime_and_project_state'}
        atomic(temp/'manifest.json',canonical(value))
        os.replace(temp,target)
    verify_backup(target)
    return {'status':'succeeded','package':str(target),'files':len(value['files'])}


def restore(package,target):
    package=Path(package).resolve(strict=True)
    value=verify_backup(package)
    target=Path(target).resolve()
    if target.exists() or package==target or package in target.parents or target in package.parents:
        raise DeliveryError('restore_target','恢复目标必须是与备份独立的全新目录')
    temp=target.with_name('.restore-'+uuid.uuid4().hex)
    temp.mkdir(parents=True)
    for name in ('runtime','state','control'):
        shutil.copytree(package/name,temp/name)
        if inventory(temp/name)!=inventory(package/name):
            raise DeliveryError('restore_integrity','恢复字节不一致','failed')
    atomic(temp/'restore-receipt.json',canonical({'schema':'learning-local-restore/1',
        'backupManifestSha256':sha256((package/'manifest.json').read_bytes()),'byteVerified':True,
        'note':'运行配置和门禁需显式重新绑定新路径；不得直接复用旧实例身份'}))
    os.replace(temp,target)
    return {'status':'succeeded','target':str(target),'byteVerified':True,'configured':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='operation',required=True)
    b=sub.add_parser('backup');b.add_argument('--config',required=True);b.add_argument('--target',required=True)
    r=sub.add_parser('restore');r.add_argument('--package',required=True);r.add_argument('--target',required=True)
    v=sub.add_parser('verify');v.add_argument('--package',required=True)
    args=parser.parse_args()
    try:
        if args.operation=='backup':result=backup(load_config(args.config),args.target)
        elif args.operation=='restore':result=restore(args.package,args.target)
        else:result={'status':'succeeded','files':len(verify_backup(args.package)['files'])}
        print(json.dumps(result,ensure_ascii=False));return 0
    except (OSError,ValueError,KeyError,TypeError,DeliveryError) as exc:
        print(json.dumps({'status':'failed','code':exc.code if isinstance(exc,DeliveryError) else 'backup_failure'}));return 1


if __name__=='__main__':sys.exit(main())
