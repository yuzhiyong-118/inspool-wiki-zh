"""只读检查；退出 2 表示强制隔离未验收，不得降级放行。"""
import argparse
import json

from .preflight import inspect_deployment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--profile')
    parser.add_argument('--tool-catalog')
    args = parser.parse_args()

    def load(path):
        if path is None:
            return None
        with open(path, encoding='utf-8') as stream:
            return json.load(stream)

    try:
        report = inspect_deployment(args.root, profile=load(args.profile),
                                    tool_catalog=load(args.tool_catalog))
    except (OSError, ValueError) as exc:
        report = {'status': 'not_verified', 'enforced': False, 'may_apply': False,
                  'error': str(exc)}
    # ASCII JSON 可在 Windows cp936 stdout 与 UTF-8 调用者之间无损传递。
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
