"""独立入口的 owner 命令；这些命令不注册为模型工具。"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid


def _load(path):
    from .backend import parse_json
    return parse_json(Path(path).read_bytes())


def _host(args, *, offline=False):
    from .supervisor import StandaloneHost
    config = _load(args.model_config) if getattr(args, 'model_config', None) else None
    return StandaloneHost(args.root, args.state_dir, config, offline=offline)


def _doctor(args):
    from .backend import probe_backend
    from .model import ResponsesTransport
    from ..contracts import bytes_digest
    root = Path(args.root).absolute()
    report = {'status': 'configuration_required', 'applied': False,
              'boundary': 'standalone-json-gateway-only', 'desktop_session_restricted': False,
              'os_isolation_verified': False, 'model_configured': False,
              'live_model_verified': False, 'missing_configuration': [], 'problems': [],
              'model_integration': 'optional_api' if args.model_config else 'native_inherited',
              'model_policy': 'explicit' if args.model_config else 'inherit',
              'native_dispatcher_bound': False}
    for path in ('AGENTS.md', 'wiki', 'raw', 'tools/wiki_runtime/contracts/rules.json'):
        if not (root / path).exists():
            report['problems'].append('缺少库入口：' + path)
    if (root / 'AGENTS.md').is_file():
        report['rules_digest'] = bytes_digest((root / 'AGENTS.md').read_bytes())
    if args.model_config:
        try:
            config = _load(args.model_config)
            if isinstance(config, dict):
                if not config.get('model'):
                    report['missing_configuration'].append('model')
                key_name = config.get('api_key_env')
                if isinstance(key_name, str) and not os.environ.get(key_name):
                    report['missing_configuration'].append('environment:' + key_name)
            ResponsesTransport(config)  # 可选适配：只校验，不发网络请求。
            report['model_configured'] = True
            report['model'] = config['model']
        except (ValueError, OSError, KeyError) as exc:
            report['problems'].append(str(exc))
    else:
        report['missing_configuration'].append('trusted_host_dispatcher')
    report['backend_probe'] = probe_backend()
    if not report['backend_probe']['passed']:
        report['problems'].append('实际 JSONL 后端绕过探针未通过')
    if not report['problems']:
        report['status'] = ('configured_not_live_verified' if args.model_config else
                            'gateway_verified_host_binding_required')
    report['may_run_model'] = report['model_configured'] and report['backend_probe']['passed']
    # doctor 不为具体候选签发应用批准，原桌面会话也不会被改权限。
    report['may_apply'] = False
    return report


def _review_record(host, operation_id):
    from ..candidate import CandidateView
    from ..contracts import digest
    record = host.load_pending(operation_id)
    bundle = record['bundle']
    if record.get('kind') == 'knowledge_candidate':
        from .knowledge_candidate import inspect_adopted
        return inspect_adopted(host, record)
    else:
        view = CandidateView(host.root, bundle['candidate'], bundle['payload_root'], allow_deletes=True)
    diffs = []
    for change in bundle['candidate']['changes']:
        source = change.get('source', change['path'])
        before = (host.root / source).read_bytes() if (host.root / source).is_file() else b''
        after = b'' if change['action'] == 'delete' else view.read_bytes(change['path'])
        if len(before) + len(after) <= 2 * 1024 * 1024:
            try:
                diff = ''.join(difflib.unified_diff(before.decode('utf-8').splitlines(True),
                                                   after.decode('utf-8').splitlines(True),
                                                   fromfile=source, tofile=change['path']))
            except UnicodeError:
                diff = '二进制文件；请核对候选路径、来源清单和 SHA-256'
        else:
            diff = '文件较大；请在本地查看候选和来源清单'
        diffs.append({'path': change['path'], 'source': source, 'action': change['action'],
                      'before_sha256': hashlib.sha256(before).hexdigest(),
                      'after_sha256': hashlib.sha256(after).hexdigest(), 'diff': diff})
    return {'status': 'pending_review', 'applied': False, 'operation_id': operation_id,
            'context_digest': digest(record['context']), 'context': record['context'], 'diffs': diffs}


def _package_check(_context, packages):
    from ..capture import validate_package
    for package, root in packages:
        validate_package(package, root)
    return bool(packages)


def _derived_executor(host):
    from .derived import check_derivation
    from ..executor import Executor
    return Executor(host.root, host.private / 'journals', deterministic_check=check_derivation,
                    package_check=_package_check)


def _prepare_derived(host, args):
    from .derived import build_capture, build_health, build_raw_index
    from ..contracts import digest
    from ..runtime.migration import assert_runtime_creation_allowed
    operation = args.operation_id or 'derived-' + uuid.uuid4().hex
    assert_runtime_creation_allowed(host.root, host.state_dir, operation)
    run_dir = host.operations / digest(operation)
    packages = []
    if args.command == 'raw-index':
        bundle = build_raw_index(host.root, run_dir, operation)
    elif args.command == 'health':
        bundle = build_health(host.root, run_dir, operation, save_report=not args.no_report,
                              write_graph=args.write_graph)
    else:
        root = Path(args.package_root).absolute()
        package = _load(root / 'source-package.json')
        bundle = build_capture(host.root, run_dir, operation, package, root, raw_path=args.raw_path)
        packages = [{'package': package, 'package_root': str(root)}]
    executor = _derived_executor(host)
    context = executor._context(bundle['manifest'], bundle['candidate'], bundle['snapshot'])
    record = {'kind': 'derived', 'runtime_managed': True, 'bundle': bundle, 'context': context,
              'config': {'root': str(host.root), 'operation_id': operation,
                         'operation_type': bundle['manifest']['operation_type']}, 'packages': packages}
    # 与模型计划共用私有 HMAC 存储，但派生记录不假造 Coordinator 状态。
    host._save_pending(operation, record)
    if args.apply:
        return _apply_record(host, operation)
    return {'status': 'ready_to_apply', 'applied': False, 'operation_id': operation,
            'context_digest': digest(context), 'paths': bundle['manifest']['allowed_paths']}


def _apply_record(host, operation_id, *, recover=False):
    record = host.load_pending(operation_id)
    if record.get('kind') != 'derived':
        return host.recover(operation_id) if recover else host.apply_pending(operation_id)
    from .derived import apply_derived_record

    return apply_derived_record(host, record, _derived_executor(host), recover=recover)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    doctor = sub.add_parser('doctor', help='只读验证网关；默认继承宿主模型，API 配置可选')
    doctor.add_argument('--root', required=True)
    doctor.add_argument('--model-config')
    run = sub.add_parser('run', help='在明确范围内生成候选；--apply 后仍需全部门禁')
    owner_commands = [run]
    for name, help_text in [('inspect', '显示可信待审 diff'), ('approve', '独立终端批准敏感操作'),
                            ('apply', '重验并应用待审计划'), ('recover', '离线恢复未完成批次'),
                            ('revoke', '离线撤销用户批准'),
                            ('adopt-knowledge', '接收已审知识候选，不重新生成、不正式应用'),
                            ('review-knowledge', '独立审阅已接收的知识候选，不签发G3')]:
        owner_commands.append(sub.add_parser(name, help=help_text))
    admit = sub.add_parser('admit-knowledge', help='可信owner为已授权的知识候选建立非教学准入；不写正式库')
    owner_commands.append(admit)
    admit.add_argument('--authorization-reason', required=True)
    admit.add_argument('--sequence', required=True, choices=('knowledge_only','learn_first'))
    for command in owner_commands:
        command.add_argument('--root', required=True)
        command.add_argument('--state-dir', required=True, help='正式库外、同卷的专属状态目录')
        command.add_argument('--model-config')
        command.add_argument('--operation-id', required=True)
    run.add_argument('--operation-type', required=True)
    run.add_argument('--task', required=True)
    run.add_argument('--allow', action='append', required=True)
    run.add_argument('--input', action='append', default=[])
    run.add_argument('--max-calls', type=int, default=12)
    run.add_argument('--max-seconds', type=float, default=900)
    run.add_argument('--call-timeout', type=float, default=60)
    run.add_argument('--apply', action='store_true')
    adopt = next(c for c in owner_commands if c.prog.endswith('adopt-knowledge'))
    for name in ('context','knowledge','candidate','request','source-root','payload-root'):
        adopt.add_argument('--'+name, required=True)
    adopt.add_argument('--baseline-scope',choices=('whole_root','knowledge_content'),default='knowledge_content')
    adopt.add_argument('--max-calls',type=int,default=2)
    adopt.add_argument('--max-seconds',type=float,default=300)
    adopt.add_argument('--call-timeout',type=float,default=60)
    derived_commands = []
    for name in ('raw-index', 'health', 'import-package'):
        command = sub.add_parser(name, help='确定性候选，经统一执行器应用；不调用模型')
        command.add_argument('--root', required=True)
        command.add_argument('--state-dir', required=True)
        command.add_argument('--operation-id')
        command.add_argument('--apply', action='store_true')
        derived_commands.append(command)
    derived_commands[1].add_argument('--write-graph', action='store_true')
    derived_commands[1].add_argument('--no-report', action='store_true')
    derived_commands[2].add_argument('--package-root', required=True)
    derived_commands[2].add_argument('--raw-path', required=True)
    args = parser.parse_args(argv)
    host = None
    try:
        if args.command == 'doctor':
            result = _doctor(args)
            code = 0 if result['status'] in ('configured_not_live_verified',
                                             'gateway_verified_host_binding_required') else 2
        elif args.command == 'run':
            host = _host(args)
            result = host.run_operation(args.operation_id, args.operation_type, args.task,
                                        args.allow, args.input, max_calls=args.max_calls,
                                        max_seconds=args.max_seconds, call_timeout=args.call_timeout,
                                        apply=args.apply)
            code = 0 if result['status'] in ('ready_to_apply', 'applied') else 1
        else:
            offline = args.command not in ('apply','review-knowledge') or not args.model_config
            host = _host(args, offline=offline)
            if args.command in ('raw-index', 'health', 'import-package'):
                result = _prepare_derived(host, args)
            elif args.command == 'adopt-knowledge':
                from ..evidence.cli import _load as bounded_load
                result = host.adopt_knowledge_candidate(args.operation_id, bounded_load(args.context),
                    bounded_load(args.knowledge), bounded_load(args.candidate), bounded_load(args.request),
                    source_root=args.source_root,payload_root=args.payload_root,
                    baseline_scope=args.baseline_scope,max_calls=args.max_calls,
                    max_seconds=args.max_seconds,call_timeout=args.call_timeout)
            elif args.command == 'review-knowledge':
                result = host.review_knowledge_candidate(args.operation_id)
            elif args.command == 'admit-knowledge':
                result = host.admit_knowledge_candidate(args.operation_id,
                    authorization_reason=args.authorization_reason,sequence=args.sequence)
            elif args.command == 'inspect':
                result = _review_record(host, args.operation_id)
            elif args.command == 'approve':
                review = _review_record(host, args.operation_id)
                # JSON 转义控制字符，模型正文不能伪装终端指令。
                print(json.dumps(review, ensure_ascii=False, indent=2))
                result = host.approve_pending(args.operation_id)
            elif args.command == 'revoke':
                result = host.revoke_pending(args.operation_id)
            else:
                result = _apply_record(host, args.operation_id, recover=args.command == 'recover')
            code = 0 if result['status'] in ('ready_to_apply', 'applied', 'recovered', 'approved',
                                            'revoked', 'pending_review', 'reviewed_for_transfer', 'admitted') else 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except Exception as exc:
        # owner CLI 只处理数据；不将异常降级为通过，也不输出网络响应/认证头。
        print(json.dumps({'status': 'error', 'applied': False, 'error': type(exc).__name__,
                          'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    finally:
        if host is not None:
            host.close()


if __name__ == '__main__':
    raise SystemExit(main())
