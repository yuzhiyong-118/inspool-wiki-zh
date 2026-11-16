"""可信维护者的 Codex 诊断与显式草稿入口；不提供 apply。"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import uuid

from .codex import CodexDispatcher, CodexError
from .backend import MAX_LINE_BYTES
from .native import NativeRequest, _ROUTES, _json_object


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'draft'))
    parser.add_argument('--codex-executable', default=shutil.which('codex'))
    parser.add_argument('--parent-thread-id', default=os.environ.get('CODEX_THREAD_ID'))
    parser.add_argument('--cwd', default=str(Path.cwd()))
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--role', choices=tuple(route[0] for route in _ROUTES.values()))
    parser.add_argument('--payload', help='显式草稿的 JSON 数据文件，不包含 system/model/tools')
    args = parser.parse_args(argv)
    if args.command == 'draft' and (args.role is None or args.payload is None):
        parser.error('draft 需要 --role 与 --payload')
    if args.command == 'inspect' and (args.role is not None or args.payload is not None):
        parser.error('inspect 不接受模型任务')
    try:
        request = None
        if args.command == 'draft':
            path = Path(args.payload)
            with path.open('rb') as stream:
                data = stream.read(MAX_LINE_BYTES + 1)
            if len(data) > MAX_LINE_BYTES:
                raise CodexError('草稿载荷超限')
            payload = _json_object(data.decode('utf-8'))
            system = next(system for system, route in _ROUTES.items() if route[0] == args.role)
            request = NativeRequest(uuid.uuid4().hex, args.role, system,
                                    json.dumps(payload, ensure_ascii=False, allow_nan=False))
            CodexDispatcher._validate(request)
        with CodexDispatcher(parent_session_id=args.parent_thread_id, cwd=args.cwd,
                             executable=args.codex_executable) as dispatcher:
            if args.command == 'inspect':
                result = dispatcher.inspect(timeout=args.timeout)
            else:
                result = asdict(dispatcher.draft(request, timeout=args.timeout))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError):
        # 服务端错误可能包含任务或私有配置；只给固定诊断。
        print(json.dumps({'status': 'stopped', 'applied': False,
                          'reason': 'Codex 诊断或草稿未完成；请核对登录、父会话、参数及协议兼容性'},
                         ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
