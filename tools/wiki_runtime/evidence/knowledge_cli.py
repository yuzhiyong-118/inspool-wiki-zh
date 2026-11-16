"""K2 私有只读 CLI；JSON 仅输出 stdout，不初始化控制库或发起外部调用。"""
from __future__ import annotations

import argparse
import json
import sys

from .cli import _load
from .knowledge import prepare_knowledge, verify_knowledge
from .preparation import PreparationError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for name in ('prepare-knowledge', 'check-knowledge'):
        command = commands.add_parser(name)
        for field in ('wiki-root', 'source-root', 'context'):
            command.add_argument('--' + field, required=True)
        if name == 'prepare-knowledge':
            command.add_argument('--request', required=True)
            command.add_argument('--review')
            command.add_argument('--previous')
        else:
            command.add_argument('--prepared', required=True)
    args = parser.parse_args(argv)
    try:
        context = _load(args.context)
        if args.operation == 'prepare-knowledge':
            value = prepare_knowledge(context, _load(args.request), wiki_root=args.wiki_root,
                source_root=args.source_root, review=_load(args.review) if args.review else None,
                previous=_load(args.previous) if args.previous else None)
        else:
            value = verify_knowledge(context, _load(args.prepared), wiki_root=args.wiki_root,
                                     source_root=args.source_root)
        code = 0 if value['knowledgeState'] == 'reviewed_for_scope' else 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        value = {'result': 'rejected', 'knowledgeState': 'rejected',
            'findings': [{'code': exc.code if isinstance(exc, PreparationError)
                         else 'invalid_or_unreadable_input'}], 'artifactRefs': [],
            'nextAction': 'inspect_input_and_limits', 'formalWriteAuthorized': False}
        code = 3
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
