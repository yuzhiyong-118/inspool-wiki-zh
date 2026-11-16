"""独立只读门禁 CLI；配置版本来自可信调用者，不从 manifest 自行信任。"""
import argparse
import json
import sys
from pathlib import Path

from ..candidate import CandidateView
from . import run_gates, VALIDATOR_VERSION


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'payload-root', 'manifest', 'candidate', 'snapshot'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--validator-version', default=VALIDATOR_VERSION)
    parser.add_argument('--review-prompt-version', default='none')
    args = parser.parse_args()
    try:
        records = [json.loads(Path(p).read_text(encoding='utf-8')) for p in (args.manifest, args.candidate, args.snapshot)]
        view = CandidateView(args.root, records[1], args.payload_root, allow_deletes=True)
        # 完整读取后再比较传入快照；CLI 从不刷新或伪造旧绑定。
        for path in view.iter_paths():
            view.read_bytes(path)
        reports = run_gates(*records, view, validator_version=args.validator_version,
                            review_prompt_version=args.review_prompt_version)
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return 0 if all(r['result'] == 'pass' for r in reports) else 1
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
