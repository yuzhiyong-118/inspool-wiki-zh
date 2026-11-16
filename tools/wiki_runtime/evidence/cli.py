"""K1 私有只读 CLI：JSON 写到 stdout，由调用者保存在明确的私有目录。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ..host.backend import parse_json
from .preparation import PreparationError, draft_learning_brief, inspect_context, verify_context


def _load(path):
    # 配置亦有限额，不跟随链接或读取无界输入。
    from ..isolation.gateway import _check_chain
    target = Path(path).absolute()
    _check_chain(target)
    with target.open('rb') as stream:
        return parse_json(stream.read(2 * 1024 * 1024 + 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for operation in ('inspect-context', 'check-context', 'draft-brief'):
        command = commands.add_parser(operation)
        command.add_argument('--wiki-root', required=True, help='包含 wiki/index.md 的项目根目录')
        command.add_argument('--source-root', required=True, help='明确允许读取的原件目录')
        if operation in ('inspect-context', 'draft-brief'):
            command.add_argument('--request', required=True)
        if operation == 'inspect-context':
            command.add_argument('--previous')
        else:
            command.add_argument('--context', required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'inspect-context':
            value = inspect_context(args.wiki_root, args.source_root, _load(args.request),
                                    previous=None if not args.previous else _load(args.previous))
        elif args.operation == 'check-context':
            value = verify_context(_load(args.context), args.wiki_root, args.source_root)
        else:
            value = draft_learning_brief(_load(args.context), _load(args.request),
                                         wiki_root=args.wiki_root, source_root=args.source_root)
        code = 0 if value['result'] == 'ready_for_review' else 2
    except (OSError, ValueError, TypeError, KeyError) as exc:
        value = {'result': 'rejected', 'findings': [{'code': exc.code
                 if isinstance(exc, PreparationError) else 'invalid_or_unreadable_input'}],
                 'artifactRefs': [], 'nextAction': 'inspect_input_and_limits'}
        code = 3
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
