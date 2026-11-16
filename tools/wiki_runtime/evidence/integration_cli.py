"""K4 离线集成检查；不调用 API、不写正式库、不签发授权。"""
import argparse
import json
import sys

from tools.learning_book.contracts import DeliveryError, digest
from tools.learning_book.knowledge_preparation import PreparationGuard
from .cli import _load
from .content_view import inspect_content_baseline
from .preparation import _fields


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    command = commands.add_parser('inspect-baseline')
    command.add_argument('--wiki-root', required=True)
    command = commands.add_parser('check-preparation')
    command.add_argument('--knowledge-preparation', required=True)
    command.add_argument('--production-request', help='后续步骤的真实待发送参数，输出独立审阅请求')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'inspect-baseline':
            result = inspect_content_baseline(args.wiki_root)
        else:
            guard = PreparationGuard(args.knowledge_preparation)
            binding, package, _ = guard.checked()
            result = {'binding': binding, 'manifest': package.manifest,
                'corpusDigest': digest(package.corpus), 'coursePublishAuthorized': False,
                'formalWriteAuthorized': False, 'modelCalls': 0}
            if args.production_request:
                request = _load(args.production_request)
                _fields(request, {'operation', 'activityId', 'scope', 'payload'}, 'production_request_fields')
                result['productionReviewRequest'] = guard.review_request(request['operation'],
                    request['activityId'], request['scope'], request['payload'], binding=binding)
        code = 0
    except (DeliveryError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        result, code = {'result': 'rejected', 'code': 'integration_input_or_dependency_invalid',
            'formalWriteAuthorized': False, 'coursePublishAuthorized': False}, 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
