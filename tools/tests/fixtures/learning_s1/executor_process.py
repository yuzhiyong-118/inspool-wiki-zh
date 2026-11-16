"""在真实 Executor 路径执行、恢复、查询、持有接受锁或运行受管 ingest。"""
import json
import os
from pathlib import Path
import sys

from tools.wiki_runtime.executor import Executor
from tools.wiki_runtime.host.derived import check_derivation
from tools.wiki_runtime.runtime import RuntimeInvocationPort, RuntimeService, RuntimeStore, readiness_digest


def managed_apply(config_path, exit_at=None):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    root, journal = Path(config['root']), Path(config['journal'])
    store = RuntimeStore(root)
    port = RuntimeInvocationPort(store, clock=lambda: 100.0)

    def reviewer(envelope, *, timeout):
        request = envelope['input']
        evidence = ['original:' + path + '#L1-L1' for path in request['originals']]
        evidence += ['candidate:' + path + '#L1-L1' for path in request['candidate_files']]
        return dict(
            contract_version='1.0', **request['bindings'], reviewer_id=envelope['reviewer_id'],
            result='recommend_pass', findings=[], evidence_refs=evidence,
        )

    def fault(event, index):
        if event == exit_at:
            os._exit(87)

    executor = Executor(
        root, journal, reviewer=reviewer, invocation_port=port, fault=fault,
        review_timeout=config.get('review_timeout', 30),
        acceptance_context=lambda admission: service.acceptance_context(admission),
    )
    service = RuntimeService(store, executor=executor, clock=lambda: 100.0)
    if not store.read('SELECT task_id FROM tasks'):
        service.create_task(
            policy=config['policy'], task=config['task'], run=config['run'],
            ownership=config['ownership'], learning_state=config['learning'],
        )
    for credential in config['credentials']:
        service.save_review_credential(credential)
    service.save_readiness(config['readiness'])
    admission = config['admission']
    authorization = service.issue_ingest_authorization(
        task_id=admission['task_id'], operation_id=admission['operation_id'],
        readiness_digest=readiness_digest(config['readiness']),
        authorization_ref=admission['authorization_ref'],
    )
    rebuilt = service.build_admission(
        run_id=admission['run_id'], operation_id=admission['operation_id'],
        manifest_digest=admission['manifest_digest'],
        readiness_digest=readiness_digest(config['readiness']),
        authorization_ref=authorization['authorization_ref'],
    )
    if rebuilt != admission:
        raise ValueError('子进程 Admission 重建不一致')
    result = executor.apply(config['bundle'], admission=admission)
    print(json.dumps(result, ensure_ascii=False))
    store.close()


def main():
    if sys.argv[1] == 'managed-apply':
        managed_apply(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        return
    command, root, state, operation = sys.argv[1:5]
    journal = Path(state) / 'private/journals'
    bundle_path = Path(state) / 'operations' / operation / 'bundle.json'
    bundle = json.loads(bundle_path.read_bytes()) if bundle_path.exists() else None
    exit_at = sys.argv[5] if len(sys.argv) > 5 else None

    def fault(event, index):
        if event == exit_at:
            os._exit(87)

    executor = Executor(root, journal, deterministic_check=check_derivation, fault=fault)
    if command == 'apply':
        result = executor.apply(bundle)
    elif command == 'recover':
        result = executor.recover(operation)
    elif command == 'lookup':
        result = executor.lookup_terminal(bundle)
    elif command == 'hold':
        with executor.acceptance_barrier():
            print('locked', flush=True)
            sys.stdin.read()
        result = {'state': 'released'}
    else:
        raise ValueError(command)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
