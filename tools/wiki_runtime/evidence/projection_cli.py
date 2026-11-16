"""K3 私有投影／候选预览 CLI；不发布课程，不正式应用。"""
import argparse
import json
import sys

from tools.learning_book.contracts import DeliveryError
from .cli import _load
from .preparation import PreparationError
from .projection import build_learning_projection
from .preview import preview_wiki_changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    for operation in ('build-learning-projection', 'preview-wiki-changes'):
        command = commands.add_parser(operation)
        for field in ('wiki-root', 'source-root', 'context', 'knowledge', 'request'):
            command.add_argument('--' + field, required=True)
        if operation == 'build-learning-projection':
            for field in ('brief', 'projection-root', 'recognition-root'):
                command.add_argument('--' + field, required=True)
            command.add_argument('--prepare', default='prepare.json', help='projection-root 内的相对 manifest 路径')
            command.add_argument('--recognition')
            command.add_argument('--review')
            command.add_argument('--previous')
        else:
            command.add_argument('--candidate', required=True)
            command.add_argument('--payload-root', required=True)
            command.add_argument('--baseline-scope', choices=('whole_root', 'knowledge_content'),
                                 default='whole_root')
    args = parser.parse_args(argv)
    try:
        context, knowledge, request = _load(args.context), _load(args.knowledge), _load(args.request)
        if args.operation == 'build-learning-projection':
            value = build_learning_projection(context, knowledge, _load(args.brief), request,
                wiki_root=args.wiki_root, source_root=args.source_root,
                projection_root=args.projection_root, recognition_root=args.recognition_root,
                prepare_path=args.prepare, recognition=_load(args.recognition) if args.recognition else None,
                review=_load(args.review) if args.review else None,
                previous=_load(args.previous) if args.previous else None)
            passed = value['projectionState'] == 'reviewed_for_scope'
        else:
            value = preview_wiki_changes(context, knowledge, _load(args.candidate), request,
                wiki_root=args.wiki_root, source_root=args.source_root, payload_root=args.payload_root,
                baseline_scope=args.baseline_scope)
            passed = value['previewState'] == 'ready_for_semantic_review'
        code = 0 if passed else 2
    except (OSError, ValueError, TypeError, KeyError, RecursionError, DeliveryError) as exc:
        value = {'result': 'rejected', 'findings': [{'code': exc.code
            if isinstance(exc, (PreparationError, DeliveryError)) else 'invalid_or_unreadable_input'}],
            'artifactRefs': [], 'nextAction': 'inspect_input_and_limits', 'previewOnly': True,
            'formalWriteAuthorized': False, 'coursePublishAuthorized': False}
        code = 3
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
