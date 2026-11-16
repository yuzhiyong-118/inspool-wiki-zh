"""可信 host 的固定机器派生入口；只生成候选，不提供模型自证开关。"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
import tempfile

from ..candidate import CandidateView
from ..capture import validate_package
from ..cli import _run_directory
from ..contracts import (ContractError, bytes_digest, candidate_digest, canonical_json,
                         digest, validate, validate_path)
from ..executor import ExecutionError
from ..executor.core import _safe, _reparse
from ..gates import VALIDATOR_VERSION
from ..gates.core import _health
from ..review import PROMPT_VERSION


def _queue(root):
    from tools import raw_index
    original = (root / 'raw/index.md').read_bytes().decode('utf-8')
    start, end = raw_index.START, raw_index.END
    if original.count(start) != 1 or original.count(end) != 1 or original.index(start) >= original.index(end):
        raise ContractError('raw/index.md 必须有唯一有序队列标记')
    newline = '\r\n' if '\r\n' in original else '\n'
    generated = raw_index.render_queue(raw_root=root / 'raw').replace('\n', newline)
    return (original[:original.index(start)] + generated + original[original.index(end) + len(end):]).encode('utf-8')


def _health_outputs(root, *, save_report, write_graph, day):
    # day 只影响固定日志标题；无字段可以借时间变化逃过逐字节比对。
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or date.fromisoformat(day).isoformat() != day:
        raise ContractError('health 日期格式无效')
    module, report = _health(root)
    outputs = {}
    if save_report:
        outputs['wiki/health-report.md'] = module.format_report(report).encode('utf-8')
    if write_graph:
        outputs['wiki/meta/graph.json'] = (json.dumps(report['graph'], ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    log = (root / 'wiki/log.md').read_bytes() if (root / 'wiki/log.md').exists() else b''
    entry = (f'\n\n## [{day}] health | 确定性结构检查\n\n'
             f'- 检查结果：{module.count_problems(report)} 项问题。\n'
             f'- 内容页：{report["stats"]["content_page_count"]}；'
             f'图节点：{report["stats"]["node_count"]}；图边：{report["stats"]["edge_count"]}。\n')
    outputs['wiki/log.md'] = log + entry.encode('utf-8')
    return outputs


def _capture_outputs(root, package, package_root, raw_path):
    validate_path(raw_path)
    if not raw_path.startswith('raw/unprocessed/') or not raw_path.endswith('.md'):
        raise ContractError('capture 仅登记 raw/unprocessed 下的 Markdown')
    validate_package(package, package_root)
    q, parser = package['quality'], package['parser']
    if (package['input_type'] not in ('markdown', 'wechat') or parser['adapter_id'] not in ('markdown', 'wechat')
            or parser['used_ocr'] or parser['used_model'] or q['status'] != 'complete'
            or q['errors'] or q['missing'] or not q['evidence']):
        raise ContractError('资料不完整或抽取需人工处理；暂停导入')
    base = 'raw/assets/' + package['source_id'] + '/' + package['source_revision']
    validate_path(base)
    if len(package['source_id'].split('/')) != 1:
        raise ContractError('source_id 必须为单一路径分量')
    # 整个修订目录不可复用，即使本轮包省略了已有文件也不能覆盖原件。
    if _safe(root, base).exists() or _safe(root, raw_path).exists():
        raise ContractError('资料修订或 raw 路径已存在；拒绝重复导入')
    outputs = {}
    for record in [*package['originals'], package['extracted'], *package['attachments']]:
        outputs[base + '/' + record['path']] = _safe(Path(package_root), record['path']).read_bytes()
    outputs[base + '/source-package.json'] = canonical_json(package) + b'\n'
    # 抽取文件和附件保持包内原路径；薄记录嵌入抽取文件，原正文不二次转换。
    header = dict(processing_status='unprocessed', source_id=package['source_id'],
                  source_revision=package['source_revision'], input_type=package['input_type'],
                  source_package='[[' + base + '/source-package.json]]',
                  external_url=package['source']['origin'])
    fm = '\n'.join(key + ': ' + json.dumps(value, ensure_ascii=False) for key, value in header.items())
    outputs[raw_path] = ('---\n' + fm + '\n---\n![[' + base + '/' + package['extracted']['path'] + ']]\n').encode('utf-8')
    # 复用同一算法，在私有临时副本上加入新记录；从不修改正式 raw。
    with tempfile.TemporaryDirectory(prefix='derived-queue-') as temporary:
        staged = Path(temporary)
        for path in (root / 'raw').rglob('*.md'):
            target = staged / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        target = staged / raw_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(outputs[raw_path])
        outputs['raw/index.md'] = _queue(staged)
    return outputs


def _bundle(root, run_dir, operation_id, operation_type, outputs):
    for supplied in (Path(root).absolute(), Path(run_dir).absolute()):
        for ancestor in (supplied, *supplied.parents):
            if ancestor.exists() and _reparse(ancestor):
                raise ContractError('拒绝重解析运行根或库根')
    root, run_dir = _run_directory(root, run_dir)
    # 在创建任何候选目录前，先检查祖先的重解析/硬链接与目标路径。
    if run_dir.is_relative_to(root):
        _safe(root, run_dir.relative_to(root).as_posix())
    if run_dir.exists():
        raise ContractError('运行目录已存在，拒绝覆盖')
    # 载荷使用平面短文件名；正式来源身份保留在清单，避免 Windows 候选路径翻倍。
    payload_names = {path: f'{index:04d}.bin' for index, path in enumerate(sorted(outputs))}
    candidate = dict(contract_version='1.0', operation_id=operation_id, changes=[])
    for path, data in sorted(outputs.items()):
        old = _safe(root, path)
        candidate['changes'].append(dict(action='write', path=path, payload_path=payload_names[path],
            sha256=bytes_digest(data), precondition=(dict(kind='hash', sha256=bytes_digest(old.read_bytes()))
                                                   if old.exists() else dict(kind='absent'))))
    validate('candidate', candidate)
    run_dir.mkdir(parents=True, exist_ok=False)
    payload = run_dir / 'payload'
    payload.mkdir()
    for path, data in outputs.items():
        target = _safe(payload, payload_names[path])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    view = CandidateView(root, candidate, payload)
    list(view.iter_paths())
    snapshot = view.dependency_snapshot()
    manifest = dict(contract_version='1.0', operation_id=operation_id, operation_type=operation_type,
        task='固定机器派生产物', input_refs=[], allowed_paths=sorted(outputs), rules_path='AGENTS.md',
        rules_digest=bytes_digest(view.read_bytes('AGENTS.md')),
        mapping_digest=bytes_digest(view.read_bytes('tools/wiki_runtime/contracts/rules.json')),
        validator_version=VALIDATOR_VERSION, review_prompt_version=PROMPT_VERSION,
        dependencies_digest=digest(snapshot), candidate_digest=candidate_digest(candidate),
        round=1, required_gates=['G0', 'G1', 'G2'], authorization_refs=[])
    validate('manifest', manifest)
    view.verify_dependencies(snapshot)
    bundle = dict(manifest=manifest, candidate=candidate, snapshot=snapshot, payload_root=str(payload))
    for name, value in [('manifest', manifest), ('candidate', candidate), ('dependencies', snapshot)]:
        (run_dir / (name + '.json')).write_bytes(canonical_json(value) + b'\n')
    return bundle


def build_raw_index(root, run_dir, operation_id):
    root = Path(root).absolute()
    return _bundle(root, run_dir, operation_id, 'index_rebuild', {'raw/index.md': _queue(root)})


def build_health(root, run_dir, operation_id, *, save_report=True, write_graph=False):
    root = Path(root).absolute()
    if type(save_report) is not bool or type(write_graph) is not bool:
        raise ContractError('health 选项必须是布尔值')
    return _bundle(root, run_dir, operation_id, 'health', _health_outputs(
        root, save_report=save_report, write_graph=write_graph, day=date.today().isoformat()))


def build_capture(root, run_dir, operation_id, package, package_root, *, raw_path):
    root = Path(root).absolute()
    return _bundle(root, run_dir, operation_id, 'capture',
                   _capture_outputs(root, package, package_root, raw_path))


def check_derivation(context, view, source_packages=()):
    """精确复算真实差异；任何不识别、缺文件、多文件或正文一字节差异均返回 False。"""
    try:
        candidate, manifest = context['candidate'], context['manifest']
        if candidate != view.candidate or context['operation_type'] != manifest['operation_type']:
            return False
        changes = candidate['changes']
        if any(c['action'] != 'write' for c in changes):
            return False
        paths = {c['path'] for c in changes}
        operation = manifest['operation_type']
        # 完整读取基线，固定所有枚举依赖；重算只看正式基线，绝不信任候选标识。
        list(view.iter_paths())
        if operation == 'index_rebuild' and paths == {'raw/index.md'} and not source_packages:
            expected = {'raw/index.md': _queue(view.root)}
        elif operation == 'health' and not source_packages:
            allowed = {'wiki/log.md', 'wiki/health-report.md', 'wiki/meta/graph.json'}
            if not paths <= allowed or 'wiki/log.md' not in paths:
                return False
            log = view.read_bytes('wiki/log.md')
            old = (view.root / 'wiki/log.md').read_bytes() if (view.root / 'wiki/log.md').exists() else b''
            suffix = log[len(old):].decode('utf-8')
            match = re.match(r'\n\n## \[(\d{4}-\d{2}-\d{2})\] health \|', suffix)
            if not log.startswith(old) or not match:
                return False
            expected = _health_outputs(view.root, save_report='wiki/health-report.md' in paths,
                                      write_graph='wiki/meta/graph.json' in paths, day=match[1])
        elif operation in ('capture', 'import') and len(source_packages) == 1:
            raw = [p for p in paths if p.startswith('raw/unprocessed/')]
            if len(raw) != 1:
                return False
            package, package_root = source_packages[0]
            expected = _capture_outputs(view.root, package, package_root, raw[0])
        else:
            return False
        return paths == set(expected) and all(view.read_bytes(p) == data for p, data in expected.items())
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, UnicodeError):
        return False


def maintenance_binding(runtime_context, bundle):
    manifest = bundle['manifest']
    task, run, policy = (runtime_context[key] for key in ('task', 'run', 'policy'))
    return {
        'task_id': task['task_id'], 'learning_task_id': task['learning_task_id'],
        'run_id': run['run_id'], 'operation_id': manifest['operation_id'],
        'operation_type': manifest['operation_type'],
        'workflow_id': task['workflow_ref']['workflow_id'],
        'policy_digest': policy['policy_digest'],
        'submission_epoch': task['submission_epoch'],
        'created_generation': runtime_context['ownership']['generation'],
        'manifest_digest': digest(manifest),
        'candidate_digest': candidate_digest(bundle['candidate']),
        'dependencies_digest': digest(bundle['snapshot']),
        'rules_digest': manifest['rules_digest'],
    }


def _derived_runtime_context(host, operation_id):
    import time

    identity = digest({'operation_id': operation_id, 'root': str(host.root)})
    ids = {'task_id': 'task-' + identity, 'learning_task_id': 'maintenance-' + identity,
           'run_id': 'run-' + identity}
    workflow = {
        'workflow_id': 'derived-maintenance-v1',
        'implementation_digest': digest({'workflow': 'derived-maintenance-v1', 'version': 1}),
        'contract_version': 'derived-1', 'required_checks': ['G0', 'G1', 'G2'],
        'allowed_capabilities': [],
    }
    policy_body = {
        'revision': 1,
        'budget': {'requests': 0, 'pages': 0, 'input_bytes': 0, 'model_calls': 0,
                   'active_seconds': 300.0, 'repairs': 0, 'appeals': 0},
        'stop_policy': {'max_step_attempts': 1, 'identical_failure_limit': 1},
        'creation_reason': '确定性派生维护的统一 Runtime 任务',
    }
    policy = dict(policy_body, policy_digest=digest(policy_body))
    rows = host.runtime.store.read(
        "SELECT record_json FROM tasks WHERE task_id='" + ids['task_id'] + "'"
    )
    if rows:
        task = json.loads(rows[0]['record_json'])
        if task['workflow_ref'] != workflow or task['current_policy_digest'] != policy['policy_digest']:
            raise ContractError('derived Runtime Task 的 Workflow 或 PolicyRevision 已变化')
        run = json.loads(host.runtime.store.read(
            "SELECT record_json FROM runs WHERE run_id='" + ids['run_id'] + "'"
        )[0]['record_json'])
        ownership = json.loads(host.runtime.store.read(
            "SELECT record_json FROM execution_ownerships WHERE task_id='" + ids['task_id'] + "'"
        )[0]['record_json'])
        return {'task': task, 'run': run, 'ownership': ownership, 'policy': policy}
    created_at = time.time()
    task = {'task_id': ids['task_id'], 'learning_task_id': ids['learning_task_id'],
            'workflow_ref': workflow, 'current_policy_digest': policy['policy_digest'],
            'submission_epoch': 1, 'revision': 1, 'state': 'running'}
    run = {**ids, 'state': 'running', 'execution_history': []}
    ownership = {'task_id': ids['task_id'], 'learning_task_id': ids['learning_task_id'],
                 'owner': 'derived-' + identity, 'generation': 1,
                 'expires_at': created_at + 300.0}
    host.runtime.create_task(
        policy=policy, task=task, run=run, ownership=ownership,
        learning_state=None, concurrency_limit=1,
    )
    return {'task': task, 'run': run, 'ownership': ownership, 'policy': policy}


def apply_derived_record(host, record, executor, *, recover=False):
    """内置 derived 工作流：原绑定终态优先，非终态才做动态准入。"""
    if record.get('kind') != 'derived':
        raise ContractError('只有 derived pending 可以进入确定性维护工作流')
    bundle = record['bundle']
    operation_id = record['config']['operation_id']
    drain_operation_id = getattr(host, '_legacy_drain_operation', None)
    if drain_operation_id is not None:
        executor._legacy_drain_operation = drain_operation_id
    binding = host.runtime.load_maintenance_binding(operation_id)
    host.runtime.executor = executor

    def finish(binding, result):
        projected = host.runtime.reconcile_maintenance(binding, result)
        return {'status': projected['state'], 'applied': projected['applied'],
                'execution': result,
                'runtime_ids': {field: binding[field] for field in (
                    'task_id', 'learning_task_id', 'run_id',
                )}}

    if binding is not None and recover:
        return finish(binding, executor.recover(operation_id))
    if binding is not None:
        try:
            terminal = executor.lookup_terminal(bundle)
        except ExecutionError as exc:
            if '必须先 recover' not in str(exc):
                raise
        else:
            if terminal is not None:
                return finish(binding, terminal)
    elif recover:
        result = executor.recover(operation_id)
        return {'status': result['state'], 'applied': result['state'] == 'applied',
                'execution': result}

    from ..runtime.migration import assert_managed_operation
    assert_managed_operation(
        host.root, host.private / 'journals', bundle,
        drain_operation_id=drain_operation_id,
    )
    context = _derived_runtime_context(host, operation_id)
    binding = host.runtime.bind_maintenance(maintenance_binding(context, bundle))
    executor.acceptance_context = lambda _admission: host.runtime.maintenance_acceptance_context(binding)
    if recover:
        result = executor.recover(operation_id)
    else:
        packages = tuple((item['package'], Path(item['package_root'])) for item in record['packages'])
        result = executor.apply(bundle, source_packages=packages)
    return finish(binding, result)
