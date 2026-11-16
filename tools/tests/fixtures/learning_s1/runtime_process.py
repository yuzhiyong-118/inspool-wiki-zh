"""S1 Invocation 的真实子进程故障屏障；输入与状态均位于临时目录。"""
import json
from pathlib import Path
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.wiki_runtime.runtime import (  # noqa: E402
    InvocationBusyError, InvocationConflictError, InvocationError, InvocationLimitError,
    LoopError, RecoveryEvidenceError, RuntimeInvocationPort, RuntimeLoop, RuntimeStore,
    RuntimeStoreError,
)


def wait_for(path: Path, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'等待屏障超时: {path}')
        time.sleep(0.01)


def main() -> int:
    command = sys.argv[1]
    config = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
    store = RuntimeStore(config['root'], busy_timeout=1.0)
    if command == 'claim':
        wait_for(Path(config['gate']))
        claimed = RuntimeLoop(store).claim_step(
            config['owner'], now=config['now'],
            lease_seconds=config.get('lease_seconds', 30.0),
            invocation_id=config.get('invocation_id'),
        )
        print(json.dumps(claimed))
        store.close()
        return 0 if claimed is not None else 36
    port = RuntimeInvocationPort(store, clock=lambda: 100.0)
    spec = config['spec']
    if 'gate' in config:
        wait_for(Path(config['gate']))
    if command == 'invoke':
        def transport():
            if 'started' in config:
                with Path(config['started']).open('a', encoding='utf-8') as stream:
                    stream.write(spec['invocation_id'] + '\n')
            if 'release' in config:
                wait_for(Path(config['release']), 30.0)
            return {'output': config.get('output', 'process-ok')}
        result = port.invoke(spec, transport, config.get('timeout', 5.0))
        print(json.dumps({'result': result, 'execution': port.get_execution(spec['invocation_id'])}))
        return 0
    if command == 'recover':
        recovered = port.recover_invocation(spec['invocation_id'], config['evidence'])
        released = port.confirm_resource_released(spec['invocation_id'], {
            'execution_token': recovered['execution_token'],
            'recovery_epoch': recovered['recovery_epoch'],
            'executor_stopped': True,
        })
        replayed = port.replay(spec)
        print(json.dumps({
            'recovered': recovered,
            'released': released,
            'replayed': replayed,
            'execution': port.get_execution(spec['invocation_id']),
        }))
        return 0
    raise ValueError(f'未知子进程命令: {command}')


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except InvocationBusyError as exc:
        print(json.dumps({'busy': str(exc)}))
        raise SystemExit(32)
    except InvocationLimitError as exc:
        print(json.dumps({'limited': str(exc)}))
        raise SystemExit(33)
    except (InvocationConflictError, RecoveryEvidenceError) as exc:
        print(json.dumps({'conflict': str(exc)}))
        raise SystemExit(34)
    except (InvocationError, RuntimeStoreError) as exc:
        print(json.dumps({'runtime_error': str(exc)}))
        raise SystemExit(35)
