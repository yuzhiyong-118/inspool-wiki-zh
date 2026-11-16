"""将固定发行物和一个本机数据目录接入正式监督入口；不改写学习内容。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

from .contracts import DeliveryError, canonical, load_deployment, read_json, sha256
from .evidence_store import atomic
from .runtime_guard import RuntimeGuard

QUESTION_PROJECT_FILES = ('contracts.py', 'question_spec.py', 'question_preparation.py', 'question_evidence.py',
    'production.py', 'knowledge_preparation.py', 'baseline.py', 'handoff.py', 'cli.py', 'deeptutor.py',
    'runtime.py', 'local_install.py', 'runtime_guard.py')
AUTHOR_PROJECT_FILES = ('authored_delivery.py',)
EXTENSION_PROJECT_FILES = ('extensions.py', 'content.py', 'records.py')


def verify_question_install(site, installed, build):
    """Required capability is proved from module bytes, never a supplied flag alone."""
    from .question_preparation import need
    manifest = read_json(Path(__file__).resolve().parents[2] / 'patches/deeptutor/q2/manifest.json')
    # Explicit fixed patch chain, not arbitrary manifest loading or negotiation.
    # Historical Q2 remains readable; Q3 fixes supersede only named file hashes.
    fix_path = Path(__file__).resolve().parents[2] / 'patches/deeptutor/q3-fix/manifest.json'
    project_files = QUESTION_PROJECT_FILES
    if fix_path.is_file():
        fix = read_json(fix_path)
        if build.get('patchSha256') == fix['patchSha256']:
            need(fix['parentPatchSha256'] == manifest['patchSha256'] and
                 fix['baseCommit'] == manifest['baseCommit'], 'install_question_parent')
            manifest = {**manifest, 'patchSha256':fix['patchSha256'],
                'files':{**manifest['files'], **fix['files']},
                'inheritedFiles':{k:v for k,v in manifest['inheritedFiles'].items() if k not in fix['files']}}
            author_path = Path(__file__).resolve().parents[2] / 'patches/deeptutor/e1-authored-delivery/manifest.json'
            extension_path = Path(__file__).resolve().parents[2] / 'patches/deeptutor/controlled-extension/manifest.json'
            if author_path.is_file():
                author = read_json(author_path)
                router = author['files']['deeptutor/api/routers/book.py']['after']
                extension_router = None
                if extension_path.is_file():
                    extension_router = read_json(extension_path)['files']['deeptutor/api/routers/book.py']['after']
                site_router = Path(site) / 'deeptutor/api/routers/book.py'
                actual_router = sha256(site_router.read_bytes().replace(b'\r\n', b'\n')) if site_router.is_file() else None
                if site_router.is_file() and actual_router in (router, extension_router):
                    need(author['parentPatchSha256'] == fix['patchSha256']
                         and author['baseCommit'] == fix['baseCommit'], 'install_question_parent')
                    manifest = {**manifest, 'files':{**manifest['files'], **author['files']},
                        'inheritedFiles':{k:v for k,v in manifest['inheritedFiles'].items() if k not in author['files']}}
                    project_files = project_files + AUTHOR_PROJECT_FILES
            extension_path = Path(__file__).resolve().parents[2] / 'patches/deeptutor/controlled-extension/manifest.json'
            if extension_path.is_file():
                extension = read_json(extension_path)
                router = extension['files']['deeptutor/api/routers/book.py']['after']
                site_router = Path(site) / 'deeptutor/api/routers/book.py'
                if site_router.is_file() and sha256(site_router.read_bytes().replace(b'\r\n', b'\n')) == router:
                    need(extension['parentPatchSha256'] == author['patchSha256']
                         and extension['baseCommit'] == author['baseCommit'], 'install_question_parent')
                    manifest = {**manifest, 'files':{**manifest['files'], **extension['files']},
                        'inheritedFiles':{k:v for k,v in manifest['inheritedFiles'].items()
                                          if k not in extension['files']}}
                    project_files = project_files + EXTENSION_PROJECT_FILES
    need(build.get('patchSha256') == manifest['patchSha256'] and build.get('baseCommit') == manifest['baseCommit']
         and build.get('capability') == 'learning-question-publication/1', 'install_question_build')
    for name, hashes in manifest['files'].items():
        path = Path(site) / name
        need(path.is_file() and installed.get(name) == sha256(path.read_bytes()) and
             sha256(path.read_bytes().replace(b'\r\n', b'\n')) == hashes['after'], 'install_question_bytes')
    for name, expected in manifest['inheritedFiles'].items():
        path = Path(site) / name
        need(path.is_file() and installed.get(name) == sha256(path.read_bytes()) and
             sha256(path.read_bytes().replace(b'\r\n',b'\n')) == expected, 'install_question_inherited')
    need(build.get('moduleSha256') == installed.get('deeptutor/book/question_publication.py'), 'install_question_module')
    return {'tools/learning_book/' + name:sha256((Path(__file__).parent / name).read_bytes())
            for name in project_files}


def verify_author_install(installed, build):
    from .question_preparation import need
    manifest = read_json(Path(__file__).resolve().parents[2] / 'patches/deeptutor/e1-authored-delivery/manifest.json')
    need(build.get('capability') == 'learning-authored-delivery/1'
         and build.get('baseCommit') == manifest['baseCommit']
         and build.get('patchSha256') == manifest['patchSha256'], 'install_author_build')
    need(build.get('moduleSha256') == installed.get('deeptutor/book/author_delivery.py'),
         'install_author_module')
    return build


def verify_extension_install(installed, build):
    from .question_preparation import need
    manifest = read_json(Path(__file__).resolve().parents[2] / 'patches/deeptutor/controlled-extension/manifest.json')
    need(build.get('capability') == 'learning-controlled-extension/1'
         and build.get('baseCommit') == manifest['baseCommit']
         and build.get('patchSha256') == manifest['patchSha256'], 'install_extension_build')
    need(build.get('moduleSha256') == installed.get('deeptutor/book/extension_delivery.py'),
         'install_extension_module')
    return build


def verify_materialized_dependencies(site):
    """缓存硬链接会被上游 pathsec 拒绝；安装接入时提前诊断。"""
    site=Path(site).resolve(strict=True)
    count=0
    for path in site.rglob('*'):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise DeliveryError('install_links','依赖目录必须为独立实体文件；uv 安装使用 --link-mode copy')
        if path.is_file():
            if site not in path.resolve(strict=True).parents or path.stat().st_nlink!=1:
                raise DeliveryError('install_links','依赖存在硬链接；uv 安装使用 --link-mode copy')
            count+=1
    return count


def enroll(*, runtime, project_state, control, python, site, node, web, deployment, budget_from, wheels,
           context_id, api_port=8136, web_port=3836, control_from=None):
    runtime,project_state,control,site,web=map(lambda p:Path(p).resolve(),(runtime,project_state,control,site,web))
    if control.exists():
        raise DeliveryError('install_exists','控制目录必须不存在；已有实例请使用 start/status/stop','conflict')
    verify_materialized_dependencies(site)
    if any(a==b or a in b.parents or b in a.parents for a,b in
           [(runtime,project_state),(runtime,control),(project_state,control)]):
        raise DeliveryError('install_overlap','runtime、项目 state 与控制目录必须独立')
    config=load_deployment(deployment)
    budget=read_json(budget_from)
    if budget['scope']!=config['scope']:
        raise DeliveryError('install_scope','预算和部署作用域不一致')
    # Full carry-forward, never a fresh baseline for the migrated ledger.
    budget.update(contextId=context_id,ledger=str(runtime/'data/user/usage.sqlite3'),stopProcess={})
    from .budget import Budget
    current=Budget(budget,config['scope'],stop=lambda:None).check()
    installed={}; distributions=[]
    for wheel_path in wheels:
        wheel_path=Path(wheel_path).resolve(strict=True)
        distributions.append({'path':str(wheel_path),'sha256':sha256(wheel_path.read_bytes())})
        with zipfile.ZipFile(wheel_path) as archive:
            for name in archive.namelist():
                if '.dist-info/' in name or name.endswith('/'):
                    continue
                target=(site/name).resolve(strict=True)
                if site not in target.parents or target.read_bytes()!=archive.read(name) or name in installed:
                    raise DeliveryError('install_bytes','模块安装字节或所有权不一致')
                installed[name]=sha256(target.read_bytes())
    if len(distributions)!=8 or not installed.get('deeptutor/book/generation.py'):
        raise DeliveryError('install_modules','需完整的八个固定模块及收尾生成补丁')
    project_files = verify_question_install(site, installed, config['questionProductionBuild']) if config.get('questionProductionBuild') else None
    author_build = verify_author_install(installed, config['authoredDeliveryBuild']) if config.get('authoredDeliveryBuild') else None
    extension_build = verify_extension_install(installed, config['extensionBuild']) if config.get('extensionBuild') else None
    web_hashes={p.relative_to(web).as_posix():sha256(p.read_bytes()) for p in web.rglob('*') if p.is_file()}
    if 'server.js' not in web_hashes:
        raise DeliveryError('install_web','缺少生产 Web 资产')
    control.mkdir(parents=True)
    if control_from:
        # 恢复沿用控制库中的 floor 和未结算调用；不靠重新接入清掉暂停原因。
        source=Path(control_from).resolve(strict=True)
        running=source/'running.json'
        from .runtime import same_process
        if running.exists() and any(same_process(r) for k,r in read_json(running).items() if k in ('supervisor','api','web')):
            raise DeliveryError('install_running','旧控制实例尚在运行；先停服','busy')
        shutil.copy2(source/'control.sqlite3',control/'control.sqlite3')
    atomic(control/'budget.json',canonical(budget))
    atomic(control/'guard.json',canonical({'controlDatabase':str(control/'control.sqlite3'),
        'budget':str(control/'budget.json'),'scope':config['scope'],'leaseSeconds':5,'callTimeoutSeconds':600}))
    guard=RuntimeGuard(control/'guard.json');guard.initialize()
    # Enrollment records the initial floor without pretending a supervisor is running.
    guard.start();guard.block('enrolled_not_started')
    configuration={'schema':'learning-local-runtime/1','runtime':str(runtime),'projectState':str(project_state),
        'controlDir':str(control),'python':str(Path(python).resolve(strict=True)),'sitePackages':str(site),
        'node':str(Path(node).resolve(strict=True)),'web':str(web),'guard':str(control/'guard.json'),
        'apiPort':api_port,'webPort':web_port,'installedFiles':installed}
    if project_files is not None:
        configuration.update(questionProductionBuild=config['questionProductionBuild'], projectFiles=project_files)
    if author_build is not None:
        configuration['authoredDeliveryBuild'] = author_build
    if extension_build is not None:
        configuration['extensionBuild'] = extension_build
    atomic(control/'runtime.json',canonical(configuration))
    atomic(control/'deployment.json',canonical({k:v for k,v in config.items() if k!='scope'}))
    atomic(control/'release.json',canonical({'schema':'learning-local-release/1','wheels':distributions,
        'installedFiles':installed,'webFiles':web_hashes,'python':'3.12','node':'22','storage':'sqlite_single_worker'}))
    atomic(control/'enrollment.json',canonical({'schema':'learning-local-enrollment/1','previousBudgetContextId':read_json(budget_from)['contextId'],
        'contextId':context_id,'position':current,'budgetBaselineUnchanged':True,
        'migration':'same cumulative call IDs, only runtime/control paths changed'}))
    return {'status':'succeeded','config':str(control/'runtime.json'),'installedFiles':len(installed),
            'webFiles':len(web_hashes),'totalTokens':current['totalTokens']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','project-state','control','python','site','node','web','deployment','budget-from','context-id'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--wheel',action='append',required=True)
    parser.add_argument('--control-from')
    parser.add_argument('--api-port',type=int,default=8136);parser.add_argument('--web-port',type=int,default=3836)
    args=vars(parser.parse_args());args['wheels']=args.pop('wheel')
    try:
        print(json.dumps(enroll(**args),ensure_ascii=False));return 0
    except (DeliveryError,OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'failed','code':exc.code if isinstance(exc,DeliveryError) else 'install_failure'}));return 1


if __name__=='__main__':sys.exit(main())
