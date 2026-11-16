"""真实旧 pending、写者和可中断 drain 的子进程入口。"""
import json
import os
from pathlib import Path
import sys
import time

from tools.wiki_runtime.contracts import digest
from tools.wiki_runtime.executor import Executor
from tools.wiki_runtime.host.derived import build_raw_index, check_derivation
from tools.wiki_runtime.host.supervisor import StandaloneHost
from tools.wiki_runtime.runtime.migration import drain_registered_pending, legacy_write_guard


def make_pending(root, state, operation):
    host = StandaloneHost(root, state, offline=True)
    bundle = build_raw_index(root, host.operations / digest(operation), operation)
    executor = Executor(root, host.private / 'journals', deterministic_check=check_derivation)
    record = {'kind': 'derived', 'bundle': bundle,
              'context': executor._context(bundle['manifest'], bundle['candidate'], bundle['snapshot']),
              'config': {'root': str(host.root), 'operation_id': operation,
                         'operation_type': bundle['manifest']['operation_type']}, 'packages': []}
    host._save_pending(operation, record)
    return {'status': record['config']['operation_id'], 'applied': False}


def main():
    command, root, state, operation = sys.argv[1:5]
    if command == 'make-pending':
        result = make_pending(root, state, operation)
    elif command == 'drain':
        result = drain_registered_pending(operation, root=root, state_dir=state)
    elif command == 'guard':
        with legacy_write_guard(root, operation or None):
            result = {'status': 'entered'}
    elif command == 'writer':
        ready, release, target = map(Path, sys.argv[5:8])
        with legacy_write_guard(root):
            ready.write_text('checked', encoding='utf-8')
            while not release.exists():
                time.sleep(0.01)
            target.write_text('writer-finished', encoding='utf-8')
        result = {'status': 'written'}
    elif command == 'interrupted-drain':
        from tools.wiki_runtime.host import cli

        def interrupt(host, operation_id):
            record = host.load_pending(operation_id)
            def fault(event, index):
                if event == 'after_applying':
                    os._exit(86)
            executor = Executor(root, Path(state) / 'private/journals',
                                deterministic_check=check_derivation, fault=fault)
            executor._legacy_drain_operation = operation_id
            executor.apply(record['bundle'])
            raise AssertionError('不可达')

        cli._apply_record = interrupt
        result = drain_registered_pending(operation, root=root, state_dir=state)
    elif command == 'host-apply':
        from tools.wiki_runtime.host.cli import _apply_record
        host = StandaloneHost(root, state, offline=True)
        result = _apply_record(host, operation)
    elif command in ('freeze-after-intent', 'freeze-after-locator'):
        from tools.wiki_runtime.runtime import migration
        original = migration._atomic
        target = ('legacy-cutover.pointer.json' if command == 'freeze-after-intent'
                  else 'legacy-cutover.json')

        def interrupt(path, data):
            if Path(path).name == target:
                os._exit(85)
            return original(path, data)

        migration._atomic = interrupt
        result = migration.freeze_legacy_entries(root, state)
    elif command == 'drain-crash':
        from tools.wiki_runtime.runtime import migration
        point = sys.argv[5]
        if point == 'after-running':
            from tools.wiki_runtime.host import supervisor

            class CrashingHost:
                def __init__(self, *args, **kwargs):
                    os._exit(86)

            supervisor.StandaloneHost = CrashingHost
        elif point in ('after-prepare', 'after-active'):
            from tools.wiki_runtime.host import cli
            event = {'after-prepare': 'after_prepare', 'after-active': 'after_active'}[point]

            def interrupt(host, operation_id):
                record = host.load_pending(operation_id)
                def fault(actual, index):
                    if actual == event:
                        os._exit(86)
                executor = Executor(root, Path(state) / 'private/journals',
                                    deterministic_check=check_derivation, fault=fault)
                executor._legacy_drain_operation = operation_id
                executor.apply(record['bundle'])
                raise AssertionError('不可达')

            cli._apply_record = interrupt
        elif point in ('after-applied', 'after-recovered'):
            def interrupt(*args):
                os._exit(86)

            migration._save_receipt = interrupt
        result = migration.drain_registered_pending(operation, root=root, state_dir=state)
        if point == 'after-completed':
            os._exit(86)
    elif command == 'supersede-crash':
        from tools.wiki_runtime.runtime import migration
        original = migration._atomic

        def interrupt(path, data):
            if Path(path).name == 'legacy-cutover.json':
                os._exit(87)
            return original(path, data)

        migration._atomic = interrupt
        result = migration.supersede_pending(
            operation, sys.argv[5], root=root, state_dir=state,
        )
    else:
        raise ValueError(command)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
