"""python -B -m tools.wiki_runtime.contracts [kind file | --examples]。"""
import argparse
import json
import sys
from pathlib import Path

from . import ContractError, validate


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='校验运行时 v1 契约（不授予执行权限）')
    parser.add_argument('kind', nargs='?')
    parser.add_argument('file', nargs='?')
    parser.add_argument('--examples', action='store_true')
    args = parser.parse_args()
    try:
        if args.examples:
            count = 0
            for sample in sorted((Path(__file__).parent / 'examples').glob('*.json')):
                kind, expectation, _ = sample.name.split('.')
                try:
                    validate(kind, json.loads(sample.read_text(encoding='utf-8')))
                    passed = True
                except ContractError:
                    passed = False
                if passed != (expectation == 'valid'):
                    raise ContractError(f'样例结果不符: {sample.name}')
                count += 1
            print(f'通过：{count} 个有效/无效样例的预期结果一致')
        else:
            if not args.kind or not args.file:
                parser.error('需要 kind 和 JSON 文件，或 --examples')
            validate(args.kind, json.loads(Path(args.file).read_text(encoding='utf-8')))
            print('契约通过（不代表门禁通过或获得授权）')
        return 0
    except (ContractError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        print(f'拒绝：{exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
