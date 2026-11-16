"""本地学习系统启动／状态／停止。生产资产、配置及数据均显式指定。"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
from urllib.request import build_opener, ProxyHandler

from .budget import ProcessStop, process_identity
from .contracts import DeliveryError, canonical, read_json, sha256
from .evidence_store import atomic
from .runtime_guard import RuntimeGuard, watchdog

REPO = Path(__file__).resolve().parents[2]
MODULE = 'tools.learning_book.runtime'


def load_config(path):
    path = Path(path).resolve(strict=True)
    config = read_json(path)
    if config.get("schema") != "learning-local-runtime/1":
        raise DeliveryError("runtime_config", "运行配置版本无效")
    for key in ("runtime", "projectState", "controlDir", "python", "sitePackages", "node", "web", "guard"):
        value = Path(config[key])
        if not value.is_absolute():
            raise DeliveryError("runtime_path", "运行配置必须使用明确的绝对路径")
    ports = [config["apiPort"], config["webPort"]]
    if any(type(p) is not int or not 1024 <= p <= 65535 for p in ports) or ports[0] == ports[1]:
        raise DeliveryError("runtime_port", "本机服务端口无效")
    if not config.get("installedFiles"):
        raise DeliveryError("runtime_build", "缺少实际发行物文件摘要")
    return config


def verify_build(config):
    site = Path(config["sitePackages"]).resolve(strict=True)
    for relative, expected in config["installedFiles"].items():
        target = (site / relative).resolve(strict=True)
        if site not in target.parents or sha256(target.read_bytes()) != expected:
            raise DeliveryError("runtime_build", "实际安装文件与发行清单不符", "failed")
    if config.get('questionProductionBuild'):
        from .local_install import verify_question_install
        expected = verify_question_install(site, config['installedFiles'], config['questionProductionBuild'])
        if config.get('projectFiles') != expected:
            raise DeliveryError('runtime_question_project', '题目接线的项目代码与接入清单不符', 'failed')
    if config.get('extensionBuild'):
        from .local_install import verify_extension_install
        verify_extension_install(config['installedFiles'], config['extensionBuild'])
    web = Path(config["web"]).resolve(strict=True)
    if not (web / 'server.js').is_file():
        raise DeliveryError("web_missing", "缺少已构建的生产网页")
    release = read_json(Path(config['controlDir'])/'release.json')
    for relative, expected in release['webFiles'].items():
        target=(web/relative).resolve(strict=True)
        if web not in target.parents or sha256(target.read_bytes())!=expected:
            raise DeliveryError('web_build','生产 Web 文件与发行清单不符','failed')
    runtime = Path(config["runtime"]).resolve(strict=True)
    settings = runtime / 'data/user/settings/system.json'
    if settings.exists() and int(read_json(settings).get('backend_workers') or 1) != 1:
        raise DeliveryError("runtime_workers", "本地发行只支持单 worker")
    for key in ('runtime', 'projectState', 'controlDir'):
        directory = Path(config[key])
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ('.permission-' + uuid.uuid4().hex)
        try:
            with probe.open('xb') as stream:
                stream.write(b'check')
        finally:
            probe.unlink(missing_ok=True)
    guard = RuntimeGuard(config['guard'])
    if guard.budget.ledger != (runtime/'data/user/usage.sqlite3').resolve():
        raise DeliveryError('runtime_ledger', '门禁账本与实际 runtime 不符')
    guard.budget.check()


def environment(config):
    allowed = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATH", "PATHEXT", "USERPROFILE", "LOCALAPPDATA", "APPDATA"}
    result = {k:v for k,v in os.environ.items() if k.upper() in allowed}
    result.update(DEEPTUTOR_HOME=config['runtime'], DEEPTUTOR_VERSION_CHECK_ENABLED='false', PYTHONUTF8='1',
                  PYTHONDONTWRITEBYTECODE='1', NEXT_TELEMETRY_DISABLED='1',
                  PYTHONPATH=os.pathsep.join((str(REPO), config['sitePackages'])), LEARNING_BOOK_GUARD=config['guard'])
    return result


@contextmanager
def controller_lock(config):
    # 监督器锁独立于资料生产锁；读写课程不需要等待整个服务退出。
    from .evidence_store import EvidenceStore
    with EvidenceStore(Path(config['controlDir'])/'controller-lock').lock({}):
        yield


def write_state(config, value):
    atomic(Path(config['controlDir'])/'running.json', canonical(value))


def same_process(receipt):
    try:
        current = process_identity(receipt['processId'])
        return all(current[k] == receipt[k] for k in ('executable', 'startedToken'))
    except (DeliveryError, KeyError):
        return False


def status(config):
    path = Path(config['controlDir'])/'running.json'
    state = read_json(path) if path.exists() else {'state':'not_started'}
    state['processes'] = {key:same_process(state[key]) for key in ('supervisor', 'api', 'web') if key in state}
    try:
        state['budget'] = RuntimeGuard(config['guard']).status()
    except DeliveryError as exc:
        state['budget'] = {'error':exc.code}
    if state.get('state') == 'running' and not all(state['processes'].values()):
        state['state'] = 'unavailable'
    if state.get('state')=='self_exit_requested' and not any(state['processes'].values()):
        state['state']='stopped'
        state['stopObserved']=True
    return state


def _spawn(command, cwd, env, log):
    return subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)


def start(config_path):
    config = load_config(config_path)
    current = status(config)
    if current.get('processes', {}).get('supervisor'):
        return current
    verify_build(config)
    control = Path(config['controlDir'])
    control.mkdir(parents=True, exist_ok=True)
    with (control/'supervisor.log').open('ab') as log:
        process = _spawn([config['python'], '-X', 'utf8', '-B', '-m', MODULE, '_supervise', '--config', str(Path(config_path).resolve())],
                         REPO, environment(config), log)
    for _ in range(160):
        time.sleep(.25)
        current = status(config)
        if current.get('state') == 'running' and current.get('supervisor',{}).get('processId') == process.pid:
            return current
        if process.poll() is not None:
            raise DeliveryError('runtime_start_failed', '监督器启动失败；查看私有运行日志与状态', 'failed')
    raise DeliveryError('runtime_start_unknown', '启动仍在途；先查询状态，勿重复启动', 'uncertain')


def stop(config):
    current = status(config)
    if not current.get('processes',{}).get('supervisor'):
        # Abandoned listeners are never killed merely from a port number.
        if any(current.get('processes',{}).get(k) for k in ('api','web')):
            for key in ('api','web'):
                if current['processes'].get(key):
                    stopper = ProcessStop(current[key])
                    stopper.bind_endpoint('http://127.0.0.1:' + str(config[key+'Port']))
                    stopper()
        return status(config)
    atomic(Path(config['controlDir'])/'stop.json', canonical({'runId':current['runId']}))
    for _ in range(100):
        time.sleep(.2)
        observed = status(config)
        if not observed.get('processes',{}).get('supervisor'):
            return observed
    raise DeliveryError('runtime_stop_unknown', '停止尚未确认；查询状态及实际进程', 'uncertain')


def _port_free(port):
    try:
        with socket.socket() as sock:
            # Windows 默认 bind 允许监听重用；排他绑定才能检测另一实例。
            if os.name=='nt':
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind(('127.0.0.1', port))
    except OSError as exc:
        raise DeliveryError('runtime_port_busy', '服务端口已被占用', 'conflict') from exc


def _ready(port, path):
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}{path}', timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def supervise(config_path):
    config = load_config(config_path)
    with controller_lock(config):
        verify_build(config)
        _port_free(config['apiPort']); _port_free(config['webPort'])
        guard = RuntimeGuard(config['guard'])
        guard.start()
        state = {'state':'starting', 'runId':uuid.uuid4().hex, 'supervisor':process_identity(os.getpid())}
        write_state(config, state)
        processes = {}
        control = Path(config['controlDir'])
        failure = None
        try:
            env = environment(config)
            for key in ('api', 'web'):
                if key == 'api':
                    command = [config['python'], '-X', 'utf8', '-B', '-m', MODULE, '_api', '--config', str(config_path)]
                    cwd = config['runtime']
                else:
                    env = {**env, 'HOSTNAME':'127.0.0.1', 'PORT':str(config['webPort']),
                           'DEEPTUTOR_API_BASE_URL':f"http://127.0.0.1:{config['apiPort']}"}
                    command, cwd = [config['node'], 'server.js'], config['web']
                with (control/(key+'.log')).open('ab') as log:
                    process = _spawn(command, cwd, env, log)
                processes[key] = process
                # Capture at creation; no lookup of an unrelated port owner on failure.
                state[key] = {**process_identity(process.pid), 'ownership':'dedicated_single_worker'}
                if key=='api':
                    budget_path = Path(guard.config['budget'])
                    budget_context = read_json(budget_path)
                    budget_context['stopProcess'] = state[key]
                    atomic(budget_path, canonical(budget_context))
                write_state(config, state)
            deadline = time.monotonic()+60
            while True:
                try:
                    guard.poll(supervisor=True)
                except DeliveryError as exc:
                    if exc.code not in ('budget_pause', 'budget_exceeded'):
                        raise
                    state.update(state='budget_paused', reason=exc.code)
                    write_state(config, state)
                if any(p.poll() is not None for p in processes.values()):
                    raise DeliveryError('service_exited', '受管服务退出', 'failed')
                if state['state']=='starting':
                    if _ready(config['apiPort'],'/health/ready') and _ready(config['webPort'],'/learning/books'):
                        for key in processes:
                            bound = ProcessStop(state[key]); bound.bind_endpoint(f"http://127.0.0.1:{config[key+'Port']}"); bound.verify()
                        state['state']='running'; write_state(config,state)
                    elif time.monotonic() > deadline:
                        raise DeliveryError('runtime_start_timeout','服务启动超时','failed')
                sentinel = control/'stop.json'
                if sentinel.exists() and read_json(sentinel).get('runId')==state['runId']:
                    break
                time.sleep(.25)
        except BaseException as exc:
            failure = exc.code if isinstance(exc,DeliveryError) else 'supervisor_failure'
        finally:
            try:
                guard.block(failure or 'operator_stop')
            except Exception:
                pass
            outcomes = {}
            for key, process in processes.items():
                if process.poll() is not None:
                    outcomes[key]='already_exited'; continue
                try:
                    ProcessStop(state[key])()
                    process.wait(timeout=8)
                    outcomes[key]='stop_confirmed'
                except Exception:
                    outcomes[key]='already_exited' if process.poll() is not None else 'stop_failed'
            state.update(state='stopped' if all(x!='stop_failed' for x in outcomes.values()) else 'stop_uncertain',
                         reason=failure or 'operator_stop', stoppedAt=time.time(), stopResults=outcomes)
            write_state(config,state)


def serve_api(config_path):
    config = load_config(config_path)
    guard = RuntimeGuard(config['guard'])
    guard.poll()
    # Dedicated API: loss of the external supervisor stops in-flight calls too.
    def lease_lost():
        # If the supervisor itself died, no external finally can stop the Web.
        # Check this API's identity before using its sibling receipt.
        try:
            state=read_json(Path(config['controlDir'])/'running.json')
            if (state.get('api',{}).get('processId')==os.getpid() and same_process(state['api'])
                    and not same_process(state.get('supervisor',{}))):
                web_stop='already_exited'
                if same_process(state.get('web',{})):
                    try:
                        stopper=ProcessStop(state['web'])
                        stopper.bind_endpoint(f"http://127.0.0.1:{config['webPort']}")
                        stopper();web_stop='stop_confirmed'
                    except Exception:
                        web_stop='stop_failed'
                state.update(state='self_exit_requested',reason='supervisor_lost',
                    stopResults={'api':'self_exit_requested','web':web_stop})
                write_state(config,state)
        finally:
            os._exit(78)
    done, thread = watchdog(guard, lease_lost)
    try:
        from deeptutor.services.config import load_system_settings
        if int(load_system_settings().get('backend_workers') or 1) != 1:
            raise DeliveryError('runtime_workers', '只支持单 worker')
        if config.get('questionProductionBuild'):
            from deeptutor.book.storage import get_book_storage
            from deeptutor.book.question_publication import recover_all
            unresolved = recover_all(get_book_storage())
            atomic(Path(config['controlDir'])/'question-recovery.json', canonical({
                'schema':'learning-question-recovery/1', 'unresolved':unresolved,
                'policy':'unresolved books stay unstable; never replay model generation'}))
        from deeptutor_cli.main import main
        sys.argv = ['deeptutor','serve','--host','127.0.0.1','--port',str(config['apiPort'])]
        main()
    finally:
        done.set(); thread.join(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start','status','stop','_supervise','_api'])
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.action=='_supervise':
            supervise(args.config); return 0
        if args.action=='_api':
            serve_api(args.config); return 0
        config = load_config(args.config)
        value = start(args.config) if args.action=='start' else stop(config) if args.action=='stop' else status(config)
        print(json.dumps(value, ensure_ascii=False))
        return 0
    except (DeliveryError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status':'failed','code':exc.code if isinstance(exc,DeliveryError) else 'runtime_failure'},ensure_ascii=False))
        return 1


if __name__=='__main__':
    sys.exit(main())
